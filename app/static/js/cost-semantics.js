/* global window */

/** Shared Actual (billing) vs Market (catalog list) semantics for tables and charts. */
(function () {
  const actual = {
    color: "#5eead4",
    rgb: "94,234,212",
    label: "Actual",
    hint: "Meter billing — CostUSD from inp/opt rows",
  };

  const market = {
    color: "#c084fc",
    rgb: "192,132,252",
    label: "Market",
    hint: "Catalog list — tokens × USD/1M from Model Prices",
  };

  function meta(kind) {
    return kind === "market" ? market : actual;
  }

  function pill(kind, { dashed = false } = {}) {
    const k = meta(kind);
    const cls =
      kind === "market"
        ? `costPill--market${dashed ? " costPill--dashed" : ""}`
        : "costPill--actual";
    return `<span class="costPill ${cls}" title="${k.hint}">${k.label}</span>`;
  }

  function legend(kinds) {
    const list = Array.isArray(kinds) ? kinds : ["actual", "market"];
    const parts = list.map((k) =>
      k === "market" ? pill("market", { dashed: true }) : pill("actual")
    );
    return `<div class="costTypeLegend" aria-label="Cost type">${parts.join('<span class="costLegendSep" aria-hidden="true"></span>')}</div>`;
  }

  function thClass(kind) {
    return kind === "market" ? "colCostMarket" : "colCostActual";
  }

  function tdClass(kind) {
    return kind === "market" ? "tdCostMarket" : "tdCostActual";
  }

  /** Chart.js currency dataset — fixed semantic label and color. */
  function chartDataset(kind, { data, dashed = false, fill = false, pointRadius = 2 } = {}) {
    const k = meta(kind);
    const bg = `rgba(${k.rgb}, ${fill ? "0.14" : "0.08"})`;
    const wrap = window.AppChartStyle?.datasetLineCurrency;
    if (typeof wrap === "function") {
      return wrap({
        label: k.label,
        data,
        borderColor: k.color,
        backgroundColor: bg,
        dashed,
        fill,
        pointRadius,
      });
    }
    return {
      label: k.label,
      data,
      borderColor: k.color,
      backgroundColor: bg,
      fill,
      tension: 0.28,
      pointRadius,
      pointHoverRadius: 5,
      borderWidth: dashed ? 2 : 2.5,
      borderDash: dashed ? [6, 4] : undefined,
      spanGaps: true,
      unitType: "currency",
    };
  }

  window.AppCostSemantics = {
    actual,
    market,
    meta,
    pill,
    legend,
    thClass,
    tdClass,
    chartDataset,
  };
})();
