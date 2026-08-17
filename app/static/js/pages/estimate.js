/* global window, document, Chart */
(() => {
  const HORIZONS = [
    { key: "day", days: 1, label: "1 day" },
    { key: "week", days: 7, label: "7 days" },
    { key: "month", days: 30, label: "30 days" },
    { key: "year", days: 365, label: "365 days" },
  ];

  const SCENARIO_PRESETS = {
    solo: { input: 2_000_000, output: 200_000, team: "1" },
    team5: { input: 1_000_000, output: 100_000, team: "5" },
    team10: { input: 500_000, output: 50_000, team: "10" },
  };

  const EMPTY_HINT =
    "Need: model + daily Input/Output tokens per person (use a preset or auto-fill from history)";

  const els = {
    modelSelect: document.getElementById("projModelSelect"),
    inputTokens: document.getElementById("projInputTokens"),
    outputTokens: document.getElementById("projOutputTokens"),
    teamSelect: document.getElementById("projTeamSizeSelect"),
    teamCustomField: document.getElementById("projTeamSizeCustomField"),
    teamCustom: document.getElementById("projTeamSizeCustom"),
    hint: document.getElementById("estimateHint"),
    statusBar: document.getElementById("estimateStatusBar"),
    loadBtn: document.getElementById("estimateLoadRatesBtn"),
    tbody: document.getElementById("reportCostProjectionTbody"),
    ratesCard: document.getElementById("estimateRatesCard"),
    ratesTbody: document.getElementById("estimateRatesTbody"),
    rateStrip: document.getElementById("estimateRateStrip"),
    marketRates: document.getElementById("estimateMarketRates"),
    opexRates: document.getElementById("estimateOpexRates"),
    chartWrap: document.getElementById("estimateChartWrap"),
    chartCanvas: document.getElementById("estimateMarketOpexChart"),
    kpi: {
      day: {
        market: document.getElementById("estimateKpiDayMarket"),
        opex: document.getElementById("estimateKpiDayOpex"),
      },
      week: {
        market: document.getElementById("estimateKpiWeekMarket"),
        opex: document.getElementById("estimateKpiWeekOpex"),
      },
      month: {
        market: document.getElementById("estimateKpiMonthMarket"),
        opex: document.getElementById("estimateKpiMonthOpex"),
      },
      year: {
        market: document.getElementById("estimateKpiYearMarket"),
        opex: document.getElementById("estimateKpiYearOpex"),
      },
    },
  };

  let unitRateModels = [];
  let unitRateDailyRows = [];
  let currency = "USD";
  let marketOpexChart = null;
  let autoFillAppliedFor = "";
  let applyingPreset = false;

  function fmtMoney(n) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    return window.AppMoney?.fmtCost(n, currency) ?? Number(n).toFixed(2);
  }

  function fmtRatePair(rateIn, rateOut) {
    const a = rateIn != null && Number.isFinite(Number(rateIn)) ? fmtMoney(rateIn) : "—";
    const b = rateOut != null && Number.isFinite(Number(rateOut)) ? fmtMoney(rateOut) : "—";
    return `In ${a} · Out ${b}`;
  }

  function fmtDelta(opexTotal, marketTotal) {
    if (
      opexTotal == null ||
      marketTotal == null ||
      !Number.isFinite(Number(opexTotal)) ||
      !Number.isFinite(Number(marketTotal))
    ) {
      return "—";
    }
    const d = Number(opexTotal) - Number(marketTotal);
    const rounded = window.AppMoney?.roundCost?.(d) ?? Math.round(d * 100) / 100;
    const sign = rounded > 0 ? "+" : "";
    return `${sign}${fmtMoney(rounded)}`;
  }

  function syncTeamCustomVisibility() {
    const isCustom = els.teamSelect?.value === "custom";
    if (els.teamCustomField) els.teamCustomField.hidden = !isCustom;
  }

  function currentTeamSize() {
    const mode = els.teamSelect?.value || "1";
    if (mode === "custom") {
      const n = Number(els.teamCustom?.value);
      if (!Number.isFinite(n) || n < 1) return 1;
      return Math.floor(n);
    }
    const n = Number(mode);
    return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
  }

  function setStatus(text, { hidden = false } = {}) {
    if (!els.statusBar) return;
    els.statusBar.hidden = hidden || !text;
    els.statusBar.textContent = text || "";
  }

  function tokensEmpty() {
    return (els.inputTokens?.value === "" || els.inputTokens?.value == null) &&
      (els.outputTokens?.value === "" || els.outputTokens?.value == null);
  }

  function avgDailyTokensForModel(modelName) {
    const rows = (unitRateDailyRows || []).filter((r) => r.model_name === modelName);
    if (!rows.length) return null;
    const byDate = new Map();
    for (const row of rows) {
      const d = String(row.date || row.usage_date || "");
      if (!d) continue;
      const cur = byDate.get(d) || { inTok: 0, outTok: 0 };
      cur.inTok += Number(row.input_tokens) || 0;
      cur.outTok += Number(row.output_tokens) || 0;
      byDate.set(d, cur);
    }
    if (!byDate.size) return null;
    let sumIn = 0;
    let sumOut = 0;
    let days = 0;
    for (const v of byDate.values()) {
      if (v.inTok <= 0 && v.outTok <= 0) continue;
      sumIn += v.inTok;
      sumOut += v.outTok;
      days += 1;
    }
    if (!days) return null;
    return {
      input: Math.round(sumIn / days),
      output: Math.round(sumOut / days),
      days,
    };
  }

  function maybeAutoFillTokens(modelName) {
    if (!modelName || applyingPreset) return false;
    if (!tokensEmpty()) return false;
    if (autoFillAppliedFor === modelName) return false;
    const avg = avgDailyTokensForModel(modelName);
    if (!avg) return false;
    if (els.inputTokens) els.inputTokens.value = String(avg.input);
    if (els.outputTokens) els.outputTokens.value = String(avg.output);
    autoFillAppliedFor = modelName;
    setStatus(
      `Auto-filled avg daily tokens from ${avg.days} day(s) of history · ${avg.input.toLocaleString()} in / ${avg.output.toLocaleString()} out`
    );
    return true;
  }

  function applyPreset(key) {
    const preset = SCENARIO_PRESETS[key];
    if (!preset) return;
    applyingPreset = true;
    try {
      if (els.inputTokens) els.inputTokens.value = String(preset.input);
      if (els.outputTokens) els.outputTokens.value = String(preset.output);
      if (els.teamSelect) {
        els.teamSelect.value = preset.team;
        syncTeamCustomVisibility();
      }
      for (const btn of document.querySelectorAll(".estimatePresetBtn")) {
        btn.classList.toggle("is-active", btn.dataset.preset === key);
      }
      autoFillAppliedFor = els.modelSelect?.value || "";
      if (!els.modelSelect?.value) {
        if (els.hint) {
          els.hint.textContent =
            "Preset applied · select a model to project Market vs OpEx";
        }
        clearResults();
        syncUrlState();
        return;
      }
      refreshProjection();
    } finally {
      applyingPreset = false;
    }
  }

  function populateModelOptions(models, preferred) {
    if (!els.modelSelect) return;
    const prev = preferred || els.modelSelect.value;
    els.modelSelect.replaceChildren();
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Select a model…";
    els.modelSelect.appendChild(opt0);
    for (const m of models || []) {
      const name = m.model_name;
      if (!name) continue;
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      els.modelSelect.appendChild(opt);
    }
    if (prev && [...els.modelSelect.options].some((o) => o.value === prev)) {
      els.modelSelect.value = prev;
    }
  }

  function currentModelRates() {
    const name = els.modelSelect?.value || "";
    if (!name) return null;
    const model = unitRateModels.find((m) => m.model_name === name);
    if (!model) return null;
    const market =
      window.AppUnitPriceTable?.resolveModelRates?.(model, unitRateDailyRows, "market") || {};
    const opex =
      window.AppUnitPriceTable?.resolveModelRates?.(model, unitRateDailyRows, "opex") || {};
    return {
      modelName: name,
      marketIn: market.rateIn ?? null,
      marketOut: market.rateOut ?? null,
      opexIn: opex.rateIn ?? null,
      opexOut: opex.rateOut ?? null,
    };
  }

  function updateRateStrip(rates) {
    if (!els.rateStrip) return;
    if (!rates) {
      els.rateStrip.hidden = true;
      if (els.marketRates) els.marketRates.textContent = "—";
      if (els.opexRates) els.opexRates.textContent = "—";
      return;
    }
    els.rateStrip.hidden = false;
    if (els.marketRates) els.marketRates.textContent = fmtRatePair(rates.marketIn, rates.marketOut);
    if (els.opexRates) els.opexRates.textContent = fmtRatePair(rates.opexIn, rates.opexOut);
  }

  function destroyChart() {
    if (marketOpexChart) {
      marketOpexChart.destroy();
      marketOpexChart = null;
    }
    if (els.chartWrap) els.chartWrap.hidden = true;
  }

  function updateChart(marketProj, opexProj) {
    if (!els.chartCanvas || typeof Chart === "undefined") {
      destroyChart();
      return;
    }
    if (!marketProj && !opexProj) {
      destroyChart();
      return;
    }
    const labels = HORIZONS.map((h) => h.label);
    const marketData = HORIZONS.map((h) => {
      if (!marketProj) return null;
      const v = Number(window.AppMoney?.roundCost?.(marketProj.day * h.days) ?? marketProj.day * h.days);
      return Number.isFinite(v) && v > 0 ? v : null;
    });
    const opexData = HORIZONS.map((h) => {
      if (!opexProj) return null;
      const v = Number(window.AppMoney?.roundCost?.(opexProj.day * h.days) ?? opexProj.day * h.days);
      return Number.isFinite(v) && v > 0 ? v : null;
    });
    if (els.chartWrap) els.chartWrap.hidden = false;
    const datasets = [
      {
        label: "Market",
        data: marketData,
        backgroundColor: "rgba(167, 139, 250, 0.65)",
        borderColor: "rgba(167, 139, 250, 0.95)",
        borderWidth: 1,
      },
      {
        label: "OpEx",
        data: opexData,
        backgroundColor: "rgba(94, 234, 212, 0.55)",
        borderColor: "rgba(94, 234, 212, 0.95)",
        borderWidth: 1,
      },
    ];
    const chartOptions = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top" },
        title: {
          display: true,
          text: "Projected totals by horizon (log scale)",
          color: "#94a3b8",
          font: { size: 11, weight: "500" },
        },
        tooltip: {
          callbacks: {
            label(ctx) {
              const v = ctx.parsed?.y;
              return `${ctx.dataset.label}: ${fmtMoney(v)}`;
            },
          },
        },
      },
      scales: {
        x: { stacked: false },
        y: {
          type: "logarithmic",
          beginAtZero: false,
          ticks: {
            callback(v) {
              const n = Number(v);
              if (!Number.isFinite(n) || n <= 0) return "";
              return fmtMoney(n);
            },
          },
        },
      },
    };
    if (marketOpexChart) {
      marketOpexChart.data.labels = labels;
      marketOpexChart.data.datasets = datasets;
      marketOpexChart.options = chartOptions;
      marketOpexChart.update();
      return;
    }
    marketOpexChart = new Chart(els.chartCanvas, {
      type: "bar",
      data: { labels, datasets },
      options: chartOptions,
    });
  }

  function clearResults() {
    for (const h of HORIZONS) {
      const kpi = els.kpi[h.key];
      if (kpi?.market) kpi.market.textContent = "—";
      if (kpi?.opex) kpi.opex.textContent = "—";
    }
    destroyChart();
    if (!els.tbody) return;
    for (const tr of els.tbody.querySelectorAll("tr[data-horizon]")) {
      for (const cell of tr.querySelectorAll("[data-cell]")) {
        cell.textContent = "—";
        cell.classList.remove("deltaNeg", "deltaPos");
      }
    }
  }

  function activateModel(model) {
    if (!model?.model_name) return;
    if (els.modelSelect) els.modelSelect.value = model.model_name;
    if (els.ratesTbody) {
      for (const tr of els.ratesTbody.querySelectorAll("tr.unitPriceSummaryRow")) {
        tr.classList.toggle("is-rowSelected", tr.dataset.modelName === model.model_name);
      }
    }
    maybeAutoFillTokens(model.model_name);
    refreshProjection();
    document.getElementById("estimateForm")?.scrollIntoView?.({
      behavior: "smooth",
      block: "nearest",
    });
  }

  function refreshProjection() {
    const rates = currentModelRates();
    updateRateStrip(rates);
    syncTeamCustomVisibility();

    if (rates?.modelName) {
      maybeAutoFillTokens(rates.modelName);
    }

    const inTok = els.inputTokens?.value === "" ? null : Number(els.inputTokens?.value);
    const outTok = els.outputTokens?.value === "" ? null : Number(els.outputTokens?.value);
    const team = currentTeamSize();

    if (!rates) {
      clearResults();
      if (els.hint) els.hint.textContent = EMPTY_HINT;
      syncUrlState();
      return;
    }

    const marketProj = window.AppCostProjection?.projectDailyCost?.({
      rateInPer1m: rates.marketIn,
      rateOutPer1m: rates.marketOut,
      inputTokensPerDay: inTok,
      outputTokensPerDay: outTok,
      teamSize: team,
    });
    const opexProj = window.AppCostProjection?.projectDailyCost?.({
      rateInPer1m: rates.opexIn,
      rateOutPer1m: rates.opexOut,
      inputTokensPerDay: inTok,
      outputTokensPerDay: outTok,
      teamSize: team,
    });

    if (!marketProj && !opexProj) {
      clearResults();
      if (els.hint) {
        els.hint.textContent = tokensEmpty()
          ? `${EMPTY_HINT} · enter tokens or click a preset`
          : `${rates.modelName} · team ${team} · enter daily input/output tokens per person.`;
      }
      syncUrlState();
      return;
    }

    for (const h of HORIZONS) {
      const days = h.days;
      const marketTotal = marketProj ? marketProj.day * days : null;
      const opexTotal = opexProj ? opexProj.day * days : null;
      const marketIn = marketProj ? (marketProj.day_input || 0) * days : null;
      const marketOut = marketProj ? (marketProj.day_output || 0) * days : null;
      const opexIn = opexProj ? (opexProj.day_input || 0) * days : null;
      const opexOut = opexProj ? (opexProj.day_output || 0) * days : null;

      const kpi = els.kpi[h.key];
      if (kpi?.market) {
        kpi.market.textContent = marketProj
          ? fmtMoney(window.AppMoney?.roundCost?.(marketTotal) ?? marketTotal)
          : "—";
      }
      if (kpi?.opex) {
        kpi.opex.textContent = opexProj
          ? fmtMoney(window.AppMoney?.roundCost?.(opexTotal) ?? opexTotal)
          : "—";
      }

      const tr = els.tbody?.querySelector(`tr[data-horizon="${h.key}"]`);
      if (!tr) continue;
      const set = (key, val) => {
        const cell = tr.querySelector(`[data-cell="${key}"]`);
        if (cell) {
          cell.textContent =
            val == null ? "—" : fmtMoney(window.AppMoney?.roundCost?.(val) ?? val);
        }
      };
      set("market-total", marketProj ? marketTotal : null);
      set("market-input", marketProj ? marketIn : null);
      set("market-output", marketProj ? marketOut : null);
      set("opex-total", opexProj ? opexTotal : null);
      set("opex-input", opexProj ? opexIn : null);
      set("opex-output", opexProj ? opexOut : null);
      const deltaCell = tr.querySelector('[data-cell="delta"]');
      if (deltaCell) {
        deltaCell.textContent = fmtDelta(
          opexProj ? opexTotal : null,
          marketProj ? marketTotal : null
        );
        deltaCell.classList.remove("deltaNeg", "deltaPos");
        if (opexProj && marketProj) {
          const d = Number(opexTotal) - Number(marketTotal);
          if (d < 0) deltaCell.classList.add("deltaNeg");
          else if (d > 0) deltaCell.classList.add("deltaPos");
        }
      }
    }

    updateChart(marketProj, opexProj);

    if (els.hint) {
      const mDay = marketProj ? fmtMoney(marketProj.day) : "—";
      const oDay = opexProj ? fmtMoney(opexProj.day) : "—";
      const people = team === 1 ? "1 person" : `${team} people`;
      els.hint.textContent =
        `${rates.modelName} · ${people} · daily Market ${mDay} vs OpEx ${oDay} · ` +
        `Market ${fmtRatePair(rates.marketIn, rates.marketOut)} · ` +
        `OpEx ${fmtRatePair(rates.opexIn, rates.opexOut)}`;
    }

    syncUrlState();
  }

  function syncUrlState() {
    if (!window.history?.replaceState) return;
    const qs = new URLSearchParams();
    const model = els.modelSelect?.value || "";
    if (model) qs.set("model", model);
    if (els.inputTokens?.value) qs.set("input", els.inputTokens.value);
    if (els.outputTokens?.value) qs.set("output", els.outputTokens.value);
    const teamMode = els.teamSelect?.value || "1";
    if (teamMode === "custom") {
      qs.set("team", String(currentTeamSize()));
      qs.set("team_mode", "custom");
    } else if (teamMode !== "1") {
      qs.set("team", teamMode);
    }
    const search = qs.toString();
    const next = `${window.location.pathname}${search ? `?${search}` : ""}`;
    const cur = `${window.location.pathname}${window.location.search}`;
    if (next !== cur) window.history.replaceState(null, "", next);
  }

  function hydrateFromQuery() {
    const qs = new URLSearchParams(window.location.search);
    const model = (qs.get("model") || "").trim();
    const input = qs.get("input");
    const output = qs.get("output");
    const team = (qs.get("team") || "").trim();
    const teamMode = (qs.get("team_mode") || "").trim();
    if (input != null && els.inputTokens) els.inputTokens.value = input;
    if (output != null && els.outputTokens) els.outputTokens.value = output;
    if (team && els.teamSelect) {
      const presets = new Set(["1", "3", "5", "10"]);
      if (teamMode === "custom" || !presets.has(team)) {
        els.teamSelect.value = "custom";
        if (els.teamCustom) els.teamCustom.value = String(Math.max(1, Math.floor(Number(team) || 1)));
      } else {
        els.teamSelect.value = team;
      }
    }
    syncTeamCustomVisibility();
    if (model && els.modelSelect) {
      els.modelSelect.value = model;
      if (els.ratesTbody) {
        for (const tr of els.ratesTbody.querySelectorAll("tr.unitPriceSummaryRow")) {
          tr.classList.toggle("is-rowSelected", tr.dataset.modelName === model);
        }
      }
      maybeAutoFillTokens(model);
    }
    refreshProjection();
  }

  async function loadUnitRates() {
    if (els.loadBtn) {
      els.loadBtn.disabled = true;
      els.loadBtn.textContent = "Loading…";
    }
    setStatus("Loading unit rates from catalog…");
    try {
      const report = await window.AppHttp.getJson("/api/reports/all-financial?currency=USD");
      const catalog = report?.catalog_market || {};
      currency = catalog.currency || report.currency || "USD";
      unitRateModels = catalog.model_unit_rates || [];
      unitRateDailyRows = catalog.daily_by_model || [];
      populateModelOptions(unitRateModels);
      const show = catalog.available === true && unitRateModels.length > 0;
      if (els.ratesCard) els.ratesCard.hidden = !show;
      if (show) {
        window.AppUnitPriceTable?.renderScopedRows?.(unitRateModels, {
          currency,
          dailyRows: unitRateDailyRows,
          tbody: els.ratesTbody,
          onRowActivate: activateModel,
        });
        setStatus(
          `${unitRateModels.length} model rate(s) loaded · click a row or choose Model above`
        );
      } else {
        if (els.ratesTbody) els.ratesTbody.replaceChildren();
        setStatus("No catalog unit rates available — ingest billing / prices first.", {
          hidden: false,
        });
      }
      hydrateFromQuery();
    } catch (err) {
      console.error(err);
      setStatus(err?.message || "Failed to load unit rates");
      hydrateFromQuery();
    } finally {
      if (els.loadBtn) {
        els.loadBtn.disabled = false;
        els.loadBtn.textContent = "Load model rates";
      }
    }
  }

  function bindEvents() {
    els.modelSelect?.addEventListener("change", () => {
      const name = els.modelSelect.value;
      autoFillAppliedFor = "";
      if (els.ratesTbody) {
        for (const tr of els.ratesTbody.querySelectorAll("tr.unitPriceSummaryRow")) {
          tr.classList.toggle("is-rowSelected", tr.dataset.modelName === name);
        }
      }
      maybeAutoFillTokens(name);
      refreshProjection();
    });
    els.teamSelect?.addEventListener("change", () => {
      syncTeamCustomVisibility();
      if (els.teamSelect.value === "custom" && els.teamCustom && !els.teamCustom.value) {
        els.teamCustom.value = "1";
      }
      refreshProjection();
    });
    for (const el of [els.inputTokens, els.outputTokens, els.teamCustom]) {
      el?.addEventListener("input", () => {
        autoFillAppliedFor = els.modelSelect?.value || autoFillAppliedFor;
        refreshProjection();
      });
    }
    els.loadBtn?.addEventListener("click", () => {
      loadUnitRates().catch((e) => console.error(e));
    });
    document.getElementById("estimatePresetSolo")?.addEventListener("click", () => applyPreset("solo"));
    document.getElementById("estimatePresetTeam5")?.addEventListener("click", () => applyPreset("team5"));
    document.getElementById("estimatePresetTeam10")?.addEventListener("click", () => applyPreset("team10"));
    document.getElementById("logoutBtnTop")?.addEventListener("click", async () => {
      try {
        await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
      } finally {
        window.location = "/login";
      }
    });
  }

  syncTeamCustomVisibility();
  bindEvents();
  loadUnitRates().catch((e) => console.error(e));

  (function bindEstimateJumpNavActive() {
    const nav = document.querySelector(".estimateNav");
    if (!nav) return;
    const links = [...nav.querySelectorAll('a.dashSectionNavLink[href^="#"]')];
    if (!links.length || !window.IntersectionObserver) return;
    const sections = links
      .map((a) => ({
        link: a,
        el: document.querySelector(a.getAttribute("href")),
      }))
      .filter((x) => x.el);
    const visible = new Map();
    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          visible.set(entry.target.id, entry.isIntersecting ? entry.intersectionRatio : 0);
        }
        let bestId = null;
        let bestRatio = 0;
        for (const [id, ratio] of visible.entries()) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestId = id;
          }
        }
        for (const { link, el } of sections) {
          link.classList.toggle("is-navActive", !!bestId && el.id === bestId);
        }
      },
      { rootMargin: "-18% 0px -55% 0px", threshold: [0, 0.2, 0.45, 0.7] }
    );
    for (const { el } of sections) obs.observe(el);
  })();
})();
