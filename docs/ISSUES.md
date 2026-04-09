# spinr — Master Issue Registry
# Version: 1.0 | Created: 2026-04-07 | Scope: Full Fortune 100 Maturity Audit

> **Coverage:** Backend · Rider App · Driver App · Frontend Web · Admin Dashboard ·
> CI/CD · Infrastructure · Claude/AI Config · .agents Framework · Compliance · Documentation
>
> **Audit basis:** Full codebase read including `backend/core/config.py`, all workflows,
> `.claude/` commands/hooks/settings, `.agents/` roles/standards/workflows, `.emergent/`, all mobile screens.

---

## Severity Scale
| Level | Definition |
|-------|-----------|
| **CRITICAL** | Exploitable in production today or blocks pilot launch entirely |
| **HIGH** | Significant risk to security, reliability, or regulatory compliance |
| **MEDIUM** | Degrades quality, developer experience, or operational capability |
| **LOW** | Technical debt, polish, best practice alignment |

## Priority Scale
| Level | SLA |
|-------|-----|
| **P0** | Fix before any code ships to production |
| **P1** | Fix within current sprint |
| **P2** | Fix within next sprint |
| **P3** | Backlog — address before public launch |

---

## CATEGORY: SECURITY (SEC)

---

### SEC-001 — Hardcoded JWT Secret Default
| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Priority** | P0 |
| **File** | `backend/core/config.py:14` — `JWT_SECRET: str = "your-strong-secret-key"` |
| **Risk** | Any attacker who sees the source code (public repo, CI logs, leaked diff) can forge valid JWT tokens and impersonate any user including admins. Full account takeover. |
| **Remediation** | Remove default. Add startup validation: `if settings.ENV != "development" and settings.JWT_SECRET == "your-strong-secret-key": raise RuntimeError("JWT_SECRET must be set in production")`. Use `render.yaml`'s `generateValue: true` (already present) and rotate quarterly. |
| **Value-add** | Implement JWKS endpoint (`/.well-known/jwks.json`) for future multi-service token verification without secret sharing. |

---

### SEC-002 — Hardcoded Admin Credentials
| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Priority** | P0 |
| **Files** | `backend/core/config.py:20-21` — `ADMIN_EMAIL: str = "admin@spinr.ca"`, `ADMIN_PASSWORD: str = "admin123"` |
| **Risk** | Default credentials visible in source code. Brute-force trivial. If admin account is bootstrapped on first deploy without overriding env vars, any attacker gains full admin access. |
| **Remediation** | Remove `ADMIN_PASSWORD` from config entirely. Admin accounts must be created via Supabase Auth (MFA-enabled). Add startup assertion: if `ADMIN_PASSWORD` env var is set, raise immediately. Use Supabase admin invites. |
| **Value-add** | Replace password-based admin auth with SSO (Google Workspace / Okta) via Supabase OAuth — eliminates password surface entirely for internal tooling. |

---

### SEC-003 — CORS Wildcard Default
| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Priority** | P0 |
| **Files** | `backend/core/config.py:17` — `ALLOWED_ORIGINS: str = "*"` · `backend/core/middleware.py` |
| **Risk** | Any website can make credentialed requests to the API. Combined with user cookies or tokens, enables CSRF and cross-origin data exfiltration. |
| **Remediation** | Hardcode explicit allowlist: `["https://spinr-admin.vercel.app", "https://spinr.ca", "http://localhost:3000", "http://localhost:3001"]`. Middleware already warns on wildcard — promote that warning to a startup error in non-development environments. |
| **Value-add** | Add `Vary: Origin` response header and log rejected CORS origins to detect probing. |

---

### SEC-004 — Docker Container Security
| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Priority** | P0 |
| **File** | `backend/Dockerfile` (12 lines) |
| **Risk** | Container runs as root. A container escape or RCE gives full host access. No `.dockerignore` means test files, credentials, audit ZIPs, markdown docs are all copied into the image. No health check means Render/Fly cannot detect a silently crashed app. |
| **Remediation** | Multi-stage build (builder + runtime). Add `RUN useradd -m -u 1001 appuser && USER appuser`. Add `HEALTHCHECK CMD curl -f http://localhost:8000/health \|\| exit 1`. Add `.dockerignore` excluding `*.md`, `tests/`, `*.txt`, `*.zip`, `*.json`, `uploads/`. Python version mismatch: Dockerfile uses `python:3.12-slim` but CI uses 3.11 — pin to `python:3.11-slim`. |
| **Value-add** | Add `--read-only` filesystem flag in deployment config. Use distroless base image for smallest attack surface. |

---

### SEC-005 — Memory-Backed Rate Limiter (Not Production-Safe)
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `backend/utils/rate_limiter.py` · `backend/requirements.txt` — SlowAPI with in-memory storage |
| **Risk** | Rate limits are per-process, not per-cluster. With multiple Render/Fly instances, each instance has its own counter — an attacker gets `N × limit` requests where N is instance count. OTP brute force (3/min × N instances). |
| **Remediation** | Add `redis` + `limits[redis]` to requirements. Configure `slowapi` with Redis storage: `Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)`. Add `REDIS_URL` env var. Use Render Redis or Upstash Redis (free tier). |
| **Value-add** | Add per-user rate limiting (by `user_id` in JWT) in addition to per-IP, so VPN abuse is mitigated. |

---

### SEC-006 — No CSRF Protection
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `backend/server.py` — no CSRF middleware present |
| **Risk** | Any authenticated browser session (admin dashboard) is vulnerable to cross-site request forgery. Admin actions (ban driver, issue refund, modify fare) can be triggered by a malicious link. |
| **Remediation** | Add `fastapi-csrf-protect` middleware. Set `CSRF_SECRET_KEY` env var. Apply `@csrf_protect` decorator to all state-changing admin endpoints. Admin dashboard must send `X-CSRF-Token` header on mutations. |
| **Value-add** | Since mobile apps use bearer tokens (not cookies), CSRF only affects the admin web dashboard — scope protection to those endpoints only, reducing overhead. |

---

### SEC-007 — 4-Digit OTP (Insufficient Entropy)
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `backend/routes/auth.py` · `driver-app/app/otp.tsx` · `rider-app/app/otp.tsx` |
| **Risk** | 4-digit OTP = 10,000 combinations. With rate limit of 5/min per IP (not per phone) and memory-backed limiter (SEC-005), an attacker with multiple IPs can brute-force in minutes. Account takeover on any phone number. |
| **Remediation** | Change OTP generation to 6 digits (1,000,000 combinations). Update backend generator, Twilio message template, and both mobile OTP input fields (change `maxLength` from 4 to 6). Add per-phone-number rate limiting independent of IP. |
| **Value-add** | Set OTP expiry to 5 minutes (vs typical 10) for ride-share — users are actively waiting and expect speed, so shorter window is both safer and acceptable UX. |

---

### SEC-008 — No Secrets Scanning in CI
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `.github/workflows/ci.yml` — Trivy scans dependencies only, not secrets |
| **Risk** | A developer accidentally commits an `.env` file, Stripe live key, or Firebase credentials. The `.claude/hooks/pre-commit` hook catches this locally but is not installed automatically and `--no-verify` bypasses it. The CI has no backstop. |
| **Remediation** | Add TruffleHog GitHub Action to `ci.yml` as a blocking step: `trufflesecurity/trufflehog@main` with `--only-verified`. Run on every push and PR. Add Trivy in `--scanners secret` mode as second layer. |
| **Value-add** | Add `git-secrets` to the pre-commit hook installation instructions in `README.md` so all developers install it on clone. |

---

### SEC-009 — Trivy Scan Does Not Gate on Severity
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `.github/workflows/ci.yml` — `security-scan` job produces SARIF but does not `exit 1` on CRITICAL/HIGH |
| **Risk** | A critical CVE in a dependency ships to production silently. Trivy reports are uploaded to GitHub Security tab but no one is paged and builds succeed regardless. |
| **Remediation** | Add `--exit-code 1 --severity CRITICAL,HIGH` to Trivy CLI args. Add a separate `trivy-fs` scan of the codebase (not just Docker image). Set the `security-scan` job as a required check in branch protection rules. |
| **Value-add** | Add Trivy to PR comments via `aquasecurity/trivy-action@master` with `comment-summary-in-pr: enabled` so devs see vulnerabilities inline without leaving GitHub. |

---

### SEC-010 — No Input Size Limits
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **File** | `backend/server.py` — no max body size middleware |
| **Risk** | Memory exhaustion DoS. An attacker sends a 500MB JSON payload to any endpoint. Uvicorn will buffer it all before Pydantic validation rejects it. |
| **Remediation** | Add `ContentSizeLimitMiddleware` from `starlette_sizecontent` or configure Uvicorn's `--limit-concurrency` and `--limit-max-requests`. Set a 10MB max body limit globally, 50MB for `POST /api/documents/*` (file uploads). |
| **Value-add** | Add file type validation on the upload endpoint (check magic bytes, not just MIME type). |

---

### SEC-011 — No API Key Rotation Policy
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | GitHub Secrets (STRIPE_SECRET_KEY, TWILIO_AUTH_TOKEN, SUPABASE_SERVICE_ROLE_KEY, etc.) |
| **Risk** | Leaked secrets remain valid indefinitely. If a GitHub Actions log exposes a secret or a former employee retains access, there is no automatic invalidation. |
| **Remediation** | Document rotation schedule in `docs/SECURITY_POLICY.md`: JWT monthly, Stripe/Twilio quarterly. Add GitHub Actions workflow that checks secret age via metadata API and creates a GitHub issue when rotation is due. |
| **Value-add** | Migrate to HashiCorp Vault or AWS Secrets Manager for dynamic secret generation — especially for database credentials (Supabase service role key). |

---

## CATEGORY: INFRASTRUCTURE & DEPLOYMENT (INF)

---

### INF-001 — render.yaml Python Version Mismatch
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `render.yaml:7` — `PYTHON_VERSION: 3.9.0` · CI uses `python: '3.11'` · Dockerfile uses `python:3.12-slim` |
| **Risk** | Three different Python versions across deployment targets. Features using `3.11` syntax (e.g., `tomllib`, match-case, `ExceptionGroup`) may silently fail or error on Render. |
| **Remediation** | Pin all three to `python:3.11-slim` in Dockerfile, `python-version: '3.11'` in all CI jobs, and `PYTHON_VERSION: 3.11.x` in render.yaml. Add a CI check that compares versions across all config files. |
| **Value-add** | Add a `pyproject.toml` with `requires-python = ">=3.11"` as the single source of truth. |

---

### INF-002 — No Prometheus Metrics Endpoint
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `backend/server.py` — no `/metrics` route · `backend/requirements.txt` — no `prometheus-fastapi-instrumentator` |
| **Risk** | No visibility into request rates, error rates, latency distributions, or business metrics. Cannot set SLOs. Cannot be alerted to degradation before users notice. |
| **Remediation** | Add `prometheus-fastapi-instrumentator` to requirements. Wire in `server.py`: `Instrumentator().instrument(app).expose(app)`. Add custom counters: `rides_requested_total`, `rides_matched_total`, `payment_failures_total`, `driver_location_updates_total`. Point Grafana Cloud (free) or Render metrics to `/metrics`. |
| **Value-add** | Add a `/api/v1/metrics/business` endpoint (admin-auth required) that returns JSON business KPIs for the admin dashboard's real-time tiles. |

---

### INF-003 — No Distributed Tracing
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/server.py` — Sentry present but no OpenTelemetry spans |
| **Risk** | When a ride match fails, there is no way to see which of the 5+ Supabase calls in the chain was slow or failed. Debugging production latency issues requires guesswork. |
| **Remediation** | Add `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`. Configure OTLP exporter to Grafana Tempo or Jaeger. Instrument Supabase client calls with custom spans. |
| **Value-add** | Add trace IDs to API error responses (already have `request_id` — extend to be a valid W3C trace ID) so users can reference in support tickets. |

---

### INF-004 — No Database Migration in Deployment Pipeline
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `.github/workflows/deploy-backend.yml` — deploys code, no schema migration step · `backend/migrations/` directory exists but not used in CI |
| **Risk** | New code deploying against old schema causes runtime errors. No rollback mechanism if a migration fails mid-deploy. |
| **Remediation** | Add migration step to `deploy-backend.yml` before the deploy step: run SQL scripts from `backend/migrations/` against Supabase using `psql` with `SUPABASE_DB_URL`. Gate deploy on migration success. Add `apply-supabase-schema.yml` as a dependency. |
| **Value-add** | Adopt Alembic for versioned migrations with `alembic upgrade head` in CI — gives migration history, rollback (`alembic downgrade -1`), and dry-run capability. |

---

### INF-005 — No Post-Deploy Smoke Test
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `.github/workflows/deploy-backend.yml` · `.github/workflows/ci.yml` — deploy steps have no verification |
| **Risk** | A broken deploy goes undetected until a user or Sentry reports errors. With Fly.io/Render rolling deploys, bad instances may serve traffic for minutes. |
| **Remediation** | Add a post-deploy job that runs `curl -f https://spinr-api.fly.dev/api/v1/health`, checks HTTP 200, then calls 3 read-only API endpoints (GET `/api/v1/settings`, GET `/api/v1/vehicle-types`, GET `/api/admin/auth/session`) and validates response shape. Fail and alert on Slack if any check fails. |
| **Value-add** | Add `synthetic monitoring` via Checkly or UptimeRobot that pings these endpoints every 60 seconds from Canada-region probes — catches outages even outside of deploys. |

---

### INF-006 — Mobile Builds Only Trigger on `[build]` Keyword
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **File** | `.github/workflows/ci.yml` — `if: contains(github.event.head_commit.message, '[build]')` |
| **Risk** | Developers forget to add `[build]` to commit message. Mobile builds are never tested automatically. A broken mobile build reaches testers instead of being caught in CI. |
| **Remediation** | Trigger EAS preview builds automatically on every PR to `develop` using `eas build --profile preview --non-interactive`. Reserve production builds for merges to `main`. Use `eas-build.yml` for production, a new `eas-preview.yml` for PRs. |
| **Value-add** | Add EAS Update (OTA) for JS-only changes on `develop` branch — testers always have latest JS without waiting for full native builds. Already partially configured in `test-env.yml`. |

---

### INF-007 — No Dependabot / Renovate
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `.github/dependabot.yml` — does not exist |
| **Risk** | Dependencies go stale. CVEs accumulate silently. Manual updates are inconsistent. With 71 Python packages and 3 npm lockfiles, this is unmanageable by hand. |
| **Remediation** | Add `.github/dependabot.yml` with daily/weekly update schedules for `pip`, `npm` (4 packages), and `github-actions`. Group minor/patch updates into a single weekly PR per ecosystem to reduce noise. |
| **Value-add** | Use Renovate instead of Dependabot for more control — it can auto-merge patch updates that pass CI, dramatically reducing manual review burden. |

---

### INF-008 — Sentry Not Wired for All Environments
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/server.py:98-105` — Sentry initializes only if `SENTRY_DSN` is set · `backend/core/config.py` — no `SENTRY_DSN` field |
| **Risk** | Production errors may go unmonitored if `SENTRY_DSN` is not in the deployment env vars. No evidence it is set in `render.yaml` or `fly.toml`. |
| **Remediation** | Add `SENTRY_DSN: Optional[str] = None` to `config.py`. Add `SENTRY_DSN` to `render.yaml` env vars (sync: false). Set `traces_sample_rate=0.1` for production, `1.0` for development. Also add Sentry to admin-dashboard (`@sentry/nextjs`) and mobile apps (already have Crashlytics — add Sentry for JS errors). |
| **Value-add** | Enable Sentry Performance Monitoring to auto-capture slow FastAPI transactions (N+1 queries, slow Supabase calls) with zero additional instrumentation. |

---

## CATEGORY: CODE QUALITY (CQ)

---

### CQ-001 — No Prettier Configuration
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | Root directory — no `.prettierrc`, `.prettierignore`, or `prettier` in any `package.json` |
| **Risk** | Every developer formats code differently. PR diffs contain whitespace noise. Code reviews waste time on style instead of logic. |
| **Remediation** | Add `.prettierrc` at repo root: `{ "singleQuote": true, "trailingComma": "es5", "semi": true, "printWidth": 100, "tabWidth": 2 }`. Add `prettier` to devDependencies of admin-dashboard, rider-app, driver-app. Add `format` script to each `package.json`. |
| **Value-add** | Use `prettier-plugin-tailwindcss` in admin-dashboard to auto-sort Tailwind class names — eliminates an entire class of PR comments. |

---

### CQ-002 — No Husky Pre-commit Hooks (JS Projects)
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | Root directory — no `husky`, no `.husky/` directory · `.claude/hooks/pre-commit` exists but requires manual installation |
| **Risk** | Code with type errors, lint failures, or formatting issues reaches CI — wasting build minutes and creating review friction. The `.claude/hooks/pre-commit` security hook is excellent but not automatically active. |
| **Remediation** | Add `husky` + `lint-staged` to root `package.json` devDependencies. Configure `prepare` script: `husky install`. Add `.husky/pre-commit` that runs `lint-staged`. Copy `.claude/hooks/pre-commit` logic into `husky` hooks. Add `lint-staged` config per package. |
| **Value-add** | Add a `commit-msg` husky hook with `commitlint` enforcing Conventional Commits — this enables auto-generated `CHANGELOG.md` via `standard-version`. |

---

### CQ-003 — Backend Linting Not Enforced in CI
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/requirements.txt:72-73` — `black`, `flake8` present · `.github/workflows/ci.yml` `backend-test` job — runs pytest only, no lint |
| **Risk** | Python code formatting and style violations accumulate. `black` and `flake8` are installed but never run automatically. Over time, the codebase diverges from style standards. |
| **Remediation** | Replace `black` + `flake8` with `ruff` (10-100x faster, covers both). Add to `backend-test` job: `ruff check backend/ && ruff format --check backend/`. Add `mypy backend/ --ignore-missing-imports` for type checking. Add `ruff.toml` config at `backend/`. |
| **Value-add** | `ruff` includes 500+ lint rules including security rules (S-prefix), complexity rules (C901), and import sorting (I) — replaces `flake8`, `black`, `isort`, and many `pylint` rules in a single tool. |

---

### CQ-004 — backend/server.py God File (3,800+ Lines)
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `backend/server.py` — 3,800+ lines containing route handlers, middleware, lifespan, logging, Sentry setup |
| **Risk** | Merge conflicts on every PR. Impossible to navigate. New developers cannot find entry points. Unit testing specific handlers requires importing the entire app. |
| **Remediation** | Most routes already exist in `backend/routes/` (16 router files). Audit what remains in `server.py` that is not yet in routes. Migrate remaining handlers to appropriate route files. `server.py` should be max ~150 lines: app factory + middleware + router includes + lifespan. |
| **Value-add** | After splitting, add route-level docstrings that auto-populate FastAPI's `/api/docs` — free API documentation with zero extra work. |

---

### CQ-005 — Duplicate Database Modules
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/db.py` (23KB) · `backend/db_supabase.py` (19KB) — overlapping data access patterns |
| **Risk** | Developers don't know which module to use. Logic may be duplicated with diverging implementations. Bug fixes applied to one may not propagate to the other. |
| **Remediation** | Audit which functions in `db.py` are still called anywhere. Deprecate `db.py` and consolidate all active functions into `db_supabase.py`. Rename to `backend/data/client.py`. Mark deprecated functions with `@deprecated` decorator and `DeprecationWarning`. |
| **Value-add** | Create a `backend/data/` package with `client.py` (Supabase), `models.py` (Pydantic schemas), `queries.py` (complex query builders) — clear separation of concerns. |

---

### CQ-006 — ESLint Configs Minimal (No Security or A11y Rules)
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `admin-dashboard/eslint.config.mjs` · `rider-app/eslint.config.js` · `driver-app/eslint.config.js` — all extend base configs only |
| **Risk** | Common React security issues (dangerouslySetInnerHTML, unescaped user input) and accessibility violations (missing alt text, invalid ARIA) are not caught automatically. |
| **Remediation** | Add `eslint-plugin-security` to all packages. Add `eslint-plugin-jsx-a11y` to admin-dashboard (AODA compliance requirement). Add `eslint-plugin-react-hooks` exhaustive-deps rule. Add `no-console` rule with `warn` to prevent debug logs in production. |
| **Value-add** | Add `eslint-plugin-import` with `import/no-cycle` to catch circular dependencies — a common source of mysterious `undefined` errors in large React apps. |

---

## CATEGORY: TESTING (TST)

---

### TST-001 — Zero Tests in Admin Dashboard
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `admin-dashboard/` — no `*.test.*` or `*.spec.*` files · `admin-dashboard/package.json` — no test framework |
| **Risk** | The admin dashboard controls driver approvals, fare pricing, service areas, promotions, and messaging. Any regression here directly impacts revenue and driver safety. Zero tests means any change could break critical admin workflows silently. |
| **Remediation** | Add `vitest` + `@testing-library/react` + `@testing-library/user-event` to devDependencies. Write unit tests for: fare calculation display, driver approval flow, cloud messaging compose, promo code validation. Target 50% coverage. Add `vitest.config.ts`. |
| **Value-add** | Add `@testing-library/jest-dom` for semantic assertions (`toBeVisible()`, `toHaveRole()`) — tests document expected UI behaviour, not implementation. |

---

### TST-002 — Zero Tests in Mobile Apps
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `rider-app/` · `driver-app/` — no Jest test files |
| **Risk** | Ride booking flow, payment confirmation, driver acceptance — all untested. A broken state transition (e.g., `RIDE_REQUESTED → DRIVER_ASSIGNED`) in the Zustand store could leave users stranded without any test catching it. |
| **Remediation** | Add `jest` + `jest-expo` + `@testing-library/react-native` to both apps. Priority tests: (1) rideStore state transitions, (2) payment flow, (3) OTP screen (6-digit after SEC-007 fix), (4) WebSocket reconnection logic (after MOB-002 fix). Target 30% coverage. |
| **Value-add** | Mock the Supabase client in tests (pattern already established in backend `conftest.py`) — reuse mock patterns for consistent test data across backend and mobile. |

---

### TST-003 — E2E Tests Are a Placeholder
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `.github/workflows/ci.yml` — `e2e-test` job: `echo "E2E tests would run here..."` |
| **Risk** | No automated validation of the full ride booking flow: user login → request ride → driver accepts → payment → completion. Regressions in critical paths are caught only in production. |
| **Remediation** | Implement Playwright E2E tests for admin dashboard (login → navigate → perform action → verify). Implement Maestro E2E for mobile apps (simpler setup than Detox). E2E suite must cover: (1) rider books ride, (2) driver accepts, (3) ride completes, (4) payment succeeds, (5) admin views completed ride. Run against staging environment. |
| **Value-add** | Add Playwright's screenshot comparison on each run — stores baseline images and fails if UI changes unexpectedly. Effective visual regression testing with no additional tool. |

---

### TST-004 — Tests Mock Supabase Entirely (Integration Gap)
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **File** | `backend/tests/conftest.py` — `mock_supabase_client` patches all Supabase table operations |
| **Risk** | Schema changes, RLS policy changes, or PostGIS query changes are not caught by the test suite. The mocks can pass while production queries fail. This happened with promotions/stats (the 500 error fixed in commit `fad2869`). |
| **Remediation** | Add an `integration` test marker that runs against a real Supabase test project (separate from production). Use Supabase branching (available on paid plans) to get per-PR databases. Run integration tests in `test-env.yml` which already has `SUPABASE_*` secrets. |
| **Value-add** | Add `schemathesis` API fuzzing against the FastAPI OpenAPI spec — auto-generates test cases from the schema definition, finding edge cases no human would think to write. |

---

### TST-005 — No Load / Performance Tests
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | No `k6/`, `locust/`, or similar test directory |
| **Risk** | Surge pricing scenarios (Friday evening rush, events) generate 10-50x normal traffic. The API has never been tested under load. Matching algorithm performance under 100 concurrent ride requests is unknown. |
| **Remediation** | Add k6 script at `tests/load/ride_booking.js` simulating: 100 concurrent users requesting rides, 50 drivers accepting. Run weekly in CI (`schedule:` trigger). Set baseline: p99 latency < 500ms, error rate < 0.1%. Alert when baseline degrades. |
| **Value-add** | Use k6 Cloud's free tier for geographic distribution — test latency from Canadian AWS regions specifically (ca-central-1) since spinr is Canada-first. |

---

## CATEGORY: MOBILE APPS (MOB)

---

### MOB-001 — Driver App: No Push Notifications for Background Rides
| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Priority** | P0 |
| **File** | `driver-app/app/driver/index.tsx` |
| **Risk** | A driver with the app backgrounded or screen locked never receives ride offers. The platform cannot function. Drivers will miss every ride that comes in while they're waiting. This is the single biggest blocker to pilot launch. |
| **Remediation** | Implement `expo-notifications` with FCM (Android) and APNs (iOS). Register push token on driver login and store in `notifications` table. Backend must send FCM push on ride dispatch alongside WebSocket message. App must wake up on push, display custom notification with Accept/Decline buttons (`NotificationContent.categoryIdentifier = 'RIDE_OFFER'`). |
| **Value-add** | Add notification categories with action buttons — driver can Accept/Decline directly from the lock screen without opening the app. Critical for driver UX and acceptance rate. |

---

### MOB-002 — Driver App: No WebSocket Reconnection Logic
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `driver-app/app/driver/index.tsx` |
| **Risk** | Mobile networks are unreliable. A 2-second LTE blip drops the WebSocket connection. Without reconnection, the driver is silently offline — they appear available in the system but receive no rides. They discover this only when they notice no rides for 30+ minutes. |
| **Remediation** | Implement exponential backoff reconnection: initial delay 1s, max delay 30s, jitter ±500ms. On reconnect, re-authenticate with JWT and re-send last known location. Show a banner in the driver UI when connection is degraded (`connectionState: 'reconnecting'`). |
| **Value-add** | Add a connection quality indicator (green/yellow/red dot) in the driver header — makes connection issues visible and reduces support tickets. |

---

### MOB-003 — Driver App: Location Updates Not Batched
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **File** | `driver-app/app/driver/index.tsx` · `backend/routes/drivers.py` — `/api/drivers/location-batch` endpoint exists |
| **Risk** | Individual location updates create N HTTP requests per driver per minute. At 100 active drivers updating every 5 seconds, that's 1,200 requests/minute to the API — unnecessary load. Also drains driver's mobile battery faster. |
| **Remediation** | Buffer location updates in the driver app for 5 seconds, then POST array to `/api/drivers/location-batch`. Use `expo-task-manager` for background location updates (required for iOS background mode). |
| **Value-add** | Implement adaptive location update frequency: high frequency (1s) when a ride is active, low frequency (10s) when waiting. Saves battery and reduces API load by 90% during idle periods. |

---

### MOB-004 — Driver App: No Geofence Arrival Verification
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **File** | `driver-app/store/driverStore.ts` |
| **Risk** | Driver can tap "I've Arrived" from across the city. Riders get a false "Driver Arrived" notification, walk outside, and the driver is nowhere near. Leads to ride cancellations, refund requests, and safety concerns. |
| **Remediation** | Add client-side geofence check: only enable "Arrived" button when driver is within 100m of pickup coordinates (compare against `rideStore.pickup.lat/lng`). Show distance countdown as driver approaches. Backend should also validate the driver's last known location on arrival events. |
| **Value-add** | Add server-side validation too: reject `DRIVER_ARRIVED` state transition if last known driver location is >300m from pickup — prevents API manipulation. |

---

### MOB-005 — No Analytics Event Tracking
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `rider-app/` · `driver-app/` — no Amplitude, Mixpanel, or Firebase Analytics calls |
| **Risk** | No funnel data. Cannot answer: Where do riders drop off during booking? What causes drivers to reject rides? Which features drive retention? Product decisions are based on assumptions, not data. |
| **Remediation** | Add Firebase Analytics (already have `@react-native-firebase/app` in both apps — just add `@react-native-firebase/analytics`). Track key events: `ride_requested`, `ride_cancelled`, `ride_completed`, `payment_failed`, `driver_accepted`, `driver_rejected`, `app_backgrounded_mid_ride`. |
| **Value-add** | Use Firebase Remote Config alongside Analytics for feature flags — A/B test UI changes (e.g., tip prompts, surge acceptance screens) with no app store release. |

---

### MOB-006 — Driver App: No Error Boundary
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `driver-app/app/_layout.tsx` — no `ErrorBoundary` component (unlike rider-app which has one) |
| **Risk** | A JavaScript error in any driver screen crashes the entire app with the React Native red screen. Driver loses their active ride context. Crashlytics captures it but the driver experience is broken. |
| **Remediation** | Add the same `ErrorBoundary` pattern used in `rider-app/app/_layout.tsx` to `driver-app/app/_layout.tsx`. Error boundary should log to Crashlytics and show a user-friendly "Something went wrong — tap to reload" screen instead of the red crash screen. |
| **Value-add** | Add route-level error boundaries on critical screens (`driver/index.tsx`, `driver/ride-detail.tsx`) so a crash in one screen doesn't affect the entire app. |

---

### MOB-007 — Bugreport ZIPs Committed to Repository
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `rider-app/bugreport-sdk_gphone64_x86_64-BE4B.251210.005-2026-04-01-21-00-06.zip` (5.3MB) · `rider-app/bugreport-sdk_gphone64_x86_64-BE4B.251210.005-2026-04-01-21-01-04.zip` (5.4MB) |
| **Risk** | 10.7MB of binary debug files in the repository. These may contain device identifiers, network logs, or other debugging information that could be sensitive. They bloat every `git clone`. |
| **Remediation** | Delete both files. Add `bugreport-*.zip` to `rider-app/.gitignore`. Use `git filter-repo` or `BFG Repo-Cleaner` to remove them from git history (reduces repo size for all future clones). |
| **Value-add** | Store bugreports in a shared Google Drive or Notion link referenced in `docs/DEBUGGING.md` — they remain accessible to the team without polluting the repo. |

---

## CATEGORY: DOCUMENTATION & PROJECT STRUCTURE (DOC)

---

### DOC-001 — CLAUDE.md Is Incomplete (Truncated)
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `CLAUDE.md` — ends with `## Repository Structure ENDOFFILE` — the actual repository structure section is missing |
| **Risk** | Claude Code (and any AI assistant) working on the project lacks critical context: folder structure, environment variable names, which services map to which deployments, how to run the project locally. This causes AI to make incorrect assumptions about file locations and architecture. |
| **Remediation** | Complete the `## Repository Structure` section with: directory tree, which env vars each service needs, how to run locally (`uvicorn`, `npx expo start`, `npm run dev`), deployment targets per service, branch strategy, and key architectural decisions. |
| **Value-add** | Add a `## Domain Rules` section to CLAUDE.md documenting spinr-specific invariants: insurance period classifications, trip state machine transitions, float-free money rule — so all AI interactions are domain-aware automatically. |

---

### DOC-002 — No API Reference Documentation
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `backend/server.py` — FastAPI auto-generates OpenAPI but `/docs` endpoint status unknown in production · no `docs/API_REFERENCE.md` |
| **Risk** | Frontend and mobile developers don't know what endpoints exist, what auth headers to send, what error codes to handle, or what request/response shapes to expect. Every integration requires reading Python source code. |
| **Remediation** | Enable FastAPI `/api/docs` and `/api/redoc` in production (verify they are not disabled). Add docstrings to all route functions (populates OpenAPI automatically). Export OpenAPI spec to `docs/openapi.json` in CI. Create `docs/API_REFERENCE.md` with auth flow, error codes, rate limits, and webhook payload shapes. |
| **Value-add** | Publish the OpenAPI spec to Stoplight or Redocly for a polished developer portal — important when onboarding third-party developers or enterprise partners. |

---

### DOC-003 — No Runbooks or Incident Playbooks
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `docs/` — empty except `superpowers` file |
| **Risk** | When production breaks at 2am (DB connection exhaustion, Stripe webhook timeout, EAS build failure), the on-call engineer has no documented procedure. Every incident requires starting from scratch. Mean time to resolution (MTTR) is high. |
| **Remediation** | Create `docs/runbooks/` with: `database-connection-exhausted.md`, `stripe-webhook-failure.md`, `api-high-latency.md`, `driver-app-not-receiving-rides.md`, `eas-build-failed.md`. Each runbook: symptoms → diagnosis commands → resolution steps → escalation path. |
| **Value-add** | Add a `docs/INCIDENT_RESPONSE.md` with severity definitions, communication templates (Slack, status page), and post-mortem template — institutional knowledge that survives team changes. |

---

### DOC-004 — No Environment Variable Reference
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/.env.example` · `rider-app/.env.example` · `driver-app/.env.example` — exist but are likely incomplete and not cross-referenced |
| **Risk** | A new developer setting up the project doesn't know all required env vars, their format, where to get them, or which are optional. Onboarding takes hours of trial and error. |
| **Remediation** | Create `docs/ENVIRONMENT_VARIABLES.md` listing every env var across all services: name, required/optional, format, where to obtain, which service uses it, and whether it differs between dev/staging/prod. Cross-reference with each `.env.example`. |
| **Value-add** | Add a startup validation script `scripts/validate_env.sh` that checks all required env vars are set before `uvicorn` starts — fail fast with clear error messages instead of cryptic runtime failures. |

---

### DOC-005 — Root Directory Cluttered with Docs and Reports
| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Priority** | P3 |
| **Files** | 15 `.md` files at root · 8 `code_review_report_*.json` files at root · `test_admin_endpoints.py` at root · `GAP_ANALYSIS.md`, `INSTRUCTIONS.md`, etc. |
| **Risk** | Discoverability. New contributors don't know which docs are current. The root should be a navigation point, not a document dump. |
| **Remediation** | Move all docs except `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md` to `docs/`. Move JSON reports to `test_reports/`. Move `test_admin_endpoints.py` to `backend/tests/`. Update all internal cross-references. |
| **Value-add** | Create a `docs/` index (`docs/README.md`) with a table of contents linking all documentation — makes the docs directory as navigable as the codebase. |

---

## CATEGORY: CLAUDE / AI CONFIGURATION (AI)

---

### AI-001 — Pre-commit Security Hook Not Auto-Installed
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `.claude/hooks/pre-commit` — excellent security hook that requires manual `cp + chmod` |
| **Risk** | Every new developer who clones the repo and doesn't read the installation instructions is committing without the security gate. The hook catches Stripe live keys, PII in logs, `.env` files — critical protections for a payments platform. |
| **Remediation** | Add a `scripts/setup_dev.sh` that installs the hook automatically: `cp .claude/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`. Call this in `README.md` setup steps. Better: add a root `package.json` with `"prepare": "node scripts/install-hooks.js"` — runs automatically on `npm install`. |
| **Value-add** | Migrate the bash hook to a `pre-commit` framework config (`.pre-commit-config.yaml`) — enables `pre-commit install` as a one-liner, supports multiple hooks, and is language-agnostic across Python and JS. |

---

### AI-002 — CLAUDE.md Missing Repository Structure Section
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **File** | `CLAUDE.md` — `## Repository Structure ENDOFFILE` is a cut-off placeholder |
| **Risk** | Every AI conversation starts without knowledge of: where to find files, what `shared/` contains, what `.agents/` is for, which Vercel projects map to which directories, or how services connect. AI makes more mistakes and needs more human correction. |
| **Remediation** | Complete CLAUDE.md with: full directory tree (`tree -L 2 --dirsfirst`), service → URL mappings, local dev commands per service, environment setup steps, key invariants (insurance periods, trip states, float-free money), and a `## Quick Reference` section with commonly edited files. |
| **Value-add** | Add `## What NOT to do` to CLAUDE.md — an explicit list of anti-patterns for spinr specifically (e.g., never use float for fares, never query Supabase from mobile with service role key, never skip RLS). Prevents repeated corrections. |

---

### AI-003 — .agents/ Framework Not Integrated with Claude Code Skills
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `.agents/roles/` (7 role files) · `.agents/standards/` (4 standards files) · `.agents/workflows/` (8 workflow files) — none referenced in `.claude/commands/` |
| **Risk** | The `.agents/` framework defines excellent roles (security-engineer, qa-engineer, tech-lead) and standards (api-standards, security-standards, testing-standards) that Claude Code skills don't leverage. When `/review` runs, it doesn't apply `security-standards.md`. When `/commit` runs, it doesn't apply `coding-standards.md`. |
| **Remediation** | Update each `.claude/commands/*.md` skill to reference the relevant `.agents/` files. For example: `/review` should include `cat .agents/standards/security-standards.md` in its instructions. `/commit` should reference `coding-standards.md`. `/start` should reference the appropriate role file. |
| **Value-add** | Create a `/audit` skill that systematically applies all `.agents/standards/` files as a structured code review checklist — a single command that produces a comprehensive quality report per file changed. |

---

### AI-004 — Missing Skills for Key Workflows
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `.claude/commands/` — has: commit, pr, review, start, status · missing: deploy, rollback, incident, test, db-migrate |
| **Risk** | Common workflows that developers trigger multiple times per day have no skill support, so they are done manually or inconsistently. Deployment, rollback, and incident response especially benefit from structured, repeatable prompts. |
| **Remediation** | Create the following skills: `/deploy` (trigger specific service deploy with env selection, smoke test), `/rollback` (identify previous good deploy, execute rollback, verify), `/incident` (structured incident response: triage → diagnose → resolve → communicate → post-mortem), `/test` (run appropriate test suite for changed files), `/migrate` (create and apply DB migration safely). |
| **Value-add** | Create `/doc` skill that reads a file and generates/updates its API documentation, JSDoc comments, and `docs/` entry — keeps documentation in sync with code automatically. |

---

### AI-005 — .claude/settings.json and claude.yml Are Untracked
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `.claude/settings.json` — untracked · `.github/workflows/claude.yml` — untracked (both shown in `git status`) |
| **Risk** | These files define how Claude Code behaves in this repository. If they are lost (new clone, branch switch, disk failure), all Claude Code automation and permission settings must be reconfigured from scratch. Other team members don't get the benefit of the configured permissions. |
| **Remediation** | Commit both files. `.claude/settings.json` contains no secrets (permissions only). `claude.yml` is a workflow that enables Claude Code in GitHub PRs and issues. Both should be version-controlled and reviewed like any other config. |
| **Value-add** | Add a `## Claude Code Setup` section to `README.md` (and `CLAUDE.md`) explaining what `.claude/` contains, how to update settings, and what each skill does — onboards new team members to AI-assisted workflows. |

---

### AI-006 — Memory System Not Initialized
| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Priority** | P3 |
| **Files** | `memory/` directory — empty · `C:\Users\TabUsrDskOff111\.claude\projects\...\memory\` — Claude's persistent memory |
| **Risk** | Project context, team preferences, recurring patterns, and architectural decisions are re-explained in every conversation. AI assistance quality degrades on context-heavy questions. |
| **Remediation** | Populate project memory with: spinr domain rules, key architectural decisions (why Supabase over MongoDB, why Expo over bare React Native), known gotchas (Supabase RLS must be enabled for all tables, insurance period classifications), team preferences (conventional commits, no floats for money). |
| **Value-add** | Treat the memory system like onboarding documentation — everything a new engineer or AI assistant needs to be productive without asking questions that have been answered before. |

---

## CATEGORY: COMPLIANCE (COM)

---

### COM-001 — PIPEDA Compliance Not Documented
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | No `docs/PRIVACY.md`, no data retention policy, no deletion procedures |
| **Risk** | spinr is a Canadian platform subject to PIPEDA (Personal Information Protection and Electronic Documents Act). Storing ride history, GPS data, phone numbers, and payment info without documented consent, retention, and deletion procedures is a legal liability. Regulators can fine up to $100,000 CAD per violation. |
| **Remediation** | Document: what PII is collected (name, phone, GPS history, payment methods), why each is collected (purpose limitation), how long it is retained (rides: 7 years for tax, GPS: 90 days, inactive accounts: 2 years), how users can request deletion, and who the Privacy Officer is. Add a `DELETE /api/v1/users/me` endpoint that hard-deletes or anonymizes all user data. |
| **Value-add** | Add a Privacy Dashboard in the rider app (visible in `rider-app/app/(tabs)/account.tsx`) where users can download their data, see what's stored, and request deletion — exceeds PIPEDA requirements and differentiates spinr on privacy. |

---

### COM-002 — No Privacy Policy / Terms in Mobile Apps
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `rider-app/app/` · `driver-app/app/` — `legal.tsx` screen exists but likely links to placeholder URLs |
| **Risk** | Apple App Store and Google Play Store both require apps to link to a Privacy Policy before submission. Without this, app submissions will be rejected. Both platforms also require ToS acceptance before account creation. |
| **Remediation** | Host Privacy Policy and Terms of Service at `https://spinr.ca/privacy` and `https://spinr.ca/terms`. Update `legal.tsx` to link there. Add explicit checkbox consent on the OTP onboarding screen: "I agree to the Terms of Service and Privacy Policy [links]". Log consent timestamp and version to the `users` table. |
| **Value-add** | Version the privacy policy (v1.0, v1.1) and store accepted version per user — when policy changes, prompt re-consent in-app. Required for PIPEDA compliance and expected by app stores. |

---

### COM-003 — AODA / WCAG 2.1 AA Not Audited (Web)
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `frontend/` · `admin-dashboard/` — no accessibility audit performed or documented |
| **Risk** | Ontario's Accessibility for Ontarians with Disabilities Act (AODA) requires web services to meet WCAG 2.1 Level AA. Non-compliance for a public-facing service can result in fines and legal action. Screen reader users cannot use an inaccessible ride booking app. |
| **Remediation** | Run `axe-core` automated audit on all web pages. Fix all Critical and Serious violations. Key checks: color contrast ratio ≥ 4.5:1, all interactive elements keyboard-navigable, form inputs have labels, images have alt text, focus indicators visible. Document compliance status in `docs/ACCESSIBILITY.md`. |
| **Value-add** | Add `eslint-plugin-jsx-a11y` to admin dashboard (already in CQ-006) and `@axe-core/playwright` to E2E tests — catches regressions automatically with no manual audit needed. |

---

### COM-004 — PCI-DSS Scope Not Documented
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/routes/payments.py` · `backend/routes/webhooks.py` — Stripe integration |
| **Risk** | spinr processes payment cards via Stripe. Even with Stripe Elements (which keeps card data off spinr servers), the platform must document its PCI-DSS compliance scope (SAQ-A) and confirm it never stores card numbers, CVVs, or PINs. |
| **Remediation** | Confirm spinr uses Stripe.js/Elements (card data never touches spinr servers — SAQ-A eligible). Document in `docs/PCI_COMPLIANCE.md`: scope, what is and isn't stored, Stripe's role as a PCI-DSS Level 1 service provider. Ensure Stripe webhook signature verification is in place (already in `webhooks.py` — confirm). |
| **Value-add** | Complete Stripe's SAQ-A self-assessment questionnaire and store the signed copy — required if spinr ever wants to partner with insurance companies or fleet operators who require vendor compliance documentation. |

---

## CATEGORY: FEATURE GAPS (FEAT)

---

### FEAT-001 — Driver Earnings Transparency
| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Priority** | P1 |
| **Files** | `driver-app/app/driver/earnings.tsx` · `driver-app/app/driver/payout.tsx` — screens exist but completeness unknown |
| **Risk** | Driver earnings fairness is listed as a core spinr differentiator. If drivers cannot see a per-ride breakdown (base fare, surge multiplier, platform commission, tips, promo deductions), they will distrust the platform and churn. This was a major Lyft/Uber driver complaint in Canada. |
| **Remediation** | Verify `earnings.tsx` shows: gross fare, platform commission %, driver net, surge multiplier if applied, tip amount, promo impact, weekly/monthly totals. Backend `routes/payments.py` must expose this breakdown per ride. Add "Earnings Explained" modal for first-time drivers. |
| **Value-add** | Add earnings forecast feature: "Based on your online hours this week, you are projected to earn $X." Uses historical earnings-per-hour data from the driver's own history — builds driver trust and increases online time. |

---

### FEAT-002 — Surge Pricing UI Not Confirmed
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `admin-dashboard/src/app/dashboard/surge/page.tsx` — admin surge management exists · rider-app screens — surge display unknown |
| **Risk** | Riders booking during surge don't see the surge multiplier clearly, leading to bill shock, disputes, and chargebacks. Regulatory risk in Canada if surge is not disclosed before booking confirmation. |
| **Remediation** | Verify `ride-options.tsx` displays surge multiplier prominently (≥ 20pt font, highlighted) before rider confirms booking. Backend `fares.py` must include `surge_multiplier` in fare calculation response. Add explicit "Surge pricing is active (1.8x)" confirmation step before ride request. |
| **Value-add** | Show surge heat map in rider app home screen (Leaflet/Maps overlay already in admin heatmap) — riders can decide to walk to a lower-surge pickup point, reducing cancellations and improving experience. |

---

### FEAT-003 — Corporate Accounts UI Integration
| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Priority** | P2 |
| **Files** | `backend/routes/corporate_accounts.py` — full CRUD exists · `backend/corporate_accounts_schema.sql` — schema exists · `admin-dashboard/src/app/dashboard/corporate-accounts/page.tsx` — admin page exists |
| **Risk** | Corporate accounts (B2B) are a high-margin revenue stream. If the admin UI is incomplete or the rider app doesn't support corporate billing, this entire feature is inaccessible to paying customers. |
| **Remediation** | Audit the corporate accounts admin page for completeness (add/edit/deactivate accounts, set credit limits, view usage). Verify rider app has a "Bill to company" payment option. Verify backend correctly handles `corporate_account_id` on ride creation and fare deduction. |
| **Value-add** | Add monthly PDF invoice generation for corporate accounts using `WeasyPrint` or `reportlab` — enterprise customers expect automated billing. High-value differentiator for B2B sales. |

---

## SUMMARY DASHBOARD

| Category | Total Issues | P0 | P1 | P2 | P3 |
|----------|-------------|----|----|----|----|
| Security (SEC) | 11 | 4 | 4 | 3 | 0 |
| Infrastructure (INF) | 8 | 0 | 5 | 3 | 0 |
| Code Quality (CQ) | 6 | 0 | 2 | 4 | 0 |
| Testing (TST) | 5 | 0 | 3 | 2 | 0 |
| Mobile (MOB) | 7 | 1 | 2 | 3 | 1 |
| Documentation (DOC) | 5 | 0 | 3 | 1 | 1 |
| Claude/AI Config (AI) | 6 | 0 | 2 | 3 | 1 |
| Compliance (COM) | 4 | 0 | 2 | 2 | 0 |
| Features (FEAT) | 3 | 0 | 1 | 2 | 0 |
| **TOTAL** | **55** | **5** | **24** | **23** | **3** |

### P0 — Must Fix Before Any Production Traffic
1. **SEC-001** — Hardcoded JWT secret
2. **SEC-002** — Hardcoded admin credentials
3. **SEC-003** — CORS wildcard default
4. **SEC-004** — Docker runs as root / no health check / no .dockerignore
5. **MOB-001** — Driver app: no push notifications (platform cannot function)

### Recommended Fix Order (P1 Sprint)
`SEC-007 (OTP 4→6 digit)` → `SEC-008 (secrets scanning in CI)` → `SEC-009 (Trivy gate)` →
`INF-001 (Python version mismatch)` → `INF-004 (DB migration in deploy)` → `INF-005 (smoke test)` →
`TST-001 (admin tests)` → `TST-002 (mobile tests)` → `TST-003 (E2E)` →
`MOB-002 (WebSocket reconnect)` → `MOB-006 (driver error boundary)` →
`DOC-001 (CLAUDE.md complete)` → `DOC-002 (API docs)` → `DOC-003 (runbooks)` →
`AI-001 (hook auto-install)` → `AI-005 (commit settings.json + claude.yml)` →
`COM-001 (PIPEDA docs)` → `COM-002 (privacy policy in apps)` →
`FEAT-001 (driver earnings)` → `CQ-004 (server.py split)`

---

*Last updated: 2026-04-07 | Audit depth: Full codebase read + all config files + CI/CD + AI config*
