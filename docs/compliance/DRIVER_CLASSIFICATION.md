# Spinr — Driver Classification Posture

Phase 3.4 of the production-readiness audit (audit finding C4).

**Version:** 1.0  
**Effective date:** 2026-04-14  
**Owner:** Legal / Head of Operations  
**Review cadence:** Annually, or on any change to provincial TNC
legislation, CRA guidance, or a material change in how drivers
use the platform.

---

## Summary

Spinr treats drivers as **independent contractors (IC)**, not
employees. This document records the factual and legal basis for that
classification, the indicia we maintain, and the compliance steps
required before and after launch.

> **Important:** This document is an internal operational record,
> not legal advice. The IC agreement and any SIN/BN collection must
> be reviewed by qualified employment counsel before driver onboarding
> begins. Provincial rules vary; Saskatchewan and other intended
> provinces each have their own tests.

---

## Legal basis

### Federal (CRA) test

The CRA applies a multi-factor test under the *Income Tax Act* to
determine employment vs. self-employment. Key factors and Spinr's
position:

| Factor | Spinr position | Evidence / control |
|---|---|---|
| Control over work | Driver sets their own hours, can log on/off at will, can decline any ride | No minimum hours; no scheduling obligation |
| Ownership of tools | Driver owns their vehicle; Spinr provides software only | Driver vehicle registration is the tool; Spinr neither owns nor leases it |
| Chance of profit / risk of loss | Driver earns per trip; can multi-app; bears their own fuel and maintenance costs | Earnings directly proportional to hours worked; no guaranteed minimum |
| Integration | Drivers use Spinr as one of potentially many income sources | App does not prohibit multi-apping |
| Exclusivity | None | Driver IC agreement explicitly permits driving for other platforms |

### Provincial (Saskatchewan)

Saskatchewan's *Labour Standards Act* and *The Workers' Compensation
Act, 2013* both use similar multi-factor tests. The IC agreement must
make clear:

- No fixed schedule obligation.
- Driver sets their own route (within the ride's destination).
- Driver is responsible for their own vehicle insurance (commercial
  endorsement or commercial policy).
- Driver pays their own fuel, maintenance, and depreciation.

---

## Indicia maintained

To defend IC classification, the following must be documented in the
driver's onboarding record:

- [ ] **Signed IC Agreement** — dated, versioned, driver's full legal
      name matches government ID. See `docs/legal/DRIVER_IC_AGREEMENT_TEMPLATE.md`.
- [ ] **Driver's licence + abstract** — current; background check
      passed; annual re-check scheduled.
- [ ] **Vehicle registration + inspection** — vehicle owned or leased
      by driver, not Spinr.
- [ ] **Commercial auto insurance certificate** — confirms commercial
      use is endorsed on the driver's policy.
- [ ] **SIN or Business Number (BN)** — for T4A issuance at year-end.
      Stored encrypted (never in plaintext in the DB).

---

## Tax obligations

### T4A (Statement of Contract Payments)

Any driver paid **$500 or more** in a calendar year must receive a
T4A slip by the last day of February of the following year.

Implementation status: **Pending** — `backend/utils/tax_slips.py`
is a placeholder. Pre-launch, the Privacy Officer + Head of Operations
must implement:

1. Year-end job (December 31 → January 31 window) that aggregates
   `rides` total fare per `driver_id` for the calendar year.
2. Generates T4A data (Box 048 — Fees for services).
3. Sends to the CRA via their electronic submission portal (XML/EFILE).
4. Emails or mails a copy to each qualifying driver by Feb 28.

### GST/HST registration

Drivers whose annual gross receipts exceed $30,000 CAD must register
for GST/HST. Spinr does not collect or remit GST on behalf of drivers.
The IC agreement informs drivers of this obligation. A FAQ in the
driver app ("Your taxes as a Spinr driver") must be published before
launch.

### Provincial requirements

- **Quebec:** Drivers operating in Quebec and earning > $30,000/year
  must register for QST in addition to GST.
- **Other provinces:** Track as Spinr expands.

---

## Background check cadence

| Event | Check required |
|---|---|
| Initial onboarding | Criminal record check + MVR (driving abstract) |
| Annual renewal | MVR refresh; criminal check if MVR shows new convictions |
| Incident trigger | Immediate criminal check + ride suspension pending result |

Background check provider: *[To be contracted — launch blocker]*.

---

## Driver agreement versioning

The IC agreement is versioned (v1, v2, …). Any material change
(earnings terms, territory, insurance requirements, exclusivity clause)
requires re-acceptance from all active drivers before the effective
date. The `drivers.ic_agreement_version` column (to be added in a
follow-up migration) tracks which version each driver accepted.

---

## Open items before launch

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Employment counsel review of IC agreement template | Legal | Pending |
| 2 | Background-check provider contracted | Operations | Pending |
| 3 | SIN/BN collection encrypted in `drivers` table (migration) | Backend | Pending |
| 4 | T4A generation flow (`utils/tax_slips.py`) | Backend | Pending |
| 5 | "Your taxes as a Spinr driver" FAQ in driver app | Product | Pending |
| 6 | `drivers.ic_agreement_version` column + re-acceptance gate | Backend | Pending |

---

## Related

- IC agreement template: `docs/legal/DRIVER_IC_AGREEMENT_TEMPLATE.md`
- PIPEDA posture: `docs/compliance/PIPEDA.md`
- Data retention (background check images): `docs/compliance/DATA_RETENTION.md`
- Driver onboarding routes: `backend/routes/drivers.py`
