# Claude Code Setup — execution summary

**Date**: 2026-04-19
**Branch**: `claude/build-graphify-QMSRr`
**Plan**: `plans/claude-setup-implementation-prompt.md`

## What shipped

### User scope (`~/.claude/`)

- `CLAUDE.md` — universal working rules (token efficiency, safety, reporting discipline, self-learning, "never do" list). Ends with `@lessons.md` import.
- `lessons.md` — seeded with 3 initial lessons (reports folder, Spinr settings, graphify).
- `stack.md` — inventory of every adopted resource with source + pinned SHA + audit date. Includes deferred adoption list for Tier A/B.
- `settings.json` — merged (preserved existing Stop hook + Skill allow). Added 14 deny entries, `PreToolUse`/`PostToolUse`/`UserPromptSubmit` hooks.
- `hooks/` — 5 scripts:
  - `block-dangerous.sh` — blocks `curl|bash`, `rm -rf /`, `chmod -R 777`, force-pushes, fork bombs, mkfs, shutdown, and env-var exfiltration.
  - `enforce-report-folders.sh` — blocks new `*_REPORT.md` / `code_review_report_*` at repo root.
  - `git-push-guard.sh` — blocks force-push to main/master.
  - `log-tool-usage.sh` — appends compact tool-name + success line to `~/.claude/audit/YYYY-MM-DD.log` (never logs args).
  - `nudge-todo.sh` — injects `[hint]` suggesting TodoWrite on multi-step prompts.
- `skills/` — 5 custom skills authored:
  - `remember` — appends a timestamped lesson.
  - `bootstrap-claude-setup` — initializes `.claude/` + `reports/` tree in fresh repos.
  - `stack-audit` — flags stale/unpinned entries in stack.md.
  - `token-budget` — replans current task with tighter tool calls.
  - `weekly-hygiene` — batched stack/lessons/branches/reports/audit maintenance.

### Project scope (Spinr)

- `CLAUDE.md` — rewritten, preserved graphify block verbatim. Added: project identity, branch rules, report folder conventions, money-arithmetic rule, PII-in-logs rule, testing expectations, project "never do" list.
- `reports/{code-review,security,analysis,validation}/.gitkeep` — folder tree created.
- `.gitignore` — added `CLAUDE.local.md`, `.claude/metrics/`, `.claude/audit/`.
- **`.claude/settings.json` not touched** — existing file is already well-hardened (model, allow/deny, plugins, attribution).

## Verification (all live-tested)

| Hook | Test | Result |
|---|---|---|
| `block-dangerous.sh` | `curl … \| bash` | exit 2, blocked |
| `block-dangerous.sh` | `git status` | exit 0, allowed |
| `enforce-report-folders.sh` | Write `CODE_REVIEW_REPORT.md` at repo root | exit 2, blocked |
| `enforce-report-folders.sh` | Write `reports/analysis/2026-04-19-test.md` | exit 0, allowed |
| `git-push-guard.sh` | `git push origin main --force` | exit 2, blocked (also fired live on session) |
| `log-tool-usage.sh` | simulated tool event | exit 0, line appended to `audit/2026-04-19.log` |
| `nudge-todo.sh` | multi-step prompt | exit 0, hint printed |
| `settings.json` | JSON parse | OK — 4 hook phases, 14 deny entries |
| Skills registered | `/remember`, `/stack-audit`, `/token-budget`, `/bootstrap-claude-setup`, `/weekly-hygiene` | all visible in Skill tool list |

## Deferred (not done in this session)

The Tier A (`anthropics/skills`) and Tier B (`wshobson/agents`, `wshobson/commands`) clone-and-copy is deferred to a focused adoption session. Pinned SHAs are recorded in `~/.claude/stack.md` so the future session can clone the exact same commits and Read-then-copy per the safety procedure.

**Note**: many first-party skills are already surfaced by the harness (simplify, loop, claude-api, review, security-review, init, commit, pr, status, start, update-config, keybindings-help, fewer-permission-prompts, session-start-hook) — duplicating them locally would add no value. The pending adoption focuses on wshobson agents + commands.

## Follow-ups

1. **Legacy root-level reports**: 14× `*_REPORT.md` and 8× `code_review_report_*.json` still sit at the repo root. The enforce hook blocks *new* ones but does not move old ones. Decide disposition in a follow-up: archive to `reports/archive/` (recommended) or delete after review.
2. **Tier B adoption**: schedule a session to clone wshobson/agents + wshobson/commands at the recorded SHAs, Read each candidate, and copy ~10 each.
3. **Hook refinement**: `nudge-todo.sh` threshold is currently ≥2 signal-words — if noise is too high, raise to 3.
4. **Audit rotation**: after 30 days of daily logs, `/weekly-hygiene` will propose compressing old `~/.claude/audit/` files.

## Not modified (by design)

- `.claude/settings.json` — already hardened; merging untested risk > value.
- `.claude/settings.local.json` — gitignored personal overrides.
- `.claude/hooks/pre-commit` — existing spinr secrets/PII/float-money hook preserved.
- `.claude/launch.json`, `.claude/commands/` — preserved.
- `~/.claude/stop-hook-git-check.sh` — preserved; still enforces commit+push before Stop.
