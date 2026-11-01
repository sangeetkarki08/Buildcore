/* Plant (batching plant, crusher, quarry) and the asset register. */
"use strict";

const PLANT_KINDS = [["batching", "Batching plant"], ["crusher", "Crusher"], ["quarry", "Quarry"],
  ["block", "Block / brick plant"], ["bending", "Bar bending yard"], ["workshop", "Workshop"], ["other", "Other"]];
const ASSET_CLASSES = [["land", "Land"], ["building", "Building"], ["camp", "Camp & site facility"],
  ["vehicle", "Light vehicle"], ["furniture", "Furniture & fitting"], ["computer", "Computer & IT"],
  ["instrument", "Survey & lab instrument"], ["tool", "Tools & small plant"], ["other", "Other"]];
const ASSET_STATUS = [["in_use", "In use"], ["spare", "Spare / store"], ["under_repair", "Under repair"],
  ["lost", "Lost"], ["disposed", "Disposed"]];
const CONDITIONS = [["good", "Good"], ["fair", "Fair"], ["poor", "Poor"], ["damaged", "Damaged"]];

/* ── plant register ─────────────────────────────────────────────── */
PAGES["pl/register"] = masterPage({
  table: "plants", module: "plant", title: "Plant register", single: "plant",
  sub: "Fixed plant that makes something: batching plant, crusher, quarry, block plant. Machines that move earth belong in Equipment.",
  cols: [{ k: "code", label: "Code" }, { k: "name", label: "Name" },
    { label: "Kind", v: (r) => (PLANT_KINDS.find(([k]) => k === r.kind) || [, r.kind])[1] },
    { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "location", label: "Location" },
    { label: "Capacity", v: (r) => r.capacity ? fmtQty(r.capacity) + " " + (r.capacity_unit || "") : "" },
    { label: "Produces", v: (r) => nm.mat(r.output_material_id) },
    { k: "active", label: "Active", fmt: "yes" }],
  defaults: () => ({ kind: "batching", project_id: S.project }),
  fields: [{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true },
    { k: "kind", label: "Kind", type: "select", noBlank: true, options: PLANT_KINDS },
    { k: "project_id", label: "Project", type: "select", options: opt.projects },
    { k: "location", label: "Location on site" },
    { k: "capacity", label: "Rated capacity per hour", type: "number" },
    { k: "capacity_unit", label: "Capacity unit", ph: "m3, MT, nos" },
    { k: "output_material_id", label: "Material produced", type: "select", options: opt.materials, req: true },
    { k: "equipment_id", label: "Machine in the equipment register", type: "select", options: opt.equipment },
    { k: "power_kw", label: "Connected load (kW)", type: "number" },
    { k: "operator", label: "Plant in charge" }, { k: "commissioned", label: "Commissioned on", type: "date" },
    { k: "notes", label: "Notes", type: "textarea", wide: true }, { k: "active", label: "Active", type: "check" }],
});

/* ── mix designs ────────────────────────────────────────────────── */
PAGES["pl/mix"] = async (root) => {
  const plants = await run("plant.list", {});
  const rows = await run("mix.list", {});
  const edit = async (mix) => {
    const f = form([
      { k: "plant_id", label: "Plant", type: "select", noBlank: true, options: plants.map((p) => [p.id, p.code + " " + p.name]), req: true },
      { k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true },
      { k: "grade", label: "Grade / class", ph: "M25, 20 mm, A-class" },
      { k: "output_material_id", label: "Produces", type: "select", options: opt.materials, req: true },
      { k: "output_qty", label: "For this much output", type: "number" }, { k: "unit", label: "Unit" },
      { k: "approved_by", label: "Approved by" }, { k: "approved_date", label: "Approved on", type: "date" },
      { k: "remarks", label: "Remarks", wide: true }, { k: "active", label: "Active", type: "check" },
    ], mix || { output_qty: 1, unit: "m3", active: 1, plant_id: plants[0] && plants[0].id });
    const le = lineEditor([
      { k: "material_id", label: "Material", type: "select", options: opt.materials, w: 240, key: "material" },
      { label: "Unit", show: (r) => nm.unit(r.material_id) },
      { k: "qty_per_unit", label: "Per unit of output", type: "number", w: 110 },
      { k: "wastage_pct", label: "Wastage %", type: "number", w: 90 },
      { label: "Cost at standard rate", num: true, show: (r) => {
        const m = byId(S.L.materials, r.material_id);
        return m ? fmtMoney((Number(r.qty_per_unit) || 0) * (1 + (Number(r.wastage_pct) || 0) / 100) * (m.standard_rate || 0)) : "";
      } },
      { k: "remarks", label: "Remarks", w: 140 }], (mix && mix.lines) || []);
    modal(mix ? "Mix design " + mix.name : "New mix design", h("div", {},
      h("p", { class: "hint" }, "What one unit of output consumes. A production run is filled in from this, and the run can still be corrected before it is posted."),
      f, h("h4", { style: "margin:14px 0 6px" }, "Ingredients"), le),
      [{ label: "Save", cls: "primary", act: async () => {
        await run("mix.save", { header: Object.assign(f.values(), { id: mix && mix.id }), lines: le.lines() }, "Saved");
        go();
      } },
       mix ? { label: "Delete", cls: "warn", act: async () => {
         if (!(await ask("Delete", "Delete this mix design?", { danger: true, ok: "Delete" }))) return false;
         await run("mix.delete", { id: mix.id }, "Deleted"); go();
       } } : null]);
  };
  root.append(pageHead("Mix designs & recipes",
    "What the plant puts into one unit of what it makes. Used to prefill production runs and to check consumption.",
    can("plant", "edit") && plants.length ? h("button", { class: "btn primary", onclick: () => edit(null) }, "New mix design") : null));
  if (!plants.length) return root.append(h("div", { class: "panel" }, h("b", {}, "Add a plant first."),
    h("p", {}, "Plant register → New plant."), h("button", { class: "btn primary", onclick: () => { location.hash = "#/pl/register"; } }, "Plant register")));
  root.append(summaryStrip([["Mix designs", rows.length], ["Plants", plants.length]]));
  root.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "grade", label: "Grade" },
    { label: "Plant", v: (r) => (plants.find((p) => p.id === r.plant_id) || {}).name || "" },
    { label: "Produces", v: (r) => nm.mat(r.output_material_id) },
    { label: "Per", v: (r) => fmtQty(r.output_qty) + " " + (r.unit || "") },
    { label: "Ingredients", v: (r) => r.lines.length },
    { k: "material_cost", label: "Material cost / unit", fmt: "money" },
    { k: "active", label: "Active", fmt: "yes" }], rows,
    { name: "mix_designs", title: "Mix designs", onRow: edit, empty: "No mix designs yet." }));
};

/* ── production runs ────────────────────────────────────────────── */
async function runEditor(runRow) {
  const plants = await run("plant.list", {});
  if (!plants.length) return toast("Add a plant first.", "err");
  const mixes = await run("mix.list", {});
  const doc = runRow || { date: today(), shift: "day", status: "draft", lines: [], project_id: S.project,
    plant_id: plants[0].id, store_id: (opt.stores(S.project)[0] || [])[0] };
  const editable = doc.status === "draft" && can("plant", "edit");
  const mixOpts = () => mixes.filter((m) => !doc.plant_id || String(m.plant_id) === String(doc.plant_id))
    .map((m) => [m.id, m.code + " " + m.name + (m.grade ? " (" + m.grade + ")" : "")]);
  const hf = form([
    { k: "plant_id", label: "Plant", type: "select", noBlank: true, options: plants.map((p) => [p.id, p.code + " " + p.name]), req: true },
    { k: "date", label: "Date", type: "date", req: true },
    { k: "shift", label: "Shift", type: "select", noBlank: true, options: [["day", "Day"], ["night", "Night"]] },
    { k: "mix_id", label: "Mix design", type: "select", options: mixOpts },
    { k: "output_material_id", label: "Produced", type: "select", options: opt.materials, req: true },
    { k: "output_qty", label: "Quantity produced", type: "number", req: true },
    { k: "rejected_qty", label: "Rejected / wasted", type: "number" },
    { k: "store_id", label: "Into store", type: "select", options: () => opt.stores(S.project), req: true },
    { k: "run_hours", label: "Plant hours run", type: "number" },
    { k: "down_hours", label: "Breakdown hours", type: "number" },
    { k: "down_reason", label: "Reason for downtime" },
    { k: "power_units", label: "Power used (units)", type: "number" },
    { k: "diesel_qty", label: "Diesel used (litre)", type: "number" },
    { k: "labour_cost", label: "Plant crew cost", type: "number" },
    { k: "other_cost", label: "Other cost", type: "number" },
    { k: "boq_item_id", label: "For BOQ item (optional)", type: "select", options: () => opt.boq(S.project) },
    { k: "operator", label: "Operator" },
    { k: "remarks", label: "Remarks", wide: true },
  ].map((f) => Object.assign({}, f, { readonly: !editable })), doc, async () => {
    const v = hf.values();
    if (v.mix_id && String(v.mix_id) !== String(doc.mix_id || "") || (v.output_qty && !le.lines().length)) {
      doc.mix_id = v.mix_id;
      if (v.mix_id && Number(v.output_qty) > 0) {
        const pre = await api("run.prefill", { mix_id: v.mix_id, output_qty: v.output_qty });
        le.setLines(pre.lines);
        if (pre.output_material_id) hf.set("output_material_id", pre.output_material_id);
      }
    }
  });
  const le = lineEditor([
    { k: "material_id", label: "Raw material", type: "select", options: opt.materials, w: 240, key: "material" },
    { label: "Unit", show: (r) => nm.unit(r.material_id) },
    { k: "planned_qty", label: "Should use", type: "number", w: 100, readonly: true },
    { k: "qty", label: "Actually used", type: "number", w: 110 },
    { label: "Difference", num: true, show: (r) => r.planned_qty ? fmtQty((Number(r.qty) || 0) - Number(r.planned_qty)) : "" },
    { k: "rate", label: "Rate", type: "number", readonly: true },
    { k: "amount", label: "Value", type: "number", readonly: true },
  ], doc.lines, { readonly: !editable });
  const body = h("div", {},
    h("p", { class: "hint" }, "The raw material leaves the store and the finished material comes back in at what it "
      + "really cost: material + power + fuel + crew + the plant's own hourly rate."),
    hf, h("h4", { style: "margin:14px 0 6px" }, "Raw material consumed"), le,
    doc.status === "posted" ? h("div", { class: "panel" }, h("h2", {}, "What it cost"),
      kv([["Material", fmtMoney(doc.material_cost)], ["Running cost", fmtMoney(doc.other_cost)],
          ["Total", fmtMoney(doc.total_cost)], ["Cost per unit", fmtMoney(doc.unit_cost)],
          ["Voucher", doc.voucher_id ? drillTo("voucher", doc.voucher_id, "Open") : "—"]])) : null);
  const btns = [];
  const save = async () => {
    const d = await run("run.save", { header: Object.assign(hf.values(), { id: doc.id, project_id: S.project }),
      lines: le.lines() }, "Saved");
    doc.id = d.id;
    return d;
  };
  if (editable) {
    btns.push({ label: "Save draft", act: async () => { await save(); m.close(); go(); } });
    btns.push({ label: "Post production", cls: "primary", act: async () => {
      await save();
      const r = await run("run.post", { id: doc.id },
        (d) => "Produced " + fmtQty(d.produced) + " at " + fmtMoney(d.unit_cost) + " per unit");
      m.close(); go();
      return r;
    } });
  }
  if (doc.status === "posted" && can("plant", "approve")) {
    btns.push({ label: "Reverse", cls: "warn", act: async () => {
      if (!(await ask("Reverse production", "Put the raw material back and take the output out of stock?", { danger: true, ok: "Reverse" }))) return false;
      await run("run.reverse", { id: doc.id }, "Reversed"); m.close(); go();
    } });
  }
  if (doc.id) btns.push({ label: "Record a test", act: async () => {
    const tf = form([{ k: "test_type", label: "Test", ph: "Cube 7 day, sieve analysis…" },
      { k: "sample_ref", label: "Sample reference" }, { k: "criteria", label: "Required" },
      { k: "result_value", label: "Result" },
      { k: "status", label: "Result", type: "select", noBlank: true, options: [["pending", "Awaiting"], ["passed", "Passed"], ["failed", "Failed"]] }], { status: "pending" });
    modal("Test on this production", tf, [{ label: "Save", cls: "primary", act: async () => {
      await run("run.test", Object.assign({ run_id: doc.id }, tf.values()), "Test recorded");
    } }], { narrow: true });
    return false;
  } });
  const m = modal("Production " + (doc.no || "(new)"), body, btns, { head: stamp(doc.status) });
}

PAGES["pl/runs"] = async (root, params) => {
  if (!S.project) { root.append(pageHead("Production runs"), projectNotice()); return; }
  let v = { from: monthAgo(), to: today(), status: "" };
  const holder = h("div");
  const load = async () => {
    const rows = await run("run.list", Object.assign({ project_id: S.project }, v));
    const plants = await run("plant.list", {});
    const posted = rows.filter((r) => r.status === "posted");
    holder.innerHTML = "";
    holder.append(summaryStrip([
      ["Runs", rows.length],
      ["Produced", fmtQty(posted.reduce((a, r) => a + (r.output_qty || 0) - (r.rejected_qty || 0), 0))],
      ["Rejected", fmtQty(posted.reduce((a, r) => a + (r.rejected_qty || 0), 0))],
      ["Cost", fmtMoney(posted.reduce((a, r) => a + (r.total_cost || 0), 0))],
      ["Plant hours", fmtQty(posted.reduce((a, r) => a + (r.run_hours || 0), 0))],
      ["Down hours", fmtQty(posted.reduce((a, r) => a + (r.down_hours || 0), 0))]]));
    holder.append(table([{ k: "no", label: "No.", v: (r) => r.no || "Draft #" + r.id }, { k: "date", label: "Date" },
      { k: "shift", label: "Shift" },
      { label: "Plant", v: (r) => (plants.find((p) => p.id === r.plant_id) || {}).name || "" },
      { label: "Produced", v: (r) => nm.mat(r.output_material_id) },
      { k: "output_qty", label: "Quantity", fmt: "qty" }, { k: "rejected_qty", label: "Rejected", fmt: "qty" },
      { k: "run_hours", label: "Hours", fmt: "qty" }, { k: "total_cost", label: "Cost", fmt: "money" },
      { k: "unit_cost", label: "Per unit", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
      rows, { name: "production_runs", title: "Production runs " + v.from + " to " + v.to,
              totals: ["output_qty", "total_cost"],
              onRow: async (r) => runEditor(await run("run.get", { id: r.id })),
              empty: "No production in this period." }));
  };
  root.append(pageHead("Production runs", "Every batch the plant made, what it consumed and what it cost.",
    can("plant", "edit") ? h("button", { class: "btn primary", onclick: () => runEditor(null) }, "New production run") : null),
    filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" },
      { k: "status", label: "Status", type: "select", options: [["draft", "Draft"], ["posted", "Posted"], ["reversed", "Reversed"]] }],
      v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.new) runEditor(null);
};

PAGES["pl/report"] = async (root) => {
  let v = { from: fyStart(), to: today() };
  const holder = h("div");
  const load = async () => {
    const rows = await run("plant.report", Object.assign({ project_id: S.project || null }, v));
    holder.innerHTML = "";
    holder.append(summaryStrip([["Plants", rows.length],
      ["Produced", fmtQty(rows.reduce((a, r) => a + r.produced, 0))],
      ["Production cost", fmtMoney(rows.reduce((a, r) => a + r.cost, 0))],
      ["Hours run", fmtQty(rows.reduce((a, r) => a + r.run_hours, 0))],
      ["Hours down", fmtQty(rows.reduce((a, r) => a + r.down_hours, 0))]]));
    holder.append(table([{ k: "code", label: "Plant" }, { k: "name", label: "Name" },
      { label: "Makes", v: (r) => r.output_name },
      { k: "runs", label: "Runs", fmt: "num" }, { k: "produced", label: "Produced", fmt: "qty" },
      { k: "rejected", label: "Rejected", fmt: "qty" }, { label: "Reject %", v: (r) => fmtPct(r.reject_pct) },
      { k: "material_cost", label: "Material", fmt: "money" }, { k: "running_cost", label: "Running", fmt: "money" },
      { k: "cost", label: "Total cost", fmt: "money" }, { k: "unit_cost", label: "Cost per unit", fmt: "money" },
      { k: "run_hours", label: "Hours", fmt: "qty" }, { k: "down_hours", label: "Down", fmt: "qty" },
      { label: "Availability", v: (r) => fmtPct(r.availability) },
      { label: "Output per hour", v: (r) => fmtQty(r.output_per_hour) },
      { label: "Of capacity", v: (r) => fmtPct(r.capacity_pct) }], rows,
      { name: "plant_performance", title: "Plant performance " + v.from + " to " + v.to,
        onRow: (r) => { location.hash = "#/pl/runs"; }, empty: "No production posted in this period." }));
  };
  root.append(pageHead("Plant performance", "Output, cost per unit, downtime and how close the plant runs to its rating."),
    filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], v, (x) => { v = x; load(); }), holder);
  await load();
};

/* ── asset register ─────────────────────────────────────────────── */
function assetDialog(asset) {
  const editable = can("assets", "edit") && (!asset || asset.status !== "disposed");
  const f = form([
    { k: "code", label: "Asset code", ph: "left blank = allotted automatically" },
    { k: "name", label: "Description", req: true },
    { k: "class", label: "Class", type: "select", noBlank: true, options: ASSET_CLASSES },
    { k: "category", label: "Category / sub-group" },
    { k: "project_id", label: "Project / office", type: "select", options: opt.projects },
    { k: "location", label: "Where it is kept" }, { k: "custodian", label: "Who holds it" },
    { k: "supplier_id", label: "Bought from", type: "select", options: () => opt.parties(["vendor"]) },
    { k: "invoice_no", label: "Bill number" }, { k: "purchase_date", label: "Bought on", type: "date" },
    { k: "purchase_value", label: "Cost", type: "number" },
    { k: "residual_value", label: "Residual value", type: "number" },
    { k: "dep_method", label: "Depreciation", type: "select", noBlank: true, options: [["slm", "Straight line"], ["wdv", "Written down value"]] },
    { k: "life_months", label: "Life (months)", type: "number" },
    { k: "wdv_rate", label: "WDV rate %", type: "number" },
    { k: "serial", label: "Serial / chassis no." },
    { k: "warranty_expiry", label: "Warranty until", type: "date" },
    { k: "insurance_policy", label: "Insurance policy" },
    { k: "insurance_expiry", label: "Insured until", type: "date" },
    { k: "condition", label: "Condition", type: "select", noBlank: true, options: CONDITIONS },
    { k: "status", label: "Status", type: "select", noBlank: true, options: ASSET_STATUS },
    { k: "remarks", label: "Remarks", type: "textarea", wide: true },
  ].map((x) => Object.assign({}, x, { readonly: !editable })),
    asset || { class: "furniture", dep_method: "slm", life_months: 60, condition: "good", status: "in_use",
               project_id: S.project, purchase_date: today() });
  const body = h("div", {}, f);
  if (asset) {
    body.append(summaryStrip([["Cost", fmtMoney(asset.purchase_value)],
      ["Depreciation to date", fmtMoney(asset.accumulated_dep)], ["Book value", fmtMoney(asset.book_value)],
      ["Age", asset.age_months != null ? asset.age_months + " months" : "—"],
      ["Last verified", asset.last_verified || "never"]]));
    body.append(h("h4", { style: "margin:14px 0 6px" }, "History"),
      table([{ k: "date", label: "Date" }, { k: "kind", label: "What happened" },
        { k: "from_location", label: "From" }, { k: "to_location", label: "To" },
        { k: "custodian", label: "Custodian" }, { k: "amount", label: "Amount", fmt: "money" },
        { k: "remarks", label: "Remarks" }], asset.moves || [], { search: false, export: false, empty: "Nothing yet." }));
    if ((asset.dep_schedule || []).length) {
      body.append(h("h4", { style: "margin:14px 0 6px" }, "Depreciation plan"),
        table([{ k: "year", label: "Year" }, { k: "charge", label: "Charge", fmt: "money" }],
          asset.dep_schedule, { search: false, export: false }));
    }
  }
  const btns = [];
  if (editable) {
    btns.push({ label: "Save", cls: "primary", act: async () => {
      await run("asset.save", { row: Object.assign(f.values(), { id: asset && asset.id }) }, "Saved"); go();
    } });
  }
  if (asset && can("assets", "edit") && asset.status !== "disposed") {
    btns.push({ label: "Hand over / move", act: async () => {
      const mf = form([{ k: "kind", label: "What is happening", type: "select", noBlank: true,
          options: [["custody", "Handed to another person"], ["transfer", "Moved to another site"],
                    ["verified", "Physically verified"], ["repair", "Sent for repair"], ["condition", "Condition changed"]] },
        { k: "date", label: "Date", type: "date" }, { k: "custodian", label: "New custodian" },
        { k: "location", label: "New location" },
        { k: "project_id", label: "New project / office", type: "select", options: opt.projects },
        { k: "condition", label: "Condition", type: "select", options: CONDITIONS },
        { k: "remarks", label: "Remarks", wide: true }], { kind: "custody", date: today() });
      modal("Move " + asset.code, mf, [{ label: "Record", cls: "primary", act: async () => {
        await run("asset.move", Object.assign({ id: asset.id }, mf.values()), "Recorded"); go();
      } }], { narrow: true });
      return false;
    } });
  }
  if (asset && can("assets", "approve") && asset.status !== "disposed") {
    btns.push({ label: "Dispose / scrap", cls: "warn", act: async () => {
      const df = form([{ k: "date", label: "Date", type: "date" },
        { k: "amount", label: "Money received", type: "number" },
        { k: "into", label: "Received into", type: "select", noBlank: true, options: [["bank", "Bank"], ["cash", "Cash"]] },
        { k: "remarks", label: "Remarks", wide: true }], { date: today(), into: "bank" });
      modal("Dispose " + asset.code, h("div", {},
        h("p", {}, "Book value now: ", h("b", {}, fmtMoney(asset.book_value)),
          ". The difference against what you receive is posted as a gain or a loss."), df),
        [{ label: "Post disposal", cls: "primary", act: async () => {
          await run("asset.dispose", Object.assign({ id: asset.id }, df.values()),
            (d) => (d.gain >= 0 ? "Gain " : "Loss ") + fmtMoney(Math.abs(d.gain)) + " posted");
          go();
        } }], { narrow: true });
      return false;
    } });
  }
  modal(asset ? asset.code + " " + asset.name : "New asset", body, btns, { narrow: !asset });
}

PAGES["as/register"] = async (root, params) => {
  let v = { class: params.class || "", status: params.status || "", project_id: "" };
  const holder = h("div");
  const load = async () => {
    const [rows, sum] = await Promise.all([run("asset.list", v), run("asset.summary", v)]);
    holder.innerHTML = "";
    holder.append(summaryStrip([["Assets", sum.count], ["Cost", fmtMoney(sum.cost)],
      ["Depreciation", fmtMoney(sum.dep)], ["Book value", fmtMoney(sum.book)],
      ["Needing attention", sum.alerts.length], ["Disposed", sum.disposed]]));
    holder.append(h("div", { class: "cols" },
      h("div", { class: "panel" }, h("h2", {}, "By class"),
        table([{ label: "Class", v: (r) => (ASSET_CLASSES.find(([k]) => k === r.class) || [, r.class])[1] },
          { k: "count", label: "Count", fmt: "num" }, { k: "cost", label: "Cost", fmt: "money" },
          { k: "dep", label: "Depreciation", fmt: "money" }, { k: "book", label: "Book value", fmt: "money" }],
          sum.by_class, { search: false, name: "assets_by_class", title: "Assets by class",
            totals: ["count", "cost", "dep", "book"],
            onRow: (r) => { v = Object.assign({}, v, { class: r.class }); load(); } })),
      h("div", { class: "panel" }, h("h2", {}, "Needs attention"),
        table([{ k: "code", label: "Asset" }, { k: "name", label: "Description" }, { k: "why", label: "Why" }],
          sum.alerts, { search: false, export: false, empty: "Nothing outstanding.",
            onRow: async (r) => assetDialog(await run("asset.get", { id: r.id })) }))));
    holder.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Description" },
      { label: "Class", v: (r) => (ASSET_CLASSES.find(([k]) => k === r.class) || [, r.class])[1] },
      { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "location", label: "Location" },
      { k: "custodian", label: "Custodian" }, { k: "purchase_date", label: "Bought" },
      { k: "purchase_value", label: "Cost", fmt: "money" },
      { k: "accumulated_dep", label: "Depreciation", fmt: "money" },
      { k: "book_value", label: "Book value", fmt: "money" },
      { k: "condition", label: "Condition" }, { k: "status", label: "Status", fmt: "status" },
      { k: "insurance_expiry", label: "Insured to" }], rows,
      { name: "asset_register", title: "Asset register", totals: ["purchase_value", "accumulated_dep", "book_value"],
        rowClass: (r) => r.status === "disposed" ? "muted" : (r.insurance_due ? "flag" : ""),
        onRow: async (r) => assetDialog(await run("asset.get", { id: r.id })),
        empty: "No assets recorded yet." }));
  };
  root.append(pageHead("Asset register",
    "Everything the company owns that is not construction equipment and not stock: land, buildings, camp, vehicles, furniture, computers and instruments.",
    can("assets", "edit") ? h("button", { class: "btn primary", onclick: () => assetDialog(null) }, "New asset") : null),
    filterBar([{ k: "class", label: "Class", type: "select", options: ASSET_CLASSES, blank: "All classes" },
      { k: "status", label: "Status", type: "select", options: ASSET_STATUS, blank: "All" },
      { k: "project_id", label: "Project", type: "select", options: opt.projects, blank: "All" },
      { k: "q", label: "Search", ph: "code, name, custodian, serial" }], v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.new) assetDialog(null);
};

PAGES["as/dep"] = async (root) => {
  let v = { month: today().slice(0, 7) };
  const holder = h("div");
  const load = async () => {
    const d = await run("asset.dep_preview", v);
    holder.innerHTML = "";
    holder.append(summaryStrip([["Month", d.month], ["Assets", d.rows.length], ["Charge", fmtMoney(d.total)],
      ["Already posted", d.already_posted ? "yes" : "no"]]));
    holder.append(table([{ k: "code", label: "Asset" }, { k: "name", label: "Description" },
      { k: "class", label: "Class" }, { label: "Project", v: (r) => nm.pcode(r.project_id) },
      { k: "method", label: "Method" }, { k: "book_value", label: "Book value", fmt: "money" },
      { k: "charge", label: "This month", fmt: "money" }], d.rows,
      { name: "asset_depreciation", title: "Asset depreciation " + d.month, totals: ["charge"],
        empty: "Nothing to depreciate." }));
    holder.append(h("div", { class: "actions" },
      can("assets", "approve") && d.rows.length && !d.already_posted
        ? h("button", { class: "btn primary", onclick: async () => {
          await run("asset.dep_run", v, (x) => "Posted " + fmtMoney(x.total)); load();
        } }, "Post depreciation for " + d.month)
        : h("span", { class: "muted" }, d.already_posted ? "This month is already posted." : "")));
  };
  root.append(pageHead("Asset depreciation",
    "One month at a time, straight line or written down value. Land is never depreciated. Posts to Depreciation and Accumulated depreciation."),
    filterBar([{ k: "month", label: "Month", type: "month" }], v, (x) => { v = x; load(); }), holder);
  await load();
};
