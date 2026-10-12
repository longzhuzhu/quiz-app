"""通过真实 HTTP 与专用 PostgreSQL 验证首次写入和删除竞争。"""

from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
from threading import Barrier
from threading import Event
import importlib.util
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from alembic.migration import MigrationContext
from alembic.operations import Operations

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.deps import get_current_user
from app.api.routes.vocab import router
from app.core.database import Base, get_db
from app.models import Exam, QuestionBank, User, Vocabulary
from app.models.bank_word import BankWordFrequency, UserBankWordProgress
from app.models.vocabulary import UserVocabProgress
from app.services import ai_service
from postgres_support import isolated_postgres


@pytest.fixture(scope="module")
def postgres():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.mark.parametrize("frequent", [False, True])
def test_concurrent_first_progress_writes_and_deletion_do_not_resurrect(postgres, frequent):
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        user = User(username=f"concurrent-{frequent}", email=f"{frequent}@example.invalid", password_hash="unused")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="study", name="Study", short_name="Study")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Study")
        db.add(bank)
        db.flush()
        if frequent:
            word = BankWordFrequency(bank_id=bank.id, term="same", frequency=10)
        else:
            word = Vocabulary(user_id=user.id, exam_id=exam.id, term="same", is_system=False)
        db.add(word)
        db.commit()
        user_id, word_id, bank_id = user.id, word.id, bank.id
    app = FastAPI()
    app.include_router(router, prefix="/api/vocab")
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    def authenticated():
        with sessions() as db:
            return db.get(User, user_id)
    app.dependency_overrides[get_current_user] = authenticated
    url = "/api/vocab/frequent-items/progress" if frequent else f"/api/vocab/items/{word_id}/progress"
    body = {"is_mastered": True, **({"bank_id": bank_id, "term": "same"} if frequent else {})}
    def race(actions):
        barrier = Barrier(len(actions))
        def run(action):
            with TestClient(app, headers={"X-Exam-Slug": "study"}, raise_server_exceptions=False) as api:
                barrier.wait(timeout=10)
                return action(api)
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(run, actions))
    results = race([lambda api: api.put(url, json=body)] * 8)
    assert [r.status_code for r in results] == [200] * 8
    with sessions() as db:
        model = UserBankWordProgress if frequent else UserVocabProgress
        assert db.query(model).filter_by(user_id=user_id).count() == 1
    delete_url = "/api/vocab/frequent-items" if frequent else f"/api/vocab/items/{word_id}"
    params = {"bank_id": bank_id, "term": "same"} if frequent else {}
    results = race([lambda api: api.put(url, json=body), lambda api: api.delete(delete_url, params=params)])
    assert results[0].status_code in {200, 404}
    assert results[1].status_code == 200
    with TestClient(app, headers={"X-Exam-Slug": "study"}) as api:
        assert api.put(url, json=body).status_code == 404
        payload = {"scope": "frequent" if frequent else "exam_personal", "refs": [{"term": "same"} if frequent else {"vocabulary_id": word_id}], **({"bank_id": bank_id} if frequent else {})}
        assert api.post("/api/vocab/study/items", json=payload).json()["results"][0]["available"] is False


def test_non_target_constraint_error_is_not_reported_as_saved(postgres):
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        user = User(username="constraint-user", email="constraint@example.invalid", password_hash="unused")
        db.add(user); db.flush()
        exam = Exam(owner_id=user.id, slug="study", name="Study", short_name="Study")
        db.add(exam); db.flush()
        word = Vocabulary(user_id=user.id, exam_id=exam.id, term="constraint", is_system=False)
        db.add(word); db.commit()
        user_id, word_id = user.id, word.id
    app = FastAPI()
    app.include_router(router, prefix="/api/vocab")
    def database():
        with sessions() as db:
            yield db
    def authenticated():
        with sessions() as db:
            return db.get(User, user_id)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = authenticated
    with postgres.begin() as connection:
        connection.execute(text("ALTER TABLE user_vocab_progress ADD CONSTRAINT study_test_reject_mastery CHECK (is_mastered IS FALSE)"))
    try:
        with TestClient(app, headers={"X-Exam-Slug": "study"}, raise_server_exceptions=False) as api:
            response = api.put(f"/api/vocab/items/{word_id}/progress", json={"is_mastered": True})
            assert response.status_code == 500
        with sessions() as db:
            assert db.query(UserVocabProgress).filter_by(user_id=user_id).count() == 0
    finally:
        with postgres.begin() as connection:
            connection.execute(text("ALTER TABLE user_vocab_progress DROP CONSTRAINT study_test_reject_mastery"))


@pytest.mark.parametrize("frequent", [False, True])
@pytest.mark.parametrize("action", ["delete", "refresh"])
def test_slow_refresh_does_not_hold_locks_or_overwrite_newer_content(postgres, monkeypatch, frequent, action):
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        name = f"refresh-{frequent}-{action}"
        user = User(username=name, email=f"{name}@example.invalid", password_hash="unused")
        db.add(user); db.flush()
        exam = Exam(owner_id=user.id, slug="study", name="Study", short_name="Study")
        db.add(exam); db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Study")
        db.add(bank); db.flush()
        word = BankWordFrequency(bank_id=bank.id, term="same", frequency=10) if frequent else Vocabulary(user_id=user.id, exam_id=exam.id, term="same", is_system=False)
        db.add(word); db.commit()
        user_id, word_id, bank_id = user.id, word.id, bank.id
    app = FastAPI()
    app.include_router(router, prefix="/api/vocab")

    def database():
        with sessions() as db:
            yield db

    def authenticated():
        with sessions() as db:
            return db.get(User, user_id)

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = authenticated
    entered, release = Event(), Event()
    calls = []

    def generate(*args, **kwargs):
        calls.append(True)
        first = len(calls) == 1
        if first:
            entered.set()
            assert release.wait(timeout=15)
        return json.dumps({"term_zh": "迟到翻译" if first else "新的翻译", "definition": "Late." if first else "New.", "definition_zh": "迟到释义" if first else "新的释义"})

    monkeypatch.setattr(ai_service, "call_ai_api", generate)
    source = {"scope": "frequent", "bank_id": bank_id} if frequent else {"scope": "exam_personal"}
    ref = {"term": "same"} if frequent else {"vocabulary_id": word_id}

    def request_refresh():
        with TestClient(app, headers={"X-Exam-Slug": "study"}) as api:
            return api.post("/api/vocab/study/refresh", json={**source, "ref": ref})

    def change_target():
        if action == "refresh":
            return request_refresh()
        with TestClient(app, headers={"X-Exam-Slug": "study"}) as api:
            return api.delete("/api/vocab/frequent-items", params={"bank_id": bank_id, "term": "same"}) if frequent else api.delete(f"/api/vocab/items/{word_id}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(request_refresh)
        try:
            assert entered.wait(timeout=5)
            # AI 尚未返回时，第二个写入/删除必须完成，不能等慢请求释放锁。
            changed = pool.submit(change_target).result(timeout=5)
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        delayed = slow.result(timeout=5)
    assert delayed.status_code == (404 if action == "delete" else 409), delayed.text
    with TestClient(app, headers={"X-Exam-Slug": "study"}) as api:
        result = api.post("/api/vocab/study/items", json={**source, "refs": [ref]}).json()["results"][0]
    if action == "delete":
        assert result == {"ref": ref, "available": False}
    else:
        assert result["content"]["term_zh"] == "新的翻译"
        assert result["content"]["definition"] == "New."
        assert result["content"]["definition_zh"] == "新的释义"
        assert result["is_mastered"] is False


def test_bank_word_definition_migration_preserves_existing_words_and_is_reversible(postgres):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/010_bank_word_definitions.py"
    spec = importlib.util.spec_from_file_location("bank_word_definitions_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with postgres.begin() as connection:
        connection.execute(text("CREATE SCHEMA refresh_migration"))
        connection.execute(text("SET LOCAL search_path TO refresh_migration"))
        connection.execute(text("CREATE TABLE bank_word_frequencies (id INTEGER PRIMARY KEY, term VARCHAR(200))"))
        connection.execute(text("INSERT INTO bank_word_frequencies VALUES (1, 'existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT term, definition, definition_zh FROM bank_word_frequencies")).one() == ("existing", None, None)
            connection.execute(text("UPDATE bank_word_frequencies SET definition='English', definition_zh='中文'"))
            migration.downgrade()
        assert connection.execute(text("SELECT * FROM bank_word_frequencies")).one() == (1, "existing")
