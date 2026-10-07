"""credit_budget singleton + users.hashed_password

Revision ID: e7f1b4c9a2d6
Revises: d8a2f4b1e903
Create Date: 2026-10-07 21:00:00.000000+00:00

The credit counter is seeded from existing sectors_cache rows — each entry's
`credits` is the upstream cost already paid for it, so the budget starts from
real historical spend rather than zero. hashed_password is nullable: the
env-provisioned account keeps its env-credential auth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7f1b4c9a2d6'
down_revision: Union[str, None] = 'd8a2f4b1e903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'credit_budget',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spent', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute(
        "INSERT INTO credit_budget (id, spent) "
        "SELECT 1, COALESCE(SUM(credits), 0) FROM sectors_cache"
    )
    op.add_column('users', sa.Column('hashed_password', sa.String(),
                                     nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'hashed_password')
    op.drop_table('credit_budget')
