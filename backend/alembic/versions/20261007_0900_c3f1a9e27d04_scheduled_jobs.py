"""scheduled_jobs

Revision ID: c3f1a9e27d04
Revises: b4e1a7c9d2f3
Create Date: 2026-10-07 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3f1a9e27d04'
down_revision: Union[str, None] = 'b4e1a7c9d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scheduled_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('frequency', sa.String(length=7), nullable=False),
    sa.Column('run_time', sa.Time(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=True),
    sa.Column('day_of_month', sa.SmallInteger(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('thread_id', sa.UUID(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id', name='uq_scheduled_jobs_thread_id')
    )
    op.create_index(op.f('ix_scheduled_jobs_user_id'), 'scheduled_jobs',
                    ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scheduled_jobs_user_id'), table_name='scheduled_jobs')
    op.drop_table('scheduled_jobs')
