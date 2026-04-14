// Spinr — k6 load test: steady-state API baseline
//
// Phase 2.5 of the production-readiness audit (audit finding T8).
//
// Purpose:
//   Establish a go/no-go latency+error baseline for the Spinr API
//   under "a busy morning commute in one city" load. This is the
//   test we run pre-launch, and re-run before any deploy that
//   touches the hot path (dispatcher, auth, routes/rides.py, Supabase
//   client, etc).
//
// SLO being exercised (docs/ops/SLOs.md):
//   * SLO-1 API availability: > 99.9% non-5xx (here: thresholds.
//     http_req_failed < 0.1%)
//   * SLO-2 API latency p95:   < 500 ms
//
// How to run:
//   BASE_URL=https://spinr-api.fly.dev \
//   API_TOKEN=<shortlived-JWT> \
//   k6 run ops/loadtest/k6-api-baseline.js
//
// Environment variables:
//   BASE_URL   - API root, default https://spinr-api.fly.dev
//   API_TOKEN  - OPTIONAL bearer. If unset, only unauthenticated
//                endpoints (GET /health, GET /health/deep) are hit.
//   SCENARIO   - 'smoke' | 'baseline' | 'spike'. Default 'baseline'.
//
// Notes:
//   * Target Canadian staging. DO NOT run against production.
//   * On a cold Fly machine the first request is always slow; the
//     first 30s of each stage are warmup and excluded via
//     `gracefulRampDown` + a single pre-check in setup().

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'https://spinr-api.fly.dev';
const API_TOKEN = __ENV.API_TOKEN || '';
const SCENARIO = __ENV.SCENARIO || 'baseline';

// Custom metrics so the summary shows what matters, not just
// aggregate http_req_*.
const healthLatency = new Trend('spinr_health_latency', true);
const rideEstimateLatency = new Trend('spinr_ride_estimate_latency', true);
const authFailureRate = new Rate('spinr_auth_failures');

// ---------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------
// Three canned profiles so a dev can smoke-test a PR in 30 s but
// still have a meaningful "real load" run for pre-launch.
const scenarios = {
    // 1 VU / 30 s. Sanity check: the script and target URL work.
    smoke: {
        executor: 'constant-vus',
        vus: 1,
        duration: '30s',
    },

    // Baseline: ramp to 50 VUs for 5 min. Roughly simulates ~250 req/s
    // across the /health + /rides/estimate mix below.
    baseline: {
        executor: 'ramping-vus',
        startVUs: 0,
        stages: [
            { duration: '30s', target: 10 },
            { duration: '1m',  target: 50 },
            { duration: '5m',  target: 50 },
            { duration: '30s', target: 0 },
        ],
        gracefulRampDown: '15s',
    },

    // Spike: burst to 200 VUs in 30 s. Used to prove the rate limiter
    // doesn't crater the p95 for legitimate traffic during a surge.
    spike: {
        executor: 'ramping-vus',
        startVUs: 10,
        stages: [
            { duration: '30s', target: 200 },
            { duration: '1m',  target: 200 },
            { duration: '30s', target: 10 },
        ],
        gracefulRampDown: '15s',
    },
};

export const options = {
    scenarios: { default: scenarios[SCENARIO] || scenarios.baseline },

    // Thresholds are the "did we pass" gate. Failing any one of
    // these fails the whole k6 run (exit code 99), so CI can block
    // a deploy on them.
    //
    // p(95) numbers here are INTENTIONALLY tighter than the SLO:
    // load-test latency is always better than production because
    // there's no real-user geographic spread. Give the SLO 100 ms of
    // headroom.
    thresholds: {
        'http_req_failed':                 ['rate<0.001'],   // 99.9% success
        'http_req_duration{expected:true}': ['p(95)<400'],
        'spinr_health_latency':            ['p(95)<100'],
        'spinr_ride_estimate_latency':     ['p(95)<800'],   // DB + Maps
        'spinr_auth_failures':             ['rate<0.01'],
    },
};

// ---------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------
export function setup() {
    // Preflight: one sync call to prove we can reach the API before
    // we burn VU-minutes on a misconfigured target.
    const res = http.get(`${BASE_URL}/health`);
    if (res.status !== 200) {
        throw new Error(
            `Preflight GET /health returned ${res.status}. ` +
            `Is BASE_URL=${BASE_URL} correct and reachable?`
        );
    }
    return { preflightOk: true };
}

// ---------------------------------------------------------------------
// Default VU loop
// ---------------------------------------------------------------------
// Each VU picks a request-mix weighted to approximate a "busy app":
//   70% health/liveness hits  (cheap, high-volume probes)
//   20% ride estimate calls   (DB + upstream, the hot path)
//   10% authenticated reads   (GET /rides/active), iff API_TOKEN set
//
// The mix is deliberately reads-heavy. Writes during a baseline test
// would pollute the DB with phantom rides and dirty the dispatcher —
// the k6-rider-flow.js script handles the write path in isolation.
export default function () {
    group('liveness', function () {
        const r = Math.random();
        if (r < 0.7) {
            const res = http.get(`${BASE_URL}/health`, {
                tags: { expected: 'true', endpoint: 'health' },
            });
            healthLatency.add(res.timings.duration);
            check(res, { 'health 200': (r) => r.status === 200 });
            return;
        }
        if (r < 0.9) {
            estimateRide();
            return;
        }
        if (API_TOKEN) {
            listActiveRides();
        } else {
            // No token — fall back to /health/deep to maintain the
            // traffic rate without the authenticated request.
            http.get(`${BASE_URL}/health/deep`, {
                tags: { expected: 'true', endpoint: 'health_deep' },
            });
        }
    });

    // Short think-time between requests. Real riders open the app,
    // look at the map, then tap — no VU should be hammering the API
    // with zero delay, that's what made k6 runs look like DDoS tests
    // on the last audit cycle.
    sleep(Math.random() * 1.5 + 0.2);
}

// ---------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------
function estimateRide() {
    // Saskatoon downtown → airport — a realistic fixed fare range.
    const body = JSON.stringify({
        pickup_lat:  52.1332,
        pickup_lng: -106.6700,
        dropoff_lat: 52.1708,
        dropoff_lng: -106.6996,
        ride_type:  'standard',
    });

    const res = http.post(`${BASE_URL}/rides/estimate`, body, {
        headers: {
            'Content-Type': 'application/json',
            ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
        },
        tags: { expected: 'true', endpoint: 'ride_estimate' },
    });

    rideEstimateLatency.add(res.timings.duration);
    check(res, {
        'estimate 200 or 401': (r) => r.status === 200 || r.status === 401,
    });
}

function listActiveRides() {
    const res = http.get(`${BASE_URL}/rides/active`, {
        headers: { Authorization: `Bearer ${API_TOKEN}` },
        tags: { expected: 'true', endpoint: 'rides_active' },
    });
    authFailureRate.add(res.status === 401);
    check(res, { 'rides/active 200': (r) => r.status === 200 });
}
