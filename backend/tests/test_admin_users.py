"""账号管理：管理员建号、停用、删除，以及账号状态对登录的影响。

全部用例跑在内存 SQLite 上，不连接业务数据库。
"""

import sys
from pathlib import Path

import pytest
from fastapi import Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


from fastapi import FastAPI  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app.api.deps import get_current_user, require_admin  # noqa: E402
from app.api.routes import auth as auth_routes  # noqa: E402
from app.api.routes import admin_users  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models import (  # noqa: E402
    BackgroundJob,
    Exam,
    ImportJob,
    ImportParsedQuestion,
    ImportReviewItem,
    Question,
    QuestionBank,
    QuizAnswer,
    QuizSession,
    User,
    UserQuestionStat,
    Vocabulary,
    WrongAnswer,
)
from app.services.exam_service import delete_user_data  # noqa: E402

ADMIN_PASSWORD = "admin-secret"


@pytest.fixture
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite 默认不校验外键，删除顺序写错也能过。开启后才能验证真实约束。
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    admin = User(
        username="root",
        email="root@example.invalid",
        password_hash=get_password_hash(ADMIN_PASSWORD),
        is_admin=True,
        is_active=True,
    )
    member = User(
        username="alice",
        email="alice@example.invalid",
        password_hash=get_password_hash("alice-secret"),
        is_admin=False,
        is_active=True,
    )
    db.add_all([admin, member])
    db.commit()

    app = FastAPI()
    app.include_router(admin_users.router, prefix="/api/admin/users")
    app.include_router(auth_routes.router, prefix="/api/auth")
    app.dependency_overrides[get_db] = lambda: db

    state = {"actor": admin, "db": db, "engine": engine}

    def current_user_provider(x_actor: str = Header("root")):
        user = db.query(User).filter_by(username=x_actor).first()
        assert user is not None, f"测试身份 {x_actor} 不存在"
        return user

    app.dependency_overrides[get_current_user] = current_user_provider
    app.dependency_overrides[require_admin] = current_user_provider

    with TestClient(app) as api:
        state["api"] = api
        yield state
    db.close()
    engine.dispose()


def _as(ctx, username):
    """切换请求身份；依赖覆盖按 X-Actor 头解析当前用户。"""
    ctx["actor"] = ctx["db"].query(User).filter_by(username=username).first()
    return {"X-Actor": username}


def test_create_user_hashes_password_and_defaults_to_active(ctx):
    response = ctx["api"].post(
        "/api/admin/users",
        json={"username": "bob", "email": "bob@example.invalid", "password": "bob-secret", "is_admin": False},
        headers=_as(ctx, "root"),
    )

    assert response.status_code == 201
    created = response.json()
    assert created["username"] == "bob"
    assert created["is_active"] is True
    assert created["is_admin"] is False

    db = ctx["db"]
    stored = db.query(User).filter_by(username="bob").one()
    assert stored.password_hash != "bob-secret"

    login = ctx["api"].post("/api/auth/login", json={"username": "bob", "password": "bob-secret"})
    assert login.status_code == 200


def test_create_user_rejects_duplicate_username_and_short_password(ctx):
    ctx["api"].post(
        "/api/admin/users",
        json={"username": "bob", "email": "bob@example.invalid", "password": "bob-secret"},
        headers=_as(ctx, "root"),
    )

    duplicate = ctx["api"].post(
        "/api/admin/users",
        json={"username": "bob", "email": "other@example.invalid", "password": "bob-secret"},
        headers=_as(ctx, "root"),
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "用户名已存在"

    short = ctx["api"].post(
        "/api/admin/users",
        json={"username": "carol", "email": "carol@example.invalid", "password": "123"},
        headers=_as(ctx, "root"),
    )
    assert short.status_code == 422


def test_register_endpoint_is_gone(ctx):
    response = ctx["api"].post(
        "/api/auth/register",
        json={"username": "mallory", "email": "mallory@example.invalid", "password": "mallory-secret"},
    )
    assert response.status_code in (404, 405)


def test_disabled_account_cannot_log_in_and_reads_as_wrong_password(ctx):
    ctx["db"].query(User).filter_by(username="alice").one().is_active = False
    ctx["db"].commit()

    response = ctx["api"].post(
        "/api/auth/login", json={"username": "alice", "password": "alice-secret"}
    )

    assert response.status_code == 401
    # 停用与密码错误共用同一提示，不给未认证请求方确认账号存在性。
    assert response.json()["detail"] == "用户名或密码错误"


def test_admin_cannot_disable_or_delete_self(ctx):
    disable = ctx["api"].patch(
        "/api/admin/users/1", json={"is_active": False}, headers=_as(ctx, "root")
    )
    assert disable.status_code == 400
    assert disable.json()["detail"] == "不能停用自己的账号"

    delete = ctx["api"].delete("/api/admin/users/1", headers=_as(ctx, "root"))
    assert delete.status_code == 400
    assert delete.json()["detail"] == "不能删除自己的账号"


def test_admin_cannot_demote_self(ctx):
    response = ctx["api"].patch(
        "/api/admin/users/1", json={"is_admin": False}, headers=_as(ctx, "root")
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "不能降级自己的账号"


def test_last_usable_admin_is_protected_from_demote_while_session_survives(ctx):
    """停用只挡新登录，被停用管理员的旧 token 仍可调用；它就是最后一个可用管理员的威胁来源。"""
    db = ctx["db"]
    second = User(
        username="root2",
        email="root2@example.invalid",
        password_hash=get_password_hash("root2-secret"),
        is_admin=True,
        is_active=False,
    )
    db.add(second)
    db.commit()

    # root 是唯一可用管理员；root2 已停用但 token 未吊销，仍能通过 require_admin。
    response = ctx["api"].patch(
        "/api/admin/users/1", json={"is_admin": False}, headers=_as(ctx, "root2")
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "系统必须保留至少一个可用管理员"

    delete = ctx["api"].delete("/api/admin/users/1", headers=_as(ctx, "root2"))
    assert delete.status_code == 400
    assert delete.json()["detail"] == "系统必须保留至少一个可用管理员"
    assert db.query(User).filter_by(username="root").one() is not None


def test_demoting_another_usable_admin_is_allowed_while_one_remains(ctx):
    db = ctx["db"]
    second = User(
        username="root2",
        email="root2@example.invalid",
        password_hash=get_password_hash("root2-secret"),
        is_admin=True,
        is_active=True,
    )
    db.add(second)
    db.commit()

    response = ctx["api"].patch(
        f"/api/admin/users/{second.id}", json={"is_admin": False}, headers=_as(ctx, "root")
    )

    assert response.status_code == 200
    assert response.json()["is_admin"] is False


def test_enable_target_allows_login_again(ctx):
    db = ctx["db"]
    db.query(User).filter_by(username="alice").one().is_active = False
    db.commit()

    response = ctx["api"].patch(
        f"/api/admin/users/{db.query(User).filter_by(username='alice').one().id}",
        json={"is_active": True},
        headers=_as(ctx, "root"),
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True

    assert ctx["api"].post(
        "/api/auth/login", json={"username": "alice", "password": "alice-secret"}
    ).status_code == 200


def test_delete_user_with_running_background_job_is_rejected(ctx):
    db = ctx["db"]
    alice = db.query(User).filter_by(username="alice").one()
    db.add(
        BackgroundJob(
            job_type="ai_explanation",
            scope_key="s1",
            payload_json="{}",
            status="running",
            created_by=alice.id,
        )
    )
    db.commit()

    response = ctx["api"].delete(f"/api/admin/users/{alice.id}", headers=_as(ctx, "root"))

    assert response.status_code == 409
    assert response.json()["detail"] == "该用户有正在执行的后台任务，请稍后重试"
    assert db.query(User).filter_by(username="alice").one() is not None


def test_delete_user_removes_owned_data_and_leaves_others_untouched(ctx):
    db = ctx["db"]
    alice = db.query(User).filter_by(username="alice").one()
    root = db.query(User).filter_by(username="root").one()

    exam = Exam(owner_id=alice.id, slug="alice-exam", name="Alice", short_name="A")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="Alice bank", exam_id=exam.id)
    db.add(bank)
    db.flush()
    question = Question(
        bank_id=bank.id,
        question_type="single",
        content="q?",
        options=[{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
        correct_answer="A",
    )
    db.add(question)
    db.flush()
    session = QuizSession(
        user_id=alice.id, bank_id=bank.id, mode="sequential", total_questions=1,
    )
    db.add(session)
    db.flush()
    db.add_all([
        QuizAnswer(session_id=session.id, question_id=question.id, user_answer="B", is_correct=False),
        WrongAnswer(user_id=alice.id, question_id=question.id),
        UserQuestionStat(user_id=alice.id, question_id=question.id, answer_count=1),
        Vocabulary(term="alice-word", user_id=alice.id),
        Vocabulary(term="root-word", user_id=root.id),
    ])
    db.commit()
    alice_id = alice.id
    exam_id = exam.id
    bank_id = bank.id
    question_id = question.id
    session_id = session.id

    response = ctx["api"].delete(f"/api/admin/users/{alice_id}", headers=_as(ctx, "root"))

    assert response.status_code == 200
    assert db.get(User, alice_id) is None
    assert db.query(Exam).filter_by(owner_id=alice_id).count() == 0
    assert db.query(QuestionBank).filter_by(exam_id=exam_id).count() == 0
    assert db.query(Question).filter_by(id=question_id).count() == 0
    assert db.query(QuizAnswer).filter_by(session_id=session_id).count() == 0
    assert db.query(QuizSession).filter_by(user_id=alice_id).count() == 0
    assert db.query(WrongAnswer).filter_by(user_id=alice_id).count() == 0
    assert db.query(UserQuestionStat).filter_by(user_id=alice_id).count() == 0
    assert db.query(Vocabulary).filter_by(user_id=alice_id).count() == 0
    # 其他用户的数据不受影响。
    assert db.query(Vocabulary).filter_by(user_id=root.id).count() == 1
    assert db.query(User).filter_by(username="root").one() is not None


def test_delete_user_data_reuses_project_cleanup_for_every_exam(ctx):
    """多项目用户一次删除，避免逐个 exam 各自提交留下半删状态。"""
    db = ctx["db"]
    alice = db.query(User).filter_by(username="alice").one()
    for slug in ("a-one", "a-two"):
        db.add(Exam(owner_id=alice.id, slug=slug, name=slug, short_name=slug))
    db.commit()

    delete_user_data(db, alice)

    assert db.query(User).filter_by(username="alice").count() == 0
    assert db.query(Exam).filter_by(owner_id=alice.id).count() == 0


def test_deleting_user_keeps_others_import_records_he_reviewed(ctx):
    """复核人身份不是流水所有权：删掉复核人，别人导入的记录继续存在，只解除署名。"""
    db = ctx["db"]
    alice = db.query(User).filter_by(username="alice").one()
    root = db.query(User).filter_by(username="root").one()

    exam = Exam(owner_id=root.id, slug="root-exam", name="Root", short_name="R")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="Root bank", exam_id=exam.id)
    db.add(bank)
    db.flush()
    job = ImportJob(
        bank_id=bank.id, file_name="f.pdf", file_path="/tmp/f.pdf",
        file_hash="h" * 64, file_type="pdf", created_by=root.id,
    )
    db.add(job)
    db.flush()
    parsed = ImportParsedQuestion(
        import_job_id=job.id, content="q?", options_json=[{"key": "A", "text": "a"}],
    )
    db.add(parsed)
    db.flush()
    review_item = ImportReviewItem(
        import_job_id=job.id, parsed_question_id=parsed.id, reviewer_id=alice.id,
    )
    db.add(review_item)
    db.commit()
    job_id = job.id
    item_id = review_item.id

    delete_user_data(db, alice)

    assert db.query(ImportJob).filter_by(id=job_id).count() == 1
    assert db.query(ImportReviewItem).filter_by(id=item_id).one().reviewer_id is None


def test_deleting_user_removes_his_own_import_records_and_their_background_jobs(ctx):
    """导入流水连带删除：先删流水再删后台任务，否则外键会挡住。"""
    db = ctx["db"]
    alice = db.query(User).filter_by(username="alice").one()

    exam = Exam(owner_id=alice.id, slug="alice-exam", name="Alice", short_name="A")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="Alice bank", exam_id=exam.id)
    db.add(bank)
    db.flush()
    bg = BackgroundJob(
        job_type="question_import_llm", scope_key="import_llm:1",
        payload_json="{}", status="queued", created_by=alice.id,
    )
    db.add(bg)
    db.flush()
    job = ImportJob(
        bank_id=bank.id, file_name="f.pdf", file_path="/tmp/f.pdf",
        file_hash="h" * 64, file_type="pdf", created_by=alice.id,
        background_job_id=bg.id,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    bg_id = bg.id

    delete_user_data(db, alice)

    assert db.query(ImportJob).filter_by(id=job_id).count() == 0
    assert db.query(BackgroundJob).filter_by(id=bg_id).count() == 0
