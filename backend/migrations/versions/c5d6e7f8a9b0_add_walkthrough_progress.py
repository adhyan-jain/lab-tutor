"""add walkthrough_progress

Per-student state for guided walkthroughs (Exp7 first): current step,
attempts, the values the student reported, curiosity-hook guesses and
checkpoint history, as controller JSON.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _actor_type():
    # The Postgres type already exists (created by the baseline schema);
    # on other dialects this falls back to a plain enum.
    return sa.Enum(
        'STUDENT', 'FACULTY_TEST', 'ADMIN_TEST', name='actortype'
    ).with_variant(
        postgresql.ENUM('STUDENT', 'FACULTY_TEST', 'ADMIN_TEST', name='actortype', create_type=False),
        'postgresql',
    )


def upgrade() -> None:
    op.create_table(
        'walkthrough_progress',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('classroom_id', sa.String(length=36), nullable=False),
        sa.Column('class_session_id', sa.String(length=36), nullable=True),
        sa.Column('experiment_id', sa.String(length=64), nullable=False),
        sa.Column('actor_type', _actor_type(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id']),
        sa.ForeignKeyConstraint(['classroom_id'], ['classrooms.id']),
        sa.ForeignKeyConstraint(['class_session_id'], ['class_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'student_id', 'classroom_id', 'experiment_id', 'actor_type', name='uq_walkthrough_scope'
        ),
    )
    op.create_index(op.f('ix_walkthrough_progress_student_id'), 'walkthrough_progress', ['student_id'])
    op.create_index(op.f('ix_walkthrough_progress_classroom_id'), 'walkthrough_progress', ['classroom_id'])
    op.create_index(op.f('ix_walkthrough_progress_class_session_id'), 'walkthrough_progress', ['class_session_id'])
    op.create_index(op.f('ix_walkthrough_progress_experiment_id'), 'walkthrough_progress', ['experiment_id'])
    op.create_index(op.f('ix_walkthrough_progress_actor_type'), 'walkthrough_progress', ['actor_type'])


def downgrade() -> None:
    op.drop_index(op.f('ix_walkthrough_progress_actor_type'), table_name='walkthrough_progress')
    op.drop_index(op.f('ix_walkthrough_progress_experiment_id'), table_name='walkthrough_progress')
    op.drop_index(op.f('ix_walkthrough_progress_class_session_id'), table_name='walkthrough_progress')
    op.drop_index(op.f('ix_walkthrough_progress_classroom_id'), table_name='walkthrough_progress')
    op.drop_index(op.f('ix_walkthrough_progress_student_id'), table_name='walkthrough_progress')
    op.drop_table('walkthrough_progress')
