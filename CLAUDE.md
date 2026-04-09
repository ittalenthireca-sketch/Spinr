# CLAUDE.md — spinr Platform Intelligence File
# Version: 1.0 | Last updated: 2026-04-07

---

## What spinr Is

spinr is a Canadian ride-sharing platform (TNC) competing in the post-Lyft-exit
Canadian market. Connects riders and drivers via mobile apps and web platform.
Safety, compliance, and driver earnings fairness are core differentiators.

Vision: Fortune 100-grade ride share platform built for the Canadian market.
Stage: Active development. Architecture exists. Building toward MVP pilot launch.
GitHub: https://github.com/srikumarimuddana-lab/spinr

---

## Actual Technology Stack (verified from codebase)

### Backend
- Language:   Python 3.11
- Framework:  FastAPI (or similar — check backend/requirements.txt)
- Database:   Supabase (PostgreSQL + PostGIS)
- Deploy:     Render (primary), Fly.io (fallback)
- Auth:       Supabase Auth + custom JWT (SECRET_KEY env var)

### Mobile Apps
- Framework:  Expo (React Native) — EAS Build for iOS/Android
- Rider app:  spinr/rider-app/ (npm/Expo)
- Driver app: spinr/driver-app/ (npm/Expo)

### Web Apps
- Frontend:   spinr/frontend/ (Next.js, deployed to Vercel)
- Admin:      spinr/admin-dashboard/ (Next.js, deployed to Vercel)

### Infrastructure
- CI/CD:      GitHub Actions (.github/workflows/ci.yml — DO NOT MODIFY)
- Security:   Trivy vulnerability scanning (already in ci.yml)
- Coverage:   Codecov (already in ci.yml)
- Mobile:     EAS (Expo Application Services)

---

## Repository Structure ENDOFFILE
