"""Spinr structured logging configuration.

Phase 2.7 of the production-readiness audit (audit finding T10).

Usage
-----
Call ``configure_logging()`` once, as early as possible in the
process lifecycle (before any other import that might emit a log
line). lifespan.py and worker.py both call it at the top of their
entrypoint. Subsequent ``from loguru import logger`` calls in any
module will automatically emit via the configured sink.

Behaviour by environment
------------------------
``ENV=production``
    Emits **newline-delimited JSON** to stdout. Each record carries:
    - Standard loguru fields (``level``, ``time``, ``message``,
      ``name``, ``function``, ``line``)
    - ``env`` — "production" | "staging" | ...
    - ``app`` — "api" | "worker" (set via ``APP_PROCESS`` env var,
      defaults to "api")
    - ``release`` — git SHA or deploy tag, read from ``FLY_MACHINE_VERSION``
      then ``GIT_COMMIT``, falls back to "unknown"
    - ``fly_machine_id`` — ``FLY_MACHINE_ID`` when running on Fly.io

    JSON-on-stdout is the canonical interface for every modern log
    aggregator (Fly log drain → BetterStack, Loki, Datadog, etc.).
    The drain ships whole lines; the aggregator parses them. No
    sidecar agent, no special plugin.

``ENV=staging``
    Same JSON output, but ``level`` floor raised to DEBUG so you can
    trace a single request end-to-end without changing code.

``ENV=development`` (default)
    Human-readable colorised output to stderr, DEBUG level. The
    loguru default is fine here; we just re-add it explicitly so
    the ``LOGURU_LEVEL`` env override still works.

Log level override
------------------
Set ``LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`` in the environment to
override the environment-based default. Useful for temporarily
increasing verbosity on a live production machine without a redeploy.
"""

import json
import os
import sys
from datetime import timezone

from loguru import logger


def _json_sink(message) -> None:
    """Write a loguru record as a single-line JSON object to stdout.

    The envelope is intentionally minimal — only fields that are
    useful in a log aggregator's search UI. Extra key/values added
    via ``logger.bind(key=value)`` or ``logger.opt(...)`` land in
    the ``extra`` dict.
    """
    record = message.record

    # Build extra dict from loguru's `extra` namespace, filtering out
    # internal loguru keys that have dedicated top-level positions.
    _loguru_internal = frozenset()
    extra = {k: v for k, v in record["extra"].items() if k not in _loguru_internal}

    payload = {
        "time":     record["time"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "level":    record["level"].name,
        "message":  record["message"],
        "logger":   record["name"],
        "function": record["function"],
        "line":     record["line"],
        # Process-level context — set once at startup by configure_logging()
        "env":        extra.pop("env", os.environ.get("ENV", "development")),
        "app":        extra.pop("app", os.environ.get("APP_PROCESS", "api")),
        "release":    extra.pop("release", _release()),
        "machine_id": extra.pop("machine_id", os.environ.get("FLY_MACHINE_ID", "")),
    }

    # Exception info — include if present; aggregators index on this.
    if record["exception"] is not None:
        exc_type, exc_value, _ = record["exception"]
        payload["exception"] = {
            "type":    exc_type.__name__ if exc_type else None,
            "message": str(exc_value) if exc_value else None,
        }

    if extra:
        payload["extra"] = extra

    # json.dumps + "\n" is the newline-delimited JSON (ndjson) wire format.
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def _release() -> str:
    """Best-effort release identifier for log correlation with Sentry."""
    return (
        os.environ.get("FLY_MACHINE_VERSION")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("RENDER_GIT_COMMIT")
        or "unknown"
    )


def configure_logging() -> None:
    """Remove loguru's default handler and install the environment-
    appropriate sink. Call once per process, before any other logging.
    """
    env = os.environ.get("ENV", "development").lower()
    log_level = os.environ.get("LOG_LEVEL", "").upper() or (
        "DEBUG"  if env in ("development", "staging")
        else "INFO"
    )

    # Remove loguru's default stderr handler so we don't double-emit.
    logger.remove()

    if env in ("production", "staging"):
        # Bind process-level context once; every subsequent log call
        # inherits these without the caller needing to pass them.
        logger.configure(extra={
            "env":        env,
            "app":        os.environ.get("APP_PROCESS", "api"),
            "release":    _release(),
            "machine_id": os.environ.get("FLY_MACHINE_ID", ""),
        })
        logger.add(
            _json_sink,
            level=log_level,
            format="{message}",    # _json_sink formats the full record
            backtrace=False,       # traceback in the `exception` key, not inline
            diagnose=False,        # don't include local variable values (PII risk)
            enqueue=False,         # synchronous — keeps line order on stdout
        )
    else:
        # Development: pretty, coloured, to stderr.
        logger.add(
            sys.stderr,
            level=log_level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
                "<level>{message}</level>"
            ),
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

    logger.info(
        f"Logging configured: env={env} level={log_level} "
        f"release={_release()} format={'json' if env != 'development' else 'pretty'}"
    )
