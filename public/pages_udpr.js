/* BuildCore 2.25 — Universal daily progress report (DPR).
   Adds tabs to Work › Daily progress (DPR): the smart DPR register, progress & acceptance, the issue register,
   DPR reports, work fronts & set-up, templates & fields. The menu, module names and groups are unchanged.
   The smart form saves through udpr.save, which runs the existing DPR engine underneath, so costing, logsheets,
   progress and the 2.24 checks behave exactly as before. The classic form stays one click away. */
(function () {
  "use strict";
  if (window.__bcoUdpr) return;
  window.__bcoUdpr = true;

  /* ───────────── small helpers ───────────── */
  const css = h("style", {}, ".stamp.st-returned{background:#fff1d6;color:#8a5300}.stamp.st-rejected{background:#fde2e1;color:#a01d16}" +
    ".stamp.st-locked{background:#e7e9ee;color:#333}.udpr-note{padding:8px 12px;border-radius:6px;margin:0 0 10px;background:#fff7e6;border:1px solid #f0d9a8}" +
    ".udpr-note.bad{background:#fdecea;border-color:#f2b8b5}.udpr-note.ok{background:#eaf6ee;border-color:#b7dfc3}.udpr-sec{border:1px solid #dde3ea;border-radius:8px;padding:10px 12px;margin:0 0 12px}" +
    ".udpr-sec h4{margin:0 0 6px}.udpr-sec .hint{margin:0 0 6px}.udpr-ms{display:flex;flex-wrap:wrap;gap:4px 12px}.udpr-ms label{white-space:nowrap}" +
    ".udpr-save{font-size:12px;color:#8a5300;margin-right:auto}.udpr-save.ok{color:#2c7a3f}.udpr-fig{font-size:11px;color:#555;white-space:nowrap}" +
    ".udpr-over{color:#b42318;font-weight:600}.udpr-tl td,.udpr-tl th{padding:3px 6px}.udpr-print h3{font-size:13px;margin:12px 0 4px;border-bottom:2px solid #1b5e86}" +
    ".udpr-print table{width:100%;border-collapse:collapse}.udpr-print th,.udpr-print td{border:1px solid #999;padding:3px 5px;font-size:11px;text-align:left;vertical-align:top}" +
    ".udpr-print td.n{text-align:right}.udpr-print .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:2px 12px;font-size:12px}" +
    ".udpr-print .sign{display:grid;grid-auto-flow:column;gap:16px;margin-top:36px;font-size:11px}.udpr-print .sign div{border-top:1px solid #333;text-align:center;padding-top:3px}" +
    ".udpr-print p{font-size:12px;margin:2px 0 6px;white-space:pre-wrap}.udpr-sel{display:flex;flex-wrap:wrap;gap:4px 14px;margin:4px 0 10px}");
  document.head.append(css);

  const NUM = new Set(["int", "decimal", "percent", "currency", "measure", "chainage"]);
  const REFS = new Set(["boq", "wbs", "equipment", "material"]);
  const SUMMARY = [["s_work", "Work carried out today"], ["s_achieve", "Key achievements"], ["s_activities", "Critical activities and their status"],
    ["s_problems", "Major problems"], ["s_instructions", "Instructions received"], ["s_decisions", "Decisions required"]];
  const WEATHER = ["Clear", "Cloudy", "Rain", "Heavy rain", "Snow", "Fog", "Windy", "Hot"].map((x) => [x, x]);
  const lsKey = (k) => "bco_udpr_" + k;
  const lsGet = (k) => { try { return JSON.parse(localStorage.getItem(lsKey(k)) || "null"); } catch (e) { return null; } };
  const lsSet = (k, v) => { try { if (v == null) localStorage.removeItem(lsKey(k)); else localStorage.setItem(lsKey(k), JSON.stringify(v)); } catch (e) { /* storage full or blocked */ } };
  const token = () => "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  const blank = (v) => v == null || v === "" || (Array.isArray(v) && !v.length);
  const num = (v) => (v === "" || v == null ? null : Number(v));
  const xdl = (x) => {
    if (!x || !x.b64) return;
    const a = document.createElement("a");
    a.href = "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + x.b64;
    a.download = x.filename; document.body.append(a); a.click(); a.remove();
  };
  const shown = (s, label) => h("span", { class: "stamp st-" + s }, label || String(s || "").replace(/_/g, " "));
  const role = () => (S.user && S.user.role) || "";
  const isAdmin = () => role() === "admin";

  let META = null;
  async function meta(force) {
    if (!S.project) return null;
    if (!META || force || META._p !== S.project) { META = await run("udpr.meta", { project_id: S.project }); META._p = S.project; }
    return META;
  }
  const frontName = (m, id) => { const f = (m.fronts || []).find((x) => String(x.id) === String(id)); return f ? (f.code ? f.code + " " : "") + f.name : ""; };
  const frontOpts = (m, kind) => (m.fronts || []).filter((f) => f.active !== 0 && (!kind || f.kind === kind)).map((f) => [f.id, (f.code ? f.code + " " : "") + f.name + (f.kind === "package" ? " (package)" : "")]);
  const actName = (id) => { const a = byId(S.P.activities, id); return a ? (a.code ? a.code + " " : "") + a.name : ""; };
  const unitOf = (r) => { const a = byId(S.P.activities, r.activity_id); return (a && a.unit) || (byId(S.L.boq, r.boq_item_id) || {}).unit || ""; };
  const refOpts = (t) => t === "boq" ? opt.boq(S.project) : t === "wbs" ? (S.P.wbs || []).map((w) => [w.id, (w.code ? w.code + " " : "") + w.name])
    : t === "equipment" ? opt.equipment() : t === "material" ? opt.materials() : [];
  const yesNo = [["Yes", "Yes"], ["No", "No"]];
  const fOpts = (f) => f.type === "select" || f.type === "multiselect" ? (f.options || []).map((o) => [o, o]) : (f.type === "yesno" || f.type === "checkbox") ? yesNo : refOpts(f.type);
  const fLabel = (f) => f.label + (f.unit ? " (" + f.unit + ")" : "");

  /* the same visibility rule as the engine (api_udpr.visible) */
  function visible(f, rec) {
    const si = f.show_if;
    if (!si) return true;
    const v = rec[si.field];
    const want = si.value;
    if (si.op === "filled") return !["", null, undefined, "No", "0"].includes(v) && !(Array.isArray(v) && !v.length);
    if (si.op === "empty") return blank(v);
    if (si.op === "eq") return String(v ?? "") === String(want ?? "");
    if (si.op === "ne") return String(v ?? "") !== String(want ?? "");
    if (si.op === "in") return (Array.isArray(want) ? want : String(want || "").split(",").map((x) => x.trim())).map(String).includes(String(v ?? ""));
    const a = parseFloat(v), b = parseFloat(want);
    if (isNaN(a) || isNaN(b)) return false;
    return si.op === "gt" ? a > b : a < b;
  }
  const canEditField = (f) => !(f.edit_roles || []).length || f.edit_roles.includes(role()) || isAdmin();

  async function uploadOne(file, m) {
    const qs = new URLSearchParams(Object.assign({ filename: file.name, mime: file.type || "" }, m));
    [...qs.keys()].forEach((k) => { const v = qs.get(k); if (v === "" || v === "null" || v === "undefined") qs.delete(k); });
    const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: file });
    const j = await r.json();
    if (!j.ok) { toast(j.error, "err"); throw new Error(j.error); }
    return j.data.id;
  }

  /* One input for a template field. Returns { el, get }. */
  function fInput(f, v, ro, onchg, ctx) {
    const t = f.type;
    const ch = () => { if (onchg) onchg(); };
    let el, get;
    if (t === "longtext") {
      el = h("textarea", { readonly: ro, rows: 2 }, v ?? "");
      get = () => el.value;
    } else if (t === "multiselect") {
      let arr = Array.isArray(v) ? v.map(String) : (typeof v === "string" && v.startsWith("[") ? (() => { try { return JSON.parse(v).map(String); } catch (e) { return []; } })() : (v ? String(v).split(",").map((x) => x.trim()) : []));
      el = h("span", { class: "udpr-ms" }, (f.options || []).map((o) => {
        const cb = h("input", { type: "checkbox", checked: arr.includes(String(o)), disabled: ro, onchange: () => { arr = arr.filter((x) => x !== String(o)); if (cb.checked) arr.push(String(o)); ch(); } });
        return h("label", {}, cb, " ", o);
      }));
      get = () => arr.slice();
    } else if (t === "file" || t === "photo") {
      let cur = v ?? "";
      const link = h("span");
      const show = () => { link.innerHTML = ""; if (cur) link.append(h("a", { href: fileUrl(cur), target: "_blank" }, t === "photo" ? "View photo" : "Open file"), " "); };
      show();
      const inp = h("input", { type: "file", accept: t === "photo" ? "image/*" : null, style: "display:none", onchange: async () => {
        const did = ctx && ctx.dprId && ctx.dprId();
        if (!did) { toast("Save the draft first, then attach the file.", "err"); inp.value = ""; return; }
        cur = String(await uploadOne(inp.files[0], { entity: "dpr", entity_id: did, dpr_id: did, project_id: S.project, kind: t === "photo" ? "photo" : "document", caption: f.label }));
        inp.value = ""; show(); ch();
      } });
      el = h("span", {}, link, ro ? null : inp, ro ? null : h("button", { class: "btn small", type: "button", onclick: () => inp.click() }, cur ? "Replace" : "Attach"));
      get = () => cur;
    } else if (t === "select" || t === "yesno" || t === "checkbox" || REFS.has(t)) {
      const opts = fOpts(f);
      if (ro) {
        el = h("span", { class: "ro" }, (opts.find((o) => String(o[0]) === String(v ?? "")) || [0, v ?? ""])[1]);
        get = () => v ?? "";
      } else if (opts.length > COMBO_FROM) {
        let cur = v ?? "";
        el = combo(opts, cur, (nv) => { cur = nv; ch(); }, { name: f.key, key: "udpr_" + t });
        get = () => cur;
      } else {
        el = h("select", {}, h("option", { value: "" }, "—"), opts.map(([a, b]) => h("option", { value: a, selected: String(a) === String(v ?? "") }, b)));
        get = () => el.value;
      }
    } else {
      const type = NUM.has(t) ? "number" : t === "date" ? "date" : t === "time" ? "time" : t === "datetime" ? "datetime-local" : "text";
      el = h("input", { type, value: v ?? "", readonly: ro, step: type === "number" ? "any" : null, min: f.min ?? null, max: f.max ?? null });
      get = () => el.value;
    }
    if (["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) { el.addEventListener("change", ch); el.addEventListener("input", ch); }
    return { el, get };
  }

  /* A "fields" section: one value per DPR, keyed section.field */
  function fieldsSection(s, values, ro, onchg, ctx) {
    const rec = {};
    const items = [];
    s.fields.forEach((f) => { const k = s.key + "." + f.key; rec[f.key] = k in values ? values[k] : (ctx.isNew ? f.default ?? "" : ""); });
    const grid = h("div", { class: "grid" });
    const vis = () => items.forEach((x) => { x.lab.style.display = visible(x.f, rec) ? "" : "none"; });
    s.fields.forEach((f) => {
      const inp = fInput(f, rec[f.key], ro || !canEditField(f), () => { rec[f.key] = inp.get(); vis(); onchg(); }, ctx);
      const lab = h("label", { class: "f" + (f.required ? " req" : "") + (f.type === "longtext" || f.type === "multiselect" ? " wide" : "") },
        h("span", {}, fLabel(f)), inp.el, f.note ? h("small", { class: "fhint" }, f.note) : null,
        (f.edit_roles || []).length && !canEditField(f) ? h("small", { class: "fhint" }, "Changed by " + f.edit_roles.join(", ").replace(/_/g, " ")) : null);
      items.push({ f, lab, inp });
      grid.append(lab);
    });
    vis();
    grid.values = () => { const o = {}; items.forEach((x) => { o[s.key + "." + x.f.key] = visible(x.f, rec) ? x.inp.get() : ""; }); return o; };
    return grid;
  }
  const colType = (t) => NUM.has(t) ? "number" : t === "date" ? "date" : t === "time" ? "time" : t === "datetime" ? "datetime-local" : null;
  function fieldCol(f, prefix) {
    const sel = f.type === "select" || f.type === "yesno" || f.type === "checkbox" || REFS.has(f.type);
    const c = { k: (prefix || "") + f.key, label: fLabel(f) + (f.required ? " *" : ""), w: f.type === "longtext" ? 220 : (sel ? 140 : (NUM.has(f.type) ? 80 : 120)) };
    if (sel) { c.type = "select"; c.options = fOpts(f); c.key = "udpr_" + f.type; }
    else if (colType(f.type)) c.type = colType(f.type);
    if (f.type === "multiselect") c.label += " (comma-separated)";
    if (!canEditField(f)) c.readonly = true;
    return c;
  }
  /* A "table" section: repeating rows */
  function tableSection(s, rows, ro, onchg, m, ctx) {
    const cols = s.fields.map((f) => fieldCol(f));
    if ((m.fronts || []).length) cols.unshift({ k: "_front_id", label: "Work front", type: "select", options: frontOpts(m), w: 140 });
    const dflt = {};
    s.fields.forEach((f) => { if (f.default != null && f.default !== "") dflt[f.key] = f.default; });
    const prepared = (rows || []).map((r) => { const x = Object.assign({}, r); s.fields.forEach((f) => { if (f.type === "multiselect" && typeof x[f.key] === "string" && x[f.key].startsWith("[")) { try { x[f.key] = JSON.parse(x[f.key]).join(", "); } catch (e) { /* keep text */ } } }); return x; });
    const ed = lineEditor(cols, prepared.length || ro ? prepared : (ctx.isNew ? [] : []), { readonly: ro, blank: dflt, onChange: onchg });
    ed.rows = () => ed.lines().filter((r) => s.fields.some((f) => !blank(r[f.key])));
    return ed;
  }

  /* ───────────── the smart DPR form ───────────── */
  async function smartDpr(id, ctx, override) {
    ctx = ctx || {};
    if (!S.project) return toast("Choose a project first.", "err");
    await loadProjectLists();
    const m = await meta(true);
    let g;
    if (id) g = await run("udpr.get", { id });
    else {
      const pre = await api("dpr.prefill", { project_id: S.project, date: today() });
      g = { dpr: { status: "draft", date: today(), shift: "day", project_id: S.project, work: pre.work || [], labour: pre.labour || [], equipment: pre.equipment || [], delays: [], photos: [] },
        head: {}, status_shown: "draft", status_label: "Draft", sections: m.sections, values: {}, rows: {}, rows_restricted: {}, problems: [], figures: {}, log: [], revisions: [], templates: m.templates, templates_outdated: [] };
      if (ctx.activity) {
        const a = byId(S.P.activities, ctx.activity);
        if (a) g.dpr.work = [{ activity_id: a.id, boq_item_id: a.boq_item_id, location: a.location, planned_qty: "", actual_qty: "", chainage_from: a.chainage_from ?? "", chainage_to: "" }];
      }
    }
    const d = g.dpr, hd = g.head || {};
    const rights = m.rights;
    const isNew = !d.id;
    const locked = !!hd.locked_at;
    const editable = d.status === "draft" && !locked && rights.edit && (isNew ? rights.create : true);
    const draftKey = isNew ? "new_" + S.project : "dpr_" + d.id;
    const tok = (override && override.client_token) || (isNew ? token() : null);
    const src = override || null;
    const cfgSec = m.cfg.sections || {};
    const fctx = { isNew, dprId: () => d.id };
    let ready = false;
    const dirty = () => { if (ready) markDirty(); };

    // ── header
    const hv = Object.assign({}, d, hd);
    if (src) Object.assign(hv, src.header || {}, src.summary || {});
    const fronts = (m.fronts || []).length > 0;
    const hf = form([{ k: "date", label: "Date", type: "date", req: true }, { k: "shift", label: "Shift", type: "select", noBlank: true, options: [["day", "Day"], ["night", "Night"]] },
      fronts ? { k: "package_id", label: "Package", type: "select", options: frontOpts(m, "package") } : null,
      fronts ? { k: "front_id", label: "Work front (main)", type: "select", options: frontOpts(m, "front") } : null,
      { k: "weather", label: "Weather", type: "select", options: WEATHER }, { k: "temp_min", label: "Temperature min (°C)", type: "number" }, { k: "temp_max", label: "Temperature max (°C)", type: "number" },
      { k: "humidity", label: "Humidity (%)", type: "number" }, { k: "rain_mm", label: "Rainfall (mm)", type: "number" }, { k: "weather_lost_hours", label: "Hours lost to weather", type: "number" },
      { k: "lost_day", label: "Whole day lost (weather / bandh / flood)", type: "check" }, { k: "site_condition", label: "Site condition" }, { k: "conditions", label: "Working conditions / access" },
      { k: "prepared_name", label: "Prepared by" }, { k: "checked_name", label: "Checked by" }, { k: "approved_name", label: "Approved by" },
      { k: "remarks", label: "General remarks", wide: true }].filter(Boolean).map((x) => Object.assign(x, { readonly: !editable })), hv, () => dirty());
    const sumF = form(SUMMARY.map(([k, l]) => ({ k, label: l, type: "textarea", wide: true, readonly: !editable })), hv, () => dirty());
    const nextF = form([{ k: "s_next", label: "Plan for tomorrow (work, resources, inspections needed)", type: "textarea", wide: true, readonly: !editable }], hv, () => dirty());

    // ── line sections become extra columns on the work rows
    const secs = g.sections || [];
    const lineSecs = secs.filter((s) => s.kind === "line");
    const lineFields = [];
    lineSecs.forEach((s) => s.fields.forEach((f) => lineFields.push(f)));
    const figs = g.figures || {};
    const withUx = (lines, src2) => (lines || []).map((ln) => {
      const x = Object.assign({}, ln);
      const ux = ln._ux || {};
      x._front_id = ux.front_id ?? "";
      if (src2 === "work") { x._package_id = ux.package_id ?? ""; x._delay_reason = ux.delay_reason ?? ""; lineFields.forEach((f) => { x["v_" + f.key] = (ux.vals || {})[f.key] ?? ""; }); }
      return x;
    });
    const fig = (r, k) => { const f = r.id ? figs[r.id] : null; return f ? f[k] : null; };
    const workCols = [];
    if (fronts) workCols.push({ k: "_front_id", label: "Work front", type: "select", options: frontOpts(m), w: 140 });
    workCols.push(
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 220, key: "activity", onChange: (r) => { const a = byId(S.P.activities, r.activity_id); if (a) { r.boq_item_id = r.boq_item_id || a.boq_item_id; r.location = r.location || a.location; } }, rerender: true },
      { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), w: 180, key: "boq" },
      { k: "location", label: "Location", w: 100 }, { k: "chainage_from", label: "Ch. from", type: "number", w: 70 }, { k: "chainage_to", label: "Ch. to", type: "number", w: 70 },
      { k: "planned_qty", label: "Planned today", type: "number", w: 75 }, { k: "actual_qty", label: "Reported today", type: "number", w: 75 },
      { label: "Unit", show: (r) => unitOf(r) },
      { label: "Scope", num: true, show: (r) => fig(r, "scope") == null ? "" : fmtQty(fig(r, "scope")) },
      { label: "Cum. reported", num: true, show: (r) => { const f = r.id ? figs[r.id] : null; if (!f) return ""; return fmtQty((f.prev_reported || 0) + (Number(r.actual_qty) || 0)) + (f.scope != null && (f.prev_reported || 0) + (Number(r.actual_qty) || 0) > f.scope ? " ▲ over scope" : ""); } },
      { label: "Accepted", num: true, show: (r) => fig(r, "accepted") == null ? (r.id ? "awaiting" : "") : fmtQty(fig(r, "accepted")) },
      { label: "Cum. accepted", num: true, show: (r) => fig(r, "current_accepted") == null ? "" : fmtQty(fig(r, "current_accepted")) },
      { label: "Balance", num: true, show: (r) => fig(r, "balance") == null ? "" : fmtQty(fig(r, "balance")) },
      { label: "%", num: true, show: (r) => fig(r, "progress_pct") == null ? "" : fmtN(fig(r, "progress_pct"), 1) + "%" });
    lineFields.forEach((f) => workCols.push(fieldCol(f, "v_")));
    workCols.push({ k: "_delay_reason", label: "Reason if below plan", w: 140 }, { k: "remarks", label: "Remarks", w: 120 });
    const work = lineEditor(workCols, withUx(src ? src.work : d.work, "work"), { readonly: !editable, onChange: () => dirty() });
    const labour = lineEditor([fronts ? { k: "_front_id", label: "Work front", type: "select", options: frontOpts(m), w: 130 } : null,
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 190, key: "activity" },
      { k: "trade_id", label: "Trade", type: "select", options: tradeOpts, w: 150, key: "trade" },
      { k: "party_id", label: "Subcontractor (if any)", type: "select", options: () => opt.parties(["subcontractor"]), w: 150 },
      { k: "count", label: "No.", type: "number", w: 55 }, { k: "hours", label: "Hours", type: "number", w: 55 }, { k: "ot_hours", label: "OT h", type: "number", w: 55 },
      { label: "Man-hours", num: true, show: (r) => fmtN((Number(r.count) || 0) * ((Number(r.hours) || 0) + (Number(r.ot_hours) || 0))) }].filter(Boolean),
    withUx(src ? src.labour : d.labour), { readonly: !editable, blank: { hours: 8 }, onChange: () => dirty() });
    const eqOpts = () => { const l = S.L.equipment.filter((e) => e.active && String(e.project_id) === String(S.project)); return (l.length ? l : S.L.equipment.filter((e) => e.active)).map((e) => [e.id, e.code + " " + e.name]); };
    /* 2.30: the output / attachment of each machine line (bucket, breaker…), as on the classic DPR, so the logsheet's
       split by output gets the line's output; a machine with outputs starts on its default one */
    let TOOLS = [];
    try { TOOLS = (await api("tool.list", {})).rows || []; } catch (e) { TOOLS = []; }
    const toolsOf = (eid) => TOOLS.filter((t) => String(t.equipment_id) === String(eid));
    const toolOf = (id) => TOOLS.find((t) => String(t.id) === String(id));
    const eqIn = withUx(src ? src.equipment : d.equipment);
    eqIn.forEach((r) => { const ts = toolsOf(r.equipment_id); if (ts.length && !r.tool_id && r.id == null) r.tool_id = (ts.find((t) => t.is_default) || ts[0]).id; });
    /* 2.35: opening = last closing, operator from the equipment list, hours = closing − opening, idle / breakdown asked */
    const mt = window.bcoDprMeter ? window.bcoDprMeter.create({ dprId: () => d.id }) : null;
    const eqCols = [fronts ? { k: "_front_id", label: "Work front", type: "select", options: frontOpts(m), w: 130 } : null,
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 180, key: "activity" },
      { k: "equipment_id", label: "Equipment", type: "select", options: eqOpts, w: 170, key: "equipment", onChange: (r) => { const e = byId(S.L.equipment, r.equipment_id); if (mt) mt.pick(r); else if (e && (r.meter_start === undefined || r.meter_start === "")) r.meter_start = e.meter; const ts = toolsOf(r.equipment_id); if (!ts.some((t) => String(t.id) === String(r.tool_id))) r.tool_id = (ts.find((t) => t.is_default) || ts[0] || {}).id || ""; }, rerender: true },
      TOOLS.length ? { k: "tool_id", label: "Output / attachment", type: "select", options: (r) => toolsOf(r.equipment_id).map((t) => [t.id, t.name]), w: 130, rerender: true } : null,
      { k: "operator", label: "Operator", w: 100 }, { k: "meter_start", label: "Open meter", type: "number", w: 75, onChange: (r, tr) => { if (mt) mt.meters(r, tr, "meter_start"); } }, { k: "meter_end", label: "Close meter", type: "number", w: 75, onChange: (r, tr) => { if (mt) mt.meters(r, tr, "meter_end"); } },
      { k: "hours", label: "Work h", type: "number", w: 55 }, { k: "idle_hours", label: "Idle h", type: "number", w: 55 }, { k: "breakdown_hours", label: "Down h", type: "number", w: 55 },
      { k: "output_qty", label: "Output", type: "number", w: 65 }, TOOLS.length ? { label: "Unit", show: (r) => (toolOf(r.tool_id) || {}).output_unit || "" } : null].filter(Boolean);
    const equipment = lineEditor(eqCols, eqIn, { readonly: !editable, onChange: () => dirty() });
    if (mt) mt.attach(equipment, eqCols, hf, { editable, isNew, date: d.date, shift: d.shift });
    const showDelays = cfgSec.delays || (d.delays || []).length > 0;
    const delays = lineEditor([{ k: "category", label: "Reason", type: "select", options: DELAY_CATS, w: 170 }, { k: "activity_id", label: "Affected activity", type: "select", options: () => actOpts(), w: 190, key: "activity" },
      { k: "hours", label: "Hours lost", type: "number", w: 70 }, { k: "description", label: "What happened", w: 240 },
      { k: "create_event", label: "Contract event?", type: "select", noBlank: true, options: [["0", "No"], ["1", "Yes, record as contract event"]] }],
    ((src ? src.delays : d.delays) || []).map((x) => Object.assign({}, x, { create_event: String(x.create_event || 0) })), { readonly: !editable, blank: { create_event: "0" }, onChange: () => dirty() });

    // ── problems: continuing issues are picked, new ones are typed
    const issueOpts = (m.open_issues || []).map((i) => [i.id, i.no + " " + i.title + (i.days_reported ? " (" + i.days_reported + " day(s))" : "")]);
    const probs = lineEditor([
      { k: "issue_id", label: "Continuing issue", type: "select", options: issueOpts, w: 220, rerender: true, onChange: (r) => { const i = (m.open_issues || []).find((x) => String(x.id) === String(r.issue_id)); if (i) { r.title = i.title; r.category = r.category || i.category || ""; r.front_id = r.front_id || i.front_id || ""; } } },
      { k: "title", label: "Or a new problem (title)", w: 200 },
      { k: "category", label: "Category", type: "select", options: (m.issue_categories || []).map((x) => [x, x]), w: 150 },
      fronts ? { k: "front_id", label: "Work front", type: "select", options: frontOpts(m), w: 130 } : null,
      { k: "hours", label: "Hours lost", type: "number", w: 60 }, { k: "impact", label: "Impact", w: 160 }, { k: "mitigation", label: "Action / mitigation", w: 160 },
      { k: "decision_required", label: "Decision required from", w: 140 }, { k: "responsible_party", label: "Responsible", w: 110 },
      { k: "claim_relevant", label: "Claim relevant?", type: "select", options: [["1", "Yes"], ["0", "No"]], w: 80 }, { k: "note", label: "Today's note", w: 160 }].filter(Boolean),
    ((src ? src.problems : g.problems) || []).map((p) => Object.assign({}, p, { claim_relevant: p.claim_relevant == null ? "" : String(p.claim_relevant) })), { readonly: !editable, onChange: () => dirty() });

    // ── template sections
    const values = Object.assign({}, g.values || {}, src ? src.values || {} : {});
    const rowsIn = Object.assign({}, g.rows || {}, src ? src.rows || {} : {});
    const secEls = [];
    let showAll = false;
    const secBox = (s) => {
      const hasData = s.kind === "fields" ? s.fields.some((f) => !blank(values[s.key + "." + f.key])) : (rowsIn[s.key] || []).length > 0 || (g.rows_restricted || {})[s.key];
      const grpOn = !s.group || cfgSec[s.group];
      const body = s.kind === "fields" ? fieldsSection(s, values, !editable, () => dirty(), fctx) : tableSection(s, rowsIn[s.key] || [], !editable, () => dirty(), m, fctx);
      const restricted = (g.rows_restricted || {})[s.key];
      const box = h("div", { class: "udpr-sec" }, h("h4", {}, s.label, h("small", { class: "muted" }, "  · " + s.template_name + " v" + s.version_no + (s.sensitive ? " · restricted" : ""))),
        s.note ? h("p", { class: "hint" }, s.note) : null,
        restricted ? h("p", { class: "hint" }, restricted + " stored row(s) are restricted to safety officers and managers; rows you add are kept with them.") : null, body);
      const el = { s, body, box, apply: () => { box.style.display = (showAll || hasData || (!s.advanced && grpOn)) ? "" : "none"; } };
      el.apply();
      secEls.push(el);
      return box;
    };
    const tableAndFieldSecs = secs.filter((s) => s.kind !== "line");
    const grpSecs = (grp) => tableAndFieldSecs.filter((s) => (s.group || "") === grp);
    const projSecs = tableAndFieldSecs.filter((s) => !["hse", "quality"].includes(s.group || ""));

    // ── autosave on this computer
    const saveState = h("span", { class: "udpr-save" });
    let timer = null;
    const collect = () => {
      const hv2 = hf.values();
      const header = { project_id: S.project, date: hv2.date, shift: hv2.shift, weather: hv2.weather || null, site_condition: hv2.site_condition, remarks: hv2.remarks,
        rain_mm: hv2.rain_mm, weather_lost_hours: hv2.weather_lost_hours, lost_day: hv2.lost_day, temp_min: hv2.temp_min, temp_max: hv2.temp_max, humidity: hv2.humidity,
        conditions: hv2.conditions, prepared_name: hv2.prepared_name, checked_name: hv2.checked_name, approved_name: hv2.approved_name };
      if (fronts) { header.package_id = hv2.package_id || null; header.front_id = hv2.front_id || null; }
      if (d.id) header.id = d.id;
      const summary = Object.assign({}, sumF.values(), nextF.values());
      const vals = {}, rows = {};
      secEls.forEach((x) => { if (x.s.kind === "fields") Object.assign(vals, x.body.values()); else rows[x.s.key] = x.body.rows(); });
      const strip = (ln) => { const o = {}; Object.keys(ln).forEach((k) => { if (!k.startsWith("_") && !k.startsWith("v_")) o[k] = ln[k]; }); return o; };
      const wl = work.lines().filter((ln) => ln.activity_id || ln.boq_item_id).map((ln) => {
        const v = {};
        lineFields.forEach((f) => { if (!blank(ln["v_" + f.key])) v[f.key] = ln["v_" + f.key]; });
        return Object.assign(strip(ln), { _ux: { front_id: ln._front_id || null, package_id: ln._package_id || (fronts ? hv2.package_id : null) || null, delay_reason: ln._delay_reason || null, vals: v } });
      });
      const ll = labour.lines().filter((ln) => ln.trade_id && Number(ln.count)).map((ln) => Object.assign(strip(ln), { _ux: { front_id: ln._front_id || null } }));
      const el = equipment.lines().filter((ln) => ln.equipment_id).map((ln) => Object.assign(strip(ln), { _ux: { front_id: ln._front_id || null } }));
      const out = { header, summary, work: wl, labour: ll, equipment: el, values: vals, rows, problems: probs.lines().filter((p) => p.issue_id || (p.title || "").trim()) };
      if (showDelays) out.delays = delays.lines().filter((x) => x.category || x.hours || x.description);
      if (tok) out.client_token = tok;
      return out;
    };
    function markDirty() {
      if (!editable) return;
      clearTimeout(timer);
      timer = setTimeout(() => { try { lsSet(draftKey, { ts: Date.now(), payload: collect() }); saveState.className = "udpr-save"; saveState.textContent = "Not yet saved · kept on this computer"; } catch (e) { /* ignore */ } }, 700);
    }

    // ── banners
    const notes = h("div");
    if (g.status_shown === "returned") notes.append(h("div", { class: "udpr-note" }, h("b", {}, "Returned for correction: "), hd.return_comment || ""));
    if (d.status === "rejected") notes.append(h("div", { class: "udpr-note bad" }, h("b", {}, "Rejected: "), hd.reject_reason || "", " · Use “Revise” to take it back to draft."));
    if (locked) notes.append(h("div", { class: "udpr-note" }, "Locked on " + String(hd.locked_at).slice(0, 16) + ". Locked reports cannot change; an approver can unlock with a reason."));
    if ((g.templates_outdated || []).length) notes.append(h("div", { class: "udpr-note" }, "This DPR keeps the template versions it was made with (" + g.templates_outdated.join(", ") + "); newer versions apply to new DPRs."));
    const local = lsGet(draftKey);
    if (editable && !src && local && local.payload && (!hd.updated_at || local.ts > Date.parse(String(hd.updated_at).replace(" ", "T")))) {
      notes.append(h("div", { class: "udpr-note" }, "This computer has changes to this DPR that were not saved (" + new Date(local.ts).toLocaleString() + "). ",
        h("button", { class: "btn small primary", onclick: () => { mod.close(); smartDpr(id, ctx, local.payload); } }, "Restore them"), " ",
        h("button", { class: "btn small", onclick: (e) => { lsSet(draftKey, null); e.target.parentNode.remove(); } }, "Discard")));
    }
    if (src) notes.append(h("div", { class: "udpr-note ok" }, "Unsaved changes restored from this computer. Save to keep them."));

    // ── photos
    const photoBox = h("div");
    const loadPhotos = async () => {
      photoBox.innerHTML = "";
      if (!d.id) return photoBox.append(h("p", { class: "hint" }, "Save the draft first, then add photos (each photo keeps its date and caption)."));
      const rows = await api("files.list", { dpr_id: d.id });
      photoBox.append(editable || rights.edit ? uploadButton({ entity: "dpr", entity_id: d.id, dpr_id: d.id, project_id: S.project, date: d.date, kind: "photo" }, loadPhotos, "Add photos", "image/*") : null, fileList(rows, loadPhotos));
    };
    loadPhotos();

    // ── quality / HSE / materials read from their own registers for the day
    const regBox = (title, cols, rows, empty) => h("div", { class: "udpr-sec" }, h("h4", {}, title), table(cols, rows || [], { search: false, export: false, empty }));
    const quality = () => h("div", {}, grpSecs("quality").map(secBox),
      g.quality ? regBox("Tests recorded in Quality (QA)", [{ k: "no", label: "No." }, { k: "test_type", label: "Test" }, { k: "location", label: "Location" }, { k: "status", label: "Status", fmt: "status" }], g.quality.tests, "No test on this day.") : null,
      g.quality ? regBox("Inspections", [{ k: "no", label: "No." }, { k: "title", label: "Inspection" }, { k: "result", label: "Result" }, { k: "status", label: "Status", fmt: "status" }], g.quality.inspections, "No inspection on this day.") : null,
      g.quality ? regBox("Non-conformances raised", [{ k: "no", label: "No." }, { k: "title", label: "NCR" }, { k: "status", label: "Status", fmt: "status" }], g.quality.ncrs, "No NCR on this day.") : null);
    const hse = () => h("div", {}, grpSecs("hse").map(secBox),
      regBox("Incidents in the HSE register", [{ k: "no", label: "No." }, { k: "kind", label: "Type" }, { label: "Details", v: (r) => r.restricted ? "restricted" : (r.description || "") }, { k: "status", label: "Status", fmt: "status" }], g.incidents, "No incident on this day."));
    const materials = () => regBox("Materials on the day (from the store ledger)", [{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "unit", label: "Unit" }, { k: "opening", label: "Opening", fmt: "qty" },
      { k: "received", label: "Received", fmt: "qty" }, { k: "issued", label: "Issued / consumed", fmt: "qty" }, { k: "closing", label: "Closing", fmt: "qty" }], g.materials_day, "No stock movement for this project on this day.");

    // ── layout: steps as tabs (the inputs keep their values across tabs)
    const fill = editable ? h("button", { class: "btn small", type: "button", onclick: () => {
      const ls = work.lines().filter((ln) => ln.activity_id || ln.boq_item_id);
      const txt = ls.map((ln) => "• " + (actName(ln.activity_id) || nm.boq(ln.boq_item_id)) + (ln.location ? " at " + ln.location : "") + ": " + fmtQty(ln.actual_qty || 0) + " " + unitOf(ln)).join("\n");
      sumF.set("s_work", txt); dirty();
    } }, "Fill “work carried out” from the work rows") : null;
    const stepBasics = h("div", {}, notes, hf, cfgSec.summary !== false ? h("div", { class: "udpr-sec" }, h("h4", {}, "Executive summary"), fill, sumF) : null);
    const stepWork = h("div", {}, h("p", { class: "hint" }, "Reported today is the site's quantity. The QS / engineer accepts it separately; progress and billing use the accepted quantity when the project is set to do so. Scope is the approved BOQ quantity including approved variations."),
      editable ? h("div", { class: "bar" }, h("span", { class: "hint grow" }, "Start from:"), ...[["schedule", "Today's scheduled activities"], ["boq", "BOQ items with balance"], ["wbs", "All open activities"]].map(([k, l]) =>
        h("button", { class: "btn small", type: "button", onclick: async () => { const rows = await run("udpr.import", { project_id: S.project, date: hf.values().date, source: k }); if (!rows.length) return toast("Nothing to add.", "err"); work.setLines(work.lines().filter((x) => x.activity_id || x.boq_item_id).concat(rows.map((x) => Object.assign({ _front_id: "" }, x)))); dirty(); toast(rows.length + " row(s) added", "ok"); } }, l))) : null,
      work);
    const stepRes = h("div", {}, cfgSec.labour !== false ? h("div", { class: "udpr-sec" }, h("h4", {}, "Manpower"), labour) : null,
      cfgSec.equipment !== false ? h("div", { class: "udpr-sec" }, h("h4", {}, "Equipment"), h("p", { class: "hint" }, "Machine logsheets are made from these lines on approval, as before." + (mt ? " " + window.bcoDprMeter.HINT : "")), equipment) : null,
      showDelays ? h("div", { class: "udpr-sec" }, h("h4", {}, "Delays (hours lost)"), delays) : null);
    const stepIssues = h("div", {}, h("p", { class: "hint" }, "Pick a continuing issue to add today's day to it (one issue, one line per day), or type a new one: it goes to the issue register. Hours lost here are for the issue history; contract delay hours stay under Delays."), probs);
    const advToggle = h("label", { class: "f check" }, h("input", { type: "checkbox", onchange: (e) => { showAll = e.target.checked; secEls.forEach((x) => x.apply()); } }), "Show all sections (advanced and empty ones)");
    const stepProj = h("div", {}, h("p", { class: "hint" }, "Fields from this project's templates: " + (g.templates || []).map((t) => t.name + " v" + t.version_no).join(", ") + ". Only what applies is shown; tick below to see every section."),
      advToggle, projSecs.map(secBox));
    const stepPhotos = h("div", {}, cfgSec.photos !== false ? h("div", { class: "udpr-sec" }, h("h4", {}, "Photographs"), photoBox) : null,
      cfgSec.next !== false ? h("div", { class: "udpr-sec" }, h("h4", {}, "Next-day plan"), nextF) : null);
    const stepHist = () => {
      const box = h("div");
      box.append(h("h4", {}, "Workflow history"), table([{ label: "When", v: (r) => String(r.ts || "").slice(0, 16) }, { label: "By", v: (r) => nm.user(r.user_id) }, { k: "action", label: "Step" },
        { label: "From → to", v: (r) => (r.from_status || "") + (r.to_status ? " → " + r.to_status : "") }, { k: "note", label: "Note / reason" }], g.log || [], { search: false, export: false, empty: "No step yet." }));
      box.append(h("h4", {}, "Revisions"), table([{ k: "rev_no", label: "Rev." }, { label: "Kind", v: (r) => r.kind === "approved" ? "Approved version" : "Before amendment" }, { k: "reason", label: "Reason" }, { label: "When", v: (r) => String(r.ts || "").slice(0, 16) }],
        g.revisions || [], { search: false, export: false, empty: "No revision yet (made on approval and before any amendment).", onRow: async (r) => { const x = await run("udpr.revision", { id: r.id }); showRevision(x); } }));
      return box;
    };
    const defs = [["1 Basics & summary", () => stepBasics], ["2 Work done", () => stepWork], ["3 Manpower & equipment", () => stepRes], ["4 Problems", () => stepIssues]];
    if (projSecs.length) defs.push(["5 Project sections", () => stepProj]);
    if (cfgSec.quality || grpSecs("quality").length) defs.push(["Quality", quality]);
    if (cfgSec.hse || grpSecs("hse").length) defs.push(["Safety & environment", hse]);
    if (cfgSec.materials) defs.push(["Materials", materials]);
    defs.push(["Photos & next day", () => stepPhotos]);
    if (d.id) defs.push(["History", stepHist]);

    // ── actions
    const save = async (quiet) => {
      if (mt && editable && !(await mt.resolve())) throw new Error("machine lines not answered");
      const p = collect();
      const r = await run("udpr.save", p);
      lsSet(draftKey, null);
      (r.warnings || []).forEach((w) => toast(w, "err"));
      if (!quiet) toast((r.duplicate ? "Already saved as " : "Saved ") + (r.no || ""), "ok");
      if (PAGES._dprReload) PAGES._dprReload();
      if (PAGES._udprReload) PAGES._udprReload();
      return r;
    };
    const step = async (action, needReason, text) => {
      let reason = "";
      if (needReason) { reason = await ask(text || "Reason", "Write the reason. It is kept with the report.", { input: "Reason", required: true }); if (reason == null) return false; }
      await run("udpr.step", { id: d.id, action, reason }, "Done");
      mod.close();
      if (PAGES._dprReload) PAGES._dprReload();
      if (PAGES._udprReload) PAGES._udprReload();
      smartDpr(d.id);
      return false;
    };
    const st = d.status;
    const btns = [];
    if (editable) {
      btns.push({ label: "Save draft", cls: "primary", act: async () => { const r = await save(); mod.close(); smartDpr(r.id); return false; } });
      btns.push({ label: "Save & submit", act: async () => { const r = await save(true); d.id = r.id; await run("udpr.step", { id: r.id, action: "submit" }, "Submitted"); mod.close(); if (PAGES._dprReload) PAGES._dprReload(); if (PAGES._udprReload) PAGES._udprReload(); return false; } });
    }
    if (d.id && !locked) {
      if (st === "submitted" && rights.edit) btns.push({ label: "Check", act: () => step("check") });
      if (["submitted", "checked", "approved"].includes(st) && rights.accept) btns.push({ label: "Accept quantities", act: () => { mod.close(); acceptDpr(d.id); return false; } });
      if (["submitted", "checked"].includes(st) && rights.approve) btns.push({ label: "Approve", cls: "primary", act: () => step("approve") });
      if (["submitted", "checked"].includes(st) && rights.edit) btns.push({ label: "Return for correction", act: () => step("return", true, "Return for correction") });
      if (["submitted", "checked"].includes(st) && rights.lock) btns.push({ label: "Reject", cls: "warn", act: () => step("reject", true, "Reject the report") });
      if (st === "rejected" && rights.edit) btns.push({ label: "Revise (back to draft)", act: () => step("revise") });
      if (st === "approved" && rights.lock) btns.push({ label: "Lock", act: () => step("lock") });
      if (st === "approved" && rights.reopen) btns.push({ label: "Reopen for amendment", cls: "warn", act: () => step("reopen", true, "Reopen an approved report") });
    }
    if (locked && rights.unlock) btns.push({ label: "Unlock", cls: "warn", act: () => step("unlock", true, "Unlock the report") });
    if (d.id) btns.push({ label: "Print", act: async () => { await printUdpr([d.id]); return false; } });
    if (window.bcoClassicDpr) btns.push({ label: "Full form (classic)", act: async () => { if (editable && timer) await save(true).catch(() => null); mod.close(); window.bcoClassicDpr(d.id ? await api("dpr.get", { id: d.id }) : null, Object.assign({}, ctx, { classic: true })); return false; } });

    const title = isNew ? "New daily progress report" : "DPR " + (d.no || "") + " · " + d.date + (d.shift ? " · " + d.shift : "") + (hd.revision ? " · rev " + hd.revision : "");
    const mod = modal(title, tabs(defs, 0), btns, { head: h("span", {}, shown(g.status_shown, g.status_label), " ", saveState) });
    mod.el.querySelector(".modal").style.maxWidth = "min(1400px, 98vw)";
    mod.el.querySelector(".modal").style.width = "min(1400px, 98vw)";
    ready = true;
    if (src) dirty();
    return mod;
  }
  window.bcoSmartDpr = smartDpr;

  function showRevision(x) {
    const s = x.snapshot || {};
    const dd = s.dpr || {};
    const body = h("div", {}, h("p", { class: "hint" }, "Revision " + x.rev_no + " · " + (x.kind === "approved" ? "approved version" : "kept before amendment") + (x.reason ? " · " + x.reason : "") + " · " + String(x.ts || "").slice(0, 16)),
      kv([["Date", dd.date], ["Shift", dd.shift], ["Weather", dd.weather], ["Remarks", dd.remarks]]),
      h("h4", {}, "Work"), table([{ label: "Activity", v: (r) => actName(r.activity_id) || nm.boq(r.boq_item_id) }, { k: "location", label: "Location" }, { k: "planned_qty", label: "Planned", fmt: "qty" }, { k: "actual_qty", label: "Reported", fmt: "qty" }],
        dd.work || s.work || [], { search: false, export: false }),
      h("h4", {}, "Labour"), table([{ label: "Trade", v: (r) => ((S.P.trades || []).find((t) => String(t.id) === String(r.trade_id)) || {}).name || "" }, { k: "count", label: "No.", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" }], dd.labour || s.labour || [], { search: false, export: false }),
      h("h4", {}, "Equipment"), table([{ label: "Machine", v: (r) => nm.eq(r.equipment_id) }, { k: "hours", label: "Work h", fmt: "qty" }, { k: "idle_hours", label: "Idle h", fmt: "qty" }], dd.equipment || s.equipment || [], { search: false, export: false }));
    modal("Revision " + x.rev_no, body, []);
  }

  /* ───────────── quantity acceptance (QS / engineer) ───────────── */
  async function acceptDpr(id) {
    const g = await run("udpr.get", { id });
    const m = await meta();
    const d = g.dpr;
    await loadProjectLists();
    const rows = (d.work || []).map((w) => { const f = (g.figures || {})[w.id] || {}; return Object.assign({ work_id: w.id, label: actName(w.activity_id) || nm.boq(w.boq_item_id), location: w.location || "", reported: w.actual_qty, unit: f.unit || unitOf(w), acc: f.accepted ?? "", note: f.accept_note || "" }, f); });
    const ro = !!(g.head || {}).locked_at || !m.rights.accept;
    const ed = lineEditor([{ k: "label", label: "Activity / item", readonly: true, w: 220 }, { k: "location", label: "Location", readonly: true }, { k: "unit", label: "Unit", readonly: true },
      { label: "Scope", num: true, show: (r) => r.scope == null ? "—" : fmtQty(r.scope) }, { label: "Prev. accepted", num: true, show: (r) => fmtQty(r.prev_accepted || 0) },
      { k: "reported", label: "Reported today", type: "number", readonly: true }, { k: "acc", label: "Accepted today", type: "number", w: 90 },
      { label: "Cum. accepted", num: true, show: (r) => fmtQty((r.prev_accepted || 0) + (Number(r.acc) || 0)) },
      { label: "Balance", num: true, show: (r) => r.scope == null ? "" : h("span", {}, fmtQty(r.scope - (r.prev_accepted || 0) - (Number(r.acc) || 0))).textContent + ((r.prev_accepted || 0) + (Number(r.acc) || 0) > r.scope ? " ▲ over scope" : "") },
      { k: "note", label: "Note (why it differs)", w: 200 }], rows, { readonly: ro, fixed: true });
    const ov = form([{ k: "override_reason", label: "Override reason (only if the accepted cumulative goes beyond the approved scope; needs an approver)", wide: true }], {});
    const body = h("div", {}, h("p", { class: "hint" }, "DPR " + (d.no || "") + " · " + d.date + ". Accept what was actually done as checked on site. A blank box means not yet accepted; a difference from the site figure needs a note. Accepting does not post anything to the accounts."),
      g.head && g.head.locked_at ? h("div", { class: "udpr-note" }, "This DPR is locked; accepted quantities are shown read-only.") : null,
      ro ? null : h("div", { class: "bar" }, h("button", { class: "btn small", type: "button", onclick: () => { ed.setLines(ed.lines().map((r) => Object.assign(r, { acc: r.reported ?? "" }))); } }, "Accept all as reported")),
      ed, ro ? null : ov);
    modal("Accept quantities", body, ro ? [] : [{ label: "Save accepted quantities", cls: "primary", act: async () => {
      const r = await run("udpr.accept", { dpr_id: d.id, lines: ed.lines().map((x) => ({ work_id: x.work_id, accepted_qty: x.acc, note: x.note })), override_reason: ov.values().override_reason });
      toast(r.changed + " line(s) updated", "ok");
      if (PAGES._udprReload) PAGES._udprReload();
    } }]).el.querySelector(".modal").style.maxWidth = "min(1300px, 98vw)";
  }
  window.bcoAcceptDpr = acceptDpr;

  /* ───────────── print (one or many DPRs, project fields included) ───────────── */
  async function udprDoc(id, m) {
    const g = await api("udpr.get", { id });
    const d = g.dpr, hd = g.head || {};
    const n = (v) => v == null || v === "" ? "" : fmtQty(v);
    const tbl = (cols, rows) => h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.n ? "n" : "" }, c.l)))),
      h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, cols.map((c) => h("td", { class: c.n ? "n" : "" }, c.v(r) ?? "")))) : h("tr", {}, h("td", { colspan: cols.length }, "—"))));
    const doc = h("div", { class: "udpr-print" });
    doc.append(h("h2", {}, (m.report_header ? m.report_header + " — " : "") + "Daily Progress Report " + (d.no || "")),
      h("div", { class: "meta" }, ...[["Project", m.project.code + " " + m.project.name], ["Date", d.date], ["Shift", d.shift], ["Status", g.status_label + (hd.revision ? " · rev " + hd.revision : "")],
        ["Package", frontName(m, hd.package_id)], ["Work front", frontName(m, hd.front_id)], ["Weather", [d.weather, hd.temp_min != null || hd.temp_max != null ? (hd.temp_min ?? "") + "–" + (hd.temp_max ?? "") + " °C" : "", hd.humidity != null ? hd.humidity + "% RH" : "", d.rain_mm ? d.rain_mm + " mm" : ""].filter(Boolean).join(" · ")],
        ["Site condition", d.site_condition], ["Templates", (g.templates || []).map((t) => t.code + " v" + t.version_no).join(", ")]].filter(([, v]) => v).map(([k, v]) => h("div", {}, h("b", {}, k + ": "), v))));
    const summ = SUMMARY.filter(([k]) => hd[k]);
    if (summ.length) { doc.append(h("h3", {}, "Executive summary")); summ.forEach(([k, l]) => doc.append(h("p", {}, h("b", {}, l + ": "), hd[k]))); }
    const F = g.figures || {};
    doc.append(h("h3", {}, "Activities and quantities"), tbl([{ l: "Activity / item", v: (r) => actName(r.activity_id) || nm.boq(r.boq_item_id) }, { l: "Front", v: (r) => frontName(m, (r._ux || {}).front_id) }, { l: "Location", v: (r) => [r.location, r.chainage_from != null && r.chainage_from !== "" ? "Ch " + r.chainage_from + "–" + (r.chainage_to ?? "") : ""].filter(Boolean).join(" ") },
      { l: "Unit", v: (r) => (F[r.id] || {}).unit || "" }, { l: "Scope", n: 1, v: (r) => n((F[r.id] || {}).scope) }, { l: "Planned", n: 1, v: (r) => n(r.planned_qty) }, { l: "Reported", n: 1, v: (r) => n(r.actual_qty) },
      { l: "Accepted", n: 1, v: (r) => n((F[r.id] || {}).accepted) }, { l: "Cum. accepted", n: 1, v: (r) => n((F[r.id] || {}).current_accepted) }, { l: "Balance", n: 1, v: (r) => n((F[r.id] || {}).balance) },
      { l: "%", n: 1, v: (r) => (F[r.id] || {}).progress_pct == null ? "" : fmtN(F[r.id].progress_pct, 1) }, { l: "Remarks", v: (r) => [(r._ux || {}).delay_reason, r.remarks].filter(Boolean).join("; ") }], d.work || []));
    const lab = d.labour || [];
    doc.append(h("h3", {}, "Manpower (" + fmtQty(lab.reduce((a, x) => a + (Number(x.count) || 0), 0)) + ")"), tbl([{ l: "Trade", v: (r) => ((S.P.trades || []).find((t) => String(t.id) === String(r.trade_id)) || {}).name || "" }, { l: "Subcontractor", v: (r) => r.party_id ? nm.party(r.party_id) : "Own" },
      { l: "Activity", v: (r) => actName(r.activity_id) }, { l: "No.", n: 1, v: (r) => n(r.count) }, { l: "Hours", n: 1, v: (r) => n(r.hours) }, { l: "OT h", n: 1, v: (r) => n(r.ot_hours) }], lab));
    doc.append(h("h3", {}, "Equipment"), tbl([{ l: "Machine", v: (r) => nm.eq(r.equipment_id) }, { l: "Operator", v: (r) => r.operator || "" }, { l: "Activity", v: (r) => actName(r.activity_id) },
      { l: "Work h", n: 1, v: (r) => n(r.hours) }, { l: "Idle h", n: 1, v: (r) => n(r.idle_hours) }, { l: "Down h", n: 1, v: (r) => n(r.breakdown_hours) }, { l: "Output", n: 1, v: (r) => n(r.output_qty) }], d.equipment || []));
    if ((g.problems || []).length) doc.append(h("h3", {}, "Major problems and issues"), tbl([{ l: "Issue", v: (r) => (r.no || "") + " " + r.title }, { l: "Category", v: (r) => r.category }, { l: "Since", v: (r) => (r.first_date || "") + (r.days_reported ? " (" + r.days_reported + " d)" : "") },
      { l: "Hours lost", n: 1, v: (r) => n(r.hours) }, { l: "Impact", v: (r) => r.impact }, { l: "Action", v: (r) => r.mitigation }, { l: "Decision from", v: (r) => r.decision_required }], g.problems));
    if ((d.delays || []).length) doc.append(h("h3", {}, "Delays"), tbl([{ l: "Reason", v: (r) => (DELAY_CATS.find((x) => x[0] === r.category) || [0, r.category])[1] }, { l: "Activity", v: (r) => actName(r.activity_id) }, { l: "Hours", n: 1, v: (r) => n(r.hours) }, { l: "What happened", v: (r) => r.description }], d.delays));
    (g.sections || []).forEach((s) => {
      if (s.kind === "fields") {
        const vs = s.fields.filter((f) => !blank((g.values || {})[s.key + "." + f.key]));
        if (vs.length) doc.append(h("h3", {}, s.label), h("div", { class: "meta" }, vs.map((f) => h("div", {}, h("b", {}, fLabel(f) + ": "), fmtVal(f, g.values[s.key + "." + f.key])))));
      } else if (s.kind === "table" && ((g.rows || {})[s.key] || []).length) {
        doc.append(h("h3", {}, s.label), tbl(s.fields.map((f) => ({ l: fLabel(f), n: NUM.has(f.type) ? 1 : 0, v: (r) => fmtVal(f, r[f.key]) })), g.rows[s.key]));
      }
    });
    if (hd.s_next) doc.append(h("h3", {}, "Next-day plan"), h("p", {}, hd.s_next));
    if (d.remarks) doc.append(h("h3", {}, "Remarks"), h("p", {}, d.remarks));
    if ((d.photos || []).length) doc.append(h("p", {}, d.photos.length + " photo(s) attached in BuildCore."));
    const names = [hd.prepared_name, hd.checked_name, hd.approved_name];
    doc.append(signRow((m.signatures || []).map((s, i) => s + (names[i] ? ": " + names[i] : ""))));
    return doc;
  }
  const signRow = (labels) => h("div", { style: "display:grid;grid-template-columns:repeat(" + Math.max(1, labels.length) + ",1fr);gap:28px;margin-top:40px;font-size:11px" },
    labels.map((l) => h("div", { style: "border-top:1px solid #333;text-align:center;padding-top:3px" }, l)));
  function fmtVal(f, v) {
    if (blank(v)) return "";
    if (f.type === "multiselect") { try { return JSON.parse(v).join(", "); } catch (e) { return String(v); } }
    if (REFS.has(f.type)) return (refOpts(f.type).find((o) => String(o[0]) === String(v)) || [0, v])[1];
    if (NUM.has(f.type)) return fmtQty(v) + (f.unit ? " " + f.unit : "");
    if (f.type === "file" || f.type === "photo") return "file #" + v;
    return String(v);
  }
  async function printUdpr(ids) {
    if (!ids.length) return toast("No DPR to print.", "err");
    await loadProjectLists();
    const m = await meta();
    const wrap = h("div");
    for (const id of ids) { const doc = await udprDoc(id, m); doc.style.pageBreakAfter = "always"; wrap.append(doc); }
    wrap.prepend(css.cloneNode(true));
    printFrame("Daily Progress Report", wrap);
  }
  window.bcoPrintUdpr = printUdpr;

  /* ───────────── tab: smart DPR register ───────────── */
  async function registerTab() {
    if (!S.project) return projectNotice();
    const m = await meta(true);
    let v = { from: monthAgo(), to: today(), status: "", front_id: "" }, page = 0;
    const holder = h("div");
    const load = async () => {
      const r = await run("udpr.list", Object.assign({ project_id: S.project, page, size: 50 }, v));
      holder.innerHTML = "";
      const t = table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { label: "Status", v: (x) => shown(x.shown, x.shown_label) },
        { label: "Main front", v: (x) => frontName(m, x.front_id) }, { k: "work_lines", label: "Work rows", fmt: "num" },
        { label: "Accepted", v: (x) => x.work_lines ? x.accepted_lines + " / " + x.work_lines : "—" }, { k: "manhours", label: "Man-hours", fmt: "qty" }, { k: "machine_hours", label: "Machine h", fmt: "qty" },
        { k: "issues", label: "Issues", fmt: "num" }, { k: "photos", label: "Photos", fmt: "num" }, { label: "Summary", v: (x) => (x.s_work || x.return_comment || x.reject_reason || "").slice(0, 80) },
        { label: "", v: (x) => h("span", { style: "display:flex;gap:6px" }, m.rights.accept && ["submitted", "checked", "approved"].includes(x.status) && !x.locked_at ? h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); acceptDpr(x.id); } }, "Accept qty") : null,
          h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); printUdpr([x.id]); } }, "Print")) }],
      r.rows, { name: "udpr_register", onRow: (x) => smartDpr(x.id), empty: "No DPR in this period." });
      const pages = Math.max(1, Math.ceil(r.total / r.size));
      holder.append(h("div", { class: "bar" }, h("span", { class: "hint grow" }, r.total + " DPR(s)" + (pages > 1 ? " · page " + (page + 1) + " of " + pages : "")),
        page > 0 ? h("button", { class: "btn small", onclick: () => { page--; load(); } }, "‹ Newer") : null, page + 1 < pages ? h("button", { class: "btn small", onclick: () => { page++; load(); } }, "Older ›") : null,
        h("button", { class: "btn", onclick: () => { const sel = t._k ? t._k.selected() : []; printUdpr((sel.length ? sel : r.rows).map((x) => x.id)); } }, "Print ticked (or all on the page)")), t);
    };
    PAGES._udprReload = load;
    const box = h("div", {},
      h("div", { class: "bar" }, h("span", { class: "hint grow" }, "The same DPRs as the first tab, with the 2.25 status (returned, rejected, locked), work fronts and accepted rows. " + (m.form === "smart" ? "New and opened DPRs use the smart form." : "The classic form is the default (settings).")),
        m.rights.create ? h("button", { class: "btn primary", onclick: () => smartDpr(null) }, "New DPR (smart form)") : null),
      filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" },
        { k: "status", label: "Status", type: "select", options: [["draft", "Draft"], ["returned", "Returned"], ["submitted", "Submitted"], ["checked", "Checked"], ["approved", "Approved"], ["locked", "Locked"], ["rejected", "Rejected"]], blank: "All" },
        (m.fronts || []).length ? { k: "front_id", label: "Work front", type: "select", options: frontOpts(m), blank: "All" } : null].filter(Boolean), v, (x) => { v = x; page = 0; load(); }), holder);
    await load();
    return box;
  }

  /* ───────────── tab: progress & acceptance ───────────── */
  async function progressTab() {
    if (!S.project) return projectNotice();
    const m = await meta();
    let v = { as_of: today(), from: "", front_id: "" };
    const holder = h("div"), waiting = h("div");
    const load = async () => {
      const [p, w1, w2] = await Promise.all([run("udpr.progress", Object.assign({ project_id: S.project }, v)),
        api("udpr.list", { project_id: S.project, status: "submitted", size: 200 }), api("udpr.list", { project_id: S.project, status: "checked", size: 200 })]);
      holder.innerHTML = "";
      holder.append(h("p", { class: "hint" }, "Progress is measured on " + (m.cfg.progress_basis === "accepted" ? "accepted quantities from " + m.cfg.basis_from + " (earlier DPRs keep their reported quantities)" : "reported quantities (the site's figures)") +
        ". Scope is the approved quantity including approved variations. Awaiting = reported but not yet accepted."),
      table(p.columns.map((c) => Object.assign({}, c, c.k === "flags" ? { v: (r) => r.flags ? h("span", { class: "udpr-over" }, r.flags) : "" } : {})), p.rows, { name: "udpr_progress", empty: "No quantity reported yet." }));
      const list = (w1.rows || []).concat(w2.rows || []).filter((x) => x.work_lines > x.accepted_lines);
      waiting.innerHTML = "";
      waiting.append(h("h3", {}, "DPRs with quantities awaiting acceptance (" + list.length + ")"), table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { label: "Status", v: (x) => shown(x.shown, x.shown_label) },
        { label: "Rows accepted", v: (x) => x.accepted_lines + " / " + x.work_lines }, { label: "", v: (x) => m.rights.accept ? h("button", { class: "btn small primary", onclick: (e) => { e.stopPropagation(); acceptDpr(x.id); } }, "Accept quantities") : "" }],
      list, { search: false, export: false, onRow: (x) => smartDpr(x.id), empty: "Nothing waiting." }));
    };
    PAGES._udprReload = load;
    const box = h("div", {}, filterBar([{ k: "as_of", label: "As of", type: "date" }, { k: "from", label: "Period from (optional)", type: "date" },
      (m.fronts || []).length ? { k: "front_id", label: "Work front", type: "select", options: frontOpts(m), blank: "All" } : null].filter(Boolean), v, (x) => { v = x; load(); }),
    m.rights.export ? h("div", { class: "bar" }, h("span", { class: "grow" }), h("button", { class: "btn", onclick: async () => xdl(await run("udpr.report_xlsx", { project_id: S.project, kind: "activity", to: v.as_of, from: v.from || "2000-01-01", front_id: v.front_id })) }, "Excel")) : null,
    holder, waiting);
    await load();
    return box;
  }

  /* ───────────── tab: issue register ───────────── */
  async function issuesTab() {
    if (!S.project) return projectNotice();
    const m = await meta();
    let v = { status: "open", category: "", front_id: "", claim: "" };
    const holder = h("div");
    const load = async () => {
      const rows = await run("udpr.issues", Object.assign({ project_id: S.project }, v));
      holder.innerHTML = "";
      holder.append(table([{ k: "no", label: "No." }, { k: "title", label: "Issue" }, { k: "category", label: "Category" }, { k: "front", label: "Work front" },
        { label: "First reported", v: (r) => r.first_date || "" }, { k: "days_reported", label: "Days on DPRs", fmt: "num" }, { k: "hours_total", label: "Hours lost", fmt: "qty" },
        { k: "decision_required", label: "Decision from" }, { k: "responsible_party", label: "Responsible" }, { label: "Due", v: (r) => r.due_date ? h("span", { class: r.overdue ? "udpr-over" : "" }, r.due_date + (r.overdue ? " · overdue" : "")) : "" },
        { label: "Claim", v: (r) => r.claim_relevant ? "Yes" + (r.event_no ? " · " + r.event_no : "") : "" }, { k: "status", label: "Status", fmt: "status" }],
      rows, { name: "udpr_issues", onRow: (r) => issueDrawer(r, m, load), empty: "No issue." }));
    };
    const box = h("div", {}, h("div", { class: "bar" }, h("span", { class: "hint grow" }, "Problems reported on DPRs. A continuing problem is one issue with one line per day it was reported. The same issues show in Work › Issues & punch list."),
      h("button", { class: "btn primary", onclick: () => issueDrawer(null, m, load) }, "New issue")),
    filterBar([{ k: "status", label: "Status", type: "select", noBlank: true, options: [["open", "Open"], ["all", "All"], ["closed", "Closed"]] },
      { k: "category", label: "Category", type: "select", options: (m.issue_categories || []).map((x) => [x, x]), blank: "All" },
      (m.fronts || []).length ? { k: "front_id", label: "Work front", type: "select", options: frontOpts(m), blank: "All" } : null,
      { k: "claim", label: "Claim relevant only", type: "check" }].filter(Boolean), v, (x) => { v = x; load(); }), holder);
    await load();
    return box;
  }
  async function issueDrawer(r, m, done) {
    r = r || { status: "open", priority: "normal" };
    const f = form([{ k: "title", label: "Issue", req: true, wide: true }, { k: "category", label: "Category", type: "select", options: (m.issue_categories || []).map((x) => [x, x]) },
      (m.fronts || []).length ? { k: "front_id", label: "Work front", type: "select", options: frontOpts(m) } : null,
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts() }, { k: "priority", label: "Priority", type: "select", noBlank: true, options: [["low", "Low"], ["normal", "Normal"], ["high", "High"], ["critical", "Critical"]] },
      { k: "status", label: "Status", type: "select", noBlank: true, options: [["open", "Open"], ["in_progress", "In progress"], ["closed", "Closed"]] },
      { k: "due_date", label: "Due", type: "date" }, { k: "assignee", label: "Action by" }, { k: "responsible_party", label: "Responsible party" },
      { k: "decision_required", label: "Decision required from" }, { k: "claim_relevant", label: "Relevant to a claim / extension of time", type: "check" },
      { k: "description", label: "Description", type: "textarea", wide: true }, { k: "impact", label: "Impact", type: "textarea", wide: true }, { k: "mitigation", label: "Mitigation / action", type: "textarea", wide: true }].filter(Boolean), r);
    const days = h("div");
    if (r.id) {
      const rows = await api("udpr.issue_days", { id: r.id });
      days.append(h("h4", {}, "Days reported"), table([{ k: "date", label: "Date" }, { k: "no", label: "DPR" }, { k: "hours", label: "Hours lost", fmt: "qty" }, { k: "note", label: "Note" }, { k: "status", label: "DPR status", fmt: "status" }],
        rows, { search: false, export: false, onRow: (x) => smartDpr(x.dpr_id), empty: "Not on any DPR yet." }));
    }
    await loadProjectLists();
    drawer(r.id ? "Issue " + (r.no || "") : "New issue", h("div", {}, f, days), [{ label: "Save", cls: "primary", act: async () => {
      const x = f.values();
      await run("udpr.issue_save", { row: Object.assign({ id: r.id, project_id: S.project }, x) }, "Saved");
      META = null;
      done();
    } }]);
  }

  /* ───────────── tab: DPR reports ───────────── */
  async function reportsTab() {
    if (!S.project) return projectNotice();
    const rm = await run("udpr.reports_meta", { project_id: S.project });
    let lays = await api("udpr.layouts", {});
    let last = null;
    const STS = [["draft", "Draft"], ["submitted", "Submitted"], ["checked", "Checked"], ["approved", "Approved"]];
    let sts = ["submitted", "checked", "approved"];
    const v = { kind: "daily", from: new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10), to: today(), front_id: "", section: "", group_by: "", sort_by: "", desc: 0 };
    const holder = h("div");
    const f = form([{ k: "kind", label: "Report", type: "select", noBlank: true, options: rm.reports.map((x) => [x.key, x.label]) }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" },
      rm.fronts.length ? { k: "front_id", label: "Work front / package", type: "select", options: rm.fronts.map((x) => [x.id, (x.code ? x.code + " " : "") + x.name]), blank: "All" } : null,
      { k: "section", label: "Section (custom field report)", type: "select", options: rm.custom.map((x) => [x.key, x.label]), blank: "—" },
      { k: "group_by", label: "Group by column (key)" }, { k: "sort_by", label: "Sort by column (key)" }, { k: "desc", label: "Largest first", type: "check" }].filter(Boolean), v);
    const stBox = h("div", { class: "udpr-sel" }, h("span", { class: "hint" }, "DPR status included:"), STS.map(([k, l]) => h("label", {}, h("input", { type: "checkbox", checked: sts.includes(k), onchange: (e) => { sts = sts.filter((x) => x !== k); if (e.target.checked) sts.push(k); } }), " ", l)));
    const args = () => Object.assign({ project_id: S.project, statuses: sts }, f.values(), { desc: f.values().desc ? 1 : 0 });
    const show = async () => {
      const r = await run("udpr.report", args());
      last = r;
      holder.innerHTML = "";
      const cols = r.columns.map((c) => Object.assign({}, c));
      holder.append(h("h3", {}, r.title + " · " + r.from + " to " + r.to), h("p", { class: "hint" }, (r.notes || []).join(" ")),
        h("p", { class: "hint" }, "Column keys: " + cols.map((c) => c.k).join(", ")),
        table(cols, r.rows, { name: "udpr_rep_" + r.kind, totals: r.totals ? Object.keys(r.totals) : null, empty: "Nothing in this period." }));
    };
    const layBox = h("span");
    const drawLays = () => {
      layBox.innerHTML = "";
      if (!lays.length) return;
      const sel = h("select", {}, h("option", { value: "" }, "Saved layouts…"), lays.map((l) => h("option", { value: l.id }, l.name + (l.shared ? "" : " (mine)"))));
      sel.onchange = () => { const l = lays.find((x) => String(x.id) === sel.value); if (!l) return; const p = JSON.parse(l.params || "{}"); Object.keys(p).forEach((k) => { if (k !== "statuses") f.set(k, p[k]); }); f.set("kind", l.kind); if (p.statuses) { sts = p.statuses; stBox.querySelectorAll("input").forEach((i, j) => { i.checked = sts.includes(STS[j][0]); }); } show(); };
      layBox.append(sel);
    };
    drawLays();
    const box = h("div", {}, f, stBox, h("div", { class: "bar" }, layBox, h("span", { class: "grow" }), h("button", { class: "btn primary", onclick: show }, "Show"),
      h("button", { class: "btn", onclick: async () => { if (!last) await show(); printReport(last); } }, "Print"),
      rm.can_export ? h("button", { class: "btn", onclick: async () => xdl(await run("udpr.report_xlsx", args())) }, "Excel") : null,
      h("button", { class: "btn", onclick: async () => { const name = await ask("Save layout", "Name for this report layout (shared with the team):", { input: "Name", required: true }); if (!name) return; const a = args(); delete a.project_id; await run("udpr.layout_save", { row: { name: name.trim(), kind: a.kind, params: a, shared: 1 } }, "Saved"); lays = await api("udpr.layouts", {}); drawLays(); } }, "Save layout")),
    holder);
    await show();
    return box;
  }
  function printReport(r) {
    if (!r) return;
    const t = h("table", {}, h("thead", {}, h("tr", {}, r.columns.map((c) => h("th", { class: c.fmt ? "n" : "" }, c.label)))),
      h("tbody", {}, r.rows.map((x) => h("tr", {}, r.columns.map((c) => h("td", { class: c.fmt ? "n" : "" }, c.fmt === "money" ? fmtMoney(x[c.k]) : c.fmt === "qty" ? fmtQty(x[c.k]) : String(x[c.k] ?? "")))))),
      r.totals ? h("tfoot", {}, h("tr", {}, r.columns.map((c, i) => h("td", { class: "n" }, i === 0 ? "Total" : (r.totals[c.k] != null ? fmtQty(r.totals[c.k]) : ""))))) : null);
    const doc = h("div", { class: "udpr-print" }, css.cloneNode(true), h("h2", {}, (r.header ? r.header + " — " : "") + r.title),
      h("div", { class: "meta" }, h("div", {}, h("b", {}, "Project: "), r.project.code + " " + r.project.name), h("div", {}, h("b", {}, "Period: "), r.from + " to " + r.to), h("div", {}, h("b", {}, "Printed: "), String(r.generated || "").slice(0, 16))),
      (r.notes || []).length ? h("p", {}, r.notes.join(" ")) : null, t, signRow(r.signatures || []));
    printFrame(r.title, doc);
  }

  /* ───────────── tab: work fronts & set-up ───────────── */
  async function setupTab() {
    if (!S.project) return projectNotice();
    const m = await meta(true);
    const pc = await run("udpr.project_cfg", { project_id: S.project });
    const can2 = m.rights.setup;
    const box = h("div");
    // fronts
    const fr = await run("udpr.fronts", { project_id: S.project });
    const editFront = (r) => {
      r = r || { kind: "front", active: 1 };
      const f = form([{ k: "kind", label: "Kind", type: "select", noBlank: true, options: [["package", "Package (contract / section)"], ["front", "Work front"]] }, { k: "code", label: "Code" }, { k: "name", label: "Name", req: true },
        { k: "parent_id", label: "Belongs to package", type: "select", options: fr.filter((x) => x.kind === "package" && x.id !== r.id).map((x) => [x.id, (x.code ? x.code + " " : "") + x.name]) },
        { k: "party_id", label: "Subcontractor", type: "select", options: () => opt.parties(["subcontractor"]) }, { k: "contract_id", label: "Contract", type: "select", options: (m.contracts || []).map((x) => [x.id, (x.ref_no || "") + " " + (x.title || "")]) },
        { k: "discipline", label: "Discipline" }, { k: "location", label: "Location" }, { k: "ch_from", label: "Chainage from (m)", type: "number" }, { k: "ch_to", label: "Chainage to (m)", type: "number" },
        { k: "sort", label: "Order", type: "number" }, { k: "active", label: "Active", type: "check" }].map((x) => Object.assign(x, { readonly: !can2 })), r);
      drawer(r.id ? "Work front " + r.name : "New package / work front", f, can2 ? [{ label: "Save", cls: "primary", act: async () => { await run("udpr.front_save", { row: Object.assign({ id: r.id, project_id: S.project }, f.values()) }, "Saved"); META = null; redraw(); } }] : []);
    };
    // project configuration
    const cf = pc.cfg;
    let tsel = (cf.templates || []).map(Number);
    const hidden = new Set(cf.hidden || []);
    const coreOn = Object.assign({}, cf.sections || {});
    const tplBox = h("div", { class: "udpr-sel" }, pc.library.map((t) => h("label", { title: t.description || "" }, h("input", { type: "checkbox", disabled: !can2, checked: tsel.includes(t.id), onchange: (e) => { tsel = tsel.filter((x) => x !== t.id); if (e.target.checked) tsel.push(t.id); } }), " ", t.name + " (" + t.code + (t.version_no ? " v" + t.version_no : "") + ")")));
    const coreBox = h("div", { class: "udpr-sel" }, pc.core_sections.filter((s) => s.key !== "custom").map((s) => h("label", {}, h("input", { type: "checkbox", disabled: !can2 || s.key === "work", checked: !!coreOn[s.key], onchange: (e) => { coreOn[s.key] = e.target.checked; } }), " ", s.label)));
    const hideBox = h("div", {}, pc.all_sections.map((s) => h("div", { class: "udpr-sec" },
      h("label", { class: "f check" }, h("input", { type: "checkbox", disabled: !can2, checked: !hidden.has(s.key), onchange: (e) => { if (e.target.checked) hidden.delete(s.key); else hidden.add(s.key); } }), h("b", {}, s.label), h("small", { class: "muted" }, "  " + s.template_name + " · " + ({ fields: "fields", table: "table", line: "columns on work rows" })[s.kind])),
      h("div", { class: "udpr-sel" }, s.fields.map((fl) => { const k = s.key + "." + fl.key; return h("label", {}, h("input", { type: "checkbox", disabled: !can2, checked: !hidden.has(k), onchange: (e) => { if (e.target.checked) hidden.delete(k); else hidden.add(k); } }), " ", fl.label); })))));
    const bf = form([{ k: "progress_basis", label: "Progress is measured on", type: "select", noBlank: true, options: [["reported", "Reported quantities (site)"], ["accepted", "Accepted quantities (QS / engineer)"]] },
      { k: "basis_from", label: "Accepted quantities from (date)", type: "date", hint: "DPRs before this date keep their reported quantities." },
      { k: "scope_tol", label: "Tolerance above approved scope (%)", type: "number", hint: "Accepted cumulative may exceed scope by this much without an approver's override." }].map((x) => Object.assign(x, { readonly: !can2 })), cf);
    const saveCfg = async () => {
      const x = bf.values();
      await run("udpr.project_cfg_save", { project_id: S.project, templates: tsel, hidden: [...hidden], sections: coreOn, progress_basis: x.progress_basis, basis_from: x.basis_from || null, scope_tol: x.scope_tol }, "Saved");
      META = null;
    };
    // company settings
    let comp = null;
    if (can2) {
      const st = Object.assign({ udpr_form: m.form, udpr_report_header: m.report_header, udpr_signatures: (m.signatures || []).join("|") }, m.settings || {});
      const sf = form([{ k: "udpr_form", label: "DPR form for New / Open", type: "select", noBlank: true, options: [["smart", "Smart form (2.25)"], ["classic", "Classic form"]] },
        { k: "udpr_autolock_days", label: "Lock approved DPRs after (days, 0 = never)", type: "number" }, { k: "udpr_report_header", label: "Report heading (company / project office)" },
        { k: "udpr_signatures", label: "Signature boxes (separate with |)" }, { k: "udpr_scope_tol", label: "Default scope tolerance (%)", type: "number" }], st);
      comp = h("div", { class: "panel" }, h("h3", {}, "DPR settings (all projects)"), sf, h("div", { class: "bar" }, h("span", { class: "grow" }),
        h("button", { class: "btn primary", onclick: async () => { const x = sf.values(); Object.keys(x).forEach((k) => { if (x[k] === "") delete x[k]; }); await run("udpr.settings_save", Object.assign({ project_id: S.project }, x), "Saved"); META = null; } }, "Save settings")));
    }
    const redraw = async () => { const n = await setupTab(); box.replaceWith(n); };
    box.append(h("div", { class: "panel" }, h("h3", {}, "Packages and work fronts"), h("p", { class: "hint" }, "A DPR stays one report per project, date and shift; each work, labour and equipment row is tagged with its front, so reports can be filtered by package or front without double-counting machine hours."),
      can2 ? h("div", { class: "bar" }, h("span", { class: "grow" }), h("button", { class: "btn primary", onclick: () => editFront(null) }, "Add package / work front")) : null,
      table([{ label: "Kind", v: (r) => r.kind === "package" ? "Package" : "Work front" }, { k: "code", label: "Code" }, { k: "name", label: "Name" }, { label: "Package", v: (r) => frontName({ fronts: fr }, r.parent_id) },
        { k: "party", label: "Subcontractor" }, { k: "discipline", label: "Discipline" }, { k: "location", label: "Location" }, { label: "Chainage", v: (r) => r.ch_from != null ? r.ch_from + "–" + (r.ch_to ?? "") : "" }, { label: "Active", v: (r) => r.active ? "Yes" : "No" }],
      fr, { search: false, onRow: (r) => editFront(r), empty: "No package or work front yet. DPRs work without them." })),
    h("div", { class: "panel" }, h("h3", {}, "This project's DPR"), can2 ? null : h("p", { class: "hint" }, "Read only: changing the set-up needs the DPR set-up right."),
      h("h4", {}, "Templates in force"), h("p", { class: "hint" }, "Combine a base template with the project type. New DPRs use the current published versions; existing DPRs keep theirs."), tplBox,
      h("h4", {}, "Standard sections"), coreBox, bf,
      h("h4", {}, "Sections and fields shown (untick to hide on this project)"), hideBox,
      can2 ? h("div", { class: "bar" }, h("span", { class: "grow" }), h("button", { class: "btn primary", onclick: async () => { await saveCfg(); redraw(); } }, "Save project set-up")) : null),
    comp || "");
    return box;
  }

  /* ───────────── tab: templates & fields ───────────── */
  const SI_RE = /^\s*([a-z][a-z0-9_]*)\s*(=|!=|>|<| in | filled| empty)\s*(.*)$/;
  const siText = (si) => !si ? "" : si.op === "filled" ? si.field + " filled" : si.op === "empty" ? si.field + " empty" : si.field + " " + ({ eq: "=", ne: "!=", gt: ">", lt: "<", in: "in" })[si.op] + " " + (Array.isArray(si.value) ? si.value.join(", ") : si.value ?? "");
  const siParse = (t) => {
    t = String(t || "").trim();
    if (!t) return null;
    const m = SI_RE.exec(t.replace(/\s+in\s+/, " in "));
    if (!m) throw new Error("Condition not understood: " + t + ". Write e.g. kind = Near miss, qty > 0, ncr filled.");
    const op = { "=": "eq", "!=": "ne", ">": "gt", "<": "lt", " in ": "in", " filled": "filled", " empty": "empty" }[m[2]];
    return { field: m[1], op, value: op === "in" ? m[3].split(",").map((x) => x.trim()) : (["filled", "empty"].includes(op) ? null : m[3].trim()) };
  };
  async function templatesTab() {
    const m = S.project ? await meta() : { rights: { setup: false } };
    const rows = await run("udpr.templates", {});
    const box = h("div");
    box.append(h("div", { class: "bar" }, h("span", { class: "hint grow" }, "Templates are data: sections of fields, repeating tables and extra columns on the work rows. Editing saves a draft; publishing makes a new version for new DPRs. DPRs already made keep the version they were filled with."),
      m.rights.setup ? h("button", { class: "btn primary", onclick: () => tplEditor(null) }, "New template") : null),
    table([{ k: "code", label: "Code" }, { k: "name", label: "Template" }, { k: "category", label: "Category" }, { label: "For", v: (r) => r.project_id ? nm.project(r.project_id) : "All projects" },
      { label: "Version", v: (r) => r.version_no ? "v" + r.version_no + (r.unpublished ? " + draft" : "") : "draft" }, { k: "sections", label: "Sections", fmt: "num" }, { k: "fields", label: "Fields", fmt: "num" },
      { k: "projects", label: "Projects using", fmt: "num" }, { label: "Built in", v: (r) => r.system ? "Yes" : "" }, { label: "Active", v: (r) => r.active ? "Yes" : "No" }],
    rows, { name: "udpr_templates", onRow: (r) => tplEditor(r.id), empty: "No template." }));
    const reload = async () => { const n = await templatesTab(); box.replaceWith(n); };
    async function tplEditor(id) {
      const t = id ? await run("udpr.template_get", { id }) : { name: "", category: "custom", description: "", project_id: S.project || null, active: 1, draft: { sections: [] }, versions: [], field_types: m.field_types || [] };
      const ro = !m.rights.setup;
      const types = (t.field_types || []).map((x) => [x.key, x.label]);
      const head = form([{ k: "name", label: "Name", req: true }, { k: "category", label: "Category" },
        { k: "project_id", label: "For project", type: "select", options: opt.projects(), blank: "All projects", readonly: !!t.system }, { k: "active", label: "Active", type: "check" },
        { k: "description", label: "Description", wide: true }].map((x) => Object.assign(x, { readonly: ro || x.readonly })), t);
      const secs = (t.draft.sections || []).map((s) => Object.assign({}, s));
      const list = h("div");
      const fEditors = [];
      const draw = () => {
        list.innerHTML = "";
        fEditors.length = 0;
        secs.forEach((s, i) => {
          const sf = form([{ k: "key", label: "Internal name (a-z, 0-9, _)", req: true }, { k: "label", label: "Section title", req: true },
            { k: "kind", label: "Kind", type: "select", noBlank: true, options: [["fields", "Fields (one value per DPR)"], ["table", "Table (repeating rows)"], ["line", "Columns on the work rows"]] },
            { k: "group", label: "Shown under", type: "select", options: [["quality", "Quality"], ["hse", "Safety & environment"]], blank: "Project sections" },
            { k: "advanced", label: "Advanced (hidden until asked)", type: "check" }, { k: "sensitive", label: "Restricted (HSE private)", type: "check" },
            { k: "note", label: "Note shown to the user", wide: true }].map((x) => Object.assign(x, { readonly: ro })), Object.assign({}, s, { advanced: s.advanced ? 1 : 0, sensitive: s.sensitive ? 1 : 0 }));
          const fe = lineEditor([{ k: "key", label: "Internal name", w: 110 }, { k: "label", label: "Label", w: 170 }, { k: "type", label: "Type", type: "select", options: types, w: 140 },
            { k: "required", label: "Required", type: "select", options: [["1", "Yes"]], w: 70 }, { k: "unit", label: "Unit", w: 60 }, { k: "options", label: "Options (a | b | c)", w: 200 },
            { k: "min", label: "Min", type: "number", w: 60 }, { k: "max", label: "Max", type: "number", w: 60 }, { k: "default", label: "Default", w: 90 },
            { k: "show_if", label: "Show only if (e.g. kind = Near miss)", w: 180 }, { k: "edit_roles", label: "Only these roles may change (comma)", w: 160 }],
          (s.fields || []).map((f) => Object.assign({}, f, { required: f.required ? "1" : "", options: (f.options || []).join(" | "), show_if: siText(f.show_if), edit_roles: (f.edit_roles || []).join(", "), default: f.default ?? "" })),
          { readonly: ro, blank: { type: "text" } });
          fEditors.push({ i, sf, fe });
          list.append(h("div", { class: "udpr-sec" }, h("div", { class: "bar" }, h("b", { class: "grow" }, "Section " + (i + 1) + ": " + (s.label || "")),
            ro ? null : h("button", { class: "btn small", onclick: () => { grab(); if (i > 0) { [secs[i - 1], secs[i]] = [secs[i], secs[i - 1]]; draw(); } } }, "↑"),
            ro ? null : h("button", { class: "btn small warn", onclick: () => { grab(); secs.splice(i, 1); draw(); } }, "Remove section")), sf, h("h4", {}, "Fields"), fe));
        });
        if (!ro) list.append(h("button", { class: "btn", onclick: () => { grab(); secs.push({ key: "", label: "", kind: "table", fields: [] }); draw(); } }, "Add section"));
      };
      const grab = () => {
        fEditors.forEach(({ i, sf, fe }) => {
          const x = sf.values();
          const s = secs[i];
          s.key = x.key; s.label = x.label; s.kind = x.kind; s.group = x.group || undefined; s.advanced = !!Number(x.advanced); s.sensitive = !!Number(x.sensitive); s.note = x.note || undefined;
          s.fields = fe.lines().filter((f) => (f.key || "").trim() || (f.label || "").trim()).map((f) => {
            const o = { key: (f.key || "").trim(), label: (f.label || "").trim(), type: f.type || "text" };
            if (f.required === "1" || f.required === true) o.required = true;
            if ((f.unit || "").trim()) o.unit = f.unit.trim();
            const ops = String(f.options || "").split("|").map((x2) => x2.trim()).filter(Boolean);
            if (ops.length) o.options = ops;
            if (f.min !== "" && f.min != null) o.min = Number(f.min);
            if (f.max !== "" && f.max != null) o.max = Number(f.max);
            if (f.default !== "" && f.default != null) o.default = f.default;
            const si = typeof f.show_if === "object" ? f.show_if : siParse(f.show_if);
            if (si) o.show_if = si;
            const er = String(f.edit_roles || "").split(",").map((x2) => x2.trim()).filter(Boolean);
            if (er.length) o.edit_roles = er;
            Object.keys(f).forEach((k) => { if (!(k in o) && !["required", "unit", "options", "min", "max", "default", "show_if", "edit_roles", "key", "label", "type"].includes(k) && f[k] !== "" && f[k] != null) o[k] = f[k]; });
            return o;
          });
        });
      };
      draw();
      const vers = h("div", {}, h("h4", {}, "Published versions"), table([{ label: "Version", v: (r) => "v" + r.version_no }, { label: "Published", v: (r) => String(r.published_at || "").slice(0, 16) }, { label: "By", v: (r) => nm.user(r.published_by) }, { k: "note", label: "Note" }],
        t.versions || [], { search: false, export: false, empty: "Not published yet." }));
      const saveT = async (publish) => {
        try { grab(); } catch (e) { toast(e.message, "err"); throw e; }
        const x = head.values();
        let note = null;
        if (publish) { note = await ask("Publish", "Publishing makes a new version for new DPRs. What changed?", { input: "Note" }); if (note == null) throw new Error("cancelled"); }
        await run("udpr.template_save", { row: { id: t.id, name: x.name, category: x.category, description: x.description, project_id: x.project_id || null, active: x.active, draft: { sections: secs } }, publish: publish ? 1 : 0, note }, publish ? "Published" : "Draft saved");
        META = null;
        reload();
      };
      const btns = ro ? [] : [{ label: "Save draft", act: () => saveT(false) }, { label: "Save & publish", cls: "primary", act: () => saveT(true) }];
      if (t.id && m.rights.setup && S.project) btns.push({ label: "Copy for this project", act: async () => { const name = await ask("Copy template", "Name of the project's copy:", { input: t.name + " (" + nm.pcode(S.project) + ")", required: true }); if (!name) return false; await run("udpr.template_copy", { id: t.id, project_id: S.project, name: name.trim() }, "Copied"); reload(); } });
      const md = modal(t.id ? "Template " + t.name : "New template", h("div", {}, t.system ? h("div", { class: "udpr-note" }, "Built-in template. Changes publish a new version; you can also copy it for one project.") : null, head, list, vers), btns);
      md.el.querySelector(".modal").style.maxWidth = "min(1400px, 98vw)";
    }
    return box;
  }

  /* ───────────── wiring: tabs on Daily progress (DPR), smart form behind New / Open ───────────── */
  window.BCO_TABS = window.BCO_TABS || {};
  window.BCO_TABS["p/dpr"] = (window.BCO_TABS["p/dpr"] || []).concat([["Smart DPR register", registerTab], ["Progress & acceptance", progressTab], ["Issue register", issuesTab],
    ["DPR reports", reportsTab], ["Work fronts & set-up", setupTab], ["Templates & fields", templatesTab]]);

  if (typeof window.dprWizard === "function" && !window.dprWizard._bco225) {
    const classic = window.dprWizard;
    window.bcoClassicDpr = classic;
    const w = async function (dpr, ctx) {
      ctx = ctx || {};
      let mode = "smart";
      if (!ctx.classic) { try { const m = await meta(); mode = (m && m.form) || "smart"; } catch (e) { mode = "classic"; } }
      if (!ctx.classic && mode === "smart" && S.project) return smartDpr(dpr && dpr.id ? dpr.id : null, ctx);
      const n = document.querySelectorAll(".overlay").length;
      const r = await classic(dpr, ctx);
      const all = document.querySelectorAll(".overlay");
      if (all.length > n) {
        const foot = all[all.length - 1].querySelector("footer");
        if (foot) foot.insertBefore(h("button", { class: "btn", onclick: () => { all[all.length - 1].remove(); smartDpr(dpr && dpr.id ? dpr.id : null, ctx); } }, "Smart form"), foot.firstChild);
      }
      return r;
    };
    w._bco225 = true;
    window.dprWizard = w;
    try { dprWizard = w; } catch (e) { /* declared as a function: the window property is already replaced */ } // eslint-disable-line no-global-assign
  }
  /* What's new */
  const VER = "2.25.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!can("project", "view")) return;
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("p", {}, "The daily progress report now fits every kind of project, in the same place: Work › Daily progress (DPR)."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("Smart form.", "Short steps, only what applies to the project, kept on this computer until saved. The classic form is one click away."),
        li("Reported and accepted quantities.", "The site reports; the QS accepts, with cumulative, balance and % against the approved scope."),
        li("Project templates and fields.", "Building, road, hydropower, railway, bridge, water, transmission line and EPC, plus your own fields and tables, versioned."),
        li("Work fronts, issues and workflow.", "Packages and fronts on every row, a continuing issue register, Returned / Rejected / Locked with revisions."),
        li("DPR reports.", "Daily to monthly, activity, front, manpower, equipment, materials, quality, safety, issues and photos; print and Excel.")),
      h("p", { class: "hint" }, "No entry, account or balance changed. Existing DPRs keep their quantities; progress keeps using reported quantities until a project chooses accepted ones.")),
    [{ label: "Open Daily progress (DPR)", cls: "primary", act: () => { location.hash = "#/p/dpr"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 6000); } }, 900);
})();
