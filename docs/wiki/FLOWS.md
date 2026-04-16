# Spinr — Critical Request Flows

> **Role:** Senior Backend Engineer  
> **Audience:** Backend engineers, mobile engineers, QA, new joiners

Every flow below traces a request end-to-end: client → edge → API
→ DB/Redis/Stripe → response → side-effects.

---

## 1. Rider login (OTP)

```
rider-app (login screen)
     │
     │  handleSendCode()
     │  POST /auth/send-otp  { phone: "+13065550199" }
     │
     ▼
Rate limiter:  otp_limit = 5 req / 15 min / IP
  Over limit → 429 (caller shows "Too many attempts")
     │
     ▼
routes/auth.py  send_otp()
     ├── Format phone to E.164
     ├── Generate 6-digit OTP, bcrypt-hash it
     ├── Upsert into otp_records { phone, hash, expires_at=+10min }
     └── Twilio SMS: "Your Spinr code is 123456"
          │
          └── Returns { success: true }

     (OTP sent to rider's phone)

rider-app (otp screen)
     │
     │  handleVerify()
     │  POST /auth/verify-otp
     │  { phone, otp: "123456", accepted_tos_version: "v1.0" }
     │
     ▼
routes/auth.py  verify_otp()
     ├── Look up otp_records by phone, not expired
     ├── bcrypt.verify(otp, hash)  → fail → 401
     ├── Look up users by phone
     │     ├── EXISTS: update last_login_at
     │     └── NEW:    require accepted_tos_version (422 if missing)
     │                 insert user with tos timestamps
     ├── Issue access_token  (JWT, 30-day TTL)
     ├── Issue refresh_token (opaque hash, 90-day TTL)
     │     └── INSERT into refresh_tokens
     └── Returns { access_token, refresh_token, user }

authStore.applyAuthResponse()
     ├── AsyncStorage: persist access_token, refresh_token
     └── Navigate to home screen
```

---

## 2. Ride request (idempotent)

```
rider-app (payment-confirm screen)
     │
     │  handleBookRide() → createRide(paymentMethod)
     │
     │  rideStore.createRide():
     │  ┌──────────────────────────────────────────┐
     │  │  idempotencyKey = crypto.randomUUID()    │
     │  │  (one UUID per *attempt*, reused across  │
     │  │   retries for the same booking attempt)  │
     │  └──────────────────────────────────────────┘
     │
     │  POST /rides
     │  Headers: Idempotency-Key: <uuid>
     │           Authorization: Bearer <access_token>
     │  Body: { pickup, dropoff, vehicle_type_id, payment_method }
     │
     ▼  (on network error: retry up to 3× with 500ms/1500ms back-off)

Rate limiter:  ride_request_limit = 10 req / min / user
     │
     ▼
routes/rides.py  create_ride()
     │
     ├── IDEMPOTENCY CHECK:
     │     claim_ride_idempotency_key(key, rider_id)
     │       ├── INSERT succeeds → is_new=True  → continue
     │       ├── DUPLICATE + response present → return cached 200
     │       └── DUPLICATE + response NULL → 409 "in flight"
     │
     ├── validate_ride_location()  (lat/lng bounds check)
     ├── Ban check  (user_status != banned/suspended)
     ├── Payment method check  (stripe_customer_id exists)
     ├── Fare calculation:
     │     base_fare + distance_fare + time_fare + booking_fee
     │     + surge_multiplier + airport_fee + tax
     │     (all Decimal arithmetic — no float rounding)
     ├── Service area resolution
     ├── rides.insert_one(ride_data)
     │
     ├── match_driver_to_ride(ride_id)
     │     └── (see flow §4)
     │
     ├── asyncio.create_task(ride_search_timeout, 300s)
     │     └── Auto-cancel if still "searching" after 5 min
     │
     ├── record_ride_idempotency_response(key, rider_id, ride_id, response)
     │     └── Stamps JSON snapshot → any retry returns this verbatim
     │
     └── Returns ride object { id, status: "searching", fare_breakdown... }

rider-app:  set currentRide, navigate to ride-status screen
```

---

## 3. Token refresh (silent)

```
rider-app makes any authenticated API call
     │
     ▼
shared/api/client.ts (Axios)
     │
     ├── Request succeeds → happy path
     │
     └── Response: 401 Unauthorized
               │
               ▼
         withRefreshRetry()
               │
               ├── Is a refresh already in flight?
               │     YES → queue this retry, wait for refresh to finish
               │     NO  → proceed (single-flight pattern)
               │
               │  POST /auth/refresh
               │  { refresh_token }
               │
               ├── 200: new { access_token, refresh_token }
               │       └── applyAuthResponse() → update AsyncStorage
               │           └── Retry all queued requests with new token
               │
               └── 401 on refresh (token revoked / expired):
                       └── authStore.logout()
                           └── Navigate to login screen
```

---

## 4. Dispatch flow

```
Worker process  (scheduled_dispatcher, 60s loop)
     │
     ├── Fetch all rides WHERE status='searching'
     │
     └── For each ride:
               │
               ├── ST_DWithin query (PostGIS):
               │     SELECT drivers WHERE is_online=true
               │     AND ST_DWithin(location_geo,
               │                    ST_MakePoint(pickup_lng, pickup_lat),
               │                    5000)  ← 5km radius
               │     ORDER BY location_geo <-> pickup_point
               │     LIMIT 10
               │
               ├── Score candidates:
               │     distance_score + rating_score + acceptance_score
               │
               ├── Send offer to best candidate:
               │     manager.send_personal_message(
               │       { type: "ride_offer", ride_id, ... },
               │       f"driver_{driver_id}"
               │     )
               │     └── → Redis pub/sub → all API machines
               │           → driver's machine delivers to WS
               │
               ├── Set offer_expiry = now + 30s
               │
               └── If no driver responds in 30s:
                         └── Try next candidate
                             (max 3 attempts, then auto-cancel at 5min)

driver-app receives ride_offer via WebSocket
     │
     └── Driver accepts:
           POST /drivers/rides/<id>/accept
                 │
                 ├── rides.update status → "accepted"
                 ├── rides.set driver_id = accepting_driver
                 └── manager.send_personal_message(
                       { type: "ride_accepted", driver, eta },
                       f"rider_{rider_id}"
                     )
```

---

## 5. Payment capture

```
ride completes (POST /rides/<id>/complete)
     │
     ├── rides.update status → "completed"
     └── asyncio.create_task(process_payment, ride_id)
               │
               ▼
Stripe PaymentIntent confirm:
     stripe.payment_intents.confirm(intent_id)
               │
               ├── SUCCESS:
               │     rides.update payment_status → "paid"
               │     send_push_notification(rider, "Payment received")
               │
               └── FAILURE:
                     rides.update payment_status → "payment_failed"
                     Insert into payment_retry queue
                           │
                           ▼
Worker process (payment_retry, 5min loop)
                     ├── Fetch rides WHERE payment_status='payment_failed'
                     │   AND retry_count < 3
                     ├── Re-attempt Stripe confirm
                     └── After 3 failures: notify support + rider
```

---

## 6. Stripe webhook (idempotent async)

```
Stripe POST /webhooks/stripe
  Header: Stripe-Signature: t=...,v1=<hmac>
     │
     ▼
routes/webhooks.py
     │
     ├── stripe.webhook.construct_event()
     │     └── Fail → 400 (invalid signature)
     │
     ├── claim_stripe_event(event.id, event.type, payload)
     │     ├── INSERT succeeds  → is_new=True  → queue it
     │     └── UNIQUE VIOLATION → is_new=False → skip (duplicate)
     │
     └── return 200  ← always fast (< 100ms)
         (Stripe never waits for business logic)

Worker process  (stripe_event_worker, 5s loop)
     │
     ├── fetch_unprocessed_stripe_events(limit=10)
     │
     └── For each event:
               ├── Dispatch to handler by event.type:
               │     payment_intent.succeeded → mark ride paid
               │     payment_intent.failed    → queue retry
               │     customer.subscription.*  → update subscription
               │
               ├── mark_stripe_event_processed(event_id)
               │
               └── On failure:
                     attempt_count++
                     next_attempt_at = now + exponential_backoff
                     (30s → 1min → 5min → 30min → 1hr)
                     mark_stripe_event_failed(event_id, error)
```

---

## 7. Emergency SOS

```
rider-app (emergency button tapped)
     │
     │  POST /rides/<id>/emergency
     │  { contact_phone: "+13065550188" }
     │
     ▼
routes/rides.py  emergency_contact()
     │
     ├── Validate ride belongs to rider (auth check)
     ├── Fetch driver + vehicle details
     ├── Compose SMS:
     │     "EMERGENCY: [Rider Name] may need help.
     │      Ride ID: abc123
     │      Driver: John Smith, Vehicle: 2022 Honda Civic ABC123
     │      Last known location: https://spinr.app/track/abc123
     │      If in immediate danger, call 911."
     ├── send_sms(contact_phone, message, twilio_sid, twilio_token,
     │           twilio_from)
     ├── Log emergency event to rides.emergency_contacts_notified
     └── return { success: true }
```

---

## 8. Share ride

```
rider-app (share button tapped)
     │
     │  POST /rides/<id>/share
     │  { contact_phone: "+13065550177" }
     │
     ▼
routes/rides.py  share_ride()
     │
     ├── Generate or reuse share_token (UUID, stored on ride)
     ├── Build URL: {FRONTEND_URL}/track/{share_token}
     ├── Check if contact is a Spinr user:
     │     ├── IS Spinr user:
     │     │     manager.send_personal_message(
     │     │       { type: "shared_ride", url },
     │     │       f"rider_{contact_user_id}"
     │     │     )
     │     └── NOT Spinr user:
     │           send_sms(contact_phone,
     │             "Tracking link: {url} — tap to follow in real time")
     └── return { share_url }
```

---

## 9. Background loop: data retention

```
Worker process  (data_retention_loop, 24h loop)
     │
     ├── Runs at: 02:00 UTC nightly
     │
     ├── otp_records older than 24h
     │     DELETE WHERE created_at < now()-1d LIMIT 500 (repeat until 0)
     │
     ├── ride_idempotency_keys older than 24h
     │     DELETE WHERE created_at < now()-1d LIMIT 500
     │
     ├── refresh_tokens (expired) older than 7 days
     │     DELETE WHERE expires_at < now()-7d LIMIT 500
     │
     ├── gps_breadcrumbs older than 90 days
     │     DETACH PARTITION gps_breadcrumbs_<month>;
     │     DROP TABLE gps_breadcrumbs_<month>;
     │     (O(1) metadata op — no row-level delete)
     │
     ├── rides (cancelled) older than 90 days
     │     DELETE WHERE status='cancelled' AND updated_at < now()-90d LIMIT 500
     │
     ├── chat_messages older than 180 days
     │     DELETE WHERE created_at < now()-180d LIMIT 500
     │
     ├── stripe_events (processed) older than 90 days
     │     DELETE WHERE processed_at < now()-90d LIMIT 500
     │
     └── record_bg_task_heartbeat("data_retention_loop", "ok")
           └── /health/deep will surface if this loop goes stale
```
