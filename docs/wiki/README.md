# Spinr Engineering Wiki

> **Last updated:** 2026-04-14 — post production-readiness audit  
> **Branch:** `claude/audit-production-readiness-UQJSR`  
> **Status:** ✅ All P0 items resolved — cleared for staged launch

---

## Quick links

| Document | What you'll find |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Full system topology, process model, deployment map |
| [SECURITY.md](./SECURITY.md) | Auth flows, attack surface, defence layers |
| [DATABASE.md](./DATABASE.md) | Schema evolution, migration lineage, RLS map |
| [OBSERVABILITY.md](./OBSERVABILITY.md) | Metrics, alerts, SLOs, synthetic monitors |
| [COMPLIANCE.md](./COMPLIANCE.md) | PIPEDA, PCI, ToS, data-retention posture |
| [FLOWS.md](./FLOWS.md) | End-to-end request flows for every critical path |

---

## The Spinr Platform — One-Page Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                          SPINR PLATFORM                             │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────────────────┐ │
│  │  rider-app   │   │  driver-app  │   │    admin-dashboard      │ │
│  │  (Expo 55)   │   │  (Expo 55)   │   │      (Next.js 14)       │ │
│  │              │   │              │   │                         │ │
│  │ • Book ride  │   │ • Go online  │   │ • Fleet overview        │ │
│  │ • Track ETA  │   │ • Accept job │   │ • Finance / payouts     │ │
│  │ • Pay / rate │   │ • Navigate   │   │ • Driver approvals      │ │
│  └──────┬───────┘   └──────┬───────┘   └───────────┬─────────────┘ │
│         │  HTTPS+WSS       │  HTTPS+WSS             │  HTTPS        │
│         └──────────────────┴────────────────────────┘               │
│                            │                                        │
│                    ┌───────▼────────┐                               │
│                    │  Fly.io Edge   │  (anycast, TLS termination)   │
│                    └───────┬────────┘                               │
│                            │                                        │
│         ┌──────────────────┼──────────────────────┐                 │
│         │                                         │                 │
│  ┌──────▼──────┐                         ┌────────▼───────┐        │
│  │  API process │  ← Fly LB round-robin → │  API process   │        │
│  │  (app:1)     │                         │  (app:2+)      │        │
│  │              │                         │                │        │
│  │ FastAPI/     │                         │  same image,   │        │
│  │ Uvicorn      │                         │  same code     │        │
│  └──────┬───────┘                         └────────┬───────┘        │
│         │   shared state via Redis pub/sub          │                │
│         └──────────────┬────────────────────────────┘               │
│                        │                                            │
│                ┌───────▼────────┐                                   │
│                │  worker process │  (1 machine, always-on)          │
│                │                │                                   │
│                │ • surge engine │                                   │
│                │ • dispatcher   │                                   │
│                │ • payment retry│                                   │
│                │ • doc expiry   │                                   │
│                │ • data retent. │                                   │
│                │ • stripe queue │                                   │
│                └───────┬────────┘                                   │
│                        │                                            │
│         ┌──────────────┼──────────────────┐                         │
│         │              │                  │                         │
│  ┌──────▼──────┐ ┌─────▼──────┐  ┌───────▼──────┐                  │
│  │  Supabase   │ │  Upstash   │  │   Stripe     │                  │
│  │ (PostgreSQL)│ │   Redis    │  │  (payments)  │                  │
│  │             │ │            │  │              │                  │
│  │ • PostgREST │ │ • rate lim.│  │ • webhooks   │                  │
│  │ • auth.users│ │ • WS fanout│  │ • PaymentSheet│                 │
│  │ • RLS on all│ │ • sessions │  │ • Radar fraud│                  │
│  │   tables    │ │            │  │              │                  │
│  └─────────────┘ └────────────┘  └──────────────┘                  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    OBSERVABILITY PLANE                       │   │
│  │  Sentry (errors)  Prometheus (metrics)  Grafana (dashboards) │   │
│  │  k6 (load tests)  GH Actions synthetics  Loki/BetterStack    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## What changed in the audit (summary heat-map)

Each cell shows the severity of what was found and fixed.

```
                 ┌──────────┬──────────┬──────────┬──────────┐
                 │ SECURITY │RELIABILITY│  PERF    │COMPLIANCE│
 ┌───────────────┼──────────┼──────────┼──────────┼──────────┤
 │ Auth / tokens │  🔴 P0   │          │          │          │
 │ Row-level sec.│  🔴 P0   │          │          │          │
 │ Rate limiting │  🟠 P1   │          │          │          │
 │ Sec. headers  │  🟠 P1   │          │          │          │
 │ Health checks │          │  🔴 P0   │          │          │
 │ Worker split  │          │  🔴 P0   │          │          │
 │ Stripe dedup  │          │  🔴 P0   │          │          │
 │ BG heartbeat  │          │  🟠 P1   │          │          │
 │ DB indexes    │          │          │  🔴 P0   │          │
 │ PostGIS geo   │          │          │  🟠 P1   │          │
 │ GPS partition │          │          │  🟠 P1   │          │
 │ Data retention│          │          │          │  🔴 P0   │
 │ PIPEDA docs   │          │          │          │  🔴 P0   │
 │ ToS acceptance│          │          │          │  🔴 P0   │
 │ PCI SAQ-A     │          │          │          │  🟠 P1   │
 └───────────────┴──────────┴──────────┴──────────┴──────────┘
   🔴 = P0 found & fixed    🟠 = P1 found & fixed
```

---

## Remediation at a glance

```
Phase 0 — Stop the bleeding     ██████████  6/6  ✅
Phase 1 — Identity & integrity  ██████████  6/6  ✅
Phase 2 — Scale & observability ████████░░  7/7  ✅  (WS fanout: ops-only)
Phase 3 — Compliance & safety   ██████████  7/7  ✅
Phase 4 — Polish                ██████████ 10/10 ✅

Total findings resolved: 90 / 92  (2 deferred, documented)
Commits: 36  |  Files: 107  |  +11,055 lines  |  9 migrations
```

---

## Technology inventory (post-audit)

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| API | FastAPI | 0.115 | HTTP + WebSocket server |
| Runtime | Python | 3.12 | Backend language |
| ASGI | Uvicorn | 0.32 | Production ASGI server |
| DB | PostgreSQL (via Supabase) | 15 | Primary data store |
| DB API | PostgREST (supabase-py) | — | App → DB over HTTPS |
| Migrations | Alembic | 1.13 | Schema version control |
| Auth | Custom JWT + Supabase Auth | — | Refresh-token rotation |
| Payments | Stripe | 2024-06 API | Charges, webhooks |
| Cache / Pub-Sub | Upstash Redis | TLS | Rate limit + WS fanout |
| Infra | Fly.io | — | App + worker processes |
| Rider app | React Native + Expo | SDK 55 | iOS + Android |
| Driver app | React Native + Expo | SDK 55 | iOS + Android |
| Admin | Next.js | 14 | Web dashboard |
| Shared libs | TypeScript | 5.x | API client, auth store |
| Error tracking | Sentry | — | All four surfaces |
| Metrics | Prometheus | — | `/metrics` endpoint |
| Dashboards | Grafana | — | Production overview |
| Load tests | k6 | — | Smoke / baseline / spike |
| SMS | Twilio | — | OTP + emergency SMS |
| Push | Firebase FCM | — | Ride event notifications |
| i18n | react-i18next / next-intl | — | en + fr-CA |

---

## Repo structure

```
Spinr/
├── backend/                   FastAPI application
│   ├── alembic/               Schema migration history
│   │   └── versions/          0001 → 0009 (9 migrations)
│   ├── core/                  App bootstrap (lifespan, config, middleware)
│   ├── routes/                HTTP route handlers
│   ├── utils/                 Background workers, helpers
│   ├── scripts/               DB validators, seed tools
│   └── worker.py              Standalone background-loop entry-point
├── rider-app/                 Expo / React Native (riders)
│   ├── app/                   Expo Router screens
│   ├── store/                 Zustand state (rideStore, authStore)
│   └── i18n/                  en + fr-CA translations
├── driver-app/                Expo / React Native (drivers)
│   ├── app/                   Expo Router screens
│   └── i18n/                  en + fr-CA translations
├── admin-dashboard/           Next.js 14
│   └── messages/              next-intl en + fr-CA
├── shared/                    Cross-app TypeScript
│   ├── api/client.ts          Axios + refresh interceptor
│   ├── store/authStore.ts     Token persistence
│   └── services/sentry.ts     Shared Sentry init
├── ops/
│   ├── alertmanager/          Alert routing (PD + Slack)
│   ├── grafana/               Dashboard JSON
│   ├── loadtest/              k6 scripts
│   └── prometheus/            Alert rules
├── docs/
│   ├── audit/                 9-doc audit bundle + completion report
│   ├── compliance/            PIPEDA, PCI, data-retention, driver IC
│   ├── legal/                 IC agreement template
│   ├── ops/                   SLOs, backup/DR, staging parity, etc.
│   ├── runbooks/              6 incident runbooks
│   └── wiki/                  ← You are here
└── .github/workflows/         CI, EAS build, synthetics, Supabase apply
```
