# Security Policy

Spinr is a Canadian ride-sharing platform operating in Saskatchewan. We take the security of our platform and the safety of our riders, drivers, and partners seriously. We welcome responsible security research and appreciate the efforts of the security community in helping us maintain a trustworthy service.

---

## Supported Versions

Only the current production release receives security patches. We do not backport fixes to older versions.

| Version | Supported          |
|---------|--------------------|
| 1.x     | Yes                |
| < 1.0   | No                 |

---

## Reporting a Vulnerability

If you believe you have discovered a security vulnerability in Spinr, please report it to us privately so we can address it before any public disclosure.

**Contact:** vikas@ngitservices.com

Please include the following in your report:

- A clear description of the vulnerability and its potential impact
- The affected component (e.g., backend API, rider app, admin dashboard)
- Step-by-step reproduction instructions
- Any supporting evidence such as proof-of-concept code, screenshots, or HTTP request/response captures
- Your suggested severity rating, if you have one

**Do not** open a public GitHub issue, post to social media, or disclose the vulnerability to any third party before we have had the opportunity to investigate and remediate it.

### Response SLA

| Milestone                             | Target Timeframe          |
|---------------------------------------|---------------------------|
| Acknowledgement of receipt            | Within 48 hours           |
| Initial triage and severity rating    | Within 7 days             |
| Patch or mitigation for Critical/High | Within 14 days of triage  |
| Patch or mitigation for Medium/Low    | Within 90 days of triage  |

We will keep you informed throughout the process and notify you when a fix has been deployed. If you do not receive an acknowledgement within 48 hours, please follow up to ensure your report was received.

---

## Safe Harbour

Spinr supports responsible security research. We consider security research conducted in good faith and within the scope defined below to be authorised conduct. We will not initiate or recommend legal action against researchers who:

- Report vulnerabilities promptly and in good faith through our stated disclosure channel
- Avoid accessing, modifying, or deleting data that does not belong to them
- Do not degrade the availability or performance of Spinr services
- Do not exploit a vulnerability beyond what is necessary to demonstrate its existence
- Do not use findings to extort or harm Spinr, its users, or its partners

We ask that you use test accounts and synthetic data wherever possible. If you inadvertently access real user data, stop immediately and report it along with your finding.

This safe harbour applies only to research conducted within the scope defined below and does not extend to activities that are explicitly listed as out of scope.

---

## Scope

### In Scope

The following assets and systems are within scope for security research:

| Asset                          | Description                                                        |
|--------------------------------|--------------------------------------------------------------------|
| Backend API                    | FastAPI application endpoints and business logic                   |
| Rider mobile app               | React Native / Expo iOS and Android application                    |
| Driver mobile app              | React Native / Expo iOS and Android application                    |
| Admin dashboard                | Next.js web application for internal operations                    |
| Supabase Row Level Security    | RLS policies and database access control configurations            |
| Stripe webhook handling        | Webhook signature verification and payment event processing logic  |
| Authentication and authorisation | JWT handling, session management, role-based access control      |
| API input validation           | Injection, deserialization, and boundary validation issues         |

### Out of Scope

The following are explicitly out of scope. Please do not submit reports for these items, as they will be closed without action.

| Asset / Area                              | Reason                                              |
|-------------------------------------------|-----------------------------------------------------|
| Stripe infrastructure                     | Managed by Stripe; report via their disclosure programme |
| Supabase platform infrastructure          | Managed by Supabase; report directly to them        |
| Firebase infrastructure (if applicable)  | Managed by Google; report via their VRP             |
| Third-party CDN and DNS providers         | Not operated by Spinr                               |
| Social engineering attacks                | Outside technical scope                             |
| Physical attacks against devices or staff | Outside technical scope                             |

---

## Out-of-Scope Behaviour

The following testing activities are prohibited regardless of target:

- Distributed denial-of-service (DDoS) or volumetric flooding of any kind
- Brute-force or credential-stuffing attacks against non-authentication endpoints
- Automated scanning that generates excessive load or degrades service availability
- Submission of spam, unsolicited messages, or bulk test transactions through production systems
- Testing against accounts or data belonging to real users without their explicit consent
- Any activity that violates applicable Canadian federal or provincial law

Reports that arise from these activities will not be eligible for acknowledgement or recognition.

---

## Disclosure Timeline

Spinr follows a coordinated disclosure model based on the industry-standard 90-day embargo.

1. **Day 0** — Researcher submits report to vikas@ngitservices.com.
2. **Day 1–2** — Spinr acknowledges receipt.
3. **Day 1–7** — Spinr triages, assigns severity, and agrees on a remediation timeline with the researcher.
4. **Day 1–14** — Critical and High severity vulnerabilities are patched and deployed to production.
5. **Day 90** — Embargo expires. Researcher may publish their findings publicly.

If we require more than 90 days to remediate due to complexity or third-party dependencies, we will request an extension and explain the reason. We ask that researchers accommodate reasonable extension requests in good faith.

**Early disclosure:** If a vulnerability is being actively exploited in the wild, we may release a public advisory ahead of the 90-day window. We will coordinate with the researcher before doing so wherever possible.

### CVE Assignment

For vulnerabilities that meet the criteria for a Common Vulnerabilities and Exposures (CVE) identifier, Spinr will request a CVE from a recognised CVE Numbering Authority (CNA) or work with the researcher to do so. The CVE will be published in the public advisory once the embargo period ends or a fix is deployed, whichever comes first.

---

## Hall of Fame

We are grateful to the researchers who help keep Spinr and its users safe. Researchers who responsibly disclose valid security vulnerabilities will be acknowledged here, with their permission.

| Researcher | Vulnerability Summary | Severity | Date |
|------------|-----------------------|----------|------|
| —          | —                     | —        | —    |

If you would prefer not to be listed, simply let us know in your report.

---

## PGP Key

A PGP public key for encrypting sensitive vulnerability reports will be published to this section prior to the Spinr public launch. Until then, please use standard email and avoid including highly sensitive details (such as working exploits) in unencrypted messages. You may reference a summary in your initial report and share full details once we have established a secure communication channel.

---

*Last updated: April 2026*
