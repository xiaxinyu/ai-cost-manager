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

  window.AppDashboardUi = {
    crosshairPlugins,
    setPageLoading,
    bindFilterEnter,
  };
})();
