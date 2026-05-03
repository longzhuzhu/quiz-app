"""Vocab API 路由 - 专业词汇、个人词汇、高频词、进度、批量翻译"""

import json
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.vocabulary import Vocabulary, UserVocabProgress
from app.models.question_bank import QuestionBank
from app.models.bank_word import BankWordFrequency, UserBankWordProgress, BankWordExclusion
from app.models.user import User
from app.services.import_service import MIN_FREQUENCY, TOP_FREQUENT_TERMS_LIMIT

router = APIRouter()


def _word_to_dict(w: Vocabulary, user: User, progress_by_vocab_id: dict) -> dict:
    return {
        "id": w.id,
        "term": w.term,
        "definition": w.definition,
        "term_zh": w.term_zh,
        "definition_zh": w.definition_zh,
        "is_system": w.is_system,
        "is_mastered": progress_by_vocab_id.get(w.id, False),
        "can_delete": bool(user and user.is_admin),
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


def _vocabulary_needs_translation(word: Vocabulary) -> bool:
    if _text_missing(word.term_zh):
        return True
    if word.definition and _text_missing(word.definition_zh):
        return True
    return False


@router.get("/professional")
def list_professional(
    mastered: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    words = db.query(Vocabulary).filter_by(is_system=True).order_by(Vocabulary.term).all()
    progress_by_vocab_id = _get_progress_map(current_user.id, db)

    mastered_value = _parse_bool_arg(mastered)
    if mastered_value is not None:
        words = [
            word for word in words
            if progress_by_vocab_id.get(word.id, False) is mastered_value
        ]

    return [_word_to_dict(w, current_user, progress_by_vocab_id) for w in words]


@router.get("/personal")
def list_personal(
    mastered: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    words = db.query(Vocabulary).filter_by(
        user_id=current_user.id, is_system=False
    ).order_by(Vocabulary.created_at.desc()).all()
    progress_by_vocab_id = _get_progress_map(current_user.id, db)

    mastered_value = _parse_bool_arg(mastered)
    if mastered_value is not None:
        words = [
            word for word in words
            if progress_by_vocab_id.get(word.id, False) is mastered_value
        ]

    return [_word_to_dict(w, current_user, progress_by_vocab_id) for w in words]


@router.post("/personal", status_code=201)
def add_personal(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    term = data.get("term", "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="单词不能为空")

    term_zh = (data.get("term_zh") or "").strip() or None
    definition_zh = (data.get("definition_zh") or "").strip() or None

    # 自动翻译：未提供中文时调用 AI
    if data.get("auto_translate") and not term_zh:
        try:
            from app.services.ai_service import translate_term
            result = translate_term(term)
            term_zh = result.get("term_zh") or term_zh
            definition_zh = result.get("definition_zh") or definition_zh
        except Exception:
            pass  # 翻译失败不影响保存

    word = Vocabulary(
        term=term,
        definition=(data.get("definition") or "").strip() or None,
        term_zh=term_zh,
        definition_zh=definition_zh,
        is_system=False,
        user_id=current_user.id,
    )
    db.add(word)
    db.commit()
    db.refresh(word)
    return _word_to_dict(word, current_user, {})


@router.put("/items/{vocabulary_id}/progress")
def update_progress(
    vocabulary_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    word = db.get(Vocabulary, vocabulary_id)
    if not word:
        raise HTTPException(status_code=404, detail="词汇不存在")

    is_mastered = data.get("is_mastered")
    if not isinstance(is_mastered, bool):
        raise HTTPException(status_code=400, detail="is_mastered 必须为布尔值")
    if not word.is_system and word.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限")

    progress = db.query(UserVocabProgress).filter_by(
        user_id=current_user.id,
        vocabulary_id=word.id,
    ).first()
    if progress is None:
        progress = UserVocabProgress(
            user_id=current_user.id,
            vocabulary_id=word.id,
            is_mastered=is_mastered,
        )
        db.add(progress)
    else:
        progress.is_mastered = is_mastered

    db.commit()
    return {"message": "已标记为掌握" if is_mastered else "已取消掌握"}


@router.post("/professional", status_code=201)
def add_professional(
    data: dict,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    term = data.get("term", "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="单词不能为空")

    word = Vocabulary(
        term=term,
        definition=(data.get("definition") or "").strip() or None,
        term_zh=(data.get("term_zh") or "").strip() or None,
        definition_zh=(data.get("definition_zh") or "").strip() or None,
        is_system=True,
    )
    db.add(word)
    db.commit()
    db.refresh(word)
    return _word_to_dict(word, _admin, {})


@router.delete("/items/{vocabulary_id}")
def delete_vocab_item(
    vocabulary_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    word = db.get(Vocabulary, vocabulary_id)
    if not word:
        raise HTTPException(status_code=404, detail="词汇不存在")

    db.query(UserVocabProgress).filter_by(vocabulary_id=word.id).delete(synchronize_session=False)
    db.delete(word)
    db.commit()
    return {"message": "已删除"}


@router.delete("/personal/{word_id}")
def delete_personal(
    word_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    word = db.get(Vocabulary, word_id)
    if not word:
        raise HTTPException(status_code=404, detail="词汇不存在")
    if word.is_system:
        raise HTTPException(status_code=400, detail="非个人词汇")
    if word.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权限")

    db.query(UserVocabProgress).filter_by(vocabulary_id=word.id).delete(synchronize_session=False)
    db.delete(word)
    db.commit()
    return {"message": "已删除"}


@router.delete("/professional/{word_id}")
def delete_professional(
    word_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    word = db.get(Vocabulary, word_id)
    if not word:
        raise HTTPException(status_code=404, detail="词汇不存在")
    if not word.is_system:
        raise HTTPException(status_code=400, detail="非专业词汇")

    db.query(UserVocabProgress).filter_by(vocabulary_id=word.id).delete(synchronize_session=False)
    db.delete(word)
    db.commit()
    return {"message": "已删除"}


@router.post("/professional/batch-translate")
def batch_translate_professional(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """批量翻译未翻译的专业词汇"""
    from app.services.ai_service import batch_translate_vocab

    untranslated = [
        word
        for word in db.query(Vocabulary).filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term).all()
        if _vocabulary_needs_translation(word)
    ]

    if not untranslated:
        return {"message": "所有词汇已翻译", "translated": 0, "remaining": 0}

    batch_size = 10
    batch = untranslated[:batch_size]
    translated = 0
    try:
        translated = batch_translate_vocab(db, batch)
    except Exception as e:
        db.rollback()
        return {
            "error": f"翻译出错：{str(e)}",
            "translated": 0,
            "remaining": len(untranslated),
        }

    remaining = len(untranslated) - translated
    return {
        "message": f"本次翻译 {translated} 个，剩余 {remaining} 个",
        "translated": translated,
        "remaining": remaining,
    }


@router.post("/professional/import-iapp")
def import_iapp_glossary(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """从 IAPP 网站批量导入隐私专业词汇"""
    try:
        from scripts.import_iapp_glossary import fetch_glossary_terms, import_terms
        terms = fetch_glossary_terms()
        added, skipped = import_terms(terms)
        return {
            "message": f"导入完成：新增 {added} 个，跳过 {skipped} 个已存在术语",
            "added": added,
            "skipped": skipped,
            "total_fetched": len(terms),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{str(e)}")


@router.get("/frequent")
def list_frequent(
    bank_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    mastered: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    excluded_terms = _get_excluded_term_set(bank_id, db)
    progress_by_term = _get_bank_word_progress_map(current_user.id, bank_id, db)

    mastered_value = _parse_bool_arg(mastered)
    if mastered_value is not None and mastered_value is None:
        raise HTTPException(status_code=400, detail="mastered 参数无效")

    frequent_query = db.query(BankWordFrequency).filter_by(bank_id=bank_id)
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
    end = start + per_page
    items = visible_terms[start:end]

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
                "can_delete": bool(current_user and current_user.is_admin),
                "can_mark_mastered": True,
            }
            for item in items
        ],
    }


@router.put("/frequent-items/progress")
def update_frequent_progress(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bank_id = data.get("bank_id")
    term = (data.get("term") or "").strip()
    is_mastered = data.get("is_mastered")

    if not isinstance(bank_id, int):
        raise HTTPException(status_code=400, detail="bank_id 必须为整数")
    if not term:
        raise HTTPException(status_code=400, detail="term 不能为空")
    if not isinstance(is_mastered, bool):
        raise HTTPException(status_code=400, detail="is_mastered 必须为布尔值")

    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    excluded = db.query(BankWordExclusion).filter_by(bank_id=bank_id, term=term).first()
    if excluded:
        raise HTTPException(status_code=404, detail="词条已被排除")

    frequency_item = db.query(BankWordFrequency).filter_by(bank_id=bank_id, term=term).first()
    if not frequency_item:
        raise HTTPException(status_code=404, detail="词条不存在")

    progress = db.query(UserBankWordProgress).filter_by(
        user_id=current_user.id,
        bank_id=bank_id,
        term=term,
    ).first()
    if progress is None:
        progress = UserBankWordProgress(
            user_id=current_user.id,
            bank_id=bank_id,
            term=term,
            is_mastered=is_mastered,
        )
        db.add(progress)
    else:
        progress.is_mastered = is_mastered

    db.commit()
    return {"message": "已标记为掌握" if is_mastered else "已取消掌握"}


@router.delete("/frequent-items")
def exclude_frequent_item(
    bank_id: int = Query(...),
    term: str = Query(...),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    term = term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="缺少 term 参数")

    bank = db.get(QuestionBank, bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    frequency_item = db.query(BankWordFrequency).filter_by(bank_id=bank_id, term=term).first()
    excluded = db.query(BankWordExclusion).filter_by(bank_id=bank_id, term=term).first()
    if frequency_item is None and excluded is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    if excluded is None:
        db.add(BankWordExclusion(bank_id=bank_id, term=term, created_by=_admin.id))

    if frequency_item is not None:
        db.delete(frequency_item)
    db.commit()
    return {"message": "已删除"}


@router.get("/stats")
def vocab_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    professional_count = db.query(Vocabulary).filter_by(is_system=True).count()
    personal_count = db.query(Vocabulary).filter_by(
        user_id=current_user.id, is_system=False
    ).count()
    return {
        "professional": professional_count,
        "personal": personal_count,
    }
