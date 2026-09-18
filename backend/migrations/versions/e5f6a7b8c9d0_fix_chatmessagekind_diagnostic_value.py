"""fix chatmessagekind missing DIAGNOSTIC value

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-09-18 07:30:00.000000

Found live in production: a1b2c3d4e5f6_add_chat_threads_and_metadata.py's
batch_op.alter_column(type_=sa.Enum('SOCRATIC', 'QA', 'DIAGNOSTIC', ...))
is a no-op against a real Postgres native enum type -- Alembic's batch
mode is a SQLite recreate-table strategy; it never emitted the
`ALTER TYPE chatmessagekind ADD VALUE` Postgres actually needs. On
SQLite (the whole test suite) Enum columns are just a VARCHAR with no
native type to widen, so this was invisible there. On the real Cloud
SQL database, the ChatMessage.kind column's Postgres enum type was
silently left at ('SOCRATIC', 'QA') only, and any attempt to insert a
DIAGNOSTIC-kind chat message -- i.e. every real diagnostic submission
made through the unified chat endpoint -- failed with
`InvalidTextRepresentation` at commit time. `alembic check` did not
catch this either: Alembic's autogenerate diffing does not compare
native enum value sets by default.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Must run outside an implicit transaction on older Postgres, and the
    # new value cannot be referenced in the same transaction it's added
    # in on any version -- this migration only alters the type, so that
    # restriction doesn't apply here. IF NOT EXISTS makes this safe to
    # re-run against an environment where the value already exists.
    op.execute("ALTER TYPE chatmessagekind ADD VALUE IF NOT EXISTS 'DIAGNOSTIC'")


def downgrade() -> None:
    # Postgres cannot drop a single value from a native enum type without
    # recreating the type and rewriting every dependent column -- not
    # attempted here. This migration is intentionally one-way.
    pass
