# Synthetic monitoring

Phase 2.6 of the production-readiness audit (audit finding T9).

Synthetic monitors probe the public API from *outside* our hosting
provider. Complements:

- **Fly's own liveness checks** — these can't detect edge/DNS/TLS
  failures because they run inside Fly's network.
- **`/health/deep`** — this endpoint is brilliant at saying "our
  dependencies are alive" but it can't run if the API itself is
  unreachable.

## Current implementation

Scheduled GitHub Actions workflow: `.github/workflows/synthetic-health.yml`.

| Probe | Target | Interval | Paging? |
|---|---|---|---|
| `GET /health` (shallow) | prod + staging | ~5 min | Slack only |
| `GET /health/deep` (readiness) | prod | ~5 min | Slack only |
| `POST /rides/estimate` (smoke) | staging | ~15 min | Slack only |

### Why GH Actions cron and not a dedicated provider

1. **Zero new vendor surface** — we already have GH Actions budget.
   A Datadog / Checkly / Uptime-Kuma install is a separate auth,
   a separate on-call escalation, and a separate invoice.
2. **Minute-floor granularity is fine at this stage** — the SLO
   fast-burn window is 1 hour, so 5-min probe granularity gives
   us plenty of signal.

### Why Slack-only, not PagerDuty

GH Actions queue latency is variable (we've seen 2-10 min delays
during their incidents). A failing probe might just mean GH is
having a bad day. Metric-driven alerts via Prometheus/Alertmanager
page the on-call (see `ops/alertmanager/alertmanager.yml`);
synthetics serve as a second, independent eye.

## Secrets required

Add to the GitHub repo's Actions secrets:

- `SLACK_WEBHOOK_ALERTS` — Slack incoming-webhook URL for `#spinr-alerts`.

## When to migrate to a dedicated synthetics provider

Move off GH Actions when:

- **Launch + >1000 DAU.** At that point 5-min granularity leaves
  too many users exposed between probes; we want 1-min or
  continuous.
- **We have a status page.** Dedicated providers (Checkly, StatusCake)
  post-to-statuspage integrations are one-click.
- **We need multi-region probes.** GH Actions runs only from the
  runner region (us-east by default), so a West-Coast-only outage
  wouldn't register.

Candidate replacements and their cost/fit:

| Provider | Monthly cost at our scale | Notes |
|---|---|---|
| Grafana Cloud synthetics | Included in $8/mo plan | Pairs with our existing Grafana + Prometheus story — **current frontrunner**. |
| Checkly | ~$40/mo | Best DX; TypeScript check syntax. |
| BetterStack | ~$18/mo | Includes status page. |

## Adding a new probe

1. Add a new job to `.github/workflows/synthetic-health.yml`. Copy
   the structure of an existing job — the `probe` step + the Slack
   `if: failure()` notification are the two required pieces.
2. Pick a failure threshold narrower than the user-visible one.
   E.g. if the SLO says "< 500 ms p95", the synthetic should fail
   at 2 s hard timeout — any single 2-second probe is already
   anomalous.
3. If the probe needs auth, store the credential as a GH secret and
   reference it via `${{ secrets.NAME }}`. **Do not** embed JWTs in
   the workflow file.

## Related

- Shallow liveness: `backend/routes/main.py` (`GET /health`)
- Deep readiness: `backend/routes/main.py` (`GET /health/deep`)
- Metric-driven alerts: `ops/prometheus/alerts.yml`
- Alert routing: `ops/alertmanager/alertmanager.yml`
- SLOs: `docs/ops/SLOs.md`
