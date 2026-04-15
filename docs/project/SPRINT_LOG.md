# Spinr — Sprint Log
<!-- Running decision log. Append entries; never delete. Newest at top. -->

---

## SPR-00 — Foundation
**Date:** 2026-04-14  
**Branch:** `claude/complete-product-streamline-Zj6lW`  
**Status:** ✅ Complete

### Context
New engagement to complete the Spinr product end-to-end. Previous sessions fixed
critical bugs (CORS, JWT, OTP, push notifications, WebSocket reconnect, race conditions,
admin auth, test suite). This session's goal: ship everything remaining.

### Audit Findings (3 parallel agents)

**Frontend Web App (`frontend/`):**
- STATUS: 42% complete (11 of 22 rider-app screens)
- Unique value vs rider-app: NONE
- Tech debt: duplicated stores, local API client, `(driver)/` directory missing
- DECISION D-003/D-004: Kill as standalone; add web build to rider-app

**Backend Feature Modules:**
- loyalty.py: MOUNTED, 4 endpoints, COMPLETE
- quests.py: MOUNTED, 8 endpoints, COMPLETE
- wallet.py: MOUNTED, 5 endpoints, COMPLETE
- favorites.py: MOUNTED, 5 endpoints, COMPLETE
- fare_split.py: MOUNTED, 6 endpoints, COMPLETE
- All mobile screens (wallet, fare-split, scheduled-rides) call real endpoints ✅

**Chat Real-Time Status:**
- Rider side: COMPLETE — REST send → WS push; `useRiderSocket` receives chat_message
- Driver side: PARTIALLY BROKEN — `chat.tsx` polls every 10s AND has a syntax bug
  (broken useEffect hook at line 95). `useDriverDashboard` receives chat_message
  via WS but only vibrates, never pushes to screen.
- DECISION D-005/D-006: Fix driver chat with driverStore subscription

**CI State:**
- 9 CI jobs: backend-test, frontend-test, driver-app-test, rider-app-test,
  admin-test, e2e-test, deploy-*, mobile-build, security-scan
- Branch `claude/complete-product-streamline-Zj6lW` is clean; no conflicts
- Backend test suite: 281 passed, 1 skipped

### Decisions Made
| ID | Decision |
|---|---|
| D-001 | Ship ALL features before first APK (no partial release train) |
| D-002 | First audience: internal only (Firebase can be mock) |
| D-003 | Kill `frontend/` as standalone app |
| D-004 | Merge web target into rider-app |
| D-005 | Rider chat real-time is already working |
| D-006 | Driver chat needs driverStore WS wiring (replace polling) |
| D-007 | Adopt Conventional Commits + SPR-nn branch prefix |
| D-008 | CalVer for apps, SemVer for API |

### Deliverables
- [x] `docs/project/MASTER_PLAN.md`
- [x] `docs/project/NAMING_CONVENTIONS.md`
- [x] `docs/project/SPRINT_LOG.md` (this file)
- [x] `docs/project/OPERATOR_TASKS.md`

---

## SPR-01 — Feature Completeness
**Date:** 2026-04-14 (started)  
**Branch:** `feat/SPR-01-feature-completeness` (to be created)  
**Status:** ✅ Complete

### Tasks
| ID | Task | Status | Notes |
|---|---|---|---|
| 1a | Fix driver chat.tsx (syntax bug + polling → driverStore WS) | ✅ | commit 36b8a66; driverStore WS subscription replaces 10s poll |
| 1b | Deprecate frontend/; configure rider-app web target | ✅ | frontend/DEPRECATED.md written; app.config.ts has web:{bundler:metro}; CI deploy-frontend builds from rider-app/ |
| 1c | Port 8 missing screens to rider-app | ✅ | All 8 screens already present with useTheme() + real API calls |
| 1d | Dark mode (ThemeContext + all screens) | ✅ | shared/theme/; all ~70 screens migrated |
| 1e | Offline mode (AsyncStorage persistence) | ✅ | rideStore + driverStore write-through; hydrateActiveRide / hydrateDriverRideState on mount |
| 1f | Legal text wire-up | ✅ | settings_router was never mounted in server.py; fixed + dual-mount at root + /api/v1 |

### Decisions
_(to be recorded as sprint progresses)_

---

## SPR-02 — Quality Gates
**Date:** 2026-04-15 (started)
**Branch:** `claude/complete-product-streamline-Zj6lW`
**Status:** ✅ Complete

### Tasks
| ID | Task | Status | Notes |
|---|---|---|---|
| 2a | Backend integration tests: loyalty, quests, wallet, fare-split | ✅ | 77 new tests; full suite 356 passing; uses TestClient + dependency_overrides + patch("routes.X.db") |
| 2b | E2E framework: Playwright for rider-app web | ✅ | rider-app/playwright.config.ts + e2e/fixtures.ts; mocks /api/v1/** + Google Maps + Firebase; CI job `rider-web-e2e` added |
| 2c | E2E: full ride cycle smoke test (mock backend) | ✅ | e2e/ride-booking.spec.ts walks 5 stages (searching → driver_assigned → driver_arrived → in_progress → completed) |
| 2d | Performance baseline: API P95 latency, WS round-trip | ✅ | perf_baseline.py: in-process ASGI bench; HTTP P95 ≤7ms, WS P95 ≤8ms; CI job `perf-baseline` saves artifact + regresses at +30% |

### Decisions
| ID | Decision |
|---|---|
| D-009 | Patch `routes.X.db` (not `backend.routes.X.db`) — server.py puts backend/ on sys.path |
| D-010 | Cross-module patches required when a route uses `get_or_create_wallet` (patch both modules' `db`) |
| D-011 | rider-app E2E runs against `expo export --platform web` output served by `npx serve` on :3002; no real network |

### Deliverables
- [x] `backend/tests/test_loyalty.py` (14 tests)
- [x] `backend/tests/test_wallet.py` (15 tests)
- [x] `backend/tests/test_quests.py` (25 tests)
- [x] `backend/tests/test_fare_split.py` (23 tests)
- [x] `rider-app/playwright.config.ts`
- [x] `rider-app/e2e/fixtures.ts`
- [x] `rider-app/e2e/smoke.spec.ts`
- [x] `rider-app/e2e/ride-booking.spec.ts`
- [x] CI job `rider-web-e2e` in `.github/workflows/ci.yml`
- [x] `backend/tests/perf_baseline.py` (HTTP P95 + WS round-trip; CI job `perf-baseline`)

---

<!-- Add new sprints above this line, newest first -->

