/* global window */

// Reusable Chart.js plugins (no bundler). Exposed as window.AppChartPlugins.

(function () {
  // Shade a region of the chart area from the start index to the end.
  // Usage: plugins: [window.AppChartPlugins.forecastHorizonShade({ startIndex, label: 'Forecast' })]
  function forecastHorizonShade({ startIndex, fill = 'rgba(245,158,11,0.08)', line = 'rgba(245,158,11,0.28)', label = 'Forecast' } = {}) {
    return {
      id: 'forecastHorizonShade',
      afterDatasetsDraw(chart) {
        const idx = Number(startIndex);
        if (!Number.isFinite(idx) || idx < 0) return;
        const ca = chart.chartArea;
        const xScale = chart.scales?.x;
        if (!ca || !xScale) return;
        const labels = chart.data?.labels || [];
        if (!labels.length) return;

        const last = Math.min(labels.length - 1, labels.length - 1);
        const startPx = xScale.getPixelForValue(labels[idx] ?? idx);
        const endPx = xScale.getPixelForValue(labels[last] ?? last);
        const left = Math.min(startPx, endPx);
        const right = Math.max(startPx, endPx);

        const ctx = chart.ctx;
        ctx.save();
        // Background shade
        ctx.fillStyle = fill;
        ctx.fillRect(left, ca.top, right - left, ca.bottom - ca.top);
        // Boundary line
        ctx.strokeStyle = line;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(left, ca.top);
        ctx.lineTo(left, ca.bottom);
        ctx.stroke();
        // Label
        ctx.fillStyle = 'rgba(200,212,224,0.85)';
        ctx.font = '600 11px system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(label, left + 6, ca.top + 14);
        ctx.restore();
      }
    };
  }

  window.AppChartPlugins = { forecastHorizonShade };
})();

