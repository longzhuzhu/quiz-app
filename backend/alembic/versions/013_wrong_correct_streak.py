"""错题连对次数：连续答对达标即自动掌握；存量行从 0 起算。

Revision ID: 013
Revises: 012
"""

from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default 不可省：该列参与算术（连对 +1），若存量行为 NULL，
    # 加成后仍是 NULL，掌握判定会永久失效。与 012 的可空字段取舍不同。
    op.add_column(
        "wrong_answers",
        sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("wrong_answers", "correct_streak")
