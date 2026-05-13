(() => {
  const vendorSelect = document.getElementById("vendorSelect");
  const platformSelect = document.getElementById("platformSelect");
  const seriesSelect = document.getElementById("seriesSelect");
  const pageSizeSelect = document.getElementById("pageSizeSelect");
  const queryBtn = document.getElementById("queryBtn");
  const tbody = document.getElementById("tbody");
  const summary = document.getElementById("summary");
  const paginationEl = document.getElementById("pagination");
  const exportBtn = document.getElementById("exportBtn");
  const pivotBtn = document.getElementById("pivotBtn");
  const detailLayoutBtn = document.getElementById("detailLayoutBtn");
  const viewLabel = document.getElementById("viewLabel");
  const priceDetailDialog = document.getElementById("priceDetailDialog");
  const priceDetailBody = document.getElementById("priceDetailBody");
  const priceDetailClose = document.getElementById("priceDetailClose");
  const syncRetailBtn = document.getElementById("syncRetailBtn");
  const retailSyncDialog = document.getElementById("retailSyncDialog");
  const retailSyncClose = document.getElementById("retailSyncClose");
  const syncSeriesSelect = document.getElementById("syncSeriesSelect");
  const syncProbeMarketing = document.getElementById("syncProbeMarketing");
  const retailSyncRun = document.getElementById("retailSyncRun");
  const syncArmRegionSelect = document.getElementById("syncArmRegionSelect");

  let currentRows = [];
  let totalMatching = 0;
  let currentPage = 1;
  let isPivot = false;
  /** When not pivot: fewer table columns (Item … Series only). */
  let isCompactDetail = false;

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

  function fmtInt(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "-";
    return Math.round(x).toLocaleString();
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function pageSize() {
    const v = Number(pageSizeSelect && pageSizeSelect.value);
    if (Number.isFinite(v) && v > 0) return Math.min(500, v);
    return 100;
  }

  function totalPages() {
    const ps = pageSize();
    return Math.max(1, Math.ceil(totalMatching / ps));
  }

  async function loadFilters() {
    const data = await window.AppHttp.getJson("/api/prices/filters");
    fillSelect(vendorSelect, data.vendors || []);
    fillSelect(platformSelect, data.platforms || []);
    fillSelect(seriesSelect, data.model_series || []);
  }

  async function loadSyncSeriesOptions(bustCache = false) {
    if (!syncSeriesSelect) return;
    const suffix = bustCache ? `?bust=${Date.now()}` : "";
    const data = await window.AppHttp.getJson(`/api/prices/sync-series-options${suffix}`, {
      cache: "no-store",
    });
    syncSeriesSelect.innerHTML = "";
    for (const o of data.series || []) {
      const opt = document.createElement("option");
      opt.value = o.key;
      opt.textContent = o.label || o.key;
      syncSeriesSelect.appendChild(opt);
    }
    const pref = syncSeriesSelect.querySelector('option[value="gpt_51_52"]');
    if (pref) syncSeriesSelect.value = "gpt_51_52";
  }

  async function openRetailSyncDialog() {
    if (!retailSyncDialog) {
      if (window.AppShell?.toast) window.AppShell.toast("Sync dialog not found — reload the page.", "error", 4000);
      return;
    }
    const prevLabel = syncRetailBtn ? syncRetailBtn.textContent : "";
    if (syncRetailBtn) {
      syncRetailBtn.disabled = true;
      syncRetailBtn.setAttribute("aria-busy", "true");
      syncRetailBtn.textContent = "Opening…";
    }
    try {
      await loadSyncSeriesOptions(true);
    } catch (e) {
      console.error(e);
      return;
    } finally {
      if (syncRetailBtn) {
        syncRetailBtn.disabled = false;
        syncRetailBtn.removeAttribute("aria-busy");
        syncRetailBtn.textContent = prevLabel || "Sync prices";
      }
    }
    try {
      if (retailSyncDialog.open) retailSyncDialog.close();
    } catch {
      /* ignore */
    }
    try {
      if (typeof retailSyncDialog.showModal === "function") {
        retailSyncDialog.showModal();
      } else if (typeof retailSyncDialog.show === "function") {
        retailSyncDialog.show();
      } else {
        retailSyncDialog.setAttribute("open", "");
      }
    } catch (e1) {
      console.error(e1);
      try {
        if (typeof retailSyncDialog.show === "function") retailSyncDialog.show();
        else retailSyncDialog.setAttribute("open", "");
      } catch (e2) {
        console.error(e2);
        retailSyncDialog.setAttribute("open", "");
      }
      if (window.AppShell?.toast) {
        window.AppShell.toast(
          "Sync panel opened in non-modal mode. If you still do not see it, try another browser or update Safari/Chrome.",
          "info",
          5200
        );
      }
    }
    if (window.AppShell?.toast) {
      window.AppShell.toast("Choose a model scope, then tap Start sync (pulls from prices.azure.com).", "info", 3800);
    }
  }

  function closeRetailSyncDialog() {
    if (!retailSyncDialog) return;
    try {
      retailSyncDialog.close();
    } catch {
      retailSyncDialog.removeAttribute("open");
    }
  }

  async function runRetailSync() {
    if (!syncSeriesSelect || !retailSyncRun) return;
    retailSyncRun.disabled = true;
    retailSyncRun.textContent = "Syncing…";
    try {
      const body = {
        series: syncSeriesSelect.value,
        probe_marketing: !!(syncProbeMarketing && syncProbeMarketing.checked),
      };
      const arm = syncArmRegionSelect && syncArmRegionSelect.value ? syncArmRegionSelect.value.trim() : "";
      if (arm) body.arm_region = arm;
      const out = await window.AppHttp.postJson("/api/prices/sync-retail", body);
      const r = out.retail || {};
      let msg = `Synced ${fmtInt(r.rows_imported || 0)} retail rows (removed ${fmtInt(r.retail_rows_deleted || 0)} old retail).`;
      if (out.marketing_probe && syncProbeMarketing && syncProbeMarketing.checked) {
        const jsonLike = (out.marketing_probe || []).filter((x) => x && x.looks_like_json).length;
        msg += ` Marketing probe: ${out.marketing_probe.length} URL(s), JSON-like: ${jsonLike}.`;
      }
      if (window.AppShell?.toast) window.AppShell.toast(msg, "info", 5200);
      closeRetailSyncDialog();
      currentPage = 1;
      await loadFilters();
      await loadRows();
    } catch (e) {
      console.error(e);
    } finally {
      retailSyncRun.disabled = false;
      retailSyncRun.textContent = "Start sync";
    }
  }

  function renderDetail(rows, serialBase) {
    tbody.innerHTML = "";
    let i = 0;
    for (const r of rows || []) {
      const tr = document.createElement("tr");
      tr.className = "priceDataRow";
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      const rid = r.id != null ? String(r.id) : "";
      const serial = serialBase + i + 1;
      i += 1;
      tr.innerHTML = `
        <td class="num colRowNum">${fmtInt(serial)}</td>
        <td><div class="itemMain">${esc(item)}</div><div class="itemSub">${esc(r.metric_name || "")}</div></td>
        <td>${esc(r.deployment_scope || "")}</td>
        <td>${esc(r.billing_mode || "")}</td>
        <td>${esc(r.metric_name || "")}</td>
        <td>${esc(r.price_region || "")}</td>
        <td>${esc(r.price_currency || "")}</td>
        <td class="num">${fmt(r.amount)}</td>
        <td>${esc(r.unit_expression || "")}</td>
        <td>${esc(r.model_series || "")}</td>
        <td>${esc(r.platform || "")}</td>
        <td>${esc(r.vendor || "")}</td>
        <td>${esc(r.effective_date || "")}</td>
        <td class="colDetail">
          <button type="button" class="detailBtn" data-price-id="${esc(rid)}">View</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
  }

  function renderDetailCompact(rows, serialBase) {
    tbody.innerHTML = "";
    let i = 0;
    for (const r of rows || []) {
      const tr = document.createElement("tr");
      tr.className = "priceDataRow priceRowClickable";
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      const rid = r.id != null ? String(r.id) : "";
      const serial = serialBase + i + 1;
      i += 1;
      if (rid) {
        tr.setAttribute("data-row-price-id", rid);
        tr.setAttribute("tabindex", "0");
        tr.setAttribute("role", "button");
        tr.setAttribute("aria-label", `Open full detail for ${String(r.model_name || "price row").replace(/"/g, "'").slice(0, 120)}`);
        tr.title = "Click or press Enter to open full detail (scope, platform, vendor, effective date, …)";
      }
      tr.innerHTML = `
        <td class="num colRowNum">${fmtInt(serial)}</td>
        <td><div class="itemMain">${esc(item)}</div></td>
        <td>${esc(r.billing_mode || "")}</td>
        <td>${esc(r.metric_name || "")}</td>
        <td>${esc(r.price_region || "")}</td>
        <td>${esc(r.price_currency || "")}</td>
        <td class="num">${fmt(r.amount)}</td>
        <td>${esc(r.unit_expression || "")}</td>
        <td>${esc(r.model_series || "")}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  function renderPivot(rows, serialBase) {
    const grouped = new Map();
    for (const r of rows || []) {
      const key = [
        r.vendor, r.platform, r.model_series, r.model_name, r.context_bucket || "",
        r.deployment_scope || "", r.billing_mode, r.price_region, r.price_currency, r.unit_expression,
      ].join("||");
      if (!grouped.has(key)) {
        grouped.set(key, {
          ...r,
          detail_id: r.id,
          input: null,
          cached_input: null,
          output: null,
        });
      }
      const g = grouped.get(key);
      if (g.detail_id == null && r.id != null) g.detail_id = r.id;
      g[r.metric_name] = r.amount;
    }
    const items = [...grouped.values()];
    tbody.innerHTML = "";
    let i = 0;
    for (const r of items) {
      const tr = document.createElement("tr");
      tr.className = "priceDataRow";
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      const rid = r.detail_id != null ? String(r.detail_id) : "";
      const serial = serialBase + i + 1;
      i += 1;
      tr.innerHTML = `
        <td class="num colRowNum">${fmtInt(serial)}</td>
        <td><div class="itemMain">${esc(item)}</div><div class="itemSub">${esc(r.billing_mode || "")}</div></td>
        <td>${esc(r.deployment_scope || "")}</td>
        <td>${esc(r.billing_mode || "")}</td>
        <td>${esc(r.price_region || "")}</td>
        <td>${esc(r.price_currency || "")}</td>
        <td class="num">${r.input == null ? "-" : fmt(r.input)}</td>
        <td class="num">${r.cached_input == null ? "-" : fmt(r.cached_input)}</td>
        <td class="num">${r.output == null ? "-" : fmt(r.output)}</td>
        <td>${esc(r.unit_expression || "")}</td>
        <td>${esc(r.model_series || "")}</td>
        <td>${esc(r.platform || "")}</td>
        <td>${esc(r.vendor || "")}</td>
        <td class="colDetail">
          <button type="button" class="detailBtn" data-price-id="${esc(rid)}">View</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
  }

  function renderPagination() {
    if (!paginationEl) return;
    const tp = totalPages();
    const ps = pageSize();
    const from = totalMatching === 0 ? 0 : (currentPage - 1) * ps + 1;
    const to = Math.min(totalMatching, currentPage * ps);
    paginationEl.innerHTML = "";
    const info = document.createElement("span");
    info.className = "pgInfo";
    info.textContent = `Showing ${from}–${to} of ${fmtInt(totalMatching)} (page ${currentPage} / ${tp})`;
    paginationEl.appendChild(info);

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "pgBtn";
    prev.textContent = "Previous";
    prev.disabled = currentPage <= 1;
    prev.addEventListener("click", () => {
      if (currentPage > 1) {
        currentPage -= 1;
        loadRows().catch((e) => console.error(e));
      }
    });

    const next = document.createElement("button");
    next.type = "button";
    next.className = "pgBtn";
    next.textContent = "Next";
    next.disabled = currentPage >= tp;
    next.addEventListener("click", () => {
      if (currentPage < tp) {
        currentPage += 1;
        loadRows().catch((e) => console.error(e));
      }
    });

    paginationEl.appendChild(prev);
    paginationEl.appendChild(next);
  }

  function renderRows(rows) {
    const thead = document.querySelector("thead tr");
    const tableShell = document.getElementById("pricingTableShell") || document.querySelector(".pricingTableShell");
    const ps = pageSize();
    const serialBase = totalMatching === 0 ? 0 : (currentPage - 1) * ps;
    if (detailLayoutBtn) {
      detailLayoutBtn.style.display = isPivot ? "none" : "";
      if (!isPivot) {
        detailLayoutBtn.textContent = isCompactDetail ? "Full columns" : "Compact";
      }
    }
    if (isPivot) {
      if (tableShell) tableShell.classList.remove("is-compact");
      thead.innerHTML = `
        <th class="num colRowNum" scope="col">#</th>
        <th>Item</th><th>Scope</th><th>Mode</th><th>Region</th><th>Currency</th>
        <th class="num">Input</th><th class="num">Cached Input</th><th class="num">Output</th><th>Unit</th>
        <th>Series</th><th>Platform</th><th>Vendor</th><th class="colDetail">Details</th>
      `;
      renderPivot(rows, serialBase);
      viewLabel.textContent = "View: Pivot";
      pivotBtn.textContent = "Detail View";
    } else if (isCompactDetail) {
      if (tableShell) tableShell.classList.add("is-compact");
      thead.innerHTML = `
        <th class="num colRowNum" scope="col">#</th>
        <th>Item</th><th>Mode</th><th>Metric</th><th>Region</th><th>Currency</th>
        <th class="num">Amount</th><th>Unit</th><th>Series</th>
      `;
      renderDetailCompact(rows, serialBase);
      viewLabel.textContent = "View: Compact";
      pivotBtn.textContent = "Pivot View";
    } else {
      if (tableShell) tableShell.classList.remove("is-compact");
      thead.innerHTML = `
        <th class="num colRowNum" scope="col">#</th>
        <th>Item</th><th>Scope</th><th>Mode</th><th>Metric</th><th>Region</th><th>Currency</th>
        <th class="num">Amount</th><th>Unit</th><th>Series</th><th>Platform</th><th>Vendor</th><th>Effective Date</th>
        <th class="colDetail">Details</th>
      `;
      renderDetail(rows, serialBase);
      viewLabel.textContent = "View: Detail";
      pivotBtn.textContent = "Pivot View";
    }
    if (!rows || rows.length === 0) {
      const tr = document.createElement("tr");
      const colspan = isPivot ? 14 : isCompactDetail ? 9 : 14;
      tr.innerHTML = `<td colspan="${colspan}" style="color:#9fb2c7;">No price rows for current filters.</td>`;
      tbody.appendChild(tr);
    }
  }

  function toCsv(rows) {
    const cols = ["id", "vendor", "platform", "model_series", "model_name", "context_bucket", "deployment_scope", "billing_mode", "metric_name", "price_region", "price_currency", "amount", "unit_expression", "effective_date"];
    const escCsv = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
    return [cols.join(","), ...rows.map((r) => cols.map((c) => escCsv(r[c])).join(","))].join("\n");
  }

  async function loadRows() {
    const params = new URLSearchParams();
    if (vendorSelect.value) params.set("vendor", vendorSelect.value);
    if (platformSelect.value) params.set("platform", platformSelect.value);
    if (seriesSelect.value) params.set("model_series", seriesSelect.value);
    params.set("page", String(currentPage));
    params.set("page_size", String(pageSize()));
    const url = `/api/prices?${params.toString()}`;
    let data = await window.AppHttp.getJson(url);
    totalMatching = Number(data.total) || 0;
    const tp = totalPages();
    if (totalMatching === 0) {
      currentPage = 1;
    } else if (currentPage > tp) {
      currentPage = tp;
      const params2 = new URLSearchParams(params);
      params2.set("page", String(currentPage));
      data = await window.AppHttp.getJson(`/api/prices?${params2.toString()}`);
    }
    currentRows = data.rows || [];
    const ps = pageSize();
    const from = totalMatching === 0 ? 0 : (currentPage - 1) * ps + 1;
    const to = Math.min(totalMatching, currentPage * ps);
    let sum = `This page: ${currentRows.length} detail row(s) — positions ${from}–${to} of ${fmtInt(totalMatching)} matching filters.`;
    if (isPivot && totalMatching > currentRows.length) {
      sum += " Pivot only merges metrics within this page.";
    }
    summary.textContent = sum;
    renderRows(currentRows);
    renderPagination();
  }

  function openDialog() {
    if (!priceDetailDialog) return;
    try {
      if (typeof priceDetailDialog.showModal === "function") {
        priceDetailDialog.showModal();
      } else {
        priceDetailDialog.setAttribute("open", "");
      }
    } catch {
      priceDetailDialog.setAttribute("open", "");
    }
  }

  function closeDialog() {
    if (!priceDetailDialog) return;
    try {
      priceDetailDialog.close();
    } catch {
      priceDetailDialog.removeAttribute("open");
    }
  }

  async function openPriceDetail(priceId) {
    if (!priceDetailDialog || !priceDetailBody) return;
    priceDetailBody.innerHTML = '<div class="muted">Loading…</div>';
    openDialog();
    try {
      const row = await window.AppHttp.getJson(`/api/prices/row/${encodeURIComponent(priceId)}`);
      const fields = [
        ["id", row.id],
        ["vendor", row.vendor],
        ["platform", row.platform],
        ["model_series", row.model_series],
        ["model_name", row.model_name],
        ["context_bucket", row.context_bucket],
        ["deployment_scope", row.deployment_scope],
        ["billing_mode", row.billing_mode],
        ["metric_name", row.metric_name],
        ["price_region", row.price_region],
        ["price_currency", row.price_currency],
        ["amount", row.amount],
        ["unit_quantity", row.unit_quantity],
        ["unit_name", row.unit_name],
        ["unit_expression", row.unit_expression],
        ["effective_date", row.effective_date],
        ["retrieved_at_utc", row.retrieved_at_utc],
        ["source_id", row.source_id],
        ["source_url", row.source_url],
        ["notes", row.notes],
      ];
      const dl = fields
        .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
        .join("");
      const retail = row.source_detail && row.source_detail.retailItem;
      const loc = retail && retail.location ? retail.location : "";
      const locHtml = loc ? `<dt>location (API)</dt><dd>${esc(loc)}</dd>` : "";
      const jsonBlock = row.source_detail
        ? `<h4 class="muted" style="margin:12px 0 6px;">Source payload (JSON)</h4><pre class="priceDetailPre">${esc(JSON.stringify(row.source_detail, null, 2))}</pre>`
        : `<p class="muted" style="margin-top:10px;">No extended source payload (e.g. old CSV import). Notes and links still apply.</p>`;
      const links = `
        <div class="priceDetailLinks">
          <a id="priceDetailSourceLink" href="#" target="_blank" rel="noopener">Open source_url</a>
          <a href="https://azure.microsoft.com/en-us/pricing/details/azure-openai/" target="_blank" rel="noopener">Azure OpenAI marketing pricing page</a>
          <a href="https://prices.azure.com/api/retail/prices" target="_blank" rel="noopener">Microsoft unit price API (root)</a>
        </div>
      `;
      priceDetailBody.innerHTML = `
        <dl class="priceDetailDl">${dl}${locHtml}</dl>
        ${jsonBlock}
        ${links}
      `;
      const sl = priceDetailBody.querySelector("#priceDetailSourceLink");
      if (sl && row.source_url) {
        try {
          sl.href = new URL(row.source_url).href;
        } catch {
          sl.removeAttribute("href");
        }
      }
    } catch (e) {
      priceDetailBody.innerHTML = `<div style="color:#f87171;">Failed to load this row (id may be invalid or session expired).</div>`;
      console.error(e);
    }
  }

  async function doLogout() {
    try {
      await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      window.location = "/login";
    }
  }

  queryBtn.addEventListener("click", () => {
    currentPage = 1;
    loadRows().catch((e) => {
      console.error(e);
    });
  });

  if (pageSizeSelect) {
    pageSizeSelect.addEventListener("change", () => {
      currentPage = 1;
      loadRows().catch((e) => console.error(e));
    });
  }

  if (detailLayoutBtn) {
    detailLayoutBtn.addEventListener("click", () => {
      if (isPivot) return;
      isCompactDetail = !isCompactDetail;
      renderRows(currentRows);
    });
  }

  pivotBtn.addEventListener("click", () => {
    isPivot = !isPivot;
    renderRows(currentRows);
    const ps = pageSize();
    const from = totalMatching === 0 ? 0 : (currentPage - 1) * ps + 1;
    const to = Math.min(totalMatching, currentPage * ps);
    let sum = `This page: ${currentRows.length} detail row(s) — positions ${from}–${to} of ${fmtInt(totalMatching)} matching filters.`;
    if (isPivot && totalMatching > currentRows.length) {
      sum += " Pivot only merges metrics within this page.";
    }
    summary.textContent = sum;
    renderPagination();
  });

  exportBtn.addEventListener("click", () => {
    const csv = toCsv(currentRows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "model_prices_export_current_page.csv";
    a.click();
    URL.revokeObjectURL(url);
  });

  tbody.addEventListener("click", (ev) => {
    const btn = ev.target && ev.target.closest && ev.target.closest("button[data-price-id]");
    if (btn) {
      const pid = btn.getAttribute("data-price-id");
      if (pid) openPriceDetail(pid).catch((e) => console.error(e));
      return;
    }
    const row = ev.target && ev.target.closest && ev.target.closest("tr[data-row-price-id]");
    if (row) {
      const pid = row.getAttribute("data-row-price-id");
      if (pid) openPriceDetail(pid).catch((e) => console.error(e));
    }
  });

  tbody.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const row = ev.target && ev.target.closest && ev.target.closest("tr[data-row-price-id]");
    if (!row || ev.target.closest("button")) return;
    ev.preventDefault();
    const pid = row.getAttribute("data-row-price-id");
    if (pid) openPriceDetail(pid).catch((e) => console.error(e));
  });

  if (priceDetailClose && priceDetailDialog) {
    priceDetailClose.addEventListener("click", () => closeDialog());
    priceDetailDialog.addEventListener("click", (ev) => {
      if (ev.target === priceDetailDialog) closeDialog();
    });
  }

  if (syncRetailBtn) {
    syncRetailBtn.addEventListener("click", () => {
      openRetailSyncDialog().catch((e) => console.error(e));
    });
  }
  if (retailSyncClose && retailSyncDialog) {
    retailSyncClose.addEventListener("click", () => closeRetailSyncDialog());
    retailSyncDialog.addEventListener("click", (ev) => {
      if (ev.target === retailSyncDialog) closeRetailSyncDialog();
    });
  }
  if (retailSyncRun) {
    retailSyncRun.addEventListener("click", () => {
      runRetailSync().catch((e) => console.error(e));
    });
  }

  const logoutBtn = document.getElementById("logoutBtn");
  const logoutBtnTop = document.getElementById("logoutBtnTop");
  if (logoutBtn) logoutBtn.addEventListener("click", doLogout);
  if (logoutBtnTop) logoutBtnTop.addEventListener("click", doLogout);

  (async () => {
    await loadFilters();
    await loadSyncSeriesOptions();
    await loadRows();
  })().catch((e) => {
    console.error(e);
  });
})();
