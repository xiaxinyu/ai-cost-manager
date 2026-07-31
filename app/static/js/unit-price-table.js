/* global window */

(() => {
  const METER_METHODS = new Set(["meter_matched", "meter_matched_partial"]);

  function isMeterAllocated(method) {
    return METER_METHODS.has(method);
  }

  function fmtUsdPer1m(n, currency) {
    return window.AppMoney?.fmtCostPer1m(n, currency) ?? "—";
  }

  function periodEffectiveUsdPer1m(rows) {
    let inputCost = 0;
    let outputCost = 0;
    let inputTokens = 0;
    let outputTokens = 0;
    for (const row of rows || []) {
      if (!isMeterAllocated(row.allocation_method)) continue;
      const inTok = Number(row.input_tokens) || 0;
      const outTok = Number(row.output_tokens) || 0;
      const inCost = row.input_cost_usd;
      const outCost = row.output_cost_usd;
      if (inCost != null && inTok > 0) {
        inputCost += Number(inCost);
        inputTokens += inTok;
      }
      if (outCost != null && outTok > 0) {
        outputCost += Number(outCost);
        outputTokens += outTok;
      }
    }
    const round = (x) => window.AppMoney?.roundCost?.(x) ?? Math.round(x * 100) / 100;
    return {
      input:
        inputTokens > 0 && inputCost > 0
          ? round((inputCost / inputTokens) * 1_000_000)
          : null,
      output:
        outputTokens > 0 && outputCost > 0
          ? round((outputCost / outputTokens) * 1_000_000)
          : null,
    };
  }

  function periodEffectiveFromModel(model, dailyRows) {
    const fromApi =
      model?.period_effective_usd_per_1m_input != null ||
      model?.period_effective_usd_per_1m_output != null ||
      model?.effective_usd_per_1m_input != null ||
      model?.effective_usd_per_1m_output != null;
    if (fromApi) {
      return {
        input: model.period_effective_usd_per_1m_input ?? model.effective_usd_per_1m_input ?? null,
        output: model.period_effective_usd_per_1m_output ?? model.effective_usd_per_1m_output ?? null,
      };
    }
    const modelRows = (dailyRows || []).filter((r) => r.model_name === model.model_name);
    return periodEffectiveUsdPer1m(modelRows);
  }

  function appendUnitPriceCell(tr, text, { className = "" } = {}) {
    const td = document.createElement("td");
    td.className = ["num", className].filter(Boolean).join(" ");
    td.textContent = text ?? "—";
    tr.appendChild(td);
    return td;
  }

  function resolveModelRates(model, dailyRows, source = "opex") {
    const m = model || {};
    const periodEff = periodEffectiveFromModel(m, dailyRows);
    const catalogIn = _num(m.catalog_usd_per_1m_input);
    const catalogOut = _num(m.catalog_usd_per_1m_output);
    const opexIn = _num(periodEff.input ?? m.effective_usd_per_1m_input);
    const opexOut = _num(periodEff.output ?? m.effective_usd_per_1m_output);
    if (source === "market") {
      return { rateIn: catalogIn, rateOut: catalogOut, source: "market" };
    }
    if (source === "opex") {
      return {
        rateIn: opexIn ?? catalogIn,
        rateOut: opexOut ?? catalogOut,
        source: opexIn != null || opexOut != null ? "opex" : "market",
      };
    }
    return { rateIn: catalogIn, rateOut: catalogOut, source: "custom" };
  }

  function _num(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function renderScopedRows(models, { currency, dailyRows, tbody, onRowActivate } = {}) {
    if (!tbody) return false;
    const rows = (models || []).filter(
      (m) =>
        m.catalog_usd_per_1m_input != null ||
        m.catalog_usd_per_1m_output != null ||
        m.effective_usd_per_1m_input != null ||
        m.effective_usd_per_1m_output != null ||
        m.period_effective_usd_per_1m_input != null ||
        m.period_effective_usd_per_1m_output != null
    );
    if (!rows.length) {
      tbody.replaceChildren();
      return false;
    }

    const ccy = currency || "USD";
    const frag = document.createDocumentFragment();
    for (const m of rows) {
      const periodEff = periodEffectiveFromModel(m, dailyRows);
      const tr = document.createElement("tr");
      tr.className = "unitPriceSummaryRow";
      tr.dataset.modelName = m.model_name || "";
      tr.dataset.catalogIn = m.catalog_usd_per_1m_input ?? "";
      tr.dataset.catalogOut = m.catalog_usd_per_1m_output ?? "";
      tr.dataset.opexIn = periodEff.input ?? m.effective_usd_per_1m_input ?? "";
      tr.dataset.opexOut = periodEff.output ?? m.effective_usd_per_1m_output ?? "";
      tr.title = "Click to prepare Estimate link for this model";
      if (typeof onRowActivate === "function") {
        tr.tabIndex = 0;
        tr.addEventListener("click", () => onRowActivate(m, periodEff));
        tr.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onRowActivate(m, periodEff);
          }
        });
      }

      const tdModel = document.createElement("td");
      tdModel.className = "unitPriceModelCell";
      const code = document.createElement("code");
      code.textContent = m.model_name || "model";
      tdModel.appendChild(code);
      tr.appendChild(tdModel);

      appendUnitPriceCell(tr, fmtUsdPer1m(m.catalog_usd_per_1m_input, ccy), {
        className: "unitPriceList",
      });
      appendUnitPriceCell(tr, fmtUsdPer1m(m.catalog_usd_per_1m_output, ccy), {
        className: "unitPriceList",
      });

      const actualIn =
        periodEff.input != null && Number.isFinite(Number(periodEff.input))
          ? fmtUsdPer1m(periodEff.input, ccy)
          : "—";
      const actualOut =
        periodEff.output != null && Number.isFinite(Number(periodEff.output))
          ? fmtUsdPer1m(periodEff.output, ccy)
          : "—";
      appendUnitPriceCell(tr, actualIn, { className: "unitPriceBilling" });
      appendUnitPriceCell(tr, actualOut, { className: "unitPriceBilling" });
      frag.appendChild(tr);
    }
    tbody.replaceChildren(frag);
    return true;
  }

  function renderProjectRows(projectRates, { currency, tbody }) {
    if (!tbody) return false;
    const projects = projectRates || [];
    if (!projects.length) {
      tbody.replaceChildren();
      return false;
    }

    const ccy = currency || "USD";
    const frag = document.createDocumentFragment();
    for (const proj of projects) {
      const pn = proj.project_name || "project";
      for (const m of proj.models || []) {
        const tr = document.createElement("tr");
        tr.className = "reportUnitRatesProjectRow";

        const tdProj = document.createElement("td");
        tdProj.className = "reportUnitRatesProjectCell";
        tdProj.textContent = pn;
        tr.appendChild(tdProj);

        const tdModel = document.createElement("td");
        tdModel.className = "unitPriceModelCell";
        const code = document.createElement("code");
        code.textContent = m.model_name || "model";
        tdModel.appendChild(code);
        tr.appendChild(tdModel);

        appendUnitPriceCell(tr, fmtUsdPer1m(m.catalog_usd_per_1m_input, ccy), {
          className: "unitPriceList",
        });
        appendUnitPriceCell(tr, fmtUsdPer1m(m.catalog_usd_per_1m_output, ccy), {
          className: "unitPriceList",
        });
        appendUnitPriceCell(
          tr,
          m.effective_usd_per_1m_input != null
            ? fmtUsdPer1m(m.effective_usd_per_1m_input, ccy)
            : "—",
          { className: "unitPriceBilling" }
        );
        appendUnitPriceCell(
          tr,
          m.effective_usd_per_1m_output != null
            ? fmtUsdPer1m(m.effective_usd_per_1m_output, ccy)
            : "—",
          { className: "unitPriceBilling" }
        );
        frag.appendChild(tr);
      }
    }
    tbody.replaceChildren(frag);
    return true;
  }

  window.AppUnitPriceTable = {
    isMeterAllocated,
    fmtUsdPer1m,
    periodEffectiveUsdPer1m,
    periodEffectiveFromModel,
    resolveModelRates,
    appendUnitPriceCell,
    renderScopedRows,
    renderProjectRows,
  };
})();
