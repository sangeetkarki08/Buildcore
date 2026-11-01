/* Equipment management */
"use strict";

const EQ_STATUS = [["working", "Working"], ["idle", "Idle"], ["standby", "Standby"], ["breakdown", "Breakdown"], ["under_maintenance", "Under maintenance"], ["in_transit", "In transit"], ["disposed", "Disposed"]];

function statusDialog(e, done) {
  const f = form([{ k: "status", label: "New status", type: "select", noBlank: true, options: EQ_STATUS, default: e.status }, { k: "reason", label: "Reason", wide: true }]);
  modal("Change status: " + e.code, f, [{ label: "Save", cls: "primary", act: async () => { await run("eq.status", Object.assign({ id: e.id }, f.values()), "Status updated"); await reloadLookups(); done && done(); } }], { narrow: true });
}
function deployDialog(e, done) {
  const f = form([{ k: "project_id", label: "Deploy to project", type: "select", options: opt.projects, default: S.project }, { k: "date", label: "Mobilised on", type: "date", default: today() }, { k: "meter", label: "Meter reading on arrival", type: "number", default: e.meter }, { k: "remarks", label: "Condition / remarks", wide: true }]);
  modal("Deploy " + e.code, f, [
    { label: "Deploy", cls: "primary", act: async () => { await run("eq.deploy", Object.assign({ equipment_id: e.id }, f.values()), "Deployed"); await reloadLookups(); done && done(); } },
    e.project_id ? { label: "Demobilise (no project)", act: async () => { await run("eq.demobilise", { equipment_id: e.id, date: f.values().date }, "Demobilised"); await reloadLookups(); done && done(); } } : null,
  ], { narrow: true });
}

PAGES["eq/register"] = masterPage({
  table: "equipment", title: "Equipment register", single: "equipment", module: "equipment", wide: true,
  importer: ["code", "name", "category", "make", "model", "reg_no", "ownership", "purchase_value", "life_months"],
  sub: "Owned and hired machines. Deploy a machine to a project to charge its logsheets, depreciation and internal hire there.",
  defaults: () => ({ ownership: "owned", meter_type: "hours", dep_method: "sl" }),
  rowClass: (r) => ["breakdown", "under_maintenance"].includes(r.status) ? "bad" : "",
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "category", label: "Category" }, { k: "ownership", label: "Owned / hired" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "meter", label: "Meter", fmt: "qty" }, { k: "insurance_expiry", label: "Insurance" }, { k: "status", label: "Status", fmt: "status" }],
  fields: [
    { k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true }, { k: "category", label: "Category", ph: "Excavator, Tipper, DG set…" },
    { k: "make", label: "Make" }, { k: "model", label: "Model" }, { k: "serial", label: "Serial / chassis no." }, { k: "reg_no", label: "Registration no." },
    { k: "ownership", label: "Ownership", type: "select", noBlank: true, options: [["owned", "Owned"], ["hired", "Hired"]] },
    { k: "vendor_id", label: "Supplier / owner", type: "select", options: () => opt.parties(["vendor", "subcontractor"]) },
    { k: "meter_type", label: "Main meter", type: "select", noBlank: true, options: [["hours", "Hour meter"], ["km", "Odometer (km)"]] },
    { k: "meters", label: "Meters on the logsheet", ph: "hour,km", hint: "Any of: hour, km, kwh, boom1, boom2, drum, strokes, load, pump" },
    { k: "checklist_id", label: "Daily check list", type: "select", options: () => (S.L.checklists || []).map((x) => [x.id, x.name]) },
    { k: "rating", label: "Capacity / rating", ph: "75 HP, 6 m³, 125 kVA" },
    { k: "owner_name", label: "Owner's name (rented machines)" },
    { k: "meter", label: "Current meter reading", type: "number" }, { k: "fuel_norm", label: "Fuel norm (L/hr or L/km)", type: "number" },
    { k: "internal_rate", label: "Internal hire rate per hour", type: "number" }, { k: "operator", label: "Operator" },
    { k: "purchase_date", label: "Purchase date", type: "date" }, { k: "purchase_value", label: "Purchase value", type: "number" },
    { k: "residual_value", label: "Residual value", type: "number" },
    { k: "dep_method", label: "Depreciation method", type: "select", noBlank: true, options: [["sl", "Straight line"], ["wdv", "Written-down value"], ["hours", "By hours worked"]] },
    { k: "life_months", label: "Useful life (months)", type: "number" }, { k: "wdv_rate", label: "WDV rate % per year", type: "number" },
    { k: "est_total_hours", label: "Estimated life hours", type: "number" }, { k: "accumulated_dep", label: "Depreciation to date", type: "number" },
    { k: "insurance_expiry", label: "Insurance expiry", type: "date" }, { k: "registration_expiry", label: "Registration expiry", type: "date" },
    { k: "notes", label: "Notes", type: "textarea", wide: true }, { k: "active", label: "Active", type: "check" },
  ],
  extraButtons: (row) => row ? [
    { label: "Open passport", act: () => { location.hash = "#/eq/passport?id=" + row.id; } },
    can("equipment", "edit") ? { label: "Change status", act: () => { statusDialog(row, go); return false; } } : null,
    can("equipment", "edit") ? { label: "Deploy / move", act: () => { deployDialog(row, go); return false; } } : null,
  ] : [],
});

/* ── logsheets ── */
function logDialog(row, done) {
  const eqOpts = () => S.L.equipment.filter((e) => e.active && (!S.project || String(e.project_id) === String(S.project) || (row && e.id === row.equipment_id))).map((e) => [e.id, e.code + " " + e.name]);
  const editable = !row || (row.status === "draft" && can("equipment", "edit"));
  const f = form([
    { k: "equipment_id", label: "Equipment", type: "select", options: eqOpts, req: true },
    { k: "date", label: "Date", type: "date", default: today(), req: true },
    { k: "shift", label: "Shift", type: "select", noBlank: true, options: [["day", "Day"], ["night", "Night"]] },
    { k: "operator", label: "Operator" },
    { k: "meter_start", label: "Opening meter", type: "number" }, { k: "meter_end", label: "Closing meter", type: "number" },
    { k: "hours", label: "Working hours (km-meter machines)", type: "number" },
    { k: "idle_hours", label: "Idle hours", type: "number" }, { k: "breakdown_hours", label: "Breakdown hours", type: "number" },
    { k: "trips", label: "Trips / loads", type: "number" },
    { k: "boq_item_id", label: "Work on BOQ item", type: "select", options: () => opt.boq(S.project || (row || {}).project_id) },
    { k: "work", label: "Work done", wide: true },
  ].map((x) => Object.assign(x, { readonly: !editable })), row || {}, () => {
    const v = f.values();
    const e = byId(S.L.equipment, v.equipment_id);
    if (e && !v.meter_start && !row) f.set("meter_start", e.meter);
  });
  modal(row ? "Logsheet" : "New logsheet", h("div", {}, f, h("p", { class: "hint" }, "Hour-meter machines: hours are closing minus opening. The opening reading cannot be below the previous closing reading.")),
    editable ? [
      { label: "Save", cls: "primary", act: async () => { const r = await run("log.save", { row: Object.assign(f.values(), { id: row && row.id, project_id: (row && row.project_id) || S.project }) }, (x) => "Saved: " + x.hours + " h"); if (r.warning) toast(r.warning); await reloadLookups(); done(); } },
      row ? { label: "Delete", cls: "warn", act: async () => { await run("log.delete", { id: row.id }, "Deleted"); done(); } } : null,
    ] : [], { narrow: true, head: row ? stamp(row.status) : null });
}
PAGES["eq/logs"] = async (root) => {
  if (!S.project) return root.append(pageHead("Daily logsheets"), projectNotice());
  let v = { from: monthAgo(), to: today(), status: "" };
  const holder = h("div");
  const picked = new Set();
  const load = async () => {
    picked.clear();
    const rows = await run("log.list", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    const cols = [
      { label: "", v: (r) => r.status === "draft" && can("equipment", "approve") ? h("input", { type: "checkbox", onclick: (e) => { e.stopPropagation(); e.target.checked ? picked.add(r.id) : picked.delete(r.id); } }) : "" },
      { k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "operator", label: "Operator" },
      { k: "meter_start", label: "Open", fmt: "qty" }, { k: "meter_end", label: "Close", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" },
      { k: "idle_hours", label: "Idle", fmt: "qty" }, { k: "breakdown_hours", label: "Breakdown", fmt: "qty" }, { k: "work", label: "Work" }, { k: "status", label: "Status", fmt: "status" },
    ];
    holder.append(table(cols, rows, { name: "logsheets", totals: ["hours", "idle_hours", "breakdown_hours"], onRow: (r) => logDialog(r, load) }));
  };
  root.append(pageHead("Daily logsheets", "One entry per machine per shift. Hours feed internal hire, hire bills, hours-based depreciation and KPIs.",
    can("equipment", "edit") ? h("button", { class: "btn primary", onclick: () => logDialog(null, load) }, "New logsheet") : null,
    can("equipment", "approve") ? h("button", { class: "btn", onclick: async () => { if (!picked.size) return toast("Tick logsheets to approve.", "err"); await run("log.approve", { ids: [...picked] }, "Approved"); load(); } }, "Approve ticked") : null),
    filterBar([{ k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, blank: "All" }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "status", label: "Status", type: "select", options: [["draft", "Draft"], ["approved", "Approved"]], blank: "All" }], v, (x) => { v = x; load(); }), holder);
  load();
};

/* ── maintenance ── */
const PLANS = masterPage({
  table: "maint_plans", title: "Maintenance plans", single: "maintenance plan", module: "equipment",
  cols: [{ label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "title", label: "Service" }, { k: "interval_type", label: "Every" }, { k: "interval", label: "Interval", fmt: "qty" }, { k: "last_date", label: "Last done" }, { k: "last_meter", label: "At meter", fmt: "qty" }, { k: "active", label: "Active", fmt: "yes" }],
  fields: [{ k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, req: true }, { k: "title", label: "Service", req: true, ph: "250-hour service" }, { k: "interval_type", label: "Interval by", type: "select", noBlank: true, options: [["hours", "Meter (hours / km)"], ["days", "Days"]] }, { k: "interval", label: "Interval", type: "number", req: true }, { k: "last_date", label: "Last done on", type: "date" }, { k: "last_meter", label: "Last done at meter", type: "number" }, { k: "checklist", label: "Checklist (one item per line)", type: "textarea", wide: true }, { k: "active", label: "Active", type: "check" }],
});
PAGES["eq/maint"] = async (root) => {
  const rows = await run("maint.status", {});
  const due = h("div");
  due.append(table([
    { label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "title", label: "Service" }, { k: "state", label: "State", v: (r) => stamp(r.state === "ok" ? "ok" : r.state === "overdue" || r.state === "never done" ? "overdue" : "due") },
    { label: "Due at", v: (r) => r.interval_type === "days" ? (r.due_date || "now") : fmtQty(r.due_meter) }, { label: "Remaining", v: (r) => r.left == null ? "" : fmtQty(r.left) + (r.interval_type === "days" ? " days" : "") },
    { k: "meter", label: "Meter now", fmt: "qty" }, { k: "open_wo", label: "Open WO" },
    { label: "", v: (r) => r.due && !r.open_wo && can("equipment", "edit") ? h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); await run("maint.create_wo", { plan_id: r.plan_id }, (x) => "Created " + x.no); go(); } }, "Create work order") : "" },
  ], rows, { name: "maintenance_due", rowClass: (r) => r.state === "overdue" ? "bad" : r.due ? "flag" : "", empty: "No maintenance plans yet." }));
  root.append(pageHead("Preventive maintenance", "Services fall due by date or meter reading, whichever the plan uses. Items within 7 days or 10% of the interval are flagged."), h("h2", {}, "Service status"), due, h("div", { style: "margin-top:22px" }));
  const plansBox = h("div");
  root.append(plansBox);
  await PLANS(plansBox);
};

PAGES["eq/wo"] = async (root) => {
  let v = { status: "" };
  const holder = h("div");
  const load = async () => {
    const rows = await run("wo.list", Object.assign({ project_id: S.project || null }, v));
    holder.innerHTML = "";
    holder.append(table([{ k: "no", label: "No." }, { k: "type", label: "Type" }, { label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "reported_at", label: "Reported", v: (r) => (r.reported_at || "").replace("T", " ").slice(0, 16) }, { k: "completed_at", label: "Completed", v: (r) => (r.completed_at || "").replace("T", " ").slice(0, 16) }, { k: "downtime_hours", label: "Downtime h", fmt: "qty" }, { k: "spares_cost", label: "Spares", fmt: "money" }, { k: "technician", label: "Technician" }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "work_orders", onRow: (r) => woDialog(r, load) }));
  };
  root.append(pageHead("Work orders", "Breakdowns and services. A breakdown work order marks the machine as broken down until completed. Issue spare parts from the store against the work order to cost them.", can("equipment", "edit") ? h("button", { class: "btn primary", onclick: () => woDialog(null, load) }, "Report breakdown") : null),
    filterBar([{ k: "status", label: "Status", type: "select", options: [["open", "Open"], ["in_progress", "In progress"], ["completed", "Completed"], ["cancelled", "Cancelled"]], blank: "All" }, { k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, blank: "All" }], v, (x) => { v = x; load(); }), holder);
  load();
};
function woDialog(w, done) {
  const open = !w || ["open", "in_progress"].includes(w.status);
  const f = form([{ k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, req: true, readonly: !!w }, { k: "type", label: "Type", type: "select", noBlank: true, options: [["breakdown", "Breakdown"], ["preventive", "Preventive"], ["inspection", "Inspection"]], readonly: !!w }, { k: "technician", label: "Technician / workshop" }, { k: "description", label: "Problem / work", type: "textarea", wide: true, req: true }].map((x) => Object.assign(x, { readonly: x.readonly || !open })), w || { type: "breakdown" });
  const b = [];
  if (open && can("equipment", "edit")) {
    b.push({ label: w ? "Save" : "Create", cls: w ? "" : "primary", act: async () => { await run("wo.save", { row: Object.assign(f.values(), { id: w && w.id, project_id: (w && w.project_id) || S.project || null }) }, "Saved"); await reloadLookups(); done(); } });
    if (w && w.status === "open") b.push({ label: "Start work", act: async () => { await run("wo.start", { id: w.id }, "Started"); await reloadLookups(); done(); } });
    if (w) b.push({ label: "Complete", cls: "primary", act: () => {
      const c = form([{ k: "at", label: "Completed at", type: "datetime-local", default: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) }, { k: "meter", label: "Meter reading", type: "number" }, { k: "action_taken", label: "Action taken", type: "textarea", wide: true }]);
      modal("Complete " + w.no, c, [{ label: "Complete", cls: "primary", act: async () => { const v = c.values(); v.at = v.at ? v.at + ":00" : null; await run("wo.complete", Object.assign({ id: w.id }, v), "Completed"); await reloadLookups(); done(); } }], { narrow: true });
      return false;
    } });
    if (w && can("inventory", "edit") && S.project) b.push({ label: "Issue spares", act: () => { docEditor(ISSUE, { status: "draft", date: today(), project_id: S.project, wo_id: w.id, issued_to: w.technician || "Workshop", store_id: (S.L.stores.find((s) => String(s.project_id) === String(S.project) && s.type === "main") || {}).id, lines: [{ target: "equipment", equipment_id: w.equipment_id }] }); return false; } });
    if (w && can("equipment", "approve")) b.push({ label: "Cancel", cls: "warn", act: async () => { await run("wo.cancel", { id: w.id }, "Cancelled"); await reloadLookups(); done(); } });
  }
  modal(w ? "Work order " + w.no : "Report breakdown", h("div", {}, f, w && w.action_taken ? kv([["Action taken", w.action_taken], ["Downtime (h)", w.downtime_hours], ["Meter", w.meter]]) : null), b, { narrow: true, head: w ? stamp(w.status) : null });
}

/* ── hire ── */
const HIRE = masterPage({
  table: "hire_agreements", title: "Hire agreements", single: "hire agreement", module: "equipment",
  cols: [{ label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { label: "Owner", v: (r) => nm.party(r.vendor_id) }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "rate", label: "Rate", fmt: "money" }, { k: "unit", label: "Per" }, { k: "min_units", label: "Minimum", fmt: "qty" }, { k: "start_date", label: "From" }, { k: "active", label: "Active", fmt: "yes" }],
  fields: [{ k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, req: true }, { k: "vendor_id", label: "Hired from", type: "select", options: () => opt.parties(["vendor", "subcontractor"]), req: true }, { k: "project_id", label: "Project", type: "select", options: opt.projects, req: true }, { k: "rate", label: "Rate", type: "number", req: true }, { k: "unit", label: "Rate per", type: "select", noBlank: true, options: [["hour", "Hour"], ["day", "Day worked"], ["month", "Month"]] }, { k: "min_units", label: "Minimum guaranteed units per month", type: "number" }, { k: "mob_cost", label: "Mobilisation (first bill)", type: "number" }, { k: "vat_rate", label: "VAT %", type: "number" }, { k: "start_date", label: "Start", type: "date" }, { k: "end_date", label: "End", type: "date" }, { k: "remarks", label: "Remarks", wide: true }, { k: "active", label: "Active", type: "check" }],
  defaults: () => ({ project_id: S.project, unit: "hour", vat_rate: S.L.settings.vat_rate }),
});
PAGES["eq/hire"] = async (root) => {
  root.append(pageHead("Hired equipment billing", "Monthly hire bills are calculated from logsheets with the minimum guarantee applied, then saved as a draft purchase bill for checking and posting."));
  const bills = await run("hire.bills", {});
  if (can("accounts", "edit")) {
    const ags = await api("master.list", { table: "hire_agreements" });
    const f = form([{ k: "agreement_id", label: "Agreement", type: "select", options: ags.filter((a) => a.active).map((a) => [a.id, nm.eq(a.equipment_id) + " — " + nm.party(a.vendor_id)]) }, { k: "month", label: "Month", type: "month", default: today().slice(0, 7) }, { k: "party_inv_no", label: "Owner's bill no." }]);
    root.append(h("div", { class: "panel" }, h("h2", {}, "Prepare a monthly bill"), f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const r = await run("hire.bill", f.values(), (x) => "Logged " + x.units + ", billing " + x.billed);
      openDoc(PINV, r.invoice_id);
      go();
    } }, "Prepare bill"))));
  }
  root.append(h("h2", {}, "Bills"), table([{ k: "month", label: "Month" }, { label: "Agreement", v: (r) => "#" + r.agreement_id }, { k: "units", label: "Logged", fmt: "qty" }, { k: "billed_units", label: "Billed", fmt: "qty" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "invoice_no", label: "Bill" }, { k: "invoice_status", label: "Status", fmt: "status" }], bills, { name: "hire_bills", onRow: (r) => openDoc(PINV, r.invoice_id) }), h("div", { style: "margin-top:22px" }));
  const box = h("div");
  root.append(box);
  await HIRE(box);
};

/* ── depreciation & internal hire ── */
PAGES["eq/dep"] = async (root) => {
  let month = (() => { const d = new Date(); d.setDate(0); return d.toISOString().slice(0, 7); })();
  const holder = h("div");
  const load = async () => {
    const [dep, ib] = [await run("dep.preview", { month }), await run("internal.preview", { month })];
    holder.innerHTML = "";
    holder.append(h("h2", {}, "Depreciation for " + month),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Equipment" }, { k: "method", label: "Method" }, { k: "book_value", label: "Book value", fmt: "money" }, { k: "amount", label: "Charge", fmt: "money" }, { label: "Posted", v: (r) => r.posted ? stamp("posted") : "" }], dep, { name: "depreciation", totals: ["amount"], search: false, empty: "No owned equipment with a purchase value." }),
      can("accounts", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("dep.run", { month }, (r) => r.count + " machines, " + fmtMoney(r.total)); load(); } }, "Post depreciation")) : null,
      h("h2", { style: "margin-top:22px" }, "Internal hire charges for " + month),
      h("p", { class: "hint" }, "Charges each project for company-owned machines at the internal rate × logged hours, and credits equipment recovery."),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Equipment" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "hours", label: "Hours", fmt: "qty" }, { k: "internal_rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" }, { label: "Posted", v: (r) => r.posted ? stamp("posted") : "" }], ib, { name: "internal_hire", totals: ["amount"], search: false, empty: "No logged hours for machines with an internal rate." }),
      can("accounts", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("internal.run", { month }, (r) => r.count + " charges, " + fmtMoney(r.total)); load(); } }, "Post internal hire")) : null);
  };
  const inp = h("input", { type: "month", value: month, style: "max-width:180px", onchange: (e) => { month = e.target.value; load(); } });
  root.append(pageHead("Depreciation & internal hire", "Run once a month after the month ends. Both runs skip anything already posted."), h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Month"), inp)), holder);
  load();
};

/* ── KPIs ── */
PAGES["eq/kpi"] = reportPage("Equipment performance", "Availability = scheduled hours minus breakdown. Utilisation = working hours ÷ available hours. Fuel comes from store issues; flagged when 15% above norm.", [{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, projFilter], () => ({ from: monthAgo(), to: today(), project_id: S.project }), async (v) => {
  const d = await run("eq.kpi", v);
  return table([
    { k: "code", label: "Code" }, { k: "name", label: "Equipment" }, { k: "status", label: "Status", fmt: "status" },
    { k: "working_hours", label: "Work h", fmt: "qty" }, { k: "breakdown_hours", label: "Down h", fmt: "qty" },
    { label: "Avail.", v: (r) => fmtPct(r.availability_pct) }, { label: "Util.", v: (r) => fmtPct(r.utilisation_pct) },
    { k: "breakdowns", label: "Breakdowns", fmt: "num" }, { label: "MTTR h", v: (r) => r.mttr ?? "—" }, { label: "MTBF h", v: (r) => r.mtbf ?? "—" },
    { k: "fuel", label: "Fuel", fmt: "qty" }, { label: "Fuel/h", v: (r) => r.fuel_per_hour == null ? "—" : r.fuel_per_hour + (r.fuel_norm ? " (norm " + r.fuel_norm + ")" : "") },
    { k: "cost", label: "Cost", fmt: "money" }, { k: "cost_per_hour", label: "Cost/h", fmt: "money" }, { k: "internal_rate", label: "Int. rate", fmt: "money" },
    { label: "Last log", v: (r) => r.days_since_log == null ? "never" : r.days_since_log + " d ago" },
  ], d.rows, { name: "equipment_kpi", rowClass: (r) => r.fuel_flag || (r.utilisation_pct != null && r.utilisation_pct < 40) ? "flag" : "", onRow: (r) => { location.hash = "#/eq/passport?id=" + r.id; } });
});

PAGES["eq/passport"] = async (root, params) => {
  if (!params.id) { location.hash = "#/eq/register"; return; }
  const d = await run("eq.passport", { id: params.id });
  const e = d.equipment;
  const tabs = [
    ["Overview", () => h("div", { class: "cols" }, h("div", { class: "panel" }, kv([["Category", e.category], ["Make / model", [e.make, e.model].filter(Boolean).join(" ")], ["Serial", e.serial], ["Registration", e.reg_no], ["Ownership", e.ownership + (e.vendor_id ? " — " + nm.party(e.vendor_id) : "")], ["Project", nm.project(e.project_id)], ["Meter", fmtQty(e.meter) + " " + e.meter_type], ["Fuel norm", e.fuel_norm], ["Internal rate", fmtMoney(e.internal_rate)], ["Operator", e.operator]])),
      h("div", { class: "panel" }, kv([["Purchase value", fmtMoney(e.purchase_value)], ["Depreciation to date", fmtMoney(e.accumulated_dep)], ["Book value", fmtMoney(e.purchase_value - e.accumulated_dep)], ["Method", e.dep_method], ["Insurance expiry", e.insurance_expiry], ["Registration expiry", e.registration_expiry]])),
      h("div", { class: "panel" }, h("h2", {}, "Costs to date"), table([{ k: "name", label: "Account" }, { k: "amt", label: "Amount", fmt: "money" }], d.costs, { search: false, export: false, totals: ["amt"], empty: "No costs booked." })))],
    ["Status history", () => table([{ k: "status", label: "Status", fmt: "status" }, { k: "from_ts", label: "From" }, { k: "to_ts", label: "To" }, { k: "reason", label: "Reason" }], d.status_log, { search: false })],
    ["Deployments", () => table([{ label: "Project", v: (r) => nm.project(r.project_id) }, { k: "mob_date", label: "Mobilised" }, { k: "demob_date", label: "Demobilised" }, { k: "meter", label: "Meter", fmt: "qty" }, { k: "remarks", label: "Remarks" }], d.deployments, { search: false })],
    ["Monthly sheets", () => h("div", {},
      h("p", { class: "hint" }, "One signed sheet a month. Click a month to open it, print it or send it for approval."),
      table([{ k: "no", label: "Sheet no." }, { label: "Month", v: (r) => r.period_label || r.period },
        { k: "sheet_type", label: "Kind" }, { k: "operator", label: "Operator / driver" },
        { k: "days", label: "Days", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" },
        { k: "fuel", label: "Fuel", fmt: "qty" }, { k: "payable_days", label: "Payable days", fmt: "qty" },
        { k: "status", label: "Status", fmt: "status" }], d.books || [],
      { search: false, totals: ["hours", "fuel"], empty: "No monthly sheet for this machine yet.",
        onRow: (r) => { location.hash = "#/eq/book?id=" + r.id; } }),
      can("equipment", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn small primary",
        onclick: () => { location.hash = "#/eq/books"; } }, "Open a new monthly sheet")) : null)],
    ["Day by day", () => table([{ k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { k: "meter_start", label: "Open", fmt: "qty" }, { k: "meter_end", label: "Close", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" }, { k: "fuel_qty", label: "Fuel", fmt: "qty" }, { k: "work", label: "Work" }, { k: "status", label: "Status", fmt: "status" }], d.logs, { search: false })],
    ["Servicing", () => table([{ k: "date", label: "Date" }, { label: "Month", v: (r) => r.period },
      { k: "description", label: "What was done / part" }, { k: "part_no", label: "Part no." },
      { k: "qty", label: "Qty", fmt: "qty" }, { k: "brand", label: "Brand" },
      { k: "at_hour", label: "At hour meter", fmt: "qty" }, { k: "remarks", label: "Remarks" }],
    d.service || [], { search: false, empty: "Nothing recorded on the monthly sheets yet." })],
    ["Maintenance", () => h("div", {}, table([{ k: "title", label: "Service" }, { k: "state", label: "State" }, { label: "Due", v: (r) => r.due_date || fmtQty(r.due_meter) }], d.plans, { search: false, empty: "No plans." }), h("h3", {}, "Work orders"), table([{ k: "no", label: "No." }, { k: "type", label: "Type" }, { k: "description", label: "Description" }, { k: "downtime_hours", label: "Downtime", fmt: "qty" }, { k: "status", label: "Status", fmt: "status" }], d.work_orders, { search: false }))],
    ["Materials & fuel", () => table([{ k: "date", label: "Date" }, { k: "no", label: "Issue" }, { label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "amount", label: "Amount", fmt: "money" }], d.materials, { search: false, totals: ["amount"] })],
  ];
  const body = h("div");
  const bar = h("div", { class: "tabs" });
  const show = (i) => { bar.querySelectorAll("button").forEach((b, j) => b.classList.toggle("on", i === j)); body.innerHTML = ""; body.append(tabs[i][1]()); };
  tabs.forEach(([t], i) => bar.append(h("button", { onclick: () => show(i) }, t)));
  root.append(pageHead(e.code + " " + e.name, null, stamp(e.status),
    can("equipment", "edit") ? h("button", { class: "btn", onclick: () => statusDialog(e, go) }, "Change status") : null,
    can("equipment", "edit") ? h("button", { class: "btn", onclick: () => deployDialog(e, go) }, "Deploy / move") : null,
    h("button", { class: "btn", onclick: () => { location.hash = "#/eq/register"; } }, "Back to register")), bar, body);
  show(0);
};
