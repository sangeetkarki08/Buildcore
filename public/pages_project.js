/* BuildCore 3 — project control pages */
"use strict";

S.P = { wbs: [], activities: [], trades: [] };
const actOpts = (wbsId) => (S.P.activities || []).filter((a) => !wbsId || String(a.wbs_id) === String(wbsId)).map((a) => [a.id, (a.code ? a.code + " " : "") + a.name]);
const wbsOpts = () => (S.P.wbs || []).map((w) => [w.id, w.code + " " + w.name]);
const tradeOpts = () => (S.P.trades || []).filter((t) => t.active).map((t) => [t.id, t.name + " (" + fmtN(t.rate_hour) + "/h)"]);
const nmAct = (id) => { const a = byId(S.P.activities, id); return a ? (a.code ? a.code + " " : "") + a.name : ""; };
const nmWbs = (id) => { const w = byId(S.P.wbs, id); return w ? w.code + " " + w.name : ""; };

async function loadProjectLists() {
  if (!S.project) { S.P = { wbs: [], activities: [], trades: [] }; return; }
  const [wbs, activities, trades] = await Promise.all([
    api("master.list", { table: "wbs", project_id: S.project }),
    api("master.list", { table: "activities", project_id: S.project }),
    api("master.list", { table: "trades" }),
  ]);
  S.P = { wbs, activities, trades: trades.filter((t) => !t.project_id || String(t.project_id) === String(S.project)) };
}
function projectGuard(root, title) {
  if (S.project) return false;
  root.append(pageHead(title), projectNotice());
  return true;
}
function tile(label, value, o) {
  o = o || {};
  return h("div", { class: "tile " + (o.cls || ""), onclick: o.href ? () => { location.hash = o.href; } : null, title: o.title || null },
    h("b", {}, value), h("span", {}, label), o.sub ? h("small", {}, o.sub) : null);
}

/* ── Command centre (company) ── */
PAGES.command = async (root) => {
  const rows = await run("portfolio", {});
  const act = rows.filter((r) => r.status === "active");
  const sum = (k) => act.reduce((a, r) => a + (Number(r[k]) || 0), 0);
  const delayed = act.filter((r) => r.health.schedule !== "ok").length;
  root.append(pageHead("Command centre", "All projects at a glance. Click a project to open its control room."),
    h("div", { class: "tiles" }, tile("Active projects", act.length), tile("Projects needing schedule attention", delayed, { cls: delayed ? "warn" : "" }),
      tile("Contract value", fmtMoney(sum("contract_value"))), tile("Work done (earned revenue)", fmtMoney(sum("earned"))),
      tile("Actual cost", fmtMoney(sum("cost"))), tile("Forecast profit", fmtMoney(sum("forecast_profit")), { cls: sum("forecast_profit") < 0 ? "bad" : "" }),
      tile("Receivables", fmtMoney(sum("receivable")), { href: "#/acc/ageing" })),
    table([
      { k: "code", label: "Project" }, { k: "name", label: "Name" },
      { label: "Progress", v: (r) => h("div", {}, progressBar(r.planned_pct, r.actual_pct), h("small", {}, fmtN(r.actual_pct, 1) + "% of " + fmtN(r.planned_pct, 1) + "% planned")) },
      { label: "SPI", v: (r) => fmtN(r.spi) }, { label: "CPI", v: (r) => fmtN(r.cpi) },
      { k: "contract_value", label: "Contract", fmt: "money" }, { k: "earned", label: "Earned", fmt: "money" },
      { k: "eac", label: "Forecast cost", fmt: "money" }, { label: "Forecast margin", v: (r) => r.forecast_margin == null ? "—" : r.forecast_margin + "%" },
      { k: "receivable", label: "Receivable", fmt: "money" },
      { label: "Health", v: (r) => h("div", { class: "dots" }, Object.entries(r.health).map(([k, l]) => h("span", { class: "dot lv-" + l, title: k + ": " + LEVEL_TEXT[l] }, k[0].toUpperCase()))) },
      { label: "Why", v: (r) => r.risks.slice(0, 2).join(" ") },
    ], rows, { name: "portfolio", onRow: (r) => { setProject(r.id); location.hash = "#/p/control"; } }));
  // What the team is doing right now, wherever they are sitting.
  try {
    const live = await api("team.feed", { limit: 12 });
    const tick = await api("team.tick", { since_id: live.last_id });
    LIVE.seen = live.last_id;
    root.append(h("div", { class: "panel" },
      h("div", { class: "bar" }, h("h2", { class: "grow" }, "Happening now"),
        h("a", { class: "btn small", href: "#/p/live" }, "Open live activity")),
      onlineStrip(tick.online), feedList(live.rows)));
  } catch (e) { /* the feed is never allowed to hide the numbers above */ }
};
PAGES.command.live = true;

/* ── Action centre ── */
PAGES.action = async (root) => {
  let scope = S.project ? "project" : "all";
  const holder = h("div");
  const CATS = [["critical", "Critical"], ["overdue", "Overdue"], ["today", "Due today"], ["approval", "Waiting approval"], ["upcoming", "Upcoming"], ["info", "Information"]];
  const load = async () => {
    const items = await run("action.centre", { project_id: scope === "project" ? S.project : null });
    holder.innerHTML = "";
    holder.append(h("div", { class: "tiles" }, CATS.map(([k, l]) => tile(l, items.filter((x) => x.category === k).length, { cls: k === "critical" ? "bad" : k === "overdue" ? "warn" : "" }))));
    CATS.forEach(([k, l]) => {
      const list = items.filter((x) => x.category === k);
      if (!list.length) return;
      holder.append(h("div", { class: "panel" }, h("h2", {}, l + " (" + list.length + ")"),
        h("ul", { class: "actions-list" }, list.map((x) => h("li", { class: "cat-" + k, onclick: () => { if (x.project_id) setProject(x.project_id, true); location.hash = x.link; } },
          h("b", {}, x.title), x.project_id && scope === "all" ? h("span", { class: "tag" }, nm.pcode(x.project_id)) : null,
          x.due ? h("span", { class: "hint" }, " due " + x.due) : null, h("div", { class: "why" }, x.why))))));
    });
    if (!items.length) holder.append(h("div", { class: "panel" }, "Nothing needs attention."));
  };
  const sel = h("select", { onchange: (e) => { scope = e.target.value; load(); } }, h("option", { value: "project", selected: scope === "project" }, "This project"), h("option", { value: "all", selected: scope === "all" }, "All projects"));
  root.append(pageHead("Action centre", "Everything that needs a person: approvals, overdue work, risks and deadlines. Each item says why it is here.",
    sel, can("project", "edit") ? h("button", { class: "btn", onclick: async () => { const r = await run("action.generate_tasks", { project_id: scope === "project" ? S.project : null }); toast(r.created + " task(s) created", "ok"); load(); } }, "Create tasks for critical items") : null), holder);
  load();
};

/* ── Project control room ── */
PAGES["p/control"] = async (root, params) => {
  if (params.project) setProject(params.project, true);
  if (projectGuard(root, "Project control room")) return;
  const d = await run("control.room", { project_id: S.project });
  const pr = d.progress, co = d.cost, bi = d.billing;
  root.append(pageHead(d.project.code + " " + d.project.name, "Control room as of " + d.as_of + (pr.days_remaining != null ? " · " + pr.days_remaining + " days to contract completion" : ""),
    can("project", "edit") ? h("button", { class: "btn primary", onclick: () => { location.hash = "#/p/dpr?new=1"; } }, "+ DPR") : null, h("button", { class: "btn", onclick: () => window.print() }, "Print")));
  const dimNames = { schedule: "Schedule", cost: "Cost", quality: "Quality", resources: "Resources", commercial: "Commercial" };
  root.append(h("div", { class: "health" }, Object.entries(d.health).map(([k, v]) => h("div", { class: "hcard lv-" + v.level },
    h("div", { class: "hhead" }, h("b", {}, dimNames[k]), levelStamp(v.level)), h("ul", {}, v.reasons.map((r) => h("li", {}, r)))))));
  root.append(h("h2", { class: "sec" }, "Progress"), h("div", { class: "tiles" },
    tile("Planned progress", fmtN(pr.planned_pct, 1) + "%"), tile("Actual progress", fmtN(pr.actual_pct, 1) + "%", { cls: pr.variance < 0 ? "warn" : "" }),
    tile("Variance", fmtN(pr.variance, 1) + " pts", { cls: pr.variance < -5 ? "bad" : "" }), tile("SPI", fmtN(pr.spi), { title: "Earned ÷ planned progress" }),
    tile("Forecast finish", pr.forecast_finish || "needs progress data", { sub: d.project.end_date ? "contract " + d.project.end_date : null }),
    tile("Days elapsed", pr.days_elapsed ?? "—")));
  const sc = h("div", { class: "panel" }, h("h2", {}, "S-curve: planned vs actual"), h("p", { class: "muted" }, "Loading…"));
  root.append(sc);
  api("sched.scurve", { project_id: S.project }).then((pts) => {
    sc.lastChild.remove();
    sc.append(pts.length ? lineChart(pts.map((p) => p.date.slice(5)), [{ name: "Planned %", color: "#1b5e86", values: pts.map((p) => p.planned) }, { name: "Actual %", color: "#d9950f", values: pts.map((p) => p.actual) }], { max: 100, unit: "%" }) : h("p", { class: "muted" }, "Add activities with planned dates to see the S-curve."));
  });
  root.append(h("h2", { class: "sec" }, "Cost & forecast"), h("div", { class: "tiles" },
    tile("Budget (BAC)", fmtMoney(co.bac)), tile("Earned value", fmtMoney(co.ev)), tile("Actual cost", fmtMoney(co.ac), { sub: "incl. " + fmtMoney(co.ac_unallocated) + " not linked to BOQ" }),
    tile("Committed (open POs)", fmtMoney(co.committed)), tile("CPI", fmtN(co.cpi), { cls: co.cpi != null && co.cpi < 0.95 ? "bad" : "" }),
    tile("Forecast cost (EAC)", fmtMoney(co.eac)), tile("Forecast revenue", fmtMoney(co.forecast_revenue)),
    tile("Forecast profit", fmtMoney(co.forecast_profit), { cls: co.forecast_profit < 0 ? "bad" : "" }),
    tile("Margin: tender / now / forecast", [co.tender_margin, co.current_margin, co.forecast_margin].map((x) => x == null ? "—" : x + "%").join(" / "), { sub: co.margin_fade != null ? "margin fade " + co.margin_fade + " pts" : null, href: "#/p/evm" })));
  const funnel = [["Executed", bi.executed], ["Measured", bi.measured], ["Billed", bi.billed], ["Certified", bi.certified], ["Received", bi.received]];
  const fmax = Math.max(1, ...funnel.map((f) => f[1]));
  root.append(h("div", { class: "cols" },
    h("div", { class: "panel" }, h("h2", {}, "Billing"), h("div", { class: "funnel" }, funnel.map(([l, v]) => h("div", {}, h("span", {}, l), h("i", { style: "width:" + (100 * v / fmax) + "%" }), h("b", {}, fmtMoney(v))))),
      h("p", {}, "Receivable: ", h("b", {}, fmtMoney(bi.receivable)))),
    h("div", { class: "panel" }, h("h2", {}, "Resources"), kv([["Manpower today", fmtN(d.resources.manpower_today, 0)], ["Man-hours (7 days)", fmtN(d.resources.manhours_week)], ["Equipment on project", d.resources.equipment_on_site], ["Machine hours (7 days)", fmtN(d.resources.equipment_hours_week)]]),
      d.resources.shortages.length ? h("div", {}, h("h3", { class: "red" }, "Material shortage risk"), h("ul", {}, d.resources.shortages.map((m) => h("li", {}, h("b", {}, m.name), " — ", m.why)))) : h("p", { class: "green" }, "No material shortage risk.")),
    h("div", { class: "panel" }, h("h2", {}, "Commercial"), kv([["Variations", (d.commercial.variations.n || 0) + " (" + (d.commercial.variations.approved || 0) + " approved, " + (d.commercial.variations.pending || 0) + " pending)"], ["Open events / claims", d.commercial.events_open], ["Delay days claimed", fmtN(d.commercial.eot_days)], ["Claimed cost impact", fmtMoney(d.commercial.claim_value)]]),
      h("p", {}, h("a", { href: "#/p/events" }, "Events & claims"), " · ", h("a", { href: "#/p/variations" }, "Variations")))));
  root.append(h("div", { class: "cols" },
    h("div", { class: "panel" }, h("h2", {}, "Critical & delayed activities"), table([{ label: "Activity", v: (r) => (r.code || "") + " " + r.name }, { label: "Progress", v: (r) => progressBar(r.planned_pct, r.actual_pct) }, { label: "Forecast", v: (r) => r.forecast_finish || "—" }, { label: "Delay", v: (r) => r.delay_days > 0 ? h("b", { class: "red" }, r.delay_days + " d") : "—" }], d.critical, { search: false, export: false, empty: "No critical or delayed activities." })),
    h("div", { class: "panel" }, h("h2", {}, "Needs attention"), d.attention.length ? h("ul", { class: "actions-list" }, d.attention.map((x) => h("li", { class: "cat-" + x.category, onclick: () => { location.hash = x.link; } }, h("b", {}, x.title), h("div", { class: "why" }, x.why)))) : h("p", {}, "Nothing needs attention."),
      h("p", {}, h("a", { href: "#/action" }, "Open action centre")))));
};

/* ── Today & site mode ── */
function quickActions(big) {
  const acts = [
    ["DPR", "#/p/dpr?new=1", "project", "edit"], ["Material issue", "#/inv/issue?new=1", "inventory", "edit"], ["Requisition", "#/inv/mrq?new=1", "inventory", "edit"],
    ["Equipment log", "#/eq/logs?new=1", "equipment", "edit"], ["Photo", "#/p/docs?photo=1", "project", "view"], ["Issue / event", "#/p/events?new=1", "project", "view"],
    ["Task", "#/p/tasks?new=1", "project", "view"], ["Test request", "#/p/quality?new=1", "quality", "edit"], ["Measurement", "#/p/measure?new=1", "commercial", "edit"],
  ].filter(([, , m, a]) => can(m, a));
  return h("div", { class: big ? "bigbtns" : "quick" }, acts.map(([l, href]) => h("button", { class: "btn " + (big ? "big" : ""), onclick: () => { location.hash = href; } }, (big ? "" : "+ ") + l)));
}
PAGES["p/today"] = async (root) => {
  if (projectGuard(root, "Today")) return;
  const d = await run("today.view", { project_id: S.project });
  root.append(pageHead("Today — " + d.date, nm.project(S.project)), quickActions(false));
  const dprBox = d.dpr ? h("p", {}, "Today's DPR ", h("a", { href: "#/p/dpr?id=" + d.dpr.id }, d.dpr.no), " is ", stamp(d.dpr.status)) : h("p", {}, h("b", { class: "red" }, "No DPR yet. "), h("a", { href: "#/p/dpr?new=1" }, "Start today's DPR"));
  root.append(h("div", { class: "cols" },
    h("div", { class: "panel" }, h("h2", {}, "Daily report"), dprBox,
      h("h3", {}, "Planned work today (from schedule)"), table([{ k: "name", label: "Activity" }, { label: "Target", v: (r) => fmtN(r.planned_qty) + " " + (r.unit || "") }, { k: "location", label: "Location" }], d.planned, { search: false, export: false, empty: "Nothing scheduled for today." })),
    h("div", { class: "panel" }, h("h2", {}, "Materials issued today"), table([{ k: "no", label: "Issue" }, { label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "amount", label: "Cost", fmt: "money" }], d.materials, { search: false, export: false, empty: "No issues today." }),
      h("h3", {}, "Equipment logged today"), table([{ label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "hours", label: "Hours", fmt: "qty" }, { k: "breakdown_hours", label: "Breakdown", fmt: "qty" }], d.logs, { search: false, export: false, empty: "No logsheets today." }),
      d.down.length ? h("p", { class: "red" }, "Down: " + d.down.map((x) => x.code).join(", ")) : null),
    h("div", { class: "panel" }, h("h2", {}, "My tasks"), d.tasks.length ? h("ul", { class: "actions-list" }, d.tasks.map((t) => h("li", { class: t.priority === "high" ? "cat-critical" : "" }, h("b", {}, t.title), h("span", { class: "hint" }, t.due_date ? " due " + t.due_date : ""),
      h("button", { class: "btn small", style: "float:right", onclick: async (e) => { e.stopPropagation(); await run("task.status", { id: t.id, status: "done" }, "Done"); go(); } }, "Done")))) : h("p", { class: "muted" }, "No open tasks."),
      h("h3", {}, "Issues recorded today"), d.events.length ? h("ul", {}, d.events.map((e) => h("li", {}, e.title))) : h("p", { class: "muted" }, "None."),
      h("h3", {}, "Photos today"), fileList(d.photos))));
};
PAGES.site = async (root) => {
  root.append(h("div", { class: "sitemode" }, h("h1", {}, "Site mode"), h("p", { class: "muted" }, S.project ? nm.project(S.project) : "Choose a project at the top first."), quickActions(true),
    h("p", {}, h("a", { href: "#/p/today" }, "Today's summary"), " · ", h("a", { href: "#/p/control" }, "Control room"))));
};

/* ── Schedule & WBS ── */
function activityForm(a, done) {
  const f = form([
    { k: "wbs_id", label: "WBS", type: "select", options: wbsOpts, req: true }, { k: "code", label: "Code" }, { k: "name", label: "Activity", req: true },
    { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), search: true }, { k: "location", label: "Location / chainage" }, { k: "unit", label: "Unit" },
    { k: "planned_qty", label: "Planned quantity", type: "number" }, { k: "planned_start", label: "Planned start", type: "date" }, { k: "planned_finish", label: "Planned finish", type: "date" },
    { k: "baseline_start", label: "Baseline start", type: "date" }, { k: "baseline_finish", label: "Baseline finish", type: "date" }, { k: "weight", label: "Weight (blank = by BOQ value)", type: "number" },
    { k: "responsible", label: "Responsible" }, { k: "predecessors", label: "Predecessors (codes)" }, { k: "std_labour_prod", label: "Standard output per man-hour", type: "number" },
    { k: "std_equip_prod", label: "Standard output per machine-hour", type: "number" }, { k: "test_required", label: "Test required after work", ph: "e.g. Cube test" },
    { k: "delay_reason", label: "Delay reason", wide: true }, { k: "critical", label: "On critical path", type: "check" }, { k: "is_milestone", label: "Milestone", type: "check" },
  ], a || { planned_start: today() }, () => {
    const b = byId(S.L.boq, f.values().boq_item_id);
    if (b && !f.values().unit) f.set("unit", b.unit);
  });
  const body = h("div", {}, f, a ? h("div", { style: "margin-top:14px" }, recordPanel("activities", a.id, { project_id: S.project, activity_id: a.id, wbs_id: a.wbs_id })) : null);
  const btns = can("project", "edit") ? [{ label: "Save", cls: "primary", act: async () => { await run("master.save", { table: "activities", row: Object.assign(f.values(), { id: a && a.id, project_id: S.project }) }, "Saved"); await loadProjectLists(); done(); } },
    a ? { label: "+ DPR for this activity", act: () => { location.hash = "#/p/dpr?new=1&activity=" + a.id; } } : null,
    a ? { label: "Delete", cls: "warn", act: async () => { await run("master.delete", { table: "activities", id: a.id }, "Deleted"); await loadProjectLists(); done(); } } : null] : [];
  drawer(a ? "Activity " + (a.code || "") + " " + a.name : "New activity", body, btns);
}
function wbsForm(w, done) {
  const f = form([{ k: "code", label: "Code", req: true, ph: "2.2" }, { k: "name", label: "Name", req: true }, { k: "parent_id", label: "Parent", type: "select", options: () => wbsOpts().filter(([id]) => !w || id !== w.id) }, { k: "sort", label: "Order", type: "number" }], w || {});
  modal(w ? "Edit WBS" : "New WBS element", f, [{ label: "Save", cls: "primary", act: async () => { await run("master.save", { table: "wbs", row: Object.assign(f.values(), { id: w && w.id, project_id: S.project }) }, "Saved"); await loadProjectLists(); done(); } },
    w ? { label: "Delete", cls: "warn", act: async () => { await run("master.delete", { table: "wbs", id: w.id }, "Deleted"); await loadProjectLists(); done(); } } : null], { narrow: true });
}
PAGES["p/schedule"] = async (root) => {
  if (projectGuard(root, "Schedule & WBS")) return;
  await loadProjectLists();
  const d = await run("sched.tree", { project_id: S.project });
  const editable = can("project", "edit");
  root.append(pageHead("Schedule & WBS", "Actual quantities come from approved DPRs, so progress never needs a separate update.",
    editable ? h("button", { class: "btn primary", onclick: () => activityForm(null, go) }, "New activity") : null,
    editable ? h("button", { class: "btn", onclick: () => wbsForm(null, go) }, "New WBS element") : null,
    editable ? h("button", { class: "btn", onclick: () => pasteActivities() }, "Paste from Excel") : null),
    h("div", { class: "tiles" }, tile("Planned", fmtN(d.planned_pct, 1) + "%"), tile("Actual", fmtN(d.actual_pct, 1) + "%"), tile("SPI", fmtN(d.spi)), tile("Forecast finish", d.forecast_finish || "—")));
  const minD = d.activities.map((a) => a.planned_start).filter(Boolean).sort()[0];
  const maxD = d.activities.map((a) => a.forecast_finish || a.planned_finish).filter(Boolean).sort().pop();
  const span = minD && maxD ? (new Date(maxD) - new Date(minD)) / 864e5 + 1 : 0;
  const bar = (a) => {
    if (!span || !a.planned_start || !a.planned_finish) return "";
    const l = (new Date(a.planned_start) - new Date(minD)) / 864e5 / span * 100, w = ((new Date(a.planned_finish) - new Date(a.planned_start)) / 864e5 + 1) / span * 100;
    const t = (new Date(today()) - new Date(minD)) / 864e5 / span * 100;
    return h("div", { class: "gantt" }, h("i", { class: "g-plan" + (a.critical ? " crit" : ""), style: `left:${l}%;width:${w}%` }, h("i", { class: "g-done", style: `width:${Math.min(a.actual_pct, 100)}%` })), t >= 0 && t <= 100 ? h("i", { class: "g-today", style: `left:${t}%` }) : null);
  };
  const rows = [];
  const walk = (parent, depth) => d.wbs.filter((w) => (w.parent_id || null) === parent).forEach((w) => {
    rows.push({ w, depth });
    d.activities.filter((a) => a.wbs_id === w.id).forEach((a) => rows.push({ a, depth: depth + 1 }));
    walk(w.id, depth + 1);
  });
  walk(null, 0);
  d.activities.filter((a) => !byId(d.wbs, a.wbs_id)).forEach((a) => rows.push({ a, depth: 0 }));
  const tb = h("tbody", {}, rows.map((r) => r.w
    ? h("tr", { class: "wbsrow click", onclick: () => editable && wbsForm(r.w, go) }, h("td", { style: "padding-left:" + (8 + r.depth * 16) + "px" }, h("b", {}, r.w.code + " " + r.w.name)), h("td", { colspan: 3 }, progressBar(r.w.planned_pct, r.w.actual_pct)), h("td", { class: "num" }, fmtN(r.w.planned_pct, 1) + " / " + fmtN(r.w.actual_pct, 1) + "%"), h("td", { colspan: 6 }))
    : h("tr", { class: "click" + ((r.a.delay_days || 0) > 0 ? " flag" : ""), onclick: () => activityForm(byId(S.P.activities, r.a.id), go) },
      h("td", { style: "padding-left:" + (8 + r.depth * 16) + "px" }, (r.a.critical ? "◆ " : "") + (r.a.code || "") + " " + r.a.name, r.a.qa_hold ? h("span", { class: "stamp lv-critical", style: "margin-left:6px" }, "QA hold") : null),
      h("td", {}, r.a.planned_start || ""), h("td", {}, r.a.planned_finish || ""), h("td", { style: "min-width:200px" }, bar(r.a)),
      h("td", { class: "num" }, fmtN(r.a.planned_pct, 1) + " / " + fmtN(r.a.actual_pct, 1) + "%"),
      h("td", { class: "num" }, fmtN(r.a.actual_qty) + " / " + fmtN(r.a.planned_qty) + " " + (r.a.unit || "")),
      h("td", { class: "num" }, fmtN(r.a.avg_daily)), h("td", {}, r.a.forecast_finish || "—"),
      h("td", { class: "num" }, r.a.delay_days > 0 ? h("b", { class: "red" }, r.a.delay_days) : (r.a.delay_days ?? "—")),
      h("td", { class: "num" }, r.a.labour_prod == null ? "—" : fmtN(r.a.labour_prod, 3) + (r.a.labour_prod_var != null ? " (" + (r.a.labour_prod_var > 0 ? "+" : "") + r.a.labour_prod_var + "%)" : "")),
      h("td", { class: "num" }, r.a.unit_cost == null ? "—" : fmtMoney(r.a.unit_cost)))));
  root.append(rows.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["WBS / activity", "Start", "Finish", "Timeline", "Plan / actual %", "Done / planned", "Avg per day", "Forecast finish", "Delay (d)", "Output per man-hour (vs std)", "Actual unit cost"].map((x) => h("th", {}, x)))), tb))
    : h("div", { class: "panel" }, "Start by adding WBS elements (e.g. 1 Headworks, 2 HRT) and activities under them."));
};
function pasteActivities() {
  const cols = ["wbs_code", "code", "name", "unit", "planned_qty", "planned_start", "planned_finish", "boq_code", "location"];
  const ta = h("textarea", { style: "min-height:200px;font-family:monospace", placeholder: cols.join("\t") });
  const prev = h("div");
  let parsed = [];
  const check = () => {
    parsed = ta.value.split(/\r?\n/).map((l) => l.split("\t")).filter((r) => r.join("").trim()).filter((r, i) => !(i === 0 && r[0].toLowerCase() === "wbs_code")).map((r) => {
      const o = {}; cols.forEach((c, j) => { o[c] = (r[j] || "").trim(); });
      const w = S.P.wbs.find((x) => x.code === o.wbs_code);
      const b = S.L.boq.find((x) => String(x.project_id) === String(S.project) && x.code === o.boq_code);
      o.error = !w ? "WBS " + o.wbs_code + " not found" : !o.name ? "name missing" : (o.boq_code && !b) ? "BOQ " + o.boq_code + " not found" : "";
      o.wbs_id = w && w.id; o.boq_item_id = b && b.id;
      return o;
    });
    prev.innerHTML = "";
    prev.append(table([{ k: "wbs_code", label: "WBS" }, { k: "name", label: "Activity" }, { k: "planned_qty", label: "Qty" }, { k: "planned_start", label: "Start" }, { k: "planned_finish", label: "Finish" }, { label: "Check", v: (r) => r.error ? h("b", { class: "red" }, r.error) : "OK" }], parsed, { search: false, export: false, rowClass: (r) => r.error ? "bad" : "" }));
  };
  modal("Paste activities from Excel", h("div", {}, h("p", { class: "hint" }, "Columns: " + cols.join(" | ") + ". Dates as YYYY-MM-DD."), ta, h("button", { class: "btn", onclick: check }, "Preview & validate"), prev),
    [{ label: "Import valid rows", cls: "primary", act: async () => {
      check();
      let n = 0;
      for (const r of parsed.filter((x) => !x.error)) {
        await api("master.save", { table: "activities", row: { project_id: S.project, wbs_id: r.wbs_id, code: r.code, name: r.name, unit: r.unit, planned_qty: r.planned_qty, planned_start: r.planned_start || null, planned_finish: r.planned_finish || null, boq_item_id: r.boq_item_id, location: r.location } });
        n++;
      }
      toast(n + " activities imported", "ok"); await loadProjectLists(); go();
    } }]);
}

/* ── DPR wizard ── */
const DELAY_CATS = [["weather", "Weather"], ["access", "Access"], ["equipment_breakdown", "Equipment breakdown"], ["material_shortage", "Material shortage"], ["drawing", "Drawing / design"], ["consultant_instruction", "Consultant instruction"], ["employer_instruction", "Employer instruction"], ["labour_shortage", "Labour shortage"], ["geology", "Geological condition"], ["other", "Other"]];
async function dprWizard(dpr, ctx) {
  await loadProjectLists();
  ctx = ctx || {};
  const isNew = !dpr;
  let pre = null;
  if (isNew) {
    pre = await api("dpr.prefill", { project_id: S.project, date: today() });
    dpr = { status: "draft", date: today(), shift: "day", project_id: S.project, work: pre.work, labour: pre.labour, equipment: pre.equipment, delays: [], materials: pre.materials, photos: [], receipts: [], tests: [], vouchers: [] };
    if (ctx.activity) {
      const a = byId(S.P.activities, ctx.activity);
      if (a) dpr.work = [{ activity_id: a.id, boq_item_id: a.boq_item_id, location: a.location, planned_qty: "", actual_qty: "" }];
    }
  }
  const editable = dpr.status === "draft" && can("project", "edit");
  const hf = form([{ k: "date", label: "Date", type: "date", req: true }, { k: "shift", label: "Shift", type: "select", noBlank: true, options: [["day", "Day"], ["night", "Night"]] },
    { k: "weather", label: "Weather", type: "select", options: [["Clear", "Clear"], ["Cloudy", "Cloudy"], ["Rain", "Rain"], ["Heavy rain", "Heavy rain"], ["Snow", "Snow"]] },
    { k: "site_condition", label: "Site condition" }, { k: "remarks", label: "General remarks", wide: true }].map((x) => Object.assign(x, { readonly: !editable })), dpr);
  const eqOpts = () => S.L.equipment.filter((e) => e.active && String(e.project_id) === String(S.project)).map((e) => [e.id, e.code + " " + e.name]);
  const allEq = () => S.L.equipment.filter((e) => e.active).map((e) => [e.id, e.code + " " + e.name]);
  const work = lineEditor([
    { k: "activity_id", label: "Activity (WBS)", type: "select", options: () => actOpts(), w: 230, key: "activity", onChange: (r) => { const a = byId(S.P.activities, r.activity_id); if (a) { r.boq_item_id = a.boq_item_id; r.location = r.location || a.location; } }, rerender: true },
    { label: "WBS", show: (r) => { const a = byId(S.P.activities, r.activity_id); return a ? nmWbs(a.wbs_id) : ""; } },
    { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), w: 190, key: "boq" },
    { k: "location", label: "Location", w: 110 }, { k: "planned_qty", label: "Planned", type: "number", w: 70 }, { k: "actual_qty", label: "Actual", type: "number", w: 70 },
    { label: "Unit", show: (r) => { const a = byId(S.P.activities, r.activity_id); return (a && a.unit) || (byId(S.L.boq, r.boq_item_id) || {}).unit || ""; } },
    { label: "Var.", num: true, show: (r) => r.planned_qty && r.actual_qty !== "" && r.actual_qty != null ? fmtN(r.actual_qty - r.planned_qty) + " (" + Math.round(100 * r.actual_qty / r.planned_qty) + "%)" : "" },
    { k: "remarks", label: "Remarks", w: 120 }], dpr.work, { readonly: !editable });
  const labour = lineEditor([
    { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 200, key: "activity" },
    { k: "trade_id", label: "Trade", type: "select", options: tradeOpts, w: 160, key: "trade" },
    { k: "party_id", label: "Subcontractor (if any)", type: "select", options: () => opt.parties(["subcontractor"]), w: 150 },
    { k: "count", label: "No.", type: "number", w: 60 }, { k: "hours", label: "Hours", type: "number", w: 60 }, { k: "ot_hours", label: "OT h", type: "number", w: 60 },
    { label: "Man-hours", num: true, show: (r) => fmtN((Number(r.count) || 0) * ((Number(r.hours) || 0) + (Number(r.ot_hours) || 0))) },
    { k: "amount", label: "Cost", readonly: true, type: "number" }], dpr.labour, { readonly: !editable, blank: { hours: 8 } });
  const equipment = lineEditor([
    { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 190, key: "activity" },
    { k: "equipment_id", label: "Equipment", type: "select", options: () => (eqOpts().length ? eqOpts() : allEq()), w: 170, key: "equipment", onChange: (r) => { const e = byId(S.L.equipment, r.equipment_id); if (e && (r.meter_start === undefined || r.meter_start === "")) r.meter_start = e.meter; }, rerender: true },
    { label: "Type / meter now", show: (r) => { const e = byId(S.L.equipment, r.equipment_id); return e ? (e.category || "") + " · " + fmtN(e.meter) + " " + e.meter_type : ""; } },
    { k: "operator", label: "Operator", w: 100 }, { k: "meter_start", label: "Open meter", type: "number", w: 80 }, { k: "meter_end", label: "Close meter", type: "number", w: 80 },
    { k: "hours", label: "Work h", type: "number", w: 60 }, { k: "idle_hours", label: "Idle h", type: "number", w: 60 }, { k: "breakdown_hours", label: "Down h", type: "number", w: 60 },
    { k: "amount", label: "Cost", readonly: true, type: "number" }], dpr.equipment, { readonly: !editable });
  const delays = lineEditor([
    { k: "category", label: "Reason", type: "select", options: DELAY_CATS, w: 170 }, { k: "activity_id", label: "Affected activity", type: "select", options: () => actOpts(), w: 190, key: "activity" },
    { k: "hours", label: "Hours lost", type: "number", w: 70 }, { k: "description", label: "What happened", w: 260 },
    { k: "create_event", label: "Create event?", type: "select", noBlank: true, options: [["0", "No"], ["1", "Yes, record as contract event"]] },
    { label: "Event", show: (r) => r.event_id ? "#" + r.event_id : "" }], dpr.delays.map((x) => Object.assign({}, x, { create_event: String(x.create_event || 0) })), { readonly: !editable, blank: { create_event: "1" } });
  const matBox = h("div", {}, h("p", { class: "hint" }, "Taken automatically from store issues and receipts dated this day, so nothing is typed twice. Issue material from the store with the activity or BOQ item to charge it."),
    h("h4", {}, "Issued today"), table([{ k: "no", label: "Issue" }, { label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { label: "Unit", v: (r) => nm.unit(r.material_id) }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Cost", fmt: "money" }, { label: "For", v: (r) => r.boq_item_id ? nm.boq(r.boq_item_id) : r.equipment_id ? nm.eq(r.equipment_id) : r.target }], dpr.materials || [], { search: false, export: false, empty: "No material issued on this date." }),
    h("h4", {}, "Received today"), table([{ k: "no", label: "GRN" }, { label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "accepted_qty", label: "Qty", fmt: "qty" }], dpr.receipts || [], { search: false, export: false, empty: "No receipts on this date." }),
    can("inventory", "edit") ? h("button", { class: "btn small", onclick: () => { location.hash = "#/inv/issue?new=1"; } }, "Issue material now") : null);
  const photoBox = h("div");
  const loadPhotos = async () => {
    photoBox.innerHTML = "";
    if (!dpr.id) return photoBox.append(h("p", { class: "hint" }, "Save the draft first, then add photos."));
    const rows = await api("files.list", { dpr_id: dpr.id });
    photoBox.append(uploadButton({ entity: "dpr", entity_id: dpr.id, dpr_id: dpr.id, project_id: S.project, date: dpr.date, kind: "photo" }, loadPhotos, "Add photos", "image/*"), fileList(rows, loadPhotos));
  };
  loadPhotos();
  const qaBox = h("div", {}, table([{ k: "no", label: "Test" }, { k: "test_type", label: "Type" }, { label: "Activity", v: (r) => nmAct(r.activity_id) }, { k: "status", label: "Status", fmt: "status" }], dpr.tests || [], { search: false, export: false, empty: "Tests required by activities are created automatically when the DPR is approved." }),
    can("quality", "edit") ? h("button", { class: "btn small", onclick: () => { location.hash = "#/p/quality?new=1"; } }, "Request a test") : null);
  const review = h("div");
  const renderReview = () => {
    const w = work.lines(), l = labour.lines(), e = equipment.lines();
    review.innerHTML = "";
    review.append(kv([["Work lines", w.filter((x) => x.activity_id || x.boq_item_id).length], ["Man-hours", fmtN(l.reduce((a, x) => a + (Number(x.count) || 0) * ((Number(x.hours) || 0) + (Number(x.ot_hours) || 0)), 0))], ["Machine hours", fmtN(e.reduce((a, x) => a + (Number(x.meter_end) && Number(x.meter_start) ? x.meter_end - x.meter_start : Number(x.hours) || 0), 0))], ["Issues / delays", delays.lines().filter((x) => x.category).length], ["Material cost today", fmtMoney((dpr.materials || []).reduce((a, x) => a + x.amount, 0))]]),
      h("p", { class: "hint" }, "On approval BuildCore updates BOQ executed quantity, activity progress, labour and equipment cost (voucher), equipment logsheets (without duplicates), events for delays, and QA test requests."),
      dpr.vouchers && dpr.vouchers.length ? h("p", {}, "Posted vouchers: ", dpr.vouchers.map((v) => v.no + " (" + v.status + ")").join(", ")) : null,
      recordPanel("dpr", dpr.id, { project_id: S.project, dpr_id: dpr.id }));
  };
  const steps = tabs([["1 Basic", () => hf], ["2 Work", () => work], ["3 Labour", () => labour], ["4 Equipment", () => equipment], ["5 Materials", () => matBox], ["6 QA", () => qaBox], ["7 Issues & delays", () => delays], ["8 Photos", () => photoBox], ["9 Review", () => { renderReview(); return review; }]]);
  /* Site connections drop. Everything typed is kept on this computer until the server has it. */
  const draftKey = () => "bco_dpr_draft_" + S.project + "_" + (dpr.id || "new");
  const payload = () => ({ header: Object.assign(hf.values(), { id: dpr.id, project_id: S.project }),
    work: work.lines(), labour: labour.lines(), equipment: equipment.lines(), delays: delays.lines() });
  const keepLocal = () => { try { localStorage.setItem(draftKey(), JSON.stringify({ saved: new Date().toISOString(), data: payload() })); } catch (e) { /* full disk */ } };
  const dropLocal = () => { try { localStorage.removeItem(draftKey()); } catch (e) { /* ignore */ } };
  const save = async (quiet) => {
    keepLocal();
    let r;
    try {
      r = await run("dpr.save", payload(), quiet ? null : "Draft saved");
    } catch (e) {
      toast("Not saved to the server — your typing is kept on this computer and this window stays open. "
        + "Press Save draft again when the connection is back.", "err");
      throw e;
    }
    dropLocal();          // clear under the key it was written with, before the id changes
    dpr.id = r.id;
    dropLocal();
    return r;
  };
  const autoKeep = setInterval(keepLocal, 20000);
  let m;
  const reopenDpr = async () => { m.close(); if (PAGES._dprReload) PAGES._dprReload(); dprWizard(await api("dpr.get", { id: dpr.id })); };
  const step = (label, fn, o) => ({ label, cls: (o || {}).cls, act: async () => {
    if (o && o.ask) { const r = await ask(label, o.ask, { input: o.reason, required: !!o.reason }); if (r === null) return false; o.value = r; }
    if (editable) await save(true);
    await fn(o && o.value);
    await reopenDpr();
  } });
  const b = [];
  if (editable) {
    b.push({ label: "Save draft", act: async () => { await save(); await reopenDpr(); } });
    b.push(step("Submit", () => run("dpr.submit", { id: dpr.id }, "Submitted"), { cls: "primary" }));
  }
  if (dpr.status === "submitted" && can("project", "edit")) b.push(step("Mark checked", () => run("dpr.check", { id: dpr.id }, "Checked")));
  if (["submitted", "checked"].includes(dpr.status) && can("project", "approve")) b.push(step("Approve & post", () => run("dpr.approve", { id: dpr.id }, "Approved — progress and costs updated"), { cls: "primary" }));
  if (["submitted", "checked"].includes(dpr.status) && can("project", "edit")) b.push(step("Return for correction", (r) => run("dpr.return", { id: dpr.id, reason: r }, "Returned"), { ask: "Send back to the engineer?", reason: "What to correct" }));
  if (dpr.status === "approved" && can("admin", "edit")) b.push(step("Reopen (admin)", (r) => run("dpr.reopen", { id: dpr.id, reason: r }, "Reopened; postings reversed"), { ask: "Reopen this approved DPR? Its cost postings are reversed and re-posted on the next approval.", reason: "Reason" }));
  if (dpr.id) b.push({ label: "Print", act: () => { printDoc("Daily Progress Report " + (dpr.no || ""), [["Project", nm.project(S.project)], ["Date", dpr.date], ["Shift", dpr.shift], ["Weather", dpr.weather], ["Status", dpr.status]], [{ label: "Activity", v: (r) => nmAct(r.activity_id) }, { label: "BOQ", v: (r) => nm.boq(r.boq_item_id) }, { k: "location", label: "Location" }, { k: "planned_qty", label: "Planned", fmt: "qty" }, { k: "actual_qty", label: "Actual", fmt: "qty" }, { k: "remarks", label: "Remarks" }], dpr.work, [["Man-hours", fmtN(dpr.labour.reduce((a, x) => a + x.count * (x.hours + (x.ot_hours || 0)), 0))], ["Machine hours", fmtN(dpr.equipment.reduce((a, x) => a + (x.hours || 0), 0))]], [dpr.remarks, ...dpr.delays.map((x) => "Delay: " + x.category + " — " + (x.description || ""))].filter(Boolean).join("\n")); return false; } });
  m = modal("DPR " + (dpr.no || "(new)") + " · " + nm.pcode(S.project), h("div", {}, isNew && pre && pre.previous_dpr ? h("p", { class: "hint" }, "Planned work is taken from today's schedule; labour and equipment are copied from the previous DPR. Change what differs.") : null, steps), b,
    { head: stamp(dpr.status), onClose: () => clearInterval(autoKeep) });
  // A DPR that never reached the server (connection lost, power cut) is offered back.
  try {
    const held = JSON.parse(localStorage.getItem(draftKey()) || "null");
    if (held && editable) {
      toast("Unsent work from " + held.saved.slice(0, 16).replace("T", " ") + " was found on this computer.", "err");
      const put = () => {
        hf.set("date", held.data.header.date); hf.set("shift", held.data.header.shift);
        hf.set("weather", held.data.header.weather); hf.set("remarks", held.data.header.remarks);
        work.setLines(held.data.work || []); labour.setLines(held.data.labour || []);
        equipment.setLines(held.data.equipment || []); delays.setLines(held.data.delays || []);
      };
      put();
    }
  } catch (e) { /* nothing held */ }
}
PAGES["p/dpr"] = async (root, params) => {
  if (projectGuard(root, "Daily progress reports")) return;
  let v = { from: monthAgo(), to: today() };
  const holder = h("div");
  const load = async () => {
    const rows = await run("dpr.list", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    holder.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { k: "weather", label: "Weather" }, { k: "work_lines", label: "Work lines", fmt: "num" }, { k: "manhours", label: "Man-hours", fmt: "qty" }, { k: "machine_hours", label: "Machine h", fmt: "qty" }, { label: "By", v: (r) => nm.user(r.created_by) }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "dpr", onRow: async (r) => dprWizard(await api("dpr.get", { id: r.id })), empty: "No DPRs in this period." }));
  };
  PAGES._dprReload = load;
  root.append(pageHead("Daily progress reports", "Draft → Submitted → Checked → Approved (locked). One approved DPR updates progress, BOQ, costs, equipment logs, events and QA.",
    can("project", "edit") ? h("button", { class: "btn primary", onclick: () => dprWizard(null) }, "New DPR") : null),
    filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "status", label: "Status", type: "select", options: ["draft", "submitted", "checked", "approved"].map((x) => [x, x]), blank: "All" }], v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.id) dprWizard(await api("dpr.get", { id: params.id }));
  else if (params.new && can("project", "edit")) dprWizard(null, { activity: params.activity });
};

/* ── BOQ control ── */
const RA_KINDS = [["material", "Material"], ["labour", "Labour"], ["equipment", "Equipment"], ["overhead", "Overhead (per unit)"], ["overhead_pct", "Overhead % of direct"]];
function boqDrawer(b, done) {
  const editable = can("commercial", "edit");
  const f = form([{ k: "code", label: "Code", req: true }, { k: "description", label: "Description", wide: true, req: true }, { k: "unit", label: "Unit" }, { k: "qty", label: "Contract quantity", type: "number" }, { k: "rate", label: "Contract rate", type: "number" },
    { k: "wbs_id", label: "WBS", type: "select", options: wbsOpts }, { k: "location", label: "Location" }, { k: "revised_qty", label: "Revised quantity (from variations)", type: "number", readonly: true }, { k: "revised_rate", label: "Revised rate", type: "number", readonly: true }].map((x) => Object.assign(x, { readonly: x.readonly || !editable })),
    b ? { code: b.code, description: b.description, unit: b.unit, qty: b.contract_qty, rate: b.contract_rate, wbs_id: b.wbs_id, location: b.location, revised_qty: b.revised_qty, revised_rate: b.revised_rate } : {});
  const overview = () => h("div", {}, f, b ? h("div", { class: "tiles", style: "margin-top:12px" }, tile("Executed", fmtN(b.executed_qty) + " " + (b.unit || "")), tile("Measured", fmtN(b.measured_qty)), tile("Billed", fmtN(b.billed_qty)), tile("Certified", fmtN(b.certified_qty)), tile("Balance", fmtN(b.balance_qty)), tile("Progress", b.progress_pct + "%")) : null);
  const ra = async () => {
    const box = h("div");
    const load = async () => {
      const rows = await api("master.list", { table: "rate_analysis", boq_item_id: b.id });
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Budget cost per " + (b.unit || "unit") + ". It sets the budget, earned value and cost variance for this item."),
        table([{ label: "Type", v: (r) => (RA_KINDS.find((k) => k[0] === r.kind) || [0, r.kind])[1] }, { k: "description", label: "Resource" }, { k: "qty_per_unit", label: "Qty per unit / %", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { label: "Cost per unit", fmt: "money", v: (r) => r.kind === "overhead_pct" ? null : r.qty_per_unit * r.rate },
          { label: "", v: (r) => editable ? h("button", { class: "btn small warn", onclick: async () => { await run("master.delete", { table: "rate_analysis", id: r.id }); load(); } }, "Remove") : "" }], rows, { search: false, export: false, empty: "No rate analysis yet." }));
      if (editable) {
        const af = form([{ k: "kind", label: "Type", type: "select", noBlank: true, options: RA_KINDS }, { k: "description", label: "Resource (e.g. Cement, Miner, Excavator)" }, { k: "qty_per_unit", label: "Qty per unit (or %)", type: "number" }, { k: "rate", label: "Rate", type: "number" }]);
        box.append(h("div", { class: "panel" }, af, h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("master.save", { table: "rate_analysis", row: Object.assign(af.values(), { boq_item_id: b.id }) }, "Added"); load(); } }, "Add resource"))));
      }
    };
    await load();
    return box;
  };
  const cost = () => h("div", {}, kv([["Budget unit cost", b.unit_budget == null ? "not set" : fmtMoney(b.unit_budget)], ["Budget parts", Object.entries(b.budget_parts || {}).map(([k, v]) => k + " " + fmtMoney(v)).join(", ")], ["Budget at completion", fmtMoney(b.bac)], ["Planned value to date", fmtMoney(b.pv)], ["Earned value", fmtMoney(b.ev)], ["Actual cost", fmtMoney(b.ac)], ["Actual unit cost", fmtMoney(b.actual_unit_cost)], ["CPI / SPI", fmtN(b.cpi) + " / " + fmtN(b.spi)], ["Forecast cost (EAC)", fmtMoney(b.eac)], ["Forecast revenue", fmtMoney(b.forecast_revenue)], ["Forecast profit", fmtMoney(b.forecast_profit)]]),
    h("p", {}, h("a", { href: "#/acc/ledger" }, "Cost postings are in the ledger with this BOQ item")));
  const linked = () => table([{ label: "Activity", v: (a) => (a.code || "") + " " + a.name }, { label: "WBS", v: (a) => nmWbs(a.wbs_id) }, { k: "planned_qty", label: "Planned", fmt: "qty" }, { k: "actual_qty", label: "Actual", fmt: "qty" }], S.P.activities.filter((a) => b && a.boq_item_id === b.id), { search: false, export: false, empty: "No activities linked." });
  const body = b ? tabs([["Overview", overview], ["Rate analysis", ra], ["Cost & EVM", cost], ["Activities", linked], ["Documents & history", () => recordPanel("boq_items", b.id, { project_id: S.project, boq_item_id: b.id })]]) : overview();
  drawer(b ? b.code + " " + (b.description || "").slice(0, 60) : "New BOQ item", body, editable ? [{ label: "Save", cls: "primary", act: async () => {
    const v = f.values(); delete v.revised_qty; delete v.revised_rate;
    await run("master.save", { table: "boq_items", row: Object.assign(v, { id: b && b.id, project_id: S.project }) }, "Saved"); await reloadLookups(); done();
  } }, b ? { label: "Delete", cls: "warn", act: async () => { await run("master.delete", { table: "boq_items", id: b.id }, "Deleted"); await reloadLookups(); done(); } } : null] : []);
}
PAGES["p/boq"] = async (root, params) => {
  if (projectGuard(root, "BOQ")) return;
  await loadProjectLists();
  const rows = await run("boq.control", { project_id: S.project });
  if (params && params.open) {
    const hit = rows.find((x) => String(x.id) === String(params.open));
    if (hit) setTimeout(() => boqDrawer(hit), 50);
  }
  const editable = can("commercial", "edit");
  root.append(pageHead("BOQ — commercial master", "Contract, revised, executed (from DPR), measured, billed and certified quantities with budget and actual unit cost. Click an item for rate analysis, cost and documents.",
    editable ? h("button", { class: "btn primary", onclick: () => boqDrawer(null, go) }, "New BOQ item") : null,
    editable ? h("button", { class: "btn", onclick: () => pasteImport({ table: "boq_items", title: "BOQ items", byProject: true, importer: ["code", "description", "unit", "qty", "rate"] }, async () => { await reloadLookups(); go(); }) }, "Paste from Excel") : null),
    table([{ k: "code", label: "Code" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" }, { k: "contract_qty", label: "Contract qty", fmt: "qty" }, { k: "revised_qty", label: "Revised qty", fmt: "qty" }, { k: "revised_rate", label: "Rate", fmt: "money" }, { k: "revised_amount", label: "Amount", fmt: "money" },
      { k: "executed_qty", label: "Executed", fmt: "qty" }, { k: "measured_qty", label: "Measured", fmt: "qty" }, { k: "billed_qty", label: "Billed", fmt: "qty" }, { k: "certified_qty", label: "Certified", fmt: "qty" }, { k: "balance_qty", label: "Balance", fmt: "qty" },
      { label: "Progress", v: (r) => r.progress_pct + "%" }, { k: "unit_budget", label: "Budget/unit", fmt: "money" }, { k: "actual_unit_cost", label: "Actual/unit", fmt: "money" }, { k: "ac", label: "Actual cost", fmt: "money" }, { k: "earned_revenue", label: "Earned revenue", fmt: "money" }],
    rows, { name: "boq", totals: ["revised_amount", "ac", "earned_revenue"], rowClass: (r) => r.actual_unit_cost && r.unit_budget && r.actual_unit_cost > r.unit_budget ? "flag" : "", onRow: (r) => boqDrawer(r, go) }));
};

/* ── Cost & EVM ── */
PAGES["p/evm"] = async (root) => {
  if (projectGuard(root, "Cost & earned value")) return;
  const d = await run("evm.project", { project_id: S.project });
  root.append(pageHead("Cost control & earned value", "CV = EV − AC · SV = EV − PV · CPI = EV ÷ AC · SPI = EV ÷ PV · EAC = AC + ETC. Profit is forecast revenue − EAC, never contract value − cost so far."),
    h("div", { class: "tiles" }, tile("Budget", fmtMoney(d.bac)), tile("Planned value", fmtMoney(d.pv)), tile("Earned value", fmtMoney(d.ev)), tile("Actual cost", fmtMoney(d.ac)), tile("CV", fmtMoney(d.cv), { cls: d.cv < 0 ? "bad" : "" }), tile("SV", fmtMoney(d.sv), { cls: d.sv < 0 ? "warn" : "" }), tile("CPI / SPI", fmtN(d.cpi) + " / " + fmtN(d.spi)), tile("EAC", fmtMoney(d.eac)), tile("ETC", fmtMoney(d.etc)), tile("Forecast profit", fmtMoney(d.forecast_profit), { cls: d.forecast_profit < 0 ? "bad" : "" }),
      tile("Tender margin", d.tender_margin == null ? "—" : d.tender_margin + "%"), tile("Current margin", d.current_margin == null ? "—" : d.current_margin + "%"), tile("Forecast margin", d.forecast_margin == null ? "—" : d.forecast_margin + "%"), tile("Margin fade", d.margin_fade == null ? "—" : d.margin_fade + " pts", { cls: d.margin_fade > 2 ? "bad" : "" })),
    d.items_without_budget ? h("p", { class: "red" }, d.items_without_budget + " BOQ items have no rate analysis; add it in BOQ → item → Rate analysis.") : null,
    h("p", { class: "hint" }, "Costs not linked to a BOQ item or activity (" + fmtMoney(d.ac_unallocated) + ") are projected to completion in proportion to progress."),
    table([{ k: "code", label: "BOQ" }, { k: "description", label: "Description" }, { label: "Progress", v: (r) => r.progress_pct + "%" }, { k: "bac", label: "BAC", fmt: "money" }, { k: "pv", label: "PV", fmt: "money" }, { k: "ev", label: "EV", fmt: "money" }, { k: "ac", label: "AC", fmt: "money" }, { k: "cv", label: "CV", fmt: "money" }, { k: "sv", label: "SV", fmt: "money" }, { label: "CPI", v: (r) => fmtN(r.cpi) }, { label: "SPI", v: (r) => fmtN(r.spi) }, { k: "unit_budget", label: "Budget/unit", fmt: "money" }, { k: "actual_unit_cost", label: "Actual/unit", fmt: "money" }, { k: "eac", label: "EAC", fmt: "money" }, { k: "forecast_revenue", label: "Revenue", fmt: "money" }, { k: "forecast_profit", label: "Profit", fmt: "money" }],
      d.rows, { name: "evm", totals: ["bac", "pv", "ev", "ac", "cv", "sv", "eac", "forecast_revenue", "forecast_profit"], rowClass: (r) => (r.cpi != null && r.cpi < 0.95) || r.forecast_profit < 0 ? "bad" : "" }));
};

/* ── Measurement ── */
async function measEditor(m) {
  const isNew = !m;
  if (isNew) m = { status: "draft", date: today(), lines: await api("meas.prefill", { project_id: S.project }) };
  const editable = m.status === "draft" && can("commercial", "edit");
  const f = form([{ k: "date", label: "Date", type: "date" }, { k: "remarks", label: "Remarks", wide: true }].map((x) => Object.assign(x, { readonly: !editable })), m);
  const le = lineEditor([{ k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), w: 260, key: "boq" }, { label: "Unit", show: (r) => (byId(S.L.boq, r.boq_item_id) || {}).unit || "" }, { label: "Executed (DPR)", show: (r) => r.executed != null ? fmtN(r.executed) : "" }, { label: "Measured before", show: (r) => r.measured != null ? fmtN(r.measured) : "" }, { k: "qty", label: "Measured now", type: "number", w: 90 }, { k: "location", label: "Location / chainage", w: 140 }, { k: "remarks", label: "Remarks", w: 140 }], m.lines, { readonly: !editable });
  const ovr = h("label", { class: "f check" }, h("input", { type: "checkbox" }), "Allow more than executed quantity (approval rights)");
  const b = [];
  let md;
  const reopen = async (gone) => { md.close(); go(); if (!gone && m.id) measEditor(await api("meas.get", { id: m.id })); };
  const save = async () => { const r = await run("meas.save", { header: Object.assign(f.values(), { id: m.id, project_id: S.project }), lines: le.lines() }, "Saved"); m.id = r.id; };
  if (editable) {
    b.push({ label: "Save", act: async () => { await save(); await reopen(); } });
    if (can("commercial", "approve")) b.push({ label: "Verify (QS)", cls: "primary", act: async () => { await save(); await run("meas.verify", { id: m.id, override: ovr.firstChild.checked }, "Verified — available for IPC"); await reopen(true); } });
    if (m.id) b.push({ label: "Delete", cls: "warn", act: async () => { await run("meas.delete", { id: m.id }, "Deleted"); await reopen(true); } });
  }
  md = modal("Measurement " + (m.no || "(new)"), h("div", {}, isNew ? h("p", { class: "hint" }, "Pre-filled with executed quantities (from approved DPRs) not yet measured.") : null, f, h("br"), le, editable ? ovr : null), b, { head: stamp(m.status) });
}
PAGES["p/measure"] = async (root, params) => {
  if (projectGuard(root, "Measurements")) return;
  const rows = await run("meas.list", { project_id: S.project });
  root.append(pageHead("Measurement sheets", "QS verifies quantities from approved progress. Only verified measurements can be billed.", can("commercial", "edit") ? h("button", { class: "btn primary", onclick: () => measEditor(null) }, "New measurement") : null),
    table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "value", label: "Value", fmt: "money" }, { k: "remarks", label: "Remarks" }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "measurements", onRow: async (r) => measEditor(await api("meas.get", { id: r.id })) }));
  if (params.new && can("commercial", "edit")) measEditor(null);
};

/* ── IPC ── */
async function ipcEditor(i) {
  const isNew = !i;
  if (isNew) {
    const client = S.L.parties.find((p) => p.kind === "client");
    i = { status: "draft", date: today(), client_id: client && client.id, vat_rate: S.L.settings.vat_rate, retention_pct: 5, tds_pct: 1.5, advance_recovery: 0, lines: await api("ipc.prefill", { project_id: S.project }) };
  }
  const editable = i.status === "draft" && can("commercial", "edit");
  const f = form([{ k: "client_id", label: "Client", type: "select", options: () => opt.parties(["client"]), req: true }, { k: "date", label: "IPC date", type: "date" }, { k: "period_to", label: "Work up to", type: "date" }, { k: "client_ref", label: "Client / consultant ref." },
    { k: "retention_pct", label: "Retention %", type: "number" }, { k: "vat_rate", label: "VAT %", type: "number" }, { k: "tds_pct", label: "TDS deducted by client %", type: "number" }, { k: "advance_recovery", label: "Advance recovery (amount)", type: "number" }, { k: "remarks", label: "Remarks", wide: true }].map((x) => Object.assign(x, { readonly: !editable })), i);
  const le = lineEditor([{ k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), w: 250, key: "boq" }, { label: "Unit", show: (r) => (byId(S.L.boq, r.boq_item_id) || {}).unit || "" }, { k: "prev_qty", label: "Previous", readonly: true, type: "number" }, { k: "qty", label: "This IPC", type: "number", w: 90 }, { label: "Cumulative", num: true, show: (r) => fmtN((Number(r.prev_qty) || 0) + (Number(r.qty) || 0)) }, { k: "rate", label: "Rate", readonly: true, type: "number" }, { label: "Amount", num: true, show: (r) => fmtMoney((Number(r.qty) || 0) * (Number(r.rate) || 0)) }], i.lines, { readonly: !editable });
  const tot = h("div", { class: "panel" });
  const calc = () => {
    const v = f.values(), g = le.lines().reduce((a, l) => a + (Number(l.qty) || 0) * (Number(l.rate) || 0), 0);
    const ret = g * v.retention_pct / 100, vat = g * v.vat_rate / 100, tds = g * v.tds_pct / 100, adv = Number(v.advance_recovery) || 0;
    tot.innerHTML = "";
    tot.append(kv([["Gross (this IPC)", fmtMoney(g)], ["VAT", fmtMoney(vat)], ["Less retention", fmtMoney(ret)], ["Less TDS", fmtMoney(tds)], ["Less advance recovery", fmtMoney(adv)], ["Net payable", h("b", {}, fmtMoney(g + vat - ret - tds - adv))], i.receivable != null ? ["Received / outstanding", fmtMoney(i.paid) + " / " + fmtMoney(i.receivable)] : null, i.invoice_no ? ["Accounts invoice", i.invoice_no] : null]));
  };
  f.addEventListener("change", calc);
  le.addEventListener("change", () => setTimeout(calc));
  calc();
  const ovr = h("label", { class: "f check" }, h("input", { type: "checkbox" }), "Bill beyond verified measurement (needs justification)");
  const save = async () => { const r = await run("ipc.save", { header: Object.assign(f.values(), { id: i.id, project_id: S.project }), lines: le.lines() }, "Saved"); i.id = r.id; };
  let m;
  const reopen = async (gone) => { m.close(); go(); if (!gone && i.id) ipcEditor(await api("ipc.get", { id: i.id })); };
  const b = [];
  if (editable) {
    b.push({ label: "Save", act: async () => { await save(); await reopen(); } });
    b.push({ label: "Submit to consultant", cls: "primary", act: async () => { await save(); await run("ipc.submit", { id: i.id, override: ovr.firstChild.checked }, "Submitted — ready for certification"); await reopen(); } });
    if (i.id) b.push({ label: "Delete", cls: "warn", act: async () => { await run("ipc.delete", { id: i.id }, "Deleted"); await reopen(true); } });
  }
  if (i.status === "submitted" && can("commercial", "approve")) {
    b.push({ label: "Record certification", cls: "primary", act: () => {
      const cf = form([{ k: "date", label: "Certified on", type: "date", default: today() }, { k: "client_ref", label: "Certificate no.", default: i.client_ref }, { k: "advance_recovery", label: "Advance recovery", type: "number", default: i.advance_recovery }]);
      const cl = lineEditor([{ label: "BOQ", show: (r) => r.code + " " + (r.description || "").slice(0, 40) }, { k: "qty", label: "Claimed", readonly: true, type: "number" }, { k: "cert", label: "Certified", type: "number" }], i.lines.map((l) => Object.assign({}, l, { cert: l.qty })), { fixed: true });
      modal("Certify " + i.no, h("div", {}, h("p", { class: "hint" }, "Certification posts the invoice: receivable, revenue, VAT, TDS, retention and advance recovery."), cf, h("br"), cl), [{ label: "Certify & post", cls: "primary", act: async () => {
        const cert = {}; cl.lines().forEach((l) => { cert[l.id] = l.cert; });
        await run("ipc.certify", Object.assign(cf.values(), { id: i.id, certified: cert }), (r) => "Certified: net " + fmtMoney(r.net)); await reopen();
      } }], { narrow: true });
      return false;
    } });
    b.push({ label: "Return to draft", act: async () => { await run("ipc.return", { id: i.id }, "Returned"); await reopen(); } });
  }
  if (i.status === "certified") {
    if (can("accounts", "edit") && i.receivable > 0.004) b.push({ label: "Receive payment", cls: "primary", act: () => { paymentDialog("receive", i.client_id, S.project); return false; } });
    if (can("accounts", "approve")) b.push({ label: "Reverse certification", cls: "warn", act: async () => { const r = await ask("Reverse certification", "Cancel the posted invoice and return this IPC to submitted?", { input: "Reason", required: true, danger: true }); if (r === null) return false; await run("ipc.uncertify", { id: i.id, reason: r }, "Reversed"); await reopen(); } });
  }
  if (i.id) b.push({ label: "Print statement", act: () => { printDoc("Interim Payment Certificate " + i.no, [["Project", nm.project(S.project)], ["Client", nm.party(i.client_id)], ["Date", i.date], ["Work up to", i.period_to], ["Reference", i.client_ref], ["Status", i.status]], [{ label: "BOQ", v: (r) => (r.code || "") + " " + (r.description || "") }, { k: "unit", label: "Unit" }, { k: "revised_qty", label: "Contract qty", fmt: "qty" }, { k: "prev_qty", label: "Previous", fmt: "qty" }, { k: "qty", label: "Current", fmt: "qty" }, { k: "cum_qty", label: "Cumulative", fmt: "qty" }, { label: "Balance", fmt: "qty", v: (r) => r.revised_qty - r.cum_qty }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Current amount", fmt: "money" }, { k: "cum_amount", label: "Cumulative amount", fmt: "money" }], i.lines || [], [["Gross", fmtMoney(i.gross)], ["Net payable", fmtMoney(i.net)]], i.remarks); return false; } });
  m = modal("IPC " + (i.no || "(new)"), h("div", {}, isNew ? h("p", { class: "hint" }, "Pre-filled from verified measurements not yet billed. Previous quantities come from earlier IPCs.") : null, f, h("br"), le, editable ? ovr : null, tot, i.id ? recordPanel("ipc", i.id, { project_id: S.project }) : null), b, { head: stamp(i.status) });
}
PAGES["p/ipc"] = async (root, params) => {
  if (projectGuard(root, "IPC")) return;
  const rows = await run("ipc.list", { project_id: S.project });
  root.append(pageHead("Interim payment certificates", "Measurement → IPC → consultant certification → accounts → payment.", can("commercial", "edit") ? h("button", { class: "btn primary", onclick: () => ipcEditor(null) }, "New IPC") : null),
    table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "period_to", label: "Up to" }, { label: "Client", v: (r) => nm.party(r.client_id) }, { k: "client_ref", label: "Ref" }, { k: "gross", label: "Gross", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "paid", label: "Received", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "ipc", totals: ["gross", "net", "paid"], onRow: async (r) => ipcEditor(await api("ipc.get", { id: r.id })) }));
  if (params.id) ipcEditor(await api("ipc.get", { id: params.id }));
};

/* ── generic register pages (events, variations, quality, tasks) ── */
function registerPage(o) {
  return async (root, params) => {
    if (o.needsProject !== false && projectGuard(root, o.title)) return;
    await loadProjectLists();
    let v = {};
    const holder = h("div");
    const canEdit = () => can(o.module, "edit") || (o.alsoProject && can("project", "edit"));
    const load = async () => {
      const rows = await run("reg.list", Object.assign({ table: o.table, project_id: S.project || null }, v));
      holder.innerHTML = "";
      holder.append(table(o.cols, rows, { name: o.table, onRow: (r) => edit(r), rowClass: o.rowClass }));
    };
    const edit = (r) => {
      const locked = r && o.locked && o.locked.includes(r.status);
      const f = form(o.fields().map((x) => Object.assign({}, x, { readonly: x.readonly || locked || !canEdit() })), r || (o.defaults ? o.defaults(params) : {}));
      const btns = [];
      let dr;
      /* after any status change, reopen the record so the next step's buttons appear */
      const refresh = async (gone) => {
        await load();
        dr.close();
        if (!gone && r) {
          const fresh = (await api("reg.list", { table: o.table, project_id: r.project_id || S.project || null })).find((x) => x.id === r.id);
          if (fresh) edit(fresh);
        }
      };
      if (!locked && canEdit()) btns.push({ label: "Save", cls: "primary", act: async () => { await run("reg.save", { table: o.table, row: Object.assign(f.values(), { id: r && r.id, project_id: (r && r.project_id) || S.project }) }, "Saved"); await refresh(!r); } });
      (o.actions ? o.actions(r, refresh) : []).forEach((b) => b && btns.push(b));
      if (r && can(o.module, "approve")) btns.push({ label: "Delete", cls: "warn", act: async () => { await run("reg.delete", { table: o.table, id: r.id }, "Deleted"); await refresh(true); } });
      dr = drawer((r ? (r.no || "") + " " : "New ") + o.single, h("div", {}, f, r ? h("div", { style: "margin-top:14px" }, recordPanel(o.table, r.id, { project_id: r.project_id, activity_id: r.activity_id })) : null), btns, { head: r && r.status ? stamp(r.status) : null });
    };
    root.append(pageHead(o.title, o.sub, canEdit() ? h("button", { class: "btn primary", onclick: () => edit(null) }, "New " + o.single) : null),
      o.filters ? filterBar(o.filters, v, (x) => { v = x; load(); }) : null, holder);
    await load();
    if (params.new && canEdit()) edit(null);
  };
}
const EVENT_TYPES = [["delay", "Delay"], ["instruction", "Instruction"], ["notice", "Notice"], ["claim", "Claim"], ["eot", "Extension of time"], ["variation", "Variation request"], ["other", "Other"]];
const EVENT_STATUS = [["open", "Open"], ["notified", "Notice sent"], ["claimed", "Claim submitted"], ["agreed", "Agreed"], ["rejected", "Rejected"], ["closed", "Closed"]];
PAGES["p/events"] = registerPage({ table: "events", module: "commercial", alsoProject: true, title: "Events, notices & claims", single: "event",
  sub: "Contract events with clause, notice deadline, time and cost impact. Delays from DPRs arrive here automatically, and deadlines appear in the Action Centre.",
  filters: [{ k: "status", label: "Status", type: "select", options: EVENT_STATUS, blank: "All" }, { k: "type", label: "Type", type: "select", options: EVENT_TYPES, blank: "All" }],
  cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "type", label: "Type" }, { k: "title", label: "Title" }, { label: "Activity", v: (r) => nmAct(r.activity_id) }, { k: "clause", label: "Clause" }, { k: "notice_deadline", label: "Notice by" }, { k: "delay_days", label: "Delay d", fmt: "qty" }, { k: "cost_impact", label: "Cost impact", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
  rowClass: (r) => r.notice_deadline && r.notice_deadline <= today() && r.status === "open" ? "bad" : "",
  defaults: () => ({ date: today(), type: "delay", status: "open" }),
  fields: () => [{ k: "date", label: "Date", type: "date" }, { k: "type", label: "Type", type: "select", noBlank: true, options: EVENT_TYPES }, { k: "status", label: "Status", type: "select", noBlank: true, options: EVENT_STATUS }, { k: "title", label: "Title", req: true, wide: true }, { k: "description", label: "What happened", type: "textarea", wide: true },
    { k: "wbs_id", label: "WBS", type: "select", options: wbsOpts }, { k: "activity_id", label: "Activity", type: "select", options: () => actOpts() }, { k: "responsible_party", label: "Responsible party" }, { k: "clause", label: "Contract clause" }, { k: "notice_deadline", label: "Notice deadline", type: "date" }, { k: "delay_days", label: "Delay days", type: "number" }, { k: "cost_impact", label: "Cost impact", type: "number" }, { k: "mitigation", label: "Mitigation", type: "textarea", wide: true }] });
PAGES["p/variations"] = registerPage({ table: "variations", module: "commercial", title: "Variations", single: "variation",
  sub: "Identified → submitted → approved. Approval updates the revised BOQ quantity and rate (or creates a new BOQ item).",
  cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "title", label: "Title" }, { label: "BOQ", v: (r) => r.boq_item_id ? nm.boq(r.boq_item_id) : "New: " + (r.new_code || "") }, { k: "var_qty", label: "Qty change", fmt: "qty" }, { k: "new_rate", label: "New rate", fmt: "money" }, { k: "time_impact_days", label: "Time (d)", fmt: "qty" }, { k: "status", label: "Status", fmt: "status" }],
  locked: ["approved", "rejected"], defaults: () => ({ date: today() }),
  fields: () => [{ k: "date", label: "Date", type: "date" }, { k: "title", label: "Title", req: true, wide: true }, { k: "boq_item_id", label: "Existing BOQ item (leave blank for a new item)", type: "select", options: () => opt.boq(S.project), search: true }, { k: "var_qty", label: "Quantity change (+/−)", type: "number" }, { k: "new_rate", label: "New rate (blank = unchanged)", type: "number" },
    { k: "new_code", label: "New item code" }, { k: "new_description", label: "New item description" }, { k: "new_unit", label: "New item unit" }, { k: "time_impact_days", label: "Time impact (days)", type: "number" }, { k: "instruction_ref", label: "Instruction reference" }, { k: "reason", label: "Reason / justification", type: "textarea", wide: true }],
  actions: (r, load) => r ? [r.status === "identified" && can("commercial", "edit") ? { label: "Submit", act: async () => { await run("var.submit", { id: r.id }, "Submitted"); await load(); } } : null,
    r.status === "submitted" && can("commercial", "approve") ? { label: "Approve", cls: "primary", act: async () => { await run("var.decide", { id: r.id, decision: "approved" }, "Approved — BOQ revised"); await reloadLookups(); load(); } } : null,
    r.status === "submitted" && can("commercial", "approve") ? { label: "Reject", cls: "warn", act: async () => { await run("var.decide", { id: r.id, decision: "rejected" }, "Rejected"); load(); } } : null] : [] });
PAGES["p/tasks"] = registerPage({ table: "tasks", module: "project", title: "Tasks", single: "task",
  sub: "Created by people or automatically (breakdowns, failed tests, contract events, critical alerts).",
  filters: [{ k: "status", label: "Status", type: "select", options: [["open", "Open"], ["done", "Done"]], blank: "All" }],
  cols: [{ k: "title", label: "Task" }, { k: "due_date", label: "Due" }, { k: "priority", label: "Priority" }, { label: "Assigned", v: (r) => nm.user(r.assigned_to) || "Anyone" }, { k: "source_type", label: "Source" }, { k: "status", label: "Status", fmt: "status" }],
  rowClass: (r) => r.status === "open" && r.due_date && r.due_date < today() ? "bad" : "",
  defaults: () => ({ due_date: today(), priority: "normal" }),
  fields: () => [{ k: "title", label: "Task", req: true, wide: true }, { k: "description", label: "Details", type: "textarea", wide: true }, { k: "due_date", label: "Due", type: "date" }, { k: "priority", label: "Priority", type: "select", noBlank: true, options: [["high", "High"], ["normal", "Normal"], ["low", "Low"]] }, { k: "assigned_to", label: "Assign to", type: "select", options: () => S.L.users.map((u) => [u.id, u.name]) }],
  actions: (r, load) => r ? [{ label: r.status === "done" ? "Reopen" : "Mark done", cls: "primary", act: async () => { await run("task.status", { id: r.id, status: r.status === "done" ? "open" : "done" }, "Updated"); load(); } }] : [] });

PAGES["p/quality"] = async (root, params) => {
  if (projectGuard(root, "Quality")) return;
  await loadProjectLists();
  const view = h("div");
  root.append(pageHead("Quality — tests & NCRs", "Activities with a required test get a test request when their DPR is approved. Work stays on QA hold until tests pass; a failed test raises an NCR and a corrective task."), view);
  const testsPage = registerPage({ table: "qa_tests", module: "quality", alsoProject: true, title: "Tests", single: "test request",
    cols: [{ k: "no", label: "No." }, { k: "test_type", label: "Test" }, { label: "Activity", v: (r) => nmAct(r.activity_id) }, { k: "location", label: "Location" }, { k: "sample_ref", label: "Sample" }, { k: "sampled_date", label: "Sampled" }, { k: "result_value", label: "Result" }, { k: "status", label: "Status", fmt: "status" }],
    locked: ["passed", "failed"], rowClass: (r) => r.status === "failed" ? "bad" : "",
    filters: [{ k: "status", label: "Status", type: "select", options: [["pending", "Pending"], ["passed", "Passed"], ["failed", "Failed"]], blank: "All" }],
    defaults: () => ({ sampled_date: today() }),
    fields: () => [{ k: "test_type", label: "Test type", req: true }, { k: "activity_id", label: "Activity", type: "select", options: () => actOpts() }, { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), search: true }, { k: "material_id", label: "Material", type: "select", options: opt.materials }, { k: "location", label: "Location" }, { k: "sample_ref", label: "Sample reference" }, { k: "sampled_date", label: "Sampled on", type: "date" }, { k: "criteria", label: "Acceptance criteria", wide: true }, { k: "remarks", label: "Remarks", wide: true }],
    actions: (r, load) => r && r.status === "pending" && can("quality", "edit") ? [{ label: "Record result", cls: "primary", act: () => {
      const f = form([{ k: "result_value", label: "Result", req: true }, { k: "status", label: "Outcome", type: "select", noBlank: true, options: [["passed", "Passed"], ["failed", "Failed"]] }, { k: "date", label: "Result date", type: "date", default: today() }]);
      modal("Result for " + r.no, f, [{ label: "Save result", cls: "primary", act: async () => { await run("qa.result", Object.assign(f.values(), { id: r.id }), "Result saved"); load(); } }], { narrow: true });
      return false;
    } }] : [] });
  const ncrPage = registerPage({ table: "ncrs", module: "quality", title: "NCRs", single: "NCR",
    cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "title", label: "Title" }, { label: "Activity", v: (r) => nmAct(r.activity_id) }, { k: "due_date", label: "Due" }, { k: "status", label: "Status", fmt: "status" }],
    locked: ["closed"], defaults: () => ({ date: today() }),
    fields: () => [{ k: "date", label: "Date", type: "date" }, { k: "title", label: "Title", req: true, wide: true }, { k: "description", label: "Non-conformance", type: "textarea", wide: true }, { k: "activity_id", label: "Activity", type: "select", options: () => actOpts() }, { k: "due_date", label: "Close by", type: "date" }, { k: "corrective_action", label: "Corrective action", type: "textarea", wide: true }],
    actions: (r, load) => r && r.status === "open" && can("quality", "approve") ? [{ label: "Close NCR", cls: "primary", act: async () => { const ca = await ask("Close NCR", "Describe the corrective action taken.", { input: "Corrective action", required: !r.corrective_action }); if (ca === null) return false; await run("ncr.close", { id: r.id, corrective_action: ca }, "Closed"); load(); } }] : [] });
  view.append(tabs([["Tests", async () => { const b = h("div"); await testsPage(b, params); const t = b.querySelector("h1"); if (t) t.parentElement.parentElement.remove(); return b; }],
    ["NCRs", async () => { const b = h("div"); await ncrPage(b, {}); const t = b.querySelector("h1"); if (t) t.parentElement.parentElement.remove(); return b; }]]));
};

/* ── Documents & photo progress ── */
PAGES["p/docs"] = async (root, params) => {
  if (projectGuard(root, "Documents & photos")) return;
  await loadProjectLists();
  let v = { kind: params.photo ? "photo" : "" };
  const holder = h("div");
  const meta = form([{ k: "kind", label: "Upload as", type: "select", noBlank: true, options: [["photo", "Progress photo"], ["document", "Document / drawing"]], default: params.photo ? "photo" : "document" }, { k: "wbs_id", label: "WBS", type: "select", options: wbsOpts }, { k: "activity_id", label: "Activity", type: "select", options: () => actOpts() }, { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), search: true }, { k: "location", label: "Location / chainage" }, { k: "stage", label: "Stage", type: "select", options: [["before", "Before"], ["progress", "Progress"], ["after", "After"]] }, { k: "date", label: "Date", type: "date", default: today() }, { k: "caption", label: "Description", wide: true }]);
  const load = async () => {
    const rows = await run("files.list", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    const photos = rows.filter((r) => r.kind === "photo");
    if (photos.length && (v.kind === "photo" || !v.kind)) {
      const groups = {};
      photos.forEach((p) => { const k = p.location || nmAct(p.activity_id) || "General"; (groups[k] = groups[k] || []).push(p); });
      holder.append(h("h2", {}, "Photo progress history"), ...Object.entries(groups).map(([k, list]) => h("div", { class: "panel" }, h("h3", {}, k), fileList(list.sort((a, b) => (a.date || "").localeCompare(b.date || "")), load))));
    }
    const docs = rows.filter((r) => r.kind !== "photo");
    if (docs.length && v.kind !== "photo") holder.append(h("h2", {}, "Documents"), table([{ label: "File", v: (f) => h("a", { href: fileUrl(f.id), target: "_blank" }, f.filename) }, { k: "date", label: "Date" }, { k: "caption", label: "Description" }, { label: "Linked to", v: (f) => [f.entity ? f.entity + " #" + f.entity_id : "", nmAct(f.activity_id), f.boq_item_id ? nm.boq(f.boq_item_id) : ""].filter(Boolean).join(" · ") }, { label: "By", v: (f) => nm.user(f.user_id) }], docs, { name: "documents" }));
    if (!rows.length) holder.append(h("p", { class: "muted" }, "No files yet."));
  };
  const inp = h("input", { type: "file", multiple: true, style: "display:none", onchange: async () => { const m = meta.values(); m.project_id = S.project; await uploadFiles([...inp.files], m); inp.value = ""; load(); } });
  root.append(pageHead("Documents & photo progress", "Every file is linked to the project and, where chosen, the WBS, activity, BOQ item and location."),
    h("div", { class: "panel" }, h("h2", {}, "Upload"), meta, h("div", { class: "actions" }, inp, h("button", { class: "btn primary", onclick: () => inp.click() }, "Choose files…"))),
    filterBar([{ k: "kind", label: "Show", type: "select", options: [["photo", "Photos"], ["document", "Documents"]], blank: "All" }, { k: "activity_id", label: "Activity", type: "select", options: () => actOpts() }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], v, (x) => { v = x; load(); }), holder);
  load();
};

/* ── resources: trades, equipment rate cards, material forecast ── */
PAGES["m/trades"] = masterPage({ table: "trades", module: "project", title: "Labour trades & rates", single: "trade",
  sub: "Hourly rates used to cost DPR labour. Overtime is costed at 1.5×. Leave project blank for a company-wide rate.",
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Trade" }, { k: "rate_hour", label: "Rate / hour", fmt: "money" }, { label: "Project", v: (r) => nm.pcode(r.project_id) || "All" }, { k: "active", label: "Active", fmt: "yes" }],
  fields: [{ k: "code", label: "Code" }, { k: "name", label: "Trade", req: true }, { k: "rate_hour", label: "Rate per hour", type: "number", req: true }, { k: "project_id", label: "Only for project", type: "select", options: opt.projects }, { k: "active", label: "Active", type: "check" }] });
PAGES["eq/rates"] = masterPage({ table: "equipment_rates", module: "equipment", title: "Equipment rate cards", single: "rate card",
  sub: "Operating cost per hour = ownership + fuel + operator + maintenance + insurance, plus overhead %. The card with the latest effective date on or before the work date is used.",
  cols: [{ label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "effective_from", label: "From" }, { k: "ownership_hr", label: "Ownership", fmt: "money" }, { k: "fuel_hr", label: "Fuel", fmt: "money" }, { k: "operator_hr", label: "Operator", fmt: "money" }, { k: "maintenance_hr", label: "Maintenance", fmt: "money" }, { k: "insurance_hr", label: "Insurance", fmt: "money" }, { k: "overhead_pct", label: "Overhead %", fmt: "qty" }, { label: "Rate / hour", fmt: "money", v: (r) => (r.ownership_hr + r.fuel_hr + r.operator_hr + r.maintenance_hr + r.insurance_hr) * (1 + r.overhead_pct / 100) }],
  fields: [{ k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, req: true }, { k: "effective_from", label: "Effective from", type: "date", req: true }, { k: "ownership_hr", label: "Ownership & depreciation / h", type: "number" }, { k: "fuel_hr", label: "Fuel & lubricant / h", type: "number" }, { k: "operator_hr", label: "Operator / h", type: "number" }, { k: "maintenance_hr", label: "Maintenance & repair / h", type: "number" }, { k: "insurance_hr", label: "Insurance & interest / h", type: "number" }, { k: "overhead_pct", label: "Overhead %", type: "number" }, { k: "remarks", label: "Basis / remarks", wide: true }] });
PAGES["inv/risk"] = async (root) => {
  if (projectGuard(root, "Material forecast")) return;
  const rows = await run("stock.risk", { project_id: S.project });
  root.append(pageHead("Material forecast & shortage risk", "Average use over the last 30 days against stock and lead time (set lead time on the material)."),
    table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "available", label: "Available", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "avg_daily", label: "Avg use / day", fmt: "qty" }, { label: "Days of stock", v: (r) => r.days_left ?? "—" }, { k: "lead_days", label: "Lead time (d)" }, { k: "pending_po", label: "On order", fmt: "qty" }, { k: "last_rate", label: "Last rate", fmt: "money" }, { label: "Risk", v: (r) => r.risk ? h("b", { class: "red" }, "SHORTAGE RISK") : "" }, { k: "why", label: "Why" }],
      rows, { name: "material_forecast", rowClass: (r) => r.risk ? "bad" : "" }));
};
