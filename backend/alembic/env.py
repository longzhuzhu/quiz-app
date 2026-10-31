"""Alembic 环境配置 - 支持 PostgreSQL 与 SQLite 的可选部署。

默认仍使用应用配置的 DATABASE_URL；-x url= 可显式指向隔离数据库。
绝不能在不覆盖 URL 的情况下对生产配置执行测试性迁移。
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, event, pool
from sqlalchemy.engine import make_url

# 确保 backend/ 在 sys.path 中，以便导入 app 模块
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.core.database import Base, DatabaseConfigError, SUPPORTED_BACKENDS

# 导入所有模型，确保 Base.metadata 包含所有表定义
from app.models import *  # noqa: F401,F403

# Alembic Config 对象
config = context.config

# 设置数据库 URL（覆盖 alembic.ini 中的默认值）
# 优先使用命令行 -x url= 参数，其次使用 settings.DATABASE_URL
cmd_line_url = context.get_x_argument(as_dictionary=True).get("url")
if cmd_line_url:
    config.set_main_option("sqlalchemy.url", cmd_line_url)
else:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

database_url = config.get_main_option("sqlalchemy.url")
backend = make_url(database_url).get_backend_name()
if backend not in SUPPORTED_BACKENDS:
    raise DatabaseConfigError(f"不支持的数据库类型: {backend}；仅支持 PostgreSQL 与 SQLite")
is_sqlite = backend == "sqlite"
if is_sqlite:
    database = make_url(database_url).database
    if not database or database == ":memory:" or not os.path.isabs(database):
        raise DatabaseConfigError("SQLite 迁移必须使用绝对路径的数据库文件")

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData 对象，用于 autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本而不连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 未来自动生成的迁移对 SQLite 也使用 batch 操作；不影响已存在的迁移文件。
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行迁移"""
    url = config.get_main_option("sqlalchemy.url")
    if is_sqlite:
        connectable = create_engine(url, poolclass=pool.NullPool)

        @event.listens_for(connectable, "connect")
        def _configure_sqlite(dbapi_connection, _record):
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()
    else:
        connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if is_sqlite:
            # batch 重建需要临时关闭外键强制；只在迁移连接上操作并恢复。
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        try:
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    if is_sqlite:
        with connectable.connect() as connection:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"迁移后外键检查失败：{len(violations)} 条悬空引用")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
