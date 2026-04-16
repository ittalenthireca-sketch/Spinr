"""stripe_events queue columns for async processing

Revision ID: 0004_stripe_event_queue_columns
Revises: 0003_critical_indexes
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 1.5 of the production-readiness audit (roadmap row 1.5, audit
finding P1-P7).

The webhook handler currently does DB writes + push notifications + Spinr
Pass activation inline in the HTTP request path. Stripe's 20s deadline
is tight if the push API is slow and a single slow request can jam the
whole Stripe retry queue.

This revision upgrades ``stripe_events`` (migration 22) from a pure
idempotency table into a minimal durable work-queue by adding three
bookkeeping columns:

    attempt_count    INT   NOT NULL DEFAULT 0
    last_error       TEXT
    next_attempt_at  TIMESTAMPTZ

The async worker polls ``processed_at IS NULL AND
(next_attempt_at IS NULL OR next_attempt_at <= now())``, dispatches the
event using the payload already persisted by ``claim_stripe_event``,
and either stamps ``processed_at`` on success or bumps
``attempt_count`` + sets an exponential ``next_attempt_at`` on failure.

Why not Redis
-------------
The audit doc suggests "push event ID into a Redis queue", but
``stripe_events`` already persists the full payload and we already run
Alembic migrations, so a Postgres-backed queue is:

* **Durable for free** — no "Redis flushed, we lost 40 events" failure
  mode.
* **Simpler to operate** — no new infra, no extra failure boundary, no
  cross-service consistency window.
* **Correct for our volume** — at ~20 events/sec peak we're nowhere
  near Postgres's comfortable LISTEN/NOTIFY or poll-and-claim ceiling.

If we later need higher throughput we can swap the underlying queue
without changing the webhook contract.

Idempotency of the migration
----------------------------
``ADD COLUMN IF NOT EXISTS`` is idempotent; re-running is safe. A
partial index on ``(next_attempt_at)`` where ``processed_at IS NULL``
keeps the worker poll cheap as the table grows.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_stripe_event_queue_columns"
down_revision: Union[str, Sequence[str], None] = "0003_critical_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.stripe_events
            ADD COLUMN IF NOT EXISTS attempt_count   INTEGER     NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_error      TEXT,
            ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;
        """
    )

    # The worker's poll query:
    #
    #   SELECT event_id, event_type, payload, attempt_count
    #     FROM stripe_events
    #    WHERE processed_at IS NULL
    #      AND (next_attempt_at IS NULL OR next_attempt_at <= now())
    #    ORDER BY received_at
    #    LIMIT N;
    #
    # Partial index on (next_attempt_at, received_at) where processed_at
    # IS NULL keeps it cheap even as the table grows (successful events
    # are excluded from the index entirely).  CONCURRENTLY is required
    # because the table is write-hot via the webhook handler.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stripe_events_queue
                ON public.stripe_events (next_attempt_at NULLS FIRST, received_at)
                WHERE processed_at IS NULL;
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.idx_stripe_events_queue")
    op.execute(
        """
        ALTER TABLE public.stripe_events
            DROP COLUMN IF EXISTS next_attempt_at,
            DROP COLUMN IF EXISTS last_error,
            DROP COLUMN IF EXISTS attempt_count;
        """
    )
