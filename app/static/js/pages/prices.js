(() => {
  const vendorSelect = document.getElementById("vendorSelect");
  const platformSelect = document.getElementById("platformSelect");
  const seriesSelect = document.getElementById("seriesSelect");
  const queryBtn = document.getElementById("queryBtn");
  const tbody = document.getElementById("tbody");
  const summary = document.getElementById("summary");
  const exportBtn = document.getElementById("exportBtn");
  const pivotBtn = document.getElementById("pivotBtn");
  const viewLabel = document.getElementById("viewLabel");

  let currentRows = [];
  let isPivot = false;

  function fillSelect(el, items) {
    el.innerHTML = '<option value="">All</option>';
    for (const v of items) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      el.appendChild(opt);
    }
  }

  function fmt(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "-";
    return x.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }

  async function loadFilters() {
    const data = await window.AppHttp.getJson("/api/prices/filters");
    fillSelect(vendorSelect, data.vendors || []);
    fillSelect(platformSelect, data.platforms || []);
    fillSelect(seriesSelect, data.model_series || []);
  }

  function renderDetail(rows) {
    tbody.innerHTML = "";
    for (const r of rows || []) {
      const tr = document.createElement("tr");
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      tr.innerHTML = `
        <td><div class="itemMain">${item}</div><div class="itemSub">${r.metric_name || ""}</div></td>
        <td>${r.deployment_scope || ""}</td>
        <td>${r.billing_mode || ""}</td>
        <td>${r.metric_name || ""}</td>
        <td>${r.price_region || ""}</td>
        <td>${r.price_currency || ""}</td>
        <td class="num">${fmt(r.amount)}</td>
        <td>${r.unit_expression || ""}</td>
        <td>${r.model_series || ""}</td>
        <td>${r.platform || ""}</td>
        <td>${r.vendor || ""}</td>
        <td>${r.effective_date || ""}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  function renderPivot(rows) {
    const grouped = new Map();
    for (const r of rows || []) {
      const key = [
        r.vendor, r.platform, r.model_series, r.model_name, r.context_bucket || "",
        r.deployment_scope || "", r.billing_mode, r.price_region, r.price_currency, r.unit_expression,
      ].join("||");
      if (!grouped.has(key)) grouped.set(key, { ...r, input: null, cached_input: null, output: null });
      grouped.get(key)[r.metric_name] = r.amount;
    }
    const items = [...grouped.values()];
    tbody.innerHTML = "";
    for (const r of items) {
      const tr = document.createElement("tr");
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      tr.innerHTML = `
        <td><div class="itemMain">${item}</div><div class="itemSub">${r.billing_mode || ""}</div></td>
        <td>${r.deployment_scope || ""}</td>
        <td>${r.billing_mode || ""}</td>
        <td>${r.price_region || ""}</td>
        <td>${r.price_currency || ""}</td>
        <td class="num">${r.input == null ? "-" : fmt(r.input)}</td>
        <td class="num">${r.cached_input == null ? "-" : fmt(r.cached_input)}</td>
        <td class="num">${r.output == null ? "-" : fmt(r.output)}</td>
        <td>${r.unit_expression || ""}</td>
        <td>${r.model_series || ""}</td>
        <td>${r.platform || ""}</td>
        <td>${r.vendor || ""}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  function renderRows(rows) {
    const thead = document.querySelector("thead tr");
    if (isPivot) {
      thead.innerHTML = `
        <th>Item</th><th>Scope</th><th>Mode</th><th>Region</th><th>Currency</th>
        <th class="num">Input</th><th class="num">Cached Input</th><th class="num">Output</th><th>Unit</th>
        <th>Series</th><th>Platform</th><th>Vendor</th>
      `;
      renderPivot(rows);
      viewLabel.textContent = "View: Pivot";
      pivotBtn.textContent = "Detail View";
    } else {
      thead.innerHTML = `
        <th>Item</th><th>Scope</th><th>Mode</th><th>Metric</th><th>Region</th><th>Currency</th>
        <th class="num">Amount</th><th>Unit</th><th>Series</th><th>Platform</th><th>Vendor</th><th>Effective Date</th>
      `;
      renderDetail(rows);
      viewLabel.textContent = "View: Detail";
      pivotBtn.textContent = "Pivot View";
    }
    if (!rows || rows.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td colspan="12" style="color:#9fb2c7;">No price rows for current filters.</td>`;
      tbody.appendChild(tr);
    }
  }

  function toCsv(rows) {
    const cols = ["vendor", "platform", "model_series", "model_name", "context_bucket", "deployment_scope", "billing_mode", "metric_name", "price_region", "price_currency", "amount", "unit_expression", "effective_date"];
    const esc = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
    return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  }

  async function loadRows() {
    const params = new URLSearchParams();
    if (vendorSelect.value) params.set("vendor", vendorSelect.value);
    if (platformSelect.value) params.set("platform", platformSelect.value);
    if (seriesSelect.value) params.set("model_series", seriesSelect.value);
    const url = `/api/prices${params.toString() ? `?${params.toString()}` : ""}`;
    const data = await window.AppHttp.getJson(url);
    currentRows = data.rows || [];
    summary.textContent = `Rows: ${data.total || 0}`;
    renderRows(currentRows);
  }

  async function doLogout() {
    try {
      await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      window.location = "/login";
    }
  }

  queryBtn.addEventListener("click", () => {
    loadRows().catch((e) => {
      console.error(e);
    });
  });
  pivotBtn.addEventListener("click", () => {
    isPivot = !isPivot;
    renderRows(currentRows);
  });
  exportBtn.addEventListener("click", () => {
    const csv = toCsv(currentRows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "model_prices_export.csv";
    a.click();
    URL.revokeObjectURL(url);
  });

  const logoutBtn = document.getElementById("logoutBtn");
  const logoutBtnTop = document.getElementById("logoutBtnTop");
  if (logoutBtn) logoutBtn.addEventListener("click", doLogout);
  if (logoutBtnTop) logoutBtnTop.addEventListener("click", doLogout);

  (async () => {
    await loadFilters();
    await loadRows();
  })().catch((e) => {
    console.error(e);
  });
})();
