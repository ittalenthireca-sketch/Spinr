# Spinr TODO List

## Critical Issues (Must Fix)

- [ ] **Driver App: No push notifications** - App won't receive rides when in background
  - File: `driver-app/app/driver/index.tsx`
  - Action: Implement Expo Notifications with FCM
  - Test: Background ride offer reception

- [ ] **Driver App: No WebSocket reconnection** - Lost rides if connection drops
  - File: `driver-app/app/driver/index.tsx`
  - Action: Add reconnection logic with exponential backoff
  - Test: Network dropout simulation

- [ ] **Driver App: Location not batched** - Inefficient individual updates
  - File: `driver-app/app/driver/index.tsx`
  - Action: Use `/api/drivers/location-batch` endpoint
  - Test: Verify batched location updates

## High Priority

- [ ] **Backend: CORS allows all origins** - Security risk in production
  - File: `backend/server.py`
  - Action: Restrict to specific origins in production

- [ ] **Backend: Hardcoded JWT secret** - Dev mode security issue
  - File: `backend/server.py`
  - Action: Ensure strong secret required in production

- [ ] **Backend: Large server.py** - 3800+ lines, needs modularization
  - File: `backend/server.py`
  - Action: Split into route modules

- [ ] **Driver App: 4-digit OTP** - Should be 6-digit for production
  - Files: `backend/server.py`, `driver-app/app/otp.tsx`
  - Action: Increase to 6-digit minimum

- [ ] **Driver App: No geofence verification** - Arrival confirmation
  - File: `driver-app/store/driverStore.ts`
  - Action: Add distance check before allowing arrival

## Medium Priority

- [ ] **Admin Dashboard: No authentication** - No visible auth implementation
  - File: `admin-dashboard/src/app/`
  - Action: Implement admin auth

- [ ] **Driver App: Hardcoded 15s timeout** - Should be configurable
  - File: `driver-app/app/driver/index.tsx`
  - Action: Make timeout configurable via API

- [ ] **Driver App: External navigation** - Leaves the app
  - File: `driver-app/app/driver/index.tsx`
  - Action: Add in-app navigation option

- [ ] **Driver App: No tip collection** - Incomplete payment flow
  - File: `driver-app/app/driver/ride-detail.tsx`
  - Action: Add tip selection UI

- [ ] **Driver App: Race condition handling** - Multiple drivers accepting
  - File: `driver-app/store/driverStore.ts`
  - Action: Handle "ride already accepted" gracefully

## Low Priority

- [ ] **Driver App: No earnings export** - Can't export for taxes
  - File: `driver-app/app/driver/earnings.tsx`
  - Action: Add CSV/PDF export

- [ ] **Driver App: No dark mode** - Light theme only
  - Files: `driver-app/`
  - Action: Implement theme system

- [ ] **API: No versioning** - No v1/v2 prefix
  - Files: `backend/server.py`
  - Action: Add API versioning

- [ ] **Error handling** - Could be more robust
  - Files: `driver-app/`, `frontend/`
  - Action: Improve error messages

---

## Notes

- All critical and high priority items should be completed before production launch
- Medium priority items improve user experience significantly
- Low priority items are nice-to-have enhancements

## Sprint 2 — Security (Added 2026-04-09)

- [ ] **Firebase key rotation** — `google-services.json` and `GoogleService-Info.plist` committed in git history
  - Files: `driver-app/google-services.json`, `driver-app/GoogleService-Info.plist`, `rider-app/google-services.json`, `rider-app/GoogleService-Info.plist`
  - Action: Owner rotates Firebase project keys in Firebase Console (Option C), new files replace committed ones
  - Priority: P1 — credentials exposed in private repo history

- [ ] **CORS origin lockdown** — `server.py` allows `*` in production
  - File: `backend/server.py`
  - Action: Restrict to `https://spinr.app`, `https://admin.spinr.app` in production env

- [ ] **server.py modularization** — 3,800 lines, unmaintainable
  - File: `backend/server.py`
  - Action: Split into 15 route modules under `backend/routes/`

- [ ] **OTP rate limiting** — no per-phone or per-IP limit on `/api/auth/send-otp`
  - File: `backend/server.py`
  - Action: 5 attempts per phone per 15 min, exponential backoff

- [ ] **Account lockout** — no lockout after repeated failed OTP verifications
  - File: `backend/server.py`
  - Action: Lock account after 10 failures, require admin unlock or 24hr cooldown
