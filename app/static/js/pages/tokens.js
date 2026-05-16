/* global Chart, window */

(() => {
  const C = window.AppChartStyle?.colors || {};
  const L = window.AppChartStyle?.labels || {};
  const F = window.AppForecasting || {};

  Chart.defaults.font.family = "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";
  Chart.defaults.color = "#e6edf3";
  Chart.defaults.font.size = 12;

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
    impliedUnitPriceHint: document.getElementById("impliedUnitPriceHint"),
    modelUnitPriceHint: document.getElementById("modelUnitPriceHint"),
    modelUnitPriceTbody: document.getElementById("modelUnitPriceTbody"),
    billingPricingSection: document.getElementById("billingPricingSection"),
    impliedChartsRow: document.getElementById("impliedChartsRow"),
    modelPricingCol: document.getElementById("modelPricingCol"),
    billingPricingNote: document.getElementById("billingPricingNote"),
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

  const BILLING_PRICING_NOTE_DEFAULT =
    'Calendar follows imported token dates. Unit is <strong>USD/1M tokens</strong>. Project unit price formula: daily bill ÷ daily input/output tokens. Model blended formula: allocated daily bill ÷ (input + output tokens) by model.';

  let tokenInputChart = null;
  let tokenOutputChart = null;
  let tokenRatioChart = null;
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
  const DAILY_TABLE_COL_COUNT = 5;

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

  function fmtUsdPer1m(n) {
    if (n === null || n === undefined || !Number.isFinite(Number(n))) return "-";
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }

  function syncBillingPricingSection() {
    if (!els.billingPricingSection) return;
    const impH = !els.impliedChartsRow || els.impliedChartsRow.hidden;
    const modH = !els.modelPricingCol || els.modelPricingCol.hidden;
    els.billingPricingSection.hidden = impH && modH;
  }

  function clearBillingPricingUi() {
    if (chartImpliedUnitInput) chartImpliedUnitInput.destroy();
    if (chartImpliedUnitOutput) chartImpliedUnitOutput.destroy();
    chartImpliedUnitInput = null;
    chartImpliedUnitOutput = null;
    if (els.impliedChartsRow) els.impliedChartsRow.hidden = true;
    if (els.modelPricingCol) els.modelPricingCol.hidden = true;
    if (els.billingPricingSection) els.billingPricingSection.hidden = true;
    if (els.modelUnitPriceTbody) els.modelUnitPriceTbody.innerHTML = "";
    if (els.billingPricingNote) els.billingPricingNote.innerHTML = BILLING_PRICING_NOTE_DEFAULT;
  }

  function renderModelUnitPrices(payload, impliedPayload, billingCurrency) {
    if (!els.modelPricingCol || !els.modelUnitPriceTbody) return;
    els.modelUnitPriceTbody.innerHTML = "";
    if (!payload?.available) {
      els.modelPricingCol.hidden = true;
      if (els.modelUnitPriceHint) {
        els.modelUnitPriceHint.textContent =
          payload?.reason === "no_imported_tokens"
            ? "Import token CSVs under bills/<project>/token/"
            : "";
      }
      syncBillingPricingSection();
      return;
    }
    els.modelPricingCol.hidden = false;
    const ccy = billingCurrency || payload.currency || impliedPayload?.currency || "USD";
    const unitLabel = `${ccy}/1M tokens`;
    if (els.modelUnitPriceHint) {
      els.modelUnitPriceHint.textContent = `Table unit: ${unitLabel}`;
    }
    const impliedRows = [
      { label: "Project unit price (input)", st: impliedPayload?.stats?.input },
      { label: "Project unit price (output)", st: impliedPayload?.stats?.output },
    ];
    for (const row of impliedRows) {
      if (!row.st || !row.st.count) continue;
      const tr = document.createElement("tr");
      tr.innerHTML = `
            <td>(Project total)</td>
            <td>${row.label}</td>
            <td class="num">${fmtUsdPer1m(row.st.min)}</td>
            <td class="num">${fmtUsdPer1m(row.st.max)}</td>
            <td class="num">${fmtUsdPer1m(row.st.mean)}</td>
            <td class="num">${fmtUsdPer1m(row.st.median)}</td>
            <td class="num">${row.st.count}</td>
            <td class="num">—</td>
            <td class="num">—</td>
          `;
      els.modelUnitPriceTbody.appendChild(tr);
    }
    const metrics = [{ key: "blended", label: "Blended (allocated)", catalogIn: "catalog_usd_per_1m_input", catalogOut: "catalog_usd_per_1m_output" }];
    for (const model of payload.models || []) {
      for (const m of metrics) {
        const st = model.stats?.[m.key];
        const tr = document.createElement("tr");
        const cin = model[m.catalogIn] != null ? fmtUsdPer1m(model[m.catalogIn]) : "—";
        const cout = model[m.catalogOut] != null ? fmtUsdPer1m(model[m.catalogOut]) : "—";
        const hasOverlap = !!(st && st.count);
        tr.innerHTML = `
              <td>${model.model_name || "-"}</td>
              <td>${hasOverlap ? m.label : `${m.label} (no billing overlap)`}</td>
              <td class="num">${hasOverlap ? fmtUsdPer1m(st.min) : "—"}</td>
              <td class="num">${hasOverlap ? fmtUsdPer1m(st.max) : "—"}</td>
              <td class="num">${hasOverlap ? fmtUsdPer1m(st.mean) : "—"}</td>
              <td class="num">${hasOverlap ? fmtUsdPer1m(st.median) : "—"}</td>
              <td class="num">${hasOverlap ? st.count : 0}</td>
              <td class="num">${cin}</td>
              <td class="num">${cout}</td>
            `;
        els.modelUnitPriceTbody.appendChild(tr);
      }
    }
    if (!els.modelUnitPriceTbody.children.length) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td colspan="9" class="muted">No token data in selected window.</td>';
      els.modelUnitPriceTbody.appendChild(tr);
    }
    syncBillingPricingSection();
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
      });
    });
    return datasets;
  }

  function renderImpliedUnitPrices(payload, billingCurrency, tokenRange, modelPayload) {
    if (!els.impliedChartsRow) return;
    if (chartImpliedUnitInput) chartImpliedUnitInput.destroy();
    if (chartImpliedUnitOutput) chartImpliedUnitOutput.destroy();
    chartImpliedUnitInput = null;
    chartImpliedUnitOutput = null;
    if (!payload?.available) {
      els.impliedChartsRow.hidden = true;
      if (els.impliedUnitPriceHint) {
        els.impliedUnitPriceHint.textContent =
          payload?.reason === "no_imported_tokens"
            ? "Import token CSVs under bills/<project>/token/"
            : "";
      }
      if (els.billingPricingNote) els.billingPricingNote.innerHTML = BILLING_PRICING_NOTE_DEFAULT;
      syncBillingPricingSection();
      return;
    }

    els.impliedChartsRow.hidden = false;
    const ccy = billingCurrency || payload.currency || "";
    const tStart = tokenRange?.start || payload.from_date || "—";
    const tEnd = tokenRange?.end || payload.to_date || "—";
    const pts = payload.points || [];
    const overlapDays = pts.filter(
      (p) =>
        Number.isFinite(Number(p?.usd_per_1m_input)) || Number.isFinite(Number(p?.usd_per_1m_output))
    ).length;
    if (els.impliedUnitPriceHint) {
      els.impliedUnitPriceHint.textContent = `Token window: ${tStart} → ${tEnd} · overlap days: ${overlapDays} · ${ccy || "-"} / 1M`;
    }
    if (els.billingPricingNote) {
      els.billingPricingNote.innerHTML = `Imported-token calendar: <strong>${tStart}</strong> → <strong>${tEnd}</strong>. Unified table includes project unit-price rows + model blended rows in the same unit (<strong>${ccy || "USD"}/1M tokens</strong>).`;
    }
    const labels = pts.map((p) => p.date);
    const models = modelPayload?.models || [];
    let datasetsIn = modelLineDatasets(labels, models, "usd_per_1m_input");
    let datasetsOut = modelLineDatasets(labels, models, "usd_per_1m_output");
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
      syncBillingPricingSection();
      return;
    }

    const xTicks = {
      color: "#9fb2c7",
      font: { size: 11, weight: "500" },
      autoSkip: true,
      maxTicksLimit: 12,
      maxRotation: 0,
    };

    const yTickFmt = (value) => {
      const n = Number(value);
      if (!Number.isFinite(n)) return String(value);
      return fmtUsdPer1m(n);
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
          labels,
          datasets,
        },
        options: {
          ...chartLineDefaults,
          plugins: {
            decimation: { enabled: true, algorithm: "min-max" },
            legend: { display: true, position: "top", labels: { color: "#e6edf3", font: { size: 12, weight: "600" } } },
            tooltip: {
              enabled: true,
              backgroundColor: "rgba(11,18,32,0.92)",
              borderColor: "rgba(255,255,255,0.16)",
              borderWidth: 1,
              callbacks: {
                label: (ctx2) => {
                  const v = ctx2.parsed?.y;
                  if (v === null || v === undefined || !Number.isFinite(Number(v))) return `${ctx2.dataset.label}: -`;
                  const u = ccy ? ` ${ccy}` : "";
                  return `${ctx2.dataset.label}: ${fmtUsdPer1m(v)}${u}`;
                },
              },
            },
          },
          scales,
        },
        plugins: [emptyStatePluginImplied(emptyMsg)],
      });

    chartImpliedUnitInput = buildChart(ctxIn, datasetsIn, "No input unit-price days with billing overlap");
    chartImpliedUnitOutput = buildChart(ctxOut, datasetsOut, "No output unit-price days with billing overlap");

    if (!hasIn && chartImpliedUnitInput) chartImpliedUnitInput.update();
    if (!hasOut && chartImpliedUnitOutput) chartImpliedUnitOutput.update();
    syncBillingPricingSection();
  }

  function setLoading(loading) {
    if (!els.loadBtn) return;
    els.loadBtn.disabled = loading;
    els.loadBtn.textContent = loading ? "Loading…" : "Load Tokens";
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
      els.sourceBadgeText.textContent = imported ? "Imported CSV" : "Cost estimate";
    }

    const inputLabel = imported ? "Input tokens (actual)" : "Estimated input";
    const outputLabel = imported ? "Output tokens (actual)" : "Estimated output";
    const totalLabel = imported ? "Total tokens (actual)" : "Estimated total";

    if (els.labelInput) els.labelInput.textContent = inputLabel;
    if (els.labelOutput) els.labelOutput.textContent = outputLabel;
    if (els.labelTotal) els.labelTotal.textContent = totalLabel;
    if (els.chartTitleInput) {
      els.chartTitleInput.textContent = imported ? "Input tokens (imported)" : "Estimated input tokens";
    }
    if (els.chartTitleOutput) {
      els.chartTitleOutput.textContent = imported ? "Output tokens (imported)" : "Estimated output tokens";
    }
    if (els.tableHint) {
      els.tableHint.textContent = imported
        ? "One row per day: input, output, and output/input ratio."
        : "Estimated daily input/output and output/input ratio from billing costs.";
    }

    chartLabels = {
      input: imported ? "Input tokens" : L.tokenInput || "Estimated input",
      output: imported ? "Output tokens" : L.tokenOutput || "Estimated output",
      total: imported ? "Total tokens" : L.tokenTotal || "Estimated total",
      inputFc: imported ? "Input forecast (7d)" : L.tokenInputForecast || "Input forecast (7d)",
      outputFc: imported ? "Output forecast (7d)" : L.tokenOutputForecast || "Output forecast (7d)",
      totalFc: imported ? "Total forecast (7d)" : L.tokenTotalForecast || "Total forecast (7d)",
    };

    if (els.filterHint) {
      els.filterHint.hidden = false;
      const models = (series.import_meta?.models || []).length;
      els.filterHint.textContent = imported
        ? `Token-only view from bills/<project>/token/. ${models} model column(s) in imported data.`
        : "Token-only estimates from pricing model (input/output ratio view).";
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

  function chartOptions(unitType = "tokens") {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { boxWidth: 10, color: "#d8e5f4", padding: 14 } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const value =
                unitType === "ratio" ? fmtRatio(ctx.parsed.y) : fmtInt(ctx.parsed.y);
              return `${ctx.dataset.label}: ${value}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { color: "rgba(173,196,228,0.08)" }, ticks: { maxRotation: 0, autoSkip: true } },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(173,196,228,0.10)" },
          ticks: { callback: (v) => (unitType === "ratio" ? Number(v).toFixed(1) : fmtInt(v)) },
        },
      },
    };
  }

  function _tokenLineDataset(label, data, color, bg) {
    return {
      label,
      data,
      borderColor: color,
      backgroundColor: bg,
      fill: true,
      tension: 0.28,
      spanGaps: true,
      pointRadius: 2,
      pointHoverRadius: 4,
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
        options: chartOptions("tokens"),
      });
    }

    const outputCtx = document.getElementById("tokenOutputChart")?.getContext("2d");
    if (outputCtx) {
      if (tokenOutputChart) tokenOutputChart.destroy();
      tokenOutputChart = new Chart(outputCtx, {
        type: "line",
        data: { labels, datasets: outputDatasets },
        options: chartOptions("tokens"),
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

    tokenRatioChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ratioRows.map((p) => p.date),
        datasets,
      },
      options: {
        ...chartOptions("ratio"),
        scales: {
          ...chartOptions("ratio").scales,
          y: {
            ...chartOptions("ratio").scales.y,
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
      return;
    }

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
        const tdDate = document.createElement("td");
        tdDate.className = "tdDate";
        tdDate.textContent = p.date || "";

        const tdModel = document.createElement("td");
        tdModel.className = "tdModel";
        tdModel.textContent = p.model_name || "—";

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

        tr.append(tdDate, tdModel, tdInput, tdOutput, tdRatio);
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
    const headers = ["date", "model_name", "input_tokens", "output_tokens", "output_input_ratio"];
    const lines = [headers.join(",")];
    for (const r of lastDailyModelRows) {
      const ratio =
        r.output_input_ratio != null
          ? r.output_input_ratio
          : r.input_tokens > 0
            ? Number(r.output_tokens) / Number(r.input_tokens)
            : "";
      lines.push(
        [r.date, r.model_name ?? "", r.input_tokens ?? "", r.output_tokens ?? "", ratio]
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

      const [stats, series] = await Promise.all([
        window.AppHttp.getJson(`/api/projects/${encodeURIComponent(project)}/stats?${statsParams.toString()}`),
        window.AppHttp.getJson(`/api/projects/${encodeURIComponent(project)}/token-timeseries?${seriesParams.toString()}`),
      ]);

      const source = series.token_data_source || stats.token_data_source || "estimated";
      const imported = source === "imported";
      if (els.noImportState) els.noImportState.hidden = imported;
      if (els.workspace) els.workspace.hidden = !imported;
      if (!imported) {
        if (els.sourceBadge) els.sourceBadge.hidden = true;
        clearBillingPricingUi();
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

      let mp = { available: false };
      try {
        mp = await window.AppHttp.getJson(
          `/api/projects/${encodeURIComponent(project)}/model-unit-prices?${pricingParams.toString()}`
        );
      } catch (e) {
        console.warn("Model unit prices unavailable", e);
      }
      let ip = { available: false };
      try {
        ip = await window.AppHttp.getJson(
          `/api/projects/${encodeURIComponent(project)}/implied-unit-prices-timeseries?${pricingParams.toString()}`
        );
      } catch (e) {
        console.warn("Implied unit price series unavailable", e);
      }
      try {
        renderImpliedUnitPrices(ip, stats.currency, { start: tokenRangeStart, end: tokenRangeEnd }, mp);
        renderModelUnitPrices(mp, ip, stats.currency);
      } catch (e) {
        console.error("Billing pricing panels failed", e);
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
        renderRatioChart(points);
      } catch (e) {
        console.error("renderRatioChart failed", e);
      }
      try {
        renderTable(series.daily_by_model || []);
      } catch (e) {
        console.error("renderTable failed", e);
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

  els.loadBtn.addEventListener("click", loadTokenData);
  els.projectSelect.addEventListener("change", () => {
    clearDateFilters();
    loadTokenData();
  });
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
