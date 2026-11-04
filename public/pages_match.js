/* BuildCore 2.45 — Match site receipts, VAT bills and payments.
   New tabs on Procurement › Purchase bills (the menu is unchanged):
     Match receipts, bills & payments · Bill vs actual · Match settings
   Store enters what arrived (GRN). Accounts enters the VAT bill exactly as printed and links it to the goods,
   records purchases without VAT bill, and pays. Stock and cost come from the GRN; VAT comes from the bill. */
(function () {
  "use strict";
  if (window.__bcoMatch) return;
  window.__bcoMatch = true;

  const ROUTE = "proc/invoices";
  const M = (v) => (v == null ? "—" : fmtMoney(v));
  const Q = (v) => (v == null ? "" : fmtQty(v));
  const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const offNote = (st) => h("div", { class: "panel" }, h("b", {}, "Matching is off for this company."),
    h("p", { class: "hint" }, "Turn it on in the Match settings tab (needs Accounts approve rights). Until then BuildCore works as before."),
    st && st.can_change ? h("button", { class: "btn primary", onclick: async () => { await run("mt.settings_save", { on: 1 }, "Matching turned on"); location.reload(); } }, "Turn matching on") : null);

  /* ───────── vendor list and vendor screen ───────── */
  async function matchTab() {
    const box = h("div", { "data-mt": "match" });
    const st = await api("mt.settings", {});
    if (!st.on) { box.append(offNote(st)); return box; }
    const list = async () => {
      const d = await api("mt.vendors", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Three truths per vendor: what arrived at site (store's GRN), what the vendor billed (VAT bill as printed) and what was paid. Gaps listed from " + d.from + ". Click a vendor to match."));
      box.append(summaryStrip([["Received, not billed", M(d.totals.received_not_billed)], ["of which older than " + st.old_days + " days", M(d.totals.received_not_billed_old)],
        ["Bills waiting for goods", M(d.totals.bills_waiting)], ["Paid, no VAT bill yet", M(d.totals.paid_no_bill)], ["Payable on bills", M(d.totals.payable)], ["Purchases without VAT bill", M(d.totals.novat)]]));
      box.append(table([{ k: "vendor", label: "Vendor" }, { k: "received_not_billed", label: "Received, not billed", fmt: "money" },
        { k: "bills_waiting", label: "Bills waiting for goods", fmt: "money" }, { k: "paid_no_bill", label: "Paid, no VAT bill yet", fmt: "money" },
        { k: "payable", label: "Payable on bills", fmt: "money" }, { k: "novat", label: "No VAT bill", fmt: "money" },
        { k: "different_items", label: "Different-item links" }, { label: "State", v: (r) => r.matched ? "matched" : "gaps" }],
      d.rows, { name: "mt_vendors", onRow: (r) => vendor(r.party_id), empty: "No purchases since " + d.from + ".", totals: ["received_not_billed", "bills_waiting", "paid_no_bill", "payable", "novat"] }));
    };
    const vendor = async (pid) => {
      const d = await api("mt.vendor", { party_id: pid });
      const s = d.summary;
      box.innerHTML = "";
      const edit = can("procurement", "edit"), appr = can("procurement", "approve"), accA = can("accounts", "approve");
      box.append(h("div", { class: "bar" }, h("button", { class: "btn small", onclick: list }, "‹ All vendors"), h("h3", { style: "margin:0 8px" }, d.vendor.name + (d.vendor.pan ? " · PAN " + d.vendor.pan : ""))));
      box.append(summaryStrip([["Received, not billed", M(s.received_not_billed)], ["Bills waiting for goods", M(s.bills_waiting)], ["Paid, no VAT bill yet", M(s.paid_no_bill)],
        ["Payable on bills", M(s.payable)], ["Without VAT bill", M(s.novat)], ["GRN clearing (ledger)", M(s.grn_clearing_ledger)]]));
      if (s.matched) box.append(h("p", { class: "green" }, "Matched: every receipt is billed, no bill waits for goods, and no money sits paid without a bill."));
      const acts = h("div", { class: "actions" });
      if (edit && s.received_not_billed > 0) acts.append(h("button", { class: "btn", onclick: () => novatDialog(d, () => vendor(pid)) }, "Purchase without VAT bill…"));
      acts.append(h("button", { class: "btn", onclick: () => { location.hash = "#/proc/invoices"; } }, "New purchase bill (as printed)"));
      box.append(acts);
      box.append(h("h3", {}, "1 · Arrived at site (store's GRNs)"), table([{ k: "date", label: "Date" }, { label: "GRN", v: (r) => drillTo("grn", r.grn_id, r.grn_no) },
        { k: "project", label: "Project" }, { k: "material", label: "Item" }, { k: "accepted_qty", label: "Accepted", fmt: "qty" }, { k: "unit", label: "Unit" },
        { k: "rate", label: "Rate", fmt: "money" }, { k: "value", label: "Value", fmt: "money" }, { k: "invoiced_qty", label: "Billed qty", fmt: "qty" },
        { k: "unbilled_value", label: "Not billed", fmt: "money" }], d.grn, { name: "mt_grn", rowClass: (r) => r.unbilled_qty > 0.0001 ? "warnrow" : "", totals: ["value", "unbilled_value"] }));
      box.append(h("h3", {}, "2 · Billed by the vendor (as printed)"), table([{ k: "date", label: "Date" }, { label: "Bill", v: (r) => drillTo("invoice", r.id, (r.party_inv_no || r.no || "draft")) },
        { k: "status", label: "Status", fmt: "status" }, { label: "Printed lines", v: (r) => r.lines.map((l) => l.description + " " + fmtQty(l.qty) + " × " + fmtMoney(l.rate)).join("; ") },
        { k: "subtotal", label: "Taxable", fmt: "money" }, { k: "vat", label: "VAT", fmt: "money" }, { k: "total", label: "Total", fmt: "money" },
        { label: "Goods link", v: (r) => r.novat ? "no VAT bill" : r.map_status || (r.posted_mapped ? "linked" : (r.lines.some((l) => l.grn) ? "linked (same item)" : "")) },
        { label: "", v: (r) => {
          const b = [];
          if (r.status === "draft" && edit && !r.novat) b.push(h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); mapDialog(r.id, () => vendor(pid)); } }, r.map_status ? "Edit links" : "Link to goods"));
          if (r.status === "draft" && r.map_status === "waiting approval" && appr) b.push(h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); await run("mt.map_approve", { invoice_id: r.id }, "Links approved"); vendor(pid); } }, "Approve links"));
          if (r.status === "draft" && r.novat && appr) b.push(h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); await run("mt.novat_approve", { invoice_id: r.id }, (x) => "Posted" + (x.advance_adjusted ? ", advance " + fmtMoney(x.advance_adjusted) + " set against it" : "")); vendor(pid); } }, "Approve no-VAT purchase"));
          if (r.status === "draft" && (r.map_status === "linked" || r.lines.some((l) => l.grn)) && edit && !r.novat) b.push(h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("invoice.post", { id: r.id }, "Bill posted"); vendor(pid); } }, "Post bill"));
          if (r.status === "posted" && accA && !r.novat) b.push(h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); reclassDialog(r.id, () => vendor(pid)); } }, "Reclassify cost…"));
          return h("span", {}, ...b);
        } }], d.bills, { name: "mt_bills", totals: ["subtotal", "vat", "total"], empty: "No bills since " + d.from + "." }));
      box.append(h("h3", {}, "3 · Paid"), table([{ k: "date", label: "Date" }, { label: "Payment", v: (r) => drillTo("payment", r.id, r.no) }, { k: "bank", label: "From" },
        { k: "cheque_no", label: "Cheque" }, { k: "gross", label: "Amount", fmt: "money" }, { k: "against", label: "Against bills" },
        { k: "advance", label: "Paid without bill (advance)", fmt: "money" }, { k: "remarks", label: "Remarks" }], d.payments, { name: "mt_pay", totals: ["gross", "advance"], empty: "No payments since " + d.from + "." }));
      if (s.paid_no_bill > 0) box.append(h("p", { class: "hint" }, "Money paid with no bill yet: " + M(s.paid_no_bill) + ". When the VAT bill comes, set the advance against it in Payments; if no bill will come, record a purchase without VAT bill for the goods and BuildCore sets the advance against it."));
    };
    await list();
    return box;
  }

  /* ───────── link a printed bill to the goods received ───────── */
  async function mapDialog(iid, done) {
    const d = await api("mt.map_get", { invoice_id: iid });
    const cand = d.candidates;
    const lineOpt = d.lines.map((l) => [l.id, l.description + " · " + fmtQty(l.qty) + " × " + fmtMoney(l.rate) + " = " + fmtMoney(l.amount)]);
    const candOpt = cand.map((g) => [g.grn_line_id, g.grn_no + " · " + (g.material || "") + " · not billed " + fmtQty(g.unbilled_qty) + " " + (g.unit || "") + " @ " + fmtMoney(g.rate)]);
    let start = d.maps.map((m) => ({ invoice_line_id: m.invoice_line_id, grn_line_id: m.grn_line_id, qty: m.qty, amount: m.amount, reason: m.reason || "" }));
    if (!start.length) {
      const left = {};
      cand.forEach((g) => { left[g.grn_line_id] = g.unbilled_qty; });
      d.lines.forEach((l) => {
        let g = cand.find((x) => x.material_id && x.material_id === l.material_id && left[x.grn_line_id] > 0.0001);
        if (g) { const qn = Math.min(Number(l.qty), left[g.grn_line_id]); left[g.grn_line_id] -= qn; start.push({ invoice_line_id: l.id, grn_line_id: g.grn_line_id, qty: qn, amount: l.amount, reason: "" }); }
        else start.push({ invoice_line_id: l.id, grn_line_id: cand.length ? cand[0].grn_line_id : "", qty: 0, amount: l.amount, reason: "" });
      });
    }
    const lineOf = (id) => d.lines.find((l) => String(l.id) === String(id)) || {};
    const gOf = (id) => cand.find((g) => String(g.grn_line_id) === String(id)) || {};
    const diff = (r) => { const l = lineOf(r.invoice_line_id), g = gOf(r.grn_line_id); return r.grn_line_id && !(l.material_id && String(l.material_id) === String(g.material_id)); };
    const check = h("div", { class: "hint" });
    const ed = lineEditor([
      { k: "invoice_line_id", label: "Bill line (as printed)", type: "select", options: lineOpt, w: 260, noBlank: true, rerender: true },
      { k: "grn_line_id", label: "Goods received (GRN line)", type: "select", options: candOpt, w: 300, rerender: true },
      { k: "qty", label: "Quantity of these goods", type: "number", w: 90 },
      { k: "amount", label: "Amount (before VAT)", type: "number", w: 110 },
      { label: "Item", show: (r) => diff(r) ? "different item" : (r.grn_line_id ? "same item" : "") },
      { k: "reason", label: "Reason (different item)", w: 200 }], start, { onChange: (rows) => {
      const per = {};
      rows.forEach((r) => { per[r.invoice_line_id] = (per[r.invoice_line_id] || 0) + Number(r.amount || 0); });
      const msgs = d.lines.filter((l) => per[l.id] != null && Math.abs(per[l.id] - l.amount) > 0.004).map((l) => l.description + ": links " + fmtMoney(per[l.id]) + " of " + fmtMoney(l.amount));
      const diffAmt = rows.filter(diff).reduce((s, r) => s + Number(r.amount || 0), 0);
      check.textContent = (msgs.length ? "Each linked bill line must be linked in full. " + msgs.join("; ") + ". " : "Every linked bill line adds up. ") +
        (diffAmt > 0 ? "Different-item links " + fmtMoney(diffAmt) + (diffAmt > d.approve_over ? " need approval (limit " + fmtMoney(d.approve_over) + ")." : " are within the approval limit.") : "");
    } });
    const body = h("div", {},
      h("p", { class: "hint" }, "Stock and project cost come from the goods received; the bill keeps its printed lines and VAT. Link a line of a different item (for example 'other item' 200 per cum that is really sand price) to the goods with quantity 0 and its amount, and give the reason."),
      ed, check);
    ed.refresh();
    modal("Link bill " + (d.invoice.party_inv_no || "draft") + " to goods received", body, [
      d.maps.length ? { label: "Remove links", act: async () => { await run("mt.map_clear", { invoice_id: iid }, "Links removed"); if (done) done(); } } : null,
      { label: "Save links", cls: "primary", act: async () => {
        const rows = ed.lines().filter((r) => r.invoice_line_id && r.grn_line_id);
        const r = await run("mt.map_save", { invoice_id: iid, rows }, (x) => x.needs_approval ? "Saved; waits for approval (different item " + fmtMoney(x.different_amount) + ")" : "Saved; the bill can be posted");
        if (done) done();
        return r;
      } }]);
  }

  /* ───────── purchase without VAT bill ───────── */
  function novatDialog(d, done) {
    const open = d.grn.filter((g) => g.unbilled_qty > 0.0001);
    const rows = open.map((g) => ({ grn_line_id: g.grn_line_id, grn_no: g.grn_no, material: g.material, unit: g.unit, left: g.unbilled_qty, qty: 0, rate: g.rate, amount: "" }));
    const ed = lineEditor([{ label: "GRN", show: (r) => r.grn_no }, { label: "Item", show: (r) => r.material + " (" + (r.unit || "") + ")" },
      { label: "Not billed", show: (r) => fmtQty(r.left) }, { k: "qty", label: "Quantity with no bill (0 = leave out)", type: "number", w: 90 }, { label: "At GRN rate", show: (r) => fmtMoney(Number(r.qty || 0) * r.rate) },
      { k: "amount", label: "Amount actually paid (if different)", type: "number", w: 120 }], rows, { fixed: true });
    const f = form([{ k: "date", label: "Date", type: "date", default: today() }, { k: "ref", label: "Reference (cash voucher / slip no.)" },
      { k: "reason", label: "Why there is no VAT bill", wide: true, req: true }, { k: "adjust_advance", label: "Set against money already paid without bill", type: "check", default: 1 }], {});
    modal("Purchase without VAT bill · " + d.vendor.name, h("div", {}, h("p", { class: "hint" }, "For goods that arrived and were paid but will never get a VAT bill. BuildCore records a zero-VAT purchase against the goods (no input VAT, left out of the VAT register). It needs approval."), ed, f), [
      { label: "Record", cls: "primary", act: async () => {
        const v = f.values();
        const lines = ed.lines().filter((r) => Number(r.qty || 0) > 0).map((r) => ({ grn_line_id: r.grn_line_id, qty: r.qty, amount: r.amount }));
        await run("mt.novat_create", Object.assign(v, { party_id: d.vendor.id, lines }), (x) => x.status === "posted" ? "Recorded and posted" : "Recorded; waits for approval");
        if (done) done();
      } }]);
  }

  /* ───────── reclassify cost of a posted bill ───────── */
  async function reclassDialog(iid, done) {
    const d = await api("mt.reclass_info", { invoice_id: iid });
    if (!d.movable.length) { toast("This bill has no cost line that can be moved.", "err"); return; }
    const f = form([{ k: "from_account_id", label: "Move from", type: "select", noBlank: true, options: d.movable.map((m) => [m.account_id, m.code + " " + m.name + " (can move " + fmtMoney(m.available) + ")"]) },
      { k: "to_account_id", label: "To", type: "select", noBlank: true, options: d.targets.map((t) => [t.id, t.code + " " + t.name]) },
      { k: "amount", label: "Amount", type: "number" }, { k: "reason", label: "Reason", wide: true, req: true }], {});
    modal("Reclassify cost · bill " + (d.invoice.party_inv_no || d.invoice.no), h("div", {},
      h("p", { class: "hint" }, "For bills posted before matching: moves an amount from one cost account to another with a journal. The bill and its VAT stay as printed; stock is not touched."),
      d.done.length ? table([{ k: "ts", label: "When" }, { k: "from_name", label: "From" }, { k: "to_name", label: "To" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "reason", label: "Reason" }], d.done, { search: false }) : null, f), [
      { label: "Post journal", cls: "primary", act: async () => { await run("mt.reclass", Object.assign(f.values(), { invoice_id: iid }), (x) => "Journal posted (" + fmtMoney(x.amount) + ")"); if (done) done(); } }]);
  }

  /* ───────── bill vs actual ───────── */
  async function billActualTab() {
    const box = h("div", { "data-mt": "actual" });
    let only = true;
    const load = async () => {
      const d = await api("mt.bill_actual", { different: only ? 1 : 0 });
      const nv = await api("mt.novat_list", { from: "0000-01-01" });
      box.innerHTML = "";
      box.append(h("div", { class: "bar" }, h("label", {}, h("input", { type: "checkbox", checked: only, onchange: (e) => { only = e.target.checked; load(); } }), " Only bills that name a different item")));
      box.append(h("p", { class: "hint" }, "What the VAT bill says beside what really came to site. Keep this list for the auditor: a bill that describes goods not supplied is a tax risk. Different-item total: " + M(d.total_different) + "."));
      box.append(table([{ k: "date", label: "Date" }, { label: "Bill", v: (r) => drillTo("invoice", r.invoice_id, r.bill) }, { k: "vendor", label: "Vendor" },
        { k: "printed", label: "Bill says" }, { k: "printed_qty", label: "Bill qty", fmt: "qty" }, { k: "printed_rate", label: "Bill rate", fmt: "money" },
        { k: "amount", label: "Amount", fmt: "money" }, { k: "received", label: "Really received" }, { k: "grn", label: "GRN" },
        { k: "received_qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "grn_rate", label: "GRN rate", fmt: "money" },
        { k: "reason", label: "Reason" }, { k: "approver", label: "Approved by" }, { k: "status", label: "Bill", fmt: "status" }], d.rows, { name: "mt_actual", export: true, totals: ["amount"], empty: "No linked bills yet." }));
      box.append(h("h3", {}, "Purchases without VAT bill"), table([{ k: "date", label: "Date" }, { label: "Bill", v: (r) => drillTo("invoice", r.invoice_id, r.no || "draft") }, { k: "vendor", label: "Vendor" },
        { k: "project", label: "Project" }, { k: "ref", label: "Reference" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "reason", label: "Reason" }, { k: "status", label: "Status", fmt: "status" }],
      nv.rows, { name: "mt_novat", export: true, totals: ["amount"], empty: "None." }));
    };
    await load();
    return box;
  }

  /* ───────── settings ───────── */
  async function settingsTab() {
    const box = h("div", { "data-mt": "settings" });
    const st = await api("mt.settings", {});
    const f = form([{ k: "on", label: "Match site receipts, VAT bills and payments", type: "check" }, { k: "from", label: "List gaps from (date)", type: "date" },
      { k: "approve_over", label: "Different-item links and no-VAT purchases above this amount need approval (0 = always)", type: "number" },
      { k: "self_approve", label: "The person who made it may also approve it", type: "check" }, { k: "old_days", label: "Warn when goods are not billed after (days)", type: "number" }],
    { on: st.on ? 1 : 0, from: st.from, approve_over: st.approve_over, self_approve: st.self_approve ? 1 : 0, old_days: st.old_days });
    box.append(h("div", { class: "panel" }, h("h3", {}, "Match settings"),
      h("p", { class: "hint" }, "Who enters what: store keepers enter goods received (GRN) with the quantity that came; accounts enter each VAT bill exactly as printed, link it to the goods and enter payments; approvers (Procurement approve, e.g. project manager) approve different-item links and purchases without VAT bill. Updated companies start with this off."),
      f, st.can_change ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("mt.settings_save", f.values(), "Saved"); } }, "Save")) : h("p", { class: "muted" }, "Only Accounts approvers can change these.")));
    return box;
  }

  addTabs(ROUTE, "Purchase bills", "Supplier bills against goods received, and how they match what arrived and what was paid.", "Purchase bills",
    [["Match receipts, bills & payments", matchTab], ["Bill vs actual", billActualTab], ["Match settings", settingsTab]]);
  /* what's new */
  const VER = "2.45.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } };
  async function whatsNew() {
    if (LSg("bco_seen_" + VER, "")) return;
    if (!S.user || S.user.role !== "admin") return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_" + VER, "1");
    let isOn = false;
    try { isOn = (await api("mt.settings", {})).on; } catch (e) { isOn = false; }
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:560px" },
      h("p", {}, "Site receipts, VAT bills and payments can now be matched."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "Store enters what came, accounts enters the bill as printed."), " Stock and project cost come from the GRN; VAT comes from the bill."),
        h("li", {}, h("b", {}, "Link a bill to the goods."), " Even when the bill names another item, or splits the sand price into 'sand' and 'other item'. Needs a reason and approval."),
        h("li", {}, h("b", {}, "Purchase without VAT bill."), " For goods paid in cash with no bill; no input VAT, left out of the VAT register."),
        h("li", {}, h("b", {}, "Per vendor:"), " received not billed, bills waiting for goods, paid with no VAT bill yet.")),
      h("p", { class: "hint" }, isOn ? "It is on for this company: Procurement › Purchase bills › Match receipts, bills & payments. Nothing already entered changed." :
        "It is off for your existing company until accounts turns it on: Procurement › Purchase bills › Match settings. Nothing already entered changed.")),
    [{ label: "Open Match settings", cls: "primary", act: () => { location.hash = "#/proc/invoices?tab=3"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user) { clearInterval(seen); setTimeout(whatsNew, 3500); } }, 1000);
})();
