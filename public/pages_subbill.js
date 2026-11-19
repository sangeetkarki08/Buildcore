/* BuildCore 2.58 — Subcontracts and billing: Commercial › Subcontract & billing control, Procurement › Rate contracts. */
(function () {
"use strict";
if (window.__bco258) return; window.__bco258 = true;
const M = (v) => (v == null ? "—" : fmtMoney(v));
const Q = (v) => (v == null ? "—" : String(Math.round(Number(v) * 1000) / 1000));
const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
const projects = () => ((S.L && S.L.projects) || []).filter((p) => !p.kind || p.kind === "project");
let PID = null;
const pidNow = () => PID || S.project || (projects()[0] || {}).id;
const projSel = (onch) => h("select", { onchange: (e) => { PID = Number(e.target.value); onch(); } },
  projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(pidNow()) }, p.code + " · " + p.name)));
const empty = (t) => h("p", { class: "muted" }, t);

/* ═════════════ Commercial › Subcontract & billing control ═════════════ */
PAGES["sb/control"] = async (root, params) => {
  root.append(pageHead("Subcontract & billing control", "What subcontractors are paid against what the client certified, labour contractors from the DPR, final accounts, preparing the IPC, how fast clients pay, retention and advances, and variations."));
  root.append(tabs([["Billed vs certified", certTab], ["Labour contractors (DPR)", labourTab], ["Final accounts", finalTab], ["Prepare IPC", ipcTab],
    ["Client payment days", payTab], ["Retention & advances", ledgerTab], ["Variation tracker", varTab], ["Settings", setTab]], params && params.tab ? Number(params.tab) : 0));
};

async function certTab() {
  const box = h("div");
  const load = async () => {
    const pid = pidNow();
    const d = await api("sb.overview", { project_id: pid });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    const over = d.rows.filter((r) => r.over > 0);
    box.append(summaryStrip([["Work-order lines", String(d.rows.length)], ["Lines paid above client certification", String(over.length)],
      ["Quantity filled from the DPR", d.on ? "On" : "Off (shown only)"], ["Stop approval above certification", d.block ? "On" : "Off"]]));
    if (over.length) box.append(h("div", { class: "sf-banner" }, "On " + over.length + " line(s) subcontractors have been billed more than the client has certified to us for the same BOQ item. Pay them only for what the client accepts, or note why (for example the client's IPC is late)."));
    box.append(table([{ k: "order", label: "Work order" }, { k: "party", label: "Subcontractor" }, { k: "boq", label: "BOQ" }, { k: "item", label: "Item" }, { k: "unit", label: "Unit" },
      { label: "Order qty", v: (r) => Q(r.order_qty) }, { label: "Billed (this order)", v: (r) => Q(r.billed) }, { label: "Billed (all subs, item)", v: (r) => Q(r.all_subs) },
      { label: "Client certified", v: (r) => Q(r.certified) }, { label: "Over", v: (r) => r.over > 0 ? h("b", { class: "neg" }, Q(r.over)) : "" }], d.rows, { name: "sb_over" }));
    // Bills waiting for approval: check + approve with a reason
    const bills = (await api("sco.bills", { project_id: pid }).catch(() => [])) || [];
    const wait = (Array.isArray(bills) ? bills : bills.rows || []).filter((b) => ["submitted", "draft"].includes(b.status));
    box.append(h("h3", {}, "Running bills not yet approved"));
    if (!wait.length) { box.append(empty("None.")); return; }
    box.append(table([{ k: "no", label: "Bill" }, { k: "party", label: "Subcontractor" }, { k: "date", label: "Date" }, { k: "status", label: "Status" }, { k: "gross", label: "Gross", fmt: "money" },
      { label: "", v: (b) => h("button", { class: "btn sm", onclick: () => checkBill(b, load) }, "Check") }], wait, { name: "sb_wait", search: false }));
  };
  await load();
  return box;
}

async function checkBill(b, reload) {
  const d = await api("sb.bill_check", { id: b.id });
  const body = h("div");
  if (!d.rows.length) body.append(h("p", {}, "Nothing on this bill goes above what the client has certified."));
  else body.append(h("p", {}, "These items would take subcontractor billing above the client's certified quantity:"),
    table([{ k: "item", label: "Item" }, { k: "unit", label: "Unit" }, { label: "Subs, to date", v: (r) => Q(r.subs_cumulative) }, { label: "Client certified", v: (r) => Q(r.client_certified) },
      { label: "Measured", v: (r) => Q(r.measured) }, { label: "Over", v: (r) => Q(r.over) }, { k: "amount", label: "Amount over", fmt: "money" }], d.rows, { search: false }));
  const btns = [];
  if (b.status === "submitted" && can("commercial", "approve")) {
    btns.push({ label: d.rows.length ? "Approve with a reason" : "Approve", cls: "primary", act: async () => {
      let reason = null;
      if (d.rows.length && d.block) { reason = await ask("Reason", "Why approve above the client's certification?", { input: "Reason", required: true }); if (reason == null) return false; }
      await run("sco.bill_approve", { id: b.id, override_reason: reason }, "Bill approved.");
      reload();
    } });
  }
  modal("Bill " + (b.no || b.id), body, btns);
}

async function labourTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("sb.labour", { project_id: pidNow() });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    box.append(h("p", { class: "hint" }, "Gang hours of each labour contractor from the approved DPRs (DPR › Labour, with the contractor chosen), against what has been billed on their labour work orders. \"Make the bill\" makes a draft running bill, one amount line per BOQ item, which then goes through submit, approve and post as usual. With no labour work order yet it makes a draft order for approval first."));
    if (!d.rows.length) { box.append(empty("No DPR labour with a contractor on this project.")); return; }
    box.append(summaryStrip([["DPR amount", M(d.rows.reduce((s, r) => s + r.amount, 0))], ["Billed", M(d.rows.reduce((s, r) => s + r.billed, 0))], ["Not billed yet", M(d.rows.reduce((s, r) => s + r.not_billed, 0))]]));
    box.append(table([{ k: "party", label: "Contractor" }, { k: "first", label: "From" }, { k: "last", label: "To" }, { label: "Man-hours", v: (r) => Q(r.hours) },
      { k: "amount", label: "DPR amount", fmt: "money" }, { k: "billed", label: "Billed", fmt: "money" }, { k: "not_billed", label: "Not billed", fmt: "money" },
      { label: "Work order", v: (r) => r.order ? (r.order.no || "#" + r.order.id) + " (" + r.order.status + ")" : "none" },
      { label: "", v: (r) => r.not_billed > 0.5 && can("commercial", "edit") ? h("button", { class: "btn sm", onclick: async () => {
        const x = await run("sb.labour_bill", { project_id: pidNow(), party_id: r.party_id });
        if (x && x.message) toast(x.message);
        load();
      } }, r.order ? "Make the bill" : "Make the work order") : "" }], d.rows, { name: "sb_lab", search: false }));
  };
  await load();
  return box;
}

async function finalTab() {
  const box = h("div");
  const load = async () => {
    const orders = await api("sco.list", { project_id: pidNow() });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    box.append(h("p", { class: "hint" }, "Before releasing retention: work billed, retention held and released, advances and materials still with the subcontractor, end of the defects period, and a checklist. This is a statement; the release is paid as before."));
    const list = orders.filter((o) => o.status !== "draft" && o.status !== "cancelled");
    if (!list.length) { box.append(empty("No approved work orders on this project.")); return; }
    box.append(table([{ k: "no", label: "Work order" }, { k: "party", label: "Subcontractor" }, { k: "type_name", label: "Type" }, { k: "status", label: "Status" },
      { k: "value", label: "Order value", fmt: "money" }, { k: "billed", label: "Billed", fmt: "money" }, { k: "with_sub", label: "Materials with sub", fmt: "money" },
      { label: "", v: (o) => h("button", { class: "btn sm", onclick: () => openFinal(o.id) }, "Final account") }], list, { name: "sb_final" }));
  };
  await load();
  return box;
}

async function openFinal(oid) {
  const d = await api("sb.final", { order_id: oid });
  const o = d.order;
  const ticks = {};
  const body = h("div", {},
    summaryStrip([["Work billed", M(d.work_billed)], ["Retention held", M(d.retention_held)], ["Released", M(d.retention_released)], ["Retention open", M(d.retention_open)],
      ["Advance open", M(d.advance_open)], ["Defects period ends", d.dlp_end || "—"]]),
    d.custody.length ? h("div", {}, h("h4", {}, "Materials still with the subcontractor"), table([{ k: "material", label: "Material" }, { k: "unit", label: "Unit" }, { label: "Qty", v: (r) => Q(r.qty) }, { k: "value", label: "Value", fmt: "money" }], d.custody, { search: false })) : null,
    h("h4", {}, "Bills"), table([{ k: "no", label: "Bill" }, { k: "date", label: "Date" }, { k: "status", label: "Status" }, { k: "gross", label: "Gross", fmt: "money" }, { k: "retention", label: "Retention", fmt: "money" }, { k: "advance_recovery", label: "Advance back", fmt: "money" }, { k: "material_recovery", label: "Materials back", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }], d.bills, { search: false }),
    h("h4", {}, "Release checklist"),
    h("div", {}, d.checks.map((x) => {
      const cb = h("input", { type: "checkbox", checked: x.ticked, disabled: !!x.auto });
      ticks[x.key] = cb;
      return h("label", { class: "f check wide" }, cb, x.label + (x.auto ? " (checked from the books)" : x.auto === false ? " (the books say not yet)" : ""));
    })));
  const note = h("textarea", { placeholder: "Note" }, d.note || "");
  body.append(note, h("p", { class: "hint" }, d.ready ? "Every check is done: retention can be released." : "Not ready to release retention yet."));
  modal("Final account · " + (o.no || "") + " · " + (o.party || ""), body, can("commercial", "edit") ? [{ label: "Save checklist", cls: "primary", act: async () => {
    const checks = {}; Object.entries(ticks).forEach(([k, cb]) => { if (cb.checked && !cb.disabled) checks[k] = 1; });
    await run("sb.final_save", { order_id: oid, checks, note: note.value, status: d.ready ? "ready" : "open" }, "Saved.");
  } }, { label: "Print", act: () => { printFrame("Final account " + (o.no || ""), body.cloneNode(true)); return false; } }] : []);
}

async function ipcTab() {
  const box = h("div");
  const load = async () => {
    const pid = pidNow();
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    let d;
    try { d = await api("sb.ipc_prepare", { project_id: pid }); } catch (e) { box.append(empty(String(e.message || e))); return; }
    box.append(h("p", { class: "hint" }, "The next IPC in one step: verified joint-measurement quantities not yet billed, with retention, VAT, TDS and advance recovery from the project's terms (Cash forecast › Contract terms). Price adjustment is worked out from the formula and shown here; it is claimed as before."));
    if (d.waiting.length) box.append(h("div", { class: "sf-banner" }, "Still open: " + d.waiting.map((w) => (w.no || "draft") + " (" + w.status + ", " + w.date + ")").join(", ") + ". Their quantities are already counted as billed."));
    box.append(summaryStrip([["Client", d.client || "—"], ["Gross this IPC", M(d.gross)], ["VAT " + d.terms.vat_pct + "%", M(d.vat)], ["Retention " + d.terms.retention_pct + "%", M(d.retention)],
      ["TDS " + d.terms.tds_pct + "%", M(d.tds)], ["Advance recovery " + d.terms.advance_recovery_pct + "% (open " + M(d.advance_open) + ")", M(d.advance_recovery)], ["Net to receive", M(d.net)],
      ["Price adjustment (formula)", d.price_adjustment && d.price_adjustment.total != null ? M(d.price_adjustment.total) : "not set"]]));
    if (!d.lines.length) { box.append(empty("No verified measurement quantity beyond what is already billed. Verify the joint measurements first (Commercial › Measurements).")); return; }
    box.append(table([{ k: "code", label: "BOQ" }, { k: "description", label: "Item" }, { k: "unit", label: "Unit" }, { label: "Billed before", v: (r) => Q(r.prev_qty) }, { label: "This IPC", v: (r) => Q(r.qty) },
      { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" }], d.lines, { name: "sb_ipc", totals: ["amount"] }));
    if (can("commercial", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const r = await run("sb.ipc_make", { project_id: pid }, "Draft IPC made. Open IPC billing to check and submit it.");
      if (r) location.hash = "#/p/ipc";
    } }, "Make the draft IPC")));
  };
  await load();
  return box;
}

async function payTab() {
  const d = await api("sb.pay_days", {});
  return h("div", {}, h("p", { class: "hint" }, "How long each client takes to pay a sales invoice (IPC) in full, weighted by amount, and how many were paid later than the project's payment days."),
    d.rows.length ? table([{ k: "client", label: "Client" }, { k: "invoices", label: "Invoices" }, { k: "paid_invoices", label: "Paid in full" }, { label: "Average days to pay", v: (r) => r.avg_days == null ? "—" : String(r.avg_days) },
      { k: "paid_late", label: "Paid late" }, { k: "open", label: "Still to receive", fmt: "money" }, { label: "Oldest open (days)", v: (r) => r.oldest_open_days == null ? "" : String(r.oldest_open_days) }], d.rows, { name: "sb_pay", search: false }) : empty("No posted sales invoices."));
}

async function ledgerTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("sb.ledger", { project_id: pidNow() });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    box.append(h("p", { class: "hint" }, "From the posted vouchers: retention the client holds from us and we hold from subcontractors, advances received and given, with what has come back."));
    box.append(d.rows.length ? table([{ k: "kind", label: "What" }, { k: "party", label: "Party" }, { k: "held", label: "Held / given", fmt: "money" }, { k: "released", label: "Released / recovered", fmt: "money" },
      { k: "open", label: "Open", fmt: "money" }, { k: "first", label: "First" }, { k: "last", label: "Last" }], d.rows, { name: "sb_ledger", search: false }) : empty("No retention or advance on this project."));
  };
  await load();
  return box;
}

async function varTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("sb.variations", { project_id: pidNow() });
    box.replaceChildren(h("div", { class: "bar" }, lbl("Project", projSel(load))));
    box.append(summaryStrip(d.summary.map((s) => [s.stage[0].toUpperCase() + s.stage.slice(1) + " (" + s.count + ")", M(s.value)])));
    box.append(d.rows.length ? table([{ k: "no", label: "No" }, { k: "title", label: "Variation" }, { k: "instruction", label: "Instruction" }, { k: "date", label: "Date" }, { k: "stage", label: "Stage" },
      { k: "value", label: "Value", fmt: "money" }, { label: "Time (days)", v: (r) => r.time_days ? String(r.time_days) : "" }, { k: "billed", label: "Billed", fmt: "money" },
      { label: "Days at this stage", v: (r) => r.stage === "billed" || r.stage === "rejected" ? "" : h("span", { class: r.age_days > 60 ? "neg" : "" }, String(r.age_days)) }], d.rows, { name: "sb_var" })
      : empty("No variations on this project (Commercial › Variations)."));
  };
  await load();
  return box;
}

async function setTab() {
  const d = await api("sb.settings", {});
  const f = form([{ k: "on", label: "Fill the running bill's quantity from the DPR / joint measurement", type: "check", wide: true },
    { k: "block", label: "Stop approval of a subcontract bill that pays above the client's certification, unless a reason is given", type: "check", wide: true }], { on: d.on ? 1 : 0, block: d.block ? 1 : 0 });
  return h("div", {}, h("p", { class: "hint" }, "Both are off on companies that already had entries before 2.58, so nothing changes until accounts turns them on. With the first off, the suggested quantity is still worked out and shown on this page."), f,
    can("accounts", "approve") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => run("sb.settings_save", f.values(), "Saved.") }, "Save")) : null);
}

/* ═════════════ Procurement › Rate contracts ═════════════ */
PAGES["rc/contracts"] = async (root) => {
  root.append(pageHead("Rate contracts", "Agreed rates per supplier and material for a period. A purchase order or GRN line for that supplier left without a rate takes the agreed rate; receipts above it are listed."));
  const box = h("div");
  root.append(box);
  const load = async () => {
    const d = await api("rc.list", {});
    box.replaceChildren();
    if (can("procurement", "approve")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => edit({}) }, "+ Rate contract")));
    box.append(d.rows.length ? table([{ k: "party", label: "Supplier" }, { k: "material", label: "Material" }, { k: "unit", label: "Unit" }, { k: "project", label: "Project", v: (r) => r.project || "All" },
      { k: "rate", label: "Rate", fmt: "money" }, { k: "valid_from", label: "From" }, { k: "valid_to", label: "To" }, { label: "Max qty", v: (r) => r.max_qty ? Q(r.max_qty) : "" },
      { label: "Received", v: (r) => h("span", { class: r.max_qty && r.used_qty > r.max_qty ? "neg" : "" }, Q(r.used_qty)) }, { k: "ref", label: "Ref" },
      { label: "Status", v: (r) => r.current ? "In force" : r.active ? "Not in period" : "Stopped" },
      { label: "", v: (r) => can("procurement", "approve") ? h("button", { class: "btn sm", onclick: () => edit(r) }, "Edit") : "" }], d.rows, { name: "rc_list" }) : empty("No rate contracts yet."));
    box.append(h("h3", {}, "Receipts above the agreed rate"));
    box.append(d.above.length ? table([{ k: "no", label: "GRN" }, { k: "date", label: "Date" }, { k: "party", label: "Supplier" }, { k: "material", label: "Material" }, { label: "Qty", v: (r) => Q(r.qty) },
      { k: "rate", label: "Rate paid", fmt: "money" }, { k: "agreed", label: "Agreed", fmt: "money" }, { k: "extra", label: "Extra", fmt: "money" }], d.above, { name: "rc_above", totals: ["extra"] }) : empty("None."));
  };
  const edit = (r) => {
    const f = form([{ k: "party_id", label: "Supplier", type: "select", options: () => opt.parties(["vendor"]), req: true },
      { k: "material_id", label: "Material", type: "select", options: opt.materials, req: true },
      { k: "project_id", label: "Project", type: "select", options: opt.projects, blank: "All projects" },
      { k: "rate", label: "Rate (without VAT)", type: "number", req: true }, { k: "valid_from", label: "Valid from", type: "date" }, { k: "valid_to", label: "Valid to", type: "date" },
      { k: "max_qty", label: "Maximum quantity", type: "number" }, { k: "ref", label: "Agreement ref" }, { k: "note", label: "Note", wide: true },
      { k: "active", label: "In use", type: "check" }], Object.assign({ active: 1 }, r));
    modal(r.id ? "Rate contract" : "New rate contract", f, [{ label: "Save", cls: "primary", act: async () => { await run("rc.save", Object.assign({ id: r.id }, f.values()), "Saved."); load(); } }]);
  };
  await load();
};
})();
