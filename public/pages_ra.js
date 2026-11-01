/* BuildCore 1.8 — Resource pool, rate books, norms library and rate analysis. */
(function () {
"use strict";
/* everything below is private to this file, so no name can clash with the rest of BuildCore */


const raAdd = (el, ...xs) => el.append(...xs.filter((x) => x != null && x !== false));
const RA_KINDS = [["L", "Labour"], ["M", "Material"], ["E", "Equipment"], ["N", "Sub-analysis (norm)"], ["X", "Percentage — code L, M, E, LM or LME"]];
const RA_TYPES = [["material", "Materials"], ["tool", "Tools & PPE"], ["labour", "Labour"], ["equipment", "Equipment"], ["transport", "Transport"]];
let RA_META = null;
async function raMeta(force) { if (!RA_META || force) RA_META = await run("respool.meta", {}); return RA_META; }
const raBooks = () => (RA_META ? RA_META.books : []).map((b) => [b.id, b.name + (b.is_default ? " (default)" : "")]);

function raDownload(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv" }));
  a.download = name; document.body.append(a); a.click(); a.remove();
}
function raPickFile(accept, cb) {
  const i = h("input", { type: "file", accept, style: "display:none" });
  i.addEventListener("change", () => {
    const f = i.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => cb({ filename: f.name, b64: String(r.result) });
    r.readAsDataURL(f);
  });
  document.body.append(i); i.click(); setTimeout(() => i.remove(), 60000);
}

/* ── resource pool ── */
PAGES["rp/pool"] = async (root, params) => {
  await raMeta();
  let v = { type: params.type || "material", category: "", q: params.q || "", book_id: "" };
  const picked = new Set();
  const holder = h("div");
  const load = async () => {
    const d = await run("respool.list", v);
    holder.innerHTML = "";
    const cnt = RA_META.counts;
    raAdd(holder, summaryStrip([["Materials", cnt.material || 0], ["Tools & PPE", cnt.tool || 0], ["Labour", cnt.labour || 0], ["Equipment", cnt.equipment || 0],
      ["Transport", cnt.transport || 0], ["Shown", d.count], ["Sample rates shown", d.rows.filter((r) => r.rate_is_sample).length],
      ["Selected", picked.size]]));
    raAdd(holder, table([
      { label: "", v: (r) => { const cb = h("input", { type: "checkbox", onclick: (e) => { e.stopPropagation(); cb.checked ? picked.add(r.id) : picked.delete(r.id); } });
        cb.checked = picked.has(r.id); return cb; } },
      { k: "code", label: "Code" }, { k: "name", label: "Resource" }, { k: "spec", label: "Specification" },
      { k: "category", label: "Category" }, { k: "subcategory", label: "Group" }, { k: "unit", label: "Unit" },
      { k: "weight", label: "kg / unit", fmt: "qty" },
      { k: "effective_rate", label: v.book_id ? "Rate (book)" : "Rate", fmt: "money" },
      { label: "Rate from", v: (r) => r.book_rate != null ? "Rate book" : (r.rate_is_sample ? "SAMPLE" : (r.rate_source || "")) },
      { label: "In masters", v: (r) => r.local_id ? "✓ " + r.local_table : "" },
    ], d.rows, { name: "resource_pool", title: "Resource pool — " + v.type,
      rowClass: (r) => r.rate_is_sample ? "flag" : (r.effective_rate == null ? "muted" : ""),
      empty: "Nothing matches. Add it with “New resource”.", onRow: (r) => raResDialog(r, load) }));
  };
  const btn = (t, f, cls) => h("button", { class: "btn " + (cls || ""), onclick: f }, t);
  root.append(pageHead("Resource pool",
    "Every construction material, labour trade, machine and transport mode, ready to use — about 1,450 lines. "
    + "Pick from here instead of creating masters one by one; add your own only when something is missing. "
    + "Yellow rows still carry a sample rate: replace it with the DRC rate or put the rate in a district rate book.",
    can("masters", "edit") ? btn("New resource", () => raResDialog({ type: v.type }, load), "primary") : null,
    can("masters", "edit") ? btn("Add selected to masters", async () => {
      if (!picked.size) return toast("Tick the lines to add first.", "err");
      await run("respool.adopt", { ids: [...picked], project_id: S.project, book_id: v.book_id || null },
        (x) => x.created + " created, " + x.linked + " linked" + (x.skipped.length ? ", " + x.skipped.length + " skipped (equipment/transport stay in the pool)" : ""));
      picked.clear(); load(); }) : null,
    can("masters", "edit") ? btn("Import .xlsx / .csv", () => raPickFile(".xlsx,.csv", async (f) => {
      await run("respool.import", Object.assign(f, { book_id: v.book_id || null }), (x) => x.added + " added, " + x.updated + " updated" + (x.errors.length ? " — " + x.errors[0] : ""));
      await raMeta(true); load(); })) : null,
    btn("Export .csv", async () => { const x = await run("respool.export", v); raDownload(x.filename, x.csv); })),
  filterBar([
    { k: "type", label: "Type", type: "select", noBlank: true, options: RA_TYPES },
    { k: "category", label: "Category", type: "select", blank: "All", options: () => RA_META.categories.filter((x) => x.type === v.type).map((x) => [x.category, x.category + " (" + x.n + ")"]) },
    { k: "q", label: "Search", ph: "cement, 16 mm, excavator 0.9 …" },
    { k: "book_id", label: "Rate book", type: "select", blank: "Pool rates", options: raBooks },
  ], v, (x) => { if (x.type !== v.type) { location.hash = "#/rp/pool?type=" + x.type; return; } v = x; load(); }), holder);
  await load();
};

function raResDialog(r, done) {
  const ro = !can("masters", "edit");
  const f = form([
    { k: "code", label: "Code", readonly: !!r.id, ph: "Leave blank to number it" },
    { k: "type", label: "Type", type: "select", noBlank: true, options: RA_TYPES, readonly: !!r.id || ro },
    { k: "category", label: "Category", readonly: ro }, { k: "subcategory", label: "Group", readonly: ro },
    { k: "name", label: "Name", req: true, wide: true, readonly: ro }, { k: "spec", label: "Specification / standard", wide: true, readonly: ro },
    { k: "unit", label: "Unit", req: true, readonly: ro }, { k: "weight", label: "Weight kg per unit (for cartage)", type: "number", readonly: ro },
    { k: "rate", label: "Rate", type: "number", readonly: ro }, { k: "rate_source", label: "Rate source", ph: "DRC Kaski 2082/83, quotation …", readonly: ro },
    { k: "remarks", label: "Remarks", wide: true, readonly: ro },
  ], r);
  const btns = ro ? [] : [{ label: "Save", cls: "primary", act: async () => {
    await run("respool.save", { row: Object.assign(r.id ? { id: r.id } : {}, f.values()) }, "Saved"); await raMeta(true); if (done) done(); } }];
  if (r.id && !ro) btns.push({ label: r.system ? "Hide from pool" : "Delete", act: async () => {
    await run("respool.delete", { id: r.id }, (x) => x.deleted ? "Deleted" : "Hidden (shipped or used in norms)"); if (done) done(); } });
  modal(r.id ? r.code + " " + r.name : "New resource", h("div", {}, f,
    r.sample ? h("p", { class: "hint" }, "This is a sample rate shipped with BuildCore. Typing a rate here replaces it.") : null), btns, { narrow: true });
}

/* ── rate books ── */
PAGES["rp/books"] = async (root) => {
  await raMeta(true);
  let v = { book_id: (RA_META.books[0] || {}).id, type: "material", q: "" };
  const holder = h("div");
  const load = async () => {
    const d = await run("respool.list", Object.assign({}, v, { limit: 2000 }));
    holder.innerHTML = "";
    const inputs = {};
    raAdd(holder, table([{ k: "code", label: "Code" }, { k: "name", label: "Resource" }, { k: "unit", label: "Unit" },
      { k: "rate", label: "Pool rate", fmt: "money" },
      { label: "Rate in this book", v: (r) => { const i = h("input", { type: "number", step: "any", class: "num" }); i.value = r.book_rate ?? ""; inputs[r.id] = [i, r.book_rate]; i.onclick = (e) => e.stopPropagation(); return i; } }],
    d.rows, { search: false, name: "rate_book", title: "Rate book" }),
    can("masters", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const rates = Object.entries(inputs).filter(([, [i, old]]) => String(i.value) !== String(old ?? "")).map(([id, [i]]) => ({ res_id: Number(id), rate: i.value }));
      await run("ratebook.set_rates", { book_id: v.book_id, rates }, (x) => x.saved + " rates saved"); load(); } }, "Save rates")) : null);
  };
  root.append(pageHead("Rate books", "One book per district and fiscal year (District Rate Committee rates). An analysis priced with a book "
    + "uses its rate where one is set, and the pool rate otherwise. Copy last year's book with an escalation % to start the new year.",
  can("masters", "edit") ? h("button", { class: "btn primary", onclick: () => raBookDialog(async () => { await raMeta(true); location.reload(); }) }, "New rate book") : null),
  filterBar([{ k: "book_id", label: "Book", type: "select", noBlank: true, options: raBooks },
    { k: "type", label: "Type", type: "select", noBlank: true, options: RA_TYPES }, { k: "q", label: "Search" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

function raBookDialog(done) {
  const f = form([{ k: "code", label: "Code", req: true, ph: "KAS-8283" }, { k: "name", label: "Name", req: true, ph: "DRC Kaski 2082/83" },
    { k: "district", label: "District" }, { k: "fy", label: "Fiscal year", ph: "2082/83" }, { k: "source", label: "Source" },
    { k: "is_default", label: "Default book", type: "select", options: [[0, "No"], [1, "Yes"]] },
    { k: "copy_from", label: "Copy rates from", type: "select", options: raBooks }, { k: "escalation_pct", label: "Escalation %", type: "number" }], {});
  modal("New rate book", f, [{ label: "Create", cls: "primary", act: async () => {
    const x = f.values(); const cf = x.copy_from, esc = x.escalation_pct; delete x.copy_from; delete x.escalation_pct;
    await run("ratebook.save", { row: x, copy_from: cf, escalation_pct: esc }, "Rate book created"); if (done) done(); } }], { narrow: true });
}

/* ── norms library ── */
PAGES["rp/norms"] = async (root, params) => {
  await raMeta(true);
  let v = { section: params.section || "", source: "", q: "", verified: "" };
  const holder = h("div");
  const load = async () => {
    const d = await run("rnorm.list", v);
    holder.innerHTML = "";
    raAdd(holder, summaryStrip([["Norms", d.rows.length], ["Verified (DoR / DUDBC)", d.rows.filter((r) => r.verified).length],
      ["Starter / company", d.rows.filter((r) => !r.verified).length]]));
    raAdd(holder, table([{ k: "code", label: "Code" }, { k: "section", label: "Section" }, { k: "title", label: "Work item" },
      { label: "Per", v: (r) => r.per_qty + " " + r.unit }, { k: "lines", label: "Lines", fmt: "num" }, { k: "source", label: "Source" },
      { label: "Status", v: (r) => r.verified ? "Verified" : (r.checks ? "Check against book" : (r.system ? "Starter — verify" : "Company")) }],
    d.rows, { name: "norms", title: "Norms library", rowClass: (r) => r.verified ? "" : "flag", onRow: (r) => raNormDialog(r.id, load) }));
  };
  root.append(pageHead("Norms library",
    "Labour, material and equipment per unit of work. BuildCore ships the DoR Norms 2075 (road & bridge), the DUDBC building norms and the "
    + "Electrical and Sanitary rate analyses 2079/80, read from the published books. Norms marked “Check against book” had text the reader "
    + "could not split cleanly — compare them with the printed page before use. You can also import norms from a sheet (one row per resource line). "
    + "Shipped and verified norms are locked; “Copy to edit” makes a company version.",
  can("masters", "edit") ? h("button", { class: "btn primary", onclick: () => raNormDialog(null, load) }, "New norm") : null,
  can("masters", "edit") ? h("button", { class: "btn", onclick: () => raPickFile(".xlsx,.csv", async (f) => {
    const x = await run("rnorm.import", Object.assign(f, { replace: confirm("Replace norms that already exist with the same code?") }),
      (r) => r.added + " added, " + r.replaced + " replaced" + (r.skipped.length ? ", " + r.skipped.length + " skipped" : ""));
    if (x.missing_resources.length) modal("Resources not in the pool", h("div", {}, h("p", {}, "Add these codes to the pool (or correct them in the sheet), then import again:"),
      h("p", {}, x.missing_resources.join(", "))), []);
    load(); }) }, "Import norms .xlsx / .csv") : null,
  h("button", { class: "btn", onclick: async () => { const x = await run("rnorm.export", v); raDownload(x.filename, x.csv); } }, "Export .csv")),
  filterBar([{ k: "section", label: "Section", type: "select", blank: "All", options: () => RA_META.sections.map((s) => [s, s]) },
    { k: "source", label: "Source", type: "select", blank: "All", options: () => RA_META.norm_sources.map((s) => [s, s]) },
    { k: "verified", label: "Status", type: "select", blank: "All", options: [[1, "Verified"], [0, "Not verified"]] },
    { k: "q", label: "Search" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

let RA_REFS = null;
async function raRefs() {
  if (!RA_REFS) {
    const [p, n] = await Promise.all([run("respool.list", { limit: 5000 }), run("rnorm.list", {})]);
    RA_REFS = { res: p.rows, norms: n.rows };
  }
  return RA_REFS;
}

async function raNormDialog(id, done) {
  const refs = await raRefs();
  const n = id ? await run("rnorm.get", { id }) : { per_qty: 1, source: "Company", lines: [] };
  const locked = !!(n.system || n.verified) || !can("masters", "edit");
  const f = form([{ k: "code", label: "Code", req: true, readonly: !!id }, { k: "section", label: "Section", readonly: locked },
    { k: "title", label: "Work item", req: true, wide: true, readonly: locked }, { k: "unit", label: "Unit", req: true, readonly: locked },
    { k: "per_qty", label: "Norm written for (quantity)", type: "number", readonly: locked }, { k: "source", label: "Source", readonly: true },
    { k: "remarks", label: "Remarks", wide: true, readonly: locked }], n);
  const dl = h("datalist", { id: "ra-refs" });
  refs.res.forEach((r) => dl.append(h("option", { value: r.code }, r.name + " (" + r.unit + ")")));
  refs.norms.forEach((r) => dl.append(h("option", { value: r.code }, "Norm: " + r.title)));
  const tb = h("tbody");
  const addLine = (ln) => {
    const k = h("select", { disabled: locked }); RA_KINDS.forEach(([a, b]) => k.append(h("option", { value: a }, b))); k.value = ln.kind || "M";
    const ref = h("input", { list: "ra-refs", value: ln.ref || "", readonly: locked, style: "width:110px" });
    const nm_ = h("span", { class: "muted" }, ln.name ? ln.name + " (" + (ln.unit || "") + ")" : "");
    ref.addEventListener("change", () => { const r = refs.res.find((x) => x.code === ref.value) || refs.norms.find((x) => x.code === ref.value);
      nm_.textContent = r ? (r.name || r.title) + " (" + r.unit + ")" : "not found"; });
    const qty = h("input", { type: "number", step: "any", value: ln.qty ?? "", readonly: locked, style: "width:90px" });
    const note = h("input", { value: ln.note || "", readonly: locked });
    const tr = h("tr", {}, h("td", {}, k), h("td", {}, ref), h("td", {}, nm_), h("td", {}, qty), h("td", {}, note),
      h("td", {}, locked ? "" : h("button", { class: "btn small", onclick: () => tr.remove() }, "✕")));
    tr._val = () => ({ kind: k.value, ref: ref.value.trim(), qty: qty.value, note: note.value });
    tb.append(tr);
  };
  n.lines.forEach(addLine);
  const lines = h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ["Kind", "Code", "Resource", "Quantity", "Note", ""].map((x) => h("th", {}, x)))), tb);
  const btns = [];
  if (!locked) btns.push({ label: "Save", cls: "primary", act: async () => {
    await run("rnorm.save", { row: Object.assign(id ? { id } : {}, f.values()), lines: [...tb.children].map((tr) => tr._val()).filter((x) => x.ref || x.kind === "X") }, "Saved");
    RA_REFS = null; if (done) done(); } });
  if (id && can("masters", "edit")) btns.push({ label: "Copy to edit", act: async () => {
    const x = await run("rnorm.copy", { id }, (r) => "Copied as " + r.code); RA_REFS = null; faCloseTop(); raNormDialog(x.id, done); return false; } });
  if (id) btns.push({ label: "Analyse rate", act: () => { location.hash = "#/rp/ra?norm=" + encodeURIComponent(n.code); } });
  modal(id ? n.code + " — " + n.title : "New norm", h("div", {}, f, dl,
    n.derivation ? h("p", { class: "hint" }, "Derivation: " + n.derivation) : null,
    n.checks ? h("p", { class: "hint flag" }, "Check this norm against the printed book before use: " + n.checks + ". Use “Copy to edit” to correct it.") : null,
    !n.verified && id && !n.checks ? h("p", { class: "hint" }, "Not a verified DoR/DUDBC norm — " + (n.system ? "BuildCore starter item." : "company norm.")) : null,
    n.ref_rate ? h("p", { class: "hint" }, "Rate printed in the 2079/80 book: Rs " + fmtMoney(n.ref_rate) + " per " + n.unit + " (excluding VAT).") : null,
    h("h3", {}, "Resources for " + (n.per_qty || 1) + " " + (n.unit || "unit")), lines,
    locked ? null : h("button", { class: "btn small", onclick: () => addLine({ kind: "M" }) }, "+ Add line")), btns);
}
const faCloseTop = () => { const o = document.querySelectorAll(".overlay"); if (o.length) o[o.length - 1].remove(); };

/* ── rate analysis ── */
PAGES["rp/ra"] = async (root, params) => {
  await raMeta(true);
  const refs = await raRefs();
  const tmodes = (await run("respool.list", { type: "transport" })).rows;
  let v = { norm_code: params.norm || "", book_id: "", overhead_pct: 15, vat_pct: 13 };
  const leads = {};
  const out = h("div"), saved = h("div");
  const leadBox = h("div", { class: "form" }, tmodes.map((t) => {
    const i = h("input", { type: "number", step: "any", placeholder: t.unit === "t-km" ? "km" : "times" });
    i.addEventListener("change", () => { leads[t.code] = i.value; });
    return h("label", {}, t.name + " (" + fmtMoney(t.effective_rate) + "/" + t.unit + ")", i);
  }));
  const compute = async () => {
    if (!v.norm_code) { out.innerHTML = ""; return; }
    const d = await run("ranal.compute", Object.assign({}, v, { leads }));
    out.innerHTML = "";
    raAdd(out, h("h2", { class: "sec" }, d.code + " — " + d.title + " (per " + d.per_qty + " " + d.unit + ")"),
      d.warnings.length ? h("div", { class: "panel flag" }, d.warnings.slice(0, 8).map((w) => h("div", {}, "⚠ " + w)),
        d.warnings.length > 8 ? h("div", {}, "… and " + (d.warnings.length - 8) + " more") : null) : null,
      table([{ label: "Kind", v: (r) => (RA_KINDS.find(([k]) => k === r.kind) || [, r.kind])[1] }, { k: "ref", label: "Code" },
        { k: "name", label: "Description" }, { k: "unit", label: "Unit" }, { k: "qty", label: "Qty", fmt: "qty" },
        { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" },
        { k: "cartage_rate", label: "Cartage / unit", fmt: "money" }, { k: "cartage", label: "Cartage", fmt: "money" }, { k: "note", label: "Note" }],
      d.rows, { search: false, name: "rate_analysis", title: "Rate analysis " + d.code, totals: ["amount", "cartage"] }),
      table([{ k: "l", label: "" }, { k: "x", label: "Amount", fmt: "money" }], [
        { l: "Labour", x: d.labour }, { l: "Material (incl. sub-analyses)", x: d.material }, { l: "Cartage of materials", x: d.cartage },
        { l: "Equipment", x: d.equipment }, { l: "Sundries", x: d.sundries }, { l: "Total for " + d.per_qty + " " + d.unit, x: d.direct },
        { l: "Cost per " + d.unit, x: d.cost_per_unit }, { l: "Overhead & profit " + d.overhead_pct + "%", x: d.overhead },
        { l: "Rate per " + d.unit + " excluding VAT", x: d.rate_ex_vat }, { l: "VAT " + d.vat_pct + "%", x: d.vat },
        { l: "Rate per " + d.unit + " including VAT", x: d.rate_incl_vat }], { search: false, export: false }),
      can("commercial", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => raSaveDialog(v, leads, loadSaved) }, "Save / apply to BOQ item")) : null);
  };
  const loadSaved = async () => {
    const d = await run("ranal.list", { project_id: S.project || null });
    saved.innerHTML = "";
    raAdd(saved, h("h2", { class: "sec" }, "Saved analyses"), table([{ k: "no", label: "No." }, { k: "norm_code", label: "Norm" },
      { k: "title", label: "Item" }, { k: "unit", label: "Unit" }, { k: "book", label: "Rate book" },
      { k: "rate_ex_vat", label: "Rate ex VAT", fmt: "money" }, { k: "rate_incl_vat", label: "Incl. VAT", fmt: "money" },
      { label: "BOQ item", v: (r) => r.boq_item_id || "" }, { label: "Norm", v: (r) => r.verified ? "Verified" : "Not verified" }, { k: "ts", label: "When" }],
    d.rows, { name: "saved_ra", title: "Rate analyses", empty: "None saved yet.",
      onRow: async (r) => { const g = await run("ranal.get", { id: r.id }); v = Object.assign(v, { norm_code: g.result.code, book_id: g.book_id || "" }); compute(); } }),
    can("commercial", "edit") && d.rows.length ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
      await run("ranal.recompute_all", { project_id: S.project || null, book_id: v.book_id || null, push: true }, (x) => x.recomputed + " analyses re-priced"); loadSaved(); } },
      "Re-price all with the chosen rate book")) : null);
  };
  const dl = h("datalist", { id: "ra-norms" });
  refs.norms.forEach((r) => dl.append(h("option", { value: r.code }, r.title + " (" + r.unit + ")")));
  const fb = filterBar([{ k: "norm_code", label: "Norm (type code or pick)" }, { k: "book_id", label: "Rate book", type: "select", blank: "Default book", options: raBooks },
    { k: "overhead_pct", label: "Overhead & profit %", type: "number" }, { k: "vat_pct", label: "VAT %", type: "number" }], v, (x) => { v = x; compute(); });
  const ni = fb.querySelector("input[name=norm_code]"); if (ni) ni.setAttribute("list", "ra-norms");
  root.append(pageHead("Rate analysis", "Labour + materials (with cartage to site) + equipment for the norm quantity, per unit, plus the contractor's "
    + "overhead & profit (15% as in DoR analyses) and VAT 13%. Save it against a BOQ item to fill the item's rate analysis."),
  fb, dl, h("details", {}, h("summary", {}, "Cartage leads (distance from source to site by road class)"), leadBox,
    h("button", { class: "btn small", onclick: compute }, "Recalculate")), out, saved);
  await compute(); await loadSaved();
};

/* ── item rates: every norm priced with one rate book ── */
PAGES["rp/items"] = async (root) => {
  await raMeta(true);
  let v = { book_id: "", source: "", section: "", q: "", show: "", overhead_pct: 15, vat_pct: 13 };
  const holder = h("div");
  const per = (r, k) => (r[k] || 0) / (r.per_qty || 1);
  const load = async () => {
    holder.innerHTML = "";
    holder.append(h("p", { class: "muted" }, "Working out the rates …"));
    const d = await run("ranal.items", v);
    let rows = d.rows;
    if (v.show === "missing") rows = rows.filter((r) => r.missing);
    if (v.show === "check") rows = rows.filter((r) => r.checks);
    if (v.show === "ok") rows = rows.filter((r) => !r.missing && !r.checks);
    if (v.show === "book") rows = rows.filter((r) => r.ref_rate);
    holder.innerHTML = "";
    const sm = d.summary;
    raAdd(holder, summaryStrip([["Norms priced", sm.norms], ["All rates found", sm.complete], ["Some rate missing", sm.missing],
      ["Using estimated rates", sm.estimates], ["Check against book", sm.to_check]]),
      h("p", { class: "hint" }, "Rate book: " + (d.book ? d.book.name : "pool rates") + ". Overhead & profit " + d.overhead_pct + "%, VAT " + d.vat_pct
        + "%. Cartage is not included here — add the leads in Rate analysis for a site. “Estimated rates” means at least one resource in the norm "
        + "uses a BuildCore estimate, not a published price: replace those in Rate books with your district rate or quotations."),
      table([{ k: "code", label: "Code" }, { k: "title", label: "Work item" }, { k: "unit", label: "Unit" },
        { label: "Labour", v: (r) => per(r, "labour"), fmt: "money" }, { label: "Material", v: (r) => per(r, "material"), fmt: "money" },
        { label: "Equipment", v: (r) => per(r, "equipment"), fmt: "money" }, { label: "Sundries %", v: (r) => per(r, "sundries"), fmt: "money" },
        { k: "rate_ex_vat", label: "Rate excl. VAT", fmt: "money" }, { k: "rate_incl_vat", label: "Rate incl. VAT", fmt: "money" },
        { k: "ref_rate", label: "Book rate 2079/80", fmt: "money" },
        { label: "Flags", v: (r) => [r.missing ? r.missing + " rate(s) missing" : "", r.estimates ? r.estimates + " estimated" : "", r.checks ? "check against book" : ""].filter(Boolean).join(" · ") },
        { k: "source", label: "Source" }, { k: "section", label: "Section" }],
      rows, { name: "item_rates", title: "Item rates", rowClass: (r) => (r.missing || r.checks) ? "flag" : "",
        onRow: (r) => { location.hash = "#/rp/ra?norm=" + encodeURIComponent(r.code); } }));
  };
  root.append(pageHead("Item rates", "The rate of every work item in the norms library, worked out from its norm and the rate book you choose. "
    + "Pick “Market reference 2083/84” for current Kathmandu market prices, or “Electrical & sanitary rate analysis 2079/80” to see the rates as the "
    + "books printed them. Click a row for the full build-up.",
  h("button", { class: "btn", onclick: async () => {
    const x = await run("ranal.items_xlsx", v);
    if (x.b64) { const a = document.createElement("a"); a.href = "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + x.b64;
      a.download = x.filename; document.body.append(a); a.click(); a.remove(); } else raDownload(x.filename, x.csv); } }, "Export to Excel")),
  filterBar([{ k: "book_id", label: "Rate book", type: "select", blank: "Default book", options: raBooks },
    { k: "source", label: "Norm book", type: "select", blank: "All", options: () => RA_META.norm_sources.map((s) => [s, s]) },
    { k: "section", label: "Section", type: "select", blank: "All", options: () => RA_META.sections.map((s) => [s, s]) },
    { k: "show", label: "Show", type: "select", blank: "All", options: [["ok", "Complete and clean"], ["missing", "Rate missing"], ["check", "Check against book"], ["book", "With a 2079/80 book rate"]] },
    { k: "q", label: "Search" }, { k: "overhead_pct", label: "Overhead & profit %", type: "number" }, { k: "vat_pct", label: "VAT %", type: "number" }],
  v, (x) => { v = x; load(); }), holder);
  await load();
};

function raSaveDialog(v, leads, done) {
  const f = form([{ k: "boq_item_id", label: "BOQ item id (optional)", type: "number" }, { k: "title", label: "Title (optional)", wide: true },
    { k: "push", label: "Write into the BOQ item's rate analysis", type: "select", options: [[1, "Yes"], [0, "No"]], default: 1 },
    { k: "remarks", label: "Remarks", wide: true }], {});
  modal("Save rate analysis", f, [{ label: "Save", cls: "primary", act: async () => {
    const x = f.values(); x.push = Number(x.push) === 1;
    await run("ranal.save", Object.assign({}, v, x, { leads, project_id: S.project || null }), (r) => r.no + " saved — Rs " + fmtMoney(r.rate_ex_vat) + (r.pushed.length ? " → BOQ" : ""));
    if (done) done(); } }], { narrow: true });
}

})();
