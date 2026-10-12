"""词汇可见性与学习集合查询。快照仅冻结身份，不冻结内容或权限。"""

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.models.bank_word import BankWordExclusion, BankWordFrequency, UserBankWordProgress
from app.models.vocabulary import UserVocabProgress, Vocabulary
from app.services.exam_service import get_bank_in_exam_or_404
from app.services.import_service import TOP_FREQUENT_TERMS_LIMIT


def visible_vocab_query(db, user_id, exam, scope):
    query = db.query(Vocabulary).filter(Vocabulary.user_id == user_id, Vocabulary.is_system.is_(False))
    if scope == "personal":
        return query.filter(Vocabulary.exam_id.is_(None))
    if scope == "exam_personal":
        return query.filter(Vocabulary.exam_id == exam.id)
    if scope == "all":
        return query.filter(or_(Vocabulary.exam_id.is_(None), Vocabulary.exam_id == exam.id))
    raise HTTPException(status_code=400, detail="scope 必须为 personal、exam_personal 或 all")


def study_context(db, user, exam, scope, bank_id):
    if scope == "frequent":
        if bank_id is None:
            raise HTTPException(status_code=422, detail="高频词必须指定 bank_id")
        get_bank_in_exam_or_404(db, bank_id, exam, lock_for_read=True)
    elif bank_id is not None:
        raise HTTPException(status_code=422, detail="普通词禁止指定 bank_id")
    return {"scope": scope, "exam_id": None if scope == "personal" else exam.id, "bank_id": bank_id}


def frequent_query(db, user_id, bank_id, *columns):
    return (
        db.query(*columns)
        .select_from(BankWordFrequency)
        .outerjoin(BankWordExclusion, and_(
            BankWordExclusion.bank_id == BankWordFrequency.bank_id,
            BankWordExclusion.term == BankWordFrequency.term,
        ))
        .outerjoin(UserBankWordProgress, and_(
            UserBankWordProgress.user_id == user_id,
            UserBankWordProgress.bank_id == BankWordFrequency.bank_id,
            UserBankWordProgress.term == BankWordFrequency.term,
        ))
        .filter(BankWordFrequency.bank_id == bank_id, BankWordExclusion.id.is_(None))
    )


def study_deck(db, user, exam, scope, mastery, bank_id):
    context = study_context(db, user, exam, scope, bank_id)
    if scope == "frequent":
        rows = frequent_query(
            db, user.id, bank_id, BankWordFrequency.term, UserBankWordProgress.is_mastered,
        ).order_by(BankWordFrequency.frequency.desc(), BankWordFrequency.term.asc()).limit(TOP_FREQUENT_TERMS_LIMIT).all()
        refs = [{"term": row.term} for row in rows if _matches_mastery(row.is_mastered, mastery)]
    else:
        rows = visible_vocab_query(db, user.id, exam, scope).with_entities(
            Vocabulary.id, Vocabulary.term, UserVocabProgress.is_mastered,
        ).outerjoin(UserVocabProgress, and_(
            UserVocabProgress.vocabulary_id == Vocabulary.id, UserVocabProgress.user_id == user.id,
        )).all()
        rows.sort(key=lambda row: (row.term.lower(), row.term, row.id))
        refs = [{"vocabulary_id": row.id} for row in rows if _matches_mastery(row.is_mastered, mastery)]
    return {
        "schema_version": 1, "context": context, "mastery": mastery, "refs": refs,
        "total": len(refs), "top_limit": TOP_FREQUENT_TERMS_LIMIT if scope == "frequent" else None,
    }


def _matches_mastery(value, mastery):
    return mastery == "all" or bool(value) == (mastery == "mastered")


def study_items(db, user, exam, request):
    study_context(db, user, exam, request.scope, request.bank_id)
    frequent = request.scope == "frequent"
    identities = [ref.term if frequent else ref.vocabulary_id for ref in request.refs]
    if frequent:
        columns = [BankWordFrequency.term, UserBankWordProgress.is_mastered]
        if request.include_content:
            columns += [BankWordFrequency.term_zh, BankWordFrequency.definition, BankWordFrequency.definition_zh, BankWordFrequency.frequency]
        rows = frequent_query(db, user.id, request.bank_id, *columns).filter(BankWordFrequency.term.in_(identities)).all()
        by_identity = {row.term: row for row in rows}
    else:
        columns = [Vocabulary.id, UserVocabProgress.is_mastered]
        if request.include_content:
            columns += [Vocabulary.term, Vocabulary.term_zh, Vocabulary.definition, Vocabulary.definition_zh]
        rows = visible_vocab_query(db, user.id, exam, request.scope).with_entities(*columns).outerjoin(
            UserVocabProgress, and_(UserVocabProgress.vocabulary_id == Vocabulary.id, UserVocabProgress.user_id == user.id),
        ).filter(Vocabulary.id.in_(identities)).all()
        by_identity = {row.id: row for row in rows}
    results = []
    for ref, identity in zip(request.refs, identities):
        row = by_identity.get(identity)
        item = {"ref": ref.model_dump(), "available": row is not None}
        if row is not None:
            content = None
            if request.include_content:
                content = {
                    "term": row.term, "term_zh": row.term_zh,
                    "definition": row.definition,
                    "definition_zh": row.definition_zh,
                    "frequency": row.frequency if frequent else None,
                }
            item.update(is_mastered=bool(row.is_mastered), can_mark_mastered=True, can_delete=True, content=content)
        results.append(item)
    return {"results": results}
