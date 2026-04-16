# Load tests (k6)

Phase 2.5 of the production-readiness audit (audit finding T8).

Two scripts, two purposes:

| Script | What it exercises | Safe to run against prod? |
|---|---|---|
| `k6-api-baseline.js` | Reads-only request-mix for availability + latency SLOs | Yes (low rate) |
| `k6-rider-flow.js`   | End-to-end rider ride-request → dispatch → assignment | **No, staging only** |

## Installing k6

```bash
# macOS
brew install k6

# Linux (official binary)
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] \
  https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt update && sudo apt install -y k6
```

## Baseline run

Intended for pre-deploy verification and for the pre-launch go/no-go
checklist. Steady, moderate load on reads + `/rides/estimate`.

```bash
BASE_URL=https://spinr-api-staging.fly.dev \
  k6 run ops/loadtest/k6-api-baseline.js
```

Scenarios (set via `SCENARIO=…`):

- `smoke` — 1 VU, 30 s. Sanity check the script and URL.
- `baseline` — ramp to 50 VUs over 5 min. Default.
- `spike` — burst to 200 VUs. Proves the rate limiter doesn't wreck
  latency for legit traffic.

### Pass/fail thresholds

The script fails (exit 99) if any of the following regress:

| Threshold | Value | Source |
|---|---|---|
| HTTP error rate | < 0.1% | SLO-1 |
| p95 all requests | < 400 ms | SLO-2 (with 100 ms headroom) |
| p95 `/health` | < 100 ms | Internal |
| p95 `/rides/estimate` | < 800 ms | Realistic DB+Maps budget |
| Auth failure rate | < 1% | Sanity |

Run with `--out json=baseline-$(date +%s).json` to archive the full
metric set; the summary at the end only prints aggregates.

## End-to-end rider flow

This is the test that catches dispatcher regressions. It writes to
the DB — **staging only**.

### Prerequisites

1. A staging environment pointed at a dedicated Supabase project.
2. Seeded rider accounts. Run:

   ```bash
   cd backend
   python scripts/seed_loadtest.py --riders 10 --output /tmp/rider-tokens.txt
   ```

   (If the seed script doesn't exist yet it's a one-evening project —
   create 10 users via `auth/signup`, accept tokens, write to file.)

3. Staging-side auto-accept flag enabled so drivers auto-accept the
   dispatcher's offer without a real device. Set `STAGING_AUTO_ACCEPT=true`
   in the staging secrets.

### Running

```bash
BASE_URL=https://spinr-api-staging.fly.dev \
RIDER_TOKENS="$(paste -sd, /tmp/rider-tokens.txt)" \
  k6 run ops/loadtest/k6-rider-flow.js
```

Default profile: 20 ride requests per minute, 10-minute run = 200 rides.

### Pass/fail thresholds

| Threshold | Value | Source |
|---|---|---|
| p95 dispatch latency | < 30 s | SLO-3 |
| Failed-to-assign rate | < 5% of rides | Internal |
| HTTP error rate | < 1% | SLO-1 |

## CI integration

The baseline run is cheap enough (~5 min total) that it can gate a
production deploy. Add a step to `.github/workflows/ci.yml`:

```yaml
- name: k6 baseline
  uses: grafana/setup-k6-action@v1
- run: k6 run ops/loadtest/k6-api-baseline.js
  env:
    BASE_URL: https://spinr-api-staging.fly.dev
    SCENARIO: baseline
```

The full rider-flow test is too slow and too environment-dependent
for every push — run it on a nightly schedule or manually before
a release.

## What "passing" means pre-launch

Per the go/no-go checklist in
`docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md`:

> "Load test passed: 500 riders, 200 drivers, p95 <2s"

Translation: crank `k6-rider-flow.js` to `rate: 500` over a 30-minute
run with 200 seeded drivers; observe p95 dispatch stays under the
SLO. Archive the resulting k6 JSON + the Grafana dashboard screenshot
in `docs/launch/`.

## Related

- SLOs: `docs/ops/SLOs.md`
- Alerts: `ops/prometheus/alerts.yml`
- Dashboard (watch during a run): `ops/grafana/spinr-overview.json`
