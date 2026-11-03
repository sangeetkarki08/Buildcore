/* BuildCore 2.40 — Money end to end.
   New tabs only; the menu, module names and groups are unchanged:
     Accounts › Payments & receipts ........... Wages · Staff salaries · Petty cash · Money settings
     Accounts › Bank reconciliation ........... Statement import
     Fixed assets › Capital register ........... Machine purchases · Link to ledger
     Accounts › Cash forecast & ratios ......... Loan register (one register: machine loans from Equipment finance) */
(function () {
  "use strict";
  if (window.__bcoMoney) return;
  window.__bcoMoney = true;

  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const M = (v) => (v == null ? "—" : fmtMoney(v));
  const projSel = (val, onchange) => h("select", { onchange }, (S.L.projects || []).filter((p) => !p.kind || p.kind === "project")
    .map((p) => h("option", { value: p.id, selected: String(p.id) === String(val) }, p.code + " · " + p.name)));
  const pidNow = () => S.project || ((S.L.projects || []).find((p) => !p.kind || p.kind === "project") || {}).id;
  const bankSel = () => h("select", {}, opt.money().map(([v, l]) => h("option", { value: v }, l)));
  const dateIn = (v) => h("input", { type: "date", value: v || today(), style: "max-width:170px" });
  const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);

  /* ───────── Wages from the DPR ───────── */
  async function wagesTab() {
    const box = h("div");
    let pid = pidNow(), month = null;
    const load = async () => {
      const d = await api("mn.wage_sheet", { project_id: pid, month });
      month = d.month;
      box.innerHTML = "";
      const msel = h("select", { onchange: (e) => { month = e.target.value; load(); } }, d.months.map((x) => h("option", { value: x.key, selected: x.key === d.month }, x.label)));
      if (!d.months.find((x) => x.key === d.month)) msel.prepend(h("option", { value: d.month, selected: true }, d.label));
      box.append(h("div", { class: "bar" }, lbl("Project", projSel(pid, (e) => { pid = e.target.value; load(); })), lbl("Month", msel)));
      box.append(h("p", { class: "hint" }, "Own gangs' wages from the approved DPRs for " + d.label + " (" + d.from + " to " + d.to + "). The DPR already credited them to Wages Payable; paying the sheet clears that month. Gangs of petty contractors are paid on their bills."));
      box.append(summaryStrip([["DPR labour", M(d.dpr_total)], ["In Wages Payable", M(d.accrued)], ["Of which waiting in the posting queue", M(d.waiting)], ["Open wage advances", M(d.advance_open)]]));
      if (Math.abs(d.dpr_total - d.accrued) > 0.5) box.append(h("p", { class: "red" }, "The DPR labour and Wages Payable differ by " + M(d.dpr_total - d.accrued) + ". Check the DPR postings in the accounts queue."));
      box.append(h("h3", {}, "By trade"), table([{ k: "trade", label: "Trade" }, { k: "head_days", label: "Head-days", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" },
        { k: "ot_hours", label: "OT hours", fmt: "qty" }, { k: "amount", label: "Wages", fmt: "money" }], d.lines, { name: "wage_lines", search: false, totals: ["head_days", "hours", "ot_hours", "amount"], empty: "No own-gang labour on approved DPRs in this month." }));
      box.append(h("h3", {}, "Attendance by day"), table([{ k: "date", label: "Date" }, { k: "heads", label: "Workers", fmt: "qty" }, { k: "amount", label: "Wages", fmt: "money" }], d.attendance, { name: "wage_days", search: false, export: true }));
      const s = d.sheet;
      const edit = can("accounts", "edit");
      if (s && s.status !== "draft") box.append(h("div", { class: "panel" }, h("h3", {}, "Paid"), kv([["Sheet", s.no], ["Paid on", s.paid_date], ["Accrued", M(s.accrued)], ["Net paid", M(s.net)]])));
      else if (edit) {
        const f = form([{ k: "advance_recovery", label: "Advance recovered", type: "number" }, { k: "tax", label: "Tax deducted", type: "number" },
          { k: "other_deduction", label: "Other deductions held", type: "number" }, { k: "note", label: "Note", wide: true }], s || {});
        const bank = bankSel(), dt = dateIn();
        box.append(h("div", { class: "panel" }, h("h3", {}, s ? "Wage sheet " + s.no + " (draft, net " + M(s.net) + ")" : "Wage sheet"), f,
          h("div", { class: "actions" },
            h("button", { class: "btn", onclick: async () => { await run("mn.wage_sheet_save", Object.assign({ project_id: pid, month }, f.values()), (x) => "Saved, net " + fmtMoney(x.net)); load(); } }, "Save the sheet"),
            s ? h("span", {}, lbl("Pay from", bank), lbl("Date", dt), h("button", { class: "btn primary", onclick: async () => {
              if (!(await ask("Pay the wage sheet", "Pay " + fmtMoney(s.net) + " net and clear " + fmtMoney(s.accrued) + " of Wages Payable for " + d.label + "?"))) return;
              await run("mn.wage_sheet_pay", { id: s.id, bank_account_id: bank.value, date: dt.value }, "Wages paid"); load(); } }, "Pay")) : null)));
        const amt = h("input", { type: "number", style: "max-width:140px" }), b2 = bankSel();
        box.append(h("div", { class: "panel" }, h("h3", {}, "Wage advance"), h("div", { class: "bar" }, lbl("Amount", amt), lbl("From", b2),
          h("button", { class: "btn", onclick: async () => { await run("mn.wage_advance", { project_id: pid, amount: amt.value, bank_account_id: b2.value }, "Advance paid"); load(); } }, "Pay advance"))));
      }
      if (d.sheets.length) box.append(h("h3", {}, "Wage sheets"), table([{ k: "no", label: "Sheet" }, { k: "from_date", label: "From" }, { k: "to_date", label: "To" },
        { k: "accrued", label: "Accrued", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }, { k: "vno", label: "Voucher" }], d.sheets, { name: "wage_sheets", search: false }));
    };
    await load();
    return box;
  }

  /* ───────── Staff salaries ───────── */
  async function salaryTab() {
    const box = h("div");
    let month = null, ssf = false;
    const load = async () => {
      const d = await api("mn.salary", { month, ssf });
      month = d.month;
      box.innerHTML = "";
      const msel = h("select", { onchange: (e) => { month = e.target.value; load(); } }, d.months.map((x) => h("option", { value: x.key, selected: x.key === d.month }, x.label)));
      const cb = h("input", { type: "checkbox", checked: ssf, onchange: (e) => { ssf = e.target.checked; load(); } });
      box.append(h("div", { class: "bar" }, lbl("Month", msel), h("label", { class: "f" }, cb, h("span", {}, " Staff enrolled in SSF"))));
      box.append(h("p", { class: "hint" }, "Every active staff member with a monthly rate (Masters › Staff). Salary goes to labour cost on the person's project, or to head-office salaries when there is no project. Social security tax goes to TDS Payable; SSF (employee and employer shares) to SSF Payable. Rates are in Money settings."));
      box.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "project", label: "Project" }, { k: "gross", label: "Gross", fmt: "money" },
        { k: "tax", label: "Tax", fmt: "money" }, { k: "ssf_employee", label: "SSF employee", fmt: "money" }, { k: "ssf_employer", label: "SSF employer", fmt: "money" }, { k: "net", label: "Net pay", fmt: "money" }],
        d.lines, { name: "salary_lines", search: false, totals: ["gross", "tax", "ssf_employee", "ssf_employer", "net"], empty: "No active staff with a monthly rate." }));
      const edit = can("accounts", "edit");
      if (d.run) {
        const bank = bankSel(), dt = dateIn();
        box.append(h("div", { class: "panel" }, h("h3", {}, "Run for " + d.label + ": " + (d.run.status === "paid" ? "paid " + d.run.paid_date : "posted, not paid")), kv([["Gross", M(d.run.gross)], ["Net", M(d.run.net)]]),
          edit && d.run.status !== "paid" ? h("div", { class: "bar" }, lbl("Pay from", bank), lbl("Date", dt), h("button", { class: "btn primary", onclick: async () => { await run("mn.salary_pay", { id: d.run.id, bank_account_id: bank.value, date: dt.value }, "Salaries paid"); load(); } }, "Pay salaries")) : null));
      } else if (edit && d.lines.length) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        if (!(await ask("Run salaries", "Post salaries for " + d.label + "?"))) return;
        await run("mn.salary_run", { month, ssf }, (x) => "Posted, net " + fmtMoney(x.net)); load(); } }, "Post the salary run")));
      if (d.runs.length) box.append(h("h3", {}, "Runs"), table([{ k: "month", label: "Month" }, { k: "gross", label: "Gross", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }, { k: "vno", label: "Voucher" }], d.runs, { name: "salary_runs", search: false }));
    };
    await load();
    return box;
  }

  /* ───────── Petty cash ───────── */
  async function pettyTab() {
    const box = h("div");
    let sel = null;
    const load = async () => {
      const d = await api("mn.imprests", sel ? { imprest_id: sel } : {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Each site imprest has a holder, a float and its own ledger account. Slips post to the project's cost (with a BOQ item, or as site overhead) once the bill or receipt is attached. Replenishing brings the imprest back to its float. Slips waiting to be replenished show in the 13-week cash forecast."));
      box.append(table([{ k: "project", label: "Project" }, { k: "holder", label: "Holder" }, { k: "account", label: "Account" }, { k: "float_amount", label: "Float", fmt: "money" },
        { k: "balance", label: "Balance", fmt: "money" }, { k: "to_replenish", label: "To replenish", fmt: "money" }, { k: "slips_open", label: "Slips", fmt: "num" }],
        d.imprests, { name: "imprests", search: false, onRow: (r) => { sel = r.id; load(); }, empty: "No imprest yet." }));
      const edit = can("accounts", "edit");
      if (edit) {
        const f = form([{ k: "project_id", label: "Project", type: "select", options: opt.projects, req: true }, { k: "holder", label: "Holder", req: true },
          { k: "float_amount", label: "Float", type: "number", req: true }, { k: "bank_account_id", label: "From", type: "select", options: opt.money, req: true }], { project_id: pidNow() });
        box.append(h("details", {}, h("summary", {}, "Open a new imprest"), f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { const x = await run("mn.imprest_open", f.values(), "Imprest opened"); sel = x.id; load(); } }, "Open"))));
      }
      const im = d.imprests.find((x) => x.id === sel);
      if (!im) return;
      box.append(h("h3", {}, "Slips · " + im.project + " · " + im.holder));
      if (edit) {
        const f = form([{ k: "date", label: "Date", type: "date" }, { k: "amount", label: "Amount", type: "number", req: true }, { k: "description", label: "What for", wide: true },
          { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(im.project_id) }, { k: "overhead", label: "Site overhead (no BOQ item)", type: "check" },
          { k: "account_id", label: "Expense account", type: "select", options: () => d.expense_accounts.map((a) => [a.id, a.code + " " + a.name]) }], { date: today(), account_id: d.default_account });
        box.append(h("div", { class: "panel" }, f, h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("mn.slip_save", Object.assign({ imprest_id: im.id }, f.values()), "Slip saved: attach the bill, then post"); load(); } }, "Save slip"),
          im.to_replenish > 0 ? h("span", {}, (() => { const b = bankSel(); return [lbl("Replenish from", b), h("button", { class: "btn primary", onclick: async () => { await run("mn.replenish", { imprest_id: im.id, bank_account_id: b.value }, (x) => "Replenished " + fmtMoney(x.amount)); load(); } }, "Replenish " + fmtMoney(im.to_replenish))]; })()) : null)));
      }
      box.append(table([{ k: "no", label: "Slip" }, { k: "date", label: "Date" }, { k: "description", label: "What for" }, { k: "boq", label: "BOQ item" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "Bill", v: (r) => r.files ? "attached" : h("span", { class: "red" }, "missing") }, { k: "status", label: "Status", fmt: "status" },
        { label: "", v: (r) => r.replenish_voucher_id ? "replenished" : "" },
        { label: "", v: (r) => r.status === "draft" && edit ? h("span", {}, uploadButton({ entity: "mn_slip", entity_id: r.id, project_id: r.project_id }, load, "Attach"),
          h("button", { class: "btn small primary", onclick: async () => { await run("mn.slip_post", { id: r.id }, "Posted"); load(); } }, "Post")) : "" }],
      d.slips || [], { name: "slips", search: false }));
    };
    await load();
    return box;
  }

  /* ───────── Money settings ───────── */
  async function settingsTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("mn.settings", {});
      box.innerHTML = "";
      box.append(h("div", { class: "panel" }, h("h3", {}, "Supplier, subcontractor and hire payments need an approved payment request: " + (d.payreq_required ? "on since " + d.payreq_from : "off")),
        h("p", { class: "hint" }, "When on, Payments & receipts refuses a payment to a vendor or subcontractor unless it is paid from an approved request (Accounts › Payment requests). Receipts, wages, tax deposits and EMIs are not affected. Payments made without a request are listed in Financial data checks."),
        d.can_change ? h("div", { class: "actions" }, h("button", { class: "btn " + (d.payreq_required ? "" : "primary"), onclick: async () => {
          if (!(await ask(d.payreq_required ? "Allow direct payments again" : "Require payment requests", d.payreq_required ? "Payments to vendors and subcontractors can be made directly again." : "From today, vendor and subcontractor payments go through an approved payment request."))) return;
          await run("mn.settings_save", { payreq_required: !d.payreq_required }, "Saved"); load(); } }, d.payreq_required ? "Switch off" : "Switch on")) : null,
        d.direct_payments.length ? table([{ k: "no", label: "Payment" }, { k: "date", label: "Date" }, { k: "party", label: "Paid to" }, { k: "gross", label: "Amount", fmt: "money" }], d.direct_payments, { name: "direct_payments", search: false, title: "Paid without a request" }) : null));
      const f = form([{ k: "payreq_exempt_sub", label: "Subcontractors do not need a request", type: "check" }, { k: "payreq_min", label: "No request needed up to (amount)", type: "number" },
        { k: "sst_pct", label: "Social security tax on salaries %", type: "number" }, { k: "ssf_employee_pct", label: "SSF employee %", type: "number" }, { k: "ssf_employer_pct", label: "SSF employer %", type: "number" }],
      Object.assign({}, d, { payreq_exempt_sub: d.payreq_exempt.includes("subcontractor") }));
      box.append(h("div", { class: "panel" }, h("h3", {}, "Rates and exemptions"), f, d.can_change ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
        const v = f.values(); await run("mn.settings_save", { payreq_exempt: v.payreq_exempt_sub ? ["subcontractor"] : [], payreq_min: v.payreq_min, sst_pct: v.sst_pct, ssf_employee_pct: v.ssf_employee_pct, ssf_employer_pct: v.ssf_employer_pct }, "Saved"); load(); } }, "Save")) : null));
      if (d.history.length) box.append(h("h4", {}, "Changes"), table([{ k: "ts", label: "When" }, { k: "user", label: "Who" }, { k: "what", label: "What" }, { k: "value", label: "Set to" }], d.history, { name: "mn_hist", search: false, export: false }));
    };
    await load();
    return box;
  }

  /* ───────── Bank statement import ───────── */
  async function stmtTab() {
    const box = h("div");
    let imp = null;
    const bank = bankSel();
    const file = h("input", { type: "file", accept: ".csv,.txt,.xlsx" });
    const out = h("div");
    const show = async () => {
      out.innerHTML = "";
      const d = await api("mn.stmt_list", imp ? { import_id: imp } : { bank_account_id: bank.value });
      if (!imp && d.imports.length) imp = d.imports[0].import_id;
      const rows = d.rows.filter((r) => !imp || r.import_id === imp);
      out.append(summaryStrip([["Statement lines", rows.length], ["Matched", rows.filter((r) => r.status === "matched").length], ["Cleared", rows.filter((r) => r.status === "cleared").length], ["Not found in the books", rows.filter((r) => r.status === "open").length]]));
      out.append(table([{ k: "date", label: "Date" }, { k: "description", label: "Description" }, { k: "ref", label: "Cheque / ref" }, { k: "withdrawal", label: "Withdrawal", fmt: "money" }, { k: "deposit", label: "Deposit", fmt: "money" },
        { label: "Book entry", v: (r) => r.vno ? r.vno + " · " + r.vdate : (r.status === "open" ? h("span", { class: "red" }, "none — enter a voucher (bank charge, interest…)") : "") }, { k: "how", label: "Matched by" }, { k: "status", label: "Status", fmt: "status" },
        { label: "", v: (r) => r.status === "matched" ? h("button", { class: "btn small", onclick: async () => { await run("mn.stmt_match", { id: r.id }, "Unmatched"); show(); } }, "Unmatch") :
          (r.status === "open" ? h("button", { class: "btn small", onclick: () => pick(r) }, "Match…") : "") }], rows, { name: "stmt_lines", search: false }));
      if (rows.some((r) => r.status === "matched") && can("accounts", "edit")) out.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("mn.stmt_confirm", { import_id: imp }, (x) => x.cleared + " entries cleared"); show(); } }, "Confirm matches (clear these entries)")));
    };
    const pick = async (r) => {
      const c = await api("mn.stmt_candidates", { id: r.id });
      const m = modal("Match " + r.date + " " + fmtMoney(r.withdrawal || r.deposit), table([{ k: "no", label: "Voucher" }, { k: "date", label: "Date" }, { k: "vnar", label: "Narration" }, { k: "ref_no", label: "Ref" }, { k: "debit", label: "In", fmt: "money" }, { k: "credit", label: "Out", fmt: "money" },
        { label: "", v: (b) => h("button", { class: "btn small primary", onclick: async () => { await run("mn.stmt_match", { id: r.id, line_id: b.id }, "Matched"); m.close(); show(); } }, "This one") }], c, { search: false }), []);
    };
    box.append(h("p", { class: "hint" }, "Import the bank's statement (CSV, or Excel .xlsx). BuildCore finds the date, cheque/reference, withdrawal and deposit columns and matches each line to an uncleared entry: same amount and cheque or reference number first, then same amount within 7 days. Confirm to clear them; the tick-off on the first tab stays as it is."),
      h("div", { class: "bar" }, lbl("Bank account", bank), lbl("Statement file", file), h("button", { class: "btn primary", onclick: async () => {
        const f = file.files[0]; if (!f) { toast("Choose the statement file.", "err"); return; }
        const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.readAsDataURL(f); });
        const d = await run("mn.stmt_import", { bank_account_id: bank.value, filename: f.name, content: b64 }, (x) => x.matched + " of " + x.rows.length + " lines matched");
        imp = d.rows[0] && d.rows[0].import_id; show(); } }, "Import and match"),
      h("button", { class: "btn", onclick: () => { imp = null; show(); } }, "Show last import")), out);
    await show();
    return box;
  }

  /* ───────── Capital register: machine purchases and link to ledger ───────── */
  async function capitalTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("mn.capital_list", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Buying a machine on a purchase bill: mark the bill line (draft bills, lines without a goods receipt) as a new machine. When the bill is posted, BuildCore creates the machine in Equipment and in this register with the bill amount, debits Plant & Machinery with the machine, and starts its Equipment finance with the price."));
      box.append(table([{ k: "no", label: "Bill" }, { k: "date", label: "Date" }, { k: "party", label: "Supplier" }, { k: "project", label: "Project" }, { k: "description", label: "Line" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "New machine", v: (r) => r.machine_code ? r.machine_code + " " + r.machine_name : "" },
        { label: "", v: (r) => r.machine_code ? h("button", { class: "btn small", onclick: async () => { await run("mn.capital_unmark", { line_id: r.line_id }, "Unmarked"); load(); } }, "Unmark") :
          h("button", { class: "btn small primary", onclick: () => mark(r) }, "Mark as new machine") }], d.drafts, { name: "capital_drafts", search: false, empty: "No draft purchase bill lines without a goods receipt." }));
      if (d.machines.length) box.append(h("h3", {}, "Machines bought on bills"), table([{ k: "eq_code", label: "Machine" }, { k: "name", label: "Name" }, { k: "no", label: "Bill" }, { k: "date", label: "Date" }, { k: "purchase_value", label: "Cost", fmt: "money" }, { k: "bill_status", label: "Bill", fmt: "status" }], d.machines, { name: "capital_done", search: false }));
    };
    const mark = (r) => {
      const f = form([{ k: "code", label: "Machine code", req: true }, { k: "name", label: "Name", req: true }, { k: "category", label: "Category" }, { k: "life_years", label: "Life (years)", type: "number" },
        { k: "method", label: "Depreciation", type: "select", noBlank: true, options: [["sl", "Straight line"], ["wdv", "Written-down value"]] }, { k: "residual_pct", label: "Residual %", type: "number" },
        { k: "meter_type", label: "Meter", type: "select", noBlank: true, options: [["hour", "Hours"], ["km", "Kilometres"]] }], { name: r.description, category: "Earthmoving", life_years: 10, residual_pct: 5, method: "sl" });
      modal("New machine from " + r.no, f, [{ label: "Mark", cls: "primary", act: async () => { await run("mn.capital_mark", Object.assign({ line_id: r.line_id }, f.values()), "Marked: post the bill to create the machine"); load(); } }], { narrow: true });
    };
    await load();
    return box;
  }

  async function linkTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("mn.asset_links", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Each owned machine's register cost against the ledger lines on the fixed asset account that carry it. Where a machine was booked by a journal without the machine on the line, link that line here. Nothing is posted."));
      box.append(table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "register_cost", label: "Register cost", fmt: "money" }, { k: "ledger", label: "Ledger lines", fmt: "money" },
        { k: "difference", label: "Difference", fmt: "money" }, { k: "status", label: "Status" },
        { label: "Lines", v: (r) => r.lines.map((x) => x.no + " " + fmtMoney(x.amount) + (x.linked ? " (linked)" : "")).join(", ") },
        { label: "", v: (r) => d.can_link && r.candidates.length ? h("span", {}, r.candidates.slice(0, 3).map((x) => h("button", { class: "btn small", onclick: async () => { await run("mn.asset_link", { equipment_id: r.equipment_id, line_id: x.id }, "Linked"); load(); } }, "Link " + x.no + " " + fmtMoney(x.amount)))) : "" }],
      d.machines, { name: "asset_links", search: false }));
    };
    await load();
    return box;
  }

  /* ───────── Loan register ───────── */
  async function loanTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("mn.loans", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "One register. Machine loans come from Equipment finance (read-only here; the balance is the Equipment Loans ledger for that machine). A loan also typed in Loans & settings can be linked to its machine; it is then counted once, from Equipment finance, in the 13-week forecast, the command centre and the funding gap."));
      box.append(h("h3", {}, "Machine loans (Equipment finance)"), table([{ k: "name", label: "Loan" }, { k: "lender", label: "Lender" }, { k: "emi", label: "Instalment", fmt: "money" }, { k: "start_date", label: "From" }, { k: "end_date", label: "To" },
        { k: "balance", label: "Balance", fmt: "money" }, { k: "balance_basis", label: "Balance from" }], d.machine_loans, { name: "machine_loans", search: false, empty: "No machine loan in Equipment finance." }));
      box.append(h("h3", {}, "Typed loans"), table([{ k: "name", label: "Loan" }, { k: "lender", label: "Lender" }, { k: "emi", label: "Instalment", fmt: "money" }, { k: "balance", label: "Typed balance", fmt: "money" },
        { k: "ledger_balance", label: "Ledger balance", fmt: "money" }, { label: "Counted", v: (r) => r.machine ? "from Equipment finance (" + r.machine + ")" : (r.active ? "yes" : "inactive") },
        { label: "", v: (r) => !d.can_link ? "" : (r.machine ? h("button", { class: "btn small", onclick: async () => { await run("mn.loan_link", { loan_id: r.id, undo: 1 }, "Unlinked"); load(); } }, "Unlink") :
          (d.machines.length ? (() => { const s = h("select", {}, d.machines.map((m) => h("option", { value: m.id }, m.code))); return h("span", {}, s, h("button", { class: "btn small", onclick: async () => { await run("mn.loan_link", { loan_id: r.id, equipment_id: s.value }, "Linked"); load(); } }, "Link to machine")); })() : "")) },
        { label: "Ledger account", v: (r) => !d.can_link ? "" : (() => { const s = h("select", { onchange: async (e) => { await run("loan.save", { row: Object.assign({}, r, { account_id: e.target.value }) }, "Saved"); load(); } }, [h("option", { value: "" }, "—")].concat(d.accounts.map((a) => h("option", { value: a.id, selected: String(a.id) === String(r.account_id) }, a.code + " " + a.name)))); return s; })() }],
      d.typed, { name: "typed_loans", search: false, empty: "No typed loans." }));
      if (d.suggestions.length) box.append(h("p", { class: "red" }, "Possibly entered twice: " + d.suggestions.map((x) => x.loan + " ↔ " + x.machine + " (" + x.why + ")").join("; ")));
    };
    await load();
    return box;
  }

  addTabs("acc/payments", "Payments & receipts", "Pay suppliers bill-wise with TDS, give advances, and record client receipts; wages, salaries and site petty cash.", "Payments & receipts",
    [["Wages", wagesTab], ["Staff salaries", salaryTab], ["Petty cash", pettyTab], ["Money settings", settingsTab]]);
  addTabs("acc/bank", "Bank reconciliation", "Tick entries that appear on the bank statement and set the clearing date, or import the statement.", "Tick off", [["Statement import", stmtTab]]);
  addTabs("fa/register", "Capital register", "Every machine and asset with its cost, depreciation and carrying amount.", "Capital register", [["Machine purchases", capitalTab], ["Link to ledger", linkTab]]);

  /* Accounts › Cash forecast & ratios: one more tab button after the others */
  const origCash = PAGES["acc/cash"];
  if (origCash && !origCash.__mn) {
    const page = async (root, params) => {
      await origCash(root, params);
      const bar = root.querySelector(".tabs");
      if (!bar) return;
      const body = bar.nextSibling;
      const btn = h("button", { type: "button", onclick: async () => {
        bar.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
        body.innerHTML = "";
        try { body.append(await loanTab()); } catch (e) { body.append(h("p", { class: "red" }, e.message)); }
      } }, "Loan register");
      bar.append(btn);
      if (params && params.loans) btn.click();
    };
    Object.keys(origCash).forEach((k) => { page[k] = origCash[k]; });
    page.__mn = true;
    PAGES["acc/cash"] = page;
  }

  /* What's new */
  const VER = "2.40.0";
  function whatsNew() {
    try { if (localStorage.getItem("bco_seen_" + VER)) return; } catch (e) { return; }
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!can("accounts", "view")) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "Wages from the DPR. "), "Accounts › Payments & receipts › ", h("b", {}, "Wages"), ": one wage sheet per project and month from the DPR labour already in Wages Payable; paying it clears the month. ", h("b", {}, "Staff salaries"), " with tax and SSF."),
        h("li", {}, h("b", {}, "Site petty cash. "), "Imprest per site with slips (bill attached), posted to the project's cost, and replenishment."),
        h("li", {}, h("b", {}, "Bank statement import "), "(Bank reconciliation): CSV or Excel, matched automatically to the books."),
        h("li", {}, h("b", {}, "Machines bought on bills "), "(Fixed assets › Capital register): the bill creates the machine and its asset row. ", h("b", {}, "Loan register"), " (Cash forecast & ratios): machine loans counted once."),
        h("li", {}, h("b", {}, "Payment requests. "), "Money settings can require an approved payment request for every supplier and subcontractor payment.")),
      h("p", { class: "hint" }, "Nothing already posted is changed. In a company updated from an earlier version, the payment-request rule stays off until accounts turns it on.")),
    [{ label: "Open Wages", cls: "primary", act: () => { location.hash = "#/acc/payments"; let n = 0; const t = setInterval(() => { const b = [...document.querySelectorAll(".tabs button")].find((x) => x.textContent.trim() === "Wages"); if (b) { clearInterval(t); b.click(); } else if (++n > 40) clearInterval(t); }, 250); } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 14000); } }, 900);
})();
