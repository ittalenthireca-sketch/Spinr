#!/usr/bin/env python3
"""Seed test rider accounts for load testing.

Phase 2.5d of the production-readiness audit (audit finding T8).

Creates N synthetic rider accounts in the target Supabase project,
writes their access JWTs to stdout (one per line) so the k6 scripts
can consume them via RIDER_TOKENS env var.

This script is STAGING ONLY. It inserts real rows into the database
and mints real JWTs. Running against production will create junk
accounts and leave debris.

Usage
-----
    # Create 20 riders, write tokens to file:
    cd backend
    ENV=staging \
    SUPABASE_URL=https://xxx.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=<key> \
    JWT_SECRET=<secret> \
    python scripts/seed_loadtest.py --riders 20 --output /tmp/rider-tokens.txt

    # Then run the k6 rider-flow test:
    RIDER_TOKENS="$(paste -sd, /tmp/rider-tokens.txt)" \
    BASE_URL=https://spinr-api-staging.fly.dev \
    k6 run ops/loadtest/k6-rider-flow.js

    # To clean up seeded accounts after a test run:
    python scripts/seed_loadtest.py --purge --output /tmp/rider-tokens.txt

Safety guards
-------------
* Refuses to run unless ENV != "production".
* All seeded phones use a fixed prefix ("+15550000") that is
  internationally invalid — no real user could be assigned one.
* Purge mode accepts the same --output file used at seed time, reads
  the user_ids embedded in each JWT, and hard-deletes those rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt

# ---------------------------------------------------------------------------
# Bootstrap: add backend/ to path so we can import project modules.
# ---------------------------------------------------------------------------
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from core.config import settings  # noqa: E402 — after path patch
from supabase import create_client  # noqa: E402

# ---------------------------------------------------------------------------
# Safety gate
# ---------------------------------------------------------------------------
ENV = os.environ.get("ENV", "development").lower()
if ENV == "production":
    print("ERROR: seed_loadtest.py refuses to run against ENV=production.", file=sys.stderr)
    sys.exit(1)

# Internationally-invalid phone prefix. These numbers cannot belong to
# real Spinr riders ("+1-555-0000-XXXX" is reserved / unallocated in NANP).
SEED_PHONE_PREFIX = "+15550000"

# ToS version placeholder so accepted_tos_version is not NULL
TOS_VERSION = "loadtest-v0"

# TTL: tokens expire after 24h so stale load-test tokens don't accumulate.
TOKEN_TTL_HOURS = 24


def _mint_jwt(user_id: str, phone: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "phone": phone,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
        "token_version": 0,
        "_loadtest": True,   # marker so we can identify these in logs
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _make_phone(index: int) -> str:
    # pad to 4 digits so the full number stays E.164-valid length
    return f"{SEED_PHONE_PREFIX}{index:04d}"


def seed(n: int, output_path: str | None) -> None:
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    tokens: list[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    print(f"Seeding {n} load-test rider accounts (ENV={ENV})…", file=sys.stderr)

    for i in range(1, n + 1):
        user_id = str(uuid.uuid4())
        phone = _make_phone(i)
        row = {
            "id": user_id,
            "phone": phone,
            "role": "rider",
            "created_at": now_iso,
            "profile_complete": True,
            "first_name": "LoadTest",
            "last_name": f"Rider{i:04d}",
            "email": f"loadtest+{i:04d}@spinr.internal",
            "current_session_id": str(uuid.uuid4()),
            "token_version": 0,
            "accepted_tos_version": TOS_VERSION,
            "accepted_tos_at": now_iso,
            "accepted_privacy_at": now_iso,
        }
        try:
            client.table("users").upsert(row, on_conflict="phone").execute()
        except Exception as exc:
            print(f"  [!] Failed to upsert rider {i} ({phone}): {exc}", file=sys.stderr)
            continue

        token = _mint_jwt(user_id, phone)
        tokens.append(token)

        if i % 5 == 0 or i == n:
            print(f"  {i}/{n} riders seeded", file=sys.stderr)

    if output_path:
        with open(output_path, "w") as f:
            f.write("\n".join(tokens) + "\n")
        print(f"Tokens written to {output_path}", file=sys.stderr)
    else:
        # stdout: one JWT per line — can be piped directly
        print("\n".join(tokens))

    print(f"Done. {len(tokens)}/{n} accounts created.", file=sys.stderr)


def purge(token_file: str) -> None:
    """Read JWTs from token_file, decode user_ids, delete from DB."""
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    with open(token_file) as f:
        tokens = [line.strip() for line in f if line.strip()]

    user_ids = []
    for token in tokens:
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET, algorithms=["HS256"],
                options={"verify_exp": False},   # tokens may be expired by purge time
            )
            if not payload.get("_loadtest"):
                print(f"  [skip] token not marked _loadtest — refusing to delete", file=sys.stderr)
                continue
            user_ids.append(payload["user_id"])
        except Exception as exc:
            print(f"  [skip] could not decode token: {exc}", file=sys.stderr)

    if not user_ids:
        print("No loadtest user_ids found — nothing to purge.", file=sys.stderr)
        return

    print(f"Purging {len(user_ids)} load-test accounts…", file=sys.stderr)
    # Delete in a single IN clause (Supabase REST supports this).
    try:
        client.table("users").delete().in_("id", user_ids).execute()
        print(f"Purged {len(user_ids)} accounts.", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR during purge: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed or purge load-test rider accounts (staging only).",
    )
    parser.add_argument(
        "--riders", type=int, default=10,
        help="Number of rider accounts to create (default: 10).",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Write JWTs to this file (one per line). Omit to print to stdout.",
    )
    parser.add_argument(
        "--purge", action="store_true",
        help="Delete previously seeded accounts. Requires --output pointing at "
             "the file produced by the seed run.",
    )
    args = parser.parse_args()

    if args.purge:
        if not args.output:
            parser.error("--purge requires --output <token-file> from a prior seed run.")
        purge(args.output)
    else:
        seed(args.riders, args.output)


if __name__ == "__main__":
    main()
