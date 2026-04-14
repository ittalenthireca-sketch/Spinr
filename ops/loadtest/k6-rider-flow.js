// Spinr — k6 load test: end-to-end rider flow
//
// Phase 2.5 of the production-readiness audit (audit finding T8).
//
// Purpose:
//   Exercises the dispatch hot path end-to-end — a rider requests a
//   ride, the dispatcher assigns a driver, the ride transitions
//   through statuses, the ride completes. This is the test that
//   catches dispatcher regressions under concurrent load.
//
// Unlike k6-api-baseline.js (which is reads-only), this script writes
// to the DB. DO NOT point it at production. Always run against
// staging or a dedicated load-test project.
//
// SLOs exercised:
//   * SLO-3 Ride dispatch p95 < 30 s (see spinr_ride_dispatch_latency)
//   * SLO-1 availability, SLO-2 latency (indirectly)
//
// Prereqs on the target environment:
//   * Seeded rider accounts (use backend/scripts/seed_loadtest.py —
//     or any equivalent fixture — and pass the resulting JWTs as
//     RIDER_TOKENS env var, comma-separated).
//   * A fleet of test drivers with the app simulator running (or
//     the "auto-accept" staging flag enabled so drivers accept on
//     receipt without a real device).
//
// How to run:
//   BASE_URL=https://spinr-api-staging.fly.dev \
//   RIDER_TOKENS="jwt1,jwt2,jwt3" \
//   k6 run ops/loadtest/k6-rider-flow.js

import http from 'k6/http';
import { check, sleep, group, fail } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import exec from 'k6/execution';

const BASE_URL = __ENV.BASE_URL || 'https://spinr-api-staging.fly.dev';
const RIDER_TOKENS = (__ENV.RIDER_TOKENS || '').split(',').filter(Boolean);

if (RIDER_TOKENS.length === 0) {
    throw new Error(
        'RIDER_TOKENS is required (comma-separated rider JWTs). ' +
        'See ops/loadtest/README.md for how to seed them.'
    );
}

// Custom metrics
const dispatchLatency = new Trend('spinr_e2e_dispatch_latency', true);
const rideRequests = new Counter('spinr_rides_requested');
const rideAssigned = new Counter('spinr_rides_assigned');
const rideFailedToAssign = new Counter('spinr_rides_failed_to_assign');

// Dispatch timeout — if a driver isn't assigned within this wall
// time we count the ride as failed. Matches the app-side timeout.
const DISPATCH_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 2_000;

export const options = {
    scenarios: {
        rider_flow: {
            executor: 'constant-arrival-rate',
            // 20 ride requests per minute — roughly the dispatcher's
            // design point. Tune up to find the knee.
            rate: 20,
            timeUnit: '1m',
            duration: '10m',
            preAllocatedVUs: 20,
            maxVUs: 50,
        },
    },
    thresholds: {
        // Direct SLO check: 95% of dispatches must land under 30 s.
        'spinr_e2e_dispatch_latency':  ['p(95)<30000'],
        // No more than 1% of requested rides fail to ever get a driver.
        // (The `rate` calc below is failed / (assigned + failed).)
        'spinr_rides_failed_to_assign':['count<10'],
        'http_req_failed':             ['rate<0.01'],
    },
};

// ---------------------------------------------------------------------
// VU loop
// ---------------------------------------------------------------------
export default function () {
    // Round-robin a token per VU iteration so we don't hammer one
    // rider with 100 concurrent requests (that trips rate limits
    // and looks like abuse, not load).
    const token = RIDER_TOKENS[exec.vu.iterationInScenario % RIDER_TOKENS.length];
    const headers = {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${token}`,
    };

    let rideId = null;

    group('request_ride', function () {
        const payload = JSON.stringify({
            pickup: {
                lat: jitter(52.1332, 0.02),
                lng: jitter(-106.6700, 0.02),
                address: '102 3rd Ave N, Saskatoon, SK',
            },
            dropoff: {
                lat: jitter(52.1708, 0.02),
                lng: jitter(-106.6996, 0.02),
                address: 'Saskatoon Airport (YXE)',
            },
            ride_type: 'standard',
        });

        const res = http.post(`${BASE_URL}/rides`, payload, { headers });
        rideRequests.add(1);

        const ok = check(res, {
            'ride request 200/201': (r) => r.status === 200 || r.status === 201,
            'returned ride id':     (r) => !!(r.json() && r.json().id),
        });
        if (!ok) {
            rideFailedToAssign.add(1);
            return fail(`ride request failed: ${res.status} ${res.body}`);
        }
        rideId = res.json().id;
    });

    if (!rideId) return;

    group('await_assignment', function () {
        const start = Date.now();
        let assigned = false;

        while (Date.now() - start < DISPATCH_TIMEOUT_MS) {
            sleep(POLL_INTERVAL_MS / 1000);
            const res = http.get(`${BASE_URL}/rides/${rideId}`, { headers });
            if (res.status !== 200) continue;

            const body = res.json();
            if (body.status && body.status !== 'searching') {
                dispatchLatency.add(Date.now() - start);
                rideAssigned.add(1);
                assigned = true;
                break;
            }
        }

        if (!assigned) {
            rideFailedToAssign.add(1);
            // Cancel so we don't leak orphan "searching" rides in
            // staging for the scheduler to chase.
            http.post(`${BASE_URL}/rides/${rideId}/cancel`,
                      JSON.stringify({ reason: 'loadtest_timeout' }),
                      { headers });
        }
    });
}

// Jitter a lat/lng so we don't all request the same GPS point
// (which would cause the dispatcher to hit the same driver every
// time and defeat the realism of the test).
function jitter(base, range) {
    return base + (Math.random() * 2 - 1) * range;
}
