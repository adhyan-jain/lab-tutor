"""add login_sessions

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-09-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'login_sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('classroom_id', sa.String(length=36), nullable=True),
        sa.Column('login_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('logout_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_reason', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['classroom_id'], ['classrooms.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_login_sessions_user_id'), 'login_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_login_sessions_classroom_id'), 'login_sessions', ['classroom_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_login_sessions_classroom_id'), table_name='login_sessions')
    op.drop_index(op.f('ix_login_sessions_user_id'), table_name='login_sessions')
    op.drop_table('login_sessions')
