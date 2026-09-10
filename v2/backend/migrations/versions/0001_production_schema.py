"""Create the production schema."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users', sa.Column('id', sa.String(32), primary_key=True), sa.Column('email', sa.String(320), nullable=False, unique=True), sa.Column('password_hash', sa.Text(), nullable=False), sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('sessions', sa.Column('id', sa.String(32), primary_key=True), sa.Column('user_id', sa.String(32), sa.ForeignKey('users.id'), nullable=False), sa.Column('token_hash', sa.String(64), nullable=False, unique=True), sa.Column('expires_at', sa.String(40), nullable=False), sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('projects', sa.Column('id', sa.String(32), primary_key=True), sa.Column('user_id', sa.String(32), sa.ForeignKey('users.id')), sa.Column('title', sa.String(120), nullable=False), sa.Column('idea', sa.Text(), nullable=False), sa.Column('constraints_text', sa.Text(), nullable=False), sa.Column('mode', sa.String(10), nullable=False), sa.Column('decision', sa.String(10)), sa.Column('created_at', sa.String(40), nullable=False), sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_projects_user_id', 'projects', ['user_id'])
    op.create_table('artifacts', sa.Column('id', sa.String(32), primary_key=True), sa.Column('project_id', sa.String(32), sa.ForeignKey('projects.id'), nullable=False), sa.Column('stage', sa.String(20), nullable=False), sa.Column('version', sa.Integer(), nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('metadata', sa.Text(), nullable=False), sa.Column('valid', sa.Integer(), nullable=False), sa.Column('approved_at', sa.String(40)), sa.Column('decision', sa.String(10)), sa.Column('created_at', sa.String(40), nullable=False), sa.UniqueConstraint('project_id', 'stage', 'version'))
    op.create_index('ix_artifacts_project_id', 'artifacts', ['project_id'])
    op.create_table('runs', sa.Column('id', sa.String(32), primary_key=True), sa.Column('project_id', sa.String(32), sa.ForeignKey('projects.id'), nullable=False), sa.Column('stage', sa.String(20), nullable=False), sa.Column('status', sa.String(20), nullable=False), sa.Column('feedback', sa.Text(), nullable=False), sa.Column('error', sa.Text()), sa.Column('artifact_id', sa.String(32), sa.ForeignKey('artifacts.id')), sa.Column('created_at', sa.String(40), nullable=False), sa.Column('finished_at', sa.String(40)))
    op.create_index('ix_runs_project_id', 'runs', ['project_id'])
    op.create_index('one_running_per_project', 'runs', ['project_id'], unique=True, postgresql_where=sa.text("status='running'"), sqlite_where=sa.text("status='running'"))


def downgrade():
    op.drop_table('runs'); op.drop_table('artifacts'); op.drop_table('projects'); op.drop_table('sessions'); op.drop_table('users')
