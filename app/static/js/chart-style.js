/* global window, Chart */

// Shared chart palette, typography, scales, and line-chart option builders.
(function () {
  const colors = {
    actual: '#5eead4',
    market: '#c084fc',
    cost: '#5eead4',
    catalog: '#c084fc',
    input: '#60a5fa',
    output: '#a78bfa',
    total: '#f59e0b',
  };

  const labels = {
    costActual: 'Actual',
    costMarket: 'Market',
    catalogMarket: 'Market',
    costForecast: 'CostUSD (Forecast 7d)',
    tokenInput: 'Input tokens',
    tokenOutput: 'Output tokens',
    tokenTotal: 'Total tokens',
    tokenInputForecast: 'Input tokens (forecast 7d)',
    tokenOutputForecast: 'Output tokens (forecast 7d)',
    tokenTotalForecast: 'Total tokens (forecast 7d)',
  };

  const theme = {
    fontFamily:
      'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
    tick: '#8fa3ba',
    grid: 'rgba(148, 163, 184, 0.11)',
    gridStrong: 'rgba(148, 163, 184, 0.18)',
    legend: '#d7dee9',
    tooltipBg: 'rgba(14, 19, 26, 0.96)',
    tooltipBorder: 'rgba(173, 196, 228, 0.24)',
    crosshair: 'rgba(148, 163, 184, 0.38)',
  };

  function applyDefaults() {
    if (typeof Chart === 'undefined') return;
    Chart.defaults.font.family = theme.fontFamily;
    Chart.defaults.color = '#e7edf6';
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.legend.labels.color = theme.legend;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.pointStyle = 'circle';
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
    Chart.defaults.plugins.legend.labels.boxHeight = 8;
    Chart.defaults.plugins.legend.labels.padding = 12;
    Chart.defaults.plugins.legend.labels.font = { size: 11, weight: '500' };
    Chart.defaults.plugins.tooltip.usePointStyle = true;
    Chart.defaults.plugins.tooltip.boxWidth = 8;
    Chart.defaults.plugins.tooltip.boxHeight = 8;
    Chart.defaults.plugins.tooltip.backgroundColor = theme.tooltipBg;
    Chart.defaults.plugins.tooltip.borderColor = theme.tooltipBorder;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.plugins.tooltip.titleFont = { size: 12, weight: '700' };
    Chart.defaults.plugins.tooltip.bodyFont = { size: 12, weight: '500' };
    Chart.defaults.plugins.tooltip.footerFont = { size: 11, weight: '500' };
    Chart.defaults.plugins.tooltip.displayColors = true;
    Chart.defaults.plugins.tooltip.boxPadding = 6;
    Chart.defaults.plugins.tooltip.caretSize = 6;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
  }

  /** Shorten YYYY-MM-DD (or YYYY-MM) for dense x-axes. */
  function formatDateTick(raw) {
    const s = String(raw ?? '').trim();
    const day = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (day) return `${day[2]}/${day[3]}`;
    const month = s.match(/^(\d{4})-(\d{2})$/);
    if (month) return `${month[1]}-${month[2]}`;
    return s;
  }

  /** Resolve category-scale tick value (index) to the chart label string. */
  function labelAtTick(scale, tickValue) {
    if (scale && typeof scale.getLabelForValue === 'function') {
      const fromScale = scale.getLabelForValue(tickValue);
      if (fromScale !== undefined && fromScale !== null && fromScale !== '') return fromScale;
    }
    const labels = scale?.chart?.data?.labels;
    if (Array.isArray(labels) && labels[tickValue] !== undefined) return labels[tickValue];
    return tickValue;
  }

  /** Full date for tooltip titles. */
  function formatFullDate(raw) {
    const s = String(raw ?? '').trim();
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return s;
    return `${m[1]}-${m[2]}-${m[3]}`;
  }

  function tooltipTitleFullDate(items) {
    const raw = items?.[0]?.label;
    return formatFullDate(raw);
  }

  function xAxisTicks(labelCount) {
    const n = Number(labelCount) || 0;
    const limit = n > 90 ? 6 : n > 55 ? 8 : n > 32 ? 10 : 12;
    return {
      color: theme.tick,
      font: { size: 11, weight: '500' },
      autoSkip: true,
      autoSkipPadding: 18,
      maxTicksLimit: limit,
      maxRotation: n > 28 ? 38 : 0,
      minRotation: 0,
      padding: 8,
      callback(value) {
        return formatDateTick(labelAtTick(this, value));
      },
    };
  }

  function yAxisCost(currency, { maxTicks = 6 } = {}) {
    return {
      ticks: {
        color: theme.tick,
        font: { size: 11, weight: '500' },
        maxTicksLimit: maxTicks,
        padding: 8,
        callback: (value) => window.AppMoney?.fmtCost(value, currency) ?? String(value),
      },
      beginAtZero: true,
      grid: { color: theme.grid, drawTicks: false },
      border: { display: false },
    };
  }

  function yAxisTokens({ maxTicks = 6 } = {}) {
    const fmt = (v) => {
      if (v === null || v === undefined || !Number.isFinite(Number(v))) return '';
      return Math.round(Number(v)).toLocaleString();
    };
    return {
      ticks: {
        color: theme.tick,
        font: { size: 11, weight: '500' },
        maxTicksLimit: maxTicks,
        padding: 8,
        callback: fmt,
      },
      beginAtZero: true,
      grid: { color: theme.grid, drawTicks: false },
      border: { display: false },
    };
  }

  function yAxisRatio({ maxTicks = 7, tickDecimals = 1 } = {}) {
    return {
      ticks: {
        color: theme.tick,
        font: { size: 11, weight: '500' },
        maxTicksLimit: maxTicks,
        padding: 8,
        callback: (value) => {
          const n = Number(value);
          if (!Number.isFinite(n)) return '';
          return n.toFixed(tickDecimals);
        },
      },
      beginAtZero: true,
      grid: { color: theme.grid, drawTicks: false },
      border: { display: false },
    };
  }

  function scalesForLineChart(currency, labelCount) {
    return {
      x: {
        ticks: xAxisTicks(labelCount),
        grid: { color: theme.grid, drawOnChartArea: false },
        border: { display: false },
      },
      y: yAxisCost(currency),
    };
  }

  function scalesForUnitChart(unitType, currency, labelCount) {
    const x = {
      ticks: xAxisTicks(labelCount),
      grid: { color: theme.grid, drawOnChartArea: false },
      border: { display: false },
    };
    let y = yAxisCost(currency);
    if (unitType === 'tokens') y = yAxisTokens();
    else if (unitType === 'ratio') y = yAxisRatio();
    return { x, y };
  }

  /** Minimal legend: small colored dots + short labels (no wide line swatches). */
  function pluginsLegend({ show = true, position = 'top', variant = 'default' } = {}) {
    const compact = variant === 'compact';
    return {
      legend: {
        display: show,
        position,
        align: 'start',
        maxHeight: compact ? 36 : 48,
        labels: {
          color: theme.legend,
          font: { size: compact ? 10.5 : 11, weight: '500' },
          usePointStyle: true,
          pointStyle: 'circle',
          boxWidth: compact ? 6 : 8,
          boxHeight: compact ? 6 : 8,
          padding: compact ? 6 : 10,
        },
        onHover: (e) => {
          if (e?.native?.target) e.native.target.style.cursor = 'pointer';
        },
        onLeave: (e) => {
          if (e?.native?.target) e.native.target.style.cursor = 'default';
        },
      },
    };
  }

  function pluginsTooltip(extraCallbacks = {}) {
    return {
      tooltip: {
        enabled: true,
        mode: 'index',
        intersect: false,
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        borderWidth: 1,
        padding: 12,
        titleMarginBottom: 8,
        bodySpacing: 6,
        callbacks: extraCallbacks,
      },
    };
  }

  function lineInteractionDefaults() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false, axis: 'x' },
      animation: { duration: 360, easing: 'easeOutQuart' },
      layout: { padding: { top: 10, right: 14, bottom: 6, left: 10 } },
      elements: {
        line: { borderJoinStyle: 'round', capBezierPoints: true },
        point: {
          radius: 0,
          hoverRadius: 5,
          hitRadius: 16,
          hoverBorderWidth: 2,
          borderWidth: 0,
        },
      },
    };
  }

  /**
   * Merge base line options with page-specific plugin overrides.
   */
  function buildLineChartOptions({
    currency = null,
    labelCount = 0,
    showLegend = true,
    legendVariant = 'default',
    tooltipCallbacks = {},
  } = {}) {
    const callbacks = {
      title: tooltipTitleFullDate,
      ...tooltipCallbacks,
    };
    return {
      ...lineInteractionDefaults(),
      plugins: {
        decimation: { enabled: true, algorithm: 'min-max', threshold: 80 },
        ...pluginsLegend({ show: showLegend, variant: legendVariant }),
        ...pluginsTooltip(callbacks),
      },
      scales: scalesForLineChart(currency, labelCount),
    };
  }

  function buildChartOptionsForUnit({
    unitType = 'currency',
    currency = null,
    labelCount = 0,
    showLegend = true,
    legendVariant = 'default',
    tooltipCallbacks = {},
  } = {}) {
    const callbacks = {
      title: tooltipTitleFullDate,
      ...tooltipCallbacks,
    };
    return {
      ...lineInteractionDefaults(),
      plugins: {
        decimation: { enabled: true, algorithm: 'min-max', threshold: 80 },
        ...pluginsLegend({ show: showLegend, variant: legendVariant }),
        ...pluginsTooltip(callbacks),
      },
      scales: scalesForUnitChart(unitType, currency, labelCount),
    };
  }

  function chartPluginsExtra() {
    const P = window.AppChartPlugins;
    const plugin = P?.hoverCrosshair?.({ color: theme.crosshair });
    return plugin ? [plugin] : [];
  }

  /** Point visibility: show dots when the series is short enough to read. */
  function pointRadiusForCount(n, { sparse = 3, dense = 0 } = {}) {
    const count = Number(n) || 0;
    return count <= 45 ? sparse : dense;
  }

  function datasetLineCurrency({
    label,
    data,
    borderColor,
    backgroundColor,
    fill = false,
    dashed = false,
    pointRadius = 2,
  }) {
    return {
      label,
      data,
      borderColor,
      backgroundColor,
      fill,
      tension: 0.28,
      pointRadius,
      pointHoverRadius: 5,
      pointHoverBorderColor: '#f3f6fa',
      pointHoverBackgroundColor: borderColor,
      borderWidth: dashed ? 2 : 2.5,
      borderDash: dashed ? [6, 4] : undefined,
      spanGaps: true,
      unitType: 'currency',
    };
  }

  window.AppChartStyle = {
    colors,
    labels,
    theme,
    applyDefaults,
    formatDateTick,
    labelAtTick,
    formatFullDate,
    tooltipTitleFullDate,
    xAxisTicks,
    yAxisCost,
    yAxisTokens,
    yAxisRatio,
    scalesForLineChart,
    scalesForUnitChart,
    pluginsLegend,
    pluginsTooltip,
    lineInteractionDefaults,
    buildLineChartOptions,
    buildChartOptionsForUnit,
    chartPluginsExtra,
    pointRadiusForCount,
    datasetLineCurrency,
  };
})();
