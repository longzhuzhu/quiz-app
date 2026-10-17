"""答题自动下一题浏览器验收：真实认证、真实答题接口与隔离 PostgreSQL。

主库 6 道单选（正确答案 A，order_index 从 1 开始），另设一个多选库 1 道（正确答案 A,C）。
仅额外挂载测试控制路由：让下一条作答请求失败，用于验证失败停留与重试。
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Lock, Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres_support import isolated_postgres  # noqa: E402

QUESTION_COUNT = 6
_dumps = json.dumps  # 上游请求体的关键字参数名是 json，函数内不能再引用同名模块


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with isolated_postgres() as engine, tempfile.TemporaryDirectory(prefix="quiz-auto-next-storage-") as storage:
        os.environ.update(
            DATABASE_URL=engine.url.render_as_string(hide_password=False),
            AI_API_KEY="", JWT_SECRET_KEY="isolated-quiz-auto-next-key",
            SECRET_KEY="isolated-quiz-auto-next-encryption", STORAGE_ROOT=storage,
        )
        from sqlalchemy.orm import Session
        from app.core.database import Base
        from app.core.security import get_password_hash
        from app.models import Exam, Question, QuestionBank, User
        from app.main import create_app
        from app.services.settings_service import set_encrypted_ai_api_key, set_key
        from app.workers.job_worker import process_one_job
        from fastapi import APIRouter
        from fastapi.responses import JSONResponse
        import httpx
        import uvicorn

        def model_http(url, *, json: dict, **kwargs):  # noqa: A002
            """按 OpenAI 兼容协议返回可校验的翻译/解析结果，避免访问真实外网。"""
            system_prompt = json["messages"][0]["content"]
            if '"options_zh"' in system_prompt:
                payload = {
                    "content_zh": "自动下一题翻译",
                    "options_zh": [{"key": key, "text_zh": f"选项{key}翻译"} for key in "ABCD"],
                }
            else:
                payload = {
                    "judged_answer": "A",
                    "stem_breakdown": {"qualifier": "", "role": "", "scenario": "", "constraint": "", "asked": "选择答案"},
                    "explanation": "The first choice is correct.",
                    "explanation_zh": "第一个选项正确。",
                    "distractors": [{"key": key, "type": "干扰项", "reason": "不符合题意"} for key in "BCD"],
                }
            return httpx.Response(200, json={"choices": [{"message": {"content": _dumps(payload, ensure_ascii=False)}}]})

        httpx.post = model_http  # 仅替换上游 HTTP；不替换任何业务模块。
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(
                username="study-user", email="auto-next@example.invalid",
                password_hash=get_password_hash("StudyTest123!"), is_admin=True,
            )
            db.add(user)
            db.flush()
            exam = Exam(owner_id=user.id, slug="current", name="Current", short_name="Current")
            db.add(exam)
            db.flush()
            user.active_exam_id = exam.id
            bank = QuestionBank(exam_id=exam.id, name="Auto Next Bank", question_count=QUESTION_COUNT)
            db.add(bank)
            db.flush()
            for index in range(1, QUESTION_COUNT + 1):
                db.add(Question(
                    bank_id=bank.id, question_type="single",
                    content=f"Auto next question {index}?",
                    options=[{"key": key, "text": f"Choice {key} for question {index}"} for key in "ABCD"],
                    correct_answer="A", order_index=index,
                ))
            multi_bank = QuestionBank(exam_id=exam.id, name="Multi Bank", question_count=1)
            db.add(multi_bank)
            db.flush()
            db.add(Question(
                bank_id=multi_bank.id, question_type="multiple",
                content="Auto next multiple choice?",
                options=[{"key": key, "text": f"Multi choice {key}"} for key in "ABCD"],
                correct_answer="A,C", order_index=1,
            ))
            set_key(db, "ai_api_base_url", "https://8.8.8.8")
            set_key(db, "ai_explain_models", json.dumps([{"model_id": "model-alpha", "reasoning_effort": None}]))
            set_encrypted_ai_api_key(db, "isolated-auto-next-token")
            db.commit()

        control = {"fail_next_answer": False}
        lock = Lock()
        app = create_app()
        fixture = APIRouter()

        @fixture.post("/api/__test/fail-next-answer")
        def fail_next_answer():
            with lock:
                control["fail_next_answer"] = True
            return {"ok": True}

        @app.middleware("http")
        async def answer_control(request, call_next):
            if request.url.path == "/api/quiz/answer":
                with lock:
                    fail = control["fail_next_answer"]
                    if fail:
                        control["fail_next_answer"] = False
                if fail:
                    return JSONResponse(status_code=500, content={"detail": "注入的提交失败"})
            return await call_next(request)

        app.router.routes = fixture.routes + app.router.routes

        stop = Event()

        def worker():
            while not stop.is_set():
                if not process_one_job():
                    stop.wait(0.05)

        threads = [Thread(target=worker, daemon=True) for _ in range(2)]
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
