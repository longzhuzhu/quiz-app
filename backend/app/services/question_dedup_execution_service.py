"""显式维护清理/恢复。完整 pre/post-image 先 durable，事务失败不会部分提交。"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

from app.services.question_dedup_service import (
    SCHEMA_VERSION, DedupError, Scope, _json, _session_refs, audit, canonical, collect_state, decode, digest, payload_ids, tables, word_changes,
)


def private_directory(path: Path) -> Path:
    path = path.absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise DedupError("UNSAFE_DIRECTORY")
    # 秘密文件只能位于仓库外，或明确忽略的目录；不修改 git 配置。
    import subprocess
    root = Path(__file__).resolve().parents[3]
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = None
    if relative is not None:
        checked = subprocess.run(["git", "check-ignore", "-q", str(relative) + "/probe.json"], cwd=root, capture_output=True)
        if checked.returncode != 0:
            raise DedupError("PRIVATE_PATH_NOT_IGNORED")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise DedupError("UNSAFE_DIRECTORY")
    return path


def write_private(path: Path, value: Any, *, replace: bool = False) -> None:
    directory = private_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if replace:
        descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".pending", dir=directory)
        temporary = Path(name)
    else:
        temporary = path
        descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(canonical(value))
            output.flush()
            os.fsync(output.fileno())
        if replace:
            if path.is_symlink():
                raise DedupError("UNSAFE_FILE")
            os.replace(temporary, path)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if replace and temporary.exists():
            temporary.unlink()


def read_private(path: Path) -> dict:
    private_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        info = os.fstat(source.fileno())
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise DedupError("UNSAFE_FILE")
        return json.load(source, object_hook=decode)


def _scope(plan: dict) -> Scope:
    raw = plan["scope"]
    scope = Scope(raw["username"], raw["exam_slug"], tuple(raw["bank_ids"]))
    scope.validate()
    return scope


def _maintenance(db: Session, maintenance: str) -> None:
    if maintenance != "offline-maintenance-confirmed":
        raise DedupError("MAINTENANCE_CONFIRMATION_REQUIRED")
    if db.get_bind().dialect.name != "postgresql":
        raise DedupError("POSTGRESQL_REQUIRED")
    if db.new or db.dirty or db.deleted:
        raise DedupError("CLEAN_SESSION_REQUIRED")
    db.execute(text("SET LOCAL statement_timeout = '30s'"))
    db.execute(text("SET LOCAL lock_timeout = '3s'"))
    # 序列化工具间调用；不能代替服务停写。
    db.execute(text("SELECT pg_advisory_xact_lock(731411014)"))


# 仅用于 schema 2 旧备份的恢复图像校验，不用于新计划执行。
# 新执行不得显式删除学习记录或清空后台引用。
REFERENCING_TABLE_BEHAVIOR = {
    # migration 001：question_id 为普通外键（NO ACTION），存在引用时阻止删除。
    "quiz_answers": ("question_id", "explicit_delete"),
    "wrong_answers": ("question_id", "explicit_delete"),
    "user_question_stats": ("question_id", "explicit_delete"),
    # migration 007/005/011 均声明 ON DELETE CASCADE。
    "practice_day_questions": ("question_id", "cascade"),
    "question_topics": ("question_id", "cascade"),
    "question_explanations": ("question_id", "cascade"),
    # migration 011：ON DELETE SET NULL，任务记录保留但引用指针置空。
    "background_jobs": ("subject_question_id", "set_null"),
}


def _assert_protected_references(pre: dict, plan: dict) -> None:
    groups = [group for group in plan["groups"] if not group["blockers"]]
    remove = {qid for group in groups for qid in group["remove"]}
    members = {qid for group in groups for qid in group["members"]}
    for session in pre["quiz_sessions"]:
        refs = _session_refs(session)
        if refs & remove or (not session["is_completed"] and refs & members):
            raise DedupError("PROTECTED_REFERENCE")
    for name in ("quiz_answers", "wrong_answers", "user_question_stats", "practice_day_questions"):
        if any(row["question_id"] in remove for row in pre.get(name, [])):
            raise DedupError("PROTECTED_REFERENCE")
    for job in pre["background_jobs"]:
        payload = _json(job["payload_json"])
        if not isinstance(payload, dict) or payload.get("unknown_structure"):
            raise DedupError("PROTECTED_REFERENCE")
        if job.get("subject_question_id") in remove or payload_ids(payload) & remove:
            raise DedupError("PROTECTED_REFERENCE")


def expected_state(pre: dict, plan: dict) -> dict:
    _assert_protected_references(pre, plan)
    return _expected_image(pre, plan, legacy=False)


def _expected_image(pre: dict, plan: dict, *, legacy: bool) -> dict:
    post = deepcopy(pre)
    remap = {i: group["keep"] for group in plan["groups"] if not group["blockers"] for i in group["remove"]}
    changes, blockers = word_changes(pre, set(remap))
    if blockers:
        raise DedupError("DERIVED_DATA_BLOCKED")
    post["questions"] = [q for q in post["questions"] if q["id"] not in remap]
    reference_behavior = REFERENCING_TABLE_BEHAVIOR if legacy else {
        "question_topics": ("question_id", "cascade"),
        "question_explanations": ("question_id", "cascade"),
    }
    for name, (column, behavior) in reference_behavior.items():
        if name not in post:
            continue
        if behavior == "set_null":
            post[name] = [{**row, column: None} if row.get(column) in remap else row for row in post[name]]
        else:
            post[name] = [row for row in post[name] if row.get(column) not in remap]
    # collect_state 查询所有库内来源，以确保重定向后仍纳入 post-image。
    for source in post.get("import_parsed_questions", []):
        if source["imported_question_id"] in remap:
            source["imported_question_id"] = remap[source["imported_question_id"]]
    for bank in post["question_banks"]:
        if any(q["bank_id"] == bank["id"] and q["id"] in remap for q in pre["questions"]):
            bank["question_count"] = sum(q["bank_id"] == bank["id"] for q in post["questions"])
    words = []
    for word in post["bank_word_frequencies"]:
        if word["id"] in changes:
            if changes[word["id"]] is None:
                continue
            word["frequency"] = changes[word["id"]]
        words.append(word)
    post["bank_word_frequencies"] = words
    for name in post:
        post[name].sort(key=canonical)
    return post


def _key(table: Any, row: dict) -> Any:
    from sqlalchemy import and_
    return and_(*(column == row[column.name] for column in table.primary_key.columns))


# 回滚整行重建的范围与顺序：父行必须先于引用行，否则外键校验失败。
# 只列完整整行图像的表；投影/摘要表不在其中（会话、后台任务、来源复核等）。
RESTORE_ORDER = (
    "questions", "bank_word_frequencies", "question_banks", "import_parsed_questions",
    "question_explanations", "question_topics", "practice_day_questions",
    "quiz_answers", "wrong_answers", "user_question_stats",
)


def apply_plan(db: Session, plan: dict, *, confirmation: str, backup_path: Path, maintenance: str) -> dict:
    try:
        _maintenance(db, maintenance)
        scope = _scope(plan)
        # 旧 schema 1/2 与当前保护合同不同，必须重新审计，不能复用旧审批。
        if plan.get("schema_version") != SCHEMA_VERSION:
            raise DedupError("PLAN_SCHEMA_VERSION_UNSUPPORTED")
        expected_digest = digest({k: v for k, v in plan.items() if k != "approval_digest"})
        if confirmation != expected_digest or plan.get("approval_digest") != expected_digest:
            raise DedupError("PLAN_CONFIRMATION_MISMATCH")
        fresh, pre = audit(db, scope, audit_id=plan["audit_id"], lock=True)
        if "semantic_confirmation" in plan:
            from app.services.question_dedup_ai_service import confirmed_semantic_plan
            confirmation_data = plan["semantic_confirmation"]
            fresh = confirmed_semantic_plan(fresh, pre, confirmation_data["ai_report"], confirmation_data["groups"])
        if digest(fresh) != digest(plan):
            raise DedupError("PLAN_DRIFT")
        remove = {i for g in plan["groups"] if not g["blockers"] for i in g["remove"]}
        if not remove:
            db.rollback()
            return {"status": "no_changes", "removed": 0}
        post = expected_state(pre, plan)
        backup = {"schema_version": 2, "plan": plan, "pre": pre, "post": post, "pre_digest": digest(pre), "post_digest": digest(post)}
        write_private(backup_path, backup)  # 严格在第一条业务写入之前。
        ts = tables(db)
        # Core reflection 没有 ORM onupdate；仅更新被授权字段，预期图像精确可比较。
        for name in ("import_parsed_questions", "bank_word_frequencies", "question_banks"):
            old = {canonical([r[c.name] for c in ts[name].primary_key.columns]): r for r in pre[name]}
            new = {canonical([r[c.name] for c in ts[name].primary_key.columns]): r for r in post[name]}
            for key, row in old.items():
                if key not in new:
                    db.execute(delete(ts[name]).where(_key(ts[name], row)))
                elif row != new[key]:
                    changed = {field: value for field, value in new[key].items() if row[field] != value}
                    db.execute(update(ts[name]).where(_key(ts[name], row)).values(**changed))
        # 仅舍弃重复成员的附加信息；学习表不发 DELETE，NO ACTION 外键继续兜底。
        for name in ("question_topics", "question_explanations"):
            db.execute(delete(ts[name]).where(ts[name].c.question_id.in_(remove)))
        db.execute(delete(ts["questions"]).where(ts["questions"].c.id.in_(remove)))
        actual, reference_context = collect_state(
            db, scope,
            tracked_ids={q["id"] for q in pre["questions"]},
            # SET NULL 后指针不再指向任何题；按 ID 显式带上 pre 中的任务行。
            tracked_job_ids={row["id"] for row in pre["background_jobs"]},
        )
        if reference_context["malformed_sessions"] or reference_context["unknown_schema"]:
            raise DedupError("POST_IMAGE_UNKNOWN_REFERENCE")
        if digest(actual) != backup["post_digest"]:
            raise DedupError("POST_IMAGE_MISMATCH")
        db.commit()
        # 不依赖末尾文件标记：备份内预期 post 已 durable，commit 后崩溃仍可恢复。
        return {"status": "applied", "removed": len(remove), "post_digest": backup["post_digest"]}
    except BaseException:
        db.rollback()
        raise


def rollback_plan(db: Session, backup: dict, *, maintenance: str) -> dict:
    try:
        _maintenance(db, maintenance)
        if backup.get("schema_version") != 2 or digest(backup["pre"]) != backup["pre_digest"] or digest(backup["post"]) != backup["post_digest"]:
            raise DedupError("INVALID_BACKUP")
        scope = _scope(backup["plan"])
        if any(question["bank_id"] not in scope.bank_ids for image in (backup["pre"], backup["post"]) for question in image["questions"]):
            raise DedupError("BACKUP_SCOPE_MISMATCH")
        plan_version = backup["plan"].get("schema_version")
        if plan_version == 2:
            # 历史破坏性备份仅可恢复；绝不能经此分支变成可执行新计划。
            expected = _expected_image(backup["pre"], backup["plan"], legacy=True)
        elif plan_version == SCHEMA_VERSION:
            expected = expected_state(backup["pre"], backup["plan"])
        else:
            raise DedupError("INVALID_BACKUP")
        if digest(expected) != backup["post_digest"]:
            raise DedupError("BACKUP_PLAN_IMAGE_MISMATCH")
        current, reference_context = collect_state(
            db, scope, lock=True,
            tracked_ids={q["id"] for q in backup["pre"]["questions"]},
            tracked_job_ids={row["id"] for row in backup["pre"]["background_jobs"]},
        )
        if reference_context["malformed_sessions"] or reference_context["unknown_schema"]:
            raise DedupError("ROLLBACK_UNKNOWN_REFERENCE")
        if digest(current) == backup["pre_digest"]:
            db.rollback()
            return {"status": "already_restored_or_not_applied"}
        if digest(current) != backup["post_digest"]:
            raise DedupError("ROLLBACK_POST_IMAGE_DRIFT")
        ts = tables(db)
        # 原 ID 有冲突（即便移到另一个库）拒绝；先恢复父题，再恢复附加信息、来源与
        # 随题删除的引用行（外键依赖要求 questions 先回来）。只重建整行图像表：
        # 其余状态（会话、后台任务投影等）是投影，按行回写会伪造列。
        for name in RESTORE_ORDER:
            if name not in ts or name not in backup["pre"]:
                continue
            old = {canonical([r[c.name] for c in ts[name].primary_key.columns]): r for r in backup["pre"].get(name, [])}
            new = {canonical([r[c.name] for c in ts[name].primary_key.columns]): r for r in backup["post"].get(name, [])}
            for key, row in old.items():
                if key not in new:
                    if db.execute(select(ts[name]).where(_key(ts[name], row))).first():
                        raise DedupError("ROLLBACK_ID_CONFLICT")
                    db.execute(insert(ts[name]).values(**row))
                elif row != new[key]:
                    db.execute(update(ts[name]).where(_key(ts[name], row)).values(**row))
        # SET NULL 指针：行本身保留，只把被清空的引用恢复成 pre 值。
        for row in backup["pre"].get("background_jobs", []):
            for previous in backup["post"].get("background_jobs", []):
                if previous["id"] == row["id"] and previous["subject_question_id"] != row["subject_question_id"]:
                    db.execute(update(ts["background_jobs"]).where(ts["background_jobs"].c.id == row["id"]).values(subject_question_id=row["subject_question_id"]))
        restored, _ = collect_state(db, scope)
        if digest(restored) != backup["pre_digest"]:
            raise DedupError("RESTORE_IMAGE_MISMATCH")
        # apply 从未降低序列；恢复的 ID 曾真实存在，下一 ID 不应低于表中最大值。
        for name in ("questions", "bank_word_frequencies", "question_explanations"):
            db.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), GREATEST((SELECT COALESCE(MAX(id), 1) FROM {name}), (SELECT last_value FROM {name}_id_seq)), true)"))
        db.commit()
        return {"status": "restored"}
    except BaseException:
        db.rollback()
        raise
