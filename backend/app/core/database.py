"""数据库配置 - SQLAlchemy 2.x + PostgreSQL"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    # 解析任务同时持有会话连接与 advisory lock 连接，池上限需覆盖 worker 线程数加解析槽位数。
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
