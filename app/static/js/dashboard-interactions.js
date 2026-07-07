/* global window, document */

(function () {
  function syncSectionNavVisibility({
    navSelector = ".dashSectionNav",
    linkSelector = ".dashSectionNavLink",
  } = {}) {
    const nav = document.querySelector(navSelector);
    if (!nav) return;
    for (const link of nav.querySelectorAll(linkSelector)) {
      const href = link.getAttribute("href") || "";
      if (!href.startsWith("#")) continue;
      const section = document.getElementById(href.slice(1));
      const hidden =
        !section ||
        section.hidden ||
        section.getAttribute("aria-hidden") === "true" ||
        section.offsetParent === null;
      link.classList.toggle("is-unavailable", hidden);
      link.setAttribute("aria-disabled", hidden ? "true" : "false");
      if (hidden) link.removeAttribute("aria-current");
    }
  }

  function mountJumpTargets({ selector = "[data-dash-jump]" } = {}) {
    for (const el of document.querySelectorAll(selector)) {
      if (el.dataset.dashJumpBound === "1") continue;
      const target = el.getAttribute("data-dash-jump");
      if (!target) continue;
      el.dataset.dashJumpBound = "1";
      el.classList.add("dashJumpTarget");
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
      const go = () => {
        const node =
          target.startsWith("#")
            ? document.querySelector(target)
            : document.getElementById(target);
        if (!node || node.hidden) return;
        node.scrollIntoView({ behavior: "smooth", block: "start" });
        history.replaceState(null, "", target.startsWith("#") ? target : `#${target}`);
      };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      });
    }
  }

  function bindSelectableRows(
    tableEl,
    { onSelect, linkAttr = "data-drill-href", selectedClass = "is-rowSelected" } = {}
  ) {
    if (!tableEl) return () => {};
    const tbody = tableEl.tBodies?.[0] || tableEl.querySelector("tbody");
    if (!tbody) return () => {};

    let selected = null;
    const clear = () => {
      if (selected) selected.classList.remove(selectedClass);
      selected = null;
    };

    tbody.addEventListener("click", (e) => {
      const link = e.target.closest(`a[${linkAttr}]`);
      if (link) return;
      const tr = e.target.closest("tr");
      if (!tr || !tbody.contains(tr) || tr.classList.contains("emptyRow")) return;
      if (selected === tr) {
        clear();
        onSelect?.(null, tr);
        return;
      }
      clear();
      selected = tr;
      tr.classList.add(selectedClass);
      onSelect?.(tr, tr);
    });

    return clear;
  }

  function setChartFootnote(footnoteEl, text, { html = false } = {}) {
    if (!footnoteEl) return;
    const value = text || "—";
    if (html) footnoteEl.innerHTML = value;
    else footnoteEl.textContent = value;
    footnoteEl.hidden = !text;
  }

  function highlightChartPoint(chart, index, { activeColor = "#5eead4", dimOpacity = 0.35 } = {}) {
    if (!chart?.data?.datasets?.length) return;
    const ds = chart.data.datasets[0];
    const n = ds.data?.length || 0;
    if (index == null || index < 0 || index >= n) {
      if (Array.isArray(ds.pointBackgroundColor)) {
        ds.pointBackgroundColor = undefined;
        ds.pointRadius = 2;
      }
      chart.update("none");
      return;
    }
    ds.pointRadius = ds.data.map((_, i) => (i === index ? 6 : 2));
    ds.pointBackgroundColor = ds.data.map((_, i) =>
      i === index ? activeColor : `rgba(94, 234, 212, ${dimOpacity})`
    );
    chart.update("none");
  }

  function mountSectionNav({
    navSelector = ".dashSectionNav",
    linkSelector = ".dashSectionNavLink",
    offset = 92,
  } = {}) {
    const nav = document.querySelector(navSelector);
    if (!nav) return { destroy() {} };

    const links = [...nav.querySelectorAll(linkSelector)];
    if (!links.length) return { destroy() {} };

    const sections = [];
    for (const link of links) {
      const href = link.getAttribute("href") || "";
      if (!href.startsWith("#")) continue;
      const id = href.slice(1);
      const section = document.getElementById(id);
      if (!section) continue;
      section.classList.add("dashScrollSection");
      sections.push({ id, section, link });
      link.addEventListener("click", (e) => {
        if (link.classList.contains("is-unavailable")) {
          e.preventDefault();
          return;
        }
        e.preventDefault();
        section.scrollIntoView({ behavior: "smooth", block: "start" });
        history.replaceState(null, "", `#${id}`);
      });
    }

    if (!sections.length) return { destroy() {} };

    let activeId = "";
    const setActive = (id) => {
      if (!id || id === activeId) return;
      activeId = id;
      for (const { id: sid, link } of sections) {
        const on = sid === id && !link.classList.contains("is-unavailable");
        link.classList.toggle("is-active", on);
        if (on) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
    };

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible.length) setActive(visible[0].target.id);
      },
      { rootMargin: `-${offset}px 0px -55% 0px`, threshold: [0, 0.15, 0.4] }
    );

    for (const { section } of sections) observer.observe(section);

    let btn = document.querySelector(".dashBackToTop");
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dashBackToTop";
      btn.setAttribute("aria-label", "Back to top");
      btn.innerHTML = '<span aria-hidden="true">↑</span>';
      document.body.appendChild(btn);
      btn.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    }

    const onScroll = () => {
      btn.classList.toggle("is-visible", window.scrollY > 420);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    syncSectionNavVisibility({ navSelector, linkSelector });
    mountJumpTargets();

    const hash = window.location.hash?.replace(/^#/, "");
    if (hash && sections.some((s) => s.id === hash)) {
      requestAnimationFrame(() => setActive(hash));
    }

    return {
      destroy() {
        observer.disconnect();
        window.removeEventListener("scroll", onScroll);
        btn?.remove();
      },
      refresh() {
        syncSectionNavVisibility({ navSelector, linkSelector });
        mountJumpTargets();
      },
    };
  }

  let navController = null;

  function mountDashPage() {
    navController = mountSectionNav();
    return navController;
  }

  function refreshDashPage() {
    if (navController?.refresh) navController.refresh();
    else syncSectionNavVisibility();
    mountJumpTargets();
  }

  window.AppDashboardInteractions = {
    mountSectionNav,
    mountDashPage,
    refreshDashPage,
    syncSectionNavVisibility,
    mountJumpTargets,
    bindSelectableRows,
    setChartFootnote,
    highlightChartPoint,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountDashPage());
  } else {
    mountDashPage();
  }
})();
