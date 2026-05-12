"""一次性回填场景题完整题干。

默认 dry-run，只输出将修改的题目；传入 --apply 才会写入数据库。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.import_parsed_question import ImportParsedQuestion  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.services.smart_import_service import (  # noqa: E402
    _content_equivalent_for_backfill,
    build_full_question_content,
)


@dataclass
class BackfillResult:
    scanned: int = 0
    matched: int = 0
    updated: int = 0
    skipped_no_question: int = 0
    skipped_no_scenario: int = 0
    skipped_content_mismatch: int = 0
    skipped_already_full: int = 0
    candidates: list[dict[str, Any]] | None = None


def backfill_scenario_question_content(db, *, apply: bool = False, limit: int | None = None) -> BackfillResult:
    """安全回填 Question.content = scenario_text + 空行 + content。

    保护条件：
    - ImportParsedQuestion.imported_question_id 必须能指向正式 Question；
    - scenario_text 非空；
    - Question.content 必须仍与 ImportParsedQuestion.content 等价，避免覆盖人工编辑。
    """
    result = BackfillResult(candidates=[])
    query = (
        db.query(ImportParsedQuestion)
        .filter(ImportParsedQuestion.imported_question_id.isnot(None))
        .order_by(ImportParsedQuestion.id.asc())
    )
    if limit:
        query = query.limit(limit)

    for parsed_question in query.all():
        result.scanned += 1
        scenario_text = (parsed_question.scenario_text or "").strip()
        if not scenario_text:
            result.skipped_no_scenario += 1
            continue

        question = db.get(Question, parsed_question.imported_question_id)
        if not question:
            result.skipped_no_question += 1
            continue

        full_content = build_full_question_content(scenario_text, parsed_question.content)
        if _content_equivalent_for_backfill(question.content, full_content):
            result.skipped_already_full += 1
            continue

        if not _content_equivalent_for_backfill(question.content, parsed_question.content):
            result.skipped_content_mismatch += 1
            continue

        result.matched += 1
        result.candidates.append({
            "parsed_question_id": parsed_question.id,
            "question_id": question.id,
            "bank_id": question.bank_id,
            "source_question_no": parsed_question.source_question_no,
            "old_preview": (question.content or "")[:160],
            "new_preview": full_content[:240],
        })
        if apply:
            question.content = full_content
            result.updated += 1

    if apply and result.updated:
        db.commit()
    else:
        db.rollback()

    return result


def _print_result(result: BackfillResult, *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"模式: {mode}")
    print(
        "扫描 {scanned} 条，候选 {matched} 条，已更新 {updated} 条；"
        "跳过：无正式题 {skipped_no_question}、无 scenario {skipped_no_scenario}、"
        "疑似人工编辑 {skipped_content_mismatch}、已是完整题干 {skipped_already_full}".format(
            **result.__dict__
        )
    )
    for item in result.candidates or []:
        print(
            f"- Question #{item['question_id']} bank={item['bank_id']} "
            f"source_qno={item['source_question_no']} parsed={item['parsed_question_id']}"
        )
        print(f"  OLD: {item['old_preview']}")
        print(f"  NEW: {item['new_preview']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="回填场景题完整题干，默认 dry-run。")
    parser.add_argument("--apply", action="store_true", help="显式写入数据库；默认仅预览。")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描多少条导入解析记录。")
    args = parser.parse_args()

    from app.core.database import SessionLocal

    print(f"开始时间: {datetime.now(timezone.utc).isoformat()}")
    db = SessionLocal()
    try:
        result = backfill_scenario_question_content(db, apply=args.apply, limit=args.limit)
        _print_result(result, apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
