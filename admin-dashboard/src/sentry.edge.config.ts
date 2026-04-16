/**
 * Sentry init for the Next.js Edge runtime — Phase 2.2f.
 *
 * Runs on Vercel Edge / middleware invocations. Middleware (see
 * `src/middleware.ts`) currently handles auth redirects; any throw in
 * there would be invisible without this init. The Edge runtime has a
 * reduced API surface so we skip integrations that need Node-only APIs
 * (e.g. profiling).
 */
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? 'production',
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
    tracesSampleRate: Number(
      process.env.SENTRY_TRACES_SAMPLE_RATE ?? '0.1',
    ),
    sendDefaultPii: false,
  });
  Sentry.setTag('app', 'admin-dashboard');
  Sentry.setTag('runtime', 'edge');
}
