"""真实临时 PostgreSQL 的关联、事务、备份/恢复与纯判重回归。"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base
from app.models import (
    User, Exam, QuestionBank, Question, QuizSession, QuizAnswer, WrongAnswer,
    UserQuestionStat, PracticeDayQuestion, BankWordFrequency, UserBankWordProgress,
    BankWordExclusion, BackgroundJob, ImportJob, ImportParsedQuestion, QuestionTopic,
    ExamTopic, QuestionExplanation, VectorIndex,
)
from app.services import question_dedup_execution_service as execution
from app.services.question_dedup_service import DedupError, Scope, audit, exact_groups, surface, digest
from postgres_support import isolated_postgres


@pytest.fixture(scope="module")
def pg():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def db(pg):
    with pg.begin() as conn:
        names = ",".join('"' + name + '"' for name in Base.metadata.tables)
        conn.execute(text("TRUNCATE " + names + " RESTART IDENTITY CASCADE"))
    with Session(pg) as db:
        user = User(username="nianyu", email="nianyu@test.invalid", password_hash="test")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
        db.add(exam)
        db.flush()
        db.add_all([QuestionBank(id=13, exam_id=exam.id, name="官方题库", question_count=2), QuestionBank(id=15, exam_id=exam.id, name="CIPT-其他", question_count=0)])
        db.flush()
        db.add_all([Question(bank_id=13, question_type="single", content="privacy privacy controls", options=[{"key": "A", "text": "security security controls"}, {"key": "B", "text": "technical technical controls"}], correct_answer="A", explanation_zh="代表解析"), Question(bank_id=13, question_type="single", content="privacy privacy controls", options=[{"key": "A", "text": "security security controls"}, {"key": "B", "text": "technical technical controls"}], correct_answer="A", content_zh="其他翻译", explanation_zh="丢弃解析")])
        db.add_all([BankWordFrequency(bank_id=13, term=term, frequency=4, term_zh="保留翻译", definition="retain", definition_zh="保留释义") for term in ("privacy", "security", "technical")])
        db.add(BankWordFrequency(bank_id=13, term="controls", frequency=6))
        db.commit()
        yield db
        db.rollback()


def plan(db):
    return audit(db, audit_id="test-audit")[0]


def apply(db, tmp_path, proposed=None):
    proposed = proposed or plan(db)
    backup = tmp_path / "private" / "backup.json"
    result = execution.apply_plan(db, proposed, confirmation=proposed["approval_digest"], backup_path=backup, maintenance="offline-maintenance-confirmed")
    return result, backup


def session(db, ids, *, completed=False, snapshot=None, frozen=None):
    db.add(QuizSession(user_id=1, bank_id=13, mode="random", total_questions=len(ids), question_ids=json.dumps(ids), is_completed=completed, question_snapshot=snapshot, final_answers=frozen))
    db.commit()


def test_identity_excludes_answer_and_type_but_preserves_order(db):
    questions = [dict(row) for row in db.execute(select(Question.__table__)).mappings()]
    questions[1]["correct_answer"] = "B"
    questions[1]["question_type"] = "multiple"
    questions[1]["content"] = "  privacy\nprivacy   controls "
    assert len(exact_groups(questions)[0]) == 1
    questions[1]["options"] = list(reversed(questions[1]["options"]))
    assert not exact_groups(questions)[0]


@pytest.mark.parametrize("options", [None, {}, [], ["A", "B"], [{"key": "A", "text": "x"}, {"key": "A", "text": "y"}], [{"key": "A", "text": 3}, {"key": "B", "text": "y"}]])
def test_invalid_surface_is_fail_closed(options):
    with pytest.raises(DedupError):
        surface({"content": "test", "options": options})


def test_answer_conflict_still_one_group(db):
    db.get(Question, 2).correct_answer = "B"
    db.commit()
    report = plan(db)
    assert report["summary"]["groups"] == 1
    assert report["summary"]["answer_conflicts"] == 1
    assert report["summary"]["eligible_remove"] == 0


@pytest.mark.parametrize("scope", [Scope("other"), Scope(bank_ids=(12, 15)), Scope(exam_slug="other")])
def test_scope_not_authorized(db, scope):
    with pytest.raises(DedupError, match="SCOPE_NOT_AUTHORIZED"):
        audit(db, scope, audit_id="test")


def test_bank_ownership_revalidated(db):
    other = Exam(owner_id=1, slug="other", name="Other", short_name="O")
    db.add(other)
    db.flush()
    db.get(QuestionBank, 15).exam_id = other.id
    db.commit()
    with pytest.raises(DedupError, match="BANK_OWNERSHIP"):
        plan(db)


@pytest.mark.parametrize("completed,ids,snapshot,frozen,reason", [(False,[1],None,None,"unfinished_session"), (False,[2],None,None,"unfinished_session"), (True,[1,2],None,None,"completed_session_retry"), (True,[],[{"question_id":1},{"question_id":2}],None,"completed_session_retry"), (True,[],None,{"1":None,"2":None},"completed_session_retry")])
def test_session_member_and_legacy_retry_protection(db, completed, ids, snapshot, frozen, reason):
    session(db, ids, completed=completed, snapshot=snapshot, frozen=frozen)
    group = plan(db)["groups"][0]
    # ADR-0009：未完成会话即使只引用代表题也阻断，原题重做引用不可删除。
    assert reason in group["blockers"]
    assert not group["cascades"]


def test_reference_weight_does_not_remove_history(db):
    session(db, [2], completed=True)
    proposal = plan(db)["groups"][0]
    assert proposal["keep"] == 2 and proposal["remove"] == [1]
    assert not proposal["blockers"]
    # 已完成会话只引用代表题，没有任何成员被删，因此也没有级联代价。
    assert not proposal["cascades"]


def test_malformed_member_lists_block_all_groups(db):
    session(db, [1])
    db.execute(update(QuizSession).values(question_ids='{"unknown": 2}'))
    db.commit()
    assert "unknown_session_structure" in plan(db)["groups"][0]["blockers"]


@pytest.mark.parametrize("kind", ["answer", "wrong", "stat", "practice", "job", "vector", "import"])
def test_removed_learning_and_unknown_references_block(db, kind):
    # 给双方等量证据，平手保持最早题，无法用换代表绕过保护。
    for qid in (1,2):
        if kind == "answer":
            session(db, [qid], completed=True)
            db.add(QuizAnswer(session_id=qid, question_id=qid, user_answer="B", is_correct=False))
        elif kind == "wrong":
            db.add(WrongAnswer(user_id=1, question_id=qid))
        elif kind == "stat":
            db.add(UserQuestionStat(user_id=1, question_id=qid))
        elif kind == "practice":
            db.add(PracticeDayQuestion(user_id=1, exam_id=1, question_id=qid, local_date=date.today()))
    if kind == "job":
        db.add(BackgroundJob(job_type="unknown", scope_key="x", created_by=1, status="completed", payload_json='{"question_ids":[2]}'))
    if kind == "vector":
        db.add(VectorIndex(vector_type="question", ref_id="2", bank_id=13, text_content="secret"))
    if kind == "import":
        db.add(ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="parsing"))
    db.commit()
    group = plan(db)["groups"][0]
    expected = {
        "answer": "quiz_answers", "wrong": "wrong_answers", "stat": "user_question_stats",
        "practice": "practice_day_questions", "job": "background_reference",
        "vector": "vector_reference", "import": "active_import",
    }[kind]
    assert expected in group["blockers"], group
    assert not group["cascades"], group


def test_unknown_fk_table_blocked(pg, db):
    with pg.begin() as conn:
        conn.execute(text("CREATE TABLE future_reference (id serial primary key, question_id integer REFERENCES questions(id))"))
        conn.execute(text("INSERT INTO future_reference(question_id) VALUES (2)"))
    try:
        assert "unknown_question_reference" in plan(db)["groups"][0]["blockers"]
        db.rollback()
    finally:
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_reference"))


def test_dry_run_truly_readonly(pg, db):
    before = plan(db)["fingerprint"]
    db.rollback()
    with Session(pg) as readonly:
        readonly.execute(text("SET TRANSACTION READ ONLY"))
        assert readonly.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        assert plan(readonly)["fingerprint"] == before
        readonly.rollback()
    assert plan(db)["fingerprint"] == before


def test_apply_preserves_representative_metadata_source_words_and_rollback(db, tmp_path):
    topic1 = ExamTopic(exam_id=1, level=2, code="keep", name_en="Keep", name_zh="保留", short_name_zh="保留", source_version="test")
    topic2 = ExamTopic(exam_id=1, level=2, code="discard", name_en="Discard", name_zh="丢弃", short_name_zh="丢弃", source_version="test")
    db.add_all([topic1,topic2])
    db.flush()
    db.add_all([QuestionTopic(question_id=1, topic_id=topic1.id, source="manual"),QuestionTopic(question_id=2, topic_id=topic2.id, source="ai")])
    db.add(QuestionExplanation(question_id=2, model_id="test", input_fingerprint="a"*64, judged_answer="A", explanation_zh="Discard", analysis={}, generation_id=1))
    job = ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="imported")
    db.add(job)
    db.flush()
    db.add(ImportParsedQuestion(import_job_id=job.id, content="original", options_json=[], imported_question_id=2, import_status="imported", source_question_no="1"))
    db.add(UserBankWordProgress(user_id=1, bank_id=13, term="privacy", is_mastered=True))
    db.add(BankWordExclusion(bank_id=13, term="privacy", created_by=1))
    db.commit()
    proposed, before = audit(db, audit_id="test-audit")
    result, backup = apply(db, tmp_path, proposed)
    assert result["removed"] == 1
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700
    db.expire_all()
    assert db.get(Question, 2) is None
    keep = db.get(Question, 1)
    assert keep.content_zh is None and keep.explanation_zh == "代表解析"
    assert [r.topic_id for r in db.query(QuestionTopic)] == [topic1.id]
    source = db.query(ImportParsedQuestion).one()
    assert source.imported_question_id == 1 and source.content == "original" and source.import_status == "imported"
    word = db.query(BankWordFrequency).filter_by(term="privacy").one()
    assert (word.id, word.frequency, word.term_zh, word.definition, word.definition_zh) == (1,2,"保留翻译","retain","保留释义")
    assert db.query(UserBankWordProgress).one().is_mastered
    assert db.query(BankWordExclusion).one().term == "privacy"
    assert db.get(QuestionBank,13).question_count == 1
    assert execution.rollback_plan(db, execution.read_private(backup), maintenance="offline-maintenance-confirmed")["status"] == "restored"
    assert plan(db)["fingerprint"] == digest(before)
    assert execution.rollback_plan(db, execution.read_private(backup), maintenance="offline-maintenance-confirmed")["status"] == "already_restored_or_not_applied"


def test_plan_drift_and_maintenance_rejected(db, tmp_path):
    proposed = plan(db)
    with pytest.raises(DedupError, match="MAINTENANCE"):
        execution.apply_plan(db, proposed, confirmation=proposed["approval_digest"], backup_path=tmp_path/"x", maintenance="")
    db.get(Question,2).explanation_zh = "changed"
    db.commit()
    with pytest.raises(DedupError, match="PLAN_DRIFT"):
        apply(db,tmp_path,proposed)
    assert db.query(Question).count() == 2


def test_backup_failure_prevents_first_write(db,tmp_path,monkeypatch):
    before = plan(db)["fingerprint"]
    monkeypatch.setattr(execution,"write_private",lambda *a,**kw: (_ for _ in ()).throw(OSError("test")))
    with pytest.raises(OSError):
        apply(db,tmp_path)
    assert plan(db)["fingerprint"] == before


def test_transaction_failure_no_partial_commit(db,tmp_path,monkeypatch):
    before = plan(db)["fingerprint"]
    real = db.execute
    def execute(statement,*args,**kwargs):
        if str(statement).startswith("DELETE FROM questions"):
            raise RuntimeError("injected")
        return real(statement,*args,**kwargs)
    monkeypatch.setattr(db,"execute",execute)
    with pytest.raises(RuntimeError):
        apply(db,tmp_path)
    monkeypatch.setattr(db,"execute",real)
    assert plan(db)["fingerprint"] == before


def test_rollback_refuses_new_changes(db,tmp_path):
    _, backup = apply(db,tmp_path)
    db.get(Question,1).content_zh = "new user change"
    db.commit()
    with pytest.raises(DedupError, match="ROLLBACK_POST_IMAGE_DRIFT"):
        execution.rollback_plan(db,execution.read_private(backup),maintenance="offline-maintenance-confirmed")
    assert db.get(Question,1).content_zh == "new user change"


def test_rollback_detects_new_session_only_removed_id(db,tmp_path):
    _, backup = apply(db,tmp_path)
    session(db,[2])
    with pytest.raises(DedupError, match="ROLLBACK_POST_IMAGE_DRIFT"):
        execution.rollback_plan(db,execution.read_private(backup),maintenance="offline-maintenance-confirmed")


def test_word_content_cannot_be_discarded(db):
    db.add(BankWordFrequency(bank_id=13,term="unused",frequency=2,definition="valuable"))
    db.commit()
    assert "vocabulary_preservation" in plan(db)["groups"][0]["blockers"]


def test_all_blocked_no_backup_no_write(db,tmp_path):
    # 硬阻断（答案冲突）时必须整场拒绝：不写库、不创建备份。
    db.get(Question,2).correct_answer = "B"
    db.commit()
    before = plan(db)["fingerprint"]
    result,backup = apply(db,tmp_path)
    assert result["status"] == "no_changes" and not backup.exists()
    assert plan(db)["fingerprint"] == before


def test_semantic_confirmed_plan_still_explicit_and_transactional(db,tmp_path):
    from app.services.question_dedup_ai_service import candidates,evaluate_candidates,confirmed_semantic_plan
    db.get(Question,2).content = "privacy privacy controls ?"
    db.commit()
    base,state = audit(db,audit_id="test-audit")
    left,right = candidates(state["questions"])[0]
    raw = json.dumps({"pair":[left["id"],right["id"]],"verdict":"same","differences":[{"field":"content","category":"wording","evidence":"Only punctuation differs with identical meaning."}]})
    report = evaluate_candidates([(left,right)],audit_id=base["audit_id"],ledger_path=tmp_path/"private"/"ai.json",invoke=lambda _:raw)
    with pytest.raises(DedupError,match="NOT_CONFIRMED"):
        confirmed_semantic_plan(base,state,report,[[2,1]])
    proposed = confirmed_semantic_plan(base,state,report,[[1,2]])
    assert proposed["groups"][0]["kind"] == "semantic"
    assert proposed["summary"]["eligible_remove"] == 1
    result,backup = apply(db,tmp_path,proposed)
    assert result["removed"] == 1
    assert execution.rollback_plan(db,execution.read_private(backup),maintenance="offline-maintenance-confirmed")["status"] == "restored"


def test_option_translation_is_not_identity():
    first={"content":"test", "options":[{"key":"A","text":"one","text_zh":"一"},{"key":"B","text":"two","text_zh":"二"}]}
    second=deepcopy(first)
    second["options"][0]["text_zh"]="不同翻译"
    assert surface(first) == surface(second)


def test_backup_omits_import_and_background_credentials(db,tmp_path):
    db.add(ImportJob(bank_id=13,file_name="test",file_path="test",file_hash="a"*64,file_type="pdf",status="imported",config_json={"api_key":"PRIVATE_IMPORT_KEY"}))
    db.add(BackgroundJob(job_type="translation",scope_key="test",status="completed",created_by=1,payload_json='{"api_key":"PRIVATE_BACKGROUND_KEY","bank_id":13}'))
    db.commit()
    _,backup = apply(db,tmp_path)
    assert "PRIVATE_IMPORT_KEY" not in backup.read_text()
    assert "PRIVATE_BACKGROUND_KEY" not in backup.read_text()


def test_source_implicit_reference_blocks_without_rewriting_parse(db):
    job=ImportJob(bank_id=13,file_name="test",file_path="test",file_hash="a"*64,file_type="pdf",status="imported")
    db.add(job);db.flush()
    db.add(ImportParsedQuestion(import_job_id=job.id,content="original",options_json=[],duplicate_json={"existing_question_id":2}))
    db.commit()
    assert "implicit_import_reference" in plan(db)["groups"][0]["blockers"]


def test_rollback_id_collision_other_bank(db,tmp_path):
    _,backup=apply(db,tmp_path)
    db.execute(insert(Question.__table__).values(id=2,bank_id=15,question_type="single",content="new",options=[{"key":"A","text":"x"},{"key":"B","text":"y"}],correct_answer="A"))
    db.commit()
    # 当前范围指纹已变化；先拒绝图像漂移，无论冲突 ID 所属库。
    with pytest.raises(DedupError,match="ROLLBACK_POST_IMAGE_DRIFT|ROLLBACK_ID_CONFLICT"):
        execution.rollback_plan(db,execution.read_private(backup),maintenance="offline-maintenance-confirmed")


def test_private_paths_reject_symlinks_and_repository_unignored(tmp_path):
    real=tmp_path/"real";real.mkdir(mode=0o700)
    link=tmp_path/"link";link.symlink_to(real,target_is_directory=True)
    with pytest.raises(DedupError,match="UNSAFE_DIRECTORY"):
        execution.write_private(link/"secret.json",{"secret":"value"})
    with pytest.raises(DedupError,match="NOT_IGNORED"):
        execution.private_directory(Path(__file__).resolve().parents[2]/"backend")


def test_cli_default_and_invalid_scope_do_not_write_or_send_ai(db,pg,tmp_path):
    import os
    import subprocess
    cli=Path(__file__).resolve().parents[1]/"scripts/deduplicate_questions.py"
    before=plan(db)["fingerprint"]
    db.rollback()
    env={**os.environ,"DATABASE_URL":pg.url.render_as_string(hide_password=False),"AI_API_KEY":""}
    output=tmp_path/"private"/"audit.json"
    result=subprocess.run([sys.executable,str(cli),"--output",str(output),"--audit-id","test-audit"],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0,result.stderr
    summary=json.loads(result.stdout)
    assert summary["readonly"] is True and summary["summary"]["groups"] == 1
    assert "privacy" not in result.stdout and "代表解析" not in output.read_text()
    assert plan(db)["fingerprint"] == before
    result=subprocess.run([sys.executable,str(cli),"--user","other"],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode == 2 and "SCOPE_NOT_AUTHORIZED" in result.stderr


def test_cli_refuses_sqlite_without_connecting(tmp_path):
    import os
    import subprocess
    cli=Path(__file__).resolve().parents[1]/"scripts/deduplicate_questions.py"
    result=subprocess.run([sys.executable,str(cli)],env={**os.environ,"DATABASE_URL":"sqlite:///"+str(tmp_path/"do-not-create.db")},capture_output=True,text=True,timeout=30)
    assert result.returncode == 2 and "POSTGRESQL_REQUIRED" in result.stderr
    assert not (tmp_path/"do-not-create.db").exists()


def test_learning_and_retry_references_prevent_apply(db, tmp_path):
    for qid in (1, 2):
        session(db, [qid], completed=True)
        db.add(QuizAnswer(session_id=qid, question_id=qid, user_answer="A", is_correct=True))
        db.add(WrongAnswer(user_id=1, question_id=qid))
        db.add(UserQuestionStat(user_id=1, question_id=qid))
        db.add(PracticeDayQuestion(user_id=1, exam_id=1, question_id=qid, local_date=date.today()))
    db.add(BackgroundJob(job_type="translation", scope_key="keep-row", created_by=1, status="completed", subject_question_id=2, payload_json='{"bank_id":13}'))
    db.commit()
    proposed = plan(db)
    group = proposed["groups"][0]
    assert group["remove"] == [2]
    assert {"completed_session_retry", "quiz_answers", "wrong_answers", "user_question_stats", "practice_day_questions", "background_reference"} <= set(group["blockers"])
    assert not group["cascades"]
    assert proposed["summary"]["eligible_remove"] == 0
    before = proposed["fingerprint"]
    result, backup = apply(db, tmp_path, proposed)
    assert result == {"status": "no_changes", "removed": 0}
    assert not backup.exists()
    assert plan(db)["fingerprint"] == before


@pytest.mark.parametrize("kind", ["unfinished", "unfinished_keep", "completed", "answer", "wrong", "stat", "practice", "subject", "payload"])
def test_execution_rejects_protected_reference_even_if_audit_omits_blocker(db, tmp_path, monkeypatch, kind):
    if kind in {"unfinished", "unfinished_keep", "completed", "answer"}:
        session(db, [1] if kind == "unfinished_keep" else [1, 2], completed=not kind.startswith("unfinished"))
    if kind == "answer":
        db.add(QuizAnswer(session_id=1, question_id=2, user_answer="A", is_correct=True))
    if kind == "wrong":
        db.add(WrongAnswer(user_id=1, question_id=2))
    if kind == "stat":
        db.add(UserQuestionStat(user_id=1, question_id=2))
    if kind == "practice":
        db.add(PracticeDayQuestion(user_id=1, exam_id=1, question_id=2, local_date=date.today()))
    if kind in {"subject", "payload"}:
        db.add(BackgroundJob(job_type="translation", scope_key="protected", created_by=1, status="completed", subject_question_id=2 if kind == "subject" else None, payload_json='{"question_ids":[2]}' if kind == "payload" else '{}'))
    db.commit()
    proposed, pre = audit(db, audit_id="test-audit")
    group = proposed["groups"][0]
    # 故意模拟未来审计遗漏；执行层仍不得删除学习事实或破坏原题重做。
    group.update(keep=1, remove=[2], blockers=[], cascades=[])
    proposed.pop("approval_digest")
    proposed["approval_digest"] = digest(proposed)
    monkeypatch.setattr(execution, "audit", lambda *args, **kwargs: (proposed, pre))
    with pytest.raises(DedupError, match="PROTECTED_REFERENCE"):
        apply(db, tmp_path, proposed)
    assert db.query(Question).count() == 2
    assert not (tmp_path / "private" / "backup.json").exists()


@pytest.mark.parametrize("legacy_version", [1, 2])
def test_legacy_schema_version_plan_is_rejected(db, tmp_path, legacy_version):
    proposed = plan(db)
    legacy = json.loads(json.dumps({**proposed, "schema_version": legacy_version}))
    legacy.pop("approval_digest", None)
    legacy["approval_digest"] = digest(legacy)
    with pytest.raises(DedupError, match="PLAN_SCHEMA_VERSION_UNSUPPORTED"):
        execution.apply_plan(db, legacy, confirmation=legacy["approval_digest"], backup_path=tmp_path/"private"/"x.json", maintenance="offline-maintenance-confirmed")
    assert db.query(Question).count() == 2


def test_schema1_backup_is_explicitly_rejected_without_modifying_data(db, tmp_path):
    _, path = apply(db, tmp_path)
    backup = execution.read_private(path)
    backup["schema_version"] = 1
    before = plan(db)["fingerprint"]
    with pytest.raises(DedupError, match="INVALID_BACKUP"):
        execution.rollback_plan(db, backup, maintenance="offline-maintenance-confirmed")
    assert plan(db)["fingerprint"] == before


def test_legacy_schema2_backup_restores_learning_history_without_reenabling_apply(db, tmp_path):
    session(db, [1, 2], completed=True)
    db.add(QuizAnswer(session_id=1, question_id=2, user_answer="A", is_correct=True))
    db.add(WrongAnswer(user_id=1, question_id=2))
    db.add(UserQuestionStat(user_id=1, question_id=2))
    db.add(PracticeDayQuestion(user_id=1, exam_id=1, question_id=2, local_date=date.today()))
    db.add(BackgroundJob(job_type="translation", scope_key="legacy", created_by=1, status="completed", subject_question_id=2, payload_json='{}'))
    db.commit()
    legacy, pre = audit(db, audit_id="legacy")
    legacy["schema_version"] = 2
    group = legacy["groups"][0]
    group.update(keep=1, remove=[2], cascades=group["blockers"], blockers=[])
    legacy.pop("approval_digest")
    legacy["approval_digest"] = digest(legacy)
    # 独立复现旧版实际 SQL 结果，不调用现行 apply 或图像预演生成期望。
    for name in ("quiz_answers", "wrong_answers", "user_question_stats"):
        db.execute(text(f"DELETE FROM {name} WHERE question_id = 2"))
    db.execute(text("DELETE FROM questions WHERE id = 2"))
    db.execute(text("UPDATE question_banks SET question_count = 1 WHERE id = 13"))
    db.execute(text("UPDATE bank_word_frequencies SET frequency = frequency / 2 WHERE bank_id = 13"))
    db.commit()
    post, _ = execution.collect_state(db, Scope(), tracked_ids={1, 2}, tracked_job_ids={1})
    backup = {"schema_version": 2, "plan": legacy, "pre": pre, "post": post,
              "pre_digest": digest(pre), "post_digest": digest(post)}
    path = tmp_path / "private" / "legacy.json"
    execution.write_private(path, backup)
    saved = execution.read_private(path)
    assert execution.rollback_plan(db, saved, maintenance="offline-maintenance-confirmed") == {"status": "restored"}
    assert plan(db)["fingerprint"] == digest(pre)
    db.expire_all()
    assert db.query(QuizAnswer).one().question_id == 2
    assert db.query(WrongAnswer).one().question_id == 2
    assert db.query(UserQuestionStat).one().question_id == 2
    assert db.query(PracticeDayQuestion).one().question_id == 2
    assert db.query(BackgroundJob).one().subject_question_id == 2
    with pytest.raises(DedupError, match="PLAN_SCHEMA_VERSION_UNSUPPORTED"):
        apply(db, tmp_path, legacy)


def test_legacy_backup_reference_behavior_matches_live_foreign_keys(pg, db):
    # 仅旧备份恢复所用的预演必须匹配真实外键；新执行不使用此删除行为表。
    rows = db.execute(text("""
        SELECT rel.relname AS table_name, att.attname AS column_name, con.confdeltype AS deltype
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class frel ON frel.oid = con.confrelid
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
        WHERE con.contype = 'f' AND frel.relname = 'questions'
    """)).mappings().all()
    behavior = {"a": "explicit_delete", "r": "explicit_delete", "c": "cascade", "n": "set_null", "d": "explicit_delete"}
    live = {row["table_name"]: (row["column_name"], behavior[row["deltype"]]) for row in rows}
    assert live == execution.REFERENCING_TABLE_BEHAVIOR
    # 整行会消失的表（CASCADE 或工具显式删除）必须纳入回滚重建范围，否则整行丢失；
    # SET NULL 表只改指针、行本身保留，由回滚的指针恢复分支处理。
    deleted = {name for name, (_, kind) in live.items() if kind != "set_null"}
    assert not deleted - set(execution.RESTORE_ORDER), "随题整行删除的表必须纳入回滚重建范围"


def test_answer_conflict_and_learning_references_both_block_apply(db, tmp_path):
    # 答案冲突与会话/学习引用均为硬阻断，不相互掩盖。
    db.get(Question, 2).correct_answer = "B"
    for qid in (1, 2):
        session(db, [qid], completed=True)
        db.add(QuizAnswer(session_id=qid, question_id=qid, user_answer="B", is_correct=False))
    db.commit()
    proposed = plan(db)
    group = proposed["groups"][0]
    assert "answer_conflict" in group["blockers"]
    assert "quiz_answers" in group["blockers"]
    assert proposed["summary"]["eligible_remove"] == 0
    result, backup = apply(db, tmp_path, proposed)
    assert result["status"] == "no_changes" and not backup.exists()
    assert db.query(Question).count() == 2 and db.query(QuizAnswer).count() == 2


def test_saved_plan_json_roundtrip_can_be_applied(db,tmp_path):
    proposed=plan(db)
    path=tmp_path/"private"/"plan.json"
    execution.write_private(path,{"plan":proposed})
    loaded=execution.read_private(path)["plan"]
    # JSON把scope.bank_ids tuple变成list；不能把合法存盘计划误判为漂移。
    assert isinstance(loaded["scope"]["bank_ids"],list)
    result,backup=apply(db,tmp_path,loaded)
    assert result["removed"] == 1 and backup.exists()


def test_rollback_mid_transaction_failure_keeps_post_image(db,tmp_path,monkeypatch):
    _,backup=apply(db,tmp_path)
    post=plan(db)["fingerprint"]
    real=db.execute
    def failed(statement,*args,**kwargs):
        if str(statement).startswith("UPDATE bank_word_frequencies"):
            raise RuntimeError("restore interrupted after question insert")
        return real(statement,*args,**kwargs)
    monkeypatch.setattr(db,"execute",failed)
    with pytest.raises(RuntimeError):
        execution.rollback_plan(db,execution.read_private(backup),maintenance="offline-maintenance-confirmed")
    monkeypatch.setattr(db,"execute",real)
    assert plan(db)["fingerprint"] == post
    assert db.get(Question,2) is None


def test_rollback_unknown_session_cannot_be_ignored(db,tmp_path):
    _,backup=apply(db,tmp_path)
    session(db,[2])
    db.execute(update(QuizSession).values(question_ids='{"unknown":2}'))
    db.commit()
    with pytest.raises(DedupError,match="ROLLBACK_UNKNOWN_REFERENCE"):
        execution.rollback_plan(db,execution.read_private(backup),maintenance="offline-maintenance-confirmed")


@pytest.mark.parametrize("bank_id", [None, 15])
def test_review_vector_direct_id_outside_bank_column_blocks(db, tmp_path, bank_id):
    db.add(VectorIndex(vector_type="question", ref_id="2", bank_id=bank_id, text_content="PRIVATE_VECTOR_SURFACE"))
    db.commit()
    proposed, state = audit(db, audit_id="test-audit")
    assert "vector_reference" in proposed["groups"][0]["blockers"]
    assert "PRIVATE_VECTOR_SURFACE" not in json.dumps(state, default=str)
    result, backup = apply(db, tmp_path, proposed)
    assert result["status"] == "no_changes" and not backup.exists()
    assert db.query(Question).count() == 2


@pytest.mark.parametrize("field,value", [
    ("terms", [{"api_key": "PRIVATE_NESTED_KEY"}]),
    ("term", {"api_key": "PRIVATE_NESTED_KEY"}),
    ("bank_id", {"api_key": "PRIVATE_NESTED_KEY"}),
])
def test_review_unknown_background_projection_does_not_leak_credentials(db, tmp_path, field, value):
    db.add(BackgroundJob(job_type="unknown", scope_key="review", created_by=1, status="completed", payload_json=json.dumps({field:value})))
    db.commit()
    proposed, state = audit(db, audit_id="test-audit")
    assert "PRIVATE_NESTED_KEY" not in json.dumps(state, default=str)
    assert "unknown_background_payload" in proposed["groups"][0]["blockers"]
    result, backup = apply(db, tmp_path, proposed)
    assert result["status"] == "no_changes" and not backup.exists()


@pytest.mark.parametrize("value", ["unknown text", 2, True])
def test_review_unknown_import_reference_roots_block(db, value):
    job = ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="imported")
    db.add(job)
    db.flush()
    db.add(ImportParsedQuestion(import_job_id=job.id, content="original", options_json=[], duplicate_json=value))
    db.commit()
    assert "unknown_import_reference" in plan(db)["groups"][0]["blockers"]


def test_review_indirect_cascade_reference_blocks(pg, db, tmp_path):
    db.add(QuestionExplanation(question_id=2, model_id="test", input_fingerprint="a"*64, judged_answer="A", explanation_zh="discard", analysis={}, generation_id=1))
    db.commit()
    with pg.begin() as conn:
        conn.execute(text("CREATE TABLE future_evidence (id serial primary key, explanation_id integer REFERENCES question_explanations(id) ON DELETE CASCADE)"))
        conn.execute(text("INSERT INTO future_evidence(explanation_id) SELECT id FROM question_explanations WHERE question_id=2"))
    try:
        proposed = plan(db)
        assert "unknown_question_reference" in proposed["groups"][0]["blockers"]
        result, backup = apply(db, tmp_path, proposed)
        assert result["status"] == "no_changes" and not backup.exists()
        assert db.execute(text("SELECT count(*) FROM future_evidence")).scalar_one() == 1
        db.rollback()
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_evidence"))


@pytest.mark.parametrize("kind,qid", [("explanation", 1), ("explanation", 2), ("topic", 1), ("topic", 2)])
def test_review_unknown_attachment_fk_respects_keep_and_composite_key(pg, db, tmp_path, kind, qid):
    if kind == "explanation":
        db.add(QuestionExplanation(question_id=qid, model_id="test", input_fingerprint="a"*64, judged_answer="A", explanation_zh="metadata", analysis={}, generation_id=1))
        db.commit()
        ddl = "CREATE TABLE future_attachment (id serial primary key, ref integer REFERENCES question_explanations(id) ON DELETE CASCADE, secret text)"
        add = "INSERT INTO future_attachment(ref,secret) SELECT id,'PRIVATE_ATTACHMENT_SECRET' FROM question_explanations"
    else:
        topic = ExamTopic(exam_id=1, level=2, code="review", name_en="Review", name_zh="复核", short_name_zh="复核", source_version="test")
        db.add(topic)
        db.flush()
        db.add(QuestionTopic(question_id=qid, topic_id=topic.id, source="manual"))
        db.commit()
        ddl = "CREATE TABLE future_attachment (id serial primary key, qid integer, tid integer, secret text, FOREIGN KEY (qid,tid) REFERENCES question_topics(question_id,topic_id) ON DELETE CASCADE)"
        add = "INSERT INTO future_attachment(qid,tid,secret) SELECT question_id,topic_id,'PRIVATE_ATTACHMENT_SECRET' FROM question_topics"
    with pg.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text(add))
    try:
        proposed, state = audit(db, audit_id="test-audit")
        assert "PRIVATE_ATTACHMENT_SECRET" not in json.dumps(state, default=str)
        assert ("unknown_question_reference" in proposed["groups"][0]["blockers"]) is (qid == 2)
        result, backup = apply(db, tmp_path, proposed)
        assert result["status"] == ("no_changes" if qid == 2 else "applied")
        assert db.execute(text("SELECT count(*) FROM future_attachment")).scalar_one() == 1
        if backup.exists():
            assert "PRIVATE_ATTACHMENT_SECRET" not in backup.read_text()
            assert execution.rollback_plan(db, execution.read_private(backup), maintenance="offline-maintenance-confirmed")["status"] == "restored"
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_attachment"))


@pytest.mark.parametrize("disappears", [False, True])
def test_review_unknown_word_fk_only_blocks_row_deletion(pg, db, tmp_path, disappears):
    if disappears:
        for row in db.query(Question):
            row.content += " ephemeral"
        db.add(BankWordFrequency(bank_id=13, term="ephemeral", frequency=2))
        db.commit()
    term = "ephemeral" if disappears else "privacy"
    with pg.begin() as conn:
        conn.execute(text("CREATE TABLE future_word_reference (id serial primary key, word_id integer REFERENCES bank_word_frequencies(id) ON DELETE CASCADE, secret text)"))
        conn.execute(text("INSERT INTO future_word_reference(word_id,secret) SELECT id,'PRIVATE_WORD_SECRET' FROM bank_word_frequencies WHERE term=:term"), {"term": term})
    try:
        proposed, state = audit(db, audit_id="test-audit")
        assert "PRIVATE_WORD_SECRET" not in json.dumps(state, default=str)
        assert ("unknown_derived_reference" in proposed["groups"][0]["blockers"]) is disappears
        result, backup = apply(db, tmp_path, proposed)
        assert result["status"] == ("no_changes" if disappears else "applied")
        assert db.execute(text("SELECT count(*) FROM future_word_reference")).scalar_one() == 1
        if backup.exists():
            assert "PRIVATE_WORD_SECRET" not in backup.read_text()
            assert execution.rollback_plan(db, execution.read_private(backup), maintenance="offline-maintenance-confirmed")["status"] == "restored"
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_word_reference"))


def test_review_cli_rejects_code_default_placeholder_before_engine(monkeypatch):
    import runpy
    cli = Path(__file__).resolve().parents[1]/"scripts/deduplicate_questions.py"
    namespace = runpy.run_path(str(cli))
    # 拼接占位串，避免静态凭据扫描器把它当成真实配置。
    placeholder = "postgresql+psycopg://" + "user" + ":" + "pass" + "@localhost:5432/quiz"
    monkeypatch.setenv("DATABASE_URL", placeholder)
    with pytest.raises(DedupError, match="EXPLICIT_POSTGRESQL_REQUIRED"):
        namespace["configured_url"]()


def test_review_cli_ai_ends_transaction_and_uses_fixed_pure_adapter(db, pg, tmp_path, monkeypatch, capsys):
    import runpy
    from app.services import ai_service, settings_service
    db.get(Question, 2).content += " ?"
    db.commit()
    cli = Path(__file__).resolve().parents[1]/"scripts/deduplicate_questions.py"
    namespace = runpy.run_path(str(cli))
    monkeypatch.setenv("DATABASE_URL", pg.url.render_as_string(hide_password=False))
    seen = {}
    config = {"base_url": "https://test.invalid", "api_key": "PRIVATE_ADAPTER_KEY", "model": "deepseek-v4.1-flash"}
    def resolve(current, **kwargs):
        assert current.in_transaction()
        assert kwargs == {"model": "deepseek-v4.1-flash", "scene": "default"}
        seen["db"] = current
        return config
    def invoke(messages, current, **kwargs):
        assert current is None and not seen["db"].in_transaction()
        assert kwargs == {"scene": "default", "timeout": 60, "ai_config": config, "reasoning_effort": None}
        supplied = json.loads(messages[1]["content"])
        assert all(set(q) == {"id", "content", "options"} for q in supplied)
        assert "PRIVATE_ADAPTER_KEY" not in json.dumps(messages)
        seen["called"] = True
        return json.dumps({"pair": [q["id"] for q in supplied], "verdict": "same", "differences": [{"field": "content", "category": "wording", "evidence": "Only punctuation differs with identical meaning."}]})
    monkeypatch.setattr(settings_service, "get_effective_ai_settings", resolve)
    monkeypatch.setattr(ai_service, "call_ai_api", invoke)
    output = tmp_path/"private"/"ai-report.json"
    code = namespace["main"](["--ai", "--output", str(output), "--ledger", str(tmp_path/"private"/"ledger.json"), "--audit-id", "test-audit"])
    assert code == 0 and seen["called"]
    captured = capsys.readouterr()
    assert "privacy" not in captured.out and "PRIVATE_ADAPTER_KEY" not in captured.out
    assert execution.read_private(output)["ai"]["requests_total"] == 1
    assert db.query(Question).count() == 2


def test_review_raw_summary_counts_subgroups_inside_mixed_normalized_group(db, tmp_path):
    db.get(Question, 2).content = "  privacy\nprivacy controls  "
    original = db.get(Question, 1)
    db.add(Question(bank_id=13, question_type=original.question_type, content=original.content, options=original.options, correct_answer=original.correct_answer))
    db.commit()
    proposed = plan(db)
    assert proposed["groups"][0]["raw_equal"] is False
    assert proposed["summary"]["groups"] == 1
    assert (proposed["summary"]["members"], proposed["summary"]["redundant"]) == (3, 2)
    raw = proposed["raw_equal_summary"]
    assert raw["totals"] == {"groups": 1, "members": 2, "redundant": 1}
    assert raw["by_bank"] == [{"bank_id": 13, "groups": 1, "members": 2, "redundant": 1}, {"bank_id": 15, "groups": 0, "members": 0, "redundant": 0}]
    assert raw["relationship"] == "included_in_whitespace_normalized_not_additive"
    saved = tmp_path/"private"/"plan.json"
    execution.write_private(saved, proposed)
    restored = execution.read_private(saved)
    assert restored["approval_digest"] == digest({k: v for k, v in restored.items() if k != "approval_digest"})
    assert restored["raw_equal_summary"] == raw
    # 新增原值统计不改变其他计划字段语义，存盘后仍可完整重验/执行。
    result, _ = apply(db, tmp_path, restored)
    assert result["removed"] == 2


def test_review_cross_scope_source_implicit_reference_is_protected_without_reading_surface(db):
    other = Exam(owner_id=1, slug="other", name="Other", short_name="O")
    db.add(other)
    db.flush()
    bank = QuestionBank(id=99, exam_id=other.id, name="Outside")
    db.add(bank)
    db.flush()
    job = ImportJob(bank_id=99, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="imported")
    db.add(job)
    db.flush()
    db.add(ImportParsedQuestion(import_job_id=job.id, content="PRIVATE_OUTSIDE_SURFACE", options_json=[], duplicate_json={"nested": {"existing_question_id": 2}}))
    db.commit()
    proposed, state = audit(db, audit_id="test-audit")
    assert "implicit_import_reference" in proposed["groups"][0]["blockers"]
    assert "PRIVATE_OUTSIDE_SURFACE" not in json.dumps(state, default=str)


def test_review_vector_metadata_only_reference_is_protected_without_text(db):
    db.add(VectorIndex(vector_type="unknown", ref_id="external", bank_id=None, text_content="PRIVATE_OUTSIDE_VECTOR", metadata_json={"nested": {"question_ids": [2]}}))
    db.commit()
    proposed, state = audit(db, audit_id="test-audit")
    assert "vector_reference" in proposed["groups"][0]["blockers"]
    assert "PRIVATE_OUTSIDE_VECTOR" not in json.dumps(state, default=str)


def test_review_optional_null_source_reference_is_not_unknown(db):
    job = ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="imported")
    db.add(job)
    db.flush()
    db.add(ImportParsedQuestion(import_job_id=job.id, content="original", options_json=[], duplicate_json={"existing_question_id": None}))
    db.commit()
    assert not plan(db)["groups"][0]["blockers"]


def test_review_unknown_foreign_background_scope_cannot_be_assumed_unrelated(db):
    user = User(username="other", email="other@test.invalid", password_hash="test")
    db.add(user)
    db.flush()
    db.add(BackgroundJob(job_type="unknown", scope_key="review-foreign", created_by=user.id, status="completed", payload_json='{"bank_id":"13","api_key":"PRIVATE_FOREIGN_KEY"}'))
    db.commit()
    proposed, state = audit(db, audit_id="test-audit")
    assert "unknown_background_payload" in proposed["groups"][0]["blockers"]
    assert "PRIVATE_FOREIGN_KEY" not in json.dumps(state, default=str)


def test_review_scoped_source_keep_reference_does_not_break_post_image(db, tmp_path):
    job = ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="imported")
    db.add(job)
    db.flush()
    db.add(ImportParsedQuestion(import_job_id=job.id, content="original", options_json=[], imported_question_id=2, duplicate_json={"existing_question_id": 1}))
    db.commit()
    result, backup = apply(db, tmp_path)
    assert result["status"] == "applied"
    db.expire_all()
    source = db.query(ImportParsedQuestion).one()
    assert source.imported_question_id == 1 and source.duplicate_json == {"existing_question_id": 1}
    assert execution.rollback_plan(db, execution.read_private(backup), maintenance="offline-maintenance-confirmed")["status"] == "restored"


def test_review_raw_summary_does_not_count_normalized_invalid_option_keys(db):
    for row in db.query(Question):
        row.options = [{"key": "A", "text": "one"}, {"key": " A ", "text": "two"}]
    db.commit()
    proposed = plan(db)
    assert proposed["invalid_question_ids"] == [1, 2]
    assert proposed["summary"]["groups"] == 0
    assert proposed["raw_equal_summary"]["totals"] == {"groups": 0, "members": 0, "redundant": 0}


@pytest.mark.parametrize("status", ["imported", "partial_imported", "review_required", "unimported", "failed", "cancelled"])
def test_import_job_domain_quiescent_status_is_not_running(db, status):
    db.add(ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status=status))
    db.commit()
    proposed = plan(db)
    assert "active_import" not in proposed["groups"][0]["blockers"]
    assert proposed["summary"]["eligible_remove"] == 1


@pytest.mark.parametrize("status", ["pending", "extracting", "chunking", "parsing", "validating", "importing", "completed", "processing", "future_status", ""])
def test_import_job_domain_running_or_unknown_status_is_blocked(db, status):
    db.add(ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status=status))
    db.commit()
    proposed = plan(db)
    assert "active_import" in proposed["groups"][0]["blockers"]
    assert proposed["summary"]["eligible_remove"] == 0


@pytest.mark.parametrize("status", ["queued", "running", "retrying"])
def test_import_job_quiescent_does_not_hide_active_background(db, status):
    db.add(ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="review_required"))
    db.add(BackgroundJob(job_type="question_import_llm", scope_key="review-active", created_by=1, status=status, payload_json='{"bank_id":13}'))
    db.commit()
    proposed = plan(db)
    assert "active_import" not in proposed["groups"][0]["blockers"]
    assert "active_background" in proposed["groups"][0]["blockers"]
    assert proposed["summary"]["eligible_remove"] == 0


def test_import_job_waiting_review_still_protects_source_and_unfinished_session(db):
    from app.models.import_review_item import ImportReviewItem
    job = ImportJob(bank_id=13, file_name="test", file_path="test", file_hash="a"*64, file_type="pdf", status="review_required")
    db.add(job)
    db.flush()
    source = ImportParsedQuestion(import_job_id=job.id, content="original", options_json=[])
    db.add(source)
    db.flush()
    db.add(ImportReviewItem(import_job_id=job.id, parsed_question_id=source.id, status="pending", before_json={"existing_question_id": 2}))
    db.commit()
    session(db, [1, 2])
    proposed = plan(db)
    group = proposed["groups"][0]
    assert "active_import" not in group["blockers"]
    assert "implicit_import_reference" in group["blockers"]
    assert "unfinished_session" in group["blockers"]
    assert proposed["summary"]["eligible_remove"] == 0


def test_import_job_domain_status_contract_matches_actual_finalizer():
    import ast
    import inspect
    from app.services.question_dedup_service import IMPORT_JOB_QUIESCENT_STATUSES
    from app.services.smart_import_service import IMPORT_JOB_STATUSES, _finalize_import
    finalizer = ast.parse(inspect.getsource(_finalize_import))
    final_statuses = {
        node.value.value for node in ast.walk(finalizer)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and any(isinstance(target, ast.Attribute) and target.attr == "status" for target in node.targets)
    }
    assert final_statuses == {"imported", "partial_imported", "review_required", "unimported"}
    assert IMPORT_JOB_QUIESCENT_STATUSES == final_statuses | {"failed", "cancelled"}
    assert IMPORT_JOB_STATUSES == IMPORT_JOB_QUIESCENT_STATUSES | {"pending", "extracting", "chunking", "parsing", "validating", "importing"}
