# Hard-Coded Values, Secrets & Keys Registry

> **Status:** Active tracking list. **Not** a blocker queue.
> **Created:** 2026-04-16 (multi-role product audit)
> **Policy:** Items remain in place until testing finishes. This file
> is the persistent reminder so nothing is forgotten at post-testing
> cleanup, and so future reviewers don't re-flag them as new findings.

Severity key (advisory only):
- 🔴 **Live credential in git** — must rotate + purge post-testing
- 🟠 **Sensitive but scoped** — dev/test only, or public-by-design
- 🟡 **Config that should be DB/env-driven** — tech debt
- ⚪ **Intentional infra literal** — expected (hostnames, image tags)

---

## 1. Real secrets / live credentials in repo

| # | File:Line | Module | Category | Value (redacted) | Severity | Notes |
|---|---|---|---|---|---|---|
| 1 | `backend/.env.example:3` | backend | SUPABASE_SERVICE_ROLE | `eyJhbGci...6wZH_E` (decoded: `role=service_role`, `exp=2086412564` / yr 2036) | 🔴 | Real JWT on `origin/main`. Bypasses all RLS. Rotate + git-history purge after testing. |
| 2 | `backend/.env.example:2` | backend | SUPABASE_URL | `https://dbbadhihiwztmnqnbdke.supabase.co` | 🔴 | Real project ref, pairs with #1. |
| 3 | `frontend/test-maps.js:2` | frontend | GOOGLE_MAPS_KEY | `AIzaSyC5i7lh...m9M` | 🔴 | Live Google Maps key in a committed test script. Restrict/rotate post-testing. |
| 4 | `frontend/test-places.js:2` | frontend | GOOGLE_MAPS_KEY | `AIzaSyC5i7lh...m9M` | 🔴 | Same key as #3. |
| 5 | `rider-app/google-services.json:18` | rider-app | FIREBASE_ANDROID_KEY | `AIzaSyBAgdg...GU3M`, project `spinrapp-6e464` | 🟠 | Firebase Android keys are **public-by-design**; real protection = Firebase Security Rules + App Check. Catalog only. |
| 6 | `driver-app/google-services.json:18,35` | driver-app | FIREBASE_ANDROID_KEY | same project as #5 | 🟠 | Same as above. |

## 2. `.env.example` placeholders (safe, track for consistency)

| File:Line | Module | Key | Value | Notes |
|---|---|---|---|---|
| `backend/.env.example:6,15` | backend | `JWT_SECRET` | `your-strong-secret-key` / `replace-with-strong-random-secret` | Two lines set same var — dedupe post-testing. |
| `backend/.env.example:11` | backend | `DATABASE_URL` | `postgres://...<project-ref>...` | Template. |
| `backend/.env.example:26` | backend | `ALLOWED_ORIGINS` | `http://localhost:3000,:8081,:19006` | Example. |
| `backend/.env.example:29-30` | backend | `BOOTSTRAP_ADMIN_*` | `admin@example.com` / `replace-me` | Placeholders. |
| `rider-app/.env.example` | rider-app | EXPO_PUBLIC_* | placeholders | OK. |
| `driver-app/.env.example` | driver-app | EXPO_PUBLIC_* | placeholders | OK. |
| `admin-dashboard/.env.example` | admin-dashboard | NEXT_PUBLIC_API_URL, SENTRY_* | `http://localhost:8000` + templates | OK. |

## 3. Hard-coded URLs & hostnames

### Backend
| File:Line | Value | Severity | Notes |
|---|---|---|---|
| `backend/core/middleware.py:405` | `https://spinr-admin.vercel.app`, `http://localhost:3000`, `http://localhost:3001` | 🟡 | CORS always-allowed. `localhost` origins bypass prod `"*"` rejection. |
| `backend/utils/error_handling.py:458-459` | same two | 🟡 | Fallback CORS list. |
| `backend/test_dns.py:4` | `dbbadhihiwztmnqnbdke.supabase.co` | 🟠 | Test refs real project. |
| `backend/server.py:109` | `0.0.0.0:8000` | ⚪ | Uvicorn bind. |
| `backend/utils/metrics.py:60` | `0.0.0.0` | ⚪ | Prometheus bind. |

### Mobile / admin / shared
| File:Line | Value | Severity | Notes |
|---|---|---|---|
| `shared/config/spinr.config.ts:52` | `http://10.0.2.2:8000` | ⚪ | Android emulator alias, dev. |
| `shared/config/spinr.config.ts:60` | `http://localhost:8000` | 🟡 | Web fallback; env-overrideable. |
| `rider-app/app.config.ts:61`, `driver-app/app.config.ts:61`, `rider-app/app.config.ts:40` | `https://spinr.app` / `applinks:spinr.app` | ⚪ | Deep-link domain. |
| `admin-dashboard/next.config.ts` | `192.168.68.63` | 🟡 | Local dev IP allowed-origin. Remove post-testing. |
| `admin-dashboard/src/app/track/[rideId]/page.tsx` | `http://localhost:8000` fallback | 🟡 | Env-overrideable. |
| `frontend/app/(tabs)/index.tsx`, `account.tsx` | `http://localhost:8000` fallback | 🟡 | Env-overrideable. |

### Infra / CI
| File:Line | Value | Severity | Notes |
|---|---|---|---|
| `.github/workflows/ci.yml:514-557` (multi) | `https://spinr-api.fly.dev`, `https://spinr-api.onrender.com`, `https://spinr-api-staging.fly.dev` | ⚪ | Health + smoke literal fallbacks. |
| `.github/workflows/synthetic-health.yml:55-193` | same fly.dev hosts | ⚪ | Synthetic probes. |
| `.github/workflows/test-env.yml:109` | `https://spinr-backend-test.up.railway.app` | ⚪ | Test-env URL. |
| `.github/workflows/upstream-sync.yml:55` | `https://github.com/srikumarimuddana-lab/spinrvm.git` | ⚪ | Upstream repo ref. |
| `ops/loadtest/k6-api-baseline.js:38` | `https://spinr-api.fly.dev` | ⚪ | k6 fallback. |
| `ops/prometheus/alerts.yml:69-256` (multi) | GitHub runbook URLs | ⚪ | Alert annotations. |

## 4. Hard-coded identities (emails / phones / routing)

| File:Line | Module | Value | Severity | Notes |
|---|---|---|---|---|
| `rider-app/app/ride-completed.tsx`, `support.tsx` (×2) | rider-app | `support@spinr.ca` | ⚪ | Intentional support contact. Move to config. |
| `driver-app/components/dashboard/DriverIdlePanel.tsx` | driver-app | `support@spinr.ca` | ⚪ | Same. |
| `rider-app/e2e/fixtures.ts` | rider-app | `rider@spinr.ca` | ⚪ | E2E fixture. |
| `admin-dashboard/e2e/auth.setup.ts`, `login.spec.ts` (×2 each) | admin-dashboard | `admin@spinr.ca` | ⚪ | E2E fixtures. |
| `admin-dashboard/src/lib/__tests__/api.test.ts` | admin-dashboard | `admin@spinr.io` | ⚪ | Unit-test fixture. Mismatch with `.ca` elsewhere. |
| `backend/tests/conftest.py:8`, `perf_baseline.py:30` | tests | `admin@spinr.ca` | ⚪ | Test bootstrap. |
| `backend/tests/conftest.py`, `test_drivers.py`, `test_auth.py` (multi) | tests | `+1234567890` | ⚪ | Standard test phone. |
| `ops/alertmanager/alertmanager.yml:27` | ops | `alerts@spinr.app` | ⚪ | SMTP from. |
| `.github/workflows/upstream-sync.yml:51` | ci | `sync-bot@spinr.app` | ⚪ | Git author. |
| `ops/alertmanager/alertmanager.yml:115,133` | ops | `#spinr-alerts` | ⚪ | Slack channel literal. |

## 5. Bootstrap / dev credentials baked into code

| File:Line | Module | Value | Severity | Notes |
|---|---|---|---|---|
| `backend/core/middleware.py:218-219` | backend | `_INSECURE_ADMIN_EMAILS`, `_INSECURE_ADMIN_PASSWORDS` reject-lists | 🟠 | **These are a blocklist, not credentials** — startup rejects them. Keep the list; do not remove. |
| `admin-dashboard/src/app/dashboard/settings/page.tsx:138` | admin-dashboard | UI text: "OTP defaults to **1234** for testing" | 🟡 | Reflects backend behavior when Twilio off. Remove path before prod. |
| `admin-dashboard/e2e/auth.setup.ts` | admin-dashboard | `password: 'Test1234!'` | ⚪ | E2E test password. |
| `.github/workflows/ci.yml:69,99` | ci | `test-secret-key-for-ci-only-32chars!!`, `test-secret-key-for-ci` | ⚪ | CI test secrets. |
| `.github/workflows/ci.yml:81` | ci | `ci:ci@localhost:5432/does_not_exist` | ⚪ | Bogus offline DB URL. |
| `.github/workflows/ci.yml:96` | ci | `spinr_test` | ⚪ | Test DB name. |

## 6. Business constants (should be DB/env-driven post-testing)

| File:Line | Module | Constant | Severity |
|---|---|---|---|
| `backend/dependencies.py:36` | backend | `OTP_EXPIRY_MINUTES = 5` | 🟡 |
| `backend/dependencies.py:39` | backend | `OTP_LENGTH = 6` | 🟡 |
| `backend/schemas.py:96` | backend | `cancellation_fee_admin = 0.50`, `cancellation_fee_driver = 2.50` | 🟡 |
| `backend/schemas.py:99` | backend | `booking_fee = 2.0` | 🟡 |
| `backend/routes/fares.py:73-74` | backend | `per_km_rate = 1.50`, `per_minute_rate = 0.25` | 🟡 |
| `backend/routes/loyalty.py:63` | backend | `REDEMPTION_RATE = 100` (pts per $1) | 🟡 |
| `backend/core/config.py:17-19` | backend | `ACCESS_TOKEN_TTL_DAYS=30`, `ADMIN_ACCESS_TOKEN_TTL_HOURS=12`, `REFRESH_TOKEN_EXPIRE_DAYS=30` | 🟡 |
| `backend/utils/data_retention.py:46-50` | backend | `_PROCESSED_STRIPE_EVENT_DAYS=90`, `_EXPIRED_REFRESH_TOKEN_DAYS=7`, `BATCH_SIZE=500` | 🟡 |
| `backend/utils/stripe_worker.py:46,50` | backend | `POLL_INTERVAL_SECONDS=5`, `BATCH_SIZE=10` | 🟡 |
| `backend/socket_manager.py:11` | backend | `_WS_MAX_CONNECTIONS=1000` | 🟡 |
| `backend/core/middleware.py:60` | backend | HSTS `max-age=31536000` | ⚪ |
| `backend/core/middleware.py:228,233` | backend | `_SUPABASE_KEY_MIN_LENGTH=40`, `_MIN_JWT_SECRET_LENGTH=32` | ⚪ |
| `shared/config/spinr.config.ts:69` | shared | `version:'1.0.0'`, `region:'CA'` | 🟡 |
| `shared/config/spinr.config.ts:109` | shared | `phone placeholder:'(306) 555-0199'` | ⚪ |
| `shared/config/spinr.config.ts:116-117` | shared | `otp.length:6`, `otp.expiryMinutes:5` | 🟡 |
| `shared/config/spinr.config.ts:122-123` | shared | `rideOffer.countdownSeconds:15`, `maxRadiusMeters:5000` | 🟡 |
| `shared/config/spinr.config.ts:130,143` | shared | `firebase.enabled:false`, `twilio.enabled:false` | 🟡 |

## 7. Infra resource literals

| File:Line | Value | Notes |
|---|---|---|
| `fly.toml:1` | `spinr-backend` | App name. |
| `fly.toml:2` | `sjc` | Region. |
| `fly.toml:32` | `min_machines_running = 0` | Per audit should be `1` for app+worker; verify. |
| `fly.toml:42-43` | `shared-cpu-1x`, `512mb` | Worker VM. |
| `Dockerfile:2,22` | `python:3.12.9-slim` | Pinned. |
| `backend/Dockerfile:5,23` | `python:3.12-slim` | Rolling tag. |
| `render.yaml:6,12,15` | `oregon`, `10000`, `3.9.0` | Region, port, legacy Python version. |
| `ops/loadtest/k6-api-baseline.js:57-178` | VU stages, thresholds (`p95<400ms`, err `<0.1%`), Saskatoon bbox `52.1332,-106.6700 → 52.1708,-106.6996`, think-time `0.2–1.7s` | Intentional test config. |

## 8. Post-testing remediation queue (priority order)

1. **Rotate `SUPABASE_SERVICE_ROLE_KEY`** (§1 #1). Purge from git history. Revoke the current one at Supabase console.
2. **Restrict or rotate `AIzaSyC5i7lh...m9M`** Google Maps key (§1 #3–4). Ideally add HTTP-referrer restrictions now; full rotation after testing.
3. **Remove `localhost:3000 / 3001` from prod CORS always-allow** (§3 · backend middleware).
4. **Remove dev IP `192.168.68.63`** from `admin-dashboard/next.config.ts`.
5. **Move business constants** (§6 · fares, booking fee, cancellation fee, countdown, radius) into DB-backed settings or env config. Reduces the need for redeploys to tune pricing.
6. **Replace `admin-dashboard` UI copy "OTP defaults to 1234"** once Twilio is mandatory in prod.
7. **Dedupe `JWT_SECRET` in `backend/.env.example`** (two definitions at lines 6 and 15).
8. **Reconcile `admin@spinr.ca` vs `admin@spinr.io`** in test fixtures (typo).
9. **Confirm `fly.toml:32 min_machines_running` is `1`** (audit P0 fix — currently shows `0` per catalog).
10. **Verify `render.yaml:15` Python version** (`3.9.0` is stale vs Docker `3.12.9`).

## 9. Critical-files index

- `backend/.env.example` (§1 #1–2, §2)
- `backend/core/middleware.py` (§3, §5, §6)
- `backend/core/config.py` (§6)
- `backend/dependencies.py` (§6)
- `backend/routes/fares.py`, `routes/loyalty.py`, `schemas.py` (§6)
- `backend/utils/data_retention.py`, `stripe_worker.py`, `socket_manager.py` (§6)
- `frontend/test-maps.js`, `test-places.js` (§1 #3–4)
- `rider-app/google-services.json`, `driver-app/google-services.json` (§1 #5–6)
- `rider-app/app.config.ts`, `driver-app/app.config.ts` (§3)
- `shared/config/spinr.config.ts` (§3, §6)
- `admin-dashboard/next.config.ts`, `src/app/dashboard/settings/page.tsx` (§3, §5)
- `fly.toml`, `Dockerfile`, `backend/Dockerfile`, `render.yaml` (§7)
- `.github/workflows/ci.yml`, `synthetic-health.yml`, `test-env.yml`, `upstream-sync.yml` (§3, §5)
- `ops/alertmanager/alertmanager.yml`, `ops/prometheus/alerts.yml`, `ops/loadtest/k6-api-baseline.js` (§3, §4, §7)

## 10. Verification (re-catalog recipe)

Quick greps to re-confirm entries on the current tree:

1. `grep -n "AIzaSyC5i7lh" frontend/` → §1 #3–4
2. `grep -n "eyJhbGci" backend/.env.example` → §1 #1
3. `grep -rn "dbbadhihiwztmnqnbdke" backend/` → Supabase project refs
4. `grep -n "localhost:300" backend/core/middleware.py backend/utils/error_handling.py` → CORS literals
5. `grep -rn "support@spinr" rider-app/ driver-app/` → §4
6. Pre-launch: re-run the three catalog searches (backend / frontend-mobile / infra) and diff against this file; new entries are either new debt or regressions.
7. Post-rotation audit: re-grep for `AIzaSy`, `eyJ`, `sk_` to confirm no live secrets remain.
