/**
 * Shared insight card panel for Cost, Tokens, and Reports dashboards.
 */
(function () {
  "use strict";

  const SEVERITY_LABELS = {
    info: "Info",
    watch: "Watch",
    action: "Action",
  };

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderCard(card) {
    const severity = card.severity || "info";
    const rec = card.recommendation
      ? `<p class="insightCardRec muted">${escapeHtml(card.recommendation)}</p>`
      : "";
    return `
      <article class="insightCard insightCard--${escapeHtml(severity)}" data-insight-id="${escapeHtml(card.id || "")}">
        <div class="insightCardHead">
          <span class="insightSeverity insightSeverity--${escapeHtml(severity)}">${escapeHtml(SEVERITY_LABELS[severity] || severity)}</span>
          <span class="insightCategory muted">${escapeHtml(card.category || "")}</span>
        </div>
        <h3 class="insightCardTitle">${escapeHtml(card.title || "")}</h3>
        <p class="insightCardSummary">${escapeHtml(card.summary || "")}</p>
        ${rec}
      </article>
    `;
  }

  /**
   * @param {HTMLElement|string} container
   * @param {Array<object>} insights
   * @param {{ limit?: number, title?: string, hideWhenEmpty?: boolean, emptyHtml?: string }} [options]
   */
  function render(container, insights, options) {
    const opts = options || {};
    const el =
      typeof container === "string" ? document.getElementById(container) : container;
    if (!el) return;

    const limit = opts.limit ?? 7;
    const cards = (insights || []).slice(0, limit);

    if (!cards.length) {
      const hide = opts.hideWhenEmpty !== false;
      el.innerHTML =
        opts.emptyHtml ||
        '<p class="insightPanelEmpty muted">No insights for this scope.</p>';
      el.hidden = hide;
      return;
    }

    el.hidden = false;
    const title = opts.title
      ? `<h3 class="insightPanelTitle">${escapeHtml(opts.title)}</h3>`
      : "";
    el.innerHTML = `${title}<div class="insightCardGrid">${cards.map(renderCard).join("")}</div>`;
  }

  window.AppInsightPanel = { render, renderCard, escapeHtml };
})();
