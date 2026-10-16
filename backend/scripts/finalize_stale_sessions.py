#!/usr/bin/env python3
"""按既有 finish 语义结束指定陈旧答题会话。默认 dry-run，`--apply` 才写入。

只接受显式 `--sessions` 列表与显式范围（username/exam），不批量猜选。写入复用
`freeze_final_answers`：写 `is_completed`、`completed_at` 与 `final_answers`，
与 `/api/quiz/finish` 完全同口径，不直接改布尔值、不伪造冻结内容。已完成会话跳过，
不重复冻结；快照从未写过的会话（冻结后复盘取不到当场题干）一律拒绝。

不把连接口令放在命令行：`DATABASE_URL` 从受保护环境或 `backend/.env` 读取，
规则与判重 CLI 相同（拒绝占位口令、符号链接与全局可读的配置文件）。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.models.exam import Exam
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizAnswer, QuizSession
from app.models.user import User
from app.services.question_dedup_service import DedupError
from app.services.quiz_snapshot_service import freeze_final_answers
from scripts.deduplicate_questions import configured_url


class FinalizeError(ValueError):
    """仅含可公开的固定错误分类，不携带数据库异常正文。"""


@dataclass(frozen=True)
class Scope:
    username: str
    exam_slug: str


def parse_sessions(raw: str) -> tuple[int, ...]:
    """解析显式会话 ID 列表；重复、非正整数或空列表一律拒绝。

    只接受 ASCII 数字：`str.isdecimal()` 还认全角/阿拉伯-印度数字，会静默接受
    非操作者本意的输入。
    """
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(not re.fullmatch(r"[0-9]+", part) or int(part) <= 0 for part in parts):
        raise FinalizeError("INVALID_SESSIONS")
    ids = tuple(int(part) for part in parts)
    if len(set(ids)) != len(ids):
        raise FinalizeError("INVALID_SESSIONS")
    return ids


@dataclass
class SessionResult:
    session_id: int
    status: str
    total_questions: int = 0
    answers: int = 0
    frozen: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "total_questions": self.total_questions,
            "answers": self.answers,
            "frozen": self.frozen,
            # 已完成会话没有重算，报 0/0 会被误读成「冻结为空」。
            "recomputed": self.status != "already_completed",
        }


@dataclass
class FinalizeResult:
    sessions: list[SessionResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(result.status == status for result in self.sessions)


def _resolve_scope(db: Session, scope: Scope) -> tuple[User, Exam]:
    user = db.execute(select(User).where(User.username == scope.username)).scalars().one_or_none()
    if user is None:
        raise FinalizeError("OWNER_NOT_FOUND")
    exam = db.execute(
        select(Exam).where(Exam.owner_id == user.id, Exam.slug == scope.exam_slug)
    ).scalars().one_or_none()
    if exam is None:
        raise FinalizeError("EXAM_NOT_FOUND")
    return user, exam


def _question_ids(session: QuizSession) -> list[int]:
    try:
        raw = json.loads(session.question_ids) if session.question_ids else []
    except ValueError:
        raise FinalizeError("UNKNOWN_SESSION_STRUCTURE") from None
    if not isinstance(raw, list) or any(type(item) is not int for item in raw):
        raise FinalizeError("UNKNOWN_SESSION_STRUCTURE")
    return raw


def finalize_sessions(db: Session, scope: Scope, session_ids: tuple[int, ...], *, apply: bool = False) -> FinalizeResult:
    """校验并（可选）结束指定会话；任何校验失败在第一条写入之前抛出。"""
    if not session_ids:
        raise FinalizeError("INVALID_SESSIONS")
    user, exam = _resolve_scope(db, scope)
    # 两阶段：先整批只读校验并算好冻结内容，再统一写入。逐条边校验边改会让排在
    # 非法会话之前的合法会话先被改脏，与「校验失败发生在第一条写入之前」不符；
    # 调用方若在异常后提交（或复用同一会话），半批结束结果就会落库。
    entries: list[SessionResult] = []
    planned: list[tuple[QuizSession, int, dict | None, int]] = []
    for session_id in sorted(session_ids):
        session = db.execute(
            select(QuizSession).where(QuizSession.id == session_id).with_for_update()
        ).scalars().one_or_none()
        if session is None:
            raise FinalizeError("SESSION_NOT_FOUND")
        bank = db.get(QuestionBank, session.bank_id)
        if session.user_id != user.id or bank is None or bank.exam_id != exam.id:
            raise FinalizeError("SESSION_NOT_IN_SCOPE")
        if session.is_completed:
            entries.append(SessionResult(session_id, "already_completed"))
            continue
        question_ids = _question_ids(session)
        if question_ids and not session.question_snapshot:
            # 冻结后判定可读但当场题面取不到，复盘会永远残缺；拒绝而不是伪造。
            raise FinalizeError("MISSING_SESSION_SNAPSHOT")
        answers = db.execute(
            select(QuizAnswer).where(QuizAnswer.session_id == session.id)
        ).scalars().all()
        frozen = freeze_final_answers(question_ids, answers) if question_ids else None
        planned.append((session, session_id, frozen, len(answers)))
    for session, session_id, frozen, answer_count in planned:
        if apply:
            session.is_completed = True
            session.completed_at = datetime.now(timezone.utc)
            if frozen is not None:
                session.final_answers = frozen
        entries.append(SessionResult(
            session_id,
            "finalized" if apply else "would_finalize",
            total_questions=session.total_questions,
            answers=answer_count,
            frozen=len(frozen or {}),
        ))
    result = FinalizeResult(sessions=sorted(entries, key=lambda entry: entry.session_id))
    if apply:
        db.commit()
    else:
        db.rollback()
    return result


def _print_result(result: FinalizeResult, *, apply: bool) -> None:
    print(json.dumps({
        "mode": "apply" if apply else "dry_run",
        "sessions": [entry.to_dict() for entry in result.sessions],
        "finalized": result.count("finalized") if apply else result.count("would_finalize"),
        "already_completed": result.count("already_completed"),
    }, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, help="显式会话 ID 列表，如 34,37,38,125")
    parser.add_argument("--user", default="nianyu")
    parser.add_argument("--exam", default="cipt")
    parser.add_argument("--apply", action="store_true", help="写入数据库；默认只读校验。")
    args = parser.parse_args(argv)
    engine = None
    try:
        session_ids = parse_sessions(args.sessions)
        engine = create_engine(configured_url(), connect_args={"options": "-c statement_timeout=30000 -c lock_timeout=3000"}, pool_pre_ping=True)
        with Session(engine, autoflush=False) as db:
            result = finalize_sessions(db, Scope(args.user, args.exam), session_ids, apply=args.apply)
        _print_result(result, apply=args.apply)
        return 0
    except (FinalizeError, DedupError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    except Exception:
        # 原始 SQL/URL 可能包含秘密，不输出 traceback 或异常正文。
        print('{"error":"FINALIZE_OPERATION_FAILED"}', file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
