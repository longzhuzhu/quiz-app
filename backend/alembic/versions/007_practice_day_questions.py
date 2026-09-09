"""practice day questions fact table for heatmap

Revision ID: 007
Revises: 006
Create Date: 2026-09-09 00:00:00.000000

练习日不从 quiz_answers.answered_at 推导（见 docs/adr/0005）。
本迁移只加表，不改存量答题记录，也不回填历史格子。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "practice_day_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_practice_day_questions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id"],
            ["exams.id"],
            name="fk_practice_day_questions_exam_id_exams",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name="fk_practice_day_questions_question_id_questions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "exam_id",
            "local_date",
            "question_id",
            name="uq_practice_day_questions_user_exam_date_question",
        ),
    )
    op.create_index(
        "idx_practice_day_questions_user_exam_date",
        "practice_day_questions",
        ["user_id", "exam_id", "local_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_practice_day_questions_user_exam_date",
        table_name="practice_day_questions",
    )
    op.drop_table("practice_day_questions")
