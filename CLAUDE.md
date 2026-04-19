# Spinr — project-scope working rules

_Layered on top of `~/.claude/CLAUDE.md` universal rules. Personal per-project notes go in `CLAUDE.local.md` (gitignored)._

## Project identity

Spinr is a rideshare platform. Stack:
- **Backend**: FastAPI (Python) — `backend/`
- **Mobile**: Expo + React Native — `rider-app/`, `driver-app/`, `frontend/`
- **Admin**: React dashboard — `admin-dashboard/`
- **Data**: Supabase (Postgres + auth)
- **Shared types/utilities**: `shared/`

## Branch rules

- **Never** commit or push directly to `main`, `master`, or `develop`. The project pre-commit hook enforces this.
- When this file pins a development branch (e.g., via Claude Code CLI system prompt), all work in the session goes there.
- Feature branches: `feature/<scope>`, fixes: `fix/<scope>`, sprint work: `sprint<N>/<scope>`.
- Force-push is denied in `.claude/settings.json`.

## Report folder conventions

Every analysis, review, audit, or validation output goes under `reports/`:

| Category | Folder |
|---|---|
| Code reviews | `reports/code-review/` |
| Security audits | `reports/security/` |
| Architecture / perf / general | `reports/analysis/` |
| Test / CI validation | `reports/validation/` |

Filename: `YYYY-MM-DD-<slug>.md`.

**Do not** create `*_REPORT.md`, `code_review_report_*.json`, or similar at the repo root. The `~/.claude/hooks/enforce-report-folders.sh` hook will block new ones. Existing root-level reports from before 2026-04-19 remain in place pending a separate cleanup pass.

## Money arithmetic

Fares, prices, earnings, and payouts must use `Decimal` (Python) or integer cents — never float. The project pre-commit hook warns on float-looking money arithmetic; treat that warning as blocking.

## PII in logs

Never log coordinates, phone numbers, or full names. The pre-commit hook blocks `print(lat, lng)` / `console.log(phoneNumber)` patterns.

## Testing before "done"

- Backend changes: `cd backend && python -m pytest` for affected paths.
- Frontend changes: start the dev server (see `.claude/launch.json`) and click through the flow. Type-checks and tests verify code correctness, not feature correctness.
- Payment / ride-state changes: walk through `reports/validation/` runbooks where they exist before reporting done.

## Never do (project-specific)

- Never modify CI workflows (`.github/workflows/ci.yml`, `deploy-backend.yml`, `eas-build.yml`, `test-env.yml`, `apply-supabase-schema.yml`) — denied in settings.
- Never write `.env*`, `*.pem`, `*.key`, or `.claude/settings.local.json`.
- Never commit `graphify-out/` (it's generated; in `.gitignore`).
- Never bypass the pre-commit hook with `--no-verify` without explicit user instruction per-commit.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
