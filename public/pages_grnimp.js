/* BuildCore 2.16.1 — import many goods received notes at once from an Excel / CSV sheet. */
(function () {
"use strict";

const pill = (txt, col) => h("span", { style: "display:inline-block;white-space:nowrap;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff;background:" + col }, txt);
const COL = { posted: "#2f7a4d", draft: "#1769aa", ok: "#2f7a4d", error: "#b42318", held: "#c05621", "already in BuildCore": "#667085" };
const money = (n) => Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function save(name, b64, mime) {
  const a = document.createElement("a");
  a.href = "data:" + mime + ";base64," + b64; a.download = name; document.body.append(a); a.click(); a.remove();
}

PAGES["inv/grnimport"] = async (root) => {
  if (!can("inventory", "edit")) { root.append(pageHead("Import goods received"), h("div", { class: "panel" }, "Your role cannot receive goods.")); return; }
  let file = null;
  const fname = h("span", { class: "muted" }, "no file chosen");
  const inp = h("input", { type: "file", accept: ".xlsx,.xlsm,.csv,.txt", style: "display:none", onchange: () => {
    const f = inp.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => { file = { filename: f.name, b64: String(r.result) }; fname.textContent = f.name; out.innerHTML = ""; impBtn.disabled = true; };
    r.readAsDataURL(f);
  } });
  const opts = form([{ k: "from", label: "Only rows from (blank = all)", type: "date" }, { k: "to", label: "Only rows up to (blank = all)", type: "date" },
    { k: "date_order", label: "Dates like 05/09/2026 are", type: "select", noBlank: true, options: [["auto", "Find out from the sheet"], ["dmy", "day/month/year"], ["mdy", "month/day/year"]] },
    { k: "post", label: "Post the GRNs (stock and accounts move now)", type: "check" }], { date_order: "auto", post: 1 });
  const out = h("div");
  const run_ = async (apply) => {
    if (!file) { toast("Choose the filled sheet first.", "err"); return; }
    const v = opts.values();
    const d = await run("grn.import", { filename: file.filename, b64: file.b64, from: v.from || null, to: v.to || null, date_order: v.date_order, post: v.post ? 1 : 0, apply: apply ? 1 : 0 });
    show(d);
    impBtn.disabled = apply || d.summary.grns === 0;
    if (apply) toast(d.summary.grns + " GRN(s) " + (d.posted ? "posted" : "saved as draft"), "ok");
  };
  const chkBtn = h("button", { class: "btn", onclick: () => run_(false) }, "1. Check the sheet");
  const impBtn = h("button", { class: "btn primary", disabled: true, onclick: async () => {
    if (await ask("Import goods received", "Save the GRNs that passed the check? Challans with an error are left out; you can fix them and import the same sheet again - challans already imported are skipped.")) run_(true);
  } }, "2. Import");

  function show(d) {
    const s = d.summary;
    out.innerHTML = "";
    out.append(h("div", { class: "panel" + (d.applied ? "" : " warn") }, h("b", {}, d.applied ? "Imported." : "Checked only - nothing is saved yet. Press Import to save."),
      d.date_order ? h("span", { class: "muted" }, "  Dates read as " + d.date_order + ".") : null,
      d.ignored_columns.length ? h("p", { class: "hint" }, "Columns not used: " + d.ignored_columns.join(", ")) : null));
    out.append(h("div", { class: "tiles" }, tile("Rows in the sheet", s.rows), tile(d.applied ? (d.posted ? "GRNs posted" : "GRNs saved as draft") : "GRNs ready", s.grns),
      tile("Value (accepted × rate)", "Rs " + money(s.value)), tile("Rows with an error", s.row_errors, { cls: s.row_errors ? "bad" : "" }),
      tile("GRNs that failed", s.grn_errors, { cls: s.grn_errors ? "bad" : "" }), tile("Already in BuildCore (skipped)", s.skipped),
      tile("New vendors", s.new_vendors, { cls: s.new_vendors ? "warn" : "" }), tile("New materials", s.new_materials, { cls: s.new_materials ? "warn" : "" }),
      s.outside ? tile("Rows outside the dates", s.outside) : null));
    out.append(h("h2", {}, "Goods received notes"), table([{ label: "", v: (g) => pill(g.status, COL[g.status] || "#667085") }, { k: "grn_no", label: "GRN no." }, { k: "date", label: "Date" },
      { k: "project", label: "Project" }, { k: "store", label: "Store" }, { k: "vendor", label: "Vendor" }, { k: "challan_no", label: "Challan / bill" },
      { k: "lines", label: "Lines" }, { k: "value", label: "Value", fmt: "money" }, { k: "message", label: "Message" }],
    d.groups, { name: "grn_import_result", rowClass: (g) => (g.status === "error" ? "flag" : ""), onRow: (g) => { if (g.grn_id && d.applied) location.hash = "#/inv/grn?id=" + g.grn_id; } }));
    const bad = d.rows.filter((r) => r.status === "error" || r.status === "held" || r.note);
    if (bad.length) out.append(h("h2", {}, "Rows to look at"), table([{ k: "line", label: "Sheet row" }, { label: "", v: (r) => pill(r.status, COL[r.status] || "#667085") }, { k: "date", label: "Date" },
      { k: "vendor", label: "Vendor" }, { k: "challan", label: "Challan" }, { k: "material", label: "Material" }, { label: "Problem / note", v: (r) => r.error || [r.note, r.status === "held" ? "its challan was not imported - see the GRN list above" : ""].filter(Boolean).join("; ") }], bad, { name: "grn_import_rows" }));
    if (d.new_vendors.length) out.append(h("h2", {}, d.applied ? "Vendors created" : "Vendors that will be created"), table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "pan", label: "PAN / VAT" }], d.new_vendors, { search: false }));
    if (d.new_materials.length) out.append(h("h2", {}, d.applied ? "Materials created" : "Materials that will be created"), table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "unit", label: "Unit" }], d.new_materials, { search: false }));
  }

  root.append(pageHead("Import goods received (Excel / CSV)", "Many GRNs at once - any dates, vendors and materials. One row per material; rows with the same date, project, store, vendor and challan become one GRN.",
    h("a", { class: "btn", href: "#/inv/grn" }, "Goods received list")));
  root.append(h("div", { class: "panel" }, h("h2", {}, "1. Get the sample sheet"),
    h("p", {}, "Every column is required: ", h("b", {}, "GRN Date, Project Code, Store, Vendor Name, Vendor PAN/VAT No, Vendor Phone, Vendor Address, Challan/Bill No, Vehicle No, Material Code, Material Name, Unit, Received Qty, Accepted Qty, Rate (excl. VAT)"), "."),
    h("ul", { class: "hint" }, h("li", {}, "Dates in AD (2026-09-27 or 27/09/2026) or BS (2083-06-11)."),
      h("li", {}, "A vendor not in BuildCore is created from the sheet - found first by PAN, then by name."),
      h("li", {}, "A material code not in BuildCore is created with the name and unit in the sheet."),
      h("li", {}, "Store = the store code or name of that project (see Stores & locations)."),
      h("li", {}, "The same sheet can be imported again after adding rows: a challan already in BuildCore is skipped.")),
    h("div", { class: "bar" }, h("button", { class: "btn", onclick: async () => { const t = await run("grn.import_template", {}); save(t.filename, t.b64, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); } }, "Download sample (.xlsx)"),
      h("button", { class: "btn", onclick: async () => { const t = await run("grn.import_template", { format: "csv" }); const a = h("a", { href: URL.createObjectURL(new Blob(["﻿" + t.csv], { type: "text/csv" })), download: t.filename }); document.body.append(a); a.click(); a.remove(); } }, "Download sample (.csv)"))),
  h("div", { class: "panel" }, h("h2", {}, "2. Choose the filled sheet, check, then import"), h("div", { class: "bar" }, inp, h("button", { class: "btn", onclick: () => inp.click() }, "Choose file…"), fname), opts,
    h("div", { class: "bar" }, chkBtn, impBtn), h("p", { class: "hint" }, "“Check” runs the whole import - vendors, materials, stock, accounts - and then undoes it, so you see every problem before anything is saved.")), out);
};

/* a button on the Goods received list */
function addButton() {
  const cur = PAGES["inv/grn"];
  if (!cur || cur._bcoImp) return;
  const wrapped = async (root, params) => {
    const r = await cur(root, params);
    try {
      if (can("inventory", "edit") && !root.querySelector(".bco-grnimp")) {
        const bar = root.querySelector(".bar");
        const b = h("a", { class: "btn bco-grnimp", href: "#/inv/grnimport" }, "Import from Excel");
        if (bar) bar.append(b); else root.prepend(b);
      }
    } catch (e) { /* never break the page */ }
    return r;
  };
  wrapped._bcoImp = true;
  PAGES["inv/grn"] = wrapped;
}
addButton();
document.addEventListener("DOMContentLoaded", addButton);
})();
