/**
 * Sentry initialisation — shared between rider-app and driver-app.
 *
 * Phase 2.2 of the production-readiness audit (audit finding T1).
 *
 * Both apps had Firebase Crashlytics wired in `services/firebase.ts`,
 * which catches native JVM / Obj-C crashes, but JS runtime errors
 * (unhandled promise rejections, render-time throws that escape the
 * ErrorBoundary, NetInfo transient failures) went to console.log
 * only — i.e. nowhere operators could see them. Sentry covers that
 * JS layer and gives us the same issue-triage surface as the backend
 * so a rider-app crash report can be correlated with the corresponding
 * API request via traceparent.
 *
 * Why a shared helper and not per-app init
 * ----------------------------------------
 * The SDK config (DSN, release, env, sampling) is structurally
 * identical between the two apps — only the `appName` tag differs.
 * Duplicating the init code across `rider-app/app/_layout.tsx` and
 * `driver-app/app/_layout.tsx` would guarantee drift the first time
 * someone tweaks sampling on one side only.
 *
 * Lazy-require pattern
 * --------------------
 * `@sentry/react-native` ships a native module. It's harmless in dev
 * builds but the require itself can throw on Expo Go (no custom
 * native modules) and during jest tests. We mirror the pattern from
 * `firebase.ts` — require inside a try/catch and no-op if unavailable
 * so the rest of the app boots regardless.
 */

// The native module is required lazily inside initSentry so this file
// is safe to import from non-bundled contexts (tests, tooling).
let Sentry: any = null;

function loadSentry(): any {
  if (Sentry) return Sentry;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    Sentry = require('@sentry/react-native');
    return Sentry;
  } catch (e) {
    console.log('[Sentry] @sentry/react-native unavailable:', e);
    return null;
  }
}

export interface SentryInitOptions {
  /** The app this init is running in — surfaces as the `app` tag. */
  appName: 'rider-app' | 'driver-app';
  /**
   * DSN — read from EXPO_PUBLIC_SENTRY_DSN via app.config.ts `extra`.
   * When blank the helper no-ops. Production deploys MUST set it; the
   * backend won't allow a deploy without it on the API side and the
   * mobile story should match.
   */
  dsn?: string | null;
  /** 'development' | 'staging' | 'production'. Defaults to 'production'. */
  environment?: string | null;
  /** Release tag — EAS passes this via env when building. */
  release?: string | null;
  /** Override default 0.1 sampling when debugging a specific release. */
  tracesSampleRate?: number;
}

/**
 * Initialise Sentry for a mobile app. Safe to call multiple times —
 * the SDK itself dedupes on its internal `isInitialized()` flag, but
 * we also short-circuit up front to avoid re-reading the DSN.
 */
let initialised = false;

export function initSentry(opts: SentryInitOptions): void {
  if (initialised) return;
  const dsn = (opts.dsn ?? '').trim();
  if (!dsn) {
    // Silent in production — the only way to surface "we forgot to set
    // the DSN" is a synthetic check that verifies a canary event lands
    // in Sentry. Phase 2.6 covers that.
    console.log(`[Sentry] No DSN configured for ${opts.appName}; skipping init`);
    return;
  }

  const S = loadSentry();
  if (!S) return;

  try {
    S.init({
      dsn,
      environment: (opts.environment ?? 'production').toLowerCase(),
      release: opts.release || undefined,
      // 10% transactions by default — enough for p95 traces, cheap on
      // Sentry quota. Operators can bump via an env override at build
      // time without touching this file.
      tracesSampleRate:
        typeof opts.tracesSampleRate === 'number' ? opts.tracesSampleRate : 0.1,
      // Attach the raw JS stack frames so Sentry can symbolicate them
      // against the sourcemaps uploaded by EAS (Phase 2.2e).
      attachStacktrace: true,
      // Off by default because React Native produces gigantic
      // breadcrumb lists — we keep the console integration but drop
      // the noisy ones.
      enableNative: true,
      enableNativeCrashHandling: true,
      sendDefaultPii: false,
    });
    S.setTag('app', opts.appName);
    initialised = true;
    console.log(`[Sentry] Initialised for ${opts.appName} (env=${opts.environment ?? 'production'})`);
  } catch (e) {
    console.log('[Sentry] init failed:', e);
  }
}

/** Capture a handled exception with extra context. */
export function captureException(err: unknown, context?: Record<string, unknown>): void {
  const S = loadSentry();
  if (!S) return;
  try {
    if (context) S.setContext('extra', context as any);
    S.captureException(err);
  } catch {
    // swallow — observability must never take the app down
  }
}

/** Attach the authenticated user so issues are filterable by user_id. */
export function setUser(user: { id?: string | null; email?: string | null } | null): void {
  const S = loadSentry();
  if (!S) return;
  try {
    if (!user || !user.id) {
      S.setUser(null);
      return;
    }
    S.setUser({ id: user.id, email: user.email ?? undefined });
  } catch {
    // swallow
  }
}
