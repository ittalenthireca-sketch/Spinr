import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8001/api/:path*",
      },
    ];
  },
};

// Sentry wrapper (Phase 2.2f / audit T1). Uploads JS sourcemaps at
// build time using SENTRY_AUTH_TOKEN + SENTRY_ORG + SENTRY_PROJECT from
// the build environment (Vercel secret store). No-ops when those are
// unset so local `next build` works without Sentry access.
//
// silent=true keeps build output clean; Sentry prints a rich summary
// block by default that drowns out actual build errors in CI logs.
//
// hideSourceMaps=true keeps the uploaded maps out of the production
// bundle so a browser DevTools user can't walk the whole source tree.
// Stack traces still resolve in Sentry because the debug-id links the
// minified bundle to the uploaded map server-side.
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT ?? "spinr-admin-dashboard",
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: true,
  widenClientFileUpload: true,
  hideSourceMaps: true,
  disableLogger: true,
});
