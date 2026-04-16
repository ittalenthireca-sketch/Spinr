/**
 * Next.js instrumentation entrypoint — Phase 2.2f of the production-
 * readiness audit (audit finding T1).
 *
 * `register()` is called by Next.js once per runtime (Node server,
 * Edge, and build). We delegate to the per-runtime Sentry configs so
 * the SDK can hook into the relevant transport for each environment.
 * The Node config runs on the server, the Edge config runs on middleware
 * routes, and the client init lives in `instrumentation-client.ts`
 * (Next 15.3+ convention — Next wires that file automatically on the
 * browser bundle).
 *
 * No-ops when `NEXT_PUBLIC_SENTRY_DSN` is unset so local dev keeps
 * working without observability plumbed in.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('./sentry.server.config');
  }
  if (process.env.NEXT_RUNTIME === 'edge') {
    await import('./sentry.edge.config');
  }
}

/**
 * Required for Sentry's `captureRequestError` integration with
 * `@sentry/nextjs` 8+. Exported from the Sentry SDK so any
 * uncaught React Server Component error reaches the same issue
 * stream as client / server exceptions.
 */
export { captureRequestError as onRequestError } from '@sentry/nextjs';
