# Multi-Region Standby

Plan for surviving a regional outage — Fly region failure, Supabase
regional incident, or upstream network partition that isolates `yyz`
from the rest of the internet. This document captures the target
architecture, failover modes, and the explicit decision to **defer
multi-region to Q2** (post-launch).

Related: [`BACKUP_DR.md`](BACKUP_DR.md), [`SLOs.md`](SLOs.md).

---

## 1. Current state

* **Backend:** single Fly app `spinr-backend`, region `yyz` (Toronto).
* **Database:** Supabase Postgres, single region (aligned with `yyz`).
* **Redis:** single Upstash/Fly Redis instance co-located with `yyz`.
* **Launch markets:** Saskatoon, Regina (Saskatchewan). Traffic is
  entirely in-Canada; `yyz` is the lowest-latency Fly region for SK.

### Risks

| Failure | Blast radius | Mitigation today |
| --- | --- | --- |
| Fly `yyz` region outage | Full platform down. Riders/drivers cannot request, dispatch, or complete rides. | None — waiting on Fly. Incident comms via status page. |
| Supabase regional incident | Full platform down (DB unreachable). | Hourly PITR snapshots (see BACKUP_DR). Cannot serve reads. |
| Network partition isolating `yyz` | Same as Fly outage from user perspective. | None. |
| Upstash Redis outage | Rate limiting + WS fan-out degraded; rides still complete (fail-open on Redis). | Fail-open already in place. |

RTO today: bounded only by Fly/Supabase incident recovery — typically
minutes to hours, no SLA commitment from us.

---

## 2. Target state (Q2+)

**Hot standby in a second Fly region** (candidate: `ord` Chicago, or
`sea` Seattle — both have low RTT to SK and are separate failure
domains from `yyz`).

* Standby Fly machines running the same image, health-checked, idle
  under normal operation.
* Supabase **read replica** in the standby region (paid-tier feature).
  Async replication, typical lag < 1s.
* Region-local Redis in the standby region (cache state is disposable;
  no replication needed).

**Not full active/active.** Dispatch is stateful: in-memory driver
proximity indexes, ride-state machines, and WS fan-out assume a single
writer. Splitting writes across regions would require either global
consensus (Spanner-class) or geographic sharding by market — neither
is justified for SK-only launch.

Model: **active/passive with read-only degraded mode**.

---

## 3. Architecture

```
                    +----------------------+
                    | DNS (Cloudflare/     |
                    | Fastly, health-check |
                    | based failover)      |
                    +----------+-----------+
                               |
                   +-----------+-----------+
                   |                       |
             (normal)                (failover only)
                   |                       |
          +--------v--------+     +--------v--------+
          | Fly region: yyz |     | Fly region: ord |
          | (PRIMARY)       |     | (STANDBY)       |
          |                 |     |                 |
          | API (R/W)       |     | API (R/O mode)  |
          | WS fan-out      |     | WS fan-out      |
          | Redis (local)   |     | Redis (local)   |
          +--------+--------+     +--------+--------+
                   |                       |
                   |    async replication  |
          +--------v--------+     +--------v--------+
          | Supabase PG     +---->| Supabase read   |
          | (PRIMARY)       |     | replica (R/O)   |
          +-----------------+     +-----------------+
                   ^                       ^
                   |                       |
           writes  |                       | reads (failover)
                   |                       |
             +-----+-----------------------+
             |      Stripe webhooks         |
             |      (single DNS endpoint)   |
             +------------------------------+
```

WS fan-out (Phase 2.1 — Redis pub/sub) must be **region-local**:
each region has its own Redis, each backend machine subscribes only
to its region. Cross-region WS delivery is not a goal; clients
reconnect to whichever region DNS resolves them to.

---

## 4. Failover modes

### a) Automatic — DNS health-check failover (read-only degraded)

Cloudflare (or Fastly) health-checks `https://api.spinr.app/healthz`
against `yyz` every 30s. On 3 consecutive failures:

* DNS record flips to standby region.
* Standby backend comes up with `SPINR_MODE=read_only` env var set.
* Read-only mode serves: `/healthz`, ride history (`GET /rides/*`),
  profile reads, auth token verification (JWT is stateless).
* Read-only mode rejects: ride creation, dispatch, payments, location
  updates — returns 503 with a user-facing "service degraded" message.
* Mobile apps detect 503 on write paths and show a banner; reads
  (trip history) keep working.

Intended window: minutes to ~1 hour while on-call promotes the
standby or waits out the primary incident.

### b) Manual — promote standby to primary

Full failover. Executed by on-call with approval from founder +
eng lead:

1. **Confirm primary is down** and unlikely to recover in RTO
   window. Check Fly status page, Supabase status page.
2. **Promote Supabase read replica:**
   * Supabase dashboard → Database → Read replicas → **Promote**.
   * ~5-minute RTO. Replica becomes a standalone primary; old
     primary must be reset before it rejoins.
   * Data loss window = replication lag at time of promotion
     (typically < 1s; check dashboard before promoting).
3. **Redirect backend writes to new DB:**
   ```bash
   fly secrets set SUPABASE_URL='<new-primary-url>' \
                   SUPABASE_SERVICE_ROLE_KEY='<new-key>' \
                   --app spinr-backend
   ```
4. **Scale up standby region, scale down primary:**
   ```bash
   flyctl scale count 2 --region ord --app spinr-backend
   flyctl scale count 0 --region yyz --app spinr-backend
   ```
5. **Flip DNS manually** if automatic failover has not already fired.
6. **Unset `SPINR_MODE=read_only`** so the promoted region accepts
   writes.
7. **Update Stripe webhook endpoint** if the endpoint URL is not
   region-agnostic (see §5).

Target RTO: ~15 minutes end-to-end, dominated by the Supabase
promotion.

Target RPO: < 1 second (async replication lag), unless replication
was already falling behind pre-outage.

---

## 5. What must be region-aware before failover ships

Explicit checklist — each item blocks multi-region go-live:

- [x] **Stateless API handlers.** Already true. Backend holds no
      per-instance state that survives a request. Dispatch state
      lives in Postgres; driver proximity is re-computable from DB.
- [x] **JWT verification is stateless.** `JWT_SECRET` is the same in
      both regions (Fly secret replicated manually). No per-region
      session store.
- [ ] **WebSocket connection tracking uses per-region Redis.** Each
      region publishes only to its own Redis; no cross-region WS
      delivery. Clients reconnect after DNS flip. (Requires Phase 2.1
      Redis pub/sub to land first.)
- [x] **Redis data is acceptable loss.** Rate-limit counters and WS
      routing tables are cache-only. Cold start in a new region is
      fine — worst case is one request not rate-limited.
- [ ] **Stripe webhook URL is region-agnostic.** Must route through
      the same DNS name that DNS failover flips (`webhooks.spinr.app`
      or similar). Stripe does not support multiple endpoint URLs
      with failover semantics; the webhook handler must be reachable
      at whichever region is live.
- [x] **FCM token mappings live in Postgres.** Region-agnostic — the
      promoted DB has all push tokens. No per-region FCM state.
- [ ] **Supabase Storage region.** Signed URLs for driver docs /
      profile photos are region-scoped; confirm with Supabase whether
      Storage fails over with the DB or must be replicated separately.
- [ ] **Fly secrets parity.** Every secret set on `spinr-backend` in
      `yyz` must also be set for the standby. Add a pre-deploy check:
      `fly secrets list` diff between regions.
- [ ] **Runbook rehearsal.** Tabletop exercise + at least one live
      failover to the standby in staging before production cut-over.

Items marked `[x]` are true today; `[ ]` must be completed before
multi-region can go live.

---

## 6. Cost & complexity trade-off

| Cost | Estimate |
| --- | --- |
| Extra Fly machines in standby region (idle hot-standby) | +30-40% of current Fly spend |
| Supabase read replica (paid tier) | +~50% of current Supabase spend |
| Second Redis instance | +~$20/month (Upstash) |
| Cloudflare / Fastly health-check DNS | ~$20/month or free tier |
| **Total infra delta** | **~30-50% of current infra bill** |
| Eng build-out (design, wire-up, runbook, rehearsal) | ~10 eng-days |
| Ongoing ops tax (parity checks, rehearsals) | ~0.5 day/quarter |

This is a real number but not a large absolute number at launch
scale. The constraint is **eng time**, not dollars.

---

## 7. Decision log

**2026-04 — defer multi-region to Q2 (post-launch).**

Rationale:

* Launch markets (Saskatoon, Regina) are small; an hour of downtime
  affects hundreds of rides, not millions.
* Fly `yyz` and Supabase have no history of multi-hour regional
  outages in the last 12 months. Baseline availability is acceptable
  for launch.
* Phase 4.8 (backup/DR) gives us PITR restore inside ~1 hour — the
  same order of magnitude as a manual multi-region failover.
* Phase 2.6 (synthetic monitors) catches regional degradation fast
  enough to trigger a status-page update and begin manual recovery.
* Eng time in Q1 is better spent on dispatch correctness, payment
  idempotency, and launch-blocking items.

Revisit trigger — any of:

1. First post-launch Fly `yyz` incident > 30 minutes.
2. Expansion beyond SK to a second province (failure domain diversity
   matters more when the business is bigger).
3. Enterprise / B2B customer contract requiring an availability SLA
   we cannot meet single-region.
4. Supabase announces regional degradation pattern affecting our
   region.

Owner: eng lead. Review quarterly at the ops review.

---

## 8. Related

* [`BACKUP_DR.md`](BACKUP_DR.md) — PITR, snapshot cadence, restore
  drill. The single-region DR story that multi-region augments but
  does not replace.
* [`SLOs.md`](SLOs.md) — availability targets. Multi-region is the
  lever we pull to raise the availability SLO past single-region
  ceilings.
* Audit roadmap: Phase 4.10 in
  `docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md`.
