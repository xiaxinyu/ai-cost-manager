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
| **CostUSD** | Daily invoice actual from billing CSV (`UsageDate` total) |
| **Meter (inp+out)** | Token meter rows matched from billing (`MeterCategory` inp/opt) |
| **Platform (other)** | Remainder of CostUSD — deployment, hosting, non-token lines |
| **Tariff reference** | Imported tokens × list USD/1M — benchmark only, not billed |
