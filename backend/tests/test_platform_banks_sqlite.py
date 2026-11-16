"""平台题库在文件型 SQLite 部署上的导入、发布与选用。

覆盖：
- 平台导入在 SQLite 上只写草稿，且来源锁走 BEGIN IMMEDIATE 而非 FOR UPDATE
- 真实 schema（经 Alembic 升级，不是 create_all）上的组合外键与唯一约束可用
- 发布 + 选用在 SQLite 上产出完整副本
- 手工删除草稿后的 reparse fail-closed 在 SQLite 上同样生效

边界：
- 使用绝对路径临时文件库，不用内存库代替部署证明。
- 迁移通过显式 -x url= 子进程执行，不读取 backend/.env 的业务库。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

QUESTION_TEXT = "Which privacy principle applies to situation {n}?"


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "AI_API_KEY": "",
        "JWT_SECRET_KEY": "platform-sqlite-test",
        "SECRET_KEY": "platform-sqlite-test",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture
def sqlite_engine(tmp_path):
    """真实迁移后的文件型 SQLite engine"""
    database = tmp_path / "platform.db"
    url = f"sqlite:///{database}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    from app.core.database import create_db_engine

    engine = create_db_engine(url)
    yield engine, url
    engine.dispose()


def _patch_llm(monkeypatch):
    from app.services import smart_import_service as svc

    text = "\n".join(
        f"Question #{n}\n{QUESTION_TEXT.format(n=n)}\nA. first option text\n"
        "B. second option text\nAnswer: A"
        for n in (1, 2)
    )
    monkeypatch.setattr(svc, "_source_file_hash", lambda *_: "b" * 64)
    monkeypatch.setattr(svc, "_extract_pages_from_file", lambda *_: [{"text": text, "page": 1}])
    response = json.dumps(
        {
            "questions": [
                {
                    "source_question_no": str(n),
                    "question_type": "single",
                    "content": QUESTION_TEXT.format(n=n),
                    "options": [
                        {"label": "A", "text": "first option text"},
                        {"label": "B", "text": "second option text"},
                    ],
                    "correct_answer": ["A"],
                    "confidence": 0.99,
                }
                for n in (1, 2)
            ]
        }
    )
    monkeypatch.setattr(svc, "call_ai_api", Mock(return_value=response))


def test_platform_import_publish_adopt_on_sqlite(sqlite_engine, monkeypatch):
    engine, _ = sqlite_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Exam, Question, QuestionBank, User
    from app.models.background_job import BackgroundJob
    from app.models.import_job import ImportJob
    from app.models.platform_bank import PlatformBank, PlatformDraftQuestion
    from app.services import platform_bank_service as service
    from app.services import smart_import_service as svc
    from app.services.job_service import try_claim_job_by_id

    # 用写会话工厂（SQLite 需要 BEGIN IMMEDIATE）
    from app.core.database import write_sessionmaker

    sessions = write_sessionmaker(engine)
    suffix = uuid.uuid4().hex

    with sessions() as db:
        admin = User(
            username=f"a-{suffix}", email=f"a-{suffix}@invalid.test", password_hash="x", is_admin=True
        )
        db.add(admin)
        db.flush()
        learner = User(username=f"l-{suffix}", email=f"l-{suffix}@invalid.test", password_hash="x")
        db.add(learner)
        db.flush()
        exam = Exam(owner_id=learner.id, slug=suffix, name="L", short_name="L")
        db.add(exam)
        source = PlatformBank(name="SQLite 平台库", created_by=admin.id)
        db.add(source)
        db.commit()
        admin_id, learner_id, exam_id, source_id = admin.id, learner.id, exam.id, source.id

    _patch_llm(monkeypatch)

    with sessions() as db:
        job = ImportJob(
            bank_id=None,
            platform_bank_id=source_id,
            file_name="platform.pdf",
            file_path="unused",
            file_hash="b" * 64,
            file_type="pdf",
            config_json={"auto_import": True},
            created_by=admin_id,
        )
        db.add(job)
        db.flush()
        bg = BackgroundJob(
            job_type="question_import_llm",
            scope_key=f"platform-sqlite:{suffix}",
            payload_json=json.dumps(
                {
                    "import_job_id": job.id,
                    "platform_bank_id": source_id,
                    "file_path": "unused",
                    "file_type": "pdf",
                    "use_llm_cache": False,
                }
            ),
            status="queued",
            platform_bank_id=source_id,
            created_by=admin_id,
        )
        db.add(bg)
        db.flush()
        job.background_job_id = bg.id
        db.commit()
        bg_id = bg.id

    with sessions() as db:
        claimed = try_claim_job_by_id(db, bg_id, worker_id="sqlite-worker")
        assert claimed is not None
        svc.run_smart_import(db, claimed)

        assert db.query(PlatformDraftQuestion).filter_by(platform_bank_id=source_id).count() == 2
        assert db.query(Question).count() == 0
        assert db.query(QuestionBank).count() == 0

    # 真实部署里 worker 会在收尾后把请求置为终态；这里补上，
    # 否则发布会被「仍有活动写者」正确挡住。
    with sessions() as db:
        db.query(BackgroundJob).filter_by(id=bg_id).update(
            {BackgroundJob.status: "completed", BackgroundJob.active_scope_key: None}
        )
        db.commit()

    # 发布
    with sessions() as db:
        release = service.publish_platform_bank(db, source_id, admin_id)
        db.commit()
        assert release.question_count == 2
        assert release.version_number == 1

    # 选用
    with sessions() as db:
        exam = db.get(Exam, exam_id)
        bank, used_release, created = service.adopt_platform_bank(
            db, exam, source_id, learner_id
        )
        db.commit()
        assert created is True
        assert used_release.version_number == 1
        assert bank.question_count == 2
        copies = (
            db.query(QuestionBank)
            .filter_by(exam_id=exam_id, source_platform_bank_id=source_id)
            .all()
        )
        assert len(copies) == 1
        questions = db.query(Question).filter_by(bank_id=bank.id).order_by(Question.order_index).all()
        assert [q.order_index for q in questions] == [0, 1]
        assert [q.content for q in questions] == [
            QUESTION_TEXT.format(n=1),
            QUESTION_TEXT.format(n=2),
        ]

        # 再选一次返回同一份副本，不新建。
        again, _, created_again = service.adopt_platform_bank(db, exam, source_id, learner_id)
        db.commit()
        assert created_again is False
        assert again.id == bank.id


def test_reparse_fail_closed_on_sqlite(sqlite_engine, monkeypatch):
    engine, _ = sqlite_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import write_sessionmaker
    from app.models import User, Exam, QuestionBank  # noqa: F401
    from app.models.import_chunk import ImportChunk
    from app.models.background_job import BackgroundJob
    from app.models.import_job import ImportJob
    from app.models.platform_bank import PlatformBank, PlatformDraftQuestion
    from app.services import smart_import_service as svc
    from app.services.import_execution import release_import_execution
    from app.services.job_service import try_claim_job_by_id

    sessions = write_sessionmaker(engine)
    suffix = uuid.uuid4().hex
    with sessions() as db:
        admin = User(
            username=f"r-{suffix}", email=f"r-{suffix}@invalid.test", password_hash="x", is_admin=True
        )
        db.add(admin)
        db.flush()
        source = PlatformBank(name="SQLite 删除重解析", created_by=admin.id)
        db.add(source)
        db.commit()
        admin_id, source_id = admin.id, source.id

    _patch_llm(monkeypatch)
    with sessions() as db:
        job = ImportJob(
            bank_id=None,
            platform_bank_id=source_id,
            file_name="p.pdf",
            file_path="unused",
            file_hash="b" * 64,
            file_type="pdf",
            config_json={"auto_import": True},
            created_by=admin_id,
        )
        db.add(job)
        db.flush()
        bg = BackgroundJob(
            job_type="question_import_llm",
            scope_key=f"sqlite-fail-closed:{suffix}",
            payload_json=json.dumps(
                {
                    "import_job_id": job.id,
                    "platform_bank_id": source_id,
                    "file_path": "unused",
                    "file_type": "pdf",
                    "use_llm_cache": False,
                }
            ),
            status="queued",
            platform_bank_id=source_id,
            created_by=admin_id,
        )
        db.add(bg)
        db.flush()
        job.background_job_id = bg.id
        db.commit()
        job_id, bg_id = job.id, bg.id

    with sessions() as db:
        claimed = try_claim_job_by_id(db, bg_id, worker_id="sqlite-w")
        svc.run_smart_import(db, claimed)
        release_import_execution(db, claimed)

        draft = (
            db.query(PlatformDraftQuestion)
            .filter_by(platform_bank_id=source_id)
            .order_by(PlatformDraftQuestion.id)
            .first()
        )
        db.delete(draft)
        db.commit()

    with sessions() as db:
        chunk = db.query(ImportChunk).filter_by(import_job_id=job_id).one()
        result = svc.create_reparse_job(db, job_id, chunk.id, admin_id)
        assert "error" in result
        assert "追加导入" in result["error"]
        assert db.query(PlatformDraftQuestion).filter_by(platform_bank_id=source_id).count() == 1
