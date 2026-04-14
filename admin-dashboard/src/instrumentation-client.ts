/**
 * Sentry init for the Next.js client runtime — Phase 2.2f.
 *
 * Next 15.3+ picks up `instrumentation-client.ts` automatically and
 * runs it once on the browser bundle. This is where tab-side
 * exceptions (unhandled promise rejections, React render errors that
 * escape the ErrorBoundary in `src/app/error.tsx`) get captured.
 *
 * `replaysOnErrorSampleRate` = 1.0 is worth the quota: a session replay
 * tied to an admin-action error is massively more actionable than the
 * stack trace alone — the replay shows exactly which row the operator
 * clicked before the dashboard crashed. Non-error sessions are sampled
 * at 0 so we're not recording every page view.
 *
 * No-ops when `NEXT_PUBLIC_SENTRY_DSN` is unset so local dev still
 * loads the dashboard without any observability plumbing.
 */
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? 'production',
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
    tracesSampleRate: Number(
      process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? '0.1',
    ),
    // Session replay: off for healthy sessions, ON for error sessions.
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1.0,
    integrations: [
      Sentry.replayIntegration({
        // Mask all PII by default — the admin dashboard shows driver
        // names, phone numbers, PayPal emails. An operator's mistake
        // during an incident shouldn't leak into the replay payload.
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    sendDefaultPii: false,
  });
  Sentry.setTag('app', 'admin-dashboard');
  Sentry.setTag('runtime', 'client');
}

/**
 * Re-exported for Next.js router-transition instrumentation. Called
 * automatically by Next App Router on navigation so Sentry can link
 * client-side route changes to the correct trace.
 */
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
