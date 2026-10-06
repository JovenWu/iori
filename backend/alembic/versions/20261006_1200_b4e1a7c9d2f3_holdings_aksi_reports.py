"""holdings and aksi_reports

Revision ID: b4e1a7c9d2f3
Revises: d031417a4a27
Create Date: 2026-10-06 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b4e1a7c9d2f3'
down_revision: Union[str, None] = 'd031417a4a27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('holdings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=4), nullable=False),
    sa.Column('shares', sa.BigInteger(), nullable=False),
    sa.Column('avg_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'symbol', name='uq_holdings_user_symbol')
    )
    op.create_index(op.f('ix_holdings_user_id'), 'holdings', ['user_id'], unique=False)
    op.create_table('aksi_reports',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('holdings_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('events', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('credits_spent', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_aksi_reports_user_created', 'aksi_reports', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_aksi_reports_user_created', table_name='aksi_reports')
    op.drop_table('aksi_reports')
    op.drop_index(op.f('ix_holdings_user_id'), table_name='holdings')
    op.drop_table('holdings')
