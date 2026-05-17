/**
 * Cost display: always 2 decimal places with currency code (e.g. USD 15.13).
 */
(function () {
  const COST_DECIMALS = 2;

  function roundCost(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return null;
    return Math.round(x * 100) / 100;
  }

  function normalizeCurrency(currency) {
    const c = String(currency || "USD").trim();
    return c || "USD";
  }

  /** Absolute cost: "15.13 USD" (locale-aware grouping). */
  function fmtCost(n, currency) {
    const x = roundCost(n);
    if (x === null) return "—";
    const cur = normalizeCurrency(currency);
    try {
      const parts = new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: cur,
        minimumFractionDigits: COST_DECIMALS,
        maximumFractionDigits: COST_DECIMALS,
      }).formatToParts(x);
      const num = parts
        .filter((p) => p.type !== "currency")
        .map((p) => p.value)
        .join("")
        .trim();
      return `${num} ${cur}`;
    } catch {
      return `${x.toFixed(COST_DECIMALS)} ${cur}`;
    }
  }

  /** Unit rate: "3.45 USD/1M". */
  function fmtCostPer1m(n, currency) {
    const x = roundCost(n);
    if (x === null) return "—";
    const cur = normalizeCurrency(currency);
    const num = x.toLocaleString(undefined, {
      minimumFractionDigits: COST_DECIMALS,
      maximumFractionDigits: COST_DECIMALS,
    });
    return `${num} ${cur}/1M`;
  }

  /** Chart axis: 2 decimals, no currency suffix (keeps Y-axis readable). */
  function fmtCostAxis(n) {
    const x = roundCost(n);
    if (x === null) return "";
    return x.toLocaleString(undefined, {
      minimumFractionDigits: COST_DECIMALS,
      maximumFractionDigits: COST_DECIMALS,
    });
  }

  window.AppMoney = {
    COST_DECIMALS,
    roundCost,
    fmtCost,
    fmtCostPer1m,
    fmtCostAxis,
  };
})();
