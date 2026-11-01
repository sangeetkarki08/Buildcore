/* Generic document editor, master data pages and inventory module */
"use strict";

/* what the stock ledger calls a document, and which screen opens it */
const DOC_KIND = { GRN: "grn", MIN: "issue", MRT: "return", "MTN-IN": "transfer", "MTN-OUT": "transfer",
                   MTN: "transfer", PSV: "count", OPENING: null, grn: "grn", issue: "issue", return: "return",
                   transfer: "transfer", count: "count" };
const MODULE_OF = { mrq: "inventory", grn: "inventory", issue: "inventory", return: "inventory", transfer: "inventory", count: "inventory", pr: "procurement", po: "procurement", invoice: "procurement" };
const TYPE_NAME = { mrq: "Material requisition", grn: "Goods received note", issue: "Material issue", return: "Material return", transfer: "Stock transfer", count: "Physical stock count", pr: "Purchase request", po: "Purchase order", invoice: "Invoice" };

/* Open any document from anywhere: a number printed in a report is a way in. */
async function docOpen(type, id) {
  const cfg = DOC_CFG[type];
  if (!cfg) return toast("That document cannot be opened from here.", "err");
  await openDoc(cfg, id);
}

async function openDoc(cfg, id) {
  const d = await run("doc.get", { type: cfg.type, id });
  docEditor(cfg, d);
}

function docEditor(cfg, doc) {
  const isNew = !doc;
  doc = doc || Object.assign({ status: "draft", lines: [], date: today() }, cfg.defaults ? cfg.defaults() : {});
  const module = cfg.module || MODULE_OF[cfg.type];
  const editable = doc.status === "draft" && can(module, "edit");
  const ctx = { doc, cfg, avail: {} };
  const title = (cfg.name || TYPE_NAME[cfg.type]) + " " + (doc.no || (isNew ? "(new)" : "draft #" + doc.id));
  const hdrFields = cfg.header(doc, ctx).map((f) => Object.assign({}, f, { readonly: f.readonly || !editable }));
  const hf = form(hdrFields, doc, async () => { if (cfg.onHeader) await cfg.onHeader(ctx); });
  ctx.hf = hf;
  const le = lineEditor(cfg.lines(doc, ctx), doc.lines, { readonly: !editable || cfg.fixedLines, blank: cfg.blank ? cfg.blank(ctx) : {}, onChange: () => ctx.onLines && ctx.onLines() });
  ctx.le = le;
  const extra = h("div", { style: "margin-top:12px" });
  ctx.extra = extra;
  ctx.header = () => Object.assign({}, cfg.fixed ? cfg.fixed(doc) : {}, hf.values(), { id: doc.id });
  ctx.save = async (quiet) => {
    const d = await run("doc.save", { type: cfg.type, header: ctx.header(), lines: le.lines() }, quiet ? null : "Draft saved");
    doc.id = d.id;
    ctx.doc = d;
    return d;
  };
  let m;
  ctx.reopen = async (id) => { m.close(); if (cfg.refresh) cfg.refresh(); if (id || doc.id) openDoc(cfg, id || doc.id); };
  ctx.act = (label, fn, o) => ({
    label, cls: (o || {}).cls, act: async () => {
      if (o && o.confirm) { const r = await ask(label, o.confirm, { input: o.reason, required: o.reasonRequired, danger: o.danger }); if (r === null) return false; ctx.reason = r; }
      if (editable && !(o && o.noSave)) await ctx.save(true);
      await fn(ctx);
      await ctx.reopen();
    },
  });
  const buttons = [];
  if (editable) {
    buttons.push({ label: "Save draft", act: async () => { await ctx.save(); await ctx.reopen(); } });
    if (doc.id) buttons.push({ label: "Delete draft", cls: "warn", act: async () => { if (!(await ask("Delete draft", "Delete this draft permanently?", { danger: true, ok: "Delete" }))) return false; await run("doc.delete", { type: cfg.type, id: doc.id }, "Draft deleted"); if (cfg.refresh) cfg.refresh(); } });
  }
  (cfg.actions ? cfg.actions(ctx) : []).forEach((b) => b && buttons.push(b));
  const body = h("div", {}, cfg.intro ? cfg.intro(ctx) : null, hf, h("h4", { style: "margin:16px 0 6px" }, "Lines"), le, extra);
  m = modal(title, body, buttons, { head: stamp(doc.status) });
  ctx.modal = m;
  if (cfg.after) cfg.after(ctx);
  if (ctx.onLines) ctx.onLines();
}

const DOC_CFG = {};           // every document type, so any reference to one can open it
function docListPage(cfg) {
  if (!DOC_CFG[cfg.type]) DOC_CFG[cfg.type] = cfg;
  return async (root) => {
    if (cfg.needsProject !== false && !S.project) return root.append(pageHead(cfg.title, cfg.sub), projectNotice());
    const statuses = cfg.statuses || ["draft", "submitted", "approved", "posted", "cancelled"];
    let filt = { status: "" };
    const holder = h("div");
    const load = async () => {
      const rows = await run("doc.list", Object.assign({ type: cfg.type, project_id: S.project || null }, cfg.listArgs || {}, filt));
      holder.innerHTML = "";
      holder.append(table(cfg.cols, rows, { name: cfg.type, onRow: (r) => openDoc(cfgR, r.id), empty: cfg.empty }));
    };
    const cfgR = Object.assign({}, cfg, { refresh: load });
    const right = [];
    if (cfg.newButton !== false && can(cfg.module || MODULE_OF[cfg.type], "edit")) right.push(h("button", { class: "btn primary", onclick: () => docEditor(cfgR, null) }, cfg.newLabel || "New"));
    (cfg.tools || []).forEach((t) => right.push(t(cfgR, load)));
    root.append(pageHead(cfg.title, cfg.sub, ...right));
    root.append(filterBar([{ k: "status", label: "Status", type: "select", options: statuses.map((s) => [s, s.replace(/_/g, " ")]), blank: "All" }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
    if (PAGES._pending) { const p = PAGES._pending; PAGES._pending = null; p(cfgR); }
  };
}

/* ── master data (generic) ── */
const MASTERS_UI = {};        // every master form, reachable from any picker in the app
function masterPage(o) {
  MASTERS_UI[o.table] = o;
  return async (root) => {
    const holder = h("div");
    const load = async () => {
      const args = { table: o.table };
      if (o.byProject) { if (!S.project) { holder.innerHTML = ""; holder.append(projectNotice()); return; } args.project_id = S.project; }
      const rows = await run("master.list", args);
      holder.innerHTML = "";
      holder.append(table(o.cols, rows, { name: o.table, onRow: (r) => edit(r), rowClass: o.rowClass }));
    };
    const edit = (row) => {
      const editable = can(o.module || "masters", "edit");
      const fields = (typeof o.fields === "function" ? o.fields(row) : o.fields).map((f) => Object.assign({}, f, { readonly: f.readonly || !editable || (row && f.lockAfter) }));
      const f = form(fields, row || Object.assign({ active: 1 }, o.defaults ? o.defaults() : {}));
      const btns = editable ? [{ label: "Save", cls: "primary", act: async () => {
        const v = f.values();
        if (o.byProject) v.project_id = row ? row.project_id : S.project;
        if (row) v.id = row.id;
        await run("master.save", { table: o.table, row: v }, "Saved");
        await reloadLookups(); load();
      } }] : [];
      if (row && editable) btns.push({ label: "Delete", cls: "warn", act: async () => {
        if (!(await ask("Delete", "Delete this record?", { danger: true, ok: "Delete" }))) return false;
        await run("master.delete", { table: o.table, id: row.id }, "Deleted"); await reloadLookups(); load();
      } });
      (o.extraButtons ? o.extraButtons(row) : []).forEach((b) => btns.push(b));
      modal((row ? "Edit " : "New ") + o.single, h("div", {}, f, o.extra ? o.extra(row) : null), btns, { narrow: !o.wide });
    };
    const right = [];
    if (can(o.module || "masters", "edit")) right.push(h("button", { class: "btn primary", onclick: () => { if (o.byProject && !S.project) return toast("Select a project first.", "err"); edit(null); } }, "New " + o.single));
    if (o.importer && can(o.module || "masters", "edit")) right.push(h("button", { class: "btn", onclick: () => pasteImport(o, load) }, "Paste from Excel"));
    root.append(pageHead(o.title, o.sub, ...right), holder);
    await load();
  };
}

function pasteImport(o, load) {
  const cols = o.importer;
  const ta = h("textarea", { style: "min-height:220px;font-family:monospace", placeholder: cols.join("\t") });
  modal("Paste " + o.title.toLowerCase(), h("div", {},
    h("p", {}, "Copy rows from Excel with these columns in this order, then paste below. A header row is skipped automatically."),
    h("p", { class: "hint" }, cols.join("  |  ")), ta), [{ label: "Import", cls: "primary", act: async () => {
    const rows = ta.value.split(/\r?\n/).map((l) => l.split("\t")).filter((r) => r.join("").trim());
    let ok = 0; const errs = [];
    for (const [i, r] of rows.entries()) {
      if (i === 0 && r[0].toLowerCase() === cols[0]) continue;
      const row = {}; cols.forEach((c, j) => { row[c] = (r[j] || "").trim(); });
      if (o.byProject) row.project_id = S.project;
      if (o.defaults) Object.entries(o.defaults()).forEach(([k, v]) => { if (row[k] === undefined || row[k] === "") row[k] = v; });
      try { await api("master.save", { table: o.table, row }); ok++; } catch (e) { errs.push("Row " + (i + 1) + ": " + e.message); }
    }
    toast(ok + " rows imported" + (errs.length ? ", " + errs.length + " failed" : ""), errs.length ? "err" : "ok");
    if (errs.length) modal("Rows not imported", h("pre", {}, errs.join("\n")), [], { narrow: true });
    await reloadLookups(); load();
  } }]);
}

const KIND_OPTS = [["vendor", "Vendor / supplier"], ["subcontractor", "Subcontractor"], ["client", "Client"]];
PAGES["m/projects"] = masterPage({ table: "projects", title: "Projects", single: "project", sub: "Each project gets a main store and an in-transit store automatically.",
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "client", label: "Client" }, { k: "location", label: "Location" }, { k: "contract_value", label: "Contract value", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
  fields: [{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true }, { k: "client", label: "Client" }, { k: "location", label: "Location" }, { k: "contract_value", label: "Contract value", type: "number" }, { k: "start_date", label: "Start date", type: "date" }, { k: "end_date", label: "End date", type: "date" }, { k: "status", label: "Status", type: "select", options: [["active", "Active"], ["closed", "Closed"]], noBlank: true }] });
PAGES["m/materials"] = masterPage({ table: "materials", title: "Materials", single: "material", importer: ["code", "name", "category", "unit", "reorder_level", "reorder_qty", "standard_rate"],
  sub: "Use a category containing 'Fuel' for diesel and lubricants and 'Spare' for spare parts; they post to their own stock and cost accounts.",
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "category", label: "Category" }, { k: "unit", label: "Unit" }, { k: "reorder_level", label: "Reorder at", fmt: "qty" }, { k: "reorder_qty", label: "Reorder qty", fmt: "qty" }, { k: "standard_rate", label: "Std rate", fmt: "money" }, { k: "active", label: "Active", fmt: "yes" }],
  fields: [{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true }, { k: "local_name", label: "Local name" }, { k: "category", label: "Category", ph: "Cement, Steel, Fuel, Spares…" }, { k: "unit", label: "Unit", req: true }, { k: "spec", label: "Specification", wide: true }, { k: "min_level", label: "Minimum level", type: "number" }, { k: "reorder_level", label: "Reorder level", type: "number" }, { k: "reorder_qty", label: "Reorder quantity", type: "number" }, { k: "lead_days", label: "Lead time (days)", type: "number" }, { k: "standard_rate", label: "Standard rate", type: "number" }, { k: "batch_tracked", label: "Track batch / heat no.", type: "check" }, { k: "active", label: "Active", type: "check" }] });
PAGES["m/parties"] = masterPage({ table: "parties", title: "Vendors, subcontractors & clients", single: "party", importer: ["code", "name", "kind", "pan", "phone", "address"],
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "kind", label: "Type" }, { k: "pan", label: "PAN" }, { k: "phone", label: "Phone" }, { k: "credit_days", label: "Credit days" }, { k: "blacklisted", label: "Blacklisted", fmt: "yes" }, { k: "active", label: "Active", fmt: "yes" }],
  rowClass: (r) => (r.blacklisted ? "bad" : ""), defaults: () => ({ kind: "vendor", credit_days: 30 }),
  fields: [{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true }, { k: "kind", label: "Type", type: "select", options: KIND_OPTS, noBlank: true }, { k: "pan", label: "PAN / VAT no." }, { k: "vat_registered", label: "VAT registered", type: "check" }, { k: "phone", label: "Phone" }, { k: "email", label: "Email" }, { k: "address", label: "Address", wide: true }, { k: "bank", label: "Bank" }, { k: "bank_acno", label: "Bank account no." }, { k: "credit_days", label: "Credit days", type: "number" }, { k: "categories", label: "Supplies (categories)" }, { k: "notes", label: "Notes", type: "textarea", wide: true }, { k: "blacklisted", label: "Blacklisted", type: "check" }, { k: "active", label: "Active", type: "check" }] });
PAGES["m/stores"] = masterPage({ table: "stores", title: "Stores & locations", single: "store", module: "inventory", byProject: true, sub: "Sub-stores and site locations of the selected project.",
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "type", label: "Type" }, { k: "keeper", label: "Storekeeper" }, { k: "active", label: "Active", fmt: "yes" }],
  fields: (r) => [{ k: "code", label: "Code" }, { k: "name", label: "Name", req: true }, { k: "type", label: "Type", type: "select", noBlank: true, readonly: r && ["main", "transit"].includes(r.type), options: r && ["main", "transit"].includes(r.type) ? [[r.type, r.type]] : [["sub", "Sub-store"], ["location", "Site location"]] }, { k: "keeper", label: "Storekeeper" }, { k: "active", label: "Active", type: "check" }] });
PAGES["m/boq"] = masterPage({ table: "boq_items", title: "BOQ items & material norms", single: "BOQ item", byProject: true, wide: true, importer: ["code", "description", "unit", "qty", "rate"],
  sub: "Executed quantity rises automatically when a client invoice line names the BOQ item. Add material norms to get the consumption reconciliation.",
  cols: [{ k: "code", label: "Code" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" }, { k: "qty", label: "BOQ qty", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money", v: (r) => r.qty * r.rate }, { k: "executed_qty", label: "Executed", fmt: "qty" }],
  fields: [{ k: "code", label: "Code", req: true }, { k: "description", label: "Description", req: true, wide: true }, { k: "unit", label: "Unit" }, { k: "qty", label: "Quantity", type: "number" }, { k: "rate", label: "Rate", type: "number" }, { k: "executed_qty", label: "Executed quantity", type: "number" }],
  extra: (row) => {
    if (!row) return h("p", { class: "hint" }, "Save the item first, then add material norms.");
    const box = h("div", { style: "margin-top:14px" });
    const load = async () => {
      const rows = await api("master.list", { table: "material_coefficients", boq_item_id: row.id });
      box.innerHTML = "";
      box.append(h("h4", {}, "Material norms per " + (row.unit || "unit")));
      box.append(table([{ label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "qty_per_unit", label: "Qty / unit", fmt: "qty" }, { k: "wastage_pct", label: "Wastage %", fmt: "qty" },
        { label: "", v: (r) => can("masters", "edit") ? h("button", { class: "btn small warn", onclick: async () => { await run("master.delete", { table: "material_coefficients", id: r.id }); load(); } }, "Remove") : "" }], rows, { search: false, export: false, empty: "No norms yet." }));
      if (can("masters", "edit")) {
        const f = form([{ k: "material_id", label: "Material", type: "select", options: opt.materials }, { k: "qty_per_unit", label: "Qty per unit", type: "number" }, { k: "wastage_pct", label: "Wastage %", type: "number" }]);
        box.append(h("div", { class: "panel", style: "margin-top:8px" }, f, h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("master.save", { table: "material_coefficients", row: Object.assign(f.values(), { boq_item_id: row.id }) }, "Norm added"); load(); } }, "Add norm"))));
      }
    };
    load();
    return box;
  } });
PAGES["m/staff"] = masterPage({ table: "staff", title: "Staff", single: "staff member", importer: ["code", "name", "designation", "phone", "daily_rate", "monthly_rate"],
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "designation", label: "Designation" }, { k: "phone", label: "Phone" }, { k: "project_id", label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "active", label: "Active", fmt: "yes" }],
  fields: [{ k: "code", label: "Code" }, { k: "name", label: "Name", req: true }, { k: "designation", label: "Designation" }, { k: "phone", label: "Phone" }, { k: "daily_rate", label: "Daily rate", type: "number" }, { k: "monthly_rate", label: "Monthly rate", type: "number" }, { k: "project_id", label: "Project", type: "select", options: opt.projects }, { k: "active", label: "Active", type: "check" }] });

/* ── inventory helpers ── */
async function loadAvail(ctx, storeId) {
  const pid = ctx.hf.values().project_id || ctx.cfg.fixed(ctx.doc).project_id || ctx.cfg.fixed(ctx.doc).from_project;
  ctx.avail = storeId ? await api("stock.available", { project_id: pid, store_id: storeId }) : {};
  ctx.le.refresh();
}
const availCol = (ctx, key) => ({ label: "In store", num: true, show: (r) => { const a = ctx.avail[r.material_id]; return r.material_id ? fmtQty(a ? a.qty : 0) + " " + nm.unit(r.material_id) : ""; } });
const unitCol = { label: "Unit", show: (r) => nm.unit(r.material_id) };
const projFixed = (d) => ({ project_id: d.project_id || S.project });
const TARGETS = [["boq", "BOQ item"], ["equipment", "Equipment"], ["overhead", "Site overhead"]];

const MRQ = {
  type: "mrq", title: "Material requisitions", sub: "Site requests material from the store. Approved requisitions are issued from stock or turned into a purchase request.",
  statuses: ["draft", "submitted", "approved", "partially_issued", "issued", "rejected", "closed"],
  cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "requested_by", label: "Requested by" }, { label: "Store", v: (r) => nm.store(r.store_id) }, { k: "auto", label: "Auto", fmt: "yes" }, { k: "status", label: "Status", fmt: "status" }],
  fixed: projFixed,
  defaults: () => ({ store_id: (S.L.stores.find((s) => String(s.project_id) === String(S.project) && s.type === "main") || {}).id }),
  header: (d) => [{ k: "date", label: "Date", type: "date", req: true }, { k: "store_id", label: "From store", type: "select", options: () => opt.stores(d.project_id || S.project) }, { k: "requested_by", label: "Requested by", req: true }, { k: "remarks", label: "Purpose / remarks", wide: true }],
  lines: (d, ctx) => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 240 }, availCol(ctx), { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "approved_qty", label: "Approved", readonly: true, type: "number" }, { k: "issued_qty", label: "Issued", readonly: true, type: "number" }, { k: "boq_item_id", label: "For BOQ item", type: "select", options: () => opt.boq(d.project_id || S.project), w: 200 }, { k: "remarks", label: "Remarks" }],
  onHeader: (ctx) => loadAvail(ctx, ctx.hf.values().store_id),
  after: (ctx) => loadAvail(ctx, ctx.doc.store_id),
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("inventory", "edit")) b.push(ctx.act("Submit for approval", (c) => run("mrq.submit", { id: c.doc.id }, "Submitted"), { cls: "primary" }));
    if (d.status === "submitted" && can("inventory", "approve")) {
      b.push({ label: "Approve", cls: "primary", act: async () => {
        const le = lineEditor([{ k: "material_id", label: "Material", type: "select", options: opt.materials, readonly: true }, { k: "qty", label: "Requested", readonly: true, type: "number" }, { k: "approved_qty", label: "Approve qty", type: "number" }], d.lines.map((l) => Object.assign({}, l, { approved_qty: l.qty })), { fixed: true });
        modal("Approve " + d.no, le, [{ label: "Approve", cls: "primary", act: async () => {
          const ap = {}; le.lines().forEach((l) => { ap[l.id] = l.approved_qty; });
          await run("mrq.approve", { id: d.id, approved: ap }, "Approved"); ctx.reopen();
        } }], { narrow: true });
        return false;
      } });
      b.push(ctx.act("Reject", (c) => run("mrq.reject", { id: d.id, reason: c.reason }, "Rejected"), { confirm: "Reject this requisition?", reason: "Reason", reasonRequired: true, danger: true }));
    }
    if (["approved", "partially_issued"].includes(d.status)) {
      if (can("inventory", "edit")) b.push({ label: "Issue from store", cls: "primary", act: async () => { const p = await run("issue.from_mrq", { mrq_id: d.id }); ctx.modal.close(); docEditor(ISSUE, Object.assign({ status: "draft", date: today() }, p.header, { lines: p.lines })); } });
      if (can("procurement", "edit")) b.push(ctx.act("Raise purchase request for shortfall", (c) => run("mrq.to_pr", { id: d.id }, (r) => "Created " + r.no)));
      if (can("inventory", "edit")) b.push(ctx.act("Close", (c) => run("mrq.close", { id: d.id }, "Closed"), { confirm: "Close this requisition? Nothing more will be issued against it." }));
    }
    return b;
  },
  tools: [(cfg, load) => can("inventory", "edit") ? h("button", { class: "btn", onclick: async () => { const r = await run("stock.reorder_run", {}); toast(r.created.length ? "Created " + r.created.join(", ") : "All items are above reorder level.", "ok"); load(); } }, "Run reorder check") : null],
};
PAGES["inv/mrq"] = docListPage(MRQ);

const GRN = {
  type: "grn", title: "Goods received (GRN)", sub: "Receive material into a store. Stock and the GRN clearing account update only when you post.",
  statuses: ["draft", "posted", "cancelled"],
  cols: [{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" }, { label: "Vendor", v: (r) => nm.party(r.vendor_id) }, { label: "Store", v: (r) => nm.store(r.store_id) }, { k: "challan_no", label: "Challan" }, { k: "status", label: "Status", fmt: "status" }],
  fixed: projFixed,
  defaults: () => ({ store_id: (S.L.stores.find((s) => String(s.project_id) === String(S.project) && s.type === "main") || {}).id }),
  header: (d, ctx) => [{ k: "date", label: "Receipt date", type: "date", req: true }, { k: "store_id", label: "Into store", type: "select", options: () => opt.stores(d.project_id || S.project), req: true }, { k: "vendor_id", label: "Vendor", type: "select", options: () => opt.parties(["vendor", "subcontractor"]), req: true }, { k: "po_id", label: "Against PO", type: "select", options: () => ctx.pos || (d.po_id ? [[d.po_id, "PO #" + d.po_id]] : []), blank: "No PO (direct)" }, { k: "challan_no", label: "Challan / delivery note" }, { k: "vehicle_no", label: "Vehicle no." }, { k: "freight", label: "Freight & unloading", type: "number" }, { k: "remarks", label: "Remarks", wide: true }],
  lines: (d, ctx) => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 230 }, unitCol, { k: "received_qty", label: "Received", type: "number", w: 80 }, { k: "accepted_qty", label: "Accepted", type: "number", w: 80 }, { k: "rate", label: "Rate", type: "number", w: 90 }, { label: "Value", num: true, show: (r) => fmtMoney((r.accepted_qty === "" || r.accepted_qty == null ? r.received_qty : r.accepted_qty) * r.rate) }, { k: "landed_rate", label: "Landed rate", readonly: true, type: "number" }, { k: "batch_no", label: "Batch / heat no." }, { k: "remarks", label: "Remarks" }],
  after: async (ctx) => {
    if (ctx.doc.status !== "draft") return;
    const pos = await api("doc.list", { type: "po", project_id: S.project });
    ctx.pos = pos.filter((p) => ["approved", "partially_received"].includes(p.status)).map((p) => [p.id, p.no + " — " + nm.party(p.vendor_id)]);
    const sel = ctx.hf.querySelector('[name="po_id"]');
    const cur = sel.value;
    sel.innerHTML = "";
    sel.append(h("option", { value: "" }, "No PO (direct)"), ctx.pos.map(([v, l]) => h("option", { value: v, selected: String(v) === String(cur) }, l)));
    ctx.extra.append(h("button", { class: "btn", onclick: async () => {
      const po = ctx.hf.values().po_id; if (!po) return toast("Choose a PO first.", "err");
      const p = await run("grn.from_po", { po_id: po });
      Object.entries(p.header).forEach(([k, v]) => { if (v != null) ctx.hf.set(k, v); });
      ctx.le.setLines(p.lines);
    } }, "Load pending PO lines"), h("span", { class: "hint" }, "  With a PO, the PO rate is used and over-receipt beyond the tolerance is blocked. Freight is spread over accepted value."));
  },
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("inventory", "edit")) b.push(ctx.act("Post GRN", (c) => run("grn.post", { id: c.doc.id }, (r) => "Posted " + r.no), { cls: "primary", confirm: "Post this GRN? Stock and accounts will be updated." }));
    if (d.status === "posted") {
      b.push({ label: "Print", act: () => { printDoc("Goods Received Note " + d.no, [["Date", d.date], ["Vendor", nm.party(d.vendor_id)], ["Store", nm.store(d.store_id)], ["Project", nm.project(d.project_id)], ["Challan", d.challan_no], ["Vehicle", d.vehicle_no]], [{ label: "Material", v: (r) => nm.mat(r.material_id) }, { label: "Unit", v: (r) => nm.unit(r.material_id) }, { k: "received_qty", label: "Received", fmt: "qty" }, { k: "accepted_qty", label: "Accepted", fmt: "qty" }, { k: "rejected_qty", label: "Rejected", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { label: "Value", fmt: "money", v: (r) => r.accepted_qty * r.landed_rate }], d.lines, [["Freight", fmtMoney(d.freight)]], d.remarks); return false; } });
      if (can("inventory", "approve")) b.push(ctx.act("Cancel GRN", (c) => run("grn.cancel", { id: d.id, reason: c.reason }, "Cancelled"), { confirm: "Cancel this GRN? Stock is taken back out and the voucher is reversed.", reason: "Reason", reasonRequired: true, danger: true }));
    }
    return b;
  },
};
PAGES["inv/grn"] = docListPage(GRN);

const ISSUE = {
  type: "issue", title: "Material issues", sub: "Issue from a store to a BOQ item, a machine or site overhead. Cost is taken at the store's weighted average rate.",
  statuses: ["draft", "posted", "cancelled"],
  cols: [{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" }, { k: "issued_to", label: "Issued to" }, { label: "Store", v: (r) => nm.store(r.store_id) }, { k: "status", label: "Status", fmt: "status" }],
  fixed: (d) => ({ project_id: d.project_id || S.project, mrq_id: d.mrq_id, wo_id: d.wo_id }),
  defaults: () => ({ store_id: (S.L.stores.find((s) => String(s.project_id) === String(S.project) && s.type === "main") || {}).id }),
  header: (d) => [{ k: "date", label: "Issue date", type: "date", req: true }, { k: "store_id", label: "From store", type: "select", options: () => opt.stores(d.project_id || S.project), req: true }, { k: "issued_to", label: "Issued to (person)", req: true }, { k: "remarks", label: "Remarks", wide: true }],
  blank: () => ({ target: "boq" }),
  lines: (d, ctx) => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 230 }, availCol(ctx), { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "target", label: "Charge to", type: "select", options: TARGETS, noBlank: true, rerender: true }, { k: "boq_item_id", label: "BOQ item", type: "select", options: (r) => r.target === "boq" ? opt.boq(d.project_id || S.project) : [], w: 190 }, { k: "equipment_id", label: "Equipment", type: "select", options: (r) => r.target === "equipment" ? opt.equipment() : [], w: 160 }, { k: "rate", label: "Rate", readonly: true, type: "number" }, { k: "amount", label: "Amount", readonly: true, type: "number" }],
  onHeader: (ctx) => loadAvail(ctx, ctx.hf.values().store_id),
  after: (ctx) => {
    loadAvail(ctx, ctx.doc.store_id);
    ctx.onLines = () => {
      const short = ctx.le.lines().filter((l) => l.material_id && Number(l.qty) > ((ctx.avail[l.material_id] || {}).qty || 0));
      ctx.extra.innerHTML = "";
      if (short.length && ctx.doc.status === "draft") ctx.extra.append(h("p", { class: "red" }, "Not enough stock for: " + short.map((l) => nm.mat(l.material_id)).join(", ")));
    };
  },
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("inventory", "edit")) b.push(ctx.act("Post issue", (c) => run("issue.post", { id: c.doc.id }, (r) => "Posted " + r.no), { cls: "primary" }));
    if (d.status === "posted") {
      b.push({ label: "Print", act: () => { printDoc("Material Issue Note " + d.no, [["Date", d.date], ["Issued to", d.issued_to], ["Store", nm.store(d.store_id)], ["Project", nm.project(d.project_id)]], [{ label: "Material", v: (r) => nm.mat(r.material_id) }, { label: "Unit", v: (r) => nm.unit(r.material_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { label: "Charged to", v: (r) => r.target === "boq" ? nm.boq(r.boq_item_id) : r.target === "equipment" ? nm.eq(r.equipment_id) : "Overhead" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" }], d.lines, [], d.remarks); return false; } });
      if (can("inventory", "approve")) b.push(ctx.act("Cancel issue", (c) => run("issue.cancel", { id: d.id, reason: c.reason }, "Cancelled"), { confirm: "Cancel this issue? Material goes back into the store.", reason: "Reason", reasonRequired: true, danger: true }));
    }
    return b;
  },
};
PAGES["inv/issue"] = docListPage(ISSUE);

const RETURN = {
  type: "return", title: "Material returns", sub: "Unused material coming back to the store. Link it to the original issue to reverse cost at the same rate. Damaged items are recorded but not added to stock.",
  statuses: ["draft", "posted", "cancelled"],
  cols: [{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" }, { k: "returned_by", label: "Returned by" }, { label: "Store", v: (r) => nm.store(r.store_id) }, { k: "status", label: "Status", fmt: "status" }],
  fixed: projFixed,
  defaults: () => ({ store_id: (S.L.stores.find((s) => String(s.project_id) === String(S.project) && s.type === "main") || {}).id }),
  header: (d) => [{ k: "date", label: "Date", type: "date", req: true }, { k: "store_id", label: "Into store", type: "select", options: () => opt.stores(d.project_id || S.project), req: true }, { k: "returned_by", label: "Returned by" }, { k: "remarks", label: "Remarks", wide: true }],
  blank: () => ({ condition: "usable" }),
  lines: (d, ctx) => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 220, rerender: true }, { k: "issue_line_id", label: "From issue", type: "select", w: 200, options: (r) => (ctx.returnable || []).filter((x) => String(x.material_id) === String(r.material_id) || String(x.id) === String(r.issue_line_id)).map((x) => [x.id, x.no + " (" + fmtQty(x.open_qty) + " open)"]) }, { k: "qty", label: "Qty", type: "number", w: 80 }, { k: "condition", label: "Condition", type: "select", noBlank: true, options: [["usable", "Usable"], ["repairable", "Repairable"], ["damaged", "Damaged"], ["write_off", "Write-off"]] }, { k: "rate", label: "Rate", readonly: true, type: "number" }],
  after: async (ctx) => { if (ctx.doc.status === "draft") { ctx.returnable = await api("issue.returnable", { project_id: ctx.doc.project_id || S.project }); ctx.le.rebuild(); } },
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("inventory", "edit")) b.push(ctx.act("Post return", (c) => run("return.post", { id: c.doc.id }, (r) => "Posted " + r.no), { cls: "primary" }));
    if (d.status === "posted" && can("inventory", "approve")) b.push(ctx.act("Cancel return", (c) => run("return.cancel", { id: d.id }, "Cancelled"), { confirm: "Cancel this return?", danger: true }));
    return b;
  },
};
PAGES["inv/return"] = docListPage(RETURN);

const TRANSFER = {
  type: "transfer", title: "Stock transfers", sub: "Dispatch moves stock into 'In transit'; the receiving store confirms what arrived. Shortages are written off to inventory loss. Transfers between projects move the value between projects.",
  statuses: ["draft", "in_transit", "received", "cancelled"],
  cols: [{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Dispatched" }, { label: "From", v: (r) => nm.pcode(r.from_project) + " / " + nm.store(r.from_store) }, { label: "To", v: (r) => nm.pcode(r.to_project) + " / " + nm.store(r.to_store) }, { k: "received_date", label: "Received" }, { k: "status", label: "Status", fmt: "status" }],
  fixed: (d) => ({ from_project: d.from_project || S.project }),
  defaults: () => ({ from_project: S.project, to_project: S.project }),
  header: (d, ctx) => [{ k: "date", label: "Dispatch date", type: "date", req: true }, { k: "from_store", label: "From store", type: "select", options: () => opt.stores(d.from_project || S.project), req: true }, { k: "to_project", label: "To project", type: "select", options: opt.projects, req: true, noBlank: true }, { k: "to_store", label: "To store", type: "select", options: () => opt.stores(ctx.toProject || d.to_project || S.project), req: true }, { k: "vehicle_no", label: "Vehicle no." }, { k: "remarks", label: "Remarks", wide: true }],
  lines: (d, ctx) => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 240 }, availCol(ctx), { k: "qty", label: "Qty", type: "number", w: 90 }, { k: "received_qty", label: "Received", readonly: true, type: "number" }, { k: "rate", label: "Rate", readonly: true, type: "number" }],
  onHeader: (ctx) => {
    const v = ctx.hf.values();
    if (String(v.to_project) !== String(ctx.toProject)) {
      ctx.toProject = v.to_project;
      const sel = ctx.hf.querySelector('[name="to_store"]');
      sel.innerHTML = ""; sel.append(h("option", { value: "" }, "—"), opt.stores(v.to_project).map(([a, b]) => h("option", { value: a }, b)));
    }
    return loadAvail(ctx, v.from_store);
  },
  after: (ctx) => { ctx.toProject = ctx.doc.to_project; loadAvail(ctx, ctx.doc.from_store); },
  actions: (ctx) => {
    const d = ctx.doc, b = [];
    if (d.status === "draft" && can("inventory", "edit")) b.push(ctx.act("Dispatch", (c) => run("transfer.dispatch", { id: c.doc.id }, (r) => "Dispatched " + r.no), { cls: "primary" }));
    if (d.status === "in_transit" && can("inventory", "edit")) b.push({ label: "Receive", cls: "primary", act: () => {
      const f = form([{ k: "date", label: "Received on", type: "date", default: today() }]);
      const le = lineEditor([{ k: "material_id", label: "Material", type: "select", options: opt.materials, readonly: true }, { k: "qty", label: "Sent", readonly: true, type: "number" }, { k: "received_qty", label: "Received", type: "number" }], d.lines.map((l) => Object.assign({}, l, { received_qty: l.qty })), { fixed: true });
      modal("Receive " + d.no, h("div", {}, f, h("br"), le), [{ label: "Confirm receipt", cls: "primary", act: async () => {
        const got = {}; le.lines().forEach((l) => { got[l.id] = l.received_qty; });
        await run("transfer.receive", { id: d.id, date: f.values().date, received: got }, "Received"); ctx.reopen();
      } }], { narrow: true });
      return false;
    } });
    if (d.status === "in_transit" && can("inventory", "approve")) b.push(ctx.act("Cancel transfer", () => run("transfer.cancel", { id: d.id }, "Cancelled"), { confirm: "Return the material to the source store?", danger: true }));
    if (d.status !== "draft") b.push({ label: "Print", act: () => { printDoc("Material Transfer Note " + d.no, [["Dispatched", d.date], ["From", nm.project(d.from_project) + " / " + nm.store(d.from_store)], ["To", nm.project(d.to_project) + " / " + nm.store(d.to_store)], ["Vehicle", d.vehicle_no], ["Received", d.received_date || "pending"]], [{ label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "qty", label: "Sent", fmt: "qty" }, { k: "received_qty", label: "Received", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }], d.lines, [], d.remarks); return false; } });
    return b;
  },
};
PAGES["inv/transfer"] = docListPage(TRANSFER);

const COUNT = {
  type: "count", title: "Physical stock count", sub: "Count a store, enter what you find, and post. Differences are booked as stock gain or loss.",
  statuses: ["draft", "posted"],
  cols: [{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" }, { label: "Store", v: (r) => nm.store(r.store_id) }, { k: "status", label: "Status", fmt: "status" }],
  fixed: projFixed,
  header: (d) => [{ k: "date", label: "Count date", type: "date", req: true }, { k: "store_id", label: "Store", type: "select", options: () => opt.stores(d.project_id || S.project), req: true }, { k: "remarks", label: "Counted by / remarks", wide: true }],
  lines: () => [{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 240 }, { k: "system_qty", label: "System qty", readonly: true, type: "number" }, { k: "counted_qty", label: "Counted", type: "number", w: 90 }, { label: "Difference", num: true, show: (r) => r.material_id ? fmtQty((Number(r.counted_qty) || 0) - (Number(r.system_qty) || 0)) : "" }, { k: "reason", label: "Reason for difference" }],
  after: (ctx) => {
    if (ctx.doc.status !== "draft") return;
    ctx.extra.append(h("button", { class: "btn", onclick: async () => {
      const v = ctx.hf.values(); if (!v.store_id) return toast("Choose the store first.", "err");
      ctx.le.setLines(await run("count.prefill", { project_id: S.project, store_id: v.store_id }));
    } }, "Load system stock"), h("span", { class: "hint" }, "  System quantity is re-read when you post, so post soon after counting."));
  },
  actions: (ctx) => ctx.doc.status === "draft" && can("inventory", "approve") ? [ctx.act("Post count", (c) => run("count.post", { id: c.doc.id }, (r) => "Posted " + r.no), { cls: "primary", confirm: "Post adjustments for all differences?" })] : [],
};
PAGES["inv/count"] = docListPage(COUNT);

PAGES["inv/opening"] = async (root) => {
  root.append(pageHead("Opening stock", "Load stock that existed before you started using BuildCore. It is valued at the rate you enter and credited to the capital account."));
  if (!S.project) return root.append(projectNotice());
  const f = form([{ k: "date", label: "As of date", type: "date", default: today() }, { k: "store_id", label: "Store", type: "select", options: () => opt.stores(S.project) }]);
  const le = lineEditor([{ k: "material_id", label: "Material", type: "select", options: opt.materials, w: 260 }, unitCol, { k: "qty", label: "Qty", type: "number" }, { k: "rate", label: "Rate", type: "number" }, { label: "Value", num: true, show: (r) => fmtMoney(r.qty * r.rate) }], [{}]);
  const ta = h("textarea", { placeholder: "Or paste from Excel: material code <tab> qty <tab> rate" });
  root.append(h("div", { class: "panel" }, f, h("br"), le, h("details", { style: "margin-top:10px" }, h("summary", {}, "Paste from Excel"), ta, h("button", { class: "btn small", onclick: () => {
    const rows = ta.value.split(/\r?\n/).map((l) => l.split("\t")).filter((r) => r[0] && r[0].trim());
    const miss = [];
    const lines = rows.map((r) => { const m = S.L.materials.find((x) => x.code.toLowerCase() === r[0].trim().toLowerCase()); if (!m) miss.push(r[0]); return m ? { material_id: m.id, qty: r[1], rate: r[2] } : null; }).filter(Boolean);
    le.setLines(lines);
    if (miss.length) toast("Unknown material codes: " + miss.join(", "), "err");
  } }, "Load pasted rows")),
  h("div", { class: "actions" }, can("inventory", "approve") ? h("button", { class: "btn primary", onclick: async () => {
    if (!(await ask("Post opening stock", "Post these quantities as opening stock?"))) return;
    await run("stock.opening", Object.assign(f.values(), { project_id: S.project, lines: le.lines() }), (r) => "Posted " + r.no);
    le.setLines([{}]);
  } }, "Post opening stock") : h("p", { class: "hint" }, "Needs inventory approval rights."))));
};

PAGES["inv/stock"] = async (root) => {
  let v = { group: "material", project_id: S.project };
  const holder = h("div");
  const cats = [...new Set(S.L.materials.map((m) => m.category).filter(Boolean))].map((c) => [c, c]);
  const load = async () => {
    const rows = await run("stock.report", v);
    holder.innerHTML = "";
    const cols = [{ label: "Project", v: (r) => r.project_code }, { k: "store_name", label: "Store" }, { label: "Code", v: (r) => drillTo("material", r.material_id, r.code) }, { k: "name", label: "Material" }, { k: "category", label: "Category" }, { k: "qty", label: "Quantity", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "rate", label: "Avg rate", fmt: "money" }, { k: "value", label: "Value", fmt: "money" }, { k: "reorder_level", label: "Reorder at", fmt: "qty" }, { label: "Flag", v: (r) => r.flag === "reorder" ? stamp("due") : r.flag === "negative" ? stamp("overdue") : "" }];
    holder.append(summaryStrip([["Lines", rows.length], ["Stock value", fmtMoney(rows.reduce((a, r) => a + (r.value || 0), 0))],
      ["At or below reorder", rows.filter((r) => r.flag === "reorder").length],
      ["Negative", rows.filter((r) => r.flag === "negative").length]]));
    holder.append(table(cols, rows, { name: "stock", title: "Stock on hand", totals: ["value"], rowClass: (r) => r.flag === "negative" ? "bad" : r.flag === "reorder" ? "flag" : "", onRow: (r) => { location.hash = "#/inv/card?material=" + r.material_id + (v.group === "store" ? "&store=" + r.store_id : ""); } }));
  };
  root.append(pageHead("Stock on hand", "One balance per project, store and material, updated by every posted document. Click a row for its stock card."),
    filterBar([{ k: "group", label: "Show", type: "select", noBlank: true, options: [["material", "By material (all stores)"], ["store", "By store"]] }, { k: "project_id", label: "Project", type: "select", options: opt.projects, blank: "All projects" }, { k: "store_id", label: "Store", type: "select", options: () => S.project ? opt.stores(S.project, true) : [], blank: "All" }, { k: "category", label: "Category", type: "select", options: cats, blank: "All" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

PAGES["inv/card"] = async (root, params) => {
  root.append(pageHead("Stock card", "Every movement of one material with running balance."));
  if (!S.project) return root.append(projectNotice());
  let v = { material_id: params.material || "", store_id: params.store || "", from: "", to: "" };
  const holder = h("div");
  const load = async () => {
    holder.innerHTML = "";
    if (!v.material_id) return holder.append(h("p", { class: "muted" }, "Choose a material."));
    const d = await run("stock.card", Object.assign({ project_id: S.project }, v));
    const unit = nm.unit(v.material_id);
    const tin = d.rows.reduce((a, r) => a + (r.qty_in || 0), 0);
    const tout = d.rows.reduce((a, r) => a + (r.qty_out || 0), 0);
    const last = d.rows[d.rows.length - 1] || {};
    holder.append(summaryStrip([["Opening", fmtQty(d.opening_qty) + " " + unit], ["Received", fmtQty(tin) + " " + unit],
      ["Issued out", fmtQty(tout) + " " + unit], ["Balance now", fmtQty(last.bal_qty != null ? last.bal_qty : d.opening_qty) + " " + unit],
      ["Stock value", fmtMoney(last.bal_value != null ? last.bal_value : d.opening_value)], ["Movements", d.rows.length]]));
    holder.append(table([{ k: "date", label: "Date" },
      { label: "Document", v: (r) => DOC_KIND[r.doc_type] ? drillTo(DOC_KIND[r.doc_type], r.doc_id, r.doc_no) : (r.doc_no || "") },
      { k: "doc_type", label: "Type" }, { k: "store_name", label: "Store" }, { k: "qty_in", label: "In", fmt: "qty" },
      { k: "qty_out", label: "Out", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" },
      { k: "bal_qty", label: "Balance", fmt: "qty" }, { k: "bal_value", label: "Value", fmt: "money" },
      { k: "batch_no", label: "Batch" }], d.rows,
      { name: "stock_card", title: "Stock card — " + nm.mat(v.material_id), totals: ["qty_in", "qty_out"] }));
  };
  root.append(filterBar([{ k: "material_id", label: "Material", type: "select", options: opt.materials }, { k: "store_id", label: "Store", type: "select", options: () => opt.stores(S.project, true), blank: "All stores" }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], v, (x) => { v = x; load(); }), holder);
  load();
};

PAGES["inv/recon"] = async (root) => {
  root.append(pageHead("Material reconciliation", "Theoretical use (executed BOQ quantity × norm × wastage) against actual issues net of returns. Set norms in BOQ items; executed quantity comes from client invoices."));
  if (!S.project) return root.append(projectNotice());
  let v = { tolerance: 3 };
  const holder = h("div");
  const load = async () => {
    const rows = await run("stock.reconciliation", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    holder.append(table([{ label: "BOQ", v: (r) => drillTo("boq", r.boq_item_id, r.boq_code) }, { k: "description", label: "Description" }, { k: "executed_qty", label: "Executed", fmt: "qty" }, { label: "Material", v: (r) => drillTo("material", r.material_id, r.mat_name) }, { k: "qty_per_unit", label: "Norm", fmt: "qty" }, { k: "wastage_pct", label: "Wastage %", fmt: "qty" }, { k: "theoretical", label: "Theoretical", fmt: "qty" }, { k: "actual", label: "Actual", fmt: "qty" }, { k: "variance", label: "Variance", fmt: "qty" }, { k: "variance_pct", label: "Var %", v: (r) => fmtPct(r.variance_pct) }, { k: "unit", label: "Unit" }], rows, { name: "reconciliation", rowClass: (r) => r.flag ? "flag" : "", empty: "No material norms set for this project's BOQ items." }));
  };
  root.append(filterBar([{ k: "tolerance", label: "Flag above variance %", type: "number" }], v, (x) => { v = x; load(); }), holder);
  load();
};
