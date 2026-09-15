"""Durable V3 jobs. Official checkpointers manage their own checkpoint schema."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('graph_jobs',
        sa.Column('run_id', sa.String(32), sa.ForeignKey('runs.id'), primary_key=True),
        sa.Column('graph_version', sa.String(20), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('snapshot', sa.Text(), nullable=False),
        sa.Column('result', sa.Text()),
        sa.Column('call_started', sa.Integer(), nullable=False),
        sa.Column('approval', sa.Text()),
        sa.Column('lease_token', sa.String(32)),
        sa.Column('lease_until', sa.String(40)),
        sa.Column('updated_at', sa.String(40), nullable=False))


def downgrade():
    op.drop_table('graph_jobs')
