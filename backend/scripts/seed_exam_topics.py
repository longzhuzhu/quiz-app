"""把考点树模板灌入指定考试项目

用法：
    python3 backend/scripts/seed_exam_topics.py --exam-slug cipt
    python3 backend/scripts/seed_exam_topics.py --exam-slug cipt --template cipt-bok-4.0.0

可重复执行：已存在的考点按 (exam_id, code) 更新，不产生重复行。
"""

import argparse
import os
import sys

# 将 backend 目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import SessionLocal
from app.models.exam import Exam
from app.services.topic_service import load_topic_template, seed_exam_topics

DEFAULT_TEMPLATE = "cipt-bok-4.0.0"


def resolve_exam(db, slug: str, owner_id: int | None) -> Exam:
    query = db.query(Exam).filter_by(slug=slug)
    if owner_id is not None:
        query = query.filter_by(owner_id=owner_id)
    exams = query.order_by(Exam.id).all()

    if not exams:
        raise SystemExit(f"未找到 slug 为 {slug} 的考试项目")
    if len(exams) > 1:
        owners = ", ".join(f"exam_id={e.id} owner_id={e.owner_id}" for e in exams)
        raise SystemExit(
            f"slug 为 {slug} 的考试项目有多个（{owners}），请用 --owner-id 指定其中一个"
        )
    return exams[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="灌入考试项目的考点树")
    parser.add_argument("--exam-slug", required=True, help="目标考试项目的 slug")
    parser.add_argument("--owner-id", type=int, default=None, help="slug 重名时用于消歧")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help="考点模板 id")
    args = parser.parse_args()

    template = load_topic_template(args.template)
    db = SessionLocal()
    try:
        exam = resolve_exam(db, args.exam_slug, args.owner_id)
        # commit 会让 exam 的属性过期，关闭 session 前先取出用于回显
        exam_slug, exam_id = exam.slug, exam.id
        result = seed_exam_topics(db, exam, template)
    finally:
        db.close()

    print(
        f"考试项目 {exam_slug}(id={exam_id}) 考点灌入完成："
        f"新建 {result['created']}，更新 {result['updated']}，"
        f"共 {result['total']} 条，大纲版本 {result['source_version']}"
    )


if __name__ == "__main__":
    main()
