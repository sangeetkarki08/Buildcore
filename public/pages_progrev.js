/* BuildCore 2.60 — Programme revisions & Gantt, Project stages & checklists, Civil 3D quantities (Measurements tab). */
(function () {
"use strict";
if (window.__bco260) return; window.__bco260 = true;
const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
const empty = (t) => h("p", { class: "muted" }, t);
const projects = () => ((S.L && S.L.projects) || []).filter((p) => !p.kind || p.kind === "project");
let PID = null;
const pidNow = () => PID || S.project || (projects()[0] || {}).id;
const projSel = (onch) => h("select", { onchange: (e) => { PID = Number(e.target.value); onch(); } },
  projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(pidNow()) }, p.code + " · " + p.name)));
const addTabs = (route, title, sub, first, list) => {
  window.BCO_TABS = window.BCO_TABS || {};
  if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
  else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
};
const STATUS_TXT = { draft: "Draft", submitted: "Submitted to the Engineer", approved: "Approved (contract baseline)", rejected: "Rejected" };

/* ═════════════ Work › Programme revisions & Gantt ═════════════ */
PAGES["pv/revisions"] = async (root, params) => {
  root.append(pageHead("Programme revisions & Gantt", "Programme submissions to the Engineer with their letters, extension of time against the forecast, and a Gantt chart to print for the Engineer and the site office."));
  root.append(tabs([["Gantt chart", ganttTab], ["Baselines & submissions", baseTab], ["Extension of time", eotTab], ["Settings", setTab]], params && params.tab ? Number(params.tab) : 0));
};

async function baseTab() {
  const box = h("div");
  const load = async () => {
    const pid = pidNow();
    const d = await api("pv.baselines", { project_id: pid });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    box.append(h("p", { class: "hint" }, "Each saved baseline is a programme. Mark it submitted with the covering letter (Correspondence register), then approved or rejected when the Engineer replies. The approved one becomes the contract baseline that progress is measured against."));
    box.append(d.rows.length ? table([{ k: "no", label: "No" }, { k: "name", label: "Name" }, { k: "data_date", label: "Data date" }, { k: "finish", label: "Finish" },
      { label: "Status", v: (r) => h("span", { class: r.status === "rejected" ? "neg" : "" }, STATUS_TXT[r.status] || r.status) }, { label: "Letter", v: (r) => r.letter_no ? r.letter_no + " " + (r.letter_subject || "") : "" },
      { k: "submitted_on", label: "Submitted" }, { k: "decided_on", label: "Decided" }, { label: "In use", v: (r) => r.is_current ? "✓" : "" }, { k: "reason", label: "Reason" },
      { label: "", v: (r) => can("project", "approve") ? h("button", { class: "btn sm", onclick: () => statusDlg(r, d.letters, load) }, "Status") : "" }], d.rows, { search: false, name: "pv_base" }) : empty("No baseline yet. Calculate the schedule (Schedule & WBS); the first calculation saves baseline 0."));
  };
  await load();
  return box;
}

function statusDlg(r, letters, reload) {
  const f = form([{ k: "status", label: "Status", type: "select", noBlank: true, options: Object.entries(STATUS_TXT) },
    { k: "letter_id", label: "Letter", type: "select", options: letters.map((l) => [l.id, (l.our_no || l.their_ref || "") + " · " + l.date + " · " + (l.subject || "")]) },
    { k: "date", label: "Date", type: "date" }, { k: "reason", label: "Engineer's reason (if rejected)", wide: true }, { k: "note", label: "Note", wide: true }],
  { status: r.status && STATUS_TXT[r.status] ? r.status : "submitted", letter_id: r.letter_id, date: new Date().toISOString().slice(0, 10), reason: r.reason, note: r.snote });
  modal("Baseline " + r.no + " · " + r.name, f, [{ label: "Save", cls: "primary", act: async () => { await run("pv.base_status", Object.assign({ baseline_id: r.id }, f.values()), "Saved."); reload(); } }]);
}

async function eotTab() {
  const box = h("div");
  const load = async () => {
    const pid = pidNow();
    const d = await api("pv.eot", { project_id: pid });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    const c = d.contract || {};
    box.append(summaryStrip([["Original completion", c.original || "—"], ["Extension granted (days)", String(c.eot_days || 0)], ["Revised completion", c.revised || "—"],
      ["Forecast finish", d.forecast_finish || "—"], ["Days late", d.late_days == null ? "—" : String(d.late_days)], ["Baseline in use", d.current_baseline ? d.current_baseline.name + " (finish " + d.current_baseline.finish + ")" : "—"]]));
    if (d.advice) box.append(h("div", { class: "sf-banner" }, d.advice));
    box.append(h("p", { class: "hint" }, "Extension granted comes from delay events agreed (Contract administration) and approved variations with time. To submit a revised programme: set the contract time and recalculate (Schedule & WBS), then save it here as a draft baseline; it becomes the contract baseline when the Engineer approves it."));
    if (can("project", "approve")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const name = await ask("Revised programme", "Name of the revised programme", { input: "e.g. Revision 1 after EOT 1" }); if (name == null) return;
      await run("pv.revise", { project_id: pid, name: name || "Revised programme" }, "Saved as a draft baseline. Mark it submitted under Baselines & submissions."); load();
    } }, "Save the revised programme")));
    if (d.events.length) box.append(h("h3", {}, "Delay events with time"), table([{ k: "no", label: "No" }, { k: "date", label: "Date" }, { k: "title", label: "Event" }, { k: "status", label: "Status" }, { k: "eot_claimed", label: "Claimed (days)" }, { k: "eot_granted", label: "Granted (days)" }], d.events, { search: false }));
    if (d.variations.length) box.append(h("h3", {}, "Variations with time"), table([{ k: "no", label: "No" }, { k: "date", label: "Date" }, { k: "title", label: "Variation" }, { k: "status", label: "Status" }, { k: "time_impact_days", label: "Days" }], d.variations, { search: false }));
  };
  await load();
  return box;
}

/* ── Gantt ── */
const DAY = 86400000;
const dt = (s) => new Date(s + "T00:00:00Z");
const iso = (d) => d.toISOString().slice(0, 10);
const addD = (s, n) => iso(new Date(dt(s).getTime() + n * DAY));
const diff = (a, b) => Math.round((dt(b) - dt(a)) / DAY);
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
let GZ = "month", GCAL = "en", GBASE = null;

function drawGantt(d) {
  const acts = d.acts.filter((a) => a.start && a.finish);
  if (!acts.length) return empty("No dated activities. Calculate the schedule first.");
  const ppd = { week: 16, month: 3.6, quarter: 1.3 }[GZ];
  let lo = acts.reduce((m, a) => (a.start < m ? a.start : m), acts[0].start);
  let hi = acts.reduce((m, a) => (a.finish > m ? a.finish : m), acts[0].finish);
  acts.forEach((a) => { if (a.b_start && a.b_start < lo) lo = a.b_start; if (a.b_finish && a.b_finish > hi) hi = a.b_finish; });
  if (d.completion && d.completion > hi) hi = d.completion;
  lo = addD(lo, -7); hi = addD(hi, 14);
  const LW = 330, RH = 22, HH = 40, span = diff(lo, hi) + 1, W = LW + span * ppd;
  const NS = "http://www.w3.org/2000/svg";
  const el = (t, at, txt) => { const e = document.createElementNS(NS, t); for (const k in at) e.setAttribute(k, at[k]); if (txt != null) e.textContent = txt; return e; };
  const x = (s) => LW + diff(lo, s) * ppd;
  // group rows by WBS
  const rows = [];
  let last = null;
  acts.forEach((a) => { if ((a.wbs || "") !== last) { last = a.wbs || ""; rows.push({ head: true, label: (a.wbs || "No WBS") + (a.wbs_name ? " · " + a.wbs_name : "") }); } rows.push(a); });
  const H = HH + rows.length * RH + 10;
  const svg = el("svg", { xmlns: NS, width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: "pv-gantt", "font-family": "Inter, Arial, sans-serif", "font-size": "11" });
  const defs = el("defs", {}); const mk = el("marker", { id: "pvarr", markerWidth: 7, markerHeight: 7, refX: 6, refY: 3.5, orient: "auto" }); mk.append(el("path", { d: "M0,0 L7,3.5 L0,7 z", fill: "#64748b" })); defs.append(mk); svg.append(defs);
  svg.append(el("rect", { x: 0, y: 0, width: W, height: H, fill: "#fff" }));
  // time header
  const bands = [];
  if (GCAL === "bs" && window.adToBs) {
    let cur = null, start = lo;
    for (let i = 0; i <= span; i++) {
      const s = addD(lo, i); const b = (window.adToBs(s) || "").slice(0, 7);
      if (b !== cur) { if (cur) bands.push([start, s, cur]); cur = b; start = s; }
    }
    bands.push([start, addD(hi, 1), cur]);
  } else {
    let s = lo;
    while (s <= hi) { const d0 = dt(s); const n = iso(new Date(Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth() + 1, 1))); bands.push([s, n, s.slice(0, 7)]); s = n; }
  }
  const bsName = (k) => { const [y, m] = k.split("-"); return ((window.BS_MONTHS || [])[Number(m) - 1] || m) + " " + y; };
  const enName = (k) => { const [y, m] = k.split("-"); return MON[Number(m) - 1] + " " + y.slice(2); };
  let qPrev = null;
  bands.forEach(([s, e, k], i) => {
    const x0 = x(s), x1 = x(e);
    svg.append(el("rect", { x: x0, y: 0, width: x1 - x0, height: 18, fill: i % 2 ? "#f1f5f9" : "#e2e8f0" }));
    if (GZ !== "quarter") { if (x1 - x0 > 26) svg.append(el("text", { x: x0 + 3, y: 13, fill: "#334155" }, GCAL === "bs" ? bsName(k) : enName(k))); }
    else { const q = k.slice(0, 4) + "Q" + (Math.floor((Number(k.slice(5)) - 1) / 3) + 1); if (q !== qPrev) { svg.append(el("text", { x: x0 + 3, y: 13, fill: "#334155" }, GCAL === "bs" ? bsName(k) : q)); qPrev = q; } }
    svg.append(el("line", { x1: x0, y1: 18, x2: x0, y2: H, stroke: "#e2e8f0" }));
  });
  if (GZ === "week") for (let i = 0; i <= span; i += 7) { const s = addD(lo, i); svg.append(el("text", { x: x(s) + 2, y: 32, fill: "#64748b", "font-size": "9" }, s.slice(8) + "/" + s.slice(5, 7))); svg.append(el("line", { x1: x(s), y1: 22, x2: x(s), y2: H, stroke: "#f1f5f9" })); }
  svg.append(el("text", { x: 6, y: 32, "font-weight": "600", fill: "#0f172a" }, "Activity"));
  svg.append(el("line", { x1: 0, y1: HH - 2, x2: W, y2: HH - 2, stroke: "#94a3b8" }));
  const ypos = {};
  rows.forEach((r, i) => {
    const y = HH + i * RH;
    if (r.head) { svg.append(el("rect", { x: 0, y, width: W, height: RH, fill: "#f8fafc" })); svg.append(el("text", { x: 6, y: y + 15, "font-weight": "700", fill: "#0f172a" }, r.label.slice(0, 60))); return; }
    ypos[r.id] = y;
    const name = ((r.code || "") + " " + r.name);
    svg.append(el("text", { x: 14, y: y + 15, fill: r.critical ? "#b91c1c" : "#0f172a" }, name.length > 52 ? name.slice(0, 51) + "…" : name));
    if (r.b_start && r.b_finish) svg.append(el("rect", { x: x(r.b_start), y: y + 15, width: Math.max(2, (diff(r.b_start, r.b_finish) + 1) * ppd), height: 4, fill: "#94a3b8", rx: 1 }));
    if (r.milestone || r.start === r.finish && r.milestone) {
      const cx = x(r.start); svg.append(el("path", { d: `M${cx},${y + 4} L${cx + 6},${y + 10} L${cx},${y + 16} L${cx - 6},${y + 10} z`, fill: r.critical ? "#dc2626" : "#1e3a8a" }));
    } else {
      const w = Math.max(2, (diff(r.start, r.finish) + 1) * ppd);
      svg.append(el("rect", { x: x(r.start), y: y + 4, width: w, height: 10, rx: 2, fill: r.done ? "#64748b" : r.critical ? "#ef4444" : "#3b82f6" }));
      if (r.pct > 0 && !r.done) svg.append(el("rect", { x: x(r.start), y: y + 7, width: w * r.pct / 100, height: 4, fill: r.critical ? "#7f1d1d" : "#1e3a8a" }));
    }
    const t = el("title", {}, `${name}\n${r.start} → ${r.finish}${r.b_start ? "\nBaseline " + r.b_start + " → " + r.b_finish : ""}\nFloat ${r.tf == null ? "—" : r.tf} days · ${r.pct}% done`);
    svg.lastChild.append(t);
  });
  const byId = {}; acts.forEach((a) => { byId[a.id] = a; });
  d.links.forEach((l) => {
    const p = byId[l.pred_id], s = byId[l.succ_id];
    if (!p || !s || ypos[p.id] == null || ypos[s.id] == null) return;
    const x1 = (l.type === "SS" || l.type === "SF") ? x(p.start) : x(p.finish) + ppd, y1 = ypos[p.id] + 9;
    const x2 = (l.type === "FF" || l.type === "SF") ? x(s.finish) + ppd : x(s.start), y2 = ypos[s.id] + 9;
    const mx = Math.max(x1 + 6, Math.min(x2 - 6, x1 + 10));
    svg.append(el("path", { d: `M${x1},${y1} H${mx} V${y2} H${x2 - 1}`, fill: "none", stroke: (p.critical && s.critical) ? "#dc2626" : "#64748b", "stroke-width": 1, "marker-end": "url(#pvarr)" }));
  });
  const vline = (s, color, label, dash) => { if (!s || s < lo || s > hi) return; svg.append(el("line", { x1: x(s), y1: 18, x2: x(s), y2: H, stroke: color, "stroke-width": 1.5, "stroke-dasharray": dash })); svg.append(el("text", { x: x(s) + 3, y: H - 3, fill: color, "font-size": "10" }, label)); };
  vline(d.data_date, "#16a34a", "Data date " + d.data_date, "4 3");
  vline(d.completion, "#dc2626", "Contract completion " + d.completion, "");
  return svg;
}

async function ganttTab() {
  const box = h("div");
  const load = async () => {
    const pid = pidNow();
    const d = await api("pv.gantt", { project_id: pid, baseline_id: GBASE });
    const zoom = h("select", { onchange: (e) => { GZ = e.target.value; load(); } }, [["week", "Week"], ["month", "Month"], ["quarter", "Quarter"]].map(([v, l]) => h("option", { value: v, selected: v === GZ }, l)));
    const cal = h("select", { onchange: (e) => { GCAL = e.target.value; load(); } }, [["en", "English months"], ["bs", "Nepali months"]].map(([v, l]) => h("option", { value: v, selected: v === GCAL }, l)));
    const bsel = h("select", { onchange: (e) => { GBASE = e.target.value ? Number(e.target.value) : null; load(); } }, h("option", { value: "" }, "Baseline in use"),
      d.baselines.map((b) => h("option", { value: b.id, selected: b.id === GBASE }, b.no + " · " + b.name + (b.status ? " (" + b.status + ")" : ""))));
    const paper = h("select", {}, ["A4", "A3", "A1"].map((p) => h("option", { value: p, selected: p === "A3" }, p)));
    const svg = drawGantt(d);
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load)), lbl("Zoom", zoom), lbl("Months", cal), lbl("Baseline bars", bsel), lbl("Paper", paper),
      h("button", { class: "btn", onclick: () => printGantt(svg, d, paper.value) }, "Print")),
    h("p", { class: "hint" }, "Red: critical path. Grey line under a bar: the baseline. Dark line in a bar: progress. Green dashed line: data date; red line: contract completion. Hover a bar for its dates and float."),
    h("div", { style: "overflow:auto;border:1px solid var(--line,#e2e8f0);border-radius:8px;max-height:75vh" }, svg));
  };
  await load();
  return box;
}

function printGantt(svg, d, paper) {
  const w = window.open("", "_blank");
  if (!w) return toast("Allow pop-ups to print.", "err");
  const title = (d.project.code || "") + " · " + (d.project.name || "") + " · Programme (data date " + d.data_date + ")";
  w.document.write(`<html><head><title>${escHtml(title)}</title><style>@page{size:${paper} landscape;margin:8mm}body{margin:0;font-family:Arial,sans-serif}h3{margin:0 0 4px;font-size:12px}svg{width:100%;height:auto}</style></head><body><h3>${escHtml(title)}</h3>${svg.outerHTML}<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

async function setTab() {
  const d = await api("pv.settings", {});
  const f = form([{ k: "hide_bar", label: "Hide the bar column in the Schedule & WBS table (the Gantt chart replaces it)", type: "check", wide: true },
    { k: "alert", label: "Alert: stage checklist item late", type: "check", wide: true }], { hide_bar: d.hide_bar ? 1 : 0, alert: d.alert ? 1 : 0 });
  return h("div", {}, f, can("project", "approve") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { const r = await run("pv.settings_save", f.values(), "Saved."); HIDE = r.hide_bar; } }, "Save")) : null);
}

/* R16: hide the bar column of the schedule table when chosen */
let HIDE = null;
const hideBars = async () => {
  if (!S || !S.token || !/^#\/p\/schedule/.test(location.hash)) return;
  if (HIDE == null) { try { HIDE = (await api("pv.settings", {})).hide_bar; } catch (e) { HIDE = false; } }
  if (!HIDE) return;
  document.querySelectorAll("table").forEach((t) => {
    const ths = [...t.querySelectorAll("thead th")];
    const i = ths.findIndex((th) => /^Timeline/.test(th.textContent.trim()));
    if (i < 0) return;
    ths[i].style.display = "none";
    t.querySelectorAll("tbody tr").forEach((tr) => { const td = tr.children[i]; if (td) td.style.display = "none"; });
  });
};
new MutationObserver(() => { clearTimeout(hideBars._t); hideBars._t = setTimeout(hideBars, 300); }).observe(document.body, { childList: true, subtree: true });

/* ═════════════ Work › Project stages & checklists ═════════════ */
PAGES["pv/stages"] = async (root, params) => {
  root.append(pageHead("Project stages & checklists", "Stage of each project from tender to closed, and the checklist for each stage. Items BuildCore finds in the books are ticked by themselves."));
  root.append(tabs([["This project", stageTab], ["All projects", companyTab], ["Checklist templates", tplTab]], params && params.tab ? Number(params.tab) : 0));
};

async function stageTab() {
  const box = h("div");
  const load = async () => {
    const pid = pidNow();
    const d = await api("pv.stage", { project_id: pid });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    box.append(summaryStrip([["Stage", d.stage_label + (d.guessed ? " (guessed)" : "")], ["Since", d.since || "—"], ["Stage to end by", d.target_end || "—"]]));
    if (d.guessed) box.append(h("p", { class: "hint" }, "The stage is guessed from the records. Set it to start the checklist dates and alerts."));
    if (can("project", "approve")) {
      const f = form([{ k: "stage", label: "Stage", type: "select", noBlank: true, options: d.stages.map((s) => [s.stage, s.label]) }, { k: "since", label: "Since", type: "date" }, { k: "target_end", label: "Stage to end by", type: "date" }],
        { stage: d.stage, since: d.since, target_end: d.target_end });
      box.append(h("details", {}, h("summary", {}, "Change the stage"), f, h("button", { class: "btn primary", onclick: async () => { await run("pv.stage_save", Object.assign({ project_id: pid }, f.values()), "Saved."); load(); } }, "Save")));
    }
    d.stages.forEach((s) => {
      box.append(h("h3", { class: s.current ? "" : "muted" }, s.label + " · " + s.done + "/" + s.total + (s.current ? " (current)" : s.past ? " (past)" : "")));
      box.append(table([{ label: "", v: (i) => { const cb = h("input", { type: "checkbox", checked: i.done, disabled: i.auto === true || !can("project", "edit") }); cb.onchange = async () => { await run("pv.check_save", { project_id: pid, tpl_id: i.id, done: cb.checked ? 1 : 0 }); load(); }; return cb; } },
        { label: "Item", v: (i) => h("span", { class: i.late ? "neg" : "" }, i.item) }, { label: "From the books", v: (i) => i.auto === true ? "found" : i.auto === false ? "not found" : "" },
        { k: "due", label: "Due" }, { k: "done_on", label: "Ticked" }, { label: "", v: (i) => i.route ? h("a", { href: i.route }, "Open") : "" }], s.items, { search: false }));
    });
  };
  await load();
  return box;
}

async function companyTab() {
  const d = await api("pv.company", {});
  return h("div", {}, summaryStrip(d.stages.map((s) => [s.label, String(s.count)])),
    table([{ k: "project", label: "Project" }, { k: "name", label: "Name" }, { label: "Stage", v: (r) => r.stage_label + (r.guessed ? " (guessed)" : "") }, { k: "since", label: "Since" },
      { label: "Checklist", v: (r) => r.done + "/" + r.total }, { label: "Late items", v: (r) => r.late.length ? h("span", { class: "neg" }, r.late.join("; ")) : "" },
      { label: "Stage overrun", v: (r) => r.overrun ? h("span", { class: "neg" }, "past " + r.target_end) : "" }], d.rows, { name: "pv_company" }));
}

async function tplTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("pv.tpl", {});
    box.replaceChildren(h("p", { class: "hint" }, "The checklist items for every project. Due days count from the day the stage starts. Items with a check from the books are ticked by themselves."));
    if (can("admin", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => edit({ active: 1, stage: "mobilisation" }, d.stages) }, "+ Item")));
    box.append(table([{ label: "Stage", v: (r) => (d.stages.find((s) => s.key === r.stage) || {}).label }, { k: "item", label: "Item" }, { k: "due_days", label: "Due (days)" }, { label: "From the books", v: (r) => r.auto ? "yes" : "" },
      { label: "In use", v: (r) => r.active ? "✓" : "" }, { label: "", v: (r) => can("admin", "edit") ? h("button", { class: "btn sm", onclick: () => edit(r, d.stages) }, "Edit") : "" }], d.rows, { name: "pv_tpl" }));
  };
  const edit = (r, stages) => {
    const f = form([{ k: "stage", label: "Stage", type: "select", noBlank: true, options: stages.map((s) => [s.key, s.label]) }, { k: "item", label: "Item", wide: true }, { k: "due_days", label: "Due (days after the stage starts)", type: "number" },
      { k: "route", label: "Link (screen)" }, { k: "sort", label: "Order", type: "number" }, { k: "active", label: "In use", type: "check" }], r);
    modal(r.id ? "Checklist item" : "New checklist item", f, [{ label: "Save", cls: "primary", act: async () => { await run("pv.tpl_save", { row: Object.assign({ id: r.id }, f.values()) }, "Saved."); load(); } }]);
  };
  await load();
  return box;
}

/* ═════════════ Commercial › Measurements › Civil 3D quantities ═════════════ */
async function c3dTab() {
  const box = h("div");
  const pid0 = pidNow();
  const ta = h("textarea", { rows: 10, placeholder: "Paste the Civil 3D volume report (Station, Cut Area, Cut Volume, Fill Area, Fill Volume ...) from Excel, or open a LandXML file below.", style: "width:100%;font-family:monospace" });
  const file = h("input", { type: "file", accept: ".xml,.csv,.txt", onchange: async (e) => { const f = e.target.files[0]; if (f) ta.value = await f.text(); } });
  const frm = h("input", { placeholder: "0+000", style: "width:100px" }), to = h("input", { placeholder: "1+500", style: "width:100px" });
  const out = h("div");
  let pid = pid0;
  const boqOpts = () => (S.L.boq || []).filter((b) => String(b.project_id) === String(pid)).map((b) => [b.id, b.code + " " + (b.description || "").slice(0, 60) + " (" + (b.unit || "") + ")"]);
  const mk = (k) => h("select", { name: k }, h("option", { value: "" }, "—"), boqOpts().map(([v, l]) => h("option", { value: v }, l)));
  let cut = mk("cut"), fill = mk("fill");
  const psel = h("select", { onchange: (e) => { pid = Number(e.target.value); const c2 = mk("cut"), f2 = mk("fill"); cut.replaceWith(c2); fill.replaceWith(f2); cut = c2; fill = f2; } },
    projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(pid) }, p.code + " · " + p.name)));
  const preview = async () => {
    const d = await run("pv.c3d_preview", { text: ta.value, from: frm.value, to: to.value });
    out.replaceChildren(summaryStrip([["Read from", d.source], ["Stations", String(d.stations) + " (" + d.first + " to " + d.last + ")"], ["Between", d.from + " and " + d.to], ["Cut (cum)", String(d.cut)], ["Fill (cum)", String(d.fill)]]),
      table([{ k: "ch", label: "Chainage" }, { k: "cut_area", label: "Cut area" }, { k: "fill_area", label: "Fill area" }, { k: "cut", label: "Cut volume" }, { k: "fill", label: "Fill volume" }], d.rows, { search: false, name: "c3d" }));
  };
  box.append(h("p", { class: "hint" }, "Cut and fill between two chainages from the Civil 3D volume report or a LandXML file with cross sections. Volumes given in the report are used; otherwise average end area. The result is a draft measurement to check and verify."),
    h("div", { class: "bar" }, lbl("Project", psel), lbl("LandXML / CSV file", file)), ta,
    h("div", { class: "bar" }, lbl("From chainage", frm), lbl("To chainage", to), lbl("BOQ item for cut", cut), lbl("BOQ item for fill", fill)),
    h("div", { class: "actions" }, h("button", { class: "btn", onclick: preview }, "Work out"),
      can("commercial", "edit") ? h("button", { class: "btn primary", onclick: async () => {
        const r = await run("pv.c3d_make", { project_id: pid, text: ta.value, from: frm.value, to: to.value, cut_boq_id: cut.value, fill_boq_id: fill.value }, (x) => "Draft measurement made: cut " + x.cut + ", fill " + x.fill + ".");
        if (r) location.hash = "#/p/measure";
      } }, "Make the draft measurement") : null), out);
  return box;
}
addTabs("p/measure", "Measurements", "Joint measurements with the client.", "Measurements", [["Civil 3D quantities", c3dTab]]);
})();
