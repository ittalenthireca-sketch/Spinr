"""bg_task_heartbeat table for worker liveness

Revision ID: 0005_bg_task_heartbeat
Revises: 0004_stripe_event_queue_columns
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 1.6 of the production-readiness audit (roadmap row 1.6, audit
finding T15).

The shallow ``GET /health`` probe and the deep ``GET /health/deep``
probe cover API-side dependencies (DB reachability). Neither catches
the case where the worker process is running but one of its inner
loops has silently wedged (deadlock, unhandled exception in a coro
that isn't awaited, a sleep stuck at the wrong scale).

This revision introduces a tiny heartbeat table — one row per task —
that every background loop touches at the end of each iteration. The
health endpoint then treats any row whose ``last_run_at`` is older
than ``2 * expected_interval_seconds`` as a liveness failure and
returns 503. That lets synthetic monitors alert *before* the first
user-facing symptom (missed scheduled dispatch, stale surge multiplier,
unprocessed Stripe event, etc.).

Schema
------
``task_name`` is the logical name of the loop (e.g. ``surge_engine``,
``stripe_event_worker``). It's the primary key because there's only
one instance of each loop per worker process, and any replay just
overwrites with the latest timestamp.

``expected_interval_seconds`` is carried on the row itself (rather
than hard-coded into the reader) so the task owner and the health
check never drift: the loop writes ``expected_interval_seconds=120``
for surge, ``60`` for scheduled, etc., and the check applies the
``2x`` fudge factor generically.

``last_status`` distinguishes a loop that's ticking but internally
failing (``error``) from one that's healthy (``ok``) — important
because ``/health/deep`` must keep returning 200 for a loop that is
alive and retrying a transient error, but 503 if it's been stuck in
error for >2 intervals (the age check catches that separately).

Idempotent: ``CREATE TABLE IF NOT EXISTS`` — re-running is safe.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_bg_task_heartbeat"
down_revision: Union[str, Sequence[str], None] = "0004_stripe_event_queue_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.bg_task_heartbeat (
            task_name                  TEXT        PRIMARY KEY,
            last_run_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_status                TEXT        NOT NULL DEFAULT 'ok',
            last_error                 TEXT,
            expected_interval_seconds  INTEGER     NOT NULL,
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT bg_task_heartbeat_status_chk
                CHECK (last_status IN ('ok', 'error'))
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.bg_task_heartbeat")
