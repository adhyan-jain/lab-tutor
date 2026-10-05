"""scope conversation and walkthrough state by chat thread

A new chat used to pick up the previous chat's guided walkthrough, because
walkthrough_progress was keyed per (student, classroom, experiment,
actor_type). It is now keyed per chat thread, and chat_threads gains a JSON
`state` column for the thread's conversation mode (initial / theory /
practice). Existing rows keep thread_id NULL: they are never auto-resumed,
only offered through "Resume previous session".

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_threads', sa.Column('state', sa.JSON(), nullable=True))
    with op.batch_alter_table('walkthrough_progress') as batch:
        batch.add_column(sa.Column('thread_id', sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            'fk_walkthrough_progress_thread_id', 'chat_threads', ['thread_id'], ['id'], ondelete='CASCADE'
        )
        batch.drop_constraint('uq_walkthrough_scope', type_='unique')
        batch.create_unique_constraint('uq_walkthrough_thread', ['thread_id'])
    op.create_index(op.f('ix_walkthrough_progress_thread_id'), 'walkthrough_progress', ['thread_id'])


def downgrade() -> None:
    # Downgrading keeps only the most recent row per old scope, since the
    # old unique key allowed one.
    op.execute(
        """
        DELETE FROM walkthrough_progress w
        USING walkthrough_progress newer
        WHERE w.student_id = newer.student_id
          AND w.classroom_id = newer.classroom_id
          AND w.experiment_id = newer.experiment_id
          AND w.actor_type = newer.actor_type
          AND w.updated_at < newer.updated_at
        """
    )
    op.drop_index(op.f('ix_walkthrough_progress_thread_id'), table_name='walkthrough_progress')
    with op.batch_alter_table('walkthrough_progress') as batch:
        batch.drop_constraint('uq_walkthrough_thread', type_='unique')
        batch.create_unique_constraint(
            'uq_walkthrough_scope', ['student_id', 'classroom_id', 'experiment_id', 'actor_type']
        )
        batch.drop_constraint('fk_walkthrough_progress_thread_id', type_='foreignkey')
        batch.drop_column('thread_id')
    op.drop_column('chat_threads', 'state')
