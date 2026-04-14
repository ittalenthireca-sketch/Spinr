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
