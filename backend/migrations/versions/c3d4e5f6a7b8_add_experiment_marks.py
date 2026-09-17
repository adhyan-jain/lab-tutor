"""add experiment_marks

Revision ID: c3d4e5f6a7b8
Revises: b095d8d1a05a
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b095d8d1a05a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'experiment_marks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('classroom_id', sa.String(length=36), nullable=False),
        sa.Column('experiment_id', sa.String(length=64), nullable=False),
        sa.Column('pre_test_marks', sa.Float(), nullable=True),
        sa.Column('pre_test_max', sa.Float(), nullable=False),
        sa.Column('post_test_marks', sa.Float(), nullable=True),
        sa.Column('post_test_max', sa.Float(), nullable=False),
        sa.Column('entered_by', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['classroom_id'], ['classrooms.id'], ),
        sa.ForeignKeyConstraint(['entered_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'classroom_id', 'experiment_id', name='uq_experiment_marks'),
    )
    op.create_index(op.f('ix_experiment_marks_student_id'), 'experiment_marks', ['student_id'], unique=False)
    op.create_index(op.f('ix_experiment_marks_classroom_id'), 'experiment_marks', ['classroom_id'], unique=False)
    op.create_index(op.f('ix_experiment_marks_experiment_id'), 'experiment_marks', ['experiment_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_experiment_marks_experiment_id'), table_name='experiment_marks')
    op.drop_index(op.f('ix_experiment_marks_classroom_id'), table_name='experiment_marks')
    op.drop_index(op.f('ix_experiment_marks_student_id'), table_name='experiment_marks')
    op.drop_table('experiment_marks')
