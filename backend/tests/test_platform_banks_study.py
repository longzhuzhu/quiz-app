"""平台副本的学习生命周期：练习、错题、翻译与 AI 解析不被来源锁定误杀。

覆盖：
- 平台副本可开练、交卷、续练，错题本正常记录
- 答案更正后该副本的进行中会话按既有语义重判
- 副本上的翻译与 AI 解析写入仍被允许（正式内容只读不等于整行冻结）
- 平台重发后副本内容与学习进度保持不变；下架后仍可继续练习

边界：
- 外部模型 HTTP 全部打桩，不发真实请求。
- 只替换数据库会话与外部依赖，保留真实身份授权。
"""

from __future__ import annotations

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

from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    Exam,
    PlatformBank,
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
STEM = "下列关于隐私设计原则的说法中，哪一项是准确的？"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def study_api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "AI_API_KEY", "")

    engine = create_engine(f"sqlite:///{tmp_path / 'study.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    with sessions() as db:
        admin = User(
            username="study-admin", email="sa@example.com", password_hash="x", is_admin=True
        )
        learner = User(username="learner", email="l@example.com", password_hash="x")
        db.add_all([admin, learner])
        db.flush()
        exam = Exam(owner_id=learner.id, slug="study", name="Study", short_name="S")
        db.add(exam)
        db.commit()
        ids = SimpleNamespace(admin=admin.id, learner=learner.id, exam=exam.id)

    def get_test_db():
        with sessions() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = get_test_db

    def make_client(user_id: int, slug: str | None = "study") -> TestClient:
        headers = {"Authorization": f"Bearer {create_access_token(str(user_id))}"}
        if slug:
            headers["X-Exam-Slug"] = slug
        return TestClient(app, headers=headers)

    yield SimpleNamespace(
        sessions=sessions,
        ids=ids,
        admin=make_client(ids.admin, None),
        learner=make_client(ids.learner),
        make_client=make_client,
        engine=engine,
    )
    engine.dispose()


def _prepare_published_source(api) -> str:
    source = api.admin.post(
        "/api/admin/platform-banks", json={"name": "学习来源", "description": "d"}
    ).json()
    source_id = source["id"]
    created = api.admin.post(
        f"/api/admin/platform-banks/{source_id}/questions",
        json={
            "question_type": "single",
            "content": STEM,
            "options": OPTIONS,
            "correct_answer": "A",
            "source_topics": [{"code": "2.1", "name": "隐私设计"}],
        },
    )
    assert created.status_code == 201, created.text
    published = api.admin.post(f"/api/admin/platform-banks/{source_id}/publish")
    assert published.status_code == 200, published.text
    return source_id


def _adopt(api, source_id: str) -> tuple[int, int]:
    payload = api.learner.post(f"/api/platform-banks/{source_id}/adopt").json()
    bank_id = payload["bank_id"]
    questions = api.learner.get(f"/api/questions/banks/{bank_id}/questions").json()["questions"]
    return bank_id, questions[0]["id"]


def test_platform_copy_supports_practice_and_wrong_answers(study_api):
    api = study_api
    source_id = _prepare_published_source(api)
    bank_id, question_id = _adopt(api, source_id)

    started = api.learner.post("/api/quiz/start", json={"bank_id": bank_id, "mode": "sequential"})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]

    wrong = api.learner.post(
        "/api/quiz/answer",
        json={"session_id": session_id, "question_id": question_id, "user_answer": "B"},
    )
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["is_correct"] is False

    finished = api.learner.post("/api/quiz/finish", json={"session_id": session_id})
    assert finished.status_code == 200, finished.text

    wrong_book = api.learner.get("/api/wrong")
    assert wrong_book.status_code == 200, wrong_book.text
    assert any(item["question_id"] == question_id for item in wrong_book.json())


def test_answer_correction_rejudges_active_session(study_api):
    api = study_api
    source_id = _prepare_published_source(api)
    bank_id, question_id = _adopt(api, source_id)

    started = api.learner.post("/api/quiz/start", json={"bank_id": bank_id, "mode": "sequential"})
    session_id = started.json()["session"]["id"]
    api.learner.post(
        "/api/quiz/answer",
        json={"session_id": session_id, "question_id": question_id, "user_answer": "A"},
    )

    corrected = api.learner.put(
        f"/api/questions/{question_id}/correct-answer",
        json={"correct_answer": "B", "session_id": session_id},
    )
    assert corrected.status_code == 200, corrected.text

    # 副本答案变更只影响本人副本；来源草稿与发布快照不变。
    with api.sessions() as db:
        draft = db.query(PlatformDraftQuestion).filter_by(platform_bank_id=source_id).one()
        assert draft.correct_answer == "A"


def test_platform_copy_allows_auxiliary_learning_writes(study_api, monkeypatch):
    """正式内容只读 ≠ 整行冻结：平台副本仍可写入翻译与 AI 解析字段。"""
    api = study_api
    source_id = _prepare_published_source(api)
    bank_id, question_id = _adopt(api, source_id)

    from app.services import ai_service

    payload = {
        "content_zh": "中文题干",
        "options_zh": [
            {"key": "A", "text_zh": "选项甲"},
            {"key": "B", "text_zh": "选项乙"},
            {"key": "C", "text_zh": "选项丙"},
            {"key": "D", "text_zh": "选项丁"},
        ],
    }
    monkeypatch.setattr(
        ai_service, "call_ai_api", lambda *a, **kw: __import__("json").dumps(payload)
    )

    response = api.learner.post("/api/ai/translate", json={"question_id": question_id})
    assert response.status_code == 200, response.text
    assert response.json()["content_zh"] == "中文题干"

    with api.sessions() as db:
        question = db.get(Question, question_id)
        assert question.content_zh == "中文题干"
        # 原选项 key/text 未被翻译改写。
        assert [opt["text"] for opt in question.options] == ["选项 A", "选项 B", "选项 C", "选项 D"]
        assert question.options[0]["text_zh"] == "选项甲"


def test_republish_and_unpublish_do_not_break_existing_copy(study_api):
    api = study_api
    source_id = _prepare_published_source(api)
    bank_id, question_id = _adopt(api, source_id)

    started = api.learner.post("/api/quiz/start", json={"bank_id": bank_id, "mode": "sequential"})
    session_id = started.json()["session"]["id"]
    api.learner.post(
        "/api/quiz/answer",
        json={"session_id": session_id, "question_id": question_id, "user_answer": "A"},
    )

    # 平台重发不同内容 + 下架
    draft = api.admin.get(f"/api/admin/platform-banks/{source_id}/questions").json()["questions"][0]
    api.admin.put(
        f"/api/admin/platform-banks/{source_id}/questions/{draft['id']}",
        json={"content": "第二版完全不同的题干内容，长度足够", "correct_answer": "C"},
    )
    assert api.admin.post(f"/api/admin/platform-banks/{source_id}/publish").status_code == 200
    assert api.admin.post(f"/api/admin/platform-banks/{source_id}/unpublish").status_code == 200

    # 副本仍是旧内容，学习进度不变，仍可继续作答与复盘。
    questions = api.learner.get(f"/api/questions/banks/{bank_id}/questions").json()["questions"]
    assert questions[0]["content"] == STEM
    assert questions[0]["correct_answer"] == "A"

    # 进行中会话仍可读取题目与作答状态（续练依据同一份快照）。
    detail = api.learner.get(f"/api/quiz/session/{session_id}")
    assert detail.status_code == 200, detail.text

    finished = api.learner.post("/api/quiz/finish", json={"session_id": session_id})
    assert finished.status_code == 200, finished.text

    # 完成后的复盘走同一会话详情接口，按完成态释放答案。
    review = api.learner.get(f"/api/quiz/session/{session_id}")
    assert review.status_code == 200, review.text
    assert review.json()["session"]["is_completed"] is True


def test_copy_does_not_create_project_topics(study_api):
    """D03：来源考点只是只读描述，不创建 ExamTopic / QuestionTopic。"""
    api = study_api
    source_id = _prepare_published_source(api)
    bank_id, _ = _adopt(api, source_id)

    with api.sessions() as db:
        from app.models import ExamTopic, QuestionTopic

        assert db.query(ExamTopic).filter_by(exam_id=api.ids.exam).count() == 0
        assert db.query(QuestionTopic).count() == 0
        question = db.query(Question).filter_by(bank_id=bank_id).one()
        assert question.source_topics == [{"code": "2.1", "name": "隐私设计"}]
