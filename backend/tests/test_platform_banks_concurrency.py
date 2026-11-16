"""平台题库并发与事务完整性：真实 PostgreSQL，不用 SQLite。

覆盖：
- 同一项目并发两次选用只产生一份完整副本，两个响应拿到同一个人题库 ID
- 复制中途写入失败时整库回滚，不残留空库或半套题
- 发布与下架交错时副本永远来自单个完整发布版本，不会混版
- 下架提交后新建副本请求被拒绝，且目录数据过期不会造成假成功
- 发布与活动导入交错：有活动写者时拒绝发布

边界：
- 只断言外部可观察状态（HTTP 响应、库内行数与内容），不锁内部函数调用顺序。
- 使用隔离 PostgreSQL 实例，不连接业务配置数据库。
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    BackgroundJob,
    Exam,
    PlatformBank,
    PlatformBankRelease,
    PlatformDraftQuestion,
    Question,
    QuestionBank,
    User,
)
from postgres_support import isolated_postgres  # noqa: E402

OPTIONS = [
    {"key": "A", "text": "选项 A"},
    {"key": "B", "text": "选项 B"},
    {"key": "C", "text": "选项 C"},
]


@pytest.fixture(scope="module")
def postgres():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


def _seed(engine, *, slug: str) -> dict:
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(
            username=f"u-{slug}", email=f"{slug}@example.invalid", password_hash="unused"
        )
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug=slug, name=slug, short_name=slug.upper())
        db.add(exam)
        db.flush()
        source = PlatformBank(name=f"来源-{slug}", is_listed=False)
        db.add(source)
        db.flush()
        draft = PlatformDraftQuestion(
            platform_bank_id=source.id,
            question_type="single",
            content="这是一道足够长的平台题库并发测试题干",
            options=OPTIONS,
            correct_answer="A",
            order_index=0,
        )
        db.add(draft)
        db.commit()
        return {"user_id": user.id, "exam_id": exam.id, "source_id": source.id, "slug": slug}


def _client(engine, seed: dict, *, raise_server_exceptions: bool = True) -> TestClient:
    sessions = sessionmaker(bind=engine)

    def database():
        with sessions() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = database
    return TestClient(
        app,
        headers={
            "Authorization": f"Bearer {create_access_token(str(seed['user_id']))}",
            "X-Exam-Slug": seed["slug"],
        },
        raise_server_exceptions=raise_server_exceptions,
    )


def _admin_client(engine, seed: dict) -> TestClient:
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = db.get(User, seed["user_id"])
        user.is_admin = True
        db.commit()

    def database():
        with sessions() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = database
    return TestClient(
        app,
        headers={
            "Authorization": f"Bearer {create_access_token(str(seed['user_id']))}",
            "X-Exam-Slug": seed["slug"],
        },
    )


def _publish(admin: TestClient, source_id: str) -> dict:
    response = admin.post(f"/api/admin/platform-banks/{source_id}/publish")
    assert response.status_code == 200, response.text
    return response.json()


# ─── 并发选用 ────────────────────────────────────────────────────


def test_concurrent_adopt_creates_exactly_one_copy(postgres):
    seed = _seed(postgres, slug="concurrent-adopt")
    admin = _admin_client(postgres, seed)
    _publish(admin, seed["source_id"])

    sessions = sessionmaker(bind=postgres)
    barrier = Barrier(2)

    def adopt(_):
        client = _client(postgres, seed)
        barrier.wait(timeout=15)
        # 每线程独立 client，避免共享 TestClient 的 cookie/连接状态
        # 每线程独立 client，避免共享 TestClient 的连接状态
        return client.post(f"/api/platform-banks/{seed['source_id']}/adopt")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(adopt, range(2)))

    for response in responses:
        assert response.status_code == 200, response.text

    bank_ids = {response.json()["bank_id"] for response in responses}
    assert len(bank_ids) == 1, f"并发选用产生了多份副本: {bank_ids}"
    created_flags = [response.json()["created"] for response in responses]
    assert created_flags.count(True) == 1, f"应恰好一次创建: {created_flags}"

    with sessions() as db:
        copies = (
            db.query(QuestionBank)
            .filter_by(exam_id=seed["exam_id"], source_platform_bank_id=seed["source_id"])
            .all()
        )
        assert len(copies) == 1
        questions = db.query(Question).filter_by(bank_id=copies[0].id).all()
        assert len(questions) == 1
        assert copies[0].question_count == 1


def test_copy_failure_leaves_no_partial_bank(postgres, monkeypatch):
    seed = _seed(postgres, slug="copy-failure")
    admin = _admin_client(postgres, seed)
    _publish(admin, seed["source_id"])

    from app.services import platform_bank_service

    def boom(*args, **kwargs):
        raise RuntimeError("模拟复制中途失败")

    # 让注入的失败以 500 响应返回，而不是在测试进程内重新抛出。
    client = _client(postgres, seed, raise_server_exceptions=False)
    monkeypatch.setattr(platform_bank_service, "_copy_questions", boom)

    response = client.post(f"/api/platform-banks/{seed['source_id']}/adopt")
    assert response.status_code >= 500, response.text

    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        copies = db.query(QuestionBank).filter_by(exam_id=seed["exam_id"]).all()
        assert copies == [], "复制失败却留下了空库或半套题"
        # 唯一键未被永久占用：失败后可重试成功。
    monkeypatch.undo()
    retry = client.post(f"/api/platform-banks/{seed['source_id']}/adopt")
    assert retry.status_code == 200, retry.text


# ─── 发布 / 下架交错 ────────────────────────────────────────────


def test_copy_always_matches_a_single_release(postgres):
    seed = _seed(postgres, slug="release-interleave")
    admin = _admin_client(postgres, seed)
    _publish(admin, seed["source_id"])
    client = _client(postgres, seed)

    # 并发：用户选用 vs 管理员重新发布（改题干）
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        draft = db.query(PlatformDraftQuestion).filter_by(
            platform_bank_id=seed["source_id"]
        ).one()
        draft.content = "第二版题干内容，长度足够用于并发验证"
        db.commit()

    barrier = Barrier(2)

    def adopt():
        barrier.wait(timeout=15)
        return _client(postgres, seed).post(f"/api/platform-banks/{seed['source_id']}/adopt")

    def publish():
        barrier.wait(timeout=15)
        return _admin_client(postgres, seed).post(
            f"/api/admin/platform-banks/{seed['source_id']}/publish"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        adopt_future = pool.submit(adopt)
        publish_future = pool.submit(publish)
        adopt_response = adopt_future.result()
        publish_response = publish_future.result()

    assert publish_response.status_code == 200, publish_response.text
    assert adopt_response.status_code == 200, adopt_response.text

    with sessions() as db:
        copy = (
            db.query(QuestionBank)
            .filter_by(exam_id=seed["exam_id"], source_platform_bank_id=seed["source_id"])
            .one()
        )
        questions = db.query(Question).filter_by(bank_id=copy.id).all()
        assert len(questions) == 1

        releases = {
            release.id: release
            for release in db.query(PlatformBankRelease)
            .filter_by(platform_bank_id=seed["source_id"])
            .all()
        }
        used = releases[copy.source_platform_release_id]
        # 副本内容必须与它声明的那一个版本完全一致，不能混版。
        assert questions[0].content == used.payload[0]["content"]
        assert copy.question_count == len(used.payload)


def test_unpublish_blocks_new_copies_after_commit(postgres):
    seed = _seed(postgres, slug="unpublish-race")
    admin = _admin_client(postgres, seed)
    _publish(admin, seed["source_id"])

    # 目录先读到「上架」，随后管理员下架；过期目录数据不能造成假成功。
    # 本模块共用同一个 PG 实例，目录里可能有其他用例的来源，按 ID 查找。
    client = _client(postgres, seed)
    directory_ids = {item["id"] for item in client.get("/api/platform-banks").json()}
    assert seed["source_id"] in directory_ids

    assert admin.post(f"/api/admin/platform-banks/{seed['source_id']}/unpublish").status_code == 200

    response = client.post(f"/api/platform-banks/{seed['source_id']}/adopt")
    assert response.status_code == 409

    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        assert (
            db.query(QuestionBank)
            .filter_by(exam_id=seed["exam_id"], source_platform_bank_id=seed["source_id"])
            .count()
            == 0
        )


def test_publish_waits_for_active_import(postgres):
    seed = _seed(postgres, slug="publish-import-race")
    admin = _admin_client(postgres, seed)

    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        db.add(
            BackgroundJob(
                job_type="question_import_llm",
                scope_key=f"platform:{seed['source_id']}",
                active_scope_key=f"platform:{seed['source_id']}",
                payload_json=json.dumps({"platform_bank_id": seed["source_id"]}),
                status="running",
                platform_bank_id=seed["source_id"],
                created_by=seed["user_id"],
            )
        )
        db.commit()

    blocked = admin.post(f"/api/admin/platform-banks/{seed['source_id']}/publish")
    assert blocked.status_code == 409

    # 导入结束后可以正常发布。
    with sessions() as db:
        db.query(BackgroundJob).filter_by(platform_bank_id=seed["source_id"]).update(
            {BackgroundJob.status: "completed", BackgroundJob.active_scope_key: None}
        )
        db.commit()
    allowed = admin.post(f"/api/admin/platform-banks/{seed['source_id']}/publish")
    assert allowed.status_code == 200, allowed.text


def test_adopt_does_not_write_to_source_tables(postgres):
    """选用只读来源：副本创建不得修改草稿、发布快照或上架状态。"""
    seed = _seed(postgres, slug="adopt-read-only")
    admin = _admin_client(postgres, seed)
    published = _publish(admin, seed["source_id"])

    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        before_draft = db.query(PlatformDraftQuestion).filter_by(
            platform_bank_id=seed["source_id"]
        ).one().content
        before_release = db.query(PlatformBankRelease).filter_by(
            platform_bank_id=seed["source_id"]
        ).one().payload

    response = _client(postgres, seed).post(f"/api/platform-banks/{seed['source_id']}/adopt")
    assert response.status_code == 200, response.text

    with sessions() as db:
        after_draft = db.query(PlatformDraftQuestion).filter_by(
            platform_bank_id=seed["source_id"]
        ).one().content
        after_release = db.query(PlatformBankRelease).filter_by(
            platform_bank_id=seed["source_id"]
        ).one().payload
        source = db.get(PlatformBank, seed["source_id"])
        assert after_draft == before_draft
        assert after_release == before_release
        assert source.is_listed is True
        assert response.json()["published_version"] == published["version_number"]
