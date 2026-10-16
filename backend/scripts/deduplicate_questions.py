#!/usr/bin/env python3
"""nianyu/CIPT 专用审计 CLI。默认只读，AI/apply/rollback 全部显式。

学习历史、原题重做、后台引用与答案/题型冲突、未知引用等均属于 `blockers`，
不能随题删除。`cascades` 仅为报告格式兼容保留，当前为空；旧计划须重新审计。"""
from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.services.question_dedup_service import DedupError, Scope, audit
from app.services.question_dedup_execution_service import apply_plan, read_private, rollback_plan, write_private


def configured_url() -> str:
    # 不导入含默认 URL 的配置来猜真实数据库；只允许显式环境/共享受保护配置。
    from dotenv import dotenv_values
    source = Path(__file__).resolve().parents[1] / ".env"
    raw = os.environ.get("DATABASE_URL")
    if not raw and source.exists():
        if source.is_symlink() or source.stat().st_uid not in {0, os.getuid()} or stat.S_IMODE(source.stat().st_mode) & 0o077:
            raise DedupError("UNPROTECTED_DATABASE_CONFIG")
        raw = dotenv_values(source).get("DATABASE_URL")
    if not raw:
        raise DedupError("EXPLICIT_DATABASE_URL_REQUIRED")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or not url.database or url.password in {"pass", "password", "changeme", "your-password"}:
        raise DedupError("EXPLICIT_POSTGRESQL_REQUIRED")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--ai", action="store_true", help="显式发送授权题面，累计最多100请求")
    modes.add_argument("--apply", type=Path, metavar="PLAN")
    modes.add_argument("--rollback", type=Path, metavar="BACKUP")
    modes.add_argument("--semantic-plan", type=Path, metavar="AI_REPORT", help="只读构建已明确选择的语义组计划")
    parser.add_argument("--user", default="nianyu")
    parser.add_argument("--exam", default="cipt")
    parser.add_argument("--banks", type=int, nargs=2, default=[13, 15])
    parser.add_argument("--audit-id", default="cipt-first-round")
    parser.add_argument("--output", type=Path, help="受限本地计划文件（0600/父目录0700）")
    parser.add_argument("--ledger", type=Path, help="AI持久预算账本，恢复必须复用")
    parser.add_argument("--semantic-confirmation", type=Path, help="受限文件：{groups:[[代表ID,成员ID,...]]}，不得省略")
    parser.add_argument("--confirm", help="用户确认的完整计划摘要")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--maintenance", choices=["offline-maintenance-confirmed"], help="操作者已确认所有写入者离线；工具不替你停止服务")
    args = parser.parse_args(argv)
    engine = None
    try:
        scope = Scope(args.user, args.exam, tuple(args.banks))
        scope.validate()
        if args.semantic_plan and (not args.semantic_confirmation or not args.output):
            raise DedupError("SEMANTIC_GROUP_CONFIRMATION_AND_OUTPUT_REQUIRED")
        if args.ai and (not args.ledger or not args.output):
            raise DedupError("AI_LEDGER_AND_REPORT_REQUIRED")
        if args.apply and (not args.confirm or not args.backup or not args.maintenance):
            raise DedupError("APPLY_CONFIRMATION_BACKUP_MAINTENANCE_REQUIRED")
        if args.rollback and not args.maintenance:
            raise DedupError("ROLLBACK_MAINTENANCE_REQUIRED")
        readonly = not (args.apply or args.rollback)
        options = "-c statement_timeout=30000 -c lock_timeout=3000 -c idle_in_transaction_session_timeout=30000"
        options += " -c default_transaction_read_only=" + ("on" if readonly else "off")
        engine = create_engine(configured_url(), connect_args={"options": options}, pool_pre_ping=True)
        with Session(engine, autoflush=False) as db:
            if readonly:
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                if db.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
                    raise DedupError("READONLY_NOT_ENFORCED")
                plan, state = audit(db, scope, audit_id=args.audit_id)
                if args.semantic_plan:
                    from app.services.question_dedup_ai_service import confirmed_semantic_plan
                    prior = read_private(args.semantic_plan)
                    if prior["plan"]["fingerprint"] != plan["fingerprint"]:
                        raise DedupError("PLAN_DRIFT")
                    plan = confirmed_semantic_plan(plan, state, prior["ai"], read_private(args.semantic_confirmation)["groups"])
                report: dict[str, Any] = {"status": "dry_run", "readonly": True, "plan": plan}
                if args.ai:
                    from app.services.settings_service import get_effective_ai_settings
                    from app.services.ai_service import call_ai_api
                    from app.services.question_dedup_ai_service import MODEL, candidates, evaluate_candidates
                    config = get_effective_ai_settings(db, model=MODEL, scene="default")
                    db.rollback()  # 不跨 HTTP 持业务事务。
                    pairs = candidates(state["questions"])
                    def invoke(messages: list[dict]) -> str:
                        return call_ai_api(messages, None, scene="default", timeout=60, ai_config=config, reasoning_effort=None)
                    report["ai"] = evaluate_candidates(pairs, audit_id=args.audit_id, ledger_path=args.ledger, invoke=invoke)
                db.rollback()
                if args.output:
                    write_private(args.output, report)
                print(json.dumps({"status": report["status"], "readonly": True, "audit_id": plan["audit_id"], "approval_digest": plan["approval_digest"], "summary": plan["summary"], "raw_equal_summary": plan["raw_equal_summary"], "ai_summary": {k: v for k, v in report.get("ai", {}).items() if k not in {"results", "semantic_groups"}}}, ensure_ascii=False))
            elif args.apply:
                loaded = read_private(args.apply)
                plan = loaded.get("plan", loaded)
                print(json.dumps(apply_plan(db, plan, confirmation=args.confirm, backup_path=args.backup, maintenance=args.maintenance)))
            else:
                print(json.dumps(rollback_plan(db, read_private(args.rollback), maintenance=args.maintenance)))
        return 0
    except DedupError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    except Exception:
        # 原始 SQL/URL/模型响应可能包含秘密，不输出 traceback 或异常正文。
        print('{"error":"DEDUP_OPERATION_FAILED"}', file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
