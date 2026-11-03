/* Procurement and accounts */
"use strict";

/* ── purchase requests ── */
const PR = {
  type: "pr", title: "Purchase requests", sub: "What the site needs to buy. Approved requests go to quotation comparison and then a purchase order.",
  statuses: ["draft", "submitted", "approved", "partially_ordered", "ordered", "closed", "cancelled"],
  cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "required_by", label: "Needed by" }, { k: "priority", label: "Priority" }, { k: "source", label: "Source" }, { k: "status", label: "Status", fmt: "status" }],
  fixed: projFixed,
  header: () => [{ k: "date", label: "Date", type: "date", req: true }, { k: "required_by", label: "Needed by", type: "date" }, { k: "priority", label: "Priority", type: "select", noBlank: true, options: [["normal", "Normal"], ["urgent", "Urgent"]] }, { k: "remarks", label: "Justification", wide: true }],
  lines: (d) => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 230, onChange: (r) => { const m = byId(S.L.materials, r.material_id); if (m) { r.description = r.description || m.name; r.unit = m.unit; r.est_rate = r.est_rate || m.standard_rate; } }, rerender: true }, { k: "description", label: "Description", w: 160 }, { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "unit", label: "Unit", w: 60 }, { k: "est_rate", label: "Est. rate", type: "number", w: 90 }, { label: "Est. value", num: true, show: (r) => fmtMoney(r.qty * r.est_rate) }, { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(d.project_id || S.project), w: 170 }, { k: "ordered_qty", label: "Ordered", readonly: true, type: "number" }],
  after: async (ctx) => {
    const b = await api("po.budget", { project_id: ctx.doc.project_id || S.project });
    if (b.budget) ctx.extra.append(h("div", { class: "panel" }, h("h2", {}, "Material budget check"), kv([["Budget", fmtMoney(b.budget)], ["Committed (open POs)", fmtMoney(b.committed)], ["Consumed", fmtMoney(b.actual)], ["In stock", fmtMoney(b.stock)], ["Available", h("b", { class: b.available < 0 ? "red" : "" }, fmtMoney(b.available))]])));
  },
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("procurement", "edit")) b.push(ctx.act("Submit for approval", (c) => run("pr.submit", { id: c.doc.id }, "Submitted"), { cls: "primary" }));
    if (d.status === "submitted" && can("procurement", "approve")) {
      b.push(ctx.act("Approve", () => run("pr.approve", { id: d.id }, "Approved"), { cls: "primary" }));
      b.push(ctx.act("Return for changes", (c) => run("pr.reject", { id: d.id, reason: c.reason }, "Returned"), { confirm: "Send back to the requester?", reason: "What needs to change", reasonRequired: true }));
    }
    if (["approved", "partially_ordered"].includes(d.status) && can("procurement", "edit")) b.push({ label: "Compare quotations", cls: "primary", act: async () => { const cs = await run("cs.save", { header: { pr_id: d.id }, quotes: [] }, "Comparative statement created"); ctx.modal.close(); csEditor(cs); } });
    if (["approved", "partially_ordered", "submitted"].includes(d.status) && can("procurement", "approve")) b.push(ctx.act("Cancel / close", () => run("pr.cancel", { id: d.id }, "Done"), { confirm: "Cancel this request (or close it if partly ordered)?", danger: true }));
    if (d.status !== "draft") b.push({ label: "Print", act: () => { printDoc("Purchase Request " + d.no, [["Date", d.date], ["Needed by", d.required_by], ["Project", nm.project(d.project_id)], ["Priority", d.priority]], [{ k: "description", label: "Item" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "est_rate", label: "Est. rate", fmt: "money" }, { label: "Est. value", fmt: "money", v: (r) => r.qty * r.est_rate }], d.lines, [], d.remarks); return false; } });
    return b;
  },
};
PAGES["proc/pr"] = docListPage(PR);

/* ── comparative statement ── */
async function csEditor(cs) {
  cs = await api("cs.get", { id: cs.id });
  const editable = cs.status === "draft" && can("procurement", "edit");
  const quotes = cs.quotes.map((q) => Object.assign({}, q));
  const box = h("div");
  const render = () => {
    box.innerHTML = "";
    const head = h("tr", {}, h("th", {}, "Item"), h("th", { class: "num" }, "Qty"), quotes.map((q, i) => h("th", {}, editable ? h("div", {}, h("select", { onchange: (e) => { q.vendor_id = e.target.value; } }, h("option", { value: "" }, "Vendor…"), opt.parties(["vendor", "subcontractor"]).map(([v, l]) => h("option", { value: v, selected: String(v) === String(q.vendor_id) }, l))), h("button", { class: "del", onclick: () => { quotes.splice(i, 1); render(); } }, "×")) : nm.party(q.vendor_id) + (q.vendor_id === cs.l1_vendor_id ? " (L1)" : ""))));
    const rows = cs.lines.map((l) => h("tr", {}, h("td", {}, l.description || nm.mat(l.material_id)), h("td", { class: "num" }, fmtQty(l.qty - (l.ordered_qty || 0)) + " " + (l.unit || "")),
      quotes.map((q) => h("td", {}, editable ? h("input", { type: "number", step: "any", value: (q.rates || {})[l.id] || "", oninput: (e) => { q.rates = q.rates || {}; q.rates[l.id] = e.target.value; } }) : h("span", { class: "num" }, fmtMoney((q.rates || {})[l.id]))))));
    const extraRow = (label, key, type) => h("tr", {}, h("td", { colspan: 2 }, label), quotes.map((q) => h("td", {}, editable ? h("input", { type: type || "text", value: q[key] ?? "", oninput: (e) => { q[key] = e.target.value; } }) : (type === "number" ? fmtMoney(q[key]) : q[key] ?? ""))));
    const totals = h("tr", {}, h("td", { colspan: 2 }, h("b", {}, "Total incl. freight (before VAT)")), quotes.map((q) => h("td", { class: "num" }, q.total != null ? h("b", { class: q.vendor_id === cs.l1_vendor_id ? "green" : "" }, fmtMoney(q.total) + (q.missing ? " (incomplete)" : "")) : "")));
    box.append(h("div", { class: "tablewrap lines" }, h("table", {}, h("thead", {}, head), h("tbody", {}, rows, extraRow("Quote no.", "quote_no"), extraRow("Freight", "freight", "number"), extraRow("VAT %", "vat_rate", "number"), extraRow("Delivery (days)", "delivery_days", "number"), extraRow("Payment terms", "payment_terms"), totals))));
    if (editable) box.append(h("div", { class: "actions" }, h("button", { class: "btn small", onclick: () => { quotes.push({ rates: {}, vat_rate: S.L.settings.vat_rate }); render(); } }, "Add vendor column")));
    if (cs.status !== "draft") box.append(h("p", {}, "Recommended: ", h("b", {}, nm.party(cs.recommended_vendor_id)), cs.reason ? " — " + cs.reason : ""));
  };
  render();
  const save = () => run("cs.save", { header: { id: cs.id, remarks: cs.remarks }, quotes }, "Saved");
  const buttons = [];
  let m;
  const reopen = async () => { m.close(); csEditor(cs); };
  if (editable) {
    buttons.push({ label: "Save & recalculate", act: async () => { await save(); await reopen(); } });
    buttons.push({ label: "Submit recommendation", cls: "primary", act: async () => {
      await save(); const fresh = await api("cs.get", { id: cs.id });
      const f = form([{ k: "vendor_id", label: "Recommended vendor", type: "select", options: fresh.quotes.map((q) => [q.vendor_id, nm.party(q.vendor_id) + " — " + fmtMoney(q.total) + (q.vendor_id === fresh.l1_vendor_id ? " (L1)" : "")]), default: fresh.l1_vendor_id }, { k: "reason", label: "Reason (needed if not L1 or fewer than " + S.L.settings.min_quotes + " quotes)", type: "textarea", wide: true }]);
      m.close();
      modal("Submit " + cs.no, f, [{ label: "Submit", cls: "primary", act: async () => { await run("cs.submit", Object.assign({ id: cs.id }, f.values()), "Submitted"); csEditor(cs); } }], { narrow: true });
      return false;
    } });
  }
  if (cs.status === "submitted" && can("procurement", "approve")) {
    buttons.push({ label: "Approve & create PO", cls: "primary", act: async () => { const r = await run("cs.approve", { id: cs.id }, "Approved — PO draft created"); m.close(); openDoc(PO, r.po_id); } });
    buttons.push({ label: "Send back", act: async () => { await run("cs.reject", { id: cs.id }, "Sent back"); await reopen(); } });
  }
  if (cs.po_id) buttons.push({ label: "Open PO", act: () => { m.close(); openDoc(PO, cs.po_id); } });
  m = modal("Comparative statement " + cs.no + " (for " + cs.pr.no + ")", box, buttons, { head: stamp(cs.status) });
}
PAGES["proc/cs"] = async (root) => {
  root.append(pageHead("Comparative statements", "Create one from an approved purchase request. The lowest complete quote is marked L1."));
  const all = await run("cs.list", { project_id: S.project || null });
  root.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "pr_no", label: "Request" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { label: "Recommended", v: (r) => nm.party(r.recommended_vendor_id) }, { k: "status", label: "Status", fmt: "status" }], all, { name: "cs", onRow: (r) => csEditor(r), empty: "No statements yet. Open an approved purchase request and choose Compare quotations." }));
};

/* ── purchase orders ── */
const PO = {
  type: "po", title: "Purchase orders", sub: "Approved POs are the only way to receive goods at an agreed rate. Revisions keep a history.",
  statuses: ["draft", "pending_approval", "approved", "partially_received", "received", "closed", "cancelled"],
  cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { label: "Vendor", v: (r) => nm.party(r.vendor_id) }, { k: "total", label: "Total", fmt: "money" }, { k: "delivery_date", label: "Delivery by" }, { label: "Received", v: (r) => r.received_pct + "%" }, { k: "revision", label: "Rev" }, { k: "status", label: "Status", fmt: "status" }],
  fixed: projFixed,
  defaults: () => ({ store_id: (S.L.stores.find((s) => String(s.project_id) === String(S.project) && s.type === "main") || {}).id, terms: S.L.settings.po_terms }),
  header: (d) => [{ k: "vendor_id", label: "Vendor", type: "select", options: () => opt.parties(["vendor", "subcontractor"]), req: true }, { k: "date", label: "PO date", type: "date", req: true }, { k: "delivery_date", label: "Deliver by", type: "date" }, { k: "store_id", label: "Deliver to store", type: "select", options: () => opt.stores(d.project_id || S.project), req: true }, { k: "payment_terms", label: "Payment terms" }, { k: "freight", label: "Freight (lump sum)", type: "number" }, { k: "terms", label: "Terms & conditions", type: "textarea", wide: true }, { k: "remarks", label: "Remarks", wide: true }],
  blank: () => ({ vat_rate: S.L.settings.vat_rate }),
  lines: () => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 220, onChange: (r) => { const m = byId(S.L.materials, r.material_id); if (m) { r.description = r.description || m.name; r.unit = m.unit; } }, rerender: true }, { k: "description", label: "Description", w: 150 }, { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "unit", label: "Unit", w: 55 }, { k: "rate", label: "Rate", type: "number", w: 90 }, { k: "vat_rate", label: "VAT %", type: "number", w: 60 }, { label: "Amount", num: true, show: (r) => fmtMoney(r.qty * r.rate) }, { k: "received_qty", label: "Received", readonly: true, type: "number" }],
  after: (ctx) => {
    const t = h("div", { class: "panel" });
    ctx.extra.append(t);
    ctx.onLines = () => {
      const ls = ctx.le.lines();
      const sub = ls.reduce((a, l) => a + (Number(l.qty) || 0) * (Number(l.rate) || 0), 0);
      const vat = ls.reduce((a, l) => a + (Number(l.qty) || 0) * (Number(l.rate) || 0) * (Number(l.vat_rate) || 0) / 100, 0);
      const fr = Number(ctx.hf.values().freight) || 0;
      t.innerHTML = "";
      t.append(kv([["Subtotal", fmtMoney(sub)], ["VAT", fmtMoney(vat)], ["Freight", fmtMoney(fr)], ["Total", h("b", {}, fmtMoney(sub + vat + fr))]]));
      if (sub + vat + fr > Number(S.L.settings.high_value_po)) t.append(h("p", { class: "hint" }, "Above " + fmtMoney(S.L.settings.high_value_po) + ": an administrator must approve."));
    };
    if (ctx.doc.id) api("po.revisions", { id: ctx.doc.id }).then((rv) => { if (rv.length) ctx.extra.append(h("h4", {}, "Revision history"), table([{ k: "revision", label: "Rev" }, { k: "ts", label: "When" }, { label: "By", v: (r) => nm.user(r.user_id) }, { k: "reason", label: "Reason" }], rv, { search: false, export: false })); });
  },
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("procurement", "edit")) b.push(ctx.act("Submit for approval", (c) => run("po.submit", { id: c.doc.id }, "Submitted"), { cls: "primary" }));
    if (d.status === "pending_approval" && can("procurement", "approve")) {
      b.push(ctx.act("Approve PO", () => run("po.approve", { id: d.id }, "Approved"), { cls: "primary" }));
      b.push(ctx.act("Return for changes", (c) => run("po.reject", { id: d.id, reason: c.reason }, "Returned"), { confirm: "Send back as draft?", reason: "What needs to change", reasonRequired: true }));
    }
    if (["approved", "partially_received"].includes(d.status)) {
      if (can("inventory", "edit")) b.push({ label: "Receive goods", cls: "primary", act: async () => { const p = await run("grn.from_po", { po_id: d.id }); ctx.modal.close(); location.hash = "#/inv/grn"; setTimeout(() => docEditor(GRN, Object.assign({ status: "draft", date: today() }, p.header, { lines: p.lines })), 300); } });
      if (can("procurement", "edit")) b.push(ctx.act("Revise PO", (c) => run("po.revise", { id: d.id, reason: c.reason }, "PO is a draft again"), { confirm: "Open this PO for revision? It will need approval again.", reason: "Reason for revision", reasonRequired: true }));
      if (can("procurement", "approve")) b.push(ctx.act("Short-close", (c) => run("po.close", { id: d.id, reason: c.reason }, "Closed"), { confirm: "Close the PO? Pending quantities will not be received.", reason: "Reason", reasonRequired: true }));
      if (can("procurement", "approve")) b.push(ctx.act("Cancel PO", (c) => run("po.cancel", { id: d.id, reason: c.reason }, "Cancelled"), { confirm: "Cancel this PO?", reason: "Reason", danger: true }));
    }
    if (d.status === "received" && can("procurement", "approve")) b.push(ctx.act("Close PO", () => run("po.close", { id: d.id }, "Closed")));
    if (d.status !== "draft") {
      b.push({ label: "Print PO", act: () => { printDoc("Purchase Order " + d.no + (d.revision ? " Rev " + d.revision : ""), [["Date", d.date], ["Vendor", nm.party(d.vendor_id)], ["Vendor PAN", (byId(S.L.parties, d.vendor_id) || {}).pan], ["Deliver to", nm.project(d.project_id) + " / " + nm.store(d.store_id)], ["Deliver by", d.delivery_date], ["Payment terms", d.payment_terms]], [{ k: "description", label: "Item" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "vat_rate", label: "VAT %", fmt: "qty" }, { label: "Amount", fmt: "money", v: (r) => r.qty * r.rate }], d.lines, [["Subtotal", fmtMoney(d.subtotal)], ["VAT", fmtMoney(d.vat)], ["Freight", fmtMoney(d.freight)], ["Total", fmtMoney(d.total)]], d.terms); return false; } });
      if (can("procurement", "edit") && d.status !== "pending_approval") b.push({ label: "Rate vendor", act: () => {
        const sc = [["5", "5 excellent"], ["4", "4 good"], ["3", "3 fair"], ["2", "2 poor"], ["1", "1 bad"]];
        const f = form([{ k: "quality", label: "Quality", type: "select", options: sc }, { k: "delivery", label: "Delivery", type: "select", options: sc }, { k: "price", label: "Price", type: "select", options: sc }, { k: "service", label: "Service", type: "select", options: sc }, { k: "remarks", label: "Remarks", wide: true }]);
        modal("Rate " + nm.party(d.vendor_id), f, [{ label: "Save rating", cls: "primary", act: () => run("master.save", { table: "vendor_ratings", row: Object.assign(f.values(), { vendor_id: d.vendor_id, po_id: d.id, date: today() }) }, "Rating saved") }], { narrow: true });
        return false;
      } });
    }
    return b;
  },
};
PAGES["proc/po"] = docListPage(PO);

PAGES["proc/pending"] = async (root) => {
  const rows = await run("po.pending", { project_id: S.project || null });
  root.append(pageHead("Pending deliveries", "PO lines not yet fully received, oldest due date first."),
    summaryStrip([["PO lines pending", rows.length], ["Pending value", fmtMoney(rows.reduce((a, r) => a + (r.pending_value || 0), 0))], ["Overdue lines", rows.filter((r) => r.overdue_days).length]]),
    table([{ label: "PO", v: (r) => drillTo("po", r.po_id, r.no) }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { label: "Vendor", v: (r) => drillTo("party", r.vendor_id, nm.party(r.vendor_id)) }, { label: "Item", v: (r) => r.material_id ? drillTo("material", r.material_id, r.description) : r.description }, { k: "qty", label: "Ordered", fmt: "qty" }, { k: "received_qty", label: "Received", fmt: "qty" }, { k: "pending", label: "Pending", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "pending_value", label: "Pending value", fmt: "money" }, { k: "delivery_date", label: "Due" }, { k: "overdue_days", label: "Days late", v: (r) => r.overdue_days || "" }], rows, { name: "pending_deliveries", totals: ["pending_value"], rowClass: (r) => r.overdue_days ? "flag" : "", onRow: (r) => openDoc(PO, r.po_id), empty: "Everything ordered has been received." }));
};

PAGES["proc/vendors"] = async (root) => {
  const rows = await run("vendor.performance", {});
  root.append(pageHead("Vendor performance", "Late deliveries count POs whose last receipt was after the promised date. Ratings come from 'Rate vendor' on POs."),
    table([{ k: "code", label: "Code" }, { k: "name", label: "Vendor" }, { k: "po_count", label: "POs", fmt: "num" }, { k: "po_value", label: "PO value", fmt: "money" }, { k: "late_pos", label: "Late POs", fmt: "num" }, { k: "rejection_pct", label: "Rejected %", fmt: "qty" }, { k: "rating", label: "Rating (1–5)", v: (r) => r.rating ?? "—" }, { k: "ratings", label: "Ratings", fmt: "num" }], rows, { name: "vendor_performance" }));
};

PAGES["proc/prices"] = async (root) => {
  let v = {};
  const holder = h("div");
  root.append(pageHead("Price history", "Last receipts of a material across all projects and vendors."), filterBar([{ k: "material_id", label: "Material", type: "select", options: opt.materials }], v, async (x) => {
    const rows = await run("price.history", x);
    holder.innerHTML = "";
    holder.append(table([{ k: "date", label: "Date" }, { k: "no", label: "GRN" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { label: "Vendor", v: (r) => nm.party(r.vendor_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "landed_rate", label: "Landed rate", fmt: "money" }], rows, { name: "price_history", empty: "No receipts for this material." }));
  }), holder);
};

/* ── invoices ── */
function invoiceCfg(kind) {
  const sales = kind === "sales";
  return {
    type: "invoice", kind, module: sales ? "accounts" : "procurement", name: sales ? "Client invoice (IPC)" : "Purchase / subcontractor bill",
    title: sales ? "Client invoices (IPC)" : "Purchase & subcontractor bills",
    sub: sales ? "Bill the client. Lines linked to a BOQ item raise its executed quantity. TDS, retention and advance recovery deducted by the client are recorded here." : "Match bills to GRNs (quantity and PO rate are checked) or book direct expenses such as freight, hire and subcontract work.",
    listArgs: { kind }, statuses: ["draft", "posted", "cancelled"],
    cols: [{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" }, { label: sales ? "Client" : "Party", v: (r) => nm.party(r.party_id) }, { k: "party_inv_no", label: sales ? "IPC / ref" : "Party bill no." }, { k: "total", label: "Total", fmt: "money" }, { k: "payable", label: sales ? "Receivable" : "Payable", fmt: "money" }, { k: "balance", label: "Balance", fmt: "money" }, { k: "due_date", label: "Due" }, { k: "match_status", label: "Match", fmt: "status" }, { k: "status", label: "Status", fmt: "status" }],
    fixed: (d) => ({ project_id: d.project_id || S.project, kind }),
    header: () => [{ k: "party_id", label: sales ? "Client" : "Vendor / subcontractor", type: "select", options: () => opt.parties(sales ? ["client"] : ["vendor", "subcontractor"]), req: true }, { k: "date", label: "Invoice date", type: "date", req: true }, { k: "party_inv_no", label: sales ? "IPC / invoice ref" : "Party's bill no." }, { k: "due_date", label: "Due date", type: "date", ph: "from credit days" }, sales ? { k: "tds", label: "TDS deducted by client", type: "number" } : null, { k: "retention", label: "Retention", type: "number" }, { k: "advance_recovery", label: "Advance recovery", type: "number" }, { k: "remarks", label: "Remarks", wide: true }].filter(Boolean),
    blank: () => ({ vat_rate: S.L.settings.vat_rate, qty: 1 }),
    lines: (d) => sales
      ? [{ k: "description", label: "Description", w: 220 }, { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(d.project_id || S.project), w: 200 }, { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "rate", label: "Rate", type: "number", w: 100 }, { k: "vat_rate", label: "VAT %", type: "number", w: 60 }, { label: "Amount", num: true, show: (r) => fmtMoney(r.qty * r.rate) }, { k: "account_id", label: "Income account", type: "select", options: () => opt.accounts(["income"]), w: 170 }]
      : [{ label: "GRN item", show: (r) => r.grn_line_id ? (r.grn_label || "GRN line: " + nm.mat(r.material_id)) : "" }, { k: "description", label: "Description (non-GRN)", w: 170 }, { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "rate", label: "Rate", type: "number", w: 90 }, { k: "vat_rate", label: "VAT %", type: "number", w: 60 }, { label: "Amount", num: true, show: (r) => fmtMoney(r.qty * r.rate) }, { k: "account_id", label: "Expense account (non-GRN)", type: "select", options: (r) => r.grn_line_id ? [] : opt.accounts(["expense", "asset", "liability"]), w: 190 }, { k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, w: 140 }, { k: "boq_item_id", label: "BOQ", type: "select", options: () => opt.boq(d.project_id || S.project), w: 140 }],
    after: (ctx) => {
      const tot = h("div", { class: "panel" });
      ctx.extra.append(tot);
      ctx.onLines = () => {
        const ls = ctx.le.lines(), hv = ctx.hf.values();
        const sub = ls.reduce((a, l) => a + (Number(l.qty) || 0) * (Number(l.rate) || 0), 0);
        const vat = ls.reduce((a, l) => a + (Number(l.qty) || 0) * (Number(l.rate) || 0) * (Number(l.vat_rate) || 0) / 100, 0);
        const ded = (Number(hv.tds) || 0) + (Number(hv.retention) || 0) + (Number(hv.advance_recovery) || 0);
        tot.innerHTML = "";
        tot.append(kv([["Subtotal", fmtMoney(sub)], ["VAT", fmtMoney(vat)], ["Deductions", fmtMoney(ded)], [sales ? "Net receivable" : "Net payable", h("b", {}, fmtMoney(sub + vat - ded))], ctx.doc.status === "posted" ? ["Settled", fmtMoney(ctx.doc.paid)] : null]));
      };
      ctx.hf.addEventListener("change", ctx.onLines);
      if (!sales && ctx.doc.status === "draft") {
        ctx.extra.append(h("button", { class: "btn", onclick: async () => {
          const pid = ctx.hf.values().party_id; if (!pid) return toast("Choose the vendor first.", "err");
          const un = await run("invoice.uninvoiced", { party_id: pid });
          if (!un.length) return toast("No uninvoiced receipts for this vendor.", "err");
          const keep = ctx.le.lines().filter((l) => !l.grn_line_id && (l.description || l.account_id));
          ctx.le.setLines(keep.concat(un.map((u) => ({ grn_line_id: u.grn_line_id, grn_label: u.grn_no + " " + nm.mat(u.material_id), material_id: u.material_id, qty: u.qty, rate: u.rate, vat_rate: u.vat_rate }))));
        } }, "Load uninvoiced GRN lines"), " ", h("button", { class: "btn", onclick: async () => {
          const pid = ctx.hf.values().party_id; if (!pid) return;
          toast("Open advance: " + fmtMoney(await api("invoice.advance_balance", { party_id: pid, kind })));
        } }, "Show open advance"));
        const ov = h("label", { class: "f check", style: "margin-top:8px" }, h("input", { type: "checkbox", id: "ovr" }), "Accept rate difference from PO (needs approval rights)");
        ctx.extra.append(ov);
      }
    },
    actions: (ctx) => {
      const d = ctx.doc, b = [];
      if (d.status === "draft" && can(sales ? "accounts" : "procurement", "edit")) b.push(ctx.act("Post invoice", (c) => run("invoice.post", { id: c.doc.id, override: !!($("#ovr") || {}).checked }, (r) => "Posted " + r.no), { cls: "primary" }));
      if (d.status === "posted") {
        if (can("accounts", "edit") && d.payable - d.paid > 0.004) b.push({ label: sales ? "Receive payment" : "Pay", cls: "primary", act: () => { ctx.modal.close(); paymentDialog(sales ? "receive" : "pay", d.party_id, d.project_id); } });
        if (can("accounts", "edit") && d.payable - d.paid > 0.004) b.push({ label: "Adjust advance", act: () => {
          const f = form([{ k: "amount", label: "Amount", type: "number" }, { k: "date", label: "Date", type: "date", default: today() }]);
          modal("Adjust advance against " + d.no, f, [{ label: "Adjust", cls: "primary", act: async () => { await run("advance.adjust", Object.assign({ invoice_id: d.id }, f.values()), "Adjusted"); ctx.reopen(); } }], { narrow: true });
          return false;
        } });
        if (can("accounts", "approve")) b.push(ctx.act("Cancel invoice", (c) => run("invoice.cancel", { id: d.id, reason: c.reason }, "Cancelled"), { confirm: "Cancel this invoice? Its voucher is reversed.", reason: "Reason", reasonRequired: true, danger: true }));
        b.push({ label: "Print", act: () => { printDoc((sales ? "Tax Invoice " : "Bill Booking ") + d.no, [["Date", d.date], [sales ? "Client" : "Party", nm.party(d.party_id)], ["PAN", (byId(S.L.parties, d.party_id) || {}).pan], ["Reference", d.party_inv_no], ["Project", nm.project(d.project_id)], ["Due", d.due_date]], [{ label: "Description", v: (r) => r.description || nm.mat(r.material_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "vat_rate", label: "VAT %", fmt: "qty" }, { k: "amount", label: "Amount", fmt: "money" }], d.lines, [["Subtotal", fmtMoney(d.subtotal)], ["VAT", fmtMoney(d.vat)], ["TDS", fmtMoney(d.tds)], ["Retention", fmtMoney(d.retention)], ["Advance recovery", fmtMoney(d.advance_recovery)], ["Net", fmtMoney(d.payable)]], d.remarks); return false; } });
      }
      return b;
    },
  };
}
const PINV = invoiceCfg("purchase");
const SINV = invoiceCfg("sales");
PAGES["proc/invoices"] = docListPage(PINV);
PAGES["acc/sales"] = docListPage(SINV);

/* ── payments ── */
function paymentDialog(kind, partyId, projectId) {
  const pay = kind === "pay";
  const f = form([{ k: "party_id", label: pay ? "Pay to" : "Receive from", type: "select", options: () => opt.parties(pay ? ["vendor", "subcontractor"] : ["client"]), default: partyId }, { k: "date", label: "Date", type: "date", default: today() }, { k: "bank_account_id", label: "Cash / bank account", type: "select", options: opt.money }, { k: "project_id", label: "Project (for advances)", type: "select", options: opt.projects, default: projectId || S.project }, { k: "mode", label: "Mode", type: "select", options: [["cheque", "Cheque"], ["transfer", "Bank transfer"], ["cash", "Cash"]] }, { k: "cheque_no", label: "Cheque / reference no." }, pay ? { k: "tds_rate_id", label: "TDS", type: "select", options: opt.tds, blank: "No TDS" } : null, { k: "advance", label: "Advance (not against an invoice)", type: "number" }, { k: "remarks", label: "Remarks", wide: true }].filter(Boolean), {}, () => { if (f.values().party_id !== loaded) loadInv(); else calc(); });
  let loaded = null, invs = [];
  const invBox = h("div"), sum = h("div", { class: "panel" });
  const calc = () => {
    const v = f.values();
    const alloc = invs.reduce((a, i) => a + (Number(i._amt) || 0), 0);
    const gross = alloc + (Number(v.advance) || 0);
    const t = pay && v.tds_rate_id ? byId(S.L.tds, v.tds_rate_id) : null;
    const tds = t && gross >= (t.threshold || 0) ? Math.round(gross * t.rate) / 100 : 0;
    sum.innerHTML = "";
    sum.append(kv([["Against invoices", fmtMoney(alloc)], ["Advance", fmtMoney(v.advance || 0)], ["Gross", fmtMoney(gross)], pay ? ["TDS", fmtMoney(tds)] : null, [pay ? "Bank pays" : "Bank receives", h("b", {}, fmtMoney(gross - tds))]]));
  };
  const loadInv = async () => {
    loaded = f.values().party_id;
    invs = loaded ? await api("invoice.open", { party_id: loaded, kind: pay ? "purchase" : "sales" }) : [];
    invBox.innerHTML = "";
    invBox.append(h("h4", {}, "Open invoices"), invs.length ? h("div", { class: "tablewrap lines" }, h("table", {}, h("thead", {}, h("tr", {}, ["Invoice", "Date", "Due", "Balance", "Amount now"].map((x, i) => h("th", { class: i >= 3 ? "num" : "" }, x)))),
      h("tbody", {}, invs.map((i) => h("tr", {}, h("td", {}, i.no + " " + (i.party_inv_no || "")), h("td", {}, i.date), h("td", {}, i.due_date), h("td", { class: "num" }, fmtMoney(i.balance)),
        h("td", {}, h("input", { type: "number", step: "any", value: "", placeholder: "0", oninput: (e) => { i._amt = e.target.value; calc(); } }), h("button", { class: "btn small", onclick: (e) => { i._amt = i.balance; e.target.previousSibling.value = i.balance; calc(); } }, "Full")))))))
      : h("p", { class: "muted" }, "No open invoices."));
    calc();
  };
  loadInv();
  modal(pay ? "Make payment" : "Receive payment", h("div", {}, f, invBox, sum), [{ label: pay ? "Post payment" : "Post receipt", cls: "primary", act: async () => {
    const v = f.values();
    const r = await run("payment.create", Object.assign(v, { kind, allocations: invs.filter((i) => Number(i._amt) > 0).map((i) => ({ invoice_id: i.id, amount: i._amt })) }), (x) => "Posted " + x.no);
    if (PAGES._refresh) PAGES._refresh();
    return r;
  } }]);
}
PAGES["acc/payments"] = async (root) => {
  let v = {};
  const holder = h("div");
  const load = async () => {
    const rows = await run("payment.list", v);
    holder.innerHTML = "";
    holder.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "kind", label: "Type" }, { label: "Party", v: (r) => nm.party(r.party_id) }, { label: "Account", v: (r) => nm.acc(r.bank_account_id) }, { k: "gross", label: "Gross", fmt: "money" }, { k: "tds", label: "TDS", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "advance", label: "Advance", fmt: "money" }, { k: "cheque_no", label: "Cheque/ref" }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "payments", onRow: (r) => {
      modal("Payment " + r.no, kv([["Party", nm.party(r.party_id)], ["Date", r.date], ["Gross", fmtMoney(r.gross)], ["TDS", fmtMoney(r.tds)], ["Net", fmtMoney(r.net)], ["Advance", fmtMoney(r.advance)], ["Mode", r.mode], ["Reference", r.cheque_no], ["Remarks", r.remarks], ["Status", stamp(r.status)]]),
        [r.status === "posted" && can("accounts", "approve") ? { label: "Cancel payment", cls: "warn", act: async () => { const why = await ask("Cancel payment", "Reverse this payment and free its invoices?", { input: "Reason", required: true, danger: true }); if (why === null) return false; await run("payment.cancel", { id: r.id, reason: why }, "Cancelled"); load(); } } : null,
         { label: "Print voucher", act: () => { printDoc((r.kind === "pay" ? "Payment " : "Receipt ") + r.no, [["Date", r.date], ["Party", nm.party(r.party_id)], ["Account", nm.acc(r.bank_account_id)], ["Mode", r.mode], ["Reference", r.cheque_no]], [{ label: "Particular", v: () => r.remarks || "As per allocation" }, { label: "Gross", fmt: "money", v: () => r.gross }, { label: "TDS", fmt: "money", v: () => r.tds }, { label: "Net", fmt: "money", v: () => r.net }], [r], []); return false; } }], { narrow: true });
    } }));
  };
  PAGES._refresh = load;
  root.append(pageHead("Payments & receipts", "Pay suppliers bill-wise with TDS, give advances, and record client receipts.",
    can("accounts", "edit") ? h("button", { class: "btn primary", onclick: () => paymentDialog("pay") }, "Make payment") : null,
    can("accounts", "edit") ? h("button", { class: "btn", onclick: () => paymentDialog("receive") }, "Receive payment") : null),
    filterBar([{ k: "kind", label: "Type", type: "select", options: [["pay", "Payments"], ["receive", "Receipts"]], blank: "All" }, { k: "party_id", label: "Party", type: "select", options: () => opt.parties() }], v, (x) => { v = x; load(); }), holder);
  load();
};

/* ── chart of accounts ── */
const ROLE_HELP = "Roles tell the system which account to post to automatically. Each role must be on exactly one active account.";
PAGES["acc/coa"] = async (root) => {
  const [groups, accounts] = [await api("master.list", { table: "account_groups" }), await api("master.list", { table: "accounts" })];
  const tb = await api("rep.tb", {});
  const bal = {}; tb.forEach((r) => { bal[r.id] = r.closing; });
  const editAcc = (a) => {
    const f = form([{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true }, { k: "type", label: "Type", type: "select", noBlank: true, options: [["asset", "Asset"], ["liability", "Liability"], ["equity", "Equity"], ["income", "Income"], ["expense", "Expense"]] }, { k: "group_id", label: "Group", type: "select", options: groups.map((g) => [g.id, g.code + " " + g.name]) }, { k: "role", label: "System role", ph: "e.g. bank, material_cost" }, { k: "opening_balance", label: "Opening balance (debit +, credit −)", type: "number" }, { k: "bank_name", label: "Bank name" }, { k: "bank_acno", label: "Bank account no." }, { k: "active", label: "Active", type: "check" }], a || { active: 1, type: "expense" });
    modal(a ? "Edit account" : "New account", h("div", {}, f, h("p", { class: "hint" }, ROLE_HELP, " Use role 'bank' or 'cash' for any account you pay from.")), can("accounts", "edit") ? [{ label: "Save", cls: "primary", act: async () => { await run("master.save", { table: "accounts", row: Object.assign(f.values(), { id: a && a.id }) }, "Saved"); await reloadLookups(); go(); } }, a ? { label: "Delete", cls: "warn", act: async () => { await run("master.delete", { table: "accounts", id: a.id }, "Deleted"); await reloadLookups(); go(); } } : null] : [], { narrow: true });
  };
  const editGroup = (g) => {
    const f = form([{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true }, { k: "type", label: "Type", type: "select", noBlank: true, options: [["asset", "Asset"], ["liability", "Liability"], ["equity", "Equity"], ["income", "Income"], ["expense", "Expense"]] }, { k: "parent_id", label: "Parent group", type: "select", options: groups.map((x) => [x.id, x.code + " " + x.name]) }], g || {});
    modal(g ? "Edit group" : "New group", f, [{ label: "Save", cls: "primary", act: async () => { await run("master.save", { table: "account_groups", row: Object.assign(f.values(), { id: g && g.id }) }, "Saved"); await reloadLookups(); go(); } }], { narrow: true });
  };
  const rows = [];
  const walk = (parent, depth) => groups.filter((g) => (g.parent_id || null) === parent).forEach((g) => {
    rows.push({ g, depth });
    accounts.filter((a) => a.group_id === g.id).forEach((a) => rows.push({ a, depth: depth + 1 }));
    walk(g.id, depth + 1);
  });
  walk(null, 0);
  const body = h("tbody", {}, rows.map((r) => r.g
    ? h("tr", { class: "click", onclick: () => editGroup(r.g) }, h("td", { style: "padding-left:" + (8 + r.depth * 18) + "px" }, h("b", {}, r.g.code + " " + r.g.name)), h("td", {}, r.g.type), h("td"), h("td"), h("td"))
    : h("tr", { class: "click" + (r.a.active ? "" : " flag"), onclick: () => editAcc(r.a) }, h("td", { style: "padding-left:" + (8 + r.depth * 18) + "px" }, r.a.code + " " + r.a.name), h("td", {}, r.a.type), h("td", {}, r.a.role ? h("code", {}, r.a.role) : ""), h("td", { class: "num" }, fmtMoney(bal[r.a.id] || 0)), h("td", {}, r.a.active ? "" : "inactive"))));
  root.append(pageHead("Chart of accounts", ROLE_HELP,
    can("accounts", "edit") ? h("button", { class: "btn primary", onclick: () => editAcc(null) }, "New account") : null,
    can("accounts", "edit") ? h("button", { class: "btn", onclick: () => editGroup(null) }, "New group") : null,
    can("admin", "edit") ? h("button", { class: "btn", onclick: async () => { const r = await run("admin.reseed_accounts", {}); toast(r.added + " missing standard accounts added", "ok"); await reloadLookups(); go(); } }, "Add missing standard accounts") : null),
    h("div", { class: "tablewrap tree" }, h("table", {}, h("thead", {}, h("tr", {}, ["Account", "Type", "Role", "Balance (Dr +)", ""].map((x, i) => h("th", { class: i === 3 ? "num" : "" }, x)))), body)));
};

PAGES["acc/tdsrates"] = masterPage({ table: "tds_rates", title: "TDS rates", single: "TDS rate", module: "accounts", sub: "Check each rate against the current Income Tax Act before use.",
  cols: [{ k: "section", label: "Section" }, { k: "description", label: "Description" }, { k: "rate", label: "Rate %", fmt: "qty" }, { k: "threshold", label: "Applies from", fmt: "money" }, { k: "active", label: "Active", fmt: "yes" }],
  fields: [{ k: "section", label: "Section" }, { k: "description", label: "Description", req: true }, { k: "rate", label: "Rate %", type: "number", req: true }, { k: "threshold", label: "Minimum payment for TDS", type: "number" }, { k: "active", label: "Active", type: "check" }] });

/* ── vouchers ── */
const VTYPES = [["journal", "Journal"], ["payment", "Payment"], ["receipt", "Receipt"], ["contra", "Contra"], ["debit_note", "Debit note"], ["credit_note", "Credit note"]];
async function voucherView(id, reload) {
  const v = await run("voucher.get", { id });
  const editable = v.status === "draft" && can("accounts", "edit");
  const f = form([{ k: "type", label: "Type", type: "select", noBlank: true, options: VTYPES }, { k: "date", label: "Date", type: "date" }, { k: "project_id", label: "Project", type: "select", options: opt.projects }, { k: "ref_no", label: "Reference" }, { k: "narration", label: "Narration", wide: true }].map((x) => Object.assign(x, { readonly: !editable })), v);
  const le = voucherLines(v.lines, !editable);
  const b = [];
  if (editable) {
    b.push({ label: "Save draft", act: async () => { await run("voucher.save", { header: Object.assign(f.values(), { id: v.id }), lines: le.lines() }, "Saved"); reload && reload(); } });
    b.push({ label: "Approve & post", cls: "primary", act: async () => { await run("voucher.save", { header: Object.assign(f.values(), { id: v.id }), lines: le.lines() }); await run("voucher.post", { id: v.id }, "Posted"); reload && reload(); } });
    b.push({ label: "Delete draft", cls: "warn", act: async () => { await run("voucher.delete", { id: v.id }, "Deleted"); reload && reload(); } });
  }
  if (v.status === "posted" && v.source === "manual" && can("accounts", "approve")) b.push({ label: "Reverse", cls: "warn", act: async () => { const why = await ask("Reverse voucher", "Post a reversing voucher?", { input: "Reason", required: true, danger: true }); if (why === null) return false; await run("voucher.reverse", { id: v.id, reason: why }, "Reversed"); reload && reload(); } });
  b.push({ label: "Print", act: () => { printDoc("Voucher " + (v.no || "draft"), [["Date", v.date], ["Type", v.type], ["Project", nm.project(v.project_id)], ["Reference", v.ref_no], ["Source", v.source], ["Narration", v.narration]], [{ label: "Account", v: (r) => r.account_code + " " + r.account_name }, { k: "narration", label: "Narration" }, { k: "debit", label: "Debit", fmt: "money" }, { k: "credit", label: "Credit", fmt: "money" }], v.lines, [["Total", fmtMoney(v.total)]]); return false; } });
  modal("Voucher " + (v.no || "draft #" + v.id), h("div", {}, v.source !== "manual" ? h("p", { class: "hint" }, "Created automatically from " + v.source + ". Change it by cancelling the source document.") : null, f, h("br"), le), b, { head: stamp(v.status) });
}
function voucherLines(lines, readonly) {
  const tot = h("p");
  const le = lineEditor([{ k: "account_id", label: "Account", type: "select", options: () => opt.accounts(), w: 240 }, { k: "debit", label: "Debit", type: "number", w: 100 }, { k: "credit", label: "Credit", type: "number", w: 100 }, { k: "narration", label: "Narration", w: 150 }, { k: "project_id", label: "Project", type: "select", options: opt.projects, w: 120 }, { k: "party_id", label: "Party", type: "select", options: () => opt.parties(), w: 130 }, { k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment, w: 120 }], lines, { readonly, onChange: (ls) => {
    const d = ls.reduce((a, l) => a + (Number(l.debit) || 0), 0), c = ls.reduce((a, l) => a + (Number(l.credit) || 0), 0);
    tot.textContent = "Debit " + fmtMoney(d) + "   Credit " + fmtMoney(c) + (Math.abs(d - c) > 0.004 ? "   Difference " + fmtMoney(d - c) : "   Balanced");
    tot.className = Math.abs(d - c) > 0.004 ? "red" : "green";
  } });
  le.append(tot);
  le.refresh();
  return le;
}
PAGES["acc/vouchers"] = async (root) => {
  let v = { from: monthAgo(), to: today() };
  const holder = h("div");
  const load = async () => {
    const rows = await run("voucher.list", v);
    holder.innerHTML = "";
    holder.append(table([{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" }, { k: "type", label: "Type" }, { k: "narration", label: "Narration" }, { k: "source", label: "Source" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "total", label: "Amount", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }], rows, { name: "vouchers", onRow: (r) => voucherView(r.id, load) }));
  };
  const newV = () => {
    const f = form([{ k: "type", label: "Type", type: "select", noBlank: true, options: VTYPES }, { k: "date", label: "Date", type: "date", default: today() }, { k: "project_id", label: "Project", type: "select", options: opt.projects, default: S.project }, { k: "ref_no", label: "Reference" }, { k: "narration", label: "Narration", wide: true, req: true }]);
    const le = voucherLines([{}, {}], false);
    modal("New voucher", h("div", {}, f, h("br"), le, h("p", { class: "hint" }, S.L.settings.voucher_approval === "1" ? "Vouchers are saved as drafts and posted by an approver." : "")), [{ label: "Save draft", cls: "primary", act: async () => { await run("voucher.save", { header: f.values(), lines: le.lines() }, "Draft saved"); load(); } }]);
  };
  root.append(pageHead("Vouchers", "Manual journals, payments, receipts and contra entries, plus every automatic posting.", can("accounts", "edit") ? h("button", { class: "btn primary", onclick: newV }, "New voucher") : null),
    filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "status", label: "Status", type: "select", options: [["draft", "Draft"], ["posted", "Posted"], ["reversed", "Reversed"]], blank: "All" }, { k: "source", label: "Source", type: "select", options: ["manual", "grn", "issue", "return", "transfer", "count", "invoice", "payment", "depreciation", "internal_billing", "reversal", "opening_stock", "advance_adjust"].map((x) => [x, x]), blank: "All" }, { k: "search", label: "Search" }], v, (x) => { v = x; load(); }), holder);
  load();
};

/* ── reports ── */
function reportPage(title, sub, fields, defaults, render) {
  return async (root, params) => {
    let v = Object.assign({}, typeof defaults === "function" ? defaults(params) : defaults);
    const holder = h("div");
    let bar = null;
    /* Reports drill in and out: the render function can change the filters and reload. */
    const setValues = (patch) => {
      v = Object.assign({}, v, patch);
      const fresh = filterBar(fields, v, (x) => { v = x; load(); });
      bar.replaceWith(fresh);
      bar = fresh;
      load();
    };
    const load = async () => {
      holder.innerHTML = "";
      try { holder.append(await render(v, setValues)); } catch (e) { holder.append(h("p", { class: "red" }, e.message)); }
    };
    bar = filterBar(fields, v, (x) => { v = x; load(); });
    root.append(pageHead(title, sub,
      h("button", { class: "btn", onclick: () => printFrame(title, holder, [["Period", (v.from || "start") + " to " + (v.to || today())]]) }, "Print")),
      bar, holder);
    load();
  };
}
const projFilter = { k: "project_id", label: "Project", type: "select", options: opt.projects, blank: "All projects" };
PAGES["acc/tb"] = reportPage("Trial balance", "Opening, movement and closing per account. Filter by project for a project trial balance (company opening balances excluded).", [{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, projFilter], () => ({ from: fyStart(), to: today(), project_id: S.project }), async (v) => {
  const rows = await run("rep.tb", v);
  const d = rows.reduce((a, r) => a + r.debit, 0), c = rows.reduce((a, r) => a + r.credit, 0);
  return h("div", {}, table([{ k: "code", label: "Code" }, { k: "name", label: "Account" }, { k: "type", label: "Type" }, { k: "opening", label: "Opening", fmt: "money" }, { k: "debit", label: "Debit", fmt: "money" }, { k: "credit", label: "Credit", fmt: "money" }, { k: "closing", label: "Closing (Dr +)", fmt: "money" }], rows, { name: "trial_balance", totals: ["opening", "debit", "credit", "closing"], onRow: (r) => { location.hash = "#/acc/ledger?account=" + r.id + "&from=" + v.from + "&to=" + v.to; } }),
    h("p", { class: Math.abs(d - c) > 0.01 ? "red" : "green" }, Math.abs(d - c) > 0.01 ? "Movements do not balance." : "Movements balance."));
});
/* Summary first: every account with its movement, then the ledger of the one you click. */
PAGES["acc/ledger"] = reportPage("Account ledger",
  "Starts with every account and what moved in the period. Click any line for its ledger; click a ledger line for the voucher behind it.",
  [{ k: "account_id", label: "Account (blank = all)", type: "select", options: () => opt.accounts() },
   { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, projFilter,
   { k: "party_id", label: "Party", type: "select", options: () => opt.parties() },
   { k: "equipment_id", label: "Equipment", type: "select", options: opt.equipment }],
  (p) => ({ account_id: p.account || "", from: p.from || fyStart(), to: p.to || today() }),
  async (v, setValues) => {
    if (!v.account_id) {
      const rows = await run("rep.tb", { from: v.from, to: v.to, project_id: v.project_id });
      return h("div", {},
        summaryStrip([["Accounts with movement", rows.length],
                      ["Total debit", fmtMoney(rows.reduce((a, r) => a + r.debit, 0))],
                      ["Total credit", fmtMoney(rows.reduce((a, r) => a + r.credit, 0))]]),
        h("p", { class: "hint" }, "Click an account for its ledger."),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Account" }, { k: "type", label: "Type" },
               { k: "opening", label: "Opening", fmt: "money" }, { k: "debit", label: "Debit", fmt: "money" },
               { k: "credit", label: "Credit", fmt: "money" }, { k: "closing", label: "Closing", fmt: "money" }],
              rows, { name: "ledger_summary", title: "Account summary " + v.from + " to " + v.to,
                      totals: ["debit", "credit"], rowClass: () => "sumrow",
                      onRow: (r) => setValues({ account_id: r.id }) }));
    }
    const d = await run("rep.ledger", v);
    const acc = byId(S.L.accounts, v.account_id) || {};
    return h("div", {},
      h("div", { class: "bar" }, h("button", { class: "btn small", onclick: () => setValues({ account_id: "" }) },
        "← All accounts"), h("b", {}, acc.code + " " + acc.name)),
      summaryStrip([["Opening", fmtMoney(d.opening)],
                    ["Debit", fmtMoney(d.rows.reduce((a, r) => a + (r.debit || 0), 0))],
                    ["Credit", fmtMoney(d.rows.reduce((a, r) => a + (r.credit || 0), 0))],
                    ["Closing", fmtMoney(d.closing)]]),
      table([{ k: "date", label: "Date" }, { label: "Voucher", v: (r) => drillTo("voucher", r.voucher_id, r.no) },
             { label: "Narration", v: (r) => r.narration || r.vnar }, { k: "ref_no", label: "Ref" },
             { label: "Project", v: (r) => nm.pcode(r.project_id) },
             { label: "Party", v: (r) => drillTo("party", r.party_id, nm.party(r.party_id)) },
             { k: "debit", label: "Debit", fmt: "money" }, { k: "credit", label: "Credit", fmt: "money" },
             { k: "balance", label: "Balance", fmt: "money" }],
            d.rows, { name: "ledger", title: (acc.code || "") + " " + (acc.name || "") + " ledger",
                      totals: ["debit", "credit"], onRow: (r) => voucherView(r.voucher_id) }));
  });
PAGES["acc/daybook"] = reportPage("Day book", "Every posted voucher with its lines.", [{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], () => ({ from: today(), to: today() }), async (v) => {
  const vs = await run("rep.daybook", v);
  const rows = [];
  vs.forEach((x) => x.lines.forEach((l, i) => rows.push({ id: x.id, date: i ? "" : x.date, no: i ? "" : x.no, narr: i ? "" : x.narration, acc: l.code + " " + l.name, debit: l.debit, credit: l.credit })));
  return table([{ k: "date", label: "Date" }, { k: "no", label: "Voucher" }, { k: "narr", label: "Narration" }, { k: "acc", label: "Account" }, { k: "debit", label: "Debit", fmt: "money" }, { k: "credit", label: "Credit", fmt: "money" }], rows, { name: "daybook", totals: ["debit", "credit"], onRow: (r) => voucherView(r.id), empty: "No vouchers in this range." });
});
const statementTable = (rows, key) => table([{ k: "code", label: "Code" }, { k: "name", label: "Account" }, { k: key || "amount", label: "Amount", fmt: "money" }], rows, { search: false, totals: [key || "amount"] });
PAGES["acc/pl"] = reportPage("Profit & loss", "Income less expenses for the period. Filter by project for project margin.", [{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, projFilter], () => ({ from: fyStart(), to: today(), project_id: S.project }), async (v) => {
  const d = await run("rep.pl", v);
  return h("div", { class: "cols" }, h("div", {}, h("h2", {}, "Income"), statementTable(d.income)), h("div", {}, h("h2", {}, "Expenses"), statementTable(d.expense)),
    h("div", { class: "panel" }, kv([["Total income", fmtMoney(d.total_income)], ["Total expenses", fmtMoney(d.total_expense)], [d.profit >= 0 ? "Profit" : "Loss", h("b", { class: d.profit >= 0 ? "green" : "red" }, fmtMoney(d.profit))], ["Margin", d.total_income ? (100 * d.profit / d.total_income).toFixed(1) + "%" : "—"]])));
});
PAGES["acc/bs"] = reportPage("Balance sheet", "Company position on a date. Profit to date is shown under equity until you transfer it.", [{ k: "as_of", label: "As of", type: "date" }], () => ({ as_of: today() }), async (v) => {
  const d = await run("rep.bs", v);
  return h("div", {}, h("div", { class: "cols" }, h("div", {}, h("h2", {}, "Assets"), statementTable(d.assets)), h("div", {}, h("h2", {}, "Liabilities"), statementTable(d.liabilities), h("h2", {}, "Equity"), statementTable(d.equity.concat([{ code: "", name: "Profit / loss to date", amount: d.profit }])))),
    h("div", { class: "panel" }, kv([["Total assets", fmtMoney(d.total_assets)], ["Total liabilities", fmtMoney(d.total_liabilities)], ["Total equity", fmtMoney(d.total_equity)], ["Difference", h("b", { class: Math.abs(d.difference) > 0.01 ? "red" : "green" }, fmtMoney(d.difference))]])));
});
/* Every vendor and client with their totals; click one for the statement, advances and all. */
PAGES["acc/party"] = reportPage("Party ledger",
  "All vendors, subcontractors and clients with what they owe and what we owe. Click a party for the full statement, including advances and retention.",
  [{ k: "party_id", label: "Party (blank = all)", type: "select", options: () => opt.parties() },
   { k: "kind", label: "Type", type: "select", options: [["vendor", "Vendors"], ["subcontractor", "Subcontractors"], ["client", "Clients"]] },
   { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }],
  (p) => ({ party_id: p.party || "", from: "", to: today() }),
  async (v, setValues) => {
    if (!v.party_id) {
      const rows = await run("rep.party_summary", v);
      const sum = (k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
      return h("div", {},
        summaryStrip([["Parties with a balance", rows.length], ["Debit", fmtMoney(sum("debit"))],
                      ["Credit", fmtMoney(sum("credit"))], ["They owe us", fmtMoney(sum("owed_by_them"))],
                      ["We owe them", fmtMoney(sum("owed_to_them"))],
                      ["Advances outstanding", fmtMoney(sum("advance"))]]),
        h("p", { class: "hint" }, "Click a party for its statement."),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Party" }, { k: "kind", label: "Type" },
               { k: "opening", label: "Opening", fmt: "money" }, { k: "debit", label: "Debit", fmt: "money" },
               { k: "credit", label: "Credit", fmt: "money" }, { k: "closing", label: "Balance", fmt: "money" },
               { k: "advance", label: "Advance with them", fmt: "money" },
               { k: "retention", label: "Retention held", fmt: "money" }],
              rows, { name: "party_summary", title: "Party balances to " + (v.to || today()),
                      totals: ["debit", "credit", "closing", "advance", "retention"], rowClass: () => "sumrow",
                      onRow: (r) => setValues({ party_id: r.party_id }) }));
    }
    const d = await run("rep.party", v);
    const party = d.party || {};
    const roleAmt = (roles) => (d.by_account || []).filter((x) => roles.includes(x.role))
      .reduce((a, x) => a + (x.amt || 0), 0);
    return h("div", {},
      h("div", { class: "bar" }, h("button", { class: "btn small", onclick: () => setValues({ party_id: "" }) },
        "← All parties"), h("b", {}, party.name || ""), h("span", { class: "muted" },
        [party.kind, party.pan ? "PAN " + party.pan : null, party.phone].filter(Boolean).join(" · "))),
      summaryStrip([["Opening", fmtMoney(d.opening)],
                    ["Closing", fmtMoney(d.closing)],
                    ["Bills outstanding", fmtMoney(Math.abs(roleAmt(["ap_control", "ar_control"])))],
                    ["Advance not yet adjusted", fmtMoney(roleAmt(["supplier_advance", "subcon_advance"]))],
                    ["Advance received", fmtMoney(-roleAmt(["client_advance"]))],
                    ["Retention", fmtMoney(-roleAmt(["retention_payable", "retention_receivable"]))],
                    ["Goods received not billed", fmtMoney(-roleAmt(["grni"]))]]),
      h("p", { class: "hint" }, d.note + " Advances and retention are part of this statement, not a separate sheet."),
      table([{ k: "date", label: "Date" }, { label: "Voucher", v: (r) => drillTo("voucher", r.voucher_id, r.no) },
             { k: "account", label: "Account" }, { label: "Narration", v: (r) => r.narration || r.vnar },
             { k: "ref_no", label: "Ref" }, { k: "debit", label: "Debit", fmt: "money" },
             { k: "credit", label: "Credit", fmt: "money" }, { k: "balance", label: "Balance", fmt: "money" }],
            d.rows, { name: "party_statement", title: (party.name || "Party") + " statement",
                      totals: ["debit", "credit"], onRow: (r) => voucherView(r.voucher_id) }),
      h("div", { class: "actions" },
        can("accounts", "edit") ? h("button", { class: "btn primary", onclick: () => paymentDialog(party.kind === "client" ? "receive" : "pay", party.id) }, party.kind === "client" ? "Receive from this party" : "Pay this party") : null,
        h("button", { class: "btn", onclick: () => { location.hash = "#/acc/ageing"; } }, "Ageing")));
  });
PAGES["acc/ageing"] = reportPage("Ageing", "Open invoice balances by days past due.", [{ k: "kind", label: "Type", type: "select", noBlank: true, options: [["purchase", "Payables"], ["sales", "Receivables"]] }, { k: "as_of", label: "As of", type: "date" }, projFilter], () => ({ kind: "purchase", as_of: today() }), async (v) => {
  const rows = await run("rep.ageing", v);
  return table([{ label: "Party", v: (r) => drillTo("party", r.party_id, nm.party(r.party_id)) }, { k: "current", label: "Not due", fmt: "money" }, { k: "d30", label: "1–30", fmt: "money" }, { k: "d60", label: "31–60", fmt: "money" }, { k: "d90", label: "61–90", fmt: "money" }, { k: "d90p", label: "Over 90", fmt: "money" }, { k: "total", label: "Total", fmt: "money" }], rows, { name: "ageing", totals: ["current", "d30", "d60", "d90", "d90p", "total"], rowClass: (r) => r.d90p ? "bad" : r.d60 || r.d90 ? "flag" : "", onRow: (r) => modal(nm.party(r.party_id), table([{ label: "Invoice", v: (x) => drillTo("invoice", x.id, x.no) }, { k: "date", label: "Date" }, { k: "due_date", label: "Due" }, { k: "days", label: "Days late" }, { k: "balance", label: "Balance", fmt: "money" }], r.invoices, { search: false }), [{ label: v.kind === "purchase" ? "Pay" : "Receive", cls: "primary", act: () => paymentDialog(v.kind === "purchase" ? "pay" : "receive", r.party_id) }], { narrow: true }), empty: "Nothing outstanding." });
});
PAGES["acc/vat"] = reportPage("VAT purchase & sales book", "Monthly register for VAT returns. Confirm the column layout your tax office requires.", [{ k: "kind", label: "Book", type: "select", noBlank: true, options: [["purchase", "Purchase book"], ["sales", "Sales book"]] }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], () => ({ kind: "purchase", from: today().slice(0, 8) + "01", to: today() }), async (v) => {
  const rows = await run("rep.vat", v);
  return table([{ k: "date", label: "Date" }, { label: "Our no.", v: (r) => drillTo("invoice", r.id, r.no) }, { k: "party_inv_no", label: "Invoice no." }, { label: "Party", v: (r) => drillTo("party", r.party_id, r.party_name) }, { k: "pan", label: "PAN" }, { k: "subtotal", label: "Total value", fmt: "money" }, { k: "exempt", label: "Exempt", fmt: "money" }, { k: "taxable", label: "Taxable", fmt: "money" }, { k: "vat", label: "VAT", fmt: "money" }], rows, { name: "vat_" + v.kind, totals: ["subtotal", "exempt", "taxable", "vat"], empty: "No invoices in this range." });
});
PAGES["acc/tds"] = reportPage("TDS register", "TDS we deducted on payments (to deposit) and TDS clients deducted from us.", [{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], () => ({ from: today().slice(0, 8) + "01", to: today() }), async (v) => {
  const d = await run("rep.tds", v);
  return h("div", {}, h("div", { class: "panel" }, kv([["Deducted", fmtMoney(d.total_deducted)], ["Deposited (debits to TDS payable)", fmtMoney(d.total_deposited)], ["Suffered (receivable)", fmtMoney(d.total_suffered)]])),
    h("h2", {}, "Deducted by us"), table([{ k: "date", label: "Date" }, { k: "no", label: "Payment" }, { k: "party_name", label: "Party" }, { k: "pan", label: "PAN" }, { k: "section", label: "Section" }, { k: "rate", label: "Rate %" }, { k: "gross", label: "Gross", fmt: "money" }, { k: "tds", label: "TDS", fmt: "money" }], d.deducted, { name: "tds_deducted", totals: ["gross", "tds"] }),
    h("h2", {}, "Deducted by clients"), table([{ k: "date", label: "Date" }, { k: "no", label: "Invoice" }, { k: "party_name", label: "Client" }, { k: "pan", label: "PAN" }, { k: "gross", label: "Invoice value", fmt: "money" }, { k: "tds", label: "TDS", fmt: "money" }], d.suffered, { name: "tds_suffered", totals: ["gross", "tds"] }),
    h("p", { class: "hint" }, "Record a TDS deposit as a payment voucher: debit TDS Payable, credit Bank."));
});
PAGES["acc/bank"] = reportPage("Bank reconciliation", "Tick entries that appear on the bank statement and set the clearing date.", [{ k: "account_id", label: "Bank account", type: "select", options: opt.money }, { k: "to", label: "Statement date", type: "date" }], () => ({ to: today() }), async (v) => {
  if (!v.account_id) return h("p", { class: "muted" }, "Choose a bank account.");
  const d = await run("bank.lines", v);
  const picked = new Set();
  const dt = h("input", { type: "date", value: v.to, style: "max-width:170px" });
  const rowsEl = d.rows.map((r) => h("tr", { class: r.cleared_date ? "" : "flag" }, h("td", {}, h("input", { type: "checkbox", onchange: (e) => e.target.checked ? picked.add(r.id) : picked.delete(r.id) })), h("td", {}, r.date), h("td", {}, r.no), h("td", {}, r.narration || r.vnar), h("td", {}, r.ref_no || ""), h("td", { class: "num" }, fmtMoney(r.debit)), h("td", { class: "num" }, fmtMoney(r.credit)), h("td", {}, r.cleared_date || "")));
  const act = async (clear) => { if (!picked.size) return toast("Tick at least one entry.", "err"); await run("bank.clear", { ids: [...picked], date: clear ? dt.value : null }, "Updated"); go(); };
  return h("div", {}, h("div", { class: "panel" }, kv([["Balance as per books", fmtMoney(d.book_balance)], ["Less: deposits not yet credited by bank", fmtMoney(d.uncleared_deposits)], ["Add: payments not yet presented", fmtMoney(d.uncleared_payments)], ["Balance as per bank should be", h("b", {}, fmtMoney(d.bank_balance))]])),
    can("accounts", "edit") ? h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Cleared on"), dt), h("button", { class: "btn primary", onclick: () => act(true) }, "Mark cleared"), h("button", { class: "btn", onclick: () => act(false) }, "Mark uncleared")) : null,
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["", "Date", "Voucher", "Narration", "Ref", "Deposit", "Withdrawal", "Cleared"].map((x) => h("th", {}, x)))), h("tbody", {}, rowsEl))));
});
PAGES["acc/budget"] = reportPage("Budget vs actual", "Set budgets per cost account (optionally per BOQ item). Open PO value counts as committed against material cost.", [], {}, async () => {
  if (!S.project) return projectNotice();
  const d = await run("rep.budget", { project_id: S.project });
  const addBtn = can("accounts", "edit") ? h("button", { class: "btn primary", onclick: () => {
    const f = form([{ k: "account_id", label: "Cost account", type: "select", options: () => opt.accounts(["expense"]) }, { k: "boq_item_id", label: "BOQ item (optional)", type: "select", options: () => opt.boq(S.project) }, { k: "amount", label: "Budget amount", type: "number" }, { k: "remarks", label: "Remarks" }]);
    modal("Add budget line", f, [{ label: "Save", cls: "primary", act: async () => { await run("master.save", { table: "budgets", row: Object.assign(f.values(), { project_id: S.project }) }, "Saved"); go(); } }], { narrow: true });
  } }, "Add budget line") : null;
  return h("div", {}, h("div", { class: "tiles" }, [["Contract value", d.project.contract_value], ["Revenue booked", d.revenue], ["Cost booked", d.cost], ["Margin", d.margin]].map(([k, x]) => h("div", { class: "tile" + (k === "Margin" && x < 0 ? " bad" : "") }, h("b", {}, fmtMoney(x)), h("span", {}, k)))),
    addBtn, table([{ k: "code", label: "Code" }, { k: "name", label: "Account" }, { label: "BOQ", v: (r) => nm.boq(r.boq_item_id) }, { k: "amount", label: "Budget", fmt: "money" }, { k: "committed", label: "Committed", fmt: "money" }, { k: "actual", label: "Actual", fmt: "money" }, { k: "available", label: "Available", fmt: "money" }, { k: "used_pct", label: "Used", v: (r) => fmtPct(r.used_pct) }], d.rows, { name: "budget", totals: ["amount", "committed", "actual", "available"], rowClass: (r) => r.available < 0 ? "bad" : r.used_pct > 90 ? "flag" : "", onRow: (r) => can("accounts", "edit") && ask("Remove budget line", "Delete this budget line?", { danger: true }).then(async (ok) => { if (ok) { await run("master.delete", { table: "budgets", id: r.id }); go(); } }), empty: "No budget lines yet." }),
    h("h2", { style: "margin-top:18px" }, "Cost by BOQ item"), table([{ k: "code", label: "Code" }, { k: "description", label: "Description" }, { k: "amount", label: "BOQ amount", fmt: "money" }, { k: "progress_pct", label: "Progress", v: (r) => r.progress_pct + "%" }, { k: "earned", label: "Earned", fmt: "money" }, { k: "cost", label: "Cost", fmt: "money" }, { k: "margin", label: "Margin", fmt: "money" }], await api("rep.boq_cost", { project_id: S.project }), { name: "boq_cost", totals: ["amount", "earned", "cost", "margin"], rowClass: (r) => r.margin < 0 ? "bad" : "" }));
});
PAGES["acc/periods"] = async (root) => {
  const rows = await run("master.list", { table: "fiscal_periods" });
  const gen = () => {
    const f = form([{ k: "fy", label: "Fiscal year label", ph: "2083-84" }, { k: "start_date", label: "Shrawan 1 falls on (AD date)", type: "date" }]);
    modal("Create 12 monthly periods", h("div", {}, f, h("p", { class: "hint" }, "Month boundaries are approximate. Edit any period's start and end dates to match the Nepali calendar exactly.")), [{ label: "Create", cls: "primary", act: async () => { await run("period.generate", f.values(), "Periods created"); go(); } }], { narrow: true });
  };
  const edit = (p) => {
    const f = form([{ k: "code", label: "Name" }, { k: "fy", label: "Fiscal year" }, { k: "start_date", label: "Start", type: "date" }, { k: "end_date", label: "End", type: "date" }], p);
    const st = (s) => ({ label: s === "open" ? "Open" : s === "soft_closed" ? "Soft-close (admins only)" : "Lock", act: async () => { await run("period.status", { id: p.id, status: s }, "Period is now " + s.replace("_", "-")); go(); } });
    modal("Period " + p.code, f, can("accounts", "approve") ? [{ label: "Save dates", cls: "primary", act: async () => { await run("master.save", { table: "fiscal_periods", row: Object.assign(f.values(), { id: p.id }) }, "Saved"); go(); } }, st("open"), st("soft_closed"), st("locked")] : [], { narrow: true, head: stamp(p.status) });
  };
  root.append(pageHead("Accounting periods", "Lock a month once it is reviewed. No document or voucher can be dated inside a locked period.", can("accounts", "approve") ? h("button", { class: "btn primary", onclick: gen }, "Create fiscal year") : null),
    table([{ k: "fy", label: "FY" }, { k: "code", label: "Period" }, { k: "start_date", label: "Start" }, { k: "end_date", label: "End" }, { k: "status", label: "Status", fmt: "status" }], rows.sort((a, b) => a.start_date.localeCompare(b.start_date)), { onRow: edit, empty: "No periods yet. Entries are allowed on any date until periods exist." }));
};
PAGES["acc/integrity"] = async (root) => {
  const rows = await run("rep.integrity", {});
  root.append(pageHead("Integrity checks", "Confirms that stores, bills and the ledger agree. Run it before closing a month."),
    table([{ label: "Result", v: (r) => stamp(r.ok ? "ok" : "overdue") }, { k: "check", label: "Check" }, { k: "detail", label: "Detail" }], rows, { search: false, rowClass: (r) => r.ok ? "" : "bad" }));
};
