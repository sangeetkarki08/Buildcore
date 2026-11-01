/* BuildCore 2.28 — cost and resource integration.
   New tabs only; the menu, module names and groups are unchanged:
     Cost control › CVR and forecast ......... Cost to complete & profit · Resources vs plan & cost
     Cost control › CVR, all projects ........ Profit after overhead & financing
     Projects › Daily progress (DPR) ......... Progress to cash
     Procurement › Purchase orders ........... Approval check (and a panel inside each PO)
   Everything here reads; nothing is posted. */
(function () {
  "use strict";
  if (window.__bcoCtc) return;
  window.__bcoCtc = true;

  const css = h("style", {}, ".ct-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:0 0 12px}" +
    ".ct-card{border:1px solid #dde3ea;border-radius:8px;padding:8px 10px;background:#fff}.ct-card b{display:block;font-size:15px;margin-top:2px}" +
    ".ct-card small{color:#667}.ct-card.bad{border-color:#f2b8b5;background:#fdf3f2}.ct-card.est{background:#f7f9fb;border-style:dashed}" +
    ".ct-card.ok{border-color:#b7dfc3;background:#f1f9f3}.ct-note{padding:8px 12px;border-radius:6px;margin:0 0 8px;background:#fff7e6;border:1px solid #f0d9a8}" +
    ".ct-note.bad{background:#fdecea;border-color:#f2b8b5}.ct-note.ok{background:#eaf6ee;border-color:#b7dfc3}.ct-flag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:8px;margin:1px 3px 1px 0;background:#fff1d6;color:#8a5300}" +
    ".ct-flag.bad{background:#fde2e1;color:#a01d16}.ct-flow{display:flex;flex-wrap:wrap;gap:4px;align-items:stretch;margin:6px 0 12px}.ct-flow .ct-card{flex:1;min-width:120px}" +
    ".ct-flow .arrow{align-self:center;color:#8895a5}.ct-bar{display:flex;gap:8px;align-items:end;flex-wrap:wrap;margin-bottom:10px}");
  document.head.append(css);

  const money = (n) => (n == null || n === "" ? "Not available" : fmtMoney(n));
  const card = (label, value, sub, cls) => h("div", { class: "ct-card " + (cls || "") }, h("small", {}, label), h("b", {}, value), sub ? h("small", {}, sub) : "");
  const note = (t, cls) => h("div", { class: "ct-note " + (cls || "") }, t);
  const FLAG = {
    over_budget: ["over budget", 1], commitments_over_budget: ["orders above remaining budget", 1], forecast_raised_to_commitments: ["forecast raised to open orders", 0],
    no_forecast: ["no budget: forecast incomplete", 1], cpi_low: ["earning less than cost", 1], negative_margin: ["negative margin", 1], cost_no_progress: ["cost, no progress", 0],
    budget_placeholder: ["placeholder budget", 0], behind_plan: ["behind plan", 1], done_not_measured: ["done, not measured", 0], measured_not_billed: ["measured, not billed", 0],
    beyond_scope: ["beyond scope: variation?", 1], awaiting_certification: ["awaiting certification", 0], labour_low: ["labour below norm", 1], machines_low: ["machines below norm", 1],
    no_output: ["hours but no output", 1], recurring_breakdown: ["recurring breakdowns", 1], low_utilisation: ["low utilisation", 1], idle_hire: ["hired, standing idle", 1],
    fuel_over_norm: ["fuel above norm", 1],
  };
  const flags = (fs) => h("span", {}, (fs || []).filter((f) => FLAG[f]).map((f) => h("span", { class: "ct-flag" + (FLAG[f][1] ? " bad" : "") }, FLAG[f][0])));
  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const pctTxt = (x) => (x == null ? "—" : x + "%");

  /* ═════════════ Cost control › CVR and forecast: cost to complete & profit ═════════════ */
  async function ctcTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const d = await api("ctc.project", { project_id: S.project });
    const t = d.total;
    if (d.alerts.length) d.alerts.forEach((a) => box.append(note(a.text + (a.items && a.items.length ? " (" + a.items.join(", ") + ")" : ""), a.severity === "high" ? "bad" : "")));
    else box.append(note("No cost alerts on this project today.", "ok"));
    box.append(h("div", { class: "ct-strip" },
      card("Approved revenue", money(d.revenue), "contract and approved variations"),
      card("Cost to date", money(t.cost), "posted, waiting and accrued"),
      card("Remaining cost", money(t.remaining), "of which open orders " + fmtMoney(t.committed)),
      card("Forecast final cost", money(t.eac), t.budget_current != null ? "budget " + fmtMoney(t.budget_current) : "no approved budget", t.budget_current != null && t.eac > t.budget_current ? "bad" : ""),
      card("Gross profit", money(d.gross), pctTxt(d.gross_pct) + (d.incomplete ? " · forecast incomplete" : ""), d.gross < 0 ? "bad" : d.incomplete ? "est" : ""),
      card("Head-office overhead", money(d.overhead), d.overhead_rate_pct != null ? d.overhead_rate_pct + "% of revenue" : "", "est"),
      card("Financing cost", money(d.financing), "estimate", "est"),
      card("Net profit", d.net == null ? "Not available" : fmtMoney(d.net), d.net == null ? "overhead or financing not available" : pctTxt(d.net_pct) + (d.incomplete ? " · forecast incomplete" : ""), d.net != null && d.net < 0 ? "bad" : "")));
    box.append(h("p", { class: "hint" }, "Forecast final cost = cost to date + remaining cost. Remaining cost is the CVR's cost to complete, or the open purchase and subcontract orders when they are larger; orders are never added on top. " +
      "Net profit = approved revenue − forecast final cost − head-office overhead (" + d.overhead_basis + ") − financing (" + d.financing_basis + ")."));
    const cols = [{ k: "code", label: "Code" }, { k: "name", label: "Item" }, { label: "Done", v: (r) => (r.done_pct == null ? "" : r.done_pct + "%") },
      { k: "budget_current", label: "Budget", fmt: "money" }, { k: "cost", label: "Cost to date", fmt: "money" },
      { label: "Open orders", v: (r) => (r.committed ? h("a", { href: "javascript:void 0", onclick: (e) => { e.stopPropagation(); commitments(r); } }, fmtMoney(r.committed)) : "") },
      { k: "ctc", label: "Cost to complete", fmt: "money" }, { k: "uncommitted", label: "Not yet ordered", fmt: "money" }, { k: "eac", label: "Final cost", fmt: "money" },
      { k: "budget_var", label: "Budget left", fmt: "money" }, { k: "forecast_value", label: "Revenue", fmt: "money" }, { k: "gross", label: "Gross profit", fmt: "money" },
      { k: "forecast_basis", label: "Forecast from" }, { label: "Flags", v: (r) => flags(r.flags) }];
    box.append(table(cols, d.rows.filter((r) => r.cost || r.eac || r.forecast_value || r.committed), { name: "cost_to_complete", totals: ["budget_current", "cost", "ctc", "uncommitted", "eac", "forecast_value", "gross"] }));
    if (d.uncoded_commitments.length) {
      box.append(h("h3", {}, "Open orders not coded to an item"), h("p", { class: "hint" }, "Counted once in the total remaining cost" + (d.raised_by_commitments ? "; they raised it by " + fmtMoney(d.raised_by_commitments) : ", inside the items' cost to complete") + "."),
        table([{ k: "doc_no", label: "Order" }, { k: "description", label: "What" }, { k: "qty", label: "Open qty", fmt: "qty" }, { k: "amount", label: "Amount", fmt: "money" }], d.uncoded_commitments, { search: false, totals: ["amount"] }));
    }
    box.append(h("h3", {}, "Not counted as revenue"));
    box.append(d.potential.length ? table([{ k: "ref", label: "Reference" }, { k: "title", label: "What" }, { k: "status", label: "Status" }, { k: "amount", label: "Possible value", fmt: "money" }], d.potential, { search: false, totals: ["amount"] })
      : h("p", { class: "hint" }, "No unapproved variations or pending claims."));
    box.append(h("p", { class: "hint" }, "Change a forecast unit cost on the first tab (project manager, with a reason). Budgets are in Cost control › Control budget."));
    return box;
  }

  async function commitments(r) {
    const d = await api("ctc.commitments", { project_id: S.project, boq_item_id: r.boq_item_id });
    drawer("Open orders: " + r.code + " " + r.name, table([{ k: "kind", label: "Kind" }, { label: "Order", v: (x) => h("a", { href: x.link }, x.doc_no) }, { k: "party", label: "Party" }, { k: "description", label: "What" },
      { k: "qty", label: "Open qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "due", label: "Due" }], d.rows, { search: false, totals: ["amount"] }), []);
  }

  /* ═════════════ Cost control › CVR and forecast: resources vs plan & cost ═════════════ */
  async function resourcesTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const to = h("input", { type: "date", value: today() });
    const d0 = new Date(); d0.setDate(d0.getDate() - 29);
    const fr = h("input", { type: "date", value: d0.toISOString().slice(0, 10) });
    const out = h("div");
    const load = async () => {
      const d = await api("ctc.resources", { project_id: S.project, from: fr.value, to: to.value });
      out.innerHTML = "";
      const lt = d.labour_total;
      out.append(h("div", { class: "ct-strip" },
        card("Labour productivity", pctTxt(lt.labour_pct), lt.labour_basis, lt.labour_pct != null && lt.labour_pct < d.thresholds.productivity_low ? "bad" : ""),
        card("Machine productivity", pctTxt(lt.machine_pct), lt.machine_basis, lt.machine_pct != null && lt.machine_pct < d.thresholds.productivity_low ? "bad" : ""),
        card("Labour cost in DPRs", money(lt.labour_amount), "estimate; the ledger is in the CVR", "est"),
        card("Machines flagged", String(d.equipment.filter((e) => e.flags.length).length), "of " + d.equipment.length + " on site")));
      out.append(h("h3", {}, "Labour and machines by activity"),
        h("p", { class: "hint" }, "Expected = quantity reported × the BOQ item's rate analysis (labour man-days and machine hours per unit). Worked = the DPR lines (" + d.hours_day + " hours = 1 man-day, overtime included). DPR attendance is not payroll attendance."),
        table([{ k: "activity", label: "Activity" }, { k: "name", label: "Name" }, { k: "boq_code", label: "BOQ" }, { k: "qty", label: "Qty done", fmt: "qty" }, { k: "unit", label: "Unit" },
          { k: "expected_md", label: "Man-days expected", fmt: "qty" }, { k: "actual_md", label: "Man-days worked", fmt: "qty" }, { label: "Labour %", v: (r) => pctTxt(r.labour_pct) }, { k: "ot_hours", label: "OT h", fmt: "qty" },
          { k: "expected_mh", label: "Machine h expected", fmt: "qty" }, { k: "actual_mh", label: "Machine h worked", fmt: "qty" }, { label: "Machine %", v: (r) => pctTxt(r.machine_pct) },
          { k: "labour_amount", label: "Labour in DPR", fmt: "money" }, { label: "Flags", v: (r) => flags(r.flags) }], d.labour, { name: "labour_vs_norm", empty: "No DPR in this period.", totals: ["expected_md", "actual_md", "expected_mh", "actual_mh", "labour_amount"] }));
      out.append(h("h3", {}, "Machines"),
        h("p", { class: "hint" }, "From the DPR machine lines, store issues of fuel to each machine, repair work orders and hire bills in the period. Flags: breakdowns on " + d.thresholds.breakdown_days + " days or more, utilisation below " +
          d.thresholds.utilisation_low + "%, a hired machine idle or broken down over " + d.thresholds.hire_idle_pct + "% of its booked hours, fuel over the machine's norm by more than " + d.thresholds.fuel_var_pct + "%."),
        table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "ownership", label: "Owned / hired" }, { k: "days", label: "Days" }, { k: "working", label: "Working h", fmt: "qty" }, { k: "idle", label: "Idle h", fmt: "qty" },
          { k: "breakdown", label: "Breakdown h", fmt: "qty" }, { label: "Utilisation", v: (r) => pctTxt(r.utilisation) }, { k: "fuel_per_hour", label: "Fuel / h", fmt: "qty" }, { k: "fuel_norm", label: "Norm", fmt: "qty" },
          { k: "fuel_cost", label: "Fuel", fmt: "money" }, { k: "repairs", label: "Repairs", fmt: "money" }, { k: "rent", label: "Hire billed", fmt: "money" }, { k: "internal", label: "Own-machine charge", fmt: "money" },
          { k: "cost_per_hour", label: "Cost / working h", fmt: "money" }, { label: "Flags", v: (r) => flags(r.flags) }], d.equipment, { name: "machines_vs_cost", empty: "No machine on the DPRs in this period.", totals: ["fuel_cost", "repairs", "rent", "internal"] }));
      out.append(h("h3", {}, "Materials (to date)"));
      if (d.materials_note) out.append(h("p", { class: "hint" }, d.materials_note));
      out.append(h("p", { class: "hint" }, "Theoretical use = work done × the material coefficients; actual = store issues less returns. The full reconciliation with causes is in Inventory › Material reconciliation."),
        table([{ k: "mat_code", label: "Code" }, { k: "mat_name", label: "Material" }, { k: "unit", label: "Unit" }, { k: "theoretical", label: "Theoretical", fmt: "qty" }, { k: "allowed", label: "Allowed with wastage", fmt: "qty" },
          { k: "actual", label: "Issued", fmt: "qty" }, { label: "Wastage", v: (r) => pctTxt(r.wastage_pct) }, { k: "abnormal_value", label: "Excess value", fmt: "money" }],
        d.materials, { search: false, name: "materials_vs_theory", empty: "No material coefficients on this project.", rowClass: (r) => (r.flag ? "bad" : "") }));
      if (d.shortages.length) out.append(h("h3", {}, "Material shortages"), table(Object.keys(d.shortages[0]).filter((k) => !/_id$|^id$/.test(k)).slice(0, 8).map((k) => ({ k, label: k.replace(/_/g, " ") })), d.shortages, { search: false }));
    };
    box.append(h("div", { class: "ct-bar" }, h("label", {}, "From ", fr), h("label", {}, "To ", to), h("button", { class: "btn primary", onclick: load }, "Show")), out);
    await load();
    return box;
  }

  /* ═════════════ Cost control › CVR, all projects: profit after overhead & financing ═════════════ */
  async function portfolioTab() {
    const d = await api("ctc.portfolio", {});
    const box = h("div");
    const t = d.total;
    box.append(h("div", { class: "ct-strip" }, card("Approved revenue", money(t.revenue)), card("Forecast final cost", money(t.eac)), card("Gross profit", money(t.gross), "", t.gross < 0 ? "bad" : ""),
      card("Head-office overhead", money(t.overhead), "", "est"), card("Financing", money(t.financing), "interest " + d.interest_pct + "% a year", "est"), card("Net profit", money(t.net), "", t.net < 0 ? "bad" : ""),
      card("Not counted (claims, unapproved variations)", money(t.potential), "", "est")));
    box.append(table([{ k: "code", label: "Project" }, { k: "name", label: "Name" }, { k: "revenue", label: "Revenue", fmt: "money" }, { k: "cost", label: "Cost to date", fmt: "money" },
      { k: "committed", label: "Open orders", fmt: "money" }, { k: "eac", label: "Final cost", fmt: "money" }, { k: "budget", label: "Budget", fmt: "money" }, { k: "gross", label: "Gross profit", fmt: "money" },
      { label: "Gross %", v: (r) => pctTxt(r.gross_pct) }, { k: "overhead", label: "Overhead", fmt: "money" }, { k: "financing", label: "Financing", fmt: "money" }, { k: "net", label: "Net profit", fmt: "money" },
      { label: "Net %", v: (r) => (r.net_pct == null ? "Not available" : r.net_pct + "%" + (r.incomplete ? " (incomplete)" : "")) }, { k: "potential", label: "Not counted", fmt: "money" }, { k: "alert_text", label: "Alerts" }],
    d.rows, { name: "profit_all_projects", totals: ["revenue", "cost", "committed", "eac", "gross", "overhead", "financing", "net", "potential"], rowClass: (r) => (r.net != null && r.net < 0 ? "bad" : ""),
      onRow: (r) => { setProject(r.project_id); location.hash = "#/cl/cvr?project_id=" + r.project_id + "&tab=1"; } }));
    box.append(h("p", { class: "hint" }, "Overhead basis: " + d.overhead_basis + ". Financing is each project's own cash need from today at the company's borrowing rate. Settings: Cost to complete settings below."),
      h("button", { class: "btn", onclick: settingsModal }, "Cost to complete settings"));
    return box;
  }

  async function settingsModal() {
    const s = await api("ctc.settings", {});
    const f = form([{ k: "ctc_oh_pct", label: "Head-office overhead, % of revenue (blank = from the books)", type: "number" }, { k: "ctc_behind_pct", label: "Behind plan when short by more than %", type: "number" },
      { k: "ctc_prod_low", label: "Productivity flagged below % of the norm", type: "number" }, { k: "ctc_bd_days", label: "Recurring breakdown: days with a breakdown", type: "number" },
      { k: "ctc_hire_idle_pct", label: "Hired machine idle over % of booked hours", type: "number" }], s);
    modal("Cost to complete settings", f, [{ label: "Save", cls: "primary", act: () => run("ctc.settings_save", f.values(), "Saved") }], { narrow: true });
  }

  /* ═════════════ Projects › Daily progress (DPR): progress to cash ═════════════ */
  async function chainTab() {
    if (!S.project) return projectNotice();
    const d = await api("ctc.chain", { project_id: S.project });
    const t = d.total;
    const box = h("div");
    const step = (l, v, sub, cls) => card(l, money(v), sub, cls);
    const arrow = () => h("span", { class: "arrow" }, "›");
    box.append(h("div", { class: "ct-flow" }, step("Planned to date", t.planned_v, "schedule, straight line", "est"), arrow(), step("Reported by site", t.reported_v, "DPRs submitted or approved"), arrow(),
      (d.progress_basis.startsWith("accepted") ? step("Accepted", t.accepted_v, "by QS / engineer") : card("Accepted", "Not recorded", "no QS acceptance yet", "est")), arrow(), step("Measured", t.measured_v, "verified measurement"), arrow(), step("Billed", t.billed_v, "IPCs submitted"), arrow(),
      step("Certified", t.certified_v, "by the client"), arrow(), step("Cash received", t.received, "net, from the bank", "ok")));
    box.append(h("p", { class: "hint" }, "Values at BOQ rates. Progress is read from " + d.progress_basis + ". A DPR quantity is never billing: only a certified IPC is, and only a bank receipt is cash."));
    const warn = [];
    if (t.unmeasured_v > 0.5) warn.push("Work done but not measured: " + fmtMoney(t.unmeasured_v) + ".");
    if (t.unbilled_v > 0.5) warn.push("Measured but not billed: " + fmtMoney(t.unbilled_v) + ".");
    if (t.behind_v > 0.5) warn.push("Work behind plan holds back " + fmtMoney(t.behind_v) + " of billing.");
    if (t.beyond_v > 0.5) warn.push("Reported beyond the approved scope: " + fmtMoney(t.beyond_v) + " (a possible variation; nothing is billed for it).");
    warn.forEach((w) => box.append(note(w)));
    box.append(table([{ k: "code", label: "BOQ" }, { k: "description", label: "Item" }, { k: "unit", label: "Unit" }, { k: "scope", label: "Scope", fmt: "qty" }, { k: "planned", label: "Planned to date", fmt: "qty" },
      { k: "reported", label: "Reported", fmt: "qty" }, { label: "Accepted", v: (r) => (r.accepted == null ? "not recorded" : fmtQty(r.accepted)) }, { k: "measured", label: "Measured", fmt: "qty" }, { k: "billed", label: "Billed", fmt: "qty" },
      { k: "certified", label: "Certified", fmt: "qty" }, { k: "received", label: "Cash received", fmt: "money" }, { label: "Progress", v: (r) => pctTxt(r.progress_pct) }, { label: "Flags", v: (r) => flags(r.flags) }],
    d.rows, { name: "progress_to_cash", totals: ["received"] }));
    box.append(h("h3", {}, "Delays and the cash they hold back (estimate)"));
    box.append(d.delays.length ? table([{ k: "code", label: "BOQ" }, { k: "description", label: "Item" }, { k: "shortfall", label: "Behind by", fmt: "qty" }, { k: "unit", label: "Unit" },
      { k: "billing_held", label: "Billing held back", fmt: "money" }, { k: "cash_held", label: "Cash after retention", fmt: "money" }, { label: "Catch-up days", v: (r) => (r.catch_up_days == null ? "Not available" : r.catch_up_days) },
      { label: "Cash later by", v: (r) => (r.cash_later_days == null ? "Not available" : "~" + r.cash_later_days + " days") }, { k: "basis", label: "How it is worked out" }], d.delays, { search: false, name: "delay_cash_impact", totals: ["billing_held", "cash_held"] })
      : h("p", { class: "hint" }, "No item is more than " + d.behind_pct + "% behind its planned quantity to date."));
    if (d.variations_open.length) box.append(h("p", { class: "hint" }, "Variations not yet approved: " + d.variations_open.map((v) => v.no + " " + (v.title || "") + " (" + v.status + ")").join("; ") + "."));
    return box;
  }

  /* ═════════════ Procurement › Purchase orders: approval check ═════════════ */
  function checkView(ck) {
    const box = h("div");
    (ck.flags.length ? ck.flags : ["No warnings: stock, budget and cash allow this order."]).forEach((f) => box.append(note(f, ck.flags.length ? "bad" : "ok")));
    const b = ck.budget, c = ck.cash;
    box.append(h("div", { class: "ct-strip" },
      card("Payment due", ck.pay_date, ck.credit_days + " days (" + ck.credit_basis + ")"),
      card("Project budget left after", b ? money(b.left_after) : "Not available", b ? b.basis : "no budget on this project", b && b.left_after < 0 ? "bad" : ""),
      card("Company cash in that week", c && c.week ? money(c.available_after) : "Not available", c && c.week ? "available to spend in week " + c.week + (c.counted ? " (already in the forecast)" : " after this order") : (c && c.note) || "", c && c.available_after < 0 ? "bad" : "")));
    box.append(table([{ k: "material", label: "Material" }, { k: "qty", label: "Ordering", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "stock_here", label: "Stock on this project", fmt: "qty" },
      { k: "stock_company", label: "Stock, all stores", fmt: "qty" }, { k: "on_order", label: "Already on order", fmt: "qty" }, { k: "demand_30", label: "Scheduled use, 30 days", fmt: "qty" },
      { label: "Needed by", v: (r) => (r.need_by ? r.need_by + (r.need_no ? " (" + r.need_no + ")" : "") : "") }, { k: "amount", label: "Amount", fmt: "money" }], ck.lines, { search: false, export: false }));
    if (ck.waits.length) box.append(h("h4", {}, "Activities that use these materials"), table([{ k: "activity", label: "Activity" }, { k: "name", label: "Name" }, { k: "material", label: "Material" }, { k: "start", label: "Starts" },
      { label: "Float", v: (r) => (r.float_days == null ? "—" : r.float_days + " d") }, { label: "Latest delivery", v: (r) => r.latest_delivery || "—" }, { label: "", v: (r) => h("span", {}, r.running ? "in progress " : "", r.late ? h("span", { class: "ct-flag bad" }, r.running ? "stock runs out first" : "delivery too late") : "") }],
    ck.waits, { search: false, export: false }));
    box.append(h("p", { class: "hint" }, "A check only: approving or holding the order is the approver's decision. Delaying past an activity's latest delivery date may hold that activity."));
    return box;
  }

  async function approvalTab() {
    const rows = await api("ctc.pending_pos", { project_id: S.project || null });
    const box = h("div");
    box.append(h("p", { class: "hint" }, "Purchase orders waiting for approval, and drafts, with what each would do to stock, the budget and company cash. Click one for the full check."));
    box.append(table([{ k: "no", label: "PO" }, { label: "Status", v: (r) => stamp(r.status) }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "vendor", label: "Vendor" }, { k: "total", label: "Total", fmt: "money" },
      { k: "delivery_date", label: "Delivery" }, { k: "pay_date", label: "Payment due" }, { k: "budget_left_after", label: "Budget left after", fmt: "money" }, { label: "Cash in that week after", v: (r) => (r.cash_after == null ? "—" : fmtMoney(r.cash_after)) },
      { k: "warning_text", label: "Warnings" }], rows, { name: "po_approval_check", empty: "No purchase order is waiting for approval.", rowClass: (r) => (r.warnings ? "bad" : ""),
      onRow: async (r) => drawer("Before approving " + (r.no || "the draft PO"), checkView(await api("ctc.po_check", { po_id: r.id })), [{ label: "Open the PO", act: () => { location.hash = "#/proc/po?id=" + r.id; } }]) }));
    return box;
  }

  /* the same check inside each purchase order, for drafts and orders waiting for approval */
  if (typeof PO !== "undefined" && PO && !PO.__ctc) {
    const prev = PO.after;
    PO.after = (ctx) => {
      if (prev) prev(ctx);
      const d = ctx.doc || {};
      if (!d.id || !["draft", "pending_approval"].includes(d.status)) return;
      const holder = h("div", { class: "panel" }, h("h2", {}, "Before approval: stock, budget and cash"), h("p", { class: "hint" }, "Checking…"));
      ctx.extra.append(holder);
      api("ctc.po_check", { po_id: d.id }).then((ck) => { holder.lastChild.remove(); holder.append(checkView(ck)); }).catch((e) => { holder.lastChild.textContent = "Check not available: " + (e.message || e); });
    };
    PO.__ctc = true;
  }

  addTabs("cl/cvr", "CVR and forecast", "What engineering earned against what accounts spent, item by item, and the forecast final profit.", "CVR",
    [["Cost to complete & profit", ctcTab], ["Resources vs plan & cost", resourcesTab]]);
  addTabs("cl/cvrall", "CVR, all projects", "Live (provisional) figures for every project, with its last locked close.", "CVR", [["Profit after overhead & financing", portfolioTab]]);
  addTabs("p/dpr", "Daily progress (DPR)", "Enter, check and approve the daily report; view and print any DPR.", "Daily reports", [["Progress to cash", chainTab]]);
  addTabs("proc/po", "Purchase orders", typeof PO !== "undefined" && PO ? PO.sub : "", "Purchase orders", [["Approval check", approvalTab]]);

  /* What's new */
  const VER = "2.28.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!(can("control", "view") || can("procurement", "approve") || can("project", "view"))) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:600px" },
      h("p", {}, "New tabs connect site progress, resources and purchases to cost and cash. The menu is unchanged."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, "CVR and forecast › Cost to complete & profit: final cost with open orders counted once, then head-office overhead and financing, and what is not yet revenue."),
        h("li", {}, "CVR and forecast › Resources vs plan & cost: labour and machine hours against the rate analysis, machine breakdowns, idle hire and fuel, material against theory."),
        h("li", {}, "Daily progress › Progress to cash: planned, reported, accepted, measured, billed, certified and received, and the cash held back by delays."),
        h("li", {}, "Purchase orders › Approval check, and a panel in each PO: stock, orders, payment date, budget, company cash and the activities waiting.")),
      h("p", { class: "hint" }, "Nothing is posted and no record changes.")),
    [{ label: "Open cost to complete", cls: "primary", act: () => { location.hash = "#/cl/cvr?tab=1"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 8000); } }, 900);
})();
