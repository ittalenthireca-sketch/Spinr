# EAS Staged Rollout Runbook

Operational procedure for shipping OTA (Over-The-Air) updates and binary
releases to the Spinr rider and driver mobile apps via Expo Application
Services (EAS). This runbook covers channel hygiene, staged rollouts,
monitoring, and rollback.

Scope: `rider-app/` and `driver-app/` (both are Expo/React Native apps
configured via `eas.json`).

---

## 1. Channel map

EAS channels are the runtime binding between a binary build and an OTA
update branch. Every binary embeds a channel; at launch it pulls updates
from whatever branch is currently mapped to that channel.

| Channel       | Purpose                                  | Binary source                               | Update branch (default) |
| ------------- | ---------------------------------------- | ------------------------------------------- | ----------------------- |
| `development` | Local dev client (Metro, hot reload)     | `eas build --profile development`           | n/a (uses Metro)        |
| `test`        | Internal QA on `spinr-api.onrender.com`  | `eas build --profile test` (APK)            | `test`                  |
| `preview`     | Staging on `spinr-api.fly.dev`           | `eas build --profile preview` (APK)         | `preview`               |
| `production`  | App Store / Play Store release builds    | `eas build --profile production`            | `production`            |

The `channel` values live in `rider-app/eas.json` and `driver-app/eas.json`
under both the `build.*` profile (burned into binaries) and the top-level
`update.*` block (used by `eas update` when `--channel` is omitted).

---

## 2. Binary builds vs OTA updates

Use a **binary build** (`eas build` + `eas submit`) when:

- Bumping Expo SDK or any native dependency (e.g. `react-native-maps`,
  `expo-notifications`, `react-native-reanimated`).
- Changing anything under `android/` or `ios/` native code, `app.json`
  native config (splash, icons, permissions, bundle identifier), or
  `eas.json` env vars that are consumed at build time.
- Rotating signing certificates or provisioning profiles.

Use an **OTA update** (`eas update`) when:

- Shipping pure JS/TS changes: screens, business logic, styles, copy.
- Updating assets bundled with JS (images, fonts declared in JS).
- Hotfixing a crash whose fix lives entirely in the JS layer.

If in doubt, run `eas update --dry-run` first — if it flags a fingerprint
mismatch (native manifest changed), you need a binary build.

---

## 3. Staged rollout procedure (production OTA)

Default progression for a production OTA: **10% -> 25% -> 50% -> 100%**.

### 3.1 Pre-flight

From the app directory (`rider-app/` or `driver-app/`):

```bash
# Confirm you are on main and the build is green.
git fetch origin && git status
# Verify the update fingerprint matches the currently-shipped binary.
eas update --branch production --message "dry run" --dry-run
```

### 3.2 Publish at 10%

```bash
cd rider-app   # or driver-app
eas update \
  --branch production \
  --message "rider: <short description> (<short-sha>)" \
  --rollout-percentage 10
```

Capture the returned **group ID** and **update ID** in the incident/release
ticket. You will need the group ID for rollback.

### 3.3 Progression schedule

| Stage | Percentage | Soak time before next stage | Command                                                                 |
| ----- | ---------- | --------------------------- | ----------------------------------------------------------------------- |
| 1     | 10%        | 1 hour (smoke)              | `eas update --branch production --rollout-percentage 10 ...`            |
| 2     | 25%        | 4 hours                     | `eas update:edit --branch production --rollout-percentage 25`           |
| 3     | 50%        | 12 hours                    | `eas update:edit --branch production --rollout-percentage 50`           |
| 4     | 100%       | terminal                    | `eas update:edit --branch production --rollout-percentage 100`          |

Do **not** advance a stage if any of the Section 4 signals have regressed.

---

## 4. Monitoring during rollout

Watch these dashboards for the entire soak window of each stage. Compare
against the 24h baseline from before the rollout began.

- **Sentry (mobile project)** — crash-free users rate must stay >= 99.5%
  and must not drop by more than 0.2pp vs baseline. Filter by release to
  isolate the new update group.
- **API error rate (Fly.io / Render dashboards + `/metrics`)** — 5xx rate
  on `spinr-api.fly.dev` must stay below baseline + 0.5%. Watch latency
  p95 as well; an OTA that changes client request patterns can shift
  backend load.
- **Mixpanel / analytics funnel** — primary conversion funnel
  (open -> request ride -> ride accepted for riders; login -> go online ->
  accept for drivers) must not drop by more than 5% vs the 7-day rolling
  median.
- **Support inbox / #ops Slack** — any spike in user reports referencing
  the new release is an automatic hold.

If a signal degrades, **hold** the rollout (do not advance) and
investigate. If the regression is clearly caused by the update, proceed
to Section 5.

---

## 5. Rollback

### 5.1 Fast rollback (preferred) — republish prior group

Re-publishing the prior known-good update group atomically moves all
clients back:

```bash
eas update --branch production --republish --group <prior-group-id>
```

`<prior-group-id>` is the group ID from the last successful 100% release
(stored in the release ticket). This is the preferred rollback because
it keeps the `production` branch as the source of truth and preserves
update history.

### 5.2 Emergency revert — cut channel to a different branch

If the `production` branch itself is compromised (e.g. poisoned update,
cannot identify a safe group), repoint the channel:

```bash
# Point the production channel at a known-good branch (e.g. the prior
# release branch, or preview if it is genuinely production-safe).
eas channel:edit production --branch <prior-branch>
```

This is a bigger hammer: it affects every user on the `production`
channel on the next app foreground. Use only when 5.1 is not viable.
Remember to cut it back once the regular branch is healthy.

### 5.3 Post-rollback

- Set rollout-percentage of the bad update to 0 (defensive):
  `eas update:edit --branch production --rollout-percentage 0`.
- Open an incident doc, capture timeline, attach Sentry and API graphs.
- Write a regression test before re-attempting the fix.

---

## 6. Known limitations

- **OTA cannot ship native changes.** Anything touching native modules,
  Expo SDK version, permissions, or entitlements requires a new binary
  build through the App Store / Play Store review pipeline.
- **Rollout-percentage is per-branch, not per-user-cohort.** EAS assigns
  users to the rollout bucket via a deterministic hash of install ID; you
  cannot target specific users, geos, or app versions beyond what
  `--runtime-version` already enforces.
- **Runtime version must match.** An OTA only reaches binaries whose
  embedded runtime version matches the update's. Bumping SDK forces a
  new runtime and therefore a new binary before OTAs flow again.
- **iOS App Store review still applies to binary builds.** Plan at least
  24-48h lead time for production binary submissions; OTAs bypass review
  only for JS-layer changes permitted by Apple's guidelines.
- **Channel != branch.** A channel is a pointer; a branch is the stream
  of updates. `eas channel:edit` swaps the pointer without publishing a
  new update, which is why it is the emergency-revert tool.

---

## 7. Quick reference

```bash
# Publish a staged production OTA
eas update --branch production --message "..." --rollout-percentage 10

# Advance rollout
eas update:edit --branch production --rollout-percentage 25

# Rollback (preferred)
eas update --branch production --republish --group <prior-group-id>

# Emergency channel cutover
eas channel:edit production --branch <prior-branch>

# Inspect current state
eas channel:view production
eas update:list --branch production --limit 10
```
