# Runbook: Background Task Stale / Erroring

**What this covers:** Diagnosing and recovering from a wedged or
error-reporting background loop. The relevant loops:

| Task name                | Cadence | Owner module                           |
|--------------------------|---------|----------------------------------------|
| `surge_engine`           | 60 s    | `backend/utils/surge_engine.py`        |
| `scheduled_dispatcher`   | 30 s    | `backend/utils/scheduled_rides.py`     |
| `payment_retry`          | 10 min  | `backend/utils/payment_retry.py`       |
| `document_expiry`        | 1 day   | `backend/utils/document_expiry.py`     |
| `subscription_expiry`    | 1 day   | `backend/routes/drivers.py` loop       |
| `stripe_event_worker`    | 5 s     | `backend/utils/stripe_worker.py`       |

Each loop calls `record_bg_task_heartbeat(task_name, status, error)`
at the end of every iteration (success or failure). `/health/deep`
and Prometheus both derive liveness from the `bg_task_heartbeat`
table.

**Severity:**
- `stripe_event_worker` stale → **P1** (receipts stall; runbook
  [`stripe-webhook-failure.md`](./stripe-webhook-failure.md) supersedes this one).
- `scheduled_dispatcher` stale → **P1** (pre-booked rides miss their
  pickup windows).
- Any other loop stale → **P2**.
- Loop reporting `error` but heartbeat fresh → **P2** (this runbook).

**Relevant alerts:**
- `SpinrBgTaskHeartbeatStale` — age > 10 min for 5 min (page)
- `SpinrBgTaskReportingError` — `last_status == 1` for 10 min (ticket)

---

## 1. Symptoms

- PagerDuty fired `SpinrBgTaskHeartbeatStale` with `task_name={...}`.
- `/health/deep` returns 503 with a `workers` block flagging one or
  more `stale: true`.
- Downstream: riders report "scheduled ride never dispatched",
  "no receipt arrived", or "surge pricing frozen at yesterday's rate".

---

## 2. Identify which loop and which failure mode

The alert label `task_name` narrows scope immediately. Two failure
modes exist:

1. **Wedged** — heartbeat age growing unbounded. The loop stopped
   running entirely (deadlock, infinite await, whole worker process
   died). Prometheus: `spinr_bg_task_heartbeat_age_seconds > 2 × interval`.
2. **Erroring** — heartbeat fresh, but `spinr_bg_task_last_status == 1`.
   The loop IS running but each iteration throws. The logic is the
   broken bit, not the scheduler.

Look at Grafana → "Background task heartbeat age" + "Background task
last status" panels side by side.

---

## 3. Triage Checklist

### 3.1 Worker process actually alive?

```bash
flyctl status -a spinr-api --process-group worker
flyctl logs  -a spinr-api --process-group worker | tail -200
```

- If `count: 0` / `suspended` — scale back up:
  `flyctl scale count 1 -a spinr-api --process-group worker`.
- If logs end with a traceback and no further activity → the process
  crashed and didn't auto-restart. `flyctl machine restart <id>`.

### 3.2 Only ONE loop stale vs. ALL loops stale?

- **All loops stale** → the worker process is dead. Fix = restart the
  worker.
- **One loop stale, others fresh** → the loop itself is deadlocked
  (await without timeout, infinite retry). The task-specific section
  below applies.

### 3.3 Sentry

Filter Sentry by `transaction:<task_name>` or search for the module
name. If the loop is erroring-but-alive, the exception class and a
stack trace will be there.

---

## 4. Per-task quick reference

### 4.1 `stripe_event_worker`

Start here: [`stripe-webhook-failure.md`](./stripe-webhook-failure.md).
That runbook covers dispatcher errors, Stripe rate limiting, and
queue depth. This file just confirms the loop is the problem; the
fix lives over there.

### 4.2 `scheduled_dispatcher`

Runbook: [`driver-not-receiving-rides.md`](./driver-not-receiving-rides.md)
covers dispatch-level failures generally. If ONLY scheduled rides
are failing (on-demand works), the issue is almost certainly a
`due_at` query or a timezone drift — check server UTC vs DB `now()`
first.

### 4.3 `surge_engine`

Wedging is low-impact — surge multipliers stay frozen at last known
value rather than updating every minute. Errors usually come from a
misconfigured surge area polygon. Inspect `service_areas.surge_config`
for the most recently edited row.

### 4.4 `document_expiry` / `subscription_expiry`

Daily loops. Staleness > 48 h is the concern. Often the first thing
to know is whether they ran at all since the worker restart — check
`bg_task_heartbeat.last_run_at` directly.

### 4.5 `payment_retry`

Payment retries failing silently means cards that should have
retried aren't. Check Sentry for `StripeError` class first; next
check `payment_attempts` table for rows with recent failures.

---

## 5. Recovery steps

### 5.1 Restart the worker (fixes wedge)

```bash
# Restart just the worker process group, leaves API serving:
flyctl machines list -a spinr-api
flyctl machine restart <worker-machine-id> -a spinr-api
```

Wait ~30 s, then verify:

```bash
curl -sf https://spinr-api.fly.dev/health/deep | jq .workers
```

All `stale: false`, all `status: "ok"` within two cadence periods of
restart.

### 5.2 Hot-fix a loop that's erroring

If the loop is throwing in a hot path (e.g. a newly deployed module
raised `KeyError` on a missing setting):

1. Identify the defect from Sentry.
2. If trivial — push a fix on a new release.
3. If not-trivial — temporarily `flyctl releases rollback` to the
   previous known-good release.
4. Re-verify with `/health/deep`.

### 5.3 Last resort: disable the loop

Every loop is registered in `backend/worker.py` or
`backend/core/lifespan.py`. If a loop is erroring badly enough to
pollute Sentry but isn't business-critical (surge, document_expiry),
you can comment it out in a hotfix release while the real fix is
being worked on. **Do not** disable `stripe_event_worker` or
`scheduled_dispatcher` this way — both cause user-visible data loss.

---

## 6. Post-incident

1. If the loop wedged (mode 1), the root cause is almost always an
   unawaited coroutine, a lock held across an `await`, or an HTTP
   call without a timeout. Add the timeout/cancel before closing.
2. If the loop errored-but-alive (mode 2), the root cause is code
   that handled the happy path but not the real data. Add a test
   with the malformed row before closing.
3. Update this runbook's per-task section if the recovery was
   non-obvious. Future-you will thank present-you.

---

## 7. Related

- SLO: `docs/ops/SLOs.md#slo-5-background-task-heartbeat-freshness`
- Alerts: `ops/prometheus/alerts.yml` (group: `background-tasks`)
- Health endpoint: `backend/routes/main.py` (`/health/deep`)
- Schema: migration `0005_bg_task_heartbeat`
- Adjacent runbooks:
  - [`stripe-webhook-failure.md`](./stripe-webhook-failure.md)
  - [`driver-not-receiving-rides.md`](./driver-not-receiving-rides.md)
