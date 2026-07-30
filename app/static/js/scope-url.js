/* global window */
/**
 * Shared reporting-scope URL helpers for Cost / Tokens deep links.
 * Query keys: project, subproject, start, end, model (optional).
 * Uses history.replaceState; preserves unrelated params (e.g. cost_debug) and hash.
 */
(function () {
  const KEYS = ["project", "subproject", "start", "end", "model"];

  function _trim(v) {
    if (v == null) return "";
    return String(v).trim();
  }

  function read(search) {
    const qs = new URLSearchParams(
      search == null ? window.location.search : String(search)
    );
    const out = {};
    for (const key of KEYS) {
      const v = _trim(qs.get(key));
      if (v) out[key] = v;
    }
    return out;
  }

  function buildSearch(scope, { preserve = true, baseSearch } = {}) {
    const qs = preserve
      ? new URLSearchParams(
          baseSearch == null ? window.location.search : String(baseSearch)
        )
      : new URLSearchParams();
    for (const key of KEYS) qs.delete(key);
    const s = scope || {};
    for (const key of KEYS) {
      const v = _trim(s[key]);
      if (v) qs.set(key, v);
    }
    const str = qs.toString();
    return str ? `?${str}` : "";
  }

  function write(scope, { preserve = true } = {}) {
    const search = buildSearch(scope, { preserve });
    const hash = window.location.hash || "";
    const next = `${window.location.pathname}${search}${hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next === cur) return;
    window.history.replaceState(null, "", next);
  }

  function href(path, scope, { preserve = false } = {}) {
    const base = path || "/";
    const search = buildSearch(scope, { preserve, baseSearch: preserve ? undefined : "" });
    return `${base}${search}`;
  }

  function fromDom({
    projectEl,
    subprojectEl,
    startEl,
    endEl,
    model,
  } = {}) {
    return {
      project: _trim(projectEl?.value),
      subproject: _trim(subprojectEl?.value),
      start: _trim(startEl?.value),
      end: _trim(endEl?.value),
      model: _trim(model),
    };
  }

  window.AppScopeUrl = {
    KEYS,
    read,
    write,
    href,
    buildSearch,
    fromDom,
  };
})();
