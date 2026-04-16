# Spinr — Security Hardening

> **Role:** Security Lead  
> **Audience:** Security reviewers, engineering, auditors

---

## 1. Defence-in-depth model

```
┌─────────────────────────────────────────────────────────────────┐
│                     ATTACK SURFACE                              │
│         Public internet  →  Fly edge  →  API                   │
└─────────────────────────────────────────────────────────────────┘
                         │
         ┌───────────────▼───────────────┐
         │     LAYER 1: TLS / Network    │
         │  • TLS 1.2+ enforced by Fly   │
         │  • HSTS max-age=31536000      │
         │  • No plaintext HTTP accepted │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │     LAYER 2: Rate Limiting    │
         │  • Redis-backed (Upstash)     │
         │  • OTP: 5 req / 15 min / IP  │
         │  • Rides: 10 req / min / user │
         │  • Global: 300 req / min / IP │
         │  • Survives deploys + scaling │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │   LAYER 3: Security Headers   │
         │  • Content-Security-Policy    │
         │  • X-Frame-Options: DENY      │
         │  • Referrer-Policy: strict    │
         │  • Permissions-Policy         │
         │  • X-Content-Type-Options     │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  LAYER 4: Authentication      │
         │  • OTP via Twilio SMS         │
         │  • JWT (HS256, 1-30 day TTL)  │
         │  • Refresh-token rotation     │
         │  • token_version revocation   │
         │  • Role loaded from DB        │  ← never from JWT claim
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │   LAYER 5: Authorisation      │
         │  • RLS on every public table  │
         │  • deny_all default           │
         │  • select_own per owner       │
         │  • BYPASSRLS only via svc key │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │   LAYER 6: Input Validation   │
         │  • Pydantic schemas on all    │
         │    request bodies             │
         │  • Magic-byte file validation │
         │  • Parameterised queries only │
         │  (PostgREST / supabase-py)    │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  LAYER 7: Payment Isolation   │
         │  • No PAN ever touches Spinr  │
         │  • Stripe PaymentSheet SDK    │
         │  • Only PM ID + PI ID stored  │
         │  • SAQ-A PCI scope            │
         └───────────────────────────────┘
```

---

## 2. Authentication flow

```
┌──────────┐   1. Enter phone      ┌──────────────┐
│  Rider   │ ──────────────────► │  POST        │
│  App     │                     │  /auth/send- │
│          │                     │  otp         │
└──────────┘                     └──────┬───────┘
                                        │ 2. Generate 6-digit OTP
                                        │    Store hash in otp_records
                                        │    (TTL 10 min)
                                        ▼
                                  ┌──────────────┐
                                  │   Twilio SMS  │
                                  │  to rider's   │
                                  │  phone        │
                                  └──────────────┘
                                        │
                                        │ 3. Rider receives SMS
                                        │
┌──────────┐   4. Submit OTP      ┌────▼─────────┐
│  Rider   │ ──────────────────► │  POST        │
│  App     │                     │  /auth/verify│
│          │                     │  -otp        │
│          │ ◄────────────────── └──────┬───────┘
│  Stores: │   5. Returns:             │
│  access_ │   { access_token,         │ Validates OTP hash
│  token   │     refresh_token,        │ Creates/updates user
│  refresh_│     user }                │ Issues token pair
│  token   │                           │ Requires accepted_tos_version
└──────────┘                           │ on new users
```

### Token types

| Token | Where stored | Lifetime | Revocation |
|---|---|---|---|
| `access_token` (JWT) | Memory + AsyncStorage | 30 days (→ 7 days post-audit) | `token_version` increment |
| `refresh_token` (opaque hash) | `refresh_tokens` DB table | 90 days | `revoked_at` timestamp |

### Revocation paths

```
POST /auth/logout
  └── Sets refresh_tokens.revoked_at = now()
      Next access token use still valid until expiry
      (mitigated by short TTL)

POST /auth/logout-all
  └── Increments users.token_version
      Every in-flight access token immediately returns 401
      All refresh tokens for this user become invalid
      ← Use this on suspected compromise

Admin forced revoke
  └── Same as logout-all, triggered by support tooling
```

---

## 3. Row-Level Security topology

```
Supabase public schema — 19 tables audited

┌──────────────────────────────────────────────────────────────┐
│  CATEGORY A: Owner-owned (9 tables)                          │
│                                                              │
│  rides  users  drivers  payments  gps_breadcrumbs           │
│  refresh_tokens  otp_records  driver_documents  ride_ratings │
│                                                              │
│  Policy: deny_all + select_own                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  CREATE POLICY select_own ON rides                  │     │
│  │    FOR SELECT USING (                               │     │
│  │      rider_id::text = auth.uid()::text              │     │
│  │      OR driver_id::text = auth.uid()::text          │     │
│  │    );                                               │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
│  Who bypasses: SUPABASE_SERVICE_ROLE_KEY (BYPASSRLS)         │
│  Why: App writes via PostgREST use service role;             │
│  RLS is defence-in-depth against direct DB access            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  CATEGORY B: Sensitive / system (7 tables)                   │
│                                                              │
│  admin_users  stripe_events  bg_task_heartbeat               │
│  area_fees  subscriptions  vehicle_types  ride_stops         │
│                                                              │
│  Policy: deny_all ONLY                                       │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  CREATE POLICY deny_all ON admin_users              │     │
│  │    FOR ALL USING (false);                           │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
│  No user can read these via PostgREST direct access.         │
│  Backend uses service role key exclusively.                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  CATEGORY C: Public catalogue (3 tables)                     │
│                                                              │
│  service_areas  fares  promotions                            │
│                                                              │
│  Policy: deny_all + public_read                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  CREATE POLICY public_read ON fares                 │     │
│  │    FOR SELECT USING (true);  -- anyone can read     │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
│  Rationale: fare display before login (estimate screen)      │
└──────────────────────────────────────────────────────────────┘
```

**Audit query** (`backend/scripts/rls_audit.sql`):
```sql
-- Must return zero rows. If any row appears, add a policy immediately.
SELECT tablename
FROM   pg_tables
WHERE  schemaname = 'public'
  AND  tablename NOT IN (
    SELECT DISTINCT tablename
    FROM   pg_policies
    WHERE  schemaname = 'public'
  );
```

---

## 4. Rate limiting configuration

```
Request arrives
       │
       ▼
slowapi middleware checks Redis
       │
       ├── Key: user_id  (authenticated routes)
       │         or
       ├── Key: IP address  (unauthenticated routes)
       │
       │   LIMITS:
       │   ┌─────────────────────────────────────────┐
       │   │  Route              Limit      Window    │
       │   │  ─────────────────────────────────────  │
       │   │  POST /auth/send-otp  5 req    15 min   │
       │   │  POST /rides          10 req   1 min    │
       │   │  global               300 req  1 min    │
       │   └─────────────────────────────────────────┘
       │
       ├── Under limit  →  pass through
       │
       └── Over limit   →  429 Too Many Requests
                               { "detail": "rate limit exceeded",
                                 "retry_after": <seconds> }
```

**Why Redis matters here:**

```
BEFORE (in-memory):
  Machine A: user made 9 requests  (1 remaining)
  Machine B: user made 9 requests  (1 remaining)
  Total: user makes 10+10 = 20 requests  ← limit bypassed

AFTER (Redis):
  Machine A: increments Redis counter  →  10
  Machine B: increments Redis counter  →  11  →  429
  Total: limit holds across the entire fleet
```

---

## 5. Security headers

Every HTTP response from the API includes:

```http
Content-Security-Policy:
  default-src 'self';
  script-src  'self' 'nonce-{nonce}';
  style-src   'self' 'unsafe-inline';
  img-src     'self' data: https:;
  connect-src 'self' https://api.stripe.com https://*.supabase.co;
  font-src    'self';
  frame-ancestors 'none';
  base-uri    'self';
  form-action 'self'

Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
X-Content-Type-Options: nosniff
```

**What each header prevents:**

| Header | Attack blocked |
|---|---|
| `Content-Security-Policy` | XSS, data injection, clickjacking via frames |
| `Strict-Transport-Security` | SSL stripping, protocol downgrade |
| `X-Frame-Options: DENY` | Clickjacking (belt-and-suspenders with CSP) |
| `Referrer-Policy` | Referrer leakage of ride/driver IDs in URLs |
| `Permissions-Policy` | Ambient sensor/camera abuse from injected scripts |
| `X-Content-Type-Options` | MIME-type sniffing attacks |

---

## 6. Stripe webhook security

```
Stripe servers
      │
      │  POST /webhooks/stripe
      │  Stripe-Signature: t=...,v1=...
      │
      ▼
webhooks.py handler
      │
      ├── 1. stripe.webhook.construct_event(body, sig, STRIPE_WEBHOOK_SECRET)
      │        └── Fails if signature invalid, timestamp > 5 min old
      │
      ├── 2. claim_stripe_event(event.id, event.type, payload)
      │        ├── INSERT into stripe_events (unique on event_id)
      │        │
      │        ├── INSERT succeeds  →  is_new=True   →  return 200
      │        │                       queue processes it async
      │        │
      │        └── UNIQUE VIOLATION  →  is_new=False  →  return 200
      │                                  (duplicate, safe to ignore)
      │
      └── Returns 200 in < 100ms regardless of business logic
          (Stripe's 20s timeout never exceeded)
```

**What protects against each threat:**

| Threat | Protection |
|---|---|
| Forged webhook | HMAC signature verification |
| Replay attack (> 5 min old) | Stripe-Signature timestamp window |
| Duplicate processing on retry | `stripe_events` PK dedup |
| Slow handler causing Stripe retry storm | Async queue; handler returns 200 in < 100ms |

---

## 7. Before / after risk matrix

```
                     BEFORE AUDIT          AFTER AUDIT
                   ┌──────────────┐      ┌──────────────┐
Auth token stolen  │  30-day open │  →   │ Revoke in    │
                   │  window, no  │      │ seconds via  │
                   │  revocation  │      │ logout-all   │
                   └──────────────┘      └──────────────┘

Cross-user data    ┌──────────────┐      ┌──────────────┐
access             │  19 tables   │  →   │  All tables  │
                   │  unprotected │      │  deny-all +  │
                   │  by RLS      │      │  scoped read  │
                   └──────────────┘      └──────────────┘

Stripe duplicate   ┌──────────────┐      ┌──────────────┐
charges            │  Handler re- │  →   │  Atomic PK   │
                   │  runs on any │      │  claim; 200  │
                   │  retry       │      │  in < 100ms  │
                   └──────────────┘      └──────────────┘

Rate limit bypass  ┌──────────────┐      ┌──────────────┐
                   │  In-memory,  │  →   │  Redis,      │
                   │  resets on   │      │  cross-fleet,│
                   │  deploy      │      │  survives    │
                   └──────────────┘      └──────────────┘

Clickjacking /     ┌──────────────┐      ┌──────────────┐
XSS amplification  │  No headers  │  →   │  CSP, HSTS,  │
                   │  at all      │      │  XFO, XCTO   │
                   └──────────────┘      └──────────────┘
```
