/* BuildCore 1.7 — Fixed assets & equipment accounting.
   Screens: capital register, depreciation run, tax pools & deferred tax, equipment costing
   (rates, charge to projects, true-up), maintenance plan (ABC), leases (NFRS 16),
   impairment & disposal, PPE movement note, inventory analysis (NAS 2). */
(function () {
"use strict";
/* everything below is private to this file, so no name can clash with the rest of BuildCore */


let FA_POL = null;
const faAdd = (el, ...xs) => el.append(...xs.filter((x) => x != null && x !== false));
const faToday = () => new Date().toISOString().slice(0, 10);
const faClose = () => { const o = document.querySelectorAll(".overlay"); if (o.length) o[o.length - 1].remove(); };
const faMonth = () => (typeof thisPeriod === "function" ? thisPeriod() : faToday().slice(0, 7));
async function faPolicy() {
  if (!FA_POL) FA_POL = await run("fa.policy", {});
  return FA_POL;
}
const faClassName = (k) => ((FA_POL && FA_POL.classes.find((x) => x[0] === k)) || [k, k])[1];
const faFy = () => (S.L.fiscal_years && S.L.fiscal_years[0]) || "";
const FA_METHODS = [["SL", "Straight line"], ["WDV", "Written down value"], ["SOY", "Sum of years' digits"],
  ["UOP", "Hour meter (units of production)"], ["NONE", "Not depreciated"]];
const FA_POOLS = [["A", "A — buildings 5%"], ["B", "B — computers, furniture 25%"], ["C", "C — vehicles 20%"],
  ["D", "D — construction equipment 15%"], ["E", "E — intangibles (cost ÷ life)"]];
const FA_STAGES = [["plan", "Plan"], ["acquire", "Acquire"], ["operate", "Operate"], ["maintain", "Maintain"],
  ["idle", "Idle / standby"], ["renew", "Renew / overhaul"], ["dispose", "Dispose"]];
const FA_SCORE = [[5, "High (5)"], [3, "Medium (3)"], [1, "Low (1)"]];

/* ── capital register ── */
PAGES["fa/register"] = async (root, params) => {
  await faPolicy();
  let v = { kind: params.kind || "", klass: params.klass || "", abc_class: "", tax_pool: "", status: "active" };
  const holder = h("div");
  const load = async () => {
    const d = await run("fa.list", Object.assign({ project_id: S.project || null }, v));
    holder.innerHTML = "";
    faAdd(holder, summaryStrip([["Items", d.rows.length], ["Cost", fmtMoney(d.totals.cost)],
      ["Accumulated depreciation", fmtMoney(d.totals.accumulated)], ["Impairment", fmtMoney(d.totals.impairment)],
      ["Carrying amount", fmtMoney(d.totals.nbv)]]));
    faAdd(holder, h("div", { class: "cols" },
      h("div", { class: "panel" }, h("h2", {}, "By class"),
        table([{ label: "Class", v: (r) => faClassName(r.klass) }, { k: "count", label: "Items", fmt: "num" },
          { k: "cost", label: "Cost", fmt: "money" }, { k: "accumulated", label: "Depreciation", fmt: "money" },
          { k: "nbv", label: "Carrying", fmt: "money" }], d.by_class,
          { search: false, name: "fa_by_class", title: "PPE by class", totals: ["count", "cost", "accumulated", "nbv"],
            onRow: (r) => { v = Object.assign({}, v, { klass: r.klass }); load(); } }))));
    faAdd(holder, table([
      { k: "code", label: "Code" }, { k: "name", label: "Description" },
      { label: "Class", v: (r) => faClassName(r.klass) },
      { label: "Kind", v: (r) => r.kind === "equipment" ? "Equipment" : "Asset" },
      { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "" },
      { k: "in_use_date", label: "In use from" }, { k: "method", label: "Method" },
      { k: "tax_pool", label: "Pool" }, { k: "abc_class", label: "ABC" },
      { label: "Stage", v: (r) => (FA_STAGES.find(([k]) => k === r.lifecycle) || [, r.lifecycle])[1] },
      { k: "cost", label: "Cost", fmt: "money" }, { k: "accumulated", label: "Depreciation", fmt: "money" },
      { k: "impairment", label: "Impairment", fmt: "money" }, { k: "nbv", label: "Carrying", fmt: "money" },
      { k: "owner_entity", label: "Owner (JV)" }, { k: "status", label: "Status", fmt: "status" },
    ], d.rows, { name: "fa_register", title: "Capital register", totals: ["cost", "accumulated", "impairment", "nbv"],
      rowClass: (r) => r.status === "disposed" ? "muted" : (!r.managed ? "" : (!r.in_use_date || !r.cost ? "flag" : "")),
      empty: "Nothing in the register yet. Use “Bring in equipment and assets”.",
      onRow: (r) => faItemDialog(r.id, load) }));
  };
  root.append(pageHead("Capital register",
    "Every machine and asset the company owns, with its NAS 16 policy, components, tax pool, ABC class and life-cycle stage. "
    + "Flagged lines have no cost or no in-use date yet, so they cannot be depreciated.",
    can("assets", "edit") ? h("button", { class: "btn primary", onclick: async () => {
      await run("fa.sync", {}, (x) => x.added + " added to the register"); load(); } }, "Bring in equipment and assets") : null,
    can("assets", "edit") ? h("button", { class: "btn", onclick: () => faItemDialog(null, load) }, "New item") : null,
    can("assets", "edit") ? h("button", { class: "btn", onclick: async () => {
      const r = await run("fa.abc_rank", { apply: true }, (x) => "A " + x.counts.A + " · B " + x.counts.B + " · C " + x.counts.C);
      load(); return r; } }, "Rank fleet A/B/C") : null),
    filterBar([
      { k: "kind", label: "Kind", type: "select", options: [["equipment", "Equipment"], ["asset", "Asset"]], blank: "All" },
      { k: "klass", label: "Class", type: "select", options: () => FA_POL.classes.map((x) => [x[0], x[1]]), blank: "All" },
      { k: "abc_class", label: "ABC", type: "select", options: [["A", "A"], ["B", "B"], ["C", "C"]], blank: "All" },
      { k: "tax_pool", label: "Tax pool", type: "select", options: FA_POOLS, blank: "All" },
      { k: "status", label: "Status", type: "select", options: [["active", "In use"], ["disposed", "Disposed"]], blank: "All" },
    ], v, (x) => { v = x; load(); }), holder);
  await load();
};

async function faItemDialog(id, done) {
  const pol = await faPolicy();
  const d = id ? await run("fa.get", { id }) : { item: { method: "SL", lifecycle: "operate", owner_share: 100, idle_threshold: 90 },
    components: [], dep: [], maint: [], impair: [], rates: [] };
  const it = d.item;
  const ro = !can("assets", "edit");
  const f = form([
    { k: "code", label: "Code", req: true, readonly: ro }, { k: "name", label: "Description", req: true, wide: true, readonly: ro },
    { k: "klass", label: "Class", type: "select", options: pol.classes.map((x) => [x[0], x[1]]), req: true, readonly: ro },
    { k: "lifecycle", label: "Life-cycle stage", type: "select", options: FA_STAGES, readonly: ro },
    { k: "cost", label: "Cost (capitalised)", type: "number", readonly: ro, hint: "Price + import duty + transport + installation + commissioning (NAS 16 para 16)" },
    { k: "in_use_date", label: "Available for use from", type: "date", readonly: ro },
    { k: "method", label: "Book method", type: "select", options: FA_METHODS, noBlank: true, readonly: ro },
    { k: "life_years", label: "Useful life (years)", type: "number", readonly: ro },
    { k: "life_hours", label: "Useful life (hours)", type: "number", readonly: ro, hint: "For the hour-meter method" },
    { k: "residual", label: "Residual value", type: "number", readonly: ro },
    { k: "wdv_rate", label: "WDV rate (blank = worked out)", type: "number", readonly: ro },
    { k: "tax_pool", label: "Tax pool (Schedule 2)", type: "select", options: FA_POOLS, readonly: ro },
    { k: "project_id", label: "Deployed on", type: "select", options: () => S.L.projects.map((p) => [p.id, p.code + " " + p.name]), readonly: ro },
    { k: "owner_entity", label: "Owned by (JV partner)", readonly: ro }, { k: "owner_share", label: "Share %", type: "number", readonly: ro },
    { k: "idle_threshold", label: "Idle days before impairment check", type: "number", readonly: ro },
    { k: "hour_reading", label: "Hour meter now", type: "number", readonly: ro },
    { k: "s_workload", label: "Workload", type: "select", options: FA_SCORE, readonly: ro },
    { k: "s_impact_other", label: "Impact on other machines", type: "select", options: FA_SCORE, readonly: ro },
    { k: "s_impact_production", label: "Impact on production", type: "select", options: FA_SCORE, readonly: ro },
    { k: "s_repair_ease", label: "Difficulty of repair", type: "select", options: FA_SCORE, readonly: ro },
    { k: "s_price", label: "Price", type: "select", options: FA_SCORE, readonly: ro },
    { k: "abc_class", label: "ABC class", type: "select", options: [["A", "A"], ["B", "B"], ["C", "C"]], readonly: ro },
    { k: "managed", label: "Depreciated here", type: "select", options: [[1, "Yes"], [0, "No — Asset module posts it"]], readonly: ro },
    { k: "remarks", label: "Remarks", type: "textarea", wide: true, readonly: ro },
  ], it);
  const tabs = [["Policy", f]];
  if (id) {
    const abc = d.abc_policy || {};
    tabs.push(["Components", h("div", {},
      table([{ k: "name", label: "Component" }, { k: "method", label: "Method" }, { k: "cost", label: "Cost", fmt: "money" },
        { k: "life_hours", label: "Life h", fmt: "qty" }, { k: "accumulated", label: "Depreciation", fmt: "money" },
        { k: "in_use_date", label: "From" }, { k: "status", label: "Status", fmt: "status" }], d.components,
        { search: false, export: false, empty: "Not split into components." }),
      ro ? null : h("div", { class: "actions" },
        h("button", { class: "btn", onclick: async () => { await run("fa.components_split", { id }, "Split"); faClose(); faItemDialog(id, done); } }, "Split from class template"),
        h("button", { class: "btn", onclick: () => faComponentDialog(it, d.components, () => { faClose(); faItemDialog(id, done); }) }, "Add / replace a component")))]);
    tabs.push(["Schedule", h("div", { class: "fa-sched" }, h("button", { class: "btn", onclick: async (ev) => {
      const s = await run("fa.schedule", { id });
      ev.target.replaceWith(h("div", {},
        h("h3", {}, "Book (NAS 16) against tax (indicative) and deferred tax"),
        table([{ k: "year", label: "Year" }, { label: "Book opening", v: (r) => fmtMoney(r.b.opening) },
          { label: "Book depreciation", v: (r) => fmtMoney(r.b.dep) }, { label: "Book closing", v: (r) => fmtMoney(r.b.closing) },
          { label: "Tax depreciation", v: (r) => fmtMoney(r.t.dep) }, { label: "Tax WDV", v: (r) => fmtMoney(r.t.closing) },
          { label: "Difference", v: (r) => fmtMoney(r.d.difference) }, { label: "Deferred tax", v: (r) => fmtMoney(r.d.net) },
          { label: "Basis", v: (r) => r.b.basis }],
          s.book.map((b, i) => ({ year: b.year, b, t: s.tax[i], d: s.deferred[i] })), { search: false, name: "fa_schedule", title: "Schedule " + it.code }),
        h("p", { class: "hint" }, s.note)));
    } }, "Work out the whole-life schedule"))]);
    tabs.push(["Depreciation", table([{ k: "month", label: "Month" }, { k: "comp_id", label: "Component" },
      { k: "method", label: "Method" }, { k: "hours", label: "Hours", fmt: "qty" }, { k: "amount", label: "Amount", fmt: "money" },
      { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "" }], d.dep,
      { search: false, totals: ["amount", "hours"], empty: "No depreciation posted yet." })]);
    tabs.push(["Maintenance", h("div", {},
      h("p", { class: "hint" }, "Class " + (it.abc_class || "C") + ": " + (abc.maintenance || "") + ". " + (abc.repair || "")
        + ". Spares held: " + Math.round((abc.spares || 0) * 100) + "%. Safety check: " + (abc.safety_check || "") + "."),
      table([{ k: "date", label: "Date" }, { k: "kind", label: "Kind" }, { k: "at_hour", label: "At hour", fmt: "qty" },
        { k: "cost", label: "Cost", fmt: "money" }, { label: "Capitalised", v: (r) => r.capitalise ? "Yes" : "" },
        { k: "remarks", label: "Remarks" }], d.maint, { search: false, totals: ["cost"], empty: "Nothing recorded." }),
      ro ? null : h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => faMaintDialog(it, () => { faClose(); faItemDialog(id, done); }) }, "Record service / inspection / repair")))]);
    tabs.push(["Impairment", table([{ k: "date", label: "Date" }, { k: "idle_days", label: "Idle days", fmt: "num" },
      { k: "indicators", label: "Indicators" }, { k: "carrying", label: "Carrying", fmt: "money" },
      { k: "recoverable", label: "Recoverable", fmt: "money" }, { k: "loss", label: "Loss", fmt: "money" }], d.impair,
      { search: false, empty: "No reviews." })]);
  }
  const tabBox = h("div", { class: "tabs" });
  const body = h("div");
  tabs.forEach(([t, el], i) => faAdd(tabBox, h("button", { class: "tab" + (i ? "" : " on"), onclick: (e) => {
    tabBox.querySelectorAll(".tab").forEach((b) => b.classList.remove("on")); e.target.classList.add("on");
    body.innerHTML = ""; body.append(el); } }, t)));
  body.append(tabs[0][1]);
  const btns = ro ? [] : [{ label: "Save", cls: "primary", act: async () => {
    const r = await run("fa.save", { row: Object.assign(id ? { id } : {}, f.values()), abc_from_score: true },
      (x) => "Saved · score " + x.abc_score + " → class " + x.abc_class);
    if (done) done(); return r;
  } }];
  if (id && it.status !== "disposed" && can("assets", "approve")) {
    btns.push({ label: "Impairment review", act: () => { faImpairDialog(it, done); return false; } });
    btns.push({ label: "Dispose", act: () => { faDisposeDialog(it, done); return false; } });
  }
  modal(id ? it.code + " " + it.name : "New register item", h("div", {}, tabBox, body), btns);
}

function faComponentDialog(it, comps, done) {
  const f = form([
    { k: "name", label: "Component", req: true, ph: "Replacement engine / undercarriage / overhaul" },
    { k: "cost", label: "Cost", type: "number", req: true }, { k: "in_use_date", label: "In use from", type: "date", default: faToday() },
    { k: "method", label: "Method", type: "select", options: FA_METHODS, default: it.method },
    { k: "life_hours", label: "Life (hours)", type: "number" }, { k: "life_years", label: "Life (years)", type: "number" },
    { k: "replaces", label: "Replaces (derecognise)", type: "select", options: comps.filter((x) => x.status === "active").map((x) => [x.id, x.name]) },
  ], {});
  modal("Add a component", h("div", {}, f, h("p", { class: "hint" },
    "NAS 16 para 13 & 70: the cost of a replaced part is added, and the carrying amount of the old part is taken out as a loss.")),
  [{ label: "Save", cls: "primary", act: async () => { await run("fa.component_save", { row: Object.assign({ fa_id: it.id }, f.values()) }, "Saved"); done(); } }], { narrow: true });
}

function faMaintDialog(it, done) {
  const f = form([
    { k: "date", label: "Date", type: "date", default: faToday(), req: true },
    { k: "kind", label: "Kind", type: "select", noBlank: true, options: [["service", "Service"], ["inspection", "Safety inspection"], ["repair", "Repair"], ["overhaul", "Major overhaul"]] },
    { k: "at_hour", label: "Hour meter", type: "number" }, { k: "cost", label: "Cost", type: "number" },
    { k: "capitalise", label: "Capitalise (extends life)", type: "select", options: [[0, "No — expense"], [1, "Yes — new component"]] },
    { k: "remarks", label: "Remarks", wide: true },
  ], {});
  modal("Maintenance on " + it.code, f, [{ label: "Save", cls: "primary", act: async () => {
    const v = f.values(); v.capitalise = Number(v.capitalise) === 1;
    await run("fa.maint_add", Object.assign({ fa_id: it.id }, v), "Recorded"); done(); } }], { narrow: true });
}

function faImpairDialog(it, done) {
  const f = form([
    { k: "date", label: "Review date", type: "date", default: faToday(), req: true },
    { k: "fvlcs", label: "Fair value less costs of disposal", type: "number", hint: "Dealer / auction quotation" },
    { k: "viu", label: "Value in use", type: "number", hint: "Or leave blank and give cash flows" },
    { k: "cash_flows", label: "Net hire earnings per year (comma separated)", wide: true },
    { k: "discount_rate", label: "Discount rate", type: "number", default: 0.12 },
    { k: "damage", label: "Physical damage", type: "select", options: [[0, "No"], [1, "Yes"]] },
    { k: "obsolete", label: "Obsolete / to be disposed", type: "select", options: [[0, "No"], [1, "Yes"]] },
  ], {});
  modal("NAS 36 impairment review — " + it.code, f, [{ label: "Review and post", cls: "primary", act: async () => {
    const v = f.values();
    if (v.cash_flows) v.cash_flows = String(v.cash_flows).split(",").map(Number); else delete v.cash_flows;
    v.damage = Number(v.damage) === 1; v.obsolete = Number(v.obsolete) === 1;
    await run("fa.impair_review", Object.assign({ id: it.id }, v),
      (x) => x.loss ? "Impairment loss " + fmtMoney(x.loss) + " posted" : (x.test_required ? "Recoverable amount covers the carrying amount" : "No indicator — no test needed"));
    if (done) done(); } }], { narrow: true });
}

function faDisposeDialog(it, done) {
  const f = form([
    { k: "date", label: "Date", type: "date", default: faToday(), req: true },
    { k: "proceeds", label: "Sale proceeds (0 if scrapped)", type: "number" },
    { k: "costs_to_sell", label: "Costs of sale", type: "number" },
  ], {});
  modal("Dispose of " + it.code, h("div", {}, f, h("p", { class: "hint" },
    "Cost, depreciation and impairment come out of the books; the difference to the net proceeds is the gain or loss (NAS 16 para 68). "
    + "The proceeds also reduce tax pool " + (it.tax_pool || "") + " this year.")),
  [{ label: "Post disposal", cls: "primary", act: async () => {
    await run("fa.dispose", Object.assign({ id: it.id }, f.values()), (x) => (x.gain >= 0 ? "Gain " : "Loss ") + fmtMoney(Math.abs(x.gain)));
    if (done) done(); } }], { narrow: true });
}

/* ── monthly depreciation ── */
PAGES["fa/dep"] = async (root) => {
  let v = { month: faMonth() };
  const holder = h("div");
  const load = async () => {
    const d = await run("fa.dep_preview", v);
    holder.innerHTML = "";
    faAdd(holder, summaryStrip([["To post", fmtMoney(d.total)], ["Already posted", fmtMoney(d.posted)], ["Lines", d.rows.length],
      ["Hour-meter machines with no hours", d.no_hours.length]]));
    faAdd(holder, table([{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "component", label: "Component" },
      { k: "method", label: "Method" }, { k: "hours", label: "Hours (logsheets)", fmt: "qty" },
      { label: "Project(s)", v: (r) => Object.keys(r.split).map((p) => nm.pcode(p) + " " + fmtMoney(r.split[p])).join(" · ") },
      { k: "amount", label: "Depreciation", fmt: "money" }, { k: "nbv_after", label: "Carrying after", fmt: "money" }], d.rows,
    { name: "fa_dep", title: "Depreciation " + d.month, totals: ["amount", "hours"], empty: "Nothing left to post for this month." }));
    if (d.no_hours.length) faAdd(holder, h("p", { class: "muted" }, "No approved logsheet hours: " + d.no_hours.join(", ")));
    if (d.rows.length && can("assets", "approve"))
      faAdd(holder, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        await run("fa.dep_run", v, (x) => "Posted " + fmtMoney(x.total)); load(); } }, "Post depreciation for " + d.month),
      h("button", { class: "btn", onclick: async () => { await run("fa.dep_reverse", v, "Reversed"); load(); } }, "Reverse this month")));
  };
  root.append(pageHead("Depreciation run",
    "Straight line, written down value and sum-of-years by the month; hour-meter machines by the hours on their approved logsheets, "
    + "charged to the project the machine worked on. Each component is depreciated on its own (NAS 16 para 43)."),
  filterBar([{ k: "month", label: "Month", type: "month" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

/* ── tax pools and deferred tax ── */
PAGES["fa/tax"] = async (root) => {
  let v = { fy: "" };
  const holder = h("div");
  const load = async () => {
    const [d, dt] = await Promise.all([run("fa.tax_pools", v), run("fa.deferred_tax", v)]);
    holder.innerHTML = "";
    faAdd(holder, summaryStrip([["Income year", d.fy], ["Tax depreciation", fmtMoney(d.totals.depreciation)],
      ["Balancing charge", fmtMoney(d.totals.balancing_charge)], ["Pool closing", fmtMoney(d.totals.closing)],
      ["Book carrying", fmtMoney(dt.carrying)], ["Deferred tax", fmtMoney(dt.net)]]));
    faAdd(holder, table([{ k: "pool", label: "Pool" }, { k: "description", label: "Assets" },
      { label: "Rate", v: (r) => r.rate ? (r.rate * 100) + "%" : "cost ÷ life" },
      { k: "opening", label: "Opening WDV", fmt: "money" }, { k: "additions_total", label: "Additions", fmt: "money" },
      { k: "additions_counted", label: "Counted this year", fmt: "money" }, { k: "disposals", label: "Disposal proceeds", fmt: "money" },
      { k: "base", label: "Depreciation base", fmt: "money" }, { k: "depreciation", label: "Depreciation", fmt: "money" },
      { k: "repairs_allowed", label: "Repairs allowed (7%)", fmt: "money" }, { k: "repairs_added_to_pool", label: "Repairs to pool", fmt: "money" },
      { k: "balancing_charge", label: "Balancing charge", fmt: "money" }, { k: "terminal_loss", label: "Terminal loss", fmt: "money" },
      { k: "deferred_additions", label: "Additions carried", fmt: "money" }, { k: "closing", label: "Closing WDV", fmt: "money" },
      { label: "", v: (r) => r.locked ? "Locked" : "" }], d.pools,
    { search: false, name: "tax_pools", title: "Schedule 2 depreciation " + d.fy,
      totals: ["opening", "additions_total", "disposals", "depreciation", "balancing_charge", "terminal_loss", "closing"],
      onRow: (r) => modal("Pool " + r.pool + " additions", table([{ k: "date", label: "Date" }, { k: "amount", label: "Cost", fmt: "money" },
        { k: "factor", label: "Share this year" }, { k: "counted", label: "Counted", fmt: "money" }], r.additions, { search: false }), []) }));
    faAdd(holder, h("p", { class: "hint" }, "Bought Shrawan–Poush: full; Magh–Chaitra: 2/3; Baishakh–Ashad: 1/3 — the rest joins next year's base. "
      + "Repairs up to 7% of the base are deductible (Sec 16); the excess is added to the pool."));
    faAdd(holder, h("div", { class: "panel" }, h("h2", {}, "Deferred tax (NAS 12)"),
      table([{ k: "l", label: "" }, { k: "v", label: "Amount", fmt: "money" }], [
        { l: "Carrying amount of PPE", v: dt.carrying }, { l: "Tax base (pool closing)", v: dt.tax_base },
        { l: "Temporary difference", v: dt.difference }, { l: "Deferred tax @ " + dt.rate * 100 + "%", v: dt.net },
        { l: "Opening balance", v: dt.opening }, { l: "Movement to post", v: dt.movement }], { search: false, export: false }),
      can("assets", "approve") ? h("div", { class: "actions" },
        dt.posted ? h("span", { class: "muted" }, "Posted for " + dt.fy) :
          h("button", { class: "btn primary", onclick: async () => { await run("fa.deferred_post", v, "Deferred tax posted"); load(); } }, "Post deferred tax"),
        h("button", { class: "btn", onclick: async () => { await run("fa.tax_lock", v, "Pools locked for " + d.fy); load(); } }, "Lock pools as filed")) : null));
  };
  root.append(pageHead("Tax depreciation", "Income Tax Act 2058 Schedule 2 pools A–E, worked from the capital register, and the deferred tax on the book–tax difference."),
    filterBar([{ k: "fy", label: "Income year", ph: "2082/83" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

/* ── equipment costing ── */
PAGES["fa/costing"] = async (root) => {
  let v = { fy: "", month: faMonth() };
  const holder = h("div");
  const load = async () => {
    const [led, al, tu] = await Promise.all([run("fa.ledger", v), run("fa.alloc_preview", v), run("fa.trueup_preview", v)]);
    holder.innerHTML = "";
    faAdd(holder, summaryStrip([["Actual equipment cost", fmtMoney(led.totals.actual)], ["Charged to projects", fmtMoney(led.totals.charged)],
      ["Hours charged", fmtQty(led.totals.hours)], ["Over / under recovered", fmtMoney(led.totals.variance)],
      ["To charge this month", fmtMoney(al.total)]]));
    const cols = [{ k: "code", label: "Machine" }, { k: "abc", label: "ABC" }]
      .concat(led.categories.map(([k, l]) => ({ k, label: l, fmt: "money" })))
      .concat([{ k: "actual", label: "Actual", fmt: "money" }, { k: "charged", label: "Charged", fmt: "money" },
        { k: "hours", label: "Hours", fmt: "qty" }, { k: "actual_per_hour", label: "Actual / h", fmt: "money" },
        { k: "variance", label: "Under (+) / over (−)", fmt: "money" }]);
    faAdd(holder, h("h2", { class: "sec" }, "Equipment ledger " + led.fy),
      table(cols, led.rows, { name: "equipment_ledger", title: "Equipment cost ledger " + led.fy,
        totals: led.categories.map(([k]) => k).concat(["actual", "charged", "hours", "variance"]),
        onRow: (r) => faRateDialog(r.fa_id, r.code, load) }));
    faAdd(holder, h("h2", { class: "sec" }, "Machine hours to charge — " + al.month),
      table([{ k: "code", label: "Machine" }, { label: "Project", v: (r) => nm.pcode(r.project_id) },
        { k: "hours", label: "Hours", fmt: "qty" }, { k: "rate", label: "Rate / h", fmt: "money" }, { k: "amount", label: "Charge", fmt: "money" }],
      al.rows, { search: false, totals: ["hours", "amount"], empty: "Nothing to charge.", rowClass: (r) => r.no_rate ? "flag" : "" }),
      can("assets", "approve") && al.rows.length ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        await run("fa.alloc_run", v, (x) => "Charged " + fmtMoney(x.total)); load(); } }, "Charge projects for " + al.month)) : null);
    faAdd(holder, h("h2", { class: "sec" }, "Year-end true-up " + tu.fy),
      table([{ k: "code", label: "Machine" }, { k: "actual", label: "Actual", fmt: "money" }, { k: "charged", label: "Charged", fmt: "money" },
        { k: "variance", label: "Variance", fmt: "money" }, { k: "status", label: "" },
        { label: "By project", v: (r) => Object.keys(r.by_job).map((p) => nm.pcode(p) + " " + fmtMoney(r.by_job[p])).join(" · ") }],
      tu.rows, { search: false, totals: ["actual", "charged", "variance"], empty: "No charges this year." }),
      can("assets", "approve") && tu.rows.length && !tu.posted ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
        await run("fa.trueup_run", v, (x) => "Variance " + fmtMoney(x.variance) + " spread over " + x.projects + " projects"); load(); } }, "Post the true-up")) : null);
  };
  root.append(pageHead("Equipment costing",
    "Peterson's equipment ledger: every cost of owning and running each machine, charged to projects at an hourly rate from the logsheets, "
    + "and trued up to actual at year end. Click a machine to work out its owning and operating rate."),
  filterBar([{ k: "fy", label: "Income year", ph: "2082/83" }, { k: "month", label: "Charge month", type: "month" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

function faRateDialog(id, code, done) {
  const f = form([
    { k: "annual_hours", label: "Budget hours a year", type: "number", default: 1800 },
    { k: "interest_rate", label: "Interest on investment", type: "number", default: 0.10 },
    { k: "insurance_tax_pct", label: "Insurance, tax, storage (% of avg investment)", type: "number", default: 0.025 },
    { k: "vehicle_tax", label: "Annual vehicle tax", type: "number" },
    { k: "repair_pct_of_dep", label: "Repairs as % of depreciation", type: "number", default: 0.8 },
    { k: "fuel_lph", label: "Fuel (litres / hour)", type: "number" }, { k: "fuel_price", label: "Diesel price / litre", type: "number" },
    { k: "lube_pct_of_fuel", label: "Lubricants (% of fuel)", type: "number", default: 0.15 },
    { k: "tyre_cost", label: "Tyre / wear part set cost", type: "number" }, { k: "tyre_life_hours", label: "Set life (hours)", type: "number" },
    { k: "operator_hr", label: "Operator / hour", type: "number" }, { k: "overhead_pct", label: "Overhead", type: "number", default: 0.10 },
    { k: "idle_allowance", label: "Idle allowance", type: "number", default: 0 },
  ], {});
  const out = h("div");
  const calc = async () => {
    const r = await run("fa.rate_calc", { id, params: f.values() });
    out.innerHTML = "";
    const rows = Object.entries(r.ownership).map(([k, x]) => ({ g: "Owning", k, x }))
      .concat(Object.entries(r.operating).map(([k, x]) => ({ g: "Operating", k, x })));
    out.append(table([{ k: "g", label: "" }, { label: "Item", v: (x) => x.k.replace(/_/g, " ") }, { k: "x", label: "Per hour", fmt: "money" }], rows,
      { search: false, export: false }),
    summaryStrip([["Cost / hour", fmtMoney(r.cost_per_hour)], ["Wet rate / hour", fmtMoney(r.rate_per_hour)], ["Dry rate / hour", fmtMoney(r.dry_rate_per_hour)]]));
  };
  modal("Owning & operating rate — " + code, h("div", {}, f, h("button", { class: "btn", onclick: calc }, "Work it out"), out),
    [{ label: "Save as the charge-out rate", cls: "primary", act: async () => {
      await run("fa.rate_save", { id, params: f.values(), update_equipment: true }, (x) => "Rate " + fmtMoney(x.rate_per_hour) + " / h"); if (done) done(); } }]);
}

/* ── maintenance plan ── */
PAGES["fa/maint"] = async (root) => {
  let v = { fund: "" };
  const holder = h("div");
  const load = async () => {
    const d = await run("fa.maint_plan", v);
    holder.innerHTML = "";
    faAdd(holder, summaryStrip([["Machines", d.rows.length], ["Overdue", d.overdue],
      ["Class A", d.rows.filter((r) => r.abc === "A").length], ["Class B", d.rows.filter((r) => r.abc === "B").length],
      ["Class C", d.rows.filter((r) => r.abc === "C").length]]));
    faAdd(holder, table([{ k: "code", label: "Machine" }, { k: "name", label: "Description" }, { k: "abc", label: "ABC" },
      { k: "maintenance", label: "Maintenance level" }, { k: "safety_check", label: "Safety check" },
      { k: "inspection_due", label: "Inspection due" }, { k: "hour", label: "Hour meter", fmt: "qty" },
      { k: "service_due_at", label: "Service at", fmt: "qty" }, { k: "hours_left", label: "Hours left", fmt: "qty" },
      { k: "spares_pct", label: "Spares %", fmt: "num" }, { k: "budget", label: "Budget", fmt: "money" }, { k: "spent", label: "Spent", fmt: "money" }],
    d.rows, { name: "maint_plan", title: "Maintenance plan", totals: ["budget", "spent"],
      rowClass: (r) => (r.service_overdue || r.inspection_overdue) ? "flag" : "", onRow: (r) => faItemDialog(r.fa_id, load) }));
    faAdd(holder, h("p", { class: "hint" }, "A: Level I, priority repair, 100% spares, monthly safety check, 70% of the fund. "
      + "B: Level II, 80% spares, quarterly, 20%. C: Level III, repair later, no reserve, yearly, 10% (Wang 2022)."));
  };
  root.append(pageHead("Maintenance plan", "Preventive maintenance by ABC class, with the maintenance fund split 70 / 20 / 10."),
    filterBar([{ k: "fund", label: "Maintenance fund for the year", type: "number" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

/* ── leases ── */
PAGES["fa/leases"] = async (root) => {
  const holder = h("div");
  const load = async () => {
    const d = await run("fa.lease_list", {});
    holder.innerHTML = "";
    faAdd(holder, summaryStrip([["Leases", d.rows.length], ["Right-of-use assets", fmtMoney(d.rows.reduce((s, r) => s + (r.rou || 0), 0))],
      ["Lease liability", fmtMoney(d.rows.reduce((s, r) => s + (r.exempt ? 0 : r.balance || 0), 0))],
      ["Exempt (≤12 months / low value)", d.rows.filter((r) => r.exempt).length]]));
    faAdd(holder, table([{ k: "no", label: "No." }, { k: "description", label: "Machine / asset" }, { k: "lessor", label: "Lessor" },
      { k: "start_date", label: "From" }, { k: "term_months", label: "Months", fmt: "num" }, { k: "payment", label: "Payment", fmt: "money" },
      { label: "Rate", v: (r) => (r.rate * 100).toFixed(2) + "%" }, { label: "Treatment", v: (r) => r.exempt ? "Expense (exempt)" : "NFRS 16" },
      { k: "rou", label: "ROU asset", fmt: "money" }, { k: "balance", label: "Liability now", fmt: "money" },
      { k: "periods_posted", label: "Periods posted", fmt: "num" }, { k: "status", label: "Status", fmt: "status" }], d.rows,
    { name: "leases", title: "Lease register", onRow: (r) => faLeaseDialog(r.id, load) }));
  };
  root.append(pageHead("Leases (NFRS 16)", "Machines hired for more than 12 months go on the balance sheet as a right-of-use asset and a lease liability. "
    + "Shorter hires and low-value items are expensed as billed.",
  can("assets", "edit") ? h("button", { class: "btn primary", onclick: () => faLeaseDialog(null, load) }, "New lease") : null,
  can("assets", "approve") ? h("button", { class: "btn", onclick: async () => {
    await run("fa.lease_post_month", { month: faMonth() }, (x) => x.periods + " lease periods posted"); load(); } }, "Post interest & depreciation to this month") : null), holder);
  await load();
};

async function faLeaseDialog(id, done) {
  const d = id ? await run("fa.lease_get", { id }) : { lease: { periods_per_year: 12 }, rows: [] };
  const L = d.lease, ro = L.status === "active";
  const f = form([
    { k: "description", label: "Machine / asset", req: true, wide: true, readonly: ro }, { k: "lessor", label: "Lessor", readonly: ro },
    { k: "project_id", label: "Project", type: "select", options: () => S.L.projects.map((p) => [p.id, p.code]), readonly: ro },
    { k: "start_date", label: "Commencement", type: "date", req: true, readonly: ro },
    { k: "term_months", label: "Term (months)", type: "number", req: true, readonly: ro },
    { k: "payment", label: "Payment per period", type: "number", req: true, readonly: ro },
    { k: "periods_per_year", label: "Payments a year", type: "select", noBlank: true, options: [[12, "Monthly"], [4, "Quarterly"], [1, "Yearly"]], readonly: ro },
    { k: "rate", label: "Incremental borrowing rate % a year", type: "number", req: true, readonly: ro },
    { k: "in_advance", label: "Paid", type: "select", options: [[0, "In arrears"], [1, "In advance"]], readonly: ro },
    { k: "direct_costs", label: "Initial direct costs", type: "number", readonly: ro },
    { k: "low_value", label: "Low-value asset", type: "select", options: [[0, "No"], [1, "Yes"]], readonly: ro },
  ], Object.assign({}, L, { rate: L.rate ? L.rate * 100 : "" }));
  const sched = d.rows.length ? table([{ k: "period", label: "Period" }, { k: "date", label: "Date" }, { k: "opening", label: "Opening", fmt: "money" },
    { k: "interest", label: "Interest", fmt: "money" }, { k: "payment", label: "Payment", fmt: "money" }, { k: "closing", label: "Closing", fmt: "money" },
    { k: "rou_dep", label: "ROU depreciation", fmt: "money" }], d.rows, { search: false, totals: ["interest", "payment", "rou_dep"], name: "lease_schedule",
    title: "Lease schedule " + (L.no || "") }) : null;
  const btns = [];
  if (!ro && can("assets", "edit")) btns.push({ label: "Save", cls: "primary", act: async () => {
    const v = f.values(); v.in_advance = Number(v.in_advance) === 1; v.low_value = Number(v.low_value) === 1;
    await run("fa.lease_save", { row: Object.assign(id ? { id } : {}, v) }, (x) => x.exempt ? "Exempt — expensed" : "Liability " + fmtMoney(x.liability));
    if (done) done(); } });
  if (id && L.status === "draft" && can("assets", "approve")) btns.push({ label: "Recognise", act: async () => {
    await run("fa.lease_recognise", { id }, "Recognised"); if (done) done(); } });
  modal(id ? L.no + " " + L.description : "New lease", h("div", {}, f, sched), btns);
}

/* ── impairment watch ── */
PAGES["fa/impair"] = async (root) => {
  const d = await run("fa.impair_scan", {});
  root.append(pageHead("Impairment watch", "Machines idle past their threshold, or marked idle — NAS 36 asks for a recoverable-amount test when an indicator exists."),
    table([{ k: "code", label: "Machine" }, { k: "name", label: "Description" }, { k: "idle_days", label: "Idle days", fmt: "num" },
      { k: "threshold", label: "Threshold", fmt: "num" }, { k: "carrying", label: "Carrying", fmt: "money" }], d.rows,
    { name: "impairment_watch", title: "Impairment watch", empty: "No machine is past its idle threshold.",
      onRow: async (r) => { const g = await run("fa.get", { id: r.fa_id }); faImpairDialog(g.item); } }));
};

/* ── PPE movement note ── */
PAGES["fa/movement"] = async (root) => {
  await faPolicy();
  let v = { fy: "" };
  const holder = h("div");
  const load = async () => {
    const d = await run("fa.movement", v);
    holder.innerHTML = "";
    faAdd(holder, table([{ k: "name", label: "Class" }, { k: "cost_open", label: "Cost — opening", fmt: "money" },
      { k: "additions", label: "Additions", fmt: "money" }, { k: "disposals", label: "Disposals", fmt: "money" },
      { k: "cost_close", label: "Cost — closing", fmt: "money" }, { k: "dep_open", label: "Depreciation — opening", fmt: "money" },
      { k: "dep_year", label: "Charge for the year", fmt: "money" }, { k: "dep_disposed", label: "On disposals", fmt: "money" },
      { k: "impairment", label: "Impairment", fmt: "money" }, { k: "dep_close", label: "Depreciation — closing", fmt: "money" },
      { k: "nbv_open", label: "Carrying — opening", fmt: "money" }, { k: "nbv_close", label: "Carrying — closing", fmt: "money" }],
    d.rows, { search: false, name: "ppe_note", title: "Property, plant and equipment " + d.fy,
      totals: ["cost_open", "additions", "disposals", "cost_close", "dep_open", "dep_year", "dep_disposed", "impairment", "dep_close", "nbv_open", "nbv_close"] }));
  };
  root.append(pageHead("PPE note", "The movement schedule for the financial statements (NAS 16 para 73)."),
    filterBar([{ k: "fy", label: "Income year", ph: "2082/83" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

/* ── inventory analysis ── */
PAGES["fa/inventory"] = async (root) => {
  let v = { fy: "" };
  const holder = h("div");
  const load = async () => {
    const d = await run("fa.inv_analysis", v);
    holder.innerHTML = "";
    if (d.summary) faAdd(holder, summaryStrip(["A", "B", "C"].map((k) => ["Class " + k, d.summary[k].items + " items · " + d.summary[k].value_pct + "%"])
      .concat([["Cost formula", d.cost_formula === "FIFO" ? "FIFO" : "Weighted average"]])));
    faAdd(holder, table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "unit", label: "Unit" },
      { k: "annual_qty", label: "Used", fmt: "qty" }, { k: "annual_value", label: "Value", fmt: "money" }, { k: "cum_pct", label: "Cum %", fmt: "num" },
      { k: "abc", label: "ABC" }, { k: "ved", label: "VED" }, { k: "category", label: "Cat." }, { k: "control", label: "Control" },
      { k: "eoq", label: "EOQ", fmt: "qty" }, { k: "safety_stock", label: "Safety stock", fmt: "qty" }, { k: "reorder_point", label: "Reorder at", fmt: "qty" }],
    d.rows, { name: "inv_analysis", title: "Inventory ABC-VED " + d.fy, totals: ["annual_value"], empty: d.note,
      onRow: (r) => faInvPolicyDialog(r, load) }));
    faAdd(holder, h("p", { class: "hint" }, d.note || ""));
  };
  root.append(pageHead("Inventory analysis", "ABC by consumption value, VED by criticality, economic order quantity and reorder point per material "
    + "(Malik & Sharma 2022). Click a material to set its VED, lead time and ordering cost."),
  filterBar([{ k: "fy", label: "Income year", ph: "2082/83" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

function faInvPolicyDialog(r, done) {
  const f = form([
    { k: "ved", label: "VED", type: "select", noBlank: true, options: [["V", "Vital"], ["E", "Essential"], ["D", "Desirable"]] },
    { k: "lead_days", label: "Lead time (days)", type: "number" }, { k: "max_lead_days", label: "Worst lead time (days)", type: "number" },
    { k: "order_cost", label: "Cost of placing an order", type: "number" }, { k: "carrying_pct", label: "Carrying cost (% of value a year)", type: "number", default: 0.2 },
    { k: "safety", label: "Safety stock (blank = worked out)", type: "number" },
  ], { ved: r.ved, lead_days: r.lead_days });
  modal("Stock policy — " + (r.name || r.code), f, [{ label: "Save", cls: "primary", act: async () => {
    await run("fa.inv_policy_save", { row: Object.assign({ material_id: r.material_id }, f.values()) }, "Saved"); if (done) done(); } }], { narrow: true });
}

})();
