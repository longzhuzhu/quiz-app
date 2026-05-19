"""一次性清空正式题目的 AI 解析字段。

默认 dry-run，只统计将清空的正式题目数量；传入 --apply 才会写入数据库。
不会修改 ImportParsedQuestion.explanation，导入解析记录仍保留用于追溯。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.question import Question  # noqa: E402


@dataclass
class ClearQuestionExplanationsResult:
    matched: int = 0
    updated: int = 0


def clear_question_explanations(db, *, apply: bool = False) -> ClearQuestionExplanationsResult:
    """清空 Question.explanation / explanation_zh。

    dry-run 模式只统计至少一个解析字段非空的正式题目数量，并 rollback 防止会话内误写。
    apply=True 时仅修改 Question 表，不触碰导入解析记录。
    """
    query = db.query(Question).filter(
        (Question.explanation.isnot(None)) | (Question.explanation_zh.isnot(None))
    )
    matched = query.count()
    result = ClearQuestionExplanationsResult(matched=matched, updated=0)

    if apply and matched:
        result.updated = query.update(
            {Question.explanation: None, Question.explanation_zh: None},
            synchronize_session=False,
        )
        db.commit()
    else:
        db.rollback()

    return result


def _print_result(result: ClearQuestionExplanationsResult, *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"模式: {mode}")
    print(f"将清空解析字段的正式题目数量: {result.matched}")
    print(f"已更新正式题目数量: {result.updated}")
    if not apply:
        print("未传入 --apply，未修改数据库。")


def main() -> None:
    parser = argparse.ArgumentParser(description="清空正式题目的 AI 解析字段，默认 dry-run。")
    parser.add_argument("--apply", action="store_true", help="显式写入数据库；默认仅统计。")
    args = parser.parse_args()

    from app.core.database import SessionLocal

    print(f"开始时间: {datetime.now(timezone.utc).isoformat()}")
    db = SessionLocal()
    try:
        result = clear_question_explanations(db, apply=args.apply)
        _print_result(result, apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
