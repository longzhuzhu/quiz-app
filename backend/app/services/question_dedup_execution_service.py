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
    DedupError, Scope, audit, canonical, collect_state, decode, digest, tables, word_changes,
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


def expected_state(pre: dict, plan: dict) -> dict:
    post = deepcopy(pre)
    remap = {i: group["keep"] for group in plan["groups"] if not group["blockers"] for i in group["remove"]}
    changes, blockers = word_changes(pre, set(remap))
    if blockers:
        raise DedupError("DERIVED_DATA_BLOCKED")
    post["questions"] = [q for q in post["questions"] if q["id"] not in remap]
    for name in ("question_topics", "question_explanations"):
        if name in post:
            post[name] = [r for r in post[name] if r["question_id"] not in remap]
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


def apply_plan(db: Session, plan: dict, *, confirmation: str, backup_path: Path, maintenance: str) -> dict:
    try:
        _maintenance(db, maintenance)
        scope = _scope(plan)
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
        backup = {"schema_version": 1, "plan": plan, "pre": pre, "post": post, "pre_digest": digest(pre), "post_digest": digest(post)}
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
        for name in ("question_topics", "question_explanations"):
            db.execute(delete(ts[name]).where(ts[name].c.question_id.in_(remove)))
        db.execute(delete(ts["questions"]).where(ts["questions"].c.id.in_(remove)))
        actual, reference_context = collect_state(db, scope, tracked_ids={q["id"] for q in pre["questions"]})
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
        if backup.get("schema_version") != 1 or digest(backup["pre"]) != backup["pre_digest"] or digest(backup["post"]) != backup["post_digest"]:
            raise DedupError("INVALID_BACKUP")
        scope = _scope(backup["plan"])
        if any(question["bank_id"] not in scope.bank_ids for image in (backup["pre"], backup["post"]) for question in image["questions"]):
            raise DedupError("BACKUP_SCOPE_MISMATCH")
        if digest(expected_state(backup["pre"], backup["plan"])) != backup["post_digest"]:
            raise DedupError("BACKUP_PLAN_IMAGE_MISMATCH")
        current, reference_context = collect_state(db, scope, lock=True, tracked_ids={q["id"] for q in backup["pre"]["questions"]})
        if reference_context["malformed_sessions"] or reference_context["unknown_schema"]:
            raise DedupError("ROLLBACK_UNKNOWN_REFERENCE")
        if digest(current) == backup["pre_digest"]:
            db.rollback()
            return {"status": "already_restored_or_not_applied"}
        if digest(current) != backup["post_digest"]:
            raise DedupError("ROLLBACK_POST_IMAGE_DRIFT")
        ts = tables(db)
        # 原 ID 有冲突（即便移到另一个库）拒绝；先恢复父题，再恢复附加信息和来源。
        for name in ("questions", "bank_word_frequencies", "question_topics", "question_explanations", "question_banks", "import_parsed_questions"):
            old = {canonical([r[c.name] for c in ts[name].primary_key.columns]): r for r in backup["pre"].get(name, [])}
            new = {canonical([r[c.name] for c in ts[name].primary_key.columns]): r for r in backup["post"].get(name, [])}
            for key, row in old.items():
                if key not in new:
                    if db.execute(select(ts[name]).where(_key(ts[name], row))).first():
                        raise DedupError("ROLLBACK_ID_CONFLICT")
                    db.execute(insert(ts[name]).values(**row))
                elif row != new[key]:
                    db.execute(update(ts[name]).where(_key(ts[name], row)).values(**row))
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
