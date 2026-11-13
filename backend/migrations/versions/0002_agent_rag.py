"""Add RAG documents, chunks, and agent run steps."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'documents',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('project_id', sa.String(32), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('embedded', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_index('ix_documents_project_id', 'documents', ['project_id'])
    op.create_table(
        'chunks',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('document_id', sa.String(32), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('project_id', sa.String(32), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('location', sa.String(400), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', sa.Text()))
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'])
    op.create_index('ix_chunks_project_id', 'chunks', ['project_id'])
    op.create_table(
        'run_steps',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('run_id', sa.String(32), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('tokens', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_index('ix_run_steps_run_id', 'run_steps', ['run_id'])


def downgrade():
    op.drop_table('run_steps')
    op.drop_table('chunks')
    op.drop_table('documents')
