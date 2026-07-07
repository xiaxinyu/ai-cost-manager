(() => {
  const tbody = document.getElementById("srcTbody");
  const refreshBtn = document.getElementById("refreshBtn");
  const editDialog = document.getElementById("editDialog");
  const editClose = document.getElementById("editClose");
  const editId = document.getElementById("editId");
  const editTitle = document.getElementById("editTitle");
  const editRef = document.getElementById("editRef");
  const editApi = document.getElementById("editApi");
  const editNotes = document.getElementById("editNotes");
  const editSave = document.getElementById("editSave");
  const refGuide = document.getElementById("priceSourceReference");
  const pageRoot = document.querySelector(".priceSourcesPage.dashPage");
  const tableHost = document.querySelector("[data-table-host]");
  const priceSourcesTable = document.getElementById("priceSourcesTable");
  const psKpiTotalEl = document.getElementById("psKpiTotal");
  const psKpiRefEl = document.getElementById("psKpiRef");
  const psKpiApiEl = document.getElementById("psKpiApi");
  const psCatalogBadgeEl = document.getElementById("psCatalogBadge");
  const psRowSelectionHintEl = document.getElementById("psRowSelectionHint");

  let catalogRows = [];
  let clearSourceRowSelect = null;

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function openDialog() {
    if (!editDialog) return;
    try {
      if (typeof editDialog.showModal === "function") editDialog.showModal();
      else editDialog.setAttribute("open", "");
    } catch {
      editDialog.setAttribute("open", "");
    }
  }

  function closeDialog() {
    if (!editDialog) return;
    try {
      editDialog.close();
    } catch {
      editDialog.removeAttribute("open");
    }
  }

  function openEditRow(row) {
    if (!row) return;
    editId.value = String(row.id);
    editTitle.value = row.title || "";
    editRef.value = row.reference_url || "";
    editApi.value = row.api_url || "";
    editNotes.value = row.notes || "";
    openDialog();
  }

  function updateSourceKpis(rows) {
    const total = rows.length;
    const refCount = rows.filter((r) => r.reference_url).length;
    const apiCount = rows.filter((r) => r.api_url).length;
    if (psKpiTotalEl) psKpiTotalEl.textContent = String(total);
    if (psKpiRefEl) psKpiRefEl.textContent = String(refCount);
    if (psKpiApiEl) psKpiApiEl.textContent = String(apiCount);
    if (psCatalogBadgeEl) psCatalogBadgeEl.textContent = total ? `${total} sources` : "—";
  }

  function updateSourceRowSelectionHint(tr) {
    if (!psRowSelectionHintEl) return;
    if (!tr) {
      psRowSelectionHintEl.hidden = true;
      psRowSelectionHintEl.replaceChildren();
      return;
    }
    const rowId = tr.dataset.sourceId || "";
    const row = catalogRows.find((x) => String(x.id) === rowId);
    const title = row?.title || tr.querySelector("td")?.textContent?.trim() || "—";
    const key = row?.source_key || tr.querySelector("code")?.textContent?.trim() || "—";
    const notes = row?.notes || tr.querySelector("td.muted")?.textContent?.trim() || "";
    psRowSelectionHintEl.hidden = false;
    psRowSelectionHintEl.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = title;
    psRowSelectionHintEl.append(
      document.createTextNode("Selected "),
      strong,
      document.createTextNode(` · ${key}`)
    );
    if (notes) {
      psRowSelectionHintEl.append(document.createTextNode(` · ${notes.slice(0, 120)}${notes.length > 120 ? "…" : ""}`));
    }
    if (row) {
      psRowSelectionHintEl.append(document.createTextNode(" · "));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "drillLink";
      btn.textContent = "Edit";
      btn.dataset.editId = String(row.id);
      psRowSelectionHintEl.append(btn);
    } else {
      psRowSelectionHintEl.append(document.createTextNode(" · click row again to clear"));
    }
  }

  function bindSourceRowSelect() {
    if (!priceSourcesTable || clearSourceRowSelect) return;
    clearSourceRowSelect = window.AppDashboardInteractions?.bindSelectableRows?.(priceSourcesTable, {
      onSelect(tr) {
        updateSourceRowSelectionHint(tr);
      },
    });
  }

  function renderReferenceGuide(rows) {
    if (!refGuide) return;
    if (!rows.length) {
      refGuide.innerHTML = `<p class="muted" style="margin:0 0 10px;line-height:1.45">No catalog rows yet. After first database init, reload this page.</p>
        <div class="psCatItem"><div class="psCatItemTitle">Fallback links</div>
        <div class="psCatLinkLine"><a href="https://azure.microsoft.com/en-us/pricing/details/azure-openai/" target="_blank" rel="noopener">Azure OpenAI — public pricing page</a></div>
        <div class="psCatLinkLine"><a href="https://prices.azure.com/api/retail/prices" target="_blank" rel="noopener">Microsoft unit price API (root)</a></div></div>`;
      return;
    }
    const bits = rows.map((s) => {
      const ref = s.reference_url
        ? `<div class="psCatLinkLine"><a href="${esc(s.reference_url)}" target="_blank" rel="noopener">Reference page</a></div>`
        : "";
      const api = s.api_url
        ? `<div class="psCatLinkLine"><a href="${esc(s.api_url)}" target="_blank" rel="noopener">API root</a></div>`
        : "";
      const note = s.notes ? `<div class="psCatNote muted">${esc(s.notes)}</div>` : "";
      return `<div class="psCatItem"><div class="psCatItemTitle">${esc(s.title || s.source_key || "")}</div>${ref}${api}${note}</div>`;
    });
    refGuide.innerHTML = bits.join("");
  }

  function setPageBusy(loading, { btn = refreshBtn, btnLabel = "Reload", btnLoading = "Loading…" } = {}) {
    window.AppDashboardUi?.setPageLoading?.({
      loading,
      loadBtn: btn,
      loadBtnLabel: btnLabel,
      loadBtnLoadingLabel: btnLoading,
      pageRoot,
    });
    window.AppDashboardUi?.setTableLoading?.({ loading, tableHosts: [tableHost] });
  }

  async function loadRows() {
    if (!tbody) return;
    setPageBusy(true);
    try {
      const data = await window.AppHttp.getJson("/api/price-sources");
      const rows = data.sources || [];
      catalogRows = rows;
      updateSourceKpis(rows);
      renderReferenceGuide(rows);
      if (clearSourceRowSelect) clearSourceRowSelect();
      updateSourceRowSelectionHint(null);
      tbody.innerHTML = "";
      for (const r of rows) {
        const tr = document.createElement("tr");
        tr.className = "priceDataRow dashRowSelectable";
        const id = r.id != null ? String(r.id) : "";
        tr.dataset.sourceId = id;
        const refUrl = r.reference_url || "";
        const apiUrl = r.api_url || "";
        tr.innerHTML = `
        <td class="cellTruncate" title="${esc(r.title)}">${esc(r.title)}</td>
        <td><code class="modelId">${esc(r.source_key)}</code></td>
        <td class="cellUrl" title="${esc(refUrl)}">${refUrl ? `<a href="${esc(refUrl)}" target="_blank" rel="noopener">${esc(refUrl)}</a>` : "—"}</td>
        <td class="cellUrl" title="${esc(apiUrl)}">${apiUrl ? `<a href="${esc(apiUrl)}" target="_blank" rel="noopener">${esc(apiUrl)}</a>` : "—"}</td>
        <td class="muted cellTruncate" title="${esc(r.notes || "")}">${esc(r.notes || "")}</td>
        <td class="colAction"><button type="button" class="editBtn" data-edit-id="${esc(id)}" data-no-row-select>Edit</button></td>
      `;
        tbody.appendChild(tr);
      }
      tbody.querySelectorAll("[data-edit-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const rid = btn.getAttribute("data-edit-id");
          const row = catalogRows.find((x) => String(x.id) === rid);
          if (row) openEditRow(row);
        });
      });
      window.AppDashboardUi?.applyTruncationTitles?.(tbody);
      window.AppDashboardInteractions?.refreshDashPage?.();
    } catch (e) {
      console.error(e);
    } finally {
      setPageBusy(false);
    }
  }

  if (editSave) {
    editSave.addEventListener("click", async () => {
      const id = Number(editId.value);
      if (!Number.isFinite(id) || id <= 0) return;
      setPageBusy(true, { btn: editSave, btnLabel: "Save", btnLoading: "Saving…" });
      try {
        await window.AppHttp.patchJson(`/api/price-sources/${id}`, {
          title: editTitle.value,
          reference_url: editRef.value,
          api_url: editApi.value,
          notes: editNotes.value,
        });
        if (window.AppShell?.toast) window.AppShell.toast("Saved.", "info", 2400);
        closeDialog();
        await loadRows();
      } catch (e) {
        console.error(e);
      } finally {
        setPageBusy(false, { btn: editSave, btnLabel: "Save", btnLoading: "Saving…" });
      }
    });
  }

  if (editClose && editDialog) {
    editClose.addEventListener("click", () => closeDialog());
    editDialog.addEventListener("click", (ev) => {
      if (ev.target === editDialog) closeDialog();
    });
  }

  psRowSelectionHintEl?.addEventListener("click", (ev) => {
    const btn = ev.target?.closest?.("button[data-edit-id]");
    if (!btn) return;
    const row = catalogRows.find((x) => String(x.id) === btn.getAttribute("data-edit-id"));
    if (row) openEditRow(row);
  });

  if (refreshBtn) refreshBtn.addEventListener("click", () => loadRows().catch((e) => console.error(e)));
  window.AppDashboardUi?.makeSortableTable?.(priceSourcesTable);
  bindSourceRowSelect();

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

  loadRows().catch((e) => console.error(e));
})();
