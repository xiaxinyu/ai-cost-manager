/* global window */

/** OpEx / CapEx management-report semantics for tables and charts. */
(function () {
  const opex = {
    color: "#5eead4",
    rgb: "94,234,212",
    label: "OpEx",
    shortLabel: "OpEx",
    subtitle: "Actual billing",
    hint: "OpEx — meter billing and platform spend in period (CostUSD from invoices)",
    pillClass: "costPill--actual",
    colClass: "colCostActual",
    tdClass: "tdCostActual",
  };

  const tariff = {
    color: "#c084fc",
    rgb: "192,132,252",
    label: "CapEx · Tariff",
    shortLabel: "Tariff",
    subtitle: "List price reference",
    hint: "CapEx reference — catalog list price (tokens × USD/1M); not capital assets",
    pillClass: "costPill--market",
    colClass: "colCostMarket",
    tdClass: "tdCostMarket",
  };

  const platform = {
    color: "#fbbf24",
    rgb: "251,191,36",
    label: "CapEx · Platform",
    shortLabel: "Platform",
    subtitle: "Non-token services",
    hint: "CapEx platform layer — billing_other (non-token Azure services); reference attribution",
    pillClass: "costPill--platform",
    colClass: "colCostPlatform",
    tdClass: "tdCostPlatform",
  };

  /** Backward-compatible aliases for chart/table code still using actual/market. */
  const actual = { ...opex, label: "OpEx", shortLabel: "OpEx" };
  const market = { ...tariff, label: "CapEx · Tariff", shortLabel: "Tariff" };

  const KIND_MAP = {
    opex,
    actual: opex,
    tariff,
    market: tariff,
    platform,
  };

  function meta(kind) {
    const k = String(kind || "opex").toLowerCase();
    return KIND_MAP[k] || opex;
  }

  function pill(kind, { dashed = false, short = false } = {}) {
    const k = meta(kind);
    const cls = `${k.pillClass}${dashed && k === tariff ? " costPill--dashed" : ""}`;
    const text = short ? k.shortLabel : k.label;
    return `<span class="costPill ${cls}" title="${k.hint}">${text}</span>`;
  }

  function legend(kinds) {
    const list = Array.isArray(kinds) ? kinds : ["opex", "tariff"];
    const parts = list.map((k) => {
      const key = String(k).toLowerCase();
      if (key === "tariff" || key === "market") return pill("tariff", { dashed: true });
      if (key === "platform") return pill("platform");
      return pill("opex");
    });
    return `<div class="costTypeLegend" aria-label="Cost type">${parts.join('<span class="costLegendSep" aria-hidden="true"></span>')}</div>`;
  }

  function thClass(kind) {
    return meta(kind).colClass;
  }

  function tdClass(kind) {
    return meta(kind).tdClass;
  }

  /** Chart.js currency dataset — fixed semantic label and color. */
  function chartDataset(kind, { data, dashed = false, fill = false, pointRadius = 2 } = {}) {
    const k = meta(kind);
    const bg = `rgba(${k.rgb}, ${fill ? "0.14" : "0.08"})`;
    const wrap = window.AppChartStyle?.datasetLineCurrency;
    if (typeof wrap === "function") {
      return wrap({
        label: k.shortLabel,
        data,
        borderColor: k.color,
        backgroundColor: bg,
        dashed,
        fill,
        pointRadius,
      });
    }
    return {
      label: k.shortLabel,
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
    opex,
    tariff,
    platform,
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
