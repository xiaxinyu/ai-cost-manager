(() => {
  const modelSelect = document.getElementById("modelSelect");
  const regionSelect = document.getElementById("regionSelect");
  const billingModeSelect = document.getElementById("billingModeSelect");
  const calcBtn = document.getElementById("calcBtn");
  const calcStatus = document.getElementById("calcStatus");
  const rateBox = document.getElementById("rateBox");
  const warnBox = document.getElementById("warnBox");
  const tbody = document.getElementById("forecastTbody");
  const forecastHint = document.getElementById("forecastHint");
  const catalogHint = document.getElementById("catalogHint");
  const teamSize = document.getElementById("teamSize");
  const kpiDailyPizza = document.getElementById("kpiDailyPizza");
  const kpiDailyTeam = document.getElementById("kpiDailyTeam");
  const kpiMonthTeam = document.getElementById("kpiMonthTeam");
  const costMixRows = document.getElementById("costMixRows");
  const horizonBars = document.getElementById("horizonBars");
  const tokIn = document.getElementById("tokIn");
  const tokCached = document.getElementById("tokCached");
  const tokOut = document.getElementById("tokOut");

  const HORIZONS = [
    { days: 1, label: "1 day" },
    { days: 7, label: "1 week" },
    { days: 15, label: "15 days" },
    { days: 30, label: "30 days" },
  ];

  /** Step 3 inputs are in millions of tokens (e.g. 0.5 → 500k tokens). */
  const TOKENS_PER_MILLION_UNIT = 1_000_000;

  let lastRates = null;

  async function fetchJsonQuiet(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    const text = await res.text();
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    try {
      return JSON.parse(text);
    } catch {
      const err = new Error("Invalid JSON");
      err.status = res.status;
      throw err;
    }
  }

  function fmtMoney(n, currency) {
    return window.AppMoney?.fmtCost(n, currency) ?? "—";
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function apiNotes(data) {
    return (data && (data.notes || data.notes_zh)) || "No matching catalog unit price.";
  }

  function teamSizeValue() {
    const people = Number(teamSize && teamSize.value);
    return Number.isFinite(people) && people > 0 ? Math.round(people) : 1;
  }

  function teamScaleSummary() {
    const p = teamSizeValue();
    return { short: `${p} people`, people: p };
  }

  function deploymentScope() {
    const r = document.querySelector('input[name="deployment"]:checked');
    const v = r && r.value;
    return v === "data_zone" ? "data_zone" : "global";
  }

  function selectedModel() {
    const opt = modelSelect && modelSelect.selectedOptions && modelSelect.selectedOptions[0];
    if (!opt) return null;
    const vendor = opt.getAttribute("data-vendor");
    const platform = opt.getAttribute("data-platform");
    const s = opt.getAttribute("data-series");
    const n = opt.getAttribute("data-name");
    if (!vendor || !platform || !s || !n) return null;
    return { vendor, platform, model_series: s, model_name: n };
  }

  function tokensPerDay(key) {
    const el = key === "in" ? tokIn : key === "cached" ? tokCached : tokOut;
    const v = Number(el && el.value);
    const millions = Number.isFinite(v) && v >= 0 ? v : 0;
    return millions * TOKENS_PER_MILLION_UNIT;
  }

  function dailyUsdPerPerson(perToken) {
    const tin = tokensPerDay("in");
    const tc = tokensPerDay("cached");
    const tout = tokensPerDay("out");
    const pin = Number(perToken.input || 0);
    const pc = Number(perToken.cached_input || 0);
    const po = Number(perToken.output || 0);
    return tin * pin + tc * pc + tout * po;
  }

  function forecastRows(dailyPerPerson) {
    const d = Number(dailyPerPerson);
    const people = teamSizeValue();
    if (!Number.isFinite(d) || d < 0) return [];
    return HORIZONS.map((h) => ({ ...h, total: d * h.days * people }));
  }

  function setKpiText(el, text) {
    if (el) el.textContent = text;
  }

  function resetVisuals() {
    setKpiText(kpiDailyPizza, "—");
    setKpiText(kpiDailyTeam, "—");
    setKpiText(kpiMonthTeam, "—");
    if (costMixRows) {
      costMixRows.innerHTML = '<div class="muted">Recalculate to show Input / Cached / Output share.</div>';
    }
    if (horizonBars) {
      horizonBars.innerHTML = '<div class="muted">Recalculate to compare horizons.</div>';
    }
  }

  function renderKpis(dailyPerPerson, currency) {
    const d = Number(dailyPerPerson);
    if (!Number.isFinite(d) || d < 0) {
      resetVisuals();
      return;
    }
    const people = teamSizeValue();
    const teamDaily = d * people;
    setKpiText(kpiDailyPizza, fmtMoney(d, currency));
    setKpiText(kpiDailyTeam, fmtMoney(teamDaily * 7, currency));
    setKpiText(kpiMonthTeam, fmtMoney(teamDaily * 30, currency));
  }

  function renderCostMix(perToken, currency) {
    if (!costMixRows) return;
    if (!perToken) {
      costMixRows.innerHTML = '<div class="muted">Recalculate to show Input / Cached / Output share.</div>';
      return;
    }
    const people = teamSizeValue();
    const items = [
      {
        key: "input",
        label: "Input",
        unit: tokensPerDay("in") / TOKENS_PER_MILLION_UNIT,
        cost: tokensPerDay("in") * (Number(perToken.input) || 0) * people,
        cls: "mixBarInput",
      },
      {
        key: "cached_input",
        label: "Cached input",
        unit: tokensPerDay("cached") / TOKENS_PER_MILLION_UNIT,
        cost: tokensPerDay("cached") * (Number(perToken.cached_input) || 0) * people,
        cls: "mixBarCached",
      },
      {
        key: "output",
        label: "Output",
        unit: tokensPerDay("out") / TOKENS_PER_MILLION_UNIT,
        cost: tokensPerDay("out") * (Number(perToken.output) || 0) * people,
        cls: "mixBarOutput",
      },
    ];
    const total = items.reduce((acc, x) => acc + x.cost, 0);
    if (!(total > 0)) {
      costMixRows.innerHTML = '<div class="muted">Usage or unit price is zero — no mix chart.</div>';
      return;
    }
    costMixRows.innerHTML = items
      .map((it) => {
        const pct = (it.cost / total) * 100;
        return `
          <div class="mixRow">
            <div class="mixHead">
              <span class="mixName">${esc(it.label)}</span>
              <span class="mixMeta">${esc(it.unit.toFixed(2).replace(/\.?0+$/, ""))}M / person / day · ${esc(fmtMoney(it.cost, currency))} / team / day</span>
            </div>
            <div class="mixTrack"><div class="mixBar ${esc(it.cls)}" style="width:${Math.max(0, Math.min(100, pct)).toFixed(2)}%"></div></div>
          </div>
        `;
      })
      .join("");
  }

  function renderHorizonBars(rows, currency) {
    if (!horizonBars) return;
    if (!Array.isArray(rows) || rows.length === 0) {
      horizonBars.innerHTML = '<div class="muted">Recalculate to compare horizons.</div>';
      return;
    }
    const max = Math.max(...rows.map((x) => Number(x.total) || 0), 0);
    if (!(max > 0)) {
      horizonBars.innerHTML = '<div class="muted">All horizon totals are zero.</div>';
      return;
    }
    horizonBars.innerHTML = rows
      .map((r) => {
        const pct = ((Number(r.total) || 0) / max) * 100;
        return `
          <div class="hBarRow">
            <div class="hBarHead">
              <span class="hBarLabel">${esc(r.label)} (${r.days}d)</span>
              <span class="hBarVal">${esc(fmtMoney(r.total, currency))}</span>
            </div>
            <div class="hBarTrack"><div class="hBarFill" style="width:${Math.max(0, Math.min(100, pct)).toFixed(2)}%"></div></div>
          </div>
        `;
      })
      .join("");
  }

  function renderTable(dailyPerPerson, currency) {
    if (!tbody) return;
    const rowsData = forecastRows(dailyPerPerson);
    if (!rowsData.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="muted">Cannot compute — missing rates or zero usage.</td></tr>`;
      return;
    }
    const rows = rowsData.map(
      (h, idx) => `
      <tr>
        <td class="num colIdx">${idx + 1}</td>
        <td>${esc(h.label)}</td>
        <td class="num">${h.days}</td>
        <td class="num">${esc(fmtMoney(h.total, currency))}</td>
      </tr>`
    );
    tbody.innerHTML = rows.join("");
    renderHorizonBars(rowsData, currency);
  }

  function renderVisuals(dailyPerPerson, currency, perToken) {
    renderKpis(dailyPerPerson, currency);
    renderCostMix(perToken, currency);
  }

  function renderHint(dailyPerPerson, currency) {
    if (!forecastHint) return;
    const d = Number(dailyPerPerson);
    if (!lastRates || !lastRates.ok || !Number.isFinite(d)) {
      forecastHint.textContent = "";
      return;
    }
    const s = teamScaleSummary();
    forecastHint.textContent = `Team: ${s.short} · Total = per-person daily × people × days.`;
  }

  function clearForecastHint() {
    if (forecastHint) forecastHint.textContent = "";
  }

  function setCalcStatus(msg) {
    if (calcStatus) calcStatus.textContent = msg || "";
  }

  function setRateEmpty(msg, muted = true) {
    if (!rateBox) return;
    rateBox.classList.toggle("muted", muted);
    rateBox.classList.toggle("baselineBoxEmpty", muted);
    rateBox.textContent = msg;
  }

  function renderRatesError(data, m) {
    if (!rateBox) return;
    rateBox.classList.remove("muted", "baselineBoxEmpty");
    rateBox.classList.add("forecastPriceBox");
    const head = apiNotes(data);
    const line =
      m && m.vendor
        ? `${esc(m.vendor)} · ${esc(m.platform)} — ${esc(m.model_series)} — ${esc(m.model_name)}`
        : "(no model selected)";
    rateBox.innerHTML = `
      <div class="priceErrorTitle">No catalog rate for forecast</div>
      <div class="priceErrorMeta">${line}</div>
      <p class="priceErrorDetail">${esc(head)}</p>
      <ul class="priceErrorList muted">
        <li>Region: choose <strong>Any (auto)</strong> for the latest effective row</li>
        <li>Deployment: match Global / Data zone to Model Prices</li>
        <li>Billing: try standard vs batch</li>
        <li>Confirm <strong>input</strong> or <strong>output</strong> meters exist in <a href="/prices">Model Prices</a></li>
      </ul>
    `;
  }

  function renderRatesOk(data, cur) {
    if (!rateBox) return;
    rateBox.classList.remove("muted", "baselineBoxEmpty");
    rateBox.classList.add("forecastPriceBox");
    const p1m = data.usd_per_1m_tokens || {};
    const chip = (label, val) => {
      const v =
        val != null && Number.isFinite(Number(val)) ? fmtMoney(Number(val), cur) : "—";
      return `<div class="priceChip"><span class="priceChipLabel">${esc(label)}</span><span class="priceChipVal">${esc(v)}</span></div>`;
    };
    rateBox.innerHTML = `
      <div class="priceChipRow">
        ${chip("Input / 1M tokens", p1m.input)}
        ${chip("Cached input / 1M", p1m.cached_input)}
        ${chip("Output / 1M tokens", p1m.output)}
      </div>
    `;
  }

  async function loadRegions() {
    if (!regionSelect) return;
    try {
      const f = await fetchJsonQuiet("/api/prices/filters");
      const regs = f.regions || [];
      regionSelect.innerHTML = "";
      const anyOpt = document.createElement("option");
      anyOpt.value = "";
      anyOpt.textContent = "Any (auto)";
      regionSelect.appendChild(anyOpt);
      for (const r of [...regs].map((x) => String(x || "").trim()).filter(Boolean).sort()) {
        const opt = document.createElement("option");
        opt.value = r;
        opt.textContent = r;
        regionSelect.appendChild(opt);
      }
      regionSelect.value = "";
    } catch {
      regionSelect.innerHTML =
        '<option value="">Any (auto)</option><option value="eastus2">eastus2</option><option value="East US">East US</option>';
      regionSelect.value = "";
    }
  }

  async function loadCatalog() {
    if (!modelSelect) return;
    modelSelect.innerHTML = "";
    try {
      const data = await fetchJsonQuiet("/api/forecast/model-catalog");
      const opts = data.options || [];
      if (opts.length === 0) {
        modelSelect.innerHTML = '<option value="">(no models in catalog)</option>';
        if (catalogHint) {
          catalogHint.innerHTML =
            'Catalog is empty. Open <a href="/prices">Model Prices</a> and run <strong>Sync prices</strong> or import CSV.';
        }
        return;
      }
      for (const o of opts) {
        const opt = document.createElement("option");
        opt.value = `${o.vendor}\t${o.platform}\t${o.model_series}\t${o.model_name}`;
        opt.textContent = `${o.vendor} · ${o.platform} — ${o.model_series} — ${o.model_name}`;
        opt.setAttribute("data-vendor", o.vendor);
        opt.setAttribute("data-platform", o.platform);
        opt.setAttribute("data-series", o.model_series);
        opt.setAttribute("data-name", o.model_name);
        modelSelect.appendChild(opt);
      }
      if (catalogHint) {
        catalogHint.textContent = `${opts.length} model(s) from catalog.`;
      }
    } catch (e) {
      console.error(e);
      modelSelect.innerHTML = '<option value="">(load failed)</option>';
      const st = Number(e && e.status) || 0;
      if (catalogHint) {
        if (st === 401) {
          catalogHint.textContent = "Session expired — refresh and sign in again.";
        } else {
          catalogHint.textContent = `Could not load models (${st || "network error"}). Check /api/forecast/model-catalog.`;
        }
      }
    }
  }

  async function recalc() {
    const m = selectedModel();
    clearForecastHint();
    if (!m || !regionSelect) {
      setCalcStatus("Select a model first.");
      setRateEmpty("Select a model, then click Recalculate.");
      lastRates = null;
      renderTable(NaN, "USD");
      resetVisuals();
      return;
    }
    const reg = regionSelect.value.trim();
    const dep = deploymentScope();
    const bm = (billingModeSelect && billingModeSelect.value) || "standard";
    setCalcStatus("Matching Model Prices catalog…");
    setRateEmpty("Loading catalog rates…");
    if (warnBox) {
      warnBox.style.display = "none";
      warnBox.textContent = "";
    }
    try {
      const qs = new URLSearchParams({
        vendor: m.vendor,
        platform: m.platform,
        model_series: m.model_series,
        model_name: m.model_name,
        deployment_scope: dep,
        billing_mode: bm,
      });
      if (reg) qs.set("price_region", reg);
      const data = await window.AppHttp.getJson(`/api/forecast/model-unit-prices?${qs.toString()}`);
      lastRates = data;
      if (!data.ok) {
        renderRatesError(data, m);
        setCalcStatus("No match — adjust region, deployment, billing, or check Model Prices.");
        renderTable(NaN, "USD");
        resetVisuals();
        clearForecastHint();
        if (warnBox && data.reason === "no_prices") {
          warnBox.style.display = "block";
          warnBox.textContent =
            "Tip: try Any region, switch deployment or billing mode, or compare columns in Model Prices.";
        }
        return;
      }
      const cur = data.currency || "USD";
      const per = {
        input: data.per_token && data.per_token.input != null ? data.per_token.input : 0,
        cached_input: data.per_token && data.per_token.cached_input != null ? data.per_token.cached_input : 0,
        output: data.per_token && data.per_token.output != null ? data.per_token.output : 0,
      };
      const daily = dailyUsdPerPerson(per);
      renderRatesOk(data, cur);
      const regLabel = data.price_region || "any match";
      setCalcStatus(`Matched · ${regLabel} · ${data.deployment_scope || dep} · ${data.billing_mode || bm}`);
      if (warnBox && daily === 0) {
        warnBox.style.display = "block";
        warnBox.textContent = "Assumed usage is zero or input/output rates are missing — total is 0.";
      }
      renderTable(daily, cur);
      renderVisuals(daily, cur, per);
      renderHint(daily, cur);
    } catch (e) {
      console.error(e);
      setCalcStatus("Request failed — check network or sign in again.");
      setRateEmpty("Request failed (session or network).", true);
      lastRates = null;
      renderTable(NaN, "USD");
      resetVisuals();
      clearForecastHint();
    }
  }

  if (teamSize) {
    const onTeamSizeChange = () => {
      if (lastRates && lastRates.ok && lastRates.per_token) {
        const pt = lastRates.per_token;
        const daily = dailyUsdPerPerson({
          input: Number(pt.input) || 0,
          cached_input: Number(pt.cached_input) || 0,
          output: Number(pt.output) || 0,
        });
        renderTable(daily, lastRates.currency);
        renderVisuals(daily, lastRates.currency, {
          input: Number(pt.input) || 0,
          cached_input: Number(pt.cached_input) || 0,
          output: Number(pt.output) || 0,
        });
        renderHint(daily, lastRates.currency);
      }
    };
    teamSize.addEventListener("change", onTeamSizeChange);
    teamSize.addEventListener("input", onTeamSizeChange);
  }

  document.querySelectorAll('input[name="deployment"]').forEach((el) => {
    el.addEventListener("change", () => recalc().catch((e) => console.error(e)));
  });

  if (billingModeSelect) {
    billingModeSelect.addEventListener("change", () => recalc().catch((e) => console.error(e)));
  }

  [tokIn, tokCached, tokOut].forEach((el) => {
    if (el) el.addEventListener("change", () => recalc().catch((e) => console.error(e)));
  });

  if (modelSelect) {
    modelSelect.addEventListener("change", () => recalc().catch((e) => console.error(e)));
  }
  if (regionSelect) {
    regionSelect.addEventListener("change", () => recalc().catch((e) => console.error(e)));
  }
  if (calcBtn) calcBtn.addEventListener("click", () => recalc().catch((e) => console.error(e)));

  const logoutBtnTop = document.getElementById("logoutBtnTop");
  if (logoutBtnTop) {
    logoutBtnTop.addEventListener("click", async () => {
      try {
        await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
      } finally {
        window.location = "/login";
      }
    });
  }

  (async () => {
    await loadRegions().catch((e) => console.error(e));
    await loadCatalog().catch((e) => console.error(e));
    await recalc().catch((e) => console.error(e));
  })().catch((e) => console.error(e));
})();
