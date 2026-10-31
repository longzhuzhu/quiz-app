"""跨进程逻辑互斥：PostgreSQL 使用 advisory lock，SQLite 使用同机原生文件锁。

只用于长生命周期执行（解析并发槽位、单个 ImportJob 写者），不代替数据库
短事务内的行锁或条件更新。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

EXPLANATION_SLOT_NAMESPACE = 540066
IMPORT_LOCK_NAMESPACE = 540067

# 可选覆盖：SQLite 锁文件默认放在数据库文件同目录的 .db-locks/ 下。
SQLITE_LOCK_DIR_ENV = "SQLITE_LOCK_DIR"


class LockBackendUnavailable(RuntimeError):
    """所需锁后端不可用；调用方必须失败关闭，不能静默降级成无锁。"""


def sqlite_lock_dir(engine: Engine) -> Path:
    """返回与 SQLite 数据库路径绑定的锁目录；内存库使用进程内临时目录。"""
    configured = os.environ.get(SQLITE_LOCK_DIR_ENV)
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            raise LockBackendUnavailable("SQLITE_LOCK_DIR 必须是绝对路径")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path
    database = engine.url.database
    if not database or database == ":memory:":
        # 内存库只用于单进程测试，锁目录仍保持进程内唯一。
        path = Path(os.environ.get("TMPDIR", "/tmp")) / f"quiz-db-locks-memory-{os.getpid()}"
    else:
        path = Path(database).resolve().parent / ".db-locks"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _sqlite_lock_file(engine: Engine, namespace: int, key: int) -> Path:
    database = engine.url.database
    scope = str(Path(database).resolve()) if database and database != ":memory:" else "memory"
    digest = hashlib.sha256(f"{scope}:{namespace}:{key}".encode()).hexdigest()[:32]
    return sqlite_lock_dir(engine) / f"{namespace}-{digest}.lock"


class FileLockHandle:
    """已验证为原生 OS 锁的句柄；持有期间必须强引用。"""

    def __init__(self, lock_file: Path):
        from filelock import FileLock

        self._lock = FileLock(str(lock_file), timeout=0, thread_local=False)
        self._acquired = False

    def try_acquire(self) -> bool:
        from filelock import Timeout

        try:
            self._lock.acquire()
        except Timeout:
            return False
        self._acquired = True
        return True

    def release(self) -> None:
        if self._acquired:
            self._acquired = False
            self._lock.release()

    @property
    def held(self) -> bool:
        return self._acquired and self._lock.is_locked


def _require_native_filelock() -> None:
    import filelock

    # 无原生后端的平台会退化为 SoftFileLock；SQLite 部署只能使用可信本地磁盘的原生锁。
    if filelock.FileLock is filelock.SoftFileLock:
        raise LockBackendUnavailable("SQLite 部署需要原生文件锁后端，禁止使用 SoftFileLock")
    if os.name != "posix":
        raise LockBackendUnavailable("SQLite 部署仅支持具备原生文件锁的 Unix 平台")


def sqlite_try_lock(engine: Engine, namespace: int, key: int):
    """尝试获取 SQLite 文件锁；成功返回句柄，忙返回 None。"""
    _require_native_filelock()
    handle = FileLockHandle(_sqlite_lock_file(engine, namespace, key))
    if handle.try_acquire():
        return handle
    return None


def pg_try_lock(engine: Engine, namespace: int, key: int):
    """获取 PostgreSQL 会话级 advisory lock；成功返回专用连接，忙返回 None。"""
    connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        acquired = connection.exec_driver_sql(
            "SELECT pg_try_advisory_lock(%s, %s)", (namespace, key)
        ).scalar()
    except BaseException:
        connection.invalidate()
        connection.close()
        raise
    if acquired:
        return connection
    connection.close()
    return None


def pg_holds_lock(connection, namespace: int, key: int) -> bool:
    """校验该连接仍持有指定 advisory lock；连接失效时抛错。"""
    if connection.closed or connection.invalidated:
        raise LockBackendUnavailable("advisory lock 连接已失效")
    return bool(connection.exec_driver_sql(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
        "AND pid = pg_backend_pid() AND classid = %s AND objid = %s AND objsubid = 2 AND granted)",
        (namespace, key),
    ).scalar())


def pg_release_lock(connection, namespace: int, key: int) -> None:
    try:
        if not connection.closed and not connection.invalidated:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(%s, %s)", (namespace, key))
    except Exception:
        connection.invalidate()
    finally:
        connection.close()


def try_backend_lock(engine: Engine, namespace: int, key: int):
    """按 dialect 获取对应后端的长生命周期锁。"""
    if engine.dialect.name == "postgresql":
        return pg_try_lock(engine, namespace, key)
    if engine.dialect.name == "sqlite":
        return sqlite_try_lock(engine, namespace, key)
    raise LockBackendUnavailable(f"不支持的数据库类型: {engine.dialect.name}")


def release_backend_lock(handle, namespace: int, key: int) -> None:
    if handle is None:
        return
    if isinstance(handle, FileLockHandle):
        handle.release()
        return
    pg_release_lock(handle, namespace, key)


def backend_lock_held(handle, namespace: int, key: int) -> bool:
    """锁仍有效返回 True；后端不可用抛 LockBackendUnavailable，绝不静默放行。"""
    if handle is None:
        return False
    if isinstance(handle, FileLockHandle):
        return handle.held
    return pg_holds_lock(handle, namespace, key)


def engine_for_session(db: Session) -> Engine:
    """Session 绑定可能是 Engine 或 Connection；统一取 Engine。"""
    bind = db.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine
