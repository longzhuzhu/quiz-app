"""后台任务 Worker（适配 FastAPI + SQLAlchemy 2.x）

直接创建 SessionLocal 获取 db session，并使用 FastAPI 的 Settings 配置
"""

import argparse
import logging
import os
import sys
import threading
import time
from typing import TypedDict

from app.core.database import SessionLocal
from app.services import job_service
from app.services.job_handlers import run_job
from app.services.import_execution import ImportExecution, LeaseLost, execution_for, release_import_execution

logger = logging.getLogger(__name__)

class _ImportTerminalKwargs(TypedDict, total=False):
    execution: ImportExecution


DEFAULT_WORKER_ID = "job-worker"
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_CONCURRENCY = 10
# SQLite 单机部署只允许一个业务执行线程；API 与 worker 仍是两个进程。
SQLITE_CONCURRENCY = 1


def _effective_concurrency(requested: int, db_engine=None) -> int:
    if db_engine is None:
        from app.core.database import engine as db_engine

    if db_engine.dialect.name == "sqlite":
        if requested > SQLITE_CONCURRENCY:
            logger.warning(
                "SQLite 部署将 worker 并发从 %s 限制为 %s（配置文件中的值未修改）",
                requested, SQLITE_CONCURRENCY,
            )
        return SQLITE_CONCURRENCY
    return requested


def process_one_job(worker_id: str = DEFAULT_WORKER_ID) -> bool:
    db = SessionLocal()
    job = None
    execution = None
    try:
        job_service.recover_stale_jobs(db)
        job = job_service.claim_next_job(db, worker_id=worker_id)
        if job is None:
            return False
        execution = execution_for(db)
        terminal_kwargs: _ImportTerminalKwargs = {"execution": execution} if execution is not None else {}

        try:
            # handler 可以返回一段收尾说明（如「部分批次跳过」），没有则用默认文案
            completion_message = run_job(db, job)
            job = db.get(type(job), job.id)
            if completion_message:
                job_service.complete_job(db, job, completion_message, **terminal_kwargs)
            else:
                job_service.complete_job(db, job, **terminal_kwargs)
        except LeaseLost:
            db.rollback()
            logger.warning("[smart_import] fenced worker background_job_id=%s attempt=%s",
                           execution.token.background_job_id if execution else job.id,
                           execution.token.attempt_count if execution else None)
        except Exception as exc:
            db.rollback()
            job = db.get(type(job), job.id)
            if job is None:
                raise
            try:
                job_service.requeue_job(db, job, str(exc), **terminal_kwargs)
            except LeaseLost:
                db.rollback()
        return True
    finally:
        try:
            db.rollback()
        finally:
            try:
                release_import_execution(db, job)
            finally:
                job_service.release_explanation_slot(job)
                db.close()


def worker_loop(
    worker_id: str = DEFAULT_WORKER_ID,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    once: bool = False,
) -> bool:
    while True:
        processed = process_one_job(worker_id=worker_id)
        if once:
            return processed
        if not processed:
            time.sleep(poll_interval)


def run_worker(
    worker_id: str = DEFAULT_WORKER_ID,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    once: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> int:
    concurrency = _effective_concurrency(max(int(concurrency or 1), 1))

    if concurrency == 1:
        worker_loop(worker_id=worker_id, poll_interval=poll_interval, once=once)
        return 0

    threads = []
    for index in range(concurrency):
        thread = threading.Thread(
            target=worker_loop,
            kwargs={
                "worker_id": f"{worker_id}-{index + 1}",
                "poll_interval": poll_interval,
                "once": once,
            },
            daemon=not once,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quiz App background job worker")
    parser.add_argument("--once", action="store_true", help="只处理一轮后退出")
    parser.add_argument("--worker-id", default=os.environ.get("JOB_WORKER_ID", DEFAULT_WORKER_ID))
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("JOB_WORKER_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL))),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("JOB_WORKER_CONCURRENCY", str(DEFAULT_CONCURRENCY))),
    )
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_worker(
        worker_id=args.worker_id,
        poll_interval=args.poll_interval,
        once=args.once,
        concurrency=args.concurrency,
    )


if __name__ == "__main__":
    raise SystemExit(main())
