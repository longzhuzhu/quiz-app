"""复盘详情 API：完成态释放判定与当场正确答案、统一统计口径、只读写入拒绝。

覆盖：
- 已完成模拟考试按原场顺序返回完整题目，释放 is_correct 与 correct_answer
- 进行中的模拟考试继续隐藏答案、对错与可推导成绩的统计
- index 为原场题号，含未答题；跳题与改答不改变编号
- 普通练习以已答数为分母、模拟考试以总题数为分母；零作答返回 0.0
- 完成后改题干/选项/正确答案、删除题目不改写复盘内容与成绩
- 旧会话（question_snapshot=NULL）保留已保存判定，不可核实处 status_unknown=true
- /quiz/history 与 session_detail 使用同一口径
- 已完成会话拒绝再次提交，记录不被修改
- 进行中会话的 resume_index 与题目结构未变（答题页刷新恢复的回归门禁）
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.questions import router as questions_router  # noqa: E402
from app.api.routes.quiz import router  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import Exam, Question, QuestionBank, QuizAnswer, QuizSession, User  # noqa: E402

QUESTION_COUNT = 10
OPTIONS = [{"key": key, "text": f"选项{key}"} for key in ("A", "B", "C", "D")]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def quiz_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="reviewer", email="reviewer@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="review", name="Review", short_name="R")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="主库", question_count=QUESTION_COUNT)
        db.add(bank)
        db.flush()
        questions = []
        for index in range(1, QUESTION_COUNT + 1):
            question = Question(
                bank_id=bank.id, question_type="single", content=f"第 {index} 题",
                options=OPTIONS, correct_answer="A", order_index=index,
            )
            db.add(question)
            questions.append(question)
        db.commit()
        ids = SimpleNamespace(
            user=user.id, exam=exam.id, bank=bank.id, questions=[q.id for q in questions],
        )

    def get_test_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/quiz")
    app.include_router(questions_router, prefix="/api/questions")
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        client.headers.update({
            "Authorization": f"Bearer {create_access_token(str(ids.user))}",
            "X-Exam-Slug": "review",
        })
        yield SimpleNamespace(client=client, ids=ids, sessions=sessions)
    engine.dispose()


def _start(api, mode="sequential") -> tuple[int, list[int]]:
    response = api.client.post("/api/quiz/start", json={"bank_id": api.ids.bank, "mode": mode})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["session"]["id"], [q["id"] for q in payload["questions"]]


def _answer(api, session_id, question_id, user_answer):
    return api.client.post("/api/quiz/answer", json={
        "session_id": session_id, "question_id": question_id, "user_answer": user_answer,
    })


def _finish(api, session_id):
    response = api.client.post("/api/quiz/finish", json={"session_id": session_id})
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _detail(api, session_id) -> dict:
    response = api.client.get(f"/api/quiz/session/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _session_row(api, session_id) -> QuizSession:
    with api.sessions() as db:
        session = db.get(QuizSession, session_id)
        db.expunge(session)
        return session


def test_completed_exam_session_releases_verdicts_in_original_order(quiz_api):
    session_id, question_ids = _start(quiz_api, mode="exam")
    for position, question_id in enumerate(question_ids):
        answer = "A" if position < 7 else "B"
        assert _answer(quiz_api, session_id, question_id, answer).status_code == 200
    _finish(quiz_api, session_id)

    detail = _detail(quiz_api, session_id)
    session = detail["session"]
    assert session["correct_count"] == 7
    assert session["wrong_count"] == 3
    assert session["unanswered_count"] == 0
    assert session["accuracy"] == 70.0
    assert session["accuracy_basis"] == "total"
    assert session["has_snapshot"] is True

    questions = detail["questions"]
    assert [q["id"] for q in questions] == question_ids
    assert [q["index"] for q in questions] == list(range(1, QUESTION_COUNT + 1))
    assert all(q["correct_answer"] == "A" for q in questions)
    assert all(q["user_answer"] is not None for q in questions)
    assert [q["status"] for q in questions] == ["correct"] * 7 + ["wrong"] * 3
    assert [q["is_correct"] for q in questions] == [position < 7 for position in range(QUESTION_COUNT)]
    assert all(q["status_unknown"] is False for q in questions)
    # 完成态只给复盘结构：过渡字段 `answers` 按作答记录顺序排列，与 question_ids 顺序不一致，
    # 同时输出会让消费方按数组下标编号而与原场题号错位
    assert "answers" not in detail


def test_in_progress_exam_session_keeps_answers_and_stats_hidden(quiz_api):
    session_id, question_ids = _start(quiz_api, mode="exam")
    assert _answer(quiz_api, session_id, question_ids[0], "A").status_code == 200

    detail = _detail(quiz_api, session_id)
    session = detail["session"]
    assert session["is_completed"] is False
    for hidden in ("accuracy", "accuracy_basis", "wrong_count", "unanswered_count", "has_snapshot"):
        assert hidden not in session
    assert all("is_correct" not in q for q in detail["questions"])
    assert all("correct_answer" not in q for q in detail["questions"])
    assert all("explanation" not in q for q in detail["questions"])
    assert all("ai_explanations" not in q for q in detail["questions"])
    assert all("is_correct" not in a for a in detail["answers"])
    assert all("correct_answer" not in a for a in detail["answers"])


def test_review_index_follows_question_order_across_skips_and_redos(quiz_api):
    session_id, question_ids = _start(quiz_api)
    first, second, third = question_ids[:3]
    # 跳过第 1 题；第 2 题先答错再改对；第 3 题答错
    assert _answer(quiz_api, session_id, second, "B").status_code == 200
    assert _answer(quiz_api, session_id, second, "A").status_code == 200
    assert _answer(quiz_api, session_id, third, "B").status_code == 200
    _finish(quiz_api, session_id)

    questions = _detail(quiz_api, session_id)["questions"]
    assert [q["id"] for q in questions] == question_ids
    assert [q["index"] for q in questions] == list(range(1, QUESTION_COUNT + 1))

    skipped, redone, wrong = questions[:3]
    assert skipped["status"] == "unanswered"
    assert skipped["is_correct"] is None
    assert skipped["user_answer"] is None
    assert redone["status"] == "correct"  # 改答后以最后一次成功提交为准
    assert redone["is_correct"] is True
    assert redone["user_answer"] == "A"
    assert wrong["status"] == "wrong"
    assert wrong["user_answer"] == "B"
    assert all(q["status"] == "unanswered" for q in questions[3:])


def test_accuracy_denominator_follows_mode_for_partially_answered_sessions(quiz_api):
    ordinary_id, ordinary_ids = _start(quiz_api)
    exam_id, exam_ids = _start(quiz_api, mode="exam")
    for session_id, question_ids in ((ordinary_id, ordinary_ids), (exam_id, exam_ids)):
        for question_id in question_ids[:2]:
            assert _answer(quiz_api, session_id, question_id, "A").status_code == 200
        _finish(quiz_api, session_id)

    ordinary = _detail(quiz_api, ordinary_id)["session"]
    exam = _detail(quiz_api, exam_id)["session"]
    assert (ordinary["correct_count"], ordinary["wrong_count"], ordinary["unanswered_count"]) == (2, 0, 8)
    assert (exam["correct_count"], exam["wrong_count"], exam["unanswered_count"]) == (2, 0, 8)
    assert (ordinary["accuracy"], ordinary["accuracy_basis"]) == (100.0, "answered")
    assert (exam["accuracy"], exam["accuracy_basis"]) == (20.0, "total")


def test_finish_without_any_answer_reports_zero_accuracy(quiz_api):
    session_id, _ = _start(quiz_api)
    finished = _finish(quiz_api, session_id)
    assert finished["accuracy"] == 0.0
    assert finished["unanswered_count"] == QUESTION_COUNT

    detail = _detail(quiz_api, session_id)
    session = detail["session"]
    assert session["accuracy"] == 0.0
    assert session["wrong_count"] == 0
    assert session["unanswered_count"] == session["total_questions"] == QUESTION_COUNT
    assert len(detail["questions"]) == QUESTION_COUNT
    assert all(q["status"] == "unanswered" and q["is_correct"] is None for q in detail["questions"])


def test_completed_review_survives_question_edit_and_deletion(quiz_api):
    session_id, question_ids = _start(quiz_api)
    first, second = question_ids[:2]
    assert _answer(quiz_api, session_id, first, "B").status_code == 200
    assert _answer(quiz_api, session_id, second, "A").status_code == 200
    _finish(quiz_api, session_id)

    update = quiz_api.client.put(f"/api/questions/{first}", json={
        "content": "题干已改",
        "options": [{"key": "A", "text": "改后甲"}, {"key": "B", "text": "改后乙"}],
        "correct_answer": "B",
    })
    assert update.status_code == 200, update.text
    assert quiz_api.client.delete(f"/api/questions/{second}").status_code == 200

    questions = _detail(quiz_api, session_id)["questions"]
    edited, deleted = questions[0], questions[1]
    # 快照仍给出当场内容与当场正确答案，题库当前值不覆盖
    assert (edited["content"], edited["correct_answer"]) == ("第 1 题", "A")
    assert edited["status"] == "wrong" and edited["user_answer"] == "B"
    assert edited["options"] == OPTIONS
    # 题目已被删除，冻结副本仍可读出最终选择与判定
    assert (deleted["id"], deleted["content"], deleted["status"]) == (second, "第 2 题", "correct")
    assert deleted["user_answer"] == "A" and deleted["correct_answer"] == "A"
    assert deleted["status_unknown"] is False


def test_legacy_session_without_snapshot_keeps_verdict_and_marks_unknown(quiz_api):
    session_id, question_ids = _start(quiz_api)
    first = question_ids[0]
    assert _answer(quiz_api, session_id, first, "A").status_code == 200
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        session = db.get(QuizSession, session_id)
        session.question_snapshot = None
        session.final_answers = None
        db.commit()

    detail = _detail(quiz_api, session_id)
    assert detail["session"]["has_snapshot"] is False
    answered, unanswered = detail["questions"][0], detail["questions"][1]
    # 已保存的判定与选择保留，且不被当前题库正确答案重新判分
    assert (answered["status"], answered["is_correct"], answered["user_answer"]) == ("correct", True, "A")
    assert answered["status_unknown"] is False
    assert answered["content"] == "第 1 题"
    # 无快照且无作答记录：不推断成错误或未答，标为不可核实
    assert unanswered["status_unknown"] is True
    assert unanswered["is_correct"] is None
    assert unanswered["status"] == "unanswered"
    assert unanswered["correct_answer"] == "A"  # 无快照时退回当前题库数据并置兼容标记


def test_corrupted_frozen_entries_do_not_turn_into_wrong_verdicts(quiz_api):
    """冻结副本损坏时不推断成错误：缺失或非 bool 判定标为不可核实。"""
    session_id, question_ids = _start(quiz_api)
    first, second = question_ids[:2]
    assert _answer(quiz_api, session_id, first, "A").status_code == 200
    assert _answer(quiz_api, session_id, second, "B").status_code == 200
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        session = db.get(QuizSession, session_id)
        session.final_answers = {
            **session.final_answers,
            str(first): {"user_answer": "A"},          # 缺 is_correct
            str(second): "corrupted",                  # 非 dict
        }
        db.commit()

    questions = _detail(quiz_api, session_id)["questions"]
    missing_verdict, malformed = questions[0], questions[1]
    assert missing_verdict["is_correct"] is None
    assert missing_verdict["user_answer"] == "A"  # 已保存的选择仍可读
    assert missing_verdict["status_unknown"] is True
    assert missing_verdict["status"] != "wrong"
    assert malformed["is_correct"] is None
    assert malformed["status_unknown"] is True
    assert malformed["status"] != "wrong"


def test_review_tolerates_malformed_snapshot_entries(quiz_api):
    """快照条目非 dict 时不抛异常：退回当前题库内容并标为不可核实。"""
    session_id, question_ids = _start(quiz_api)
    assert _answer(quiz_api, session_id, question_ids[0], "A").status_code == 200
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        session = db.get(QuizSession, session_id)
        session.question_snapshot = [None, *session.question_snapshot[1:]]
        db.commit()

    questions = _detail(quiz_api, session_id)["questions"]
    assert len(questions) == QUESTION_COUNT
    degraded = questions[0]
    assert degraded["content"] == "第 1 题"          # 退回当前题库数据
    assert degraded["status"] == "correct"           # 已保存判定仍可核实
    assert degraded["is_correct"] is True
    assert degraded["status_unknown"] is False


def test_malformed_final_answers_column_does_not_crash_or_infer(quiz_api):
    """final_answers 整列损坏（非 dict）时不抛异常：不得当作「键不存在」推断成未答。"""
    session_id, question_ids = _start(quiz_api)
    assert _answer(quiz_api, session_id, question_ids[0], "A").status_code == 200
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        session = db.get(QuizSession, session_id)
        session.final_answers = 12345  # 非容器：旧实现 key in frozen_answers 会 TypeError
        db.commit()

    questions = _detail(quiz_api, session_id)["questions"]
    assert len(questions) == QUESTION_COUNT
    # 作答记录仍可核实：保存的判定优先，绝不显示「未答」
    answered = questions[0]
    assert answered["status"] == "correct"
    assert answered["is_correct"] is True
    assert answered["status_unknown"] is False


def test_review_index_follows_question_order_in_random_mode(quiz_api):
    """随机模式题号按 question_ids 原场顺序，不按作答先后或答案数组下标。"""
    session_id, question_ids = _start(quiz_api, mode="random")
    last = question_ids[-1]
    assert _answer(quiz_api, session_id, last, "A").status_code == 200
    _finish(quiz_api, session_id)

    questions = _detail(quiz_api, session_id)["questions"]
    assert [q["id"] for q in questions] == question_ids
    assert [q["index"] for q in questions] == list(range(1, QUESTION_COUNT + 1))
    assert questions[-1]["status"] == "correct"
    assert all(q["status"] == "unanswered" for q in questions[:-1])


def test_history_uses_same_accuracy_basis_as_session_detail(quiz_api):
    ordinary_id, ordinary_ids = _start(quiz_api)
    exam_id, exam_ids = _start(quiz_api, mode="exam")
    for session_id, question_ids in ((ordinary_id, ordinary_ids), (exam_id, exam_ids)):
        for question_id in question_ids[:2]:
            assert _answer(quiz_api, session_id, question_id, "A").status_code == 200
        _finish(quiz_api, session_id)

    items = quiz_api.client.get("/api/quiz/history", params={"page": 1, "per_page": 20}).json()["items"]
    by_id = {item["id"]: item for item in items}
    assert by_id[ordinary_id]["accuracy"] == _detail(quiz_api, ordinary_id)["session"]["accuracy"] == 100.0
    assert by_id[ordinary_id]["accuracy_basis"] == "answered"
    assert by_id[exam_id]["accuracy"] == _detail(quiz_api, exam_id)["session"]["accuracy"] == 20.0
    assert by_id[exam_id]["accuracy_basis"] == "total"


def test_completed_session_rejects_further_answers_without_recording(quiz_api):
    session_id, question_ids = _start(quiz_api)
    first, second = question_ids[:2]
    assert _answer(quiz_api, session_id, first, "A").status_code == 200
    _finish(quiz_api, session_id)
    session_before = _session_row(quiz_api, session_id)

    def read_answers():
        with quiz_api.sessions() as db:
            rows = db.query(QuizAnswer).filter_by(session_id=session_id).all()
            return sorted((row.question_id, row.user_answer, row.is_correct) for row in rows)

    answers_before = read_answers()
    assert _answer(quiz_api, session_id, first, "B").status_code == 400  # 改答
    assert _answer(quiz_api, session_id, second, "A").status_code == 400  # 补答

    assert read_answers() == answers_before
    session_after = _session_row(quiz_api, session_id)
    assert (session_after.answered_count, session_after.correct_count) == (
        session_before.answered_count, session_before.correct_count,
    )


def test_in_progress_session_keeps_resume_fields_for_answering_page(quiz_api):
    session_id, question_ids = _start(quiz_api)
    assert _answer(quiz_api, session_id, question_ids[0], "A").status_code == 200
    assert _answer(quiz_api, session_id, question_ids[1], "B").status_code == 200

    detail = _detail(quiz_api, session_id)
    # 最近的作答在第 2 题，恢复索引指向下一题；答题页据此续答
    assert detail["session"]["resume_index"] == 2
    assert len(detail["questions"]) == QUESTION_COUNT
    resumed = detail["questions"][2]
    assert set(resumed) == {
        "id", "bank_id", "bank_name", "question_type", "content", "content_zh", "options",
        "answered", "user_answer_count", "ai_explanations",
        "ai_input_fingerprint", "explanation", "explanation_zh",
    }
    assert resumed["answered"] is False
    assert detail["answers"][1]["is_correct"] is False
    assert detail["answers"][1]["correct_answer"] == "A"
    assert detail["answers"][1]["answer_duration_ms"] is None


def test_review_detail_enforces_exam_and_owner_boundaries(quiz_api):
    session_id, question_ids = _start(quiz_api)
    assert _answer(quiz_api, session_id, question_ids[0], "A").status_code == 200
    _finish(quiz_api, session_id)

    # 跨考试项目：同一用户换 slug
    quiz_api.client.headers["X-Exam-Slug"] = "other"
    assert quiz_api.client.get(f"/api/quiz/session/{session_id}").status_code == 404
    quiz_api.client.headers["X-Exam-Slug"] = "review"

    # 其他用户的同名 slug 解析到自己的考试项目，不得读出该会话
    with quiz_api.sessions() as db:
        intruder = User(username="intruder", email="intruder@example.com", password_hash="hash")
        db.add(intruder)
        db.flush()
        db.add(Exam(owner_id=intruder.id, slug="review", name="Intruder", short_name="I"))
        db.commit()
        token = create_access_token(str(intruder.id))

    original_auth = quiz_api.client.headers["Authorization"]
    quiz_api.client.headers["Authorization"] = f"Bearer {token}"
    response = quiz_api.client.get(f"/api/quiz/session/{session_id}")
    assert response.status_code in (403, 404)
    assert "questions" not in response.json()
    quiz_api.client.headers["Authorization"] = original_auth

    assert quiz_api.client.get(f"/api/quiz/session/{session_id}").status_code == 200
