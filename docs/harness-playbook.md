# Harness Playbook

This playbook defines the operational workflow for **Vibe Coding + Harness Engineering** in this repository.

## 1) Delivery Lifecycle

1. **Intake**
   - Clarify objective, success criteria, and constraints.
2. **Scope**
   - Identify impacted layers: API, DB, ingest pipeline, templates, page scripts.
3. **Implement**
   - Apply smallest coherent change set.
4. **Verify**
   - Execute tests and targeted runtime checks.
5. **Handoff**
   - Provide concise change rationale and validation evidence.

## 2) Architecture Boundaries

- `app/main.py`: routing and HTTP orchestration only.
- `app/db.py` (+ related modules): schema and query logic.
- `app/templates/`: page structure and minimal wiring.
- `app/static/js/`: shared behavior and page-specific logic.
- `bills/`: source data (billing and pricing snapshots).

## 3) Quality Gates

- Functional: feature works end-to-end for target flow.
- Structural: no unnecessary coupling or copy-paste drift.
- Safety: explicit error paths, no silent failures.
- Verification: tests run and results recorded.

## 4) DB Change Protocol

When schema evolves:

1. Keep migration additive whenever possible.
2. Preserve compatibility for existing DB files.
3. Validate ingestion and reporting flows against updated schema.
4. Document migration impact in final summary.

## 5) Frontend Engineering Protocol

- Shared behaviors (navigation shell, toast, http loading/error handling) belong in `app/static/js/`.
- Page logic should live in `app/static/js/pages/` rather than large inline template scripts.
- UI changes should preserve consistent shell/navigation and fallback states.

## 6) Definition of Done

A change is done only when:

- implementation is complete for requested scope
- verification has run (`pytest` minimum)
- risks/assumptions are disclosed
- user can run and observe the result quickly

## 7) Recommended Command Set

```bash
.venv/bin/python -m pytest
.venv/bin/python -m app.cli ingest --db-path data/cost_mgmt.sqlite3
.venv/bin/python -m app.cli import-prices --db-path data/cost_mgmt.sqlite3 --csv-path bills/price/azure_openai_prices_2026-04-29_eastus_usd.csv
```

## 8) Team Roles Template

Use this template for non-trivial work:

- **Owner**: implements feature/fix and runs baseline verification.
- **Reviewer**: checks architecture, safety, and maintainability.
- **QA/Verifier**: validates critical user flows and data expectations.

Recommended assignment note in task/PR:

```text
Owner: <name>
Reviewer: <name>
QA: <name>
Scope: <short scope>
Risk level: <low|medium|high>
```

## 9) PR Checklist (Harness Standard)

Copy this checklist into PR descriptions:

```text
- [ ] Scope is clear and limited
- [ ] No unrelated file churn
- [ ] API/data contracts are backward-compatible (or explicitly documented)
- [ ] Error handling is explicit (no silent failure)
- [ ] Tests executed (`pytest`)
- [ ] Manual checks completed for changed user flows
- [ ] Release/rollback notes included when needed
```

Template reference:
- `docs/templates/pr-description.md`

## 10) Incident Workflow

When incident happens:

1. Stabilize impact first (containment).
2. Classify severity (Sev-1/2/3).
3. Apply safe mitigation.
4. Verify service and data integrity.
5. Publish root cause + prevention actions.

Post-incident minimum:
- one regression test or guardrail added
- one process/monitoring improvement item recorded

Template reference:
- `docs/templates/incident-postmortem.md`
