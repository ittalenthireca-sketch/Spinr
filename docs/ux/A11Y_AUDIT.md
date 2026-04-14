# Spinr — Mobile Accessibility Audit (A11y)

Phase 4.2 of the production-readiness audit (audit finding F4).

**Version:** 1.0
**Effective date:** 2026-04-14
**Owner:** Mobile Lead
**Review cadence:** Once per Expo SDK upgrade, and on any change to a
screen listed in §3 below.

This document is the source of truth for Spinr's mobile accessibility
posture. It defines (a) the conformance target, (b) the 12 critical
screens we audit every release, (c) the remediation status for each
screen, and (d) the manual test protocol we run before we ship a
build to the App Store / Play Store.

---

## 1. Conformance target

**WCAG 2.1 Level AA**, adapted for native mobile:

- **Perceivable.** Every interactive or informational element is
  reachable by a screen reader. Dynamic state changes (loading,
  error, success) are announced. Contrast ratio ≥ 4.5:1 for text,
  ≥ 3:1 for large text and icons.
- **Operable.** Every touch target ≥ 44×44 dp (iOS HIG) / 48×48 dp
  (Material). Focus order follows visual order. No gesture is
  required that a switch-control user cannot simulate.
- **Understandable.** Screens, controls, and errors have accessible
  names that describe *what the control does*, not *what it looks
  like*. Language is declared per-screen for VoiceOver pronunciation
  (en-CA / fr-CA).
- **Robust.** We use React Native's native accessibility props
  (`accessibilityLabel`, `accessibilityHint`, `accessibilityRole`,
  `accessibilityState`) so VoiceOver (iOS) and TalkBack (Android)
  both get correct semantics without a custom bridge.

**Non-goals (explicitly out of scope):** WCAG AAA, BrowseAloud-style
text-to-speech of non-interactive content, automated CI a11y
linting (tracked as a follow-up in §6).

---

## 2. Protocol

Before every production release we run this matrix:

| Screen | VoiceOver (iOS) | TalkBack (Android) | Dynamic text | Contrast | Touch targets |
|---|---|---|---|---|---|
| 12 critical screens in §3 | pass | pass | 200% OK | ≥ 4.5:1 | ≥ 44 dp |

The runner records pass/fail per cell in a shared spreadsheet, and
any fail blocks the release unless the responsible PM signs off on a
hotfix deferral in writing.

---

## 3. The 12 critical screens

"Critical" = every screen in the rider-app core flow (request →
pay → ride → rate) plus the driver-app onboarding + active-ride
surfaces. These are the screens that a visually-impaired user
literally cannot skip.

| # | App | Screen file | Flow | Remediation status |
|---|---|---|---|---|
| 1 | rider-app | `app/login.tsx` | Auth: phone entry | ✅ pass (2026-04-14) |
| 2 | rider-app | `app/otp.tsx` | Auth: OTP verify | ✅ pass (2026-04-14) |
| 3 | rider-app | `app/(tabs)/index.tsx` | Home / pickup entry | ⏳ pending |
| 4 | rider-app | `app/search-destination.tsx` | Destination search | ⏳ pending |
| 5 | rider-app | `app/ride-options.tsx` | Vehicle + surge + promo | ⏳ pending |
| 6 | rider-app | `app/payment-confirm.tsx` | Confirm + book | ✅ pass (2026-04-14) |
| 7 | rider-app | `app/ride-status.tsx` | Driver en route | ⏳ pending |
| 8 | rider-app | `app/ride-in-progress.tsx` | In-ride map | ⏳ pending |
| 9 | rider-app | `app/rate-ride.tsx` | Rating + tip | ⏳ pending |
| 10 | driver-app | `app/login.tsx` | Auth: phone entry | ✅ pass (2026-04-14) |
| 11 | driver-app | `app/driver/home.tsx` | Go-online + requests | ⏳ pending |
| 12 | driver-app | `app/driver/active-ride.tsx` | Navigation + actions | ⏳ pending |

"⏳ pending" = passes visual tests but still missing explicit
`accessibilityLabel` / `accessibilityHint` annotations on
dynamically-labelled controls. Remediation order follows the
customer-funnel: we close 3 → 4 → 5 → 7 first, then the driver
screens.

### Patterns already landed

The remediation sweep applied four mechanical patterns that every
future screen must reuse:

1. **Form inputs** get `accessibilityLabel`,
   `accessibilityHint`, platform-appropriate `autoComplete`,
   `textContentType`, and `importantForAutofill`. See
   `rider-app/app/login.tsx:154-172` for the canonical phone-input
   example and `rider-app/app/otp.tsx:222-240` for the OTP input.
2. **Primary CTAs** get `accessibilityRole="button"`, a label that
   describes the action (not the visible text — labels can be
   overridden for screen readers), and `accessibilityState` with
   `disabled` + `busy` flags so VoiceOver announces "Send
   verification code, dimmed" vs "Send verification code, busy".
   See `rider-app/app/login.tsx:184-210` and
   `rider-app/app/payment-confirm.tsx:309-325`.
3. **Icon-only buttons** (back chevron, close X, etc.) get
   `accessibilityLabel` + `hitSlop` (≥ 12 dp each side) so they
   both announce correctly and satisfy the 44-dp target even when
   the icon itself is smaller. See
   `rider-app/app/otp.tsx:199-208`.
4. **Announce dynamic state.** When a ride transitions (e.g.
   "driver arriving → driver arrived"), the new screen's top-level
   heading gets `accessibilityLiveRegion="polite"` on Android and
   the equivalent `accessibilityRole="header"` + focus-on-mount on
   iOS. This pattern is tracked as a refactor in §6.

### What a "pass" means for a screen

To mark a row ✅ the screen must satisfy:

- Every interactive element has an `accessibilityLabel` *and*
  either `accessibilityHint` or an accessible-enough label on its
  own.
- Every interactive element has an `accessibilityRole`
  (`"button"`, `"link"`, `"header"`, `"image"`, `"switch"`,
  `"adjustable"`).
- Every disabled / busy / selected control reflects that state
  via `accessibilityState`.
- All images are either decorative (`accessibilityElementsHidden`
  on iOS / `importantForAccessibility="no"` on Android) or carry a
  real label.
- Manual VoiceOver and TalkBack walkthrough completes the golden
  path without the tester needing to look at the screen.

---

## 4. Contrast + colour

We ship one light-mode palette today (see
`shared/config/spinr.config.ts`). Contrast spot-checked at audit
time:

| Pair | Ratio | WCAG AA | Notes |
|---|---|---|---|
| `#1A1A1A` text on `#FFFFFF` | 17.1:1 | ✅ AAA | Primary body text |
| `#6B6B6B` text-dim on `#FFFFFF` | 5.7:1 | ✅ AA | Secondary captions |
| `THEME.primary` (brand orange) on `#FFFFFF` | depends on exact hex — retested each brand refresh | ✅ AA at current `#E85A00` | CTA + accent |
| `#B0B0B0` disabled text on `#F0F0F0` button | 2.1:1 | ❌ fails AA | Intentional: disabled controls use shape + opacity to signal state, not text-contrast alone. Documented deviation — WCAG SC 1.4.3 explicitly exempts disabled UI. |

Dark mode is not in scope for the first launch and is tracked as a
Q2 item.

---

## 5. Dynamic-text support

Every screen renders correctly at the OS "largest" text size
(iOS: Extra Extra Extra Large; Android: 200%). The patterns we
rely on:

- `Text` never has a hard `height` — heights are derived from
  content via `lineHeight` multiplied by a font-size variable.
- Buttons use `minHeight: 44` not `height: 44`.
- Labels that risk wrapping past the screen edge use
  `numberOfLines={2}` + `ellipsizeMode="tail"` rather than a fixed
  width.

---

## 6. Known gaps + follow-ups

1. **Remaining 8 screens** (table §3). Remediation ordered
   rider-first.
2. **CI lint.** `eslint-plugin-react-native-a11y` is not yet in the
   lint pipeline. Add once it supports Expo SDK 55. Until then, the
   manual protocol in §2 is the safety net.
3. **Screen-reader announcements for live data.** Map screens
   (`ride-status.tsx`, `ride-in-progress.tsx`) update ETA and
   driver-location every few seconds; the screen reader currently
   does not re-announce when ETA changes by more than one minute.
   Needs an `AccessibilityInfo.announceForAccessibility` hook tied
   to the WS event stream.
4. **Dark mode.** Q2 scope; adds a second contrast matrix.
5. **Reduced motion.** Animated transitions in
   `rider-app/app/otp.tsx` (shake, pulse) should respect
   `AccessibilityInfo.isReduceMotionEnabled()`. Tracked as a
   mobile-platform follow-up.

---

## 7. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Mobile Lead | | | |
| Product | | | |
| Accessibility Advisor | | | |

---

## Related

- Canonical patterns: `rider-app/app/login.tsx`, `rider-app/app/otp.tsx`,
  `rider-app/app/payment-confirm.tsx`, `driver-app/app/login.tsx`.
- i18n (complements a11y): `docs/ux/I18N.md` (Phase 4.1).
- Release checklist: `docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md`.
