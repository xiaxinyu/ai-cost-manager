(() => {
  let activeRequests = 0;
  let bar = document.getElementById("globalLoadingBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "globalLoadingBar";
    bar.className = "globalLoadingBar";
    document.body.appendChild(bar);
  }

  function showBar() {
    bar.style.width = "45%";
    window.requestAnimationFrame(() => {
      bar.style.width = "82%";
    });
  }

  function hideBar() {
    bar.style.width = "100%";
    window.setTimeout(() => {
      bar.style.width = "0";
    }, 120);
  }

  function explainStatus(status) {
    if (status === 401) return "Session expired. Please login again.";
    if (status === 403) return "No permission for this action.";
    if (status >= 500) return "Server error. Please retry later.";
    return `Request failed (${status})`;
  }

  async function getJson(url, options = {}) {
    activeRequests += 1;
    if (activeRequests === 1) showBar();
    try {
      const res = await fetch(url, { credentials: "same-origin", ...options });
      if (!res.ok) {
        const err = new Error(`HTTP ${res.status}`);
        err.status = res.status;
        throw err;
      }
      return await res.json();
    } catch (err) {
      if (window.AppShell?.toast) {
        const status = Number(err?.status || 0);
        const detail = String(err?.message || "").trim();
        const msg =
          detail && (status === 0 || detail.includes(":") || detail.length > 12)
            ? detail
            : explainStatus(status);
        window.AppShell.toast(msg.length > 280 ? `${msg.slice(0, 280)}…` : msg, "error", 4800);
      }
      throw err;
    } finally {
      activeRequests = Math.max(0, activeRequests - 1);
      if (activeRequests === 0) hideBar();
    }
  }

  async function postJson(url, body, options = {}) {
    activeRequests += 1;
    if (activeRequests === 1) showBar();
    try {
      const res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        body: JSON.stringify(body ?? {}),
        ...options,
      });
      if (!res.ok) {
        const err = new Error(`HTTP ${res.status}`);
        err.status = res.status;
        let detail = "";
        try {
          const j = await res.clone().json();
          detail = j.detail != null ? String(j.detail) : "";
        } catch {
          /* ignore */
        }
        if (detail) err.message = `${err.message}: ${detail}`;
        throw err;
      }
      return await res.json();
    } catch (err) {
      if (window.AppShell?.toast) {
        const status = Number(err?.status || 0);
        const detail = String(err?.message || "").trim();
        const msg =
          detail && (status === 0 || detail.includes(":") || detail.length > 12)
            ? detail
            : explainStatus(status);
        window.AppShell.toast(msg.length > 280 ? `${msg.slice(0, 280)}…` : msg, "error", 4800);
      }
      throw err;
    } finally {
      activeRequests = Math.max(0, activeRequests - 1);
      if (activeRequests === 0) hideBar();
    }
  }

  async function patchJson(url, body, options = {}) {
    activeRequests += 1;
    if (activeRequests === 1) showBar();
    try {
      const res = await fetch(url, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        body: JSON.stringify(body ?? {}),
        ...options,
      });
      if (!res.ok) {
        const err = new Error(`HTTP ${res.status}`);
        err.status = res.status;
        let detail = "";
        try {
          const j = await res.clone().json();
          detail = j.detail != null ? String(j.detail) : "";
        } catch {
          /* ignore */
        }
        if (detail) err.message = `${err.message}: ${detail}`;
        throw err;
      }
      return await res.json();
    } catch (err) {
      if (window.AppShell?.toast) {
        const status = Number(err?.status || 0);
        const detail = String(err?.message || "").trim();
        const msg =
          detail && (status === 0 || detail.includes(":") || detail.length > 12)
            ? detail
            : explainStatus(status);
        window.AppShell.toast(msg.length > 280 ? `${msg.slice(0, 280)}…` : msg, "error", 4800);
      }
      throw err;
    } finally {
      activeRequests = Math.max(0, activeRequests - 1);
      if (activeRequests === 0) hideBar();
    }
  }

  window.AppHttp = Object.assign(window.AppHttp || {}, { getJson, postJson, patchJson });
})();
