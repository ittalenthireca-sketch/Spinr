# Claude Code Durable Setup — Implementation Prompt

> **Use**: paste this as the next prompt to Claude Code (in this repo) to execute the full setup end-to-end. The prompt is self-contained; it does not depend on prior conversation state.

---

## Role

You are acting as a senior Claude Code platform engineer. Your job is to build a durable, safe, community-backed Claude Code configuration across **user scope** (`~/.claude/`) and **project scope** (this Spinr repo's `.claude/` + `CLAUDE.md`), so that future sessions — in this repo and any other — start with strong defaults for task decomposition, token efficiency, safety, and reporting discipline.

## Prime directives

1. **Decisions already made** (do not re-ask; proceed):
   - Adoption breadth: Tier A (first-party) + Tier B cherry-pick (~10 agents, ~10 commands) from `wshobson/agents` and `wshobson/commands`.
   - Hooks: **enforced** — PreToolUse blocks, PostToolUse logs.
   - Storage: inline at `~/.claude/`; dotfiles-repo promotion deferred.
   - Pilot: apply to Spinr project simultaneously on branch `claude/build-graphify-QMSRr`.
2. **Safety first.** Never install anything unpinned. Every adopted external file is copied at a specific commit SHA and recorded in `~/.claude/stack.md`.
3. **Use TodoWrite** to track the 9 phases below — one in-progress at a time, mark complete as you go.
4. **Prefer community-vetted over bespoke.** Only write custom skills where the community gap is clear (the 5 listed).
5. **Pause and ask** with AskUserQuestion only if a decision surfaces that was not pre-decided above. Otherwise proceed.

## Safety gates (hard rules — do not violate)

- Never run `curl … | bash` or `npx <unpinned>`. Use `git clone` to a temp dir, `git checkout <sha>`, then copy specific files you have read.
- Never install any resource you have not `Read` in full first (every `SKILL.md`, every shell script, every agent prompt, every hook command).
- Never write secrets. Never reference `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, or `GITHUB_TOKEN` in any skill/hook/agent.
- Never set `permissions.defaultMode: "bypassPermissions"` in any file.
- Skip any file that contains: base64 blobs in SKILL.md, zero-width characters, env-var exfiltration (`env`, `printenv`, `process.env`, `os.environ` piped to network), or hooks with `matcher: "*"` + no `if:` filter.
- If a repo's license forbids redistribution (e.g., CC BY-NC-ND), treat it as reference only — do not copy files from it.

## Target architecture

```
~/.claude/
├── CLAUDE.md                      # universal working rules + @lessons.md import
├── settings.json                  # deny-list, env, model, hooks, permissions
├── stack.md                       # inventory of every adopted resource w/ pinned SHA
├── lessons.md                     # self-learning log, appended by /remember
├── agents/                        # cherry-picked subagents
├── skills/                        # first-party + 5 custom skills
├── commands/                      # cherry-picked slash commands
├── hooks/                         # shell scripts
├── metrics/                       # PostToolUse usage log (gitignored)
└── audit/                         # YYYY-MM-DD.log per day

<repo>/
├── CLAUDE.md                      # project context + conventions (committed)
├── CLAUDE.local.md                # personal per-project notes (gitignored)
├── .claude/
│   ├── settings.json              # team policy (committed)
│   ├── settings.local.json        # personal overrides (gitignored)
│   ├── agents/                    # project-specific, if any
│   └── commands/                  # project-specific, if any
├── reports/
│   ├── code-review/
│   ├── security/
│   ├── analysis/
│   └── validation/
├── plans/                         # already exists
└── docs/                          # already exists
```

## Phase 0 — Pre-flight (5 min)

1. Confirm current branch is `claude/build-graphify-QMSRr`; if not, switch.
2. Read this file (`plans/claude-setup-implementation-prompt.md`) in full.
3. Read the project root `CLAUDE.md`.
4. Create `~/.claude/stack.md` with header:
   ```
   # Claude Code Stack Inventory
   | Resource | Source URL | Pinned SHA | Scope | Adopted | Last audited | Notes |
   |---|---|---|---|---|---|---|
   ```
5. Create `~/.claude/lessons.md` with header `# Lessons Learned\n\n_Appended by /remember. Review weekly._\n`.

## Phase 1 — User-scope CLAUDE.md (universal rules)

Write `~/.claude/CLAUDE.md` with sections:

- **Working style**: break work into small tasks; use TodoWrite for >2 steps; delegate broad research to Explore subagent to protect main context.
- **Token optimization**: Grep/Glob before Read; `head_limit` on Grep; line-ranged Reads; never dump whole large files; summarize then discard raw tool output.
- **Role discipline**: announce role shifts briefly when switching (e.g., "as reviewer:", "as architect:").
- **Safety**: never force-push; always confirm before destructive ops; respect deny-list in settings.json.
- **Reporting**: every report goes to `<repo>/reports/<category>/YYYY-MM-DD-<slug>.md` — never the repo root.
- **Self-learning**: when I discover a recurring gotcha, offer to append to `lessons.md` via `/remember`.
- **API resilience**: on 429, back off; on context warnings, spawn Explore subagent; on tool validation errors, re-read the schema.
- Final line: `@lessons.md` to import accumulated lessons.

## Phase 2 — User-scope settings.json

Write `~/.claude/settings.json`:

- `model`: leave unset (respect per-session choice) OR set a sensible default.
- `permissions.defaultMode`: `"default"` (never `bypassPermissions`).
- `permissions.deny` (the hardening list):
  - `Bash(curl:*|*bash*)`, `Bash(wget:*|*bash*)`
  - `Bash(rm -rf:*)`, `Bash(rm -rf /*)`
  - `Bash(git push --force:*)`, `Bash(git push -f:*)`
  - `Bash(git reset --hard:*)` (wildcarded conservative)
  - `Bash(:(*ANTHROPIC_BASE_URL*))`, `Bash(:(*ANTHROPIC_AUTH_TOKEN*))`
  - `Bash(chmod -R 777:*)`
- `permissions.ask`: all `mcp__*__*` tools you don't explicitly allow.
- `hooks`:
  - `PreToolUse` matcher on `Bash`: call `~/.claude/hooks/block-dangerous.sh` — exit non-zero to block.
  - `PreToolUse` matcher on `Write|Edit`: call `~/.claude/hooks/enforce-report-folders.sh` — block writes of `*_REPORT.md`/`code_review_report_*` at any repo root; suggest correct folder.
  - `PostToolUse` matcher `*`: call `~/.claude/hooks/log-tool-usage.sh` → append to `~/.claude/audit/$(date +%F).log`.
  - `PreToolUse` matcher on `Bash(git push:*)`: call `~/.claude/hooks/git-push-guard.sh` — warn if pushing to `main`/`master`; confirm branch matches any `CLAUDE.md` "develop on branch X" rule.
  - `UserPromptSubmit`: `~/.claude/hooks/nudge-todo.sh` — if prompt contains multiple `and`/`then`/numbered items, inject a reminder to use TodoWrite.

Each hook script must:
- Start with `#!/usr/bin/env bash`, `set -euo pipefail`.
- Read tool input from stdin JSON (Claude Code hook contract).
- Exit 0 for "allow", non-zero with stderr message for "block".
- Log nothing sensitive — never echo env or arguments containing tokens.

## Phase 3 — Tier A install (first-party skills)

1. `git clone https://github.com/anthropics/skills /tmp/anthropics-skills` — record HEAD SHA.
2. `Read` every `SKILL.md` in skills you plan to import. Candidates: `simplify`, `security-review`, `review`, `commit`, `pr`, `init`, `loop`, `batch`, `claude-api`, `debug`.
3. For each approved skill: `cp -r /tmp/anthropics-skills/<skill>/ ~/.claude/skills/<skill>/` — record in `stack.md` with the SHA.
4. Skip skills with restrictive licenses (docx/pdf/pptx/xlsx are source-available, not OSS). Note this in stack.md.

## Phase 4 — Tier B cherry-pick (agents + commands)

1. `git clone https://github.com/wshobson/agents /tmp/wshobson-agents` — record HEAD SHA.
2. `Read` each candidate. Pick these 10 (adjust if names differ):
   - `code-reviewer`, `security-auditor`, `architect`, `test-writer`, `debugger`,
   - `devops-engineer`, `performance-analyst`, `refactorer`, `api-designer`, `documentation-writer`.
3. For each: verify no env exfiltration, no network calls, no broad matchers; `cp` into `~/.claude/agents/`; record in `stack.md`.
4. `git clone https://github.com/wshobson/commands /tmp/wshobson-commands` — record HEAD SHA.
5. Cherry-pick ~10 broadly useful commands (e.g., `/review-pr`, `/security-audit`, `/architecture-review`, `/refactor-plan`, `/add-tests`, `/performance-check`, `/api-design`, `/debug-issue`, `/tech-debt`, `/release-notes`). Verify each before copying.

## Phase 5 — Custom skills (5 only)

Author these in `~/.claude/skills/`:

1. **`remember`** — `/remember <lesson>`: appends a timestamped entry to `~/.claude/lessons.md`. One-liner skill.
2. **`bootstrap-claude-setup`** — initializes a new project: creates `.claude/`, `reports/*`, `CLAUDE.local.md` template, `.gitignore` entries for `CLAUDE.local.md`/`settings.local.json`/`metrics/`/`audit/`.
3. **`stack-audit`** — prints `~/.claude/stack.md`; runs `git log` on cached clones; flags any resource adopted >90 days ago or missing a pinned SHA.
4. **`token-budget`** — asks Claude to re-plan the current task with fewer/tighter tool calls; lists which reads/searches to drop.
5. **`weekly-hygiene`** — audits: stale branches, `reports/` older than 30 days, `lessons.md` entries ready for promotion to CLAUDE.md, any unpinned resources in stack.md.

Each skill must have valid YAML frontmatter (`name`, `description`, optional `allowed-tools`). Keep skill bodies under 60 lines.

## Phase 6 — Project-scope setup (Spinr)

1. Update existing `/home/user/Spinr/CLAUDE.md`: **preserve** the graphify block; add sections:
   - Project identity (rideshare, Expo + FastAPI + Supabase).
   - Development branch rule: `claude/build-graphify-QMSRr`.
   - Report folder conventions (point at `reports/<category>/`).
   - Stop creating `*_REPORT.md` / `code_review_report_*.json` at repo root.
2. Create `/home/user/Spinr/.claude/settings.json` (committed): light — just project-specific deny entries and any project-specific MCP servers.
3. Create `/home/user/Spinr/.claude/settings.local.json` (gitignored): personal overrides, experimental hooks.
4. Create `/home/user/Spinr/CLAUDE.local.md` (gitignored) with a stub for personal notes.
5. Create folders: `reports/code-review/`, `reports/security/`, `reports/analysis/`, `reports/validation/`. Add a `.gitkeep` in each.
6. Update `.gitignore`: add `CLAUDE.local.md`, `.claude/settings.local.json`, `.claude/metrics/`, `.claude/audit/`.
7. **Do not move or delete** the existing root-level `*_REPORT.md` / `code_review_report_*.json` files — just stop creating new ones there. A follow-up cleanup can decide disposition.

## Phase 7 — Verification

1. `claude --version` and confirm settings load without errors.
2. Trigger a safe pre-tool hook (e.g., attempt `rm -rf /tmp/__claude-test-xyz` in a Bash tool call) and confirm deny fires.
3. Attempt a `Write` to `NEW_REPORT.md` at repo root and confirm the enforce-report-folders hook blocks and suggests `reports/analysis/…`.
4. Run `/stack-audit` — should list every adopted resource with its pinned SHA.
5. Run `/bootstrap-claude-setup` in a scratch `/tmp/demo-project` and confirm it produces a compliant layout.
6. Append a dummy lesson via `/remember "Test entry"`; confirm it appears in `~/.claude/lessons.md`.

## Phase 8 — Commit & document

1. Only project-scope files are committed. User-scope (`~/.claude/`) is not touched by git here.
2. Stage only: `CLAUDE.md` (updated), `.claude/settings.json`, `.gitignore` (updated), `reports/*/​.gitkeep`, `plans/claude-setup-implementation-prompt.md` (this file).
3. Exclude: anything in `.claude/settings.local.json`, `CLAUDE.local.md`, `reports/` content.
4. Commit on branch `claude/build-graphify-QMSRr` with message:
   ```
   chore(claude-code): adopt durable user+project setup

   - Add project CLAUDE.md conventions and .claude/settings.json
   - Introduce reports/{category}/ folder discipline
   - Document implementation prompt for user-scope setup
   ```
5. Push with `git push -u origin claude/build-graphify-QMSRr` (retry up to 4× with exponential backoff on network errors only).
6. Do NOT open a PR unless explicitly requested.

## Phase 9 — Report

Produce `reports/analysis/claude-setup-summary.md` with:
- Resources adopted (copy from `stack.md`).
- Hooks installed + what each blocks/logs.
- Verification results (what passed, what failed).
- Follow-ups: disposition of the 14 `*_REPORT.md` and 8 `code_review_report_*.json` files at repo root (recommend: move to `reports/archive/` in a future session, after user review).

## Done criteria

- [ ] `~/.claude/CLAUDE.md`, `settings.json`, `stack.md`, `lessons.md` exist and parse.
- [ ] Tier A + Tier B resources copied, each with SHA in `stack.md`.
- [ ] 5 custom skills present and valid.
- [ ] 5 hooks installed; 2 verifiably firing (deny + report-folders).
- [ ] Project `.claude/` present; `.gitignore` updated; `reports/` tree created.
- [ ] `CLAUDE.md` graphify rules preserved.
- [ ] One commit on `claude/build-graphify-QMSRr`; pushed; no PR.
- [ ] Summary report in `reports/analysis/claude-setup-summary.md`.

## If you get blocked

- Any external repo clone fails → report it, skip that resource, continue.
- A candidate agent/skill/hook fails safety review → skip it, note the reason in `stack.md` under "Rejected".
- A new decision surfaces that was not pre-decided → pause and AskUserQuestion.
- Do not invent CVE references or safety claims; if uncertain, say so.
