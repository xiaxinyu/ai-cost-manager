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
    tokenInput: 'Estimated Input Tokens',
    tokenOutput: 'Estimated Output Tokens',
    tokenTotal: 'Estimated Total Tokens',
    tokenInputForecast: 'Estimated Input Tokens (Forecast 7d)',
    tokenOutputForecast: 'Estimated Output Tokens (Forecast 7d)',
    tokenTotalForecast: 'Estimated Total Tokens (Forecast 7d)',
  };

  window.AppChartStyle = { colors, labels };
})();

