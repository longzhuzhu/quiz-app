"""考试项目共享服务。"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.bank_word import BankWordExclusion, BankWordFrequency, UserBankWordProgress
from app.models.background_job import BackgroundJob
from app.models.exam import Exam
from app.models.import_chunk import ImportChunk
from app.models.import_job import ImportJob
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.import_review_item import ImportReviewItem
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizAnswer, QuizSession
from app.models.user import User
from app.models.vector_index import VectorIndex
from app.models.vocabulary import UserVocabProgress, Vocabulary
from app.models.wrong import UserQuestionStat, WrongAnswer

DEFAULT_TRANSLATION_SYSTEM_PROMPT = (
    "你是专业考试题目的翻译助手。请将以下英文考试题目翻译为中文。"
    "保留技术缩写和专有名词。"
    '返回 JSON 格式：{"content_zh": "中文题目", "options_zh": [{"key": "A", "text_zh": "中文选项"}, ...]}'
    "只返回 JSON，不要其他内容。"
)

CIPT_TRANSLATION_SYSTEM_PROMPT = (
    "你是一位专业的隐私技术领域翻译专家。请将以下 CIPT 考试题目从英文翻译为中文。"
    "保留技术缩写（如 GDPR、PII、DPO、DPIA 等）不翻译。"
    '返回 JSON 格式：{"content_zh": "中文题目", "options_zh": [{"key": "A", "text_zh": "中文选项"}, ...]}'
    "只返回 JSON，不要其他内容。"
)

# 干扰项类型封闭枚举。固定取值范围才能让不同题目的解析可比，
# 考生也能据此积累"自己总是栽在哪一类干扰"的判断。
EXPLANATION_DISTRACTOR_TYPES = (
    "术语混淆",
    "范围过窄",
    "范围过宽",
    "时机错误",
    "层级错位",
    "看似正确但非最优",
    "与题干约束冲突",
    "无关干扰",
)

# 题干限定词。读反限定词是高频错因，需要在解析中被显式点出来。
EXPLANATION_STEM_QUALIFIERS = ("MOST", "BEST", "LEAST", "EXCEPT", "NOT", "PRIMARY", "FIRST")

_EXPLANATION_JSON_SHAPE = (
    '{"stem_breakdown": {"qualifier": "题干限定词", "role": "主体或视角", '
    '"scenario": "场景概括", "constraint": "限定条件", "asked": "到底问什么"}, '
    '"explanation": "英文解析", "explanation_zh": "中文知识点解析", '
    '"distractors": [{"key": "A", "type": "干扰项类型", "reason": "为什么错"}]}'
)


def _build_explanation_system_prompt(persona: str) -> str:
    return (
        persona
        + "考生母语为中文、正在备考全英文考试，除知识点之外还需要读题训练。请完成三件事："
        "一是拆解题干结构，让考生看清题目到底在问什么；"
        "二是解析正确答案的原理；"
        "三是逐个说明错误选项属于哪一类干扰、为什么错。"
        "stem_breakdown 字段要求："
        f"qualifier 只填题干中实际出现的限定词（{'/'.join(EXPLANATION_STEM_QUALIFIERS)} 等），没有则填空字符串；"
        "role 填题干的主体或视角；scenario 用一句话概括发生了什么；"
        "constraint 填题干给出的限定条件（法规、技术、数据生命周期阶段等），没有则填空字符串；"
        "asked 用一句中文说清到底问什么，并点明限定词的含义。"
        "distractors 只包含错误选项，不包含正确答案；"
        f"type 必须从以下枚举中选一个：{'、'.join(EXPLANATION_DISTRACTOR_TYPES)}。"
        "explanation_zh 只写正确答案的原理和相关知识点，不要重复题干拆解和干扰项分析的内容。"
        f"返回 JSON 格式：{_EXPLANATION_JSON_SHAPE}"
        "只返回 JSON，不要其他内容。"
    )


DEFAULT_EXPLANATION_SYSTEM_PROMPT = _build_explanation_system_prompt("你是专业考试辅导专家。")

CIPT_EXPLANATION_SYSTEM_PROMPT = _build_explanation_system_prompt(
    "你是一位 CIPT（认证信息隐私技术师）考试辅导专家。"
)

DEFAULT_AI_PROFILE = {
    "translation_system_prompt": DEFAULT_TRANSLATION_SYSTEM_PROMPT,
    "explanation_system_prompt": DEFAULT_EXPLANATION_SYSTEM_PROMPT,
    "vocab_extract_system_prompt": "从下列题目中识别专业术语。",
    "source_lang": "en",
    "target_lang": "zh-CN",
    "model_override": None,
    "enabled_features": ["translate", "explain", "vocab_extract"],
}

CIPT_AI_PROFILE = {
    **DEFAULT_AI_PROFILE,
    "translation_system_prompt": CIPT_TRANSLATION_SYSTEM_PROMPT,
    "explanation_system_prompt": CIPT_EXPLANATION_SYSTEM_PROMPT,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_owned_exam_or_404(db: Session, user: User, slug: str) -> Exam:
    exam = db.query(Exam).filter_by(owner_id=user.id, slug=slug).first()
    if exam is None:
        raise HTTPException(status_code=404, detail="考试项目不存在")
    return exam


def get_bank_in_exam_or_404(db: Session, bank_id: int, exam: Exam) -> QuestionBank:
    bank = db.query(QuestionBank).filter_by(id=bank_id, exam_id=exam.id).first()
    if bank is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


def get_question_in_exam_or_404(db: Session, question_id: int, exam: Exam) -> Question:
    question = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(Question.id == question_id, QuestionBank.exam_id == exam.id)
        .first()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


def get_import_job_in_exam_or_404(db: Session, job_id: int, exam: Exam) -> ImportJob:
    import_job = (
        db.query(ImportJob)
        .join(QuestionBank, ImportJob.bank_id == QuestionBank.id)
        .filter(ImportJob.id == job_id, QuestionBank.exam_id == exam.id)
        .first()
    )
    if import_job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return import_job


def serialize_exam(exam: Exam, db: Session, include_ai_profile: bool = True) -> dict:
    bank_count = db.query(QuestionBank).filter_by(exam_id=exam.id).count()
    question_count = (
        db.query(func.count(Question.id))
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(QuestionBank.exam_id == exam.id)
        .scalar()
        or 0
    )
    wrong_count = (
        db.query(func.count(WrongAnswer.id))
        .join(Question, WrongAnswer.question_id == Question.id)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(WrongAnswer.user_id == exam.owner_id, QuestionBank.exam_id == exam.id)
        .scalar()
        or 0
    )

    data = {
        "id": exam.id,
        "slug": exam.slug,
        "name": exam.name,
        "short_name": exam.short_name,
        "description": exam.description,
        "icon": exam.icon,
        "locale": exam.locale,
        "sort_order": exam.sort_order,
        "owner": {"id": exam.owner.id, "username": exam.owner.username} if exam.owner else None,
        "stats": {
            "bank_count": bank_count,
            "question_count": question_count,
            "wrong_count": wrong_count,
            "progress": 0.0,
        },
        "created_at": exam.created_at.isoformat(),
        "updated_at": exam.updated_at.isoformat() if exam.updated_at else None,
    }
    if include_ai_profile:
        data["ai_profile"] = exam.ai_profile or DEFAULT_AI_PROFILE
    return data


def delete_bank_data(db: Session, bank: QuestionBank) -> None:
    question_ids_subquery = db.query(Question.id).filter(Question.bank_id == bank.id)

    db.query(QuizAnswer).filter(QuizAnswer.question_id.in_(question_ids_subquery)).delete(synchronize_session=False)
    db.query(WrongAnswer).filter(WrongAnswer.question_id.in_(question_ids_subquery)).delete(synchronize_session=False)
    db.query(UserQuestionStat).filter(UserQuestionStat.question_id.in_(question_ids_subquery)).delete(synchronize_session=False)

    db.query(QuizSession).filter_by(bank_id=bank.id).delete(synchronize_session=False)
    db.query(BankWordFrequency).filter_by(bank_id=bank.id).delete(synchronize_session=False)
    db.query(UserBankWordProgress).filter_by(bank_id=bank.id).delete(synchronize_session=False)
    db.query(BankWordExclusion).filter_by(bank_id=bank.id).delete(synchronize_session=False)
    db.query(VectorIndex).filter_by(bank_id=bank.id).delete(synchronize_session=False)
    db.query(Question).filter_by(bank_id=bank.id).delete(synchronize_session=False)

    import_job_ids_subquery = db.query(ImportJob.id).filter(ImportJob.bank_id == bank.id)
    db.query(ImportReviewItem).filter(ImportReviewItem.import_job_id.in_(import_job_ids_subquery)).delete(synchronize_session=False)
    db.query(ImportParsedQuestion).filter(ImportParsedQuestion.import_job_id.in_(import_job_ids_subquery)).delete(synchronize_session=False)
    db.query(ImportChunk).filter(ImportChunk.import_job_id.in_(import_job_ids_subquery)).delete(synchronize_session=False)

    import_jobs = db.query(ImportJob).filter(ImportJob.bank_id == bank.id).all()
    bg_job_ids = [ij.background_job_id for ij in import_jobs if ij.background_job_id]
    for import_job in import_jobs:
        import_job.background_job_id = None
    db.flush()
    if bg_job_ids:
        db.query(BackgroundJob).filter(BackgroundJob.id.in_(bg_job_ids)).delete(synchronize_session=False)
    db.query(ImportJob).filter_by(bank_id=bank.id).delete(synchronize_session=False)
    db.delete(bank)


def delete_exam_data(db: Session, exam: Exam) -> None:
    try:
        for bank in db.query(QuestionBank).filter_by(exam_id=exam.id).all():
            delete_bank_data(db, bank)
        vocab_ids = db.query(Vocabulary.id).filter_by(user_id=exam.owner_id, exam_id=exam.id)
        db.query(UserVocabProgress).filter(UserVocabProgress.vocabulary_id.in_(vocab_ids)).delete(synchronize_session=False)
        db.query(Vocabulary).filter_by(user_id=exam.owner_id, exam_id=exam.id).delete(synchronize_session=False)
        db.query(User).filter_by(active_exam_id=exam.id).update({User.active_exam_id: None}, synchronize_session=False)
        db.delete(exam)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="删除考试项目失败，请稍后重试")
