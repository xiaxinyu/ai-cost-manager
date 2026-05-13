(() => {
  const projectSelect = document.getElementById("projectSelect");
  const windowDaysInput = document.getElementById("windowDaysInput");
  const refreshBtn = document.getElementById("refreshBtn");
  const baselineBox = document.getElementById("baselineBox");
  const warnBox = document.getElementById("warnBox");
  const tbody = document.getElementById("forecastTbody");

  const HORIZONS = [
    { days: 1, label: "1 天" },
    { days: 7, label: "1 周" },
    { days: 15, label: "半个月" },
    { days: 30, label: "1 个月" },
  ];

  let lastBaseline = null;

  function fmtUsd(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "—";
    return x.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function pizzaScale() {
    const r = document.querySelector('input[name="pizza"]:checked');
    const v = Number(r && r.value);
    return v === 2 ? 2 : 1;
  }

  function renderTable(baselineUsdPerDay) {
    if (!tbody) return;
    const scale = pizzaScale();
    const b = Number(baselineUsdPerDay);
    if (!Number.isFinite(b) || b < 0) {
      tbody.innerHTML = `<tr><td colspan="3" class="muted">无有效基线。</td></tr>`;
      return;
    }
    const rows = HORIZONS.map(
      (h) => `
      <tr>
        <td>${esc(h.label)}</td>
        <td class="num">${h.days}</td>
        <td class="num">${esc(fmtUsd(b * h.days * scale))}</td>
      </tr>`
    );
    tbody.innerHTML = rows.join("");
  }

  async function loadProjects() {
    if (!projectSelect) return;
    const data = await window.AppHttp.getJson("/api/projects");
    const projects = data.projects || [];
    projectSelect.innerHTML = "";
    for (const p of projects) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      projectSelect.appendChild(opt);
    }
    if (projects.length === 0) {
      projectSelect.innerHTML = '<option value="">（无项目）</option>';
    }
  }

  async function refreshBaseline() {
    if (!projectSelect || !projectSelect.value) {
      if (baselineBox) baselineBox.textContent = "没有可选项目。请先导入账单。";
      return;
    }
    const wd = Math.min(90, Math.max(7, Number(windowDaysInput && windowDaysInput.value) || 28));
    if (windowDaysInput) windowDaysInput.value = String(wd);
    if (baselineBox) baselineBox.textContent = "加载中…";
    if (warnBox) {
      warnBox.style.display = "none";
      warnBox.textContent = "";
    }
    try {
      const data = await window.AppHttp.getJson(
        `/api/projects/${encodeURIComponent(projectSelect.value)}/forecast-baseline?window_days=${wd}`
      );
      lastBaseline = data;
      if (!data.ok) {
        if (baselineBox) baselineBox.textContent = "该项目暂无账单数据，无法计算基线。";
        renderTable(NaN);
        return;
      }
      const cur = data.currency || "USD";
      if (baselineBox) {
        baselineBox.classList.remove("muted");
        baselineBox.innerHTML = `
          <div><strong>项目</strong>：${esc(data.project)} · <strong>币种</strong>：${esc(cur)}</div>
          <div><strong>窗口</strong>：${esc(data.window_start)} → ${esc(data.window_end)}（共 ${data.window_days} 个日历天）</div>
          <div><strong>窗口总成本</strong>：${esc(fmtUsd(data.window_total_usd))}</div>
          <div><strong>日均基线</strong>：${esc(fmtUsd(data.baseline_usd_per_day))} / 天</div>
          <div class="muted" style="margin-top:8px">${esc(data.notes_zh || "")}</div>
        `;
      }
      if (warnBox && Number(data.baseline_usd_per_day) === 0) {
        warnBox.style.display = "block";
        warnBox.textContent =
          "最近窗口内日均成本为 0：外推结果均为 0。可缩短/拉长窗口或确认账单是否含 CostUSD。";
      }
      renderTable(data.baseline_usd_per_day);
    } catch (e) {
      console.error(e);
      if (baselineBox) baselineBox.textContent = "加载失败（会话过期或网络错误）。";
      renderTable(NaN);
    }
  }

  document.querySelectorAll('input[name="pizza"]').forEach((el) => {
    el.addEventListener("change", () => {
      if (lastBaseline && lastBaseline.ok) renderTable(lastBaseline.baseline_usd_per_day);
    });
  });

  if (refreshBtn) refreshBtn.addEventListener("click", () => refreshBaseline().catch((e) => console.error(e)));

  const logoutBtnTop = document.getElementById("logoutBtnTop");
  if (logoutBtnTop) {
    logoutBtnTop.addEventListener("click", async () => {
      try {
        await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
      } finally {
        window.location = "/login";
      }
    });
  }

  (async () => {
    await loadProjects().catch((e) => console.error(e));
    await refreshBaseline().catch((e) => console.error(e));
  })().catch((e) => console.error(e));
})();
