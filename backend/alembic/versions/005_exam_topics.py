"""exam topics and question topic tagging

Revision ID: 005
Revises: 004
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, text
from sqlalchemy.dialects.postgresql import JSONB

# 迁移文件保持自包含：不导入会随应用演进的模型或默认常量。
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _json_default(value: str):
    """JSON 列服务端默认值：PostgreSQL 保留原 ``'...'::jsonb``，SQLite 使用 JSON 文本。"""
    if op.get_bind().dialect.name == "postgresql":
        return text(f"'{value}'::jsonb")
    return text(f"'{value}'")

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exam_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_zh", sa.Text(), nullable=False),
        sa.Column("short_name_zh", sa.String(length=40), nullable=False),
        sa.Column("blueprint_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blueprint_max", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "indicators_en",
            JSONType,
            nullable=False,
            server_default=_json_default("[]"),
        ),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_version", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exams.id"], name="fk_exam_topics_exam_id_exams", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["exam_topics.id"],
            name="fk_exam_topics_parent_id_exam_topics",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("exam_id", "code", name="uq_exam_topics_exam_code"),
    )
    op.create_index(
        "idx_exam_topics_exam_level_order",
        "exam_topics",
        ["exam_id", "level", "order_index"],
        unique=False,
    )

    op.create_table(
        "question_topics",
        sa.Column("question_id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="ai"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name="fk_question_topics_question_id_questions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["exam_topics.id"],
            name="fk_question_topics_topic_id_exam_topics",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_question_topics_topic_question",
        "question_topics",
        ["topic_id", "question_id"],
        unique=False,
    )

    if op.get_bind().dialect.name == "sqlite":
        # SQLite 不支持 ALTER ADD CONSTRAINT，列与外键一起通过 batch 重建。
        with op.batch_alter_table("quiz_sessions") as batch:
            batch.add_column(sa.Column("topic_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_quiz_sessions_topic_id_exam_topics",
                "exam_topics",
                ["topic_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.add_column("quiz_sessions", sa.Column("topic_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_quiz_sessions_topic_id_exam_topics",
            "quiz_sessions",
            "exam_topics",
            ["topic_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("quiz_sessions") as batch:
            batch.drop_constraint("fk_quiz_sessions_topic_id_exam_topics", type_="foreignkey")
            batch.drop_column("topic_id")
    else:
        op.drop_constraint("fk_quiz_sessions_topic_id_exam_topics", "quiz_sessions", type_="foreignkey")
        op.drop_column("quiz_sessions", "topic_id")

    op.drop_index("idx_question_topics_topic_question", table_name="question_topics")
    op.drop_table("question_topics")

    op.drop_index("idx_exam_topics_exam_level_order", table_name="exam_topics")
    op.drop_table("exam_topics")
