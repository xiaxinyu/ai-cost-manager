/* global window */

// Shared chart style constants (colors + common label strings).
// Exposed as window.AppChartStyle for template-driven pages.

(function () {
  const colors = {
    cost: '#5eead4',
    input: '#60a5fa',
    output: '#a78bfa',
    total: '#f59e0b',
  };

  const labels = {
    costActual: 'CostUSD (Actual)',
    costForecast: 'CostUSD (Forecast 7d)',
    tokenInput: 'Input tokens',
    tokenOutput: 'Output tokens',
    tokenTotal: 'Total tokens',
    tokenInputForecast: 'Input tokens (forecast 7d)',
    tokenOutputForecast: 'Output tokens (forecast 7d)',
    tokenTotalForecast: 'Total tokens (forecast 7d)',
  };

  window.AppChartStyle = { colors, labels };
})();

