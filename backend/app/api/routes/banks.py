"""Banks API 路由 - 题库 CRUD、文件导入、高频词翻译"""

import json

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_exam_context
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.models.bank_word import BankWordFrequency
from app.models.exam import Exam
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.schemas.bank import BankCreateRequest, BankUpdateRequest
from app.services.ai_service import batch_translate_terms
from app.services.exam_service import delete_bank_data, get_bank_in_exam_or_404
from app.services.smart_import_service import create_smart_import_job

router = APIRouter()


def bank_to_dict(bank: QuestionBank) -> dict:
    return {
        "id": bank.id,
        "exam_id": bank.exam_id,
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


@router.get("")
@router.get("/")
def list_banks(
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    banks = db.query(QuestionBank).filter_by(exam_id=exam.id).order_by(QuestionBank.created_at.desc()).all()
    return [bank_to_dict(b) for b in banks]


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_bank(
    data: BankCreateRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = QuestionBank(name=data.name, description=data.description, exam_id=exam.id)
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank_to_dict(bank)


@router.get("/{bank_id}")
def get_bank(
    bank_id: int,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    return bank_to_dict(get_bank_in_exam_or_404(db, bank_id, exam))


@router.put("/{bank_id}")
def update_bank(
    bank_id: int,
    data: BankUpdateRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = get_bank_in_exam_or_404(db, bank_id, exam)

    if data.name is not None:
        bank.name = data.name
    if data.description is not None:
        bank.description = data.description
    db.commit()
    db.refresh(bank)
    return bank_to_dict(bank)


@router.delete("/{bank_id}")
def delete_bank(
    bank_id: int,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = get_bank_in_exam_or_404(db, bank_id, exam)
    delete_bank_data(db, bank)
    db.commit()
    return {"message": "题库已删除"}


@router.post("/{bank_id}/import")
def import_questions(
    bank_id: int,
    file: UploadFile = File(...),
    force: str = Form("false"),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = get_bank_in_exam_or_404(db, bank_id, exam)

    file_bytes = file.file.read()
    if len(file_bytes) > app_settings.upload_max_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超过限制（最大 {app_settings.MAX_UPLOAD_SIZE_MB}MB）",
        )

    result = create_smart_import_job(
        db=db,
        bank_id=bank.id,
        file_bytes=file_bytes,
        filename=file.filename or "unknown",
        user_id=current_user.id,
        force=force.lower() == "true",
    )

    if "error" in result:
        # 兼容旧 service 返回 duplicate_of 的 409 语义；新同文件重导入默认不再报错。
        status_code = 409 if result.get("duplicate_of") else 400
        raise HTTPException(status_code=status_code, detail=result)

    return result


@router.post("/{bank_id}/translate-frequencies")
def translate_frequencies(
    bank_id: int,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = get_bank_in_exam_or_404(db, bank_id, exam)

    untranslated = db.query(BankWordFrequency).filter_by(
        bank_id=bank.id, term_zh=None
    ).order_by(BankWordFrequency.frequency.desc()).limit(100).all()

    if not untranslated:
        return {"translated": 0, "remaining": 0}

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
        bank_id=bank.id, term_zh=None
    ).count()

    return {"translated": translated_count, "remaining": remaining}
