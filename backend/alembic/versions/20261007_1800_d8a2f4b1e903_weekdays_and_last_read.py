"""weekdays frequency + threads.last_read_at

Revision ID: d8a2f4b1e903
Revises: c3f1a9e27d04
Create Date: 2026-10-07 18:00:00.000000+00:00

"weekdays" (Mon–Fri, IDX trading days) is 8 chars — frequency was
String(7). last_read_at drives the unread marker on scheduled threads.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd8a2f4b1e903'
down_revision: Union[str, None] = 'c3f1a9e27d04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('scheduled_jobs', 'frequency',
                    existing_type=sa.String(length=7),
                    type_=sa.String(length=16),
                    existing_nullable=False)
    op.add_column('threads', sa.Column('last_read_at',
                                       sa.DateTime(timezone=True),
                                       nullable=True))


def downgrade() -> None:
    op.drop_column('threads', 'last_read_at')
    op.alter_column('scheduled_jobs', 'frequency',
                    existing_type=sa.String(length=16),
                    type_=sa.String(length=7),
                    existing_nullable=False)
