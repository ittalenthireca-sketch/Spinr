# i18n (shared translations)

Placeholder for consolidated, cross-app translation catalogs. Each mobile
app currently ships its own copy; there are no translations for the
admin dashboard or backend-generated strings (SMS, email, push).

## What already exists in the repo

Per-app catalogs:

- `driver-app/i18n/` — `en.json`, `es.json`, `fr.json`, `fr-CA.json`,
  `index.ts`
- `rider-app/i18n/` — `en.json`, `fr-CA.json`, `index.ts`

Accessibility / language references:

- `docs/ux/A11Y_AUDIT.md`
- `rider-app/store-assets/metadata.json`,
  `driver-app/store-assets/metadata.json` (store listing localization)

## What's missing

- `rider-app` is missing `es` and `fr` (only `en` + `fr-CA`)
- `admin-dashboard` has no i18n setup at all
- Backend-generated strings (Twilio SMS templates in
  `backend/services/sms_service.py`, push notifications in
  `backend/routes/notifications.py`, email receipts) are English-only
- No shared translation source of truth → rider and driver apps can drift
- No locale negotiation on the API (no `Accept-Language` handling)

## Suggested layout when implementing

```
i18n/
  locales/
    en/
      common.json
      rider.json
      driver.json
      admin.json
      notifications.json   # SMS / push / email
    es/
    fr/
    fr-CA/
  scripts/                 # extract-keys, sync-to-apps, lint-missing
  README.md
```

Apps would import from `i18n/locales/<lang>/<namespace>.json` (or a
published `@spinr/i18n` workspace package) instead of maintaining
private copies.
