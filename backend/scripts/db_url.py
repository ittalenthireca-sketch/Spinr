"""Validate that DATABASE_URL points at the Supabase Supavisor pooler.

Shared by backend/scripts/run_migrations.py and backend/alembic/env.py so
both refuse to run against the non-pooled direct-connection endpoint
without an explicit override.

Why this matters (Phase 1.3 of the production-readiness audit)
--------------------------------------------------------------
Supabase exposes three Postgres endpoints:

    db.<project-ref>.supabase.co:5432           ← direct, IPv6-only,
                                                   NO connection pooling;
                                                   connection storms kill
                                                   the cluster.

    aws-0-<region>.pooler.supabase.com:5432     ← Supavisor session mode;
                                                   compatible with
                                                   prepared statements,
                                                   LISTEN/NOTIFY, session
                                                   variables. Right
                                                   default for DDL /
                                                   migrations / SQLAlchemy.

    aws-0-<region>.pooler.supabase.com:6543     ← Supavisor transaction
                                                   mode; short-lived,
                                                   serverless-friendly,
                                                   but prepared statements
                                                   disabled. Best for
                                                   application runtime
                                                   traffic.

Spinr's application runtime goes through PostgREST (supabase-py, HTTPS),
so the only code that touches Postgres directly is the migration path
(Alembic + scripts/run_migrations.py). We lock those to session-mode
pooler as the default and let operators override with an env var when
they genuinely need the direct endpoint (e.g. rare ops tooling that
requires LISTEN/NOTIFY on a CDC stream).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# Hostname fragment that identifies the non-pooled Supabase endpoint.
# Anything of the form ``db.<ref>.supabase.co`` is the direct cluster.
DIRECT_HOST_FRAGMENT = ".supabase.co"
POOLER_HOST_FRAGMENT = ".pooler.supabase.com"

# Recommended default port for migrations (Supavisor session mode).
RECOMMENDED_SESSION_PORT = 5432
# Transaction-mode port; fine for DDL but not the default we document.
TRANSACTION_PORT = 6543

# Operators who consciously need the direct endpoint (e.g. one-time data
# imports that require features the pooler doesn't support) can set this
# env var to any non-empty value and the validator will stand down.
ALLOW_DIRECT_ENV = "SPINR_ALLOW_DIRECT_DATABASE_URL"


class DatabaseUrlValidationError(RuntimeError):
    """Raised when DATABASE_URL looks like a footgun for migrations."""


def validate_database_url(url: str) -> list[str]:
    """Return a list of human-readable warnings about ``url``.

    An empty list means the URL looks correctly pointed at the Supavisor
    pooler. Warnings are printed by callers; hard errors are raised for
    the one case we refuse to proceed on (direct cluster host without
    the explicit-override env var).
    """
    warnings: list[str] = []
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port

    if not host:
        # urlparse couldn't make sense of it — let the driver fail with
        # its own, more specific error.
        return warnings

    is_pooler = host.endswith(POOLER_HOST_FRAGMENT)
    is_direct = (
        host.endswith(DIRECT_HOST_FRAGMENT)
        and not is_pooler
        and host.startswith("db.")
    )

    if is_direct:
        if not os.environ.get(ALLOW_DIRECT_ENV):
            raise DatabaseUrlValidationError(
                f"DATABASE_URL host '{host}' is the direct Supabase cluster "
                f"endpoint, which has NO connection pooling. Use the "
                f"Supavisor pooler instead "
                f"(aws-0-<region>.pooler.supabase.com:{RECOMMENDED_SESSION_PORT}). "
                f"If you genuinely need the direct endpoint for a one-off "
                f"(e.g. LISTEN/NOTIFY), re-run with "
                f"{ALLOW_DIRECT_ENV}=1 set in the environment."
            )
        warnings.append(
            f"DATABASE_URL host '{host}' is the direct (non-pooled) endpoint; "
            f"{ALLOW_DIRECT_ENV} is set so proceeding anyway."
        )

    if is_pooler and port == TRANSACTION_PORT:
        warnings.append(
            f"DATABASE_URL port {TRANSACTION_PORT} is Supavisor transaction "
            f"mode; prepared statements are disabled. Migrations and "
            f"SQLAlchemy generally prefer session mode "
            f"(port {RECOMMENDED_SESSION_PORT}). Proceeding — most DDL "
            f"works on either — but switch to {RECOMMENDED_SESSION_PORT} "
            f"if you see 'prepared statement does not exist' errors."
        )

    return warnings


def resolve_and_validate_database_url() -> str:
    """Read DATABASE_URL from env, validate, print warnings, return it.

    Raises RuntimeError (or DatabaseUrlValidationError) if unset or if
    the URL points at the direct cluster without the override.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Export the Supabase Supavisor pooler "
            "URL with the service-role password before running migrations. "
            "See backend/.env.example and backend/alembic/README.md."
        )

    for message in validate_database_url(url):
        # Print to stderr so it shows up in CI logs without polluting
        # Alembic's own stdout (which CI captures as SQL output in
        # --sql mode).
        import sys

        print(f"[db-url] WARN: {message}", file=sys.stderr)

    return url
