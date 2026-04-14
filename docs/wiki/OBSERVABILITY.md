# Spinr — Observability Stack

> **Role:** SRE / Platform Engineer  
> **Audience:** On-call engineers, DevOps, product (for SLOs)

---

## 1. The full stack

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SIGNALS                                         │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │   ERRORS     │  │   METRICS    │  │         LOGS             │  │
│  │              │  │              │  │                          │  │
│  │  Sentry      │  │  Prometheus  │  │  loguru JSON → Fly drain │  │
│  │  • backend   │  │  /metrics    │  │  → BetterStack / Loki    │  │
│  │  • worker    │  │  (bearer     │  │                          │  │
│  │  • rider app │  │   gated)     │  │  Fields per line:        │  │
│  │  • driver app│  │              │  │  time, level, message,   │  │
│  │  • admin dash│  │  Grafana     │  │  logger, function, line, │  │
│  │              │  │  dashboard   │  │  env, app, release,      │  │
│  │  Source maps │  │              │  │  machine_id              │  │
│  │  on all apps │  │              │  │                          │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘  │
│         │                 │                       │                 │
└─────────┼─────────────────┼───────────────────────┼─────────────────┘
          │                 │                       │
          ▼                 ▼                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                        ALERTING                                  │
│                                                                  │
│  Prometheus Alertmanager                                         │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  14 alert rules in 4 groups                               │   │
│  │                                                           │   │
│  │  severity=page  ──►  PagerDuty  (on-call phone)          │   │
│  │  severity=ticket ──►  Slack #spinr-alerts                │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  GitHub Actions synthetics (independent path)                    │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Every 5 min: /health shallow + deep                      │   │
│  │  Every 15 min: POST /rides/estimate (smoke)               │   │
│  │  Every 30 min: k6 latency synthetic                       │   │
│  │  All failures → Slack #spinr-alerts                       │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Sentry coverage

```
Surface          SDK                    What's captured
────────────────────────────────────────────────────────────────────
backend API      sentry-sdk (Python)    Unhandled exceptions,
                                        slow transactions (p95),
                                        breadcrumbs on 5xx routes.
                                        User: user_id, role.
                                        server_name: "spinr-api"

worker process   sentry-sdk (Python)    Background loop crashes.
                                        server_name: "spinr-worker"
                                        Tags: loop name, iteration #

rider-app        @sentry/react-native   JS crashes, ANR events.
                                        User cleared on logout.
                                        Sourcemaps from EAS build.

driver-app       @sentry/react-native   Same as rider-app.
                                        Separate Sentry project.

admin-dashboard  @sentry/nextjs         Client errors (browser),
                                        Server Component errors,
                                        Edge runtime errors.
                                        3 init files (client/server/edge)
────────────────────────────────────────────────────────────────────
```

**Startup guard** (backend):
```python
if settings.ENVIRONMENT != "development" and not settings.SENTRY_DSN:
    raise RuntimeError("SENTRY_DSN must be set in production")
```
The API process refuses to start without a valid DSN in production.

---

## 3. Prometheus metrics

```
Metric                              Type     Labels          What it measures
──────────────────────────────────────────────────────────────────────────────
spinr_active_rides                  Gauge    status          Active ride count by status
spinr_online_drivers                Gauge    —               Currently online drivers
spinr_stripe_events_pending         Gauge    —               Unprocessed Stripe events
spinr_bg_task_age_seconds           Gauge    task            Seconds since last heartbeat
spinr_http_requests_total           Counter  method,path,    Request count by route
                                             status_code
spinr_http_request_duration_seconds Histogram method,path    Latency distribution (p50/95/99)
spinr_ws_connections                Gauge    role            Active WS connections by role
──────────────────────────────────────────────────────────────────────────────
```

**Access control:**
```
GET /metrics
  Headers: Authorization: Bearer <METRICS_BEARER_TOKEN>
  Source IP must be in METRICS_ALLOWLIST_CIDR
  Returns: Prometheus text format
```

**Worker metrics** are exposed on port 9091, scraped independently:
```
scrape_configs:
  - job_name: spinr-api
    targets: ['spinr-api.fly.dev:443']
    bearer_token: <token>

  - job_name: spinr-worker
    targets: ['spinr-worker.internal:9091']
```

---

## 4. Grafana dashboard panels

```
┌────────────────────────────────────────────────────────────────┐
│  spinr-overview dashboard  (ops/grafana/spinr-overview.json)   │
│                                                                │
│  Row 1: Traffic                                                │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │  Request Rate    │  │   Error Rate     │                   │
│  │  req/s by method │  │   5xx %          │                   │
│  └──────────────────┘  └──────────────────┘                   │
│  ┌──────────────────────────────────────┐                     │
│  │  p95 Latency (all routes, 5-min win) │                     │
│  └──────────────────────────────────────┘                     │
│                                                                │
│  Row 2: Business KPIs                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ Active   │ │ Online   │ │ Stripe   │ │ Dispatch │         │
│  │ Rides    │ │ Drivers  │ │ Q Depth  │ │ Accept % │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
│                                                                │
│  Row 3: Background loops                                       │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  bg_task_age_seconds per loop (surge, dispatcher,      │   │
│  │  payment_retry, document_expiry, stripe_worker,        │   │
│  │  data_retention)                                       │   │
│  │  Red threshold line at 2 × expected_interval           │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│  Row 4: Infrastructure                                         │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │  WS Connections  │  │  Redis ops/sec   │                   │
│  │  by role         │  │  (rate limit +   │                   │
│  │  (rider/driver)  │  │   WS pub/sub)    │                   │
│  └──────────────────┘  └──────────────────┘                   │
└────────────────────────────────────────────────────────────────┘
```

---

## 5. SLOs and burn-rate alerts

### SLO targets

| SLO | Target | Window | Error budget |
|---|---|---|---|
| `/health` availability | 99.5% | 30-day rolling | 3.6 h/month |
| Crash-free users (mobile) | 99.0% | 7-day rolling | 1.68 h/week |
| Ride request p95 latency | < 2.0 s | 1-hour window | 0 / hr |
| WS heartbeat success | 99.0% | 5-min window | 3 s / 5 min |
| Payment capture success | 99.5% | 24-hour window | 7.2 min/day |
| Dispatch accept rate (60 s) | ≥ 90% | 1-hour window | 6 min/hr |
| Open P1 security items | 0 | continuous | n/a |

### Burn-rate alert structure

```
Each SLO has two alert windows (Google SRE Workbook §5 pattern):

FAST BURN (5-minute window)
  └── Triggers if error rate is burning the budget 14× faster
      than steady state. Fires within minutes of an incident.
      severity: page  →  PagerDuty

SLOW BURN (1-hour window)
  └── Triggers if error rate is burning the budget 2× faster
      than steady state. Catches gradual degradation.
      severity: ticket  →  Slack

Example: /health availability SLO = 99.5%
  allowed error rate = 0.5%
  fast burn threshold = 0.5% × 14 = 7.0% errors in 5 min
  slow burn threshold = 0.5% × 2  = 1.0% errors in 1 hour
```

### Alert routing tree

```
Alertmanager receives firing alert
          │
          ├── severity=page
          │     └── PagerDuty routing key
          │           └── On-call engineer notified by phone/SMS
          │
          ├── severity=ticket
          │     └── Slack #spinr-alerts webhook
          │           └── Engineer reviews within 4 hours
          │
          └── inhibit_rules:
                APIDown inhibits → APILatency
                (if the API is down, latency alerts add no info)
```

---

## 6. Synthetic monitors

```
GitHub Actions cron: */5 * * * *  (every 5 min)

┌──────────────────────────────────────────────────────────────┐
│  Job 1: health-shallow                                       │
│  GET /health  (prod + staging)                               │
│  Timeout: 10s   Expected: 200                                │
│  Failure → Slack (prod only)                                 │
├──────────────────────────────────────────────────────────────┤
│  Job 2: health-deep                                          │
│  GET /health/deep  (prod only)                               │
│  Timeout: 15s   Expected: 200                                │
│  Response body included in Slack alert                       │
│  Failure → Slack                                             │
├──────────────────────────────────────────────────────────────┤
│  Job 3: rider-smoke-flow  (every ~15 min)                    │
│  POST /rides/estimate  (staging)                             │
│  Body: Saskatoon pickup/dropoff                              │
│  Timeout: 20s   Expected: 200 or 401                         │
│  Failure → Slack                                             │
├──────────────────────────────────────────────────────────────┤
│  Job 4: k6-latency-synthetic  (every ~30 min)                │
│  k6 smoke scenario (1 VU × 30s)  (staging)                   │
│  Thresholds: p95 < 400ms, error rate < 0.1%                 │
│  Threshold breach → Slack                                    │
│  Does NOT page on-call (GH Actions timing too variable)      │
└──────────────────────────────────────────────────────────────┘
```

**Why two monitoring paths?**

```
Prometheus Alertmanager      GitHub Actions Synthetics
─────────────────────────    ─────────────────────────
Internal to Fly network      External to Fly network
Catches app-level issues     Catches DNS/edge/LB failures
Metric-driven (reliable)     Schedule-driven (approximate)
→ PagerDuty                  → Slack only
Fires in seconds             Fires within ~5 minutes
```

---

## 7. `/health/deep` response

```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "background_tasks": {
    "surge_engine": {
      "status": "ok",
      "age_seconds": 12,
      "expected_interval_seconds": 30,
      "stale": false
    },
    "scheduled_dispatcher": {
      "status": "ok",
      "age_seconds": 45,
      "expected_interval_seconds": 60,
      "stale": false
    },
    "stripe_event_worker": {
      "status": "error",
      "age_seconds": 75,
      "expected_interval_seconds": 5,
      "stale": true,
      "last_error": "connection timeout to Stripe API"
    }
  }
}
```

Returns `503 Service Unavailable` if:
- DB probe fails (SELECT 1)
- Redis probe fails (PING)
- Any background loop `age_seconds > 2 × expected_interval_seconds`

Returns `200 OK` only when everything is healthy.

---

## 8. Incident runbook index

| Runbook | Trigger signal |
|---|---|
| `api-down.md` | Synthetic /health failure OR APIDown Prometheus alert |
| `api-latency.md` | p95 > 2s (slow burn) or p95 > 5s (fast burn) |
| `bg-task-stale.md` | Any loop stale in `/health/deep` |
| `driver-not-receiving-rides.md` | Dispatch accept rate < 90% |
| `otp-lockout-false-positive.md` | Support tickets: "can't log in" spike |
| `stripe-webhook-failure.md` | `spinr_stripe_events_pending` gauge rising |

Every runbook structure:
```
1. Alert description
2. Immediate actions (< 2 min)
3. Diagnosis tree
4. Mitigation options
5. Escalation path
6. Post-incident checklist
```
