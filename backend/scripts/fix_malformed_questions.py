#!/usr/bin/env python3
"""一次性修复 nianyu/CIPT 两库中 7 道结构非法的题；默认 dry-run，`--apply` 才写入。

可修复项固定在本文件的白名单里，且只接受显式 `--questions` 列表；不在名单内的 ID 一律拒绝，
避免脚本被当成通用删除/改题工具：

- 删除 4 道源 PDF 本身无选项的题（3072/3372/3376/3386）——原文在 `Answer: D/B` 前没有
  选项，3372 更是 `NO.63 SCENARIO` 场景描述块（选项属其后的子问题）。不从源 PDF 无法补全，
  也不编造考试数据。
- 修正 3 道第四个选项 key 被误标为 C 的题（3520/3522/3771），其中 3522 的 text_zh 一并纠正。
  修正不改变 correct_answer。

安全门禁与 `finalize_stale_sessions.py` 同口径：连接口令从受保护环境/`backend/.env` 读取、
整批先校验后写入（任一项失败在第一条写入之前抛出）、任何写入都在单事务内完成。

删除前保护学习历史：quiz_answers / wrong_answers / user_question_stats /
practice_day_questions 以及未完成或已完成会话的题目列表、快照、冻结答案引用均硬阻断，
不通过显式删除或 CASCADE 绕过。可替代的考点/解析按真实外键随题删除，
已结束后台任务的 SET NULL 指针自动置空。
`import_parsed_questions.imported_question_id` **没有外键**，不会随题失效；溯源行本身保留，
只把指针置 NULL——被删题不存在了，指向它的"已导入"指针是悬空引用，而 NULL 正是应用既有的
"该解析未关联存活题目" 语义（见 smart_import_service 的写入路径）。判重工具对被删题做的是
重定向（合并到代表题），本脚本没有代表题可指向，故用 NULL 而不是制造一个假引用。

删除前必须先通过引用门禁，口径与判重工具的硬阻断一致：未知表经 CASCADE 引用被删题、
`vector_index` 投影、导入溯源 JSON 内的隐式题目指针、活跃后台任务引用、跨范围来源指针
一律在第一条写入之前拒绝（`UNKNOWN_QUESTION_REFERENCE` / `IMPLICIT_IMPORT_REFERENCE` /
`ACTIVE_BACKGROUND_REFERENCE` / `CROSS_SCOPE_SOURCE`）。不靠数据库级联掩盖未知引用。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, delete, literal, select, tuple_
from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob
from app.models.bank_word import BankWordExclusion, BankWordFrequency, UserBankWordProgress
from app.models.exam import Exam
from app.models.import_job import ImportJob
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.services.import_service import build_bank_word_frequencies
from app.services.question_dedup_execution_service import REFERENCING_TABLE_BEHAVIOR
from app.services.question_dedup_service import (
    DedupError, _json_reference_rows, _session_reference_rows, _session_refs, payload_ids, surface, tables,
)
from scripts.deduplicate_questions import configured_url


class FixError(ValueError):
    """仅含可公开的固定错误分类，不携带数据库异常正文。"""


@dataclass(frozen=True)
class Scope:
    username: str
    exam_slug: str


@dataclass(frozen=True)
class KeyRepair:
    """第四个选项 key 由 C 改为 D 的授权修复；option_text 用于精确定位该选项。"""

    option_text: str
    expected_answer: str
    text_zh_from: str | None = None
    text_zh_to: str | None = None


DELETE_IDS = (3072, 3372, 3376, 3386)
# 与判重 CLI 相同的题库范围：bank 12 等其余库不在本任务授权内（PRD R8）。
AUTHORIZED_BANKS = (13, 15)
# 删除会带走整行的表：未知表对它们的引用必须阻断，而不是让数据库静默 CASCADE。
VANISHING_ROW_TABLES = frozenset({
    "questions", "quiz_answers", "wrong_answers", "user_question_stats",
    "practice_day_questions", "question_topics", "question_explanations",
})
ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "retrying"})
IMPORT_JSON_FIELDS = {
    "import_parsed_questions": ("duplicate_json", "issues_json", "source_evidence_json"),
    "import_review_items": ("before_json", "after_json"),
}
KEY_REPAIRS = {
    3520: KeyRepair("Pseudonymization", "B"),
    3522: KeyRepair("Tokenization", "A", text_zh_from="掩码", text_zh_to="令牌化"),
    3771: KeyRepair("Pseudonymization", "B"),
}
AUTHORIZED_IDS = frozenset(DELETE_IDS) | frozenset(KEY_REPAIRS)


def parse_question_ids(raw: str) -> tuple[int, ...]:
    """解析显式题目 ID 列表；重复、非正整数或空列表一律拒绝（只认 ASCII 数字）。"""
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(not re.fullmatch(r"[0-9]+", part) or int(part) <= 0 for part in parts):
        raise FixError("INVALID_QUESTION_IDS")
    ids = tuple(int(part) for part in parts)
    if len(set(ids)) != len(ids):
        raise FixError("INVALID_QUESTION_IDS")
    return ids


@dataclass
class PlannedRepair:
    question_id: int
    key_to: str
    option_text: str
    new_options: list[dict]
    text_zh_to: str | None = None

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "option_text": self.option_text,
            "key_from": "C",
            "key_to": self.key_to,
            "text_zh_to": self.text_zh_to,
        }


@dataclass
class FixResult:
    mode: str
    deleted: list[int] = field(default_factory=list)
    key_fixes: list[dict] = field(default_factory=list)
    import_pointers_cleared: int = 0
    banks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "deleted": self.deleted,
            "key_fixes": self.key_fixes,
            "import_pointers_cleared": self.import_pointers_cleared,
            "banks": self.banks,
        }


def _resolve_scope(db: Session, scope: Scope) -> tuple[User, Exam]:
    user = db.execute(select(User).where(User.username == scope.username)).scalars().one_or_none()
    if user is None:
        raise FixError("OWNER_NOT_FOUND")
    exam = db.execute(
        select(Exam).where(Exam.owner_id == user.id, Exam.slug == scope.exam_slug)
    ).scalars().one_or_none()
    if exam is None:
        raise FixError("EXAM_NOT_FOUND")
    return user, exam


def _is_malformed(question: Question) -> bool:
    """用判重工具同一套 surface() 门禁判定，保证修复后审计的 invalid_question_ids 会消失。"""
    try:
        surface({"content": question.content, "options": question.options})
    except DedupError:
        return True
    return False


def _plan_key_repair(question: Question, repair: KeyRepair) -> PlannedRepair:
    """按授权修复精确校验现场；形状不符即拒绝，不猜哪一项是"第四个选项"。"""
    options = question.options
    if not isinstance(options, list) or len(options) != 4 or any(not isinstance(option, dict) for option in options):
        raise FixError("UNEXPECTED_OPTION_STRUCTURE")
    matches = [
        index for index, option in enumerate(options)
        if str(option.get("text", "")).strip() == repair.option_text
    ]
    keys = [str(option.get("key", "")).strip() for option in options]
    if matches != [3] or keys != ["A", "B", "C", "C"]:
        raise FixError("UNEXPECTED_OPTION_STRUCTURE")
    if (question.correct_answer or "").strip() != repair.expected_answer:
        raise FixError("ANSWER_DRIFT")
    if repair.text_zh_from is not None and options[3].get("text_zh") != repair.text_zh_from:
        raise FixError("UNEXPECTED_OPTION_TEXT_ZH")
    new_options = [dict(option) for option in options]
    new_options[3] = {**new_options[3], "key": "D"}
    if repair.text_zh_to is not None:
        new_options[3]["text_zh"] = repair.text_zh_to
    # 修复后必须通过同一门禁；形状有别的毛病时拒绝，而不是带着 INVALID_OPTIONS 写回去。
    try:
        surface({"content": question.content, "options": new_options})
    except DedupError:
        raise FixError("UNEXPECTED_OPTION_STRUCTURE") from None
    return PlannedRepair(question.id, "D", repair.option_text, new_options, repair.text_zh_to)


def _bank_term_tasks(db: Session, bank_id: int) -> tuple[set[str], bool]:
    """题库词条的后台任务引用；未知 payload 形状返回 unknown=True，由调用方失败保护。"""
    terms: set[str] = set()
    unknown = False
    for job in db.query(BackgroundJob).all():
        try:
            payload = json.loads(job.payload_json or "{}")
        except ValueError:
            unknown = True
            continue
        if not isinstance(payload, dict):
            unknown = True
            continue
        job_terms = payload.get("terms") or []
        if not isinstance(job_terms, list) or any(not isinstance(term, str) for term in job_terms):
            unknown = True
            continue
        if payload.get("bank_id") == bank_id:
            if isinstance(payload.get("term"), str):
                terms.add(payload["term"])
            terms.update(job_terms)
    return terms, unknown


def _unknown_word_references(db: Session, ts: dict, removed: list[BankWordFrequency]) -> bool:
    """动态发现引用 bank_word_frequencies 的未知表；有行即失败保护，不静默级联。

    复合外键按全部分量比对（与判重工具一致），任一被引用列无法从词行取值时失败保护。
    """
    if not removed:
        return False
    for name, table in ts.items():
        if name == "bank_word_frequencies":
            continue
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            if elements[0].column.table.name != "bank_word_frequencies":
                continue
            try:
                keys = [tuple(removed_word.__dict__[element.column.name] for element in elements) for removed_word in removed]
            except KeyError:
                return True
            columns = [element.parent.name for element in elements]
            predicate = (
                table.c[columns[0]].in_([key[0] for key in keys]) if len(columns) == 1
                else tuple_(*(table.c[column] for column in columns)).in_(keys)
            )
            if db.execute(select(literal(1)).select_from(table).where(predicate).limit(1)).first():
                return True
    return False


def _word_plan(db: Session, bank_id: int, projected: list[dict]) -> tuple[list[tuple[BankWordFrequency, int]], list[BankWordFrequency]]:
    """按 `pending` 题面重算词频：surviving 词只改 frequency，保留 ID/翻译/释义/学习进度。"""
    try:
        frequencies = {item["term"]: item["frequency"] for item in build_bank_word_frequencies(projected)}
    except (AttributeError, TypeError, ValueError):
        raise FixError("DERIVED_DATA_BLOCKED") from None
    # 不按 bank_word_exclusions 过滤：判重工具 word_changes 在删题时用同一份未过滤的
    # 重建结果比对词表，若这里额外删掉被排除的词行，判重会以 missing_derived_terms 硬阻断。
    exclusions = {row.term for row in db.query(BankWordExclusion).filter_by(bank_id=bank_id).all()}
    words = db.query(BankWordFrequency).filter_by(bank_id=bank_id).order_by(BankWordFrequency.id).all()
    if set(frequencies) - {word.term for word in words}:
        # 派生词不在词表里说明库内本就不一致，不擅自补行。
        raise FixError("DERIVED_DATA_BLOCKED")
    progress = {row.term for row in db.query(UserBankWordProgress).filter_by(bank_id=bank_id).all()}
    task_terms, unknown_tasks = _bank_term_tasks(db, bank_id)
    updates: list[tuple[BankWordFrequency, int]] = []
    removals: list[BankWordFrequency] = []
    for word in words:
        frequency = frequencies.get(word.term)
        if frequency is None:
            protected = (
                unknown_tasks
                or any(getattr(word, key) for key in ("term_zh", "definition", "definition_zh"))
                or word.term in progress
                or word.term in exclusions
                or word.term in task_terms
            )
            if protected:
                raise FixError("DERIVED_DATA_BLOCKED")
            removals.append(word)
        elif word.frequency != frequency:
            updates.append((word, frequency))
    # 只有确实要删词行时才做整库反射；纯 frequency 更新不需要未知表检查。
    if removals and _unknown_word_references(db, tables(db), removals):
        raise FixError("DERIVED_DATA_BLOCKED")
    return updates, removals


def _unknown_row_references(db: Session, ts: dict, delete_ids: list[int]) -> bool:
    """动态发现引用会被删除整行的未知表；有行即失败保护，不静默让 CASCADE 带走。

    判重工具对同类引用报 unknown_question_reference / unknown_derived_reference 并阻断，
    本脚本删除的目标题同样会带走引用行，因此口径必须一致：只对登记在案的
    REFERENCING_TABLE_BEHAVIOR 表按真实外键行为处理，其余一律拒绝。
    """
    ids = set(delete_ids)
    known = {"questions", *REFERENCING_TABLE_BEHAVIOR}
    for name, table in ts.items():
        if name in known or name == "vector_index":
            continue
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            parent = elements[0].column.table
            if parent.name not in VANISHING_ROW_TABLES:
                continue
            # 外键引用的是实际父行的指定列，附属行的主键不能当成题 ID。
            # 子查询只投影引用键，复合外键保留所有分量，不读取未知表全文。
            question_column = parent.c.id if parent.name == "questions" else parent.c.question_id
            removed_keys = select(*(element.column for element in elements)).where(question_column.in_(ids))
            columns = [element.parent for element in elements]
            predicate = (
                columns[0].in_(removed_keys) if len(columns) == 1
                else tuple_(*columns).in_(removed_keys)
            )
            if db.execute(
                select(literal(1)).select_from(table).where(predicate).limit(1)
            ).first():
                return True
    return False


def _vector_references(db: Session, ts: dict, ids: set[int], bank_ids: set[int]) -> bool:
    """向量索引是无外键的投影表（`ref_id` 存字符串、metadata 可嵌 ID），删题不会让它失效。

    在数据库端只投影 ID/摘要，不把向量题面读进进程（与判重工具同口径）。
    """
    if "vector_index" not in ts:
        return False
    references = {str(question_id) for question_id in ids}
    for row in _json_reference_rows(db, ts["vector_index"], ["id", "bank_id", "ref_id"], ("metadata_json",)):
        if row["bank_id"] in bank_ids or row["ref_id"] in references:
            return True
        if row["unknown_structure"] or set(row["question_ids"]) & ids:
            return True
    return False


def _import_json_references(db: Session, ts: dict, delete_ids: list[int]) -> bool:
    """导入溯源 JSON 内的隐式题目引用：被删题在其中出现即阻断，不静默留下悬空引用。

    `imported_question_id` 没有外键且本脚本会置 NULL，但 duplicate/issue/before/after
    JSON 里可能还嵌着 `existing_question_id`/`question_id` 等指针，删题后无从修复。
    未知结构同样不能猜它引用了什么，与判重工具的 `unknown_import_reference` 同口径：
    有未知结构的溯源行即阻断，不因它属于哪个导入任务而放宽。
    """
    ids = set(delete_ids)
    for name, fields in IMPORT_JSON_FIELDS.items():
        if name not in ts:
            continue
        for row in _json_reference_rows(db, ts[name], ["id", "import_job_id"], fields):
            if row["unknown_structure"] or set(row["question_ids"]) & ids:
                return True
    return False


def _cross_scope_sources(db: Session, delete_ids: list[int], scoped_jobs: set[int]) -> bool:
    """范围外导入任务的溯源行指向被删题时阻断：指针属于别的题库，本脚本无权改写。

    只投影来源行 ID，不读取其他用户/题库的题面全文。
    """
    for row in db.execute(
        select(ImportParsedQuestion.id, ImportParsedQuestion.import_job_id)
        .where(ImportParsedQuestion.imported_question_id.in_(delete_ids))
    ).mappings():
        if row["import_job_id"] not in scoped_jobs:
            return True
    return False


def _active_job_references(db: Session, delete_ids: list[int]) -> bool:
    """活跃后台任务引用被删题时阻断；已结束任务由 SET NULL 处理。"""
    ids = set(delete_ids)
    for job in db.query(BackgroundJob).all():
        if job.status not in ACTIVE_JOB_STATUSES:
            continue
        if job.subject_question_id in ids:
            return True
        try:
            payload = json.loads(job.payload_json or "{}")
        except ValueError:
            return True
        if not isinstance(payload, dict):
            return True
        try:
            if payload_ids(payload) & ids:
                return True
        except DedupError:
            return True
    return False


def _protect_learning_history(db: Session, ts: dict, delete_ids: list[int]) -> None:
    """在任何写入前拒绝删除被学习历史引用的原题，未知会话结构同样失败保护。"""
    for name in ("quiz_answers", "wrong_answers", "user_question_stats", "practice_day_questions"):
        table = ts[name]
        if db.execute(
            select(literal(1)).select_from(table).where(table.c.question_id.in_(delete_ids)).limit(1)
        ).first():
            raise FixError("LEARNING_HISTORY_REFERENCE")
    sessions, malformed = _session_reference_rows(db)
    if malformed:
        raise FixError("UNKNOWN_SESSION_STRUCTURE")
    ids = set(delete_ids)
    if any(_session_refs(session) & ids for session in sessions):
        raise FixError("LEARNING_HISTORY_REFERENCE")


def _projected(db: Session, bank_id: int, delete_ids: set[int], repairs: dict[int, PlannedRepair]) -> list[dict]:
    rows = []
    for question in db.query(Question).filter_by(bank_id=bank_id).order_by(Question.order_index, Question.id).all():
        if question.id in delete_ids:
            continue
        repair = repairs.get(question.id)
        rows.append({
            "content": question.content,
            "options": repair.new_options if repair is not None else question.options,
        })
    return rows


def fix_questions(db: Session, scope: Scope, question_ids: tuple[int, ...], *, apply: bool = False) -> FixResult:
    """校验并（可选）修复指定题目；任何校验失败在第一条写入之前抛出。"""
    if not question_ids:
        raise FixError("INVALID_QUESTION_IDS")
    if sorted(qid for qid in question_ids if qid not in AUTHORIZED_IDS):
        raise FixError("UNKNOWN_QUESTION_ID")
    _user, exam = _resolve_scope(db, scope)
    questions = {
        question.id: question
        for question in db.execute(
            select(Question).where(Question.id.in_(list(question_ids))).with_for_update()
        ).scalars().all()
    }
    # 两阶段：先整批只读校验并算好预期效果，再统一写入。逐条边校验边改会让排在非法项
    # 之前的合法项先被改脏，与「校验失败发生在第一条写入之前」不符。
    planned: list[PlannedRepair] = []
    delete_ids: list[int] = []
    for question_id in sorted(question_ids):
        question = questions.get(question_id)
        if question is None:
            raise FixError("QUESTION_NOT_FOUND")
        bank = db.get(QuestionBank, question.bank_id)
        if bank is None or bank.exam_id != exam.id or bank.id not in AUTHORIZED_BANKS:
            raise FixError("QUESTION_NOT_IN_SCOPE")
        if not _is_malformed(question):
            # 已经合法的题不在本脚本授权范围内（重复执行或 ID 漂移时拒绝，不重复改）。
            raise FixError("NOT_MALFORMED")
        if question_id in DELETE_IDS:
            delete_ids.append(question_id)
        else:
            planned.append(_plan_key_repair(question, KEY_REPAIRS[question_id]))
    delete_set = set(delete_ids)
    repairs = {repair.question_id: repair for repair in planned}
    pointer_rows = (
        db.query(ImportParsedQuestion).filter(ImportParsedQuestion.imported_question_id.in_(delete_ids)).all()
        if delete_ids else []
    )
    if delete_ids:
        # 引用门禁：与判重工具的硬阻断同口径。升级前的脚本只处理登记在案的 7 张表，
        # 未知表的 CASCADE、vector_index 投影与导入 JSON 里的隐式指针都会被静默带走；
        # 这些引用一律在第一条写入之前拒绝，不靠数据库级联掩盖。
        ts = tables(db)
        affected_banks = {questions[qid].bank_id for qid in delete_ids}
        scope_job_ids = {
            job.id for job in db.query(ImportJob).filter(ImportJob.bank_id.in_(AUTHORIZED_BANKS)).all()
        }
        if _unknown_row_references(db, ts, delete_ids) \
                or _vector_references(db, ts, set(delete_ids), affected_banks):
            raise FixError("UNKNOWN_QUESTION_REFERENCE")
        if _import_json_references(db, ts, delete_ids):
            raise FixError("IMPLICIT_IMPORT_REFERENCE")
        if _active_job_references(db, delete_ids):
            raise FixError("ACTIVE_BACKGROUND_REFERENCE")
        if _cross_scope_sources(db, delete_ids, scope_job_ids):
            raise FixError("CROSS_SCOPE_SOURCE")
        _protect_learning_history(db, ts, delete_ids)
    result = FixResult(
        mode="apply" if apply else "dry_run",
        deleted=sorted(delete_ids),
        key_fixes=[repair.to_dict() for repair in planned],
        import_pointers_cleared=len(pointer_rows),
    )
    # 删除影响的题库：题数与词频都要按删后题面重算；只读预演与实际写入共用同一份计划。
    effects: list[tuple[QuestionBank, int, list[tuple[BankWordFrequency, int]], list[BankWordFrequency]]] = []
    for bank_id in sorted({questions[qid].bank_id for qid in delete_ids}):
        bank = db.get(QuestionBank, bank_id)
        projected = _projected(db, bank_id, delete_set, repairs)
        updates, removals = _word_plan(db, bank_id, projected)
        effects.append((bank, len(projected), updates, removals))
        result.banks.append({
            "bank_id": bank_id,
            "question_count": len(projected),
            "words_updated": len(updates),
            "words_deleted": len(removals),
        })
    if apply:
        try:
            ts = tables(db)
            for repair in planned:
                # JSONB 必须整字段重新赋值，就地 mutate 不会被 flush 写出。
                questions[repair.question_id].options = repair.new_options
            if delete_ids:
                # 学习表已通过硬阻断门禁；不显式删学习行，保留外键作为额外防线。
                db.execute(delete(ts["questions"]).where(ts["questions"].c.id.in_(delete_ids)))
            for row in pointer_rows:
                row.imported_question_id = None
            db.flush()
            db.expire_all()
            for bank, question_count, updates, removals in effects:
                bank = db.get(QuestionBank, bank.id)
                bank.question_count = question_count
                for word, frequency in updates:
                    db.get(BankWordFrequency, word.id).frequency = frequency
                for word in removals:
                    db.delete(db.get(BankWordFrequency, word.id))
            db.flush()
            for question_id in question_ids:
                question = db.get(Question, question_id)
                if question_id in delete_set:
                    if question is not None:
                        raise FixError("POST_IMAGE_MISMATCH")
                elif question is None or _is_malformed(question):
                    raise FixError("POST_IMAGE_MISMATCH")
            for bank, question_count, updates, removals in effects:
                actual = db.query(Question).filter_by(bank_id=bank.id).count()
                if actual != question_count:
                    raise FixError("POST_IMAGE_MISMATCH")
            db.commit()
        except BaseException:
            # 写路径任何失败整体回滚，不留半批结果。
            db.rollback()
            raise
    else:
        db.rollback()
    return result


def _print_result(result: FixResult) -> None:
    print(json.dumps(result.to_dict(), ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", required=True, help="显式题目 ID 列表，如 3072,3372,3376,3386,3520,3522,3771")
    parser.add_argument("--user", default="nianyu")
    parser.add_argument("--exam", default="cipt")
    parser.add_argument("--apply", action="store_true", help="写入数据库；默认只读校验。")
    args = parser.parse_args(argv)
    engine = None
    try:
        question_ids = parse_question_ids(args.questions)
        engine = create_engine(
            configured_url(),
            connect_args={"options": "-c statement_timeout=30000 -c lock_timeout=3000"},
            pool_pre_ping=True,
        )
        with Session(engine, autoflush=False) as db:
            result = fix_questions(db, Scope(args.user, args.exam), question_ids, apply=args.apply)
        _print_result(result)
        return 0
    except (FixError, DedupError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    except Exception:
        # 原始 SQL/URL 可能包含秘密，不输出 traceback 或异常正文。
        print('{"error":"FIX_OPERATION_FAILED"}', file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
