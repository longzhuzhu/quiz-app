"""worker 领取任务时的时间比较回归。

背景：``background_jobs`` 的时间列是无时区的 ``DateTime``，而领取条件用带时区的
``utc_now()`` 参与比较。SQLAlchemy 的 ORM UPDATE 默认做 ``evaluate`` 会话同步，
会对 session 中已加载的对象在 Python 端求值 —— 把数据库读回的 naive 值与 aware 值
相比，抛 ``TypeError: can't compare offset-naive and offset-aware datetimes``。

该缺陷只在队列头部存在 ``next_run_at`` 非空（即重试过一次）的任务时触发：
``next_run_at IS NULL`` 会短路求值，掩盖问题。曾导致 worker 反复崩溃重启，
后台解析与翻译任务完全无法执行。

覆盖路径：
    TC-1  队首是 next_run_at 已到期的重试任务时，领取不抛异常并正确改为 running。
    TC-2  队首是 next_run_at 未到期的重试任务时，不领取，保持 queued。
    TC-3  解析任务领取后租约使用延长值，非解析任务仍用默认租约。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base  # noqa: E402
from app.models import Exam, User  # noqa: E402
from app.models.background_job import BackgroundJob  # noqa: E402
from app.services import job_service  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402


@pytest.fixture(scope="module")
def postgres():
    """naive/aware 比较是驱动层行为，必须用真实 PostgreSQL，SQLite 会掩盖该缺陷。"""
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def sessions(postgres):
    return sessionmaker(bind=postgres)


def _seed_owner(db) -> int:
    """复用同一 owner；模块级数据库在用例间不重建，重复插入会违反唯一约束。"""
    user = db.query(User).filter_by(username="worker-owner").first()
    if user is None:
        user = User(username="worker-owner", email="worker@example.invalid", password_hash="unused")
        db.add(user)
        db.flush()
    if db.query(Exam).filter_by(slug="worker").first() is None:
        db.add(Exam(owner_id=user.id, slug="worker", name="Worker", short_name="Worker"))
        db.flush()
    return user.id


def _queued_job(
    db,
    owner_id: int,
    *,
    job_type: str,
    scope_key: str,
    next_run_at: datetime | None,
    attempt_count: int = 1,
) -> int:
    job = BackgroundJob(
        job_type=job_type,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json="{}",
        status="queued",
        attempt_count=attempt_count,
        max_attempts=3,
        progress_total=1,
        created_by=owner_id,
        next_run_at=next_run_at,
    )
    db.add(job)
    db.commit()
    return job.id


# ─── TC-1 ────────────────────────────────────────────────────────────


def test_claim_succeeds_when_retried_job_is_due(sessions):
    """队首为已到期的重试任务时领取成功。

    回归点：该场景此前抛 TypeError，导致 worker 崩溃循环。
    """
    with sessions() as db:
        owner_id = _seed_owner(db)
        job_id = _queued_job(
            db, owner_id,
            job_type=job_service.JOB_TYPE_BANK_FREQUENT_TRANSLATE,
            scope_key="bank_frequent:1",
            next_run_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30),
        )

        claimed = job_service.claim_next_job(db, worker_id="regression-worker")

        assert claimed is not None, "已到期的重试任务应能被领取"
        assert claimed.id == job_id
        assert claimed.status == "running"
        assert claimed.attempt_count == 2
        assert claimed.next_run_at is None


# ─── TC-2 ────────────────────────────────────────────────────────────


def test_claim_skips_retried_job_that_is_not_due_yet(sessions):
    """队首为尚未到期的重试任务时保持 queued，不提前领取。"""
    with sessions() as db:
        owner_id = _seed_owner(db)
        job_id = _queued_job(
            db, owner_id,
            job_type=job_service.JOB_TYPE_BANK_FREQUENT_TRANSLATE,
            scope_key="bank_frequent:2",
            next_run_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        )

        claimed = job_service.claim_next_job(db, worker_id="regression-worker")

        assert claimed is None, "未到期的重试任务不应被领取"
        assert db.get(BackgroundJob, job_id).status == "queued"


# ─── TC-3 ────────────────────────────────────────────────────────────


def test_explanation_job_gets_extended_lease(sessions):
    """解析任务领取时使用延长租约，覆盖两次模型调用的最坏耗时。"""
    with sessions() as db:
        owner_id = _seed_owner(db)
        job_id = _queued_job(
            db, owner_id,
            job_type=job_service.JOB_TYPE_AI_EXPLANATION,
            scope_key="explain:1:1:abc:def",
            next_run_at=None,
            attempt_count=0,
        )

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        claimed = job_service.claim_next_job(db, worker_id="regression-worker")

        assert claimed is not None and claimed.id == job_id
        assert claimed.lease_until is not None
        lease_seconds = (claimed.lease_until - before).total_seconds()
        assert lease_seconds > job_service.DEFAULT_JOB_LEASE_SECONDS, (
            f"解析任务租约 {lease_seconds}s 未超过默认 {job_service.DEFAULT_JOB_LEASE_SECONDS}s"
        )
        assert lease_seconds >= job_service.EXPLANATION_JOB_LEASE_SECONDS - 5
