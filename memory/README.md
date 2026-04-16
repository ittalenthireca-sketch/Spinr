# memory/

Reserved for long-lived, cross-session state for the LLM agents defined
in `agents/`. Empty today except for `.gitkeep`.

## Intended use

The agents in `agents/` (orchestrator, code_reviewer, backend_agent,
frontend_agent, tester, deployer, documenter, security_agent) need a
place to persist:

- Architectural decisions and their rationale
- Patterns observed across the codebase
- Technical-debt findings and status
- Cross-session context that shouldn't live in a single chat transcript

## What already exists elsewhere

The `KnowledgeBaseAgent` (`agents/knowledge_base.py`) is the canonical
owner of persistent agent knowledge. It currently writes to:

- `agents/knowledge/tasks/*.json` — per-task records
- `agents/knowledge/reviews/*.json` — per-review records

Project-level narrative memory is scattered across root-level reports:

- `ANALYSIS_REPORT.md`, `ARCHITECTURE.md`, `CODE_ANALYSIS_REPORT.md`,
  `CODE_REVIEW_REPORT.md`, `GAP_ANALYSIS.md`, `READINESS_REPORT.md`,
  `TODO.md`
- `code_review_report_*.json` snapshots
- `docs/audit/` production-readiness audits

## Suggested layout when populated

```
memory/
  decisions/       # ADR-style records
  patterns/        # recurring code patterns + anti-patterns
  debt/            # tracked technical debt items
  sessions/        # compressed session summaries
  index.json       # searchable manifest
  README.md
```

Either migrate `agents/knowledge/` into this folder, or keep
`agents/knowledge/` as the runtime store and use `memory/` for curated,
human-reviewed long-term records. Pick one before populating.
