"""数据库可选部署：配置识别、SQLite 文件库、跨进程锁与写事务边界。

边界说明：
- 不导入 backend/.env，不连接生产或开发业务库；SQLite 使用临时文件，PostgreSQL 仅做 URL 校验。
- 不使用内存 SQLite 作为“正式兼容”的证据：文件库才覆盖连接池、锁文件与跨进程行为。
- 外部 AI 不参与本文件。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import (  # noqa: E402
    DatabaseConfigError,
    SQLITE_IMMEDIATE,
    create_db_engine,
    is_sqlite_bind,
    write_sessionmaker,
)
from app.core.db_locks import (  # noqa: E402
    IMPORT_LOCK_NAMESPACE,
    FileLockHandle,
    LockBackendUnavailable,
    backend_lock_held,
    release_backend_lock,
    sqlite_lock_dir,
    try_backend_lock,
)


def _sqlite_engine(tmp_path: Path):
    return create_db_engine(f"sqlite:///{tmp_path / 'support.db'}")


def test_unsupported_backend_fails_without_echoing_credentials():
    with pytest.raises(DatabaseConfigError) as excinfo:
        create_db_engine("mysql://user:secret@127.0.0.1/db")
    message = str(excinfo.value)
    assert "mysql" in message
    assert "secret" not in message


def test_sqlite_requires_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DatabaseConfigError, match="绝对路径"):
        create_db_engine("sqlite:///relative.db")
    assert not (tmp_path / "relative.db").exists()


def test_postgres_url_keeps_existing_pool_contract():
    # 用 URL 对象组装，避免源码里出现可被误认为真实凭据的连接串字面量。
    url = URL.create(
        "postgresql+psycopg", username="user", password="pass",
        host="127.0.0.1", port=5432, database="quiz",
    )
    engine = create_db_engine(url.render_as_string(hide_password=False))
    assert engine.dialect.name == "postgresql"
    assert engine.pool.size() == 10
    assert engine.pool._max_overflow == 20
    engine.dispose()


def test_sqlite_file_engine_enables_foreign_keys_per_connection(tmp_path):
    engine = _sqlite_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        for _ in range(3):
            assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    # 同一 engine 的新连接也必须开启，不是建库时一次性设置。
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_sqlite_lock_dir_is_derived_from_database_path(tmp_path):
    engine = _sqlite_engine(tmp_path)
    lock_dir = sqlite_lock_dir(engine)
    assert lock_dir == (tmp_path / ".db-locks").resolve()
    assert lock_dir.is_dir()
    engine.dispose()


def test_file_lock_is_exclusive_across_processes(tmp_path):
    """两个独立 Python 进程争同一锁：只有一个成功，退出后另一个可领取。"""
    lock_dir = tmp_path / ".db-locks"
    lock_dir.mkdir()
    script = textwrap.dedent(
        """
        import sys, time
        from filelock import FileLock, Timeout
        lock_file = sys.argv[1]
        hold_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 0
        lock = FileLock(lock_file, timeout=0, thread_local=False)
        try:
            lock.acquire()
        except Timeout:
            print("busy", flush=True)
        else:
            print("held", flush=True)
            time.sleep(hold_seconds)
            lock.release()
        """
    )
    lock_file = lock_dir / "shared.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_file), "30"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        contender = subprocess.run(
            [sys.executable, "-c", script, str(lock_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert contender.stdout.strip() == "busy"
    finally:
        holder.terminate()
        holder.wait(timeout=10)
    after = subprocess.run(
        [sys.executable, "-c", script, str(lock_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert after.stdout.strip() == "held"


def test_backend_lock_detects_release(tmp_path):
    engine = _sqlite_engine(tmp_path)
    first = try_backend_lock(engine, IMPORT_LOCK_NAMESPACE, 7)
    assert isinstance(first, FileLockHandle)
    assert try_backend_lock(engine, IMPORT_LOCK_NAMESPACE, 7) is None
    assert backend_lock_held(first, IMPORT_LOCK_NAMESPACE, 7)
    release_backend_lock(first, IMPORT_LOCK_NAMESPACE, 7)
    assert not backend_lock_held(first, IMPORT_LOCK_NAMESPACE, 7)
    second = try_backend_lock(engine, IMPORT_LOCK_NAMESPACE, 7)
    assert second is not None
    release_backend_lock(second, IMPORT_LOCK_NAMESPACE, 7)
    engine.dispose()


def test_soft_filelock_fallback_is_rejected(monkeypatch):
    import filelock

    monkeypatch.setattr(filelock, "FileLock", filelock.SoftFileLock)
    with pytest.raises(LockBackendUnavailable):
        try_backend_lock(_fake_sqlite_engine(), IMPORT_LOCK_NAMESPACE, 1)


def _fake_sqlite_engine():
    class _Dialect:
        name = "sqlite"

    class _Engine:
        dialect = _Dialect()
        url = type("URL", (), {"database": ":memory:"})()

    return _Engine()


def test_write_session_starts_immediate_and_holds_write_permission(tmp_path):
    engine = _sqlite_engine(tmp_path)
    Session = write_sessionmaker(engine)
    with Session() as db:
        db.execute(text("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)"))
        db.commit()

    holder = Session()
    holder.execute(text("INSERT INTO t (v) VALUES ('y')"))
    # 写会话的第一条语句就是写事务（BEGIN IMMEDIATE），此时另一个连接拿不到写权限。
    blocked = write_sessionmaker(engine)()
    try:
        blocked.execute(text("INSERT INTO t (v) VALUES ('z')"))
        blocked.commit()
        raise AssertionError("IMMEDIATE 持有期间第二个写会话不应成功")
    except Exception:
        blocked.rollback()
    finally:
        blocked.close()
        holder.commit()
        holder.close()
    with Session() as db:
        assert db.execute(text("SELECT count(*) FROM t")).scalar() == 1
    engine.dispose()


def test_read_session_does_not_take_write_lock(tmp_path):
    engine = _sqlite_engine(tmp_path)
    writer = write_sessionmaker(engine)
    with writer() as db:
        db.execute(text("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)"))
        db.commit()
    holder = writer()
    holder.execute(text("INSERT INTO t (id) VALUES (1)"))
    reader = sessionmaker(bind=engine)()
    try:
        # deferred 读在写者持有写锁时仍可读取已提交数据。
        assert reader.execute(text("SELECT count(*) FROM t")).scalar() == 0
    finally:
        reader.close()
        holder.commit()
        holder.close()
    engine.dispose()


def test_is_sqlite_bind_recognises_connection_bound_sessions(tmp_path):
    engine = _sqlite_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.execute(text("SELECT 1"))
        assert is_sqlite_bind(db) is True
    with engine.connect() as conn:
        Session2 = sessionmaker(bind=conn)
        with Session2() as db:
            assert is_sqlite_bind(db) is True
    engine.dispose()


def test_sqlite_datetime_roundtrip_keeps_naive_utc_semantics(tmp_path):
    """UTC aware 值写入 SQLite 后读回为 naive；现有到期比较须自行归一化。"""
    from sqlalchemy import Column, DateTime, Integer, MetaData, Table, insert, select

    engine = _sqlite_engine(tmp_path)
    metadata = MetaData()
    table = Table(
        "datetimes", metadata,
        Column("id", Integer, primary_key=True),
        Column("at", DateTime, nullable=False),
    )
    metadata.create_all(engine)
    moment = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(insert(table).values(id=1, at=moment))
        raw = conn.exec_driver_sql("SELECT at FROM datetimes").scalar()
        typed = conn.execute(select(table.c.at)).scalar()
    assert raw == "2026-10-31 12:00:00.000000"
    assert typed == datetime(2026, 10, 31, 12, 0)
    assert typed.tzinfo is None
    engine.dispose()


def test_worker_session_factory_can_request_immediate_begin(tmp_path):
    """OptionEngine 共享连接池；会话级 begin 选项让 worker 每条事务先取写锁。"""
    engine = _sqlite_engine(tmp_path)
    begins: list[bool] = []

    @event.listens_for(engine, "begin")
    def _record(connection):
        begins.append(bool(connection.get_execution_options().get(SQLITE_IMMEDIATE)))

    immediate_engine = engine.execution_options(**{SQLITE_IMMEDIATE: True})
    assert immediate_engine.pool is engine.pool
    Session = sessionmaker(bind=immediate_engine)
    with Session() as db:
        db.execute(text("SELECT 1"))
    assert begins == [True]
    engine.dispose()
