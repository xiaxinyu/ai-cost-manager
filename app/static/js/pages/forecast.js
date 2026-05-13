(() => {
  const modelSelect = document.getElementById("modelSelect");
  const regionSelect = document.getElementById("regionSelect");
  const billingModeSelect = document.getElementById("billingModeSelect");
  const calcBtn = document.getElementById("calcBtn");
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

  function pizzaScale() {
    const r = document.querySelector('input[name="pizza"]:checked');
    return Number(r && r.value) === 2 ? 2 : 1;
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

  function tokenDay(key) {
    const el = key === "in" ? tokIn : key === "cached" ? tokCached : tokOut;
    const v = Number(el && el.value);
    return Number.isFinite(v) && v >= 0 ? v : 0;
  }

  function dailyUsdPerPizza(perToken) {
    const tin = tokenDay("in");
    const tc = tokenDay("cached");
    const tout = tokenDay("out");
    const pin = Number(perToken.input || 0);
    const pc = Number(perToken.cached_input || 0);
    const po = Number(perToken.output || 0);
    return tin * pin + tc * pc + tout * po;
  }

  function renderTable(dailyPerPizza, currency) {
    if (!tbody) return;
    const scale = pizzaScale();
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
    const scale = pizzaScale();
    const d = Number(dailyPerPizza);
    if (!lastRates || !lastRates.ok || !Number.isFinite(d)) {
      forecastHint.textContent = "";
      return;
    }
    forecastHint.textContent = `每个披萨日均目录成本约 ${fmtMoney(d, currency)}；当前披萨 ×${scale}；总成本 = 日均 × 披萨 × 天数。`;
  }

  function setRateEmpty(msg, muted = true) {
    if (!rateBox) return;
    rateBox.classList.toggle("muted", muted);
    rateBox.classList.toggle("baselineBoxEmpty", muted);
    rateBox.textContent = msg;
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
    if (!m || !regionSelect) {
      setRateEmpty("请选择模型。");
      renderTable(NaN, "USD");
      return;
    }
    const reg = regionSelect.value.trim();
    const dep = deploymentScope();
    const bm = (billingModeSelect && billingModeSelect.value) || "standard";
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
        setRateEmpty(data.notes_zh || "无法匹配目录单价。", true);
        renderTable(NaN, "USD");
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
      rateBox.classList.remove("muted", "baselineBoxEmpty");
      const p1m = data.usd_per_1m_tokens || {};
      rateBox.innerHTML = `
        <div class="baselineGrid">
          <div><strong>Vendor</strong><br />${esc(data.vendor)}</div>
          <div><strong>Platform</strong><br />${esc(data.platform)}</div>
          <div><strong>模型</strong><br />${esc(data.model_name)}</div>
          <div><strong>系列</strong><br />${esc(data.model_series)}</div>
          <div><strong>区域</strong><br />${esc(data.price_region || "（自动）")}</div>
          <div><strong>部署</strong><br />${esc(data.deployment_scope || dep)}</div>
          <div><strong>计费</strong><br />${esc(data.billing_mode || bm)}</div>
          <div><strong>Input / 1M</strong><br />${p1m.input != null ? esc(fmtMoney(p1m.input, cur)) : "—"}</div>
          <div><strong>Cached in / 1M</strong><br />${p1m.cached_input != null ? esc(fmtMoney(p1m.cached_input, cur)) : "—"}</div>
          <div><strong>Output / 1M</strong><br />${p1m.output != null ? esc(fmtMoney(p1m.output, cur)) : "—"}</div>
          <div><strong>每披萨日均</strong><br />${esc(fmtMoney(daily, cur))}</div>
        </div>
        <div class="baselineNotes">${esc(data.notes_zh || "")}</div>
      `;
      if (warnBox && daily === 0) {
        warnBox.style.display = "block";
        warnBox.textContent = "当前假设日用量为 0 或缺少 input/output 单价，总成本为 0。";
      }
      renderTable(daily, cur);
      renderHint(daily, cur);
    } catch (e) {
      console.error(e);
      setRateEmpty("请求失败（会话过期或网络错误）。", true);
      lastRates = null;
      renderTable(NaN, "USD");
    }
  }

  document.querySelectorAll('input[name="pizza"]').forEach((el) => {
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
