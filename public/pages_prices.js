/* BuildCore 2.43 — Past prices on purchase requests and purchase orders.
   Picking a material that the project already bought fills the rate with its price (one price) or with the average of the
   latest three (prices differ), and a "Past prices" column shows the latest three. A "Past prices" panel under the lines
   lists them with the GRN, vendor and date. Typed rates are never changed. */
(function () {
  "use strict";
  if (window.__bcoPrices) return;
  window.__bcoPrices = true;

  const CACHE = {};
  const AUTO = new WeakMap();   // rows whose rate we filled, so changing the material refreshes it
  const load = async (pid) => {
    const key = String(pid || "");
    if (!CACHE[key]) {
      try { CACHE[key] = (await api("price.recent", { project_id: pid || null })).materials || {}; } catch (e) { CACHE[key] = {}; }
    }
    return CACHE[key];
  };
  const fmt = (x) => fmtMoney(x);
  const short = (s) => !s ? "" : s.latest.map((x) => fmt(x.rate)).join(" · ") + (s.scope === "company" ? " (other projects)" : "");

  function hook(cfg, field) {
    if (!cfg || cfg.__prices) return;
    const orig = cfg.lines;
    cfg.lines = function (d, ctx) {
      const cols = orig.call(this, d, ctx);
      const pid = (d && d.project_id) || S.project;
      const map = CACHE[String(pid || "")] || {};
      const out = cols.map((c) => {
        if (c.k !== "material_id") return c;
        return Object.assign({}, c, { onChange: (r, tr) => {
          const before = r[field];
          const mat = byId(S.L.materials, r.material_id);
          if (c.onChange) c.onChange(r, tr);
          const s = map[r.material_id];
          const auto = AUTO.has(r) && Number(AUTO.get(r)) === Number(before);
          const typed = Number(before) > 0 && !auto && !(mat && Number(before) === Number(mat.standard_rate));
          if (s && !typed) { r[field] = s.suggested; AUTO.set(r, s.suggested); }
        } });
      });
      const at = out.findIndex((c) => c.k === field);
      out.splice(at + 1, 0, { label: "Past prices (latest 3)", show: (r) => { const s = map[r.material_id]; return s ? (s.single ? "always " + fmt(s.suggested) + (s.scope === "company" ? " (other projects)" : "") : short(s)) : ""; } });
      return out;
    };
    cfg.__prices = true;
  }

  function panel(pid, getLines) {
    const box = h("div", { class: "panel", style: "margin-top:10px", "data-past-prices": "1" });
    let last = null;
    const render = () => load(pid).then((map) => {
      const lines = getLines();
      const key = JSON.stringify((lines || []).map((l) => l.material_id));
      if (key === last) return;
      last = key;
      box.innerHTML = "";
      const ids = [...new Set((lines || []).map((l) => l.material_id).filter(Boolean).map(String))];
      const rows = [];
      ids.forEach((m) => { const s = map[m]; if (s) s.latest.forEach((x, i) => rows.push({ mat: i ? "" : nm.mat(Number(m)), basis: i ? "" : (s.single ? "one price: " + fmt(s.suggested) : "suggested " + fmt(s.suggested) + " (average of latest " + s.latest.length + ")") + (s.scope === "company" ? " · other projects" : ""), ...x })); });
      box.append(h("b", {}, "Past prices"), rows.length
        ? table([{ k: "mat", label: "Material" }, { k: "basis", label: "Price used" }, { k: "date", label: "Date" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "vendor", label: "Vendor" }, { k: "grn", label: "GRN" }, { k: "project", label: "Project" }], rows, { search: false, export: false })
        : h("p", { class: "muted" }, "None of these materials has been bought before."));
      box.append(h("p", { class: "hint" }, "When a material was always bought at one price, that price is used; when prices differ, the average of the latest three. A rate you type is kept."));
    });
    render();
    box.refresh = render;
    return box;
  }

  /* make sure the prices are loaded before the window opens, and add the panel */
  if (typeof window.docEditor === "function" && !window.docEditor.__prices) {
    const orig = window.docEditor;
    const wrapped = async function (cfg, doc) {
      const field = cfg && cfg.type === "pr" ? "est_rate" : cfg && cfg.type === "po" ? "rate" : null;
      if (!field) return orig(cfg, doc);
      const pid = (doc && doc.project_id) || S.project;
      await load(pid);
      if (typeof PR !== "undefined") hook(PR, "est_rate");
      if (typeof PO !== "undefined") hook(PO, "rate");
      hook(cfg, field);
      const cfg2 = Object.assign({}, cfg, { after: (ctx) => {
        const r = cfg.after ? cfg.after(ctx) : null;
        const p = panel(pid, () => (ctx.le && ctx.le.lines ? ctx.le.lines() : (doc && doc.lines) || []));
        ctx.extra.append(p);
        const hookLines = () => { const prev = ctx.onLines; if (prev && prev.__pp43) return; const f = () => { if (prev) prev(); p.refresh(); }; f.__pp43 = true; ctx.onLines = f; };
        hookLines();
        Promise.resolve(r).then(hookLines);
        return r;
      } });
      return orig(cfg2, doc);
    };
    Object.keys(orig).forEach((k) => { wrapped[k] = orig[k]; });
    wrapped.__prices = true;
    window.docEditor = wrapped;
  }
})();
