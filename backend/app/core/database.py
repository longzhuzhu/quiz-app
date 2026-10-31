"""数据库配置 - SQLAlchemy 2.x，部署时选择 PostgreSQL 或 SQLite。

默认仍为 PostgreSQL；SQLite 必须通过 DATABASE_URL 显式选择，不做自动回退。
"""

import sqlite3
from collections.abc import Generator
from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

SUPPORTED_BACKENDS = {"postgresql", "sqlite"}
# SQLite 会话在事务开始前取得写权限（BEGIN IMMEDIATE）的执行选项名。
SQLITE_IMMEDIATE = "sqlite_immediate"
SQLITE_BUSY_TIMEOUT_MS = 5000
# json_extract 在 SQLite 3.38 起默认编入；低于该版本拒绝启动，避免迁移期才暴露差异。
MINIMUM_SQLITE_VERSION = (3, 38, 0)


class DatabaseConfigError(ValueError):
    """数据库配置错误；消息不得包含连接串凭据。"""


def _dialect_name(url: str | URL) -> str:
    return make_url(url).get_backend_name()


def _sqlite_database_path(url: str | URL) -> Path | None:
    """文件型 SQLite 的绝对路径；内存库返回 None。"""
    database = make_url(url).database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.is_absolute():
        raise DatabaseConfigError("SQLite 部署必须使用绝对路径的数据库文件")
    return path


def _validate_url(url: str) -> str:
    backend = _dialect_name(url)
    if backend not in SUPPORTED_BACKENDS:
        raise DatabaseConfigError(f"不支持的数据库类型: {backend}；仅支持 PostgreSQL 与 SQLite")
    if backend == "sqlite":
        _sqlite_database_path(url)
    return backend


def _install_sqlite_hooks(engine: Engine, *, foreign_keys: bool) -> None:
    minimum = ".".join(str(part) for part in MINIMUM_SQLITE_VERSION)

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):
        if sqlite3.sqlite_version_info < MINIMUM_SQLITE_VERSION:
            raise DatabaseConfigError(
                f"SQLite 版本过低（{sqlite3.sqlite_version}），部署需要 {minimum} 或更高版本"
            )
        # 显式事务控制：避免 sqlite3 legacy 模式下 SELECT/DDL/SAVEPOINT 不进入事务。
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            # SQLite 默认不强制外键；ondelete 语义依赖每个连接都开启。
            cursor.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
            # 写竞争时最多等待 5 秒。回滚日志模式下，第一个写语句和 BEGIN IMMEDIATE
            # 都会遵守该等待；不使用 WAL，避免读到旧快照后升级写事务时直接 BUSY。
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _begin_sqlite(connection):
        if connection.get_execution_options().get(SQLITE_IMMEDIATE):
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.exec_driver_sql("BEGIN")


def create_db_engine(url: str, *, echo: bool = False, sqlite_foreign_keys: bool = True) -> Engine:
    """按 URL 创建 engine；PostgreSQL 保留原有池参数，SQLite 使用文件库默认池。"""
    backend = _validate_url(url)
    if backend == "postgresql":
        # 解析任务同时持有会话连接与 advisory lock 连接，池上限需覆盖 worker 线程数加解析槽位数。
        return create_engine(url, echo=echo, pool_pre_ping=True, pool_size=10, max_overflow=20)
    engine = create_engine(url, echo=echo, pool_pre_ping=True)
    _install_sqlite_hooks(engine, foreign_keys=sqlite_foreign_keys)
    return engine


engine = create_db_engine(settings.DATABASE_URL)


def _is_read_method(method: str) -> bool:
    return method.upper() in {"GET", "HEAD", "OPTIONS"}


def write_sessionmaker(bind):
    """返回写会话工厂；SQLite 的每个事务以 BEGIN IMMEDIATE 开始。"""
    if bind.dialect.name == "sqlite":
        bind = bind.execution_options(**{SQLITE_IMMEDIATE: True})
    return sessionmaker(bind=bind, autocommit=False, autoflush=False)


# 写会话：SQLite 每个事务先取得写权限，避免「先读后写」升级失败。
SessionLocal = write_sessionmaker(engine)
# 读会话：GET/HEAD/OPTIONS 使用 deferred 事务。
ReadSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


def get_db(request: Request) -> Generator[Session, None, None]:
    """FastAPI 依赖：GET/HEAD/OPTIONS 使用读会话，其余使用写会话。"""
    db = (ReadSessionLocal if _is_read_method(request.method) else SessionLocal)()
    try:
        yield db
    finally:
        db.close()


def is_sqlite_bind(db_or_bind) -> bool:
    bind = getattr(db_or_bind, "get_bind", lambda: db_or_bind)()
    return bind.dialect.name == "sqlite"
