"""解析浏览器验收：真实认证、业务接口、worker 与隔离 PostgreSQL。"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Lock, Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres_support import isolated_postgres


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with isolated_postgres() as engine, tempfile.TemporaryDirectory(prefix="explanation-storage-") as storage:
        os.environ.update(DATABASE_URL=engine.url.render_as_string(hide_password=False), AI_API_KEY="", JWT_SECRET_KEY="isolated-explanation-key", SECRET_KEY="isolated-explanation-encryption", STORAGE_ROOT=storage, AI_EXPLANATION_CONCURRENCY="3")
        from sqlalchemy.orm import Session
        from app.core.database import Base
        from app.core.security import get_password_hash
        from app.models import Exam, Question, QuestionBank, User
        from app.main import create_app
        from app.services.settings_service import set_key, set_encrypted_ai_api_key
        from app.workers.job_worker import process_one_job
        from fastapi import APIRouter
        import httpx
        import uvicorn

        state = {"calls": [], "active": 0, "peak": 0}
        lock, stop = Lock(), Event()
        long_id = "model-d/" + "long-model-id-" * 8
        models = ["model-a", "model-b", "model-c", long_id, "model-e"]

        def model_http(url, *, json: dict, **kwargs):
            with lock:
                state["calls"].append({"model": json["model"], "reasoning_effort": json.get("reasoning_effort", "omitted")})
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                time.sleep(.15 if json["model"] != long_id else .4)
                if json["model"] == "model-e" and json.get("reasoning_effort") != "high":
                    raise httpx.ReadTimeout("private-upstream-information")
                answer = "A" if json["model"] == "model-b" else "D"
                value = {
                    "judged_answer": answer,
                    "stem_breakdown": {"qualifier": "MOST", "role": "工程师", "scenario": "比较保护措施", "constraint": "", "asked": "选择最有效的措施"},
                    "explanation": "The measure reduces exposure. It covers the full data lifecycle.",
                    "explanation_zh": "该措施减少数据暴露。它能覆盖数据处理的完整生命周期。" + "较长的分析正文用于确认移动端阅读不会受到导航遮挡。" * 15,
                    "distractors": [{"key": k, "type": "范围过窄", "reason": "该措施只覆盖单个环节，无法满足整体限制"} for k in "ABCD" if k != answer],
                }
                return httpx.Response(200, json={"choices": [{"message": {"content": __import__('json').dumps(value, ensure_ascii=False)}}]})
            finally:
                with lock:
                    state["active"] -= 1

        httpx.post = model_http  # 仅替换上游 HTTP；不替换任何业务模块。
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="study-user", email="ai@example.invalid", password_hash=get_password_hash("StudyTest123!"), is_admin=True)
            db.add(user); db.flush()
            exam = Exam(owner_id=user.id, slug="current", name="Current", short_name="Current")
            db.add(exam); db.flush()
            user.active_exam_id = exam.id
            bank = QuestionBank(exam_id=exam.id, name="Explanation Bank", question_count=2)
            db.add(bank); db.flush()
            for i in range(2):
                db.add(Question(bank_id=bank.id, question_type="single", content=f"Which control is MOST effective? {i+1}", content_zh="选择最有效的保护措施", options=[{"key": k, "text": f"Option {k}", "text_zh": f"选项{k}"} for k in "ABCD"], correct_answer="D", order_index=i, explanation_zh="历史旧解析，没有可验证的模型来源" if i == 0 else None))
            set_key(db, "ai_api_base_url", "https://8.8.8.8")
            set_encrypted_ai_api_key(db, "isolated-explanation-token")
            set_key(db, "ai_explain_models", json.dumps([{"model_id": m, "reasoning_effort": None if m == "model-b" else "xhigh"} for m in models]))
            db.commit()
        app = create_app()
        fixture = APIRouter()
        @fixture.get("/api/__test/ai-state")
        def ai_state():
            with lock:
                return {**state, "calls": list(state["calls"])}
        app.router.routes = fixture.routes + app.router.routes

        def worker():
            while not stop.is_set():
                if not process_one_job():
                    stop.wait(.05)
        threads = [Thread(target=worker, daemon=True) for _ in range(3)]
        for thread in threads:
            thread.start()
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            stop.set()
            for thread in threads:
                thread.join(10)


if __name__ == "__main__":
    main()
