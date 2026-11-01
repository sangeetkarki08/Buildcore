/* Split procurement (BuildCore 2.19): one supplier purchase shared between project use and trading / resale.
   Adds a Procurement purpose to the GRN and the purchase bill, an allocation editor for mixed purchases,
   the Project & trading purchases screen with its reports, and the Trading sales screen. */
"use strict";

(function () {
  const PURPOSES = [["project", "Project use"], ["trading", "Trading / resale"], ["general", "General company use"], ["mixed", "Mixed purchase"]];
  const DEST_PURPOSES = PURPOSES.slice(0, 3);
  const PNAME = Object.fromEntries(PURPOSES);
  const pname = (p) => PNAME[p] || (p ? p : "(not set)");
  const ccs = (purpose) => (S.L.projects || []).filter((p) => ((p.kind || "project") === purpose) && p.status !== "closed")
    .map((p) => [p.id, p.code + " " + p.name]);
  const mainStore = (pid) => (S.L.stores.find((x) => String(x.project_id) === String(pid) && x.type === "main") || {}).id;
  const repop = (f, name, opts, blank) => {
    const sel = f.querySelector('select[name="' + name + '"]');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = "";
    if (blank !== false) sel.append(h("option", { value: "" }, blank || "—"));
    opts.forEach(([v, l]) => sel.append(h("option", { value: v, selected: String(v) === String(cur) }, l)));
  };
  const ccOf = (pid) => { const p = (S.L.projects || []).find((x) => String(x.id) === String(pid)); return p ? (p.kind || "project") : "project"; };

  /* ── the GRN editor gets the purpose and the allocation editor ── */
  function purposeField(d) {
    return { k: "procurement_purpose", label: "Procurement purpose", type: "select", options: PURPOSES,
             blank: "(not set)", readonly: d.status !== "draft" };
  }

  async function allocEditor(ctx) {
    const d = await ctx.save(true);                 // lines need their ids
    const cur = await api("proc.alloc_get", { grn_id: d.id });
    const lineOpts = d.lines.filter((l) => l.material_id).map((l) => [l.id, nm.mat(l.material_id) + " — " +
      fmtQty(l.accepted_qty == null ? l.received_qty : l.accepted_qty) + " " + nm.unit(l.material_id)]);
    const rows = [];
    cur.lines.forEach((l) => (l.destinations || []).forEach((x) => rows.push({
      grn_line_id: l.grn_line_id, purpose: x.purpose, project_id: x.project_id, store_id: x.store_id,
      boq_item_id: x.boq_item_id, qty: x.qty })));
    if (!rows.length) {  // start from "all of it to the GRN's own store"; the user carves the other shares out
      const hv = ctx.hf.values();
      cur.lines.forEach((l) => rows.push({ grn_line_id: l.grn_line_id, purpose: ccOf(hv.project_id || d.project_id),
        project_id: hv.project_id || d.project_id, store_id: hv.store_id || d.store_id,
        qty: l.accepted_qty == null ? l.received_qty : l.accepted_qty }));
    }
    const le = lineEditor([
      { k: "grn_line_id", label: "GRN line", type: "select", options: lineOpts, w: 230 },
      { k: "purpose", label: "Purpose", type: "select", options: DEST_PURPOSES, w: 150, rerender: true,
        onChange: (r) => { r.project_id = ""; r.store_id = ""; r.boq_item_id = ""; } },
      { k: "project_id", label: "Project / cost centre", type: "select", w: 210, rerender: true,
        options: (r) => ccs(r.purpose || "project"), onChange: (r) => { r.store_id = mainStore(r.project_id); r.boq_item_id = ""; } },
      { k: "store_id", label: "Into store", type: "select", w: 150, options: (r) => r.project_id ? opt.stores(r.project_id) : [] },
      { k: "boq_item_id", label: "BOQ item (project use)", type: "select", w: 190,
        options: (r) => (r.purpose || "project") === "project" && r.project_id ? opt.boq(r.project_id) : [] },
      { k: "qty", label: "Qty", type: "number", w: 90 },
    ], rows, { blank: { purpose: "project" } });
    const sum = h("div", { class: "panel" });
    const refresh = () => {
      sum.innerHTML = "";
      sum.append(h("b", {}, "Allocation against the received quantity"), kv(cur.lines.map((l) => {
        const got = le.lines().filter((x) => String(x.grn_line_id) === String(l.grn_line_id))
          .reduce((a, x) => a + (Number(x.qty) || 0), 0);
        const left = (l.accepted_qty || 0) - got;
        return [nm.mat(l.material_id), fmtQty(got) + " of " + fmtQty(l.accepted_qty) +
          (Math.abs(left) < 0.0005 ? " — complete" : "  (" + fmtQty(left) + " left)")];
      })));
    };
    refresh();
    le.addEventListener("input", (e) => {                        // keep the totals live while qty is typed
      const t = e.target, tr = t && t.closest ? t.closest("tr") : null;
      if (tr && tr._row && t.type === "number") tr._row.qty = t.value;  // lineEditor itself commits on blur
      refresh();
    });
    le.addEventListener("change", refresh);                      // select changes commit before this bubbles up
    le.addEventListener("click", () => setTimeout(refresh, 0));  // and after a row is added or removed
    const body = h("div", {},
      h("p", { class: "hint" }, "Say where each quantity of this purchase goes. The whole accepted quantity must be " +
        "allocated before a mixed GRN can be posted; each destination's stock, cost and VAT share follow it."),
      le, sum);
    modal("Destinations of " + (d.no || "draft #" + d.id), body, [
      { label: "Save allocation", cls: "primary", act: async () => {
        await run("proc.alloc_save", { grn_id: d.id, rows: le.lines() }, "Allocation saved");
        ctx.hf.set("procurement_purpose", "mixed");
      } },
      { label: "Check totals", act: () => { refresh(); return false; } },
    ]);
  }

  function destTable(dests) {
    return table([
      { k: "purpose", label: "Purpose", v: (r) => pname(r.purpose) },
      { label: "Project / cost centre", v: (r) => nm.project(r.project_id) },
      { label: "Store", v: (r) => r.store_id ? nm.store(r.store_id) : "" },
      { k: "qty", label: "Qty", fmt: "qty" }, { k: "value", label: "Stock value", fmt: "money" },
      { k: "invoiced_qty", label: "Billed qty", fmt: "qty" }, { k: "net", label: "Billed net", fmt: "money" },
      { k: "vat", label: "VAT share", fmt: "money" },
    ], dests, { search: false, export: false, empty: "No destinations yet." });
  }

  function reclassDialog(d, line, dest, reopen) {
    const p0 = dest.purpose === "project" ? "trading" : "project";
    let f;
    const sync = () => {
      const v = f.values();
      repop(f, "to_project_id", ccs(v.to_purpose || "project"));
      const pid = f.values().to_project_id;
      repop(f, "to_store_id", pid ? opt.stores(pid) : [], "(main store)");
      repop(f, "boq_item_id", (v.to_purpose || "project") === "project" && pid ? opt.boq(pid) : []);
    };
    f = form([
      { k: "qty", label: "Quantity to move (of " + fmtQty(dest.qty) + ")", type: "number", req: true },
      { k: "to_purpose", label: "To purpose", type: "select", options: DEST_PURPOSES, noBlank: true },
      { k: "to_project_id", label: "To project / cost centre", type: "select", options: ccs(p0) },
      { k: "to_store_id", label: "To store", type: "select", options: [], blank: "(main store)" },
      { k: "boq_item_id", label: "BOQ item (project use)", type: "select", options: [] },
      { k: "date", label: "Date", type: "date", default: today() },
      { k: "reason", label: "Reason", wide: true, req: true },
    ], { to_purpose: p0 }, sync);
    modal("Reclassify " + nm.mat(line.material_id) + " from " + pname(dest.purpose), h("div", {},
      h("p", { class: "hint" }, "Moves stock at the purchase rate and carries its billed net and VAT share with it. " +
        "Posted as an auditable adjustment; the original purchase is not edited."), f),
      [{ label: "Reclassify", cls: "primary", act: async () => {
        const v = f.values();
        await run("proc.reclass", Object.assign(v, { grn_line_id: line.grn_line_id, from_purpose: dest.purpose,
          from_project_id: dest.project_id, from_store_id: dest.store_id }), (r) => "Posted " + r.no);
        if (reopen) reopen();
      } }], { narrow: true });
  }

  function returnDialog(d, line, dest, reopen) {
    const f = form([
      { k: "qty", label: "Quantity returned (of " + fmtQty(dest.qty) + ")", type: "number", req: true },
      { k: "credit_note_no", label: "Supplier credit note no. (needed once billed)" },
      { k: "date", label: "Date", type: "date", default: today() },
      { k: "reason", label: "Reason", wide: true, req: true },
    ], {});
    modal("Return " + nm.mat(line.material_id) + " to the supplier", h("div", {},
      h("p", { class: "hint" }, "Before billing, the receipt is simply reduced. After billing, a debit note reduces this " +
        "destination's stock, the supplier balance and the input VAT, against the supplier's credit note."), f),
      [{ label: "Post return", cls: "primary", act: async () => {
        await run("proc.return", Object.assign(f.values(), { grn_line_id: line.grn_line_id, purpose: dest.purpose,
          project_id: dest.project_id, store_id: dest.store_id }), (r) => "Posted " + r.no);
        if (reopen) reopen();
      } }], { narrow: true });
  }

  if (typeof GRN === "object") {
    const gh = GRN.header;
    GRN.header = (d, ctx) => gh(d, ctx).concat([purposeField(d)]);
    const ga = GRN.after;
    GRN.after = async (ctx) => {
      await ga(ctx);
      const d = ctx.doc;
      const box = h("div", { style: "margin-top:10px" });
      ctx.extra.append(box);
      const render = async () => {
        box.innerHTML = "";
        const p = (ctx.hf.values().procurement_purpose || d.procurement_purpose || "");
        if (d.status === "draft") {
          if (can("inventory", "edit")) box.append(h("button", { class: "btn", onclick: () => allocEditor(ctx) },
            "Allocate destinations (mixed purchase)"), h("span", { class: "hint" },
            "  One delivery shared between a project and trading / resale: set the purpose to Mixed purchase and say where each quantity goes."));
          return;
        }
        if (p !== "mixed") return;
        const cur = await api("proc.alloc_get", { grn_id: d.id });
        box.append(h("h4", {}, "Destinations of this purchase"));
        for (const l of cur.lines) {
          box.append(h("p", { style: "margin:6px 0 2px" }, h("b", {}, nm.mat(l.material_id)),
            "  accepted " + fmtQty(l.accepted_qty)), destTable(l.destinations));
          if (can("inventory", "approve")) {
            l.destinations.forEach((x) => box.append(
              h("button", { class: "btn small", onclick: () => reclassDialog(d, l, x, ctx.reopen) }, "Reclassify from " + pname(x.purpose)), " ",
              h("button", { class: "btn small", onclick: () => returnDialog(d, l, x, ctx.reopen) }, "Return from " + pname(x.purpose)), " "));
          }
        }
        if (cur.adjustments.length) box.append(h("h4", {}, "Adjustments"), table([
          { k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "kind", label: "Kind" },
          { label: "From", v: (r) => r.from_project ? pname(r.from_purpose) + " / " + nm.pcode(r.from_project) : "" },
          { label: "To", v: (r) => r.to_project ? pname(r.to_purpose) + " / " + nm.pcode(r.to_project) : "" },
          { k: "qty", label: "Qty", fmt: "qty" }, { k: "value", label: "Stock value", fmt: "money" },
          { k: "net", label: "Net moved", fmt: "money" }, { k: "vat", label: "VAT moved", fmt: "money" },
          { k: "reason", label: "Reason" }], cur.adjustments, { search: false, export: false }));
      };
      ctx.hf.addEventListener("change", () => { if (ctx.doc.status === "draft") render(); });
      render();
    };
  }

  if (typeof PINV === "object") {
    const ph = PINV.header;
    PINV.header = (d, ctx) => ph(d, ctx).concat([purposeField(d || { status: "draft" })]);
    const pa = PINV.after;
    PINV.after = (ctx) => {
      pa(ctx);
      const d = ctx.doc;
      if (d.kind !== "purchase" || d.status !== "posted") return;
      const box = h("div", { style: "margin-top:10px" });
      ctx.extra.append(box);
      api("proc.invoice_alloc", { invoice_id: d.id }).then((r) => {
        if (!r.dests || !r.dests.length || (r.dests.length === 1 && !d.procurement_purpose)) return;
        box.append(h("h4", {}, "This bill by destination"), table([
          { k: "purpose", label: "Purpose", v: (x) => pname(x.purpose) },
          { label: "Project / cost centre", v: (x) => nm.project(x.project_id) },
          { k: "qty", label: "Qty", fmt: "qty" }, { k: "net", label: "Net", fmt: "money" },
          { k: "vat", label: "VAT", fmt: "money" }, { k: "payable", label: "Share of payable", fmt: "money" },
          { k: "paid", label: "Settled", fmt: "money" }, { k: "outstanding", label: "Outstanding", fmt: "money" },
        ], r.dests, { search: false, export: false }));
        if (r.payments && r.payments.length) box.append(h("h4", {}, "Settled by"), table([
          { k: "payment_no", label: "Payment", v: (x) => x.payment_no || "(debit note / advance)" }, { k: "date", label: "Date" },
          { label: "Funding source", v: (x) => pname(x.funding_purpose) + (x.funding_project_id ? " / " + nm.pcode(x.funding_project_id) : "") },
          { label: "Settles", v: (x) => pname(x.purpose) }, { k: "amount", label: "Amount", fmt: "money" },
          { k: "kind", label: "Kind" }], r.payments, { search: false, export: false }));
      }).catch(() => {});
    };
  }

  /* ── Project & trading purchases: setup, reports, review ── */
  const money = (k, label) => ({ k, label, fmt: "money" });
  const qty = (k, label) => ({ k, label, fmt: "qty" });
  const pcol = { k: "purpose", label: "Purpose", v: (r) => pname(r.purpose) };
  const ccol = { label: "Project / cost centre", v: (r) => r.project_id ? nm.project(r.project_id) : "" };
  const party = { label: "Supplier", v: (r) => nm.party(r.party_id) };
  const openBill = (r) => r.invoice_id ? docOpen("invoice", r.invoice_id) : (r.grn_id ? docOpen("grn", r.grn_id) : null);
  const VIEWS = {
    mixed: ["Mixed procurement allocation", [
      { k: "grn_no", label: "GRN" }, { k: "date", label: "Date" }, party,
      { label: "Material", v: (r) => nm.mat(r.material_id) }, pcol, ccol,
      qty("qty", "Qty"), money("value", "Stock value"), qty("billed_qty", "Billed qty"), money("net", "Billed net"),
      money("vat", "VAT share"), { k: "check", label: "Complete", fmt: "status" }], (r) => docOpen("grn", r.grn_id)],
    project_cost: ["Project purchases & material cost", [
      ccol.label ? { label: "Project", v: (r) => nm.project(r.project_id) } : null,
      { label: "Material", v: (r) => nm.mat(r.material_id) },
      qty("purchased_qty", "Purchased"), money("purchased_value", "Purchase value"), money("billed_net", "Billed net"),
      money("billed_vat", "VAT"), qty("issued_qty", "Consumed"), money("issued_value", "Material cost"),
      qty("returned_qty", "Returned"), qty("closing_qty", "Closing"), money("closing_value", "Closing value")].filter(Boolean), null],
    trading: ["Trading stock purchases & movement", [
      { k: "grn_no", label: "GRN" }, { k: "date", label: "Date" }, party,
      { label: "Material", v: (r) => nm.mat(r.material_id) }, qty("qty", "Qty"), money("value", "Stock value"),
      money("net", "Billed net"), money("vat", "VAT share")], (r) => docOpen("grn", r.grn_id)],
    supplier_purpose: ["Supplier ledger by procurement purpose", [
      { k: "no", label: "Bill" }, { k: "date", label: "Date" }, party, { k: "party_inv_no", label: "Supplier bill" },
      pcol, ccol, money("net", "Net"), money("vat", "VAT"), money("payable", "Share of payable"),
      money("paid", "Settled"), money("outstanding", "Outstanding")], openBill],
    supplier: ["Consolidated supplier ledger", [
      { k: "no", label: "Bill" }, { k: "date", label: "Date" }, party, { k: "party_inv_no", label: "Supplier bill" },
      { label: "Purpose", v: (r) => pname(r.purpose) || "(not reviewed)" }, money("subtotal", "Net"), money("vat", "VAT"),
      money("payable", "Payable"), money("debit_notes", "Debit notes"), money("paid", "Paid"), money("balance", "Balance")], openBill],
    payments: ["Project & trading payment allocation", [
      { k: "payment_no", label: "Payment", v: (r) => r.payment_no || "(debit note)" }, { k: "date", label: "Date" }, party,
      { k: "bank", label: "Paid from" },
      { label: "Funding source", v: (r) => pname(r.funding_purpose) + (r.funding_project_id ? " / " + nm.pcode(r.funding_project_id) : "") },
      { k: "invoice_no", label: "Bill" }, { label: "Settles", v: (r) => pname(r.purpose) }, money("amount", "Amount"),
      { k: "kind", label: "Kind" }], openBill],
    stores: ["Project store vs trading store stock", [
      { label: "Material", v: (r) => nm.mat(r.material_id) },
      qty("project_qty", "Project qty"), money("project_value", "Project value"),
      qty("trading_qty", "Trading qty"), money("trading_value", "Trading value"),
      qty("general_qty", "General qty"), money("general_value", "General value")], null],
    vat: ["VAT allocation & reconciliation", [
      { k: "no", label: "Bill" }, { k: "date", label: "Date" }, party, { k: "pan", label: "PAN" },
      { k: "party_inv_no", label: "Supplier bill" }, money("taxable", "Taxable"), money("invoice_vat", "Bill VAT"),
      money("project_vat", "Project VAT"), money("trading_vat", "Trading VAT"), money("general_vat", "General VAT"),
      money("returned_vat", "Returned"), money("difference", "Difference")], openBill],
    unallocated: ["Unallocated quantity & amount", [
      { k: "no", label: "Document" }, { k: "type", label: "Type" }, { k: "date", label: "Date" }, party,
      { label: "Material", v: (r) => r.material_id ? nm.mat(r.material_id) : "" }, qty("qty", "Qty"),
      qty("allocated", "Allocated"), qty("unallocated_qty", "Unallocated qty"), money("unallocated_value", "Unallocated value"),
      { k: "status", label: "Status", fmt: "status" }], (r) => docOpen(r.type, r.id)],
    reconcile: ["Invoice-level reconciliation", [
      { k: "no", label: "Bill" }, { k: "date", label: "Date" }, party, { k: "party_inv_no", label: "Supplier bill" },
      money("subtotal", "Net"), money("vat", "VAT"), money("payable", "Payable"), money("alloc_net", "Allocated net"),
      money("alloc_vat", "Allocated VAT"), money("alloc_payable", "Allocated payable"), money("returns", "Returns"),
      money("paid", "Paid"), money("outstanding", "Outstanding"), { k: "status", label: "Check", fmt: "status" }], openBill],
  };
  const ROWS_OF = { project_cost: "rows", stores: "by_material" };

  function reviewDialog(load) {
    const f = form([
      { k: "type", label: "Document", type: "select", options: [["grn", "Goods received note"], ["invoice", "Purchase bill"]], noBlank: true },
      { k: "id", label: "Document id (from the Unallocated report)", type: "number", req: true },
      { k: "purpose", label: "Purpose after review", type: "select", options: DEST_PURPOSES, noBlank: true },
      { k: "reason", label: "Reason / note", wide: true },
    ], { type: "grn", purpose: "project" });
    modal("Review the purpose of an old document", h("div", {},
      h("p", { class: "hint" }, "Documents from before 2.19 keep working as they are; this only records their purpose " +
        "for the purpose-wise reports. The purpose must match the cost centre the goods were booked to - nothing is reposted."), f),
      [{ label: "Record purpose", cls: "primary", act: async () => { await run("proc.review", f.values(), "Recorded"); load(); } }], { narrow: true });
  }

  PAGES["proc/split"] = async (root) => {
    let view = "mixed", filt = {};
    const holder = h("div"), totals = h("div");
    const load = async () => {
      const r = await run("proc.report", Object.assign({ view }, filt));
      const [title, cols, onRow] = VIEWS[view];
      const rows = r[ROWS_OF[view] || "rows"] || [];
      holder.innerHTML = "";
      totals.innerHTML = "";
      holder.append(table(cols, rows, { name: "proc_" + view, onRow: onRow || undefined, empty: "Nothing yet for this view." }));
      const t = [];
      Object.entries(r.totals || {}).forEach(([k, v]) => t.push([k.replace(/_/g, " "), /qty/.test(k) ? fmtQty(v) : fmtMoney(v)]));
      if (view === "trading" && r.books) t.push(["sales in books", fmtMoney(-r.books.trading_sales)], ["cost of goods sold", fmtMoney(r.books.cogs_trading)], ["gross profit", fmtMoney(r.gross_profit)]);
      if (view === "vat") t.push(["VAT input in books", fmtMoney(r.vat_input_books)], ["trading VAT output", fmtMoney(r.trading_sales_vat - r.trading_return_vat)]);
      if (view === "reconcile") t.push(["creditors in books", fmtMoney(r.ap_books)], ["open bills", fmtMoney(r.open_bills)]);
      if (view === "unallocated" && r.legacy_counts) t.push(["old GRNs not yet reviewed", r.legacy_counts.grn], ["old bills not yet reviewed", r.legacy_counts.invoice]);
      if (t.length) totals.append(h("div", { class: "panel" }, kv(t)));
      if (r.note) totals.append(h("p", { class: "hint" }, r.note));
      if (view === "supplier_purpose" && (r.check || []).length) totals.append(h("div", { class: "panel" }, h("b", {}, "One liability, three views"),
        kv(r.check.map((x) => [nm.party(x.party_id), "purposes " + fmtMoney(x.sum_of_purposes) + " = open bills " + fmtMoney(x.open_bills) + " = books " + fmtMoney(x.ap_books)]))));
    };
    const right = [];
    if (can("masters", "edit")) right.push(h("button", { class: "btn", onclick: async () => {
      const r = await run("proc.setup", {}, (x) => x.created.length ? "Created " + x.created.join(", ") : "Already set up");
      await reloadLookups(); load();
    } }, "Set up trading & general cost centres"));
    if (can("procurement", "approve")) right.push(h("button", { class: "btn", onclick: () => reviewDialog(load) }, "Review purpose of an old document"));
    root.append(pageHead("Project & trading purchases",
      "One supplier, one bill, one liability - with each quantity, cost, VAT share and payment followed to project use, trading / resale or general company use.", ...right));
    root.append(filterBar([
      { k: "view", label: "Report", type: "select", noBlank: true, options: Object.entries(VIEWS).map(([k, v]) => [k, v[0]]) },
      { k: "party_id", label: "Supplier", type: "select", options: () => opt.parties(["vendor", "subcontractor"]) },
      { k: "project_id", label: "Project / cost centre", type: "select", options: opt.projects },
      { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" },
    ], { view }, (v) => { view = v.view || "mixed"; filt = { party_id: v.party_id, project_id: v.project_id, from: v.from, to: v.to }; load(); }));
    root.append(totals, holder);
    await load();
  };

  /* ── trading sales ── */
  function saleDialog(load) {
    const tcs = ccs("trading");
    if (!tcs.length) return toast("Set up the Trading cost centre first (Project & trading purchases).", "err");
    let f;
    f = form([
      { k: "party_id", label: "Customer", type: "select", options: () => opt.parties(["client"]), req: true },
      { k: "project_id", label: "Trading cost centre", type: "select", options: tcs, noBlank: true },
      { k: "store_id", label: "From store", type: "select", options: opt.stores(tcs[0][0]) },
      { k: "date", label: "Date", type: "date", default: today() },
      { k: "bill_no", label: "Your sales bill no." },
      { k: "remarks", label: "Remarks", wide: true },
    ], { project_id: tcs[0][0], store_id: mainStore(tcs[0][0]) },
    () => repop(f, "store_id", opt.stores(f.values().project_id || tcs[0][0]), "(main store)"));
    const le = lineEditor([
      { k: "material_id", label: "Material", type: "select", options: opt.materials, w: 240 },
      { k: "qty", label: "Qty", type: "number", w: 90 },
      { k: "price", label: "Selling price", type: "number", w: 110 },
      { k: "vat_rate", label: "VAT %", type: "number", w: 70 },
    ], [], { blank: { vat_rate: S.L.settings.vat_rate } });
    modal("Trading sale", h("div", {}, h("p", { class: "hint" },
      "Posts one sales invoice (VAT output as usual) and takes the goods out of the trading store at their weighted " +
      "average cost, into Cost of Goods Sold - Trading. Add the buyer under Master data › Vendors, subcontractors & clients as a Client."),
      f, h("h4", { style: "margin:12px 0 6px" }, "Lines"), le),
      [{ label: "Post sale", cls: "primary", act: async () => {
        const v = f.values();
        if (!v.store_id) v.store_id = (S.L.stores.find((s) => String(s.project_id) === String(v.project_id) && s.type === "main") || {}).id;
        await run("trade.sale", Object.assign(v, { lines: le.lines() }), (r) => "Posted " + r.no + " (cost of goods " + fmtMoney(r.cogs) + ")");
        load();
      } }]);
  }

  function saleReturnDialog(row, load) {
    const f = form([
      { k: "qty", label: "Quantity returned (of " + fmtQty(row.qty - row.returned_qty) + ")", type: "number", req: true },
      { k: "date", label: "Date", type: "date", default: today() },
      { k: "reason", label: "Reason", wide: true, req: true },
    ], {});
    modal("Customer returns " + nm.mat(row.material_id), h("div", {}, h("p", { class: "hint" },
      "Posts a credit note against the sale and puts the goods back into the trading store at the cost they left at."), f),
      [{ label: "Post return", cls: "primary", act: async () => {
        const v = f.values();
        await run("trade.return", { invoice_id: row.invoice_id, date: v.date, reason: v.reason, qty: { [row.id]: v.qty } },
          (r) => "Posted " + r.no + " (credit " + fmtMoney(r.credit) + ")");
        load();
      } }], { narrow: true });
  }

  /* one-time what's-new, after any earlier version's own note */
  const LS9 = (k) => { try { return localStorage.getItem(k); } catch (e) { return "1"; } };
  const LS9set = (k) => { try { localStorage.setItem(k, "1"); } catch (e) { /* ignore */ } };
  function whatsNew219() {
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore 2.19.0", h("div", { style: "max-width:560px" },
      h("p", {}, "One supplier purchase, shared between the project and trading."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("Procurement purpose.", "A goods receipt or purchase bill can be marked Project use, Trading / resale, General company use or Mixed purchase. Documents without it work exactly as before."),
        li("Mixed purchases.", "Receive one delivery and say how much goes to which project store and how much to the trading store. One bill, one supplier liability, one VAT entry - with each destination's share of quantity, cost and VAT followed through."),
        li("Payments by funding source.", "Pay the same bill partly from project funds and partly from trading funds; the supplier ledger stays one ledger."),
        li("Trading sales.", "Sell trading stock with a normal sales invoice; cost of goods sold is taken at the trading store's average cost, and customer returns post a credit note."),
        li("Reports.", "Procurement \u203a Project & trading purchases: allocation, project cost, trading stock, supplier ledger by purpose, payment allocation, store comparison, VAT allocation, unallocated quantities and an invoice-level reconciliation.")),
      h("p", { class: "hint" }, "Old purchases are not reclassified - they keep working unchanged, and you can record their purpose later with 'Review purpose of an old document'.")),
      [{ label: "Open Project & trading purchases", cls: "primary", act: () => { location.hash = "#/proc/split"; } }], { narrow: true });
  }
  const hooks9 = (window.bcoBootHooks = window.bcoBootHooks || []);
  hooks9.push(() => {
    setTimeout(() => {
      if (LS9("bco_seen_2.19.0") === "1") return;
      if (!document.querySelector(".top") || document.querySelector(".overlay")) return;
      LS9set("bco_seen_2.19.0");
      whatsNew219();
    }, 2600);
  });

  PAGES["proc/trade"] = async (root) => {
    let filt = {};
    const holder = h("div");
    const load = async () => {
      const rows = await run("trade.list", filt);
      holder.innerHTML = "";
      holder.append(table([
        { k: "no", label: "No." }, { k: "kind", label: "Kind" }, { k: "date", label: "Date" },
        { k: "invoice_no", label: "Invoice" }, { label: "Customer", v: (r) => nm.party(r.party_id) },
        { k: "material", label: "Material" }, { k: "qty", label: "Qty", fmt: "qty" },
        { k: "price", label: "Price", fmt: "money" }, { k: "net", label: "Net", fmt: "money" },
        { k: "vat", label: "VAT", fmt: "money" }, { k: "cost_value", label: "Cost (COGS)", fmt: "money" },
        { label: "Margin", fmt: "money", v: (r) => r.kind === "sale" ? (r.net - r.cost_value) : -(Math.abs(r.net) - Math.abs(r.cost_value)) },
        { k: "returned_qty", label: "Returned", fmt: "qty" },
      ], rows, { name: "trade_moves", onRow: (r) => {
        const btns = [];
        if (r.kind === "sale" && r.qty - r.returned_qty > 0.0005 && can("accounts", "edit"))
          btns.push({ label: "Customer return", act: () => { saleReturnDialog(r, load); return false; } });
        btns.push({ label: "Open invoice", act: () => { docOpen("invoice", r.invoice_id); return false; } });
        modal(r.kind === "sale" ? "Trading sale " + r.no : "Sales return " + r.no,
          kv([["Customer", nm.party(r.party_id)], ["Material", r.material], ["Quantity", fmtQty(r.qty)],
              ["Price", fmtMoney(r.price)], ["Net", fmtMoney(r.net)], ["VAT", fmtMoney(r.vat)],
              ["Cost", fmtMoney(r.cost_value)], ["Invoice", r.invoice_no], ["Reason", r.reason]]), btns, { narrow: true });
      }, empty: "No trading sales yet. Receive stock for Trading / resale on a GRN, then post a sale here." }));
    };
    root.append(pageHead("Trading sales", "Sell trading / resale stock: one sales invoice, cost of goods sold at the trading store's average cost, returns by credit note.",
      can("accounts", "edit") ? h("button", { class: "btn primary", onclick: () => saleDialog(load) }, "New sale") : null));
    root.append(filterBar([{ k: "project_id", label: "Trading cost centre", type: "select", options: () => ccs("trading") }],
      filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };
})();
