"""add classrooms.archived_at

"Deleting" a class archives it (hidden, not joinable/startable, data kept).

Revision ID: b4c5d6e7f8a9
Revises: a2b3c4d5e6f7
Create Date: 2026-09-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('classrooms', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_classrooms_archived_at'), 'classrooms', ['archived_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_classrooms_archived_at'), table_name='classrooms')
    op.drop_column('classrooms', 'archived_at')
