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

  function pill(kind) {
    const k = kind === "market" ? market : actual;
    const cls = kind === "market" ? "costPill--market" : "costPill--actual";
    return `<span class="costPill ${cls}" title="${k.hint}">${k.label}</span>`;
  }

  function legend(kinds) {
    const list = Array.isArray(kinds) ? kinds : ["actual", "market"];
    return `<div class="costTypeLegend" aria-label="Cost type">${list.map((k) => pill(k)).join("")}</div>`;
  }

  function thClass(kind) {
    return kind === "market" ? "colCostMarket" : "colCostActual";
  }

  function tdClass(kind) {
    return kind === "market" ? "tdCostMarket" : "tdCostActual";
  }

  window.AppCostSemantics = {
    actual,
    market,
    pill,
    legend,
    thClass,
    tdClass,
  };
})();
