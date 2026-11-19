/* BuildCore 2.56 — People and payroll: Accounts › Payroll, Site work › Site attendance, Masters › Staff › One people list. */
(function () {
"use strict";
if (window.__bco256) return; window.__bco256 = true;
const M = (v) => (v == null ? "—" : fmtMoney(v));
const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
const projects = () => ((S.L && S.L.projects) || []).filter((p) => !p.kind || p.kind === "project");
const pidNow = () => S.project || (projects()[0] || {}).id;
const projSel = (val, onch) => h("select", { onchange: (e) => onch(Number(e.target.value)) }, projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(val) }, p.code + " · " + p.name)));
const bankSel = () => h("select", {}, opt.money().map(([v, l]) => h("option", { value: v }, l)));
const num = (v, w) => h("input", { type: "number", step: "any", value: v == null ? "" : v, style: "width:" + (w || 90) + "px" });
const addTabs = (route, title, sub, first, list) => {
  window.BCO_TABS = window.BCO_TABS || {};
  if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
  else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
};
const csv = (name, rows, cols) => {
  const esc = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const text = [cols.map((c) => c[1]).join(",")].concat(rows.map((r) => cols.map((c) => esc(r[c[0]])).join(","))).join("\r\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/csv" })), download: name });
  document.body.append(a); a.click(); a.remove();
};

/* ═════════════ Accounts › Payroll ═════════════ */
PAGES["py/payroll"] = async (root, params) => {
  root.append(pageHead("Payroll", "Salaries with Nepal income-tax slabs, allowances, overtime, festival allowance, SSF / provident fund / CIT, advances, payslips and the bank list. The salary of each person is split over the projects they were marked present on (Site attendance)."));
  root.append(tabs([["This month", monthTab], ["Pay details", detailsTab], ["Advances", advancesTab], ["Payslips & bank list", slipsTab], ["Settings & tax slabs", settingsTab]],
    params && params.tab ? Number(params.tab) : 0));
};

async function monthTab() {
  const box = h("div");
  let month = null;
  const load = async () => {
    const d = await api("py.month", month ? { month } : {});
    month = d.month;
    box.replaceChildren();
    box.append(h("div", { class: "bar" }, lbl("Month", h("select", { onchange: (e) => { month = e.target.value; load(); } }, d.months.map((x) => h("option", { value: x.key, selected: x.key === d.month }, x.label)))),
      h("span", { class: "hint" }, d.from + " to " + d.to + " · " + d.days + " days")));
    if (!d.on) box.append(h("div", { class: "sf-banner" }, "The full payroll is off on this company: the Staff salaries tab still posts the monthly rate with a flat tax. This page shows what the full payroll would post. Accounts turns it on under Settings & tax slabs."));
    if (d.old_run) box.append(h("div", { class: "sf-banner" }, "This month was posted by the earlier salary run (monthly rate, flat tax). The lines below only show what the full payroll would have posted; nothing changes."));
    if (d.is_payroll_run) box.append(h("p", { class: "hint" }, "Posted by the payroll: the lines are as posted."));
    const t = d.total;
    box.append(summaryStrip([["Gross", M(t.gross)], ["Tax (TDS)", M(t.tax)], ["SSF / PF employee", M(t.ee)], ["Employer share", M(t.er)], ["Gratuity", M(t.gratuity)], ["Advances recovered", M(t.advance)], ["Net pay", M(t.net)], ["Cost to company", M(t.cost)]]));
    const inputs = {};
    const editable = d.can_edit && !d.run;
    const cols = [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { label: "Projects", v: (x) => h("span", { title: x.split_basis }, x.split.map((s) => s.project + (x.split.length > 1 ? " " + Math.round(s.share * 100) + "%" : "")).join(", ")) },
      { k: "basic", label: "Basic", fmt: "money" },
      { label: "Unpaid days", v: (x) => editable ? (inputs[x.staff_id] = inputs[x.staff_id] || {}, inputs[x.staff_id].unpaid_days = num((d.inputs[x.staff_id] || {}).unpaid_days ?? null, 60), inputs[x.staff_id].unpaid_days.placeholder = String(x.unpaid_days), inputs[x.staff_id].unpaid_days) : String(x.unpaid_days) },
      { label: "OT hours", v: (x) => editable ? (inputs[x.staff_id].ot_hours = num((d.inputs[x.staff_id] || {}).ot_hours ?? null, 60), inputs[x.staff_id].ot_hours.placeholder = String(x.ot_hours), inputs[x.staff_id].ot_hours) : String(x.ot_hours) },
      { label: "Festival", v: (x) => editable ? (inputs[x.staff_id].festival = h("input", { type: "checkbox", checked: !!(d.inputs[x.staff_id] || {}).festival }), inputs[x.staff_id].festival) : (x.festival ? "✓" : "") },
      { label: "Advance back", v: (x) => editable ? (inputs[x.staff_id].advance_recovery = num((d.inputs[x.staff_id] || {}).advance_recovery ?? null, 80), inputs[x.staff_id].advance_recovery.placeholder = String(x.advance), inputs[x.staff_id].advance_recovery) : M(x.advance) },
      { label: "Other deduction", v: (x) => editable ? (inputs[x.staff_id].other_deduction = num((d.inputs[x.staff_id] || {}).other_deduction || "", 80), inputs[x.staff_id].other_deduction) : M(x.other) },
      { k: "gross", label: "Gross", fmt: "money" }, { label: "SSF/PF", v: (x) => M(x.ee) }, { k: "cit", label: "CIT", fmt: "money" }, { k: "tax", label: "Tax", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "cost", label: "Cost", fmt: "money" }];
    box.append(h("p", { class: "hint" }, "Blank boxes take the figure shown in grey: unpaid days and overtime from Site attendance, advance recovery from the advance's monthly amount. Hover the projects to see how the split was made."),
      table(cols, d.lines, { name: "py_month", search: false, totals: ["gross", "cit", "tax", "net", "cost"] }));
    const bar = h("div", { class: "actions" });
    if (editable) {
      bar.append(h("button", { class: "btn", onclick: async () => {
        const rows = Object.entries(inputs).map(([sid, f]) => ({ staff_id: Number(sid), unpaid_days: f.unpaid_days.value, ot_hours: f.ot_hours.value, festival: f.festival.checked ? 1 : 0,
          advance_recovery: f.advance_recovery.value, other_deduction: f.other_deduction.value }));
        await run("py.input_save", { month, rows }, "Saved"); load();
      } }, "Save and recalculate"));
      if (d.on) bar.append(h("button", { class: "btn primary", onclick: async () => {
        if (!(await ask("Post salaries", "Post the payroll for " + d.label + "? Net " + M(t.net) + ", cost " + M(t.cost) + ". Save first if you changed a box."))) return;
        await run("py.run", { month }, (x) => "Posted, net " + fmtMoney(x.net)); load();
      } }, "Post the payroll"));
    }
    if (d.run) bar.append(h("span", {}, "Run for " + d.label + ": " + (d.run.status === "paid" ? "paid " + d.run.paid_date : "posted, not paid") + (d.run.vno ? " · voucher " + d.run.vno : "") + ". "),
      h("a", { href: "#/acc/payments?tab=2" }, "Pay it in Payments › Staff salaries ›"));
    box.append(bar);
  };
  await load();
  return box;
}

async function detailsTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("py.staff", {});
    box.replaceChildren(h("p", { class: "hint" }, "Basic salary defaults to the monthly rate on the staff card. SSF: employee 11 %, employer 20 % of basic (no separate gratuity). Provident fund: 10 % + 10 %, plus gratuity 8.33 %. None: gratuity 8.33 % only."),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "designation", label: "Designation" }, { k: "project", label: "Project" },
        { label: "Basic", v: (r) => M(r.basic ?? r.monthly_rate) }, { label: "Allowances", v: (r) => M((r.allow_site || 0) + (r.allow_field || 0) + (r.allow_fuel || 0) + (r.allow_mobile || 0) + (r.allow_other || 0)) },
        { label: "Scheme", v: (r) => ({ ssf: "SSF", pf: "Provident fund", none: "None" })[r.scheme || "none"] }, { label: "Status", v: (r) => (r.marital || "single") + (r.female ? ", woman" : "") },
        { label: "Bank", v: (r) => r.bank_acno ? (r.bank_name || "") + " " + r.bank_acno : h("span", { class: "red" }, "no account") }, { k: "advance_open", label: "Advance open", fmt: "money" },
        { label: "", v: (r) => can("accounts", "edit") ? h("button", { class: "btn small", onclick: () => editStaff(r, load) }, "Edit") : "" }], d.rows, { name: "py_staff" }));
  };
  await load();
  return box;
}

function editStaff(r, done) {
  const f = form([{ k: "basic", label: "Basic salary a month (blank = monthly rate " + (r.monthly_rate || 0) + ")", type: "number" },
    { k: "allow_site", label: "Site allowance", type: "number" }, { k: "allow_field", label: "Field / remote allowance", type: "number" }, { k: "allow_fuel", label: "Fuel allowance", type: "number" },
    { k: "allow_mobile", label: "Mobile allowance", type: "number" }, { k: "allow_other", label: "Other allowance", type: "number" },
    { k: "scheme", label: "Retirement scheme", type: "select", noBlank: true, options: [["none", "None (gratuity only)"], ["ssf", "Social Security Fund (SSF)"], ["pf", "Provident fund + gratuity"]] },
    { k: "cit", label: "CIT a month", type: "number" }, { k: "life_ins", label: "Life insurance premium a year", type: "number" }, { k: "health_ins", label: "Health insurance premium a year", type: "number" },
    { k: "marital", label: "Tax status", type: "select", noBlank: true, options: [["single", "Single"], ["married", "Married (couple)"]] }, { k: "female", label: "Woman (10 % rebate when single)", type: "check" },
    { k: "pan", label: "PAN" }, { k: "bank_name", label: "Bank" }, { k: "bank_acno", label: "Account number" }],
    { basic: r.basic ?? "", allow_site: r.allow_site || "", allow_field: r.allow_field || "", allow_fuel: r.allow_fuel || "", allow_mobile: r.allow_mobile || "", allow_other: r.allow_other || "",
      scheme: r.scheme || "none", cit: r.cit || "", life_ins: r.life_ins || "", health_ins: r.health_ins || "", marital: r.marital || "single", female: r.female ? 1 : 0, pan: r.pan || "", bank_name: r.bank_name || "", bank_acno: r.bank_acno || "" });
  modal("Pay details: " + r.name, f, [{ label: "Save", cls: "primary", act: async () => { const v = f.values(); await run("py.staff_save", Object.assign(v, { staff_id: r.staff_id, female: v.female ? 1 : 0 }), "Saved"); done(); } }]);
}

async function advancesTab() {
  const box = h("div");
  const load = async () => {
    const [d, st] = await Promise.all([api("py.advances", {}), api("py.staff", {})]);
    box.replaceChildren();
    if (can("accounts", "edit")) {
      const who = h("select", {}, st.rows.filter((r) => r.active !== 0).map((r) => h("option", { value: r.staff_id }, r.code + " · " + r.name)));
      const amt = num("", 110), mon = num("", 110), bank = bankSel(), note = h("input", { placeholder: "Reason" });
      box.append(h("div", { class: "panel" }, h("h3", {}, "Give a salary advance"), h("div", { class: "bar" }, lbl("Staff", who), lbl("Amount", amt), lbl("Recover a month", mon), lbl("Pay from", bank), lbl("Note", note),
        h("button", { class: "btn primary", onclick: async () => { await run("py.advance_give", { staff_id: who.value, amount: amt.value, monthly: mon.value, bank_account_id: bank.value, note: note.value }, "Advance paid"); load(); } }, "Pay advance"))));
    }
    box.append(table([{ k: "date", label: "Date" }, { k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "amount", label: "Advance", fmt: "money" }, { k: "monthly", label: "A month", fmt: "money" },
      { k: "open", label: "Still open (person)", fmt: "money" }, { k: "note", label: "Note" }, { k: "vno", label: "Voucher" }], d.rows, { name: "py_adv", empty: "No salary advances." }));
  };
  await load();
  return box;
}

async function slipsTab() {
  const box = h("div");
  let month = null;
  const load = async () => {
    const m = await api("py.month", month ? { month } : {});
    month = m.month;
    const d = await api("py.payslips", { month });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Month", h("select", { onchange: (e) => { month = e.target.value; load(); } }, m.months.map((x) => h("option", { value: x.key, selected: x.key === month }, x.label)))),
      h("span", { class: "hint" }, d.state)));
    const slips = h("div");
    d.lines.forEach((x) => {
      const row = (k, v) => h("tr", {}, h("td", {}, k), h("td", { style: "text-align:right" }, v));
      slips.append(h("div", { class: "panel", style: "break-inside:avoid;margin-bottom:12px" },
        h("h3", {}, "Payslip — " + d.label + (d.company ? " · " + d.company : "")), h("div", {}, h("b", {}, x.code + " " + x.name), " · " + (x.designation || "") + (x.pan ? " · PAN " + x.pan : "")),
        h("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:16px" },
          h("table", { class: "tbl" }, h("tbody", {}, row("Basic (" + (x.days - x.unpaid_days) + " of " + x.days + " days)", M(x.earned_basic)), row("Allowances", M(x.allowances)), row("Overtime (" + x.ot_hours + " h)", M(x.ot)),
            x.festival ? row("Festival allowance", M(x.festival)) : null, row(h("b", {}, "Gross"), h("b", {}, M(x.gross))))),
          h("table", { class: "tbl" }, h("tbody", {}, row(x.scheme === "ssf" ? "SSF (11 %)" : x.scheme === "pf" ? "Provident fund" : "Retirement", M(x.ee)), row("CIT", M(x.cit)), row("Income tax", M(x.tax)),
            row("Advance recovered", M(x.advance)), row("Other deductions", M(x.other)), row(h("b", {}, "Net pay"), h("b", {}, M(x.net)))))),
        h("div", { class: "hint" }, "Employer contributions: " + M(x.er) + (x.gratuity ? " · gratuity provision " + M(x.gratuity) : "") + " · Bank: " + (x.bank_name || "—") + " " + (x.bank_acno || ""))));
    });
    box.append(h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => printFrame("Payslips " + d.label, slips) }, "Print payslips"),
      h("button", { class: "btn", onclick: () => csv("bank_list_" + month + ".csv", d.bank_list, [["code", "Code"], ["name", "Name"], ["bank_name", "Bank"], ["bank_acno", "Account"], ["amount", "Amount"]]) }, "Bank list (CSV)"),
      h("span", { class: "hint" }, d.bank_list.filter((x) => !x.bank_acno).length + " without a bank account")), slips);
  };
  await load();
  return box;
}

async function settingsTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("py.settings", {});
    const v = d.values;
    const f = form([["py_ssf_ee", "SSF employee %"], ["py_ssf_er", "SSF employer %"], ["py_pf_ee", "Provident fund employee %"], ["py_pf_er", "Provident fund employer %"], ["py_gratuity", "Gratuity % (not for SSF)"],
      ["py_ret_cap", "Retirement deduction cap a year"], ["py_life_cap", "Life insurance cap"], ["py_health_cap", "Health insurance cap"], ["py_female_rebate", "Rebate for single women %"],
      ["py_ot_factor", "Overtime factor"], ["py_hours_day", "Hours a day"], ["py_days_month", "Days a month for the hourly rate"]].map(([k, l]) => ({ k, label: l, type: "number" })), v);
    const slabBox = (kind) => {
      const rows = d.slabs[kind].map(([w, r]) => [num(w, 120), num(r, 70)]);
      const t = h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, h("th", {}, "Width of slab (blank = the rest)"), h("th", {}, "Rate %"))), h("tbody", {}, rows.map(([a, b]) => h("tr", {}, h("td", {}, a), h("td", {}, b)))));
      t.read = () => rows.map(([a, b]) => [a.value === "" ? null : Number(a.value), Number(b.value)]);
      return t;
    };
    const sS = slabBox("single"), sM = slabBox("married");
    const appr = can("accounts", "approve");
    box.replaceChildren(h("p", { class: "hint" }, d.note),
      h("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px" }, h("div", {}, h("h3", {}, "Single"), sS), h("div", {}, h("h3", {}, "Married (couple)"), sM)),
      h("h3", {}, "Rates"), f,
      appr ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("py.settings_save", Object.assign(f.values(), { slabs: { single: sS.read(), married: sM.read() } }), "Saved"); load(); } }, "Save"),
        h("div", { class: "grow" }), h("span", {}, "Full payroll: ", h("b", {}, d.on ? "On" : "Off")),
        h("button", { class: "btn" + (d.on ? "" : " primary"), onclick: async () => {
          if (!(await ask(d.on ? "Switch off? Salary runs go back to the monthly rate with a flat tax." : "Switch on? From the next run, salaries are posted with the tax slabs, allowances, SSF / PF / CIT, gratuity and advances, and split over projects by attendance. Runs already posted do not change."))) return;
          await run("py.settings_save", { on: d.on ? 0 : 1 }); load();
        } }, d.on ? "Switch off" : "Switch on")) : h("p", { class: "hint" }, "Accounts (approve) changes these."));
  };
  await load();
  return box;
}

/* ═════════════ Site work › Site attendance ═════════════ */
PAGES["py/attendance"] = async (root, params) => {
  root.append(pageHead("Site attendance", "Who was on site each day: staff and workers present, half day, absent or on leave, with overtime. Feeds the payroll (days, overtime, salary split by project) and the check against the DPR."));
  root.append(tabs([["Mark the day", dayTab], ["Month", attMonthTab], ["Attendance against DPR", vsDprTab]], params && params.tab ? Number(params.tab) : 0));
};

async function dayTab() {
  const box = h("div");
  let pid = pidNow(), dt = today();
  const load = async () => {
    box.replaceChildren(h("p", { class: "hint" }, "Loading…"));
    const d = await api("py.att_day", { project_id: pid, date: dt });
    const din = h("input", { type: "date", value: dt, max: today(), onchange: (e) => { dt = e.target.value; load(); } });
    const sel = {};
    const marks = d.statuses;
    const rows = d.rows.map((r) => {
      const s = h("select", { disabled: !d.can_edit }, h("option", { value: "" }, "—"), marks.map(([k, l]) => h("option", { value: k, selected: r.status === k }, l)));
      const ot = num(r.ot_hours || "", 60); ot.disabled = !d.can_edit;
      sel[r.kind + ":" + r.person_id] = { r, s, ot };
      return h("tr", {}, h("td", {}, r.kind === "staff" ? "Staff" : "Worker"), h("td", {}, r.code || ""), h("td", {}, r.name), h("td", {}, r.trade || ""), h("td", {}, s), h("td", {}, ot));
    });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(pid, (v) => { pid = v; load(); })), lbl("Date", din),
      h("span", {}, "Present: ", h("b", {}, String(d.present)), " · on the DPR (all gangs): ", h("b", {}, String(d.dpr_heads)))),
      d.rows.length ? h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["", "Code", "Name", "Trade / designation", "Mark", "OT hours"].map((x) => h("th", {}, x)))), h("tbody", {}, rows))
        : h("p", { class: "panel" }, "No staff or workers on this project. Staff come from Masters › Staff (their project), workers from Workers & safety."),
      d.can_edit && d.rows.length ? h("div", { class: "actions" },
        h("button", { class: "btn", onclick: () => { Object.values(sel).forEach((x) => { if (!x.s.value) x.s.value = "P"; }); } }, "Mark the rest present"),
        h("button", { class: "btn primary", onclick: async () => {
          const out = Object.values(sel).map((x) => ({ kind: x.r.kind, person_id: x.r.person_id, name: x.r.name, trade: x.r.trade, status: x.s.value, ot_hours: x.ot.value }));
          await run("py.att_save", { project_id: pid, date: dt, rows: out }, (x) => x.saved + " marked"); load();
        } }, "Save attendance")) : null);
  };
  await load();
  return box;
}

async function attMonthTab() {
  const box = h("div");
  let pid = pidNow(), month = null;
  const load = async () => {
    const d = await api("py.att_month", month ? { project_id: pid, month } : { project_id: pid });
    month = d.month;
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(pid, (v) => { pid = v; load(); })),
      lbl("Month", h("select", { onchange: (e) => { month = e.target.value; load(); } }, d.months.map((x) => h("option", { value: x.key, selected: x.key === month }, x.label))))),
      table([{ label: "", v: (r) => r.kind === "staff" ? "Staff" : "Worker" }, { k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "p", label: "Present", fmt: "num" }, { k: "hd", label: "Half days", fmt: "num" },
        { k: "ab", label: "Absent", fmt: "num" }, { k: "lv", label: "Leave", fmt: "num" }, { k: "off", label: "Off", fmt: "num" }, { k: "days", label: "Days worked", fmt: "num" }, { k: "ot", label: "OT hours", fmt: "num" }],
      d.rows, { name: "py_att_month", empty: "No attendance marked in " + d.label + "." }));
  };
  await load();
  return box;
}

async function vsDprTab() {
  const box = h("div");
  let pid = pidNow(), month = null;
  const load = async () => {
    const d = await api("py.att_vs_dpr", month ? { project_id: pid, month } : { project_id: pid });
    month = d.month;
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(pid, (v) => { pid = v; load(); })),
      lbl("Month", h("select", { onchange: (e) => { month = e.target.value; load(); } }, d.months.map((x) => h("option", { value: x.key, selected: x.key === month }, x.label))))),
      h("p", { class: "hint" }, d.note),
      summaryStrip([["Head-days on DPRs", String(d.dpr_heads)], ["Head-days present", String(d.att_heads)], ["DPR wages", M(d.dpr_amount)], ["Wage sheet", d.wage_sheet == null ? "not made" : M(d.wage_sheet)]]),
      table([{ k: "date", label: "Date" }, { k: "dpr", label: "On DPR", fmt: "num" }, { k: "attendance", label: "Present", fmt: "num" }, { k: "difference", label: "Difference", fmt: "num" },
        { k: "dpr_amount", label: "DPR wages", fmt: "money" }, { label: "", v: (r) => r.flag ? h("span", { class: r.flag === "DPR higher" ? "red" : "hint" }, r.flag) : "✓" }], d.rows, { name: "py_vs", empty: "No DPR labour or attendance in this month." }));
  };
  await load();
  return box;
}

/* ═════════════ Masters › Staff › One people list ═════════════ */
async function peopleTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("py.people", {});
    const edit = can("masters", "edit");
    box.replaceChildren(h("p", { class: "hint" }, "One person, one record: each staff member is linked to their worker card (Workers & safety: SSF number, insurance, bank) and their user login. Suggestions come from the same name or phone. " +
      d.workers_unlinked + " worker card(s) are not linked to a staff member (daily-wage workers need no link)."),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "designation", label: "Designation" }, { k: "project", label: "Project" },
        { label: "Worker card", v: (r) => r.worker ? (r.worker.code || "") + " " + r.worker.name : r.suggest_worker && edit ? h("button", { class: "btn small", onclick: async () => { await run("py.people_link", { staff_id: r.staff_id, worker_id: r.suggest_worker.id }, "Linked"); load(); } }, "Link " + r.suggest_worker.name) : "—" },
        { label: "User login", v: (r) => r.user ? r.user.username : r.suggest_user && edit ? h("button", { class: "btn small", onclick: async () => { await run("py.people_link", { staff_id: r.staff_id, user_id: r.suggest_user.id }, "Linked"); load(); } }, "Link " + r.suggest_user.username) : "—" },
        { label: "Pay details", v: (r) => r.pay_details ? "✓" : "—" }, { label: "Bank", v: (r) => r.bank ? "✓" : h("span", { class: "red" }, "missing") },
        { label: "", v: (r) => edit ? h("button", { class: "btn small", onclick: () => linkDlg(r, d, load) }, "Change") : "" }], d.rows, { name: "py_people" }));
  };
  await load();
  return box;
}
function linkDlg(r, d, done) {
  const f = form([{ k: "worker_id", label: "Worker card", type: "select", noBlank: true, options: [["", "— none —"]].concat(d.workers.map((w) => [String(w.id), w.label])) },
    { k: "user_id", label: "User login", type: "select", noBlank: true, options: [["", "— none —"]].concat(d.user_list.map((x) => [String(x.id), x.label])) }],
    { worker_id: r.worker ? String(r.worker.id) : "", user_id: r.user ? String(r.user.id) : "" });
  modal("Link " + r.name, f, [{ label: "Save", cls: "primary", act: async () => { await run("py.people_link", Object.assign({ staff_id: r.staff_id }, f.values()), "Saved"); done(); } }], { narrow: true });
}
const goPeople = () => addTabs("m/staff", "Staff", "Employees: designation, rates and project.", "Staff", [["One people list", peopleTab]]);
if (PAGES["m/staff"]) goPeople(); else window.addEventListener("load", goPeople);
})();
