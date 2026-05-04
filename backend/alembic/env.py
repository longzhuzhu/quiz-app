"""Alembic 环境配置 - 支持 async/sync、自动生成迁移脚本"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 确保 backend/ 在 sys.path 中，以便导入 app 模块
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.core.database import Base

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
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行迁移"""
    url = config.get_main_option("sqlalchemy.url")
    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
