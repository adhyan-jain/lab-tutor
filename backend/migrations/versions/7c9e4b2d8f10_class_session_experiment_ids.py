"""class_sessions.experiment_ids: allow several experiments per session

Revision ID: 7c9e4b2d8f10
Revises: d6e7f8a9b0c1
Create Date: 2026-10-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c9e4b2d8f10'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: existing sessions keep meaning "just experiment_id".
    op.add_column('class_sessions', sa.Column('experiment_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('class_sessions', 'experiment_ids')
