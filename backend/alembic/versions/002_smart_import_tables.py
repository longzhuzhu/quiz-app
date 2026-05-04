"""002_smart_import_tables

Revision ID: 002
Revises: 001
Create Date: 2026-05-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- import_jobs ---
    op.create_table(
        'import_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bank_id', sa.Integer(), nullable=False),
        sa.Column('background_job_id', sa.Integer(), nullable=True),
        sa.Column('file_name', sa.String(length=300), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('file_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('total_pages', sa.Integer(), nullable=False),
        sa.Column('total_chunks', sa.Integer(), nullable=False),
        sa.Column('parsed_questions', sa.Integer(), nullable=False),
        sa.Column('imported_questions', sa.Integer(), nullable=False),
        sa.Column('review_questions', sa.Integer(), nullable=False),
        sa.Column('failed_chunks', sa.Integer(), nullable=False),
        sa.Column('config_json', postgresql.JSONB(), nullable=True),
        sa.Column('summary_json', postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['bank_id'], ['question_banks.id']),
        sa.ForeignKeyConstraint(['background_job_id'], ['background_jobs.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_import_jobs_bank_id', 'import_jobs', ['bank_id'])
    op.create_index('idx_import_jobs_status', 'import_jobs', ['status'])
    op.create_index('idx_import_jobs_file_hash', 'import_jobs', ['file_hash'])

    # --- import_chunks ---
    op.create_table(
        'import_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('import_job_id', sa.Integer(), nullable=False),
        sa.Column('chunk_no', sa.Integer(), nullable=False),
        sa.Column('start_page', sa.Integer(), nullable=True),
        sa.Column('end_page', sa.Integer(), nullable=True),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('normalized_text', sa.Text(), nullable=True),
        sa.Column('chunk_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('llm_request_json', postgresql.JSONB(), nullable=True),
        sa.Column('llm_response_json', postgresql.JSONB(), nullable=True),
        sa.Column('issues_json', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['import_job_id'], ['import_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_import_chunks_job_id', 'import_chunks', ['import_job_id'])
    op.create_index('idx_import_chunks_status', 'import_chunks', ['status'])
    op.create_index('idx_import_chunks_hash', 'import_chunks', ['chunk_hash'])

    # --- import_parsed_questions ---
    op.create_table(
        'import_parsed_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('import_job_id', sa.Integer(), nullable=False),
        sa.Column('chunk_id', sa.Integer(), nullable=True),
        sa.Column('source_question_no', sa.String(length=64), nullable=True),
        sa.Column('question_type', sa.String(length=32), nullable=True),
        sa.Column('scenario_text', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('options_json', postgresql.JSONB(), nullable=False),
        sa.Column('correct_answer', postgresql.JSONB(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('references_json', postgresql.JSONB(), nullable=True),
        sa.Column('source_evidence_json', postgresql.JSONB(), nullable=True),
        sa.Column('llm_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('final_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('issues_json', postgresql.JSONB(), nullable=True),
        sa.Column('duplicate_json', postgresql.JSONB(), nullable=True),
        sa.Column('review_status', sa.String(length=32), nullable=False),
        sa.Column('import_status', sa.String(length=32), nullable=False),
        sa.Column('imported_question_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['import_job_id'], ['import_jobs.id']),
        sa.ForeignKeyConstraint(['chunk_id'], ['import_chunks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_import_parsed_questions_job_id', 'import_parsed_questions', ['import_job_id'])
    op.create_index('idx_import_parsed_questions_review_status', 'import_parsed_questions', ['review_status'])
    op.create_index('idx_import_parsed_questions_import_status', 'import_parsed_questions', ['import_status'])

    # --- import_review_items ---
    op.create_table(
        'import_review_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('import_job_id', sa.Integer(), nullable=False),
        sa.Column('parsed_question_id', sa.Integer(), nullable=False),
        sa.Column('review_type', sa.String(length=64), nullable=True),
        sa.Column('severity', sa.String(length=32), nullable=True),
        sa.Column('before_json', postgresql.JSONB(), nullable=True),
        sa.Column('after_json', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('reviewer_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['import_job_id'], ['import_jobs.id']),
        sa.ForeignKeyConstraint(['parsed_question_id'], ['import_parsed_questions.id']),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- llm_parse_cache ---
    op.create_table(
        'llm_parse_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(length=64), nullable=False),
        sa.Column('model_name', sa.String(length=128), nullable=True),
        sa.Column('prompt_version', sa.String(length=64), nullable=True),
        sa.Column('chunk_hash', sa.String(length=64), nullable=True),
        sa.Column('request_json', postgresql.JSONB(), nullable=True),
        sa.Column('response_json', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cache_key'),
    )
    op.create_index('idx_llm_parse_cache_chunk_hash', 'llm_parse_cache', ['chunk_hash'])

    # --- vector_index (Phase 3 预留，本阶段不含 pgvector) ---
    op.create_table(
        'vector_index',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vector_type', sa.String(length=64), nullable=False),
        sa.Column('ref_id', sa.String(length=128), nullable=False),
        sa.Column('bank_id', sa.Integer(), nullable=True),
        sa.Column('text_content', sa.Text(), nullable=False),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['bank_id'], ['question_banks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_vector_index_type', 'vector_index', ['vector_type'])
    op.create_index('idx_vector_index_bank_id', 'vector_index', ['bank_id'])


def downgrade() -> None:
    op.drop_table('vector_index')
    op.drop_table('llm_parse_cache')
    op.drop_table('import_review_items')
    op.drop_index('idx_import_parsed_questions_import_status', table_name='import_parsed_questions')
    op.drop_index('idx_import_parsed_questions_review_status', table_name='import_parsed_questions')
    op.drop_index('idx_import_parsed_questions_job_id', table_name='import_parsed_questions')
    op.drop_table('import_parsed_questions')
    op.drop_index('idx_import_chunks_hash', table_name='import_chunks')
    op.drop_index('idx_import_chunks_status', table_name='import_chunks')
    op.drop_index('idx_import_chunks_job_id', table_name='import_chunks')
    op.drop_table('import_chunks')
    op.drop_index('idx_import_jobs_file_hash', table_name='import_jobs')
    op.drop_index('idx_import_jobs_status', table_name='import_jobs')
    op.drop_index('idx_import_jobs_bank_id', table_name='import_jobs')
    op.drop_table('import_jobs')
