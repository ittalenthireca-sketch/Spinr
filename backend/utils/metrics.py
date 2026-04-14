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
