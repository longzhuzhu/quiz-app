"""保守的库内题面身份与只读关联审计；不裁决答案、不重写学习历史。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from sqlalchemy import MetaData, literal_column, or_, select, text, tuple_
from sqlalchemy.orm import Session

from app.services.import_service import build_bank_word_frequencies

RULE_VERSION = "cipt-surface-v1"
SCHEMA_VERSION = 1
QUESTION_ID_KEYS = ("question_id", "subject_question_id", "imported_question_id", "existing_question_id", "matched_question_id")
# ImportJob 不是 BackgroundJob：_finalize_import 的四种输出均已停止执行；
# review_required 仅等待人工。集合由 IMPORT_JOB_STATUSES/终态写入合同测试锁定。
IMPORT_JOB_QUIESCENT_STATUSES = frozenset({
    "imported", "partial_imported", "review_required", "unimported", "failed", "cancelled",
})


class DedupError(ValueError):
    """仅含可公开的固定错误分类，绝不携带数据库/上游异常正文。"""


@dataclass(frozen=True)
class Scope:
    username: str = "nianyu"
    exam_slug: str = "cipt"
    bank_ids: tuple[int, ...] = (13, 15)

    def validate(self) -> None:
        if self.username != "nianyu" or self.exam_slug != "cipt" or self.bank_ids != (13, 15):
            raise DedupError("SCOPE_NOT_AUTHORIZED")


def encode(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return {"$datetime" if isinstance(value, datetime) else "$date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    raise TypeError("UNSUPPORTED_BACKUP_VALUE")


def decode(value: dict) -> Any:
    if set(value) == {"$datetime"}:
        return datetime.fromisoformat(value["$datetime"])
    if set(value) == {"$date"}:
        return date.fromisoformat(value["$date"])
    if set(value) == {"$decimal"}:
        return Decimal(value["$decimal"])
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, default=encode, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def surface(question: dict, *, normalize: bool = True) -> tuple:
    def text(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DedupError("INVALID_SURFACE")
        return " ".join(value.split()) if normalize else value

    options = question.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise DedupError("INVALID_OPTIONS")
    pairs = []
    for option in options:
        if not isinstance(option, dict) or not {"key", "text"}.issubset(option) or set(option) - {"key", "text", "text_zh"}:
            raise DedupError("INVALID_OPTIONS")
        pairs.append((text(option["key"]), text(option["text"])))
    # 原值统计也使用相同合法性门禁，只保留签名原值，不接受归一后撞键。
    if len({" ".join(key.split()) for key, _ in pairs}) != len(pairs):
        raise DedupError("INVALID_OPTION_KEYS")
    return text(question.get("content")), tuple(pairs)


def exact_groups(questions: list[dict], *, normalize: bool = True) -> tuple[list[list[dict]], list[int]]:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    invalid = []
    for question in questions:
        try:
            buckets[(question["bank_id"], surface(question, normalize=normalize))].append(question)
        except DedupError:
            invalid.append(question["id"])
    return [sorted(rows, key=lambda q: q["id"]) for rows in buckets.values() if len(rows) > 1], sorted(invalid)


def tables(db: Session) -> dict:
    metadata = MetaData()
    metadata.reflect(db.connection())
    return dict(metadata.tables)


def _rows(db: Session, table: Any, predicate: Any = None) -> list[dict]:
    query = select(table)
    if predicate is not None:
        query = query.where(predicate)
    return [dict(row) for row in db.execute(query).mappings()]


def _reference_rows(db: Session, table: Any, columns: list[str], predicate: Any) -> list[dict]:
    """仅返回引用键及数据库端摘要，不读取未知表/向量题面全文。"""
    quoted_name = db.get_bind().dialect.identifier_preparer.quote(table.name)
    row_digest = literal_column(
        f"encode(sha256(convert_to(row_to_json({quoted_name})::text, 'UTF8')), 'hex')"
    ).label("row_digest")
    query = select(*(table.c[name] for name in columns), row_digest).where(predicate)
    return [dict(row) for row in db.execute(query).mappings()]


def _attachment_references(db: Session, ts: dict, state: dict) -> list[dict]:
    references = []
    for name, table in ts.items():
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            target = elements[0].column.table.name
            if target not in {"question_topics", "question_explanations", "bank_word_frequencies"}:
                continue
            # 保留复合外键所有分量，不能只检查第一列。
            keys = {tuple(row[fk.column.name] for fk in elements) for row in state.get(target, [])}
            if not keys:
                continue
            columns = [fk.parent.name for fk in elements]
            predicate = tuple_(*(table.c[column] for column in columns)).in_(keys)
            for row in _reference_rows(db, table, columns, predicate):
                references.append({
                    "table": name, "target_table": target,
                    "target_key": {fk.column.name: row[fk.parent.name] for fk in elements},
                    "row_digest": row["row_digest"],
                })
    return references


def _has_attachment_reference(state: dict, table: str, removed_rows: list[dict]) -> bool:
    return any(
        reference["target_table"] == table
        and any(all(row.get(key) == value for key, value in reference["target_key"].items()) for row in removed_rows)
        for reference in state.get("unknown_attachment_references", [])
    )


def _json_reference_rows(db: Session, table: Any, columns: list[str], fields: tuple[str, ...]) -> list[dict]:
    """在 PostgreSQL 内投影 JSON 引用；跨范围记录不读取原始题面或元数据全文。"""
    preparer = db.get_bind().dialect.identifier_preparer
    keys = (*QUESTION_ID_KEYS, "question_ids[*]")
    arrays = []
    for field in fields:
        for key in keys:
            path = f"$.**.{key}" + (" ? (@ != null)" if key in QUESTION_ID_KEYS else "")
            arrays.append(f"COALESCE(jsonb_path_query_array({preparer.quote(field)}, '{path}'), '[]'::jsonb)")
    unknown = [
        f"COALESCE(jsonb_typeof({preparer.quote(field)}) NOT IN ('object', 'array', 'null'), false)"
        for field in fields
    ]
    query = text(
        "SELECT " + ", ".join(preparer.quote(column) for column in columns)
        + ", " + " || ".join(arrays) + " AS reference_ids, "
        + " OR ".join(unknown) + " AS unknown_structure, "
        + "encode(sha256(convert_to(row_to_json(ref)::text, 'UTF8')), 'hex') AS row_digest "
        + "FROM " + preparer.format_table(table) + " AS ref"
    )
    result = []
    for mapping in db.execute(query).mappings():
        row = dict(mapping)
        ids = row.pop("reference_ids")
        row["unknown_structure"] = row["unknown_structure"] or any(type(i) is not int for i in ids)
        row["question_ids"] = sorted({i for i in ids if type(i) is int})
        result.append(row)
    return result


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            raise DedupError("UNKNOWN_REFERENCE_STRUCTURE") from None
    return value


def payload_ids(value: Any) -> set[int]:
    """只认明确的题目引用键；未知嵌套仍递归，非法题目引用失败保护。"""
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in QUESTION_ID_KEYS:
                if child is not None:
                    if type(child) is not int:
                        raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
                    result.add(child)
            elif key == "question_ids":
                if not isinstance(child, list) or any(type(item) is not int for item in child):
                    raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
                result.update(child)
            else:
                result.update(payload_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(payload_ids(child))
    return result


def _safe_background_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
    projected: dict[str, Any] = {"question_ids": sorted(payload_ids(payload))}
    for key in ("bank_id", "exam_id", "term", "terms"):
        if key not in payload:
            continue
        value = payload[key]
        valid = (
            value is None
            or (key in {"bank_id", "exam_id"} and type(value) is int)
            or (key == "term" and isinstance(value, str))
            or (key == "terms" and isinstance(value, list) and all(isinstance(term, str) for term in value))
        )
        if not valid:
            raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
        projected[key] = value
    return projected


def collect_state(db: Session, scope: Scope, *, lock: bool = False, tracked_ids: set[int] | None = None) -> tuple[dict, dict]:
    scope.validate()
    ts = tables(db)
    user = _rows(db, ts["users"], ts["users"].c.username == scope.username)
    if len(user) != 1:
        raise DedupError("OWNER_NOT_UNIQUE")
    owner_id = user[0]["id"]
    exams = _rows(db, ts["exams"], (ts["exams"].c.owner_id == owner_id) & (ts["exams"].c.slug == scope.exam_slug))
    if len(exams) != 1:
        raise DedupError("EXAM_NOT_UNIQUE")
    exam_id = exams[0]["id"]
    banks = _rows(db, ts["question_banks"], ts["question_banks"].c.id.in_(scope.bank_ids))
    if len(banks) != 2 or any(bank["exam_id"] != exam_id for bank in banks):
        raise DedupError("BANK_OWNERSHIP_MISMATCH")
    if lock:
        # 维护前提仍必须由操作者保证；短事务行锁不冒充全局停写。
        for name in ("question_banks", "questions", "bank_word_frequencies"):
            table = ts[name]
            column = table.c.id if name == "question_banks" else table.c.bank_id
            db.execute(select(table).where(column.in_(scope.bank_ids)).with_for_update()).all()
    questions = _rows(db, ts["questions"], ts["questions"].c.bank_id.in_(scope.bank_ids))
    ids = {q["id"] for q in questions} | (tracked_ids or set())
    state = {"question_banks": banks, "questions": questions}
    unknown_schema = []
    # 动态发现直接外键：新表不会被静默漏过。
    for name, table in ts.items():
        columns = {fk.parent.name for fk in table.foreign_keys if fk.column.table.name == "questions"}
        if "question_id" in table.c:
            columns.add("question_id")
        if name == "import_parsed_questions":
            columns.add("imported_question_id")
        if columns:
            predicate = or_(*(table.c[column].in_(ids) for column in columns))
            known = name in {"quiz_answers", "wrong_answers", "user_question_stats", "practice_day_questions", "question_topics", "question_explanations", "background_jobs", "import_parsed_questions"}
            state[name] = _rows(db, table, predicate) if known else _reference_rows(db, table, sorted(columns), predicate)
            if not known and state[name]:
                unknown_schema.append(name)
    # 在数据库端投影快照 ID 和整行摘要，不取无关用户历史题面/作答全文。
    sessions = [dict(row) for row in db.execute(text("""
        SELECT id, user_id, bank_id, is_completed, question_ids,
               CASE WHEN question_snapshot IS NULL OR question_snapshot = 'null'::jsonb THEN NULL
                    WHEN jsonb_typeof(question_snapshot) = 'array'
                    THEN CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(question_snapshot) AS entry
                                          WHERE jsonb_typeof(entry) != 'object' OR NOT (entry ? 'question_id'))
                              THEN jsonb_build_object('unknown_structure', true)
                              ELSE jsonb_path_query_array(question_snapshot, '$[*].question_id') END
                    ELSE jsonb_build_object('unknown_structure', true) END AS snapshot_ids,
               CASE WHEN final_answers IS NULL OR final_answers = 'null'::jsonb THEN NULL
                    WHEN jsonb_typeof(final_answers) = 'object'
                    THEN (SELECT jsonb_agg(key) FROM jsonb_object_keys(final_answers) AS key)
                    ELSE jsonb_build_object('unknown_structure', true) END AS frozen_ids,
               encode(sha256(convert_to(row_to_json(s)::text, 'UTF8')), 'hex') AS row_digest
        FROM quiz_sessions AS s
    """)).mappings()]
    malformed = False
    relevant_sessions = []
    for session in sessions:
        try:
            members = _json(session["question_ids"])
            if members is None:
                members = []
            if not isinstance(members, list) or any(type(i) is not int for i in members):
                raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
            snapshots = session["snapshot_ids"]
            frozen = session["frozen_ids"]
            if snapshots is not None and (not isinstance(snapshots, list) or any(type(i) is not int for i in snapshots)):
                raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
            if frozen is not None and (not isinstance(frozen, list) or any(not isinstance(k, str) or not k.isdecimal() for k in frozen)):
                raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
            refs = set(members) | set(snapshots or []) | {int(k) for k in frozen or []}
            if refs & ids:
                relevant_sessions.append(session)
        except DedupError:
            malformed = True
    state["quiz_sessions"] = relevant_sessions
    for name in ("bank_word_frequencies", "bank_word_exclusions", "user_bank_word_progress", "import_jobs"):
        state[name] = _rows(db, ts[name], ts[name].c.bank_id.in_(scope.bank_ids))
    vector = ts["vector_index"]
    state["vector_index"] = [row for row in _json_reference_rows(
        db, vector, ["id", "bank_id", "vector_type", "ref_id"], ("metadata_json",),
    ) if row["bank_id"] in scope.bank_ids or row["ref_id"] in {str(i) for i in ids}
         or set(row["question_ids"]) & ids or row["unknown_structure"]]
    state["unknown_attachment_references"] = _attachment_references(db, ts, state)
    jobs = []
    for row in _rows(db, ts["background_jobs"]):
        try:
            payload = _safe_background_payload(_json(row["payload_json"]))
            linked = bool(set(payload["question_ids"]) & ids) or payload.get("bank_id") in scope.bank_ids or payload.get("exam_id") == exam_id
        except DedupError:
            linked = True
        if linked or row["created_by"] == owner_id:
            jobs.append(row)
    linked_jobs = state.get("background_jobs", [])
    all_jobs = list({row["id"]: row for row in linked_jobs + jobs}.values())
    safe_jobs = []
    for row in all_jobs:
        try:
            safe_payload = _safe_background_payload(_json(row["payload_json"]))
        except DedupError:
            safe_payload = {"unknown_structure": True}
        safe_jobs.append({key: row[key] for key in ("id", "created_by", "status", "subject_question_id", "job_type") } | {"payload_json": canonical(safe_payload), "row_digest": digest(row)})
    state["background_jobs"] = safe_jobs
    state["import_jobs"] = [{key: row[key] for key in ("id", "bank_id", "status", "background_job_id")} | {"row_digest": digest(row)} for row in state["import_jobs"]]
    source_table = ts["import_parsed_questions"]
    source_jobs = select(ts["import_jobs"].c.id).where(ts["import_jobs"].c.bank_id.in_(scope.bank_ids))
    sources = state.get("import_parsed_questions", []) + _rows(db, source_table, source_table.c.import_job_id.in_(source_jobs))
    state["import_parsed_questions"] = list({row["id"]: row for row in sources}.values())
    review_table = ts["import_review_items"]
    state["import_review_items"] = _rows(db, review_table, review_table.c.import_job_id.in_(source_jobs))
    state["external_import_references"] = []
    for table, fields in ((source_table, ("duplicate_json", "issues_json", "source_evidence_json")), (review_table, ("before_json", "after_json"))):
        # 库内/直接来源已有完整图像；补充投影仅覆盖未加载的外部来源，
        # 避免来源指针重定向后出现一份无法预计算的冗余行摘要。
        loaded_ids = {row["id"] for row in state[table.name]}
        for row in _json_reference_rows(db, table, ["id", "import_job_id"], fields):
            if row["id"] not in loaded_ids and (set(row["question_ids"]) & ids or row["unknown_structure"]):
                state["external_import_references"].append({"table": table.name, **row})
    context = {"owner_id": owner_id, "exam_id": exam_id, "unknown_schema": unknown_schema, "malformed_sessions": malformed}
    for name in state:
        state[name].sort(key=canonical)
    return state, context


def _session_refs(row: dict) -> set[int]:
    return set(_json(row["question_ids"]) or []) | set(row.get("snapshot_ids") or []) | {int(k) for k in row.get("frozen_ids") or []}


def group_plan(rows: list[dict], state: dict, context: dict, *, semantic: bool = False) -> dict:
    ids = {q["id"] for q in rows}
    learning_tables = ("quiz_answers", "wrong_answers", "user_question_stats", "practice_day_questions")
    weight = {i: sum(r.get("question_id") == i for name in learning_tables for r in state.get(name, [])) + sum(i in _session_refs(r) for r in state["quiz_sessions"]) for i in ids}
    keep = min(rows, key=lambda q: (-weight[q["id"]], q.get("created_at") or datetime.max, q["id"]))["id"]
    remove = ids - {keep}
    blockers = []
    if any(q["question_type"] not in {"single", "multiple", "truefalse"} or not isinstance(q["correct_answer"], str) or not q["correct_answer"].strip() for q in rows):
        blockers.append("invalid_answer_or_type")
    if len({q["correct_answer"] for q in rows}) != 1:
        blockers.append("answer_conflict")
    if len({q["question_type"] for q in rows}) != 1:
        blockers.append("type_conflict")
    if context["malformed_sessions"]:
        blockers.append("unknown_session_structure")
    if context["unknown_schema"]:
        blockers.append("unknown_question_reference")
    for session in state["quiz_sessions"]:
        refs = _session_refs(session)
        if refs & ids and not session["is_completed"]:
            blockers.append("unfinished_session")
        elif refs & remove:
            blockers.append("completed_session_retry")
    for name in learning_tables:
        if any(row["question_id"] in remove for row in state.get(name, [])):
            blockers.append(name)
    bank_id = rows[0]["bank_id"]
    if any(row["bank_id"] == bank_id and row["status"] not in IMPORT_JOB_QUIESCENT_STATUSES for row in state["import_jobs"]):
        blockers.append("active_import")
    for job in state["background_jobs"]:
        try:
            payload = _json(job["payload_json"])
            if not isinstance(payload, dict):
                raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
            if payload.get("unknown_structure"):
                raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
            refs = payload_ids(payload)
            if job.get("subject_question_id") in remove or refs & remove:
                blockers.append("background_reference")
            if job["status"] in {"queued", "running", "retrying"} and (payload.get("bank_id") == bank_id or refs & ids or payload.get("exam_id") == context["exam_id"] or job["created_by"] == context["owner_id"]):
                blockers.append("active_background")
        except DedupError:
            blockers.append("unknown_background_payload")
    scoped_jobs = {row["id"] for row in state["import_jobs"]}
    if any(row["imported_question_id"] in remove and row["import_job_id"] not in scoped_jobs for row in state["import_parsed_questions"]):
        blockers.append("cross_scope_source")
    if any(row["bank_id"] == bank_id or row["ref_id"] in {str(i) for i in ids} or set(row["question_ids"]) & ids or row["unknown_structure"] for row in state["vector_index"]):
        blockers.append("vector_reference")
    for name in ("question_topics", "question_explanations"):
        if _has_attachment_reference(state, name, [row for row in state.get(name, []) if row["question_id"] in remove]):
            blockers.append("unknown_question_reference")
    for reference in state["external_import_references"]:
        if reference["unknown_structure"]:
            blockers.append("unknown_import_reference")
        elif set(reference["question_ids"]) & remove:
            blockers.append("implicit_import_reference")
    for name, fields in (("import_parsed_questions", ("duplicate_json", "issues_json", "source_evidence_json")), ("import_review_items", ("before_json", "after_json"))):
        for row in state[name]:
            try:
                for field in fields:
                    value = _json(row.get(field))
                    if value is not None and not isinstance(value, (dict, list)):
                        raise DedupError("UNKNOWN_REFERENCE_STRUCTURE")
                    if payload_ids(value) & remove:
                        blockers.append("implicit_import_reference")
            except DedupError:
                blockers.append("unknown_import_reference")
    if semantic:
        blockers.append("semantic_confirmation_required")
    return {"bank_id": bank_id, "members": sorted(ids), "keep": keep, "remove": sorted(remove), "answer_conflict": "answer_conflict" in blockers, "type_conflict": "type_conflict" in blockers, "raw_equal": len({surface(q, normalize=False) for q in rows}) == 1, "blockers": sorted(set(blockers)), "kind": "semantic" if semantic else "exact"}


def word_changes(state: dict, remove: set[int]) -> tuple[dict[int, int | None], list[str]]:
    changes = {}
    blockers = []
    affected = {q["bank_id"] for q in state["questions"] if q["id"] in remove}
    for bank_id in affected:
        remaining = [q for q in state["questions"] if q["bank_id"] == bank_id and q["id"] not in remove]
        try:
            for question in remaining:
                surface(question)
        except DedupError:
            blockers.append("invalid_bank_surface")
            continue
        frequencies = {r["term"]: r["frequency"] for r in build_bank_word_frequencies(remaining)}
        words = [r for r in state["bank_word_frequencies"] if r["bank_id"] == bank_id]
        if set(frequencies) - {r["term"] for r in words}:
            blockers.append("missing_derived_terms")
        for word in words:
            frequency = frequencies.get(word["term"])
            has_content = any(word.get(key) for key in ("term_zh", "definition", "definition_zh"))
            has_progress = any(
                row["bank_id"] == bank_id and row["term"] == word["term"]
                for name in ("user_bank_word_progress", "bank_word_exclusions")
                for row in state[name]
            )
            has_task = False
            for job in state["background_jobs"]:
                payload = _json(job["payload_json"])
                terms = payload.get("terms") or []
                if not isinstance(terms, list):
                    has_task = True  # 未知词汇任务形状不能静默忽略。
                    break
                if payload.get("bank_id") == bank_id and (
                    payload.get("term") == word["term"] or word["term"] in terms
                ):
                    has_task = True
                    break
            if frequency is None and (has_content or has_progress or has_task):
                blockers.append("vocabulary_preservation")
            if frequency is None and _has_attachment_reference(state, "bank_word_frequencies", [word]):
                blockers.append("unknown_derived_reference")
            changes[word["id"]] = frequency
    return changes, sorted(set(blockers))


def audit(db: Session, scope: Scope = Scope(), *, audit_id: str, lock: bool = False) -> tuple[dict, dict]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", audit_id):
        raise DedupError("INVALID_AUDIT_ID")
    state, context = collect_state(db, scope, lock=lock)
    groups, invalid = exact_groups(state["questions"])
    raw_groups, _ = exact_groups(state["questions"], normalize=False)
    def counts(selected: list[list[dict]]) -> dict[str, int]:
        return {"groups": len(selected), "members": sum(len(group) for group in selected), "redundant": sum(len(group) - 1 for group in selected)}
    raw_equal_summary = {
        "totals": counts(raw_groups),
        "by_bank": [{"bank_id": bank_id, **counts([group for group in raw_groups if group[0]["bank_id"] == bank_id])} for bank_id in scope.bank_ids],
        "relationship": "included_in_whitespace_normalized_not_additive",
    }
    plans = [group_plan(rows, state, context) for rows in groups]
    eligible = {i for group in plans if not group["blockers"] for i in group["remove"]}
    _, word_blockers = word_changes(state, eligible)
    if word_blockers:
        for group in plans:
            if not group["blockers"]:
                group["blockers"] = word_blockers
    plan = {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION, "audit_id": audit_id, "scope": asdict(scope), "exam_id": context["exam_id"], "owner_id": context["owner_id"], "fingerprint": digest(state), "groups": plans, "invalid_question_ids": invalid, "question_total": len(state["questions"]), "association_context": context, "raw_equal_summary": raw_equal_summary}
    return finalize_plan(plan), state


def finalize_plan(plan: dict) -> dict:
    plans = plan["groups"]
    plan["summary"] = {
        "questions": plan["question_total"],
        "groups": len(plans),
        "members": sum(len(group["members"]) for group in plans),
        "redundant": sum(len(group["remove"]) for group in plans),
        "answer_conflicts": sum(group["answer_conflict"] for group in plans),
        "type_conflicts": sum(group["type_conflict"] for group in plans),
        "blocked_groups": sum(bool(group["blockers"]) for group in plans),
        "eligible_remove": sum(len(group["remove"]) for group in plans if not group["blockers"]),
    }
    plan.pop("approval_digest", None)
    plan["approval_digest"] = digest(plan)
    return plan
