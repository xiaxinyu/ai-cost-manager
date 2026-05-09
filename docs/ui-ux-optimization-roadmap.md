# UI/UX Optimization Roadmap

Owner: Codex
Reviewer: TBD
QA: TBD
Scope: login-to-reporting experience, cost/token separation, tests
Risk level: medium

## Goals

- Separate cost management and token analysis into distinct user journeys.
- Keep login, import, price management, reports, and token analysis navigable from a consistent shell.
- Add regression coverage for every meaningful route/API touched by the split.
- Keep data contracts backward-compatible and avoid SQLite schema changes unless required by a later feature.

## Requirements

1. Login should remain themed, explicit on failure, and free of remote assets.
2. Dashboard should remain the cost-first landing page.
3. Token analysis should have a dedicated `/tokens` page with project/date/currency filters, summary cards, charts, ratio analysis, detail table, and CSV export.
4. Price management remains the source of model price data used by token estimates.
5. Financial reports remain available at `/reports`; token-specific operational review should use `/tokens`.
6. Import remains isolated at `/import` and must still support selected import plus imported-file verification.
7. All pages must share navigation, login/logout behavior, and local static assets.

## Initial Bug/Task Backlog

- [x] Add dedicated token workspace at `/tokens`.
- [x] Add total token field to project stats API.
- [x] Add route/page access tests for the token workspace.
- [x] Add e2e-style smoke coverage for login -> navigation -> core API flows.
- [ ] Refactor large inline dashboard/report scripts into `app/static/js/pages/`.
- [ ] Convert dashboard to a stricter cost-only view after legacy inline script extraction.
- [ ] Split financial report token widgets into a separate token report variant or link-out flow.
- [ ] Add browser-level Playwright coverage when the dependency is approved for the repo.
- [ ] Add release screenshots to PRs for changed UI flows.

## Release Readiness Notes

- No schema migration is required for the first split.
- Existing token APIs remain backward-compatible; `estimated_total_tokens` is additive on project stats.
- Rollback is limited to removing `/tokens`, its static assets, and the additive stats field.
