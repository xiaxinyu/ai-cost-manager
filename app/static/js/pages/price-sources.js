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
      renderReferenceGuide(rows);
      tbody.innerHTML = "";
      for (const r of rows) {
        const tr = document.createElement("tr");
        tr.className = "priceDataRow";
        const id = r.id != null ? String(r.id) : "";
        const refUrl = r.reference_url || "";
        const apiUrl = r.api_url || "";
        tr.innerHTML = `
        <td class="cellTruncate" title="${esc(r.title)}">${esc(r.title)}</td>
        <td><code class="modelId">${esc(r.source_key)}</code></td>
        <td class="cellUrl" title="${esc(refUrl)}">${refUrl ? `<a href="${esc(refUrl)}" target="_blank" rel="noopener">${esc(refUrl)}</a>` : "—"}</td>
        <td class="cellUrl" title="${esc(apiUrl)}">${apiUrl ? `<a href="${esc(apiUrl)}" target="_blank" rel="noopener">${esc(apiUrl)}</a>` : "—"}</td>
        <td class="muted cellTruncate" title="${esc(r.notes || "")}">${esc(r.notes || "")}</td>
        <td class="colAction"><button type="button" class="editBtn" data-edit-id="${esc(id)}">Edit</button></td>
      `;
        tbody.appendChild(tr);
      }
      tbody.querySelectorAll("[data-edit-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const rid = btn.getAttribute("data-edit-id");
          const row = rows.find((x) => String(x.id) === rid);
          if (!row) return;
          editId.value = String(row.id);
          editTitle.value = row.title || "";
          editRef.value = row.reference_url || "";
          editApi.value = row.api_url || "";
          editNotes.value = row.notes || "";
          openDialog();
        });
      });
      window.AppDashboardUi?.applyTruncationTitles?.(tbody);
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

  if (refreshBtn) refreshBtn.addEventListener("click", () => loadRows().catch((e) => console.error(e)));
  window.AppDashboardUi?.makeSortableTable?.(priceSourcesTable);

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
