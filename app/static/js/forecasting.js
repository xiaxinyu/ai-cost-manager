/* global window */

// Lightweight, deterministic forecasting utilities shared across pages.
// Exposed as window.AppForecasting to work in template-driven pages without bundling.

(function () {
  function _median(arr) {
    const xs = (arr || []).filter((x) => Number.isFinite(Number(x))).map((x) => Number(x)).sort((a, b) => a - b);
    if (!xs.length) return null;
    const mid = Math.floor(xs.length / 2);
    if (xs.length % 2 === 1) return xs[mid];
    return (xs[mid - 1] + xs[mid]) / 2;
  }

  // Lightweight, explainable quality heuristic for a forecast window.
  // Intended for UI hinting only (High/Medium/Low), not a statistical confidence interval.
  function forecastQuality(points, key, { windowDays = 28 } = {}) {
    const rowsAll = (points || [])
      .map((p) => ({ date: safeDateStr(p?.date), v: p?.[key] }))
      .filter((x) => x.date)
      .sort((a, b) => a.date.localeCompare(b.date));

    const win = Math.max(2, Math.min(Number(windowDays) || 28, 365));
    const windowRows = rowsAll.slice(-win);
    const values = windowRows
      .map((r) => r.v)
      .filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v)))
      .map((v) => Number(v));

    const expected = windowRows.length;
    const valid = values.length;
    const missingRatio = expected ? (expected - valid) / expected : 1;

    // Volatility: median absolute day-to-day change (robust).
    const diffs = [];
    for (let i = 1; i < values.length; i++) diffs.push(Math.abs(values[i] - values[i - 1]));
    const madDiff = _median(diffs) ?? 0;
    const med = _median(values) ?? 0;
    const relVol = med > 0 ? madDiff / med : (madDiff > 0 ? 1 : 0);

    let score = 0;
    if (valid >= 21) score += 2;
    else if (valid >= 10) score += 1;

    if (missingRatio <= 0.05) score += 2;
    else if (missingRatio <= 0.25) score += 1;

    if (relVol <= 0.25) score += 2;
    else if (relVol <= 0.60) score += 1;

    const level = score >= 5 ? 'high' : score >= 3 ? 'medium' : 'low';
    return { level, score, valid, expected, missingRatio, relVol };
  }

  function dailyTokenRatio(points, { inputKey = 'estimated_input_tokens', outputKey = 'estimated_output_tokens' } = {}) {
    const rows = (points || [])
      .map((p) => ({
        date: safeDateStr(p?.date),
        inV: p?.[inputKey],
        outV: p?.[outputKey],
      }))
      .filter((r) => r.date)
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((r) => {
        const inN = r.inV === null || r.inV === undefined ? null : Number(r.inV);
        const outN = r.outV === null || r.outV === undefined ? null : Number(r.outV);
        if (!Number.isFinite(inN) || !Number.isFinite(outN) || inN <= 0) return { date: r.date, ratio: null };
        return { date: r.date, ratio: outN / inN };
      });
    return rows;
  }

  function ratioStats(ratioRows) {
    const xs = (ratioRows || []).map((r) => r?.ratio).filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v))).map((v) => Number(v));
    const valid = xs.length;
    if (!valid) return { valid_days: 0, above_1_days: 0, below_1_days: 0, above_1_pct: 0, below_1_pct: 0 };
    let above = 0;
    let below = 0;
    for (const v of xs) {
      if (v > 1) above += 1;
      else if (v < 1) below += 1;
    }
    const abovePct = Math.round((above / valid) * 100);
    const belowPct = Math.round((below / valid) * 100);
    return { valid_days: valid, above_1_days: above, below_1_days: below, above_1_pct: abovePct, below_1_pct: belowPct };
  }

  // Y-range for output/input ratio: always include every data point (no IQR tail clipping).
  function ratioSuggestedBounds(ratioRows) {
    const xs = (ratioRows || [])
      .map((r) => r?.ratio)
      .filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v)))
      .map((v) => Number(v));
    if (!xs.length) return { min: 0, max: 2 };

    const rawMin = Math.min(...xs);
    const rawMax = Math.max(...xs);
    const spread = Math.max(rawMax - rawMin, 0);
    const anchor = Math.max(Math.abs((rawMax + rawMin) / 2), rawMax, 1e-12);
    let pad = Math.max(spread * 0.1, anchor * 0.06, 1e-9);
    if (spread === 0) pad = Math.max(anchor * 0.12, 0.0005);

    let minV = Math.max(0, rawMin - pad);
    let maxV = rawMax + pad;
    if (maxV <= minV) maxV = minV + Math.max(anchor * 0.15, 0.001);

    // Include parity reference when the series approaches 1.0.
    if (rawMax >= 0.8) {
      maxV = Math.max(maxV, 1.0);
      minV = Math.min(minV, 1.0);
      minV = Math.max(0, minV);
    }

    return { min: minV, max: maxV };
  }

  function ratioYTickDecimals(bounds) {
    if (!bounds || !Number.isFinite(bounds.min) || !Number.isFinite(bounds.max)) return 3;
    const span = Math.max(bounds.max - bounds.min, 1e-15);
    if (span < 0.015) return 4;
    if (span < 0.08) return 3;
    return 2;
  }

  function safeDateStr(s) {
    if (!s) return '';
    const t = String(s).trim();
    return t.length > 0 ? t : '';
  }

  function toYmd(d) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function addDaysYmd(dateStr, days) {
    const d = new Date(`${dateStr}T00:00:00`);
    if (Number.isNaN(d.getTime())) return null;
    d.setDate(d.getDate() + Number(days || 0));
    return toYmd(d);
  }

  // Forecast: linear trend + day-of-week residual mean correction.
  // - points: [{ date: 'YYYY-MM-DD', ... }]
  // - key: numeric field to forecast
  // - lastDateStr: last observed date used as horizon start
  // Output: [{ date, value }] integer, non-negative. Returns null if insufficient data.
  function forecastNextDaysDOW(points, key, lastDateStr, { windowDays = 28, horizonDays = 7 } = {}) {
    const rowsAll = (points || [])
      .map((p) => ({ date: safeDateStr(p?.date), v: p?.[key] }))
      .filter((x) => x.date && x.v !== null && x.v !== undefined && Number.isFinite(Number(x.v)))
      .map((x) => ({ date: x.date, v: Number(x.v) }))
      .sort((a, b) => a.date.localeCompare(b.date));

    const win = Math.max(2, Math.min(Number(windowDays) || 28, 365));
    const rows = rowsAll.slice(-win);
    if (rows.length < 2 || !lastDateStr) return null;

    const m = rows.length;
    const xs = Array.from({ length: m }, (_, i) => i);
    const ys = rows.map((r) => r.v);
    const xBar = xs.reduce((a, b) => a + b, 0) / m;
    const yBar = ys.reduce((a, b) => a + b, 0) / m;

    let num = 0;
    let den = 0;
    for (let i = 0; i < m; i++) {
      const dx = xs[i] - xBar;
      num += dx * (ys[i] - yBar);
      den += dx * dx;
    }
    const a = den === 0 ? 0 : num / den;
    const b = yBar - a * xBar;

    const dowSum = new Array(7).fill(0);
    const dowCnt = new Array(7).fill(0);
    for (let i = 0; i < m; i++) {
      const date = rows[i].date;
      const d = new Date(`${date}T00:00:00`);
      if (Number.isNaN(d.getTime())) continue;
      const dow = d.getDay();
      const trend = a * xs[i] + b;
      const resid = ys[i] - trend;
      dowSum[dow] += resid;
      dowCnt[dow] += 1;
    }
    const dowMean = dowSum.map((s, i) => (dowCnt[i] ? s / dowCnt[i] : 0));

    const H = Math.max(1, Math.min(Number(horizonDays) || 7, 30));
    const out = [];
    const lastX = m - 1;
    for (let h = 1; h <= H; h++) {
      const dateStr = addDaysYmd(lastDateStr, h);
      if (!dateStr) continue;
      const d = new Date(`${dateStr}T00:00:00`);
      const dow = Number.isNaN(d.getTime()) ? 0 : d.getDay();
      const xFuture = lastX + h;
      let yHat = a * xFuture + b + (dowMean[dow] || 0);
      if (!Number.isFinite(yHat)) yHat = 0;
      if (yHat < 0) yHat = 0;
      yHat = Math.round(yHat);
      out.push({ date: dateStr, value: yHat });
    }
    return out;
  }

  window.AppForecasting = {
    safeDateStr,
    addDaysYmd,
    forecastNextDaysDOW,
    forecastQuality,
    dailyTokenRatio,
    ratioStats,
    ratioSuggestedBounds,
    ratioYTickDecimals,
  };
})();
