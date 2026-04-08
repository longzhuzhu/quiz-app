#!/usr/bin/env python3
import argparse
import os
import socket
import sys
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from models import db
from services import job_service
from services.job_handlers import get_job_handler


def process_one_job(app, worker_id=None):
    worker_id = worker_id or socket.gethostname()
    with app.app_context():
        job_service.recover_stale_jobs()
        job = job_service.claim_next_job(worker_id=worker_id)
        if job is None:
            return False

        try:
            handler = get_job_handler(job.job_type)
            handler(job, worker_id=worker_id)
            job = db.session.get(type(job), job.id)
            job_service.complete_job(job)
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(type(job), job.id)
            if job is None:
                raise
            if job_service.should_retry(job):
                job_service.requeue_job(job, str(exc))
            else:
                job_service.fail_job(job, str(exc))
        return True


def run_worker(app, worker_id=None, poll_interval=5.0, once=False):
    while True:
        processed = process_one_job(app, worker_id=worker_id)
        if once:
            return 0
        if not processed:
            time.sleep(poll_interval)


def build_arg_parser():
    parser = argparse.ArgumentParser(description='Quiz App background job worker')
    parser.add_argument('--once', action='store_true', help='只处理一轮后退出')
    parser.add_argument('--worker-id', default=os.environ.get('JOB_WORKER_ID') or socket.gethostname())
    parser.add_argument('--poll-interval', type=float, default=float(os.environ.get('JOB_WORKER_POLL_INTERVAL', '5')))
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    app = create_app()
    return run_worker(app, worker_id=args.worker_id, poll_interval=args.poll_interval, once=args.once)


if __name__ == '__main__':
    raise SystemExit(main())
