"""用户启用状态：账号改由管理员创建，停用只阻止新登录。

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default 不可省：存量用户必须可登录，非空列直接加会失败。
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
