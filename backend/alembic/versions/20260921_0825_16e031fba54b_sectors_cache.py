"""sectors_cache

Revision ID: 16e031fba54b
Revises: 93a005eb04c2
Create Date: 2026-09-21 08:25:53.711510+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '16e031fba54b'
down_revision: Union[str, None] = '93a005eb04c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sectors_cache',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('endpoint', sa.String(length=128), nullable=False),
    sa.Column('freshness', sa.String(length=16), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('credits', sa.Integer(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sectors_cache_endpoint'), 'sectors_cache', ['endpoint'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sectors_cache_endpoint'), table_name='sectors_cache')
    op.drop_table('sectors_cache')
