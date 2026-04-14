# Spinr — Log aggregation

Phase 2.7 of the production-readiness audit (audit finding T10).

All Spinr processes emit **newline-delimited JSON** to stdout when
`ENV` is `production` or `staging`. The log format is designed to
be ingested by any modern aggregator without a sidecar agent —
Fly.io ships every stdout line to its log endpoint, and from there
a single log-drain forwards to the aggregator of your choice.

---

## Log format

Each line is a JSON object. Example:

```json
{
  "time":       "2026-04-14T18:32:01.247Z",
  "level":      "INFO",
  "message":    "Stripe event worker: processed 3 events in 42ms",
  "logger":     "utils.stripe_worker",
  "function":   "stripe_event_worker_loop",
  "line":       87,
  "env":        "production",
  "app":        "worker",
  "release":    "v1.4.0-fly.1a2b3c4",
  "machine_id": "9080e4d4a44518"
}
```

On exception the record also carries:

```json
{
  ...
  "exception": {
    "type":    "StripeError",
    "message": "No such payment_intent: 'pi_...'"
  }
}
```

Fields marked `extra` come from `logger.bind(key=value)` call-sites.

### Configuration

`backend/core/logging_config.py` — `configure_logging()` is called
once at process start by:
- `backend/core/lifespan.py` (API process)
- `backend/worker.py` (worker process)

Environment variables:

| Variable | Default | Effect |
|---|---|---|
| `LOG_LEVEL` | DEBUG (dev/staging), INFO (prod) | Floor log level |
| `APP_PROCESS` | `api` | Value of the `app` field in JSON |
| `FLY_MACHINE_ID` | (injected by Fly) | `machine_id` field |
| `FLY_MACHINE_VERSION` | (injected by Fly) | `release` field |
| `GIT_COMMIT` | fallback for `release` | `release` field |

---

## Architecture: Fly → log drain → aggregator

```
Fly machine (API / worker)
  │  stdout (ndjson)
  │
  ▼
Fly log destination (fly.toml [logs] or flyctl logs --stream)
  │
  ▼
Log drain HTTP endpoint          ← configured once via flyctl
  │
  ▼
Aggregator (BetterStack / Loki / Datadog)
  │
  ├── Full-text search + structured field filters
  ├── Retention policy (30-day rolling recommended)
  └── Alert on error spikes (supplement Prometheus alerts)
```

No sidecar agent is required — Fly captures stdout natively and
forwards it as-is. The JSON format means the aggregator can parse
the fields without a custom Grok/VRL rule.

---

## Setting up BetterStack (recommended for launch)

BetterStack Logs is the current frontrunner because:
- Fly drain setup is one `flyctl` command.
- On-call integration with BetterStack Incidents (replaces PagerDuty
  at smaller scale).
- Retention and search are fast enough for support debugging.
- ~$25/mo at our estimated 5 GB/day log volume.

### Step 1: Create a BetterStack source

1. BetterStack → Logs → Sources → **New source**.
2. Platform: **HTTP**.
3. Copy the **Source token**.

### Step 2: Add the Fly log drain

```bash
# Replace <SOURCE_TOKEN> with the token from step 1.
flyctl logs drain create \
  "https://in.logs.betterstack.com" \
  --header "Authorization: Bearer <SOURCE_TOKEN>" \
  -a spinr-api

# Verify:
flyctl logs drain list -a spinr-api
```

Do the same for the worker app (`-a spinr-api-worker` or whichever
app name the worker runs under).

### Step 3: Verify ingestion

```bash
flyctl logs -a spinr-api | head -5
# Then check BetterStack Logs → Live tail — lines should appear
# within 5-10 seconds.
```

---

## Alternative: self-hosted Loki + Grafana

If you already run a managed Grafana (e.g. Grafana Cloud's free tier),
Loki is the natural pairing:

### Step 1: Get a Loki push URL + token

Grafana Cloud → Connections → Add new connection → Logs → Loki.
Copy the endpoint URL and the token.

### Step 2: Add a Promtail sidecar to the fly.toml

Fly doesn't support custom sidecars natively. Instead, run Promtail
as a second Fly app that reads from the Fly NATS log stream:

```bash
# Deploy the spinr-promtail app (one-time setup):
flyctl launch --name spinr-promtail --image grafana/promtail:latest \
  --no-deploy

# Set the Loki URL:
flyctl secrets set \
  LOKI_URL=https://logs-prod-us-central1.grafana.net \
  LOKI_USER=<grafana_cloud_user_id> \
  LOKI_PASSWORD=<api_token> \
  -a spinr-promtail
```

Then configure Promtail's `config.yml` to scrape Fly's syslog
(`syslog://[fdaa::1]:601`) and push to Loki. The key Promtail
pipeline stages:

```yaml
pipeline_stages:
  - json:
      expressions:
        level:   level
        app:     app
        env:     env
        release: release
  - labels:
      level:
      app:
      env:
      release:
```

This makes `{app="worker", level="ERROR"}` a valid LogQL query in
Grafana.

---

## Querying

### BetterStack

Use the structured query bar:
```
app:worker level:error
```
or full-text:
```
"stripe_event_worker" AND "StripeError"
```

### Loki / Grafana

LogQL filter then parser:
```logql
{app="api"} | json | level="ERROR"
```

To correlate with a Sentry issue:
```logql
{app="api"} |= "sentry_event_id" | json | message =~ ".*pi_.*"
```

---

## Retention policy

| Environment | Retention | Reason |
|---|---|---|
| Production | 30 days | Matches SLO rolling window; covers a full error-budget cycle |
| Staging | 7 days | Staging logs are noisy and not needed for incident review |
| Development | Local only | Never shipped to an aggregator |

Logs older than 30 days should be automatically deleted by the
aggregator — do not rely on manual cleanup. If BetterStack's plan
retention is shorter than 30 days, upgrade or switch to Loki.

---

## Log level guidance

| Level | When to use |
|---|---|
| `DEBUG` | Loop diagnostics, per-row processing counts. Not emitted in production unless `LOG_LEVEL=DEBUG` is set for triage. |
| `INFO` | Normal lifecycle events: startup, shutdown, task start/stop, background-loop completion summary. |
| `WARNING` | Unexpected but non-fatal: missing optional config, fallback taken, retry scheduled. |
| `ERROR` | Unhandled exception, external API error, loop iteration failure. Should produce a Sentry event too. |
| `CRITICAL` | Never use. Sentry handles "fatal, needs waking someone up" through alert rules. |

---

## Adding structured context to a log call

Use `logger.bind()` to attach search-friendly fields without
embedding them in the message string:

```python
from loguru import logger

# Per-request context (good for middleware):
req_logger = logger.bind(ride_id=ride_id, rider_id=rider_id)
req_logger.info("Ride dispatched to driver")

# Exception with context:
try:
    await process_stripe_event(event)
except StripeError as exc:
    logger.bind(stripe_event_id=event["id"]).error(
        f"Stripe event processing failed: {exc}"
    )
```

Bound fields land in the `extra` dict of the JSON record, which
most aggregators index as searchable labels.

---

## Related

- Logging implementation: `backend/core/logging_config.py`
- Metric-driven alerts: `ops/prometheus/alerts.yml`
- SLOs: `docs/ops/SLOs.md`
- Sentry (exception tracking): `backend/core/lifespan.py` (init)
