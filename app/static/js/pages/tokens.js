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
    startDate: document.getElementById("startDateInput"),
    endDate: document.getElementById("endDateInput"),
    loadBtn: document.getElementById("loadTokensBtn"),
    emptyState: document.getElementById("emptyState"),
    estimatedInput: document.getElementById("estimatedInputTokens"),
    estimatedOutput: document.getElementById("estimatedOutputTokens"),
    estimatedTotal: document.getElementById("estimatedTotalTokens"),
    inputStats: document.getElementById("inputStats"),
    outputStats: document.getElementById("outputStats"),
    totalStats: document.getElementById("totalStats"),
    tokenModel: document.getElementById("tokenModel"),
    tokenRegion: document.getElementById("tokenRegion"),
    rangeLabel: document.getElementById("rangeLabel"),
    ratioSummary: document.getElementById("ratioSummary"),
    forecastQuality: document.getElementById("forecastQualityTokens"),
    rowsTbody: document.getElementById("tokenRowsTbody"),
    exportBtn: document.getElementById("exportTokensBtn"),
  };

  let tokenActualChart = null;
  let tokenForecastChart = null;
  let tokenRatioChart = null;
  let lastTokenRows = [];
  let lastCurrency = "";

  function fmtInt(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "-";
    return Math.round(Number(v)).toLocaleString();
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
    els.loadBtn.textContent = loading ? "Loading..." : "Load Tokens";
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
        legend: { labels: { boxWidth: 10, color: "#d8e5f4" } },
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

  function renderActualChart(points) {
    const ctx = document.getElementById("tokenActualChart").getContext("2d");
    if (tokenActualChart) tokenActualChart.destroy();
    tokenActualChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: points.map((p) => p.date),
        datasets: [
          {
            label: L.tokenInput || "Estimated Input Tokens",
            data: points.map((p) => p.estimated_input_tokens),
            borderColor: C.input || "#60a5fa",
            backgroundColor: "rgba(96,165,250,0.16)",
            fill: true,
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: L.tokenOutput || "Estimated Output Tokens",
            data: points.map((p) => p.estimated_output_tokens),
            borderColor: C.output || "#a78bfa",
            backgroundColor: "rgba(167,139,250,0.12)",
            fill: true,
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: L.tokenTotal || "Estimated Total Tokens",
            data: points.map((p) => p.estimated_total_tokens),
            borderColor: C.total || "#f59e0b",
            backgroundColor: "rgba(245,158,11,0.10)",
            fill: false,
            tension: 0.25,
            borderWidth: 2.8,
            spanGaps: true,
          },
        ],
      },
      options: chartOptions("tokens"),
    });
  }

  function renderForecastChart(points) {
    const lastDate = points.length ? F.safeDateStr?.(points[points.length - 1].date) || points[points.length - 1].date : "";
    const fcInput = F.forecastNextDaysDOW?.(points, "estimated_input_tokens", lastDate, { windowDays: 28, horizonDays: 7 }) || [];
    const fcOutput = F.forecastNextDaysDOW?.(points, "estimated_output_tokens", lastDate, { windowDays: 28, horizonDays: 7 }) || [];
    const fcTotal = F.forecastNextDaysDOW?.(points, "estimated_total_tokens", lastDate, { windowDays: 28, horizonDays: 7 }) || [];
    const horizon = fcTotal.length ? fcTotal : fcInput.length ? fcInput : fcOutput;
    const labels = points.map((p) => p.date).concat(horizon.map((p) => p.date));

    const byInput = new Map(fcInput.map((x) => [x.date, x.value]));
    const byOutput = new Map(fcOutput.map((x) => [x.date, x.value]));
    const byTotal = new Map(fcTotal.map((x) => [x.date, x.value]));

    function forecastData(byMap, actualKey) {
      const out = labels.map(() => null);
      if (points.length) out[points.length - 1] = points[points.length - 1][actualKey];
      for (let i = points.length; i < labels.length; i += 1) {
        out[i] = byMap.has(labels[i]) ? byMap.get(labels[i]) : null;
      }
      return out;
    }

    const q = F.forecastQuality?.(points, "estimated_total_tokens", { windowDays: 28 });
    renderForecastQuality(q);

    const ctx = document.getElementById("tokenForecastChart").getContext("2d");
    if (tokenForecastChart) tokenForecastChart.destroy();
    tokenForecastChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: L.tokenInputForecast || "Estimated Input Tokens (Forecast 7d)",
            data: forecastData(byInput, "estimated_input_tokens"),
            borderColor: C.input || "#60a5fa",
            borderDash: [5, 4],
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: L.tokenOutputForecast || "Estimated Output Tokens (Forecast 7d)",
            data: forecastData(byOutput, "estimated_output_tokens"),
            borderColor: C.output || "#a78bfa",
            borderDash: [5, 4],
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: L.tokenTotalForecast || "Estimated Total Tokens (Forecast 7d)",
            data: forecastData(byTotal, "estimated_total_tokens"),
            borderColor: C.total || "#f59e0b",
            borderDash: [5, 4],
            borderWidth: 2.6,
            tension: 0.25,
            spanGaps: true,
          },
        ],
      },
      options: chartOptions("tokens"),
    });
  }

  function renderForecastQuality(q) {
    if (!els.forecastQuality) return;
    const level = q?.level || "low";
    const label = level.charAt(0).toUpperCase() + level.slice(1);
    els.forecastQuality.textContent = q ? `Forecast quality: ${label} (${q.valid}/${q.expected})` : "Forecast quality: -";
    els.forecastQuality.classList.remove("qualityHigh", "qualityMedium", "qualityLow");
    els.forecastQuality.classList.add(level === "high" ? "qualityHigh" : level === "medium" ? "qualityMedium" : "qualityLow");
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
            label: "Output/Input",
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
            borderColor: "rgba(226,232,240,0.62)",
            borderDash: [4, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        ...chartOptions("ratio"),
        scales: {
          ...chartOptions("ratio").scales,
          y: {
            ...chartOptions("ratio").scales.y,
            min: bounds.min,
            max: bounds.max,
          },
        },
      },
    });
  }

  function renderTable(points, currency) {
    lastTokenRows = points || [];
    lastCurrency = currency || "";
    els.rowsTbody.innerHTML = "";
    if (!points.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="6" class="muted">No token data in the selected range.</td>';
      els.rowsTbody.appendChild(tr);
      return;
    }

    const ratioByDate = new Map(
      (F.dailyTokenRatio?.(points, { inputKey: "estimated_input_tokens", outputKey: "estimated_output_tokens" }) || []).map((r) => [
        r.date,
        r.ratio,
      ])
    );

    for (const p of points.slice().reverse()) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${p.date || ""}</td>
        <td class="num">${fmtCost(p.cost_usd)} ${currency || ""}</td>
        <td class="num">${fmtInt(p.estimated_input_tokens)}</td>
        <td class="num">${fmtInt(p.estimated_output_tokens)}</td>
        <td class="num">${fmtInt(p.estimated_total_tokens)}</td>
        <td class="num">${fmtRatio(ratioByDate.get(p.date))}</td>
      `;
      els.rowsTbody.appendChild(tr);
    }
  }

  function csvEscape(v) {
    const s = v === null || v === undefined ? "" : String(v);
    if (/[",\n]/.test(s)) return `"${s.replaceAll('"', '""')}"`;
    return s;
  }

  function exportCsv() {
    const headers = ["date", "source_cost", "currency", "estimated_input_tokens", "estimated_output_tokens", "estimated_total_tokens"];
    const lines = [headers.join(",")];
    for (const r of lastTokenRows) {
      lines.push(
        [
          r.date,
          r.cost_usd ?? "",
          lastCurrency,
          r.estimated_input_tokens ?? "",
          r.estimated_output_tokens ?? "",
          r.estimated_total_tokens ?? "",
        ].map(csvEscape).join(",")
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "token-estimates.csv";
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

      updateCurrencyOptions(series.available_currencies || [], currency || series.currency || "");
      const points = series.points || [];
      els.estimatedInput.textContent = fmtInt(stats.estimated_input_tokens);
      els.estimatedOutput.textContent = fmtInt(stats.estimated_output_tokens);
      els.estimatedTotal.textContent = fmtInt(stats.estimated_total_tokens);
      els.tokenModel.textContent = series.token_estimate_model || stats.token_estimate_model || "-";
      els.tokenRegion.textContent = `Region: ${series.token_estimate_region || "-"}`;
      els.rangeLabel.textContent = `Selected range: ${stats.min_usage_date || "-"} ~ ${stats.max_usage_date || "-"}`;

      renderStats(els.inputStats, seriesStats(points, "estimated_input_tokens"));
      renderStats(els.outputStats, seriesStats(points, "estimated_output_tokens"));
      renderStats(els.totalStats, seriesStats(points, "estimated_total_tokens"));
      renderActualChart(points);
      renderForecastChart(points);
      renderRatioChart(points);
      renderTable(points, series.currency || currency);
    } catch (err) {
      console.error(err);
      window.AppShell?.toast?.("Failed to load token data", "error", 4200);
    } finally {
      setLoading(false);
    }
  }

  async function init() {
    setLoading(true);
    try {
      const data = await window.AppHttp.getJson("/api/projects");
      const projects = data.projects || [];
      els.emptyState.hidden = projects.length > 0;
      els.projectSelect.innerHTML = "";
      for (const p of projects) {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        els.projectSelect.appendChild(opt);
      }
      updateCurrencyOptions([], "");

      if (!projects.length) {
        els.loadBtn.disabled = true;
        return;
      }

      try {
        const latest = await window.AppHttp.getJson("/api/projects/latest");
        if (latest.project_name && projects.includes(latest.project_name)) {
          els.projectSelect.value = latest.project_name;
        }
      } catch (err) {
        console.warn("Latest project lookup failed", err);
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
    loadTokenData();
  });
  els.exportBtn.addEventListener("click", exportCsv);

  init();
})();
