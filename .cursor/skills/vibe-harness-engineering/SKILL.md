## Vibe Harness Engineering (Repo Skill)

This repository follows **Vibe Coding + Harness Engineering**:
fast iteration with strict quality gates.

### Working contract
- Understand current behavior and target outcome.
- Implement the smallest cohesive change.
- Verify (`pytest` minimum + targeted runtime checks).
- Summarize what/why and validation evidence.

### Architecture boundaries
- `app/main.py`: transport/routing only
- `app/db.py` (+ related): schema and queries
- `app/templates/`: view structure
- `app/static/js/`: shared UI primitives + page logic

### Checklists
- For PRs: `docs/templates/pr-description.md`
- For incidents: `docs/templates/incident-postmortem.md`
- For playbook: `docs/harness-playbook.md`

