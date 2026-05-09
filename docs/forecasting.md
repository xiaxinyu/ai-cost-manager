# Forecasting (Cost & Estimated Tokens)

This project provides **short-horizon, lightweight forecasts** for:

- **CostUSD** (daily)
- **Estimated input / output / total tokens** (daily)

The forecasts are intended for **dashboard guidance** (7-day outlook), not financial-grade planning. The emphasis is:

- deterministic output
- explainable behavior
- no external ML dependencies
- safe handling of missing/dirty data

## Where the forecast is computed

Forecasts are computed **client-side** (no server-side ML pipeline today).

### Code locations (source of truth)

- **Shared forecast utility**
  - `app/static/js/forecasting.js`
    - `window.AppForecasting.forecastNextDaysDOW(points, key, lastDateStr, { windowDays=28, horizonDays=7 })`
- **Dashboard (`/`) wiring**
  - `app/templates/index.html`
    - `loadProject()` builds daily timeseries inputs, calls `forecastNextDaysDOW(...)`, then renders:
      - `timeseriesChartActual` (actual only)
      - `timeseriesChartCostForecast` (forecast only, with last actual point as the dashed start)
      - `timeseriesChartTokenForecast` (forecast only, with last actual point as the dashed start)
- **Reports (`/reports`) wiring**
  - `app/templates/reports.html`
    - `renderForecastReports(report)` calls `forecastNextDaysDOW(...)` and renders:
      - `costForecastChart`
      - `tokenForecastChart`

Cost and token series are forecast **independently** from their own history.

### Visualization conventions (professional consistency)

- **Actual series**: solid line
- **Forecast series**: dashed line
- **Continuity rule**: forecast dashed line should start at the **last actual point** (same value) to avoid a visible break at the boundary.
- **Forecast horizon marker** (Reports): when a chart mixes actual + forecast on one canvas, visually separate the forecast region:
  - shade the horizon background starting at the last actual index
  - draw a subtle boundary line and label (e.g. “Forecast horizon”)
- **Forecast horizon marker** (Dashboard forecast canvases): apply the same visual separation on the forecast-only charts, starting at the last-actual anchor point used for continuity.
- **Assumptions disclosure**: forecast sections should include a small, collapsible “Forecast assumptions” block so readers can audit:
  - window size and horizon
  - linear trend + day-of-week correction
  - integer rounding and non-negative clamp
  - continuity rule at the actual→forecast boundary
- **Global style consistency**: use a single shared color mapping across pages:
  - Cost: teal (`#5eead4`)
  - Input tokens: blue (`#60a5fa`)
  - Output tokens: purple (`#a78bfa`)
  - Total tokens: orange (`#f59e0b`)

## Input / output contract

### Inputs

- **`points`**: array of objects that include:
  - `date`: `YYYY-MM-DD`
  - `key`: numeric (e.g. `cost_usd`, `estimated_input_tokens`, ...)
- **`key`**: the metric to forecast within each point
- **`lastDateStr`**: the last observed date (used to generate the next 7 dates)
- **`windowDays`**: maximum number of most-recent samples used for fitting (default 28; clamped to `[2, 365]`)
- **`horizonDays`**: number of days to forecast (default 7; clamped to `[1, 30]`)

### Output

An array of `{ date, value }` for the next \(H\) days:

- `date`: `YYYY-MM-DD`
- `value`: **integer** (rounded) and **non-negative** (clamped at 0)

If inputs are insufficient (fewer than 2 valid samples, or missing `lastDateStr`), the function returns `null`.

## Current algorithm: linear trend + day-of-week correction

The current forecast is a **two-part model**:

1. **Linear trend** over the most recent \(m\) samples
2. **Day-of-week residual mean correction** (captures weekly seasonality)

### Step 1: clean and select samples

From `points`, the algorithm:

- extracts rows as `(date, v)` where `date` is non-empty and `v` is finite
- sorts rows by `date`
- takes the last `windowDays` rows → \(m\) samples

The model uses **sample index** as the time variable:

- \(x_i = i\) for \(i \in [0, m-1]\)
- \(y_i = v_i\)

This makes the forecast robust to missing dates (it is effectively “per-sample” trend, not strictly “per-calendar-day”).

### Step 2: fit a linear trend

Fit ordinary least squares on \((x_i, y_i)\):

\[
\hat{y}_{trend}(x) = a x + b
\]

Where:

\[
a = \frac{\sum_i (x_i-\bar{x})(y_i-\bar{y})}{\sum_i (x_i-\bar{x})^2},\quad
b = \bar{y} - a \bar{x}
\]

If the denominator is 0 (degenerate), set \(a = 0\).

### Step 3: learn day-of-week residual means

Compute residuals against the fitted trend:

\[
r_i = y_i - (a x_i + b)
\]

Group residuals by day-of-week \(dow \in [0..6]\) and compute:

\[
\mu_{dow} = mean(\{ r_i \mid dow(date_i)=dow\})
\]

If a day-of-week has no samples, its correction defaults to 0.

### Step 4: forecast next H days

For each horizon step \(h \in [1..H]\):

- date = `lastDateStr + h days`
- \(x_{future} = (m-1) + h\)
- \(dow = dow(date)\)

Predict:

\[
\hat{y} = a x_{future} + b + \mu_{dow}
\]

Then apply safety transforms:

- if non-finite → 0
- clamp negative → 0
- round to nearest integer

## Why this method (trade-offs)

### Strengths

- **Simple and explainable**: trend + weekly pattern
- **Deterministic** and easy to debug
- **No dependencies** (works offline; no model storage)
- **Handles sparse series** reasonably (missing days)

### Limitations

- Linear trend may overreact to spikes (no robust loss)
- Using sample index (not calendar-day index) can under-estimate growth if many dates are missing
- Only weekly seasonality is modeled; holidays and billing cutoffs are not
- Designed for **7-day outlook**, not long-term forecasting

## Recommended “next” method (if/when we upgrade)

If forecast accuracy becomes more important than simplicity, a good next step is a **robust seasonal baseline + damped trend**:

- **Seasonality**: for each day-of-week, use median of the last \(k\) occurrences (e.g. last 6 weeks)
- **Trend**: compute a robust weekly delta (median difference between last week and prior week), then **damp** it (e.g. multiply by 0.6)
- **Forecast**: \( \hat{y} = seasonal(dow) + dampedTrend \cdot \lceil h/7 \rceil \)
- Keep the same safety transforms: non-negative, integer output

This keeps the model explainable but reduces sensitivity to outliers and avoids the “slope from a single spike” issue.

## Forecast quality (UI hint)

Some pages display a small **Forecast quality** badge (High / Medium / Low). This is a **heuristic** intended to help readers interpret the forecast, not a statistical confidence interval.

Implementation:

- `app/static/js/forecasting.js`: `forecastQuality(points, key, { windowDays=28 })`

Signals used (within the last 28 samples):

- **Sample sufficiency**: number of valid numeric points
- **Missing ratio**: missing/invalid points within the window
- **Volatility**: robust median absolute day-to-day change, normalized by median level

The badge also exposes details on hover (samples, missing %, volatility %).

## Verification checklist

When changing forecast logic:

- run `pytest`
- dashboard smoke check:
  - switch project + date range, click Apply
  - confirm 3 charts update and horizon X-axis shows **next 7 days**
  - confirm token values are integers (tooltip + axis + table)

