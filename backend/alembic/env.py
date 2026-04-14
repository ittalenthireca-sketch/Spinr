"""Alembic environment for the spinr backend.

Design notes
------------
* spinr has **no SQLAlchemy models** — the schema is authored in raw SQL
  under backend/migrations/. Alembic is adopted for NEW changes going
  forward (see backend/alembic/README.md for the cutover story). We
  therefore set ``target_metadata = None``; ``alembic revision
  --autogenerate`` is intentionally a no-op and migrations are written
  by hand with ``op.execute(...)`` or the ``op.*`` helpers.

* Database URL resolution mirrors scripts/run_migrations.py: we pull
  ``DATABASE_URL`` straight out of the process environment so CI,
  production, and local dev all share one knob. We do NOT set
  ``sqlalchemy.url`` in alembic.ini on purpose (committing a dev URL
  is how credentials leak into git).

* Offline mode is kept working — ``alembic upgrade head --sql`` emits
  the raw SQL without touching a database. CI uses that to verify the
  migration chain compiles on every PR.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Alembic Config object — gives access to values within the .ini file.
config = context.config

# Set up loggers per alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models — autogenerate is disabled by design. See module docstring.
target_metadata = None


def _resolve_database_url() -> str:
    """Pull DATABASE_URL from the environment.

    We deliberately require the env var rather than falling back to a
    baked-in default: anything that silently connects to a dev DB is a
    foot-gun waiting to happen in CI / production.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Export the Postgres URL "
            "(e.g. the Supabase pooler URL with the service role password) "
            "before running alembic."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout.

    Used by CI: ``alembic upgrade head --sql`` validates that every
    revision in the chain compiles without needing a live database.
    ``literal_binds=True`` makes ``op.execute`` calls render their
    parameters inline so the emitted SQL is directly runnable.
    """
    context.configure(
        url=_resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database (normal ``upgrade`` path)."""
    # alembic.ini leaves sqlalchemy.url blank — inject it from env here.
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
