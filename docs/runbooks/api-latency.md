# Runbook: API Latency

**What this covers:** Diagnosing and mitigating elevated API response
latency, specifically when p95 request duration exceeds the 500 ms
SLO target (see `docs/ops/SLOs.md` SLO-2).

**Severity:** P2 — service is up but degraded UX. Escalate to P1 if
latency degrades into timeouts (> 10 s) or cascades into 5xx errors.

**Prerequisites:**
- Grafana access ("Spinr — Production Overview" dashboard)
- Fly.io CLI (`flyctl`) + access to the `spinr-api` app
- Supabase project dashboard (Database → Query performance)
- Sentry access

**Relevant alerts:**
- `SpinrAPILatencyFastBurn` — p95 > 500 ms on > 25% of requests for 10 min (page)
- `SpinrAPILatencySlowBurn` — sustained > 10% slow for 30 min (ticket)

---

## 1. Symptoms

- Rider/driver apps show visible loading spinners where they used to snap in.
- Admin dashboard tables take multiple seconds to load.
- Grafana "API p95 latency by handler" panel trending above the 0.5 s line.
- `SpinrAPILatencyFastBurn` paged you.

---

## 2. Triage Checklist (stop when you find the cause)

- [ ] Which handlers are slow? (Grafana p95-by-handler panel)
- [ ] Is it one handler or the whole API? (one handler → downstream;
      everything → compute / DB / network)
- [ ] Is the DB hot? (Supabase → Database → Query performance)
- [ ] Did anything deploy in the last 30 min? (`flyctl releases list`)
- [ ] Are we rate-limited somewhere? (Sentry for `429` spikes from
      Stripe / Google Maps / FCM)
- [ ] CPU saturated on a Fly machine? (`flyctl machine status`)
- [ ] Background task blocking the event loop? (look at
      `spinr_bg_task_heartbeat_age_seconds` — if one loop is growing
      unbounded the event loop may be pinned)

---

## 3. Diagnosis

### 3.1 Narrow down "which handler"

Open Grafana → "Spinr — Production Overview" → "API p95 latency by
handler". The top one or two lines are usually the answer. The common
cases:

- `/api/rides/request` slow → dispatcher or driver-search query.
- `/api/payments/*` slow → Stripe API latency or network egress.
- `/api/drivers/location` slow → PostGIS / `drivers.location` write contention.
- Everything slow → shared resource: DB pool, Redis, Fly machine.

### 3.2 Check the database

```bash
# In Supabase SQL editor:
select
  round(mean_exec_time::numeric, 2) as mean_ms,
  calls,
  query
from pg_stat_statements
order by mean_exec_time desc
limit 20;
```

Look for a query that's suddenly near the top that wasn't before.
`mean_exec_time * calls` = total wall time; a slow rare query may not
matter, a medium query called 1000×/min does.

### 3.3 Check Fly machine health

```bash
flyctl status -a spinr-api
flyctl machine status <machine-id> -a spinr-api
```

Look for `cpu` / `mem` pressure. If one machine is pegged and siblings
are idle, the LB stickiness is probably dragging a specific user onto
one box — restart the hot machine:

```bash
flyctl machine restart <machine-id> -a spinr-api
```

### 3.4 Check upstream dependencies

Sentry Performance → filter by `http.client` spans. If Stripe or
Google Maps p95 jumped in the same window, the slowness is not ours —
file a status ticket with them and add a breaker/timeout locally.

---

## 4. Mitigations (in order of preference)

### 4.1 Roll back a recent deploy

If the fast-burn alert coincides with a deploy, this is almost always
the fix.

```bash
flyctl releases list -a spinr-api
flyctl releases rollback <previous-release> -a spinr-api
# Remember to roll back the worker process group too if the change
# touched shared code:
flyctl releases rollback <previous-release> -a spinr-api --process-group worker
```

### 4.2 Scale the API horizontally

Add machines while you investigate. Safe and reversible.

```bash
flyctl scale count 4 -a spinr-api --process-group app
```

### 4.3 Kill a hung query

If a specific DB query is dominating:

```sql
-- Find it:
select pid, now() - query_start as duration, state, query
  from pg_stat_activity
 where state != 'idle'
 order by duration desc
 limit 20;

-- Kill it (cancel first, terminate only if cancel doesn't clear it):
select pg_cancel_backend(<pid>);
select pg_terminate_backend(<pid>);
```

### 4.4 Enable circuit-breaker on a slow upstream

For Stripe / FCM / Maps — if they're slow, we should be returning a
user-visible "try again" rather than queueing requests. Bump timeouts
down in the relevant client module and deploy, then post a status
page update.

---

## 5. Post-incident

1. File a ticket with the SLO tag if > 5% of the 30-day error budget
   was burned (see `docs/ops/SLOs.md` for the math).
2. Capture the timeline in a Sentry issue comment linked from the
   PagerDuty incident.
3. If the root cause is a query, add an index or a rewrite to the
   next sprint — latency alerts should produce durable fixes, not
   just "I restarted the box".

---

## 6. Related

- SLO: `docs/ops/SLOs.md#slo-2-api-latency-p95`
- Alerts: `ops/prometheus/alerts.yml` (group: `api-latency`)
- Dashboard: `ops/grafana/spinr-overview.json`
- Adjacent runbooks:
  - [`api-down.md`](./api-down.md) (if latency tips over into 5xx)
  - [`driver-not-receiving-rides.md`](./driver-not-receiving-rides.md)
    (if `/rides/*` handlers are the ones slow)
