# Forecasting utilities

Client-side helpers in `app/static/js/forecasting.js` — used for **token ratio** charts and related analytics. **Cost/token 7-day forecast charts are not shown in the UI** (removed — poor signal for billing).

## Active uses

- **Tokens** — output/input ratio Y-axis bounds (`ratioSuggestedBounds`, `ratioYTickDecimals`)
- **Reports** — same ratio chart helpers on token sections

## Core API

- `forecastNextDaysDOW(points, key, lastDateStr, { windowDays, horizonDays })` — linear trend + day-of-week correction (still available for scripts; not wired to dashboard charts)
- `forecastQuality(points, key, { windowDays })` — High/Medium/Low heuristic
- `dailyTokenRatio`, `ratioStats`, `ratioSuggestedBounds`, `ratioYTickDecimals`

## Daily spend chart semantics

Billing legend for Cost / Reports is driven by `AppCostSemantics.billingKey()` in `cost-semantics.js`:

| Pill | Billing meaning |
|------|-----------------|
| **Meter** | By model — **gpt-5.x** model rows, **Meter** column (Input + Output USD) |
| **Others · Platform** | By model — **Others · …** rows (Defender, Bing, Foundry unmatched) |
| **Tariff ref** | By model — **Tariff** column (Model Prices list USD/1M; not billed) |
