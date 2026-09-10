"""practice accuracy day snapshots for the trend chart

Revision ID: 008
Revises: 007
Create Date: 2026-09-10 00:00:00.000000

滚动正确率按日快照，不从 quiz_answers.answered_at 回放（见 docs/adr/0006）。
本迁移只加表，不回填历史正确率形状。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "practice_accuracy_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_practice_accuracy_days_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"],
            ["exams.id"],
            name="fk_practice_accuracy_days_exam_id_exams",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "exam_id",
            "local_date",
            name="uq_practice_accuracy_days_user_exam_date",
        ),
    )
    op.create_index(
        "idx_practice_accuracy_days_user_exam_date",
        "practice_accuracy_days",
        ["user_id", "exam_id", "local_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_practice_accuracy_days_user_exam_date",
        table_name="practice_accuracy_days",
    )
    op.drop_table("practice_accuracy_days")
