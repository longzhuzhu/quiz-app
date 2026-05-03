"""Banks API 路由 - 题库 CRUD、文件导入、高频词翻译"""

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.question_bank import QuestionBank
from app.models.question import Question
from app.models.quiz import QuizSession, QuizAnswer
from app.models.wrong import WrongAnswer
from app.models.bank_word import BankWordFrequency, UserBankWordProgress, BankWordExclusion
from app.models.user import User
from app.services.import_service import parse_file, build_bank_word_frequencies
from app.services.ai_service import batch_translate_terms
from app.services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    build_scope_key,
    invalidate_active_scope,
)

router = APIRouter()


def bank_to_dict(bank: QuestionBank) -> dict:
    return {
        "id": bank.id,
        "name": bank.name,
        "description": bank.description,
        "source_filename": bank.source_filename,
        "question_count": bank.question_count,
        "created_at": bank.created_at.isoformat(),
    }


def _normalize_options(options):
    return json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _question_signature(question_type, content, options, correct_answer):
    return (
        question_type,
        (content or "").strip(),
        _normalize_options(options),
        (correct_answer or "").strip().upper(),
    )


def _translate_frequency_batch(batch, start_index):
    try:
        translations = batch_translate_terms([
            {"id": index, "term": item["term"]}
            for index, item in enumerate(batch, start=start_index)
        ])
        return {
            item["id"]: item.get("term_zh")
            for item in translations
            if item.get("term_zh")
        }
    except Exception:
        if len(batch) == 1:
            return {}

    middle = len(batch) // 2
    translation_map = _translate_frequency_batch(batch[:middle], start_index)
    translation_map.update(_translate_frequency_batch(batch[middle:], start_index + middle))
    return translation_map


def translate_bank_word_frequencies(items):
    if not items:
        return items

    translation_map = {}
    batch_size = 100

    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        translation_map.update(_translate_frequency_batch(batch, start + 1))

    translated_items = []
    for index, item in enumerate(items, start=1):
        translated_items.append({
            **item,
            "term_zh": translation_map.get(index),
        })
    return translated_items


@router.get("/")
def list_banks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    banks = db.query(QuestionBank).order_by(QuestionBank.created_at.desc()).all()
    return [bank_to_dict(b) for b in banks]


@router.post("/", status_code=201)
def create_bank(
    data: dict,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = QuestionBank(name=data["name"], description=data.get("description", ""))
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank_to_dict(bank)


@router.put("/{bank_id}")
def update_bank(
    bank_id: int,
    data: dict,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    if "name" in data:
        bank.name = data["name"]
    if "description" in data:
        bank.description = data["description"]
    db.commit()
    db.refresh(bank)
    return bank_to_dict(bank)


@router.delete("/{bank_id}")
def delete_bank(
    bank_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    try:
        question_ids_subquery = db.query(Question.id).filter(Question.bank_id == bank.id)

        db.query(QuizAnswer).filter(
            QuizAnswer.question_id.in_(question_ids_subquery)
        ).delete(synchronize_session=False)
        db.query(WrongAnswer).filter(
            WrongAnswer.question_id.in_(question_ids_subquery)
        ).delete(synchronize_session=False)

        db.query(QuizSession).filter_by(bank_id=bank.id).delete(synchronize_session=False)
        db.query(BankWordFrequency).filter_by(bank_id=bank.id).delete(synchronize_session=False)
        db.query(UserBankWordProgress).filter_by(bank_id=bank.id).delete(synchronize_session=False)
        db.query(BankWordExclusion).filter_by(bank_id=bank.id).delete(synchronize_session=False)
        db.query(Question).filter_by(bank_id=bank.id).delete(synchronize_session=False)

        db.delete(bank)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="删除题库失败，请稍后重试")

    return {"message": "题库已删除"}


@router.post("/{bank_id}/import")
def import_questions(
    bank_id: int,
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    filename = (file.filename or "").lower()

    # 读取文件内容
    file_bytes = file.file.read()

    # 创建 SpooledTemporaryFile 兼容的类文件对象供 parse_file 使用
    import io
    file_storage = io.BytesIO(file_bytes)

    try:
        questions_data = parse_file(file_storage, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")

    existing_questions = db.query(Question).filter_by(bank_id=bank.id).order_by(
        Question.order_index.asc(),
        Question.id.asc(),
    ).all()

    seen_signatures = {
        _question_signature(
            q.question_type,
            q.content,
            q.options if isinstance(q.options, list) else json.loads(q.options),
            q.correct_answer,
        )
        for q in existing_questions
    }
    next_order_index = max((q.order_index or 0 for q in existing_questions), default=-1) + 1

    count = 0
    missing_answer_count = 0
    skipped_duplicate_count = 0

    for q in questions_data:
        signature = _question_signature(
            q["question_type"],
            q["content"],
            q["options"],
            q["correct_answer"],
        )
        if signature in seen_signatures:
            skipped_duplicate_count += 1
            continue

        seen_signatures.add(signature)
        if q.get("answer_missing"):
            missing_answer_count += 1

        question = Question(
            bank_id=bank.id,
            question_type=q["question_type"],
            content=q["content"],
            options=q["options"],  # JSONB 直接存储列表
            correct_answer=q["correct_answer"],
            order_index=next_order_index,
        )
        db.add(question)
        next_order_index += 1
        count += 1

    db.flush()

    full_bank_questions = db.query(Question).filter_by(bank_id=bank.id).order_by(
        Question.order_index.asc(), Question.id.asc()
    ).all()

    frequency_items = build_bank_word_frequencies([
        {
            "content": question.content,
            "options": question.options if isinstance(question.options, list) else json.loads(question.options),
        }
        for question in full_bank_questions
    ])
    translated_frequency_items = translate_bank_word_frequencies(frequency_items)
    excluded_terms = {
        row.term
        for row in db.query(BankWordExclusion).filter_by(bank_id=bank.id).all()
    }
    db.query(BankWordFrequency).filter_by(bank_id=bank.id).delete()
    for item in translated_frequency_items:
        if item["term"] in excluded_terms:
            continue
        db.add(BankWordFrequency(
            bank_id=bank.id,
            term=item["term"],
            term_zh=item.get("term_zh"),
            frequency=item["frequency"],
        ))

    bank.question_count = len(full_bank_questions)
    bank.source_filename = file.filename
    invalidate_active_scope(
        db,
        build_scope_key(JOB_TYPE_BANK_FREQUENT_TRANSLATE, {"bank_id": bank.id}),
        "题库已重新导入，旧高频词翻译任务已失效",
    )
    db.commit()

    frequency_count = sum(
        1
        for item in translated_frequency_items
        if item["term"] not in excluded_terms and not item.get("term_zh")
    )
    msg = f"成功导入 {count} 道题目"
    if skipped_duplicate_count:
        msg += f"，跳过 {skipped_duplicate_count} 道重复题"
    if missing_answer_count:
        msg += f"，其中 {missing_answer_count} 道未找到正确答案（需手动补充）"
    return {
        "message": msg,
        "count": count,
        "missing_answer_count": missing_answer_count,
        "skipped_duplicate_count": skipped_duplicate_count,
        "frequency_count": frequency_count,
    }


@router.post("/{bank_id}/translate-frequencies")
def translate_frequencies(
    bank_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    untranslated = db.query(BankWordFrequency).filter_by(
        bank_id=bank_id, term_zh=None
    ).order_by(BankWordFrequency.frequency.desc()).limit(100).all()

    if not untranslated:
        remaining = 0
        return {"translated": 0, "remaining": remaining}

    batch = [{"term": item.term} for item in untranslated]
    translation_map = _translate_frequency_batch(batch, 1)

    translated_count = 0
    for index, item in enumerate(untranslated, start=1):
        zh = translation_map.get(index)
        if zh:
            item.term_zh = zh
            translated_count += 1

    db.commit()

    remaining = db.query(BankWordFrequency).filter_by(
        bank_id=bank_id, term_zh=None
    ).count()

    return {"translated": translated_count, "remaining": remaining}
