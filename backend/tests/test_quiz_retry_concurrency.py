"""POST /quiz/retry 与并发删除题目的竞态：真实 PostgreSQL，不用 SQLite。

`question_ids` 存 JSON 而非外键，删除题目不会触发约束错误。若校验与创建之间被并发
删除，新会话会带上一个已不存在的题且无法作答。校验查询必须与删除端持有同一把行锁
（`with_for_update(of=Question)`），把两个操作串行化。

SQLite 不支持 `FOR UPDATE`，本测试必须在真实 PostgreSQL 上跑才有意义。
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Thread
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.deps import get_current_user  # noqa: E402
from app.api.routes.questions import router as questions_router  # noqa: E402
from app.api.routes.quiz import router as quiz_router  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.models import Exam, Question, QuestionBank, QuizSession, User  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402

OPTIONS = [{"key": key, "text": f"选项{key}"} for key in ("A", "B", "C", "D")]


@pytest.fixture(scope="module")
def postgres():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


def test_retry_and_concurrent_question_delete_stay_atomic(postgres):
    """整场重开与删除任一原题并发时，两种结果都必须自洽，不存在中间态。

    - 删除先完成 → 重开返回 400，列出缺题，且不创建任何会话。
    - 重开先完成 → 新会话保留完整原题与原顺序，快照齐备。

    不保证「新会话引用的题都存在」——重开成功之后仍可被删除，那是管理员的合法操作，
    快照正是为此存在。锁的作用是消除「校验与创建之间被插入删除」这个窗口，使两种结果
    互斥且都完整，而非让新会话永久免疫后续删除。
    """
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        user = User(username="retry-race", email="retry-race@example.invalid", password_hash="unused")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="race", name="Race", short_name="Race")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Race")
        db.add(bank)
        db.flush()
        questions = []
        for index in range(4):
            question = Question(
                bank_id=bank.id, question_type="single", content=f"第 {index} 题",
                options=OPTIONS, correct_answer="A", order_index=index,
            )
            db.add(question)
            questions.append(question)
        db.flush()
        session = QuizSession(
            user_id=user.id, bank_id=bank.id, mode="sequential",
            total_questions=len(questions),
            question_ids=json.dumps([q.id for q in questions]),
            is_completed=True, answered_count=0, correct_count=0,
        )
        db.add(session)
        db.commit()
        user_id, exam_id, session_id = user.id, exam.id, session.id
        question_ids = [q.id for q in questions]

    app = FastAPI()
    app.include_router(quiz_router, prefix="/api/quiz")
    app.include_router(questions_router, prefix="/api/questions")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database

    def authenticated():
        with sessions() as db:
            return db.get(User, user_id)

    app.dependency_overrides[get_current_user] = authenticated

    def race(actions):
        barrier = Barrier(len(actions))

        def run(action):
            with TestClient(app, headers={"X-Exam-Slug": "race"}, raise_server_exceptions=False) as api:
                barrier.wait(timeout=10)
                return action(api)

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(run, actions))

    # 重开与删除并发时，两种结果都必须自洽（不存在中间态）。
    # 锁的作用是让二者互斥，而不是让新会话免疫后续删除——重开成功后题仍可被删，
    # 那是管理员的合法操作，也正是快照存在的理由。
    # 锁本身的验证见 test_retry_endpoint_waits_for_lock_held_by_delete：状态断言无法
    # 区分两者（有锁与无锁的最终库状态同形），只有阻塞行为可以。
    victim = question_ids[0]
    results = race([
        lambda api: api.post("/api/quiz/retry", json={"session_id": session_id}),
        lambda api: api.delete(f"/api/questions/{victim}"),
    ])
    retry_response, delete_response = results
    assert delete_response.status_code in {200, 404}, delete_response.text
    assert retry_response.status_code in {200, 400}, retry_response.text

    with sessions() as db:
        created_sessions = (
            db.query(QuizSession)
            .filter(QuizSession.user_id == user_id, QuizSession.id != session_id)
            .all()
        )
        if retry_response.status_code == 400:
            # 重开失败必须是「检测到缺题」，且不留部分会话（原子性）
            assert "不可用" in retry_response.json()["detail"], retry_response.text
            assert created_sessions == [], "重开失败却创建了会话"
        else:
            assert len(created_sessions) == 1, f"重开成功却创建了 {len(created_sessions)} 个会话"
            stored = json.loads(created_sessions[0].question_ids)
            assert stored == question_ids, f"重开成功必须保留完整原题与原顺序: {stored}"
            snapshot_ids = [e["question_id"] for e in created_sessions[0].question_snapshot]
            assert snapshot_ids == question_ids, "快照必须覆盖全部原题且与 question_ids 同序"


def test_retry_endpoint_waits_for_lock_held_by_delete(postgres):
    """端点级验证：删除方持锁未提交时，retry 必须等待而不是抢先通过。

    这是本文件唯一能区分「retry 加锁」与「retry 不加锁」的测试——二者在最终库状态上
    完全同形（重开成功 + 该题已删），状态断言无法证明锁存在，只有**阻塞行为**可以。

    做法：另一连接删除该题但**不提交**，持住行锁；此时调用 retry：
    - retry 有 `with_for_update` → 阻塞在 SELECT 上，删除提交后读到缺题 → 400
    - retry 无锁               → 立刻按「题都在」通过 → 200（并在提交时写入已删的题）
    """
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        user = User(username="lock-wait", email="lock-wait@example.invalid", password_hash="unused")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="lockwait", name="LockWait", short_name="LockWait")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="LockWait")
        db.add(bank)
        db.flush()
        questions = []
        for index in range(2):
            question = Question(
                bank_id=bank.id, question_type="single", content=f"锁验证题 {index}",
                options=OPTIONS, correct_answer="A", order_index=index,
            )
            db.add(question)
            questions.append(question)
        db.flush()
        session = QuizSession(
            user_id=user.id, bank_id=bank.id, mode="sequential",
            total_questions=len(questions),
            question_ids=json.dumps([q.id for q in questions]),
            is_completed=True,
        )
        db.add(session)
        db.commit()
        user_id, session_id = user.id, session.id
        victim = questions[0].id
        all_ids = [q.id for q in questions]

    app = FastAPI()
    app.include_router(quiz_router, prefix="/api/quiz")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database

    def authenticated():
        with sessions() as db:
            return db.get(User, user_id)

    app.dependency_overrides[get_current_user] = authenticated

    retry_result = {}

    def call_retry():
        with TestClient(app, headers={"X-Exam-Slug": "lockwait"}, raise_server_exceptions=False) as api:
            started = time.monotonic()
            response = api.post("/api/quiz/retry", json={"session_id": session_id})
            retry_result["elapsed"] = time.monotonic() - started
            retry_result["status"] = response.status_code
            retry_result["body"] = response.text

    with postgres.connect() as blocker:
        blocker.execute(text("BEGIN"))
        blocker.execute(text("DELETE FROM questions WHERE id = :qid"), {"qid": victim})

        worker = Thread(target=call_retry, daemon=True)
        worker.start()
        # 锁被持有期间，retry 必须仍在等待；若它已返回，说明没有走 FOR UPDATE
        worker.join(timeout=1.0)
        assert worker.is_alive(), (
            f"retry 在删除方持锁期间就返回了（status={retry_result.get('status')}）——"
            "说明校验查询未持有行锁，删除与重开可以交错"
        )

        blocker.execute(text("COMMIT"))  # 释放锁，删除生效

    worker.join(timeout=15)
    assert not worker.is_alive(), "释放锁后 retry 应能完成"
    # 删除先提交，retry 读到缺题，整场失败
    assert retry_result["status"] == 400, retry_result["body"]
    assert str(victim) in retry_result["body"]

    with sessions() as db:
        created = (
            db.query(QuizSession)
            .filter(QuizSession.user_id == user_id, QuizSession.id != session_id)
            .all()
        )
        assert created == [], "重开失败不得留下部分会话"
    assert all_ids  # 保留变量以免被误判为未使用

    # 说明：重开成功后再发生的删除会让新会话引用已删除的题，这是**预期行为**而非缺陷——
    # 快照正是为此存在（题目后来被删，历史场次仍可复盘）。因此这里不断言「无悬空引用」：
    # 该性质在竞态下本来就不可保证（管理员有权随时删题），强行断言会让测试随调度抖动。


def test_retry_after_question_deleted_returns_400_without_partial_session(postgres):
    """顺序场景（非并发）：删题后重开必须整场失败，且不留下部分会话。"""
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        user = User(username="retry-serial", email="retry-serial@example.invalid", password_hash="unused")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="serial", name="Serial", short_name="Serial")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Serial")
        db.add(bank)
        db.flush()
        questions = []
        for index in range(3):
            question = Question(
                bank_id=bank.id, question_type="single", content=f"第 {index} 题",
                options=OPTIONS, correct_answer="A", order_index=index,
            )
            db.add(question)
            questions.append(question)
        db.flush()
        session = QuizSession(
            user_id=user.id, bank_id=bank.id, mode="sequential",
            total_questions=len(questions),
            question_ids=json.dumps([q.id for q in questions]),
            is_completed=True,
        )
        db.add(session)
        db.commit()
        user_id, session_id = user.id, session.id
        victim = questions[1].id

    app = FastAPI()
    app.include_router(quiz_router, prefix="/api/quiz")
    app.include_router(questions_router, prefix="/api/questions")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database

    def authenticated():
        with sessions() as db:
            return db.get(User, user_id)

    app.dependency_overrides[get_current_user] = authenticated

    with TestClient(app, headers={"X-Exam-Slug": "serial"}) as api:
        assert api.delete(f"/api/questions/{victim}").status_code == 200
        response = api.post("/api/quiz/retry", json={"session_id": session_id})
        assert response.status_code == 400, response.text
        assert str(victim) in response.json()["detail"]

    with sessions() as db:
        # 只统计本用户在本用例中创建的会话（同一集群里可能已有前一个用例的数据）
        others = (
            db.query(QuizSession)
            .filter(QuizSession.id != session_id, QuizSession.user_id == user_id)
            .count()
        )
        assert others == 0
