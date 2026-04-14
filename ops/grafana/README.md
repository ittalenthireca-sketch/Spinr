# Grafana dashboards

Phase 2.3f of the production-readiness audit (audit finding T3).

The JSON files in this directory are Grafana dashboard definitions
committed as source of truth. Treating them as code avoids the usual
"works on one operator's Grafana, nobody can reproduce" drift and
lets us review changes via PR.

## `spinr-overview.json`

The production overview dashboard. Covers:

1. **Availability & latency** — request rate, p95 per handler, 5xx rate.
   Sourced from `prometheus-fastapi-instrumentator` (`http_requests_total`,
   `http_request_duration_seconds_bucket`).
2. **Ride pipeline** — `spinr_active_rides` by status (the dispatch funnel)
   and `spinr_ride_dispatch_latency_seconds` p50/p95.
3. **Async queues & background tasks** — `spinr_stripe_queue_depth`,
   `spinr_bg_task_heartbeat_age_seconds`, `spinr_bg_task_last_status`.
4. **WebSocket connections by role** — `spinr_ws_connections`.

Panels are intentionally thin on styling — the goal is the queries
are right and the operator can read them, not a polished design.
Bikeshed freely in follow-up PRs; the queries themselves should not
change without a corresponding metric emission change in
`backend/utils/metrics.py`.

## Importing

### Via the UI (one-time setup)

1. Grafana → Dashboards → Import.
2. Upload `spinr-overview.json`.
3. Select your Prometheus datasource for the `DS_PROMETHEUS` input.
4. Save.

### Via provisioning (recommended for a managed Grafana)

Drop `spinr-overview.json` into the Grafana container's
`/etc/grafana/provisioning/dashboards/` mount and add a provider YAML:

```yaml
apiVersion: 1
providers:
  - name: spinr
    folder: Spinr
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

This is what Fly's managed Prometheus add-on expects; see
`docs/deploy/02-backend-fly.md` for Fly-side wiring.

## Updating the dashboard

1. Edit in Grafana UI.
2. Share → Export → **Export for sharing externally** (this strips
   the datasource UIDs and replaces them with the `${datasource}`
   variable; without this step the dashboard will only work on the
   exact Grafana instance it was exported from).
3. Replace the JSON in this directory and commit.

## Related

- Metric definitions: `backend/utils/metrics.py`
- Emission sites: `backend/utils/metrics.py` (refresh loop),
  `backend/socket_manager.py` (WS gauges), `backend/db_supabase.py`
  (count helpers).
- `/metrics` auth: `backend/core/middleware.py`
  (`MetricsGuardMiddleware`).
- SLO + burn-rate alerts: Phase 2.4 (separate PR).
