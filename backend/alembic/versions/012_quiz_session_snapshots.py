"""答题会话本场题目快照、完成冻结与最近一次错误答案；旧记录不回填。

Revision ID: 012
Revises: 011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 四列均可空：存量会话保持 NULL，复盘接口按「无快照」走兼容分支，不回填伪造历史。
    op.add_column("quiz_sessions", sa.Column("question_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("quiz_sessions", sa.Column("final_answers", postgresql.JSONB(), nullable=True))
    op.add_column("wrong_answers", sa.Column("last_wrong_answer", sa.String(20), nullable=True))
    op.add_column("wrong_answers", sa.Column("last_wrong_session_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("wrong_answers", "last_wrong_session_id")
    op.drop_column("wrong_answers", "last_wrong_answer")
    op.drop_column("quiz_sessions", "final_answers")
    op.drop_column("quiz_sessions", "question_snapshot")
