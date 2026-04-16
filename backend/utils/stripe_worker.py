"""Background worker loop that drains the stripe_events queue.

Phase 1.5 of the production-readiness audit (P1-P7). The HTTP webhook
handler (``routes/webhooks.py``) persists every Stripe event into
``stripe_events`` and returns 200 immediately. This loop owns the
processing side: it polls the table for unprocessed events and calls
``utils.stripe_dispatcher.dispatch_stripe_event`` on each.

Lifecycle
---------
Registered in ``backend/worker.py`` alongside the other background
loops. Runs on the dedicated worker machine (Fly process group
``worker``). Lives until SIGTERM.

Failure handling
----------------
* Transient errors (network blip, supabase 5xx) — exception caught,
  ``last_error`` recorded, ``next_attempt_at`` set to exponential
  backoff (30s → 1h cap). Event stays in the queue, gets picked up on
  the next poll once the backoff expires.
* Permanent errors (bad schema, code bug) — same path, but the
  ``attempt_count`` climbs visibly. At ~10 attempts operators should
  look at the ``last_error`` column and either fix the root cause or
  manually stamp ``processed_at`` to drop the row.
* Loop itself crashing — caught by ``worker.py``'s per-loop try/except
  so one loop dying doesn't take the whole worker down. asyncio
  restarts it on the next boot.

Poll cadence
------------
5 seconds. Stripe's retry SLA is on the order of minutes-to-hours so
a multi-second poll is fine; we pay very little Postgres cost because
the worker query hits the partial index ``idx_stripe_events_queue``
which only includes ``processed_at IS NULL`` rows.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Seconds between polls when the queue is empty.  Short enough that the
# tail latency from webhook arrival to side-effect is typically <5s.
POLL_INTERVAL_SECONDS = 5

# Events processed per poll. Kept small so one slow event doesn't
# starve others — the next poll drains more if needed.
BATCH_SIZE = 10


async def stripe_event_worker_loop() -> None:
    """Drain stripe_events forever, one batch per poll.

    Safe against being imported at module load in contexts without a
    configured Supabase client (returns quickly when fetch helper
    returns []).
    """
    # Lazy imports so importing this module is cheap in tests.
    try:
        from ..db_supabase import (
            fetch_unprocessed_stripe_events,
            mark_stripe_event_failed,
            mark_stripe_event_processed,
            record_bg_task_heartbeat,
        )
        from .stripe_dispatcher import dispatch_stripe_event
    except ImportError:
        from db_supabase import (  # type: ignore[no-redef]
            fetch_unprocessed_stripe_events,
            mark_stripe_event_failed,
            mark_stripe_event_processed,
            record_bg_task_heartbeat,
        )
        from utils.stripe_dispatcher import dispatch_stripe_event  # type: ignore[no-redef]

    logger.info(f"[stripe-worker] starting poll loop (interval={POLL_INTERVAL_SECONDS}s, batch={BATCH_SIZE})")

    while True:
        status = "ok"
        loop_err: str | None = None

        try:
            batch = await fetch_unprocessed_stripe_events(limit=BATCH_SIZE)
        except Exception as e:  # noqa: BLE001 — loop stability trumps specificity
            logger.error(f"[stripe-worker] poll failed: {e}")
            batch = []
            status = "error"
            loop_err = f"poll failed: {e}"

        if batch:
            logger.debug(f"[stripe-worker] processing batch of {len(batch)} event(s)")

            for row in batch:
                event_id = row.get("event_id")
                event_type = row.get("event_type") or ""
                payload = row.get("payload") or {}
                attempt_count = int(row.get("attempt_count") or 0)
                if not event_id:
                    continue

                try:
                    await dispatch_stripe_event(event_type, payload)
                except Exception as e:  # noqa: BLE001 — we classify below
                    # Truncated repr — `last_error` is TEXT but we cap at
                    # 2000 chars in the DB helper to avoid pathological
                    # traceback dumps blowing up the row.
                    logger.error(
                        f"[stripe-worker] dispatch failed "
                        f"event_id={event_id} type={event_type} "
                        f"attempt={attempt_count + 1}: {e}"
                    )
                    await mark_stripe_event_failed(event_id, str(e), attempt_count)
                    # We keep loop status='ok' here: dispatch failures are
                    # already tracked per-event on the row via
                    # `attempt_count` / `last_error`, and the loop itself
                    # is healthy as long as it keeps polling.
                    continue

                await mark_stripe_event_processed(event_id)
                logger.info(
                    f"[stripe-worker] dispatched event_id={event_id} type={event_type} attempt={attempt_count + 1}"
                )

        # Heartbeat (Phase 1.6 / T15) — written every tick regardless of
        # whether the batch was empty, so /health/deep doesn't flag the
        # worker as stale during quiet periods.
        await record_bg_task_heartbeat(
            "stripe_event_worker",
            POLL_INTERVAL_SECONDS,
            status=status,
            error=loop_err,
        )

        # Short sleep when there was work to process (keeps up with bursts);
        # full poll interval otherwise.
        await asyncio.sleep(0.1 if batch else POLL_INTERVAL_SECONDS)
