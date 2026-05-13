(() => {
  const projectSelect = document.getElementById("projectSelect");
  const windowDaysInput = document.getElementById("windowDaysInput");
  const refreshBtn = document.getElementById("refreshBtn");
  const baselineBox = document.getElementById("baselineBox");
  const warnBox = document.getElementById("warnBox");
  const tbody = document.getElementById("forecastTbody");
  const teamModelPanel = document.getElementById("teamModelPanel");
  const forecastHint = document.getElementById("forecastHint");

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

  function renderTeamModel(teamModel, projectName) {
    if (!teamModelPanel) return;
    if (!teamModel || !teamModel.model_name) {
      teamModelPanel.className = "modelPanel muted";
      teamModelPanel.innerHTML = `
        <p class="modelName" style="font-size:14px;font-weight:650;color:#e2e8f0;margin:0 0 6px">未绑定主力模型</p>
        <p style="margin:0">项目 <strong>${esc(projectName)}</strong> 尚未在 <a href="/tokens">Tokens</a> 页配置主力模型。
        配置后此处会显示模型名，便于在 <a href="/prices">Model Prices</a> 对照官方目录单价（预测金额仍以账单日均为准）。</p>
      `;
      return;
    }
    const ver = teamModel.api_version ? String(teamModel.api_version) : "—";
    teamModelPanel.className = "modelPanel";
    teamModelPanel.innerHTML = `
      <div class="modelName">${esc(teamModel.model_name)}</div>
      <div class="modelMeta">
        <span><strong>API 版本</strong>：${esc(ver)}</span>
        <span><strong>Endpoint</strong>：${teamModel.has_endpoint ? "已填写" : "未填"}</span>
      </div>
      <div class="modelActions">
        <a href="/tokens">在 Tokens 中修改绑定</a>
        <a href="/prices">打开 Model Prices 对照目录价</a>
      </div>
    `;
  }

  function renderForecastHint(baselineUsdPerDay) {
    if (!forecastHint) return;
    const scale = pizzaScale();
    const b = Number(baselineUsdPerDay);
    if (!lastBaseline || !lastBaseline.ok || !Number.isFinite(b) || b < 0) {
      forecastHint.textContent = "";
      return;
    }
    forecastHint.textContent = `计算方式：日均基线 ${fmtUsd(b)} × 披萨倍率 ${scale}× × 各列天数 → 下表「预计总成本」。`;
  }

  function renderTable(baselineUsdPerDay) {
    if (!tbody) return;
    renderForecastHint(baselineUsdPerDay);
    const scale = pizzaScale();
    const b = Number(baselineUsdPerDay);
    if (!Number.isFinite(b) || b < 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="muted">无有效基线。</td></tr>`;
      return;
    }
    const rows = HORIZONS.map(
      (h, idx) => `
      <tr>
        <td class="num colIdx">${idx + 1}</td>
        <td>${esc(h.label)}</td>
        <td class="num">${h.days}</td>
        <td class="num">${esc(fmtUsd(b * h.days * scale))}</td>
      </tr>`
    );
    tbody.innerHTML = rows.join("");
  }

  function setBaselineEmpty(msg, isMuted = true) {
    if (!baselineBox) return;
    baselineBox.classList.toggle("muted", isMuted);
    baselineBox.classList.toggle("baselineBoxEmpty", isMuted);
    baselineBox.textContent = msg;
  }

  function renderBaselineHtml(data) {
    if (!baselineBox) return;
    const cur = data.currency || "USD";
    baselineBox.classList.remove("muted", "baselineBoxEmpty");
    baselineBox.innerHTML = `
      <div class="baselineGrid">
        <div><strong>项目</strong><br />${esc(data.project)}</div>
        <div><strong>币种</strong><br />${esc(cur)}</div>
        <div><strong>窗口</strong><br />${esc(data.window_start)} → ${esc(data.window_end)}</div>
        <div><strong>日历天数</strong><br />${esc(String(data.window_days))} 天</div>
        <div><strong>窗口总成本</strong><br />${esc(fmtUsd(data.window_total_usd))}</div>
        <div><strong>日均基线</strong><br />${esc(fmtUsd(data.baseline_usd_per_day))} / 天</div>
      </div>
      <div class="baselineNotes">${esc(data.notes_zh || "")}</div>
    `;
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
      setBaselineEmpty("没有可选项目。请先导入账单。");
      if (teamModelPanel) {
        teamModelPanel.className = "modelPanel muted";
        teamModelPanel.textContent = "请选择账单项目。";
      }
      renderTable(NaN);
      return;
    }
    const proj = projectSelect.value;
    const wd = Math.min(90, Math.max(7, Number(windowDaysInput && windowDaysInput.value) || 28));
    if (windowDaysInput) windowDaysInput.value = String(wd);
    setBaselineEmpty("加载中…");
    if (warnBox) {
      warnBox.style.display = "none";
      warnBox.textContent = "";
    }
    if (teamModelPanel) {
      teamModelPanel.className = "modelPanel muted";
      teamModelPanel.textContent = "加载中…";
    }
    try {
      const data = await window.AppHttp.getJson(
        `/api/projects/${encodeURIComponent(proj)}/forecast-baseline?window_days=${wd}`
      );
      lastBaseline = data;
      renderTeamModel(data.team_model != null ? data.team_model : null, proj);
      if (!data.ok) {
        setBaselineEmpty("该项目暂无账单数据，无法计算基线。", true);
        renderTable(NaN);
        return;
      }
      renderBaselineHtml(data);
      if (warnBox && Number(data.baseline_usd_per_day) === 0) {
        warnBox.style.display = "block";
        warnBox.textContent =
          "最近窗口内日均成本为 0：外推结果均为 0。可缩短/拉长窗口或确认账单是否含 CostUSD。";
      }
      renderTable(data.baseline_usd_per_day);
    } catch (e) {
      console.error(e);
      setBaselineEmpty("加载失败（会话过期或网络错误）。", true);
      if (teamModelPanel) {
        teamModelPanel.className = "modelPanel muted";
        teamModelPanel.textContent = "无法加载模型信息，请重试或重新登录。";
      }
      renderTable(NaN);
    }
  }

  document.querySelectorAll('input[name="pizza"]').forEach((el) => {
    el.addEventListener("change", () => {
      if (lastBaseline && lastBaseline.ok) renderTable(lastBaseline.baseline_usd_per_day);
    });
  });

  if (projectSelect) {
    projectSelect.addEventListener("change", () => {
      refreshBaseline().catch((e) => console.error(e));
    });
  }

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
