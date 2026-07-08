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
    hint: "By model table — Meter column (model rows: Input + Output USD)",
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
    hint: "By model table — Others · … rows (non-token services; chart Platform stack)",
    pillClass: "costPill--platform",
    colClass: "colCostPlatform",
    tdClass: "tdCostPlatform",
  };

  const tariff = {
    color: "#c084fc",
    rgb: "192,132,252",
    label: "Ref. Arch · Tariff",
    shortLabel: "Ref. Arch · Tariff",
    layerLabel: "Ref. Arch.",
    sectionTitle: "Reference architecture",
    sectionLead: "List-price tariff benchmark — not invoice spend.",
    varianceLabel: "Tariff variance",
    varianceHint: "OpEx − Ref. Arch · Tariff",
    rateCardLabel: "Tariff schedule",
    rateCardValue: "List price",
    subtitle: "List-price benchmark",
    hint: "Tariff column — list USD/1M from Model Prices (not invoice)",
    pillClass: "costPill--market",
    colClass: "colCostMarket",
    tdClass: "tdCostMarket",
  };

  /** Backward-compatible aliases for chart/table code still using actual/market. */
  const actual = { ...opex, label: "OpEx", shortLabel: "OpEx" };
  const market = { ...tariff };

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

  function pill(kind, { dashed = false, variant = "full" } = {}) {
    const k = meta(kind);
    const cls = `${k.pillClass}${dashed && k === tariff ? " costPill--dashed" : ""}`;
    let text = k.label;
    if (variant === "layer") text = k.layerLabel || k.shortLabel;
    else if (variant === "short") text = k.shortLabel;
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

  /** Plain-language billing key — aligned with Allocation → By model table. */
  function billingKey({ stacked = false, meterSplit = false, hasTariff = false, allocationHref = null } = {}) {
    const rows = [];
    const split = stacked || meterSplit;
    if (split) {
      rows.push({
        kind: "meter",
        text: "Model rows · <b>Meter</b> column (Input + Output USD)",
      });
      rows.push({
        kind: "platform",
        text: "<b>Others · …</b> rows · non-token platform services",
      });
    } else {
      rows.push({
        kind: "opex",
        text: "Daily <b>CostUSD</b> from billing CSV",
      });
    }
    if (hasTariff) {
      rows.push({
        kind: "tariff",
        text: "<b>Ref. Arch · Tariff</b> column · list USD/1M (<a href=\"/prices\">Tariff schedule</a>)",
      });
    }
    if (!rows.length) return "";
    const items = rows
      .map(
        (r) =>
          `<div class="costBillingKeyRow">${pill(r.kind, {
            dashed: r.kind === "tariff",
            variant: r.kind === "meter" ? "short" : r.kind === "tariff" ? "layer" : "full",
          })}<span class="costBillingKeyText">${r.text}</span></div>`
      )
      .join("");
    const link =
      allocationHref != null && String(allocationHref).trim()
        ? `<p class="costBillingKeyFoot muted"><a href="${String(allocationHref).trim()}">Open Allocation → By model</a></p>`
        : "";
    return `<div class="costBillingKey" aria-label="Billing legend">${items}${link}</div>`;
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
