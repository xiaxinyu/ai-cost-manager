/* global window, document */

(function () {
  const M = window.AppMoney;

  function isMeterAllocated(method) {
    return method === "meter_matched" || method === "meter_matched_partial";
  }

  function allocationLabel(method) {
    switch (method) {
      case "meter_matched":
        return "Meter";
      case "meter_matched_partial":
        return "Meter (partial)";
      case "no_meter_match":
        return "No meter";
      default:
        return method || "—";
    }
  }

  function fmtInt(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
    return Math.round(Number(v)).toLocaleString();
  }

  function fmtRatio(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
    const x = Number(v);
    const ax = Math.abs(x);
    if (ax === 0) return "0.000";
    if (ax >= 0.2) return x.toFixed(3);
    return x.toFixed(4);
  }

  function fmtUsd(n, currency) {
    return M?.fmtCost(n, currency) ?? "—";
  }

  function fmtUsdPer1m(n, currency) {
    return M?.fmtCostPer1m(n, currency) ?? "—";
  }

  function fmtDeltaPct(actual, market) {
    if (actual == null || market == null || !Number.isFinite(Number(actual)) || !Number.isFinite(Number(market))) {
      return "—";
    }
    const a = Number(actual);
    const m = Number(market);
    if (m === 0) return a === 0 ? "0%" : "—";
    const pct = ((a - m) / m) * 100;
    const sign = pct > 0 ? "+" : "";
    return `${sign}${pct.toFixed(1)}%`;
  }

  function deltaClass(actual, market) {
    if (actual == null || market == null) return "deltaCell--na";
    const a = Number(actual);
    const m = Number(market);
    if (!Number.isFinite(a) || !Number.isFinite(m) || m === 0) return "deltaCell--na";
    const pct = ((a - m) / m) * 100;
    if (Math.abs(pct) < 0.05) return "deltaCell--flat";
    return pct > 0 ? "deltaCell--over" : "deltaCell--under";
  }

  function sortRows(rows) {
    return window.AppDashboardUi?.sortByDateDesc(rows, {
      tieBreak: (a, b) => String(a.model_name || "").localeCompare(String(b.model_name || "")),
    }) ?? rows;
  }

  function actualUnitPer1m(costUsd, tokens) {
    if (costUsd == null || tokens == null || Number(tokens) <= 0) return null;
    return M?.roundCost((Number(costUsd) / Number(tokens)) * 1_000_000) ?? null;
  }

  function outputInputRatio(row) {
    if (row.output_input_ratio != null && Number.isFinite(Number(row.output_input_ratio))) {
      return Number(row.output_input_ratio);
    }
    const inp = Number(row.input_tokens);
    const out = Number(row.output_tokens);
    if (inp > 0 && out != null) return out / inp;
    return null;
  }

  function totalCost(row) {
    if (row.total_cost_usd != null) return row.total_cost_usd;
    if (row.actual_cost_usd != null) return row.actual_cost_usd;
    const cin = row.input_cost_usd;
    const cout = row.output_cost_usd;
    if (cin != null && cout != null) return M?.roundCost(Number(cin) + Number(cout)) ?? null;
    if (cin != null) return cin;
    if (cout != null) return cout;
    return null;
  }

  function appendRow(tbody, row, { currency = "USD", variant = "tokens" } = {}) {
    const tr = document.createElement("tr");
    if (!isMeterAllocated(row.allocation_method)) tr.classList.add("rowNoMeter");
    const dateLabel = String(row.date || "").trim();
    const modelLabel = String(row.model_name || "").trim() || "—";
    if (dateLabel) tr.dataset.date = dateLabel;
    if (modelLabel && modelLabel !== "—") tr.dataset.modelName = modelLabel;

    const tdDate = document.createElement("td");
    tdDate.className = "tdDate mono";
    tdDate.textContent = dateLabel || "—";
    tr.appendChild(tdDate);

    const tdModel = document.createElement("td");
    tdModel.className = "tdModel";
    if (modelLabel === "—") {
      tdModel.textContent = "—";
    } else {
      const span = document.createElement("span");
      span.className = "modelNameLabel";
      span.textContent = modelLabel;
      tdModel.title = modelLabel;
      tdModel.appendChild(span);
    }
    tr.appendChild(tdModel);

    const tdInput = document.createElement("td");
    tdInput.className = "num tdInput";
    tdInput.textContent = fmtInt(row.input_tokens);
    tr.appendChild(tdInput);

    const tdOutput = document.createElement("td");
    tdOutput.className = "num tdOutput";
    tdOutput.textContent = fmtInt(row.output_tokens);
    tr.appendChild(tdOutput);

    const allocTitle = row.allocation_method ? `allocation: ${row.allocation_method}` : "";

    const tdInCost = document.createElement("td");
    tdInCost.className = "num tdInputCost tdCostActual";
    tdInCost.textContent = fmtUsd(row.input_cost_usd, currency);
    if (allocTitle) tdInCost.title = allocTitle;
    tr.appendChild(tdInCost);

    const tdOutCost = document.createElement("td");
    tdOutCost.className = "num tdOutputCost tdCostActual";
    tdOutCost.textContent = fmtUsd(row.output_cost_usd, currency);
    if (allocTitle) tdOutCost.title = allocTitle;
    tr.appendChild(tdOutCost);

    const tdTotalCost = document.createElement("td");
    tdTotalCost.className = "num tdTotalCost tdCostActual colEmphasis";
    const tCost = totalCost(row);
    tdTotalCost.textContent = fmtUsd(tCost, currency);
    if (allocTitle) tdTotalCost.title = allocTitle;
    tr.appendChild(tdTotalCost);

    if (variant === "cost") {
      const tdMarket = document.createElement("td");
      tdMarket.className = "num tdCostMarket";
      tdMarket.textContent = fmtUsd(row.catalog_cost_usd, currency);
      tr.appendChild(tdMarket);

      const tdDelta = document.createElement("td");
      tdDelta.className = `num mono deltaCell ${deltaClass(tCost, row.catalog_cost_usd)}`;
      tdDelta.textContent = fmtDeltaPct(tCost, row.catalog_cost_usd);
      tr.appendChild(tdDelta);
    }

    const tdBilling = document.createElement("td");
    tdBilling.className = "tdBilling";
    const badge = document.createElement("span");
    badge.className = `allocBadge alloc-${String(row.allocation_method || "none").replaceAll("_", "-")}`;
    badge.textContent = allocationLabel(row.allocation_method);
    tdBilling.title =
      row.allocation_method === "no_meter_match"
        ? "No billing Meter matched this model/day."
        : row.allocation_method === "meter_matched_partial"
          ? "Only one direction had meter rows."
          : "Input/opt costs summed from transaction Meter rows.";
    tdBilling.appendChild(badge);
    tr.appendChild(tdBilling);

    const unitIn =
      row.usd_per_1m_input != null
        ? row.usd_per_1m_input
        : actualUnitPer1m(row.input_cost_usd, row.input_tokens);
    const unitOut =
      row.usd_per_1m_output != null
        ? row.usd_per_1m_output
        : actualUnitPer1m(row.output_cost_usd, row.output_tokens);

    const tdUnitIn = document.createElement("td");
    tdUnitIn.className = "num tdUnitIn";
    if (isMeterAllocated(row.allocation_method) && unitIn != null) {
      tdUnitIn.textContent = fmtUsdPer1m(unitIn, currency);
    } else {
      tdUnitIn.textContent = "—";
      tdUnitIn.title = "Requires meter-matched input billing";
    }
    tr.appendChild(tdUnitIn);

    const tdUnitOut = document.createElement("td");
    tdUnitOut.className = "num tdUnitOut";
    if (isMeterAllocated(row.allocation_method) && unitOut != null) {
      tdUnitOut.textContent = fmtUsdPer1m(unitOut, currency);
    } else {
      tdUnitOut.textContent = "—";
      tdUnitOut.title = "Requires meter-matched output billing";
    }
    tr.appendChild(tdUnitOut);

    const tdRatio = document.createElement("td");
    tdRatio.className = "num tdRatio";
    tdRatio.textContent = fmtRatio(outputInputRatio(row));
    tr.appendChild(tdRatio);

    tbody.appendChild(tr);
    return tr;
  }

  function rowSummary(rows) {
    const list = rows || [];
    const meter = list.filter((r) => isMeterAllocated(r.allocation_method)).length;
    const withCost = list.filter(
      (r) => r.input_cost_usd != null || r.output_cost_usd != null || r.actual_cost_usd != null
    ).length;
    return { total: list.length, meter, withCost };
  }

  function exportCsv(rows, { currency = "USD", variant = "tokens", filename = "billing-detail.csv" } = {}) {
    const headers =
      variant === "cost"
        ? [
            "date",
            "model_name",
            "input_tokens",
            "output_tokens",
            "input_cost_usd",
            "output_cost_usd",
            "total_cost_usd",
            "catalog_cost_usd",
            "delta_pct",
            "allocation_method",
            "usd_per_1m_input",
            "usd_per_1m_output",
            "output_input_ratio",
          ]
        : [
            "date",
            "model_name",
            "input_tokens",
            "output_tokens",
            "input_cost_usd",
            "output_cost_usd",
            "total_cost_usd",
            "allocation_method",
            "usd_per_1m_input",
            "usd_per_1m_output",
            "output_input_ratio",
          ];

    const esc = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
      return s;
    };

    const lines = [headers.join(",")];
    for (const r of rows || []) {
      const tCost = totalCost(r);
      const unitIn =
        r.usd_per_1m_input != null
          ? r.usd_per_1m_input
          : actualUnitPer1m(r.input_cost_usd, r.input_tokens);
      const unitOut =
        r.usd_per_1m_output != null
          ? r.usd_per_1m_output
          : actualUnitPer1m(r.output_cost_usd, r.output_tokens);
      const base = [
        r.date,
        r.model_name,
        r.input_tokens,
        r.output_tokens,
        r.input_cost_usd,
        r.output_cost_usd,
        tCost,
      ];
      if (variant === "cost") {
        base.push(r.catalog_cost_usd);
        const m = r.catalog_cost_usd;
        const pct =
          tCost != null && m != null && Number(m) !== 0
            ? M?.roundCost(((Number(tCost) - Number(m)) / Number(m)) * 100)
            : "";
        base.push(pct);
      }
      base.push(
        r.allocation_method,
        unitIn,
        unitOut,
        outputInputRatio(r)
      );
      lines.push(base.map(esc).join(","));
    }

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  window.AppBillingDetailTable = {
    isMeterAllocated,
    allocationLabel,
    sortRows,
    appendRow,
    rowSummary,
    exportCsv,
    COL_COUNT: { tokens: 11, cost: 13 },
  };
})();
