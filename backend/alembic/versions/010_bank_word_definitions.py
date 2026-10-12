"""为高频词保存中英文释义，既有词条不回填。

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_word_frequencies", sa.Column("definition", sa.Text(), nullable=True))
    op.add_column("bank_word_frequencies", sa.Column("definition_zh", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bank_word_frequencies", "definition_zh")
    op.drop_column("bank_word_frequencies", "definition")
