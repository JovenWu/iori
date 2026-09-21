"""threads starred

Revision ID: d031417a4a27
Revises: 16e031fba54b
Create Date: 2026-09-22 00:20:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd031417a4a27'
down_revision: Union[str, None] = '16e031fba54b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'threads',
        sa.Column('starred', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('threads', 'starred')
