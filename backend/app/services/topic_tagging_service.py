"""考点打标服务 - 用 AI 把题目归类到考试大纲的能力项

打标只写 source="ai" 的关联；人工修正（source="manual"）不受批量打标影响。
AI 判不准时允许返回空列表，该题落入「未分类」，不强行归类。
"""

import json
import logging

from sqlalchemy.orm import Session

from app.models.exam_topic import ExamTopic, TOPIC_LEVEL_COMPETENCY
from app.models.question import Question
from app.models.question_topic import QuestionTopic, TOPIC_SOURCE_AI
from app.services.ai_service import call_ai_api, strip_code_fence
from app.services.topic_service import list_unclassified_question_ids

logger = logging.getLogger(__name__)

TAGGING_BATCH_SIZE = 10
TAGGING_TIMEOUT = 120.0

SYSTEM_PROMPT = (
    "你是一位 CIPT（认证信息隐私技术师）考试命题分析专家。"
    "你的任务是把每道考题归类到官方考纲的能力项编码上。"
    "判断依据是题目考查的知识点，而不是题面出现的字面词汇。"
    "一道题可以同时属于多个能力项；如果无法确定，返回空数组，不要勉强归类。"
    '返回 JSON 格式：{"results": [{"no": 1, "codes": ["II.A"]}, ...]}，'
    "codes 只能取给定的能力项编码，不得自创。只返回 JSON，不要其他内容。"
)


def build_taxonomy_prompt(competencies: list[ExamTopic]) -> str:
    """把能力项及其表现指标拼成打标用的考纲说明"""
    lines = ["可选的能力项编码及其含义："]
    for topic in competencies:
        lines.append(f"\n[{topic.code}] {topic.name_en}")
        for indicator in topic.indicators_en or []:
            lines.append(f"  - {indicator}")
    return "\n".join(lines)


def build_questions_prompt(questions: list[Question]) -> str:
    """把一批题目编号后拼进 prompt；编号是本批内的序号，与题目 id 无关"""
    blocks = []
    for index, question in enumerate(questions, start=1):
        options = question.options
        if isinstance(options, str):
            options = json.loads(options)
        option_lines = [
            f"  {item.get('key')}. {item.get('text')}"
            for item in (options or [])
            if isinstance(item, dict)
        ]
        block = f"题目 {index}:\n{question.content}"
        if option_lines:
            block += "\n" + "\n".join(option_lines)
        blocks.append(block)
    return "\n\n".join(blocks)


def parse_tagging_response(raw: str, batch_size: int, valid_codes: set[str]) -> dict[int, list[str]]:
    """解析 AI 的打标响应。

    返回本批序号（1-based）到合法能力项编码列表的映射。不在 valid_codes 内的
    编码会被丢弃，越界或缺失的序号不会出现在结果里。响应整体无法解析时抛
    ValueError，交由任务重试机制处理。
    """
    text = strip_code_fence(raw or "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"打标响应不是合法 JSON: {text[:200]}") from exc

    results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(results, list):
        raise ValueError("打标响应缺少 results 数组")

    parsed: dict[int, list[str]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            no = int(item.get("no"))
        except (TypeError, ValueError):
            continue
        if not 1 <= no <= batch_size:
            continue

        codes = item.get("codes")
        if not isinstance(codes, list):
            codes = []
        kept = []
        dropped = []
        for code in codes:
            if not isinstance(code, str):
                dropped.append(repr(code))
                continue
            normalized = code.strip().upper()
            if normalized not in valid_codes:
                dropped.append(normalized)
            elif normalized not in kept:
                kept.append(normalized)
        if dropped:
            # 模型幻觉出来的编码不能落库，但要留痕以便回看打标质量
            logger.warning("题目 %s 返回了考点树外的编码，已丢弃: %s", no, dropped)
        parsed[no] = kept

    return parsed


def list_untagged_question_ids(db: Session, bank_id: int) -> list[int]:
    """题库中还没有任何考点关联的题目 id，即待打标题目。

    判定条件是「没有任何关联」而不是「没有 AI 关联」：人工设过考点的题目
    如果被当成待打标，下一轮打标会在人工结果之上再叠加 AI 标签。
    要用新 prompt 重打，先清掉 source="ai" 的关联行。

    因此「待打标」与「未分类」是同一个集合，查询复用 topic_service 的实现。
    """
    return list_unclassified_question_ids(db, bank_id)


def load_competencies(db: Session, exam_id: int) -> list[ExamTopic]:
    """按考纲顺序（域序 → 域内序）列出能力项。

    order_index 只在域内唯一（每个域都从 1 开始），跨域会重复，所以必须先按
    所属域的顺序排。只按 order_index 排会把考纲横向串成 I.A、II.A、III.A…，
    且同值之间的次序由数据库决定，打标 prompt 的考纲部分会不稳定。
    """
    parent = ExamTopic.__table__.alias("parent_topic")
    return (
        db.query(ExamTopic)
        .join(parent, ExamTopic.parent_id == parent.c.id)
        .filter(ExamTopic.exam_id == exam_id, ExamTopic.level == TOPIC_LEVEL_COMPETENCY)
        .order_by(parent.c.order_index, ExamTopic.order_index, ExamTopic.code)
        .all()
    )


def tag_question_batch(
    db: Session,
    questions: list[Question],
    competencies: list[ExamTopic],
) -> tuple[int, int]:
    """给一批题目打标，返回 (打上考点的题数, 未归类的题数)。

    两个计数之和等于本批题数——每道题都算处理过，判不准的记为跳过。
    """
    if not questions:
        return 0, 0

    topic_id_by_code = {topic.code: topic.id for topic in competencies}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{build_taxonomy_prompt(competencies)}\n\n"
                f"请为下面 {len(questions)} 道题分别给出能力项编码。\n\n"
                f"{build_questions_prompt(questions)}"
            ),
        },
    ]

    raw = call_ai_api(messages, db, scene="default", timeout=TAGGING_TIMEOUT)
    parsed = parse_tagging_response(raw, len(questions), set(topic_id_by_code))

    tagged_count = 0
    for index, question in enumerate(questions, start=1):
        codes = parsed.get(index, [])
        if not codes:
            logger.info("题目 %s 未能归类到任何考点，归入未分类", question.id)
            continue
        for code in codes:
            db.add(
                QuestionTopic(
                    question_id=question.id,
                    topic_id=topic_id_by_code[code],
                    source=TOPIC_SOURCE_AI,
                )
            )
        tagged_count += 1

    db.commit()
    return tagged_count, len(questions) - tagged_count
