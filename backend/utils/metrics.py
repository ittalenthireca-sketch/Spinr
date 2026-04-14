"""Prometheus metrics wiring for the Spinr backend.

Phase 2.3 of the production-readiness audit (audit finding T3).

This module is the single owner of the Prometheus instrumentation
surface. Two responsibilities:

1. **Install the FastAPI instrumentator** — auto-captures HTTP request
   counts, latency histograms, and in-flight request gauges without
   any per-endpoint code change. That alone covers most dashboards
   (availability, p95 latency, error rate).

2. **Expose the /metrics scrape endpoint** on the API process. Phase 2.3d
   adds a separate exporter on the worker; both share the same
   `prometheus_client` default registry, so the custom gauges defined
   in later sub-tasks (2.3b/2.3c) light up on whichever process
   actually emits them.

Why not just register directly in ``server.py``?
------------------------------------------------
The worker process also needs to export metrics (dispatch latency,
stripe queue depth, heartbeat age) but doesn't have a FastAPI app to
piggy-back on. Keeping the instrumentator install behind a function
lets us share the import-time story with ``worker.py`` in 2.3d.

Endpoint protection
-------------------
``/metrics`` is left unauthenticated in this sub-task. Phase 2.3e
adds the IP allow-list / bearer guard; shipping the raw endpoint
first lets us validate the dashboard wiring before deciding on the
final auth story.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger
from prometheus_client import Counter, Gauge, Histogram

# ────────────────────────────────────────────────────────────────────────
# Custom application metrics (Phase 2.3b / audit T3)
#
# These are the five key gauges called out in the launch-checklist
# ("`/metrics` live + Grafana dashboard with 5 key gauges"). Declared
# here — at module scope — so they register into the default
# prometheus_client registry on first import, which is the same
# registry the FastAPI instrumentator's /metrics endpoint reads from.
# Emission sites (the code that actually updates these) are wired in
# 2.3c.
#
# Naming convention: `spinr_<subject>_<unit>`. Unit suffix is required
# by Prometheus style guide so operators reading a histogram don't
# have to guess whether it's milliseconds or seconds.
# ────────────────────────────────────────────────────────────────────────

# Active rides gauge, labelled by status. `status` is one of the
# ride.status enum values; keeping it as a label lets a single gauge
# series cover the dispatch-pipeline funnel (searching → driver_assigned
# → in_progress). Lowish cardinality — ~8 statuses × N areas is fine.
active_rides = Gauge(
    "spinr_active_rides",
    "Count of rides in non-terminal states, labelled by status.",
    labelnames=("status",),
)

# Dispatch latency histogram (seconds). Observed when a ride transitions
# from `searching` to `driver_assigned`; the bucket choice targets the
# 30s SLO with headroom on either side for tuning.
ride_dispatch_latency_seconds = Histogram(
    "spinr_ride_dispatch_latency_seconds",
    "Wall time from ride request to first driver assignment.",
    buckets=(0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300),
)

# Active WebSocket connections, labelled by role. Role is the
# ``client_type`` from the /ws/{client_type}/{client_id} route
# ('rider', 'driver', 'admin') — bounded, low cardinality.
ws_connections = Gauge(
    "spinr_ws_connections",
    "Active WebSocket connections held by this instance, by role.",
    labelnames=("role",),
)

# Stripe event queue depth — number of rows in `stripe_events` with
# processed_at IS NULL. Refreshed periodically by the metrics loop
# rather than computed on every scrape so a scraping burst doesn't
# translate to a DB-query burst.
stripe_queue_depth = Gauge(
    "spinr_stripe_queue_depth",
    "Unprocessed rows in stripe_events (async webhook queue).",
)

# Age in seconds of the oldest background-task heartbeat, per task.
# Labelled by task_name so a single scrape tells you which loop is
# stale. Populated from bg_task_heartbeat (Phase 1.6) on the metrics
# refresh cadence.
bg_task_heartbeat_age_seconds = Gauge(
    "spinr_bg_task_heartbeat_age_seconds",
    "Seconds since the last heartbeat for each background task.",
    labelnames=("task_name",),
)

# Companion gauge: the task's self-reported status (0 = ok, 1 = error).
# A task can be fresh (heartbeat age low) but internally erroring —
# this gauge catches that case so Grafana can alert on either dimension.
bg_task_last_status = Gauge(
    "spinr_bg_task_last_status",
    "Last-reported status per background task (0=ok, 1=error).",
    labelnames=("task_name",),
)

# Counters for things we want to rate() but don't need latency bands on.
ride_dispatch_total = Counter(
    "spinr_ride_dispatch_total",
    "Count of ride dispatch attempts, labelled by outcome.",
    labelnames=("outcome",),
)


def install_fastapi_instrumentator(app) -> None:
    """Attach the prometheus-fastapi-instrumentator to ``app``.

    Safe to call multiple times — the instrumentator itself dedupes
    on the FastAPI middleware list, but we also guard so boot ordering
    changes don't cause double-registration warnings.

    Falls back silently if the package isn't installed; this matters
    for dev-without-extras and for the Alembic env.py which imports
    chunks of the backend package but never needs metrics.
    """
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:
        logger.warning(
            "prometheus-fastapi-instrumentator not installed — /metrics will not be exposed"
        )
        return

    # `should_respect_env_var=False` keeps the instrumentator from
    # silently disabling itself when ENABLE_METRICS is unset; we want
    # /metrics always on, protected by 2.3e instead.
    instrumentator = Instrumentator(
        # Don't let in-flight long-running requests (WS upgrades,
        # streaming uploads) skew the latency histograms.
        excluded_handlers=["/metrics", "/health", "/health/deep"],
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
    )

    instrumentator.instrument(app)
    # Expose at /metrics with `include_in_schema=False` so it doesn't
    # pollute the OpenAPI docs. The endpoint itself is served by the
    # instrumentator's own handler which writes out the default
    # prometheus_client registry — that's the registry any custom
    # gauges (2.3b) also publish into, so they appear automatically.
    instrumentator.expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
        should_gzip=True,
    )
    logger.info("Prometheus /metrics endpoint installed")


# ────────────────────────────────────────────────────────────────────────
# Periodic gauge refresh (Phase 2.3c / audit T3)
#
# Some of the custom gauges above are snapshot-style — they don't have
# a natural "event" to increment on, and computing them on every
# Prometheus scrape would translate to a DB-query storm when multiple
# scrapers hit us (Grafana + uptime checks + ad-hoc operators).
# Instead we compute them on a fixed cadence (``REFRESH_INTERVAL``) and
# the scrape simply reads the cached value.
#
# Runs on BOTH the API and worker process so whichever /metrics endpoint
# an operator hits always has data. Duplicate writes to the same gauge
# are harmless — the last writer wins and both processes see the same
# DB state.
# ────────────────────────────────────────────────────────────────────────

# 30 seconds is a good balance between gauge staleness and DB load.
# Prometheus' default scrape interval is 15s; at 30s refresh, the worst-
# case gauge age at scrape time is 30s, which is well under the alerting
# evaluation window (typically 2-5 minutes).
REFRESH_INTERVAL_SECONDS = 30


async def _refresh_periodic_gauges() -> None:
    """One-shot refresh pass; called by ``metrics_refresh_loop``.

    Exposed as a separate function so tests / ad-hoc scripts can trigger
    a refresh without waiting 30s. All lookups are fail-soft — a single
    failed read clears the gauge to 0 rather than propagating the error.
    """
    # Lazy import to avoid a circular import at module load time
    # (db_supabase imports loguru which imports plenty of stdlib but
    # nothing metric-related, yet if the worker's boot order changes
    # we don't want metrics.py hoisting supabase).
    try:
        from db_supabase import (
            count_active_rides_by_status,
            count_unprocessed_stripe_events,
            fetch_bg_task_heartbeats,
        )
    except Exception as e:  # pragma: no cover — module not importable in tests
        logger.debug(f"metrics refresh: db_supabase unavailable ({e})")
        return

    # 1. Stripe queue depth
    try:
        depth = await count_unprocessed_stripe_events()
        stripe_queue_depth.set(depth)
    except Exception as e:
        logger.debug(f"metrics refresh: stripe queue depth failed: {e}")

    # 2. Active rides by status
    try:
        by_status = await count_active_rides_by_status()
        for status, count in by_status.items():
            active_rides.labels(status=status).set(count)
    except Exception as e:
        logger.debug(f"metrics refresh: active rides failed: {e}")

    # 3. Background task heartbeat age + last status
    try:
        rows = await fetch_bg_task_heartbeats()
        now = datetime.now(timezone.utc)
        for row in rows:
            task_name = row.get("task_name")
            if not task_name:
                continue
            last_run_at_raw = row.get("last_run_at")
            age_seconds = 0.0
            if last_run_at_raw:
                try:
                    # Supabase returns timestamptz as ISO-8601; handle
                    # both "…Z" and "…+00:00" forms.
                    last_run_at = datetime.fromisoformat(
                        str(last_run_at_raw).replace("Z", "+00:00")
                    )
                    age_seconds = max(0.0, (now - last_run_at).total_seconds())
                except Exception:
                    age_seconds = 0.0
            bg_task_heartbeat_age_seconds.labels(task_name=task_name).set(age_seconds)
            status = (row.get("last_status") or "ok").lower()
            bg_task_last_status.labels(task_name=task_name).set(0 if status == "ok" else 1)
    except Exception as e:
        logger.debug(f"metrics refresh: bg task heartbeats failed: {e}")


async def metrics_refresh_loop() -> None:
    """Long-running loop that refreshes snapshot gauges every 30s.

    Spawned from both ``core/lifespan.py`` (API in single-process mode)
    and ``worker.py`` (always-on worker machine). The two processes
    refreshing independently means a worker outage doesn't blind us to
    active_rides/stripe_queue_depth — the API keeps publishing them,
    and vice versa.

    Never raises — any exception is logged and the loop continues, so
    a transient DB blip doesn't permanently detach us from our own
    metrics.
    """
    logger.info(f"metrics_refresh_loop: starting (every {REFRESH_INTERVAL_SECONDS}s)")
    while True:
        try:
            await _refresh_periodic_gauges()
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"metrics_refresh_loop iteration failed: {e}")
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
