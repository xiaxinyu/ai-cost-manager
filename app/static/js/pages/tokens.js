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
    subprojectSelect: document.getElementById("subprojectSelect"),
    subprojectField: document.getElementById("subprojectField"),
    toolbarGrid: document.getElementById("toolbarGrid"),
    startDate: document.getElementById("tokenStartDateInput"),
    endDate: document.getElementById("tokenEndDateInput"),
    loadBtn: document.getElementById("loadTokensBtn"),
    emptyState: document.getElementById("emptyState"),
    workspace: document.getElementById("tokenWorkspace"),
    noImportState: document.getElementById("noImportState"),
    noImportHint: document.getElementById("noImportHint"),
    sourceBadge: document.getElementById("tokenSourceBadge"),
    sourceBadgeText: document.getElementById("tokenSourceBadgeText"),
    dataStatusBar: document.getElementById("dataStatusBar"),
    tokenSummaryLead: document.getElementById("tokenSummaryLead"),
    tokenTrendsLead: document.getElementById("tokenTrendsLead"),
    tokenSourceMeta: document.getElementById("tokenSourceMeta"),
    avgDailyTokens: document.getElementById("avgDailyTokens"),
    activeDaysCount: document.getElementById("activeDaysCount"),
    tokenPeriodRange: document.getElementById("tokenPeriodRange"),
    tokenPeriodFootnote: document.getElementById("tokenPeriodFootnote"),
    metricsFlowLead: document.getElementById("metricsFlowLead"),
    labelInput: document.getElementById("labelInputTokens"),
    labelOutput: document.getElementById("labelOutputTokens"),
    labelTotal: document.getElementById("labelTotalTokens"),
    estimatedInput: document.getElementById("estimatedInputTokens"),
    estimatedOutput: document.getElementById("estimatedOutputTokens"),
    estimatedTotal: document.getElementById("estimatedTotalTokens"),
    inputStats: document.getElementById("inputStats"),
    outputStats: document.getElementById("outputStats"),
    totalStats: document.getElementById("totalStats"),
    tokenModel: document.getElementById("tokenModel"),
    tokenRegion: document.getElementById("tokenRegion"),
    tokenMetaExtra: document.getElementById("tokenMetaExtra"),
    ratioSummary: document.getElementById("ratioSummary"),
    modelPanel: document.getElementById("flowUsage"),
    modelTbody: document.getElementById("modelBreakdownTbody"),
    modelRowBadge: document.getElementById("modelRowBadge"),
    unitPriceSection: document.getElementById("unitPriceSection"),
    catalogRefLine: document.getElementById("catalogRefLine"),
    unitPriceSummaryTbody: document.getElementById("unitPriceSummaryTbody"),
    unitPriceSummaryDate: document.getElementById("unitPriceSummaryDate"),
    modelPager: document.getElementById("modelPager"),
    modelPageSizeSelect: document.getElementById("modelPageSizeSelect"),
    modelPrevBtn: document.getElementById("modelPrevBtn"),
    modelNextBtn: document.getElementById("modelNextBtn"),
    modelPageInfo: document.getElementById("modelPageInfo"),
    subprojectTokenStrip: document.getElementById("subprojectTokenStrip"),
    subprojectTokenCards: document.getElementById("subprojectTokenCards"),
  };

  let tokenInputChart = null;
  let tokenOutputChart = null;
  let tokenRatioChart = null;
  let cacheMatchChart = null;
  let avgLatencyChart = null;
  let modelRequestsChart = null;

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

  let perfModelColorMap = {};
  let perfHiddenModels = new Set();

  function escHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** Grafana dashboard panel order for performance metrics. */
  const GRAFANA_PERF_METRIC_ORDER = ["model_requests", "cache_match_rate", "avg_latency"];

  function setMetricPanelData(metricKey, hasData, emptyMessage) {
    const panel = document.querySelector(`.metricPanel[data-metric-key="${metricKey}"]`);
    if (!panel) return;
    const empty = panel.querySelector("[data-metric-empty]");
    const hosts = panel.querySelectorAll("[data-chart-host]");
    if (empty) {
      empty.hidden = !!hasData;
      if (!hasData && emptyMessage) empty.textContent = emptyMessage;
    }
    hosts.forEach((host) => {
      host.hidden = !hasData;
    });
  }

  function updateMetricPanelScope(project, subproject, range) {
    const scopeLabel = subproject ? `${project} / ${subproject}` : project || "—";
    document.querySelectorAll("[data-metric-scope]").forEach((el) => {
      el.textContent = scopeLabel;
    });
    if (els.metricsFlowLead) {
      const rangeText =
        range?.start && range?.end && range.start !== "—"
          ? ` · ${range.start} → ${range.end}`
          : "";
      if (subproject) {
        els.metricsFlowLead.textContent = `Grafana performance panels · subproject “${subproject}”${rangeText}`;
      } else if (hasSubprojectsScope()) {
        els.metricsFlowLead.textContent = `Grafana performance panels · all subprojects combined${rangeText}`;
      } else {
        els.metricsFlowLead.textContent = `Grafana performance panels · project scope${rangeText}`;
      }
    }
    if (els.tokenTrendsLead) {
      const rangeText =
        range?.start && range?.end && range.start !== "—"
          ? ` · ${range.start} → ${range.end}`
          : "";
      els.tokenTrendsLead.textContent = subproject
        ? `Daily token volume for “${subproject}”${rangeText}.`
        : `Daily input and output volume${rangeText}.`;
    }
  }

  function scopedMetricEmptyMessage(metricLabel, subproject) {
    if (subproject) return `No ${metricLabel} data for subproject “${subproject}”.`;
    return `No ${metricLabel} data for this scope.`;
  }

  function _metricChartUnitLabel(unit) {
    if (unit === "pct") return "%";
    if (unit === "ms") return "ms";
    return "count";
  }

  function _fmtPerfValue(v, unit) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (unit === "pct") return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
    if (unit === "ms") {
      if (n >= 60_000) return `${(n / 60_000).toFixed(2)} min`;
      if (n >= 1000) return `${(n / 1000).toFixed(2)} s`;
      return `${Math.round(n)} ms`;
    }
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(2)}K`;
    return Math.round(n).toLocaleString();
  }

  function _collectPerfModels(metricRoot) {
    const models = new Set();
    const metrics = metricRoot?.metrics || {};
    for (const m of Object.values(metrics)) {
      for (const name of m.models || []) models.add(String(name));
    }
    return [...models].sort();
  }

  function _buildPerfModelColorMap(models) {
    perfModelColorMap = {};
    models.forEach((name, i) => {
      perfModelColorMap[name] = CHART?.modelColorAt?.(i) || { border: C.actual, bg: "rgba(94,234,212,0.16)" };
    });
  }

  function _metricSeriesToChart(metric, modelsOrder) {
    const pts = [...(metric?.points || [])].slice().reverse();
    const models = modelsOrder || metric?.models || [];
    const labels = pts.map((p) => String(p.usage_date || p.recorded_at || "").slice(0, 10));
    const fullLabels = pts.map((p) => String(p.recorded_at || p.usage_date || ""));
    const n = pts.length;
    const pointRadius = CHART?.pointRadiusForCount?.(n) ?? (n <= 45 ? 3 : 0);
    const datasets = models.map((name) => {
      const i = modelsOrder ? modelsOrder.indexOf(name) : (metric?.models || []).indexOf(name);
      const ds =
        CHART?.datasetLineSeries?.({
          label: name,
          data: pts.map((p) => Number(p?.values?.[name] ?? 0)),
          seriesIndex: i >= 0 ? i : 0,
          pointRadius,
        }) || {};
      return { ...ds, perfModel: name, hidden: perfHiddenModels.has(name) };
    });
    return { labels, fullLabels, datasets, points: pts };
  }

  function _yAxisForPerfUnit(unit, datasets) {
    const flat = (datasets || []).flatMap((ds) => ds.data || []).filter((v) => Number.isFinite(Number(v)));
    const maxV = flat.length ? Math.max(...flat.map(Number)) : 0;
    if (unit === "pct") {
      const cap = maxV <= 100 ? Math.max(5, Math.ceil(maxV * 1.2)) : Math.ceil(maxV * 1.12);
      const suggestedMax = maxV <= 100 ? Math.min(100, cap) : cap;
      return CHART?.yAxisPct?.({ suggestedMax }) || { beginAtZero: true };
    }
    if (unit === "ms") return CHART?.yAxisMs?.() || { beginAtZero: true };
    return CHART?.yAxisCount?.() || { beginAtZero: true };
  }

  function _perfLegendClick(_e, legendItem) {
    const label = legendItem?.text;
    if (!label || !lastPerfSeries) return;
    if (perfHiddenModels.has(label)) perfHiddenModels.delete(label);
    else perfHiddenModels.add(label);
    renderPerfCharts(lastPerfSeries);
  }

  function _perfChartOptions(unit, labelCount, fullLabels, datasets) {
    const unitType = unit === "pct" ? "pct" : unit === "ms" ? "ms" : "count";
    return CHART?.buildSeriesLineChartOptions?.({
      unitType,
      labelCount,
      yScale: _yAxisForPerfUnit(unit, datasets),
      legendOnClick: _perfLegendClick,
      tooltipCallbacks: {
        title: (items) => {
          const idx = items?.[0]?.dataIndex;
          const full = idx != null ? fullLabels[idx] : items?.[0]?.label;
          return CHART?.formatFullDate?.(full) || String(full || "");
        },
        label: (ctx) => {
          const v = ctx.parsed?.y;
          return `${ctx.dataset.label}: ${_fmtPerfValue(v, unit)}`;
        },
      },
    }) || chartLineDefaults;
  }

  let lastPerfSeries = null;

  function renderPerfCharts(series, scope = {}) {
    lastPerfSeries = series;
    const subproject = scope.subproject || series?.subproject || selectedSubproject();
    const metricRoot = series?.token_metrics;
    const perfKeys = GRAFANA_PERF_METRIC_ORDER;
    if (!metricRoot?.available) {
      [cacheMatchChart, avgLatencyChart, modelRequestsChart].forEach((ch) => ch?.destroy?.());
      cacheMatchChart = avgLatencyChart = modelRequestsChart = null;
      for (const key of perfKeys) {
        const label = key.replace(/_/g, " ");
        setMetricPanelData(key, false, scopedMetricEmptyMessage(label, subproject));
      }
      return;
    }
    const modelsOrder = _collectPerfModels(metricRoot);
    _buildPerfModelColorMap(modelsOrder);

    const metrics = metricRoot.metrics || {};
    const charts = [
      { key: "model_requests", metric: metrics.model_requests, id: "modelRequestsChart", unit: "count" },
      { key: "cache_match_rate", metric: metrics.cache_match_rate, id: "cacheMatchChart", unit: "pct" },
      { key: "avg_latency", metric: metrics.avg_latency, id: "avgLatencyChart", unit: "ms" },
    ];

    for (const c of charts) {
      const hasPoints = !!(c.metric?.points?.length);
      const label = c.key.replace(/_/g, " ");
      setMetricPanelData(c.key, hasPoints, scopedMetricEmptyMessage(label, subproject));
      const ctx = document.getElementById(c.id)?.getContext?.("2d");
      if (!ctx || !hasPoints) {
        if (c.key === "cache_match_rate" && cacheMatchChart) cacheMatchChart.destroy();
        if (c.key === "avg_latency" && avgLatencyChart) avgLatencyChart.destroy();
        if (c.key === "model_requests" && modelRequestsChart) modelRequestsChart.destroy();
        if (c.key === "cache_match_rate") cacheMatchChart = null;
        if (c.key === "avg_latency") avgLatencyChart = null;
        if (c.key === "model_requests") modelRequestsChart = null;
        continue;
      }
      const chartData = _metricSeriesToChart(c.metric, modelsOrder);
      const unit = c.metric?.unit || c.unit;
      const opts = _perfChartOptions(
        unit,
        chartData.labels.length,
        chartData.fullLabels,
        chartData.datasets
      );

      if (c.key === "cache_match_rate" && cacheMatchChart) cacheMatchChart.destroy();
      if (c.key === "avg_latency" && avgLatencyChart) avgLatencyChart.destroy();
      if (c.key === "model_requests" && modelRequestsChart) modelRequestsChart.destroy();

      const ch = new Chart(ctx, {
        type: "line",
        data: { labels: chartData.labels, datasets: chartData.datasets },
        options: opts,
        plugins: [...(DASH?.crosshairPlugins?.() || [])],
      });
      if (c.key === "cache_match_rate") cacheMatchChart = ch;
      if (c.key === "avg_latency") avgLatencyChart = ch;
      if (c.key === "model_requests") modelRequestsChart = ch;
    }
  }

  let lastSource = "estimated";
  let projectsWithImportedTokens = [];
  let projectDetailsByName = new Map();
  let modelPage = 1;
  let lastModelBreakdown = [];
  let chartLabels = {
    input: "Input tokens",
    output: "Output tokens",
    total: "Total tokens",
  };

  function isMeterAllocated(method) {
    return method === "meter_matched" || method === "meter_matched_partial";
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

  function applySubprojectFilterByName(name) {
    if (!els.subprojectSelect || els.subprojectField?.hidden) return;
    els.subprojectSelect.value = name;
    clearDateFilters();
    loadTokenData();
  }

  function renderSubprojectTokenStrip(series, subproject) {
    if (!els.subprojectTokenStrip || !els.subprojectTokenCards) return;
    if (subproject) {
      els.subprojectTokenStrip.hidden = true;
      els.subprojectTokenCards.replaceChildren();
      return;
    }
    const rows = Array.isArray(series?.subproject_breakdown) ? series.subproject_breakdown : [];
    if (rows.length <= 1) {
      els.subprojectTokenStrip.hidden = true;
      els.subprojectTokenCards.replaceChildren();
      return;
    }
    const totalAll = rows.reduce((s, r) => s + Number(r.total_tokens || 0), 0);
    const frag = document.createDocumentFragment();
    for (const row of rows) {
      const name = String(row.subproject_name || "").trim();
      if (!name) continue;
      const inTok = Number(row.input_tokens || 0);
      const outTok = Number(row.output_tokens || 0);
      const total = Number(row.total_tokens || inTok + outTok);
      const share = totalAll > 0 ? Math.round((total / totalAll) * 1000) / 10 : null;
      const card = document.createElement("article");
      card.className = "card dashSubprojectCard dashSubprojectCard--clickable tokenSubprojectCard";
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute("title", `Filter to ${name}`);
      card.innerHTML = `
        <div class="stat">
          <div class="label dashSubprojectCardLabel">${escHtml(name)}</div>
          <div class="value value--md tokenSubprojectCardTotal">${escHtml(fmtInt(total))}</div>
          <div class="sub tokenStats kpiFootnote tokenSubprojectCardIo">IN ${escHtml(fmtInt(inTok))} · OUT ${escHtml(fmtInt(outTok))}</div>
          <div class="sub tokenStats kpiFootnote">${share != null ? `${share}% of scope` : "—"} · click to filter</div>
        </div>`;
      const apply = () => applySubprojectFilterByName(name);
      card.addEventListener("click", apply);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          apply();
        }
      });
      frag.appendChild(card);
    }
    const cardCount = frag.childNodes.length;
    els.subprojectTokenCards.replaceChildren(frag);
    els.subprojectTokenStrip.hidden = cardCount === 0;
  }

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

  function syncUnitPriceSection() {
    if (!els.unitPriceSection) return;
    const hasTable = els.catalogRefLine && !els.catalogRefLine.hidden;
    els.unitPriceSection.hidden = !hasTable;
  }

  function clearUnitPriceUi() {
    if (els.unitPriceSection) els.unitPriceSection.hidden = true;
    if (els.catalogRefLine) els.catalogRefLine.hidden = true;
    if (els.unitPriceSummaryTbody) els.unitPriceSummaryTbody.innerHTML = "";
    if (els.unitPriceSummaryDate) els.unitPriceSummaryDate.hidden = true;
  }

  function latestMeterDailyRow(daily) {
    const sorted = [...(daily || [])].sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    return (
      sorted.find(
        (d) =>
          (d.usd_per_1m_input != null && Number.isFinite(Number(d.usd_per_1m_input))) ||
          (d.usd_per_1m_output != null && Number.isFinite(Number(d.usd_per_1m_output)))
      ) ||
      sorted[0] ||
      null
    );
  }

  function periodEffectiveUsdPer1m(rows) {
    let inputCost = 0;
    let outputCost = 0;
    let inputTokens = 0;
    let outputTokens = 0;
    for (const row of rows || []) {
      if (!isMeterAllocated(row.allocation_method)) continue;
      const inTok = Number(row.input_tokens) || 0;
      const outTok = Number(row.output_tokens) || 0;
      const inCost = row.input_cost_usd;
      const outCost = row.output_cost_usd;
      if (inCost != null && inTok > 0) {
        inputCost += Number(inCost);
        inputTokens += inTok;
      }
      if (outCost != null && outTok > 0) {
        outputCost += Number(outCost);
        outputTokens += outTok;
      }
    }
    const round = (x) => window.AppMoney?.roundCost?.(x) ?? Math.round(x * 100) / 100;
    return {
      input:
        inputTokens > 0 && inputCost > 0
          ? round((inputCost / inputTokens) * 1_000_000)
          : null,
      output:
        outputTokens > 0 && outputCost > 0
          ? round((outputCost / outputTokens) * 1_000_000)
          : null,
    };
  }

  function periodEffectiveFromModel(model, dailyRows) {
    const fromApi = model?.period_effective_usd_per_1m_input != null || model?.period_effective_usd_per_1m_output != null;
    if (fromApi) {
      return {
        input: model.period_effective_usd_per_1m_input ?? null,
        output: model.period_effective_usd_per_1m_output ?? null,
      };
    }
    const modelRows = (dailyRows || []).filter((r) => r.model_name === model.model_name);
    return periodEffectiveUsdPer1m(modelRows);
  }

  function appendUnitPriceCell(tr, text, { className = "" } = {}) {
    const td = document.createElement("td");
    td.className = ["num", className].filter(Boolean).join(" ");
    td.textContent = text ?? "—";
    tr.appendChild(td);
    return td;
  }

  function renderCatalogRefLine(catalogPayload, currency, dailyRows, periodLabel) {
    if (!els.catalogRefLine || !els.unitPriceSummaryTbody) return;
    const models = (catalogPayload?.models || []).filter(
      (m) => m.catalog_usd_per_1m_input != null || m.catalog_usd_per_1m_output != null
    );
    if (!models.length) {
      els.catalogRefLine.hidden = true;
      els.unitPriceSummaryTbody.innerHTML = "";
      if (els.unitPriceSummaryDate) els.unitPriceSummaryDate.hidden = true;
      syncUnitPriceSection();
      return;
    }

    const ccy = currency || catalogPayload.currency || "USD";
    const frag = document.createDocumentFragment();

    for (const m of models) {
      const periodEff = periodEffectiveFromModel(m, dailyRows);

      const tr = document.createElement("tr");
      tr.className = "unitPriceSummaryRow";

      const tdModel = document.createElement("td");
      tdModel.className = "unitPriceModelCell";
      const code = document.createElement("code");
      code.textContent = m.model_name || "model";
      tdModel.appendChild(code);
      tr.appendChild(tdModel);

      appendUnitPriceCell(tr, fmtUsdPer1m(m.catalog_usd_per_1m_input, ccy), {
        className: "unitPriceList",
      });
      appendUnitPriceCell(tr, fmtUsdPer1m(m.catalog_usd_per_1m_output, ccy), {
        className: "unitPriceList",
      });

      const actualIn =
        periodEff.input != null && Number.isFinite(Number(periodEff.input))
          ? fmtUsdPer1m(periodEff.input, ccy)
          : "—";
      const actualOut =
        periodEff.output != null && Number.isFinite(Number(periodEff.output))
          ? fmtUsdPer1m(periodEff.output, ccy)
          : "—";
      appendUnitPriceCell(tr, actualIn, { className: "unitPriceBilling" });
      appendUnitPriceCell(tr, actualOut, { className: "unitPriceBilling" });

      frag.appendChild(tr);
    }

    els.unitPriceSummaryTbody.replaceChildren(frag);
    if (els.unitPriceSummaryDate) {
      if (periodLabel) {
        els.unitPriceSummaryDate.hidden = false;
        els.unitPriceSummaryDate.textContent = periodLabel;
      } else {
        els.unitPriceSummaryDate.hidden = true;
      }
    }
    els.catalogRefLine.hidden = false;
    syncUnitPriceSection();
  }

  function sumTokenPoints(points) {
    let input = 0;
    let output = 0;
    for (const p of points || []) {
      const inVal = p?.input_tokens ?? p?.estimated_input_tokens;
      const outVal = p?.output_tokens ?? p?.estimated_output_tokens;
      if (inVal != null && Number.isFinite(Number(inVal))) input += Number(inVal);
      if (outVal != null && Number.isFinite(Number(outVal))) output += Number(outVal);
    }
    return { input, output, total: input + output };
  }

  function resolveTokenDateRange(series, stats) {
    const meta = series?.import_meta;
    if (meta?.min_usage_date || meta?.max_usage_date) {
      return {
        start: meta.min_usage_date || "—",
        end: meta.max_usage_date || "—",
      };
    }
    return {
      start: stats?.min_usage_date || els.startDate?.value || "—",
      end: stats?.max_usage_date || els.endDate?.value || "—",
    };
  }

  function updateDataStatusBar(project, stats, series, subproject) {
    if (!els.dataStatusBar) return;
    const rows = series?.daily_by_model || [];
    const meta = series?._cost_meta || {};
    const meterRows =
      meta.rows_meter_matched != null
        ? Number(meta.rows_meter_matched) + Number(meta.rows_meter_partial || 0)
        : rows.filter((r) => isMeterAllocated(r.allocation_method)).length;
    const models = new Set(rows.map((r) => r.model_name).filter(Boolean)).size;
    const range = resolveTokenDateRange(series, stats);
    const ccy = stats?.currency || series?.currency || lastBillingCurrency || "USD";
    const importPath = series?.token_import_path || tokenImportPathLabel(project, subproject);

    const pill = (label, value) => {
      const span = document.createElement("span");
      span.className = "statusPill";
      span.innerHTML = `${label}: <strong>${value}</strong>`;
      return span;
    };

    els.dataStatusBar.innerHTML = "";
    const pills = [
      pill("Range", `${range.start} → ${range.end}`),
      pill("Models", String(models)),
      pill("Billing rows matched", `${meterRows}/${rows.length || 0}`),
      pill("Currency", ccy),
    ];
    if (subproject) pills.splice(1, 0, pill("Subproject", subproject));
    els.dataStatusBar.append(...pills);

    const path = document.createElement("span");
    path.className = "dataStatusPath muted";
    path.textContent = importPath;
    els.dataStatusBar.appendChild(path);
    els.dataStatusBar.hidden = false;
  }

  function updateToolbarGridLayout() {
    if (!els.toolbarGrid) return;
    const hasSubprojects = els.subprojectField && !els.subprojectField.hidden;
    els.toolbarGrid.classList.toggle("toolbarGrid--noSubproject", !hasSubprojects);
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
        input_tokens: row.input_tokens,
        output_tokens: row.output_tokens,
        input_cost_usd: row.input_cost_usd,
        output_cost_usd: row.output_cost_usd,
        allocation_method: row.allocation_method,
        usd_per_1m_input: row.usd_per_1m_input,
        usd_per_1m_output: row.usd_per_1m_output,
      });
    }
    const models = [...byModel.values()].map((m) => {
      const inVals = m.daily.map((d) => d.usd_per_1m_input);
      const outVals = m.daily.map((d) => d.usd_per_1m_output);
      const periodEffective = periodEffectiveUsdPer1m(m.daily);
      return {
        ...m,
        period_effective_usd_per_1m_input: periodEffective.input,
        period_effective_usd_per_1m_output: periodEffective.output,
        stats: {
          period_effective: periodEffective,
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
          period_effective_usd_per_1m_input:
            cat.period_effective_usd_per_1m_input ?? m.period_effective_usd_per_1m_input,
          period_effective_usd_per_1m_output:
            cat.period_effective_usd_per_1m_output ?? m.period_effective_usd_per_1m_output,
        };
      }),
    };
  }

  const tokenPageRoot = document.querySelector(".tokenPage.dashPage");

  function setLoading(loading) {
    DASH?.setPageLoading?.({
      loading,
      loadBtn: els.loadBtn,
      loadBtnLabel: "Load data",
      loadBtnLoadingLabel: "Loading…",
      pageRoot: tokenPageRoot,
      disableEls: [els.projectSelect, els.subprojectSelect, els.startDate, els.endDate],
    });
  }

  function chartPlugins() {
    return CHART?.chartPluginsExtra?.() || DASH?.crosshairPlugins?.() || [];
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

  function countActiveTokenDays(points) {
    if (!Array.isArray(points)) return 0;
    return points.filter((p) => {
      const t = Number(p?.estimated_total_tokens);
      const i = Number(p?.estimated_input_tokens);
      const o = Number(p?.estimated_output_tokens);
      return (
        (Number.isFinite(t) && t > 0) ||
        (Number.isFinite(i) && i > 0) ||
        (Number.isFinite(o) && o > 0)
      );
    }).length;
  }

  function updateSummaryPeriodKpis(stats, series, points) {
    const activeDays =
      series?.import_meta?.day_count ??
      stats?.actual_days ??
      countActiveTokenDays(points);
    const total = Number(stats?.estimated_total_tokens ?? 0);
    if (els.activeDaysCount) {
      els.activeDaysCount.textContent = activeDays > 0 ? String(activeDays) : "—";
    }
    if (els.avgDailyTokens) {
      els.avgDailyTokens.textContent =
        activeDays > 0 && Number.isFinite(total) ? fmtInt(total / activeDays) : "—";
    }
    if (els.tokenPeriodRange) {
      const min = stats?.min_usage_date ?? series?.import_meta?.min_date;
      const max = stats?.max_usage_date ?? series?.import_meta?.max_date;
      els.tokenPeriodRange.textContent =
        min || max ? `${min ?? "—"} – ${max ?? "—"}` : "—";
    }
    if (els.tokenPeriodFootnote) {
      els.tokenPeriodFootnote.textContent = stats?.currency
        ? `${stats.currency} · in-scope dates`
        : "Data range in scope";
    }
  }

  function applySourceUi(source, series, stats, scope = {}) {
    lastSource = source || "estimated";
    const imported = lastSource === "imported";
    const project = scope.project || els.projectSelect?.value || "";
    const subproject = scope.subproject || series.subproject || selectedSubproject();
    const importPath =
      series.token_import_path || tokenImportPathLabel(project, subproject);

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

    chartLabels = {
      input: imported ? "Input tokens" : "Input tokens (from billing)",
      output: imported ? "Output tokens" : "Output tokens (from billing)",
      total: imported ? "Total tokens" : "Total tokens (from billing)",
    };

    if (els.tokenSourceMeta) {
      els.tokenSourceMeta.textContent = imported ? "Imported CSV" : "From billing";
    }

    if (els.tokenSummaryLead) {
      const rangeText =
        stats?.min_usage_date || stats?.max_usage_date
          ? ` · ${stats.min_usage_date || "…"} – ${stats.max_usage_date || "…"}`
          : "";
      if (subproject) {
        els.tokenSummaryLead.textContent = `Period totals for subproject “${subproject}”${rangeText}.`;
      } else if (hasSubprojectsScope()) {
        els.tokenSummaryLead.textContent = `Project-level token totals${rangeText}. Use the subproject filter to drill down.`;
      } else {
        els.tokenSummaryLead.textContent = `Period token totals${rangeText}.`;
      }
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
      if (imported) {
        els.tokenRegion.title = importPath;
        els.tokenRegion.textContent = importPath;
      } else {
        els.tokenRegion.title = "";
        els.tokenRegion.textContent = `Region: ${series.token_estimate_region || "-"}`;
      }
    }
    if (els.tokenMetaExtra) {
      if (imported && series.import_meta) {
        const days = series.import_meta.day_count ?? "-";
        els.tokenMetaExtra.textContent = `${days} days with data in range`;
        els.tokenMetaExtra.hidden = false;
      } else {
        els.tokenMetaExtra.textContent = "";
        els.tokenMetaExtra.hidden = true;
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
      if (els.modelRowBadge) els.modelRowBadge.hidden = true;
      return;
    }

    const models = new Set(lastModelBreakdown.map((r) => r.model_name).filter(Boolean)).size;
    if (els.modelRowBadge) {
      els.modelRowBadge.hidden = false;
      els.modelRowBadge.textContent = `${lastModelBreakdown.length} rows · ${models} model(s)`;
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

  function renderTokenUsageCharts(points, dailyByModel, scope = {}) {
    const subproject = scope.subproject || selectedSubproject();
    const labels = points.map((p) => p.date);
    const inputValues = points.map((p) => p.estimated_input_tokens);
    const outputValues = points.map((p) => p.estimated_output_tokens);
    const hasInput = inputValues.some((v) => v != null && Number(v) > 0);
    const hasOutput = outputValues.some((v) => v != null && Number(v) > 0);
    setMetricPanelData(
      "input_tokens",
      hasInput,
      scopedMetricEmptyMessage("input token", subproject)
    );
    setMetricPanelData(
      "output_tokens",
      hasOutput,
      scopedMetricEmptyMessage("output token", subproject)
    );

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
    const subproject = selectedSubproject();
    setLoading(true);
    try {
      const statsParams = new URLSearchParams();
      const seriesParams = new URLSearchParams({ granularity: "day" });
      if (subproject) {
        statsParams.set("subproject", subproject);
        seriesParams.set("subproject", subproject);
      }
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
      applySourceUi(source, series, stats, { project, subproject });
      const points = series.points || [];
      updateSummaryPeriodKpis(stats, series, points);
      updateDataStatusBar(project, stats, series, subproject);

      const totals = sumTokenPoints(points);
      const hasScopedTokenData = totals.total > 0 || (series.import_meta?.day_count || 0) > 0;
      if (subproject && !hasScopedTokenData) {
        window.AppShell?.toast?.(
          `No imported token data for subproject “${subproject}”. Import CSVs under bills/${project}/token/${subproject}/.`,
          "warn",
          8000
        );
      }

      modelPage = 1;
      els.estimatedInput.textContent = fmtInt(stats.estimated_input_tokens ?? totals.input);
      els.estimatedOutput.textContent = fmtInt(stats.estimated_output_tokens ?? totals.output);
      els.estimatedTotal.textContent = fmtInt(stats.estimated_total_tokens ?? totals.total);
      const range = resolveTokenDateRange(series, stats);
      updateMetricPanelScope(project, subproject, range);
      renderSubprojectTokenStrip(series, subproject);

      try {
        renderModelBreakdown(series.breakdown_by_model || []);
      } catch (e) {
        console.error("renderModelBreakdown failed", e);
      }

      try {
        perfHiddenModels = new Set();
        renderPerfCharts(series, { project, subproject });
      } catch (e) {
        console.error("renderPerf failed", e);
      }

      const tokenRangeStart = range.start !== "—" ? range.start : els.startDate.value || "";
      const tokenRangeEnd = range.end !== "—" ? range.end : els.endDate.value || "";
      const pricingParams = new URLSearchParams();
      if (tokenRangeStart) pricingParams.set("start_date", tokenRangeStart);
      if (tokenRangeEnd) pricingParams.set("end_date", tokenRangeEnd);
      if (stats.currency) pricingParams.set("currency", stats.currency);
      if (subproject) pricingParams.set("subproject", subproject);

      const dailyForPricing = series.daily_by_model || [];
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
      const periodLabel =
        range.start !== "—" && range.end !== "—"
          ? `Period weighted · ${range.start} ~ ${range.end}`
          : "Period weighted";
      try {
        renderCatalogRefLine(mp, stats.currency, dailyForPricing, periodLabel);
      } catch (e) {
        console.error("Unit price summary failed", e);
      }

      try {
        renderStats(els.inputStats, seriesStats(points, "estimated_input_tokens"));
        renderStats(els.outputStats, seriesStats(points, "estimated_output_tokens"));
        renderStats(els.totalStats, seriesStats(points, "estimated_total_tokens"));
      } catch (e) {
        console.error("renderStats failed", e);
      }
      try {
        renderTokenUsageCharts(points, series.daily_by_model || [], { project, subproject });
      } catch (e) {
        console.error("renderTokenUsageCharts failed", e);
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
      window.AppDashboardInteractions?.refreshDashPage?.();
    }
  }

  function hasSubprojectsScope() {
    return Boolean(els.subprojectField && !els.subprojectField.hidden);
  }

  function syncSubprojectOptions(projectName) {
    if (!els.subprojectSelect || !els.subprojectField) return;
    const detail = projectDetailsByName.get(projectName);
    const subprojects = Array.isArray(detail?.subprojects) ? detail.subprojects : [];
    const previous = selectedSubproject();
    els.subprojectSelect.innerHTML = "";
    const allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = "All subprojects";
    els.subprojectSelect.appendChild(allOpt);
    for (const sp of subprojects) {
      const opt = document.createElement("option");
      opt.value = sp;
      opt.textContent = sp;
      els.subprojectSelect.appendChild(opt);
    }
    els.subprojectField.hidden = subprojects.length === 0;
    updateToolbarGridLayout();
    if (previous && subprojects.includes(previous)) {
      els.subprojectSelect.value = previous;
    }
  }

  function selectedSubproject() {
    if (!els.subprojectSelect || els.subprojectField?.hidden) return "";
    return String(els.subprojectSelect.value || "").trim();
  }

  function tokenImportPathLabel(project, subproject) {
    if (subproject) return `bills/${project}/token/${subproject}/`;
    return `bills/${project}/token/`;
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
      const detailsByName = Object.fromEntries(
        (data.project_details || []).filter((d) => d?.name).map((d) => [d.name, d])
      );
      projectDetailsByName = new Map(Object.entries(detailsByName));
      projectsWithImportedTokens = data.projects_with_imported_tokens || [];
      const hasProjects = projects.length > 0;
      els.emptyState.hidden = hasProjects;
      if (els.workspace) els.workspace.hidden = !hasProjects;
      els.projectSelect.innerHTML = "";
      for (const p of projects) {
        const opt = document.createElement("option");
        opt.value = p;
        const detail = detailsByName[p];
        const baseLabel = detail?.display_label || p;
        opt.textContent = projectsWithImportedTokens.includes(p)
          ? `${baseLabel} · tokens`
          : baseLabel;
        if (detail) {
          opt.title = `Folder: ${p}\nPrimary: ${detail.primary_model || "—"}\nToken models: ${(detail.token_models || []).join(", ") || "—"}`;
        }
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
      syncSubprojectOptions(els.projectSelect.value);
      await loadTokenData();
    } catch (err) {
      console.error(err);
      window.AppShell?.toast?.("Failed to initialize token page", "error", 4200);
    } finally {
      setLoading(false);
    }
  }

  window.AppDateRangePicker?.mount({
    startInput: els.startDate,
    endInput: els.endDate,
    autoApply: true,
    onApply: () => loadTokenData(),
  });

  DASH?.bindFilterEnter?.(
    document.querySelector(".tokenPage .filterCard"),
    () => loadTokenData()
  );

  els.loadBtn.addEventListener("click", loadTokenData);
  els.projectSelect.addEventListener("change", () => {
    clearDateFilters();
    syncSubprojectOptions(els.projectSelect.value);
    loadTokenData();
  });
  els.subprojectSelect?.addEventListener("change", () => {
    clearDateFilters();
    loadTokenData();
  });
  for (const input of [els.startDate, els.endDate]) {
    input?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        loadTokenData();
      }
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
