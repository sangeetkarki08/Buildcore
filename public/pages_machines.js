/* BuildCore 2.59 — Machines: Equipment › Machine page, Equipment › Machine & manpower plan. */
(function () {
"use strict";
if (window.__bco259) return; window.__bco259 = true;
const M = (v) => (v == null ? "—" : fmtMoney(v));
const N = (v) => (v == null ? "—" : String(Math.round(Number(v) * 100) / 100));
const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
const empty = (t) => h("p", { class: "muted" }, t);
const projects = () => ((S.L && S.L.projects) || []).filter((p) => !p.kind || p.kind === "project");
let PID = null;
const pidNow = () => PID || S.project || (projects()[0] || {}).id;
const projSel = (onch) => h("select", { onchange: (e) => { PID = Number(e.target.value); onch(); } },
  projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(pidNow()) }, p.code + " · " + p.name)));
const wk = (d) => d.slice(5);

/* ═════════════ Equipment › Machine page ═════════════ */
let EID = null;
PAGES["mc/machine"] = async (root, params) => {
  if (params && params.id) EID = Number(params.id);
  const list = (await api("mc.machines", {})).rows;
  if (!list.length) { root.append(pageHead("Machine page", ""), empty("No machines in the register.")); return; }
  if (!EID || !list.find((x) => x.id === EID)) EID = list[0].id;
  const to0 = new Date().toISOString().slice(0, 10);
  let frm = null, to = null;
  const head = h("div");
  const body = h("div");
  root.append(pageHead("Machine page", "Everything about one machine: hours, cost per hour, what it charged the projects, depreciation and loan, repairs, fuel against its norm, papers and where it has worked."), head, body);
  const load = async () => {
    const d = await api("mc.machine", { equipment_id: EID, from: frm, to: to });
    frm = d.from; to = d.to;
    const m = d.machine, k = d.cost;
    const fIn = h("input", { type: "date", value: frm, onchange: (e) => { frm = e.target.value; load(); } });
    const tIn = h("input", { type: "date", value: to, onchange: (e) => { to = e.target.value; load(); } });
    head.replaceChildren(h("div", { class: "bar" },
      lbl("Machine", h("select", { onchange: (e) => { EID = Number(e.target.value); load(); } }, list.map((x) => h("option", { value: x.id, selected: x.id === EID }, x.code + " · " + x.name + (x.project ? " (" + x.project + ")" : ""))))),
      lbl("From", fIn), lbl("To", tIn)));
    body.replaceChildren();
    body.append(h("div", { class: d.gain >= 0 ? "panel" : "sf-banner" }, h("b", {}, d.verdict)),
      summaryStrip([["Hours worked", N(k.hours)], ["Utilisation", k.utilisation_pct == null ? "—" : N(k.utilisation_pct) + "%"], ["Idle / breakdown h", N(k.idle_hours) + " / " + N(k.breakdown_hours)],
        ["Cost (running + depreciation + interest)", M(k.economic_cost)], ["Cost per hour", M(k.economic_per_unit)], ["Charge rate", M(k.internal_rate)], ["Charged to projects", M(k.earned)], ["Hired out", M(k.hire_out)]]));
    const tabsDef = [
      ["Summary", () => h("div", {}, kv([["Code", m.code], ["Name", m.name], ["Kind", d.kind || m.category], ["Make / model", [m.make, m.model].filter(Boolean).join(" ")], ["Registration no", m.reg_no],
        ["Ownership", m.ownership + (m.vendor ? " (" + m.vendor + ")" : "")], ["Status", m.status], ["Project now", m.pcode], ["Operator", m.operator], ["Meter", N(m.meter) + " " + (m.meter_type || "")],
        ["Purchase", m.purchase_date ? m.purchase_date + " · " + M(m.purchase_value) : ""], ["Fuel norm (litres/hour)", m.fuel_norm]]),
        h("h4", {}, "Cost in the period"), kv([["Running cost (fuel, repairs, operator...)", M(k.operating)], ["Depreciation", M(k.depreciation)], ["Loan interest", M(k.interest)],
          ["Loan instalments paid", M(k.emi_paid)], ["Cash cost", M(k.cash_cost)], ["Cash cost per hour", M(k.cash_per_unit)], ["Market hire rate", M(k.market_rate)],
          ["Owning against renting (per hour)", k.own_vs_rent == null ? "—" : M(k.own_vs_rent)], ["Idle hours caused by the employer", N(k.employer_idle_hours) + " (" + M(k.employer_idle_cost) + ")"]]))],
      ["By project", () => d.by_project.length ? table([{ k: "project", label: "Project" }, { label: "Hours", v: (r) => N(r.hours) }, { label: "Idle", v: (r) => N(r.idle) }, { label: "Breakdown", v: (r) => N(r.breakdown) }, { k: "charged", label: "Charged", fmt: "money" }], d.by_project, { search: false }) : empty("No logsheets in the period.")],
      ["Month by month", () => table([{ k: "month", label: "Month" }, { label: "Hours", v: (r) => N(r.hours) }, { label: "Idle", v: (r) => N(r.idle) }, { label: "Breakdown", v: (r) => N(r.breakdown) },
        { label: "Fuel (l)", v: (r) => N(r.fuel) }, { label: "Litres/hour", v: (r) => r.fuel_per_hour == null ? "" : h("span", { class: r.over_norm ? "neg" : "" }, N(r.fuel_per_hour)) }, { label: "Norm", v: (r) => r.norm ? N(r.norm) : "" },
        { k: "depreciation", label: "Depreciation", fmt: "money" }, { k: "emi", label: "Loan instalment", fmt: "money" }], d.months, { search: false, name: "mc_months" })],
      ["Repairs", () => h("div", {}, h("h4", {}, "Work orders"), d.work_orders.length ? table([{ k: "no", label: "No" }, { k: "type", label: "Type" }, { k: "status", label: "Status" }, { k: "reported_at", label: "Reported" }, { k: "completed_at", label: "Done" }, { k: "description", label: "What" }, { label: "Downtime h", v: (r) => N(r.downtime_hours) }, { label: "Cost", v: (r) => M((r.parts_cost || 0) + (r.labour_cost || 0) + (r.external_cost || 0)) }], d.work_orders, { search: false }) : empty("No work orders."),
        h("h4", {}, "Spares and oil issued (period)"), d.parts.length ? table([{ k: "date", label: "Date" }, { k: "no", label: "Issue" }, { k: "material", label: "Material" }, { label: "Qty", v: (r) => N(r.qty) + " " + (r.unit || "") }, { k: "amount", label: "Amount", fmt: "money" }], d.parts, { search: false, totals: ["amount"] }) : empty("None."))],
      ["Papers", () => h("div", {}, table([{ k: "paper", label: "Paper" }, { k: "expiry", label: "Expires" }, { label: "State", v: (r) => h("span", { class: /expired|due|missing/.test(r.state) ? "neg" : "" }, r.state) }], d.papers, { search: false }),
        h("h4", {}, "Documents attached"), d.docs.length ? table([{ k: "title", label: "Title" }, { k: "doc_number", label: "No" }, { k: "doc_date", label: "Date" }, { k: "file_name", label: "File" }], d.docs, { search: false }) : empty("None in the Document library for this machine."))],
      ["Where it worked", () => h("div", {}, d.deployments.length ? table([{ k: "project", label: "Project" }, { k: "mob_date", label: "Arrived" }, { k: "demob_date", label: "Left" }, { label: "Meter", v: (r) => N(r.meter) }, { k: "remarks", label: "Remarks" }], d.deployments, { search: false }) : empty("No moves recorded."),
        d.hire.length ? h("div", {}, h("h4", {}, "Hire agreements"), table([{ k: "vendor", label: "Owner" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "unit", label: "Per" }, { k: "start_date", label: "From" }, { k: "end_date", label: "To" }], d.hire, { search: false })) : null)],
    ];
    body.append(tabs(tabsDef, 0));
  };
  await load();
};

/* ═════════════ Equipment › Machine & manpower plan ═════════════ */
PAGES["mc/plan"] = async (root, params) => {
  root.append(pageHead("Machine & manpower plan", "Machine hours and labour each project's programme needs, week by week, against the machines and people the company has. Nothing moves by itself: use the suggestions to move or hire."));
  root.append(tabs([["Machines", machinesTab], ["Manpower", peopleTab], ["Weekly planning", weeksTab], ["Breakdowns", bdTab], ["Depreciation", depTab], ["Settings", setTab]], params && params.tab ? Number(params.tab) : 0));
};

async function machinesTab() {
  const d = await api("mc.plan", {});
  const box = h("div");
  box.append(h("p", { class: "hint" }, "Machines needed = machine hours from the resources on the activities (spread over their remaining dates) ÷ " + d.capacity_hours + " hours a week. A machine under repair is not counted."));
  box.append(summaryStrip([["Weeks short (company)", String(d.clashes.length)], ["Suggestions", String(d.suggestions.length)], ["Machines with no work ahead", String(d.idle.length)], ["Under repair", String(d.down.length)]]));
  if (d.suggestions.length) box.append(h("h3", {}, "Suggestions"), h("ul", {}, d.suggestions.map((s) => h("li", {}, s.text, " ", s.machine_id ? h("a", { href: "#/eq/register" }, "Move it") : h("a", { href: "#/eq/hire" }, "Hire")))));
  const cols = [{ k: "kind_label", label: "Machine" }, { label: "Project", v: (r) => r.total ? h("b", {}, "Company") : r.project || "Yard" }, { label: "Have", v: (r) => String(r.have) + (r.down ? " (+" + r.down + " down)" : "") }]
    .concat(d.weeks.map((w, i) => ({ label: wk(w), v: (r) => { const n = r.need[i]; const s = r.short[i]; return n < 0.01 ? "" : h("span", { class: s > 0 ? "neg" : "", title: N(n * d.capacity_hours) + " machine hours" }, N(n) + (s > 0 ? " ▲" : "")); } })));
  const rows = d.rows.filter((r) => r.have || r.down || r.need.some((x) => x >= 0.15));
  const small = d.rows.filter((r) => !r.total && !r.have && !r.down && r.need.some((x) => x >= 0.01) && !r.need.some((x) => x >= 0.15)).map((r) => r.kind_label);
  box.append(h("h3", {}, "Machines needed per week (▲ short)"), table(cols, rows, { name: "mc_plan", search: false }));
  if (small.length) box.append(h("p", { class: "hint" }, "Less than a day a week, not shown: " + [...new Set(small)].join(", ") + "."));
  if (d.idle.length) box.append(h("h3", {}, "Machines with no work ahead"), table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "project", label: "Project" }, { k: "last_log", label: "Last logsheet" }, { k: "why", label: "Why" },
    { label: "", v: (m) => h("a", { href: "#/mc/machine?id=" + m.id }, "Machine page") }], d.idle, { search: false }));
  if (d.down.length) box.append(h("h3", {}, "Under repair"), table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "project", label: "Project" }, { k: "status", label: "Status" }], d.down, { search: false }));
  if (d.unmatched.length) {
    box.append(h("h3", {}, "Programme resources the plan cannot match to a machine kind"));
    box.append(table([{ k: "name", label: "Resource" }, { label: "Hours ahead", v: (r) => N(r.hours) }, { label: "Machine kind", v: (r) => can("equipment", "edit") ? h("select", { onchange: async (e) => { await run("mc.map_save", { name: r.name, kind: e.target.value }, "Saved."); go(); } },
      h("option", { value: "" }, "—"), d.kinds.map((k) => h("option", { value: k.key }, k.label))) : "" }], d.unmatched, { search: false }));
  }
  return box;
}

async function peopleTab() {
  const d = await api("mc.people", {});
  const box = h("div");
  box.append(h("p", { class: "hint" }, "Labour heads per week from the programme's labour resources (labour days ÷ 6), and key staff on each project from the staff list."));
  box.append(d.labour.length ? table([{ k: "project", label: "Project" }, { k: "kind", label: "Labour" }].concat(d.weeks.map((w, i) => ({ label: wk(w), v: (r) => r.heads[i] ? String(r.heads[i]) : "" }))), d.labour, { search: false, name: "mc_lab" }) : empty("No labour resources on the programmes."));
  if (d.gaps.length) box.append(h("h3", {}, "Projects missing key staff"), table([{ k: "project", label: "Project" }, { k: "missing", label: "Missing" }, { k: "why", label: "Why" }], d.gaps, { search: false }));
  if (d.free.length) box.append(h("h3", {}, "Key staff with no project"), table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "designation", label: "Designation" }], d.free, { search: false }));
  box.append(h("h3", {}, "Staff by project"), table([{ label: "Project", v: (r) => r.project || "Head office / none" }, { k: "designation", label: "Designation" }, { k: "name", label: "Name" }], d.staff, { name: "mc_staff" }));
  return box;
}

async function weeksTab() {
  const box = h("div");
  const d = await api("mc.weeks", {});
  box.append(h("p", { class: "hint" }, "Each project commits the coming week's tasks in Schedule › Look-ahead (the constraint check now also looks at the machines on the project). PPC is worked out from the approved DPRs."));
  box.append(d.rows.length ? table([{ k: "project", label: "Project" }, { label: "This week (" + wk(d.this_week) + ")", v: (r) => r.this_week ? r.this_week + " tasks" : h("span", { class: "neg" }, "not committed") },
    { label: "Next week (" + wk(d.next_week) + ")", v: (r) => r.next_week ? r.next_week + " tasks" : h("span", { class: "neg" }, "not committed") },
    { label: "PPC last two weeks", v: (r) => r.ppc.length ? h("span", { class: r.low ? "neg" : "" }, r.ppc.map((x) => x == null ? "—" : x + "%").join(", ")) : "—" },
    { label: "", v: (r) => h("span", {}, h("a", { href: "#/p/schedule" }, "Look-ahead"), " · ", h("a", { href: "javascript:void 0", onclick: () => printWeek(r.project_id, d.this_week) }, "Print week plan")) }], d.rows, { search: false }) : empty("No project has a programme."));
  return box;
}

async function printWeek(pid, ws) {
  const d = await api("mc.week_plan", { project_id: pid, week_start: ws });
  const node = h("div", {}, h("h2", {}, (d.project || {}).code + " · Week plan " + d.week_start + " to " + d.week_end));
  if (!d.foremen.length) node.append(h("p", {}, "Nothing committed for this week."));
  d.foremen.forEach((f) => node.append(h("h3", {}, f.foreman), h("table", { class: "print" }, h("tr", {}, ["Activity", "Location", "Quantity", "Done (fill in)"].map((x) => h("th", {}, x))),
    f.rows.map((r) => h("tr", {}, h("td", {}, (r.code || "") + " " + r.name), h("td", {}, r.location || (r.chainage_from != null ? r.chainage_from + "–" + r.chainage_to : "")), h("td", {}, N(r.planned_qty) + " " + (r.unit || "")), h("td", {}, " "))))));
  printFrame("Week plan", node);
}

async function bdTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("mc.breakdowns", {});
    box.replaceChildren(h("p", { class: "hint" }, "Breakdown hours on the logsheets (from the DPR or the logsheet screens) since " + d.from + ", one line per machine and spell of days. " + (d.on ? "A work order opens by itself when the DPR or logsheet is approved." : "Switch \"Breakdown opens a work order\" is off: open them here.")));
    if (d.missing && can("equipment", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("mc.open_work_orders", {}, (r) => r.made + " work order(s) opened."); load(); } }, "Open the " + d.missing + " missing work order(s)")));
    box.append(d.rows.length ? table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "from", label: "From" }, { k: "to", label: "To" }, { label: "Hours", v: (r) => N(r.hours) }, { k: "reason", label: "Reason" },
      { label: "Work order", v: (r) => r.work_order ? (r.work_order.no + " (" + r.work_order.status + ")") : h("span", { class: "neg" }, "none") }], d.rows, { search: false, name: "mc_bd" }) : empty("No breakdown hours."));
  };
  await load();
  return box;
}

async function depTab() {
  const d = await api("mc.dep_view", {});
  const box = h("div", {}, h("p", { class: "hint" }, "Depreciation of each machine is posted once a month. " + (d.on ? "Only Fixed assets › Depreciation run posts on this company; Equipment › Depreciation and Assets › Asset depreciation show." : "Equipment › Depreciation and Fixed assets › Depreciation run both post today (the second one skips a month already posted). Settings can make Fixed assets the only one.")));
  if (d.not_in_register.length) box.append(h("div", { class: "sf-banner" }, "Not in the capital register yet: " + d.not_in_register.map((m) => m.code).join(", ") + ". Fixed assets › \"Bring machines in\" adds them."));
  box.append(d.rows.length ? table([{ k: "month", label: "Month" }, { k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "voucher", label: "Voucher" }, { k: "posted_from", label: "Posted from" }], d.rows, { name: "mc_dep" }) : empty("No depreciation in the last 12 months."));
  return box;
}

async function setTab() {
  const d = await api("mc.settings", {});
  const f = form([{ k: "bd_on", label: "Breakdown hours on an approved DPR or logsheet open a breakdown work order", type: "check", wide: true },
    { k: "dep_one", label: "Post depreciation only from Fixed assets › Depreciation run", type: "check", wide: true },
    { k: "alerts", label: "Alerts: week not committed, PPC low two weeks, machines short, machine with no work ahead", type: "check", wide: true }],
  { bd_on: d.bd_on ? 1 : 0, dep_one: d.dep_one ? 1 : 0, alerts: d.alerts.some((x) => x.enabled) ? 1 : 0 });
  return h("div", {}, h("p", { class: "hint" }, "All three are off on companies that had entries before 2.59. Each alert kind can also be turned on or off in Action centre › Alerts › Rules."), f,
    can("accounts", "approve") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => run("mc.settings_save", f.values(), "Saved.") }, "Save")) : null);
}
})();
