"""考点服务 - 考点树的灌入与查询"""

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.exam import Exam
from app.models.exam_topic import ExamTopic, TOPIC_LEVEL_COMPETENCY, TOPIC_LEVEL_DOMAIN
from app.models.question import Question
from app.models.question_topic import QuestionTopic, TOPIC_SOURCE_MANUAL
from app.models.quiz import QuizSession

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "topic_templates"


def load_topic_template(template_id: str) -> dict:
    """按模板 id 读取考点树模板文件"""
    path = TEMPLATE_DIR / f"{template_id}.json"
    if not path.exists():
        raise ValueError(f"考点模板不存在: {template_id}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def seed_exam_topics(db: Session, exam: Exam, template: dict) -> dict:
    """把考点树模板灌入指定考试项目，按 (exam_id, code) upsert。

    可重复执行：已存在的考点更新字段，不存在的新建。返回各项计数。
    """
    source_version = template["source_version"]
    existing = {
        topic.code: topic
        for topic in db.query(ExamTopic).filter_by(exam_id=exam.id).all()
    }
    created = 0
    updated = 0

    def upsert(node: dict, level: int, parent_id: int | None) -> ExamTopic:
        nonlocal created, updated
        topic = existing.get(node["code"])
        if topic is None:
            topic = ExamTopic(exam_id=exam.id, code=node["code"])
            db.add(topic)
            existing[node["code"]] = topic
            created += 1
        else:
            updated += 1
        topic.parent_id = parent_id
        topic.level = level
        topic.name_en = node["name_en"]
        topic.name_zh = node["name_zh"]
        topic.short_name_zh = node["short_name_zh"]
        topic.blueprint_min = node["blueprint_min"]
        topic.blueprint_max = node["blueprint_max"]
        topic.indicators_en = list(node.get("indicators_en", []))
        topic.order_index = node["order_index"]
        topic.source_version = source_version
        return topic

    for domain_node in template["domains"]:
        domain = upsert(domain_node, TOPIC_LEVEL_DOMAIN, None)
        # 域必须先落库拿到主键，子考点才能引用
        db.flush()
        for competency_node in domain_node.get("competencies", []):
            upsert(competency_node, TOPIC_LEVEL_COMPETENCY, domain.id)
        db.flush()

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "total": created + updated,
        "source_version": source_version,
    }


def list_competency_ids(db: Session, exam_id: int) -> dict[str, int]:
    """返回该考试项目下 code -> id 的能力项映射，供打标校验 AI 返回的编码"""
    rows = db.execute(
        select(ExamTopic.code, ExamTopic.id).where(
            ExamTopic.exam_id == exam_id,
            ExamTopic.level == TOPIC_LEVEL_COMPETENCY,
        )
    ).all()
    return {code: topic_id for code, topic_id in rows}


def topic_number(domain_order: int, competency_order: int | None = None) -> str:
    """界面用的阿拉伯数字编号。官方 BOK 编码（I.A）只留给打标 prompt。"""
    if competency_order is None:
        return str(domain_order)
    return f"{domain_order}.{competency_order}"


def _question_counts_by_topic(db: Session, bank_id: int) -> dict[int, int]:
    """每个能力项在该题库中的去重题数"""
    return dict(
        db.execute(
            select(QuestionTopic.topic_id, func.count(func.distinct(QuestionTopic.question_id)))
            .join(Question, QuestionTopic.question_id == Question.id)
            .where(Question.bank_id == bank_id)
            .group_by(QuestionTopic.topic_id)
        ).all()
    )


def _topic_session_flags(
    db: Session, user_id: int, bank_id: int
) -> tuple[set[int], set[int], bool, bool]:
    """当前用户在该题库的专项练习覆盖：已练 / 进行中的考点 id，以及未分类两态。"""
    rows = db.execute(
        select(QuizSession.topic_id, QuizSession.is_completed).where(
            QuizSession.user_id == user_id,
            QuizSession.bank_id == bank_id,
            QuizSession.mode == "topic",
        )
    ).all()
    practiced_ids: set[int] = set()
    in_progress_ids: set[int] = set()
    unclassified_practiced = False
    unclassified_in_progress = False
    for topic_id, is_completed in rows:
        if topic_id is None:
            if is_completed:
                unclassified_practiced = True
            else:
                unclassified_in_progress = True
            continue
        if is_completed:
            practiced_ids.add(topic_id)
        else:
            in_progress_ids.add(topic_id)
    return practiced_ids, in_progress_ids, unclassified_practiced, unclassified_in_progress


def list_bank_topic_overview(
    db: Session, exam_id: int, bank_id: int, user_id: int | None = None
) -> dict:
    """题库维度的考点概览：每个域及其能力项的题数、考试出题配额，以及未分类题数。

    域的题数是其下能力项关联题目的去重计数——一道题挂了同域两个能力项只算一次。
    传入 user_id 时附上该用户的已练 / 进行中标记；不传则两态均为假。
    """
    domains = (
        db.query(ExamTopic)
        .filter_by(exam_id=exam_id, level=TOPIC_LEVEL_DOMAIN)
        .order_by(ExamTopic.order_index)
        .all()
    )

    parent = ExamTopic.__table__.alias("parent_topic")
    counts_by_domain = dict(
        db.execute(
            select(parent.c.id, func.count(func.distinct(QuestionTopic.question_id)))
            .select_from(QuestionTopic)
            .join(ExamTopic, QuestionTopic.topic_id == ExamTopic.id)
            .join(parent, ExamTopic.parent_id == parent.c.id)
            .join(Question, QuestionTopic.question_id == Question.id)
            .where(Question.bank_id == bank_id)
            .group_by(parent.c.id)
        ).all()
    )
    counts_by_competency = _question_counts_by_topic(db, bank_id)
    competencies = list_competencies(db, exam_id, counts_by_competency)
    competencies_by_parent: dict[int, list[dict]] = {}
    for competency in competencies:
        competencies_by_parent.setdefault(competency["parent_id"], []).append(competency)

    total_questions = db.query(func.count(Question.id)).filter_by(bank_id=bank_id).scalar() or 0
    classified = (
        db.query(func.count(func.distinct(QuestionTopic.question_id)))
        .join(Question, QuestionTopic.question_id == Question.id)
        .filter(Question.bank_id == bank_id)
        .scalar()
        or 0
    )

    if user_id is None:
        practiced_ids, in_progress_ids = set(), set()
        unclassified_practiced = False
        unclassified_in_progress = False
    else:
        (
            practiced_ids,
            in_progress_ids,
            unclassified_practiced,
            unclassified_in_progress,
        ) = _topic_session_flags(db, user_id, bank_id)

    for competency in competencies:
        competency["practiced"] = competency["id"] in practiced_ids
        competency["in_progress"] = competency["id"] in in_progress_ids

    return {
        "topics": [
            {
                "id": domain.id,
                "code": domain.code,
                "number": topic_number(domain.order_index),
                "name_zh": domain.name_zh,
                "short_name_zh": domain.short_name_zh,
                "blueprint_min": domain.blueprint_min,
                "blueprint_max": domain.blueprint_max,
                "question_count": counts_by_domain.get(domain.id, 0),
                "competencies": competencies_by_parent.get(domain.id, []),
            }
            for domain in domains
        ],
        # 扁平列表留给管理端人工设定单题考点，避免前端再拆一次树
        "competencies": competencies,
        "unclassified_count": total_questions - classified,
        "unclassified_practiced": unclassified_practiced,
        "unclassified_in_progress": unclassified_in_progress,
        "total_questions": total_questions,
    }


def list_competencies(
    db: Session,
    exam_id: int,
    counts_by_competency: dict[int, int] | None = None,
) -> list[dict]:
    """按域顺序、域内顺序列出所有能力项"""
    parent = ExamTopic.__table__.alias("parent_topic")
    rows = db.execute(
        select(
            ExamTopic.id,
            ExamTopic.parent_id,
            ExamTopic.code,
            ExamTopic.short_name_zh,
            ExamTopic.name_zh,
            ExamTopic.blueprint_min,
            ExamTopic.blueprint_max,
            parent.c.order_index,
            ExamTopic.order_index,
        )
        .join(parent, ExamTopic.parent_id == parent.c.id)
        .where(
            ExamTopic.exam_id == exam_id,
            ExamTopic.level == TOPIC_LEVEL_COMPETENCY,
        )
        .order_by(parent.c.order_index, ExamTopic.order_index, ExamTopic.code)
    ).all()
    counts = counts_by_competency or {}
    return [
        {
            "id": topic_id,
            "parent_id": parent_id,
            "code": code,
            "number": topic_number(domain_order, competency_order),
            "short_name_zh": short_name_zh,
            "name_zh": name_zh,
            "blueprint_min": blueprint_min,
            "blueprint_max": blueprint_max,
            "question_count": counts.get(topic_id, 0),
        }
        for (
            topic_id,
            parent_id,
            code,
            short_name_zh,
            name_zh,
            blueprint_min,
            blueprint_max,
            domain_order,
            competency_order,
        ) in rows
    ]


def list_question_ids_for_domain(db: Session, bank_id: int, domain_id: int) -> list[int]:
    """某个域下所有能力项关联到的题目 id，去重并按题目顺序返回"""
    rows = db.execute(
        select(Question.id)
        .distinct()
        .select_from(Question)
        .join(QuestionTopic, QuestionTopic.question_id == Question.id)
        .join(ExamTopic, QuestionTopic.topic_id == ExamTopic.id)
        .where(Question.bank_id == bank_id, ExamTopic.parent_id == domain_id)
        .order_by(Question.id)
    ).all()
    return [row[0] for row in rows]


def list_question_ids_for_competency(db: Session, bank_id: int, competency_id: int) -> list[int]:
    """某个能力项直接关联的题目 id，按题目顺序返回"""
    rows = db.execute(
        select(Question.id)
        .join(QuestionTopic, QuestionTopic.question_id == Question.id)
        .where(Question.bank_id == bank_id, QuestionTopic.topic_id == competency_id)
        .order_by(Question.id)
    ).all()
    return [row[0] for row in rows]


def list_unclassified_question_ids(db: Session, bank_id: int) -> list[int]:
    """题库中没有任何考点关联的题目 id"""
    rows = db.execute(
        select(Question.id)
        .where(
            Question.bank_id == bank_id,
            ~select(QuestionTopic.question_id)
            .where(QuestionTopic.question_id == Question.id)
            .exists(),
        )
        .order_by(Question.id)
    ).all()
    return [row[0] for row in rows]


def set_question_topics_manually(db: Session, question: Question, topic_ids: list[int]) -> None:
    """整份替换某道题的考点，写为人工来源。

    只接受本考试项目下的能力项：域级考点不能直接关联，否则按域汇总题目时
    （list_question_ids_for_domain 走 parent_id）会漏掉这道题。
    """
    exam_id = question.bank.exam_id
    unique_ids = list(dict.fromkeys(topic_ids))
    if unique_ids:
        valid_ids = {
            row[0]
            for row in db.execute(
                select(ExamTopic.id).where(
                    ExamTopic.id.in_(unique_ids),
                    ExamTopic.exam_id == exam_id,
                    ExamTopic.level == TOPIC_LEVEL_COMPETENCY,
                )
            ).all()
        }
        invalid = [topic_id for topic_id in unique_ids if topic_id not in valid_ids]
        if invalid:
            raise ValueError(f"考点不存在或不可直接关联: {invalid}")

    # 考点没变时原样保留：题目管理页每次保存都会带上 topic_ids，若无条件重建，
    # 只改题干也会把 AI 打的标转成 source="manual"，之后清 source="ai" 重打标就清不掉了
    existing_ids = {
        row[0]
        for row in db.execute(
            select(QuestionTopic.topic_id).where(QuestionTopic.question_id == question.id)
        ).all()
    }
    if existing_ids == set(unique_ids):
        return

    db.query(QuestionTopic).filter_by(question_id=question.id).delete(synchronize_session=False)
    for topic_id in unique_ids:
        db.add(
            QuestionTopic(
                question_id=question.id,
                topic_id=topic_id,
                source=TOPIC_SOURCE_MANUAL,
            )
        )


def topics_for_questions(db: Session, question_ids: list[int]) -> dict[int, list[dict]]:
    """批量取题目的考点，返回 question_id -> [{id, code, short_name_zh}]"""
    if not question_ids:
        return {}
    # order_index 每个域内都从 1 开始，跨域重复，必须先按域序排并补 code 兜底，
    # 否则同一道题的多个考点标签次序由数据库决定
    parent = ExamTopic.__table__.alias("parent_topic")
    rows = db.execute(
        select(
            QuestionTopic.question_id,
            ExamTopic.id,
            ExamTopic.code,
            ExamTopic.short_name_zh,
            parent.c.order_index,
            ExamTopic.order_index,
        )
        .join(ExamTopic, QuestionTopic.topic_id == ExamTopic.id)
        .join(parent, ExamTopic.parent_id == parent.c.id)
        .where(QuestionTopic.question_id.in_(question_ids))
        .order_by(parent.c.order_index, ExamTopic.order_index, ExamTopic.code)
    ).all()

    result: dict[int, list[dict]] = {}
    for question_id, topic_id, code, short_name_zh, domain_order, competency_order in rows:
        result.setdefault(question_id, []).append(
            {
                "id": topic_id,
                "code": code,
                "number": topic_number(domain_order, competency_order),
                "short_name_zh": short_name_zh,
            }
        )
    return result
