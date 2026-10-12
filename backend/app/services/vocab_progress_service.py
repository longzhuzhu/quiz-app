"""绝对掌握写入与删除的事务协议：上下文、词条、进度按此顺序加锁。"""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.exam import Exam
from app.models.question_bank import QuestionBank


def lock_exam(db, exam):
    # SHARE 允许同词并发写入，但项目删除必须等待这些事务结束。
    if db.query(Exam.id).filter_by(id=exam.id, owner_id=exam.owner_id).with_for_update(read=True).first() is None:
        raise HTTPException(status_code=404, detail="EXAM_NOT_FOUND")


def lock_bank(db, exam, bank_id):
    lock_exam(db, exam)
    bank = db.query(QuestionBank).filter_by(id=bank_id, exam_id=exam.id).with_for_update(read=True).first()
    if bank is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


def _target_unique_conflict(error, model, identity):
    table = model.__tablename__
    columns = list(identity)
    original = error.orig
    if getattr(original, "sqlstate", None) == "23505":
        return original.diag.constraint_name == f"{table}_{'_'.join(columns)}_key"
    # SQLite 快速测试。外键、非目标唯一键与其他 IntegrityError 不能被当成成功。
    return getattr(original, "sqlite_errorcode", None) == 2067 and str(original) == (
        "UNIQUE constraint failed: " + ", ".join(f"{table}.{column}" for column in columns)
    )


def save_progress(db, model, identity, is_mastered):
    # 已存在的记录也必须锁住：相同布尔值的 ORM 赋值可能不发 UPDATE，
    # 无锁时会在读取和提交之间遗漏另一个事务的改判。
    query = db.query(model).filter_by(**identity).with_for_update()
    progress = query.first()
    if progress is None:
        try:
            with db.begin_nested():
                progress = model(**identity, is_mastered=is_mastered)
                db.add(progress)
                db.flush()
        except IntegrityError as error:
            if not _target_unique_conflict(error, model, identity):
                raise
            progress = query.populate_existing().one()
    progress.is_mastered = is_mastered
    db.commit()
