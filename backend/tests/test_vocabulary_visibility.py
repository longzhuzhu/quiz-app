"""单词本：个人词汇独立展示，项目词汇与用户数据保持隔离。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
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


from app.api.deps import get_current_user  # noqa: E402
from app.api.routes.vocab import router  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.models import Exam, User  # noqa: E402


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        user = User(username="alice", email="alice@example.invalid", password_hash="unused")
        other_user = User(username="bob", email="bob@example.invalid", password_hash="unused")
        db.add_all([user, other_user])
        db.flush()
        db.add_all([
            Exam(owner_id=user.id, slug=slug, name=slug, short_name=slug)
            for slug in ("current", "other")
        ])
        db.add(Exam(owner_id=other_user.id, slug="current", name="Bob", short_name="Bob"))
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api/vocab")
        app.dependency_overrides[get_db] = lambda: db

        def test_user(x_test_user: str = Header("alice")):
            return other_user if x_test_user == "bob" else user

        app.dependency_overrides[get_current_user] = test_user
        with TestClient(app, headers={"X-Exam-Slug": "current"}) as api:
            yield api
    engine.dispose()


def _add(client, term, scope="personal", exam="current"):
    response = client.post(
        "/api/vocab",
        params={"scope": scope},
        headers={"X-Exam-Slug": exam},
        json={"term": term},
    )
    assert response.status_code == 201
    return response.json()


def test_wordbook_contains_personal_words_but_not_project_vocabulary(client):
    favorite = _add(client, "privacy")
    shared = _add(client, "shared")
    project = _add(client, "project glossary", scope="exam_personal")
    _add(client, "other-project", scope="exam_personal", exam="other")

    response = client.get("/api/vocab", params={"scope": "personal"})
    assert response.status_code == 200
    assert {w["id"] for w in response.json()["items"]} == {favorite["id"], shared["id"]}
    assert favorite["scope_label"] == "personal"
    assert shared["scope_label"] == "personal"
    assert client.get("/api/vocab/stats").json() == {"personal": 2, "exam_personal": 1, "all": 3}

    response = client.get("/api/vocab", params={"scope": "exam_personal"})
    assert [w["id"] for w in response.json()["items"]] == [project["id"]]

    response = client.get("/api/vocab", params={"scope": "personal"}, headers={"X-Exam-Slug": "other"})
    assert {w["id"] for w in response.json()["items"]} == {favorite["id"], shared["id"]}


def test_wordbook_can_mark_and_delete_personal_favorites_without_changing_project_words(client):
    favorite = _add(client, "privacy")
    shared = _add(client, "shared")
    project = _add(client, "project glossary", scope="exam_personal")
    url = f"/api/vocab/items/{favorite['id']}"
    assert client.put(f"{url}/progress", json={"is_mastered": True}).status_code == 200
    response = client.get("/api/vocab", params={"scope": "personal", "mastered": "true"})
    assert [w["id"] for w in response.json()["items"]] == [favorite["id"]]

    assert client.delete(url).status_code == 200
    assert client.get("/api/vocab/stats").json() == {"personal": 1, "exam_personal": 1, "all": 2}
    response = client.get("/api/vocab", params={"scope": "personal"})
    assert [w["id"] for w in response.json()["items"]] == [shared["id"]]
    response = client.get("/api/vocab", params={"scope": "exam_personal"})
    assert [w["id"] for w in response.json()["items"]] == [project["id"]]
    assert response.json()["items"][0]["is_mastered"] is False


def test_other_project_favorites_cannot_be_modified_in_current_project(client):
    other = _add(client, "other-project", scope="exam_personal", exam="other")
    url = f"/api/vocab/items/{other['id']}"
    assert client.put(f"{url}/progress", json={"is_mastered": True}).status_code == 404
    assert client.delete(url).status_code == 404


def test_other_users_words_are_not_visible_or_editable(client):
    response = client.post(
        "/api/vocab", params={"scope": "personal"},
        headers={"X-Test-User": "bob"}, json={"term": "private word"},
    )
    assert response.status_code == 201
    url = f"/api/vocab/items/{response.json()['id']}"
    assert client.get("/api/vocab", params={"scope": "personal"}).json()["items"] == []
    assert client.get("/api/vocab/stats").json() == {"personal": 0, "exam_personal": 0, "all": 0}
    assert client.put(f"{url}/progress", json={"is_mastered": True}).status_code == 404
    assert client.delete(url).status_code == 404
