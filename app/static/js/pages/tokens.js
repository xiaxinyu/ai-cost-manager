/* global Chart, window */

(() => {
  const CHART = window.AppChartStyle;
  const DASH = window.AppDashboardUi;
  const C = CHART?.colors || {};
  const L = CHART?.labels || {};
  const F = window.AppForecasting || {};

  CHART?.applyDefaults?.();

  const els = {
    projectSelect: document.getElementById("projectSelect"),
    startDate: document.getElementById("tokenStartDateInput"),
    endDate: document.getElementById("tokenEndDateInput"),
    loadBtn: document.getElementById("loadTokensBtn"),
    emptyState: document.getElementById("emptyState"),
    workspace: document.getElementById("tokenWorkspace"),
    noImportState: document.getElementById("noImportState"),
    noImportHint: document.getElementById("noImportHint"),
    sourceBadge: document.getElementById("tokenSourceBadge"),
    sourceBadgeText: document.getElementById("tokenSourceBadgeText"),
    filterHint: document.getElementById("filterHint"),
    dataStatusBar: document.getElementById("dataStatusBar"),
    tableRowBadge: document.getElementById("tableRowBadge"),
    labelInput: document.getElementById("labelInputTokens"),
    labelOutput: document.getElementById("labelOutputTokens"),
    labelTotal: document.getElementById("labelTotalTokens"),
    chartTitleInput: document.getElementById("chartTitleInput"),
    chartTitleOutput: document.getElementById("chartTitleOutput"),
    tableHint: document.getElementById("tableHint"),
    estimatedInput: document.getElementById("estimatedInputTokens"),
    estimatedOutput: document.getElementById("estimatedOutputTokens"),
    estimatedTotal: document.getElementById("estimatedTotalTokens"),
    inputStats: document.getElementById("inputStats"),
    outputStats: document.getElementById("outputStats"),
    totalStats: document.getElementById("totalStats"),
    tokenModel: document.getElementById("tokenModel"),
    tokenRegion: document.getElementById("tokenRegion"),
    tokenMetaExtra: document.getElementById("tokenMetaExtra"),
    rangeLabel: document.getElementById("rangeLabel"),
    ratioSummary: document.getElementById("ratioSummary"),
    ratioBaselinePill: document.getElementById("ratioBaselinePill"),
    modelPanel: document.getElementById("modelBreakdownPanel"),
    modelTbody: document.getElementById("modelBreakdownTbody"),
    unitPriceSection: document.getElementById("unitPriceSection"),
    unitPriceNote: document.getElementById("unitPriceNote"),
    catalogRefLine: document.getElementById("catalogRefLine"),
    impliedChartsRow: document.getElementById("impliedChartsRow"),
    modelPager: document.getElementById("modelPager"),
    modelPageSizeSelect: document.getElementById("modelPageSizeSelect"),
    modelPrevBtn: document.getElementById("modelPrevBtn"),
    modelNextBtn: document.getElementById("modelNextBtn"),
    modelPageInfo: document.getElementById("modelPageInfo"),
    rowsTbody: document.getElementById("tokenRowsTbody"),
    dailyPageSizeSelect: document.getElementById("dailyPageSizeSelect"),
    dailyPrevBtn: document.getElementById("dailyPrevBtn"),
    dailyNextBtn: document.getElementById("dailyNextBtn"),
    dailyPageInfo: document.getElementById("dailyPageInfo"),
    exportBtn: document.getElementById("exportTokensBtn"),
  };

  let tokenInputChart = null;
  let tokenOutputChart = null;
  let tokenRatioChart = null;
  let tokenInputCostChart = null;
  let tokenOutputCostChart = null;
  let chartImpliedUnitInput = null;
  let chartImpliedUnitOutput = null;

  const chartLineDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    animation: { duration: 450 },
    elements: {
      line: { capBezierPoints: true },
      point: { hitRadius: 12 },
    },
  };

  function emptyStatePluginImplied(emptyMessage) {
    const msg = emptyMessage || "No data in selected range";
    return {
      id: "emptyStateImplied",
      afterDraw: (c) => {
        const hasData = (c?.data?.datasets || []).some((ds) =>
          (ds.data || []).some((v) => v !== null && v !== undefined && !Number.isNaN(v))
        );
        if (hasData) return;
        const x = c?.ctx;
        const chartArea = c?.chartArea;
        if (!x || !chartArea) return;
        x.save();
        x.fillStyle = "rgba(159,178,199,0.85)";
        x.font = "600 14px system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";
        x.textAlign = "center";
        x.fillText(msg, (chartArea.left + chartArea.right) / 2, (chartArea.top + chartArea.bottom) / 2);
        x.restore();
      },
    };
  }
  let lastDailyModelRows = [];
  let lastSource = "estimated";
  let projectsWithImportedTokens = [];
  let dailyPage = 1;
  let modelPage = 1;
  let lastModelBreakdown = [];
  let chartLabels = {
    input: "Input tokens",
    output: "Output tokens",
    total: "Total tokens",
  };
  const DAILY_TABLE_COL_COUNT = 11;

  function isMeterAllocated(method) {
    return method === "meter_matched" || method === "meter_matched_partial";
  }

  function allocationLabel(method) {
    switch (method) {
      case "meter_matched":
        return "Meter";
      case "meter_matched_partial":
        return "Meter (partial)";
      case "no_meter_match":
        return "No meter";
      default:
        return method || "—";
    }
  }
  let lastBillingCurrency = "USD";

  const MODEL_CHART_COLORS = [
    { border: "#60a5fa", fill: "rgba(96, 165, 250, 0.12)" },
    { border: "#a78bfa", fill: "rgba(167, 139, 250, 0.12)" },
    { border: "#5eead4", fill: "rgba(94, 234, 212, 0.12)" },
    { border: "#fbbf24", fill: "rgba(251, 191, 36, 0.12)" },
    { border: "#f87171", fill: "rgba(248, 113, 113, 0.12)" },
    { border: "#34d399", fill: "rgba(52, 211, 153, 0.12)" },
  ];

  function fmtInt(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return Math.round(Number(v)).toLocaleString();
  }

  function fmtPct(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return `${Number(v).toFixed(1)}%`;
  }

  function fmtRatio(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    const x = Number(v);
    const ax = Math.abs(x);
    if (ax === 0) return "0.000";
    if (ax >= 0.2) return x.toFixed(3);
    return x.toFixed(4);
  }

  function fmtUsdPer1m(n, currency) {
    return window.AppMoney?.fmtCostPer1m(n, currency || lastBillingCurrency) ?? "—";
  }

  function fmtUsd(n, currency) {
    return window.AppMoney?.fmtCost(n, currency || lastBillingCurrency) ?? "—";
  }

  function roundMoney(n) {
    return window.AppMoney?.roundCost(n);
  }

  function fmtUsdAxis(n) {
    return window.AppMoney?.fmtCostAxis(n) ?? "";
  }

  function syncUnitPriceSection() {
    if (!els.unitPriceSection) return;
    const chartsHidden = !els.impliedChartsRow || els.impliedChartsRow.hidden;
    els.unitPriceSection.hidden = chartsHidden;
  }

  function clearUnitPriceUi() {
    if (chartImpliedUnitInput) chartImpliedUnitInput.destroy();
    if (chartImpliedUnitOutput) chartImpliedUnitOutput.destroy();
    chartImpliedUnitInput = null;
    chartImpliedUnitOutput = null;
    if (els.impliedChartsRow) els.impliedChartsRow.hidden = true;
    if (els.unitPriceSection) els.unitPriceSection.hidden = true;
    if (els.catalogRefLine) {
      els.catalogRefLine.hidden = true;
      els.catalogRefLine.textContent = "";
    }
  }

  function renderCatalogRefLine(catalogPayload, currency) {
    if (!els.catalogRefLine) return;
    const models = (catalogPayload?.models || []).filter(
      (m) => m.catalog_usd_per_1m_input != null || m.catalog_usd_per_1m_output != null
    );
    if (!models.length) {
      els.catalogRefLine.hidden = true;
      els.catalogRefLine.innerHTML = "";
      return;
    }
    const ccy = currency || catalogPayload.currency || "USD";
    const grid = document.createElement("div");
    grid.className = "catalogRefGrid";
    for (const m of models) {
      const cin = m.catalog_usd_per_1m_input != null ? fmtUsdPer1m(m.catalog_usd_per_1m_input, ccy) : "—";
      const cout = m.catalog_usd_per_1m_output != null ? fmtUsdPer1m(m.catalog_usd_per_1m_output, ccy) : "—";
      const daily = m.daily || [];
      const last = daily.length ? daily[daily.length - 1] : null;
      const item = document.createElement("div");
      item.className = "catalogRefItem";
      const title = document.createElement("div");
      title.className = "catalogRefModel";
      title.textContent = m.model_name || "model";
      const prices = document.createElement("div");
      prices.className = "catalogRefPrices";
      prices.textContent = `List: in ${cin} · out ${cout}`;
      item.append(title, prices);
      if (last) {
        const pin = pctVsCatalog(last.usd_per_1m_input, m.catalog_usd_per_1m_input);
        const pout = pctVsCatalog(last.usd_per_1m_output, m.catalog_usd_per_1m_output);
        const bits = [];
        if (pin != null) bits.push(`in ${pin >= 0 ? "+" : ""}${pin.toFixed(0)}%`);
        if (pout != null) bits.push(`out ${pout >= 0 ? "+" : ""}${pout.toFixed(0)}%`);
        if (bits.length) {
          const delta = document.createElement("div");
          delta.className = "catalogRefDelta";
          delta.textContent = `Latest vs list: ${bits.join(", ")}`;
          item.appendChild(delta);
        }
      }
      grid.appendChild(item);
    }
    els.catalogRefLine.innerHTML = "";
    els.catalogRefLine.appendChild(grid);
    els.catalogRefLine.hidden = false;
  }

  function updateDataStatusBar(project, stats, series) {
    if (!els.dataStatusBar) return;
    const rows = series?.daily_by_model || [];
    const meta = series?._cost_meta || {};
    const withCost = rows.filter(
      (r) => r.input_cost_usd != null || r.output_cost_usd != null
    ).length;
    const meterRows =
      meta.rows_meter_matched != null
        ? Number(meta.rows_meter_matched) + Number(meta.rows_meter_partial || 0)
        : rows.filter((r) => isMeterAllocated(r.allocation_method)).length;
    const models = new Set(rows.map((r) => r.model_name).filter(Boolean)).size;
    const rangeStart = stats?.min_usage_date || els.startDate?.value || "—";
    const rangeEnd = stats?.max_usage_date || els.endDate?.value || "—";
    const ccy = stats?.currency || series?.currency || lastBillingCurrency || "USD";
    const pipeline = series?.cost_pipeline_version || "—";
    const source = series?.token_data_source || stats?.token_data_source || "—";

    const pill = (label, value) => {
      const span = document.createElement("span");
      span.className = "statusPill";
      span.innerHTML = `${label}: <strong>${value}</strong>`;
      return span;
    };

    els.dataStatusBar.innerHTML = "";
    els.dataStatusBar.append(
      pill("Project", project || "—"),
      pill("Range", `${rangeStart} → ${rangeEnd}`),
      pill("Rows", String(rows.length)),
      pill("Models", String(models)),
      pill("Meter matched", `${meterRows}/${rows.length || 0}`),
      pill("With cost", `${withCost}/${rows.length || 0}`),
      pill("Currency", ccy),
      pill("Source", source),
      pill("Pipeline", pipeline)
    );
    els.dataStatusBar.hidden = false;
  }

  function updateTableRowBadge(totalRows, withCostRows) {
    if (!els.tableRowBadge) return;
    if (!totalRows) {
      els.tableRowBadge.hidden = true;
      return;
    }
    els.tableRowBadge.hidden = false;
    const meterRows = lastDailyModelRows.filter((r) => isMeterAllocated(r.allocation_method)).length;
    els.tableRowBadge.textContent = `${totalRows} rows · ${meterRows} meter-matched · ${withCostRows} with cost`;
  }

  function moneyStats(vals) {
    const nums = (vals || []).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
    if (!nums.length) return { min: null, max: null, mean: null, median: null, count: 0 };
    const sorted = [...nums].sort((a, b) => a - b);
    const sum = nums.reduce((a, b) => a + b, 0);
    const mid = Math.floor(sorted.length / 2);
    const median =
      sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
    const round = (x) => window.AppMoney?.roundCost(x) ?? Math.round(x * 100) / 100;
    return {
      min: round(sorted[0]),
      max: round(sorted[sorted.length - 1]),
      mean: round(sum / nums.length),
      median: round(median),
      count: nums.length,
    };
  }

  /** Unit prices from meter-matched rows only (cost ÷ tokens × 1M). */
  function modelUnitPricesFromDaily(dailyByModel) {
    const byModel = new Map();
    for (const row of dailyByModel || []) {
      if (!isMeterAllocated(row.allocation_method)) continue;
      const name = row.model_name || "model";
      if (!byModel.has(name)) {
        byModel.set(name, { model_name: name, daily: [] });
      }
      byModel.get(name).daily.push({
        date: row.date,
        usd_per_1m_input: row.usd_per_1m_input,
        usd_per_1m_output: row.usd_per_1m_output,
      });
    }
    const models = [...byModel.values()].map((m) => {
      const inVals = m.daily.map((d) => d.usd_per_1m_input);
      const outVals = m.daily.map((d) => d.usd_per_1m_output);
      return {
        ...m,
        stats: {
          input: moneyStats(inVals),
          output: moneyStats(outVals),
          blended: moneyStats(
            m.daily
              .map((d) => {
                const a = d.usd_per_1m_input;
                const b = d.usd_per_1m_output;
                if (a != null && b != null) return (Number(a) + Number(b)) / 2;
                return a != null ? a : b;
              })
              .filter((v) => v != null)
          ),
        },
      };
    });
    return { available: models.length > 0, models };
  }

  function stripAzureModelDateSuffix(name) {
    let s = String(name || "").trim().toLowerCase();
    const re = /[-_](?:20\d{2})(?:[-_](?:\d{1,2}|\d{2}|\d{4}|\d{2}[-_]\d{2}))*$/;
    let prev = null;
    while (s !== prev) {
      prev = s;
      s = s.replace(re, "");
    }
    return s;
  }

  function canonicalModelKey(name) {
    let raw = stripAzureModelDateSuffix(name);
    const compact = raw.replace(/[^a-z0-9.]/g, "");
    const tokens = raw.match(/[a-z0-9.]+/g) || [];
    if (/mini/.test(raw) && (/4o/.test(compact) || tokens.includes("4o"))) {
      return "gpt-4o-mini";
    }
    if (/^gpt4omini(?:20\d{2,})?$/i.test(compact)) {
      return "gpt-4o-mini";
    }
    if (/gpt[\s\-_]*4o[\s\-_]*mini|4o[\s\-_]*mini/i.test(raw)) {
      return "gpt-4o-mini";
    }
    if (/^gpt4o(?:20\d{2,})?$/i.test(compact)) {
      return "gpt-4o";
    }
    if (/gpt[\s\-_]*4o(?:[\s\-_]|$)/i.test(raw)) {
      return "gpt-4o";
    }
    if (tokens.includes("4o") && (tokens.includes("gpt") || compact.startsWith("gpt"))) {
      return "gpt-4o";
    }
    return raw.replace(/\s+/g, "-");
  }

  function normalizeModelKey(name) {
    const canonical = canonicalModelKey(name);
    return canonical.replace(/[^a-z0-9]/g, "");
  }

  function findCatalogModel(modelName, catalogModels) {
    const target = normalizeModelKey(modelName);
    if (!target) return null;
    let exact = null;
    let fuzzy = null;
    for (const c of catalogModels || []) {
      const cn = normalizeModelKey(c.model_name);
      if (!cn) continue;
      if (cn === target) {
        exact = c;
        break;
      }
      if (!fuzzy && (cn.includes(target) || target.includes(cn))) {
        fuzzy = c;
      }
    }
    return exact || fuzzy;
  }

  function mergeCatalogPrices(tablePayload, catalogPayload) {
    const catalogModels = catalogPayload?.models || [];
    const tableModels = tablePayload?.models || [];
    if (!catalogModels.length) return tablePayload;
    return {
      ...tablePayload,
      currency: catalogPayload.currency || tablePayload.currency,
      models: tableModels.map((m) => {
        const cat = findCatalogModel(m.model_name, catalogModels) || {};
        return {
          ...m,
          catalog_usd_per_1m_input: cat.catalog_usd_per_1m_input ?? m.catalog_usd_per_1m_input,
          catalog_usd_per_1m_output: cat.catalog_usd_per_1m_output ?? m.catalog_usd_per_1m_output,
        };
      }),
    };
  }

  /** Horizontal dashed lines: catalog list price (USD/1M) from model_prices. */
  function catalogReferenceDatasets(labels, models, catalogKey) {
    const datasets = [];
    (models || []).forEach((model, idx) => {
      const raw = model[catalogKey];
      if (raw == null || !Number.isFinite(Number(raw))) return;
      const y = Number(raw);
      const col = MODEL_CHART_COLORS[idx % MODEL_CHART_COLORS.length];
      const name = model.model_name || "model";
      datasets.push({
        label: `${name} (list)`,
        data: (labels || []).map(() => y),
        borderColor: col.border,
        backgroundColor: "transparent",
        borderDash: [7, 5],
        borderWidth: 1.6,
        pointRadius: 0,
        pointHoverRadius: 0,
        tension: 0,
        fill: false,
        spanGaps: true,
        order: 0,
        catalogReference: true,
      });
    });
    return datasets;
  }

  function pctVsCatalog(actual, catalog) {
    if (actual == null || catalog == null || !Number.isFinite(Number(actual)) || !Number.isFinite(Number(catalog))) {
      return null;
    }
    const c = Number(catalog);
    if (c <= 0) return null;
    return ((Number(actual) - c) / c) * 100;
  }

  function modelLineDatasets(labels, models, valueKey) {
    const datasets = [];
    (models || []).forEach((model, idx) => {
      const daily = model.daily || [];
      if (!daily.length) return;
      const byDate = new Map(daily.map((d) => [d.date, d]));
      const series = labels.map((d) => {
        const row = byDate.get(d);
        const raw = row?.[valueKey];
        return raw != null && Number.isFinite(Number(raw)) ? Number(raw) : null;
      });
      if (!series.some((v) => v !== null && Number.isFinite(v))) return;
      const col = MODEL_CHART_COLORS[idx % MODEL_CHART_COLORS.length];
      datasets.push({
        label: model.model_name || "model",
        data: series,
        borderColor: col.border,
        backgroundColor: col.fill,
        fill: false,
        tension: 0.22,
        pointRadius: 2,
        pointHoverRadius: 4,
        borderWidth: 2,
        spanGaps: true,
        order: 1,
      });
    });
    return datasets;
  }

  function renderImpliedUnitPrices(payload, billingCurrency, tokenRange, modelPayload, chartLabels) {
    if (!els.impliedChartsRow) return;
    if (chartImpliedUnitInput) chartImpliedUnitInput.destroy();
    if (chartImpliedUnitOutput) chartImpliedUnitOutput.destroy();
    chartImpliedUnitInput = null;
    chartImpliedUnitOutput = null;
    if (!modelPayload?.models?.length) {
      els.impliedChartsRow.hidden = true;
      syncUnitPriceSection();
      return;
    }

    els.impliedChartsRow.hidden = false;
    if (els.unitPriceSection) els.unitPriceSection.hidden = false;
    const ccy = billingCurrency || payload.currency || "";
    const tStart = tokenRange?.start || payload.from_date || "—";
    const tEnd = tokenRange?.end || payload.to_date || "—";
    const pts = payload.points || [];
    const overlapDays = (modelPayload?.models || []).reduce(
      (n, m) => n + (m.daily || []).filter(
        (d) =>
          Number.isFinite(Number(d?.usd_per_1m_input)) || Number.isFinite(Number(d?.usd_per_1m_output))
      ).length,
      0
    );
    if (els.unitPriceNote) {
      els.unitPriceNote.textContent = `Actual vs catalog · ${tStart} → ${tEnd} · ${overlapDays} model-days · ${ccy || "USD"}/1M`;
    }
    const labels =
      chartLabels?.length > 0
        ? chartLabels
        : [...new Set((modelPayload?.models || []).flatMap((m) => (m.daily || []).map((d) => d.date)))].sort();
    const labelsFromPts = pts.map((p) => p.date);
    const xLabels = labels.length ? labels : labelsFromPts;
    const models = modelPayload?.models || [];
    let datasetsIn = [
      ...catalogReferenceDatasets(xLabels, models, "catalog_usd_per_1m_input"),
      ...modelLineDatasets(xLabels, models, "usd_per_1m_input"),
    ];
    let datasetsOut = [
      ...catalogReferenceDatasets(xLabels, models, "catalog_usd_per_1m_output"),
      ...modelLineDatasets(xLabels, models, "usd_per_1m_output"),
    ];
    const Ch = window.AppChartStyle?.colors || {};
    if (!datasetsIn.length) {
      const dataIn = pts.map((p) => (p.usd_per_1m_input != null ? Number(p.usd_per_1m_input) : null));
      datasetsIn = [
        {
          label: ccy ? `Project (${ccy}/1M in)` : "Project input",
          data: dataIn,
          borderColor: Ch.input || "#60a5fa",
          backgroundColor: "rgba(96, 165, 250, 0.12)",
          fill: true,
          tension: 0.22,
          pointRadius: 2,
          pointHoverRadius: 4,
          borderWidth: 2.2,
          spanGaps: true,
        },
      ];
    }
    if (!datasetsOut.length) {
      const dataOut = pts.map((p) => (p.usd_per_1m_output != null ? Number(p.usd_per_1m_output) : null));
      datasetsOut = [
        {
          label: ccy ? `Project (${ccy}/1M out)` : "Project output",
          data: dataOut,
          borderColor: Ch.output || "#a78bfa",
          backgroundColor: "rgba(167, 139, 250, 0.12)",
          fill: true,
          tension: 0.22,
          pointRadius: 2,
          pointHoverRadius: 4,
          borderWidth: 2.2,
          spanGaps: true,
        },
      ];
    }
    const hasIn = datasetsIn.some((ds) => (ds.data || []).some((v) => v !== null && Number.isFinite(v)));
    const hasOut = datasetsOut.some((ds) => (ds.data || []).some((v) => v !== null && Number.isFinite(v)));

    const ctxIn = document.getElementById("impliedUnitPriceInputChart")?.getContext("2d");
    const ctxOut = document.getElementById("impliedUnitPriceOutputChart")?.getContext("2d");
    if (!ctxIn || !ctxOut) {
      syncUnitPriceSection();
      return;
    }

    const xTicks = CHART?.xAxisTicks?.(xLabels.length) || {
      color: "#9fb2c7",
      font: { size: 11, weight: "500" },
      autoSkip: true,
      maxTicksLimit: 12,
      maxRotation: 0,
    };

    const yTickFmt = (value) => {
      const n = Number(value);
      if (!Number.isFinite(n)) return String(value);
      const num = fmtUsdAxis(n);
      return ccy ? `${num} ${ccy}` : num;
    };

    const scales = {
      x: { ticks: xTicks, grid: { color: "rgba(255,255,255,0.08)" } },
      y: {
        type: "linear",
        display: true,
        position: "left",
        beginAtZero: true,
        ticks: { color: "#9fb2c7", font: { size: 11, weight: "500" }, callback: yTickFmt },
        grid: { color: "rgba(255,255,255,0.08)" },
        title: {
          display: true,
          text: `${ccy || "Cost"} / 1M`,
          color: "#9fb2c7",
          font: { size: 11 },
        },
      },
    };
    const buildChart = (ctx, datasets, emptyMsg) =>
      new Chart(ctx, {
        type: "line",
        data: {
          labels: xLabels,
          datasets,
        },
        plugins: [...chartPlugins(), emptyStatePluginImplied(emptyMsg)],
        options: {
          ...chartLineDefaults,
          plugins: {
            decimation: { enabled: true, algorithm: "min-max" },
            legend: {
              display: true,
              position: "top",
              labels: {
                color: "#e6edf3",
                font: { size: 12, weight: "600" },
                filter: (item) => item.text != null,
              },
            },
            tooltip: {
              enabled: true,
              backgroundColor: "rgba(11,18,32,0.92)",
              borderColor: "rgba(255,255,255,0.16)",
              borderWidth: 1,
              callbacks: {
                label: (ctx2) => {
                  const v = ctx2.parsed?.y;
                  if (v === null || v === undefined || !Number.isFinite(Number(v))) return `${ctx2.dataset.label}: -`;
                  const isList = ctx2.dataset.catalogReference === true || String(ctx2.dataset.label || "").includes("(list)");
                  let line = `${ctx2.dataset.label}: ${fmtUsdPer1m(v, ccy)}`;
                  if (!isList && models.length) {
                    const modelLabel = String(ctx2.dataset.label || "");
                    const m = models.find((x) => x.model_name === modelLabel);
                    if (m) {
                      const catKey =
                        ctx2.chart?.canvas?.id === "impliedUnitPriceOutputChart"
                          ? "catalog_usd_per_1m_output"
                          : "catalog_usd_per_1m_input";
                      const cat = m[catKey];
                      const pct = pctVsCatalog(v, cat);
                      if (pct != null) {
                        line += ` (${pct >= 0 ? "+" : ""}${pct.toFixed(0)}% vs list)`;
                      }
                    }
                  }
                  return line;
                },
              },
            },
          },
          scales,
        },
      });

    chartImpliedUnitInput = buildChart(ctxIn, datasetsIn, "No input unit-price days with billing overlap");
    chartImpliedUnitOutput = buildChart(ctxOut, datasetsOut, "No output unit-price days with billing overlap");

    if (!hasIn && chartImpliedUnitInput) chartImpliedUnitInput.update();
    if (!hasOut && chartImpliedUnitOutput) chartImpliedUnitOutput.update();
    syncUnitPriceSection();
  }

  const tokenPageRoot = document.querySelector(".tokenPage.dashPage");

  function setLoading(loading) {
    DASH?.setPageLoading?.({
      loading,
      loadBtn: els.loadBtn,
      loadBtnLabel: "Load data",
      loadBtnLoadingLabel: "Loading…",
      pageRoot: tokenPageRoot,
      disableEls: [els.projectSelect, els.startDate, els.endDate],
    });
  }

  function chartPlugins() {
    return CHART?.chartPluginsExtra?.() || DASH?.crosshairPlugins?.() || [];
  }

  function isoDateLocal(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function setDateChipActive(activeId) {
    for (const id of ["dateLast7Btn", "dateLast30Btn", "dateClearBtn"]) {
      const el = document.getElementById(id);
      if (el) el.classList.toggle("is-active", id === activeId);
    }
  }

  function applyDateRangePreset(preset) {
    if (preset === "clear") {
      clearDateFilters();
      setDateChipActive("dateClearBtn");
    } else {
      const days = preset === "7" ? 7 : 30;
      const end = new Date();
      const start = new Date();
      start.setDate(end.getDate() - (days - 1));
      if (els.startDate) els.startDate.value = isoDateLocal(start);
      if (els.endDate) els.endDate.value = isoDateLocal(end);
      setDateChipActive(preset === "7" ? "dateLast7Btn" : "dateLast30Btn");
    }
    loadTokenData();
  }

  function seriesStats(points, key) {
    const vals = (points || [])
      .map((p) => p?.[key])
      .filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v)))
      .map(Number);
    if (!vals.length) return null;
    const sum = vals.reduce((a, b) => a + b, 0);
    return {
      max: Math.max(...vals),
      mean: sum / vals.length,
      min: Math.min(...vals),
    };
  }

  function renderStats(el, stats) {
    if (!stats) {
      el.textContent = "Max: - · Mean: - · Min: -";
      return;
    }
    el.textContent = `Max: ${fmtInt(stats.max)} · Mean: ${fmtInt(stats.mean)} · Min: ${fmtInt(stats.min)}`;
  }

  function applySourceUi(source, series, stats) {
    lastSource = source || "estimated";
    const imported = lastSource === "imported";

    if (els.sourceBadge) {
      els.sourceBadge.hidden = false;
      els.sourceBadge.classList.remove("sourceImported", "sourceEstimated");
      els.sourceBadge.classList.add(imported ? "sourceImported" : "sourceEstimated");
      els.sourceBadgeText.textContent = imported ? "Imported CSV" : "From billing";
    }

    const inputLabel = "Input tokens";
    const outputLabel = "Output tokens";
    const totalLabel = "Total tokens";

    if (els.labelInput) els.labelInput.textContent = inputLabel;
    if (els.labelOutput) els.labelOutput.textContent = outputLabel;
    if (els.labelTotal) els.labelTotal.textContent = totalLabel;
    if (els.chartTitleInput) {
      els.chartTitleInput.textContent = imported ? "Input tokens" : "Input tokens (from billing)";
    }
    if (els.chartTitleOutput) {
      els.chartTitleOutput.textContent = imported ? "Output tokens" : "Output tokens (from billing)";
    }
    if (els.tableHint) {
      els.tableHint.textContent = imported
        ? "One row per model/day — tokens, costs, unit $/1M, and out÷in ratio."
        : "Token volume derived from billing and catalog pricing (no token CSV).";
    }

    chartLabels = {
      input: imported ? "Input tokens" : "Input tokens (from billing)",
      output: imported ? "Output tokens" : "Output tokens (from billing)",
      total: imported ? "Total tokens" : "Total tokens (from billing)",
    };

    if (els.filterHint) {
      els.filterHint.hidden = false;
      const models = (series.import_meta?.models || []).length;
      els.filterHint.textContent = imported
        ? `Imported CSV · ${models} model column(s) · bills/<project>/token/`
        : "Derived from billing × catalog price (no token CSV).";
    }

    if (els.tokenModel) {
      if (imported) {
        const n = (series.import_meta?.models || []).length;
        els.tokenModel.textContent = n ? `${n} model(s)` : "Imported";
      } else {
        els.tokenModel.textContent = series.token_estimate_model || stats.token_estimate_model || "No price match";
      }
    }
    if (els.tokenRegion) {
      els.tokenRegion.textContent = imported
        ? "bills/<project>/token/"
        : `Region: ${series.token_estimate_region || "-"}`;
    }
    if (els.tokenMetaExtra) {
      if (imported && series.import_meta) {
        const days = series.import_meta.day_count ?? "-";
        els.tokenMetaExtra.textContent = `${days} day(s) with token data in range`;
      } else {
        els.tokenMetaExtra.textContent = "";
      }
    }

    if (els.modelPanel) {
      const breakdown = series.breakdown_by_model || [];
      els.modelPanel.hidden = !imported || breakdown.length === 0;
    }
  }

  function pageSizeFromSelect(selectEl, fallback = 25) {
    const v = Number(selectEl?.value);
    return Number.isFinite(v) && v > 0 ? v : fallback;
  }

  function renderPagedSlice({ items, page, pageSize, renderRow, tbodyEl, pageInfoEl, prevBtn, nextBtn, label }) {
    const total = items.length;
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    const safePage = Math.max(1, Math.min(pageCount, Math.floor(page)));
    const offset = (safePage - 1) * pageSize;
    const slice = items.slice(offset, offset + pageSize);

    if (tbodyEl) tbodyEl.innerHTML = "";
    if (!total) {
      if (pageInfoEl) pageInfoEl.textContent = `0 ${label}`;
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      return safePage;
    }

    for (const row of slice) renderRow(row);
    if (prevBtn) prevBtn.disabled = safePage <= 1;
    if (nextBtn) nextBtn.disabled = safePage >= pageCount;
    if (pageInfoEl) pageInfoEl.textContent = `${safePage} / ${pageCount} · ${total} ${label}`;
    return safePage;
  }

  function appendModelRow(row, maxShare) {
    const tr = document.createElement("tr");
    const dir = String(row.token_direction || "").toLowerCase();
    const share = Number(row.share_pct) || 0;
    const widthPct = Math.max(2, Math.round((share / maxShare) * 100));

    const tdModel = document.createElement("td");
    tdModel.textContent = row.model_name || "-";
    const tdDir = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = `dirPill ${dir}`;
    pill.textContent = dir || "-";
    tdDir.appendChild(pill);
    const tdCount = document.createElement("td");
    tdCount.className = "num";
    tdCount.textContent = fmtInt(row.token_count);
    const tdShare = document.createElement("td");
    tdShare.className = "num";
    tdShare.textContent = fmtPct(share);
    const tdBar = document.createElement("td");
    tdBar.className = "barCell";
    const barWrap = document.createElement("div");
    barWrap.className = "shareBar";
    barWrap.title = fmtPct(share);
    const barFill = document.createElement("div");
    barFill.className = `shareBarFill ${dir}`;
    barFill.style.width = `${widthPct}%`;
    barWrap.appendChild(barFill);
    tdBar.appendChild(barWrap);

    tr.append(tdModel, tdDir, tdCount, tdShare, tdBar);
    els.modelTbody.appendChild(tr);
  }

  function renderModelBreakdown(breakdown) {
    if (!els.modelTbody) return;
    lastModelBreakdown = breakdown || [];
    if (!lastModelBreakdown.length) {
      els.modelTbody.innerHTML = "";
      if (els.modelPager) els.modelPager.hidden = true;
      return;
    }

    const pageSize = pageSizeFromSelect(els.modelPageSizeSelect, 25);
    const needsPager = lastModelBreakdown.length > pageSize;
    if (els.modelPager) els.modelPager.hidden = !needsPager;

    const maxShare = Math.max(...lastModelBreakdown.map((r) => Number(r.share_pct) || 0), 1);
    modelPage = renderPagedSlice({
      items: lastModelBreakdown,
      page: modelPage,
      pageSize,
      tbodyEl: els.modelTbody,
      pageInfoEl: els.modelPageInfo,
      prevBtn: els.modelPrevBtn,
      nextBtn: els.modelNextBtn,
      label: "rows",
      renderRow: (row) => appendModelRow(row, maxShare),
    });
  }

  function chartOptions(unitType = "tokens", currency = "", labelCount = 0) {
    const unit = unitType === "usd" ? "currency" : unitType;
    return (
      CHART?.buildChartOptionsForUnit?.({
        unitType: unit,
        currency: currency || lastBillingCurrency,
        labelCount,
        tooltipCallbacks: {
          label: (ctx) => {
            let value = fmtInt(ctx.parsed.y);
            if (unitType === "ratio") value = fmtRatio(ctx.parsed.y);
            if (unitType === "usd") value = fmtUsd(ctx.parsed.y, currency);
            return `${ctx.dataset.label}: ${value}`;
          },
        },
      }) || chartLineDefaults
    );
  }

  function _tokenLineDataset(label, data, color, bg) {
    const n = (data || []).filter((v) => v != null && !Number.isNaN(v)).length;
    const pr = CHART?.pointRadiusForCount?.(n, { sparse: 2, dense: 0 }) ?? 2;
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: bg,
      fill: true,
      tension: 0.28,
      spanGaps: true,
      pointRadius: pr,
      pointHoverRadius: 5,
      borderWidth: 2.2,
    };
  }

  function modelTokenDatasets(labels, dailyByModel, direction) {
    const modelNames = [
      ...new Set((dailyByModel || []).map((r) => r.model_name).filter(Boolean)),
    ].sort();
    if (!modelNames.length) return null;
    const byKey = new Map(
      (dailyByModel || []).map((r) => [`${r.date}\0${r.model_name}`, r])
    );
    const key = direction === "output" ? "output_tokens" : "input_tokens";
    return modelNames.map((name, idx) => {
      const data = labels.map((d) => {
        const row = byKey.get(`${d}\0${name}`);
        const v = row?.[key];
        return v != null && Number(v) > 0 ? Number(v) : null;
      });
      const col = MODEL_CHART_COLORS[idx % MODEL_CHART_COLORS.length];
      return _tokenLineDataset(name, data, col.border, col.fill);
    });
  }

  function modelCostDatasets(labels, dailyByModel, key) {
    const modelNames = [...new Set((dailyByModel || []).map((r) => r.model_name).filter(Boolean))].sort();
    if (!modelNames.length) return null;
    const byKey = new Map((dailyByModel || []).map((r) => [`${r.date}\0${r.model_name}`, r]));
    return modelNames
      .map((name, idx) => {
        const data = labels.map((d) => {
          const row = byKey.get(`${d}\0${name}`);
          const v = row?.[key];
          return v != null && Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : null;
        });
        if (!data.some((v) => v !== null && Number.isFinite(v))) return null;
        const col = MODEL_CHART_COLORS[idx % MODEL_CHART_COLORS.length];
        return _tokenLineDataset(name, data, col.border, col.fill);
      })
      .filter(Boolean);
  }

  function renderTokenUsageCharts(points, dailyByModel) {
    const labels = points.map((p) => p.date);
    const inputDatasets =
      modelTokenDatasets(labels, dailyByModel, "input") || [
        _tokenLineDataset(
          chartLabels.input,
          points.map((p) => p.estimated_input_tokens),
          C.input || "#60a5fa",
          "rgba(96,165,250,0.14)"
        ),
      ];
    const outputDatasets =
      modelTokenDatasets(labels, dailyByModel, "output") || [
        _tokenLineDataset(
          chartLabels.output,
          points.map((p) => p.estimated_output_tokens),
          C.output || "#a78bfa",
          "rgba(167,139,250,0.14)"
        ),
      ];

    const inputCtx = document.getElementById("tokenInputChart")?.getContext("2d");
    if (inputCtx) {
      if (tokenInputChart) tokenInputChart.destroy();
      tokenInputChart = new Chart(inputCtx, {
        type: "line",
        data: { labels, datasets: inputDatasets },
        options: chartOptions("tokens", "", labels.length),
        plugins: chartPlugins(),
      });
    }

    const outputCtx = document.getElementById("tokenOutputChart")?.getContext("2d");
    if (outputCtx) {
      if (tokenOutputChart) tokenOutputChart.destroy();
      tokenOutputChart = new Chart(outputCtx, {
        type: "line",
        data: { labels, datasets: outputDatasets },
        options: chartOptions("tokens", "", labels.length),
        plugins: chartPlugins(),
      });
    }
  }

  function renderTokenCostCharts(points, dailyByModel, currency) {
    const labels = points.map((p) => p.date);
    const inByModel = modelCostDatasets(labels, dailyByModel, "input_cost_usd");
    const outByModel = modelCostDatasets(labels, dailyByModel, "output_cost_usd");

    const inFallback = labels.map((d) =>
      (dailyByModel || [])
        .filter((r) => r.date === d)
        .reduce((acc, r) => acc + (Number(r.input_cost_usd) || 0), 0)
    );
    const outFallback = labels.map((d) =>
      (dailyByModel || [])
        .filter((r) => r.date === d)
        .reduce((acc, r) => acc + (Number(r.output_cost_usd) || 0), 0)
    );

    const inputDatasets =
      inByModel && inByModel.length
        ? inByModel
        : [
            _tokenLineDataset(
              `Input cost (${currency || "USD"})`,
              inFallback.map((v) => (v > 0 ? v : null)),
              "#60a5fa",
              "rgba(96,165,250,0.14)"
            ),
          ];
    const outputDatasets =
      outByModel && outByModel.length
        ? outByModel
        : [
            _tokenLineDataset(
              `Output cost (${currency || "USD"})`,
              outFallback.map((v) => (v > 0 ? v : null)),
              "#a78bfa",
              "rgba(167,139,250,0.14)"
            ),
          ];

    const inputCtx = document.getElementById("tokenInputCostChart")?.getContext("2d");
    if (inputCtx) {
      if (tokenInputCostChart) tokenInputCostChart.destroy();
      tokenInputCostChart = new Chart(inputCtx, {
        type: "line",
        data: { labels, datasets: inputDatasets },
        options: chartOptions("usd", currency, labels.length),
        plugins: chartPlugins(),
      });
    }

    const outputCtx = document.getElementById("tokenOutputCostChart")?.getContext("2d");
    if (outputCtx) {
      if (tokenOutputCostChart) tokenOutputCostChart.destroy();
      tokenOutputCostChart = new Chart(outputCtx, {
        type: "line",
        data: { labels, datasets: outputDatasets },
        options: chartOptions("usd", currency, labels.length),
        plugins: chartPlugins(),
      });
    }
  }

  function renderRatioChart(points) {
    const ratioRows = F.dailyTokenRatio?.(points, {
      inputKey: "estimated_input_tokens",
      outputKey: "estimated_output_tokens",
    }) || [];
    const stats = F.ratioStats?.(ratioRows) || { valid_days: 0, above_1_days: 0, below_1_days: 0 };
    const finiteRatios = ratioRows
      .map((r) => r?.ratio)
      .filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v)))
      .map(Number);
    let rangeText = "";
    if (finiteRatios.length) {
      const rLo = Math.min(...finiteRatios);
      const rHi = Math.max(...finiteRatios);
      const span = rHi - rLo;
      const p = span < 0.02 ? 4 : 3;
      rangeText = ` · Values: ${rLo.toFixed(p)}–${rHi.toFixed(p)}`;
    }
    if (els.ratioSummary) {
      els.ratioSummary.textContent = `Valid days: ${stats.valid_days} · >1: ${stats.above_1_days} · <1: ${stats.below_1_days}${rangeText}`;
    }
    const bounds = F.ratioSuggestedBounds?.(ratioRows) || { min: 0, max: 2 };
    const tickDec = F.ratioYTickDecimals?.(bounds) ?? 3;
    const showParityLine = bounds.max >= 0.55;
    if (els.ratioBaselinePill) els.ratioBaselinePill.hidden = !showParityLine;

    const ctx = document.getElementById("tokenRatioChart").getContext("2d");
    if (tokenRatioChart) tokenRatioChart.destroy();
    const datasets = [
      {
        label: "Output / input",
        data: ratioRows.map((p) => p.ratio),
        borderColor: "#34d399",
        backgroundColor: "rgba(52,211,153,0.12)",
        fill: true,
        tension: 0.22,
        spanGaps: true,
        pointRadius: 2,
        pointHoverRadius: 4,
        borderWidth: 2.2,
      },
    ];
    if (showParityLine) {
      datasets.push({
        label: "Baseline 1.0",
        data: ratioRows.map(() => 1),
        borderColor: "rgba(226,232,240,0.55)",
        borderDash: [4, 4],
        pointRadius: 0,
      });
    }

    const ratioLabels = ratioRows.map((p) => p.date);
    const ratioOpts = chartOptions("ratio", "", ratioLabels.length);
    tokenRatioChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ratioLabels,
        datasets,
      },
      options: {
        ...ratioOpts,
        scales: {
          ...ratioOpts.scales,
          y: {
            ...ratioOpts.scales.y,
            beginAtZero: false,
            min: bounds.min,
            max: bounds.max,
            grace: "0%",
            ticks: {
              maxTicksLimit: 7,
              autoSkip: true,
              callback: (value) => {
                const n = Number(value);
                if (!Number.isFinite(n)) return "";
                return n.toFixed(tickDec);
              },
            },
          },
        },
      },
      plugins: chartPlugins(),
    });
  }

  function renderTable(dailyByModel) {
    if (dailyByModel !== undefined) {
      lastDailyModelRows = (dailyByModel || []).slice();
    }

    if (!lastDailyModelRows.length) {
      els.rowsTbody.innerHTML = "";
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = DAILY_TABLE_COL_COUNT;
      td.className = "muted";
      td.textContent = "No token data in the selected range.";
      tr.appendChild(td);
      els.rowsTbody.appendChild(tr);
      if (els.dailyPageInfo) els.dailyPageInfo.textContent = "0 days";
      if (els.dailyPrevBtn) els.dailyPrevBtn.disabled = true;
      if (els.dailyNextBtn) els.dailyNextBtn.disabled = true;
      updateTableRowBadge(0, 0);
      return;
    }

    const withCostRows = lastDailyModelRows.filter(
      (r) => r.input_cost_usd != null || r.output_cost_usd != null
    ).length;
    updateTableRowBadge(lastDailyModelRows.length, withCostRows);

    const pageSize = pageSizeFromSelect(els.dailyPageSizeSelect, 25);

    dailyPage = renderPagedSlice({
      items: lastDailyModelRows,
      page: dailyPage,
      pageSize,
      tbodyEl: els.rowsTbody,
      pageInfoEl: els.dailyPageInfo,
      prevBtn: els.dailyPrevBtn,
      nextBtn: els.dailyNextBtn,
      label: "rows",
      renderRow: (p) => {
        const tr = document.createElement("tr");
        if (!isMeterAllocated(p.allocation_method)) {
          tr.classList.add("rowNoMeter");
        }
        const tdDate = document.createElement("td");
        tdDate.className = "tdDate";
        tdDate.textContent = p.date || "";

        const tdModel = document.createElement("td");
        tdModel.className = "tdModel";
        const modelLabel = String(p.model_name || "").trim() || "—";
        if (modelLabel === "—") {
          tdModel.textContent = "—";
        } else {
          const span = document.createElement("span");
          span.className = "modelNameLabel";
          span.textContent = modelLabel;
          tdModel.title = modelLabel;
          tdModel.appendChild(span);
        }

        const tdInput = document.createElement("td");
        tdInput.className = "num tdInput";
        tdInput.textContent = fmtInt(p.input_tokens);

        const tdOutput = document.createElement("td");
        tdOutput.className = "num tdOutput";
        tdOutput.textContent = fmtInt(p.output_tokens);

        const tdRatio = document.createElement("td");
        tdRatio.className = "num tdRatio";
        const ratio =
          p.output_input_ratio != null && Number.isFinite(Number(p.output_input_ratio))
            ? Number(p.output_input_ratio)
            : p.input_tokens > 0 && p.output_tokens != null
              ? Number(p.output_tokens) / Number(p.input_tokens)
              : null;
        tdRatio.textContent = fmtRatio(ratio);
        const tdInputCost = document.createElement("td");
        tdInputCost.className = "num tdInputCost";
        tdInputCost.textContent = fmtUsd(p.input_cost_usd, lastBillingCurrency);
        tdInputCost.title = p.allocation_method ? `allocation: ${p.allocation_method}` : "";

        const tdOutputCost = document.createElement("td");
        tdOutputCost.className = "num tdOutputCost";
        tdOutputCost.textContent = fmtUsd(p.output_cost_usd, lastBillingCurrency);
        tdOutputCost.title = p.allocation_method ? `allocation: ${p.allocation_method}` : "";

        const tdTotalCost = document.createElement("td");
        tdTotalCost.className = "num tdTotalCost";
        tdTotalCost.textContent = fmtUsd(p.total_cost_usd, lastBillingCurrency);
        tdTotalCost.title = p.allocation_method ? `allocation: ${p.allocation_method}` : "";

        const tdBilling = document.createElement("td");
        tdBilling.className = "tdBilling";
        const badge = document.createElement("span");
        badge.className = `allocBadge alloc-${String(p.allocation_method || "none").replaceAll("_", "-")}`;
        badge.textContent = allocationLabel(p.allocation_method);
        tdBilling.title =
          p.allocation_method === "no_meter_match"
            ? "No billing Meter matched this model/day — costs and unit prices are not estimated."
            : p.allocation_method === "meter_matched_partial"
              ? "Only one direction had meter rows; the other $/1M is blank."
              : "Input/opt costs summed from transaction Meter rows.";
        tdBilling.appendChild(badge);

        const tdUnitIn = document.createElement("td");
        tdUnitIn.className = "num tdUnitIn";
        if (isMeterAllocated(p.allocation_method) && p.usd_per_1m_input != null) {
          tdUnitIn.textContent = fmtUsdPer1m(p.usd_per_1m_input, lastBillingCurrency);
        } else {
          tdUnitIn.textContent = "—";
          tdUnitIn.title = "Requires meter-matched input billing";
        }

        const tdUnitOut = document.createElement("td");
        tdUnitOut.className = "num tdUnitOut";
        if (isMeterAllocated(p.allocation_method) && p.usd_per_1m_output != null) {
          tdUnitOut.textContent = fmtUsdPer1m(p.usd_per_1m_output, lastBillingCurrency);
        } else {
          tdUnitOut.textContent = "—";
          tdUnitOut.title = "Requires meter-matched output billing";
        }

        tr.append(
          tdDate,
          tdModel,
          tdInput,
          tdOutput,
          tdInputCost,
          tdOutputCost,
          tdTotalCost,
          tdBilling,
          tdUnitIn,
          tdUnitOut,
          tdRatio
        );
        els.rowsTbody.appendChild(tr);
      },
    });
  }

  function csvEscape(v) {
    const s = v === null || v === undefined ? "" : String(v);
    if (/[",\n]/.test(s)) return `"${s.replaceAll('"', '""')}"`;
    return s;
  }

  function exportCsv() {
    const headers = [
      "date",
      "model_name",
      "input_tokens",
      "output_tokens",
      "input_cost_usd",
      "output_cost_usd",
      "total_cost_usd",
      "usd_per_1m_input",
      "usd_per_1m_output",
      "output_input_ratio",
      "allocation_method",
    ];
    const lines = [headers.join(",")];
    for (const r of lastDailyModelRows) {
      const ratio =
        r.output_input_ratio != null
          ? r.output_input_ratio
          : r.input_tokens > 0
            ? Number(r.output_tokens) / Number(r.input_tokens)
            : "";
      const costIn = roundMoney(r.input_cost_usd);
      const costOut = roundMoney(r.output_cost_usd);
      const costTotal = roundMoney(r.total_cost_usd);
      const unitIn = roundMoney(r.usd_per_1m_input);
      const unitOut = roundMoney(r.usd_per_1m_output);
      lines.push(
        [
          r.date,
          r.model_name ?? "",
          r.input_tokens ?? "",
          r.output_tokens ?? "",
          costIn ?? "",
          costOut ?? "",
          costTotal ?? "",
          unitIn ?? "",
          unitOut ?? "",
          ratio,
          r.allocation_method ?? "",
        ]
          .map(csvEscape)
          .join(",")
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = lastSource === "imported" ? "token-usage-imported.csv" : "token-estimates.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function auditCostPipeline(series, dailyRows) {
    const meta = series._cost_meta || {};
    const rows = dailyRows || series.daily_by_model || [];
    const withCost = rows.filter(
      (r) => r.input_cost_usd != null || r.output_cost_usd != null
    ).length;
    console.group("[tokens] cost pipeline");
    console.info("cost_pipeline_version", series.cost_pipeline_version || "(missing — restart serve)");
    console.info("_cost_meta", meta);
    console.info(`rows=${rows.length} with_cost=${withCost}`);
    if (series._cost_trace_sample) {
      console.info("_cost_trace_sample", series._cost_trace_sample);
    }
    rows.slice(0, 5).forEach((r, i) => {
      console.info(`row[${i}]`, r.date, r.model_name, {
        input_cost_usd: r.input_cost_usd,
        output_cost_usd: r.output_cost_usd,
        total_cost_usd: r.total_cost_usd,
        allocation_method: r.allocation_method,
      });
    });
    const noMeter = rows.filter((r) => r.allocation_method === "no_meter_match").length;
    if (rows.length > 0 && withCost === 0) {
      console.warn(
        "All daily costs are null. Restart: COST_DEBUG=1 .venv/bin/python -m app.cli serve --reload --log-level info"
      );
      window.AppShell?.toast?.(
        "No meter-matched billing for this range — unit prices require inp/opt Meter rows. Check billing CSV or Import.",
        "warn",
        9000
      );
    } else if (rows.length > 0 && noMeter > 0 && meta.policy === "meter_only") {
      window.AppShell?.toast?.(
        `${noMeter} row(s) have tokens but no matching billing Meter — costs are not estimated.`,
        "info",
        7000
      );
    }
    console.groupEnd();
  }

  async function loadTokenData() {
    const project = els.projectSelect.value;
    if (!project) return;
    setLoading(true);
    try {
      const statsParams = new URLSearchParams();
      const seriesParams = new URLSearchParams({ granularity: "day" });
      if (els.startDate.value) {
        statsParams.set("from_date", els.startDate.value);
        seriesParams.set("start_date", els.startDate.value);
      }
      if (els.endDate.value) {
        statsParams.set("to_date", els.endDate.value);
        seriesParams.set("end_date", els.endDate.value);
      }

      const stats = await window.AppHttp.getJson(
        `/api/projects/${encodeURIComponent(project)}/stats?${statsParams.toString()}`
      );
      lastBillingCurrency = stats.currency || "USD";
      if (stats.currency) seriesParams.set("currency", stats.currency);
      if (new URLSearchParams(window.location.search).get("cost_debug") === "1") {
        seriesParams.set("cost_debug", "1");
      }

      const series = await window.AppHttp.getJson(
        `/api/projects/${encodeURIComponent(project)}/token-timeseries?${seriesParams.toString()}`
      );
      auditCostPipeline(series, series.daily_by_model || []);

      const source = series.token_data_source || stats.token_data_source || "estimated";
      if (!stats.currency && series.currency) lastBillingCurrency = series.currency;
      const imported = source === "imported";
      if (els.noImportState) els.noImportState.hidden = imported;
      if (els.workspace) els.workspace.hidden = !imported;
      if (!imported) {
        if (els.sourceBadge) els.sourceBadge.hidden = true;
        if (els.dataStatusBar) els.dataStatusBar.hidden = true;
        clearUnitPriceUi();
        if (els.noImportHint) {
          const others = projectsWithImportedTokens.filter((p) => p !== project);
          if (others.length > 0) {
            els.noImportHint.textContent =
              `Project "${project}" has no imported token CSVs. Select a project with token data: ${others.join(", ")}.`;
          } else {
            els.noImportHint.textContent =
              `Project "${project}" has no imported token CSVs. Import input/output files under bills/${project}/token/ on the Import page.`;
          }
        }
        return;
      }
      applySourceUi(source, series, stats);
      updateDataStatusBar(project, stats, series);

      const points = series.points || [];
      dailyPage = 1;
      modelPage = 1;
      els.estimatedInput.textContent = fmtInt(stats.estimated_input_tokens);
      els.estimatedOutput.textContent = fmtInt(stats.estimated_output_tokens);
      els.estimatedTotal.textContent = fmtInt(stats.estimated_total_tokens);
      els.rangeLabel.textContent = `Selected range: ${stats.min_usage_date || "-"} ~ ${stats.max_usage_date || "-"}`;

      try {
        renderModelBreakdown(series.breakdown_by_model || []);
      } catch (e) {
        console.error("renderModelBreakdown failed", e);
      }

      const pricingParams = new URLSearchParams();
      const tokenRangeStart = stats.min_usage_date || els.startDate.value || "";
      const tokenRangeEnd = stats.max_usage_date || els.endDate.value || "";
      if (tokenRangeStart) pricingParams.set("start_date", tokenRangeStart);
      if (tokenRangeEnd) pricingParams.set("end_date", tokenRangeEnd);
      if (stats.currency) pricingParams.set("currency", stats.currency);

      const dailyForPricing = series.daily_by_model || [];
      const chartDates = [...new Set(dailyForPricing.map((r) => r.date))].sort();
      const mpFromTable = modelUnitPricesFromDaily(dailyForPricing);
      let mpCatalog = { available: false };
      try {
        mpCatalog = await window.AppHttp.getJson(
          `/api/projects/${encodeURIComponent(project)}/model-unit-prices?${pricingParams.toString()}`
        );
      } catch (e) {
        console.warn("Catalog list prices unavailable", e);
      }
      const mp = mergeCatalogPrices(mpFromTable, mpCatalog);
      try {
        renderCatalogRefLine(mp, stats.currency);
        renderImpliedUnitPrices(
          { available: true, currency: stats.currency, from_date: tokenRangeStart, to_date: tokenRangeEnd },
          stats.currency,
          { start: tokenRangeStart, end: tokenRangeEnd },
          mp,
          chartDates
        );
      } catch (e) {
        console.error("Unit price charts failed", e);
      }

      try {
        renderTable(series.daily_by_model || []);
      } catch (e) {
        console.error("renderTable failed", e);
      }

      try {
        renderStats(els.inputStats, seriesStats(points, "estimated_input_tokens"));
        renderStats(els.outputStats, seriesStats(points, "estimated_output_tokens"));
        renderStats(els.totalStats, seriesStats(points, "estimated_total_tokens"));
      } catch (e) {
        console.error("renderStats failed", e);
      }
      try {
        renderTokenUsageCharts(points, series.daily_by_model || []);
      } catch (e) {
        console.error("renderTokenUsageCharts failed", e);
      }
      try {
        renderTokenCostCharts(points, series.daily_by_model || [], lastBillingCurrency);
      } catch (e) {
        console.error("renderTokenCostCharts failed", e);
      }
      try {
        renderRatioChart(points);
      } catch (e) {
        console.error("renderRatioChart failed", e);
      }
    } catch (err) {
      console.error(err);
      window.AppShell?.toast?.(`Failed to load token data: ${err?.message || "unknown error"}`, "error", 5200);
    } finally {
      setLoading(false);
    }
  }

  function clearDateFilters() {
    if (els.startDate) els.startDate.value = "";
    if (els.endDate) els.endDate.value = "";
  }

  async function init() {
    setLoading(true);
    clearDateFilters();
    try {
      const data = await window.AppHttp.getJson("/api/projects");
      const projects = data.projects || [];
      projectsWithImportedTokens = data.projects_with_imported_tokens || [];
      const hasProjects = projects.length > 0;
      els.emptyState.hidden = hasProjects;
      if (els.workspace) els.workspace.hidden = !hasProjects;
      els.projectSelect.innerHTML = "";
      for (const p of projects) {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = projectsWithImportedTokens.includes(p) ? `${p} · tokens` : p;
        els.projectSelect.appendChild(opt);
      }
      if (!hasProjects) {
        els.loadBtn.disabled = true;
        return;
      }

      const tokenSet = new Set(projectsWithImportedTokens);
      let defaultProject = projectsWithImportedTokens.find((p) => projects.includes(p)) || null;
      if (!defaultProject) {
        try {
          const latestToken = await window.AppHttp.getJson("/api/projects/latest-token");
          if (latestToken.project_name && projects.includes(latestToken.project_name)) {
            defaultProject = latestToken.project_name;
          }
        } catch (err) {
          console.warn("Latest token project lookup failed", err);
        }
      }
      if (!defaultProject) {
        try {
          const latest = await window.AppHttp.getJson("/api/projects/latest");
          if (latest.project_name && projects.includes(latest.project_name)) {
            defaultProject = latest.project_name;
          }
        } catch (err) {
          console.warn("Latest project lookup failed", err);
        }
      }
      if (defaultProject) {
        els.projectSelect.value = defaultProject;
      } else if (tokenSet.size > 0) {
        const firstWithTokens = projects.find((p) => tokenSet.has(p));
        if (firstWithTokens) els.projectSelect.value = firstWithTokens;
      }
      await loadTokenData();
    } catch (err) {
      console.error(err);
      window.AppShell?.toast?.("Failed to initialize token page", "error", 4200);
    } finally {
      setLoading(false);
    }
  }

  DASH?.bindFilterEnter?.(
    document.querySelector(".tokenPage .filterCard"),
    () => {
      setDateChipActive(null);
      loadTokenData();
    }
  );

  els.loadBtn.addEventListener("click", loadTokenData);
  els.projectSelect.addEventListener("change", () => {
    clearDateFilters();
    loadTokenData();
  });
  for (const input of [els.startDate, els.endDate]) {
    input?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        setDateChipActive(null);
        loadTokenData();
      }
    });
    input?.addEventListener("change", () => setDateChipActive(null));
  }
  document.getElementById("dateLast7Btn")?.addEventListener("click", () => applyDateRangePreset("7"));
  document.getElementById("dateLast30Btn")?.addEventListener("click", () => applyDateRangePreset("30"));
  document.getElementById("dateClearBtn")?.addEventListener("click", () => applyDateRangePreset("clear"));
  els.exportBtn.addEventListener("click", exportCsv);

  if (els.dailyPrevBtn) {
    els.dailyPrevBtn.addEventListener("click", () => {
      dailyPage = Math.max(1, dailyPage - 1);
      renderTable();
    });
  }
  if (els.dailyNextBtn) {
    els.dailyNextBtn.addEventListener("click", () => {
      dailyPage += 1;
      renderTable();
    });
  }
  if (els.dailyPageSizeSelect) {
    els.dailyPageSizeSelect.addEventListener("change", () => {
      dailyPage = 1;
      renderTable();
    });
  }
  if (els.modelPrevBtn) {
    els.modelPrevBtn.addEventListener("click", () => {
      modelPage = Math.max(1, modelPage - 1);
      renderModelBreakdown(lastModelBreakdown);
    });
  }
  if (els.modelNextBtn) {
    els.modelNextBtn.addEventListener("click", () => {
      modelPage += 1;
      renderModelBreakdown(lastModelBreakdown);
    });
  }
  if (els.modelPageSizeSelect) {
    els.modelPageSizeSelect.addEventListener("change", () => {
      modelPage = 1;
      renderModelBreakdown(lastModelBreakdown);
    });
  }

  init();
})();
