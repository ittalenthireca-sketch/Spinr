/**
 * Sentry init for the Next.js Node runtime — Phase 2.2f.
 *
 * Called from `instrumentation.ts` once per Node server boot. Mirrors
 * the backend's `utils/sentry_init.py` shape (role tag, sampling, PII
 * policy) so the admin dashboard's issue stream joins the same Sentry
 * project without drift between surfaces.
 *
 * No-ops when `NEXT_PUBLIC_SENTRY_DSN` is unset; production deploys
 * must set it alongside `NEXT_PUBLIC_SENTRY_ENV` and
 * `NEXT_PUBLIC_SENTRY_RELEASE`.
 */
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? 'production',
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
    // 10% transactions by default — same rate as the backend and the
    // mobile apps. Tuned centrally from one env var so an incident
    // triage doesn't need a redeploy to bump sampling.
    tracesSampleRate: Number(
      process.env.SENTRY_TRACES_SAMPLE_RATE ?? '0.1',
    ),
    // PII is off — admin dashboard pages include driver/rider PII in
    // the URL (user IDs, ride IDs). Keeping sendDefaultPii=false means
    // Sentry receives URLs but no cookies/IP/user agent that could
    // re-identify an individual's session.
    sendDefaultPii: false,
  });
  Sentry.setTag('app', 'admin-dashboard');
  Sentry.setTag('runtime', 'server');
}
