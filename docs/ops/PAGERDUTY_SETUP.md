# Spinr — PagerDuty Setup Guide

Phase 2.4d of the production-readiness audit (audit finding T2).

This guide wires PagerDuty into the Alertmanager routing configuration
already committed at `ops/alertmanager/alertmanager.yml`. When complete,
every alert labelled `severity: page` will wake on-call; every alert
labelled `severity: ticket` will post to Slack only.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create the Spinr API Service in PagerDuty](#2-create-the-spinr-api-service-in-pagerduty)
3. [Configure the Escalation Policy](#3-configure-the-escalation-policy)
4. [On-Call Rotation](#4-on-call-rotation)
5. [Wire the Integration Key into Fly.io](#5-wire-the-integration-key-into-flyio)
6. [Test the Integration](#6-test-the-integration)
7. [Severity Routing Reference](#7-severity-routing-reference)
8. [Maintenance Windows (Suppress Alerts During Deploys)](#8-maintenance-windows-suppress-alerts-during-deploys)

---

## 1. Prerequisites

| Item | Status |
|------|--------|
| PagerDuty account with admin access | Required before starting |
| Alertmanager config committed at `ops/alertmanager/alertmanager.yml` | Already present |
| Fly.io CLI installed and authenticated (`fly auth whoami`) | Required for step 5 |
| Slack `#spinr-alerts` webhook already set (`SPINR_SLACK_WEBHOOK_ALERTS`) | Should already be set |
| At least two engineers with PagerDuty accounts and the mobile app installed | Required before step 3 |

> Alertmanager already expects `${SPINR_PAGERDUTY_ROUTING_KEY}` injected
> as a Fly.io secret. You only need to obtain the key from PagerDuty and
> store it — no YAML changes required.

---

## 2. Create the Spinr API Service in PagerDuty

### 2.1 Open the Services page

1. Log in to PagerDuty.
2. In the top navigation, click **Services** > **Service Directory**.
3. Click **+ New Service** (top-right).

### 2.2 General settings

Fill in the **General Settings** form:

| Field | Value |
|-------|-------|
| Name | `Spinr API` |
| Description | `FastAPI backend on Fly.io — rides, payments, driver dispatch` |
| Escalation Policy | Leave blank for now; you will assign this in step 3 |

Click **Next**.

### 2.3 Reduce noise settings

On the **Reduce Noise** page, use these settings:

| Setting | Recommended value | Rationale |
|---------|------------------|-----------|
| Alert grouping | **Intelligent** | Groups related alerts automatically |
| Alert grouping time window | **5 minutes** | Matches Alertmanager `group_interval: 5m` |
| Auto-resolve incidents | **On** | Alertmanager sends resolved payloads |
| Auto-resolve after | **30 minutes** | Clears ghost incidents if Alertmanager misses a resolve |

Click **Next**.

### 2.4 Integrations — select Prometheus Alertmanager

1. On the **Integrations** page, search for **Prometheus**.
2. Select **Prometheus Alertmanager** (Events API v2).
3. Click **Create Service**.

PagerDuty creates the service and drops you on the service's
**Integrations** tab.

### 2.5 Copy the integration key

On the **Integrations** tab, find the row labelled
**Prometheus Alertmanager** and click the gear icon > **Copy Key**.

This is the `routing_key` value that goes into Fly.io in step 5.
Store it in your password manager immediately — you need it once and
it is not re-displayed.

---

## 3. Configure the Escalation Policy

### 3.1 Create the policy

1. In PagerDuty, click **People** > **Escalation Policies**.
2. Click **+ New Escalation Policy**.
3. Set the name to `Spinr On-Call`.
4. Enable **Repeat this policy** if all levels are unreachable, then
   set **repeat** to `0` times (one-shot — if nobody responds after
   level 3, the incident stays open; do not loop silently).

### 3.2 Define the three escalation levels

#### Level 1 — On-call engineer (immediate)

| Setting | Value |
|---------|-------|
| Notify after | 0 minutes (immediately) |
| Notifies | Current on-call engineer (assigned via schedule — see step 4) |
| Notification rules | Push notification (PagerDuty app) + Phone call |
| Acknowledgement timeout | **15 minutes** |

#### Level 2 — Backup engineer (15 min)

| Setting | Value |
|---------|-------|
| Escalate after | 15 minutes unacknowledged |
| Notifies | Backup on-call engineer |
| Notification rules | Push notification + Phone call |
| Acknowledgement timeout | **15 minutes** |

#### Level 3 — Engineering lead (30 min)

| Setting | Value |
|---------|-------|
| Escalate after | 30 minutes unacknowledged (15 min from level 2 trigger) |
| Notifies | Engineering lead (static user, not a schedule) |
| Notification rules | Push notification + Phone call + SMS |

Click **Save**.

### 3.3 Attach the policy to the service

1. Go back to **Services** > **Spinr API**.
2. Click **Edit Service**.
3. Under **Escalation Policy**, select **Spinr On-Call**.
4. Click **Save**.

---

## 4. On-Call Rotation

### 4.1 Create an on-call schedule

1. In PagerDuty, click **People** > **On-Call Schedules**.
2. Click **+ New Schedule**.
3. Name: `Spinr Primary On-Call`.
4. Time zone: `America/Toronto` (Eastern, where the team is based).
5. Add a **Weekly** rotation, starting Monday 09:00.
6. Add all primary on-call engineers to the layer.
7. Repeat for `Spinr Backup On-Call` with the backup engineers.

### 4.2 Update the escalation policy

1. Edit `Spinr On-Call`.
2. At **Level 1**, change the target from a static user to the
   `Spinr Primary On-Call` schedule.
3. At **Level 2**, change the target to the `Spinr Backup On-Call` schedule.
4. Save.

### 4.3 On-call roster template

Populate and maintain this table. Keep a copy in the team wiki and
update it each rotation change.

| Name | Mobile (CA) | Primary window | Backup window |
|------|-------------|----------------|---------------|
| _Engineer A_ | +1 (416) 555-0001 | Week 1 Mon–Sun | Week 3 Mon–Sun |
| _Engineer B_ | +1 (604) 555-0002 | Week 2 Mon–Sun | Week 1 Mon–Sun |
| _Engineer C_ | +1 (613) 555-0003 | Week 3 Mon–Sun | Week 2 Mon–Sun |
| _Engineering lead_ | +1 (416) 555-0099 | Level 3 only | Level 3 only |

> Replace the placeholder rows with real names and numbers before
> going live. Verify each engineer's PagerDuty notification rules
> (app + phone) are confirmed — a missed configuration is a missed page.

---

## 5. Wire the Integration Key into Fly.io

Alertmanager reads `${SPINR_PAGERDUTY_ROUTING_KEY}` at startup via
env-subst. The Fly.io secret is the authoritative source.

### 5.1 Set the secret

```bash
fly secrets set SPINR_PAGERDUTY_ROUTING_KEY=<paste-key-here> \
  --app spinr-api
```

Fly.io automatically triggers a rolling restart of the `spinr-api` app
so Alertmanager picks up the new value without downtime.

### 5.2 Verify the secret is present

```bash
fly secrets list --app spinr-api | grep PAGERDUTY
```

Expected output:

```
SPINR_PAGERDUTY_ROUTING_KEY    Set 2026-04-17
```

### 5.3 Confirm Alertmanager loaded the key

After the restart completes (usually 30–60 seconds):

```bash
fly ssh console --app spinr-api -C \
  "alertmanager --version && curl -s http://localhost:9093/-/healthy"
```

A `200 OK` from `/-/healthy` means Alertmanager is up. If it
exits immediately, the config failed validation — run
`alertmanager --config.file=/etc/alertmanager/alertmanager.yml --check-config`
inside the console to see the error.

---

## 6. Test the Integration

### 6.1 Send a synthetic alert via amtool

`amtool` ships inside the Alertmanager container. SSH in and fire a
test alert manually:

```bash
fly ssh console --app spinr-api

# Inside the container:
amtool alert add \
  --alertmanager.url=http://localhost:9093 \
  alertname="SpinrIntegrationTest" \
  severity="page" \
  slo="api-availability" \
  team="backend" \
  --annotation summary="PagerDuty wiring test — safe to resolve" \
  --annotation description="Sent by ops team to verify routing. Resolve immediately." \
  --annotation runbook_url="https://github.com/ittalenthireca-sketch/Spinr/blob/main/docs/ops/PAGERDUTY_SETUP.md"
```

### 6.2 Confirm the incident appears in PagerDuty

1. Open **PagerDuty** > **Incidents**.
2. You should see a new incident titled `SpinrIntegrationTest` within
   10 seconds (Alertmanager `group_wait` for page alerts is 10s).
3. The incident detail should show the `runbook`, `summary`, and
   `description` fields populated from the alert annotations.

### 6.3 Confirm Slack mirrors the page

Check `#spinr-alerts` in Slack. The `continue: true` route in
`alertmanager.yml` means every paging alert also posts to Slack for
team visibility. You should see a message formatted like:

```
[FIRING x 1] SpinrIntegrationTest
PagerDuty wiring test — safe to resolve
...
```

### 6.4 Resolve the test alert

```bash
# Still inside the container:
amtool alert expire \
  --alertmanager.url=http://localhost:9093 \
  alertname="SpinrIntegrationTest"
```

PagerDuty should auto-resolve the incident within 5 minutes
(`resolve_timeout: 5m` in `alertmanager.yml`). Alternatively,
resolve it manually in the PagerDuty UI.

### 6.5 Test a ticket-only alert (Slack, no page)

```bash
amtool alert add \
  --alertmanager.url=http://localhost:9093 \
  alertname="SpinrSlackOnlyTest" \
  severity="ticket" \
  slo="api-availability" \
  --annotation summary="Slack-only routing test — no page expected"
```

Confirm:
- Slack `#spinr-alerts` receives the message.
- No incident is created in PagerDuty.

Resolve when done:

```bash
amtool alert expire \
  --alertmanager.url=http://localhost:9093 \
  alertname="SpinrSlackOnlyTest"
```

---

## 7. Severity Routing Reference

Routing is controlled by the `severity` label on each Prometheus alert
in `ops/prometheus/alerts.yml`. The table below maps Spinr's specific
alerts to their routing destination.

### 7.1 Alerts that page on-call (severity: page)

These fire the `pagerduty-backend` receiver and simultaneously mirror
to `#spinr-alerts`.

| Alert name | Condition | SLO | Runbook |
|------------|-----------|-----|---------|
| `SpinrAPIAvailabilityFastBurn` | API 5xx error rate > 1.44% for 5m (14.4x burn rate — budget exhausted in ~2h) | SLO-1: API Availability | `docs/runbooks/api-down.md` |
| `SpinrAPILatencyFastBurn` | > 25% of requests slow (> 500ms) for 10m | SLO-2: API Latency | `docs/runbooks/api-latency.md` |
| `SpinrRideDispatchLatencyHigh` | p95 dispatch latency > 60s for 10m (SLO target is 30s) | SLO-3: Dispatch Latency | `docs/runbooks/driver-not-receiving-rides.md` |
| `SpinrActiveRidesStuckSearching` | > 20 rides stuck in `searching` state for 5m | SLO-3: Dispatch Latency | `docs/runbooks/driver-not-receiving-rides.md` |
| `SpinrStripeQueueCritical` | Stripe event queue depth > 200 for 10m — payment processing stalled | SLO-4: Stripe Queue | `docs/runbooks/stripe-webhook-failure.md` |
| `SpinrBgTaskHeartbeatStale` | Any background task heartbeat age > 10m | bg-tasks | `docs/runbooks/bg-task-stale.md` |

### 7.2 Alerts that go to Slack only (severity: ticket)

These fire the `slack-alerts` receiver only. No incident is created in
PagerDuty. Review during business hours.

| Alert name | Condition | Rationale |
|------------|-----------|-----------|
| `SpinrAPIAvailabilitySlowBurn` | API 5xx rate > 0.6% sustained 30m (slow regression, budget not in immediate danger) | Gradual degradation, not an outage |
| `SpinrAPILatencySlowBurn` | > 10% of requests slow for 30m | Degraded UX; no rider impact yet |
| `SpinrStripeQueueBackedUp` | Stripe queue depth > 50 for 10m | Worker behind; not yet causing receipt delays |
| `SpinrBgTaskReportingError` | Background task running but returning error status for 10m | Loop alive; investigate the exception |
| `SpinrWebSocketConnectionsCollapse` | Zero driver WebSocket connections for 10m | Ambiguous — could be off-hours low traffic |

> If `SpinrWebSocketConnectionsCollapse` fires while `active_rides > 0`,
> treat it as P1 and escalate manually — rides cannot dispatch without
> driver WebSocket connections. A future improvement is to add an
> inhibit rule combining both conditions into a paging alert.

### 7.3 Inhibit rules already in place

The alertmanager config suppresses ticket alerts when the matching
paging alert is already firing (prevents alert storms):

- Any `severity: page` for a given SLO suppresses the matching
  `severity: ticket` for the same SLO.
- `SpinrStripeQueueCritical` (page) suppresses `SpinrStripeQueueBackedUp`
  (ticket) so on-call sees only the critical alert.

---

## 8. Maintenance Windows (Suppress Alerts During Deploys)

A rolling deploy on Fly.io takes 30–120 seconds per machine. During
that window, the API error rate can spike and trigger
`SpinrAPIAvailabilityFastBurn` even though the deploy is intentional.

### 8.1 Option A — PagerDuty maintenance window (recommended)

PagerDuty maintenance windows suppress incident creation for a specified
time window. Alerts still flow from Alertmanager; PagerDuty discards them.

**Before a production deploy:**

1. Open PagerDuty > **Services** > **Spinr API**.
2. Click **Maintenance Windows** (tab on the service page).
3. Click **+ New Maintenance Window**.
4. Set the duration to `15 minutes` (adjust for large migrations).
5. Add a description: `Deploy vX.Y.Z — <PR or commit link>`.
6. Click **Start Maintenance Window**.

**After the deploy completes:**

1. Return to **Maintenance Windows**.
2. Click **End Maintenance Window** to restore alerting immediately
   (do not wait for the window to expire if the deploy finished early).

### 8.2 Option B — amtool silence (Alertmanager level)

Use this when you want to suppress a specific alert rather than the
entire service.

```bash
fly ssh console --app spinr-api

# Silence SpinrAPIAvailabilityFastBurn for 20 minutes:
amtool silence add \
  --alertmanager.url=http://localhost:9093 \
  --duration=20m \
  --comment="Deploy v1.2.3 — expected 5xx spike" \
  alertname="SpinrAPIAvailabilityFastBurn"
```

List active silences:

```bash
amtool silence query --alertmanager.url=http://localhost:9093
```

Expire a silence early (copy the `<silence-id>` from the list output):

```bash
amtool silence expire --alertmanager.url=http://localhost:9093 <silence-id>
```

### 8.3 Deploy checklist integration

Add these steps to the `docs/ops/deploy` checklist:

```
Before deploy:
  [ ] Open PagerDuty maintenance window for Spinr API (15 min)
  [ ] Announce in #spinr-deploys: "Starting deploy vX.Y.Z — alerts suppressed"

After deploy:
  [ ] Verify /health and /health/deep return 200
  [ ] Close PagerDuty maintenance window
  [ ] Announce in #spinr-deploys: "Deploy complete — alerting restored"
  [ ] Watch #spinr-alerts for 10 minutes post-deploy for slow-burn regressions
```

---

## Appendix: Environment Variables

All secrets referenced by Alertmanager are injected at startup via
Fly.io. None are committed to the repository.

| Fly.io secret name | Purpose |
|---------------------|---------|
| `SPINR_PAGERDUTY_ROUTING_KEY` | PagerDuty Events API v2 integration key (set in step 5) |
| `SPINR_SLACK_WEBHOOK_ALERTS` | Slack incoming webhook for `#spinr-alerts` |
| `SPINR_SMTP_PASSWORD` | SendGrid API key for email fallback |

To rotate the PagerDuty key (e.g., after a team member leaves):

1. In PagerDuty, go to **Services** > **Spinr API** > **Integrations**.
2. Click the gear icon > **Regenerate Key** on the Prometheus integration.
3. Copy the new key.
4. Run `fly secrets set SPINR_PAGERDUTY_ROUTING_KEY=<new-key> --app spinr-api`.
5. Verify with step 5.2–5.3 of this guide.
