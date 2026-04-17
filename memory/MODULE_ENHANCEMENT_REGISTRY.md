# Module Enhancement Registry — Spinr

> **Status:** Active tracking document. Living backlog.
> **Created:** 2026-04-17
> **Branch:** `claude/count-project-modules-H99sr`
> **Scope:** Folder-by-folder audit of every top-level module in the repo —
> what exists today, what needs enhancement, and why (value-add, coverage,
> UX, admin experience, operations).
>
> **Sister document:** [`HARDCODED_VALUES_REGISTRY.md`](./HARDCODED_VALUES_REGISTRY.md)
> tracks hard-coded values/secrets/constants as a separate concern.
> **Production audit:** [`../docs/audit/production-readiness-2026-04/00_INDEX.md`](../docs/audit/production-readiness-2026-04/00_INDEX.md)
> catalogs P0/P1/P2 blockers — this document complements, not duplicates.

## How to read this document

Each section covers one module group. Every enhancement has:
- **Path** — file or folder it applies to
- **What exists** — one-line summary of current state
- **Enhancement** — what to add/change
- **Value-add** — one of: User experience · Admin experience · Operations · Reliability · Compliance · Developer experience
- **Priority** — see severity key below

### Severity key (advisory)

| Icon | Meaning |
|---|---|
| 🔥 | **Critical gap** — blocks a user-visible flow or an audit-flagged P0/P1 |
| 🟠 | **High-value add** — closes a real UX or ops gap within 1–2 weeks |
| 🟡 | **Medium uplift** — measurable quality/maintainability gain, quarter-scoped |
| ⚪ | **Polish** — nice-to-have, non-blocking |

---

## Table of contents

1. [User-facing apps](#1-user-facing-apps) — `rider-app/`, `driver-app/`, `admin-dashboard/`, `frontend/`, `shared/`
2. [Backend & data](#2-backend--data) — `backend/`, `backend/alembic/`, `backend/migrations/`, `backend/tests/`
3. [Infra, ops & docs](#3-infra-ops--docs) — `.github/workflows/`, `ops/`, `docs/`, `fly.toml`, `render.yaml`, `Dockerfile`, `.husky/`, `.maestro/`
4. [Auxiliary / meta / compliance](#4-auxiliary--meta--compliance) — `discovery/`, `compliance/`, `agents/`, `memory/`, `i18n/`, `.kilo/`, `.agents/`, `.emergent/`, `.claude/`, `graphify-out/`
5. [Root cleanup, cross-cutting themes & priority summary](#5-root-cleanup-cross-cutting-themes--priority-summary)

---

## 1. User-facing apps

Covers everything a rider, driver, or admin interacts with. Four apps plus
one shared lib. **`frontend/` is deprecated** — retained only as reference
for the rider-app web build migration.

### 1.1 `rider-app/` (Expo SDK 55 / React Native — rider mobile)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Authentication | `rider-app/app/(auth)/` | Firebase phone OTP + JWT | Surface refresh-token rotation errors to user; add "too many attempts" UX | User experience | 🟠 |
| Ride tracking | `rider-app/app/(tabs)/index.tsx` | Live map + driver ETA | **Phone masking** (Twilio Proxy) before showing driver number | User experience / Compliance | 🔥 |
| Deep linking | `rider-app/app.config.ts:40,61` | `applinks:spinr.app` configured | Wire OTA deep-link handler for ride share URLs (`/ride/:id`) | User experience | 🟠 |
| Offline / retry | `rider-app/services/api.ts` | Fetch wrapper, no retry | Add exponential-backoff retry on 5xx + network errors; queue pending requests | Reliability | 🟠 |
| i18n catalog | `rider-app/i18n/` | `en.json`, `fr-CA.json` only | Add `es` + `fr` to match driver-app; consolidate under `i18n/locales/` | User experience | 🟡 |
| E2E coverage | `rider-app/e2e/` + `.maestro/rider/` | 2 Maestro flows, Playwright fixtures | **Wire Maestro to CI** (currently orphaned) | Developer experience / Reliability | 🔥 |
| Accessibility | `rider-app/app/**/*.tsx` | Sparse `accessibilityLabel` coverage per `docs/ux/A11Y_AUDIT.md` | Audit with axe-core + fix missing labels on interactive elements | User experience / Compliance | 🟡 |
| Crash reporting | `rider-app/app/_layout.tsx` | Sentry optional | Make Sentry mandatory in EAS production profile | Operations | 🟠 |
| Analytics | _(none)_ | No product analytics | Add funnel events (search → book → complete) via Segment/Amplitude | Operations / Product | 🟡 |

### 1.2 `driver-app/` (Expo SDK 55 / React Native — driver mobile)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Location batching | `driver-app/services/locationTracker.ts` | Sends on every GPS tick | **Batch to 10–15s** windows + geofence deltas; reduces battery drain 40%+ | User experience / Operations | 🔥 |
| WebSocket backoff | `driver-app/hooks/useWebSocket.ts` | Reconnects immediately on drop | Add jittered exponential backoff; cap at 60s | Reliability | 🟠 |
| Heartbeat | `driver-app/services/heartbeat.ts` | Fixed 30s interval | Adapt to app state (foreground 30s / background 120s) | Operations | 🟡 |
| Navigation handoff | `driver-app/components/dashboard/` | Manual "Open in Maps" button | **Auto-handoff** to Google/Apple Maps on ride accept; deep link back | User experience | 🟠 |
| Ride-offer countdown | `driver-app/components/RideOfferCard.tsx` | 15s countdown (from `shared/config`) | Show visual urgency (color shift + haptic) at 3s | User experience | ⚪ |
| Document upload | `driver-app/app/(onboarding)/documents.tsx` | Magic-byte validated | Show upload progress + retry on network blip | User experience | 🟠 |
| i18n catalog | `driver-app/i18n/` | `en`, `es`, `fr`, `fr-CA` — most complete | **Canonical source** — migrate rider-app missing locales from here | Developer experience | 🟡 |
| Idle-panel support contact | `driver-app/components/dashboard/DriverIdlePanel.tsx` | Hardcoded `support@spinr.ca` | Move to `shared/config/spinr.config.ts` support block | Developer experience | ⚪ |
| Earnings breakdown | `driver-app/app/(tabs)/earnings.tsx` | Total-only display | Line items: fare · booking fee · surge · tips · deductions | User experience / Compliance | 🟠 |

### 1.3 `admin-dashboard/` (Next.js 14 — ops & support console)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Landing KPIs | `admin-dashboard/src/app/dashboard/page.tsx` | Table of recent rides | **KPI cards** (active rides · online drivers · p95 ETA · daily GMV) | Admin experience | 🔥 |
| Real-time tile | _(none)_ | No live updates | WebSocket tile: ride state transitions, driver online/offline | Admin experience / Operations | 🟠 |
| Incident / dispute flow | `admin-dashboard/src/app/dashboard/rides/_components/ride-flag-form.tsx`, `ride-complaint-form.tsx` | Flags + complaints forms exist | Wire into a **structured dispute queue** with states (open / investigating / resolved) | Admin experience / Compliance | 🔥 |
| Settings UI | `admin-dashboard/src/app/dashboard/settings/page.tsx:138` | Shows "OTP defaults to 1234 for testing" | Gate behind `NODE_ENV !== 'production'`; remove copy in prod | Compliance | 🟠 |
| i18n | _(none)_ | **No i18n at all** | Add `next-intl` + pull `admin.json` namespace from `i18n/locales/` | User experience | 🟡 |
| E2E | `admin-dashboard/e2e/auth.setup.ts`, `login.spec.ts` | Playwright login + axe-core | Extend to cover rides search · driver approve · payout disputes | Reliability | 🟠 |
| Dev-IP allowlist | `admin-dashboard/next.config.ts` | Hardcoded `192.168.68.63` | Remove; use env-driven allowed-origin list (tracked in `HARDCODED_VALUES_REGISTRY.md §3`) | Operations | 🟠 |
| Type safety with backend | `admin-dashboard/src/lib/api.ts` | Hand-maintained types | **OpenAPI → TypeScript codegen** on every backend merge | Developer experience | 🟠 |
| Track-page fallback | `admin-dashboard/src/app/track/[rideId]/page.tsx` | `http://localhost:8000` fallback | Fail loudly if `NEXT_PUBLIC_API_URL` unset in prod builds | Reliability | ⚪ |

### 1.4 `frontend/` (Expo web — **DEPRECATED**)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Status | `frontend/DEPRECATED.md` | Explicit deprecation marker; 42% feature parity with `rider-app` | **Delete after rider-app web export replaces it**; meanwhile block new feature PRs | Developer experience | 🟠 |
| Live Google Maps key | `frontend/test-maps.js:2`, `test-places.js:2` | Real key committed | Revoke post-testing per `HARDCODED_VALUES_REGISTRY.md §1 #3–4` | Compliance | 🔥 |

### 1.5 `shared/` (cross-app config + utilities)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Config surface | `shared/config/spinr.config.ts` | Region, phone formats, OTP, ride-offer, feature flags | Absorb per-app literals (support email, deep-link host) | Developer experience | 🟡 |
| Feature flags | `shared/config/spinr.config.ts:130,143` | `firebase.enabled`, `twilio.enabled` hardcoded `false` | Drive from `EXPO_PUBLIC_FEATURE_*` env vars | Operations | 🟡 |
| API base URL | `shared/config/spinr.config.ts:52,60` | Android `10.0.2.2`, web `localhost:8000` | Single resolver function `getApiBaseUrl({ platform, env })`; test each branch | Developer experience | 🟡 |
| TypeScript types | `shared/types/` _(missing)_ | No shared type barrel | Add types folder; re-export from OpenAPI codegen | Developer experience | 🟠 |
| Constants dedup | across apps | `REDEMPTION_RATE`, `OTP_LENGTH` duplicated in mobile + backend | Single source in `shared/`; backend reads from env populated by same config | Developer experience | 🟡 |


---

## 2. Backend & data

FastAPI monolith on Python 3.12.9 backed by Supabase (Postgres + PostGIS)
and Upstash Redis. Worker process split via `FLY_PROCESS_GROUP` gate.
Strong foundation; thin service layer and uneven test coverage are the
dominant gaps.

### 2.1 `backend/routes/` (39 files — HTTP surface)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Route count vs service layer | `backend/routes/**` + `backend/services/` | **39 route files, only 2 service classes** — business logic inlined in handlers | Extract per-domain services (`rides`, `payments`, `drivers`, `promos`, `loyalty`); routes become thin controllers | Developer experience / Reliability | 🔥 |
| Zero-test routes | `admin/support.py`, `promotions.py`, `quests.py`, `referrals.py`, `wallet.py` | Endpoints exist, no pytest coverage | Add happy-path + auth-fail + 400-input tests per route | Reliability | 🔥 |
| Idempotency | `backend/routes/webhooks.py:106` (`claim_stripe_event`) | Stripe events deduped | Extend pattern to ride-creation, payout, subscription-renewal | Reliability / Compliance | 🟠 |
| Rate-limit backend | `backend/routes/*` via `slowapi` | Uses `storage_uri="memory://"` | **Switch to Redis storage** so Fly multi-machine scale respects limits (cross-ref prod audit blocker #4) | Reliability / Compliance | 🔥 |
| OpenAPI export | _(none automated)_ | FastAPI serves `/docs` | **Codegen pipeline**: export OpenAPI → generate TS types consumed by admin + mobile | Developer experience | 🟠 |
| Pagination | multiple list endpoints | Inconsistent (`limit/offset` in some, cursor in others) | Standardize on cursor pagination; document in `docs/API.md` | Developer experience | 🟡 |
| Error responses | `backend/utils/error_handling.py` | Structured error codes + request IDs | Publish the catalog to `docs/api/ERRORS.md` for client error-handling | Developer experience | 🟡 |

### 2.2 `backend/services/` (thin service layer)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Service coverage | `backend/services/` | Only `sms_service.py` + `stripe_service.py` | Add `ride_service.py`, `driver_service.py`, `fare_service.py`, `payout_service.py` | Developer experience | 🔥 |
| SMS templates | `backend/services/sms_service.py` | English-only inline strings | Move to `i18n/locales/<lang>/notifications.json`; pass recipient locale | User experience / Compliance | 🟡 |
| Payment gateway abstraction | `backend/services/stripe_service.py` | Stripe-specific | Interface so we can plug PayPal/Interac later without route rewrite | Developer experience | ⚪ |

### 2.3 `backend/utils/` (cross-cutting helpers)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| WebSocket fan-out | `backend/socket_manager.py` + `utils/ws_pubsub.py` | Redis pub/sub exists, **silently falls back to in-process** if `UPSTASH_REDIS_URL` unset | Fail-fast on startup in prod if Redis URL missing (cross-ref prod audit blocker #9) | Reliability | 🔥 |
| Caching layer | _(missing)_ | Every settings/fares/polygon read hits Postgres | **Redis cache** with 60s TTL on read-mostly tables (`settings`, `fare_rules`, `service_areas`) | Operations / User experience | 🟠 |
| Background workers | `backend/worker.py` | 7 loops (surge, scheduled, retries, expiries, Stripe, metrics, retention) | Add per-loop liveness metric + last-run timestamp so Grafana can alert on stalls | Operations | 🟠 |
| Data retention | `backend/utils/data_retention.py` | Deletes stripe events >90d, refresh tokens >7d | Add PII redaction for closed accounts (PIPEDA) | Compliance | 🟠 |
| Refresh tokens | `backend/utils/refresh_tokens.py` | Rotation + `token_version` revocation | Add `/auth/sessions` endpoint so users can view + revoke own sessions | User experience | 🟡 |
| Metrics | `backend/utils/metrics.py` | Prometheus exporter on `0.0.0.0` | Add histograms for dispatch latency, payment latency, WS message round-trip | Operations | 🟠 |

### 2.4 `backend/alembic/` (canonical migrations)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Migration count | `backend/alembic/versions/` | 9 forward-only migrations (`0001_baseline` → `0009_postgis_geography`) | Add `schema_migrations` provenance table surfaced in `/health/deep` | Operations | 🟡 |
| Rollback scripts | `backend/alembic/versions/*.py` | `downgrade()` mostly empty | Implement reversible downgrades for last 3 migrations at minimum | Reliability | 🟠 |
| Pre-merge check | `.github/workflows/ci.yml` | No migration-dry-run step | Add job: spin ephemeral Postgres · `alembic upgrade head` · `alembic downgrade -1` | Reliability | 🟠 |

### 2.5 `backend/migrations/` (legacy SQL — parallel to Alembic)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Legacy SQL files | `backend/migrations/*.sql` | **27 pre-Alembic SQL files** with duplicate prefixes (`10_disputes_table.sql` vs `10_service_area_driver_matching.sql`) | **Archive** to `backend/migrations/_legacy/`; verify each has been absorbed into Alembic baseline | Reliability / Developer experience | 🔥 |
| RLS script | `backend/migrations/supabase_rls.sql` | Enables RLS on 19 tables | Convert to Alembic op; add **RLS policy integration tests** that fail on drift | Compliance / Reliability | 🔥 |
| RLS coverage audit | `backend/migrations/rls_audit.sql` | Audit script exists, never run | Wire into CI post-migration step; fail build if any table has `rowsecurity=false` | Compliance | 🟠 |

### 2.6 `backend/tests/` (pytest suite)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Overall coverage | `backend/tests/` | ~80% target per CI config | Raise threshold to 85%; enforce per-module `--cov-fail-under` so hot modules can't regress | Reliability | 🟠 |
| Integration tests | `backend/tests/test_*.py` | Mostly unit tests against mocked Supabase | Add **integration suite** against a real ephemeral Postgres + Upstash Redis | Reliability | 🟠 |
| RLS tests | _(none)_ | Zero tests verify RLS policies | Add `test_rls_policies.py` using non-service-role JWT; verify every table denies cross-tenant reads | Compliance | 🔥 |
| WebSocket tests | _(limited)_ | Basic connect/heartbeat test | Add dispatch-across-machines test (2 workers via Redis pub/sub) | Reliability | 🟠 |
| Fixtures | `backend/tests/conftest.py:8` | `admin@spinr.ca`, `+1234567890` hardcoded | Move to env-configurable fixtures so contributors can vary safely | Developer experience | ⚪ |

### 2.7 Data model hotspots

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| `rides` table scale | `backend/alembic/versions/*_rides*.py` | Single table, no partitioning | **Plan monthly range partition** on `created_at` before it crosses 10M rows; migrate with `pg_partman` | Operations / Reliability | 🟠 |
| Spatial index | `backend/alembic/versions/20260414_0009_postgis_geography.py` | PostGIS migration applied | Verify `GIST` indexes on `driver_location`, `ride_pickup`, `ride_dropoff`; add `EXPLAIN` tests | Operations | 🟡 |
| Foreign-key audit | DB | Unknown FK coverage | Script: list all tables without PK or without outbound FK; decide per-case | Reliability | 🟡 |
| Backup / DR drill | _(manual)_ | Supabase PITR exists | Document + run a restore drill; record RTO/RPO in `docs/audit/production-readiness-2026-04/` | Operations / Compliance | 🟠 |


---

## 3. Infra, ops & docs

CI is strong (Trivy, TruffleHog, Dependabot, Playwright, axe-core). Infra
observability and pre-commit hygiene are the weak links. Deploy surface
is fragmented across 4 vendors; should be consolidated to 2.

### 3.1 `.github/workflows/` (CI/CD)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Pipeline | `ci.yml` (598 lines) | pytest, ESLint, Playwright, Trivy, TruffleHog, EAS build | **Wire `.maestro/` mobile E2E** to mobile build job | Reliability | 🔥 |
| Load testing | `ci.yml` | No k6 step | Nightly job: run `ops/loadtest/k6-api-baseline.js` against staging; fail on p95 regression | Reliability | 🟠 |
| Migration check | `ci.yml` | No alembic dry-run | Add ephemeral Postgres job that runs `upgrade head` + `downgrade -1` | Reliability | 🟠 |
| Secret rotation | _(manual)_ | Fly secrets via CLI | Script + runbook: quarterly key rotation checklist referencing `HARDCODED_VALUES_REGISTRY.md §8` | Compliance | 🟠 |
| Synthetic probes | `synthetic-health.yml` | Fly + Render health pings every 5m | Extend to ride-lifecycle synthetic (book → accept → complete on a test fixture) | Reliability | 🟠 |
| Test-env workflow | `test-env.yml:109` | Points at Railway test env | Ensure parity with prod Fly config or mark explicitly `offline-contract-only` | Developer experience | 🟡 |
| Upstream sync | `upstream-sync.yml` | Mirrors from `srikumarimuddana-lab/spinrvm` | Document the purpose in `docs/ops/UPSTREAM_SYNC.md`; restrict write scope | Operations | ⚪ |

### 3.2 `ops/` (SRE & operational tooling)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Grafana dashboard | `ops/grafana/spinr-overview.json` | Request rate + p95 latency only | Expand with **USE metrics** (CPU/mem/disk on Fly), **rider/driver SLIs** (dispatch latency, match success %), **business KPIs** (GMV, active rides, driver utilization) | Admin experience / Operations | 🔥 |
| Alertmanager | `ops/alertmanager/alertmanager.yml` | Slack `#spinr-alerts`, SMTP `alerts@spinr.app` | Add Opsgenie/PagerDuty escalation for P0; silence logic for known drills | Operations | 🟠 |
| Prometheus alerts | `ops/prometheus/alerts.yml` (69–256) | 9 alert rules with runbook URLs | Extend to cover: WS fan-out lag, worker loop stall, Stripe webhook backlog | Operations | 🟠 |
| Runbooks | `ops/runbooks/` | Covers 6 of 9 P0 incident types | Author remaining 3: **WS pub/sub outage**, **Stripe webhook replay flood**, **driver geofence service degraded** | Operations | 🟠 |
| Load test scripts | `ops/loadtest/k6-api-baseline.js` | Saskatoon bbox, p95<400ms threshold | Add a second profile for driver-heavy load (dispatch + WS); baseline each profile quarterly | Reliability | 🟠 |
| Synthetic seed | `scripts/seed_loadtest.py` | **Missing** (referenced by loadtest) | Author seed script for test riders/drivers so k6 has realistic fixtures | Reliability | 🟠 |

### 3.3 `docs/` (engineering + ops + audit docs)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Production readiness audit | `docs/audit/production-readiness-2026-04/` | 10-document audit (indexed in `00_INDEX.md`) — 90/92 findings resolved | Schedule next audit cadence (quarterly); track delta in `docs/audit/YYYY-MM/` | Compliance | 🟡 |
| A11y audit | `docs/ux/A11Y_AUDIT.md` | Checklist + rider-app findings | Re-run with axe-core on every release; publish diff in audit folder | User experience / Compliance | 🟡 |
| API reference | _(none)_ | Only FastAPI-auto `/docs` | Commit OpenAPI spec to `docs/api/openapi.json`; generate HTML site from it | Developer experience | 🟡 |
| Onboarding | `docs/onboarding/` _(thin)_ | Minimal | **Developer 30-min quickstart**: `make bootstrap` + "where do I find X" index | Developer experience | 🟠 |
| Incident postmortems | `docs/incidents/` _(missing)_ | No postmortem template | Add `INCIDENT_TEMPLATE.md` + first blameless postmortem once real incidents happen | Operations | 🟡 |

### 3.4 `fly.toml`, `render.yaml`, `Dockerfile` (deploy surface)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Fly machines | `fly.toml:32` | `min_machines_running = 0` per registry | **Set to 1 for app + worker** (per prod audit blocker #7 — already acknowledged resolved in `00_INDEX.md` but verify) | Reliability | 🔥 |
| Multi-region | `fly.toml:2` | Single region `sjc` | Add `yyz` for Canadian latency; wait until WS Redis fan-out verified | User experience | 🟡 |
| Render fallback | `render.yaml:15` | Python `3.9.0` — stale | Bump to 3.12.x to match `Dockerfile:2` (or retire Render fallback entirely) | Developer experience | 🟠 |
| Docker base tag | `backend/Dockerfile:5,23` | Rolling `python:3.12-slim` | Pin to `python:3.12.9-slim` like root `Dockerfile:2` | Reliability | 🟡 |
| Deploy vendor sprawl | Fly + Render + Vercel + EAS | 4 vendors | **Consolidate to Fly (backend) + Vercel (admin)**; mobile stays on EAS; retire Render post-testing | Operations | 🟠 |

### 3.5 `.husky/` (git hooks)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Hook coverage | `.husky/` | Only `commit-msg` (commitlint) | Add **`pre-commit`**: lint-staged + secret scan (`trufflehog filesystem`) | Developer experience / Compliance | 🔥 |
| Pre-push | _(missing)_ | None | Optional: quick `pytest -m "not slow"` on touched test files | Reliability | ⚪ |

### 3.6 `.maestro/` (mobile E2E)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Flow coverage | `.maestro/rider/`, `.maestro/driver/` | 2 rider + 2 driver flows | Add: driver document upload, rider payment-failure retry, rider ride-cancellation | Reliability | 🟠 |
| CI wiring | `.github/workflows/ci.yml` | **Not wired** | Add mobile-e2e job using `mobile-dev-inc/action-maestro-cloud` with EAS build artifact | Reliability | 🔥 |
| Flake detection | _(none)_ | First CI run will determine flake rate | Record retry count; quarantine flaky flows rather than disabling | Reliability | 🟡 |


---

## 4. Auxiliary / meta / compliance

Everything that isn't a shipped module but still lives in the repo:
archived work, compliance stubs, agent tooling, memory docs, and hidden
meta folders. These are mostly cheap wins — a lot of deletion and
renaming, little code to write.

### 4.1 `discovery/` (MongoDB-era artefacts)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Status | `discovery/` | Dormant; references deprecated MongoDB stack | **Archive**: move to `archive/discovery/` or delete post-testing | Developer experience | 🟠 |
| Reports | `discovery/**/*.md` | Legacy architectural reports | Cross-check against `docs/audit/` and merge anything still relevant into current audit | Developer experience | 🟡 |

### 4.2 `compliance/` (regulatory stubs)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Background checks | `compliance/background-checks/README.md` | Stub; references `onboarding_status.py`, `documents.py` | **Integrate Checkr (or Certn for Canada)** — webhook into driver onboarding state machine | Compliance / Operations | 🔥 |
| Insurance | `compliance/insurance/README.md` | Stub; references ride lifecycle hooks + disputes | Vendor integration stub: mirror Uber/Lyft commercial-auto per-trip insurance hand-off | Compliance | 🟠 |
| Fraud detection | `compliance/fraud-detection/README.md` | Stub; references admin flag/complaint UI, validators | Add **velocity rules** (cancels/hour, new-card+new-device+high-fare); feed existing flags UI | Operations / Compliance | 🟠 |
| Umbrella README | `compliance/README.md` _(missing)_ | No top-level index | Author `compliance/README.md` tying the three subfolders together | Developer experience | ⚪ |
| Privacy policy + ToS | `backend/routes/legal.py` _(if exists)_ / admin settings | ToS + Privacy Policy stored as **empty strings in DB** per prod audit | Populate with legal-reviewed copy in `docs/legal/`; seed DB from there | Compliance | 🔥 |

### 4.3 `agents/` (LLM agent tooling)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Agent definitions | `agents/*.py` | `orchestrator`, `code_reviewer`, `backend_agent`, `frontend_agent`, `tester`, `deployer`, `documenter`, `security_agent` | Document when each is invoked in `agents/README.md` | Developer experience | 🟡 |
| Knowledge base | `agents/knowledge_base.py` + `agents/knowledge/tasks/*.json`, `agents/knowledge/reviews/*.json` | Persistent per-task/per-review records | **Consolidate** with `memory/` or explicitly split: agent runtime store stays in `agents/knowledge/`, human-curated records in `memory/` | Developer experience | 🟡 |
| Agent output retention | `agents/knowledge/` | No TTL | Add cleanup policy (keep last 90d by default) | Operations | ⚪ |

### 4.4 `memory/` (curated long-term records)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Active records | `memory/HARDCODED_VALUES_REGISTRY.md`, `README.md`, **this file** | 2 curated docs + index; this file makes 3 | Adopt suggested folder layout (`decisions/`, `patterns/`, `debt/`) as registry grows past 5 docs | Developer experience | ⚪ |
| Index | `memory/README.md` | Currently lists only `HARDCODED_VALUES_REGISTRY.md` | **Add link to `MODULE_ENHANCEMENT_REGISTRY.md`** (done in sub-task 7) | Developer experience | 🔥 |
| ADR stream | `memory/decisions/` _(missing)_ | No architectural decision records yet | Seed 3 ADRs: (1) Alembic over raw SQL, (2) Redis WS fan-out, (3) Stripe SAQ-A boundary | Developer experience | 🟡 |

### 4.5 `i18n/` (shared translation scaffold)

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Catalog fragmentation | `rider-app/i18n/` (en, fr-CA), `driver-app/i18n/` (en, es, fr, fr-CA), admin (none) | Per-app catalogs, drift risk | **Centralize** under `i18n/locales/<lang>/<namespace>.json`; apps import via `@spinr/i18n` workspace or relative path | User experience / Developer experience | 🟠 |
| Missing namespaces | _(none)_ | Backend SMS/push/email strings inline in Python | Add `i18n/locales/<lang>/notifications.json`; backend reads via `accept-language` header | User experience | 🟠 |
| Tooling | `i18n/scripts/` _(missing)_ | No extract/sync/lint scripts | Author `extract-keys`, `sync-to-apps`, `lint-missing` scripts | Developer experience | 🟡 |
| Locale negotiation | backend | No `Accept-Language` handling | Add FastAPI dependency that parses header + selects catalog per request | User experience | 🟡 |

### 4.6 Hidden meta folders

| Area | Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|---|
| Master roadmap | `.kilo/plans/1776144706168-quick-moon.md` | Comprehensive roadmap — canonical per prior research | Cross-link from `README.md` and `docs/audit/00_INDEX.md` so it's discoverable | Developer experience | 🟠 |
| Agent roles | `.agents/` | Role + workflow docs | Dedupe with `agents/` (Python) — one is docs, one is code; clarify in each's README | Developer experience | 🟡 |
| Emergent.sh | `.emergent/` | Dormant config for Emergent.sh tool | Delete or document reason for keeping | Developer experience | ⚪ |
| Claude Code settings | `.claude/settings.json`, `.claude/settings.local.json` | Per-repo Claude Code config | Audit permissions; lock to read-only tools + specific allowlist | Developer experience | 🟡 |
| Graphify output | `graphify-out/` | **Missing** — `CLAUDE.md` references `graphify-out/GRAPH_REPORT.md` | **Fix**: either generate graph (`python3 -m graphify code .`) or remove the reference from `CLAUDE.md` | Developer experience | 🔥 |


---

## 5. Root cleanup, cross-cutting themes & priority summary

### 5.1 Root directory clutter

The repo root contains 17+ MD files and 8 stale JSON snapshots that
accumulated from prior audits and agent runs. Most should move to `docs/`
or be deleted outright.

| Path | What exists | Enhancement | Value-add | Priority |
|---|---|---|---|---|
| `ANALYSIS_REPORT.md`, `ARCHITECTURE.md`, `CODE_ANALYSIS_REPORT.md`, `CODE_REVIEW_REPORT.md`, `GAP_ANALYSIS.md`, `READINESS_REPORT.md`, `TODO.md` (and 10 more) | Historical agent reports at repo root | Move to `docs/reports/YYYY-MM/` with ISO-dated subfolders | Developer experience | ✅ 2026-04-17, commit `67127cf` |
| `code_review_report_*.json` (×8) | Stale JSON snapshots | Delete; `agents/knowledge/reviews/` is the canonical store | Developer experience | ✅ 2026-04-17, commit `0126563` |
| `CLAUDE.md` | Claude Code project instructions | Remove stale `graphify-out/` reference OR generate the graph (see §4.6) | Developer experience | ✅ 2026-04-17, commit `b5e99a2` |
| `README.md` | Project root readme | Link to `docs/audit/00_INDEX.md`, `.kilo/plans/1776144706168-quick-moon.md`, and `memory/` | Developer experience | 🟠 |
| `package.json` / `turbo.json` / `pnpm-workspace.yaml` _(if present)_ | Monorepo wiring | Verify all apps listed; add `i18n` as a workspace once centralized | Developer experience | 🟡 |

### 5.2 Cross-cutting themes

Patterns that recur across the five module groups. Fix one theme, and
multiple individual findings close together.

| Theme | Where it hurts | Root cause | Fix |
|---|---|---|---|
| **Test coverage in 3 tiers** | RLS (0 tests), integration (thin), mobile E2E (not in CI) | Growth outpaced test investment | RLS test suite (§2.6) + Maestro CI (§3.6) + integration harness with ephemeral deps (§2.6) |
| **Observability thin** | Grafana 2 panels, no SLO alerts, no business KPIs | Dashboards bolted on late | Expand `ops/grafana/spinr-overview.json` + USE + RED + business KPIs (§3.2) |
| **Secret & constant sprawl** | Live keys in git, business constants inlined | No vault, no settings table | Follow `HARDCODED_VALUES_REGISTRY.md §8` rotation plan + move business constants to DB-backed settings |
| **i18n drift** | Rider missing es/fr, admin no i18n, backend English-only | No central catalog | Centralize in `i18n/locales/` + backend namespace (§4.5) |
| **Deploy vendor sprawl** | Fly + Render + Vercel + EAS — 4 vendors | Phased adoption never pruned | Retire Render fallback post-testing; document 2-vendor target (§3.4) |
| **Service-layer thinness** | 39 routes, 2 services — logic in controllers | Routes grew faster than services | Extract per-domain services (§2.2) — pays down testability gap simultaneously |

### 5.3 Priority summary — top 15 enhancements

Ranked by (user-visible impact × ops risk reduced × effort inverse).
Cross-references the 🔥 items from each section.

| # | Enhancement | Module | Section | Reason |
|---|---|---|---|---|
| 1 | Wire `.maestro/` mobile E2E to CI | `.maestro/`, `.github/workflows/ci.yml` | 1.1, 3.1, 3.6 | 4 flows ready but orphaned; closes mobile regression gap overnight |
| 2 | Fix `CLAUDE.md` graphify reference (or generate `graphify-out/`) | Root, `.claude/` | 4.6, 5.1 | Broken instruction; trivial to fix |
| 3 | Expand Grafana dashboard with SLIs + business KPIs | `ops/grafana/spinr-overview.json` | 3.2 | Can't see production pulse today |
| 4 | Add Redis caching for settings/fares/polygons | `backend/utils/` | 2.3 | Every request hits Postgres unnecessarily |
| 5 | Archive `backend/migrations/` legacy SQL | `backend/migrations/` | 2.5 | 27 SQL files parallel to Alembic — drift risk |
| 6 | Phone masking (rider ↔ driver) via Twilio Proxy | `rider-app/`, `driver-app/`, `backend/` | 1.1 | PII exposure + compliance |
| 7 | Move root MD reports → `docs/reports/` + delete stale JSON | Root | 5.1 | ✅ 2026-04-17 — moved to `docs/reports/2026-Q1/` (`67127cf`) + JSON deleted (`0126563`) |
| 8 | Add pre-commit secret-scan hook | `.husky/` | 3.5 | Prevents next leaked key |
| 9 | Admin dashboard KPI cards + real-time tile | `admin-dashboard/` | 1.3 | Ops team currently flies blind |
| 10 | Thicken service layer (routes → services) | `backend/routes/`, `backend/services/` | 2.1, 2.2 | Blocks testability of whole backend |
| 11 | RLS policy integration tests | `backend/tests/`, `backend/migrations/supabase_rls.sql` | 2.5, 2.6 | RLS drift goes undetected |
| 12 | OpenAPI → TypeScript codegen pipeline | `admin-dashboard/`, `shared/`, `.github/workflows/` | 1.3, 1.5, 2.1 | Type drift between mobile/admin and backend |
| 13 | Consolidate i18n catalogs into `i18n/locales/` | `i18n/`, `rider-app/`, `driver-app/`, `admin-dashboard/`, `backend/` | 4.5 | 3 apps, 3 drift vectors today |
| 14 | Background-check vendor integration (Checkr / Certn) | `compliance/background-checks/`, `backend/` | 4.2 | Onboarding compliance gap |
| 15 | Archive `discovery/` (MongoDB-era) | `discovery/` | 4.1 | Stale context clutters new-dev ramp |

Cross-links for execution:
- **Secrets / constants:** follow [`HARDCODED_VALUES_REGISTRY.md §8`](./HARDCODED_VALUES_REGISTRY.md#8-post-testing-remediation-queue-priority-order)
- **Compliance / audit blockers:** follow [`../docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md`](../docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md)
- **Master roadmap:** [`.kilo/plans/1776144706168-quick-moon.md`](../.kilo/plans/1776144706168-quick-moon.md)

### 5.4 Maintenance

This document is **living**. When an item ships:
1. Mark it ✅ in its row (don't delete — retain history for review).
2. Note commit SHA in the row.
3. Re-run the folder audit if structural changes were made (folders added/removed).

Re-catalog cadence: **monthly** until first production launch, then
**quarterly** aligned with the prod audit cycle.

---

## 6. Reconciliation with existing research artifacts

Added **2026-04-17** after an OODA pass against the prior-work artifacts
the registry originally only cross-referenced. Several sections above
were written without consulting the `10_COMPLETION_REPORT.md` and
therefore flagged items as gaps that have already shipped. This
section records the reconciliation, with **spot-checked evidence**
from the actual files rather than relying on the completion report's
prose.

### 6.1 Artifacts consulted

| Artifact | Location | Pages read | Relevance |
|---|---|---|---|
| Production readiness audit — INDEX | `docs/audit/production-readiness-2026-04/00_INDEX.md` | full | Top-10 blockers, scope |
| Roadmap & launch checklist | `docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md` | p.1–100 | Phase 0–4 status with commit SHAs |
| Completion report | `docs/audit/production-readiness-2026-04/10_COMPLETION_REPORT.md` | p.1–100 | 92 findings, 90 resolved, 2 deferred |
| Master roadmap (kilo) | `.kilo/plans/1776144706168-quick-moon.md` | p.1–80 | Pre-audit gap analysis — now superseded |
| Stale agent review snapshots | `code_review_report_*.json` (×8) | 2026-03-26 | **Pre-audit state** — superseded by completion report; safe to delete |
| Hardcoded values registry | `memory/HARDCODED_VALUES_REGISTRY.md` | full | Secret + constant companion |

**Artifacts discovered but missing:**
- `docs/audit/production-readiness-2026-04/01_…md` through `08_…md`
  — the 10-doc bundle INDEX references only has 3 files on disk
  (INDEX, ROADMAP, COMPLETION). The topic-specific audit docs were
  either never committed or removed during cleanup. INDEX should
  be corrected to match.
- `graphify-out/` — referenced by `CLAUDE.md`, never generated.

### 6.2 Registry corrections (items already ✅ shipped)

Spot-checked against actual files, not just the completion report's claims.

| Registry § | Row | Audit status | Verified in file | Correction |
|---|---|---|---|---|
| 1.3 | admin-dashboard has no i18n | ✅ done (Phase 4.1, `3db92bf`) | `admin-dashboard/messages/en.json`, `fr-CA.json` present | ✅ **Done** — locale files exist; registry row can close. Enhancement becomes: *add `es` + `fr` + backend namespace sync* |
| 1.1 | `rider-app` missing offline/retry | ✅ done (Phase 4.4, `0717d40`) | Alembic `0007_ride_idempotency`, `Idempotency-Key` header in `rider-app/store/rideStore.ts` | ✅ **Done for rides**. Residual: non-ride endpoints still lack retry. |
| 1.1 | `rider-app` on Expo SDK 55 upgrade | ✅ done (Phase 4.3, `8ab2529`) | — | ✅ **Done** — registry already assumed SDK 55 |
| 2.3 | WebSocket fan-out silently degrades | ✅ shipped (Phase 2.1) | `backend/utils/ws_pubsub.py` + `socket_manager.py` | ⚠️ **Partial** — pubsub ships, but fallback still silent per source. Harden fail-fast in prod still open. |
| 2.3 | Prometheus metrics | ✅ done (Phase 2.3) | `backend/utils/metrics.py` exporter live | ✅ **Done** for liveness; business + dispatch histograms still open |
| 2.4 | Alembic bootstrap + CI migration check | ✅ done (Phase 0.6) | `backend/alembic/versions/0001_baseline`–`0009_postgis_geography`; CI has `upgrade head --sql` | ✅ **Done** — only residual is reversible downgrades for last 3 migrations |
| 2.6 | Sentry optional | ✅ mandatory (Phase 2.2) | — | ✅ **Done** — registry stale |
| 2.7 | Multi-region deploy / backup drill | ✅ done (Phase 4.10 `bd3322d`, 4.8 `0e75ba7`) | `docs/ops/STAGING_PARITY.md` | ✅ **Done** |
| 3.1 | k6 not in CI | ✅ done (Phase 2.5) | `.github/workflows/ci.yml:538` `Phase 2.5e — k6 smoke` | ✅ **Done** — registry was stale |
| 3.2 | Grafana 2 panels only | ✅ expanded (Phase 2.3) | `ops/grafana/spinr-overview.json` has **13 panels** (`grep -c "title"`) | ✅ **Done** — residual: rider/driver SLIs + business KPIs still thin |
| 3.2 | Synthetic probes | ✅ done (Phase 2.6) | `.github/workflows/synthetic-health.yml` | ✅ **Done**; ride-lifecycle synthetic still open |
| 3.4 | Backup/DR drill missing | ✅ done (Phase 4.8, `0e75ba7`) | — | ✅ **Done** — registry stale |
| 4.2 | ToS/Privacy empty in DB | ✅ done (Phase 3.3) | — | ✅ **Done** per audit; verify seed seeded in prod DB |
| 4.2 | Compliance stubs — privacy/PIPEDA | ✅ done (Phase 3.1, 3.2, 3.5) | — | ✅ **Done** — Background-check vendor + fraud still open |

### 6.3 Registry corrections (gaps the audit missed or got wrong)

| Registry § | Row | Audit claim | Verified in file | Reality |
|---|---|---|---|---|
| 3.4 | `fly.toml:32 min_machines_running = 0` | ✅ set to 1 (Phase 0.1) | `grep -n "min_machines" fly.toml` → **line 32: `min_machines_running = 0`** | 🔥 **NOT FIXED.** Completion report is wrong. Comment at `fly.toml:28` says "keep min_machines=1 on …" but line 32 is `0`. **Production risk — background loops halt on idle.** |
| 2.5 | 27 legacy SQL files | — | `ls backend/migrations/*.sql \| wc -l` → **28** | Close enough; registry figure off by 1 — update to 28 |
| 4.1 | `discovery/` = MongoDB-era | — | `ls discovery/` shows `_layout.tsx`, `app.config.ts`, `babel.config.js`, `schema.sql` | **Wrong characterization.** It's an Expo skeleton + spec docs (`features.md`, `report.md`, `security.md`, `schema.sql`), not MongoDB. Still stale, but for different reason. |
| 5.1 | 17 MD files at root | — | `ls /home/user/Spinr/*.md \| wc -l` → **15** | Off by 2 |
| 4.6 | `graphify-out/` missing | — | Confirmed missing | Registry correct |
| 6.1 | `docs/audit/` 10-doc bundle | — | Only 3 files present (`00_INDEX`, `09_ROADMAP`, `10_COMPLETION`) | **Docs 01–08 referenced in INDEX do not exist on disk.** Either remove references or restore the files. |

### 6.4 Residual gaps (post-reconciliation)

After removing ✅ items, these are the **truly still-open** enhancements
the registry's priority summary (§5.3) should focus on:

| # | Enhancement | Section | Why still open | Priority |
|---|---|---|---|---|
| 1 | **Fix `fly.toml:32 min_machines_running = 0` → 1** | 3.4 | Completion report claims done; **file disagrees** | ✅ 2026-04-17, commit `a83ecc2` |
| 2 | Restore or remove `docs/audit/` 01–08 references in INDEX | 6.1 | Broken documentation | ✅ 2026-04-17, commit `85f289a` |
| 3 | WebSocket multi-machine (deferred P2 from audit §1 summary) | 2.3 | Pubsub exists but horizontal-scale deployment + sticky sessions not finished | 🟠 |
| 4 | A11y completion on remaining 8 mobile screens (deferred P2) | 1.1, 1.2 | `docs/ux/A11Y_AUDIT.md` tracks; 4/12 screens done, 8 left | 🟠 |
| 5 | Wire `.maestro/` mobile E2E to CI | 3.6 | Still orphaned per ci.yml grep | ✅ 2026-04-17, commit `8aabf03` |
| 6 | Fix `CLAUDE.md` → `graphify-out/` reference | 4.6, 5.1 | Broken tool instruction | ✅ 2026-04-17, commit `b5e99a2` |
| 7 | Harden WS pubsub fail-fast (no silent fallback) | 2.3 | Pubsub ships but degrades silently if Redis URL unset | 🟠 |
| 8 | Redis caching for read-hot (settings/fares/polygons) | 2.3 | Not addressed in audit phases | 🟠 |
| 9 | Service-layer thickening (routes → services) | 2.1, 2.2 | Not addressed in audit phases | 🟠 |
| 10 | RLS policy integration tests (drift detection) | 2.5, 2.6 | Policies closed (Phase 1.2) but no test that breaks on regression | 🔥 |
| 11 | OpenAPI → TypeScript codegen | 1.3, 1.5, 2.1 | Not addressed in audit phases | 🟠 |
| 12 | Phone masking (rider ↔ driver) via Twilio Proxy | 1.1, 1.2 | Not addressed in audit phases | 🔥 |
| 13 | Archive `backend/migrations/` legacy SQL (28 files) | 2.5 | Alembic is canonical; legacy is drift risk | 🟠 |
| 14 | Background-check vendor integration (Checkr / Certn) | 4.2 | Stub only; audit marked compliance done but vendor integration still open | 🔥 |
| 15 | Archive `discovery/` (Expo skeleton + legacy specs) | 4.1 | Dormant code path | 🟠 |
| 16 | Admin dashboard KPI cards + live tile | 1.3 | Not addressed in audit phases | 🟠 |
| 17 | Dedupe JWT_SECRET definitions in `backend/.env.example` | `HARDCODED_VALUES_REGISTRY.md §8 #7` | Cheap post-testing cleanup | 🟡 |
| 18 | Rotate Supabase service_role key + git history purge | `HARDCODED_VALUES_REGISTRY.md §8 #1` | Live credential in repo | 🔥 post-testing |
| 19 | Restrict/rotate Google Maps key `AIzaSyC5i7lh...m9M` | `HARDCODED_VALUES_REGISTRY.md §8 #2` | Live key in two committed test scripts | 🔥 post-testing |
| 20 | Delete stale `code_review_report_*.json` (×8) | 5.1 | Pre-audit (2026-03-26), superseded | ✅ 2026-04-17, commit `0126563` |

### 6.5 Maintenance rule

Going forward, any claim "X is done" in this registry or in a sister
audit must be **verified against the filesystem** before being cited.
Prose-only completion reports are advisory, not authoritative. Row
updates should include:

- Commit SHA (if known)
- File path + line number of evidence
- Date of verification

Specifically for this registry: when an enhancement in §1–5 lands,
add a ✅ marker **and** a short parenthetical citation like
`(✅ 2026-04-17 — backend/routes/foo.py:42, commit abc1234)`.

### 6.6 Artifact retention policy

| Artifact class | Retention | Rationale |
|---|---|---|
| `docs/audit/production-readiness-YYYY-MM/` | Permanent | Compliance evidence |
| `code_review_report_*.json` | **Delete** on next cleanup pass | Pre-audit snapshots, superseded |
| Root `*.md` reports (15 files) | Move to `docs/reports/2026-Q1/` | Historical context, not current state |
| `.kilo/plans/*.md` | Keep as narrative roadmap; link from README | Product thinking, not code |
| `agents/knowledge/tasks/*.json`, `reviews/*.json` | Keep 90 days rolling | Runtime store for agents |
| `memory/*.md` | Permanent, curated | Long-term human-reviewed records |
| `discovery/` | Archive to `archive/discovery-2025/` | Legacy Expo skeleton + spec docs |


