# GitHub Actions Secrets Setup

This guide covers every secret and repository variable required for the
Spinr CI/CD pipeline (`ci.yml`, `synthetic-health.yml`, `deploy-backend.yml`,
`eas-build.yml`). Follow it in the order below.

---

## Quick-start: minimum secrets for CI tests to pass

CI tests (`backend-test`, `frontend-test`, `rider-app-test`, `driver-app-test`,
`admin-test`) run against a local Postgres container spun up by the workflow.
The only secrets they need to run without skipping are:

| Secret | Required for |
| --- | --- |
| `SUPABASE_URL` | Backend test suite (integration fixtures) |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend test suite (integration fixtures) |

Everything else gates deployment, mobile builds, Slack notifications, or
synthetic monitoring. Those jobs are skipped automatically on PRs and when
secrets are absent; they will not cause CI to fail.

Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` first if you only want
green CI before the rest of the infrastructure is provisioned.

---

## Where to add secrets and variables

**Secrets** (encrypted, never shown after save):
Settings → Secrets and variables → Actions → **Secrets** tab → New repository secret

**Repository Variables** (visible in logs, safe for non-sensitive flags):
Settings → Secrets and variables → Actions → **Variables** tab → New repository variable

---

## Secrets

### SUPABASE_URL

**What it is:** The public REST/PostgREST base URL for your Supabase project.
Format: `https://<project-ref>.supabase.co`

**Where to get it:**
1. Open [supabase.com](https://supabase.com) and select the `spinr-prod` project.
2. Settings → API → **Project URL**.

**Used by:** `ci.yml` backend-test job; backend runtime.

**Security notes:**
- This URL is not a secret in the Supabase sense (it is public-facing), but
  it reveals which project is yours. Keep it out of public logs.
- Never use the `spinr-prod` URL for a local dev `.env`. Create a separate
  `spinr-dev` project.

---

### SUPABASE_SERVICE_ROLE_KEY

**What it is:** A long-lived JWT that bypasses Row-Level Security. Anyone with
this key can read and write every table without restriction.

**Where to get it:**
1. Supabase dashboard → `spinr-prod` project → Settings → API.
2. Under "Project API keys", reveal and copy the **service_role** key.
   It starts with `eyJ`.

**Used by:** `ci.yml` backend-test job; backend runtime for admin operations.

**Security notes:**
- This is the most sensitive credential in the stack. Treat it like a root
  database password.
- Do NOT use the service-role key on the client side or in mobile apps.
- Rotate quarterly: generate a new project key via Supabase dashboard
  (Settings → API → Rotate), then update this secret and the matching
  Fly/Render secret in the same change.

---

### VERCEL_TOKEN

**What it is:** A Vercel personal access token used by `amondnet/vercel-action`
to authenticate deployments.

**Where to get it:**
1. Log in to [vercel.com](https://vercel.com).
2. Click your avatar (top-right) → Settings → Tokens → Create.
3. Name it `spinr-ci`, set scope to **Full Account**, expiry to 1 year.

**Used by:** `ci.yml` deploy-frontend and deploy-admin jobs.

**Security notes:**
- A single token can deploy to all projects in your org. Scope to "Full
  Account" is required for the action; there is currently no project-scoped
  token option in Vercel.
- Rotate annually (set a calendar reminder when you create it).
- If leaked, revoke immediately from vercel.com → Settings → Tokens.

---

### VERCEL_ORG_ID

**What it is:** The Vercel team or personal account ID that owns the projects.

**Where to get it:**
1. vercel.com → click your avatar → Settings → General.
2. Copy the **Team ID** (starts with `team_`) for a team account, or
   the **User ID** for a personal account.

Alternatively, run `vercel whoami --json` in a directory linked to the org.

**Used by:** `ci.yml` deploy-frontend and deploy-admin jobs.

**Security notes:** Not sensitive but must match the token's owner. Mismatch
causes a 403 on every deploy.

---

### VERCEL_FRONTEND_PROJECT_ID

**What it is:** The Vercel project ID for the rider-facing Expo web export
(`frontend/`).

**Where to get it:**
1. vercel.com → open the frontend project.
2. Project Settings → General → **Project ID** (starts with `prj_`).

Alternatively, check `.vercel/project.json` in the `frontend/` directory if
the project was linked locally.

**Used by:** `ci.yml` deploy-frontend job.

---

### VERCEL_ADMIN_PROJECT_ID

**What it is:** The Vercel project ID for the Next.js admin dashboard
(`admin-dashboard/`).

**Where to get it:**
1. vercel.com → open the admin dashboard project.
2. Project Settings → General → **Project ID** (starts with `prj_`).

**Used by:** `ci.yml` deploy-admin job.

---

### SLACK_WEBHOOK_URL

**What it is:** An incoming webhook URL that posts to the general CI/CD
notification channel (used when the pipeline fails on `main`).

**Where to get it:**
1. Go to [api.slack.com/apps](https://api.slack.com/apps) and open (or
   create) the Spinr app.
2. Features → Incoming Webhooks → Add New Webhook to Workspace.
3. Pick the `#spinr-ci` or `#spinr-deployments` channel.
4. Copy the webhook URL (format: `https://hooks.slack.com/services/T.../B.../...`).

**Used by:** `ci.yml` notify-failure job (pipeline failure on `main`).

**Security notes:**
- Webhook URLs are effectively a secret: anyone with the URL can post to
  that channel. Keep it out of logs and code.
- To revoke: Slack app → Incoming Webhooks → Revoke.

---

### SLACK_WEBHOOK_ALERTS

**What it is:** A separate incoming webhook that posts to the `#spinr-alerts`
channel used by the synthetic health monitors.

**Where to get it:** Same process as `SLACK_WEBHOOK_URL` but select the
`#spinr-alerts` channel.

Having a separate webhook lets you mute/archive one channel without
silencing the other.

**Used by:** `synthetic-health.yml` (health-shallow, health-deep,
rider-smoke-flow, k6-latency-synthetic failure notifications).

---

### EXPO_TOKEN

**What it is:** An EAS CLI access token used to authenticate `eas build`
in the mobile-build job.

**Where to get it:**
1. Log in to [expo.dev](https://expo.dev).
2. Account menu (top-right) → Access Tokens → Create token.
3. Name it `spinr-ci`, leave it as a personal token (no expiry option on
   the free tier; set a manual rotation reminder for 90 days).

**Used by:** `ci.yml` mobile-build job (triggered only when the commit
message contains `[build]`).

**Security notes:**
- The token has full access to your EAS account including all builds and
  credentials. Revoke from expo.dev if compromised.
- Mobile builds are expensive (credits) — the `[build]` trigger guard
  prevents accidental builds on every push.

---

### RENDER_API_KEY

**What it is:** A Render API key used to trigger backend deployments via
the Render deploy API.

**Where to get it:**
1. Log in to [render.com](https://render.com).
2. Account Settings → API Keys → Create API Key.
3. Name it `spinr-github-actions`.

**Used by:** `ci.yml` deploy-backend job (primary backend deploy).

**Security notes:**
- Render API keys are account-scoped and can manage all services. There
  is currently no service-scoped key option.
- Rotate quarterly.

---

### RENDER_BACKEND_SERVICE_ID

**What it is:** The Render service ID for the `spinr-backend` web service.
Format: `srv-<alphanumeric>`.

**Where to get it:**
1. Render dashboard → select the `spinr-backend` service.
2. The service ID appears in the URL: `render.com/web/srv-XXXXXX` or under
   Settings → Service Details.

**Used by:** `ci.yml` deploy-backend job.

**Security notes:** Not sensitive, but it is an operational detail that
reveals your infrastructure layout. Treat it as internal.

---

### RAILWAY_TOKEN

**What it is:** A Railway API token used as a fallback deploy target when
the Render deploy step fails.

**Where to get it:**
1. Log in to [railway.app](https://railway.app).
2. Account → Tokens → Create Token.
3. Name it `spinr-ci-fallback`.

**Used by:** `ci.yml` deploy-backend job (`if: failure()` fallback step).

**Security notes:**
- Railway tokens are account-scoped.
- If you are not using Railway as a fallback, you may set a placeholder
  value here and the fallback step will simply fail silently (it only
  runs when Render already failed).
- Rotate quarterly alongside `RENDER_API_KEY`.

---

## Repository Variables

Variables are unencrypted and appear in workflow logs. Only use them for
non-sensitive feature flags.

### SPINR_DEPLOY_ACTIVE

**What it is:** A flag that gates the entire `synthetic-health.yml` workflow.
When not set (or set to any value other than `'true'`), all synthetic
monitoring jobs are skipped. This prevents failed health checks from spamming
Slack before infrastructure is live.

**Where to set it:**
Settings → Secrets and variables → Actions → **Variables** tab → New repository variable.

- Name: `SPINR_DEPLOY_ACTIVE`
- Value: `true`

**When to set it:** After `spinr-api.fly.dev` and `spinr-api-staging.fly.dev`
are both live and returning 200 from `/health`.

**Default:** Leave unset (do not create the variable) until infrastructure
is provisioned. The synthetic workflow will skip silently.

**Used by:** `synthetic-health.yml` — all four jobs check
`vars.SPINR_DEPLOY_ACTIVE == 'true'` before running.

---

## Rotation schedule

| Secret | Rotation cadence | Notes |
| --- | --- | --- |
| `SUPABASE_SERVICE_ROLE_KEY` | Quarterly | Rotate in Supabase dashboard; update Fly + Render secrets in the same change |
| `VERCEL_TOKEN` | Annually (set expiry at creation) | |
| `EXPO_TOKEN` | Every 90 days (set calendar reminder) | |
| `RENDER_API_KEY` | Quarterly | |
| `RAILWAY_TOKEN` | Quarterly | |
| `SLACK_WEBHOOK_URL` | On team membership change | Revoke old, create new webhook in Slack |
| `SLACK_WEBHOOK_ALERTS` | On team membership change | |
| `SUPABASE_URL` | Never (stable project URL) | Changes only if project is recreated |
| `VERCEL_ORG_ID` | Never (stable org ID) | |
| `VERCEL_FRONTEND_PROJECT_ID` | Never (stable project ID) | |
| `VERCEL_ADMIN_PROJECT_ID` | Never (stable project ID) | |
| `RENDER_BACKEND_SERVICE_ID` | Never (stable service ID) | Changes only if service is recreated |

See `docs/ops/SECRETS_ROTATION.md` for the step-by-step rotation playbook
for each credential.
