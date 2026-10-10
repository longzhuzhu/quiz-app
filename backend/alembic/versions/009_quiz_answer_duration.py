"""保存首次成功提交的单题耗时，旧记录不回填。

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quiz_answers", sa.Column("answer_duration_ms", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("quiz_answers", "answer_duration_ms")
