/* BuildCore 2.1 — cash and bidding inside existing screens:
   Cost & earned value › cost codes, LCPI, control chart, cash flow · IPC billing › NFRS 15 and sub-ledgers ·
   Commercial › Bids & markup · Budget vs actual › head-office overhead budget ·
   Accounts › Cash forecast & ratios · Command centre tiles · rate-analysis markup split · cash-payment limit. */
(function () {
  "use strict";
  const bars = (...a) => window.bcoBars(...a);
  const pct = (v) => (v == null ? "—" : fmtN(v, 2) + "%");
  const M = (v) => (v == null ? "—" : fmtN(v / 1e6, 2) + " M");

  /* ── cash-payment limit: offer the override when the server refuses ── */
  const origApi = window.api;
  window.api = async function (fn, args) {
    try { return await origApi(fn, args); } catch (e) {
      if (fn === "payment.create" && /^Cash payment of/.test(e.message) && !(args || {}).cash_override) {
        const why = await ask("Cash payment above the limit", e.message, { input: "Reason for paying in cash (recorded in the audit log)", required: true, danger: true, ok: "Pay in cash anyway" });
        if (why) return origApi(fn, Object.assign({}, args, { cash_override: why }));
      }
      throw e;
    }
  };

  /* ── Cost & earned value tabs ── */
  async function costCodesTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const load = async () => {
      const d = await api("cost.codes", { project_id: S.project });
      box.innerHTML = "";
      box.append(h("div", { class: "tiles" }, tile("Budget", fmtMoney(d.totals.bac)), tile("Actual", fmtMoney(d.totals.ac)), tile("Committed (open POs)", fmtMoney(d.totals.committed)),
        tile("Still to commit", fmtMoney(d.totals.etc_uncommitted)), tile("Estimate at completion", fmtMoney(d.totals.eac), { cls: d.totals.eac > d.totals.bac ? "bad" : "" }),
        tile("Not coded to a BOQ item", fmtMoney(d.unallocated_actual), { sub: "committed " + fmtMoney(d.unallocated_committed) })),
      h("p", { class: "hint" }, "EAC = actual + committed + the uncommitted rest of the estimate to complete. Classify each overrun: clerical (the cost is on the wrong code — re-code it), estimating (the estimate was wrong — revise the forecast) or scope (a variation)."),
      table([{ k: "code", label: "Cost code" }, { label: "Description", v: (r) => (r.description || "").slice(0, 60) }, { label: "Progress", v: (r) => r.progress_pct + "%" },
        { k: "bac", label: "Budget", fmt: "money" }, { k: "ac", label: "Actual", fmt: "money" }, { k: "committed", label: "Committed", fmt: "money" }, { k: "etc_uncommitted", label: "To commit", fmt: "money" },
        { k: "eac", label: "EAC", fmt: "money" }, { k: "variance", label: "Budget − EAC", fmt: "money" }, { label: "CPI", v: (r) => fmtN(r.cpi) },
        { label: "Review", v: (r) => r.review ? r.review + (r.review_note ? " — " + r.review_note : "") : (r.flag && can("commercial", "edit") ? h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); review(r); } }, "Classify") : "") }],
      d.rows, { name: "cost_codes", totals: ["bac", "ac", "committed", "etc_uncommitted", "eac", "variance"], rowClass: (r) => r.flag ? "bad" : "", onRow: can("commercial", "edit") ? review : null }));
    };
    const review = (r) => {
      const f = form([{ k: "class", label: "Why is it over?", type: "select", noBlank: true, options: [["clerical", "Clerical — cost on the wrong code (re-code it)"], ["estimating", "Estimating — revise the forecast"], ["scope", "Scope — raise a variation"], ["ok", "Reviewed, no action"]] },
        { k: "revised_eac", label: "Revised EAC (estimating)", type: "number" }, { k: "note", label: "Note", wide: true }]);
      modal("Review " + r.code, f, [{ label: "Save", cls: "primary", act: async () => { await run("cost.review", { row: Object.assign(f.values(), { project_id: S.project, boq_item_id: r.id }) }, "Saved"); load(); } }], { narrow: true });
    };
    await load();
    return box;
  }
  async function lcpiTab() {
    if (!S.project) return projectNotice();
    const d = await api("cost.lcpi", { project_id: S.project, weeks: 20 });
    return h("div", {}, h("div", { class: "tiles" }, tile("LCPI to date", fmtN(d.lcpi), { cls: d.lcpi != null && d.lcpi < 0.95 ? "bad" : "" }), tile("Budgeted labour cost of work done", fmtMoney(d.budgeted)), tile("Labour cost", fmtMoney(d.actual))),
      h("p", { class: "hint" }, "LCPI = budgeted cost of labour for the work done ÷ what the labour cost, week by week from approved DPRs. Below 1 means the crews are costing more than the estimate allowed. " + d.note),
      h("div", { class: "panel" }, lineChart(d.weeks.map((w) => w.week.slice(5)), [{ name: "Weekly LCPI", color: "#1b5e86", values: d.weeks.map((w) => w.lcpi) }, { name: "Cumulative", color: "#d9950f", values: d.weeks.map((w) => w.cum_lcpi) }, { name: "1.0", color: "#9aa9b1", dash: true, values: d.weeks.map(() => 1) }], { max: 2 })),
      h("h2", { class: "sec" }, "By activity (worst first)"),
      table([{ label: "Activity", v: (r) => (r.code || "") + " " + r.name }, { k: "budgeted", label: "Budgeted labour", fmt: "money" }, { k: "actual", label: "Actual labour", fmt: "money" }, { label: "LCPI", v: (r) => r.lcpi == null ? "—" : h("b", { class: r.lcpi < 0.95 ? "red" : "green" }, fmtN(r.lcpi)) }], d.activities, { name: "lcpi_activities" }),
      table([{ k: "week", label: "Week of" }, { k: "budgeted", label: "Budgeted", fmt: "money" }, { k: "actual", label: "Actual", fmt: "money" }, { label: "LCPI", v: (r) => fmtN(r.lcpi) }, { label: "Cumulative", v: (r) => fmtN(r.cum_lcpi) }], d.weeks, { name: "lcpi_weeks", search: false }));
  }
  function scatter(points, o) {
    const W = 520, H = 420, P = 44;
    const xs = points.map((p) => p.spi), ys = points.map((p) => p.cpi);
    const lo = Math.min(0.5, ...xs, ...ys) - 0.05, hi = Math.max(1.5, ...xs, ...ys) + 0.05;
    const X = (v) => P + (W - 2 * P) * (v - lo) / (hi - lo), Y = (v) => H - P - (H - 2 * P) * (v - lo) / (hi - lo);
    let s = `<rect x="${X(1)}" y="${Y(hi)}" width="${X(hi) - X(1)}" height="${Y(1) - Y(hi)}" fill="#e3f1e8"/><rect x="${X(lo)}" y="${Y(1)}" width="${X(1) - X(lo)}" height="${Y(lo) - Y(1)}" fill="#fbe9e6"/>`;
    for (const band of [2, 1]) {
      if (o.cpi_sd != null) s += `<rect x="${P}" y="${Y(o.cpi_mean + band * o.cpi_sd)}" width="${W - 2 * P}" height="${Math.max(0, Y(o.cpi_mean - band * o.cpi_sd) - Y(o.cpi_mean + band * o.cpi_sd))}" fill="${band === 2 ? "#e6eff5" : "#cfe0ec"}" opacity="0.6"/>`;
    }
    s += `<line x1="${X(1)}" x2="${X(1)}" y1="${P}" y2="${H - P}" stroke="#5b6970"/><line x1="${P}" x2="${W - P}" y1="${Y(1)}" y2="${Y(1)}" stroke="#5b6970"/>`;
    s += `<text x="${W / 2}" y="${H - 8}" class="ax" text-anchor="middle">SPI (schedule) →</text><text x="12" y="${H / 2}" class="ax" transform="rotate(-90 12 ${H / 2})" text-anchor="middle">CPI (cost) →</text>`;
    s += `<text x="${X(hi) - 4}" y="${Y(hi) + 14}" class="ax" text-anchor="end">under budget, ahead</text><text x="${X(lo) + 4}" y="${Y(lo) - 6}" class="ax">over budget, behind</text>`;
    for (let v = Math.ceil(lo * 10) / 10; v <= hi; v += 0.1) s += `<text x="${X(v)}" y="${H - P + 14}" class="ax" text-anchor="middle">${v.toFixed(1)}</text><text x="${P - 6}" y="${Y(v) + 3}" class="ax" text-anchor="end">${v.toFixed(1)}</text>`;
    let prev = null;
    points.forEach((p, i) => {
      if (prev) s += `<line x1="${X(prev.spi)}" y1="${Y(prev.cpi)}" x2="${X(p.spi)}" y2="${Y(p.cpi)}" stroke="#1b5e86" stroke-width="1.5"/>`;
      s += `<circle cx="${X(p.spi)}" cy="${Y(p.cpi)}" r="${i === points.length - 1 ? 6 : 4}" fill="${i === points.length - 1 ? "#b3392c" : "#1b5e86"}"><title>${p.month}: CPI ${p.cpi}, SPI ${p.spi}</title></circle><text x="${X(p.spi) + 7}" y="${Y(p.cpi) - 5}" class="ax">${p.month.slice(2)}</text>`;
      prev = p;
    });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "chart"); svg.style.maxWidth = "560px"; svg.innerHTML = s;
    return svg;
  }
  async function controlTab() {
    if (!S.project) return projectNotice();
    const d = await api("cost.control_chart", { project_id: S.project });
    if (!d.points.length) return h("p", { class: "muted" }, "Needs approved DPRs and a BOQ with rate analysis.");
    return h("div", { class: "cols" }, h("div", { class: "panel" }, h("h2", {}, "CPI against SPI, month by month"), scatter(d.points, d),
      h("p", { class: "hint" }, "Shaded band: CPI mean ± 1 and 2 standard deviations. The red dot is the latest month.")),
    h("div", { class: "panel" }, kv([["Latest position", d.quadrant], ["CPI mean ± sd", fmtN(d.cpi_mean, 3) + " ± " + fmtN(d.cpi_sd, 3)], ["SPI mean ± sd", fmtN(d.spi_mean, 3) + " ± " + fmtN(d.spi_sd, 3)], ["Consistency", d.consistency]]),
      table([{ k: "month", label: "Month" }, { k: "cpi", label: "CPI", fmt: "num" }, { k: "spi", label: "SPI", fmt: "num" }, { k: "ev", label: "EV", fmt: "money" }, { k: "pv", label: "PV", fmt: "money" }, { k: "ac", label: "AC", fmt: "money" }], d.points, { search: false, name: "cpi_spi" })));
  }
  async function cashFlowTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    let v = { basis: "early", delay: 0, overrun: 0 };
    const load = async () => {
      const d = await api("cash.project", Object.assign({ project_id: S.project }, v));
      box.innerHTML = "";
      const f = form([{ k: "basis", label: "Schedule dates", type: "select", noBlank: true, options: [["early", "Early start"], ["late", "Late start"]] },
        { k: "delay", label: "Client pays late by (days)", type: "number" }, { k: "overrun", label: "Cost overrun %", type: "number" }], v);
      f.className = "bar"; f.append(h("button", { class: "btn primary", onclick: () => { v = f.values(); load(); } }, "Recalculate"),
        can("commercial", "edit") ? h("button", { class: "btn", onclick: () => termsDialog(d.terms, load) }, "Payment terms") : null);
      box.append(f, h("div", { class: "tiles" }, tile("Peak cash needed", fmtMoney(d.peak_cash), { cls: d.peak_cash > 0 ? "warn" : "", sub: d.peak_month ? "in " + d.peak_month : null }),
        tile("Financing cost", fmtMoney(d.financing_cost)), tile("Mobilisation advance still to recover", fmtMoney(d.advance_outstanding)), tile("Retention held by the client", fmtMoney(d.retention_held))),
      h("div", { class: "panel" }, h("h2", {}, "Cash in, cash out and the running balance"),
        bars(d.rows.map((r) => r.month.slice(2)), [{ name: "Cash in", color: "#2f7a4d", values: d.rows.map((r) => r.in / 1e6) }, { name: "Cash out", color: "#b3392c", values: d.rows.map((r) => r.out / 1e6) }], { stacked: false }),
        lineChart(d.rows.map((r) => r.month.slice(2)), [{ name: "Cumulative (M)", color: "#1b5e86", values: d.rows.map((r) => Math.round(r.cumulative / 1e5) / 10) }], {})),
      h("p", { class: "hint" }, "Receipts: work on the CPM dates billed at month end, certified after " + d.terms.cert_days + " days and paid " + d.terms.pay_days + " days later, less retention " + d.terms.retention_pct + "%, TDS " + d.terms.tds_pct + "% and advance recovery " + d.terms.advance_recovery_pct + "%. Payments: labour after " + d.terms.labour_pay_days + " days, materials after " + d.terms.supplier_credit_days + " days' credit, subcontractors when paid."),
      table([{ k: "month", label: "Month" }].concat(d.categories_in.map((k) => ({ label: k, fmt: "money", v: (r) => r.in_detail[k] }))).concat([{ k: "in", label: "Total in", fmt: "money" }])
        .concat(d.categories_out.map((k) => ({ label: k, fmt: "money", v: (r) => r.out_detail[k] }))).concat([{ k: "out", label: "Total out", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "cumulative", label: "Cumulative", fmt: "money" }]),
      d.rows, { name: "project_cash_flow", search: false, rowClass: (r) => r.cumulative < 0 ? "flag" : "" }));
    };
    await load();
    return box;
  }
  function termsDialog(t, done) {
    const f = form([{ k: "ipc_cycle_days", label: "IPC every (days)", type: "number" }, { k: "cert_days", label: "Certification takes (days)", type: "number" }, { k: "pay_days", label: "Payment after certification (days)", type: "number" },
      { k: "retention_pct", label: "Retention %", type: "number" }, { k: "retention_release_pct", label: "Released at completion %", type: "number" }, { k: "dlp_months", label: "Defects liability (months)", type: "number" },
      { k: "advance_pct", label: "Mobilisation advance %", type: "number" }, { k: "advance_recovery_pct", label: "Advance recovered from each IPC %", type: "number" },
      { k: "vat_pct", label: "VAT %", type: "number" }, { k: "tds_pct", label: "TDS deducted by client %", type: "number" }, { k: "supplier_credit_days", label: "Supplier credit (days)", type: "number" },
      { k: "labour_pay_days", label: "Labour paid after month end (days)", type: "number" }, { k: "subcon_pct", label: "Share of work subcontracted (pay when paid) %", type: "number" }], t);
    modal("Payment terms for " + nm.pcode(S.project), f, [{ label: "Save", cls: "primary", act: async () => { await run("cash.terms_save", { project_id: S.project, row: f.values() }, "Saved"); done(); } }]);
  }
  bcoTabbed("p/evm", "Cost control & earned value", "CV = EV − AC · SV = EV − PV · CPI = EV ÷ AC · SPI = EV ÷ PV · EAC = AC + ETC. Profit is forecast revenue − EAC.",
    { firstLabel: "Earned value", tabs: [["Cost codes & commitments", costCodesTab], ["Labour (LCPI)", lcpiTab], ["CPI / SPI control chart", controlTab], ["Cash flow forecast", cashFlowTab], ...((window.EVM_TABS) || [])] });

  /* ── IPC billing › NFRS 15 ── */
  async function nfrsTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const load = async () => {
      const d = await api("nfrs15.get", { project_id: S.project });
      box.innerHTML = "";
      const p = d.project;
      box.append(h("div", { class: "tiles" }, tile("Transaction price", fmtMoney(d.transaction_price)), tile("Progress (" + (p.revenue_method === "cost" ? "cost to cost" : "output") + ")", d.progress_pct + "%"),
        tile("Revenue to date", fmtMoney(d.revenue_to_date)), tile("Certified (billed)", fmtMoney(d.certified_to_date)),
        tile(d.contract_asset > 0 ? "Contract asset" : "Contract liability", fmtMoney(d.contract_asset || d.contract_liability), { cls: d.contract_liability > 0 ? "warn" : "" }),
        tile("Remaining performance obligations", fmtMoney(d.remaining_obligations)), tile("Expected loss", fmtMoney(d.expected_loss), { cls: d.expected_loss > 0 ? "bad" : "" })),
      h("div", { class: "cols" }, h("div", { class: "panel" }, h("h2", {}, "Transaction price"), kv([["Contract price", fmtMoney(d.contract_price)], ["Approved variations", fmtMoney(d.approved_variations)],
        ["Pending variations marked highly probable", fmtMoney(d.pending_variations_highly_probable)], ["Claims / escalation marked highly probable", fmtMoney(d.claims_highly_probable)],
        ["Liquidated damages expected", "− " + fmtMoney(d.ld_expected)], ["Transaction price", h("b", {}, fmtMoney(d.transaction_price))]]),
        h("p", { class: "hint" }, "Variable consideration (pending variations, claims, escalation) is included only when it is highly probable that no significant reversal will follow — tick “highly probable” on the variation or event.")),
      h("div", { class: "panel" }, h("h2", {}, "Costs and progress"), kv([["Estimate at completion", fmtMoney(d.eac)], ["Actual cost to date", fmtMoney(d.actual_cost)], ["Abnormal waste already expensed", fmtMoney(d.abnormal_waste_excluded)],
        ["Materials in store, not installed", fmtMoney(d.uninstalled_materials)], ["Revenue in the books", fmtMoney(d.revenue_in_books)], ["Asset/liability adjustment booked", fmtMoney(d.adjustment_booked)],
        ["Adjustment still to post", h("b", {}, fmtMoney(d.adjustment_needed))], ["Onerous provision to post", fmtMoney(d.onerous_provision_needed)]]), h("p", { class: "hint" }, d.note))),
      h("div", { class: "panel" }, h("h2", {}, "Contract register"), kv([["Contract type", p.contract_type || "—"], ["Long-term contract (Income Tax Act s.26)", p.sec26 ? "Yes" : "No"], ["Performance obligations", p.performance_obligations || "One: the completed works"],
        ["Revenue method", p.revenue_method === "cost" ? "Cost to cost" : "Output (measured work)"], ["JV share", p.jv_share_pct != null ? p.jv_share_pct + "% (" + (p.jv_partners || "") + ")" : "Not a JV"]]),
        can("commercial", "edit") ? h("button", { class: "btn small", onclick: () => regDialog(p, load) }, "Edit contract register") : null));
      if (can("accounts", "approve") && (Math.abs(d.adjustment_needed) > 0.5 || d.onerous_provision_needed > 0.5)) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        if (!(await ask("Post NFRS 15 adjustments", "Post the contract asset/liability adjustment of " + fmtMoney(d.adjustment_needed) + (d.onerous_provision_needed > 0.5 ? " and an onerous-contract provision of " + fmtMoney(d.onerous_provision_needed) : "") + " dated today?"))) return;
        await run("nfrs15.post", { project_id: S.project }, "Posted"); load();
      } }, "Post the adjustments")));
      box.append(h("h2", { class: "sec" }, "Variable consideration"), table([{ k: "no", label: "No." }, { k: "title", label: "Variation" }, { k: "status", label: "Status", fmt: "status" }, { k: "est_value", label: "Estimated value", fmt: "money" }, { label: "Highly probable", v: (r) => r.highly_probable ? "Yes" : "No" }], d.pending_variations, { search: false, export: false, empty: "No pending variations." }),
        table([{ k: "no", label: "No." }, { k: "type", label: "Type" }, { k: "title", label: "Claim / event" }, { k: "claim_value", label: "Claim value", fmt: "money" }, { k: "cost_impact", label: "Cost impact", fmt: "money" }, { label: "Highly probable", v: (r) => r.highly_probable ? "Yes" : "No" }], d.claims, { search: false, export: false, empty: "No open claims." }));
    };
    const regDialog = (p, done) => {
      const f = form([{ k: "contract_type", label: "Contract type", type: "select", options: [["admeasurement", "Admeasurement (item rate)"], ["lump_sum", "Lump sum"], ["epc", "EPC / design-build"], ["cost_plus", "Cost plus"], ["jv", "Joint venture"]] },
        { k: "sec26", label: "Long-term contract under Income Tax Act s.26", type: "check" }, { k: "revenue_method", label: "Measure progress by", type: "select", noBlank: true, options: [["output", "Output (measured work × rate)"], ["cost", "Cost to cost"]] },
        { k: "performance_obligations", label: "Performance obligations", type: "textarea", wide: true }, { k: "jv_share_pct", label: "Our JV share %", type: "number" }, { k: "jv_partners", label: "JV partners and shares", wide: true },
        { k: "project_type", label: "Project type (for profit centres)" }, { k: "pm_name", label: "Project manager" }], p);
      modal("Contract register", f, [{ label: "Save", cls: "primary", act: async () => { await run("cash.terms_save", { project_id: S.project, row: f.values() }, "Saved"); done(); } }]);
    };
    await load();
    return box;
  }
  async function ledgersTab() {
    if (!S.project) return projectNotice();
    const d = await api("nfrs15.subledgers", { project_id: S.project });
    return h("div", {}, ...Object.values(d).map((x) => h("div", { class: "panel" }, h("h2", {}, x.label + ": " + fmtMoney(Math.abs(x.balance))),
      x.by_party.length ? h("p", {}, x.by_party.map((p) => (nm.party(p.party_id) || "No party") + " " + fmtMoney(Math.abs(p.balance))).join(" · ")) : null,
      table([{ k: "date", label: "Date" }, { k: "no", label: "Voucher" }, { k: "narration", label: "Narration" }, { label: "Party", v: (r) => nm.party(r.party_id) }, { k: "debit", label: "Debit", fmt: "money" }, { k: "credit", label: "Credit", fmt: "money" }, { k: "balance", label: "Balance", fmt: "money" }], x.rows, { name: "subledger", search: false, empty: "No entries." }))));
  }
  bcoTabbed("p/ipc", "Interim payment certificates", "Measurement → IPC → consultant certification → accounts → payment.",
    { firstLabel: "IPCs", tabs: [["Contract accounting (NFRS 15)", nfrsTab], ["Retention & advance ledgers", ledgersTab]] });

  /* ── variations: highly probable and estimated value ── */
  PAGES["p/variations"] = registerPage({ table: "variations", module: "commercial", title: "Variations", single: "variation",
    sub: "Identified → submitted → approved. Approval updates the revised BOQ quantity and rate (or creates a new BOQ item). Pending ones marked highly probable count in the NFRS 15 transaction price.",
    cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "title", label: "Title" }, { label: "BOQ", v: (r) => r.boq_item_id ? nm.boq(r.boq_item_id) : "New: " + (r.new_code || "") }, { k: "var_qty", label: "Qty change", fmt: "qty" }, { k: "new_rate", label: "New rate", fmt: "money" }, { k: "est_value", label: "Est. value", fmt: "money" }, { label: "Highly probable", v: (r) => r.highly_probable ? "Yes" : "" }, { k: "time_impact_days", label: "Time (d)", fmt: "qty" }, { k: "status", label: "Status", fmt: "status" }],
    locked: ["approved", "rejected"], defaults: () => ({ date: today() }),
    fields: () => [{ k: "date", label: "Date", type: "date" }, { k: "title", label: "Title", req: true, wide: true }, { k: "boq_item_id", label: "Existing BOQ item (leave blank for a new item)", type: "select", options: () => opt.boq(S.project), search: true }, { k: "var_qty", label: "Quantity change (+/−)", type: "number" }, { k: "new_rate", label: "New rate (blank = unchanged)", type: "number" },
      { k: "new_code", label: "New item code" }, { k: "new_description", label: "New item description" }, { k: "new_unit", label: "New item unit" }, { k: "time_impact_days", label: "Time impact (days)", type: "number" }, { k: "instruction_ref", label: "Instruction reference" },
      { k: "est_value", label: "Estimated value (blank = qty × rate)", type: "number" }, { k: "highly_probable", label: "Highly probable to be approved (NFRS 15)", type: "check" }, { k: "reason", label: "Reason / justification", type: "textarea", wide: true }],
    actions: (r, load) => r ? [r.status === "identified" && can("commercial", "edit") ? { label: "Submit", act: async () => { await run("var.submit", { id: r.id }, "Submitted"); await load(); } } : null,
      r.status === "submitted" && can("commercial", "approve") ? { label: "Approve", cls: "primary", act: async () => { await run("var.decide", { id: r.id, decision: "approved" }, "Approved — BOQ revised"); await reloadLookups(); load(); } } : null,
      r.status === "submitted" && can("commercial", "approve") ? { label: "Reject", cls: "warn", act: async () => { await run("var.decide", { id: r.id, decision: "rejected" }, "Rejected"); load(); } } : null] : [] });

  /* ── Commercial › Bids & markup ── */
  const BID_STATUS = [["preparing", "Preparing"], ["submitted", "Submitted"], ["won", "Won"], ["lost", "Lost"], ["cancelled", "Cancelled / not submitted"]];
  PAGES["c/bids"] = async (root, params) => {
    root.append(pageHead("Bids & markup", "Every tender with the engineer's estimate, our price and every competitor's price (from the e-GP opening sheet); hit rate and winning margins; and the markup that covers overhead and profit."));
    root.append(tabs([["Bid register", bidRegister], ["Hit rate & competitors", bidStats], ["Markup calculator", markupTab]], Number(params.tab || 0)));
  };
  async function bidRegister() {
    const box = h("div");
    const load = async () => {
      const rows = await api("bid.list", {});
      box.innerHTML = "";
      box.append(h("div", { class: "bar" }, h("div", { class: "grow" }), can("commercial", "edit") ? h("button", { class: "btn primary", onclick: () => bidEdit(null, load) }, "New bid") : null),
        table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "client", label: "Client" }, { k: "title", label: "Work" }, { k: "work_type", label: "Type" }, { k: "ee", label: "Engineer's estimate", fmt: "money" },
          { k: "our_bid", label: "Our bid", fmt: "money" }, { label: "Ours % of EE", v: (r) => pct(r.our_pct_ee) }, { label: "Markup", v: (r) => pct(r.markup_pct) }, { label: "Rank", v: (r) => r.our_rank ? r.our_rank + " of " + r.bidders : "" },
          { k: "winner", label: "Winner" }, { label: "Winner % of EE", v: (r) => pct(r.win_pct_ee) }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "bid_register", onRow: (r) => bidEdit(r, load), rowClass: (r) => r.status === "won" ? "" : r.status === "lost" ? "flag" : "" }));
    };
    await load();
    return box;
  }
  function bidEdit(b, done) {
    const f = form([{ k: "date", label: "Date", type: "date", default: today() }, { k: "submission_date", label: "Submission date", type: "date" }, { k: "client", label: "Client / employer" }, { k: "title", label: "Work", req: true, wide: true },
      { k: "work_type", label: "Type of work (road, hydro, building…)" }, { k: "location", label: "Location" }, { k: "ee", label: "Engineer's estimate (cost estimate)", type: "number" },
      { k: "our_cost", label: "Our estimated cost", type: "number" }, { k: "our_bid", label: "Our bid", type: "number" }, { k: "markup_pct", label: "Markup % on cost (blank = from cost and bid)", type: "number" },
      { k: "bid_security", label: "Bid security", type: "number" }, { k: "status", label: "Status", type: "select", noBlank: true, options: BID_STATUS }, { k: "winner", label: "Winner" }, { k: "winning_bid", label: "Winning bid", type: "number" },
      { k: "project_id", label: "Project (if won)", type: "select", options: opt.projects }, { k: "remarks", label: "Remarks", wide: true }], b || { status: "preparing" });
    const pr = lineEditor([{ k: "bidder", label: "Bidder", w: 220 }, { k: "price", label: "Quoted price", type: "number", w: 150 }, { k: "is_us", label: "Us?", type: "select", noBlank: true, options: [["0", "No"], ["1", "Yes"]] },
      { k: "responsive", label: "Responsive", type: "select", noBlank: true, options: [["1", "Yes"], ["0", "No"]] }, { k: "remarks", label: "Remarks", w: 160 }],
    (b && b.prices ? b.prices : []).map((p) => Object.assign({}, p, { is_us: String(p.is_us), responsive: String(p.responsive) })), { blank: { is_us: "0", responsive: "1" } });
    modal(b ? b.no + " " + b.title : "New bid", h("div", {}, f, h("h3", {}, "Bid opening sheet (all prices read out)"), pr), can("commercial", "edit") ? [
      { label: "Save", cls: "primary", act: async () => { await run("bid.save", { row: Object.assign(f.values(), { id: b && b.id }), prices: pr.lines() }, "Saved"); done(); } },
      b ? { label: "Delete", cls: "warn", act: async () => { await run("bid.delete", { id: b.id }, "Deleted"); done(); } } : null] : []);
  }
  async function bidStats() {
    const d = await api("bid.stats", {});
    const g = [{ k: "key", label: "" }, { k: "bids", label: "Decided bids", fmt: "num" }, { k: "won", label: "Won", fmt: "num" }, { label: "Hit rate", v: (r) => r.hit_rate + "%" },
      { label: "Winning bid % of EE", v: (r) => pct(r.avg_winning_pct_ee) }, { label: "Our bid % of EE", v: (r) => pct(r.avg_our_pct_ee) }, { label: "We were above the winner by", v: (r) => pct(r.avg_gap_when_lost) }];
    return h("div", {}, h("div", { class: "tiles" }, tile("Hit rate", d.hit_rate == null ? "—" : d.hit_rate + "%"), tile("Bids decided", d.decided), tile("Won", d.won), tile("Value won", fmtMoney(d.won_value))),
      h("h2", { class: "sec" }, "By client"), table(g.map((c, i) => i === 0 ? Object.assign({}, c, { label: "Client" }) : c), d.by_client, { name: "hit_rate_client", search: false }),
      h("h2", { class: "sec" }, "By type of work"), table(g.map((c, i) => i === 0 ? Object.assign({}, c, { label: "Type" }) : c), d.by_type, { name: "hit_rate_type", search: false }),
      h("h2", { class: "sec" }, "Competitors to watch"), table([{ k: "bidder", label: "Competitor" }, { k: "bids", label: "Met in bids", fmt: "num" }, { k: "wins", label: "Won", fmt: "num" }, { k: "beat_us", label: "Priced below us", fmt: "num" }, { label: "Their price % of EE", v: (r) => pct(r.avg_pct_ee) }], d.competitors, { name: "competitors" }));
  }
  async function markupTab() {
    const g = await api("markup.get", {});
    const f = form([{ k: "overhead", label: "Head-office overhead for the year", type: "number", default: g.overhead_budget }, { k: "profit", label: "Profit wanted for the year", type: "number" },
      { k: "volume", label: "Expected volume of work (revenue)", type: "number", default: g.revenue_last_12m }, { k: "risk_pct", label: "Adjustment for this bid (risk +, courtesy/price check −) %", type: "number", default: 0 }]);
    const out = h("div", { class: "panel" });
    let last = null;
    const calc = async () => {
      const v = f.values();
      out.innerHTML = "";
      if (!Number(v.volume)) { out.append(h("p", { class: "muted" }, "Enter the volume of work.")); return; }
      try { last = await api("markup.calc", v); } catch (e) { out.append(h("p", { class: "red" }, e.message)); return; }
      out.append(kv([["Direct cost of that volume", fmtMoney(last.direct_cost)], ["Markup on cost", h("b", {}, last.markup_pct + "%")], ["= overhead on cost", last.overhead_pct_on_cost + "%"], ["+ profit on cost", last.profit_pct_on_cost + "%"],
        ["Gross margin on price", last.gross_margin_pct + "%"], ["Break-even volume (revenue that just covers overhead)", fmtMoney(last.break_even_volume)], ["Markup for this bid", last.bid_markup_pct + "% (margin " + last.bid_margin_pct + "%)"]]),
      can("commercial", "approve") ? h("button", { class: "btn primary", onclick: async () => { await run("markup.apply", { overhead_pct: last.overhead_pct_on_cost, profit_pct: last.profit_pct_on_cost }, "Rate analysis now adds overhead " + last.overhead_pct_on_cost + "% and profit " + last.profit_pct_on_cost + "%"); } }, "Use in rate analysis") : "");
    };
    f.addEventListener("change", calc);
    calc();
    return h("div", {}, h("p", { class: "hint" }, "Markup and margin are not the same: markup is added to cost, margin is the share of the price. Markup = margin ÷ (100 − margin); a 15% markup is only a 13.04% margin. Rate analysis now uses overhead " + g.ra_overhead_pct + "% + profit " + g.ra_profit_pct + "% on cost; only the overhead goes into the BOQ budget cost."),
      h("div", { class: "cols" }, h("div", { class: "panel" }, h("h2", {}, "Required markup"), f), out),
      h("h2", { class: "sec" }, "Markup ↔ margin"), table([{ label: "Markup on cost", v: (r) => r.markup + "%" }, { label: "Gross margin on price", v: (r) => r.margin + "%" }], g.table, { search: false, export: false }));
  }

  /* ── rate analysis page: show the overhead / profit split ── */
  const origRa = PAGES["rp/ra"];
  if (origRa) PAGES["rp/ra"] = async (root, params) => {
    await origRa(root, params);
    try {
      const g = await api("markup.get", {});
      const tot = g.ra_overhead_pct + g.ra_profit_pct;
      const note = h("div", { class: "panel" }, h("b", {}, "Overhead and profit: "), "the % you enter is markup on cost; it is split overhead " + g.ra_overhead_pct + " : profit " + g.ra_profit_pct +
        " (set in Commercial › Bids & markup). Only the overhead part goes into the BOQ item's budget cost. " + tot + "% markup = " + fmtN(100 * tot / (100 + tot), 2) + "% margin on price.");
      const bar = root.querySelector(".bar");
      if (bar && bar.nextSibling) root.insertBefore(note, bar.nextSibling); else root.append(note);
    } catch (e) { /* the note is only a help */ }
  };

  /* ── Budget vs actual › head-office overhead budget ── */
  async function ohTab() {
    const box = h("div");
    let fy = null, d = null, rows = [];
    const edit = can("accounts", "edit");
    const inputs = [];
    const render = () => {
      box.innerHTML = "";
      inputs.length = 0;
      const fysel = h("select", { onchange: (e) => { fy = e.target.value; load(); } }, [d.fy - 1, d.fy, d.fy + 1].map((y) => h("option", { value: y, selected: y === d.fy }, y + "/" + String((y + 1) % 100).padStart(2, "0"))));
      box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Fiscal year"), fysel), h("div", { class: "grow" }),
        h("span", { class: "hint" }, "Budget " + fmtMoney(d.total_budget) + " · actual " + fmtMoney(d.total_actual))));
      const tb = h("tbody");
      rows.forEach((r) => {
        const acc = h("select", { disabled: !edit, style: "min-width:150px" }, h("option", { value: "" }, "— account —"), d.accounts.map((a) => h("option", { value: a.id, selected: String(a.id) === String(r.account_id) }, a.code + " " + a.name)));
        const kind = h("select", { disabled: !edit }, [["fixed", "Fixed"], ["variable", "Variable"]].map(([v, l]) => h("option", { value: v, selected: v === r.kind }, l)));
        const cat = h("input", { value: r.category, disabled: !edit, style: "min-width:160px" });
        const cells = r.budget.map((v) => h("input", { type: "number", step: "any", value: v || "", disabled: !edit, style: "width:84px" }));
        inputs.push({ r, cat, acc, kind, cells });
        tb.append(h("tr", {}, h("td", {}, cat), h("td", {}, acc), h("td", {}, kind), cells.map((c, i) => h("td", { title: "Actual " + fmtMoney((r.actual || [])[i] || 0) }, c)),
          h("td", { class: "num" }, fmtMoney(r.budget_total)), h("td", { class: "num" }, fmtMoney(r.actual_total)), h("td", { class: "num" }, r.variance_to_date == null ? "" : h("b", { class: r.variance_to_date > 0 ? "red" : "green" }, fmtMoney(r.variance_to_date))), h("td", { class: "num" }, fmtMoney(r.projection_next_year))));
      });
      box.append(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Category", "Account", "Kind"].concat(d.months).concat(["Budget", "Actual", "Actual − budget to date", "Next year (trend)"]).map((x) => h("th", {}, x)))), tb)),
        h("p", { class: "hint" }, "Actuals are head-office costs: postings to the mapped account with no project. Hover a month for its actual. Next year's figure is this year's run-rate plus 7% inflation."));
      const collect = () => inputs.map((x) => ({ category: x.cat.value, account_id: x.acc.value, kind: x.kind.value, budget: x.cells.map((c) => c.value) }));
      if (edit) box.append(h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => {
        const keep = collect();
        rows = keep.map((k, i) => Object.assign({}, rows[i], k, { budget: k.budget.map((v) => Number(v) || 0) })).concat([{ category: "", kind: "fixed", budget: Array(12).fill(0), actual: [] }]);
        render();
      } }, "Add category"),
      h("button", { class: "btn primary", onclick: async () => { await run("oh.save", { fy, rows: collect() }, "Overhead budget saved"); load(); } }, "Save budget")));
      if (d.unmapped_actuals.length) box.append(h("div", { class: "panel" }, h("h3", {}, "Head-office costs on accounts not in the budget"), table([{ k: "code", label: "Account" }, { k: "name", label: "Name" }, { k: "amt", label: "This year", fmt: "money" }], d.unmapped_actuals, { search: false, export: false })));
    };
    const load = async () => {
      d = await api("oh.get", { fy });
      fy = d.fy;
      rows = d.rows.length ? d.rows : d.categories.map((c) => ({ category: c, kind: "fixed", budget: Array(12).fill(0), actual: Array(12).fill(0) }));
      render();
    };
    await load();
    return box;
  }
  bcoTabbed("acc/budget", "Budget vs actual", "Project cost budgets against actual, and the head-office overhead budget by month.", { firstLabel: "Project budgets", tabs: [["Head-office overhead budget", ohTab]] });

  /* ── Accounts › Cash forecast & ratios ── */
  PAGES["acc/cash"] = async (root, params) => {
    root.append(pageHead("Cash forecast & ratios", "Twelve months of company cash from every project's schedule and payment terms, the overhead budget, loans and advance tax; and the financial ratios with months in backlog."));
    root.append(tabs([["Company cash budget", companyCash], ["Loans & settings", loansTab], ["Financial ratios", ratiosTab]], Number(params.tab || 0)));
  };
  async function companyCash() {
    const box = h("div");
    let v = { delay: 0, overrun: 0 };
    const load = async () => {
      const args = { months: 12, delay: v.delay, overrun: v.overrun };
      if (v.np_value) args.new_project = { start: v.np_start, value: v.np_value, months: v.np_months, margin: v.np_margin };
      const d = await api("cash.company", args);
      box.innerHTML = "";
      const f = form([{ k: "delay", label: "IPCs paid late by (days)", type: "number" }, { k: "overrun", label: "Cost overrun %", type: "number" },
        { k: "np_start", label: "New project starts (month)", type: "month" }, { k: "np_value", label: "New project value", type: "number" }, { k: "np_months", label: "Duration (months)", type: "number" }, { k: "np_margin", label: "Margin %", type: "number" }], v);
      f.className = "bar"; f.append(h("button", { class: "btn primary", onclick: () => { v = f.values(); load(); } }, "Test"));
      box.append(h("p", { class: "hint" }, "Sensitivity: try “IPCs paid 60 days late” or “a new lot starts in Magh” and see the overdraft needed and the month it bites."), f,
        h("div", { class: "tiles" }, tile("Cash & bank today", fmtMoney(d.opening)), tile("Lowest balance", d.lowest ? fmtMoney(d.lowest.balance) : "—", { cls: d.lowest && d.lowest.balance < d.min_balance ? "bad" : "", sub: d.lowest ? d.lowest.month : null }),
          tile("First month below the minimum", d.first_shortfall || "none", { cls: d.first_shortfall ? "bad" : "", sub: "minimum " + fmtMoney(d.min_balance) }), tile("Largest overdraft needed", fmtMoney(d.max_overdraft), { cls: d.max_overdraft > 0 ? "warn" : "" })),
        h("div", { class: "panel" }, bars(d.months.map((m) => m.slice(2)), [{ name: "Closing balance (M)", color: "#1b5e86", values: d.rows.map((r) => Math.max(0, r.closing) / 1e6) }, { name: "Overdraft needed (M)", color: "#b3392c", values: d.rows.map((r) => r.overdraft_needed / 1e6) }], { stacked: false })),
        table([{ k: "label", label: "" }].concat(d.months.map((m, i) => ({ label: m, fmt: "money", v: (r) => r.values[i] }))).concat([{ k: "total", label: "12 months", fmt: "money" }]),
          d.lines.concat([{ label: "Net cash flow", values: d.rows.map((r) => r.net), total: d.rows.reduce((a, r) => a + r.net, 0) }, { label: "Closing balance", values: d.rows.map((r) => r.closing), total: null }, { label: "Overdraft needed", values: d.rows.map((r) => r.overdraft_needed), total: null }]),
          { name: "company_cash_budget", search: false }),
        h("p", { class: "hint" }, d.note + (d.overhead_budgeted ? "" : " No overhead budget yet: the last 12 months of head-office cost is used.")),
        h("h3", {}, "Peak cash by project"), table([{ k: "code", label: "Project" }, { k: "peak_cash", label: "Peak cash needed", fmt: "money" }, { k: "peak_month", label: "Month" }, { k: "error", label: "" }], d.projects, { search: false, export: false }));
    };
    await load();
    return box;
  }
  async function loansTab() {
    const box = h("div");
    const load = async () => {
      const rows = await api("loan.list", {});
      box.innerHTML = "";
      const edit = can("accounts", "edit");
      const s = S.L.settings || {};
      const sf = form([{ k: "cash_min_balance", label: "Minimum bank balance to keep", type: "number" }, { k: "cash_interest_pct", label: "Overdraft interest % a year", type: "number" },
        { k: "advance_tax_estimate", label: "Estimated income tax for the year (advance tax)", type: "number" }, { k: "cash_limit_npr", label: "Largest single cash payment (NPR)", type: "number" }], s);
      box.append(h("div", { class: "panel" }, h("h2", {}, "Settings"), sf, edit ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("cash.settings", sf.values(), "Saved"); await reloadLookups(); } }, "Save")) : null),
        h("div", { class: "bar" }, h("h2", { class: "grow" }, "Loans and facilities"), edit ? h("button", { class: "btn", onclick: () => loanEdit(null) }, "Add loan") : null),
        table([{ k: "name", label: "Loan" }, { k: "lender", label: "Lender" }, { k: "kind", label: "Kind" }, { k: "emi", label: "Instalment / month", fmt: "money" }, { k: "start_date", label: "From" }, { k: "end_date", label: "To" }, { k: "balance", label: "Balance", fmt: "money" }, { k: "rate", label: "Rate %", fmt: "num" }, { k: "limit_amount", label: "Limit", fmt: "money" }, { k: "active", label: "Active", fmt: "yes" }], rows, { search: false, onRow: edit ? loanEdit : null }));
    };
    const loanEdit = (l) => {
      const f = form([{ k: "name", label: "Name", req: true }, { k: "lender", label: "Bank / lender" }, { k: "kind", label: "Kind", type: "select", noBlank: true, options: [["term", "Term loan"], ["od", "Overdraft limit"], ["equipment", "Equipment loan / hire purchase"], ["guarantee", "Guarantee line"]] },
        { k: "emi", label: "Instalment per month", type: "number" }, { k: "start_date", label: "From", type: "date" }, { k: "end_date", label: "To", type: "date" }, { k: "balance", label: "Balance now", type: "number" }, { k: "rate", label: "Interest %", type: "number" }, { k: "limit_amount", label: "Limit", type: "number" }, { k: "active", label: "Active", type: "check" }, { k: "remarks", label: "Remarks", wide: true }], l || { active: 1, kind: "term" });
      modal(l ? l.name : "New loan", f, [{ label: "Save", cls: "primary", act: async () => { await run("loan.save", { row: Object.assign(f.values(), { id: l && l.id }) }, "Saved"); load(); } },
        l ? { label: "Delete", cls: "warn", act: async () => { await run("loan.delete", { id: l.id }, "Deleted"); load(); } } : null], { narrow: true });
    };
    await load();
    return box;
  }
  async function ratiosTab() {
    const d = await api("ratio.get", { trend: 6 });
    const groups = [...new Set(d.rows.map((r) => r.group))];
    const val = (r) => r.value == null ? "—" : fmtN(r.value, 2) + (r.unit === "%" ? "%" : r.unit === "x" ? "×" : " " + r.unit);
    const tf = form(d.rows.filter((r) => r.key).map((r) => ({ k: r.key, label: r.name + " target", type: "number" })), Object.fromEntries(d.rows.filter((r) => r.key).map((r) => [r.key, r.target])));
    return h("div", {}, h("div", { class: "tiles" }, tile("Backlog (work not yet done)", fmtMoney(d.backlog)), tile("Revenue, last 12 months", fmtMoney(d.revenue_12m)), tile("Net profit, last 12 months", fmtMoney(d.net_profit_12m)), tile("Net worth", fmtMoney(d.equity))),
      ...groups.map((g) => h("div", { class: "panel" }, h("h2", {}, g), table([{ k: "name", label: "Ratio" }, { label: "Now", v: (r) => h("b", { class: r.ok === false ? "red" : r.ok ? "green" : "" }, val(r)) }, { label: "Target", v: (r) => r.target == null ? "" : fmtN(r.target, 2) },
        ...d.trend.map((t) => ({ label: t.as_of.slice(0, 7), v: (r) => t.values[r.name] == null ? "—" : fmtN(t.values[r.name], 2) }))], d.rows.filter((r) => r.group === g), { search: false, export: false }))),
      h("p", { class: "hint" }, d.note + " Months in backlog = unperformed work ÷ last 12 months' revenue × 12 — also the remaining performance obligations for NFRS 15."),
      can("accounts", "edit") ? h("details", {}, h("summary", {}, "Set targets"), tf, h("button", { class: "btn", onclick: async () => { await run("ratio.targets", { targets: tf.values() }, "Targets saved"); } }, "Save targets")) : null);
  }

  /* ── Command centre: cash, backlog, ratios, hit rate ── */
  const origCmd = PAGES.command;
  PAGES.command = async (root, params) => {
    await origCmd(root, params);
    try {
      const d = await api("cash.summary", {});
      const tiles = [];
      if (d.cash != null) tiles.push(tile("Cash & bank", fmtMoney(d.cash), { href: "#/acc/cash" }));
      if (d.lowest) tiles.push(tile("Lowest cash in 12 months", fmtMoney(d.lowest.balance), { cls: d.first_shortfall ? "bad" : "", sub: d.lowest.month + (d.first_shortfall ? " · short from " + d.first_shortfall : ""), href: "#/acc/cash" }));
      if (d.backlog != null) tiles.push(tile("Backlog", fmtMoney(d.backlog), { href: "#/acc/cash?tab=2" }));
      (d.ratios || []).forEach((r) => tiles.push(tile(r.name, r.value == null ? "—" : fmtN(r.value, 2) + (r.unit === "%" ? "%" : r.unit === "x" ? "×" : " " + r.unit), { cls: r.ok === false ? "warn" : "", href: "#/acc/cash?tab=2" })));
      if (d.hit_rate !== undefined) tiles.push(tile("Bid hit rate", d.hit_rate == null ? "—" : d.hit_rate + "%", { sub: (d.bids_open || 0) + " bids open", href: "#/c/bids?tab=1" }));
      if (tiles.length) {
        const panel = h("div", {}, h("h2", { class: "sec" }, "Cash, backlog and ratios"), h("div", { class: "tiles" }, tiles));
        const t = root.querySelector(".tiles");
        if (t && t.nextSibling) root.insertBefore(panel, t.nextSibling); else root.append(panel);
      }
    } catch (e) { /* never hide the portfolio */ }
  };
  PAGES.command.live = true;
})();
