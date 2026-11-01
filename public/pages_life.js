/* BuildCore 2.2 — equipment and asset life cycle inside existing screens:
   Equipment › Register (business cases, acquisition files, replacement & disposal, QR verification, maturity),
   Monthly logsheets (inspections & violations), Work orders (breakdown analysis), Maintenance (class rules,
   spares, spare forecast), Day-by-day log (telematics import), Fixed assets › Equipment costing (decision tools),
   Assets › Asset register (QR verification) and the phone page opened by a QR tag. */
(function () {
  "use strict";
  let OPT = null;
  const opts = async () => { if (!OPT) OPT = await api("life.options", {}); return OPT; };
  const bars = (...a) => window.bcoBars(...a);
  const eqOpts = () => S.L.equipment.map((e) => [e.id, e.code + " " + e.name]);

  /* ── business cases ── */
  async function casesTab() {
    const box = h("div");
    const load = async () => {
      const [rows, dem] = await Promise.all([api("life.case_list", {}), api("life.demand", {})]);
      box.innerHTML = "";
      box.append(h("div", { class: "bar" }, h("p", { class: "hint grow" }, "Before buying: the need from the schedule, buy vs hire vs lease on NPV and annual cost, a failure-risk rating and the savings expected — then, after purchase, the savings actually made (ISO 55000 business-case stage)."),
        can("equipment", "edit") ? h("button", { class: "btn primary", onclick: () => caseEdit(null, dem, load) }, "New business case") : null),
      table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "title", label: "Purchase" }, { k: "category", label: "Type" }, { k: "hours_year", label: "Hours a year", fmt: "num" },
        { label: "Cheapest", v: (r) => (r.result || {}).best }, { k: "chosen", label: "Chosen" }, { label: "Risk", v: (r) => (r.result || {}).risk_level || "" }, { k: "savings_year", label: "Savings promised / yr", fmt: "money" },
        { label: "Savings made (12 months)", v: (r) => r.actual ? h("b", { class: r.actual.actual_savings < r.savings_year * 0.8 ? "red" : "green" }, fmtMoney(r.actual.actual_savings)) : "" },
        { k: "status", label: "Status", fmt: "status" }], rows, { name: "business_cases", onRow: (r) => caseEdit(r, dem, load) }),
      h("h2", { class: "sec" }, "Machine demand in the schedules (remaining work)"),
      table([{ k: "name", label: "Machine type" }, { k: "hours", label: "Hours still to work", fmt: "num" }, { k: "from", label: "From" }, { k: "to", label: "To" }, { k: "hours_year", label: "Hours a year", fmt: "num" }, { k: "owned", label: "Owned now", fmt: "num" }],
        dem, { search: false, name: "machine_demand", empty: "Load resources on the schedules first (Schedule & WBS › Resources)." }));
    };
    await load();
    return box;
  }
  function caseEdit(r, dem, done) {
    const inp = (r && r.inputs) || {};
    const b = inp.buy || {}, hi = inp.hire || {}, le = inp.lease || {};
    const locked = r && ["approved", "rejected"].includes(r.status);
    const f = form([{ k: "title", label: "Purchase", req: true, wide: true }, { k: "category", label: "Machine type" }, { k: "project_id", label: "For project", type: "select", options: opt.projects },
      { k: "need", label: "Need (from the schedule demand)", type: "textarea", wide: true }, { k: "hours_year", label: "Hours a year", type: "number" }, { k: "years", label: "Study period (years)", type: "number" }, { k: "marr", label: "MARR %", type: "number" },
      { k: "b_price", label: "Buy: price", type: "number" }, { k: "b_salvage", label: "Buy: salvage at the end", type: "number" }, { k: "b_fixed", label: "Buy: insurance, tax, storage a year", type: "number" }, { k: "b_op", label: "Buy: running cost per hour", type: "number" },
      { k: "h_rate", label: "Hire: rate per hour", type: "number" }, { k: "h_min", label: "Hire: minimum hours a month", type: "number" }, { k: "h_mob", label: "Hire: mobilisation a year", type: "number" },
      { k: "l_pay", label: "Lease: payment a month", type: "number" }, { k: "l_term", label: "Lease: term (months)", type: "number" }, { k: "l_buyout", label: "Lease: buy-out at the end", type: "number" }, { k: "l_op", label: "Lease: running cost per hour", type: "number" },
      { k: "risk_likelihood", label: "Failure likelihood (1 rare – 5 frequent)", type: "number" }, { k: "risk_consequence", label: "Consequence (1 minor – 5 stops the job)", type: "number" }, { k: "risk_note", label: "Failure risks and how they are covered", wide: true },
      { k: "chosen", label: "Decision", type: "select", options: [["Buy", "Buy"], ["Hire", "Hire"], ["Lease", "Lease"]] }, { k: "equipment_id", label: "Machine bought (after purchase)", type: "select", options: eqOpts }, { k: "remarks", label: "Remarks", wide: true }].map((x) => Object.assign(x, { readonly: locked && x.k !== "equipment_id" })),
    Object.assign({ years: 5, marr: (OPT && OPT.marr) || 12 }, r || {}, { b_price: b.price, b_salvage: b.salvage, b_fixed: b.fixed_year, b_op: b.operating_hour, h_rate: hi.rate_hour, h_min: hi.min_hours_month, h_mob: hi.mob_per_year,
      l_pay: le.payment_month, l_term: le.term_months, l_buyout: le.residual_buyout, l_op: le.operating_hour }));
    const res = h("div", { class: "panel" });
    const row = () => {
      const v = f.values();
      return { id: r && r.id, title: v.title, category: v.category, project_id: v.project_id, need: v.need, hours_year: v.hours_year, years: v.years, marr: v.marr, chosen: v.chosen, equipment_id: v.equipment_id,
        risk_likelihood: v.risk_likelihood, risk_consequence: v.risk_consequence, risk_note: v.risk_note, remarks: v.remarks,
        inputs: { buy: { price: v.b_price, salvage: v.b_salvage, fixed_year: v.b_fixed, operating_hour: v.b_op }, hire: { rate_hour: v.h_rate, min_hours_month: v.h_min, mob_per_year: v.h_mob, operating_hour: 0 },
          lease: { payment_month: v.l_pay, term_months: v.l_term, residual_buyout: v.l_buyout, operating_hour: v.l_op } } };
    };
    const calc = async () => {
      const x = await api("life.calc", { row: row() });
      res.innerHTML = "";
      res.append(h("h3", {}, "Buy, hire or lease"), table([{ k: "option", label: "Option" }, { k: "annual_cost", label: "Annual equivalent cost", fmt: "money" }, { k: "cost_per_hour", label: "Per hour", fmt: "money" }, { k: "npv", label: "NPV of costs", fmt: "money" }], x.options, { search: false, export: false }),
        kv([["Cheapest", h("b", {}, x.best || "—")], ["Savings a year against hiring", fmtMoney(x.savings_year)], ["Failure risk", x.risk_score ? x.risk_score + " (" + x.risk_level + ")" : "not rated"]]));
    };
    f.addEventListener("change", calc);
    calc();
    const acq = h("div");
    if (r) api("life.acq_get", { case_id: r.id }).then((d) => acq.append(acqTable(d, () => caseEdit(r, dem, done))));
    const btns = [];
    if (can("equipment", "edit") && (!locked || true)) btns.push({ label: "Save", cls: "primary", act: async () => { await run("life.case_save", { row: row() }, "Saved"); done(); } });
    if (r && r.status === "draft" && can("equipment", "edit")) btns.push({ label: "Submit for approval", act: async () => { await run("life.case_save", { row: row() }); await run("life.case_decide", { id: r.id, status: "submitted" }, "Submitted"); done(); } });
    if (r && r.status === "submitted" && can("equipment", "approve")) {
      btns.push({ label: "Approve", cls: "primary", act: async () => { await run("life.case_decide", { id: r.id, status: "approved" }, "Approved"); done(); } });
      btns.push({ label: "Reject", cls: "warn", act: async () => { await run("life.case_decide", { id: r.id, status: "rejected" }, "Rejected"); done(); } });
    }
    drawer(r ? r.no + " " + r.title : "New business case", h("div", {}, f, res, r && r.actual ? h("div", { class: "panel" }, h("h3", {}, "After purchase — last 12 months"), kv([["Hours worked", fmtN(r.actual.hours)], ["What it cost", fmtMoney(r.actual.cost)], ["Hiring the same hours would cost", fmtMoney(r.actual.hire_equivalent)], ["Savings made", fmtMoney(r.actual.actual_savings)], ["Savings promised a year", fmtMoney(r.actual.promised_savings)]])) : null,
      r ? h("div", {}, h("h3", {}, "Acquisition file"), acq) : null, r ? recordPanel("asset_cases", r.id, {}) : null), btns, { head: r ? stamp(r.status) : null });
  }
  function acqTable(d, reload) {
    return h("div", {}, h("p", { class: "hint" }, d.done + " of " + d.total + " steps done. Attach each document below."),
      table([{ k: "label", label: "Step" }, { label: "Done", v: (s) => s.done ? h("b", { class: "green" }, "✓") : "" }, { k: "date", label: "Date" }, { k: "ref", label: "Reference" }, { k: "supplier", label: "Supplier" }, { label: "Vetted", v: (s) => s.vetted ? "Yes" : "" }, { k: "notes", label: "Notes" }],
        d.steps, { search: false, export: false, onRow: can("equipment", "edit") ? (s) => {
          const f = form([{ k: "done", label: "Done", type: "check" }, { k: "date", label: "Date", type: "date" }, { k: "ref", label: "Reference / document no." }, { k: "supplier", label: "Supplier" }, { k: "vetted", label: "Supplier vetted", type: "check" }, { k: "notes", label: "Notes", wide: true }], s);
          modal(s.label, f, [{ label: "Save", cls: "primary", act: async () => { await run("life.acq_save", { row: Object.assign(f.values(), { id: s.id }) }, "Saved"); reload(); } }], { narrow: true });
        } : null }));
  }
  async function acqMachineTab() {
    const box = h("div");
    const sel = h("select", { onchange: () => load() }, h("option", { value: "" }, "— choose a machine —"), eqOpts().map(([v, l]) => h("option", { value: v }, l)));
    const out = h("div");
    const load = async () => {
      out.innerHTML = "";
      if (!sel.value) return;
      const d = await api("life.acq_get", { equipment_id: sel.value });
      out.append(acqTable(d, load), recordPanel("equipment_acq", Number(sel.value), {}));
    };
    box.append(h("p", { class: "hint" }, "One file per machine (Wang, Fig. 2): application, price comparison, supplier selection and vetting, contract, receipt and acceptance, installation and commissioning, put into operation."), h("label", { class: "f" }, h("span", {}, "Machine"), sel), out);
    return box;
  }

  /* ── replacement & disposal ── */
  async function replacementTab() {
    const box = h("div");
    const load = async () => {
      const [d, disp] = await Promise.all([api("life.replacement_scan", {}), api("life.disp_list", {})]);
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Triggers: economic life reached (lowest annual equivalent cost of ownership at " + d.marr + "% MARR), repairs above the set share of the price or rising fast, or repeated breakdowns on a class A machine. Then: expert assessment → scrap application → evaluation → approval → sale or scrap (posted in Fixed assets)."),
        table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "class", label: "Class" }, { k: "age", label: "Age (years)", fmt: "num" }, { k: "economic_life", label: "Economic life", fmt: "num" }, { k: "repairs_12m", label: "Repairs 12 months", fmt: "money" }, { k: "breakdowns_90d", label: "Breakdowns 90 days", fmt: "num" },
          { label: "Triggers", v: (r) => r.triggers.length ? h("b", { class: "red" }, r.triggers.join("; ")) : "—" },
          { label: "", v: (r) => r.disposal ? r.disposal.no + " (" + r.disposal.status + ")" : (r.triggers.length && can("equipment", "edit") ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("life.disp_save", { row: { equipment_id: r.id, trigger: r.triggers.join("; ") } }, "Disposal proposed"); load(); } }, "Propose disposal") : "") }],
        d.rows, { name: "replacement_scan", rowClass: (r) => r.triggers.length ? "flag" : "", onRow: (r) => r.euac.length ? modal(r.code + " — cost of keeping it n years", table([{ k: "year", label: "Keep for (years)" }, { k: "salvage", label: "Salvage then", fmt: "money" }, { k: "capital_recovery", label: "Capital recovery / yr", fmt: "money" }, { k: "om_equivalent", label: "Repairs, equivalent / yr", fmt: "money" }, { k: "euac", label: "Annual equivalent cost", fmt: "money" }], r.euac, { search: false, rowClass: (x) => x.year === r.economic_life ? "flag" : "" }), []) : null }),
        h("h2", { class: "sec" }, "Disposals"),
        table([{ k: "no", label: "No." }, { label: "Machine", v: (x) => (x.eq_code || "") + " " + (x.eq_name || "") }, { k: "trigger", label: "Why" }, { k: "evaluation_value", label: "Evaluated at", fmt: "money" }, { k: "method", label: "Sale / scrap" }, { k: "proceeds", label: "Proceeds", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
          disp, { search: false, onRow: (x) => dispEdit(x, load), empty: "No disposals." }));
    };
    await load();
    return box;
  }
  function dispEdit(x, done) {
    const closed = ["completed", "cancelled"].includes(x.status);
    const f = form([{ k: "trigger", label: "Why (trigger)", wide: true }, { k: "assessment", label: "Expert assessment", type: "textarea", wide: true }, { k: "assessed_by", label: "Assessed by" },
      { k: "application", label: "Scrap / sale application", type: "textarea", wide: true }, { k: "evaluation_value", label: "Evaluation (value)", type: "number" }, { k: "process", label: "Process sheet notes", wide: true },
      { k: "method", label: "Method", type: "select", options: [["sale", "Sale"], ["auction", "Auction"], ["scrap", "Scrap"], ["transfer", "Transfer"]] }, { k: "proceeds", label: "Proceeds", type: "number" }, { k: "remarks", label: "Remarks", wide: true }].map((y) => Object.assign(y, { readonly: closed })), x);
    const b = [];
    if (!closed && can("equipment", "edit")) b.push({ label: "Save", act: async () => { await run("life.disp_save", { row: Object.assign(f.values(), { id: x.id }) }, "Saved"); done(); } });
    if (!closed && can("equipment", "approve")) {
      b.push({ label: x.status === "approved" ? "Complete (post in Fixed assets)" : "Next step", cls: "primary", act: async () => { await run("life.disp_save", { row: Object.assign(f.values(), { id: x.id }) }); const r = await run("life.disp_advance", { id: x.id, method: f.values().method, proceeds: f.values().proceeds }); toast("Now " + r.status, "ok"); done(); } });
      b.push({ label: "Cancel disposal", cls: "warn", act: async () => { await run("life.disp_advance", { id: x.id, cancel: 1 }, "Cancelled"); done(); } });
    }
    drawer("Disposal " + x.no, h("div", {}, h("p", { class: "hint" }, "Stages: proposed → assessed → applied → evaluated → approved → completed."), f, recordPanel("asset_disposals", x.id, {})), b, { head: stamp(x.status) });
  }

  /* ── QR tags and verification ── */
  function qrSvg(text, size) {
    const qr = window.qrcode(0, "M");
    qr.addData(text); qr.make();
    const n = qr.getModuleCount(), c = size / (n + 8);
    let d = "";
    for (let r = 0; r < n; r++) for (let k = 0; k < n; k++) if (qr.isDark(r, k)) d += `M${(k + 4) * c},${(r + 4) * c}h${c}v${c}h-${c}z`;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"><rect width="100%" height="100%" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  }
  async function baseUrl() {
    try {
      const s = await api("server.info", {});
      const a = (s.addresses || []).find((x) => !/127\.0\.0\.1|localhost/.test(x));
      if (a) return a.replace(/\/$/, "");
    } catch (e) { /* not an admin */ }
    return location.origin;
  }
  async function qrTab(kindFilter) {
    const box = h("div");
    const load = async () => {
      const [items, rounds] = await Promise.all([api("life.tags", {}), api("life.rounds", {})]);
      const list = items.filter((t) => !kindFilter || t.kind === kindFilter);
      box.innerHTML = "";
      const base = h("input", { value: await baseUrl(), style: "min-width:280px" });
      const pick = new Set();
      box.append(h("div", { class: "panel" }, h("h2", {}, "Print QR labels"), h("p", { class: "hint" }, "Each label opens this item in BuildCore on a phone. Use the address the phones reach BuildCore on (Administration › Remote access)."),
        h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Address in the QR code"), base), h("button", { class: "btn primary", onclick: () => printLabels(list.filter((t) => !pick.size || pick.has(t.kind + t.id)), base.value) }, "Print labels (ticked, or all)")),
        table([{ label: "", v: (t) => h("input", { type: "checkbox", style: "width:auto", onclick: (e) => { e.stopPropagation(); const k = t.kind + t.id; if (e.target.checked) pick.add(k); else pick.delete(k); } }) },
          { label: "Kind", v: (t) => t.kind === "eq" ? "Machine" : "Asset" }, { k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "extra", label: "Reg. / location" }], list, { name: "qr_tags" })));
      const open = rounds.find((r) => r.status === "open");
      box.append(h("div", { class: "panel" }, h("div", { class: "bar" }, h("h2", { class: "grow" }, "Physical verification rounds"),
        can("assets", "edit") ? h("button", { class: "btn", onclick: async () => { const nmv = await ask("Start a verification round", "Start a new round? Any open round is closed.", { input: "Name, e.g. Annual count 2083" }); if (nmv === null) return; await run("life.round_save", { row: { name: nmv } }, "Round started"); load(); } }, "Start a round") : null),
      open ? h("p", {}, "Open round: ", h("b", {}, open.name), " — " + open.found + " of " + open.total + " seen. Scan the tags with a phone, or tick them here.") : h("p", { class: "muted" }, "No open round."),
      table([{ k: "name", label: "Round" }, { k: "date", label: "Started" }, { k: "status", label: "Status", fmt: "status" }, { label: "Seen", v: (r) => r.found + " / " + r.total }, { k: "missing_marked", label: "Marked missing", fmt: "num" }], rounds, { search: false, export: false, onRow: (r) => roundReport(r) })));
    };
    const roundReport = async (r) => {
      const d = await api("life.round_report", { id: r.id });
      modal(r.name + " — " + d.found + " found, " + d.discrepancies.length + " discrepancies", table([{ label: "Kind", v: (x) => x.kind === "eq" ? "Machine" : "Asset" }, { k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "state", label: "State" }, { k: "location", label: "Location seen" }, { k: "condition", label: "Condition" }, { k: "by", label: "By" },
        { label: "", v: (x) => r.status === "open" && x.state !== "found" && can("equipment", "view") ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("life.scan", { round_id: r.id, kind: x.kind, ref_id: x.id, location: x.extra, condition: "seen at desk" }, "Marked found"); } }, "Mark found") : "" }],
      d.rows, { name: "verification_" + r.id, rowClass: (x) => x.state === "found" ? "" : "flag" }), []);
    };
    await load();
    return box;
  }
  function printLabels(list, base) {
    const cells = list.map((t) => `<div class="lab">${qrSvg(base + "/#/verify?k=" + t.kind + "&c=" + encodeURIComponent(t.code), 120)}<div><b>${escHtml(t.code)}</b><br>${escHtml(t.name)}<br><small>${escHtml(S.L.settings.company_name || "")}</small></div></div>`).join("");
    const w = window.open("", "_blank");
    if (!w) return toast("Allow pop-ups to print labels.", "err");
    w.document.write(`<html><head><title>QR labels</title><style>body{font:12px Arial;margin:8mm}.lab{display:inline-flex;gap:8px;align-items:center;width:62mm;height:34mm;border:1px dashed #999;margin:2mm;padding:2mm;box-sizing:border-box;page-break-inside:avoid;vertical-align:top}svg{flex:none}</style></head><body>${cells}<script>setTimeout(()=>print(),300)<\/script></body></html>`);
    w.document.close();
  }
  PAGES["verify"] = async (root, params) => {
    const kind = params.k || "eq", code = params.c || "";
    let d;
    try { d = await run("life.lookup", { kind, code }); } catch (e) { root.append(pageHead("Not found"), h("p", {}, e.message)); return; }
    const r = d.record;
    const f = form([{ k: "location", label: "Where is it now?", default: r.location || "" }, { k: "condition", label: "Condition", type: "select", noBlank: true, options: [["good", "Good"], ["fair", "Fair, working"], ["poor", "Poor, needs repair"], ["not_working", "Not working"]] }, { k: "notes", label: "Notes", wide: true }]);
    root.append(h("div", { class: "sitemode" }, h("h1", {}, r.code), h("p", {}, r.name + (r.category ? " · " + r.category : "")),
      kv([["Status", r.status || "—"], ["Project", r.project_id ? nm.pcode(r.project_id) : "—"], ["Recorded location", r.location || "—"], [kind === "eq" ? "Operator" : "Custodian", r.operator || r.custodian || "—"],
        ["Verification round", d.round ? d.round.name : "none open"], ["Already seen", d.seen ? (d.seen.ts || "").slice(0, 16).replace("T", " ") + " by " + d.seen.by : "no"]]),
      d.round ? h("div", {}, f, h("div", { class: "bigbtns" },
        h("button", { class: "btn big primary", onclick: async () => { await run("life.scan", Object.assign(f.values(), { kind, ref_id: r.id, found: 1 }), "Recorded — found"); go(); } }, "Found here"),
        h("button", { class: "btn big warn", onclick: async () => { await run("life.scan", Object.assign(f.values(), { kind, ref_id: r.id, found: 0 }), "Recorded as not matching"); go(); } }, "Not as recorded"))) : h("p", { class: "muted" }, "Start a verification round to record counts."),
      kind === "eq" ? h("p", {}, h("a", { href: "#/eq/register?open=" + r.id }, "Open the machine record")) : null));
  };

  /* ── maturity check ── */
  async function maturityTab() {
    const box = h("div");
    let year = String(new Date().getFullYear());
    const load = async () => {
      const d = await api("life.maturity", { year });
      box.innerHTML = "";
      const ysel = h("input", { value: year, style: "max-width:100px", onchange: (e) => { year = e.target.value; load(); } });
      const inputs = {};
      box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Year"), ysel), h("div", { class: "grow" }), h("span", { class: "hint" }, d.note)));
      d.stages.forEach((s) => {
        box.append(h("div", { class: "panel" }, h("h2", {}, s.label + (s.mean ? " — " + s.mean + " / 4" : "")),
          ...s.items.map((it) => {
            const sel = h("select", { style: "max-width:220px" }, h("option", { value: "" }, "—"), d.scale.map(([v, l]) => h("option", { value: v, selected: Number(it.score) === v }, v + " " + l)));
            const note = h("input", { value: it.note || "", placeholder: "evidence / note" });
            inputs[it.key] = { sel, note };
            return h("div", { class: "bar" }, h("span", { class: "grow" }, it.question), sel, note);
          })));
      });
      if (d.history.length) {
        const years = [...new Set(d.history.map((x) => x.year))];
        box.append(h("div", { class: "panel" }, h("h2", {}, "Progress by year"), table([{ k: "stage", label: "Stage" }, ...years.map((y) => ({ label: y, v: (r) => { const x = d.history.find((z) => z.year === y && z.stage === r.stage); return x ? fmtN(x.m, 2) : "—"; } }))],
          [...new Set(d.history.map((x) => x.stage))].map((s) => ({ stage: s })), { search: false, export: false })));
      }
      if (can("assets", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        const scores = {}; Object.entries(inputs).forEach(([k, v]) => { if (v.sel.value) scores[k] = { score: v.sel.value, note: v.note.value }; });
        await run("life.maturity_save", { year, scores }, "Saved"); load();
      } }, "Save the self-assessment")));
    };
    await load();
    return box;
  }
  bcoTabbed("eq/register", "Equipment register", "Every machine, owned or hired, and its life cycle: business case, acquisition, replacement and disposal, physical verification.",
    { firstLabel: "Register", tabs: [["Business cases", casesTab], ["Acquisition files", acqMachineTab], ["Replacement & disposal", replacementTab], ["QR tags & verification", () => qrTab(null)], ["Maturity check", maturityTab], ["Outputs & attachments", toolsTab]] });
  bcoTabbed("as/register", "Asset register", "Assets with custody, location and depreciation; QR tags for the annual physical count.", { firstLabel: "Register", tabs: [["QR tags & verification", () => qrTab("as")]] });

  /* ── Monthly logsheets › inspections & violations ── */
  async function inspectTab() {
    const box = h("div");
    const load = async () => {
      const [d, v] = await Promise.all([api("life.inspections", {}), api("life.viol_list", {})]);
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Daily point inspection is ticked on the monthly logsheet (Checks). Any item marked “repair” raises a work order at once. Days a machine worked without a check are listed here."),
        table([{ k: "code", label: "Machine" }, { k: "operator", label: "Operator" }, { k: "days_worked", label: "Days worked", fmt: "num" }, { k: "days_checked", label: "Days checked", fmt: "num" }, { label: "Compliance", v: (r) => r.compliance_pct == null ? "—" : h("b", { class: r.compliance_pct < 90 ? "red" : "green" }, r.compliance_pct + "%") },
          { k: "flagged", label: "Items flagged", fmt: "num" }, { k: "work_orders", label: "Work orders raised", fmt: "num" }, { label: "Days missed (latest)", v: (r) => r.missed.join(", ") }], d.rows, { name: "point_inspection" }),
        h("div", { class: "bar", style: "margin-top:16px" }, h("h2", { class: "grow" }, "Operator violations and penalties"), can("equipment", "edit") ? h("button", { class: "btn", onclick: () => violEdit(null, load) }, "Record a violation") : null),
        h("div", { class: "cols" }, table([{ k: "date", label: "Date" }, { label: "Machine", v: (r) => nm.eq(r.equipment_id) }, { k: "operator", label: "Operator" }, { k: "violation", label: "Violation" }, { k: "penalty", label: "Penalty", fmt: "money" }, { k: "action", label: "Action" }], v.rows, { name: "violations", onRow: (r) => violEdit(r, load) }),
          table([{ k: "operator", label: "Operator" }, { k: "count", label: "Violations", fmt: "num" }, { k: "penalty", label: "Penalties", fmt: "money" }], v.by_operator, { search: false, export: false })));
    };
    await load();
    return box;
  }
  function violEdit(r, done) {
    const f = form([{ k: "date", label: "Date", type: "date", default: today() }, { k: "equipment_id", label: "Machine", type: "select", options: eqOpts }, { k: "operator", label: "Operator", req: true },
      { k: "violation", label: "Violation", type: "select", options: [["Overloading", "Overloading"], ["Overspeeding", "Overspeeding"], ["No daily check", "No daily check"], ["Unauthorised operator", "Unauthorised operator"], ["Idling engine", "Idling engine / fuel waste"], ["Safety rule broken", "Safety rule broken"], ["Misuse / damage", "Misuse / damage"], ["Other", "Other"]] },
      { k: "penalty", label: "Penalty (amount)", type: "number" }, { k: "action", label: "Action taken (warning, training…)" }, { k: "remarks", label: "Remarks", wide: true }], r || {});
    modal(r ? "Violation" : "Record a violation", f, [can("equipment", "edit") ? { label: "Save", cls: "primary", act: async () => { await run("life.viol_save", { row: Object.assign(f.values(), { id: r && r.id }) }, "Saved"); done(); } } : null,
      r && can("equipment", "approve") ? { label: "Delete", cls: "warn", act: async () => { await run("life.viol_delete", { id: r.id }, "Deleted"); done(); } } : null], { narrow: true });
  }
  bcoTabbed("eq/books", "Monthly logsheets", "One sheet per machine per month, as on paper: hours, fuel, daily checks, service and signatures.", { firstLabel: "Logsheets", tabs: [["Inspections & violations", inspectTab], ["Split by output", splitTab]] });

  /* ── Work orders › breakdown analysis ── */
  async function breakdownTab() {
    await opts();
    const box = h("div");
    const load = async () => {
      const d = await api("life.reliability", {});
      box.innerHTML = "";
      const lab = Object.fromEntries(d.failure_codes);
      box.append(h("p", { class: "hint" }, "MTBF = operating hours ÷ breakdowns; MTTR = repair hours ÷ breakdowns; availability = MTBF ÷ (MTBF + MTTR). Downtime cost = idle crew and idle linked machines, plus liquidated damages when the machine was on a critical activity. Last 12 months."),
        h("div", { class: "cols" }, h("div", { class: "panel" }, h("h2", {}, "Failure codes (Pareto)"), d.codes.length ? bars(d.codes.map((x) => x.label.slice(0, 12)), [{ name: "Breakdowns", values: d.codes.map((x) => x.n) }]) : h("p", { class: "muted" }, "No completed breakdowns."),
          table([{ k: "label", label: "Code" }, { k: "n", label: "Breakdowns", fmt: "num" }, { k: "h", label: "Downtime h", fmt: "num" }, { k: "cost", label: "Downtime cost", fmt: "money" }, { label: "Cumulative", v: (x) => x.cum_pct + "%" }], d.codes, { search: false, export: false })),
        h("div", { class: "panel" }, h("h2", {}, "By ABC class"), table([{ k: "key", label: "Class" }, { k: "machines", label: "Machines", fmt: "num" }, { k: "failures", label: "Breakdowns", fmt: "num" }, { k: "mtbf", label: "MTBF h", fmt: "num" }, { k: "mttr", label: "MTTR h", fmt: "num" }, { label: "Availability", v: (x) => x.availability == null ? "—" : x.availability + "%" }, { k: "downtime_cost", label: "Downtime cost", fmt: "money" }], d.by_class, { search: false, export: false }),
          h("h2", {}, "By type"), table([{ k: "key", label: "Type" }, { k: "failures", label: "Breakdowns", fmt: "num" }, { k: "mtbf", label: "MTBF h", fmt: "num" }, { k: "mttr", label: "MTTR h", fmt: "num" }, { label: "Availability", v: (x) => x.availability == null ? "—" : x.availability + "%" }], d.by_category, { search: false, export: false }))),
        h("h2", { class: "sec" }, "By machine"),
        table([{ k: "code", label: "Machine" }, { k: "class", label: "Class" }, { k: "hours", label: "Hours", fmt: "num" }, { k: "failures", label: "Breakdowns", fmt: "num" }, { k: "mtbf", label: "MTBF h", fmt: "num" }, { k: "mttr", label: "MTTR h", fmt: "num" }, { label: "Availability", v: (x) => x.availability == null ? "—" : x.availability + "%" }, { k: "downtime_cost", label: "Downtime cost", fmt: "money" }, { k: "uncoded", label: "Not coded", fmt: "num" }], d.rows, { name: "reliability" }),
        h("h2", { class: "sec" }, "Breakdowns to code"),
        table([{ k: "no", label: "WO" }, { label: "Machine", v: (w) => w.eq_code + " " + w.eq_name }, { k: "description", label: "What failed" }, { k: "status", label: "Status", fmt: "status" }, { k: "downtime_hours", label: "Downtime h", fmt: "num" }],
          d.uncoded, { search: false, empty: "Every breakdown has a failure code.", onRow: can("equipment", "edit") ? (w) => codeWo(w, d.failure_codes, load) : null }));
    };
    await load();
    return box;
  }
  function codeWo(w, codes, done) {
    const f = form([{ k: "failure_code", label: "Failure code", type: "select", noBlank: true, options: codes }, { k: "cause_detail", label: "Cause in detail", wide: true },
      { k: "idle_crew", label: "Workers standing idle", type: "number" }, { k: "crew_rate_hour", label: "Their rate per hour (blank = average trade rate)", type: "number" },
      { k: "idle_linked_cost_hour", label: "Idle linked machines, cost per hour", type: "number" }, { k: "activity_id", label: "Activity it was working on (blank = last logsheet)", type: "select", options: () => actOpts() }], w);
    modal("Code breakdown " + w.no, f, [{ label: "Save", cls: "primary", act: async () => { const r = await run("life.wo_code", Object.assign(f.values(), { id: w.id })); toast("Downtime cost " + fmtMoney(r.downtime_cost) + (r.ld ? " incl. LD " + fmtMoney(r.ld) : ""), "ok"); done(); } }], { narrow: true });
  }
  bcoTabbed("eq/wo", "Work orders", "Breakdowns, services and inspections with downtime, spares and cost.", { firstLabel: "Work orders", tabs: [["Breakdown analysis", breakdownTab]] });

  /* ── Maintenance › class rules, spares, safety checks, spare forecast ── */
  async function classTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("life.class_status", {});
      box.innerHTML = "";
      const R = d.rules;
      const rf = h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Class", "Operator certificate", "Named person responsible", "Full records", "Spare reserve %", "Safety check every (days)"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ["A", "B", "C"].map((k) => h("tr", {}, h("td", {}, h("b", {}, k)), ["operator_cert", "responsible", "full_records"].map((f) => h("td", {}, h("input", { type: "checkbox", style: "width:auto", "data-k": k, "data-f": f, checked: !!R[k][f] }))),
          ["spare_reserve_pct", "safety_cycle_days"].map((f) => h("td", {}, h("input", { type: "number", "data-k": k, "data-f": f, value: R[k][f], style: "max-width:90px" }))))))));
      box.append(h("div", { class: "panel" }, h("h2", {}, "Class rules (Wang, Table 3 — extends the 1.7 ABC classes)"), rf,
        can("equipment", "approve") ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
          const rules = { A: {}, B: {}, C: {} };
          rf.querySelectorAll("input").forEach((i) => { rules[i.dataset.k][i.dataset.f] = i.type === "checkbox" ? (i.checked ? 1 : 0) : i.value; });
          await run("life.rules_save", { rules }, "Rules saved"); load();
        } }, "Save rules"), h("button", { class: "btn primary", onclick: async () => { const r = await run("life.spares_apply", {}); toast(r.updated + " spares now hold the reserve as their minimum level", "ok"); } }, "Set spare minimum levels from the rules")) : null),
      table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "class", label: "Class" }, { k: "operator", label: "Operator" }, { k: "operator_cert_no", label: "Certificate" }, { k: "responsible_person", label: "Responsible" }, { k: "last_safety", label: "Last safety check" }, { k: "safety_due", label: "Next due" }, { k: "spares", label: "Spares linked", fmt: "num" },
        { label: "Not complying", v: (r) => r.issues.length ? h("b", { class: "red" }, r.issues.join("; ")) : h("span", { class: "green" }, "OK") }], d.rows, { name: "class_rules", rowClass: (r) => r.issues.length ? "flag" : "", onRow: (r) => machineRules(r, load) }));
    };
    await load();
    return box;
  }
  async function machineRules(r, done) {
    const sp = await api("life.spares", { equipment_id: r.id });
    const f = form([{ k: "operator_cert_no", label: "Operator certificate no." }, { k: "operator_cert_expiry", label: "Certificate valid to", type: "date" }, { k: "responsible_person", label: "Named person responsible" }], r);
    const sf = form([{ k: "material_id", label: "Spare (store material)", type: "select", options: opt.materials }, { k: "qty", label: "Quantity per machine", type: "number", default: 1 }]);
    const safety = form([{ k: "date", label: "Safety check date", type: "date", default: today() }, { k: "result", label: "Result", type: "select", noBlank: true, options: [["pass", "Pass"], ["fail", "Fail (raises a work order)"]] }, { k: "checked_by", label: "Checked by" }, { k: "notes", label: "Notes", wide: true }]);
    const edit = can("equipment", "edit");
    modal(r.code + " " + r.name + " — class " + r.class, h("div", {}, f, edit ? h("button", { class: "btn small", onclick: async () => { await run("life.eq_save", { row: Object.assign(f.values(), { id: r.id }) }, "Saved"); } }, "Save") : null,
      h("h3", {}, "Spares kept for this machine"), table([{ k: "code", label: "Code" }, { k: "name", label: "Spare" }, { k: "qty", label: "Qty", fmt: "qty" }, { label: "", v: (s) => edit ? h("button", { class: "btn small warn", onclick: async () => { await run("life.spare_delete", { id: s.id }); done(); } }, "Remove") : "" }], sp, { search: false, export: false, empty: "None linked." }),
      edit ? h("div", {}, sf, h("button", { class: "btn small", onclick: async () => { await run("life.spare_save", { row: Object.assign(sf.values(), { equipment_id: r.id }) }, "Linked"); done(); } }, "Link spare")) : null,
      h("h3", {}, "Record a safety check"), safety, edit ? h("button", { class: "btn small", onclick: async () => { await run("life.safety_save", { row: Object.assign(safety.values(), { equipment_id: r.id }) }, "Recorded"); done(); } }, "Save safety check") : null), []);
  }
  async function spareFcTab() {
    const d = await api("life.spare_forecast", {});
    return h("div", {}, h("p", { class: "hint" }, "Spares issued to machines and work orders over the last " + d.months.length + " months. " + d.note),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Spare" }, { k: "unit", label: "Unit" }, ...d.months.map((m, i) => ({ label: m.slice(2), fmt: "qty", v: (r) => r.history[i] || "" })),
        { k: "forecast_smoothing", label: "Next month (smoothing)", fmt: "qty" }, { k: "forecast_ma3", label: "3-month average", fmt: "qty" }, { k: "suggested_min", label: "Suggested minimum", fmt: "qty" }, { k: "current_min", label: "Minimum now", fmt: "qty" }, { k: "stock", label: "Stock", fmt: "qty" }],
      d.rows, { name: "spare_forecast", empty: "No spares issued to machines yet.", rowClass: (r) => r.stock < r.suggested_min ? "flag" : "" }));
  }
  bcoTabbed("eq/maint", "Maintenance", "Service plans by hours, kilometres or days, with the class rules, spares and safety checks.", { firstLabel: "Service plans", tabs: [["Class rules, spares & safety", classTab], ["Spare-parts forecast", spareFcTab]] });


  /* ── 2.6: logsheets only from the DPR ── */
  let LOGMODE = null;
  const logMode = async (force) => { if (force || !LOGMODE) { try { LOGMODE = await api("life.log_mode", {}); } catch (e) { LOGMODE = { dpr_only: true }; } } return LOGMODE; };
  window.bcoLogMode = logMode;
  const modeSwitch = (after) => S.user && S.user.role === "admin" ? h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:6px;margin-top:8px" },
    h("input", { type: "checkbox", style: "width:auto", checked: LOGMODE && LOGMODE.dpr_only, onchange: async (e) => { await run("life.log_mode", { set: e.target.checked ? 1 : 0 }, e.target.checked ? "Logsheets now come only from DPRs" : "Hand entry of logsheets is allowed"); await logMode(true); if (after) after(); } }),
    h("span", {}, "Logsheets only from DPR (administrator setting)")) : "";
  /* ── Day-by-day log › telematics import ── */
  async function telematicsTab() {
    if ((await logMode()).dpr_only) return h("div", { class: "panel" }, h("b", {}, "Switched off: "), "logsheets come only from the approved DPR, so machine data is not imported here.", modeSwitch(() => go()));
    const ta = h("textarea", { style: "min-height:180px;font-family:monospace", placeholder: "code,date,hours,fuel,lat,lon,location\nEX-01,2026-09-26,7.5,62,27.35,87.67,Inlet portal" });
    const mode = h("select", {}, h("option", { value: "hours" }, "Third column = engine hours worked that day"), h("option", { value: "meter" }, "Third column = hour meter at the end of the day"));
    const out = h("div");
    return h("div", {}, h("p", { class: "hint" }, "Export the day summary from the machine maker's telematics portal (engine hours, fuel, GPS) as CSV and paste it here. BuildCore makes draft day logs (approve them as usual) and moves each machine's location."),
      h("label", { class: "f" }, h("span", {}, "Hours column"), mode), ta,
      can("equipment", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        const r = await run("life.telematics", { text: ta.value, hours_mode: mode.value });
        out.innerHTML = "";
        out.append(h("p", {}, r.created + " day logs created."), r.skipped.length ? h("ul", {}, r.skipped.map((x) => h("li", {}, x))) : "");
      } }, "Import")) : null, out);
  }
  bcoTabbed("eq/logs", "Day-by-day log", "One line per machine per day and shift.", { firstLabel: "Day logs", tabs: [["Telematics import", telematicsTab]] });

  /* ── Fixed assets › Equipment costing › decision tools ── */
  async function decisionTab() {
    const O = await opts();
    const tv = form([{ k: "op", label: "Find", type: "select", noBlank: true, options: [["P2F", "F given P (future value)"], ["F2P", "P given F (present value)"], ["P2A", "A given P (instalment / capital recovery)"], ["A2P", "P given A"], ["A2F", "F given A"], ["F2A", "A given F (sinking fund)"], ["rate", "Interest rate given P, F, n"], ["real", "Real rate given inflation"]] },
      { k: "i", label: "Interest % per period", type: "number", default: O.marr }, { k: "n", label: "Periods", type: "number", default: 5 }, { k: "p", label: "P (present)", type: "number" }, { k: "f", label: "F (future)", type: "number" }, { k: "a", label: "A (per period)", type: "number" }, { k: "inflation", label: "Inflation %", type: "number" }]);
    const tvOut = h("div", { class: "panel" });
    const tvCalc = async () => { const r = await api("life.tvm", tv.values()); tvOut.innerHTML = ""; tvOut.append(kv([["Answer", h("b", {}, r.answer == null ? "—" : fmtN(r.answer, 2))], ...Object.entries(r.factors).map(([k, v]) => ["(" + k + ")", v == null ? "—" : v])])); };
    tv.addEventListener("change", tvCalc); tvCalc();
    const marr = h("input", { type: "number", value: O.marr, style: "max-width:100px" });
    const alts = lineEditor([{ k: "name", label: "Alternative", w: 180 }, { k: "flows", label: "Cash flows year 0, 1, 2 … (money out negative), comma separated", w: 520 }],
      [{ name: "Overhaul the old machine", flows: "-2000000, 700000, 700000, 700000, 500000" }, { name: "Buy new", flows: "-9000000, 2500000, 2500000, 2500000, 2500000, 3000000" }], {});
    const dOut = h("div");
    const decideRun = async () => {
      const r = await run("life.decide", { marr: marr.value, alternatives: alts.lines().map((x) => ({ name: x.name, flows: String(x.flows || "").split(/[,;\s]+/).filter(Boolean).map(Number) })) });
      dOut.innerHTML = "";
      dOut.append(table([{ k: "name", label: "Alternative" }, { k: "npv", label: "NPV", fmt: "money" }, { k: "fw", label: "Future worth", fmt: "money" }, { k: "ae", label: "Annual equivalent", fmt: "money" }, { label: "Rate of return", v: (x) => x.irr == null ? "—" : x.irr + "%" }, { k: "capital_recovery", label: "Capital recovery / yr", fmt: "money" }, { k: "payback", label: "Payback (yrs)", fmt: "num" }, { k: "discounted_payback", label: "Discounted payback", fmt: "num" }, { label: "Project balance", v: (x) => x.project_balance.map((v) => fmtN(v / 1e6, 2)).join(" → ") + " M" }], r.alternatives, { search: false, export: false }),
        r.incremental.length ? table([{ label: "Step", v: (x) => x.from + " → " + x.to }, { k: "npv", label: "Incremental NPV", fmt: "money" }, { label: "Incremental ROR", v: (x) => x.irr == null ? "—" : x.irr + "%" }, { k: "choose", label: "Choose" }], r.incremental, { search: false, export: false }) : null,
        h("p", {}, "Best on NPV at " + r.marr + "% MARR: ", h("b", {}, r.best || "—"), ". ", h("span", { class: "hint" }, r.note)));
    };
    const bh = form([{ k: "hours_year", label: "Hours a year", type: "number", default: 1500 }, { k: "years", label: "Years", type: "number", default: 5 }, { k: "price", label: "Buy: price", type: "number" }, { k: "salvage", label: "Buy: salvage", type: "number" }, { k: "fixed", label: "Buy: fixed cost a year", type: "number" }, { k: "op", label: "Running cost / hour (buy or lease)", type: "number" },
      { k: "hire", label: "Hire rate / hour", type: "number" }, { k: "lpay", label: "Lease payment / month", type: "number" }, { k: "lterm", label: "Lease term (months)", type: "number" }]);
    const bhOut = h("div");
    const bhRun = async () => {
      const v = bh.values();
      const r = await run("life.bhl", { hours_year: v.hours_year, years: v.years, marr: Number(marr.value) / 100, buy: { price: v.price, salvage: v.salvage, fixed_year: v.fixed, operating_hour: v.op }, hire: { rate_hour: v.hire }, lease: { payment_month: v.lpay, term_months: v.lterm, operating_hour: v.op } });
      bhOut.innerHTML = "";
      bhOut.append(table([{ k: "option", label: "Option" }, { k: "annual_cost", label: "Annual equivalent cost", fmt: "money" }, { k: "cost_per_hour", label: "Per hour", fmt: "money" }, { k: "npv", label: "NPV", fmt: "money" }], r.options, { search: false, export: false }));
    };
    return h("div", {}, h("h2", { class: "sec" }, "Compare alternatives (NPV, FW, AE, ROR, incremental ROR, capital recovery, payback, project balance)"),
      h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "MARR % (cost of capital + risk)"), marr)), alts, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: decideRun }, "Compare")), dOut,
      h("div", { class: "cols" }, h("div", { class: "panel" }, h("h2", {}, "Buy vs hire vs lease"), bh, h("button", { class: "btn", onclick: bhRun }, "Work it out"), bhOut),
        h("div", { class: "panel" }, h("h2", {}, "Time-value calculator"), tv, tvOut)));
  }
  bcoTabbed("fa/costing", "Equipment costing", "Equipment ledger, owning and operating rates, charges to projects and the year-end true-up.", { firstLabel: "Costing", tabs: [["Decision tools", decisionTab]] });
  /* ── attachments: one machine, several tools and outputs (bucket / breaker) ── */
  async function toolsTab() {
    const box = h("div");
    const f = form([{ k: "from", label: "Output from", type: "date" }, { k: "to", label: "To", type: "date" }], { from: new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10), to: today() });
    const out = h("div");
    const load = async () => {
      const [t, o] = await Promise.all([api("tool.list", {}), api("tool.output", f.values())]);
      box.innerHTML = "";
      const kinds = t.kinds;
      box.append(h("div", { class: "bar" }, h("p", { class: "hint grow" }, "Excavators and backhoes start with a bucket and a hydraulic rock breaker. Give an attachment its own rate if it costs more (breaker wear, extra fuel); blank = the machine's rate. The norm output per hour is used to judge productivity."),
        can("equipment", "edit") ? h("button", { class: "btn primary", onclick: () => edit(null, kinds) }, "Add attachment") : ""),
      table([{ k: "eq_code", label: "Machine" }, { k: "eq_name", label: "Name" }, { k: "name", label: "Attachment" }, { label: "Default", v: (r) => r.is_default ? "Yes" : "" },
        { label: "Own rate / h", v: (r) => r.rate_hr ? fmtMoney(r.rate_hr) : h("span", { class: "muted" }, "machine rate") }, { k: "hire_rate_hr", label: "Hire rate / h", fmt: "money" },
        { k: "norm_output_hr", label: "Norm output / h", fmt: "num" }, { k: "output_unit", label: "Unit" }, { k: "fuel_hr", label: "Fuel l/h", fmt: "num" }], t.rows,
      { name: "attachments", onRow: can("equipment", "edit") ? (r) => edit(r, kinds) : null, empty: "No attachments yet." }),
      h("h2", { class: "sec" }, "Output by machine and attachment"), f, out);
      out.append(hint(o.note),
        table([{ k: "code", label: "Machine" }, { k: "tool", label: "Attachment" }, { k: "days", label: "Days", fmt: "num" }, { k: "hours", label: "Hours", fmt: "num" }, { k: "output", label: "Output", fmt: "num" }, { k: "unit", label: "Unit" },
          { k: "output_per_hr", label: "Output / h", fmt: "num" }, { k: "norm_output_hr", label: "Norm / h", fmt: "num" }, { label: "% of norm", v: (r) => r.vs_norm_pct == null ? "" : h("b", { class: r.vs_norm_pct < 85 ? "red" : "green" }, r.vs_norm_pct + "%") },
          { k: "cost_per_hr", label: "Cost / h", fmt: "money" }, { k: "cost_per_unit", label: "Cost / unit", fmt: "money" }], o.rows, { name: "attachment_output", empty: "Record attachment hours and output on the DPR or in Monthly logsheets › Split by attachment." }));
    };
    const hint = (t) => h("p", { class: "hint" }, t);
    const edit = (r, kinds) => {
      const fm = form([{ k: "equipment_id", label: "Machine", type: "select", req: true, options: eqOpts }, { k: "kind", label: "Type", type: "select", noBlank: true, options: kinds.map((k) => [k[0], k[1]]) },
        { k: "name", label: "Name", req: true }, { k: "output_unit", label: "Output unit (m3, m, trip…)" }, { k: "rate_hr", label: "Own rate per hour (blank = machine rate)", type: "number" },
        { k: "hire_rate_hr", label: "Hire rate per hour (rented machine)", type: "number" }, { k: "norm_output_hr", label: "Norm output per hour", type: "number" }, { k: "fuel_hr", label: "Fuel litres per hour", type: "number" },
        { k: "is_default", label: "Default attachment", type: "check" }, { k: "remarks", label: "Remarks", wide: true }], r || { kind: "breaker", name: "Hydraulic rock breaker", output_unit: "m3" });
      fm.addEventListener("change", (e) => { if (e.target.name === "kind") { const k = kinds.find((x) => x[0] === e.target.value); const n = fm.querySelector("[name=name]"), u = fm.querySelector("[name=output_unit]"); if (k && n && !r) { n.value = k[1]; u.value = k[2]; } } });
      const b = [{ label: "Save", cls: "primary", act: async () => { await run("tool.save", { row: Object.assign(fm.values(), { id: r && r.id }) }, "Saved"); load(); } }];
      if (r) b.push({ label: "Remove", cls: "warn", act: async () => { await run("tool.delete", { id: r.id }, "Removed"); load(); } });
      modal(r ? r.eq_code + " · " + r.name : "New attachment", fm, b, { narrow: true });
    };
    f.addEventListener("change", load);
    await load();
    return box;
  }
  async function splitTab() {
    const box = h("div");
    const lm = await logMode();
    const t = await api("tool.list", {});
    const machines = [...new Map(t.rows.map((x) => [x.equipment_id, x.eq_code + " " + x.eq_name])).entries()];
    if (!machines.length) return h("div", { class: "panel" }, "No machine has attachments yet (Equipment register › Attachments & output).");
    const sel = h("select", {}, machines.map(([v, l]) => h("option", { value: v }, l)));
    /* 2.30: the month follows the date switch (a Nepali month with Nepali dates) */
    const nepali = typeof window.bcoNepaliMonths === "function" && window.bcoNepaliMonths();
    if (nepali && window.bcoLoadBS) await window.bcoLoadBS();
    let range = nepali && window.bcoBsRange ? window.bcoBsRange(today()) : null;
    if (!range) range = { from: today().slice(0, 7) + "-01", to: "", key: today().slice(0, 7) };
    const mon = window.bcoMonthBox ? window.bcoMonthBox({ value: today().slice(0, 7), from: range.from, fireOnLoad: false, onChange: (x) => { range = x; load(); } })
      : h("input", { type: "month", value: today().slice(0, 7), onchange: (e) => { range = { key: e.target.value }; load(); } });
    const out = h("div");
    const blank = (v) => (v == null || v === "" || Number(v) === 0) ? "" : fmtN(v);
    const load = async () => {
      const d = await api("tool.log_get", { equipment_id: sel.value, month: (range.key || "").length === 7 && !range.bs ? range.key : (range.from || today()).slice(0, 7), from: range.from || null, to: range.to || null });
      out.innerHTML = "";
      if (!d.logs.length) { out.append(h("p", { class: "muted" }, "No logsheet days for this machine " + (range.label ? "in " + range.label : "from " + d.from + " to " + d.to) + ".")); return; }
      const state = d.logs.map((l) => ({ l, v: Object.fromEntries(d.tools.map((x) => [x.id, Object.assign({ hours: "", output_qty: "" }, l.tools[x.id] || {})])), dirty: false }));
      const tb = h("tbody");
      const tot = { hours: 0, t: {} };
      state.forEach((s) => {
        const locked = lm.dpr_only || s.l.from_dpr && Object.keys(s.l.tools).length > 0 || !can("equipment", "edit");
        const rest = h("td", { class: "num" });
        const upd = () => { const used = d.tools.reduce((a, x) => a + (Number(s.v[x.id].hours) || 0), 0); const r = (s.l.hours || 0) - used; rest.textContent = Math.abs(r) < 0.005 ? "" : fmtN(r); rest.className = "num" + (r < -0.01 ? " red" : ""); };
        tot.hours += Number(s.l.hours) || 0;
        d.tools.forEach((x) => { const o = tot.t[x.id] || (tot.t[x.id] = { hours: 0, output_qty: 0 }); o.hours += Number(s.v[x.id].hours) || 0; o.output_qty += Number(s.v[x.id].output_qty) || 0; });
        const work = (s.l.dpr_work || []).map((w) => fmtN(w.qty) + " " + (w.unit || "") + " " + w.activity + (w.machines > 1 ? " (" + w.machines + " machines)" : "")).join("; ");
        const src = s.l.from_dpr ? (s.l.dpr_no || "from DPR") + (s.l.output_missing ? " · no output on the DPR" : "") : "";
        tb.append(h("tr", {}, h("td", { style: "white-space:nowrap" }, cellValue({ k: "date" }, s.l)), h("td", {}, s.l.shift), h("td", { class: "num" }, fmtN(s.l.hours)),
          ...d.tools.flatMap((x) => ["hours", "output_qty"].map((k) => h("td", { class: "num" }, locked ? blank(s.v[x.id][k]) : h("input", { type: "number", value: s.v[x.id][k] ?? "", style: "width:70px", oninput: (e) => { s.v[x.id][k] = e.target.value; s.dirty = true; upd(); } })))),
          rest, h("td", { class: "muted", style: "max-width:260px" }, work), h("td", { class: "muted" }, src)));
        upd();
      });
      const head = h("tr", {}, h("th", {}, "Date"), h("th", {}, "Shift"), h("th", { class: "num" }, "Hours"), ...d.tools.flatMap((x) => [h("th", { class: "num" }, x.name + " h"), h("th", { class: "num" }, x.name + " output" + (x.output_unit ? " (" + x.output_unit + ")" : ""))]),
        h("th", { class: "num", title: "Hours of the day not given to any attachment; they count as the default attachment" }, "Not split (default)"), h("th", {}, "Work on the DPR (same activity)"), h("th", {}, "Source"));
      const foot = h("tfoot", {}, h("tr", {}, h("td", {}, "Total"), h("td"), h("td", { class: "num" }, fmtN(tot.hours)), ...d.tools.flatMap((x) => [h("td", { class: "num" }, blank(tot.t[x.id].hours)), h("td", { class: "num" }, blank(tot.t[x.id].output_qty))]), h("td"), h("td"), h("td")));
      const missing = state.filter((s) => s.l.output_missing).length;
      out.append(missing ? h("p", { class: "hint" }, missing + " DPR day(s) carry no output for this machine: write the output on the machine line of the DPR (Output box). The work reported on the same activity is shown beside it for reference.") : "",
        h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, head), tb, foot)),
        can("equipment", "edit") && !lm.dpr_only ? h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => {
          let n = 0;
          for (const s of state.filter((x) => x.dirty)) {
            await run("tool.log_save", { log_id: s.l.id, items: d.tools.map((x) => ({ tool_id: x.id, hours: s.v[x.id].hours, output_qty: s.v[x.id].output_qty })) });
            n++;
          }
          toast(n + " day(s) saved", "ok"); load();
        } }, "Save")) : "");
    };
    sel.onchange = load;
    box.append(h("p", { class: "hint" }, lm.dpr_only ? "Hours and output by attachment, as reported on the approved DPRs (choose the output on each machine line of the DPR). A DPR line without an attachment counts as the machine's default attachment." : "Split each day's hours between the attachments and write the output (m3 dug, m3 of rock broken…). Hours not split count as the default attachment. Days approved on a DPR with attachments are split there."),
      h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Machine"), sel), h("label", { class: "f" }, h("span", {}, nepali ? "Month (Nepali)" : "Month"), mon)), out);
    await load();
    return box;
  }
  /* ── 2.4.1: outputs / attachments on the machine itself (any machine, two or more outputs) ── */
  let TPL = null;
  const templates = async () => { if (!TPL) TPL = await api("tool.templates", {}); return TPL; };
  function outputsPanel(row) {
    const box = h("div", { class: "panel", style: "margin-top:14px" });
    box.append(h("h3", {}, "Outputs / attachments"));
    if (!row) {
      box.append(h("p", { class: "hint" }, "Save the machine first, then open it again to set its outputs. Excavators and backhoe loaders get Bucket + Hydraulic breaker automatically."));
      return box;
    }
    const editable = can("equipment", "edit");
    const holder = h("div");
    let ed = null, dirty = false;
    const save = async (quiet) => {
      if (!ed) return;
      const rows = ed.lines().map((r) => Object.assign({}, r, { is_default: r.is_default === "1" ? 1 : 0 }));
      const d = await run("tool.save_all", { equipment_id: row.id, rows }, quiet ? null : "Outputs saved");
      dirty = false; render(d);
    };
    const render = async (d) => {
      const t = await templates();
      holder.innerHTML = "";
      ed = lineEditor([{ k: "name", label: "Output / attachment", w: 190 }, { k: "kind", label: "Type", type: "select", noBlank: true, options: t.kinds.map((k) => [k[0], k[1]]), w: 150 },
        { k: "output_unit", label: "Unit", w: 60 }, { k: "rate_hr", label: "Own rate / h (blank = machine)", type: "number", w: 110 }, { k: "hire_rate_hr", label: "Hire rate / h", type: "number", w: 90 },
        { k: "norm_output_hr", label: "Norm output / h", type: "number", w: 90 }, { k: "fuel_hr", label: "Fuel l/h", type: "number", w: 70 },
        { k: "is_default", label: "Default", type: "select", noBlank: true, options: [["0", "No"], ["1", "Yes"]], w: 70 }],
      d.rows.map((x) => Object.assign({}, x, { is_default: x.is_default ? "1" : "0" })), { readonly: !editable, blank: { kind: "other", is_default: "0" } });
      ed.addEventListener("input", () => { dirty = true; }); ed.addEventListener("change", () => { dirty = true; });
      const tsel = h("select", { style: "width:auto" }, h("option", { value: "" }, "Add a ready set…"), t.templates.map((x) => h("option", { value: x.key }, x.label + ": " + x.outputs.join(" + "))));
      tsel.onchange = async () => { if (!tsel.value) return; if (dirty) await save(true); render(await run("tool.apply_template", { equipment_id: row.id, key: tsel.value }, "Outputs added")); };
      holder.append(h("p", { class: "hint" }, "A machine with two or more outputs, e.g. an excavator digging with the bucket (m3) and breaking rock with the breaker (m3 of rock). On the DPR and the logsheet each day's hours are split between them, each with its own output, rate and norm."),
        ed, editable ? h("div", { class: "bar" }, tsel, h("div", { class: "grow" }), h("button", { class: "btn primary", onclick: () => save(false) }, "Save outputs")) : "");
    };
    api("tool.list", { equipment_id: row.id }).then(render);
    box.append(holder);
    if (typeof window.outputSheets === "function") {
      const mon = window.bcoMonthBox ? window.bcoMonthBox({ value: today().slice(0, 7), fireOnLoad: false }) : h("input", { type: "month", value: today().slice(0, 7), style: "width:auto" });
      box.append(h("div", { class: "bar", style: "margin-top:8px" }, h("span", { class: "hint" }, "Logsheet for each output:"), mon,
        h("button", { class: "btn", onclick: async () => {
          const r = mon._sel || { key: mon.value || today().slice(0, 7) };
          const m = (r.key && r.key.length === 7 && !r.bs) ? r.key : (r.from || today()).slice(0, 7);
          const body = await window.outputSheets(r.bs ? { equipment_id: row.id, month: m, from: r.from, to: r.to } : { equipment_id: row.id, month: m });
          modal("Logsheet by output — " + row.code + " " + (row.name || "") + " · " + (r.label || m), body, [], { wide: true });
        } }, "Open logsheets by output")));
    }
    /* the machine's own Save button also saves changed outputs */
    setTimeout(() => {
      const btn = box.closest(".modal") && box.closest(".modal").querySelector("footer .btn.primary");
      if (btn) btn.addEventListener("click", () => { if (dirty) save(true).catch(() => {}); }, true);
    }, 0);
    return box;
  }
  if (typeof MASTERS_UI !== "undefined" && MASTERS_UI.equipment) {
    const prevExtra = MASTERS_UI.equipment.extra;
    MASTERS_UI.equipment.extra = (row) => h("div", {}, prevExtra ? prevExtra(row) : "", outputsPanel(row));
  }

  /* day logsheet: hours and quantity per output */
  if (typeof window.logDialog === "function") {
    const _logDialog = window.logDialog;
    window.logDialog = async function (row, done) {
      const lm = await logMode();
      if (lm.dpr_only && !row) {
        modal("Logsheets come from the DPR", h("div", {}, h("p", {}, "A machine's day is recorded on the Daily progress report (DPR › Equipment): hours, meters, idle and breakdown time, operator and output. When the DPR is approved, BuildCore writes the logsheet here by itself."),
          h("p", {}, "Fuel, oil and grease are issued from the store to the machine (Inventory › Issues › issue to the machine) and appear on the logsheet automatically."),
          h("p", { class: "hint" }, "In Equipment you only keep the list of machines and deploy them to projects."), modeSwitch()),
          [{ label: "Open Daily progress", cls: "primary", act: () => { location.hash = "#/p/dpr"; } }], { narrow: true });
        return;
      }
      if (lm.dpr_only && row && row.status === "draft") row = Object.assign({}, row, { status: "locked" });
      _logDialog(row, done);
      const modals = document.querySelectorAll(".overlay .modal");
      const m = modals[modals.length - 1];
      if (!m) return;
      const body = m.querySelector(".body");
      const eqSel = m.querySelector("[name=equipment_id]");
      const hoursIn = m.querySelector("[name=hours]");
      const sec = h("div", { class: "panel", style: "margin-top:10px" });
      body.append(sec);
      let tools = [], inputs = {};
      const editable = !row || (row.status === "draft" && can("equipment", "edit"));
      const draw = async () => {
        const eid = eqSel ? eqSel.value : row && row.equipment_id;
        sec.innerHTML = "";
        inputs = {};
        if (!eid) return;
        tools = (await api("tool.list", { equipment_id: eid })).rows;
        if (!tools.length) { sec.append(h("p", { class: "hint" }, "This machine has one output. To record two or more (bucket and breaker…), add them in Equipment register › open the machine › Outputs / attachments.")); return; }
        let have = {};
        if (row && row.id) {
          const d = await api("tool.log_get", { equipment_id: eid, month: row.date.slice(0, 7) });
          const l = d.logs.find((x) => x.id === row.id);
          have = (l && l.tools) || {};
        }
        const rest = h("b");
        const upd = () => { const used = tools.reduce((a, t) => a + (Number(inputs[t.id].hours.value) || 0), 0); const tot = Number(hoursIn && hoursIn.value) || (row && row.hours) || 0; rest.textContent = tot ? fmtN(tot - used) + " h left → " + ((tools.find((t) => t.is_default) || tools[0]).name) : ""; };
        sec.append(h("h4", {}, "Hours and quantity by output"),
          h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Output / attachment"), h("th", {}, "Hours"), h("th", {}, "Quantity done"), h("th", {}, "Unit"))),
            h("tbody", {}, tools.map((t) => {
              const v = have[t.id] || {};
              inputs[t.id] = { hours: h("input", { type: "number", value: v.hours ?? "", disabled: !editable, style: "width:90px", oninput: upd }), qty: h("input", { type: "number", value: v.output_qty ?? "", disabled: !editable, style: "width:110px" }) };
              return h("tr", {}, h("td", {}, t.name + (t.is_default ? " (default)" : "")), h("td", {}, inputs[t.id].hours), h("td", {}, inputs[t.id].qty), h("td", {}, t.output_unit || ""));
            })))), h("p", { class: "hint" }, "Hours not given here count for the default output. ", rest));
        if (hoursIn) hoursIn.addEventListener("input", upd);
        upd();
      };
      let lastEq = eqSel ? eqSel.value : null;
      if (eqSel) {
        eqSel.addEventListener("change", () => { lastEq = eqSel.value; draw(); });
        const tick = setInterval(() => { if (!m.isConnected) return clearInterval(tick); if (eqSel.value !== lastEq) { lastEq = eqSel.value; draw(); } }, 400);
      }
      draw();
      /* after the logsheet is saved, save the split */
      const btn = m.querySelector("footer .btn.primary");
      if (!btn || !editable) return;
      const origRun = window.run;
      btn.addEventListener("click", () => {
        const items = tools.map((t) => ({ tool_id: t.id, hours: inputs[t.id] && inputs[t.id].hours.value, output_qty: inputs[t.id] && inputs[t.id].qty.value }));
        if (!items.some((x) => x.hours || x.output_qty) && !(row && row.id)) return;
        window.run = async function (fn, args, msg) {
          const r = await origRun(fn, args, msg);
          if (fn === "log.save" && r && r.id) {
            window.run = origRun;
            try { await api("tool.log_save", { log_id: r.id, items }); } catch (e) { toast("Logsheet saved, but the output split was not: " + e.message, "err"); }
          }
          return r;
        };
        setTimeout(() => { window.run = origRun; }, 15000);
      }, true);
    };
  }
})();
