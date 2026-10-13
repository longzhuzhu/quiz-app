"""原题原序重开 API：POST /quiz/retry。

覆盖：
- 从已完成的顺序练习重开：题目 ID 列表与顺序与原会话完全一致，含原场未答题
- 原场题库之后新增题目不进新会话；原考点成员变化不改变原题集合
- 考点已删除时保留原题集合；`topic_id` 由外键 `SET NULL` 置空，响应不承诺考点不可用提示
- 已标记掌握的错题不被剔除；跨题库错题会话逐题保留全部原题
- 模式与题数沿用；exam 模式返回时不泄露解析
- 任一原题不可用：整场失败并列出题目 ID，不创建部分会话
- 旧会话 question_ids 为 NULL/空/损坏：400，不查询题库猜原范围
- 未完成的原会话 400；他人用户 403；跨考试项目 404 且响应不含题目内容
- 新会话初始状态为起点，且写入自己的快照；原会话不变
- 重开不产生 UserQuestionStat 与练习日记录
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.quiz import router  # noqa: E402
from app.api.routes.wrong import router as wrong_router  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import (  # noqa: E402
    Exam,
    ExamTopic,
    PracticeDayQuestion,
    Question,
    QuestionBank,
    QuestionTopic,
    QuizSession,
    User,
    UserQuestionStat,
    WrongAnswer,
)
from app.models.exam_topic import TOPIC_LEVEL_COMPETENCY  # noqa: E402

SNAPSHOT_FIELDS = {"question_id", "question_type", "content", "options", "correct_answer"}
OPTIONS = [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def quiz_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        """SQLite 默认不强制外键，会让 `ON DELETE SET NULL` 等语义在测试里静默失效。

        本文件依赖 `quiz_sessions.topic_id` 的 `ondelete="SET NULL"`
        （生产 PostgreSQL 行为）。不开这个 PRAGMA，考点删除后 `topic_id` 会残留悬空 id，
        测试就会断言到生产上不可能出现的状态。
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="retry", email="retry@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="retry", name="Retry", short_name="R")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="主库", question_count=4)
        other_bank = QuestionBank(exam_id=exam.id, name="副库", question_count=1)
        db.add_all([bank, other_bank])
        db.flush()
        questions = [
            Question(
                bank_id=bank.id, question_type="single", content=f"Q{index}",
                options=OPTIONS, correct_answer="A", order_index=index,
            )
            for index in range(1, 5)
        ]
        other_question = Question(
            bank_id=other_bank.id, question_type="single", content="跨库题",
            options=OPTIONS, correct_answer="B", order_index=1,
        )
        db.add_all(questions + [other_question])
        db.flush()
        topic = ExamTopic(
            exam_id=exam.id, level=TOPIC_LEVEL_COMPETENCY, code="I.A",
            name_en="Privacy", name_zh="隐私", short_name_zh="隐私", source_version="test",
        )
        db.add(topic)
        db.flush()
        db.add(QuestionTopic(question_id=questions[0].id, topic_id=topic.id, source="manual"))
        db.commit()
        ids = SimpleNamespace(
            user=user.id, exam=exam.id, bank=bank.id, other_bank=other_bank.id,
            questions=[q.id for q in questions], other_question=other_question.id,
            topic=topic.id,
        )

    def get_test_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/quiz")
    app.include_router(wrong_router, prefix="/api/wrong")
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        client.headers.update({
            "Authorization": f"Bearer {create_access_token(str(ids.user))}",
            "X-Exam-Slug": "retry",
        })
        yield SimpleNamespace(client=client, ids=ids, sessions=sessions)
    engine.dispose()


def _start(api, **body):
    body.setdefault("bank_id", api.ids.bank)
    response = api.client.post("/api/quiz/start", json=body)
    assert response.status_code == 200, response.text
    return response.json()["session"]["id"]


def _answer(api, session_id, question_id, user_answer, **extra):
    return api.client.post("/api/quiz/answer", json={
        "session_id": session_id, "question_id": question_id, "user_answer": user_answer,
        **extra,
    })


def _finish(api, session_id):
    response = api.client.post("/api/quiz/finish", json={"session_id": session_id})
    assert response.status_code == 200, response.text
    return response


def _retry(api, session_id):
    return api.client.post("/api/quiz/retry", json={"session_id": session_id})


def _load_session(api, session_id) -> QuizSession:
    with api.sessions() as db:
        session = db.get(QuizSession, session_id)
        db.expunge(session)
        return session


def _session_count(api) -> int:
    with api.sessions() as db:
        return db.query(QuizSession).count()


def test_retry_reuses_original_ids_and_order_including_unanswered(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    first, second = quiz_api.ids.questions[:2]
    assert _answer(quiz_api, session_id, second, "B").status_code == 200
    _finish(quiz_api, session_id)

    response = _retry(quiz_api, session_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    new_session_id = payload["session"]["id"]
    assert new_session_id != session_id
    assert [q["id"] for q in payload["questions"]] == quiz_api.ids.questions

    new_session = _load_session(quiz_api, new_session_id)
    assert json.loads(new_session.question_ids) == quiz_api.ids.questions
    assert [e["question_id"] for e in new_session.question_snapshot] == quiz_api.ids.questions
    # 原场未答题（第 1 题）同样包含在新会话中
    assert first in json.loads(new_session.question_ids)


def test_retry_keeps_original_members_after_bank_and_topic_change(quiz_api):
    session_id = _start(quiz_api, mode="topic", topic_id=quiz_api.ids.topic)
    assert json.loads(_load_session(quiz_api, session_id).question_ids) == [quiz_api.ids.questions[0]]
    _finish(quiz_api, session_id)

    with quiz_api.sessions() as db:
        # 题库新增题目、原考点成员变化（撤销打标并挂到新题）
        db.add(Question(
            bank_id=quiz_api.ids.bank, question_type="single", content="新增题",
            options=OPTIONS, correct_answer="A", order_index=9,
        ))
        db.query(QuestionTopic).delete()
        db.add(QuestionTopic(
            question_id=quiz_api.ids.questions[1], topic_id=quiz_api.ids.topic, source="manual",
        ))
        db.commit()

    payload = _retry(quiz_api, session_id).json()
    assert [q["id"] for q in payload["questions"]] == [quiz_api.ids.questions[0]]
    assert payload["session"]["total_questions"] == 1
    new_session = _load_session(quiz_api, payload["session"]["id"])
    assert json.loads(new_session.question_ids) == [quiz_api.ids.questions[0]]
    assert json.loads(new_session.question_ids) != [quiz_api.ids.questions[1]]
    assert new_session.topic_id == quiz_api.ids.topic


def test_retry_snapshot_uses_current_question_content_not_old_version(quiz_api):
    """「原题」指成员与顺序，不是恢复题库旧版本：新会话快照取原题当前内容。"""
    session_id = _start(quiz_api, mode="sequential")
    first = quiz_api.ids.questions[0]
    _finish(quiz_api, session_id)

    with quiz_api.sessions() as db:
        question = db.get(Question, first)
        question.content = "题干已改"
        question.options = [{"key": "A", "text": "改后甲"}, {"key": "B", "text": "改后乙"}]
        question.correct_answer = "B"
        db.commit()

    payload = _retry(quiz_api, session_id).json()
    new_session = _load_session(quiz_api, payload["session"]["id"])
    entry = next(e for e in new_session.question_snapshot if e["question_id"] == first)
    assert entry["content"] == "题干已改"
    assert entry["correct_answer"] == "B"
    assert entry["options"] == [{"key": "A", "text": "改后甲"}, {"key": "B", "text": "改后乙"}]
    assert [q["content"] for q in payload["questions"]][0] == "题干已改"

    # 原会话冻结的复盘依据不受影响
    original = _load_session(quiz_api, session_id)
    old_entry = next(e for e in original.question_snapshot if e["question_id"] == first)
    assert (old_entry["content"], old_entry["correct_answer"]) == ("Q1", "A")


def test_retry_keeps_resolved_wrong_questions(quiz_api):
    with quiz_api.sessions() as db:
        db.add(WrongAnswer(
            user_id=quiz_api.ids.user, question_id=quiz_api.ids.questions[0], is_resolved=True,
        ))
        db.commit()

    session_id = _start(quiz_api, mode="sequential")
    _finish(quiz_api, session_id)

    payload = _retry(quiz_api, session_id).json()
    assert quiz_api.ids.questions[0] in [q["id"] for q in payload["questions"]]


def test_retry_wrong_practice_session_keeps_questions_across_banks(quiz_api):
    with quiz_api.sessions() as db:
        db.add_all([
            WrongAnswer(user_id=quiz_api.ids.user, question_id=quiz_api.ids.questions[0]),
            WrongAnswer(user_id=quiz_api.ids.user, question_id=quiz_api.ids.other_question),
        ])
        db.commit()

    start = quiz_api.client.post("/api/wrong/practice", json={})
    assert start.status_code == 200, start.text
    session_id = start.json()["session"]["id"]
    original_ids = [q["id"] for q in start.json()["questions"]]
    assert len(original_ids) == 2
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        # 会话建立后其中一题被标记为已掌握：重做仍保留全部原题
        db.query(WrongAnswer).filter_by(
            user_id=quiz_api.ids.user, question_id=quiz_api.ids.other_question,
        ).update({"is_resolved": True})
        db.commit()

    payload = _retry(quiz_api, session_id).json()
    assert [q["id"] for q in payload["questions"]] == original_ids
    new_session = _load_session(quiz_api, payload["session"]["id"])
    assert new_session.mode == "wrong_practice"
    assert new_session.total_questions == 2
    # 逐题取各自题库内容，不缩成首个题库
    assert {entry["question_id"] for entry in new_session.question_snapshot} == set(original_ids)
    assert json.loads(new_session.question_ids) == original_ids


@pytest.mark.parametrize("mode", ["sequential", "random", "exam", "topic"])
def test_retry_keeps_mode_and_question_count(quiz_api, mode):
    body = {"mode": mode}
    if mode == "topic":
        body["topic_id"] = quiz_api.ids.topic
    session_id = _start(quiz_api, **body)
    original = json.loads(_load_session(quiz_api, session_id).question_ids)
    _finish(quiz_api, session_id)

    payload = _retry(quiz_api, session_id).json()
    assert payload["session"]["mode"] == mode
    assert payload["session"]["total_questions"] == len(original)
    new_session = _load_session(quiz_api, payload["session"]["id"])
    assert new_session.mode == mode
    assert json.loads(new_session.question_ids) == original
    if mode == "topic":
        assert new_session.topic_id == quiz_api.ids.topic
        assert payload["session"]["topic_short_name"] == "隐私"
    else:
        assert new_session.topic_id is None


def test_exam_retry_response_hides_explanations(quiz_api):
    session_id = _start(quiz_api, mode="exam")
    _finish(quiz_api, session_id)

    payload = _retry(quiz_api, session_id).json()
    assert payload["session"]["mode"] == "exam"
    assert all("explanation" not in q for q in payload["questions"])
    assert all("ai_explanations" not in q for q in payload["questions"])
    assert all("correct_answer" not in q for q in payload["questions"])


def test_retry_with_removed_topic_keeps_questions(quiz_api):
    """考点已删除时仍保留原题集合；`topic_id` 由外键 `SET NULL` 置空。

    这条用例同时是夹具的金丝雀：SQLite 不强制外键时 `topic_id` 会残留悬空 id，
    下面的 `topic_id is None` 断言会失败，避免再出现「只能靠 SQLite 才成立」的绿灯。
    置空后与「练未分类题目」同形，无法反推原考点已删除，因此响应不再承诺该提示。
    """
    session_id = _start(quiz_api, mode="topic", topic_id=quiz_api.ids.topic)
    original = json.loads(_load_session(quiz_api, session_id).question_ids)
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        db.query(ExamTopic).delete()
        db.commit()

    # 删除考点后外键把原会话的 topic_id 置空，不留悬空 id
    assert _load_session(quiz_api, session_id).topic_id is None

    payload = _retry(quiz_api, session_id).json()
    assert payload["session"]["topic_short_name"] is None
    assert "topic_unavailable" not in payload["session"]
    assert [q["id"] for q in payload["questions"]] == original
    new_session = _load_session(quiz_api, payload["session"]["id"])
    assert new_session.topic_id is None
    assert json.loads(new_session.question_ids) == original


def test_retry_fails_whole_session_when_any_question_is_missing(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    original = json.loads(_load_session(quiz_api, session_id).question_ids)
    _finish(quiz_api, session_id)
    removed = original[1]
    with quiz_api.sessions() as db:
        db.delete(db.get(Question, removed))
        db.commit()

    sessions_before = _session_count(quiz_api)
    response = _retry(quiz_api, session_id)
    assert response.status_code == 400, response.text
    assert str(removed) in response.json()["detail"]
    assert _session_count(quiz_api) == sessions_before  # 没有部分新会话


@pytest.mark.parametrize("stored", [None, "[]", "not-json", '{"a": 1}', '["x", null]'])
def test_retry_rejects_sessions_without_usable_question_ids(quiz_api, stored):
    session_id = _start(quiz_api, mode="sequential")
    _finish(quiz_api, session_id)
    with quiz_api.sessions() as db:
        db.get(QuizSession, session_id).question_ids = stored
        db.commit()

    sessions_before = _session_count(quiz_api)
    response = _retry(quiz_api, session_id)
    assert response.status_code == 400, response.text
    assert _session_count(quiz_api) == sessions_before


def test_retry_rejects_in_progress_session(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    assert _answer(quiz_api, session_id, quiz_api.ids.questions[0], "A").status_code == 200

    sessions_before = _session_count(quiz_api)
    assert _retry(quiz_api, session_id).status_code == 400
    assert _session_count(quiz_api) == sessions_before


def test_retry_rejects_foreign_session_without_leaking_questions(quiz_api):
    """他人用户拥有同名 slug 时只解析到自己的项目：跨项目按不存在处理，不泄露题目。"""
    session_id = _start(quiz_api, mode="sequential")
    _finish(quiz_api, session_id)

    with quiz_api.sessions() as db:
        intruder = User(username="intruder", email="intruder@example.com", password_hash="hash")
        db.add(intruder)
        db.flush()
        db.add(Exam(owner_id=intruder.id, slug="retry", name="Intruder", short_name="I"))
        db.commit()
        token = create_access_token(str(intruder.id))

    original_auth = quiz_api.client.headers["Authorization"]
    quiz_api.client.headers["Authorization"] = f"Bearer {token}"
    response = _retry(quiz_api, session_id)
    assert response.status_code == 404, response.text
    assert "questions" not in response.json()
    quiz_api.client.headers["Authorization"] = original_auth


def test_retry_rejects_session_owned_by_another_user(quiz_api):
    """会话落在当前考试项目内但属于他人：403，且响应不含任何题目内容。"""
    with quiz_api.sessions() as db:
        other = User(username="other", email="other@example.com", password_hash="hash")
        db.add(other)
        db.flush()
        # 手工构造：题目属于当前用户的题库，但会话记在另一个用户名下
        session = QuizSession(
            user_id=other.id,
            bank_id=quiz_api.ids.bank,
            mode="sequential",
            total_questions=1,
            question_ids=json.dumps([quiz_api.ids.questions[0]]),
            question_snapshot=[{
                "question_id": quiz_api.ids.questions[0], "question_type": "single",
                "content": "Q1", "options": OPTIONS, "correct_answer": "A",
            }],
            is_completed=True,
        )
        db.add(session)
        db.commit()
        session_id = session.id

    sessions_before = _session_count(quiz_api)
    response = _retry(quiz_api, session_id)
    assert response.status_code == 403, response.text
    assert "questions" not in response.json()
    assert _session_count(quiz_api) == sessions_before


def test_retry_rejects_session_in_other_exam_project(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    _finish(quiz_api, session_id)

    with quiz_api.sessions() as db:
        second = Exam(
            owner_id=quiz_api.ids.user, slug="retry-second", name="Second", short_name="S2",
        )
        db.add(second)
        db.commit()

    quiz_api.client.headers["X-Exam-Slug"] = "retry-second"
    response = _retry(quiz_api, session_id)
    assert response.status_code == 404, response.text
    assert "questions" not in response.json()
    quiz_api.client.headers["X-Exam-Slug"] = "retry"


def test_retry_rejects_unknown_session(quiz_api):
    assert _retry(quiz_api, 999999).status_code == 404


def test_retry_starts_new_session_with_own_snapshot_and_fresh_state(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    first = quiz_api.ids.questions[0]
    assert _answer(quiz_api, session_id, first, "A").status_code == 200
    _finish(quiz_api, session_id)
    frozen_before = dict(_load_session(quiz_api, session_id).final_answers)

    payload = _retry(quiz_api, session_id).json()
    new_session = _load_session(quiz_api, payload["session"]["id"])

    assert (new_session.answered_count, new_session.correct_count) == (0, 0)
    assert new_session.is_completed is False
    assert new_session.final_answers is None
    assert new_session.completed_at is None
    assert json.loads(new_session.question_ids) == quiz_api.ids.questions
    # 快照取自原题**当前**内容，五个判分依据字段完整
    assert [e["question_id"] for e in new_session.question_snapshot] == quiz_api.ids.questions
    for entry in new_session.question_snapshot:
        assert set(entry) == SNAPSHOT_FIELDS
        assert entry["correct_answer"] == "A"

    # 原会话未被覆盖
    original_after = _load_session(quiz_api, session_id)
    assert original_after.is_completed is True
    assert original_after.final_answers == frozen_before
    assert (original_after.answered_count, original_after.correct_count) == (1, 1)


def test_retry_does_not_write_practice_stats(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    assert _answer(
        quiz_api, session_id, quiz_api.ids.questions[0], "B", local_date="2026-10-13",
    ).status_code == 200
    _finish(quiz_api, session_id)

    def read_stats():
        with quiz_api.sessions() as db:
            return (
                db.query(UserQuestionStat).count(),
                db.query(PracticeDayQuestion).count(),
            )

    # 作答已写入统计；重开本身不增加任何作答统计或练习日
    stats_before = read_stats()
    assert stats_before[0] > 0 and stats_before[1] > 0
    assert _retry(quiz_api, session_id).status_code == 200
    assert read_stats() == stats_before


def test_retried_session_starts_clean_and_does_not_pollute_source_history(quiz_api):
    session_id = _start(quiz_api, mode="sequential")
    first = quiz_api.ids.questions[0]
    assert _answer(quiz_api, session_id, first, "B").status_code == 200
    _finish(quiz_api, session_id)

    new_session_id = _retry(quiz_api, session_id).json()["session"]["id"]
    detail = quiz_api.client.get(f"/api/quiz/session/{new_session_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["session"]["is_completed"] is False

    # 新会话作答不改变原场结果
    assert _answer(quiz_api, new_session_id, first, "A").status_code == 200
    source = quiz_api.client.get(f"/api/quiz/session/{session_id}").json()["session"]
    assert (source["answered_count"], source["correct_count"]) == (1, 0)
    new_detail = quiz_api.client.get(f"/api/quiz/session/{new_session_id}").json()["session"]
    assert (new_detail["answered_count"], new_detail["correct_count"]) == (1, 1)
