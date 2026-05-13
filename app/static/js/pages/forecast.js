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
  const tokIn = document.getElementById("tokIn");
  const tokCached = document.getElementById("tokCached");
  const tokOut = document.getElementById("tokOut");

  const HORIZONS = [
    { days: 1, label: "1 天" },
    { days: 7, label: "1 周" },
    { days: 15, label: "半个月" },
    { days: 30, label: "1 个月" },
  ];

  /** One "pizza" = 7 FTE-style concurrent seats for forecasting. */
  const PEOPLE_PER_PIZZA = 7;

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
    const x = Number(n);
    const cur = (currency || "USD").trim() || "USD";
    if (!Number.isFinite(x)) return "—";
    try {
      return x.toLocaleString(undefined, { style: "currency", currency: cur, maximumFractionDigits: 2 });
    } catch {
      return `${x.toFixed(4)} ${cur}`;
    }
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function teamScaleFactor() {
    const r = document.querySelector('input[name="teamScale"]:checked');
    const v = r && r.value;
    if (v === "p1") return 1 / PEOPLE_PER_PIZZA;
    if (v === "p3") return 3 / PEOPLE_PER_PIZZA;
    if (v === "pz2") return 2;
    return 1;
  }

  function teamScaleSummary() {
    const r = document.querySelector('input[name="teamScale"]:checked');
    const v = r && r.value;
    if (v === "p1") return { short: "1 人", people: 1, factor: 1 / PEOPLE_PER_PIZZA };
    if (v === "p3") return { short: "3 人", people: 3, factor: 3 / PEOPLE_PER_PIZZA };
    if (v === "pz2") return { short: "2 个披萨", people: 14, factor: 2 };
    return { short: "1 个披萨", people: 7, factor: 1 };
  }

  function formatScaleFactor(f) {
    const x = Number(f);
    if (!Number.isFinite(x)) return "—";
    if (Math.abs(x - 1) < 1e-9) return "1";
    if (Math.abs(x - 2) < 1e-9) return "2";
    if (Math.abs(x - 1 / PEOPLE_PER_PIZZA) < 1e-9) return "1/7";
    if (Math.abs(x - 3 / PEOPLE_PER_PIZZA) < 1e-9) return "3/7";
    const t = x.toFixed(3).replace(/\.?0+$/, "");
    return t;
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

  /** Tokens per day from step 3 fields (values are in 1M-token units). */
  function tokensPerDay(key) {
    const el = key === "in" ? tokIn : key === "cached" ? tokCached : tokOut;
    const v = Number(el && el.value);
    const millions = Number.isFinite(v) && v >= 0 ? v : 0;
    return millions * TOKENS_PER_MILLION_UNIT;
  }

  function dailyUsdPerPizza(perToken) {
    const tin = tokensPerDay("in");
    const tc = tokensPerDay("cached");
    const tout = tokensPerDay("out");
    const pin = Number(perToken.input || 0);
    const pc = Number(perToken.cached_input || 0);
    const po = Number(perToken.output || 0);
    return tin * pin + tc * pc + tout * po;
  }

  function renderTable(dailyPerPizza, currency) {
    if (!tbody) return;
    const scale = teamScaleFactor();
    const d = Number(dailyPerPizza);
    if (!Number.isFinite(d) || d < 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="muted">无法计算（缺少单价或用量全为 0）。</td></tr>`;
      return;
    }
    const rows = HORIZONS.map(
      (h, idx) => `
      <tr>
        <td class="num colIdx">${idx + 1}</td>
        <td>${esc(h.label)}</td>
        <td class="num">${h.days}</td>
        <td class="num">${esc(fmtMoney(d * h.days * scale, currency))}</td>
      </tr>`
    );
    tbody.innerHTML = rows.join("");
  }

  function renderHint(dailyPerPizza, currency) {
    if (!forecastHint) return;
    const d = Number(dailyPerPizza);
    if (!lastRates || !lastRates.ok || !Number.isFinite(d)) {
      forecastHint.textContent = "";
      return;
    }
    const s = teamScaleSummary();
    forecastHint.textContent = `每披萨（7 人）日均目录成本约 ${fmtMoney(
      d,
      currency
    )}；当前规模：${s.short}（约 ${s.people} 人 · 倍率 ×${formatScaleFactor(
      s.factor
    )}）；总成本 = 每披萨日均 × 倍率 × 天数。`;
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
    const head = (data && data.notes_zh) || "无法匹配目录单价。";
    const line =
      m && m.vendor
        ? `${esc(m.vendor)} · ${esc(m.platform)} — ${esc(m.model_series)} — ${esc(m.model_name)}`
        : "（未选择模型）";
    rateBox.innerHTML = `
      <div class="priceErrorTitle">未匹配到可用于预测的单价行</div>
      <div class="priceErrorMeta">${line}</div>
      <p class="priceErrorDetail">${esc(head)}</p>
      <ul class="priceErrorList muted">
        <li>区域选「任意（自动匹配）」，让系统按生效日期取最新一行</li>
        <li>切换部署范围 Global / Data zone，与价格表 deployment 列一致</li>
        <li>切换计费 standard / batch</li>
        <li>在 <a href="/prices">Model Prices</a> 中确认该模型是否存在 <strong>input</strong> 或 <strong>output</strong> 计量</li>
      </ul>
    `;
  }

  function renderRatesOk(data, daily, cur) {
    if (!rateBox) return;
    rateBox.classList.remove("muted", "baselineBoxEmpty");
    rateBox.classList.add("forecastPriceBox");
    const p1m = data.usd_per_1m_tokens || {};
    const chip = (label, val) => {
      const v =
        val != null && Number.isFinite(Number(val)) ? fmtMoney(Number(val), cur) : "—";
      return `<div class="priceChip"><span class="priceChipLabel">${esc(label)}</span><span class="priceChipVal">${esc(v)}</span></div>`;
    };
    const miss = (data.missing_metrics || []).join(", ") || "无";
    const meta = `${esc(data.vendor)} · ${esc(data.platform)} — ${esc(data.model_series)} — ${esc(data.model_name)} · 区域 ${esc(data.price_region || "—")} · ${esc(data.deployment_scope || "")} · ${esc(data.billing_mode || "")}`;
    rateBox.innerHTML = `
      <div class="priceChipRow">
        ${chip("Input / 1M tokens", p1m.input)}
        ${chip("Cached input / 1M", p1m.cached_input)}
        ${chip("Output / 1M tokens", p1m.output)}
      </div>
      <div class="priceChipMeta muted">${meta}</div>
      <div class="priceDailyHighlight">
        <span class="priceDailyLabel">每披萨日均（7 人基准 · 按步骤 3 用量）</span>
        <span class="priceDailyVal">${esc(fmtMoney(daily, cur))}</span>
      </div>
      <div class="baselineNotes">未匹配计量：${esc(miss)}。${esc(data.notes_zh || "")}</div>
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
      anyOpt.textContent = "任意（自动匹配）";
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
        '<option value="">任意（自动匹配）</option><option value="eastus2">eastus2</option><option value="East US">East US</option>';
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
        modelSelect.innerHTML = '<option value="">（价格表无模型行）</option>';
        if (catalogHint) {
          catalogHint.innerHTML =
            '价格表为空。请打开 <a href="/prices">Model Prices</a> 执行 <strong>Sync prices</strong> 或导入 CSV。';
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
        catalogHint.textContent = `共 ${opts.length} 条模型（来自价格表去重）。`;
      }
    } catch (e) {
      console.error(e);
      modelSelect.innerHTML = '<option value="">（加载失败）</option>';
      const st = Number(e && e.status) || 0;
      if (catalogHint) {
        if (st === 401) {
          catalogHint.textContent = "未登录或会话已过期，请刷新页面并重新登录。";
        } else {
          catalogHint.textContent = `无法加载模型列表（${st || "网络错误"}）。若已登录仍失败，请检查 /api/forecast/model-catalog。`;
        }
      }
    }
  }

  async function recalc() {
    const m = selectedModel();
    clearForecastHint();
    if (!m || !regionSelect) {
      setCalcStatus("请先在下拉框中选择模型。");
      setRateEmpty("请选择模型后点击「重新计算」。");
      lastRates = null;
      renderTable(NaN, "USD");
      return;
    }
    const reg = regionSelect.value.trim();
    const dep = deploymentScope();
    const bm = (billingModeSelect && billingModeSelect.value) || "standard";
    setCalcStatus("正在匹配 Model Prices 目录…");
    setRateEmpty("加载目录单价…");
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
        setCalcStatus("未匹配到单价：请按下方提示调整区域 / 部署 / 计费，或核对 Model Prices。");
        renderTable(NaN, "USD");
        clearForecastHint();
        if (warnBox && data.reason === "no_prices") {
          warnBox.style.display = "block";
          warnBox.textContent =
            "提示：可尝试「任意区域」、切换部署范围 / 计费模式（standard vs batch），或与 Model Prices 表格逐列对照。";
        }
        return;
      }
      const cur = data.currency || "USD";
      const per = {
        input: data.per_token && data.per_token.input != null ? data.per_token.input : 0,
        cached_input: data.per_token && data.per_token.cached_input != null ? data.per_token.cached_input : 0,
        output: data.per_token && data.per_token.output != null ? data.per_token.output : 0,
      };
      const daily = dailyUsdPerPizza(per);
      renderRatesOk(data, daily, cur);
      const regLabel = data.price_region || "任意匹配";
      setCalcStatus(`已匹配目录单价 · 区域 ${regLabel} · ${data.deployment_scope || dep} · ${data.billing_mode || bm}`);
      if (warnBox && daily === 0) {
        warnBox.style.display = "block";
        warnBox.textContent = "当前假设日用量为 0 或缺少 input/output 单价，总成本为 0。";
      }
      renderTable(daily, cur);
      renderHint(daily, cur);
    } catch (e) {
      console.error(e);
      setCalcStatus("请求失败：请检查网络或重新登录。");
      setRateEmpty("请求失败（会话过期或网络错误）。", true);
      lastRates = null;
      renderTable(NaN, "USD");
      clearForecastHint();
    }
  }

  document.querySelectorAll('input[name="teamScale"]').forEach((el) => {
    el.addEventListener("change", () => {
      if (lastRates && lastRates.ok && lastRates.per_token) {
        const pt = lastRates.per_token;
        const daily = dailyUsdPerPizza({
          input: Number(pt.input) || 0,
          cached_input: Number(pt.cached_input) || 0,
          output: Number(pt.output) || 0,
        });
        renderTable(daily, lastRates.currency);
        renderHint(daily, lastRates.currency);
      }
    });
  });

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
