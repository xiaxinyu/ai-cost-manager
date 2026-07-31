/* global window */
/**
 * Project token spend from USD/1M unit rates and daily token volume.
 * Periods: 1 day, 7 days, 30 days, 365 days.
 */
(() => {
  const PER_1M = 1_000_000;

  function _num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function _roundMoney(n) {
    if (n == null || !Number.isFinite(n)) return null;
    return window.AppMoney?.roundCost?.(n) ?? Math.round(n * 100) / 100;
  }

  /**
   * @param {{
   *   rateInPer1m: number|null|undefined,
   *   rateOutPer1m: number|null|undefined,
   *   inputTokensPerDay: number|null|undefined,
   *   outputTokensPerDay: number|null|undefined,
   * }} opts
   */
  function projectDailyCost({
    rateInPer1m,
    rateOutPer1m,
    inputTokensPerDay,
    outputTokensPerDay,
    teamSize = 1,
  } = {}) {
    const rateIn = _num(rateInPer1m);
    const rateOut = _num(rateOutPer1m);
    const inTok = _num(inputTokensPerDay) ?? 0;
    const outTok = _num(outputTokensPerDay) ?? 0;
    const team = Math.max(1, Math.floor(_num(teamSize) ?? 1));
    if ((rateIn == null && rateOut == null) || (inTok <= 0 && outTok <= 0)) {
      return null;
    }
    const dayInput =
      rateIn != null && inTok > 0 ? (inTok / PER_1M) * rateIn * team : 0;
    const dayOutput =
      rateOut != null && outTok > 0 ? (outTok / PER_1M) * rateOut * team : 0;
    const day = dayInput + dayOutput;
    if (!Number.isFinite(day) || day < 0) return null;
    return {
      day_input: _roundMoney(dayInput),
      day_output: _roundMoney(dayOutput),
      day: _roundMoney(day),
      days_7: _roundMoney(day * 7),
      days_30: _roundMoney(day * 30),
      days_365: _roundMoney(day * 365),
      input_tokens_per_day: inTok,
      output_tokens_per_day: outTok,
      team_size: team,
      rate_in_per_1m: rateIn,
      rate_out_per_1m: rateOut,
    };
  }

  function periodsFromProjection(proj) {
    if (!proj) return [];
    return [
      { key: "day", label: "1 day", days: 1, total: proj.day },
      { key: "week", label: "7 days", days: 7, total: proj.days_7 },
      { key: "month", label: "30 days", days: 30, total: proj.days_30 },
      { key: "year", label: "365 days", days: 365, total: proj.days_365 },
    ];
  }

  window.AppCostProjection = {
    PER_1M,
    projectDailyCost,
    periodsFromProjection,
  };
})();
