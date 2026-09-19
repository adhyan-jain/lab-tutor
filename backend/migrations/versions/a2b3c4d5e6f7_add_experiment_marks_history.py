"""add experiment_marks_history

Revision ID: a2b3c4d5e6f7
Revises: f7a8b9c0d1e2
Create Date: 2026-09-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'experiment_marks_history',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('classroom_id', sa.String(length=36), nullable=False),
        sa.Column('experiment_id', sa.String(length=64), nullable=False),
        sa.Column('pre_test_marks', sa.Float(), nullable=True),
        sa.Column('pre_test_max', sa.Float(), nullable=False),
        sa.Column('post_test_marks', sa.Float(), nullable=True),
        sa.Column('post_test_max', sa.Float(), nullable=False),
        sa.Column('entered_by', sa.String(length=36), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['classroom_id'], ['classrooms.id'], ),
        sa.ForeignKeyConstraint(['entered_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_experiment_marks_history_student_id'), 'experiment_marks_history', ['student_id'], unique=False)
    op.create_index(op.f('ix_experiment_marks_history_classroom_id'), 'experiment_marks_history', ['classroom_id'], unique=False)
    op.create_index(op.f('ix_experiment_marks_history_experiment_id'), 'experiment_marks_history', ['experiment_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_experiment_marks_history_experiment_id'), table_name='experiment_marks_history')
    op.drop_index(op.f('ix_experiment_marks_history_classroom_id'), table_name='experiment_marks_history')
    op.drop_index(op.f('ix_experiment_marks_history_student_id'), table_name='experiment_marks_history')
    op.drop_table('experiment_marks_history')
