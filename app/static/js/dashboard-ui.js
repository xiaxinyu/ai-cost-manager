/* global window, document */

(function () {
  function crosshairPlugins() {
    const P = window.AppChartPlugins;
    const color = window.AppChartStyle?.theme?.crosshair;
    const plugin = P?.hoverCrosshair?.({ color });
    return plugin ? [plugin] : [];
  }

  /**
   * @param {object} opts
   * @param {boolean} opts.loading
   * @param {HTMLElement|null} [opts.loadBtn]
   * @param {string} [opts.loadBtnLabel]
   * @param {string} [opts.loadBtnLoadingLabel]
   * @param {HTMLElement|null} [opts.pageRoot]
   * @param {string} [opts.chartHostSelector]
   * @param {HTMLElement[]|NodeList} [opts.chartHosts]
   * @param {HTMLElement[]|NodeList} [opts.disableEls]
   */
  function setPageLoading({
    loading,
    loadBtn = null,
    loadBtnLabel = 'Apply',
    loadBtnLoadingLabel = 'Loading…',
    pageRoot = null,
    chartHostSelector = '[data-chart-host], .chartCanvasHost, .chartCanvasWrap',
    chartHosts = null,
    disableEls = [],
  } = {}) {
    const hosts =
      chartHosts ||
      (pageRoot || document).querySelectorAll?.(chartHostSelector) ||
      [];
    hosts.forEach?.((el) => el.classList.toggle('is-chartLoading', loading));

    if (pageRoot) pageRoot.classList.toggle('is-loading', loading);

    if (loadBtn) {
      loadBtn.disabled = loading;
      loadBtn.classList.toggle('is-loading', loading);
      loadBtn.setAttribute('aria-busy', loading ? 'true' : 'false');
      if (loadBtn.dataset.defaultLabel === undefined) {
        loadBtn.dataset.defaultLabel = loadBtn.textContent?.trim() || loadBtnLabel;
      }
      loadBtn.textContent = loading ? loadBtnLoadingLabel : loadBtn.dataset.defaultLabel;
    }

    const extra = Array.isArray(disableEls) ? disableEls : [...(disableEls || [])];
    for (const el of extra) {
      if (!el) continue;
      el.disabled = loading;
    }
  }

  /** Newest period first; optional stable tie-break (e.g. model name A→Z). */
  function sortByDateDesc(rows, { dateKey = "date", tieBreak } = {}) {
    const list = [...(rows || [])];
    return list.sort((a, b) => {
      const da = String(a?.[dateKey] ?? "");
      const db = String(b?.[dateKey] ?? "");
      const byDate = db.localeCompare(da);
      if (byDate !== 0) return byDate;
      if (typeof tieBreak === "function") return tieBreak(a, b);
      return 0;
    });
  }

  function bindFilterEnter(filterRoot, onSubmit) {
    if (!filterRoot || typeof onSubmit !== 'function') return;
    filterRoot.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'textarea') return;
      e.preventDefault();
      onSubmit();
    });
  }

  /**
   * @param {object} opts
   * @param {boolean} opts.loading
   * @param {HTMLElement[]|NodeList} [opts.tableHosts]
   * @param {HTMLElement|null} [opts.pageRoot]
   */
  function setTableLoading({ loading, tableHosts = null, pageRoot = null } = {}) {
    const hosts =
      tableHosts ||
      (pageRoot || document).querySelectorAll?.('[data-table-host]') ||
      [];
    hosts.forEach?.((el) => {
      el.classList.toggle('is-tableLoading', loading);
      el.setAttribute('aria-busy', loading ? 'true' : 'false');
    });
  }

  /**
   * Client-side sort via delegated clicks on `th[data-sortable]`.
   * @param {HTMLTableElement|null} table
   * @param {{ skipSelector?: string }} [options]
   */
  function makeSortableTable(table, { skipSelector = 'tr.dashTableEmptyRow' } = {}) {
    if (!table || table.dataset.sortBound === '1') return;
    table.dataset.sortBound = '1';
    const tbody = table.tBodies[0];
    const thead = table.tHead;
    if (!tbody || !thead) return;

    table.addEventListener('click', (e) => {
      const th = e.target.closest?.('thead th[data-sortable]');
      if (!th || !table.contains(th)) return;
      const cur = th.getAttribute('aria-sort');
      const next = cur === 'ascending' ? 'descending' : 'ascending';
      thead.querySelectorAll('th').forEach((h) => {
        h.classList.remove('is-sorted');
        h.removeAttribute('aria-sort');
      });
      th.classList.add('is-sorted');
      th.setAttribute('aria-sort', next);

      const idx = th.cellIndex;
      const type = th.dataset.sortType || 'text';
      const dir = next === 'ascending' ? 1 : -1;
      const rows = [...tbody.rows].filter((r) => !r.matches(skipSelector));
      rows.sort((a, b) => {
        const ac = a.cells[idx];
        const bc = b.cells[idx];
        let av = ac?.dataset?.sortValue ?? ac?.textContent?.trim() ?? '';
        let bv = bc?.dataset?.sortValue ?? bc?.textContent?.trim() ?? '';
        if (type === 'number') {
          av = parseFloat(String(av).replace(/,/g, '')) || 0;
          bv = parseFloat(String(bv).replace(/,/g, '')) || 0;
          return (av - bv) * dir;
        }
        if (type === 'date') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return (
          String(av).localeCompare(String(bv), undefined, {
            numeric: true,
            sensitivity: 'base',
          }) * dir
        );
      });
      rows.forEach((r) => tbody.appendChild(r));
    });
  }

  /** Set `title` on truncated cells and always on file/url paths. */
  function applyTruncationTitles(root) {
    const scope = root || document;
    scope.querySelectorAll?.('.cellTruncate, .cellFile, .cellUrl, .itemMain').forEach((el) => {
      const text = el.textContent?.trim();
      if (!text) return;
      if (el.classList.contains('cellFile') || el.classList.contains('cellUrl')) {
        el.title = text;
        return;
      }
      if (el.scrollWidth > el.clientWidth) el.title = text;
    });
  }

  window.AppDashboardUi = {
    crosshairPlugins,
    setPageLoading,
    setTableLoading,
    bindFilterEnter,
    makeSortableTable,
    applyTruncationTitles,
    sortByDateDesc,
  };
})();
