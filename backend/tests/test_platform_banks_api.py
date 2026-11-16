"""平台题库：管理员维护、发布隔离、目录、个人副本与来源型权限矩阵。

覆盖：
- 管理员可无个人项目地创建来源、维护草稿、发布/下架；普通用户与访客被拒
- 空库、坏题与活动导入拒绝发布；草稿修订在重新发布前不改变目录
- 目录只暴露上架来源的展示字段，不含答案、快照与任务数据
- 选用按项目+来源幂等，返回同一个人题库；不同项目各得独立副本
- 副本正式内容只读：增题、通用 PUT、删题、再导入、考点打标均拒绝
- 专用答案更正、改名改简介、整库删除仍可用；伪造来源/版本写请求被拒
- 删除账号不清平台内容，只解除审计署名

边界：
- 真实 Bearer 身份，只 override 数据库会话与外部模型 HTTP。
- 使用 SQLite 临时库验证 HTTP 契约；并发与事务交错在独立 PG 测试中证明。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    BackgroundJob,
    Exam,
    ImportJob,
    ImportParsedQuestion,
    ImportReviewItem,
    PlatformBank,
    PlatformBankRelease,
    PlatformDraftQuestion,
    Question,
    QuestionBank,
    User,
)

OPTIONS = [
    {"key": "A", "text": "选项 A"},
    {"key": "B", "text": "选项 B"},
    {"key": "C", "text": "选项 C"},
    {"key": "D", "text": "选项 D"},
]
STEM = "下列关于隐私影响评估的说法中，哪一项是正确的？"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def platform_api(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "AI_API_KEY", "")

    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    with sessions() as db:
        admin = User(
            username="admin", email="admin@example.com", password_hash="x", is_admin=True
        )
        alice = User(username="alice", email="alice@example.com", password_hash="x")
        bob = User(username="bob", email="bob@example.com", password_hash="x")
        db.add_all([admin, alice, bob])
        db.flush()
        # 管理员刻意没有个人项目；alice/bob 各有一个项目。
        alice_exam = Exam(owner_id=alice.id, slug="alice", name="Alice", short_name="A")
        bob_exam = Exam(owner_id=bob.id, slug="bob", name="Bob", short_name="B")
        db.add_all([alice_exam, bob_exam])
        db.commit()
        ids = SimpleNamespace(
            admin=admin.id,
            alice=alice.id,
            bob=bob.id,
            alice_exam=alice_exam.id,
            bob_exam=bob_exam.id,
        )

    def get_test_db():
        with sessions() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = get_test_db

    def as_user(user_id: int, slug: str | None = None) -> TestClient:
        headers = {"Authorization": f"Bearer {create_access_token(str(user_id))}"}
        if slug:
            headers["X-Exam-Slug"] = slug
        return TestClient(app, headers=headers)

    yield SimpleNamespace(
        app=app,
        sessions=sessions,
        ids=ids,
        engine=engine,
        as_user=as_user,
        admin=as_user(ids.admin),
        alice=as_user(ids.alice, "alice"),
        bob=as_user(ids.bob, "bob"),
        anonymous=TestClient(app),
    )
    engine.dispose()


def _create_source(api, name="CIPT 平台题库") -> str:
    response = api.admin.post("/api/admin/platform-banks", json={"name": name, "description": "简介"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_draft(api, source_id: str, *, answer="A", stem=STEM) -> int:
    response = api.admin.post(
        f"/api/admin/platform-banks/{source_id}/questions",
        json={
            "question_type": "single",
            "content": stem,
            "options": OPTIONS,
            "correct_answer": answer,
            "source_topics": [{"code": "1.1", "name": "隐私治理"}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _publish(api, source_id: str) -> dict:
    response = api.admin.post(f"/api/admin/platform-banks/{source_id}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def _publish_ready_source(api, name="CIPT 平台题库") -> str:
    source_id = _create_source(api, name=name)
    _add_draft(api, source_id)
    _publish(api, source_id)
    return source_id


# ─── 管理员权限与来源维护 ────────────────────────────────────────


def test_admin_can_manage_without_personal_exam(platform_api):
    api = platform_api
    source_id = _create_source(api)
    listed = api.admin.get("/api/admin/platform-banks")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [source_id]
    # 管理接口不依赖 X-Exam-Slug：管理员没有任何个人项目也能读取。
    assert "X-Exam-Slug" not in api.admin.headers


def test_non_admin_and_anonymous_cannot_manage(platform_api):
    api = platform_api
    source_id = _create_source(api)

    assert api.alice.get("/api/admin/platform-banks").status_code == 403
    assert api.alice.post("/api/admin/platform-banks", json={"name": "x"}).status_code == 403
    assert api.alice.delete(f"/api/admin/platform-banks/{source_id}/questions/1").status_code == 403
    assert api.alice.post(f"/api/admin/platform-banks/{source_id}/publish").status_code == 403

    assert api.anonymous.get("/api/admin/platform-banks").status_code == 401
    assert api.anonymous.post(f"/api/admin/platform-banks/{source_id}/publish").status_code == 401


def test_draft_crud_validates_content(platform_api):
    api = platform_api
    source_id = _create_source(api)

    bad = api.admin.post(
        f"/api/admin/platform-banks/{source_id}/questions",
        json={
            "question_type": "single",
            "content": "短",
            "options": OPTIONS,
            "correct_answer": "A",
        },
    )
    assert bad.status_code == 400

    wrong_answer = api.admin.post(
        f"/api/admin/platform-banks/{source_id}/questions",
        json={
            "question_type": "single",
            "content": STEM,
            "options": OPTIONS,
            "correct_answer": "Z",
        },
    )
    assert wrong_answer.status_code == 400

    draft_id = _add_draft(api, source_id)
    updated = api.admin.put(
        f"/api/admin/platform-banks/{source_id}/questions/{draft_id}",
        json={"content": STEM + "（修订）", "correct_answer": "B"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["correct_answer"] == "B"

    # 草稿题必须按来源定位：跨来源 ID 访问返回 404。
    other_source = _create_source(api, name="另一个来源")
    cross = api.admin.put(
        f"/api/admin/platform-banks/{other_source}/questions/{draft_id}",
        json={"correct_answer": "A"},
    )
    assert cross.status_code == 404

    deleted = api.admin.delete(f"/api/admin/platform-banks/{source_id}/questions/{draft_id}")
    assert deleted.status_code == 200


# ─── 发布隔离 ────────────────────────────────────────────────────


def test_publish_rejects_empty_source(platform_api):
    source_id = _create_source(platform_api)
    response = platform_api.admin.post(f"/api/admin/platform-banks/{source_id}/publish")
    assert response.status_code == 400
    assert "没有可发布" in response.text


def test_publish_rejects_active_import(platform_api):
    api = platform_api
    source_id = _create_source(api)
    _add_draft(api, source_id)

    with api.sessions() as db:
        db.add(
            BackgroundJob(
                job_type="question_import_llm",
                scope_key="platform-import:1",
                active_scope_key="platform-import:1",
                payload_json=json.dumps({"platform_bank_id": source_id}),
                status="running",
                platform_bank_id=source_id,
                created_by=api.ids.admin,
            )
        )
        db.commit()

    response = api.admin.post(f"/api/admin/platform-banks/{source_id}/publish")
    assert response.status_code == 409

    # 草稿写入口同样被活动导入挡住。
    blocked = api.admin.post(
        f"/api/admin/platform-banks/{source_id}/questions",
        json={
            "question_type": "single",
            "content": STEM,
            "options": OPTIONS,
            "correct_answer": "A",
        },
    )
    assert blocked.status_code == 409


def test_draft_edits_do_not_change_published_directory(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)

    first = api.alice.get("/api/platform-banks").json()
    assert first[0]["name"] == "CIPT 平台题库"
    assert first[0]["published_version"] == 1
    assert first[0]["question_count"] == 1

    draft_id = api.admin.get(f"/api/admin/platform-banks/{source_id}/questions").json()["questions"][0]["id"]
    api.admin.put(
        f"/api/admin/platform-banks/{source_id}/questions/{draft_id}",
        json={"content": "草稿已修订的新题干内容，长度足够"},
    )
    api.admin.put(f"/api/admin/platform-banks/{source_id}", json={"name": "改名后"})

    second = api.alice.get("/api/platform-banks").json()
    assert second[0]["name"] == "CIPT 平台题库"
    assert second[0]["published_version"] == 1

    # 重新发布后新用户拿到新版；旧副本不动。
    api.admin.put(
        f"/api/admin/platform-banks/{source_id}/questions/{draft_id}",
        json={"content": "第二版正式题干内容，长度足够"},
    )
    published = _publish(api, source_id)
    assert published["version_number"] == 2

    third = api.bob.get("/api/platform-banks").json()
    assert third[0]["name"] == "改名后"
    assert third[0]["published_version"] == 2


def test_unlisted_source_leaves_directory(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)

    assert api.alice.post(f"/api/admin/platform-banks/{source_id}/unpublish").status_code == 403
    assert api.admin.post(f"/api/admin/platform-banks/{source_id}/unpublish").status_code == 200

    assert api.alice.get("/api/platform-banks").json() == []


# ─── 目录与选用 ──────────────────────────────────────────────────


def test_directory_does_not_leak_answers_or_drafts(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    # 新增一道未发布草稿：目录题量仍是发布版题量。
    _add_draft(api, source_id, stem="未发布的草稿题干内容，长度足够")

    items = api.alice.get("/api/platform-banks").json()
    assert len(items) == 1
    body = json.dumps(items, ensure_ascii=False)
    assert "payload" not in body
    assert "correct_answer" not in body
    assert '"A"' not in body
    assert items[0]["question_count"] == 1
    assert items[0]["adopted_bank_id"] is None


def test_directory_requires_exam_context(platform_api):
    api = platform_api
    _publish_ready_source(api)

    no_context = TestClient(
        api.app,
        headers={"Authorization": f"Bearer {create_access_token(str(api.ids.alice))}"},
    )
    assert no_context.get("/api/platform-banks").status_code == 400
    assert api.anonymous.get("/api/platform-banks").status_code == 401


def test_adopt_is_idempotent_and_creates_full_copy(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)

    first = api.alice.post(f"/api/platform-banks/{source_id}/adopt")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["created"] is True
    assert payload["published_version"] == 1

    second = api.alice.post(f"/api/platform-banks/{source_id}/adopt")
    assert second.status_code == 200
    assert second.json()["bank_id"] == payload["bank_id"]
    assert second.json()["created"] is False

    bank_id = payload["bank_id"]
    detail = api.alice.get(f"/api/banks/{bank_id}").json()
    assert detail["is_platform_copy"] is True
    assert detail["source_platform_bank_id"] == source_id
    assert detail["question_count"] == 1

    questions = api.alice.get(f"/api/questions/banks/{bank_id}/questions").json()["questions"]
    assert len(questions) == 1
    assert questions[0]["content"] == STEM
    assert questions[0]["correct_answer"] == "A"
    assert questions[0]["source_topics"] == [{"code": "1.1", "name": "隐私治理"}]

    directory = api.alice.get("/api/platform-banks").json()
    assert directory[0]["adopted_bank_id"] == bank_id


def test_different_exams_get_independent_copies(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)

    alice_bank = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]
    bob_bank = api.bob.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]
    assert alice_bank != bob_bank

    # 副本使用各自的题目 ID，不共享对象。
    alice_q = api.alice.get(f"/api/questions/banks/{alice_bank}/questions").json()["questions"][0]["id"]
    bob_q = api.bob.get(f"/api/questions/banks/{bob_bank}/questions").json()["questions"][0]["id"]
    assert alice_q != bob_q


def test_adopt_unlisted_source_is_rejected_without_copy(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    api.admin.post(f"/api/admin/platform-banks/{source_id}/unpublish")

    response = api.alice.post(f"/api/platform-banks/{source_id}/adopt")
    assert response.status_code == 409
    assert "下架" in response.text

    with api.sessions() as db:
        assert db.query(QuestionBank).filter_by(exam_id=api.ids.alice_exam).count() == 0


def test_existing_copy_survives_unpublish(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    bank_id = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]

    api.admin.post(f"/api/admin/platform-banks/{source_id}/unpublish")

    again = api.alice.post(f"/api/platform-banks/{source_id}/adopt")
    assert again.status_code == 200
    assert again.json()["bank_id"] == bank_id
    # 个人题库仍然可读可练（下架只阻止新建副本）。
    assert api.alice.get(f"/api/banks/{bank_id}").status_code == 200


def test_adopt_unknown_source_is_404(platform_api):
    api = platform_api
    response = api.alice.post("/api/platform-banks/does-not-exist/adopt")
    assert response.status_code == 404


# ─── 来源型权限矩阵 ──────────────────────────────────────────────


def test_formal_writes_are_rejected_on_platform_copy(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    bank_id = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]
    question = api.alice.get(f"/api/questions/banks/{bank_id}/questions").json()["questions"][0]

    create = api.alice.post(
        "/api/questions",
        json={
            "bank_id": bank_id,
            "question_type": "single",
            "content": STEM,
            "options": OPTIONS,
            "correct_answer": "A",
        },
    )
    assert create.status_code == 403

    generic_put = api.alice.put(
        f"/api/questions/{question['id']}", json={"correct_answer": "B"}
    )
    assert generic_put.status_code == 403

    delete = api.alice.delete(f"/api/questions/{question['id']}")
    assert delete.status_code == 403

    reimport = api.alice.post(
        f"/api/banks/{bank_id}/import",
        files={"file": ("q.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert reimport.status_code == 403

    tagging = api.alice.post(
        "/api/jobs", json={"job_type": "question_topic_tag", "bank_id": bank_id}
    )
    # 非管理员本来就是 403；管理员选用到自己的副本时也必须被拒，见下一断言。
    assert tagging.status_code in (403, 400)


def test_admin_copy_is_also_protected(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)

    # 给管理员一个个人项目，再选用平台题库。
    with api.sessions() as db:
        exam = Exam(owner_id=api.ids.admin, slug="admin", name="Admin", short_name="AD")
        db.add(exam)
        db.commit()
        exam_id = exam.id
    admin_exam = api.as_user(api.ids.admin, "admin")
    bank_id = admin_exam.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]
    question = admin_exam.get(f"/api/questions/banks/{bank_id}/questions").json()["questions"][0]

    assert admin_exam.put(f"/api/questions/{question['id']}", json={"content": "改动"}).status_code == 403
    assert admin_exam.delete(f"/api/questions/{question['id']}").status_code == 403
    tagging = admin_exam.post(
        "/api/jobs", json={"job_type": "question_topic_tag", "bank_id": bank_id}
    )
    assert tagging.status_code == 403

    # 专用入口仍可用。
    corrected = admin_exam.put(
        f"/api/questions/{question['id']}/correct-answer", json={"correct_answer": "B"}
    )
    assert corrected.status_code == 200, corrected.text


def test_answer_correction_only_affects_own_copy(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    alice_bank = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]
    bob_bank = api.bob.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]

    alice_q = api.alice.get(f"/api/questions/banks/{alice_bank}/questions").json()["questions"][0]
    corrected = api.alice.put(
        f"/api/questions/{alice_q['id']}/correct-answer", json={"correct_answer": "B"}
    )
    assert corrected.status_code == 200, corrected.text

    bob_q = api.bob.get(f"/api/questions/banks/{bob_bank}/questions").json()["questions"][0]
    assert bob_q["correct_answer"] == "A"

    with api.sessions() as db:
        draft = db.query(PlatformDraftQuestion).filter_by(platform_bank_id=source_id).one()
        assert draft.correct_answer == "A"
        release = db.query(PlatformBankRelease).filter_by(platform_bank_id=source_id).one()
        assert release.payload[0]["correct_answer"] == "A"


def test_bank_metadata_editable_but_provenance_is_read_only(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    bank_id = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]

    renamed = api.alice.put(f"/api/banks/{bank_id}", json={"name": "我的副本", "description": "自述"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "我的副本"
    assert renamed.json()["source_platform_bank_id"] == source_id

    forged = api.alice.put(
        f"/api/banks/{bank_id}",
        json={"name": "x", "source_platform_bank_id": "forged"},
    )
    assert forged.status_code == 422
    assert "只读" in forged.text


def test_deleting_copy_allows_readopting_latest(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    bank_id = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]

    # 删除后释放唯一键，可以从当时最新版本重新选用。
    # 断言「重新创建且副本完整」，不绑定具体 ID：SQLite 会复用被删行的 rowid。
    assert api.alice.delete(f"/api/banks/{bank_id}").status_code == 200
    again = api.alice.post(f"/api/platform-banks/{source_id}/adopt")
    assert again.status_code == 200
    assert again.json()["created"] is True
    rebuilt = api.alice.get(f"/api/questions/banks/{again.json()['bank_id']}/questions").json()
    assert rebuilt["total"] == 1

    # 下架后不可重新获取。
    assert api.alice.delete(f"/api/banks/{again.json()['bank_id']}").status_code == 200
    api.admin.post(f"/api/admin/platform-banks/{source_id}/unpublish")
    assert api.alice.post(f"/api/platform-banks/{source_id}/adopt").status_code == 409


def test_cross_user_and_cross_exam_ids_do_not_escape(platform_api):
    api = platform_api
    source_id = _publish_ready_source(api)
    alice_bank = api.alice.post(f"/api/platform-banks/{source_id}/adopt").json()["bank_id"]
    alice_q = api.alice.get(f"/api/questions/banks/{alice_bank}/questions").json()["questions"][0]

    assert api.bob.get(f"/api/banks/{alice_bank}").status_code == 404
    assert api.bob.get(f"/api/questions/banks/{alice_bank}/questions").status_code == 404
    assert api.bob.put(
        f"/api/questions/{alice_q['id']}/correct-answer", json={"correct_answer": "B"}
    ).status_code == 404


# ─── 导入结果查询与管理隔离 ──────────────────────────────────────


def test_platform_import_job_results_are_source_scoped(platform_api):
    """管理端可读平台任务结果，但裸 job_id 不能跨来源或跨目标读取。"""
    api = platform_api
    source_id = _create_source(api)
    other_source = _create_source(api, name="另一个来源")

    with api.sessions() as db:
        job = ImportJob(
            bank_id=None,
            platform_bank_id=source_id,
            file_name="platform.pdf",
            file_path="unused",
            file_hash="c" * 64,
            file_type="pdf",
            config_json={"auto_import": True},
            created_by=api.ids.admin,
        )
        db.add(job)
        db.flush()
        parsed = ImportParsedQuestion(
            import_job_id=job.id,
            content=STEM,
            options_json=OPTIONS,
            correct_answer=["A"],
            review_status="auto_accepted",
            import_status="imported",
            inserted_new=True,
        )
        db.add(parsed)
        db.flush()
        db.add(
            ImportReviewItem(
                import_job_id=job.id,
                parsed_question_id=parsed.id,
                review_type="LOW_CONFIDENCE",
                severity="MEDIUM",
                status="pending",
            )
        )
        db.commit()
        job_id, item_id = job.id, db.query(ImportReviewItem).one().id

    base = f"/api/admin/platform-banks/{source_id}/import-jobs/{job_id}"
    assert api.admin.get(base).status_code == 200
    assert len(api.admin.get(f"{base}/chunks").json()["chunks"]) == 0
    parsed_body = api.admin.get(f"{base}/parsed-questions").json()
    assert parsed_body["questions"][0]["inserted_new"] is True
    assert api.admin.get(f"{base}/auto-handled").json()["total"] == 1
    assert len(api.admin.get(f"{base}/review-items").json()["items"]) == 1

    # 换一个来源前缀访问同一个 job：必须 404，而不是读出别人的任务。
    cross = f"/api/admin/platform-banks/{other_source}/import-jobs/{job_id}"
    assert api.admin.get(cross).status_code == 404
    assert api.admin.get(f"{cross}/parsed-questions").status_code == 404
    assert api.admin.post(f"{cross}/review-items/{item_id}/accept").status_code == 404

    # 普通用户不能读管理端的平台任务。
    assert api.alice.get(base).status_code == 403

    # 个人导入任务路由读不到平台任务（INNER JOIN 个人题库天然隔离）。
    assert api.alice.get(f"/api/import-jobs/{job_id}").status_code == 404


# ─── 作者删除不影响平台内容 ──────────────────────────────────────


def test_deleting_admin_keeps_platform_content(tmp_path):
    from app.models import User as UserModel
    from app.services.exam_service import delete_user_data

    engine = create_engine(f"sqlite:///{tmp_path / 'author.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        admin = UserModel(
            username="admin2", email="a2@example.com", password_hash="x", is_admin=True
        )
        db.add(admin)
        db.flush()
        bank = PlatformBank(id="source-1", name="平台库", created_by=admin.id)
        db.add(bank)
        db.flush()
        db.add(
            PlatformBankRelease(
                id="release-1",
                platform_bank_id="source-1",
                version_number=1,
                name="平台库",
                question_count=0,
                payload=[],
                created_by=admin.id,
            )
        )
        db.add(
            BackgroundJob(
                job_type="question_import_llm",
                scope_key="platform:1",
                payload_json="{}",
                status="queued",
                platform_bank_id="source-1",
                created_by=admin.id,
            )
        )
        db.commit()

        delete_user_data(db, db.get(UserModel, admin.id))

    with sessions() as db:
        assert db.get(PlatformBank, "source-1") is not None
        assert db.get(PlatformBankRelease, "release-1") is not None
        job = db.query(BackgroundJob).filter_by(platform_bank_id="source-1").one()
        assert job.created_by is None
        assert db.get(PlatformBank, "source-1").created_by is None
    engine.dispose()
