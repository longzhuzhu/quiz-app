"""错题连对掌握与错题练习取题：POST /quiz/answer、POST /wrong/practice。

覆盖：
- 跨场连对达标自动掌握并退出错题本；stats 的 resolved 随之增加
- 答对一次后答错归零；已掌握题答错复活且连对为 0
- 手动标记掌握清零连对，与自动掌握落到同一状态
- 本场改答：答对后改成错归零；答错后改成对不加一
- 模拟考试答对不加一、答错不归零，但答错仍写/复活错题
- 顺序/随机/专项/错题练习答对都计入连对（掌握是全局的，不限于错题练习）
- 题量上限截断、非法题量 400、缺省取全部
- 随机洗牌：集合正确、多次调用的顺序不全相同、限定题量取随机子集而非固定前 N 道
- 会话快照隔离：练习开始后其他题被掌握不影响本场题目
- 从未答错的题答对不产生错题记录
- 013 迁移在真实 PostgreSQL 上升级/回滚，存量错题行取 0 而非 NULL
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
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
    Question,
    QuestionBank,
    QuestionTopic,
    QuizSession,
    User,
    WrongAnswer,
)
from app.models.exam_topic import TOPIC_LEVEL_COMPETENCY  # noqa: E402
from app.models.wrong import MASTERY_CORRECT_STREAK  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402

OPTIONS = [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}]
QUESTION_COUNT = 5


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'streak.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="streak", email="streak@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="streak", name="Streak", short_name="S")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="主库", question_count=QUESTION_COUNT)
        db.add(bank)
        db.flush()
        questions = [
            Question(
                bank_id=bank.id, question_type="single", content=f"Q{index}",
                options=OPTIONS, correct_answer="A", order_index=index,
            )
            for index in range(1, QUESTION_COUNT + 1)
        ]
        db.add_all(questions)
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
            user=user.id, exam=exam.id, bank=bank.id,
            questions=[q.id for q in questions], topic=topic.id,
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
            "X-Exam-Slug": "streak",
        })
        yield SimpleNamespace(client=client, ids=ids, sessions=sessions)
    engine.dispose()


# --- 辅助 ---

def _start(api, **body):
    body.setdefault("bank_id", api.ids.bank)
    body.setdefault("mode", "sequential")
    response = api.client.post("/api/quiz/start", json=body)
    assert response.status_code == 200, response.text
    return response.json()["session"]["id"]


def _practice(api, **body):
    return api.client.post("/api/wrong/practice", json=body)


def _answer(api, session_id, question_id, user_answer):
    return api.client.post("/api/quiz/answer", json={
        "session_id": session_id, "question_id": question_id, "user_answer": user_answer,
    })


def _finish(api, session_id):
    response = api.client.post("/api/quiz/finish", json={"session_id": session_id})
    assert response.status_code == 200, response.text


def _answer_in_new_session(api, question_id, user_answer, mode="sequential", **extra):
    """新开一场并作答，用于模拟跨场作答。"""
    session_id = _start(api, mode=mode, **extra)
    response = _answer(api, session_id, question_id, user_answer)
    assert response.status_code == 200, response.text
    _finish(api, session_id)
    return session_id


def _wrong_row(api, question_id) -> WrongAnswer | None:
    with api.sessions() as db:
        row = db.query(WrongAnswer).filter_by(
            user_id=api.ids.user, question_id=question_id
        ).first()
        if row is not None:
            db.expunge(row)
        return row


def _wrong_list(api):
    response = api.client.get("/api/wrong")
    assert response.status_code == 200, response.text
    return response.json()


def _wrong_stats(api):
    response = api.client.get("/api/wrong/stats")
    assert response.status_code == 200, response.text
    return response.json()


# --- 连对达标自动掌握 ---

def test_two_correct_across_sessions_marks_mastered(api):
    """跨两场各答对一次即达标，题目退出错题本且统计口径同步。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")  # 先答错沉淀错题
    assert _wrong_row(api, question_id).correct_streak == 0

    _answer_in_new_session(api, question_id, "A")  # 第一次答对
    row = _wrong_row(api, question_id)
    assert row.correct_streak == 1
    assert row.is_resolved is False

    before = _wrong_stats(api)
    _answer_in_new_session(api, question_id, "A")  # 第二次答对，达标
    row = _wrong_row(api, question_id)
    assert row.correct_streak == MASTERY_CORRECT_STREAK
    assert row.is_resolved is True

    assert question_id not in [item["question_id"] for item in _wrong_list(api)]
    after = _wrong_stats(api)
    assert after["resolved"] == before["resolved"] + 1
    assert after["unresolved"] == before["unresolved"] - 1


def test_wrong_list_exposes_correct_streak(api):
    """列表需要连对进度供前端展示。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")
    _answer_in_new_session(api, question_id, "A")

    entry = next(item for item in _wrong_list(api) if item["question_id"] == question_id)
    assert entry["correct_streak"] == 1


def test_never_wrong_question_records_no_wrong_answer(api):
    """从未答错的题答对不应凭空生成错题记录。"""
    question_id = api.ids.questions[1]
    _answer_in_new_session(api, question_id, "A")
    _answer_in_new_session(api, question_id, "A")

    assert _wrong_row(api, question_id) is None


# --- 答错归零与复活 ---

def test_wrong_answer_resets_streak(api):
    """答对一次后答错，连对归零且题目留在错题本。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")
    _answer_in_new_session(api, question_id, "A")
    assert _wrong_row(api, question_id).correct_streak == 1

    _answer_in_new_session(api, question_id, "B")
    row = _wrong_row(api, question_id)
    assert row.correct_streak == 0
    assert row.is_resolved is False
    assert row.wrong_count == 2


def test_wrong_answer_revives_mastered_question(api):
    """已自动掌握的题再答错即复活，且连对从 0 重新开始。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")
    _answer_in_new_session(api, question_id, "A")
    _answer_in_new_session(api, question_id, "A")
    assert _wrong_row(api, question_id).is_resolved is True

    _answer_in_new_session(api, question_id, "B")
    row = _wrong_row(api, question_id)
    assert row.is_resolved is False
    assert row.correct_streak == 0
    assert question_id in [item["question_id"] for item in _wrong_list(api)]


# --- 手动掌握 ---

def test_manual_resolve_clears_streak_and_matches_auto_state(api):
    """手动掌握清零连对，避免残留计数让下次答对直接达标。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")
    _answer_in_new_session(api, question_id, "A")

    entry = next(item for item in _wrong_list(api) if item["question_id"] == question_id)
    response = api.client.put(f"/api/wrong/{entry['id']}/resolve")
    assert response.status_code == 200, response.text

    row = _wrong_row(api, question_id)
    assert row.is_resolved is True
    assert row.correct_streak == 0
    # 与自动掌握状态一致：答对一次不应立刻重新掌握
    _answer_in_new_session(api, question_id, "A")
    row = _wrong_row(api, question_id)
    assert row.correct_streak == 1
    assert row.is_resolved is True


# --- 本场改答边界 ---

def test_reanswer_wrong_clears_streak(api):
    """本场先答对再改成错：连对归零（改答到错同样视为答错）。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")

    session_id = _start(api)
    assert _answer(api, session_id, question_id, "A").status_code == 200
    assert _wrong_row(api, question_id).correct_streak == 1

    assert _answer(api, session_id, question_id, "B").status_code == 200
    assert _wrong_row(api, question_id).correct_streak == 0


def test_reanswer_correct_does_not_increment_streak(api):
    """本场先答错再改成对：连对不增加，防止同场反复改答刷满。"""
    question_id = api.ids.questions[0]
    session_id = _start(api)
    assert _answer(api, session_id, question_id, "B").status_code == 200
    assert _answer(api, session_id, question_id, "A").status_code == 200

    assert _wrong_row(api, question_id).correct_streak == 0


# --- 模拟考试隔离 ---

def test_exam_mode_correct_does_not_increment_streak(api):
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")
    _answer_in_new_session(api, question_id, "A")
    assert _wrong_row(api, question_id).correct_streak == 1

    _answer_in_new_session(api, question_id, "A", mode="exam")
    assert _wrong_row(api, question_id).correct_streak == 1


def test_exam_mode_wrong_keeps_streak_but_still_collects(api):
    """模拟考试答错不清零连对，但仍按既有行为写入错题。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")
    _answer_in_new_session(api, question_id, "A")
    assert _wrong_row(api, question_id).correct_streak == 1

    _answer_in_new_session(api, question_id, "B", mode="exam")
    row = _wrong_row(api, question_id)
    assert row.correct_streak == 1
    assert row.wrong_count == 2
    assert row.is_resolved is False

    # 模拟考试首次答错也要沉淀错题
    fresh = api.ids.questions[2]
    _answer_in_new_session(api, fresh, "B", mode="exam")
    assert _wrong_row(api, fresh) is not None


# --- 掌握是全局的：其他模式也计入 ---

def test_random_and_topic_modes_count_toward_streak(api):
    """随机与专项模式也计入连对（顺序模式由默认 `_answer_in_new_session` 覆盖）。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")

    _answer_in_new_session(api, question_id, "A", mode="random")
    assert _wrong_row(api, question_id).correct_streak == 1

    _answer_in_new_session(api, question_id, "A", mode="topic", topic_id=api.ids.topic)
    row = _wrong_row(api, question_id)
    assert row.correct_streak == MASTERY_CORRECT_STREAK
    assert row.is_resolved is True


def test_wrong_practice_mode_counts_toward_streak(api):
    """R3 列出的「错题练习」模式同样计入连对，验证四种非考试模式全覆盖。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")

    practice = _practice(api)
    assert practice.status_code == 200, practice.text
    session_id = practice.json()["session"]["id"]
    assert _answer(api, session_id, question_id, "A").status_code == 200
    _finish(api, session_id)
    assert _wrong_row(api, question_id).correct_streak == 1


# --- 错题练习题量上限 ---

def test_practice_defaults_to_all_unresolved(api):
    for question_id in api.ids.questions:
        _answer_in_new_session(api, question_id, "B")

    response = _practice(api)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session"]["total_questions"] == QUESTION_COUNT
    assert len(payload["questions"]) == QUESTION_COUNT


def test_practice_truncates_when_count_exceeds_available(api):
    for question_id in api.ids.questions[:2]:
        _answer_in_new_session(api, question_id, "B")

    response = _practice(api, question_count=99)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session"]["total_questions"] == 2
    assert len(payload["questions"]) == 2


def test_practice_honors_count_within_available(api):
    for question_id in api.ids.questions:
        _answer_in_new_session(api, question_id, "B")

    response = _practice(api, question_count=2)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session"]["total_questions"] == 2
    assert len(payload["questions"]) == 2


@pytest.mark.parametrize("invalid", [0, -1, -100])
def test_practice_rejects_non_positive_count_with_readable_400(api, invalid):
    """非法题量返回 400 与可读文案；若改回 Pydantic 约束会变成 422 + detail 数组。"""
    question_id = api.ids.questions[0]
    _answer_in_new_session(api, question_id, "B")

    response = _practice(api, question_count=invalid)
    assert response.status_code == 400
    body = response.json()
    assert isinstance(body["detail"], str)
    assert "题目数量" in body["detail"]


def test_practice_without_wrong_answers_returns_400(api):
    response = _practice(api)
    assert response.status_code == 400
    assert response.json()["detail"] == "没有错题"


# --- 随机顺序 ---

def test_practice_subset_is_within_unresolved_and_unique(api):
    """题量上限取到的是未掌握错题的子集且无重复。"""
    for question_id in api.ids.questions:
        _answer_in_new_session(api, question_id, "B")
    mastered = api.ids.questions[0]
    _answer_in_new_session(api, mastered, "A")
    _answer_in_new_session(api, mastered, "A")
    assert _wrong_row(api, mastered).is_resolved is True

    response = _practice(api, question_count=2)
    assert response.status_code == 200, response.text
    returned = [item["id"] for item in response.json()["questions"]]
    unresolved = {item["question_id"] for item in _wrong_list(api)}
    assert len(returned) == len(set(returned))
    assert set(returned) <= unresolved
    assert mastered not in returned


def test_practice_shuffles_order_across_starts(api):
    """反复开始时顺序不应总是一致。真随机会偶发相同，故只要求至少出现一次差异。"""
    for question_id in api.ids.questions:
        _answer_in_new_session(api, question_id, "B")

    first = [item["id"] for item in _practice(api).json()["questions"]]
    assert len(first) == QUESTION_COUNT
    observed_difference = any(
        [item["id"] for item in _practice(api).json()["questions"]] != first
        for _ in range(12)
    )
    assert observed_difference, "连续 13 次开始错题练习的顺序完全相同，随机洗牌可能失效"


def test_limited_practice_takes_random_subset_not_fixed_prefix(api):
    """AC7：题量上限生效时取到的是随机子集，而非固定前 N 道。

    只运行不加限的路径无法发现「限定时按固定顺序切片」的实现——上面那条
    顺序差异用例在限定路径被改成固定排序时仍会通过。
    """
    for question_id in api.ids.questions:
        _answer_in_new_session(api, question_id, "B")

    subsets = {
        tuple(item["id"] for item in _practice(api, question_count=2).json()["questions"])
        for _ in range(30)
    }
    assert len(subsets) > 1, f"30 次限定题量练习取到同一子集 {subsets}，随机子集可能退化为固定前 N 道"


# --- 会话快照隔离 ---

def test_practice_session_snapshot_unaffected_by_later_mastery(api):
    """练习开始后其他题被答对掌握，不应改变本场题目列表。"""
    for question_id in api.ids.questions:
        _answer_in_new_session(api, question_id, "B")

    payload = _practice(api).json()
    session_id = payload["session"]["id"]
    original_ids = [item["id"] for item in payload["questions"]]

    mastered = api.ids.questions[0]
    _answer_in_new_session(api, mastered, "A")
    _answer_in_new_session(api, mastered, "A")
    assert _wrong_row(api, mastered).is_resolved is True

    with api.sessions() as db:
        session = db.get(QuizSession, session_id)
        stored = json.loads(session.question_ids)
        assert stored == original_ids
        assert session.total_questions == len(original_ids)


# --- 013 迁移（AC9）---

@contextmanager
def _migration_sandbox(schema: str):
    """在隔离 PostgreSQL 的专用 schema 上跑 alembic，产出 (engine, migrate, columns)。

    `migrate(*args)` 转发给 alembic（如 `("upgrade", "head")`）；`columns()` 返回
    `wrong_answers.correct_streak` 是否存在的列名集合。测试结束自动 DROP SCHEMA。
    """
    def columns(engine):
        with engine.connect() as conn:
            return set(conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'wrong_answers' "
                    "AND column_name = 'correct_streak'"
                ),
                {"schema": schema},
            ).scalars().all())

    with isolated_postgres() as engine:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        try:
            url = engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
            # alembic 把 -x url= 交给 configparser，URL 里的 % 需转义成 %% 否则插值报错
            url_string = url.render_as_string(hide_password=False).replace("%", "%%")

            def migrate(*args):
                # Alembic env 会重配置日志；隔离进程避免影响其他测试的日志捕获。
                subprocess.run(
                    [sys.executable, "-m", "alembic", "-x", f"url={url_string}", *args],
                    cwd=BACKEND_ROOT, check=True, capture_output=True, text=True,
                )

            yield engine, migrate, columns
        finally:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_migration_013_adds_not_null_default_zero_for_existing_rows():
    """013 在真实 PostgreSQL（隔离实例）上升级/回滚，且存量错题行取 0 而非 NULL。

    SQLite 掩盖 NOT NULL + server_default 的差异，该回归必须连真实 PostgreSQL。
    """
    schema = "wrong_streak_migration_test"
    with _migration_sandbox(schema) as (engine, migrate, migration_columns):
        migrate("upgrade", "001")
        # 003 要求 owner 用户先存在；迁移跑在专用 schema 上，这里补最小的 admin 行。
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text(
                "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
                "VALUES (1, 'nianyu', 'nianyu@example.com', 'x', TRUE, NOW())"
            ))

        # 先升到 012（无 correct_streak），插入一条存量错题，再升 013。
        # 只有「存量行在升级后是 0 而不是 NULL」才是本迁移要锁住的契约；
        # 升级之后再插入的行本就会被 ORM/DDL 默认值覆盖，验证不到回填。
        migrate("upgrade", "012")
        assert migration_columns(engine) == set()
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text(
                "INSERT INTO question_banks (id, exam_id, name, question_count, created_at) "
                "SELECT 1, id, 'b', 1, NOW() FROM exams LIMIT 1"
            ))
            conn.execute(text(
                "INSERT INTO questions (id, bank_id, question_type, content, options, correct_answer, order_index, created_at) "
                "VALUES (1, 1, 'single', 'q', '[]'::jsonb, 'A', 1, NOW())"
            ))
            conn.execute(text(
                "INSERT INTO wrong_answers (id, user_id, question_id, wrong_count, last_wrong_at, is_resolved) "
                "VALUES (1, 1, 1, 1, NOW(), FALSE)"
            ))

        migrate("upgrade", "head")
        assert migration_columns(engine) == {"correct_streak"}
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            column = conn.execute(text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'wrong_answers' "
                "AND column_name = 'correct_streak'"
            ), {"schema": schema}).one()
            assert tuple(column) == ("NO", "0")
            assert conn.execute(text(
                "SELECT count(*) FROM wrong_answers WHERE correct_streak IS NULL"
            )).scalar() == 0
            assert conn.execute(text("SELECT correct_streak FROM wrong_answers")).scalar() == 0

        migrate("downgrade", "012")
        assert migration_columns(engine) == set()


def test_migration_013_upgrades_empty_table():
    """AC9 的空库分支：wrong_answers 零行时升级同样成功，且定义与含存量行时一致。"""
    schema = "wrong_streak_empty_test"
    with _migration_sandbox(schema) as (engine, migrate, migration_columns):
        # 迁移链的 003 要求 admin 用户先存在（见另一条迁移用例的同类前置），
        # 但这里**不插入任何错题行**——空表升级不会被 server_default 的回填掩盖问题
        # （如列被误建为可空），是与含存量行分支互补的验证。
        migrate("upgrade", "001")
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text(
                "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
                "VALUES (1, 'nianyu', 'nianyu@example.com', 'x', TRUE, NOW())"
            ))
            # 确认起点确实是空表，否则这条用例论证不到「空库升级」
            assert conn.execute(text("SELECT count(*) FROM wrong_answers")).scalar() == 0

        migrate("upgrade", "head")
        assert migration_columns(engine) == {"correct_streak"}
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            column = conn.execute(text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'wrong_answers' "
                "AND column_name = 'correct_streak'"
            ), {"schema": schema}).one()
            assert tuple(column) == ("NO", "0")
            assert conn.execute(text("SELECT count(*) FROM wrong_answers")).scalar() == 0

        migrate("downgrade", "012")
        assert migration_columns(engine) == set()
