"""导入专用执行锁与 attempt fencing；不改变其他后台任务的生命周期。"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
import json
import logging
import threading

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.background_job import BackgroundJob
from app.models.import_job import ImportJob

logger = logging.getLogger(__name__)

IMPORT_LOCK_NAMESPACE = 540067
EXECUTION_KEY = "import_execution"
IMPORT_JOB_TYPES = {"question_import_llm", "question_import_llm_reparse"}


class LeaseLost(RuntimeError):
    """控制流：旧 attempt 不得继续业务写入或改写新 attempt 终态。"""


class ImportBusy(RuntimeError):
    """同一导入任务已有写者。"""


def is_postgres_session(db) -> bool:
    return isinstance(db, Session) and db.get_bind().dialect.name == "postgresql"


def acquire_import_lock(db: Session, import_job_id: int) -> Connection | None:
    connection = db.get_bind().engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        if connection.exec_driver_sql("SELECT pg_try_advisory_lock(%s, %s)",
                                      (IMPORT_LOCK_NAMESPACE, import_job_id)).scalar():
            return connection
    except BaseException:
        connection.invalidate()
        connection.close()
        raise
    connection.close()
    return None


def release_import_lock(connection: Connection, import_job_id: int) -> None:
    try:
        if not connection.closed and not connection.invalidated:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(%s, %s)",
                                       (IMPORT_LOCK_NAMESPACE, import_job_id))
    except Exception:
        connection.invalidate()
    finally:
        connection.close()


@dataclass(frozen=True)
class AttemptToken:
    background_job_id: int
    attempt_count: int
    import_job_id: int


class ImportExecution:
    def __init__(self, token: AttemptToken, connection: Connection, bind: Engine | Connection, lease_seconds: int):
        self._token = token
        self.connection = connection
        self.lock_pid = connection.exec_driver_sql("SELECT pg_backend_pid()").scalar()
        self.lease_seconds = lease_seconds
        self.sessions = sessionmaker(bind=bind.engine)
        self.lost = threading.Event()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def token(self) -> AttemptToken:
        return self._token

    def descriptor(self) -> dict:
        return {"request_id": self.token.background_job_id, "attempt": self.token.attempt_count}

    def check_lock(self) -> None:
        if self.lost.is_set() or self.connection.closed or self.connection.invalidated:
            raise LeaseLost("导入执行租约或锁连接已失效")
        try:
            held = self.connection.exec_driver_sql(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = pg_backend_pid() AND classid = %s AND objid = %s AND objsubid = 2 AND granted)",
                (IMPORT_LOCK_NAMESPACE, self.token.import_job_id),
            ).scalar()
        except Exception as exc:
            self.lost.set()
            raise LeaseLost("导入锁连接不可用") from exc
        if not held:
            self.lost.set()
            raise LeaseLost("导入专用锁已丢失")

    def guard(self, db: Session) -> None:
        self.check_lock()
        # 与 claim 相同的锁顺序；列查询不覆盖尚未 flush 的业务对象。
        with db.no_autoflush:
            config = db.execute(select(ImportJob.config_json).where(
                ImportJob.id == self.token.import_job_id).with_for_update()).scalar_one_or_none()
            row = db.execute(select(BackgroundJob.status, BackgroundJob.attempt_count,
                                    BackgroundJob.lease_until).where(
                BackgroundJob.id == self.token.background_job_id).with_for_update()).one_or_none()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if (config is None or config.get("active_execution") != self.descriptor() or row is None
                or row.status != "running" or row.attempt_count != self.token.attempt_count
                or row.lease_until is None or row.lease_until.replace(tzinfo=None) <= now):
            self.lost.set()
            raise LeaseLost("导入 attempt 已被替换或租约已过期")

    def start_renewal(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._renew_loop, name=f"import-lease-{self.token.background_job_id}", daemon=True)
        self.thread.start()

    def renew_once(self) -> None:
        # 续约只锁 BackgroundJob；不访问共享业务 Session 或专用连接。
        now = datetime.now(timezone.utc)
        with self.sessions() as db:
            db.execute(text("SET LOCAL statement_timeout = 5000"))
            held = db.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND pid = :pid "
                "AND classid = :namespace AND objid = :job_id AND objsubid = 2 AND granted)"
            ), {"pid": self.lock_pid, "namespace": IMPORT_LOCK_NAMESPACE, "job_id": self.token.import_job_id}).scalar()
            if not held:
                raise LeaseLost("导入续约时专用锁已丢失")
            result = db.execute(update(BackgroundJob).where(
                BackgroundJob.id == self.token.background_job_id,
                BackgroundJob.status == "running",
                BackgroundJob.attempt_count == self.token.attempt_count,
                BackgroundJob.lease_until > now,
            ).values(heartbeat_at=now, lease_until=now + timedelta(seconds=self.lease_seconds)),
                execution_options={"synchronize_session": False})
            if result.rowcount != 1:
                raise LeaseLost("导入续约 token 不再有效")
            db.commit()

    def _renew_loop(self) -> None:
        while not self.stop.wait(max(0.1, self.lease_seconds / 3)):
            try:
                self.renew_once()
            except Exception as exc:
                self.lost.set()
                logger.warning("[smart_import] lease renewal lost background_job_id=%s attempt=%s error_type=%s",
                               self.token.background_job_id, self.token.attempt_count, type(exc).__name__)
                return

    def close(self) -> None:
        self.stop.set()
        try:
            if self.thread is not None and self.thread.ident is not None:
                self.thread.join()
        finally:
            release_import_lock(self.connection, self.token.import_job_id)


def execution_for(db: Session) -> ImportExecution | None:
    return db.info.get(EXECUTION_KEY) if isinstance(db, Session) else None


def require_execution(db, background_job_id=None, import_job_id=None) -> None:
    if is_postgres_session(db) and execution_for(db) is None:
        raise LeaseLost("导入必须先领取专用执行上下文")
    execution = execution_for(db)
    if execution is not None and (execution.token.background_job_id != background_job_id
                                  or execution.token.import_job_id != import_job_id):
        raise LeaseLost("导入请求与不可变执行上下文不匹配")


def commit_import(db: Session) -> None:
    execution = execution_for(db)
    if execution is not None:
        execution.guard(db)
    review_lock = db.info.get("import_review_lock") if isinstance(db, Session) else None
    if review_lock is not None:
        connection, job_id = review_lock
        if connection.closed or connection.invalidated:
            raise LeaseLost("人工复核写者锁已失效")
        try:
            held = connection.exec_driver_sql(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
                "AND classid = %s AND objid = %s AND objsubid = 2 AND granted)",
                (IMPORT_LOCK_NAMESPACE, job_id),
            ).scalar()
        except Exception as exc:
            raise LeaseLost("人工复核写者锁连接不可用") from exc
        if not held:
            raise LeaseLost("人工复核写者锁已丢失")
        with db.no_autoflush:
            db.execute(select(ImportJob.id).where(ImportJob.id == job_id).with_for_update())
    db.commit()


def release_import_execution(db: Session, job: BackgroundJob | None = None) -> None:
    execution = db.info.pop(EXECUTION_KEY, None) if isinstance(db, Session) else None
    if execution is None and job is not None:
        execution = getattr(job, "_import_execution", None)
    if execution is not None:
        execution.close()
    if job is not None:
        job._import_execution = None


@contextmanager
def review_writer(db, import_job_id: int):
    if not is_postgres_session(db):
        yield
        return
    connection = acquire_import_lock(db, import_job_id)
    if connection is None:
        db.rollback()
        raise ImportBusy("导入任务正在解析或复核，请稍后重试")
    try:
        db.rollback()  # 丢弃入口读取的旧快照；尚未开始业务修改。
        db.execute(select(ImportJob.id).where(ImportJob.id == import_job_id).with_for_update())
        db.info["import_review_lock"] = (connection, import_job_id)
        yield
    except BaseException:
        db.rollback()
        raise
    finally:
        try:
            db.rollback()
        finally:
            db.info.pop("import_review_lock", None)
            release_import_lock(connection, import_job_id)


def coordinated_review(function):
    @wraps(function)
    def wrapped(db, import_job_id, *args, **kwargs):
        try:
            with review_writer(db, import_job_id):
                return function(db, import_job_id, *args, **kwargs)
        except ImportBusy as exc:
            return {"error": str(exc), "status_code": 409}
    return wrapped


def try_claim_import(
    db: Session, candidate: BackgroundJob, worker_id: str, now: datetime, lease_seconds: int,
) -> BackgroundJob | None:
    from app.models.import_chunk import ImportChunk
    if execution_for(db) is not None:
        # 一个业务 Session 只能拥有一个不可变领取上下文，不能覆盖仍在运行的 writer。
        return None
    payload = json.loads(candidate.payload_json or "{}")
    if not isinstance(payload, dict) or lease_seconds <= 0:
        raise ValueError("导入 payload 或 lease 配置无效")
    import_job_id = payload.get("import_job_id")
    if not isinstance(import_job_id, int) or isinstance(import_job_id, bool):
        raise ValueError("导入 payload 缺少有效 import_job_id")
    candidate_id = candidate.id
    db.rollback()
    connection = acquire_import_lock(db, import_job_id)
    if connection is None:
        return None
    execution = None
    try:
        import_job = db.query(ImportJob).filter_by(id=import_job_id).with_for_update().populate_existing().first()
        current = db.query(BackgroundJob).filter_by(id=candidate_id).with_for_update().populate_existing().first()
        if import_job is None:
            raise ValueError("导入任务不存在")
        if current is None or current.status != "queued" or (current.next_run_at and current.next_run_at.replace(tzinfo=None) > now.replace(tzinfo=None)):
            db.rollback()
            release_import_lock(connection, import_job_id)
            return None
        if current.job_type not in IMPORT_JOB_TYPES or json.loads(current.payload_json or "{}") != payload:
            raise ValueError("导入请求在领取期间发生变化")
        if current.job_type == "question_import_llm":
            if import_job.background_job_id != current.id:
                raise ValueError("主导入请求不属于该 ImportJob")
        else:
            chunk = db.get(ImportChunk, payload.get("chunk_id"))
            if chunk is None or chunk.import_job_id != import_job_id or payload.get("bank_id") != import_job.bank_id:
                raise ValueError("重解析 chunk/bank 不属于该导入任务")
        # stale recovery 可以把最后一次执行重排 queued；领取锁内必须再次检查额度。
        # 尚未领取新 attempt，不能调用要求 running token 的 fail_job。
        if (current.attempt_count or 0) >= (current.max_attempts or 0):
            current.status = "failed"
            current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
            current.progress_total = max(current.progress_total or 0, current.progress_done)
            current.last_error = current.last_error or "导入执行次数已耗尽，不能继续自动重试"
            current.status_message = f"任务已自动执行 {current.max_attempts} 次仍失败"
            current.finished_at = now
            current.next_run_at = None
            current.lease_until = None
            current.active_scope_key = None
            db.commit()
            release_import_lock(connection, import_job_id)
            return None
        current.status = "running"
        current.attempt_count = (current.attempt_count or 0) + 1
        current.started_at = current.started_at or now
        current.heartbeat_at = now
        current.lease_until = now + timedelta(seconds=lease_seconds)
        current.next_run_at = None
        current.status_message = f"worker {worker_id} 已接手任务"
        execution = ImportExecution(AttemptToken(current.id, current.attempt_count, import_job_id),
                                    connection, db.get_bind(), lease_seconds)
        import_job.config_json = {**(import_job.config_json or {}), "active_execution": execution.descriptor()}
        db.commit()
        current._import_execution = execution
        db.info[EXECUTION_KEY] = execution
        execution.start_renewal()
        return current
    except BaseException:
        try:
            db.rollback()
        finally:
            db.info.pop(EXECUTION_KEY, None)
            candidate._import_execution = None
            if execution is not None:
                execution.close()
            else:
                release_import_lock(connection, import_job_id)
        raise
