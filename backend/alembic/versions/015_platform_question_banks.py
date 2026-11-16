"""平台题库来源、草稿与不可变发布版本；个人副本来源标识与导入双目标。

Revision ID: 015
Revises: 014

边界：
- 存量个人数据原样保留：question_banks 来源字段为 NULL，import_jobs 仍指向个人题库，
  不做任何平台回填，也不把旧管理员题库自动公开。
- 有新平台数据时 downgrade 必须显式拒绝破坏性回退，不能删除来源/发布快照或
  把个人副本「洗成」自建库后悄悄放开编辑权限。
- SQLite 的约束/可空变更使用 batch；JSON 列使用跨后端 JSONType。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, text
from sqlalchemy.dialects.postgresql import JSONB

# 迁移文件保持自包含：不导入会随应用演进的模型或默认常量。
JSONType = JSON().with_variant(JSONB(), "postgresql")

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

PLATFORM_TABLES = (
    "platform_bank_releases",
    "platform_draft_questions",
    "platform_banks",
)


def _has_platform_data() -> bool:
    """存在任何平台来源、草稿、发布版或平台副本/平台任务时返回 True"""
    bind = op.get_bind()
    for table in PLATFORM_TABLES:
        if bind.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            return True
    if bind.execute(
        text("SELECT 1 FROM question_banks WHERE source_platform_bank_id IS NOT NULL LIMIT 1")
    ).first() is not None:
        return True
    if bind.execute(
        text("SELECT 1 FROM import_jobs WHERE platform_bank_id IS NOT NULL LIMIT 1")
    ).first() is not None:
        return True
    if bind.execute(
        text("SELECT 1 FROM background_jobs WHERE platform_bank_id IS NOT NULL LIMIT 1")
    ).first() is not None:
        return True
    return False


def upgrade() -> None:
    # ─── 平台来源 / 草稿题 / 发布版本 ───────────────────────────────
    op.create_table(
        "platform_banks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_listed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_platform_banks_name_not_blank"),
    )
    op.create_index("idx_platform_banks_listed", "platform_banks", ["is_listed"])

    op.create_table(
        "platform_draft_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "platform_bank_id",
            sa.String(36),
            sa.ForeignKey("platform_banks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_zh", sa.Text(), nullable=True),
        sa.Column("options", JSONType, nullable=False),
        sa.Column("correct_answer", sa.String(20), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_topics", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_platform_draft_questions_bank",
        "platform_draft_questions",
        ["platform_bank_id", "order_index"],
    )

    op.create_table(
        "platform_bank_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "platform_bank_id",
            sa.String(36),
            sa.ForeignKey("platform_banks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "platform_bank_id", "version_number", name="uq_platform_bank_releases_version"
        ),
        # 支撑 question_banks 的组合外键：副本记录的版本必须属于该来源。
        sa.UniqueConstraint("id", "platform_bank_id", name="uq_platform_bank_releases_id_bank"),
        sa.CheckConstraint(
            "version_number > 0", name="ck_platform_bank_releases_version_positive"
        ),
        sa.CheckConstraint(
            "question_count >= 0", name="ck_platform_bank_releases_count_non_negative"
        ),
    )
    op.create_index(
        "idx_platform_bank_releases_bank",
        "platform_bank_releases",
        ["platform_bank_id", "version_number"],
    )

    # ─── 个人题库来源标识 ─────────────────────────────────────────
    with op.batch_alter_table("question_banks") as batch:
        batch.add_column(sa.Column("source_platform_bank_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_platform_release_id", sa.String(36), nullable=True))
        batch.create_check_constraint(
            "ck_question_banks_source_pair",
            "(source_platform_bank_id IS NULL) = (source_platform_release_id IS NULL)",
        )
        batch.create_unique_constraint(
            "uq_question_banks_exam_platform_source", ["exam_id", "source_platform_bank_id"]
        )
        batch.create_foreign_key(
            "fk_question_banks_platform_bank",
            "platform_banks",
            ["source_platform_bank_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_question_banks_platform_release",
            "platform_bank_releases",
            ["source_platform_release_id", "source_platform_bank_id"],
            ["id", "platform_bank_id"],
            ondelete="RESTRICT",
        )

    op.add_column("questions", sa.Column("source_topics", JSONType, nullable=True))

    # ─── 导入双目标 ───────────────────────────────────────────────
    with op.batch_alter_table("import_jobs") as batch:
        batch.alter_column("bank_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("platform_bank_id", sa.String(36), nullable=True))
        batch.create_check_constraint(
            "ck_import_jobs_single_target",
            "(bank_id IS NULL) <> (platform_bank_id IS NULL)",
        )
        batch.create_foreign_key(
            "fk_import_jobs_platform_bank",
            "platform_banks",
            ["platform_bank_id"],
            ["id"],
        )
    op.create_index("idx_import_jobs_platform_bank_id", "import_jobs", ["platform_bank_id"])

    with op.batch_alter_table("import_parsed_questions") as batch:
        batch.add_column(
            sa.Column("imported_platform_question_id", sa.Integer(), nullable=True)
        )
        # server_default 不可省：存量个人行必须是 false，且不能为 NULL。
        batch.add_column(
            sa.Column(
                "inserted_new", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.create_check_constraint(
            "ck_import_parsed_questions_single_pointer",
            "NOT (imported_question_id IS NOT NULL AND imported_platform_question_id IS NOT NULL)",
        )
        batch.create_foreign_key(
            "fk_import_parsed_questions_platform_question",
            "platform_draft_questions",
            ["imported_platform_question_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "idx_import_parsed_questions_platform_question",
        "import_parsed_questions",
        ["imported_platform_question_id"],
    )

    # ─── 后台任务平台目标与可空作者 ────────────────────────────────
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column("created_by", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("platform_bank_id", sa.String(36), nullable=True))
        batch.create_check_constraint(
            "ck_background_jobs_platform_author",
            "platform_bank_id IS NOT NULL OR created_by IS NOT NULL",
        )
        batch.create_foreign_key(
            "fk_background_jobs_platform_bank",
            "platform_banks",
            ["platform_bank_id"],
            ["id"],
        )
    op.create_index(
        "idx_background_jobs_platform_bank",
        "background_jobs",
        ["platform_bank_id", "status"],
    )


def downgrade() -> None:
    if _has_platform_data():
        raise RuntimeError(
            "存在平台题库或副本数据，禁止破坏性降级：请先导出/清理平台数据，"
            "或使用前向修复。降级会删除发布快照并移除副本的只读来源保护。"
        )

    op.drop_index("idx_background_jobs_platform_bank", table_name="background_jobs")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("fk_background_jobs_platform_bank", type_="foreignkey")
        batch.drop_constraint("ck_background_jobs_platform_author", type_="check")
        batch.drop_column("platform_bank_id")
        batch.alter_column("created_by", existing_type=sa.Integer(), nullable=False)

    op.drop_index(
        "idx_import_parsed_questions_platform_question",
        table_name="import_parsed_questions",
    )
    with op.batch_alter_table("import_parsed_questions") as batch:
        batch.drop_constraint(
            "fk_import_parsed_questions_platform_question", type_="foreignkey"
        )
        batch.drop_constraint("ck_import_parsed_questions_single_pointer", type_="check")
        batch.drop_column("inserted_new")
        batch.drop_column("imported_platform_question_id")

    op.drop_index("idx_import_jobs_platform_bank_id", table_name="import_jobs")
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_constraint("fk_import_jobs_platform_bank", type_="foreignkey")
        batch.drop_constraint("ck_import_jobs_single_target", type_="check")
        batch.drop_column("platform_bank_id")
        batch.alter_column("bank_id", existing_type=sa.Integer(), nullable=False)

    op.drop_column("questions", "source_topics")

    with op.batch_alter_table("question_banks") as batch:
        batch.drop_constraint("fk_question_banks_platform_release", type_="foreignkey")
        batch.drop_constraint("fk_question_banks_platform_bank", type_="foreignkey")
        batch.drop_constraint("uq_question_banks_exam_platform_source", type_="unique")
        batch.drop_constraint("ck_question_banks_source_pair", type_="check")
        batch.drop_column("source_platform_release_id")
        batch.drop_column("source_platform_bank_id")

    op.drop_index("idx_platform_bank_releases_bank", table_name="platform_bank_releases")
    op.drop_table("platform_bank_releases")
    op.drop_index(
        "idx_platform_draft_questions_bank", table_name="platform_draft_questions"
    )
    op.drop_table("platform_draft_questions")
    op.drop_index("idx_platform_banks_listed", table_name="platform_banks")
    op.drop_table("platform_banks")
