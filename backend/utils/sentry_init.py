"""Shared Sentry initialisation for the API and worker processes.

Phase 2.2 of the production-readiness audit (audit finding T1).

Both the API (``server.py``) and the worker (``worker.py``) need to
report unhandled exceptions to Sentry — a worker crash that silently
stops the scheduled dispatcher is actually more dangerous than an API
crash, because there's no HTTP probe to notice it until the heartbeat
staleness check fires (Phase 1.6). Centralising the init keeps the
two entrypoints aligned on DSN, release tag, sampling, and
integration list.

No-op when ``settings.sentry_dsn`` is empty. The production boot
validator (``core/middleware._validate_production_config``) enforces
that the DSN must be set when ``ENV=production``; for local dev and
tests we want the unset-DSN path to short-circuit rather than crash
the import (sentry_sdk's starlette integration in particular raises
``DidNotEnable`` when Starlette isn't fully importable).
"""

from __future__ import annotations

import os
from typing import Literal

from loguru import logger

try:
    from core.config import settings
except ImportError:  # pragma: no cover — package-relative fallback for tests
    from ..core.config import settings  # type: ignore[no-redef]


# ── Sampling rates ───────────────────────────────────────────────────
# Transactions and profiling ride the same wire as error events in the
# SDK, so pushing either of these to 1.0 means we'll exhaust the Sentry
# ingest quota in a week. 0.1 (10%) gives enough signal for p95/p99
# traces and flamegraphs without the cost. Operators can bump via the
# SENTRY_TRACES_SAMPLE_RATE env var (read below) without a redeploy.
_DEFAULT_TRACES_SAMPLE_RATE = 0.1
_DEFAULT_PROFILES_SAMPLE_RATE = 0.1


def _resolve_release() -> str | None:
    """Best-effort release tag for Sentry deduplication.

    Prefers ``FLY_IMAGE_REF`` (set by Fly on every release so it's the
    most granular identifier we have), then falls back to
    ``SENTRY_RELEASE`` (explicit override), then the app version string
    from settings. Returns ``None`` only if none of those are set,
    which lets the SDK pick its own tag and keeps the init from
    failing.
    """
    fly_image = os.environ.get("FLY_IMAGE_REF", "").strip()
    if fly_image:
        # FLY_IMAGE_REF looks like "registry.fly.io/spinr:deployment-01JX…".
        # Strip the registry prefix so the release tag in Sentry is just
        # "spinr:deployment-01JX…" — still unique, much more readable.
        return fly_image.split("/", 1)[1] if "/" in fly_image else fly_image

    explicit = os.environ.get("SENTRY_RELEASE", "").strip()
    if explicit:
        return explicit

    app_version = getattr(settings, "APP_VERSION", "").strip()
    return f"spinr@{app_version}" if app_version else None


def _resolve_sample_rate(env_var: str, default: float) -> float:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"Sentry: {env_var}={raw!r} is not a float; using default {default}")
        return default
    if not 0.0 <= value <= 1.0:
        logger.warning(f"Sentry: {env_var}={value} out of [0, 1]; clamping")
        return max(0.0, min(1.0, value))
    return value


def init_sentry(role: Literal["api", "worker"]) -> None:
    """Initialise Sentry for the given process role.

    ``role`` is attached as a Sentry tag so we can filter the issue
    stream by ``role:worker`` vs ``role:api`` — useful because the two
    process groups hit different code paths (worker never serves HTTP
    requests, so HTTP-level transactions are always API).
    """
    dsn = (getattr(settings, "sentry_dsn", None) or "").strip()
    if not dsn:
        logger.debug(f"Sentry: no DSN configured, skipping init for role={role}")
        return

    # Imported here (not at module scope) so modules that never call
    # init_sentry don't pay the import cost, and so environments
    # without a working Starlette install don't fail at import time.
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    integrations: list = [
        LoggingIntegration(event_level="ERROR", breadcrumb_level="WARNING"),
    ]

    if role == "api":
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration

            integrations.append(FastApiIntegration(transaction_style="url"))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Sentry: FastApiIntegration unavailable: {exc}")

        try:
            from sentry_sdk.integrations.starlette import StarletteIntegration

            integrations.append(StarletteIntegration(transaction_style="url"))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Sentry: StarletteIntegration unavailable: {exc}")

    environment = (getattr(settings, "ENV", None) or "production").lower()
    release = _resolve_release()
    traces_rate = _resolve_sample_rate(
        "SENTRY_TRACES_SAMPLE_RATE", _DEFAULT_TRACES_SAMPLE_RATE
    )
    profiles_rate = _resolve_sample_rate(
        "SENTRY_PROFILES_SAMPLE_RATE", _DEFAULT_PROFILES_SAMPLE_RATE
    )

    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        environment=environment,
        release=release,
        traces_sample_rate=traces_rate,
        profiles_sample_rate=profiles_rate,
        # send_default_pii=True surfaces request headers and the User
        # object (user.id) on issues — essential for triage. We scrub
        # cookies / auth via Sentry's server-side data scrubbers rather
        # than refusing to send anything.
        send_default_pii=True,
    )

    # Tag every issue with the role so filters in the Sentry UI work
    # without having to grep the stack trace for a module name.
    sentry_sdk.set_tag("role", role)

    logger.info(
        "Sentry initialised: role={} env={} release={} traces={} profiles={}",
        role,
        environment,
        release or "<auto>",
        traces_rate,
        profiles_rate,
    )
