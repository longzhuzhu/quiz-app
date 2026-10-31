"""user owned exams

Revision ID: 003
Revises: 002
Create Date: 2026-05-24 00:00:00.000000

PostgreSQL 分支保持原有数据归属语义不变：必须已有指定管理员，且将存量题库/词汇
迁移到该管理员的 CIPT 项目。SQLite 是全新部署，没有历史归属数据；只有数据库确实
为空时才走 schema-only 路径，非空库仍执行同样的 owner 校验，不能为通过迁移随意
挑选第一个用户。
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, text
from sqlalchemy.dialects.postgresql import JSONB

# 迁移文件保持自包含：不导入会随应用演进的模型或默认常量。
JSONType = JSON().with_variant(JSONB(), "postgresql")

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MIGRATION_OWNER_USERNAME = "nianyu"
CIPT_AI_PROFILE = {
    "translation_system_prompt": (
        "你是一位专业的隐私技术领域翻译专家。请将以下 CIPT 考试题目从英文翻译为中文。"
        "保留技术缩写（如 GDPR、PII、DPO、DPIA 等）不翻译。"
        '返回 JSON 格式：{"content_zh": "中文题目", "options_zh": [{"key": "A", "text_zh": "中文选项"}, ...]}'
        "只返回 JSON，不要其他内容。"
    ),
    "explanation_system_prompt": (
        "你是一位 CIPT（认证信息隐私技术师）考试辅导专家。"
        "请解析以下题目，说明正确答案的原因以及其他选项为什么不正确。"
        '返回 JSON 格式：{"explanation": "英文解析", "explanation_zh": "中文解析"}'
        "只返回 JSON，不要其他内容。"
    ),
    "vocab_extract_system_prompt": "从下列题目中识别专业术语。",
    "source_lang": "en",
    "target_lang": "zh-CN",
    "model_override": None,
    "enabled_features": ["translate", "explain", "vocab_extract"],
}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _owner_row():
    return op.get_bind().execute(
        sa.text("SELECT id, is_admin FROM users WHERE username = :username"),
        {"username": MIGRATION_OWNER_USERNAME},
    ).mappings().first()


def _require_owner(owner):
    if owner is None:
        raise RuntimeError("Migration owner username 'nianyu' does not exist; create the admin user before running migration 003.")
    if not owner["is_admin"]:
        raise RuntimeError("Migration owner username 'nianyu' is not an admin; update the migration owner before running migration 003.")


def _has_legacy_rows() -> bool:
    bind = op.get_bind()
    for table in ("question_banks", "vocabularies"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            return True
    return False


def _create_exams_table() -> None:
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("short_name", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("locale", sa.String(length=10), nullable=False, server_default="en-US"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("importer_profile", sa.String(length=50), nullable=False, server_default="examtopics-pdf"),
        sa.Column(
            "ai_profile",
            JSONType,
            nullable=False,
            server_default=text("'{}'::jsonb") if not _is_sqlite() else text("'{}'"),
        ),
        sa.Column(
            "quiz_profile",
            JSONType,
            nullable=False,
            server_default=text("'{}'::jsonb") if not _is_sqlite() else text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_exams_owner_id_users"),
        sa.UniqueConstraint("owner_id", "slug", name="uq_exams_owner_slug"),
    )
    op.create_index("ix_exams_owner_sort", "exams", ["owner_id", "sort_order"], unique=False)


def _insert_cipt_exam(owner_id: int) -> int:
    profile = json.dumps(CIPT_AI_PROFILE, ensure_ascii=False)
    if _is_sqlite():
        return op.get_bind().execute(
            sa.text(
                """
                INSERT INTO exams (owner_id, slug, name, short_name, description, icon, locale,
                                   sort_order, importer_profile, ai_profile, quiz_profile)
                VALUES (:owner_id, 'cipt', 'CIPT 认证信息隐私技术师', 'CIPT', '存量 CIPT 题库迁移项目',
                        'ShieldCheck', 'en-US', 0, 'examtopics-pdf', :ai_profile, '{}')
                RETURNING id
                """
            ),
            {"owner_id": owner_id, "ai_profile": profile},
        ).scalar_one()
    return op.get_bind().execute(
        sa.text(
            """
            INSERT INTO exams (owner_id, slug, name, short_name, description, icon, locale, sort_order, importer_profile, ai_profile, quiz_profile)
            VALUES (:owner_id, 'cipt', 'CIPT 认证信息隐私技术师', 'CIPT', '存量 CIPT 题库迁移项目', 'ShieldCheck', 'en-US', 0, 'examtopics-pdf', CAST(:ai_profile AS jsonb), '{}'::jsonb)
            RETURNING id
            """
        ),
        {"owner_id": owner_id, "ai_profile": profile},
    ).scalar_one()


def _add_exam_columns_sqlite(cipt_exam_id: int | None, owner_id: int | None) -> None:
    """SQLite 需要用 batch 重建来添加非空列与外键。

    先加可空列并回填，再收紧为非空；空库与非空旧库共用同一条安全路径。
    """
    bind = op.get_bind()
    with op.batch_alter_table("question_banks") as batch:
        batch.add_column(sa.Column("exam_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_question_banks_exam_id_exams", "exams", ["exam_id"], ["id"])
    with op.batch_alter_table("vocabularies") as batch:
        batch.add_column(sa.Column("exam_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_vocabularies_exam_id_exams", "exams", ["exam_id"], ["id"])
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("active_exam_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_users_active_exam_id_exams", "exams", ["active_exam_id"], ["id"])
    if cipt_exam_id is not None:
        bind.execute(sa.text("UPDATE question_banks SET exam_id = :exam_id"), {"exam_id": cipt_exam_id})
        bind.execute(
            sa.text(
                """
                UPDATE vocabularies
                SET user_id = :owner_id, exam_id = :exam_id, is_system = false
                WHERE is_system = true
                """
            ),
            {"owner_id": owner_id, "exam_id": cipt_exam_id},
        )
        bind.execute(
            sa.text("UPDATE users SET active_exam_id = :exam_id WHERE id = :owner_id"),
            {"exam_id": cipt_exam_id, "owner_id": owner_id},
        )
    with op.batch_alter_table("question_banks") as batch:
        batch.alter_column("exam_id", existing_type=sa.Integer(), nullable=False)
    op.create_index(op.f("ix_question_banks_exam_id"), "question_banks", ["exam_id"], unique=False)
    op.create_index(op.f("ix_vocabularies_exam_id"), "vocabularies", ["exam_id"], unique=False)
    op.create_index("idx_wrong_answers_user_question", "wrong_answers", ["user_id", "question_id"], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = _is_sqlite()
    owner = None
    if not (sqlite and not _has_legacy_rows()):
        owner = _owner_row()
        _require_owner(owner)

    _create_exams_table()
    cipt_exam_id = _insert_cipt_exam(owner["id"]) if owner is not None else None

    if sqlite:
        _add_exam_columns_sqlite(cipt_exam_id, owner["id"] if owner else None)
        return

    op.add_column("question_banks", sa.Column("exam_id", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE question_banks SET exam_id = :exam_id").bindparams(exam_id=cipt_exam_id))
    op.alter_column("question_banks", "exam_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("fk_question_banks_exam_id_exams", "question_banks", "exams", ["exam_id"], ["id"])
    op.create_index(op.f("ix_question_banks_exam_id"), "question_banks", ["exam_id"], unique=False)

    op.add_column("vocabularies", sa.Column("exam_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE vocabularies
            SET user_id = :owner_id, exam_id = :exam_id, is_system = false
            WHERE is_system = true
            """
        ).bindparams(owner_id=owner["id"], exam_id=cipt_exam_id)
    )
    op.create_foreign_key("fk_vocabularies_exam_id_exams", "vocabularies", "exams", ["exam_id"], ["id"])
    op.create_index(op.f("ix_vocabularies_exam_id"), "vocabularies", ["exam_id"], unique=False)

    op.add_column("users", sa.Column("active_exam_id", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE users SET active_exam_id = :exam_id WHERE id = :owner_id").bindparams(exam_id=cipt_exam_id, owner_id=owner["id"]))
    op.create_foreign_key("fk_users_active_exam_id_exams", "users", "exams", ["active_exam_id"], ["id"])

    op.create_index("idx_wrong_answers_user_question", "wrong_answers", ["user_id", "question_id"], unique=False)


def downgrade() -> None:
    if _is_sqlite():
        op.drop_index("idx_wrong_answers_user_question", table_name="wrong_answers")
        with op.batch_alter_table("users") as batch:
            batch.drop_constraint("fk_users_active_exam_id_exams", type_="foreignkey")
            batch.drop_column("active_exam_id")
        op.drop_index(op.f("ix_vocabularies_exam_id"), table_name="vocabularies")
        with op.batch_alter_table("vocabularies") as batch:
            batch.drop_constraint("fk_vocabularies_exam_id_exams", type_="foreignkey")
            batch.drop_column("exam_id")
        op.drop_index(op.f("ix_question_banks_exam_id"), table_name="question_banks")
        with op.batch_alter_table("question_banks") as batch:
            batch.drop_constraint("fk_question_banks_exam_id_exams", type_="foreignkey")
            batch.drop_column("exam_id")
        op.drop_index("ix_exams_owner_sort", table_name="exams")
        op.drop_table("exams")
        return

    op.drop_index("idx_wrong_answers_user_question", table_name="wrong_answers")
    op.drop_constraint("fk_users_active_exam_id_exams", "users", type_="foreignkey")
    op.drop_column("users", "active_exam_id")

    op.drop_index(op.f("ix_vocabularies_exam_id"), table_name="vocabularies")
    op.drop_constraint("fk_vocabularies_exam_id_exams", "vocabularies", type_="foreignkey")
    op.drop_column("vocabularies", "exam_id")

    op.drop_index(op.f("ix_question_banks_exam_id"), table_name="question_banks")
    op.drop_constraint("fk_question_banks_exam_id_exams", "question_banks", type_="foreignkey")
    op.drop_column("question_banks", "exam_id")

    op.drop_index("ix_exams_owner_sort", table_name="exams")
    op.drop_table("exams")
