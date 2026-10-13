"""登录后公开接口 + 真实 worker/PostgreSQL；只替换外部模型 HTTP。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.routes import ai, questions, settings as settings_routes, wrong, quiz
from app.core.database import Base, get_db
from app.core.config import settings as runtime_settings
from app.core.security import create_access_token
from app.models import Exam, Question, QuestionBank, QuizSession, User
from app.services.settings_service import set_encrypted_ai_api_key, set_key
from app.workers import job_worker
from postgres_support import isolated_postgres


@pytest.fixture(scope="module")
def postgres():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def api(postgres, monkeypatch):
    monkeypatch.setattr(runtime_settings, "JWT_SECRET_KEY", "isolated-api-auth")
    monkeypatch.setattr(runtime_settings, "SECRET_KEY", "isolated-api-encryption")
    monkeypatch.setattr(runtime_settings, "SYSTEM_SETTINGS_ENCRYPTION_KEY", None)
    monkeypatch.setattr(runtime_settings, "AI_EXPLANATION_CONCURRENCY", 3)
    with postgres.begin() as connection:
        names = ', '.join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f'TRUNCATE {names} RESTART IDENTITY CASCADE'))
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        admin = User(username="owner", email="owner@example.invalid", password_hash="unused", is_admin=True)
        other = User(username="other", email="other@example.invalid", password_hash="unused", is_admin=False)
        db.add_all([admin, other]); db.flush()
        exam = Exam(owner_id=admin.id, slug="study", name="Study", short_name="Study")
        db.add(exam); db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Study")
        db.add(bank); db.flush()
        qs = [Question(bank_id=bank.id, question_type="single", content=f"Which control is MOST effective? {n}", options=[{"key": key, "text": f"Option {key}"} for key in "ABCD"], correct_answer="D") for n in range(2)]
        db.add_all(qs); db.flush()
        session = QuizSession(user_id=admin.id, bank_id=bank.id, mode="sequential", total_questions=2, question_ids=json.dumps([q.id for q in qs]))
        db.add(session)
        set_key(db, "ai_api_base_url", "https://8.8.8.8")
        set_encrypted_ai_api_key(db, "isolated-model-token")
        set_key(db, "ai_explain_model", "model-a")
        db.commit()
        ids = [q.id for q in qs]
        owner_id, other_id, session_id = admin.id, other.id, session.id
    app = FastAPI()
    app.include_router(ai.router, prefix="/api/ai")
    app.include_router(settings_routes.router, prefix="/api/settings")
    app.include_router(questions.router, prefix="/api/questions")
    app.include_router(wrong.router, prefix="/api/wrong")
    app.include_router(quiz.router, prefix="/api/quiz")
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(job_worker, "SessionLocal", sessions)
    with TestClient(app, headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}", "X-Exam-Slug": "study"}) as client:
        yield SimpleNamespace(client=client, app=app, sessions=sessions, ids=ids, owner_id=owner_id, other_id=other_id, session_id=session_id)


def test_admin_configures_ordered_models_and_invalid_lists_are_rejected(api):
    c = api.client
    response = c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "model-b", "reasoning_effort": None}, {"model_id": " model-a "}]})
    assert response.status_code == 200, response.text
    models = c.get('/api/settings/ai').json()['ai_explain_models']
    assert models == [{"model_id": "model-b", "reasoning_effort": None}, {"model_id": "model-a", "reasoning_effort": "xhigh"}]
    assert c.get('/api/ai/explanation-models').json() == {"models": ["model-b", "model-a"]}
    for invalid in ([{"model_id": "bad\x00id"}], [], [{"model_id": ""}], [{"model_id": "x"}, {"model_id": " x "}], [{"model_id": str(i)} for i in range(6)], None):
        assert c.put('/api/settings/ai', json={"ai_explain_models": invalid}).status_code == 422
    assert c.get('/api/ai/explanation-models').json() == {"models": ["model-b", "model-a"]}
    token = create_access_token(str(api.other_id))
    assert c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "other"}]}, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def valid_analysis(answer="D", *, marker="分析"):
    return {
        "judged_answer": answer,
        "stem_breakdown": {"qualifier": "MOST", "role": "工程师", "scenario": "选择控制措施", "constraint": "", "asked": "选择最有效的措施"},
        "explanation": "The control reduces exposure. It also protects the data.",
        "explanation_zh": f"{marker}：该控制措施减少数据暴露。它还能够保护数据的整个处理过程。",
        "distractors": [{"key": k, "type": "范围过窄", "reason": "该措施只覆盖单个环节，无法满足题目的整体限制"} for k in "ABCD" if k not in answer.split(',')],
    }


def upstream(monkeypatch, responses=None):
    calls = []
    def post(url, *, json, **kwargs):
        calls.append(json)
        item = responses[len(calls) - 1] if responses else valid_analysis("A" if json["model"] == "model-b" else "D")
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json={"choices": [{"message": {"content": __import__('json').dumps(item, ensure_ascii=False)}}]})
    monkeypatch.setattr(httpx, 'post', post)
    return calls


def test_each_model_is_independent_cached_and_refreshed_through_worker(api, monkeypatch):
    c = api.client
    c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "model-a"}, {"model_id": "model-b", "reasoning_effort": None}]})
    calls = upstream(monkeypatch)
    qid = api.ids[0]
    first = c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    assert first.status_code == 202, first.text
    duplicate = c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a", "force": True})
    assert duplicate.json()['generation']['id'] == first.json()['generation']['id']
    second = c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-b"})
    assert second.status_code == 202
    assert calls == []
    assert job_worker.process_one_job()
    summary = c.get('/api/ai/explanations', params={"question_id": qid}).json()
    assert summary['models'][0]['result']['judged_answer'] == 'D'
    assert summary['models'][1]['result'] is None
    assert 'explanation_zh' not in summary['models'][0]['result']
    assert job_worker.process_one_job()
    summary = c.get('/api/ai/explanations', params={"question_id": qid}).json()
    assert [m['result']['judged_answer'] for m in summary['models']] == ['D', 'A']
    assert [m['result']['is_conflict'] for m in summary['models']] == [False, True]
    detail = c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-b"}).json()
    assert detail['result']['analysis']['judged_answer'] == 'A'
    assert '题库答案' not in detail['result']['explanation_zh']
    assert '【题干拆解】' in detail['result']['explanation_zh']
    assert calls[0]['reasoning_effort'] == 'xhigh'
    assert 'reasoning_effort' not in calls[1]
    assert '正确答案' not in calls[0]['messages'][1]['content']
    assert 'single' in calls[0]['messages'][1]['content']
    assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"}).status_code == 200
    assert not job_worker.process_one_job()
    assert len(calls) == 2
    refresh = c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-b", "force": True})
    assert refresh.status_code == 202
    assert refresh.json()['result']['judged_answer'] == 'A'
    assert job_worker.process_one_job()
    assert len(calls) == 3
    assert c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-a"}).json()['result']['generation_id'] == first.json()['generation']['id']


def test_all_models_prewarm_reuses_jobs_and_failed_model_is_not_silently_retried(api, monkeypatch):
    c = api.client
    c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "model-a"}, {"model_id": "model-b"}]})
    # 已翻译，预热仅检查解析；没有替换业务层。
    with api.sessions() as db:
        for qid in api.ids:
            q = db.get(Question, qid)
            q.content_zh = "已翻译"
            q.options = [{"key": k, "text": f"Option {k}", "text_zh": f"选项{k}"} for k in "ABCD"]
        db.commit()
    calls = upstream(monkeypatch, [httpx.ReadTimeout("upstream-private-token"), valid_analysis(), valid_analysis(), valid_analysis()])
    body = {"session_id": api.session_id, "question_ids": api.ids}
    assert c.post('/api/ai/prewarm', json=body).status_code == 200
    initial = [c.get('/api/ai/explanations', params={"question_id": qid}).json()['models'] for qid in api.ids]
    assert all(m['generation']['status'] == 'queued' for models in initial for m in models)
    assert c.post('/api/ai/prewarm', json=body).status_code == 200
    assert [m['generation']['id'] for m in c.get('/api/ai/explanations', params={"question_id": api.ids[0]}).json()['models']] == [m['generation']['id'] for m in initial[0]]
    assert job_worker.process_one_job()
    failed = c.get('/api/ai/explanations', params={"question_id": api.ids[0]}).json()['models'][0]
    assert failed['generation']['status'] == 'failed'
    assert "private" not in json.dumps(failed)
    assert c.post('/api/ai/prewarm', json=body).status_code == 200
    for _ in range(3):
        assert job_worker.process_one_job()
    assert not job_worker.process_one_job()
    assert len(calls) == 4
    assert c.post('/api/ai/explain', json={"question_id": api.ids[0], "model_id": "model-a", "force": True}).status_code == 202


def test_failed_refresh_keeps_success_and_output_repair_is_limited(api, monkeypatch):
    c, qid = api.client, api.ids[0]
    calls = upstream(monkeypatch, [valid_analysis(), {}, {}, httpx.ReadTimeout("upstream-secret")])
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    assert job_worker.process_one_job()
    before = c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-a"}).json()['result']
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a", "force": True})
    assert job_worker.process_one_job()
    state = c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-a"}).json()
    assert state['result'] == before
    assert state['generation']['status'] == 'failed'
    assert not job_worker.process_one_job()
    assert len(calls) == 3
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a", "force": True})
    assert job_worker.process_one_job()
    assert len(calls) == 4
    assert not job_worker.process_one_job()


def _run_slot_worker(database_url, release, active, peak, started):
    from sqlalchemy import create_engine
    engine = create_engine(database_url)
    runtime_settings.SECRET_KEY = "isolated-api-encryption"
    runtime_settings.SYSTEM_SETTINGS_ENCRYPTION_KEY = None
    runtime_settings.AI_EXPLANATION_CONCURRENCY = 3
    job_worker.SessionLocal = sessionmaker(bind=engine)

    def post(url, **kwargs):
        with active.get_lock():
            active.value += 1
            peak.value = max(peak.value, active.value)
            started.value += 1
        try:
            assert release.wait(15)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(valid_analysis())}}]})
        finally:
            with active.get_lock():
                active.value -= 1

    httpx.post = post
    try:
        job_worker.process_one_job()
    finally:
        engine.dispose()


def test_multiple_worker_processes_share_three_slots(api, postgres, monkeypatch):
    import multiprocessing
    import time
    c, qid = api.client, api.ids[0]
    c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": f"model-{i}"} for i in range(5)]})
    for i in range(5):
        assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": f"model-{i}"}).status_code == 202
    context = multiprocessing.get_context('spawn')
    active, peak, started = context.Value('i', 0), context.Value('i', 0), context.Value('i', 0)
    release = context.Event()
    workers = [context.Process(target=_run_slot_worker, args=(postgres.url.render_as_string(hide_password=False), release, active, peak, started)) for _ in range(5)]
    try:
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + 10
        while started.value < 3 and time.monotonic() < deadline:
            time.sleep(.02)
        time.sleep(.15)
        assert peak.value == 3
        states = c.get('/api/ai/explanations', params={"question_id": qid}).json()['models']
        assert sum(m['generation']['status'] == 'running' for m in states) == 3
        assert sum(m['generation']['status'] == 'queued' for m in states) == 2
    finally:
        release.set()
        for worker in workers:
            worker.join(15)
            if worker.is_alive():
                worker.terminate(); worker.join()
            assert worker.exitcode == 0
    assert all(m['generation']['status'] != 'running' for m in c.get('/api/ai/explanations', params={"question_id": qid}).json()['models'])


def test_correct_answer_keeps_models_and_model_reconfiguration_does_not_recompute(api, monkeypatch):
    c, qid = api.client, api.ids[0]
    calls = upstream(monkeypatch)
    with api.sessions() as db:
        db.get(Question, qid).explanation_zh = "【答案冲突】历史未知来源"
        db.commit()
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    job_worker.process_one_job()
    before = c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-a"}).json()['result']
    response = c.put(f'/api/questions/{qid}/correct-answer', json={"correct_answer": "A"})
    assert response.status_code == 200, response.text
    after = c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-a"}).json()['result']
    assert after['judged_answer'] == 'D'
    assert after['generation_id'] == before['generation_id']
    assert after['is_conflict'] is True
    with api.sessions() as db:
        assert db.get(Question, qid).explanation_zh is None
    c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "new"}, {"model_id": "model-a", "reasoning_effort": None}]})
    summary = c.get('/api/ai/explanations', params={"question_id": qid}).json()['models']
    assert [m['model_id'] for m in summary] == ['new', 'model-a']
    assert summary[0]['result'] is None
    assert summary[1]['result']['generation_id'] == before['generation_id']
    assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"}).status_code == 200
    assert len(calls) == 1
    c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "new"}]})
    assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"}).status_code == 422
    c.put('/api/settings/ai', json={"ai_explain_models": [{"model_id": "model-a"}]})
    assert c.get('/api/ai/explanations', params={"question_id": qid}).json()['models'][0]['result']['generation_id'] == before['generation_id']


@pytest.mark.parametrize('action', ['content', 'options', 'question_type', 'delete'])
def test_late_generation_cannot_overwrite_changed_or_deleted_question(api, monkeypatch, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    c, qid = api.client, api.ids[0]
    entered, release = Event(), Event()
    def post(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(valid_analysis())}}]})
    monkeypatch.setattr(httpx, 'post', post)
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(job_worker.process_one_job)
        try:
            assert entered.wait(5)
            if action == 'delete':
                changed = c.delete(f'/api/questions/{qid}')
            else:
                payload = {"content": "A new question", "options": [{"key": "A", "text": "New"}, {"key": "B", "text": "Other"}], "question_type": "multiple"}
                changed = c.put(f'/api/questions/{qid}', json={action: payload[action]})
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        assert pending.result(5)
    response = c.get('/api/ai/explanations', params={"question_id": qid})
    if action == 'delete':
        assert response.status_code == 404
    else:
        assert response.json()['models'][0]['result'] is None


def test_wrong_list_includes_lightweight_models_and_ownership_is_enforced(api, monkeypatch):
    from app.models import WrongAnswer
    c, qid = api.client, api.ids[0]
    upstream(monkeypatch)
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    job_worker.process_one_job()
    with api.sessions() as db:
        db.add(WrongAnswer(user_id=api.owner_id, question_id=qid))
        db.commit()
    listing = c.get('/api/wrong').json()
    summary = listing[0]['question']['ai_explanations']
    assert summary[0]['result']['judged_answer'] == 'D'
    assert 'explanation_zh' not in summary[0]['result']
    outsider = {"Authorization": f"Bearer {create_access_token(str(api.other_id))}"}
    assert c.get('/api/ai/explanations', params={"question_id": qid}, headers=outsider).status_code == 404
    assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"}, headers=outsider).status_code == 404
    assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": "not-allowed"}).status_code == 422



def test_quiz_summary_is_lightweight_and_exam_does_not_expose_models(api, monkeypatch):
    c, qid = api.client, api.ids[0]
    upstream(monkeypatch)
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    job_worker.process_one_job()
    ordinary = c.post('/api/quiz/start', json={"bank_id": 1, "mode": "sequential"})
    assert ordinary.status_code == 200, ordinary.text
    model = ordinary.json()['questions'][0]['ai_explanations'][0]
    assert model['result']['judged_answer'] == 'D'
    assert 'explanation_zh' not in model['result']
    resumed = c.get(f"/api/quiz/session/{ordinary.json()['session']['id']}").json()
    assert resumed['questions'][0]['ai_explanations'][0]['result']['judged_answer'] == 'D'
    exam = c.post('/api/quiz/start', json={"bank_id": 1, "mode": "exam"}).json()
    assert all('ai_explanations' not in q for q in exam['questions'])
    assert all('explanation_zh' not in q for q in exam['questions'])
    resumed_exam = c.get(f"/api/quiz/session/{exam['session']['id']}").json()
    assert all('ai_explanations' not in q for q in resumed_exam['questions'])


@pytest.mark.parametrize('kind, answer, expected', [('single', 'A,C', 'failed'), ('truefalse', '', 'failed'), ('multiple', 'C,A', 'completed')])
def test_answers_are_required_and_valid_for_question_type(api, monkeypatch, kind, answer, expected):
    c, qid = api.client, api.ids[0]
    c.put(f'/api/questions/{qid}', json={"question_type": kind})
    calls = upstream(monkeypatch, [valid_analysis(answer), valid_analysis(answer)])
    c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    job_worker.process_one_job()
    model = c.get('/api/ai/explanations', params={"question_id": qid}).json()['models'][0]
    assert model['generation']['status'] == expected
    if expected == 'completed':
        assert model['result']['judged_answer'] == 'A,C'
        assert len(calls) == 1
    else:
        assert model['result'] is None
        assert len(calls) == 2
    assert not job_worker.process_one_job()


def test_manual_request_promotes_prewarm_without_duplicate(api, monkeypatch):
    c = api.client
    with api.sessions() as db:
        for qid in api.ids:
            q = db.get(Question, qid)
            q.content_zh = "已翻译"
            q.options = [{"key": k, "text": f"Option {k}", "text_zh": k} for k in "ABCD"]
        db.commit()
    calls = upstream(monkeypatch)
    c.post('/api/ai/prewarm', json={"session_id": api.session_id, "question_ids": api.ids})
    queued = c.get('/api/ai/explanations', params={"question_id": api.ids[1]}).json()['models'][0]['generation']['id']
    promoted = c.post('/api/ai/explain', json={"question_id": api.ids[1], "model_id": "model-a"}).json()
    assert promoted['generation']['id'] == queued
    job_worker.process_one_job()
    assert 'effective? 1' in calls[0]['messages'][1]['content']
    assert c.get('/api/ai/explanations', params={"question_id": api.ids[0]}).json()['models'][0]['result'] is None


def test_migration_keeps_legacy_unknown_and_terminates_only_old_explanation_tasks(postgres):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/011_multi_model_explanations.py'
    module_spec = importlib.util.spec_from_file_location('multi_model_migration', path)
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    with postgres.begin() as connection:
        connection.execute(text('CREATE SCHEMA explanation_migration'))
        connection.execute(text('SET LOCAL search_path TO explanation_migration'))
        connection.execute(text('CREATE TABLE questions (id INTEGER PRIMARY KEY, explanation_zh TEXT)'))
        connection.execute(text("INSERT INTO questions VALUES (1, 'unknown legacy')"))
        connection.execute(text('CREATE TABLE background_jobs (id INTEGER PRIMARY KEY, job_type TEXT, status TEXT, active_scope_key TEXT, lease_until TIMESTAMP, finished_at TIMESTAMP, last_error TEXT, status_message TEXT, payload_json TEXT)'))
        connection.execute(text("""INSERT INTO background_jobs(id,job_type,status,active_scope_key,payload_json) VALUES
            (1,'ai_prewarm','queued','old-explanation','{"artifact_type":"explanation"}'),
            (2,'ai_prewarm','queued','translation','{"artifact_type":"translation"}')"""))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text('SELECT explanation_zh FROM questions')).scalar() == 'unknown legacy'
            assert connection.execute(text('SELECT COUNT(*) FROM question_explanations')).scalar() == 0
            assert connection.execute(text('SELECT status,priority FROM background_jobs ORDER BY id')).all() == [('failed', 0), ('queued', 0)]
            migration.downgrade()
        assert connection.execute(text('SELECT explanation_zh FROM questions')).scalar() == 'unknown legacy'


def test_outdated_input_receipt_rejects_generation_without_provider_call(api, monkeypatch):
    c, qid = api.client, api.ids[0]
    stamp = c.get('/api/ai/explanations', params={"question_id": qid}).json()['input_fingerprint']
    assert c.put(f'/api/questions/{qid}', json={"content": "An updated question MOST effective?"}).status_code == 200
    calls = upstream(monkeypatch)
    response = c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a", "input_fingerprint": stamp})
    assert response.status_code == 409
    assert not job_worker.process_one_job()
    assert calls == []


def test_stale_recovery_cannot_overwrite_worker_success(api, postgres, monkeypatch):
    """租约到期与成功提交交错，公开状态仍必须为成功且不再调用模型。"""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from threading import Event, current_thread
    from sqlalchemy import event

    c, qid = api.client, api.ids[0]
    calls = upstream(monkeypatch)
    response = c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"})
    job_id = response.json()['generation']['id']
    locked, release, recovery_read = Event(), Event(), Event()

    # 只编排真实 PostgreSQL 的时序，不替换 worker 或任务服务。
    def after_sql(connection, cursor, statement, parameters, context, many):
        if 'SELECT' not in statement or 'background_jobs' not in statement:
            return
        if current_thread().name.startswith('finishing') and 'FOR UPDATE' in statement and 'background_jobs.id =' in statement:
            locked.set()
            assert release.wait(10)
        elif current_thread().name.startswith('recovering'):
            recovery_read.set()

    original_post = httpx.post
    def expire_during_upstream(*args, **kwargs):
        with api.sessions() as db:
            db.execute(text('UPDATE background_jobs SET lease_until=:expired WHERE id=:id'), {"expired": datetime.now(timezone.utc) - timedelta(seconds=1), "id": job_id})
            db.commit()
        return original_post(*args, **kwargs)
    monkeypatch.setattr(httpx, 'post', expire_during_upstream)
    event.listen(postgres, 'after_cursor_execute', after_sql)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='finishing') as finishing, ThreadPoolExecutor(max_workers=1, thread_name_prefix='recovering') as recovering:
            completed = finishing.submit(job_worker.process_one_job)
            try:
                assert locked.wait(5)
                recovered = recovering.submit(job_worker.process_one_job)
                assert recovery_read.wait(5)
                # 完成事务仍持锁；旧回收路径在陈旧 UPDATE 上阻塞。
                import time
                time.sleep(.15)
            finally:
                release.set()
            assert completed.result(5)
            assert not recovered.result(5)
    finally:
        release.set()
        event.remove(postgres, 'after_cursor_execute', after_sql)
    state = c.get('/api/ai/explanation', params={"question_id": qid, "model_id": "model-a"}).json()
    assert state['result']['judged_answer'] == 'D'
    assert state['generation']['status'] == 'completed'
    assert c.post('/api/ai/explain', json={"question_id": qid, "model_id": "model-a"}).status_code == 200
    assert len(calls) == 1
