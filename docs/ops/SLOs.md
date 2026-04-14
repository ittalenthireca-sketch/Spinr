# Spinr — Service Level Objectives

Phase 2.4a of the production-readiness audit (audit finding T2).

This document is the single source of truth for what "good" looks
like operationally. Every alert in `ops/prometheus/alerts.yml`
ultimately traces back to one of these SLOs — if an alert fires, the
runbook link in its annotations points at the remediation path.
If an alert is noisy, the right fix is almost always to tune the
SLO here (not to silence the alert).

## Conventions

- **SLI** (service level indicator) — the measured quantity. Always a
  ratio of "good" events / "total" events, so error budgets
  compose cleanly.
- **SLO** (service level objective) — the target value for the SLI
  over a rolling window.
- **Error budget** = 100% − SLO, over the same window.
- **Burn rate** = the rate at which we're consuming budget. A burn
  rate of 1.0 means "at this pace we finish the budget exactly at
  the end of the window"; 14.4 means "we'll burn the whole month's
  budget in 2 hours" (industry-standard fast-burn threshold).

All SLOs use a **30-day rolling window** unless otherwise noted. The
compliance window is shorter than a calendar month so on-call
operators don't have to think about month boundaries during an
incident.

---

## SLO-1: API Availability

**Owner:** Backend on-call.
**Audience:** Riders, drivers, admins — every HTTP request hits this.

### SLI
Ratio of API requests that return a non-5xx response.

```promql
sum(rate(http_requests_total{status!~"5.."}[5m]))
  /
sum(rate(http_requests_total[5m]))
```

### SLO
**99.9%** over 30 days.

- Budget: **43.2 min** of full-outage-equivalent downtime / month.
- Breaching this SLO is a P1 incident.

### Notes
- 4xx responses are counted as "good" because a 401/403/404 is the
  API correctly rejecting a request — not an outage.
- Health-check endpoints (`/health`, `/health/deep`, `/metrics`)
  are excluded from the denominator so a scraper outage can't
  inflate the error rate.

---

## SLO-2: API Latency (p95)

**Owner:** Backend on-call.

### SLI
Ratio of API requests whose end-to-end latency is under 500 ms.

```promql
sum(rate(http_request_duration_seconds_bucket{le="0.5"}[5m]))
  /
sum(rate(http_request_duration_seconds_count[5m]))
```

### SLO
**95%** of requests under 500ms over 30 days.

- Budget: 5% of requests may exceed 500ms.
- Breach is a P2 — degraded UX but service is up.

### Notes
- WebSocket upgrade handlers are excluded at the instrumentator
  level (`excluded_handlers` in `utils/metrics.py`).
- This is an end-to-end latency SLO — it includes DB round-trips and
  upstream calls (Stripe, Supabase). Don't separate them; fragmented
  SLOs generate alert noise without improving remediation.

---

## SLO-3: Ride Dispatch Latency (p95)

**Owner:** Backend on-call + product (dispatch engine tuning).
**Audience:** Riders — "driver found" time is the single most
user-visible latency in the whole app.

### SLI
Ratio of ride dispatches that find a driver in under 30 seconds.

```promql
sum(rate(spinr_ride_dispatch_latency_seconds_bucket{le="30"}[15m]))
  /
sum(rate(spinr_ride_dispatch_latency_seconds_count[15m]))
```

### SLO
**95%** of dispatches assign a driver within 30 seconds, 30-day window.

- Budget: 5% of requested rides may take longer than 30s to dispatch.
- Breach is a P2.

### Notes
- "Dispatch" here means `searching → driver_assigned`; it does NOT
  include the driver actually accepting. That's a separate product
  metric (acceptance rate) without an SLO.
- Budget consumption spikes usually track driver-supply shortfalls
  (low `active_drivers` gauge in Grafana) or surge-pricing
  mis-configuration. Runbook: `docs/runbooks/driver-not-receiving-rides.md`.

---

## SLO-4: Stripe Event Queue Drain

**Owner:** Backend on-call.
**Audience:** Finance, riders (payment receipts), drivers (payouts).

### SLI
Maximum age of the oldest unprocessed row in `stripe_events`. We use
the queue depth as a proxy because Prometheus doesn't emit a "max
age" histogram bucket — but the 5-second worker loop means a
depth > 50 translates directly to a > 250s-old event.

```promql
max_over_time(spinr_stripe_queue_depth[5m])
```

### SLO
Queue depth must stay below **50** for 95% of 5-min windows over the
30-day period.

- Breach = queue backed up → payment receipts stuck → risk of double-
  charging on retry if the worker restarts mid-flight.
- P1 incident if depth > 200 for 10 minutes (see burn-rate alert).

### Notes
- Steady-state queue depth is near-zero. A sustained non-zero value
  almost always means the worker process is wedged or the Stripe API
  is rate-limiting us.
- Runbook: `docs/runbooks/stripe-webhook-failure.md`.

---

## SLO-5: Background Task Heartbeat Freshness

**Owner:** Backend on-call.

### SLI
For each background task, the ratio of time it stays within 2×
expected interval. Computed by `/health/deep` already — the SLO
view just aggregates across tasks.

```promql
sum(spinr_bg_task_heartbeat_age_seconds > on(task_name) (2 * spinr_bg_task_expected_interval_seconds))
  /
count(spinr_bg_task_heartbeat_age_seconds)
```

### SLO
**99%** of task-minutes are "fresh" (age < 2× expected interval),
30-day window.

- Breach means a loop has wedged — scheduled rides not dispatching,
  failed payments not retrying, etc.
- P1 if `stripe_event_worker` is stale; P2 for the others.

### Notes
- The 2× threshold matches the `/health/deep` endpoint logic in
  `routes/main.py` so Grafana, Prometheus, and the healthcheck all
  agree on what "stale" means.

---

## Error budget policy

Spending the error budget isn't "bad" — it's the signal that we're
free to ship risky changes. Hoarding budget means we're being too
cautious (or the SLO is set too low).

- **Budget > 50% remaining, mid-window:** Normal. Ship features,
  run experiments, deploy on Fridays if you're brave.
- **Budget 10-50% remaining:** Slow deploys. No migrations that
  would extend a rollback path.
- **Budget < 10% remaining:** Freeze all non-critical deploys
  until the next window starts. Post-mortem every incident.
- **Budget exhausted:** All new deploys require sign-off from the
  backend on-call + the product owner. The bar is "this deploy
  reduces risk, not adds risk."

## Review cadence

- **Weekly:** Backend on-call scans the SLO dashboard (Grafana →
  "Spinr — SLOs") and flags any SLO that burned more than 20% of
  its budget that week.
- **Quarterly:** Product + engineering review SLO targets. Any SLO
  that has been green for a full quarter gets tightened; any SLO
  that has been red for a full quarter gets investigated (often
  the root cause is architecture, not an operator error).

---

## Related

- Alert rules: `ops/prometheus/alerts.yml`
- Alertmanager routing: `ops/alertmanager/alertmanager.yml`
- Dashboard: `ops/grafana/spinr-overview.json`
- Runbooks: `docs/runbooks/`
