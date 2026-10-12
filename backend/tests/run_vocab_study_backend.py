"""浏览器闭环专用后端：真实应用、真实认证、临时 PostgreSQL，无外部 AI。"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres_support import isolated_postgres


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with isolated_postgres() as engine, tempfile.TemporaryDirectory(prefix="vocab-storage-") as storage:
        os.environ["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
        os.environ["AI_API_KEY"] = ""
        os.environ["JWT_SECRET_KEY"] = "isolated-vocab-browser-test-key"
        os.environ["STORAGE_ROOT"] = storage
        from sqlalchemy.orm import Session
        from app.core.database import Base
        from app.core.security import get_password_hash
        from app.models import Exam, QuestionBank, User, Vocabulary
        from app.models.bank_word import BankWordFrequency
        from app.models.vocabulary import UserVocabProgress
        from app.main import create_app
        from app.services import ai_service
        import uvicorn

        # 仅替换外部 AI 边界；浏览器仍经过真实路由、校验和数据库事务。
        def fixture_ai(messages, db, **kwargs):
            term = json.loads(messages[-1]["content"])["term"]
            return json.dumps({"term_zh": f"刷新后的 {term} 中文", "definition": f"A refreshed English definition for {term}.", "definition_zh": f"刷新后的 {term} 中文释义。"}, ensure_ascii=False)

        ai_service.call_ai_api = fixture_ai
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="study-user", email="study@example.invalid", password_hash=get_password_hash("StudyTest123!"), is_admin=True)
            db.add(user); db.flush()
            current = Exam(owner_id=user.id, slug="current", name="Current", short_name="Current")
            other = Exam(owner_id=user.id, slug="other", name="Other", short_name="Other")
            db.add_all([current, other]); db.flush()
            user.active_exam_id = current.id
            bank = QuestionBank(exam_id=current.id, name="Study Bank")
            db.add(bank); db.flush()
            for scope in (None, current.id):
                for i in range(110):
                    term = ["alpha", "beta", "gamma"][i] if scope is None and i < 3 else f"word{i:03}"
                    word = Vocabulary(user_id=user.id, exam_id=scope, term=term, term_zh="测试中文", definition_zh="真实释义", is_system=False)
                    db.add(word); db.flush()
                    if scope is None and i >= 3:
                        db.add(UserVocabProgress(user_id=user.id, vocabulary_id=word.id, is_mastered=True))
            db.add_all([BankWordFrequency(bank_id=bank.id, term=f"term{i:04}", term_zh="高频词", frequency=5001-i) for i in range(5001)])
            db.commit()
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
