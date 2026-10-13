"""复盘页浏览器闭环专用后端：真实应用、真实认证、真实 worker 与临时 PostgreSQL。

只替换外部 AI 边界（上游 HTTP），翻译与解析仍经过真实路由、任务队列和数据库事务。
固定数据：考试项目 current（另有 other 用于跨项目边界）、主库 10 道单选（正确答案 A）、
1 道长英文题干单选、1 道多选（正确答案 A,C），以及第二题库 1 道单选（供跨题库场景）。
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres_support import isolated_postgres  # noqa: E402

QUESTION_COUNT = 10
LONG_STEM = "Which control is MOST effective for the international transfer scenario described above? " * 6
_dumps = json.dumps  # 上游请求体的关键字参数名是 json，函数内不能再引用同名模块


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with isolated_postgres() as engine, tempfile.TemporaryDirectory(prefix="quiz-review-storage-") as storage:
        os.environ.update(
            DATABASE_URL=engine.url.render_as_string(hide_password=False),
            AI_API_KEY="", JWT_SECRET_KEY="isolated-quiz-review-key",
            SECRET_KEY="isolated-quiz-review-encryption", STORAGE_ROOT=storage,
        )
        from sqlalchemy.orm import Session
        from app.core.database import Base
        from app.core.security import get_password_hash
        from app.models import Exam, Question, QuestionBank, User
        from app.main import create_app
        from app.services.settings_service import set_encrypted_ai_api_key, set_key
        from app.workers.job_worker import process_one_job
        import httpx
        import uvicorn

        def model_http(url, *, json: dict, **kwargs):  # noqa: A002
            """按 OpenAI 兼容协议返回可校验的翻译/解析结果。"""
            system_prompt = json["messages"][0]["content"]
            if '"options_zh"' in system_prompt:
                payload = {
                    "content_zh": "复盘翻译内容",
                    "options_zh": [{"key": key, "text_zh": f"选项{key}翻译"} for key in "ABCD"],
                }
            else:
                payload = {
                    "judged_answer": "A",
                    "stem_breakdown": {"qualifier": "MOST", "role": "数据保护负责人", "scenario": "跨境传输", "constraint": "", "asked": "选择最有效的控制措施"},
                    "explanation": "The measure reduces exposure across the full lifecycle.",
                    "explanation_zh": "该措施覆盖数据处理完整生命周期，能持续降低暴露风险。其余选项只覆盖单个环节，无法满足题干限制。",
                    "distractors": [{"key": key, "type": "范围过窄", "reason": "该措施只覆盖单个环节，无法满足整体限制"} for key in "BCD"],
                }
            return httpx.Response(200, json={"choices": [{"message": {"content": _dumps(payload, ensure_ascii=False)}}]})

        httpx.post = model_http  # 仅替换上游 HTTP；不替换任何业务模块。
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="study-user", email="review@example.invalid", password_hash=get_password_hash("StudyTest123!"), is_admin=True)
            db.add(user)
            db.flush()
            current = Exam(owner_id=user.id, slug="current", name="Current", short_name="Current")
            other = Exam(owner_id=user.id, slug="other", name="Other", short_name="Other")
            db.add_all([current, other])
            db.flush()
            user.active_exam_id = current.id
            bank = QuestionBank(exam_id=current.id, name="Review Bank", question_count=QUESTION_COUNT)
            db.add(bank)
            db.flush()
            for index in range(1, QUESTION_COUNT + 1):
                db.add(Question(
                    bank_id=bank.id, question_type="single",
                    content=f"Which control is MOST effective? {index}",
                    options=[{"key": key, "text": f"Option {key} for question {index}"} for key in "ABCD"],
                    correct_answer="A", order_index=index,
                ))
            db.add(Question(
                bank_id=bank.id, question_type="single", content=LONG_STEM,
                options=[{"key": key, "text": f"Long option {key} " * 12} for key in "ABCD"],
                correct_answer="A", order_index=QUESTION_COUNT + 1,
            ))
            # 第二个题库：跨题库错题练习的成员分属两个题库，重开必须逐题复用而非只取首个。
            # 多选题也放这里，不混进主库——主库被既有 E2E 按「答 A 即正确」的假设抽题，
            # 混入正确答案为 A,C 的题会让那些断言随抽题结果漂移。
            second_bank = QuestionBank(exam_id=current.id, name="Second Bank", question_count=2)
            db.add(second_bank)
            db.flush()
            db.add(Question(
                bank_id=second_bank.id, question_type="single",
                content="Cross-bank question from the second bank",
                options=[{"key": key, "text": f"Second bank option {key}"} for key in "ABCD"],
                correct_answer="B", order_index=1,
            ))
            db.add(Question(
                bank_id=second_bank.id, question_type="multiple",
                content="Which TWO controls are required? (choose two)",
                options=[{"key": key, "text": f"Multi option {key}"} for key in "ABCD"],
                correct_answer="A,C", order_index=2,
            ))
            bank.question_count = QUESTION_COUNT + 1
            set_key(db, "ai_api_base_url", "https://8.8.8.8")
            set_encrypted_ai_api_key(db, "isolated-quiz-review-token")
            set_key(db, "ai_explain_models", json.dumps([
                {"model_id": "model-alpha", "reasoning_effort": None},
                {"model_id": "model-beta", "reasoning_effort": None},
            ]))
            db.commit()

        stop = Event()

        def worker():
            while not stop.is_set():
                if not process_one_job():
                    stop.wait(0.05)

        threads = [Thread(target=worker, daemon=True) for _ in range(3)]
        for thread in threads:
            thread.start()
        try:
            uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            stop.set()
            for thread in threads:
                thread.join(10)


if __name__ == "__main__":
    main()
