"""POST /quiz/retry 与并发删除题目的竞态：真实 PostgreSQL，不用 SQLite。

`question_ids` 存 JSON 而非外键，删除题目不会触发约束错误。若校验与创建之间被并发
删除，新会话会带上一个已不存在的题且无法作答。校验查询必须与删除端持有同一把行锁
（`with_for_update(of=Question)`），把两个操作串行化。

SQLite 不支持 `FOR UPDATE`，本测试必须在真实 PostgreSQL 上跑才有意义。
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


def test_retry_and_concurrent_question_delete_never_keeps_deleted_question(postgres):
    """整场重开与删除任一原题并发时，结果只能是「重开成功且题目全在」或「重开失败」。"""
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

    victims = question_ids[:2]
    results = race([
        lambda api: api.post("/api/quiz/retry", json={"session_id": session_id}),
        lambda api: api.delete(f"/api/questions/{victims[0]}"),
        lambda api: api.delete(f"/api/questions/{victims[1]}"),
    ])
    retry_response, *delete_responses = results
    assert all(r.status_code == 200 for r in delete_responses), [r.status_code for r in delete_responses]
    assert retry_response.status_code in {200, 400}, retry_response.text

    with sessions() as db:
        existing = {q.id for q in db.query(Question).all()}
        new_sessions = (
            db.query(QuizSession)
            .filter(QuizSession.id != session_id, QuizSession.user_id == user_id)
            .all()
        )
        # 无论竞态如何交错，都不能留下「会话引用了不存在题目」的状态
        for created in new_sessions:
            stored = json.loads(created.question_ids)
            assert all(qid in existing for qid in stored), (
                f"新会话引用了已删除题目: {sorted(set(stored) - existing)}"
            )
        if retry_response.status_code == 400:
            # 重开失败时不得留下部分会话
            assert new_sessions == [], "重开失败却创建了会话"
        else:
            assert len(new_sessions) == 1
            assert len(json.loads(new_sessions[0].question_ids)) == len(question_ids)


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
