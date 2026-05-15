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
    currencySelect: document.getElementById("currencySelect"),
    currencyField: document.getElementById("currencyField"),
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
    thInput: document.getElementById("thInput"),
    thOutput: document.getElementById("thOutput"),
    thTotal: document.getElementById("thTotal"),
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
    modelPanel: document.getElementById("modelBreakdownPanel"),
    modelTbody: document.getElementById("modelBreakdownTbody"),
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
  let lastTokenRows = [];
  let lastCurrency = "";
  let lastSource = "estimated";
  let projectsWithImportedTokens = [];
  let dailyPage = 1;
  let modelPage = 1;
  let lastModelBreakdown = [];
  let lastTableMeta = { ratioByDate: new Map(), showCost: false };
  let chartLabels = {
    input: "Input tokens",
    output: "Output tokens",
    total: "Total tokens",
  };

  function fmtInt(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return Math.round(Number(v)).toLocaleString();
  }

  function fmtPct(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return `${Number(v).toFixed(1)}%`;
  }

  function fmtCost(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function fmtRatio(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return Number(v).toFixed(3);
  }

  function setLoading(loading) {
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
    if (els.thInput) els.thInput.textContent = imported ? "Input" : "Est. input";
    if (els.thOutput) els.thOutput.textContent = imported ? "Output" : "Est. output";
    if (els.thTotal) els.thTotal.textContent = imported ? "Total" : "Est. total";
    if (els.chartTitleInput) {
      els.chartTitleInput.textContent = imported ? "Input tokens (imported)" : "Estimated input tokens";
    }
    if (els.chartTitleOutput) {
      els.chartTitleOutput.textContent = imported ? "Output tokens (imported)" : "Estimated output tokens";
    }
    if (els.tableHint) {
      els.tableHint.textContent = imported
        ? "Token counts from bills/<project>/token/ CSV. Cost column joins billing when dates overlap."
        : "Token counts derived from daily CostUSD and model list prices.";
    }

    chartLabels = {
      input: imported ? "Input tokens" : L.tokenInput || "Estimated input",
      output: imported ? "Output tokens" : L.tokenOutput || "Estimated output",
      total: imported ? "Total tokens" : L.tokenTotal || "Estimated total",
      inputFc: imported ? "Input forecast (7d)" : L.tokenInputForecast || "Input forecast (7d)",
      outputFc: imported ? "Output forecast (7d)" : L.tokenOutputForecast || "Output forecast (7d)",
      totalFc: imported ? "Total forecast (7d)" : L.tokenTotalForecast || "Total forecast (7d)",
    };

    if (els.currencyField) {
      els.currencyField.style.opacity = imported ? "0.55" : "1";
    }
    if (els.filterHint) {
      if (imported) {
        const models = (series.import_meta?.models || []).length;
        els.filterHint.hidden = false;
        els.filterHint.textContent = `Currency filter applies to billing join only. ${models} model column(s) in imported data.`;
      } else {
        els.filterHint.hidden = true;
        els.filterHint.textContent = "";
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

  function updateCurrencyOptions(options, selected) {
    const values = Array.from(new Set((options || []).filter(Boolean)));
    if (selected && !values.includes(selected)) values.unshift(selected);
    els.currencySelect.innerHTML = "";
    const auto = document.createElement("option");
    auto.value = "";
    auto.textContent = values.length ? "Auto" : "No currency";
    els.currencySelect.appendChild(auto);
    for (const c of values) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      els.currencySelect.appendChild(opt);
    }
    els.currencySelect.value = selected || "";
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
              const value = unitType === "ratio" ? fmtRatio(ctx.parsed.y) : fmtInt(ctx.parsed.y);
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

  function renderTokenUsageCharts(points) {
    const labels = points.map((p) => p.date);
    const inputData = points.map((p) => p.estimated_input_tokens);
    const outputData = points.map((p) => p.estimated_output_tokens);

    const inputCtx = document.getElementById("tokenInputChart")?.getContext("2d");
    if (inputCtx) {
      if (tokenInputChart) tokenInputChart.destroy();
      tokenInputChart = new Chart(inputCtx, {
        type: "line",
        data: {
          labels,
          datasets: [
            _tokenLineDataset(
              chartLabels.input,
              inputData,
              C.input || "#60a5fa",
              "rgba(96,165,250,0.14)"
            ),
          ],
        },
        options: chartOptions("tokens"),
      });
    }

    const outputCtx = document.getElementById("tokenOutputChart")?.getContext("2d");
    if (outputCtx) {
      if (tokenOutputChart) tokenOutputChart.destroy();
      tokenOutputChart = new Chart(outputCtx, {
        type: "line",
        data: {
          labels,
          datasets: [
            _tokenLineDataset(
              chartLabels.output,
              outputData,
              C.output || "#a78bfa",
              "rgba(167,139,250,0.14)"
            ),
          ],
        },
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
    els.ratioSummary.textContent = `Valid days: ${stats.valid_days} · >1: ${stats.above_1_days} · <1: ${stats.below_1_days}`;
    const bounds = F.ratioSuggestedBounds?.(ratioRows) || { min: 0, max: 2 };

    const ctx = document.getElementById("tokenRatioChart").getContext("2d");
    if (tokenRatioChart) tokenRatioChart.destroy();
    tokenRatioChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: ratioRows.map((p) => p.date),
        datasets: [
          {
            label: "Output / input",
            data: ratioRows.map((p) => p.ratio),
            borderColor: "#34d399",
            backgroundColor: "rgba(52,211,153,0.12)",
            fill: true,
            tension: 0.22,
            spanGaps: true,
          },
          {
            label: "Baseline 1.0",
            data: ratioRows.map(() => 1),
            borderColor: "rgba(226,232,240,0.55)",
            borderDash: [4, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        ...chartOptions("ratio"),
        scales: {
          ...chartOptions("ratio").scales,
          y: { ...chartOptions("ratio").scales.y, min: bounds.min, max: bounds.max },
        },
      },
    });
  }

  function renderTable(points, currency) {
    if (points !== undefined) {
      lastTokenRows = (points || []).slice().reverse();
      lastCurrency = currency || "";
      const ratioRows =
        F.dailyTokenRatio?.(points, { inputKey: "estimated_input_tokens", outputKey: "estimated_output_tokens" }) || [];
      lastTableMeta = {
        ratioByDate: new Map(ratioRows.map((r) => [r.date, r.ratio])),
        showCost: lastSource !== "imported" || (points || []).some((p) => p.cost_usd != null),
      };
    }

    if (!lastTokenRows.length) {
      els.rowsTbody.innerHTML = "";
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="6" class="muted">No token data in the selected range.</td>';
      els.rowsTbody.appendChild(tr);
      if (els.dailyPageInfo) els.dailyPageInfo.textContent = "0 days";
      if (els.dailyPrevBtn) els.dailyPrevBtn.disabled = true;
      if (els.dailyNextBtn) els.dailyNextBtn.disabled = true;
      return;
    }

    const { ratioByDate, showCost } = lastTableMeta;
    const pageSize = pageSizeFromSelect(els.dailyPageSizeSelect, 25);

    dailyPage = renderPagedSlice({
      items: lastTokenRows,
      page: dailyPage,
      pageSize,
      tbodyEl: els.rowsTbody,
      pageInfoEl: els.dailyPageInfo,
      prevBtn: els.dailyPrevBtn,
      nextBtn: els.dailyNextBtn,
      label: "days",
      renderRow: (p) => {
        const tr = document.createElement("tr");
        const costCell =
          !showCost || p.cost_usd === null || p.cost_usd === undefined
            ? '<span class="muted">—</span>'
            : `${fmtCost(p.cost_usd)} ${currency || ""}`.trim();
        tr.innerHTML = `
        <td>${p.date || ""}</td>
        <td class="num">${costCell}</td>
        <td class="num">${fmtInt(p.estimated_input_tokens)}</td>
        <td class="num">${fmtInt(p.estimated_output_tokens)}</td>
        <td class="num">${fmtInt(p.estimated_total_tokens)}</td>
        <td class="num">${fmtRatio(ratioByDate.get(p.date))}</td>
      `;
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
    const headers = ["date", "data_source", "source_cost", "currency", "input_tokens", "output_tokens", "total_tokens"];
    const lines = [headers.join(",")];
    for (const r of lastTokenRows) {
      lines.push(
        [
          r.date,
          lastSource,
          r.cost_usd ?? "",
          lastCurrency,
          r.estimated_input_tokens ?? "",
          r.estimated_output_tokens ?? "",
          r.estimated_total_tokens ?? "",
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

  async function loadTokenData() {
    const project = els.projectSelect.value;
    if (!project) return;
    setLoading(true);
    try {
      const currency = els.currencySelect.value;
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
      if (currency) {
        statsParams.set("currency", currency);
        seriesParams.set("currency", currency);
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
      updateCurrencyOptions(series.available_currencies || [], currency || series.currency || "");
      applySourceUi(source, series, stats);

      const points = series.points || [];
      dailyPage = 1;
      modelPage = 1;
      els.estimatedInput.textContent = fmtInt(stats.estimated_input_tokens);
      els.estimatedOutput.textContent = fmtInt(stats.estimated_output_tokens);
      els.estimatedTotal.textContent = fmtInt(stats.estimated_total_tokens);
      els.rangeLabel.textContent = `Selected range: ${stats.min_usage_date || "-"} ~ ${stats.max_usage_date || "-"}`;

      renderModelBreakdown(series.breakdown_by_model || []);
      renderStats(els.inputStats, seriesStats(points, "estimated_input_tokens"));
      renderStats(els.outputStats, seriesStats(points, "estimated_output_tokens"));
      renderStats(els.totalStats, seriesStats(points, "estimated_total_tokens"));
      renderTokenUsageCharts(points);
      renderRatioChart(points);
      renderTable(points, series.currency || currency);
    } catch (err) {
      console.error(err);
      window.AppShell?.toast?.("Failed to load token data", "error", 4200);
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
      updateCurrencyOptions([], "");
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
    updateCurrencyOptions([], "");
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
