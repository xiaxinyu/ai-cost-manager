/* global window */

/** OpEx statement semantics + reference tariff benchmark (not a second spend layer). */
(function () {
  const opex = {
    color: "#5eead4",
    rgb: "94,234,212",
    label: "OpEx",
    shortLabel: "OpEx",
    subtitle: "Actual billing",
    hint: "Billing CSV CostUSD — daily invoice actual (UsageDate)",
    pillClass: "costPill--actual",
    colClass: "colCostActual",
    tdClass: "tdCostActual",
  };

  const meter = {
    color: "#5eead4",
    rgb: "94,234,212",
    label: "OpEx · Meter",
    shortLabel: "Meter",
    subtitle: "Token meter (inp/out)",
    hint: "Matched billing meter rows — token input/output (MeterCategory inp + opt)",
    pillClass: "costPill--actual",
    colClass: "colCostActual",
    tdClass: "tdCostActual",
  };

  const platform = {
    color: "#fbbf24",
    rgb: "251,191,36",
    label: "OpEx · Platform",
    shortLabel: "Platform",
    subtitle: "Non-token services",
    hint: "CostUSD minus meter — deployment, PTU/hosting, and other non-token lines",
    pillClass: "costPill--platform",
    colClass: "colCostPlatform",
    tdClass: "tdCostPlatform",
  };

  const tariff = {
    color: "#c084fc",
    rgb: "192,132,252",
    label: "Reference · Tariff",
    shortLabel: "Tariff",
    subtitle: "List price benchmark",
    hint: "Reference only — catalog list price (tokens × USD/1M); not invoice spend",
    pillClass: "costPill--market",
    colClass: "colCostMarket",
    tdClass: "tdCostMarket",
  };

  /** Backward-compatible aliases for chart/table code still using actual/market. */
  const actual = { ...opex, label: "OpEx", shortLabel: "OpEx" };
  const market = { ...tariff, label: "Reference · Tariff", shortLabel: "Tariff" };

  const KIND_MAP = {
    opex,
    actual: opex,
    meter,
    platform,
    tariff,
    market: tariff,
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
      if (key === "meter") return pill("meter", { short: true });
      return pill("opex");
    });
    return `<div class="costTypeLegend" aria-label="Cost type">${parts.join('<span class="costLegendSep" aria-hidden="true"></span>')}</div>`;
  }

  /** Plain-language billing key for Daily spend charts (maps pills → CSV / derivation). */
  function billingKey({ stacked = false, hasTariff = false } = {}) {
    const rows = [];
    if (stacked) {
      rows.push({
        kind: "meter",
        text: "Token meter (inp + out) — billing rows matched to model/token usage (MeterCategory inp/opt)",
      });
      rows.push({
        kind: "platform",
        text: "Platform & other — remainder of daily CostUSD (deployment, hosting, non-token services)",
      });
    } else {
      rows.push({
        kind: "opex",
        text: "Daily CostUSD — invoice actual from Azure billing CSV (UsageDate total)",
      });
    }
    if (hasTariff) {
      rows.push({
        kind: "tariff",
        text: "Tariff reference — imported tokens × list USD/1M (benchmark only, not billed)",
      });
    }
    if (!rows.length) return "";
    const items = rows
      .map(
        (r) =>
          `<div class="costBillingKeyRow">${pill(r.kind, {
            dashed: r.kind === "tariff",
            short: r.kind === "meter",
          })}<span class="costBillingKeyText">${r.text}</span></div>`
      )
      .join("");
    return `<div class="costBillingKey" aria-label="Billing legend">${items}</div>`;
  }

  function thClass(kind) {
    return meta(kind).colClass;
  }

  function tdClass(kind) {
    return meta(kind).tdClass;
  }

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
    meter,
    platform,
    tariff,
    actual,
    market,
    meta,
    pill,
    legend,
    billingKey,
    thClass,
    tdClass,
    chartDataset,
  };
})();
