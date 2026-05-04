"""后台任务 Worker（适配 FastAPI + SQLAlchemy 2.x）

与 Flask 版的核心区别：
- 不依赖 Flask app context，直接创建 SessionLocal 获取 db session
- 使用 FastAPI 的 Settings 配置
"""

import argparse
import os
import sys
import threading
import time

from app.core.database import SessionLocal
from app.services import job_service
from app.services.job_handlers import run_job

DEFAULT_WORKER_ID = "job-worker"
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_CONCURRENCY = 2


def process_one_job(worker_id: str = DEFAULT_WORKER_ID) -> bool:
    db = SessionLocal()
    try:
        job_service.recover_stale_jobs(db)
        job = job_service.claim_next_job(db, worker_id=worker_id)
        if job is None:
            return False

        try:
            run_job(db, job)
            job = db.get(type(job), job.id)
            job_service.complete_job(db, job)
        except Exception as exc:
            db.rollback()
            job = db.get(type(job), job.id)
            if job is None:
                raise
            job_service.requeue_job(db, job, str(exc))
        return True
    finally:
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
    concurrency = max(int(concurrency or 1), 1)

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
