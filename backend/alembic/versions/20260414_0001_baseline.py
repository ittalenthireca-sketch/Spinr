"""baseline — spinr adopts alembic

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-14 00:00:00.000000+00:00

This is the empty baseline revision that marks the point in history
at which the spinr backend adopted Alembic.

Context
-------
The existing production schema is authored and applied by the raw-SQL
migrations under backend/migrations/*.sql, driven by
backend/scripts/run_migrations.py. Those files remain the immutable
source of truth for the schema as it existed on the cutover date;
editing them is explicitly forbidden (the runner checksums every
file and refuses to re-apply a changed migration).

Going forward, every NEW schema change is an Alembic revision that
descends from this baseline. See backend/alembic/README.md for the
cutover workflow, including the one-time
``alembic stamp 0001_baseline`` step operators run against every
existing environment (prod, staging, CI, dev) to tell Alembic
"everything up to the baseline is already applied; resume from here."

Why the revision is empty
-------------------------
* Backfilling the entire 24-file legacy schema into a single Alembic
  revision would either (a) diverge from what's actually in the
  database (schema-capture bugs) or (b) fail to apply idempotently
  to already-migrated environments. Stamping the baseline avoids
  both failure modes.
* spinr has no SQLAlchemy models, so autogenerate produces no diff.
  An empty baseline is honest about that.
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — schema up to the cutover lives in backend/migrations/*.sql."""
    pass


def downgrade() -> None:
    """No-op — we do not support unwinding past the cutover point."""
    pass
