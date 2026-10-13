"""每模型最新解析、任务优先级与题目关联；不猜测历史解析来源。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("background_jobs", sa.Column("subject_question_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_background_jobs_subject_question", "background_jobs", "questions", ["subject_question_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_background_jobs_subject_question_id", "background_jobs", ["subject_question_id"])
    op.create_table("question_explanations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("judged_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("explanation_zh", sa.Text(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(), nullable=False),
        sa.Column("generation_id", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("question_id", "model_id", name="uq_question_explanations_model"),
    )
    op.create_index("ix_question_explanations_question_id", "question_explanations", ["question_id"])
    op.execute("UPDATE background_jobs SET status='failed', active_scope_key=NULL, lease_until=NULL, finished_at=NOW(), last_error='解析已升级，请手动重新解析', status_message='旧解析任务已终结' WHERE job_type='ai_prewarm' AND status IN ('queued','running') AND payload_json::jsonb->>'artifact_type'='explanation'")


def downgrade() -> None:
    op.execute("UPDATE background_jobs SET status='failed', active_scope_key=NULL, lease_until=NULL WHERE job_type='ai_explanation' AND status IN ('queued','running')")
    op.drop_table("question_explanations")
    op.drop_index("ix_background_jobs_subject_question_id", table_name="background_jobs")
    op.drop_constraint("fk_background_jobs_subject_question", "background_jobs", type_="foreignkey")
    op.drop_column("background_jobs", "subject_question_id")
    op.drop_column("background_jobs", "priority")
