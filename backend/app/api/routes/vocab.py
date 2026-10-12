"""Vocab API 路由 - 跨考试项目个人词汇、考试项目专属词汇、高频词"""

from math import ceil
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_exam_context, get_study_exam_context
from app.core.database import get_db
from app.models.bank_word import BankWordExclusion, BankWordFrequency, UserBankWordProgress
from app.models.exam import Exam
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.models.vocabulary import UserVocabProgress, Vocabulary
from app.schemas.vocab import (
    FrequentProgressUpdateRequest, StudyDeckResponse, StudyItemsRequest, StudyItemsResponse,
    StudyRefreshRequest, StudyRefreshResponse, VocabAddRequest, VocabProgressUpdateRequest,
)
from app.services.exam_service import get_bank_in_exam_or_404
from app.services.import_service import MIN_FREQUENCY, TOP_FREQUENT_TERMS_LIMIT
from app.services.vocab_query_service import study_deck, study_items, visible_vocab_query as _visible_vocab_query
from app.services.vocab_progress_service import lock_bank, lock_exam, save_progress

router = APIRouter()


def _scope_label(word: Vocabulary, exam: Exam) -> str:
    return "exam_personal" if word.exam_id == exam.id else "personal"


def _word_to_dict(w: Vocabulary, user: User, exam: Exam, progress_by_vocab_id: dict) -> dict:
    return {
        "id": w.id,
        "term": w.term,
        "definition": w.definition,
        "term_zh": w.term_zh,
        "definition_zh": w.definition_zh,
        "is_system": False,
        "scope_label": _scope_label(w, exam),
        "is_mastered": progress_by_vocab_id.get(w.id, False),
        "can_delete": w.user_id == user.id,
        "can_mark_mastered": True,
        "created_at": w.created_at.isoformat(),
    }


def _get_progress_map(user_id: int, db: Session) -> dict:
    progress_rows = db.query(UserVocabProgress).filter_by(user_id=user_id).all()
    return {row.vocabulary_id: row.is_mastered for row in progress_rows}


def _get_bank_word_progress_map(user_id: int, bank_id: int, db: Session) -> dict:
    progress_rows = db.query(UserBankWordProgress).filter_by(
        user_id=user_id, bank_id=bank_id
    ).all()
    return {row.term: row.is_mastered for row in progress_rows}


def _get_excluded_term_set(bank_id: int, db: Session) -> set:
    exclusion_rows = db.query(BankWordExclusion).filter_by(bank_id=bank_id).all()
    return {row.term for row in exclusion_rows}


def _parse_bool_arg(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _text_missing(value) -> bool:
    return value is None or not str(value).strip()


def _get_visible_vocab_or_404(db: Session, user: User, exam: Exam, vocabulary_id: int, *, deleting=False) -> Vocabulary:
    lock_exam(db, exam)
    word = _visible_vocab_query(db, user.id, exam, "all").filter(Vocabulary.id == vocabulary_id).with_for_update(read=not deleting).first()
    if not word:
        raise HTTPException(status_code=404, detail="词汇不存在")
    return word


@router.get("/study/deck", response_model=StudyDeckResponse)
def get_study_deck(
    scope: Literal["personal", "exam_personal", "frequent"] = Query(...),
    mastery: Literal["all", "unmastered", "mastered"] = Query("unmastered"),
    bank_id: int | None = Query(None, gt=0),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_study_exam_context),
    db: Session = Depends(get_db),
):
    return study_deck(db, current_user, exam, scope, mastery, bank_id)


@router.post("/study/items", response_model=StudyItemsResponse)
def get_study_items(
    data: StudyItemsRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_study_exam_context),
    db: Session = Depends(get_db),
):
    return study_items(db, current_user, exam, data)


def _refresh_target(db, user_id, exam, data, *, for_update=False):
    if data.scope == "frequent":
        bank = get_bank_in_exam_or_404(db, data.bank_id, exam, lock_for_read=True)
        query = db.query(BankWordFrequency).filter_by(bank_id=bank.id, term=data.ref.term)
    else:
        query = _visible_vocab_query(db, user_id, exam, data.scope).filter(Vocabulary.id == data.ref.vocabulary_id)
    word = (query.with_for_update() if for_update else query).populate_existing().first()
    if word is None:
        raise HTTPException(status_code=404, detail="词汇不存在")
    if data.scope == "frequent" and db.query(BankWordExclusion.id).filter_by(bank_id=data.bank_id, term=data.ref.term).first():
        raise HTTPException(status_code=404, detail="词条已被排除")
    return word


@router.post("/study/refresh", response_model=StudyRefreshResponse)
def refresh_study_word(
    data: StudyRefreshRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_study_exam_context),
    db: Session = Depends(get_db),
):
    from app.services.ai_service import refresh_vocab_content

    user_id, exam_id = current_user.id, exam.id
    word = _refresh_target(db, user_id, exam, data)
    term = word.term
    original = (word.term_zh, word.definition, word.definition_zh)
    # 不在网络调用期间持有项目/题库/词条锁，以免 AI 慢请求阻塞删除和其他学习操作。
    db.rollback()
    try:
        content = refresh_vocab_content(term, db, definition=original[1])
    except httpx.TimeoutException:
        db.rollback()
        raise HTTPException(status_code=504, detail="AI 刷新超时，请稍后重试") from None
    except Exception:
        db.rollback()
        raise HTTPException(status_code=502, detail="词条刷新失败，请检查 AI 配置或稍后重试") from None
    db.rollback()
    # AI 返回后重新校验权限与可见性，已删除/排除的词绝不能被重建。
    exam = db.query(Exam).filter_by(id=exam_id, owner_id=user_id).with_for_update(read=True).populate_existing().first()
    if exam is None:
        raise HTTPException(status_code=404, detail="EXAM_NOT_FOUND")
    word = _refresh_target(db, user_id, exam, data, for_update=True)
    if word.term != term or (word.term_zh, word.definition, word.definition_zh) != original:
        raise HTTPException(status_code=409, detail="词条内容已变化，请重新加载后再刷新")
    for field, value in content.items():
        setattr(word, field, value)
    response = {"ref": data.ref.model_dump(), "content": {
        "term": term, **content, "frequency": word.frequency if data.scope == "frequent" else None,
    }}
    db.commit()
    return response


@router.get("")
def list_vocab(
    scope: str = Query("all"),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mastered: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    query = _visible_vocab_query(db, current_user.id, exam, scope)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Vocabulary.term.ilike(like), Vocabulary.term_zh.ilike(like)))

    progress_by_vocab_id = _get_progress_map(current_user.id, db)
    mastered_value = _parse_bool_arg(mastered)
    words = query.order_by(Vocabulary.created_at.desc()).all()
    if mastered_value is not None:
        words = [word for word in words if progress_by_vocab_id.get(word.id, False) is mastered_value]

    total = len(words)
    total_pages = max(1, ceil(total / page_size)) if total else 1
    start = (page - 1) * page_size
    items = words[start:start + page_size]
    return {
        "items": [_word_to_dict(w, current_user, exam, progress_by_vocab_id) for w in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_items": total,
        },
    }


@router.post("", status_code=201)
def add_vocab(
    data: VocabAddRequest,
    scope: str = Query("exam_personal"),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    term = data.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="单词不能为空")
    if scope not in {"personal", "exam_personal"}:
        raise HTTPException(status_code=400, detail="scope 必须为 personal 或 exam_personal")

    term_zh = (data.term_zh or "").strip() or None
    definition_zh = (data.definition_zh or "").strip() or None

    if data.auto_translate and not term_zh:
        try:
            from app.services.ai_service import translate_term
            result = translate_term(term, db)
            term_zh = result.get("term_zh") or term_zh
            definition_zh = result.get("definition_zh") or definition_zh
        except Exception:
            pass

    word = Vocabulary(
        term=term,
        definition=data.definition.strip() or None if data.definition else None,
        term_zh=term_zh,
        definition_zh=definition_zh,
        is_system=False,
        user_id=current_user.id,
        exam_id=None if scope == "personal" else exam.id,
    )
    db.add(word)
    db.commit()
    db.refresh(word)
    return _word_to_dict(word, current_user, exam, {})


@router.put("/items/{vocabulary_id}/progress")
def update_progress(
    vocabulary_id: int,
    data: VocabProgressUpdateRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    word = _get_visible_vocab_or_404(db, current_user, exam, vocabulary_id)
    save_progress(db, UserVocabProgress, {"user_id": current_user.id, "vocabulary_id": word.id}, data.is_mastered)
    return {"message": "已标记为掌握" if data.is_mastered else "已取消掌握"}


@router.delete("/items/{vocabulary_id}")
def delete_vocab_item(
    vocabulary_id: int,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    word = _get_visible_vocab_or_404(db, current_user, exam, vocabulary_id, deleting=True)
    db.query(UserVocabProgress).filter_by(vocabulary_id=word.id).delete(synchronize_session=False)
    db.delete(word)
    db.commit()
    return {"message": "已删除"}


@router.get("/frequent")
def list_frequent(
    bank_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    mastered: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = get_bank_in_exam_or_404(db, bank_id, exam)
    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    excluded_terms = _get_excluded_term_set(bank.id, db)
    progress_by_term = _get_bank_word_progress_map(current_user.id, bank.id, db)
    mastered_value = _parse_bool_arg(mastered)

    # 概览/分页不需要释义，避免新增 Text 字段让统计请求读取整组大正文。
    frequent_query = db.query(
        BankWordFrequency.term, BankWordFrequency.term_zh, BankWordFrequency.frequency,
    ).filter(BankWordFrequency.bank_id == bank.id)
    if excluded_terms:
        frequent_query = frequent_query.filter(~BankWordFrequency.term.in_(excluded_terms))
    top_terms = frequent_query.order_by(
        BankWordFrequency.frequency.desc(),
        BankWordFrequency.term.asc(),
    ).limit(TOP_FREQUENT_TERMS_LIMIT).all()

    visible_terms = top_terms
    if mastered_value is not None:
        visible_terms = [
            item for item in visible_terms
            if progress_by_term.get(item.term, False) is mastered_value
        ]

    total_terms = len(visible_terms)
    untranslated_terms = sum(1 for item in visible_terms if _text_missing(item.term_zh))
    total_pages = max(1, ceil(total_terms / per_page)) if total_terms else 1
    start = (page - 1) * per_page
    items = visible_terms[start:start + per_page]

    return {
        "bank": {"id": bank.id, "name": bank.name},
        "summary": {
            "total_terms": total_terms,
            "untranslated_terms": untranslated_terms,
            "min_frequency": MIN_FREQUENCY,
            "top_terms_limit": TOP_FREQUENT_TERMS_LIMIT,
        },
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "total_items": total_terms,
        },
        "items": [
            {
                "term": item.term,
                "term_zh": item.term_zh,
                "frequency": item.frequency,
                "is_mastered": progress_by_term.get(item.term, False),
                "can_delete": True,
                "can_mark_mastered": True,
            }
            for item in items
        ],
    }


@router.put("/frequent-items/progress")
def update_frequent_progress(
    data: FrequentProgressUpdateRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = lock_bank(db, exam, data.bank_id)
    term = data.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="缺少 term 参数")

    frequency_item = db.query(BankWordFrequency).filter_by(bank_id=bank.id, term=term).with_for_update(read=True).first()
    if not frequency_item:
        raise HTTPException(status_code=404, detail="词条不存在")
    excluded = db.query(BankWordExclusion).filter_by(bank_id=bank.id, term=term).first()
    if excluded:
        raise HTTPException(status_code=404, detail="词条已被排除")
    save_progress(db, UserBankWordProgress, {"user_id": current_user.id, "bank_id": bank.id, "term": term}, data.is_mastered)
    return {"message": "已标记为掌握" if data.is_mastered else "已取消掌握"}


@router.delete("/frequent-items")
def exclude_frequent_item(
    bank_id: int = Query(...),
    term: str = Query(...),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = lock_bank(db, exam, bank_id)
    term = term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="缺少 term 参数")

    frequency_item = db.query(BankWordFrequency).filter_by(bank_id=bank.id, term=term).with_for_update().first()
    excluded = db.query(BankWordExclusion).filter_by(bank_id=bank.id, term=term).first()
    if frequency_item is None and excluded is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    if excluded is None:
        db.add(BankWordExclusion(bank_id=bank.id, term=term, created_by=current_user.id))

    db.query(UserBankWordProgress).filter_by(bank_id=bank.id, term=term).delete(synchronize_session=False)
    if frequency_item is not None:
        db.delete(frequency_item)
    db.commit()
    return {"message": "已删除"}


@router.get("/stats")
def vocab_stats(
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    personal_count = _visible_vocab_query(db, current_user.id, exam, "personal").count()
    exam_personal_count = _visible_vocab_query(db, current_user.id, exam, "exam_personal").count()
    return {
        "personal": personal_count,
        "exam_personal": exam_personal_count,
        "all": personal_count + exam_personal_count,
    }
