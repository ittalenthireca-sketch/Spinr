# Spinr — System Architecture

> **Role:** Solutions Architect  
> **Audience:** All engineers, new joiners, external reviewers

---

## 1. Process model

Spinr runs as **two separate Fly.io processes** from the same Docker
image, controlled by the `[processes]` block in `fly.toml`.

```
┌─────────────────────────────────────────────────────┐
│                   Docker Image                      │
│            (same build, two entry-points)           │
│                                                     │
│  FLY_PROCESS_GROUP=app                              │
│  ┌────────────────────────────────────────────────┐ │
│  │              API Process                       │ │
│  │  uvicorn server:app --host 0.0.0.0 --port 8000 │ │
│  │                                                │ │
│  │  • HTTP routes    (FastAPI)                    │ │
│  │  • WebSocket hub  (socket_manager.py)          │ │
│  │  • /metrics       (Prometheus)                 │ │
│  │  • /health        (liveness)                   │ │
│  │  • /health/deep   (readiness)                  │ │
│  │                                                │ │
│  │  Scale: min=1, scales with load                │ │
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  FLY_PROCESS_GROUP=worker                           │
│  ┌────────────────────────────────────────────────┐ │
│  │             Worker Process                     │ │
│  │         python -m worker                       │ │
│  │                                                │ │
│  │  • surge_engine          (30s loop)            │ │
│  │  • scheduled_dispatcher  (60s loop)            │ │
│  │  • payment_retry         (5min loop)           │ │
│  │  • document_expiry       (1h loop)             │ │
│  │  • subscription_expiry   (1h loop)             │ │
│  │  • stripe_event_worker   (5s loop)             │ │
│  │  • data_retention_loop   (24h loop)            │ │
│  │                                                │ │
│  │  Scale: always exactly 1 machine               │ │
│  └────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Why two processes matter

| Concern | Single-process (before) | Split-process (after) |
|---|---|---|
| Worker stops on deploy | ✅ Yes — cold restart kills loops | ❌ Worker restarts independently |
| API overload kills dispatcher | ✅ Yes — shared CPU | ❌ Worker has dedicated CPU |
| Scale API without duplicating workers | ✅ Can't | ❌ `fly scale count app=N` only |
| Health check accuracy | ✅ Fly sees API alive even if worker dead | ❌ Worker heartbeat tracked separately |

---

## 2. Network topology

```
Internet
   │
   │  HTTPS (443) / WSS (443)
   ▼
┌──────────────────────────────────────────┐
│         Fly.io Anycast Edge              │
│   TLS termination · DDoS protection      │
│   Geographic routing (yyz primary)       │
└──────────────────┬───────────────────────┘
                   │  HTTP (private network)
                   │
        ┌──────────┴──────────┐
        │  Fly Load Balancer  │  (round-robin across app machines)
        └──────────┬──────────┘
                   │
     ┌─────────────┴──────────────┐
     │                            │
┌────▼────────┐           ┌───────▼────────┐
│ app machine │           │  app machine   │
│    :8000    │           │     :8000      │  (+ more at peak)
└────┬────────┘           └───────┬────────┘
     │                            │
     │   ┌────────────────────┐   │
     └───►  Upstash Redis     ◄───┘
         │  (WS pub/sub +     │
         │   rate limiting)   │
         └────────────────────┘
              │
         ┌────▼────────────────┐
         │  worker machine     │
         │  (background loops) │
         └────┬────────────────┘
              │
    ┌─────────┴──────────┐
    │                    │
┌───▼───────────┐  ┌─────▼────────┐
│   Supabase    │  │    Stripe    │
│  PostgreSQL   │  │  (payments)  │
│  PostgREST    │  └──────────────┘
│  Supavisor    │
│  (pooler)     │
└───────────────┘
```

---

## 3. WebSocket fan-out (post-audit)

Before the audit, all WebSocket connections were stored in a single
Python dict per API process. Events dispatched from the worker
would only reach riders connected to that specific machine.

```
BEFORE (broken at 2+ machines):

  Worker ──► API machine A ──► rider on A  ✅
                 │
                 └──────────► rider on B  ❌  (different machine, unreachable)


AFTER (Redis pub/sub fan-out):

  Worker ──► Redis channel "spinr:ws:dispatch"
                 │
                 ├──► API machine A subscriber ──► deliver if local  ✅
                 │
                 └──► API machine B subscriber ──► deliver if local  ✅

  Every machine subscribes to ONE shared channel.
  Each machine delivers only messages whose client_id is in its
  local active_connections dict. Non-local messages are silently
  discarded (expected and logged at DEBUG level).
```

**Fallback behaviour:** If Redis is unreachable, `publish()` returns
`False` and `send_personal_message` falls back to direct local
delivery — identical to the pre-audit single-machine behaviour. The
system degrades gracefully rather than dropping traffic entirely.

---

## 4. Boot sequence

```
flyctl deploy
     │
     ▼
Docker image pulled to Fly machine
     │
     ▼
Fly starts: uvicorn server:app
     │
     ▼
core/lifespan.py  ──  startup phase
     │
     ├── 1. Configure structured logging (loguru JSON)
     │
     ├── 2. Initialise Sentry
     │        └── aborts if SENTRY_DSN unset in production
     │
     ├── 3. DB health probe  (SELECT 1 via Supabase)
     │        └── aborts if DB unreachable → Fly rolls back deploy
     │
     ├── 4. Redis health probe  (PING via rate-limiter)
     │        └── aborts if RATE_LIMIT_REDIS_URL unset in production
     │
     ├── 5. Start WS pub/sub  (subscribe to spinr:ws:dispatch)
     │        └── degrades to local-only if WS_REDIS_URL unset
     │
     └── 6. (worker process only) Register + start 7 background loops
              └── each loop records heartbeat to bg_task_heartbeat table

API now accepts traffic.
Fly health check: GET /health  →  200  →  machine marked live.
```

---

## 5. Data stores and their roles

```
┌─────────────────────────────────────────────────────────────┐
│                        Supabase                             │
│                     (PostgreSQL 15)                         │
│                                                             │
│  Schema: public                                             │
│  ┌─────────────────┐  ┌───────────────────┐                │
│  │   Core tables   │  │  Operational tbls │                │
│  │                 │  │                   │                │
│  │  users          │  │  stripe_events    │                │
│  │  drivers        │  │  refresh_tokens   │                │
│  │  rides          │  │  otp_records      │                │
│  │  payments       │  │  bg_task_heartbt  │                │
│  │  ride_ratings   │  │  ride_idmp_keys   │                │
│  │  driver_docs    │  │                   │                │
│  │  gps_breadcrumbs│  │                   │                │
│  └─────────────────┘  └───────────────────┘                │
│                                                             │
│  Schema: auth  (Supabase managed)                           │
│  └── auth.users  (phone auth)                              │
│                                                             │
│  Access paths:                                              │
│  • App runtime  →  PostgREST (HTTPS, supabase-py)           │
│  • Migrations   →  Alembic (direct TCP via Supavisor :5432) │
│  • Admin bypass →  SUPABASE_SERVICE_ROLE_KEY (BYPASSRLS)    │
│  • Client apps  →  BLOCKED (RLS deny-all on all tables)     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      Upstash Redis                          │
│                     (TLS, managed)                          │
│                                                             │
│  Key spaces:                                                │
│  • slowapi:*          rate-limit counters (TTL-based)       │
│  • spinr:ws:dispatch  pub/sub channel (WS fan-out)          │
│                                                             │
│  No persistence required — Redis is pure operational cache. │
│  Loss of Redis degrades (rate limits reset, WS local-only)  │
│  but does not cause data loss.                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Deployment pipeline

```
Developer pushes to GitHub
         │
         ▼
   GitHub Actions (ci.yml)
         │
         ├── Python lint + type-check
         ├── Python tests  (pytest, ~80% coverage)
         ├── alembic upgrade head --sql  (syntax validation)
         ├── k6 smoke  (1 VU × 30s vs staging)
         └── Build status → ✅ or ❌
                   │
                   ▼  merge to main
         ┌─────────────────────────────┐
         │  apply-supabase-schema.yml  │
         │  alembic upgrade head       │
         │  (against staging Supabase) │
         └─────────────────────────────┘
                   │
                   │  manual: flyctl deploy
                   ▼
              Fly.io build
                   │
                   ├── Docker multi-stage build
                   ├── Fly deploys new image
                   ├── Boot sequence runs (§4 above)
                   └── Health check passes → old machine removed

Mobile apps (EAS):
  ├── eas build  →  App Store / Play Store binaries
  └── eas update →  OTA patch (JS bundle only, < 15 min rollout)
```

---

## 7. Environment variables (required in production)

| Variable | Used by | What breaks if missing |
|---|---|---|
| `SUPABASE_URL` | All | All DB reads/writes fail |
| `SUPABASE_SERVICE_ROLE_KEY` | All | All DB reads/writes fail |
| `JWT_SECRET` | Auth | All auth tokens invalid |
| `SENTRY_DSN` | API + worker | Startup aborts in prod |
| `RATE_LIMIT_REDIS_URL` | API | Startup aborts in prod |
| `STRIPE_SECRET_KEY` | Webhooks | Payment processing fails |
| `STRIPE_WEBHOOK_SECRET` | Webhooks | Webhook signature fails |
| `TWILIO_ACCOUNT_SID` | Auth, emergency | OTP SMS fails |
| `TWILIO_AUTH_TOKEN` | Auth, emergency | OTP SMS fails |
| `TWILIO_PHONE_NUMBER` | Auth, emergency | OTP SMS fails |
| `FCM_SERVER_KEY` | Push notifications | Push notifications fail |
| `WS_REDIS_URL` | WS fan-out | Falls back to local-only (safe at 1 machine) |
| `FRONTEND_URL` | Share links | Share URLs point to localhost |
| `METRICS_BEARER_TOKEN` | `/metrics` | Metrics endpoint open to all |
| `ENVIRONMENT` | Config guard | Guards treated as dev |

---

## 8. Mobile app architecture

Both apps follow the same pattern:

```
Screen (Expo Router)
   │
   ▼
Zustand Store  (rideStore / authStore / driverStore)
   │
   ├── api.get / api.post  (Axios via shared/api/client.ts)
   │       │
   │       ├── withRefreshRetry interceptor
   │       │      ├── On 401: call POST /auth/refresh
   │       │      └── Retry original request once
   │       │
   │       └── Idempotency-Key header  (on POST /rides)
   │              └── UUID per attempt, reused across retries
   │
   └── WebSocket  (native WS, not Axios)
          └── Reconnects on close with exponential back-off
```

**Token lifecycle:**

```
Login (OTP verify)
   │
   ▼
POST /auth/verify-otp
   │
   └── Returns { access_token, refresh_token, expires_at }
              │
              ▼
         authStore.applyAuthResponse()
              │
              └── AsyncStorage  (persists across app restarts)

On API call with expired access token:
   │
   └── 401 response
         │
         ▼
   withRefreshRetry()  (single-flight: concurrent 401s queue)
         │
         └── POST /auth/refresh  { refresh_token }
                   │
                   └── New { access_token, refresh_token }
                              │
                              └── applyAuthResponse() → retry
```
