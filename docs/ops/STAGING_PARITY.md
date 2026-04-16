# Spinr — Staging Environment Parity

Phase 4.9 of the production-readiness audit (audit finding D4).

This document is the source of truth for what must match between
`spinr-api` (prod) and `spinr-api-staging` (staging), what is
deliberately allowed to diverge, and how we detect drift before a
customer does.

If a config setting exists in prod and is not covered by one of the
rows in the matrix below, it is drift by definition — either add it
to the matrix with an explicit owner, or delete it.

---

## 1. Parity goals

The point of staging is to catch configuration drift before it hits
paying customers. Specifically:

- **Catch breaking migrations** before they run against the prod
  Supabase instance. Alembic heads must match post-deploy.
- **Catch secret/env-var regressions** (a new `FLY_SECRET` added in
  prod code but never set in staging surfaces as a 500 on first
  request, not a Fly health-check failure at boot).
- **Validate external-integration wiring** (Stripe webhook signing,
  Twilio SMS delivery, FCM token refresh) against test-mode
  equivalents before cutting over to live credentials.
- **Give on-call a non-destructive target** for runbook rehearsal,
  chaos drills, and load tests.

Staging is not a preview environment and not a QA sandbox. It is a
smaller, cheaper, test-credentialed copy of prod. If a change can't
be reproduced on staging, that itself is a parity bug.

---

## 2. Parity matrix

One row per system. `Parity` column values:
- **match** — identical by contract, enforced by CI or deploy tooling.
- **scaled** — same shape, smaller size (documented below).
- **test-mode** — deliberately different credentials (see §3).
- **gap** — known drift, tracked in §6.

| System | Production | Staging | Parity | Owner |
| --- | --- | --- | --- | --- |
| Fly app name | `spinr-api` | `spinr-api-staging` | n/a | Backend |
| Fly primary region | `yyz` | `yyz` | match | Backend |
| Fly machine size (app) | `shared-cpu-2x`, 1 GB | `shared-cpu-1x`, 512 MB | scaled | Backend |
| Fly machine size (worker) | `shared-cpu-1x`, 512 MB | `shared-cpu-1x`, 512 MB | match | Backend |
| Process groups | `app`, `worker` | `app`, `worker` | match | Backend |
| Min running machines (app) | 2 | 1 | scaled | Backend |
| Min running machines (worker) | 1 | 1 | match | Backend |
| Supabase plan | Pro | Free | scaled | Backend |
| Supabase project ref | `spinr-prod` | `spinr-staging` | n/a | Backend |
| DB schema | `alembic heads` @ tip | `alembic heads` @ tip | match (CI) | Backend |
| DB seed data | real | synthetic (see §3) | test-mode | Backend |
| Redis (Upstash) | prod DB, TLS | staging DB, TLS | scaled | Backend |
| Stripe mode | live keys | test keys | test-mode | Backend + Finance |
| Stripe webhook endpoint | `/webhooks/stripe` on prod host | same path on staging host | match | Backend |
| Twilio account | live SID, live number | test SID, magic number | test-mode | Backend |
| FCM project | `spinr-prod` | `spinr-test` | test-mode | Mobile |
| Env vars (non-secret) | `fly.toml` `[env]` | `fly.staging.toml` `[env]` | match (CI diff) | Backend |
| Env vars (secret keys) | `fly secrets list` | `fly secrets list` | match (CI diff) | Backend |
| Sentry project | `spinr-backend` | `spinr-backend-staging` | match (separate DSN) | Backend |
| Feature flags | `settings.feature_flags` | mirror of prod + explicit overrides | match w/ overrides | Product |
| Rate limits | prod values | 10x lower (see §3) | test-mode | Backend |
| TLS cert | Fly-managed, custom domain | Fly-managed, `*.fly.dev` | scaled | Backend |

Python version, base Docker image, and `requirements.txt` are a
single artifact across both environments — they are not in the
matrix because there is no way for them to drift.

---

## 3. Non-parity by design

The following divergences are intentional. Do not "fix" them without
a cross-team discussion.

- **Stripe test mode.** Staging uses `sk_test_…` and the Stripe
  test-clock. We never want a staging load test to charge a real
  card. Webhook signing secret is the test-mode one from the Stripe
  dashboard under the staging webhook endpoint.
- **Twilio test credentials.** Test SID + magic numbers
  (`+15005550006` etc.) so load tests don't burn SMS quota. Real
  numbers are not delivered on staging; QA uses the Twilio
  dashboard to inspect the request log.
- **FCM test project.** Separate Firebase project so a bad push
  payload can't spam a real user. Staging builds of the mobile app
  are wired to this project via `google-services.staging.json`.
- **Synthetic data.** No production PII on staging. The staging DB
  is seeded nightly from `scripts/seed_staging.py`; backups from
  prod are not restored onto staging (see `docs/ops/BACKUP_DR.md`).
- **Lower quota limits.** SlowAPI rate limits in staging are 10x
  looser so load tests don't trip them, and Supabase Free's 500 MB
  DB ceiling means we prune old ride records aggressively.
- **Smaller Fly footprint.** 1 app machine, 1 worker, smaller
  CPU/RAM. Acceptable because we do not run customer load against
  staging.

---

## 4. Drift detection

Drift detection runs in CI (`.github/workflows/ci.yml`, job
`parity-check`) on every push to `main` and on a nightly cron.

### Secret-key diff

```bash
fly secrets list --app spinr-api --json | jq -r '.[].Name' | sort > /tmp/prod.keys
fly secrets list --app spinr-api-staging --json | jq -r '.[].Name' | sort > /tmp/staging.keys
diff /tmp/prod.keys /tmp/staging.keys
```

We diff **names only**, never values. A non-empty diff fails the
job. Exceptions are listed in `ops/parity/allowed_key_diff.txt`
(one key per line, with a one-line comment explaining why).

### Alembic head match

```bash
alembic -x url=$PROD_DB_URL heads | awk '{print $1}' > /tmp/prod.head
alembic -x url=$STAGING_DB_URL heads | awk '{print $1}' > /tmp/staging.head
diff /tmp/prod.head /tmp/staging.head
```

Heads must be identical. If staging is ahead, that is expected
during a release bake (see §5). If prod is ahead, someone deployed
a migration that skipped staging — page the backend on-call.

### Non-secret env diff

```bash
diff <(yq '.env' fly.toml) <(yq '.env' fly.staging.toml)
```

Intended diff is keys only; values that differ must be noted in
the matrix above. Every divergence needs a §3 justification.

### Dashboards

Sentry, Grafana, and the Fly dashboard each have a "Staging"
variant of every prod dashboard. Broken dashboards on staging are a
parity bug — fix them the same way you'd fix a prod dashboard.

---

## 5. Release-promotion flow

All backend deploys go through staging first. No exceptions for
"tiny" or "docs-only" changes — the whole point is that the
pipeline stays warm.

1. **Merge to `main`.** CI runs the test suite and the parity
   checks from §4.
2. **Auto-deploy to staging.** `flyctl deploy --app
   spinr-api-staging --strategy rolling`. Alembic migrations run
   here first.
3. **Bake.** Minimum **2 hours** of staging traffic (synthetic
   health monitor + manual smoke tests) before promotion. For
   migrations that rewrite rows, bake **24 hours**.
4. **Promote to prod.** `flyctl deploy --app spinr-api --strategy
   rolling` using the same git SHA that baked on staging. The
   Docker image is rebuilt — we do not retag — but the source ref
   is identical.
5. **Post-deploy parity check.** The CI `parity-check` job re-runs.
   Alembic heads should match within the Fly rolling-deploy window
   (<10 min); if they don't, rollback.

### Rollback

- **App code:** `flyctl releases list --app spinr-api`, then
  `flyctl releases rollback <version> --app spinr-api`. This is a
  pure image swap; no DB changes.
- **Migrations:** rollback is not automatic. If a migration is
  live-incompatible with the previous image, deploy a hotfix
  forward instead. The down-migration is a last resort and must be
  run manually against the prod DB with the on-call +1 watching.
- See the rollback section of `docs/ops/SLOs.md` for the error-
  budget implications.

---

## 6. Known parity gaps

Tracked drift. Each row has a remediation owner and a target
resolution window. If the window lapses, the item is escalated at
the weekly on-call handoff.

| Gap | Detected | Owner | Target |
| --- | --- | --- | --- |
| Staging Supabase is Free plan — no PITR, 500 MB ceiling | 2026-02 | Backend | Q3 2026 (move to Pro when budget allows) |
| Staging has no multi-region replica (prod has `yyz` + `ewr`) | 2026-03 | Backend | Not planned; scaled-down by design |
| Mobile staging builds are manual (EAS profile `staging` exists but no auto-publish on merge) | 2026-03 | Mobile | Q2 2026 |
| Sentry release-health integration only wired on prod | 2026-01 | Backend | Q2 2026 |
| Feature-flag mirror job runs hourly, not on-write — can lag up to 60 min | 2026-04 | Product | Accept |

Gaps marked "Accept" are permanent documented divergences, not TODOs.

---

## 7. Related

- `docs/ops/BACKUP_DR.md` — why prod backups do not restore to staging.
- `.github/workflows/ci.yml` — `parity-check` job implementing §4.
- `docs/ops/SLOs.md` — error-budget policy gating prod deploys.
- `docs/ops/SECRETS_ROTATION.md` — rotate staging credentials
  alongside prod on the same cadence.
- `docs/ops/MULTI_REGION.md` — regional footprint that staging
  deliberately does not replicate.
