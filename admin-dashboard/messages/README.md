# admin-dashboard i18n messages

This directory holds translation dictionaries consumed by `next-intl`.
Supported locales: `en` (default) and `fr-CA` (Canadian French).

## Wire-up plan (deferred to a follow-up ticket)

Full integration of `next-intl` touches several areas and needs careful
server/client component separation, so it is intentionally **not** landed
alongside these message files. The follow-up work will:

1. Add `next-intl` to `admin-dashboard/package.json`.
2. Introduce middleware (`admin-dashboard/src/middleware.ts`) that negotiates
   the request locale from the `Accept-Language` header or a cookie.
3. Restructure routes under `src/app/[locale]/...` and create a root
   `[locale]/layout.tsx` that wraps children in `<NextIntlClientProvider>`.
4. Expose `useTranslations()` to client components and `getTranslations()`
   to server components / route handlers.
5. Update `next.config.js` with the `next-intl` plugin.

Until then, teams can still edit `en.json` / `fr-CA.json` freely; adding new
keys here is non-breaking. Keep both files in lockstep (same key shape).
