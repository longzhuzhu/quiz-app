"""平台题库导入：只写草稿、真实新增计数、reparse fail-closed 与来源隔离。

覆盖：
- 平台导入任务写入 PlatformDraftQuestion，不写任何个人 Question / QuestionBank
- `inserted_new` 作为「确实新增过」的历史证据，草稿题被删后仍计数
- 同一文件重复导入按题面签名跳过，不重复计新增
- 删除草稿题后该 chunk 的 reparse 在入队与执行两处都 fail-closed
- 个人导入路径行为不变（仍然写 Question）

边界：
- 推理全部打桩，不发真实模型请求。
- 使用隔离 PostgreSQL，验证真实事务与唯一约束。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT_SKIP = None
from app.core.database import Base  # noqa: E402
from app.models import Exam, Question, QuestionBank, User  # noqa: E402
from app.models.background_job import BackgroundJob  # noqa: E402
from app.models.import_chunk import ImportChunk  # noqa: E402
from app.models.import_job import ImportJob  # noqa: E402
from app.models.import_parsed_question import ImportParsedQuestion  # noqa: E402
from app.models.platform_bank import PlatformBank, PlatformDraftQuestion  # noqa: E402
from app.services import smart_import_service as svc  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402

QUESTION_TEXT = "Which privacy principle applies to situation {n}?"


@pytest.fixture(scope="module")
def sessions():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine)


def _llm_response(count: int = 2) -> str:
    return json.dumps(
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
                for n in range(1, count + 1)
            ]
        }
    )


def _patch_llm(monkeypatch, response: str | None = None) -> Mock:
    text = "\n".join(
        f"Question #{n}\n{QUESTION_TEXT.format(n=n)}\nA. first option text\n"
        "B. second option text\nAnswer: A"
        for n in (1, 2)
    )
    monkeypatch.setattr(svc, "_source_file_hash", lambda *_: "a" * 64)
    monkeypatch.setattr(svc, "_extract_pages_from_file", lambda *_: [{"text": text, "page": 1}])
    model = Mock(return_value=response or _llm_response())
    monkeypatch.setattr(svc, "call_ai_api", model)
    return model


@pytest.fixture
def platform_case(sessions, monkeypatch):
    db = sessions()
    suffix = uuid.uuid4().hex
    user = User(username=f"p-{suffix}", email=f"p-{suffix}@invalid.test", password_hash="unused")
    db.add(user)
    db.flush()
    source = PlatformBank(name="平台导入来源", created_by=user.id)
    db.add(source)
    db.commit()

    job = ImportJob(
        bank_id=None,
        platform_bank_id=source.id,
        file_name="platform.pdf",
        file_path="unused",
        file_hash="a" * 64,
        file_type="pdf",
        config_json={"auto_import": True},
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    bg = BackgroundJob(
        job_type="question_import_llm",
        scope_key=f"platform:{suffix}",
        payload_json=json.dumps(
            {
                "import_job_id": job.id,
                "platform_bank_id": source.id,
                "file_path": "unused",
                "file_type": "pdf",
                "use_llm_cache": False,
            }
        ),
        status="queued",
        platform_bank_id=source.id,
        created_by=user.id,
    )
    db.add(bg)
    db.flush()
    job.background_job_id = bg.id
    db.commit()

    from app.services.job_service import try_claim_job_by_id

    bg = try_claim_job_by_id(db, bg.id, worker_id="platform-test")
    try:
        yield db, bg, job, source, user
    finally:
        # 一个 Session 只能拥有一个不可变领取上下文；用例之间必须显式释放。
        from app.services.import_execution import release_import_execution

        try:
            release_import_execution(db, bg)
        except Exception:
            pass
        db.rollback()
        db.close()


def _draft_count(db, source_id: str) -> int:
    return db.query(PlatformDraftQuestion).filter_by(platform_bank_id=source_id).count()


def test_platform_import_writes_drafts_only(platform_case, monkeypatch):
    db, bg, job, source, _ = platform_case
    _patch_llm(monkeypatch)

    svc.run_smart_import(db, bg)

    assert _draft_count(db, source.id) == 2
    # 平台导入绝不能写任何个人题库/题目。
    assert db.query(QuestionBank).count() == 0
    assert db.query(Question).count() == 0

    parsed = db.query(ImportParsedQuestion).filter_by(import_job_id=job.id).all()
    assert len(parsed) == 2
    for item in parsed:
        assert item.inserted_new is True
        assert item.imported_platform_question_id is not None
        assert item.imported_question_id is None
        assert item.import_status == "imported"

    # 实际新增按 inserted_new 计数，不依赖当前草稿指针。
    serialized = svc.serialize_import_job(job, db)
    assert serialized["actual_inserted_count"] == 2
    assert serialized["draft_question_count"] == 2
    assert serialized["platform_bank_id"] == source.id


def test_inserted_count_survives_manual_draft_deletion(platform_case, monkeypatch):
    db, bg, job, source, _ = platform_case
    _patch_llm(monkeypatch)
    svc.run_smart_import(db, bg)

    draft = (
        db.query(PlatformDraftQuestion)
        .filter_by(platform_bank_id=source.id)
        .order_by(PlatformDraftQuestion.id)
        .first()
    )
    db.delete(draft)
    db.commit()

    # 指针被 SET NULL，但历史新增证据与审计必须保留。
    db.expire_all()
    assert _draft_count(db, source.id) == 1
    serialized = svc.serialize_import_job(job, db)
    assert serialized["actual_inserted_count"] == 2
    assert serialized["draft_question_count"] == 1


def test_reparse_fails_closed_after_manual_deletion(platform_case, monkeypatch):
    db, bg, job, source, user = platform_case
    _patch_llm(monkeypatch)
    svc.run_smart_import(db, bg)

    draft = (
        db.query(PlatformDraftQuestion)
        .filter_by(platform_bank_id=source.id)
        .order_by(PlatformDraftQuestion.id)
        .first()
    )
    db.delete(draft)
    db.commit()

    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()

    # 入队即拒绝。
    result = svc.create_reparse_job(db, job.id, chunk.id, user.id)
    assert "error" in result
    assert "追加导入" in result["error"]

    # 执行处也必须拒绝（覆盖绕过入口或旧数据）。
    from app.services.job_service import try_claim_job_by_id

    reparse_bg = BackgroundJob(
        job_type="question_import_llm_reparse",
        scope_key=f"reparse:{chunk.id}:{uuid.uuid4().hex}",
        payload_json=json.dumps(
            {
                "import_job_id": job.id,
                "chunk_id": chunk.id,
                "platform_bank_id": source.id,
            }
        ),
        status="queued",
        platform_bank_id=source.id,
        created_by=user.id,
    )
    db.add(reparse_bg)
    db.commit()
    from app.services.import_execution import release_import_execution

    # 主导入的执行上下文必须先释放，同一 Session 才能领取新的重解析请求。
    release_import_execution(db, bg)
    claimed = try_claim_job_by_id(db, reparse_bg.id, worker_id="platform-reparse")
    assert claimed is not None

    with pytest.raises(Exception) as excinfo:
        svc.run_reparse(db, claimed)
    assert "追加导入" in str(excinfo.value)

    # 被手工删除的题不能被复活，新增计数也不能重复。
    assert _draft_count(db, source.id) == 1
    assert svc.serialize_import_job(job, db)["actual_inserted_count"] == 2


def test_platform_import_dedups_same_content(platform_case, monkeypatch):
    db, bg, job, source, _ = platform_case
    _patch_llm(monkeypatch)
    svc.run_smart_import(db, bg)
    assert _draft_count(db, source.id) == 2

    # 同一份内容再导入：命中草稿签名，记为跳过，不重复写。
    second = ImportJob(
        bank_id=None,
        platform_bank_id=source.id,
        file_name="platform.pdf",
        file_path="unused",
        file_hash="a" * 64,
        file_type="pdf",
        config_json={"auto_import": True},
        created_by=job.created_by,
    )
    db.add(second)
    db.flush()
    bg2 = BackgroundJob(
        job_type="question_import_llm",
        scope_key=f"platform2:{uuid.uuid4().hex}",
        payload_json=json.dumps(
            {
                "import_job_id": second.id,
                "platform_bank_id": source.id,
                "file_path": "unused",
                "file_type": "pdf",
                "use_llm_cache": False,
            }
        ),
        status="queued",
        platform_bank_id=source.id,
        created_by=job.created_by,
    )
    db.add(bg2)
    db.flush()
    second.background_job_id = bg2.id
    db.commit()
    from app.services.job_service import try_claim_job_by_id

    from app.services.import_execution import release_import_execution

    release_import_execution(db, bg)
    claimed = try_claim_job_by_id(db, bg2.id, worker_id="platform-test-2")
    assert claimed is not None
    _patch_llm(monkeypatch)
    svc.run_smart_import(db, claimed)

    assert _draft_count(db, source.id) == 2
    assert svc.serialize_import_job(second, db)["actual_inserted_count"] == 0


def test_personal_import_still_writes_questions(sessions, monkeypatch):
    """回归：个人导入路径不受双目标改造影响。"""
    db = sessions()
    suffix = uuid.uuid4().hex
    user = User(username=f"u-{suffix}", email=f"u-{suffix}@invalid.test", password_hash="unused")
    db.add(user)
    db.flush()
    exam = Exam(owner_id=user.id, slug=suffix, name="Test", short_name="T")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="个人库", exam_id=exam.id)
    db.add(bank)
    db.flush()
    job = ImportJob(
        bank_id=bank.id,
        file_name="p.pdf",
        file_path="unused",
        file_hash="a" * 64,
        file_type="pdf",
        config_json={"auto_import": True},
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    bg = BackgroundJob(
        job_type="question_import_llm",
        scope_key=f"p:{suffix}",
        payload_json=json.dumps(
            {
                "import_job_id": job.id,
                "bank_id": bank.id,
                "file_path": "unused",
                "file_type": "pdf",
                "use_llm_cache": False,
            }
        ),
        status="queued",
        created_by=user.id,
    )
    db.add(bg)
    db.flush()
    job.background_job_id = bg.id
    db.commit()
    from app.services.job_service import try_claim_job_by_id

    claimed = try_claim_job_by_id(db, bg.id, worker_id="personal-test")
    _patch_llm(monkeypatch)
    try:
        svc.run_smart_import(db, claimed)
        assert db.query(Question).filter_by(bank_id=bank.id).count() == 2
        parsed = db.query(ImportParsedQuestion).filter_by(import_job_id=job.id).all()
        assert all(item.imported_question_id is not None for item in parsed)
        # 个人任务的行保持 inserted_new=False，不改变原统计路径。
        assert all(item.inserted_new is False for item in parsed)
    finally:
        db.rollback()
        db.close()
