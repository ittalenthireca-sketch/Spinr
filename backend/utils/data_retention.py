"""Spinr data retention enforcement — nightly deletion cron.

Phase 3.1 of the production-readiness audit (audit finding C1).

Policy source of truth: docs/compliance/DATA_RETENTION.md.

This module implements the nightly sweep that applies the retention
schedule. It is intentionally conservative:

  * Each table is processed in its own try/except so a failure on
    one table does not abort the rest.
  * Every deletion is logged with a row count for audit trail.
  * A ``dry_run`` flag lets operators validate the DELETE clauses
    before running live.
  * Batch sizes cap each DELETE to 500 rows to avoid long-running
    transactions that could stall the DB under load.

Registered in backend/worker.py as ``data_retention_loop``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from loguru import logger

try:
    from utils.bg_heartbeat import record_bg_task_heartbeat

    from db_supabase import run_sync
    from supabase_client import supabase
except ImportError:
    from ..db_supabase import run_sync  # type: ignore
    from ..supabase_client import supabase  # type: ignore
    from ..utils.bg_heartbeat import record_bg_task_heartbeat  # type: ignore

# ---------------------------------------------------------------------------
# Retention periods (in days) — mirror docs/compliance/DATA_RETENTION.md
# ---------------------------------------------------------------------------
_CANCELLED_RIDE_DAYS = 90
_GPS_BREADCRUMB_DAYS = 90
_CHAT_MESSAGE_DAYS = 180
_OTP_RECORD_HOURS = 24
_PROCESSED_STRIPE_EVENT_DAYS = 90
_EXPIRED_REFRESH_TOKEN_DAYS = 7
_RIDE_IDEMPOTENCY_HOURS = 24

BATCH_SIZE = 500
LOOP_INTERVAL_SECONDS = 24 * 60 * 60  # run once per day


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff(days: int = 0, hours: int = 0) -> str:
    """ISO-8601 timestamp for the cutoff point relative to now."""
    delta = timedelta(days=days, hours=hours)
    return (_now_utc() - delta).isoformat()


async def _delete_batch(
    table: str,
    column: str,
    cutoff: str,
    extra_filter: dict | None = None,
    dry_run: bool = False,
) -> int:
    """Delete up to BATCH_SIZE rows older than cutoff.

    Returns the number of rows deleted (0 on dry_run or error).
    """
    try:
        if dry_run:
            # Count instead of delete so we can report what *would* happen.
            result = await run_sync(
                lambda: supabase.table(table).select("id", count="exact").lt(column, cutoff).limit(BATCH_SIZE).execute()
            )
            count = result.count or 0
            logger.info(
                f"[dry_run] data_retention: would delete up to {count} rows from {table} where {column} < {cutoff}"
            )
            return 0

        query = supabase.table(table).delete().lt(column, cutoff).limit(BATCH_SIZE)
        if extra_filter:
            for col, val in extra_filter.items():
                query = query.eq(col, val)

        result = await run_sync(lambda: query.execute())
        deleted = len(result.data) if result.data else 0
        if deleted:
            logger.info(
                f"data_retention: deleted {deleted} rows from {table} "
                f"where {column} < {cutoff}" + (f" (extra_filter={extra_filter})" if extra_filter else "")
            )
        return deleted
    except Exception as exc:
        logger.warning(f"data_retention: error deleting from {table}: {exc}")
        return 0


async def run_retention_pass(dry_run: bool = False) -> None:
    """Run one full pass of the retention policy across all tables."""
    log = logger.bind(task="data_retention", dry_run=dry_run)
    log.info("data_retention: starting retention pass")

    # -- OTP records (24-hour TTL) ----------------------------------------
    await _delete_batch(
        table="otp_records",
        column="created_at",
        cutoff=_cutoff(hours=_OTP_RECORD_HOURS),
        dry_run=dry_run,
    )

    # -- Ride idempotency keys (24-hour TTL) ------------------------------
    # Write-once from the rider client on every POST /rides attempt;
    # no reason to retain past the client's retry window.
    await _delete_batch(
        table="ride_idempotency_keys",
        column="created_at",
        cutoff=_cutoff(hours=_RIDE_IDEMPOTENCY_HOURS),
        dry_run=dry_run,
    )

    # -- Cancelled rides (90 days, never billed) ---------------------------
    await _delete_batch(
        table="rides",
        column="updated_at",
        cutoff=_cutoff(days=_CANCELLED_RIDE_DAYS),
        extra_filter={"status": "cancelled"},
        dry_run=dry_run,
    )

    # -- GPS breadcrumbs (90 days) ----------------------------------------
    # Rides older than 90 days are either billed (retained for 7 yrs,
    # so breadcrumbs have served their purpose) or cancelled (deleted
    # above). Safe to purge all breadcrumbs older than 90 days.
    await _delete_batch(
        table="gps_breadcrumbs",
        column="created_at",
        cutoff=_cutoff(days=_GPS_BREADCRUMB_DAYS),
        dry_run=dry_run,
    )

    # -- Chat messages (180 days) -----------------------------------------
    await _delete_batch(
        table="chat_messages",
        column="created_at",
        cutoff=_cutoff(days=_CHAT_MESSAGE_DAYS),
        dry_run=dry_run,
    )

    # -- Processed Stripe events (90 days) --------------------------------
    await _delete_batch(
        table="stripe_events",
        column="processed_at",
        cutoff=_cutoff(days=_PROCESSED_STRIPE_EVENT_DAYS),
        extra_filter=None,
        dry_run=dry_run,
    )

    # -- Expired / revoked refresh tokens (7 days post-expiry) -----------
    await _delete_batch(
        table="refresh_tokens",
        column="expires_at",
        cutoff=_cutoff(days=_EXPIRED_REFRESH_TOKEN_DAYS),
        dry_run=dry_run,
    )

    log.info("data_retention: retention pass complete")


async def data_retention_loop() -> None:
    """Long-running loop: run retention once a day at approximately 02:00 UTC.

    The loop sleeps until the next 02:00 UTC window rather than just
    sleeping for 24h so restarts don't shift the window around.
    """
    task_name = "data_retention"
    dry_run = os.environ.get("RETENTION_DRY_RUN", "").lower() in ("1", "true", "yes")

    if dry_run:
        logger.info("data_retention_loop: DRY RUN mode — no rows will be deleted")

    while True:
        try:
            await run_retention_pass(dry_run=dry_run)
            await record_bg_task_heartbeat(task_name, status="ok")
        except Exception as exc:
            logger.error(f"data_retention_loop iteration failed: {exc}")
            await record_bg_task_heartbeat(task_name, status="error", error=str(exc))

        # Sleep until next 02:00 UTC.
        now = _now_utc()
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        sleep_seconds = (next_run - now).total_seconds()
        logger.info(
            f"data_retention_loop: sleeping {sleep_seconds / 3600:.1f}h until next run at {next_run.isoformat()}"
        )
        await asyncio.sleep(sleep_seconds)
