# Expo SDK 54 -> 55 Upgrade Runbook (rider-app)

Status: **manifest-only PR**. `package-lock.json` / `yarn.lock` regen, native
rebuilds, EAS submissions and store promotion are **follow-up work** tracked in
separate tickets.

> This PR does NOT run `npm install` - follow-up ticket regenerates
> `package-lock.json` in a clean env.

## 1. Why we are upgrading

1. **Security patches.** SDK 55 rolls up several CVE-addressed transitive
   patches (react-native, expo-updates, expo-modules-core). Staying on SDK 54
   means we accumulate known-vuln debt on every cycle.
2. **Parity with driver-app.** `driver-app` shipped on SDK 55 in the previous
   release train. Divergent SDKs in the same monorepo force us to maintain two
   Metro configs, two Babel config trees, two EAS build images, and two sets
   of native pod caches. This blocks shared component extraction (F1 in the
   production-readiness audit).
3. **Dep alignment.** Several shared deps (`expo-blur`, `expo-document-picker`,
   `expo-router`, `ajv`, `jest-expo`, `@testing-library/react-native`) are
   already newer in driver-app. Aligning reduces "works on my machine" drift.
4. **Toolchain deprecations.** Expo typically supports N-2 SDKs; staying on 54
   risks losing EAS Build support within one or two more releases.

## 2. Scope of this PR

Only `rider-app/package.json` is touched. No code changes, no metro config
changes, no native project regeneration, no lockfile changes.

### Version bumps applied

| Dependency                              | Old         | New          |
| --------------------------------------- | ----------- | ------------ |
| `expo`                                  | `~54.0.0`   | `~55.0.15`   |
| `expo-blur`                             | `~15.0.8`   | `~55.0.14`   |
| `expo-document-picker`                  | `~14.0.8`   | `~55.0.13`   |
| `expo-router`                           | `~55.0.12`  | `~6.0.23`    |
| `ajv`                                   | `^8.17.1`   | `^8.18.0`    |
| `jest-expo` (dev)                       | `~54.0.0`   | `^55.0.14`   |
| `@testing-library/react-native` (dev)   | `^12.4.0`   | `^13.3.3`    |

Rider-only deps (`@stripe/stripe-react-native`, `@gorhom/bottom-sheet`,
`expo-symbols`, `expo-web-browser`, `react-native-webview`) are left
untouched - they are not shared with driver-app and have no forcing function
in this PR.

## 3. Known breaking changes (SDK 54 -> 55)

**Do not rely on the specifics below as gospel - read the official changelog
before starting the rebuild.** Canonical sources:

- https://expo.dev/changelog (look for the "SDK 55" post)
- https://github.com/expo/expo/blob/main/CHANGELOG.md
- https://reactnative.dev/blog (for the bundled RN 0.81 notes)

Broad categories of documented breaking changes to expect:

- React Native core bump (new architecture defaults, bridgeless mode changes).
- `expo-router` major version jump (file-based routing API tweaks, typed
  routes generation).
- `expo-notifications` permissions + channel API adjustments (rider-app does
  not currently depend on it directly, but transitive usage via Firebase
  messaging should be smoke-tested).
- `expo-updates` manifest schema and runtime version policy changes.
- Node engine minimum bumped (verify local + CI Node versions).

## 4. Upgrade procedure (follow-up ticket)

1. **Sync manifest** (this PR already does this). Confirm `rider-app/package.json`
   matches what driver-app ships for shared deps.
2. **Regenerate lockfile in a clean env.**
   ```bash
   cd rider-app
   rm -rf node_modules package-lock.json yarn.lock
   npm install      # or `yarn install` - match the packageManager field
   npx expo install --fix
   ```
3. **iOS pod install.**
   ```bash
   cd rider-app/ios
   pod deintegrate && pod install --repo-update
   ```
4. **Clean Metro + Watchman caches.**
   ```bash
   watchman watch-del-all
   rm -rf $TMPDIR/metro-* $TMPDIR/haste-map-*
   npx expo start -c
   ```
5. **Dev client build.** `eas build --profile development --platform all`.
   Install on a physical device and run the full app.
6. **EAS build against `test` channel.**
   `eas build --profile preview --channel test --platform all`.
7. **Smoke test** (see QA checklist below) on the `test` channel build.
8. **Promote to `preview` channel** for broader internal QA.
   `eas update --channel preview --message "SDK 55 upgrade"`.
9. **Production promotion** only after 48h soak on preview with no
   crash-free-session regression in Crashlytics.
   `eas update --channel production --message "SDK 55 upgrade"`.

## 5. QA checklist

- [ ] App boots cleanly (cold start < 3s on mid-tier Android).
- [ ] Auth flow: phone OTP sign-in, session persistence across relaunch.
- [ ] Place search (Google Places autocomplete) returns results.
- [ ] Ride request: create, track driver, receive state updates.
- [ ] Payment sheet: Stripe `presentPaymentSheet` renders and confirms.
- [ ] Map rendering: `react-native-maps` tiles + directions polyline.
- [ ] Push notification receipt (foreground + background + killed state).
- [ ] Deep links: universal / app links route to correct expo-router screen.
- [ ] OTA update delivery via `expo-updates` on the target channel.
- [ ] Crashlytics and App Check still register events post-upgrade.

## 6. Rollback procedure

If the `test` or `preview` channel shows a regression:

1. **Revert `rider-app/package.json`** to the SDK 54 pin set (this commit's
   parent).
2. **Regenerate lockfile** in a clean env (same steps as section 4.2).
3. **Rebuild native** (`pod install`, EAS build on the prior channel).
4. **Republish OTA** to roll affected users back:
   ```bash
   eas update --channel <affected-channel> --message "Rollback SDK 55"
   ```
5. File an incident ticket with the failing QA checklist item + Crashlytics
   stack trace so the next attempt has concrete repro data.

Production rollback specifically: because `expo-updates` runtime version is
tied to the native binary, an OTA alone can only roll back JS/asset changes.
If the native layer is the regression, a full store submission of the prior
binary is required - budget 24-72h for Apple review.

## 7. Risk assessment

| Dependency                          | Risk   | Notes                                                                 |
| ----------------------------------- | ------ | --------------------------------------------------------------------- |
| `expo` (SDK)                        | Red    | Cross-cutting; triggers native rebuild on both platforms.             |
| `expo-router`                       | Red    | Major version (5 -> 6 line); routing API + typed routes churn.        |
| `expo-blur`                         | Yellow | Version line realigned to SDK channel; native module changes.         |
| `expo-document-picker`              | Yellow | Realigned to SDK channel; Android intent handling changes.            |
| `jest-expo`                         | Yellow | May require snapshot regeneration; dev-only blast radius.             |
| `@testing-library/react-native`     | Yellow | v12 -> v13 drops some legacy query fallbacks; test-only.              |
| `ajv`                               | Green  | Patch-range bump within 8.x.                                          |

## 8. Explicit non-goals of this PR

- No `package-lock.json` / `yarn.lock` regeneration.
- No native `ios/` or `android/` project changes.
- No Metro / Babel config edits.
- No EAS build, no channel publish, no store submission.
- No rider-app-only dep bumps (Stripe, bottom-sheet, webview, symbols).

Follow-up tickets track each of the above.
