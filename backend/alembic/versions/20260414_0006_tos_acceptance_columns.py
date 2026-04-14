"""Add ToS / Privacy acceptance columns to users table.

Revision ID: 0006_tos_acceptance_columns
Revises: 0005_bg_task_heartbeat
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 3.3 of the production-readiness audit (audit finding C3).

Evidence for the finding: users.py stores user profiles but there is
no audit trail of which version of the Terms of Service and Privacy
Policy each user accepted, or when. Without this record:

  * We cannot prove consent to any version of our Privacy Policy in a
    regulatory inquiry (PIPEDA Principle 3 / Law 25).
  * We cannot selectively re-prompt users who signed up before a
    material policy change.
  * We cannot answer a PIPEDA access request with "you accepted v2 of
    our ToS on 2026-04-14 from IP 1.2.3.4".

Schema changes
--------------
Three columns on ``public.users``:

  accepted_tos_version TEXT
      The semantic version identifier of the ToS document the user
      accepted (e.g. ``"v1"``, ``"v2.1"``). NULL = not yet accepted
      (legacy rows migrated before this revision).

  accepted_tos_at TIMESTAMPTZ
      UTC timestamp of acceptance. NULL for legacy rows.

  accepted_privacy_at TIMESTAMPTZ
      UTC timestamp of Privacy Policy acceptance. Stored separately
      because the ToS and Privacy Policy have independent version
      histories; a user may be re-prompted for one but not the other.

Application layer
-----------------
``backend/schemas.py`` is updated to expose these fields on
``UserProfile`` and ``VerifyOTPRequest``.

``backend/routes/auth.py`` ``verify_otp``:
  * New-user path: writes accepted_tos_version / accepted_tos_at /
    accepted_privacy_at from the request payload. Raises 422 if the
    caller does not send a version string (mobile app must send it
    from the sign-up screen).
  * Existing-user path: no change (re-acceptance flow is handled by a
    separate ``POST /auth/accept-tos`` endpoint — to be added once the
    mobile apps ship the re-prompt screen).

Rollback
--------
The three columns are nullable, so adding them is fully backwards
compatible. Dropping them removes the audit trail — only do this
in a deliberate schema reversal.
"""

from alembic import op


revision = "0006_tos_acceptance_columns"
down_revision = "0005_bg_task_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.users
          ADD COLUMN IF NOT EXISTS accepted_tos_version   TEXT,
          ADD COLUMN IF NOT EXISTS accepted_tos_at        TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS accepted_privacy_at    TIMESTAMPTZ;

        COMMENT ON COLUMN public.users.accepted_tos_version IS
          'Semantic version of the ToS document accepted at sign-up or re-prompt (e.g. v1).';
        COMMENT ON COLUMN public.users.accepted_tos_at IS
          'UTC timestamp when the user accepted the ToS. NULL = legacy row.';
        COMMENT ON COLUMN public.users.accepted_privacy_at IS
          'UTC timestamp when the user accepted the Privacy Policy. NULL = legacy row.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.users
          DROP COLUMN IF EXISTS accepted_tos_version,
          DROP COLUMN IF EXISTS accepted_tos_at,
          DROP COLUMN IF EXISTS accepted_privacy_at;
        """
    )
