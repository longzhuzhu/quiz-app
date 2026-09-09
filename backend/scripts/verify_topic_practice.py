"""专项练习端到端验收脚本（对真实数据库执行，只读 + 创建一次答题会话）

用法：
    python3 backend/scripts/verify_topic_practice.py --exam-slug cipt --bank-id 12
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.main import create_app
from app.models.exam import Exam
from app.models.quiz import QuizSession
from app.models.user import User

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exam-slug", default="cipt")
    parser.add_argument("--bank-id", type=int, required=True)
    args = parser.parse_args()

    db = SessionLocal()
    exam = db.query(Exam).filter_by(slug=args.exam_slug).order_by(Exam.id).first()
    owner = db.get(User, exam.owner_id)
    token = create_access_token(str(owner.id))
    exam_slug = exam.slug
    db.close()

    client = TestClient(create_app())
    headers = {"Authorization": f"Bearer {token}", "X-Exam-Slug": exam_slug}

    resp = client.get(f"/api/banks/{args.bank_id}/topics", headers=headers)
    check("AC6 考点概览可获取", resp.status_code == 200, f"HTTP {resp.status_code}")
    overview = resp.json()

    domains = overview["topics"]
    check("AC6 返回 5 个域", len(domains) == 5, f"实际 {len(domains)} 个")
    competencies = [c for d in domains for c in d.get("competencies") or []]
    check("AC6 域下挂出 16 个能力项", len(competencies) == 16, f"实际 {len(competencies)} 个")
    check(
        "AC6 每个域都带蓝图配额",
        all(d["blueprint_max"] > 0 for d in domains),
        ", ".join(f"{d['code']}={d['blueprint_min']}-{d['blueprint_max']}" for d in domains),
    )
    check(
        "AC6 每个能力项都带题数和配额",
        all("question_count" in c and c.get("blueprint_max", 0) > 0 for c in competencies),
    )

    classified = overview["total_questions"] - overview["unclassified_count"]
    check(
        "AC6 题数勾稽：有考点 + 未分类 = 总数",
        classified + overview["unclassified_count"] == overview["total_questions"],
        f"{classified} + {overview['unclassified_count']} = {overview['total_questions']}",
    )

    target = next((c for c in competencies if c["question_count"] > 0), None)
    if target is None:
        check("AC7 专项练习出题", False, "没有任何能力项有题目，先跑批量打标")
        return

    resp = client.post(
        "/api/quiz/start",
        json={"bank_id": args.bank_id, "mode": "topic", "topic_id": target["id"]},
        headers=headers,
    )
    check("AC7 专项练习可开始", resp.status_code == 200, f"HTTP {resp.status_code} {resp.text[:200]}")
    started = resp.json()
    session_id = started["session"]["id"]
    question_ids = [q["id"] for q in started["questions"]]

    check(
        "AC7 出题数等于该能力项题数",
        len(question_ids) == target["question_count"],
        f"出题 {len(question_ids)}，能力项 {target['question_count']}",
    )
    check("AC7 题目不重复", len(question_ids) == len(set(question_ids)))
    check(
        "AC7 会话记录了所练考点",
        started["session"]["topic_short_name"] == target["short_name_zh"],
        str(started["session"]["topic_short_name"]),
    )

    from app.services.topic_service import list_question_ids_for_competency

    db = SessionLocal()
    expected = set(list_question_ids_for_competency(db, args.bank_id, target["id"]))
    check("AC7 出题范围全部属于该能力项", set(question_ids) == expected)

    resp = client.get(f"/api/quiz/session/{session_id}", headers=headers)
    check(
        "AC9 会话详情带考点名（继续答题可辨识）",
        resp.status_code == 200 and resp.json()["session"]["topic_short_name"] == target["short_name_zh"],
        str(resp.json().get("session", {}).get("topic_short_name")),
    )

    resp = client.get("/api/quiz/history", params={"page": 1, "per_page": 5}, headers=headers)
    items = resp.json()["items"]
    topic_item = next((i for i in items if i["id"] == session_id), None)
    check(
        "AC10 答题历史带模式与考点名",
        topic_item is not None
        and topic_item["mode"] == "topic"
        and topic_item["topic_short_name"] == target["short_name_zh"],
        str(topic_item and (topic_item["mode"], topic_item["topic_short_name"])),
    )
    check(
        "AC11 存量非专项会话不受影响",
        all(i["topic_short_name"] is None for i in items if i["mode"] != "topic"),
    )

    if overview["unclassified_count"] > 0:
        resp = client.post(
            "/api/quiz/start",
            json={"bank_id": args.bank_id, "mode": "topic", "topic_id": None},
            headers=headers,
        )
        check("AC8 未分类专项可开始", resp.status_code == 200, f"HTTP {resp.status_code}")
        unclassified_ids = [q["id"] for q in resp.json()["questions"]]
        from app.services.topic_service import list_unclassified_question_ids

        check(
            "AC8 未分类出题全部无考点关联",
            set(unclassified_ids) == set(list_unclassified_question_ids(db, args.bank_id)),
            f"出题 {len(unclassified_ids)}，未分类 {overview['unclassified_count']}",
        )
        unclassified_session_id = resp.json()["session"]["id"]
    else:
        unclassified_session_id = None

    # 清理本次验收产生的会话，避免污染答题历史
    for sid in filter(None, [session_id, unclassified_session_id]):
        session = db.get(QuizSession, sid)
        if session:
            db.delete(session)
    db.commit()
    db.close()

    failed = [name for name, passed, _ in CHECKS if not passed]
    print(f"\n合计 {len(CHECKS)} 项，失败 {len(failed)} 项")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
