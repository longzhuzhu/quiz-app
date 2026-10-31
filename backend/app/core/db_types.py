"""跨数据库的列类型：PostgreSQL 使用 JSONB，其他受支持后端使用通用 JSON。"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# 同一实例可被多个列复用；SQLAlchemy 类型对象在列定义时不会被就地修改。
JSONType = JSON().with_variant(JSONB(), "postgresql")
