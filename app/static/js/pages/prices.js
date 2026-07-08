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
  const pricesStatusBarEl = document.getElementById("pricesStatusBar");
  const catalogBadgeEl = document.getElementById("catalogBadge");
  const priceRowSelectionHintEl = document.getElementById("priceRowSelectionHint");
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
  const pageRoot = document.querySelector(".pricePage.dashPage");
  const tableHost = document.getElementById("pricingTableShell");
  const pricesTable = document.getElementById("pricesTable");
  const filterRoot = document.querySelector("[data-filter-root]");

  let currentRows = [];
  let totalMatching = 0;
  let currentPage = 1;
  let isPivot = false;
  /** When not pivot: fewer table columns (Item … Series only). */
  let isCompactDetail = false;
  let clearPriceRowSelect = null;
  let catalogMeta = null;

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

  function formatUtcShort(value) {
    if (!value) return "—";
    const text = String(value).trim();
    if (!text) return "—";
    const normalized = text.includes("T") ? text : text.replace(" ", "T");
    const d = new Date(`${normalized.endsWith("Z") ? normalized : `${normalized}Z`}`);
    if (Number.isNaN(d.getTime())) return text.slice(0, 16);
    return d.toISOString().slice(0, 16).replace("T", " ");
  }

  function activeFilterCount() {
    return [vendorSelect?.value, platformSelect?.value, seriesSelect?.value].filter(Boolean).length;
  }

  function updateMetaKpis(meta) {
    catalogMeta = meta || catalogMeta;
    if (!catalogMeta) return;
    updatePricesStatusBar();
  }

  function updatePricesStatusBar() {
    const bar = pricesStatusBarEl;
    if (!bar || !catalogMeta) return;
    const total = Number(catalogMeta.total_rows) || 0;
    const sources = Array.isArray(catalogMeta.sources) ? catalogMeta.sources : [];
    const retail = sources.find((s) => String(s.source_id || "").includes("retail"));
    const latest = sources
      .map((s) => s.last_retrieved_at_utc)
      .filter(Boolean)
      .sort()
      .pop();
    const syncTs = retail?.last_retrieved_at_utc || latest;
    const filters = activeFilterCount();
    const mk = (html) => {
      const span = document.createElement("span");
      span.className = "statusPill";
      span.innerHTML = html;
      return span;
    };
    const pills = [
      mk(`<strong>${fmtInt(totalMatching || total)}</strong> matching`),
      mk(`<strong>${fmtInt(total)}</strong> in catalog`),
      mk(`<strong>${sources.length}</strong> sources`),
    ];
    if (syncTs) {
      pills.push(Object.assign(document.createElement("span"), { className: "statusPill", textContent: `Sync ${formatUtcShort(syncTs)}` }));
    }
    if (filters) {
      pills.push(Object.assign(document.createElement("span"), { className: "statusPill", textContent: `${filters} filter(s)` }));
    }
    bar.replaceChildren(...pills);
    bar.hidden = false;
  }

  async function loadMeta() {
    try {
      const meta = await window.AppHttp.getJson("/api/prices/meta");
      updateMetaKpis(meta);
    } catch (e) {
      console.error(e);
    }
  }

  function updatePriceRowSelectionHint(tr) {
    if (!priceRowSelectionHintEl) return;
    if (!tr) {
      priceRowSelectionHintEl.hidden = true;
      priceRowSelectionHintEl.replaceChildren();
      return;
    }
    const item = tr.querySelector(".itemMain code, .itemMain")?.textContent?.trim() || "—";
    const cells = tr.querySelectorAll("td");
    const metric = cells[3]?.textContent?.trim() || cells[2]?.textContent?.trim() || "—";
    const region = cells[4]?.textContent?.trim() || cells[3]?.textContent?.trim() || "—";
    const amount = tr.querySelector("td.num")?.textContent?.trim() || "—";
    const priceId = tr.querySelector("[data-price-id]")?.getAttribute("data-price-id")
      || tr.getAttribute("data-row-price-id")
      || "";
    priceRowSelectionHintEl.hidden = false;
    priceRowSelectionHintEl.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = item;
    priceRowSelectionHintEl.append(
      document.createTextNode("Selected "),
      strong,
      document.createTextNode(` · ${metric} · ${region} · ${amount}`)
    );
    if (priceId) {
      priceRowSelectionHintEl.append(document.createTextNode(" · "));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "drillLink";
      btn.textContent = "View detail";
      btn.dataset.priceId = priceId;
      priceRowSelectionHintEl.append(btn);
    } else {
      priceRowSelectionHintEl.append(document.createTextNode(" · click row again to clear"));
    }
  }

  function bindPriceRowSelect() {
    if (!pricesTable || clearPriceRowSelect) return;
    clearPriceRowSelect = window.AppDashboardInteractions?.bindSelectableRows?.(pricesTable, {
      onSelect(tr) {
        updatePriceRowSelectionHint(tr);
      },
    });
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

  function th(label, unit, { className = "", sortable = false, sortType = "text" } = {}) {
    const cls = [className, sortable ? "sortable" : ""].filter(Boolean).join(" ");
    const sortAttrs = sortable ? ` data-sortable data-sort-type="${sortType}"` : "";
    const unitHtml = unit ? `<span class="thUnit">${unit}</span>` : "";
    return `<th class="${cls}"${sortAttrs} scope="col"><span class="thLabel">${label}</span>${unitHtml}</th>`;
  }

  function setPricesLoading(loading, { btn = queryBtn, btnLabel = "Query", btnLoading = "Loading…" } = {}) {
    window.AppDashboardUi?.setPageLoading?.({
      loading,
      loadBtn: btn,
      loadBtnLabel: btnLabel,
      loadBtnLoadingLabel: btnLoading,
      pageRoot,
      disableEls: [
        vendorSelect,
        platformSelect,
        seriesSelect,
        pageSizeSelect,
        pivotBtn,
        detailLayoutBtn,
        exportBtn,
        syncRetailBtn,
      ],
    });
    window.AppDashboardUi?.setTableLoading?.({ loading, tableHosts: [tableHost] });
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
      await loadMeta();
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
      tr.className = "priceDataRow dashRowSelectable";
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      const rid = r.id != null ? String(r.id) : "";
      if (rid) tr.dataset.rowPriceId = rid;
      const serial = serialBase + i + 1;
      i += 1;
      tr.innerHTML = `
        <td class="num colRowNum">${fmtInt(serial)}</td>
        <td><div class="itemMain tdModelName"><code class="modelId">${esc(item)}</code></div><div class="itemSub muted" title="${esc(r.metric_name || "")}">${esc(r.metric_name || "")}</div></td>
        <td>${esc(r.deployment_scope || "")}</td>
        <td>${esc(r.billing_mode || "")}</td>
        <td>${esc(r.metric_name || "")}</td>
        <td>${esc(r.price_region || "")}</td>
        <td>${esc(r.price_currency || "")}</td>
        <td class="num" data-sort-value="${Number(r.amount) || 0}">${fmt(r.amount)}</td>
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
    window.AppDashboardUi?.applyTruncationTitles?.(tbody);
  }

  function renderDetailCompact(rows, serialBase) {
    tbody.innerHTML = "";
    let i = 0;
    for (const r of rows || []) {
      const tr = document.createElement("tr");
      tr.className = "priceDataRow priceRowClickable dashRowSelectable";
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
        <td><div class="itemMain tdModelName"><code class="modelId">${esc(item)}</code></div></td>
        <td>${esc(r.billing_mode || "")}</td>
        <td>${esc(r.metric_name || "")}</td>
        <td>${esc(r.price_region || "")}</td>
        <td>${esc(r.price_currency || "")}</td>
        <td class="num" data-sort-value="${Number(r.amount) || 0}">${fmt(r.amount)}</td>
        <td>${esc(r.unit_expression || "")}</td>
        <td>${esc(r.model_series || "")}</td>
      `;
      tbody.appendChild(tr);
    }
    window.AppDashboardUi?.applyTruncationTitles?.(tbody);
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
      tr.className = "priceDataRow dashRowSelectable";
      const item = `${r.model_name || ""}${r.context_bucket ? ` (${r.context_bucket})` : ""}`;
      const rid = r.detail_id != null ? String(r.detail_id) : "";
      if (rid) tr.dataset.rowPriceId = rid;
      const serial = serialBase + i + 1;
      i += 1;
      tr.innerHTML = `
        <td class="num colRowNum">${fmtInt(serial)}</td>
        <td><div class="itemMain tdModelName"><code class="modelId">${esc(item)}</code></div><div class="itemSub muted" title="${esc(r.billing_mode || "")}">${esc(r.billing_mode || "")}</div></td>
        <td>${esc(r.deployment_scope || "")}</td>
        <td>${esc(r.billing_mode || "")}</td>
        <td>${esc(r.price_region || "")}</td>
        <td>${esc(r.price_currency || "")}</td>
        <td class="num" data-sort-value="${r.input == null ? -1 : Number(r.input)}">${r.input == null ? "-" : fmt(r.input)}</td>
        <td class="num" data-sort-value="${r.cached_input == null ? -1 : Number(r.cached_input)}">${r.cached_input == null ? "-" : fmt(r.cached_input)}</td>
        <td class="num" data-sort-value="${r.output == null ? -1 : Number(r.output)}">${r.output == null ? "-" : fmt(r.output)}</td>
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
    window.AppDashboardUi?.applyTruncationTitles?.(tbody);
  }

  function renderPagination() {
    if (!paginationEl) return;
    const tp = totalPages();
    const ps = pageSize();
    const from = totalMatching === 0 ? 0 : (currentPage - 1) * ps + 1;
    const to = Math.min(totalMatching, currentPage * ps);
    paginationEl.innerHTML = "";
    const info = document.createElement("span");
    info.className = "pageInfo muted";
    info.textContent = `Showing ${from}–${to} of ${fmtInt(totalMatching)} (page ${currentPage} / ${tp})`;
    paginationEl.appendChild(info);

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "btnSmall pgBtn";
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
    next.className = "btnSmall pgBtn";
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
    if (clearPriceRowSelect) clearPriceRowSelect();
    updatePriceRowSelectionHint(null);
    if (detailLayoutBtn) {
      detailLayoutBtn.style.display = isPivot ? "none" : "";
      if (!isPivot) {
        detailLayoutBtn.textContent = isCompactDetail ? "Full columns" : "Compact";
      }
    }
    if (isPivot) {
      if (tableShell) tableShell.classList.remove("is-compact");
      thead.innerHTML = `
        ${th("#", "", { className: "num colRowNum" })}
        ${th("Item", "", { sortable: true })}
        ${th("Scope", "", { sortable: true })}
        ${th("Mode", "", { sortable: true })}
        ${th("Region", "", { sortable: true })}
        ${th("Currency", "", { sortable: true })}
        ${th("Input", "per unit", { className: "num", sortable: true, sortType: "number" })}
        ${th("Cached Input", "per unit", { className: "num", sortable: true, sortType: "number" })}
        ${th("Output", "per unit", { className: "num", sortable: true, sortType: "number" })}
        ${th("Unit", "", { sortable: true })}
        ${th("Series", "", { sortable: true })}
        ${th("Platform", "", { sortable: true })}
        ${th("Vendor", "", { sortable: true })}
        ${th("Details", "", { className: "colDetail" })}
      `;
      renderPivot(rows, serialBase);
      pivotBtn.textContent = "Detail view";
    } else if (isCompactDetail) {
      if (tableShell) tableShell.classList.add("is-compact");
      thead.innerHTML = `
        ${th("#", "", { className: "num colRowNum" })}
        ${th("Item", "", { sortable: true })}
        ${th("Mode", "", { sortable: true })}
        ${th("Metric", "", { sortable: true })}
        ${th("Region", "", { sortable: true })}
        ${th("Currency", "", { sortable: true })}
        ${th("Amount", "value", { className: "num", sortable: true, sortType: "number" })}
        ${th("Unit", "", { sortable: true })}
        ${th("Series", "", { sortable: true })}
      `;
      renderDetailCompact(rows, serialBase);
      pivotBtn.textContent = "Pivot view";
    } else {
      if (tableShell) tableShell.classList.remove("is-compact");
      thead.innerHTML = `
        ${th("#", "", { className: "num colRowNum" })}
        ${th("Item", "", { sortable: true })}
        ${th("Scope", "", { sortable: true })}
        ${th("Mode", "", { sortable: true })}
        ${th("Metric", "", { sortable: true })}
        ${th("Region", "", { sortable: true })}
        ${th("Currency", "", { sortable: true })}
        ${th("Amount", "value", { className: "num", sortable: true, sortType: "number" })}
        ${th("Unit", "", { sortable: true })}
        ${th("Series", "", { sortable: true })}
        ${th("Platform", "", { sortable: true })}
        ${th("Vendor", "", { sortable: true })}
        ${th("Effective Date", "", { sortable: true, sortType: "date" })}
        ${th("Details", "", { className: "colDetail" })}
      `;
      renderDetail(rows, serialBase);
      pivotBtn.textContent = "Pivot view";
    }
    if (!rows || rows.length === 0) {
      const tr = document.createElement("tr");
      tr.className = "emptyRow";
      const colspan = isPivot ? 14 : isCompactDetail ? 9 : 14;
      tr.innerHTML = `<td colspan="${colspan}" style="color:#9fb2c7;">No price rows for current filters.</td>`;
      tbody.appendChild(tr);
    }
    if (catalogBadgeEl) {
      catalogBadgeEl.textContent = totalMatching === 0 ? "—" : `${fmtInt(totalMatching)} matching`;
    }
  }

  function toCsv(rows) {
    const cols = ["id", "vendor", "platform", "model_series", "model_name", "context_bucket", "deployment_scope", "billing_mode", "metric_name", "price_region", "price_currency", "amount", "unit_expression", "effective_date"];
    const escCsv = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
    return [cols.join(","), ...rows.map((r) => cols.map((c) => escCsv(r[c])).join(","))].join("\n");
  }

  async function loadRows() {
    setPricesLoading(true);
    try {
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
      updateMetaKpis(catalogMeta);
      updatePricesStatusBar();
      renderRows(currentRows);
      renderPagination();
      window.AppDashboardInteractions?.refreshDashPage?.();
    } catch (e) {
      console.error(e);
      summary.textContent = "Failed to load prices.";
    } finally {
      setPricesLoading(false);
    }
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

  function submitQuery() {
    currentPage = 1;
    loadRows().catch((e) => console.error(e));
  }

  queryBtn.addEventListener("click", submitQuery);
  window.AppDashboardUi?.bindFilterEnter?.(filterRoot, submitQuery);
  window.AppDashboardUi?.makeSortableTable?.(pricesTable);
  bindPriceRowSelect();

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

  priceRowSelectionHintEl?.addEventListener("click", (ev) => {
    const btn = ev.target?.closest?.("button[data-price-id]");
    if (!btn) return;
    const pid = btn.getAttribute("data-price-id");
    if (pid) openPriceDetail(pid).catch((e) => console.error(e));
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
    await loadMeta();
    await loadRows();
  })().catch((e) => {
    console.error(e);
    setPricesLoading(false);
  });
})();
