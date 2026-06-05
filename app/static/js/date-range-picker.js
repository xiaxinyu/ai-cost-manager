/* global window, document */

(function () {
  const MONTH_SHORT = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];

  function parseYmd(value) {
    if (!value) return null;
    const parts = String(value).trim().split("-").map(Number);
    if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function toYmd(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function todayLocal() {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  }

  function addDays(date, days) {
    const next = new Date(date);
    next.setDate(next.getDate() + days);
    return next;
  }

  function startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  function endOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth() + 1, 0);
  }

  function startOfQuarter(date) {
    const q = Math.floor(date.getMonth() / 3) * 3;
    return new Date(date.getFullYear(), q, 1);
  }

  function endOfQuarter(date) {
    const q = Math.floor(date.getMonth() / 3) * 3;
    return new Date(date.getFullYear(), q + 3, 0);
  }

  function daysInclusive(start, end) {
    const ms = end.getTime() - start.getTime();
    return Math.floor(ms / 86400000) + 1;
  }

  function formatMonthYear(date) {
    return `${MONTH_SHORT[date.getMonth()]} ${date.getFullYear()}`;
  }

  function formatMonthSpan(start, end) {
    if (start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth()) {
      return formatMonthYear(start);
    }
    if (start.getFullYear() === end.getFullYear()) {
      return `${MONTH_SHORT[start.getMonth()]} – ${MONTH_SHORT[end.getMonth()]} ${end.getFullYear()}`;
    }
    return `${MONTH_SHORT[start.getMonth()]} ${start.getFullYear()} – ${MONTH_SHORT[end.getMonth()]} ${end.getFullYear()}`;
  }

  function formatDaySpan(start, end) {
    if (start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth()) {
      return `${MONTH_SHORT[start.getMonth()]} ${start.getDate()} – ${end.getDate()}`;
    }
    return `${MONTH_SHORT[start.getMonth()]} ${start.getDate()} – ${MONTH_SHORT[end.getMonth()]} ${end.getDate()}`;
  }

  function formatRangeHint(start, end) {
    if (!start || !end) return "";
    if (start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth() && start.getDate() === 1 && end.getDate() === endOfMonth(end).getDate()) {
      return formatMonthYear(start);
    }
    if (start.getMonth() === 0 && start.getDate() === 1 && end.getMonth() === 11 && end.getDate() === 31 && start.getFullYear() === end.getFullYear()) {
      return String(start.getFullYear());
    }
    if (daysInclusive(start, end) <= 45) return formatDaySpan(start, end);
    return formatMonthSpan(start, end);
  }

  const PRESET_SECTIONS = [
    {
      id: "recommended",
      label: "Recommended",
      items: [
        { id: "last_7", label: "Last 7 days" },
        { id: "this_month", label: "This month" },
        { id: "custom", label: "Custom date range", action: "custom" },
      ],
    },
    {
      id: "relative",
      label: "Relative dates",
      items: [
        { id: "last_7", label: "Last 7 days" },
        { id: "last_30", label: "Last 30 days" },
      ],
    },
    {
      id: "calendar",
      label: "Calendar months",
      items: [
        { id: "this_month", label: "This month" },
        { id: "this_quarter", label: "This quarter" },
        { id: "this_year", label: "This year" },
        { id: "last_month", label: "Last month" },
        { id: "last_quarter", label: "Last quarter" },
        { id: "last_3_months", label: "Last 3 months" },
        { id: "last_6_months", label: "Last 6 months" },
        { id: "last_12_months", label: "Last 12 months" },
      ],
    },
  ];

  function computePresetRange(presetId, refDate = todayLocal()) {
    const today = refDate;
    switch (presetId) {
      case "last_7":
        return { start: addDays(today, -6), end: today };
      case "last_30":
        return { start: addDays(today, -29), end: today };
      case "this_month":
        return { start: startOfMonth(today), end: today };
      case "this_quarter":
        return { start: startOfQuarter(today), end: today };
      case "this_year":
        return { start: new Date(today.getFullYear(), 0, 1), end: today };
      case "last_month": {
        const prev = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        return { start: startOfMonth(prev), end: endOfMonth(prev) };
      }
      case "last_quarter": {
        const qStart = startOfQuarter(today);
        const prevQEnd = addDays(qStart, -1);
        return { start: startOfQuarter(prevQEnd), end: endOfQuarter(prevQEnd) };
      }
      case "last_3_months":
      case "last_6_months":
      case "last_12_months": {
        const n = presetId === "last_3_months" ? 3 : presetId === "last_6_months" ? 6 : 12;
        const end = endOfMonth(new Date(today.getFullYear(), today.getMonth() - 1, 1));
        const start = startOfMonth(new Date(end.getFullYear(), end.getMonth() - (n - 1), 1));
        return { start, end };
      }
      case "clear":
        return { start: null, end: null };
      default:
        return { start: null, end: null };
    }
  }

  function shiftRangeByWindow(startYmd, endYmd, direction) {
    const start = parseYmd(startYmd);
    const end = parseYmd(endYmd);
    if (!start || !end) return null;
    const span = daysInclusive(start, end);
    if (direction < 0) {
      const newEnd = addDays(start, -1);
      const newStart = addDays(newEnd, -(span - 1));
      return { start: newStart, end: newEnd };
    }
    const newStart = addDays(end, 1);
    const newEnd = addDays(newStart, span - 1);
    return { start: newStart, end: newEnd };
  }

  function rangesMatch(startYmd, endYmd, presetId, refDate = todayLocal()) {
    const preset = computePresetRange(presetId, refDate);
    if (!preset.start || !preset.end) return !startYmd && !endYmd;
    return toYmd(preset.start) === startYmd && toYmd(preset.end) === endYmd;
  }

  function detectActivePreset(startYmd, endYmd) {
    const ids = [
      "last_7", "last_30", "this_month", "this_quarter", "this_year",
      "last_month", "last_quarter", "last_3_months", "last_6_months", "last_12_months",
    ];
    for (const id of ids) {
      if (rangesMatch(startYmd, endYmd, id)) return id;
    }
    return null;
  }

  function buildPanelHtml() {
    const sections = PRESET_SECTIONS.map((section) => {
      const items = section.items
        .map((item) => {
          const hint = item.action === "custom" ? "" : formatRangeHint(
            computePresetRange(item.id).start,
            computePresetRange(item.id).end
          );
          const chevron = item.action === "custom" ? '<span class="dateRangePickerChevron" aria-hidden="true">›</span>' : `<span class="dateRangePickerHint">${hint}</span>`;
          return `<button type="button" class="dateRangePickerOption" data-preset="${item.id}" data-action="${item.action || "apply"}">${item.label}${chevron}</button>`;
        })
        .join("");
      return `<div class="dateRangePickerSection"><div class="dateRangePickerSectionLabel">${section.label}</div>${items}</div>`;
    }).join("");

    return `
      <div class="dateRangePickerNav">
        <button type="button" class="dateRangePickerNavBtn" data-shift="-1" aria-label="Previous period">‹ Previous</button>
        <button type="button" class="dateRangePickerNavBtn" data-shift="1" aria-label="Next period">Next ›</button>
      </div>
      ${sections}
      <div class="dateRangePickerFooter">
        <button type="button" class="dateRangePickerOption" data-preset="clear" data-action="apply">All dates</button>
        <button type="button" class="dateRangePickerOption" data-preset="custom" data-action="custom">
          Custom date range<span class="dateRangePickerChevron" aria-hidden="true">›</span>
        </button>
      </div>
    `;
  }

  /**
   * @param {object} opts
   * @param {HTMLInputElement} opts.startInput
   * @param {HTMLInputElement} opts.endInput
   * @param {(detail: {preset: string|null, start: string, end: string}) => void} [opts.onApply]
   * @param {boolean} [opts.autoApply]
   */
  function mount(opts = {}) {
    const { startInput, endInput, onApply, autoApply = false } = opts;
    if (!startInput || !endInput) return null;

    const root = document.createElement("div");
    root.className = "dateRangePicker";

    const inputsWrap = document.createElement("div");
    inputsWrap.className = "dateRangePickerInputs";

    const parent = startInput.parentElement;
    if (parent) {
      parent.insertBefore(root, startInput);
      root.appendChild(inputsWrap);
      inputsWrap.appendChild(startInput);
      const sep = document.createElement("span");
      sep.className = "dateRangePickerSep";
      sep.textContent = "–";
      sep.setAttribute("aria-hidden", "true");
      inputsWrap.appendChild(sep);
      inputsWrap.appendChild(endInput);
    }

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "dateRangePickerToggle";
    toggle.setAttribute("aria-label", "Quick date ranges");
    toggle.setAttribute("aria-haspopup", "dialog");
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = '<span class="dateRangePickerToggleIcon" aria-hidden="true"></span>';
    inputsWrap.appendChild(toggle);

    const panel = document.createElement("div");
    panel.className = "dateRangePickerPanel";
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Date range presets");
    panel.innerHTML = buildPanelHtml();
    root.appendChild(panel);

    let activePreset = null;
    let open = false;

    function refreshHints() {
      panel.querySelectorAll(".dateRangePickerOption[data-preset]:not([data-action='custom'])").forEach((btn) => {
        const id = btn.getAttribute("data-preset");
        if (!id || id === "custom") return;
        const range = computePresetRange(id);
        const hintEl = btn.querySelector(".dateRangePickerHint");
        if (hintEl) hintEl.textContent = formatRangeHint(range.start, range.end);
      });
    }

    function syncActiveOption() {
      activePreset = detectActivePreset(startInput.value, endInput.value);
      panel.querySelectorAll(".dateRangePickerOption[data-preset]").forEach((btn) => {
        const id = btn.getAttribute("data-preset");
        const isActive = id && id !== "custom" && id === activePreset;
        btn.classList.toggle("is-active", Boolean(isActive));
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function emitApply(preset = activePreset) {
      if (typeof onApply === "function") {
        onApply({
          preset,
          start: startInput.value || "",
          end: endInput.value || "",
        });
      }
    }

    function applyRange(start, end, preset = null) {
      startInput.value = start ? toYmd(start) : "";
      endInput.value = end ? toYmd(end) : "";
      activePreset = preset;
      syncActiveOption();
      if (autoApply) emitApply(preset);
    }

    function setPreset(presetId) {
      if (presetId === "clear") {
        applyRange(null, null, null);
        return;
      }
      const range = computePresetRange(presetId);
      applyRange(range.start, range.end, presetId);
    }

    function closePanel() {
      open = false;
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    }

    function openPanel() {
      refreshHints();
      syncActiveOption();
      open = true;
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
    }

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      if (open) closePanel();
      else openPanel();
    });

    panel.addEventListener("click", (e) => {
      const navBtn = e.target.closest("[data-shift]");
      if (navBtn) {
        const dir = Number(navBtn.getAttribute("data-shift"));
        const shifted = shiftRangeByWindow(startInput.value, endInput.value, dir);
        if (shifted) {
          applyRange(shifted.start, shifted.end, null);
          if (autoApply) emitApply(null);
        }
        return;
      }

      const option = e.target.closest(".dateRangePickerOption");
      if (!option) return;

      const action = option.getAttribute("data-action");
      if (action === "custom") {
        closePanel();
        startInput.focus();
        return;
      }

      const presetId = option.getAttribute("data-preset");
      if (!presetId) return;
      setPreset(presetId);
      closePanel();
      if (autoApply) emitApply(presetId);
    });

    function onDocClick(e) {
      if (!root.contains(e.target)) closePanel();
    }

    function onKeydown(e) {
      if (e.key === "Escape" && open) {
        e.preventDefault();
        closePanel();
      }
    }

    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeydown);

    startInput.addEventListener("change", () => {
      activePreset = detectActivePreset(startInput.value, endInput.value);
      syncActiveOption();
    });
    endInput.addEventListener("change", () => {
      activePreset = detectActivePreset(startInput.value, endInput.value);
      syncActiveOption();
    });

    syncActiveOption();

    return {
      setPreset,
      clear: () => setPreset("clear"),
      close: closePanel,
      destroy() {
        document.removeEventListener("click", onDocClick);
        document.removeEventListener("keydown", onKeydown);
        closePanel();
        root.remove();
      },
    };
  }

  window.AppDateRangePicker = {
    mount,
    computePresetRange,
    shiftRangeByWindow,
    detectActivePreset,
    toYmd,
    formatRangeHint,
    PRESET_SECTIONS,
  };
})();
