"""结构非法题一次性修复脚本：dry-run/apply、外键行为、词频与归属校验。

只跑隔离 PostgreSQL 与本地构造数据，不连接业务库、不调用模型。
"""
import json
from datetime import date
from pathlib import Path
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base
from app.models import (
    BackgroundJob, BankWordExclusion, BankWordFrequency, Exam, ExamTopic, ImportJob,
    ImportParsedQuestion, PracticeDayQuestion, Question, QuestionBank, QuestionExplanation,
    QuestionTopic, QuizAnswer, QuizSession, User, UserBankWordProgress, UserQuestionStat,
    VectorIndex, WrongAnswer,
)
from app.services.question_dedup_service import DedupError, Scope as DedupScope, audit, surface
from scripts.fix_malformed_questions import (
    AUTHORIZED_IDS, DELETE_IDS, KEY_REPAIRS, FixError, Scope, fix_questions, parse_question_ids,
)
from postgres_support import isolated_postgres

ALL_IDS = tuple(sorted(AUTHORIZED_IDS))


def _same_as_3530(question_id):
    return Question(id=question_id, bank_id=13, question_type="single", content="enduring",
                    options=[{"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"}],
                    correct_answer="A")


@pytest.fixture(scope="module")
def pg():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def db(pg):
    """与生产同形状的 7 道现场：4 道无选项题（A 类）+ 3 道第四个 key 误标 C 的题（B 类）。"""
    with pg.begin() as conn:
        names = ",".join('"' + name + '"' for name in Base.metadata.tables)
        conn.execute(text("TRUNCATE " + names + " RESTART IDENTITY CASCADE"))
    with Session(pg) as db:
        user = User(username="nianyu", email="nianyu@test.invalid", password_hash="test")
        other = User(username="other", email="other@test.invalid", password_hash="test")
        db.add_all([user, other])
        db.flush()
        exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
        foreign = Exam(owner_id=other.id, slug="cipt", name="Other", short_name="O")
        db.add_all([exam, foreign])
        db.flush()
        db.add_all([
            QuestionBank(id=13, exam_id=exam.id, name="官方题库", question_count=7),
            QuestionBank(id=15, exam_id=exam.id, name="CIPT-其他", question_count=1),
            QuestionBank(id=77, exam_id=foreign.id, name="外部题库", question_count=0),
        ])
        db.flush()
        db.add_all([
            # A 类：源 PDF 无选项（options 为空）。前 3 道共享 "disappearing"，
            # 第 4 道额外带 "enduring audits"，让残留词与消失词都出现。
            Question(id=3072, bank_id=13, question_type="single", content="disappearing", options=[], correct_answer="D"),
            Question(id=3372, bank_id=13, question_type="single", content="disappearing", options=[], correct_answer="D"),
            Question(id=3376, bank_id=13, question_type="single", content="disappearing", options=[], correct_answer="B"),
            Question(id=3386, bank_id=13, question_type="single", content="enduring disappearing audits", options=[], correct_answer="D"),
            # B 类：第四个选项 key 误标为 C，修正不得改变 answer。
            Question(id=3520, bank_id=13, question_type="single", content="enduring", options=[
                {"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"},
                {"key": "C", "text": "charlie"}, {"key": "C", "text": "Pseudonymization"},
            ], correct_answer="B"),
            Question(id=3522, bank_id=13, question_type="single", content="enduring", options=[
                {"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"},
                {"key": "C", "text": "Masking", "text_zh": "掩码"},
                {"key": "C", "text": "Tokenization", "text_zh": "掩码"},
            ], correct_answer="A"),
            Question(id=3530, bank_id=13, question_type="single", content="enduring",
                     options=[{"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"}], correct_answer="A"),
            Question(id=3771, bank_id=15, question_type="single", content="safeguards", options=[
                {"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"},
                {"key": "C", "text": "charlie"}, {"key": "C", "text": "Pseudonymization"},
            ], correct_answer="B"),
        ])
        # 词表：4 行由全库题面派生；"enduring" 带翻译/释义与学习进度（必须保留），
        # "disappearing" 无内容（可随题面消失）。
        db.add_all([
            BankWordFrequency(id=1, bank_id=13, term="disappearing", frequency=4),
            BankWordFrequency(id=2, bank_id=13, term="enduring", frequency=4,
                              term_zh="持久", definition="lasting", definition_zh="持久的"),
            BankWordFrequency(id=3, bank_id=13, term="alpha", frequency=3),
            BankWordFrequency(id=4, bank_id=13, term="biometrics", frequency=3),
        ])
        topic = ExamTopic(exam_id=exam.id, level=2, code="t1", name_en="Topic",
                          name_zh="考点", short_name_zh="考点", source_version="test")
        db.add(topic)
        db.flush()
        # 关联记录：CASCADE 三张、NO ACTION 三张、SET NULL 指针、无外键的来源指针。
        db.add_all([
            QuestionTopic(question_id=3372, topic_id=topic.id, source="manual"),
            QuestionExplanation(question_id=3372, model_id="test", input_fingerprint="a" * 64,
                                judged_answer="D", explanation_zh="discard", analysis={}, generation_id=1),
        ])
        db.add(QuizSession(id=1, user_id=user.id, bank_id=13, mode="random", total_questions=1,
                           question_ids=json.dumps([3072]), is_completed=True,
                           question_snapshot=[{"question_id": 3072}]))
        db.flush()
        db.add_all([
            QuizAnswer(session_id=1, question_id=3072, user_answer="D", is_correct=True),
            WrongAnswer(user_id=user.id, question_id=3376),
            UserQuestionStat(user_id=user.id, question_id=3386),
            PracticeDayQuestion(user_id=user.id, exam_id=exam.id, local_date=date(2026, 5, 28), question_id=3372),
            BackgroundJob(job_type="translation", scope_key="keep-row", created_by=user.id,
                          status="completed", subject_question_id=3386, payload_json='{"bank_id":13}'),
        ])
        job = ImportJob(bank_id=13, file_name="f.pdf", file_path="/tmp/f.pdf", file_hash="a" * 64,
                        file_type="pdf", status="imported")
        db.add(job)
        db.flush()
        db.add(ImportParsedQuestion(import_job_id=job.id, content="source stem", options_json=[],
                                    imported_question_id=3072, import_status="imported",
                                    source_question_no="1"))
        db.add(UserBankWordProgress(user_id=user.id, bank_id=13, term="enduring", is_mastered=True))
        db.commit()
        yield db
        db.rollback()


@pytest.fixture
def unreferenced_db(db):
    """保留全部历史行，但只关联存活题；成功删除用例不得依赖删除历史。"""
    for model in (QuizAnswer, WrongAnswer, UserQuestionStat, PracticeDayQuestion):
        for row in db.query(model).all():
            row.question_id = 3530
    session = db.get(QuizSession, 1)
    session.question_ids = json.dumps([3530])
    session.question_snapshot = [{"question_id": 3530}]
    db.commit()
    return db


def _options(db, question_id):
    return db.get(Question, question_id).options


def test_authorization_table_matches_prd():
    assert sorted(AUTHORIZED_IDS) == [3072, 3372, 3376, 3386, 3520, 3522, 3771]
    assert DELETE_IDS == (3072, 3372, 3376, 3386)
    assert set(KEY_REPAIRS) == {3520, 3522, 3771}


def test_parse_question_ids_rejects_ambiguous_input():
    assert parse_question_ids("3072,3372") == (3072, 3372)
    # 只认 ASCII 数字：全角/阿拉伯-印度数字不能被当成操作者本意的输入。
    for raw in ("", "3072,", "3072,3072", "0", "-1", "3072,abc", "٣٠٧٢"):
        with pytest.raises(FixError, match="INVALID_QUESTION_IDS"):
            parse_question_ids(raw)


def test_audit_sees_seven_invalid_questions_before_fix(db):
    proposed, _state = audit(db, audit_id="test-audit")
    assert proposed["invalid_question_ids"] == sorted(AUTHORIZED_IDS)
    with pytest.raises(DedupError, match="INVALID_OPTIONS"):
        surface({"content": "disappearing", "options": []})
    with pytest.raises(DedupError, match="INVALID_OPTION_KEYS"):
        surface({"content": "enduring", "options": _options(db, 3520)})


def test_dry_run_validates_without_writing(unreferenced_db):
    db = unreferenced_db
    result = fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS)
    assert result.mode == "dry_run"
    assert result.deleted == [3072, 3372, 3376, 3386]
    assert [fix["question_id"] for fix in result.key_fixes] == [3520, 3522, 3771]
    assert result.import_pointers_cleared == 1
    assert result.banks == [{"bank_id": 13, "question_count": 3, "words_updated": 1, "words_deleted": 1}], result.banks
    db.expire_all()
    assert db.query(Question).count() == 8
    assert _options(db, 3520)[3]["key"] == "C"
    assert db.query(QuizAnswer).count() == 1 and db.query(BankWordFrequency).count() == 4
    assert db.get(QuestionBank, 13).question_count == 7
    assert db.query(QuestionExplanation).count() == 1


def test_apply_deletes_class_a_and_repairs_class_b(unreferenced_db):
    db = unreferenced_db
    result = fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    assert result.mode == "apply"
    db.expire_all()
    assert sorted(row.id for row in db.query(Question).all()) == [3520, 3522, 3530, 3771]
    # 第四个选项 key C → D：顺序与答案不变；3522 的中文漏译一并纠正。
    assert [(option["key"], option["text"]) for option in _options(db, 3520)] == [
        ("A", "alpha"), ("B", "biometrics"), ("C", "charlie"), ("D", "Pseudonymization")]
    options = _options(db, 3522)
    assert [(option["key"], option["text"]) for option in options] == [
        ("A", "alpha"), ("B", "biometrics"), ("C", "Masking"), ("D", "Tokenization")]
    assert [option.get("text_zh") for option in options] == [None, None, "掩码", "令牌化"]
    assert [(option["key"], option["text"]) for option in _options(db, 3771)] == [
        ("A", "alpha"), ("B", "biometrics"), ("C", "charlie"), ("D", "Pseudonymization")]
    assert [db.get(Question, qid).correct_answer for qid in (3520, 3522, 3771)] == ["B", "A", "B"]
    for question in db.query(Question).all():
        surface({"content": question.content, "options": question.options})


def test_apply_handles_foreign_keys_per_database_behavior(unreferenced_db):
    db = unreferenced_db
    fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    # 可替代的解析/考点随题删除；学习历史只引用保留题，必须原样保留。
    assert db.query(QuestionTopic).count() == 0
    assert db.query(QuestionExplanation).count() == 0
    for model in (PracticeDayQuestion, QuizAnswer, WrongAnswer, UserQuestionStat):
        assert db.query(model).one().question_id == 3530
    # SET NULL：后台任务行保留，指针置空；会话是 JSON 引用，不重写。
    job = db.query(BackgroundJob).one()
    assert job.subject_question_id is None and job.scope_key == "keep-row"
    session = db.get(QuizSession, 1)
    assert session.question_ids == json.dumps([3530]) and session.is_completed
    assert session.question_snapshot == [{"question_id": 3530}]
    # import_parsed_questions.imported_question_id 无外键：溯源行保留、指针显式置 NULL。
    source = db.query(ImportParsedQuestion).one()
    assert source.imported_question_id is None and source.content == "source stem"
    assert source.import_status == "imported"


def test_apply_recomputes_counts_and_preserves_surviving_word_metadata(unreferenced_db):
    db = unreferenced_db
    fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.get(QuestionBank, 13).question_count == 3
    assert db.get(QuestionBank, 15).question_count == 1
    words = {row.term: row for row in db.query(BankWordFrequency).all()}
    # "disappearing" 只出现在被删题面里且无内容/进度/任务 → 词行随题面消失。
    assert "disappearing" not in words
    # surviving 词只改 frequency：ID、词译与双语释义原样保留。
    enduring = words["enduring"]
    assert (enduring.id, enduring.frequency, enduring.term_zh, enduring.definition, enduring.definition_zh) == (2, 3, "持久", "lasting", "持久的")
    assert (words["alpha"].id, words["alpha"].frequency) == (3, 3)
    assert (words["biometrics"].id, words["biometrics"].frequency) == (4, 3)
    assert db.query(UserBankWordProgress).one().is_mastered


def test_key_only_batch_leaves_questions_and_counts_untouched(db):
    # 只给 B 类（key 修正）时：不删题、不动词频、不改题库计数，只把 options 写回。
    result = fix_questions(db, Scope("nianyu", "cipt"), (3520, 3522, 3771), apply=True)
    db.expire_all()
    assert result.deleted == [] and result.banks == []
    assert result.import_pointers_cleared == 0 and db.query(Question).count() == 8
    assert db.get(QuestionBank, 13).question_count == 7
    assert [row.term for row in db.query(BankWordFrequency).order_by(BankWordFrequency.id)] == [
        "disappearing", "enduring", "alpha", "biometrics"]
    assert db.query(QuizAnswer).count() == 1 and db.query(QuestionExplanation).count() == 1
    assert db.query(BackgroundJob).one().subject_question_id == 3386
    for question_id in (3520, 3522, 3771):
        surface({"content": db.get(Question, question_id).content, "options": _options(db, question_id)})


def test_audit_is_clean_after_apply_and_dedup_group_can_execute(unreferenced_db):
    db = unreferenced_db
    fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.add(_same_as_3530(3531))
    db.commit()
    proposed, _state = audit(db, audit_id="test-audit")
    assert proposed["invalid_question_ids"] == []
    assert proposed["summary"]["hard_blocked_groups"] == 0
    assert proposed["summary"]["eligible_remove"] == 1
    group = proposed["groups"][0]
    assert group["remove"] == [3531] and group["blockers"] == []


def test_dedup_word_check_passes_after_fix(unreferenced_db):
    db = unreferenced_db
    # 修复必须让判重工具的 word_changes 也通过，否则清理推不动：
    # 1) 只出现在被删题面里的词行必须被脚本删掉（否则 missing_derived_terms）；
    # 2) 被 bank_word_exclusions 排除但仍可从剩余题面派生的词行不能被删（同样会缺词）。
    db.add(BankWordExclusion(bank_id=13, term="enduring", created_by=1))
    db.commit()
    fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.add(_same_as_3530(3531))
    db.commit()
    db.expire_all()
    proposed, _state = audit(db, audit_id="test-audit")
    assert proposed["invalid_question_ids"] == []
    assert proposed["groups"][0]["blockers"] == []
    assert proposed["summary"]["eligible_remove"] == 1


def test_remaining_malformed_question_keeps_bank_surface_blocked(unreferenced_db):
    db = unreferenced_db
    # 只修 A 类（B 类仍是非法题面）时，任何组仍被 invalid_bank_surface 硬阻断；
    # 证明"清空 invalid_bank_surface"确实需要这 7 道全修完。
    fix_questions(db, Scope("nianyu", "cipt"), (3072, 3372, 3376, 3386), apply=True)
    db.add(_same_as_3530(3531))
    db.commit()
    db.expire_all()
    proposed, _state = audit(db, audit_id="test-audit")
    assert proposed["invalid_question_ids"] == [3520, 3522, 3771]
    group = proposed["groups"][0]
    assert "invalid_bank_surface" in group["blockers"]
    assert proposed["summary"]["eligible_remove"] == 0


def test_scope_and_ownership_are_enforced_before_any_write(db):
    for scope, expected in (
        (Scope("ghost", "cipt"), "OWNER_NOT_FOUND"),
        (Scope("nianyu", "missing"), "EXAM_NOT_FOUND"),
        # 另一个属主也有同名 slug：它不是脚本的目标考试项目。
        (Scope("other", "cipt"), "QUESTION_NOT_IN_SCOPE"),
    ):
        with pytest.raises(FixError, match=expected):
            fix_questions(db, scope, (3072,), apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8 and db.get(Question, 3072) is not None
    # 把授权 ID 挪到范围外题库：归属校验拒绝，而不是照 ID 直接改。
    db.get(Question, 3372).bank_id = 77
    db.commit()
    with pytest.raises(FixError, match="QUESTION_NOT_IN_SCOPE"):
        fix_questions(db, Scope("nianyu", "cipt"), (3372,), apply=True)
    db.expire_all()
    assert db.get(Question, 3372).bank_id == 77
    # 本属主名下但不在 (13, 15) 的题库同样拒绝（bank 12 不在任务范围）。
    db.get(Question, 3372).bank_id = 12
    db.add(QuestionBank(id=12, exam_id=1, name="越界题库", question_count=0))
    db.commit()
    with pytest.raises(FixError, match="QUESTION_NOT_IN_SCOPE"):
        fix_questions(db, Scope("nianyu", "cipt"), (3372,), apply=True)
    db.expire_all()
    assert db.get(Question, 3372).bank_id == 12


def test_authorization_whitelist_rejects_unauthorized_ids(db):
    for question_id in (9999, 1, 0):
        with pytest.raises(FixError, match="UNKNOWN_QUESTION_ID"):
            fix_questions(db, Scope("nianyu", "cipt"), (question_id,), apply=True)
    # 混合批：任一未授权 ID 即整批拒绝，合法 ID 也不写入。
    with pytest.raises(FixError, match="UNKNOWN_QUESTION_ID"):
        fix_questions(db, Scope("nianyu", "cipt"), (3072, 9999), apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8 and db.get(Question, 3072) is not None


def test_missing_or_already_valid_questions_are_rejected(db):
    db.query(UserQuestionStat).filter_by(question_id=3386).delete()
    db.delete(db.get(Question, 3386))
    db.commit()
    with pytest.raises(FixError, match="QUESTION_NOT_FOUND"):
        fix_questions(db, Scope("nianyu", "cipt"), (3386,), apply=True)
    # 已是合法形状的题（重复执行/ID 漂移）必须拒绝，而不是被改第二次。
    db.get(Question, 3520).options = [
        {"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"},
        {"key": "C", "text": "charlie"}, {"key": "D", "text": "Pseudonymization"}]
    db.commit()
    with pytest.raises(FixError, match="NOT_MALFORMED"):
        fix_questions(db, Scope("nianyu", "cipt"), (3520,), apply=True)
    db.expire_all()
    assert _options(db, 3520)[3]["key"] == "D"


def test_batch_is_atomic_when_one_item_fails_validation(db):
    db.get(Question, 3520).correct_answer = "C"
    db.commit()
    with pytest.raises(FixError, match="ANSWER_DRIFT"):
        fix_questions(db, Scope("nianyu", "cipt"), (3072, 3520), apply=True)
    db.expire_all()
    # 两阶段：排在失败项之前的合法删除项也不落库。
    assert db.query(Question).count() == 8 and db.get(Question, 3072) is not None
    assert db.query(QuizAnswer).count() == 1 and db.query(BankWordFrequency).count() == 4


def test_unexpected_option_shape_is_rejected_without_guessing(db):
    # 仍是非法题面（重复 key），但第四个选项不是授权的那个词：不猜哪一项要改，整批拒绝。
    db.get(Question, 3520).options = [
        {"key": "A", "text": "alpha"}, {"key": "B", "text": "biometrics"},
        {"key": "C", "text": "Pseudonymization"}, {"key": "C", "text": "charlie"}]
    db.commit()
    with pytest.raises(FixError, match="UNEXPECTED_OPTION_STRUCTURE"):
        fix_questions(db, Scope("nianyu", "cipt"), (3520,), apply=True)
    db.expire_all()
    assert _options(db, 3520)[3]["key"] == "C"


def test_word_with_content_cannot_be_discarded(unreferenced_db):
    db = unreferenced_db
    # "disappearing" 若挂着翻译/释义，删词行会丢信息 → 整批拒绝，题也不删。
    db.get(BankWordFrequency, 1).definition = "valuable"
    db.commit()
    with pytest.raises(FixError, match="DERIVED_DATA_BLOCKED"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8 and db.get(BankWordFrequency, 1) is not None


def test_word_with_learning_progress_cannot_be_discarded(unreferenced_db):
    db = unreferenced_db
    db.add(BankWordExclusion(bank_id=13, term="disappearing", created_by=1))
    db.commit()
    with pytest.raises(FixError, match="DERIVED_DATA_BLOCKED"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)


@pytest.mark.parametrize("payload", [
    '{"bank_id": 13, "term": "disappearing"}',
    '{"bank_id": 13, "terms": ["disappearing"]}',
    # 未知 payload 形状不能静默忽略：词频行可能被别的任务用到。
    '{"bank_id": 13, "terms": "disappearing"}',
    '{"bank_id": 13, "terms": [7]}',
])
def test_word_referenced_by_task_or_unknown_payload_blocks_removal(unreferenced_db, payload):
    db = unreferenced_db
    db.add(BackgroundJob(job_type="translation", scope_key="term-task", created_by=1,
                         status="completed", payload_json=payload))
    db.commit()
    with pytest.raises(FixError, match="DERIVED_DATA_BLOCKED"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8


def test_unknown_fk_on_word_table_blocks_deletion(pg, unreferenced_db):
    db = unreferenced_db
    with pg.begin() as conn:
        conn.execute(text("CREATE TABLE future_word_reference (id serial primary key, word_id integer REFERENCES bank_word_frequencies(id), secret text)"))
        conn.execute(text("INSERT INTO future_word_reference(word_id) VALUES (1)"))
    try:
        with pytest.raises(FixError, match="DERIVED_DATA_BLOCKED"):
            fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
        db.expire_all()
        assert db.query(Question).count() == 8
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_word_reference"))


def test_unknown_table_cascading_from_questions_blocks_deletion(pg, db):
    # 未登记的新表即使带着 ON DELETE CASCADE，也不能让数据库静默带走它的行；
    # 判重工具对同类引用报 unknown_question_reference，本脚本口径必须一致。
    with pg.begin() as conn:
        conn.execute(text("CREATE TABLE future_question_reference (id serial primary key, question_id integer REFERENCES questions(id) ON DELETE CASCADE, secret text)"))
        conn.execute(text("INSERT INTO future_question_reference(question_id, secret) VALUES (3072, 'silent-loss')"))
    try:
        with pytest.raises(FixError, match="UNKNOWN_QUESTION_REFERENCE"):
            fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
        db.expire_all()
        assert db.query(Question).count() == 8 and db.get(Question, 3072) is not None
    finally:
        db.rollback()
        with pg.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM future_question_reference")).scalar() == 1
            conn.execute(text("DROP TABLE future_question_reference"))


@pytest.mark.parametrize("model,question_id", [
    (QuizAnswer, 3072), (WrongAnswer, 3376),
    (UserQuestionStat, 3386), (PracticeDayQuestion, 3372),
])
@pytest.mark.parametrize("apply", [False, True], ids=["dry_run", "apply"])
def test_learning_history_blocks_deletion_without_mutating_batch(unreferenced_db, model, question_id, apply):
    db = unreferenced_db
    row = db.query(model).one()
    row.question_id = question_id
    db.commit()
    with pytest.raises(FixError, match="LEARNING_HISTORY_REFERENCE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=apply)
    db.expire_all()
    assert db.query(model).one().question_id == question_id
    assert db.get(Question, question_id) is not None
    assert _options(db, 3520)[3]["key"] == "C"


@pytest.mark.parametrize("field,value", [
    ("question_ids", json.dumps([3072])),
    ("question_snapshot", [{"question_id": 3072}]),
    ("final_answers", {"3072": {"user_answer": "D", "is_correct": True}}),
])
@pytest.mark.parametrize("completed", [False, True], ids=["unfinished", "completed"])
@pytest.mark.parametrize("apply", [False, True], ids=["dry_run", "apply"])
def test_session_history_blocks_deletion_for_every_reference_shape(unreferenced_db, field, value, completed, apply):
    db = unreferenced_db
    session = db.get(QuizSession, 1)
    session.is_completed = completed
    setattr(session, field, value)
    db.commit()
    with pytest.raises(FixError, match="LEARNING_HISTORY_REFERENCE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=apply)
    db.expire_all()
    assert getattr(db.get(QuizSession, 1), field) == value
    assert db.get(Question, 3072) is not None
    assert _options(db, 3520)[3]["key"] == "C"


@pytest.mark.parametrize("field,value", [
    ("question_ids", "not-json"),
    ("question_ids", json.dumps(["3072"])),
    ("question_snapshot", [{"content": "unknown reference"}]),
    ("question_snapshot", [{"question_id": "3072"}]),
    ("final_answers", []),
    ("final_answers", {"not-an-id": None}),
])
def test_unknown_session_reference_structure_fails_closed(unreferenced_db, field, value):
    db = unreferenced_db
    setattr(db.get(QuizSession, 1), field, value)
    db.commit()
    with pytest.raises(FixError, match="UNKNOWN_SESSION_STRUCTURE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.get(Question, 3072) is not None
    assert _options(db, 3520)[3]["key"] == "C"


@pytest.mark.parametrize("parent_table", ["quiz_answers", "question_explanations"])
@pytest.mark.parametrize("on_delete", ["CASCADE", "NO ACTION", "SET NULL"])
@pytest.mark.parametrize("apply", [False, True], ids=["dry_run", "apply"])
def test_unknown_reference_to_deleted_child_blocks_before_any_write(pg, db, parent_table, on_delete, apply):
    # 子行 ID 为 1，并非其 question_id；不能拿题 ID 去匹配附属行主键。
    with pg.begin() as conn:
        parent_id, question_id = conn.execute(text(
            f"SELECT id, question_id FROM {parent_table}"
        )).one()
        assert parent_id != question_id
        conn.execute(text(
            f"CREATE TABLE future_child_reference (id serial primary key, "
            f"child_id integer REFERENCES {parent_table}(id) ON DELETE {on_delete}, secret text)"
        ))
        conn.execute(text("INSERT INTO future_child_reference(child_id, secret) VALUES (:id, 'private')"),
                     {"id": parent_id})
    try:
        with pytest.raises(FixError, match="UNKNOWN_QUESTION_REFERENCE"):
            fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=apply)
        # 在校验异常后、尚未 rollback 时断言，保证同批修 key 也未被提前写入。
        db.expire_all()
        assert _options(db, 3520)[3]["key"] == "C"
        assert db.get(Question, question_id) is not None
        assert db.execute(text("SELECT child_id FROM future_child_reference")).scalar_one() == parent_id
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_child_reference"))


@pytest.mark.parametrize("on_delete", ["CASCADE", "NO ACTION", "SET NULL"])
def test_unknown_reference_only_to_retained_child_does_not_block(pg, unreferenced_db, on_delete):
    db = unreferenced_db
    # 刻意让存活解析的 ID 等于被删题 ID：错误地匹配题 ID 也会误阻断。
    db.add(QuestionExplanation(id=3072, question_id=3530, model_id="retained", input_fingerprint="b" * 64,
                               judged_answer="A", explanation_zh="keep", analysis={}, generation_id=1))
    db.commit()
    with pg.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE future_child_reference (id serial primary key, child_id integer "
            f"REFERENCES question_explanations(id) ON DELETE {on_delete}, secret text)"
        ))
        conn.execute(text("INSERT INTO future_child_reference(child_id, secret) VALUES (3072, 'keep')"))
    try:
        assert fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True).mode == "apply"
        assert db.execute(text("SELECT child_id FROM future_child_reference")).scalar_one() == 3072
        assert db.get(QuestionExplanation, 3072).question_id == 3530
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_child_reference"))


@pytest.mark.parametrize("retained", [False, True], ids=["deleted", "retained"])
def test_unknown_composite_reference_matches_all_parent_columns(pg, unreferenced_db, retained):
    db = unreferenced_db
    original = db.query(QuestionTopic).one()
    topic_id = original.topic_id
    db.add(QuestionTopic(question_id=3530, topic_id=topic_id, source="manual"))
    db.commit()
    question_id = 3530 if retained else 3372
    with pg.begin() as conn:
        conn.execute(text(
            "CREATE TABLE future_composite_reference (question_ref integer, topic_ref integer, "
            "secret text, FOREIGN KEY (question_ref, topic_ref) "
            "REFERENCES question_topics(question_id, topic_id) ON DELETE CASCADE)"
        ))
        conn.execute(text("INSERT INTO future_composite_reference VALUES (:qid, :tid, 'keep')"),
                     {"qid": question_id, "tid": topic_id})
    try:
        if retained:
            assert fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True).mode == "apply"
        else:
            with pytest.raises(FixError, match="UNKNOWN_QUESTION_REFERENCE"):
                fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
            db.expire_all()
            assert _options(db, 3520)[3]["key"] == "C"
        assert db.execute(text("SELECT question_ref FROM future_composite_reference")).scalar_one() == question_id
    finally:
        db.rollback()
        with pg.begin() as conn:
            conn.execute(text("DROP TABLE future_composite_reference"))


def test_vector_projection_of_deleted_question_blocks(db):
    # vector_index 无外键，删题不会让它失效；指向被删题或落在被删题库的投影行必须先阻断。
    db.add(VectorIndex(vector_type="question", ref_id="3072", bank_id=13, text_content="PRIVATE_VECTOR"))
    db.commit()
    with pytest.raises(FixError, match="UNKNOWN_QUESTION_REFERENCE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8
    # 只改 key 时（不删题）同样的投影行不阻断。
    assert fix_questions(db, Scope("nianyu", "cipt"), (3520,), apply=True).deleted == []


def test_import_json_implicit_reference_blocks_deletion(db):
    # imported_question_id 会被置 NULL，但溯源 JSON 里的隐式指针删题后无从修复。
    source = db.query(ImportParsedQuestion).one()
    source.issues_json = {"details": [{"existing_question_id": 3376}]}
    db.commit()
    with pytest.raises(FixError, match="IMPLICIT_IMPORT_REFERENCE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8


def test_cross_scope_source_pointer_blocks_deletion(db):
    # 指向被删题的溯源行属于范围外题库时，本脚本无权改写它的指针，整批拒绝。
    other_bank = QuestionBank(id=14, exam_id=1, name="外部库", question_count=0)
    other_job = ImportJob(bank_id=14, file_name="o.pdf", file_path="/tmp/o.pdf", file_hash="b" * 64,
                          file_type="pdf", status="imported")
    db.add_all([other_bank, other_job])
    db.flush()
    db.add(ImportParsedQuestion(import_job_id=other_job.id, content="x", options_json=[],
                                imported_question_id=3386, import_status="imported"))
    db.commit()
    with pytest.raises(FixError, match="CROSS_SCOPE_SOURCE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8


@pytest.mark.parametrize("status", ["queued", "running", "retrying"])
def test_active_background_job_reference_blocks_deletion(db, status):
    db.add(BackgroundJob(job_type="translation", scope_key=f"active-{status}", created_by=1,
                         status=status, subject_question_id=3372, payload_json='{"bank_id":13}'))
    db.commit()
    with pytest.raises(FixError, match="ACTIVE_BACKGROUND_REFERENCE"):
        fix_questions(db, Scope("nianyu", "cipt"), ALL_IDS, apply=True)
    db.expire_all()
    assert db.query(Question).count() == 8


def test_cli_defaults_to_read_only_and_reports_json(pg, unreferenced_db):
    db = unreferenced_db
    import os
    import subprocess
    cli = Path(__file__).resolve().parents[1] / "scripts" / "fix_malformed_questions.py"
    env = {**os.environ, "DATABASE_URL": pg.url.render_as_string(hide_password=False)}
    db.rollback()
    result = subprocess.run([sys.executable, str(cli), "--questions", "3072,3520"],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "dry_run" and report["deleted"] == [3072]
    assert [fix["question_id"] for fix in report["key_fixes"]] == [3520]
    result = subprocess.run([sys.executable, str(cli), "--questions", "9999"],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "UNKNOWN_QUESTION_ID" in result.stderr
    result = subprocess.run([sys.executable, str(cli), "--questions", "3072", "--apply"],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "apply"
    db.expire_all()
    assert db.query(Question).count() == 7 and db.get(Question, 3072) is None
    assert db.get(QuestionBank, 13).question_count == 6


def test_cli_refuses_sqlite_without_connecting(tmp_path):
    import os
    import subprocess
    cli = Path(__file__).resolve().parents[1] / "scripts" / "fix_malformed_questions.py"
    result = subprocess.run([sys.executable, str(cli), "--questions", "3072"],
                            env={**os.environ, "DATABASE_URL": "sqlite:///" + str(tmp_path / "do-not-create.db")},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "POSTGRESQL_REQUIRED" in result.stderr
    assert not (tmp_path / "do-not-create.db").exists()
