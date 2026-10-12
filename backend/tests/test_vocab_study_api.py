"""学习读取的公开 HTTP 契约：身份快照与内容分离，权限不能被快照冻结。"""

from test_vocabulary_visibility import client  # noqa: F401
import json
import httpx
import pytest
from sqlalchemy import event
from app.core.database import get_db
from app.models import Exam, QuestionBank
from app.models.bank_word import BankWordExclusion, BankWordFrequency
from app.services import ai_service


def add(api, term, scope="personal", exam="current", **content):
    response = api.post(
        "/api/vocab", params={"scope": scope}, headers={"X-Exam-Slug": exam},
        json={"term": term, **content},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_personal_deck_is_complete_stable_and_has_no_project_identity(client):
    ids = [add(client, f"word{i:03}") for i in range(110)]
    upper = add(client, "Apple")
    lower = add(client, "apple")
    duplicate = add(client, "Apple")
    add(client, "project", "exam_personal")
    add(client, "other", "exam_personal", "other")
    marked = ids[0]
    assert client.put(f"/api/vocab/items/{marked}/progress", json={"is_mastered": True}).status_code == 200
    response = client.get("/api/vocab/study/deck", params={"scope": "personal"})
    assert response.status_code == 200
    deck = response.json()
    assert deck == {
        "schema_version": 1,
        "context": {"scope": "personal", "exam_id": None, "bank_id": None},
        "mastery": "unmastered", "top_limit": None, "total": 112,
        "refs": [{"vocabulary_id": i} for i in [upper, duplicate, lower, *ids[1:]]],
    }
    assert client.get("/api/vocab/study/deck", params={"scope": "personal", "mastery": "mastered"}).json()["refs"] == [{"vocabulary_id": marked}]
    assert client.get("/api/vocab/study/deck", params={"scope": "personal", "mastery": "all"}).json()["total"] == 113
    assert client.get("/api/vocab/study/deck", params={"scope": "personal"}, headers={"X-Exam-Slug": "other"}).json() == deck


def seed_bank(api, count=3, exam="current"):
    db = api.app.dependency_overrides[get_db]()
    owner_exam = db.query(Exam).filter_by(slug=exam, owner_id=1).one()
    bank = QuestionBank(name="Study bank", exam_id=owner_exam.id)
    db.add(bank)
    db.flush()
    db.add_all([BankWordFrequency(bank_id=bank.id, term=f"term{i:04}", frequency=count-i, term_zh="词") for i in range(count)])
    db.commit()
    return bank.id


@pytest.mark.parametrize("scope", ["personal", "exam_personal", "frequent"])
def test_refresh_updates_translation_and_both_definitions_without_marking(client, monkeypatch, scope):
    updated = {"term_zh": "新的中文翻译", "definition": "A newly generated English definition.", "definition_zh": "重新生成的中文释义。"}
    calls = []

    def generate(messages, db, **kwargs):
        calls.append((messages, kwargs))
        return json.dumps(updated)

    monkeypatch.setattr(ai_service, "call_ai_api", generate)
    if scope == "frequent":
        bank = seed_bank(client)
        source = {"scope": scope, "bank_id": bank}
        ref = {"term": "term0000"}
        assert client.put("/api/vocab/frequent-items/progress", json={"bank_id": bank, "term": ref["term"], "is_mastered": True}).status_code == 200
        term = ref["term"]
    else:
        word = add(client, "alpha", scope, term_zh="旧翻译", definition="Old definition.", definition_zh="旧释义")
        source, ref, term = {"scope": scope}, {"vocabulary_id": word}, "alpha"
        assert client.put(f"/api/vocab/items/{word}/progress", json={"is_mastered": True}).status_code == 200
    response = client.post("/api/vocab/study/refresh", json={**source, "ref": ref})
    assert response.status_code == 200, response.text
    assert response.json() == {"ref": ref, "content": {"term": term, **updated, "frequency": 3 if scope == "frequent" else None}}
    read = client.post("/api/vocab/study/items", json={**source, "refs": [ref]}).json()["results"][0]
    assert read["content"] == response.json()["content"]
    assert read["is_mastered"] is True
    assert len(calls) == 1
    assert term in calls[0][0][-1]["content"]


@pytest.mark.parametrize("frequent", [False, True])
@pytest.mark.parametrize("generated", [
    'not JSON', '[]', '{}',
    json.dumps({"term_zh": "新词义", "definition": "English."}),
    json.dumps({"term_zh": "新词义", "definition": "English.", "definition_zh": "   "}),
    json.dumps({"term_zh": None, "definition": "English.", "definition_zh": "中文"}),
    json.dumps({"term_zh": 123, "definition": "English.", "definition_zh": "中文"}),
    json.dumps({"term_zh": "词" * 201, "definition": "English.", "definition_zh": "中文"}),
    json.dumps({"term_zh": "词", "definition": "e" * 10001, "definition_zh": "中文"}),
    json.dumps({"term": "changed", "term_zh": "词", "definition": "English.", "definition_zh": "中文"}),
])
def test_refresh_invalid_ai_result_does_not_partially_replace_old_content(client, monkeypatch, frequent, generated):
    if frequent:
        source, ref = {"scope": "frequent", "bank_id": seed_bank(client)}, {"term": "term0000"}
    else:
        source = {"scope": "personal"}
        ref = {"vocabulary_id": add(client, "alpha", term_zh="旧词义", definition="Old.", definition_zh="旧释义")}
    before = client.post("/api/vocab/study/items", json={**source, "refs": [ref]}).json()
    monkeypatch.setattr(ai_service, "call_ai_api", lambda *args, **kwargs: generated)
    response = client.post("/api/vocab/study/refresh", json={**source, "ref": ref})
    assert response.status_code == 502
    assert client.post("/api/vocab/study/items", json={**source, "refs": [ref]}).json() == before


@pytest.mark.parametrize("timeout", [False, True])
def test_refresh_ai_errors_are_safe_and_leave_old_content(client, monkeypatch, timeout):
    word = add(client, "alpha", term_zh="旧翻译", definition="Old.", definition_zh="旧释义")
    body = {"scope": "personal", "ref": {"vocabulary_id": word}}

    def failing(*args, **kwargs):
        raise httpx.ReadTimeout("private provider sk-secret") if timeout else ValueError("private provider sk-secret")

    monkeypatch.setattr(ai_service, "call_ai_api", failing)
    response = client.post("/api/vocab/study/refresh", json=body)
    assert response.status_code == (504 if timeout else 502)
    assert "sk-secret" not in response.text
    result = client.post("/api/vocab/study/items", json={"scope": "personal", "refs": [body["ref"]]}).json()["results"][0]
    assert result["content"]["definition"] == "Old."
    assert result["content"]["term_zh"] == "旧翻译"


def test_refresh_forbidden_or_missing_targets_never_call_ai(client, monkeypatch):
    personal = add(client, "personal")
    project = add(client, "project", "exam_personal")
    foreign = add(client, "foreign", "exam_personal", "other")
    bank = seed_bank(client)
    db = client.app.dependency_overrides[get_db]()
    db.add(BankWordExclusion(bank_id=bank, term="term0001", created_by=1)); db.commit()
    calls = []
    monkeypatch.setattr(ai_service, "call_ai_api", lambda *args, **kwargs: calls.append(args))
    cases = [
        ({"scope": "personal", "ref": {"vocabulary_id": personal}}, {"X-Test-User": "bob"}),
        ({"scope": "personal", "ref": {"vocabulary_id": project}}, {}),
        ({"scope": "exam_personal", "ref": {"vocabulary_id": personal}}, {}),
        ({"scope": "exam_personal", "ref": {"vocabulary_id": foreign}}, {}),
        ({"scope": "personal", "ref": {"vocabulary_id": 99999}}, {}),
        ({"scope": "frequent", "bank_id": bank, "ref": {"term": "term0000"}}, {"X-Exam-Slug": "other"}),
        ({"scope": "frequent", "bank_id": bank, "ref": {"term": "term0000"}}, {"X-Test-User": "bob"}),
        ({"scope": "frequent", "bank_id": bank, "ref": {"term": "term0001"}}, {}),
        ({"scope": "frequent", "bank_id": bank, "ref": {"term": "unknown"}}, {}),
    ]
    for body, headers in cases:
        assert client.post("/api/vocab/study/refresh", json=body, headers=headers).status_code == 404
    assert calls == []


@pytest.mark.parametrize("body", [
    {"scope": "all", "ref": {"vocabulary_id": 1}},
    {"scope": "personal", "ref": {"term": "alpha"}},
    {"scope": "personal", "bank_id": None, "ref": {"vocabulary_id": 1}},
    {"scope": "personal", "ref": {"vocabulary_id": True}},
    {"scope": "personal", "ref": {"vocabulary_id": 1}, "definition": "injected"},
    {"scope": "frequent", "ref": {"term": "alpha"}},
    {"scope": "frequent", "bank_id": 1, "ref": {"term": " "}},
])
def test_refresh_rejects_invalid_source_or_identity(client, body):
    assert client.post("/api/vocab/study/refresh", json=body).status_code == 422


def test_refresh_accepts_fenced_json_and_trims_all_three_fields(client, monkeypatch):
    word = add(client, "alpha")
    monkeypatch.setattr(ai_service, "call_ai_api", lambda *args, **kwargs: '```json\n' + json.dumps({"term_zh": "  中文  ", "definition": " English.\n", "definition_zh": " 释义\n"}) + '\n```')
    response = client.post("/api/vocab/study/refresh", json={"scope": "personal", "ref": {"vocabulary_id": word}})
    assert response.status_code == 200
    assert response.json()["content"] == {"term": "alpha", "term_zh": "中文", "definition": "English.", "definition_zh": "释义", "frequency": None}


def test_frequent_overview_and_light_checks_do_not_load_new_definition_fields(client):
    bank = seed_bank(client)
    db = client.app.dependency_overrides[get_db]()
    statements = []

    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        assert client.get("/api/vocab/frequent", params={"bank_id": bank, "per_page": 1}).status_code == 200
        assert client.get("/api/vocab/study/deck", params={"scope": "frequent", "bank_id": bank}).status_code == 200
        assert client.post("/api/vocab/study/items", json={"scope": "frequent", "bank_id": bank, "refs": [{"term": "term0000"}], "include_content": False}).status_code == 200
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert not any("definition" in statement.lower() for statement in statements)


def test_batches_keep_order_and_recheck_visibility_without_reapplying_mastery(client):
    first = add(client, "alpha", term_zh="阿尔法", definition="english", definition_zh="中文释义")
    second = add(client, "beta")
    foreign = add(client, "other", "exam_personal", "other")
    refs = [{"vocabulary_id": i} for i in [second, foreign, first, 99999]]
    response = client.post("/api/vocab/study/items", json={"scope": "personal", "refs": refs})
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["ref"] for r in results] == refs
    assert results[1] == {"ref": refs[1], "available": False}
    assert results[3] == {"ref": refs[3], "available": False}
    assert results[2] == {
        "ref": refs[2], "available": True, "is_mastered": False,
        "can_mark_mastered": True, "can_delete": True,
        "content": {"term": "alpha", "term_zh": "阿尔法", "definition": "english", "definition_zh": "中文释义", "frequency": None},
    }
    assert client.put(f"/api/vocab/items/{first}/progress", json={"is_mastered": True}).status_code == 200
    assert client.delete(f"/api/vocab/items/{second}").status_code == 200
    light = client.post("/api/vocab/study/items", json={"scope": "personal", "refs": refs, "include_content": False}).json()["results"]
    assert light[0] == {"ref": refs[0], "available": False}
    assert light[2]["available"] and light[2]["is_mastered"]
    assert light[2]["content"] is None
    assert client.post("/api/vocab/study/items", headers={"X-Test-User": "bob"}, json={"scope": "personal", "refs": [refs[2]]}).json()["results"] == [{"ref": refs[2], "available": False}]


@pytest.mark.parametrize("params", [
    {"scope": "all"}, {"scope": "personal", "mastery": "invalid"},
    {"scope": "personal", "bank_id": 1}, {"scope": "frequent"}, {"scope": "frequent", "bank_id": 0},
])
def test_deck_rejects_invalid_context(client, params):
    assert client.get("/api/vocab/study/deck", params=params).status_code == 422


@pytest.mark.parametrize("payload", [
    {"scope": "all", "refs": [{"vocabulary_id": 1}]},
    {"scope": "personal", "refs": []},
    {"scope": "personal", "refs": [{"term": "word"}]},
    {"scope": "personal", "bank_id": 1, "refs": [{"vocabulary_id": 1}]},
    {"scope": "personal", "bank_id": None, "refs": [{"vocabulary_id": 1}]},
    {"scope": "personal", "refs": [{"vocabulary_id": 1}, {"vocabulary_id": 1}]},
    {"scope": "personal", "refs": [{"vocabulary_id": i} for i in range(1, 102)]},
    {"scope": "personal", "include_content": False, "refs": [{"vocabulary_id": i} for i in range(1, 502)]},
] + [{"scope": "personal", "refs": [{"vocabulary_id": value}]} for value in [0, -1, True, 1.5, "1"]]
  + [{"scope": "frequent", "bank_id": 1, "refs": [{"term": value}]} for value in ["", "   ", "x" * 201]])
def test_invalid_batches_are_rejected(client, payload):
    assert client.post("/api/vocab/study/items", json=payload).status_code == 422


def test_frequent_top_limit_precedes_mastery_and_old_members_ignore_new_rank(client):
    bank_id = seed_bank(client, 5001)
    progress = {"bank_id": bank_id, "term": "term0000", "is_mastered": True}
    assert client.put("/api/vocab/frequent-items/progress", json=progress).status_code == 200
    deck = client.get("/api/vocab/study/deck", params={"scope": "frequent", "bank_id": bank_id}).json()
    assert deck["total"] == 4999 and deck["top_limit"] == 5000
    assert deck["refs"][0] == {"term": "term0001"}
    assert deck["refs"][-1] == {"term": "term4999"}
    assert deck["context"] == {"scope": "frequent", "exam_id": 1, "bank_id": bank_id}
    db = client.app.dependency_overrides[get_db]()
    db.query(BankWordFrequency).filter_by(bank_id=bank_id, term="term0001").update({"frequency": 0})
    db.add(BankWordExclusion(bank_id=bank_id, term="term0002", created_by=1))
    db.commit()
    refs = [{"term": "term0001"}, {"term": "term0002"}, {"term": "unknown"}]
    results = client.post("/api/vocab/study/items", json={"scope": "frequent", "bank_id": bank_id, "refs": refs}).json()["results"]
    assert results[0]["available"] and results[0]["content"]["frequency"] == 0
    assert results[1:] == [{"ref": ref, "available": False} for ref in refs[1:]]
    assert client.post("/api/vocab/study/items", headers={"X-Exam-Slug": "other"}, json={"scope": "frequent", "bank_id": bank_id, "refs": refs}).status_code == 404
    assert client.post("/api/vocab/study/items", headers={"X-Test-User": "bob"}, json={"scope": "frequent", "bank_id": bank_id, "refs": refs}).status_code == 404


def test_snapshot_and_light_checks_do_not_select_definitions_or_query_per_word(client):
    refs = [{"vocabulary_id": add(client, f"word{i}")} for i in range(6)]
    db = client.app.dependency_overrides[get_db]()
    statements = []
    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        assert client.get("/api/vocab/study/deck", params={"scope": "personal"}).status_code == 200
        assert client.post("/api/vocab/study/items", json={"scope": "personal", "include_content": False, "refs": refs}).status_code == 200
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert len(statements) <= 4  # 每个请求一个上下文查询和一个集合查询。
    assert not any("definition" in statement.lower() for statement in statements)


def test_project_snapshot_excludes_other_projects_and_uses_stable_exam_id(client):
    ids = [add(client, f"word{i:03}", "exam_personal") for i in range(110)]
    add(client, "personal")
    add(client, "other", "exam_personal", "other")
    deck = client.get("/api/vocab/study/deck", params={"scope": "exam_personal"}).json()
    assert deck["refs"] == [{"vocabulary_id": i} for i in ids]
    assert deck["context"] == {"scope": "exam_personal", "exam_id": 1, "bank_id": None}
    assert client.get("/api/vocab/study/deck", params={"scope": "personal"}, headers={"X-Exam-Slug": "deleted"}).status_code == 404


@pytest.mark.parametrize("frequent", [False, True])
def test_absolute_false_cancels_long_term_mastery_and_reenters_unmastered(client, frequent):
    if frequent:
        bank = seed_bank(client)
        url = "/api/vocab/frequent-items/progress"
        body = {"bank_id": bank, "term": "term0000"}
        scope = {"scope": "frequent", "bank_id": bank}
        ref = {"term": "term0000"}
    else:
        word = add(client, "absolute")
        url = f"/api/vocab/items/{word}/progress"
        body = {}
        scope = {"scope": "personal"}
        ref = {"vocabulary_id": word}
    assert client.put(url, json={**body, "is_mastered": True}).status_code == 200
    assert client.get("/api/vocab/study/deck", params={**scope, "mastery": "mastered"}).json()["refs"] == [ref]
    assert client.put(url, json={**body, "is_mastered": False}).status_code == 200
    assert client.get("/api/vocab/study/deck", params={**scope, "mastery": "mastered"}).json()["total"] == 0
    assert ref in client.get("/api/vocab/study/deck", params=scope).json()["refs"]
    result = client.post("/api/vocab/study/items", json={**scope, "refs": [ref], "include_content": False}).json()["results"][0]
    assert result["is_mastered"] is False
