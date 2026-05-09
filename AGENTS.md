# AGENTS

This repository follows a **Vibe Coding + Harness Engineering** workflow:
rapid iteration with strict quality gates.

## Project Intent

- Build a practical cost management system for billing CSV ingestion, model pricing management, and reporting.
- Optimize for delivery speed **without** sacrificing structure, testability, or operational clarity.

## Operating Model

1. **Understand** current behavior and target outcome.
2. **Implement** minimal cohesive changes.
3. **Verify** via tests and/or executable checks.
4. **Summarize** decisions, files changed, and validation results.

## Architecture Principles

- Keep concerns separated:
  - `app/main.py`: transport/routing
  - `app/db.py` and related modules: data/query logic
  - `app/templates/`: view structure
  - `app/static/js/`: reusable client logic and page logic
- Reuse shared primitives for cross-cutting concerns:
  - shell/navigation
  - HTTP client
  - toast/error handling

## Strict Quality Requirements

- No hidden errors; failures should be explicit and user understandable.
- No breaking schema/API changes without migration strategy.
- No dead code, TODO leftovers, or temporary hacks in final output.
- Any meaningful change must include verification evidence.

## UI/UX Standards

- Maintain consistent shell layout across pages.
- Keep page scripts modular (`app/static/js/pages/`).
- Prefer progressive enhancement: filters, export, and diagnostics should fail gracefully.

## Test & Verification Policy

- Default validation: run `pytest`.
- For data/schema features, include a quick DB sanity check.
- For UI changes, verify navigation and primary action flows still work.

## Delivery Format

When completing substantial work, report:
- What changed
- Why it changed
- How it was validated

## Mandatory Harness Compliance

- For substantial changes, use the PR checklist in `docs/harness-playbook.md`.
- If a release-impacting change is made, include release readiness notes.
- For incidents/regressions, follow incident workflow and produce a postmortem draft.

## Templates (Required for Team Use)

- PR template: `docs/templates/pr-description.md`
- Incident postmortem template: `docs/templates/incident-postmortem.md`
