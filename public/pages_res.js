/* BuildCore 2.0 — resources and materials inside existing screens:
   Schedule & WBS › Resources, Material forecast › Material plan & Reorder points,
   Material reconciliation › Theoretical vs actual, Vendor performance › Lead times,
   Labour trades › Labour burden. */
(function () {
  "use strict";
  const COLORS = ["#1b5e86", "#d9950f", "#2f7a4d", "#b3392c", "#6b4c9a", "#0f8b8d", "#8a5d00", "#5b6970", "#c05780", "#3c8dbc"];
  /* stacked or grouped SVG bars; series = [{name, values}] */
  function bars(labels, series, o) {
    o = o || {};
    const W = 760, H = o.height || 240, P = 36;
    const n = labels.length || 1;
    const tot = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
    const max = Math.max(1, o.max || 0, ...(o.stacked === false ? series.flatMap((s) => s.values) : tot), o.limit || 0);
    const bw = (W - 2 * P) / n;
    let inner = "";
    for (let g = 0; g <= 4; g++) { const v = max * g / 4; const y = H - P - (H - 2 * P) * v / max; inner += `<line x1="${P}" x2="${W - P}" y1="${y}" y2="${y}" class="grid"/><text x="2" y="${y + 4}" class="ax">${Math.round(v)}</text>`; }
    labels.forEach((l, i) => {
      let acc = 0;
      series.forEach((s, k) => {
        const v = s.values[i] || 0; if (!v) return;
        const h0 = (H - 2 * P) * v / max, y = H - P - (H - 2 * P) * acc / max - h0;
        inner += `<rect x="${P + i * bw + 1}" y="${y}" width="${Math.max(1, bw - 2)}" height="${h0}" fill="${s.color || COLORS[k % COLORS.length]}"><title>${l}: ${s.name} ${Math.round(v * 10) / 10}</title></rect>`;
        acc += v;
      });
      const step = Math.max(1, Math.ceil(n / 12));
      if (i % step === 0) inner += `<text x="${P + i * bw + bw / 2}" y="${H - 12}" class="ax" text-anchor="middle">${l}</text>`;
    });
    if (o.limit) { const y = H - P - (H - 2 * P) * o.limit / max; inner += `<line x1="${P}" x2="${W - P}" y1="${y}" y2="${y}" stroke="#b3392c" stroke-dasharray="5 4" stroke-width="2"/>`; }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "chart"); svg.innerHTML = inner;
    return h("div", {}, svg, h("div", { class: "legend" }, series.map((s, k) => h("span", {}, h("i", { style: "height:10px;background:" + (s.color || COLORS[k % COLORS.length]) }), s.name))));
  }
  window.bcoBars = bars;

  /* ── Schedule & WBS › Resources ── */
  async function resourcesTab() {
    const box = h("div");
    let kind = "L", basis = "early";
    const editable = can("project", "edit");
    const load = async () => {
      box.innerHTML = "";
      const d = await api("res.histogram", { project_id: S.project, kind, basis });
      const ksel = h("select", { onchange: (e) => { kind = e.target.value; load(); } }, [["L", "Labour (workers on site)"], ["E", "Machines working"], ["M", "Materials (quantity a day)"]].map(([v, l]) => h("option", { value: v, selected: v === kind }, l)));
      const bsel = h("select", { onchange: (e) => { basis = e.target.value; load(); } }, [["early", "Early start"], ["late", "Late start"]].map(([v, l]) => h("option", { value: v, selected: v === basis }, l)));
      box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Show"), ksel), h("label", { class: "f" }, h("span", {}, "Dates"), bsel), h("div", { class: "grow" }),
        editable ? h("button", { class: "btn primary", onclick: async () => {
          if (!(await ask("Load resources", "Load labour, machines and materials on every activity from its norm (activity norm code or the BOQ item's saved rate analysis). Where there is no norm, the BOQ rate analysis man-hours and machine-hours are split by the trade and machine mix in the DPRs. Lines you typed by hand are kept."))) return;
          const r = await run("res.load", { project_id: S.project }); toast("From norms " + r.norm + ", from BOQ rate analysis " + r.rate_analysis + ", nothing to load " + r.none, "ok"); load();
        } }, "Load resources from norms") : null));
      if (!d.series.length) { box.append(h("div", { class: "panel" }, d.note || "No remaining work with resources.")); return; }
      const top = d.series.slice(0, 8);
      box.append(h("div", { class: "panel" }, h("h2", {}, "Histogram — " + d.measure + " (average per working day each week, remaining work)"),
        bars(d.weeks.map((w) => w.slice(2)), top.map((s) => ({ name: s.name, values: s.weekly })))),
      table([{ k: "name", label: "Resource" }, { k: "unit", label: "Unit" }, { k: "peak", label: "Peak", fmt: "num" }, { k: "avg", label: "Average (weeks worked)", fmt: "num" }, { k: "total", label: "Total remaining (" + (kind === "M" ? "qty" : "hours / days as loaded") + ")", fmt: "qty" }], d.series, { name: "resource_histogram" }));
      if (kind !== "M" && editable) {
        const lv = h("div", { class: "panel" }, h("h2", {}, "Leveling (finish date fixed)"),
          h("p", { class: "hint" }, "Moves non-critical activities inside their float to flatten the peaks (minimum-moment method): less hiring and laying off of short-term workers and fewer extra hired machines. Preview first; applying sets start-no-earlier-than dates, then recalculate."));
        const lvOut = h("div");
        const doLevel = async (apply) => {
          const r = await run("res.level", { project_id: S.project, kind, apply: apply ? 1 : 0 }, apply ? "Leveling applied — recalculating" : null);
          if (apply) { await run("sched.calc", { project_id: S.project }); go(); return; }
          lvOut.innerHTML = "";
          lvOut.append(table([{ k: "ref", label: "Resource" }, { label: "Peak before", fmt: "num", v: (x) => fmtN(x.before, 1) }, { label: "Peak after", fmt: "num", v: (x) => fmtN(x.after, 1) }],
            Object.keys(r.peaks_before).map((k) => ({ ref: (d.series.find((s) => s.ref === k) || {}).name || k, before: r.peaks_before[k], after: r.peaks_after[k] })), { search: false, export: false }),
          h("p", {}, r.moves.length + " activities move; finish stays " + r.finish + "."),
          table([{ label: "Activity", v: (x) => (x.code || "") + " " + x.name }, { k: "from", label: "Now starts" }, { k: "to", label: "Leveled start" }, { k: "shift_days", label: "Working days later", fmt: "num" }], r.moves, { search: false, name: "leveling" }),
          r.moves.length ? h("button", { class: "btn primary", onclick: () => doLevel(true) }, "Apply leveling") : "");
        };
        lv.append(h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => doLevel(false) }, "Preview leveling"),
          h("button", { class: "btn", onclick: async () => { const r = await run("res.clear_leveling", { project_id: S.project }); toast(r.cleared + " leveling dates removed", "ok"); await run("sched.calc", { project_id: S.project }); go(); } }, "Remove leveling dates")), lvOut);
        const resSel = h("select", {}, d.series.map((s) => h("option", { value: s.ref }, s.name)));
        const lim = h("input", { type: "number", step: "any", value: 1, style: "max-width:110px" });
        const alOut = h("div");
        const doAlloc = async (apply) => {
          const r = await run("res.allocate", { project_id: S.project, kind, limits: { [resSel.value]: lim.value }, apply: apply ? 1 : 0 });
          if (apply) { await run("sched.calc", { project_id: S.project }); toast("Allocation applied", "ok"); go(); return; }
          alOut.innerHTML = "";
          alOut.append(h("p", {}, "With at most " + lim.value + " × " + resSel.selectedOptions[0].textContent + ", the work finishes " + r.finish + " instead of " + r.base_finish + (r.delay_days > 0 ? " — " + r.delay_days + " working days later." : " — no delay.")),
            table([{ label: "Activity", v: (x) => (x.code || "") + " " + x.name }, { k: "from", label: "Now starts" }, { k: "to", label: "Starts when the resource is free" }, { k: "shift_days", label: "Delay (working days)", fmt: "num" }], r.moves, { search: false, name: "allocation" }),
            r.moves.length ? h("button", { class: "btn primary", onclick: () => doAlloc(true) }, "Apply to the schedule") : null);
        };
        const al = h("div", { class: "panel" }, h("h2", {}, "Limited resources (Brooks' method)"),
          h("p", { class: "hint" }, "When a crew or machine type is capped (e.g. one drilling jumbo), activities are ranked by late start and started as the resource frees up; the finish moves if it has to."),
          h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Resource"), resSel), h("label", { class: "f" }, h("span", {}, "Available at once"), lim), h("button", { class: "btn", onclick: () => doAlloc(false) }, "Test the limit")), alOut);
        box.append(h("div", { class: "cols" }, lv, al));
      }
      // resource lines per activity
      const rl = await api("res.list", { project_id: S.project });
      box.append(h("h2", { class: "sec" }, "Resources on each activity"), table([{ label: "Activity", v: (r) => (r.act_code || "") + " " + r.act_name }, { k: "kind", label: "Type" }, { k: "name", label: "Resource" }, { k: "qty_total", label: "Total", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "source", label: "From" },
        { label: "", v: (r) => editable && r.source === "manual" ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("res.delete", { id: r.id }); load(); } }, "Remove") : "" }], rl.filter((r) => r.kind === kind || kind === "M" && r.kind === "M"), { name: "activity_resources" }));
      if (editable) {
        const f = form([{ k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), search: true }, { k: "kind", label: "Type", type: "select", noBlank: true, options: [["L", "Labour"], ["E", "Machine"], ["M", "Material"]], default: kind },
          { k: "name", label: "Resource (e.g. Drilling jumbo, Miner)" }, { k: "qty_total", label: "Total quantity for the activity", type: "number" }, { k: "unit", label: "Unit (day, hr, m3, bag…)" },
          { k: "material_id", label: "Store material (for the material plan)", type: "select", options: opt.materials }]);
        box.append(h("div", { class: "panel" }, h("h3", {}, "Add a resource by hand"), f, h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("res.save", { row: f.values() }, "Added"); load(); } }, "Add"))));
      }
    };
    await load();
    return box;
  }
  window.SCHED_TABS = (window.SCHED_TABS || []).concat([["Resources", resourcesTab]]);

  /* ── Material forecast › Material plan (MRP) and reorder points ── */
  async function mrpTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const d = await api("res.mrp", { project_id: S.project, weeks: 16 });
    const pick = new Set();
    const editable = can("procurement", "edit");
    box.append(h("p", { class: "hint" }, "Demand = remaining quantity of each activity × material coefficient of its BOQ item (or its norm), placed on the CPM dates (data date " + d.data_date + "). Net of stock and open POs; the order-by date is the first week the balance falls below safety stock, less the measured lead time and " + d.safety_days + " safety days. Suggested quantity covers " + d.cover_weeks + " weeks."));
    const rows = d.rows;
    box.append(table([
      { label: "", v: (r) => editable && r.suggested_qty > 0 ? h("input", { type: "checkbox", style: "width:auto", onclick: (e) => { e.stopPropagation(); if (e.target.checked) pick.add(r.material_id); else pick.delete(r.material_id); } }) : "" },
      { k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "unit", label: "Unit" }, { k: "stock", label: "Stock", fmt: "qty" }, { k: "on_order", label: "On order", fmt: "qty" }, { k: "open_pr", label: "In open PRs", fmt: "qty" },
      { k: "demand_horizon", label: "Demand 16 weeks", fmt: "qty" }, { label: "Lead (d)", v: (r) => fmtN(r.lead_avg, 0) + (r.lead_measured ? "" : " typed") }, { k: "safety", label: "Safety stock", fmt: "qty" },
      { k: "need_date", label: "Short from" }, { label: "Order by", v: (r) => r.order_by ? h("b", { class: r.urgency === "late" ? "red" : r.urgency === "now" ? "" : "green" }, r.order_by) : "—" },
      { k: "suggested_qty", label: "Suggested qty", fmt: "qty" }],
    rows, { name: "material_plan", rowClass: (r) => r.urgency === "late" ? "bad" : r.urgency === "now" ? "flag" : "", onRow: (r) => detail(r), empty: "No schedule demand. Link activities to BOQ items that have material coefficients, and calculate the schedule." }));
    if (editable && rows.some((r) => r.suggested_qty > 0)) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const sel = rows.filter((r) => pick.has(r.material_id)).map((r) => ({ material_id: r.material_id, qty: r.suggested_qty, need_date: r.need_date }));
      if (!sel.length) return toast("Tick the materials to order.", "err");
      const pr = await run("res.mrp_to_pr", { project_id: S.project, rows: sel }, "Purchase request raised");
      location.hash = "#/proc/pr";
      return pr;
    } }, "Raise a purchase request for the ticked lines")));
    const detail = (r) => modal(r.code + " " + r.name + " — weekly plan", h("div", {}, bars(r.weeks.map((w) => w.week.slice(5)), [{ name: "Demand", values: r.weeks.map((w) => w.demand) }, { name: "Receipts", color: "#2f7a4d", values: r.weeks.map((w) => w.receipts) }], { stacked: false }),
      table([{ k: "week", label: "Week" }, { k: "demand", label: "Demand", fmt: "qty" }, { k: "receipts", label: "Receipts", fmt: "qty" }, { k: "balance", label: "Projected balance", fmt: "qty" }], r.weeks, { search: false, rowClass: (w) => w.balance < r.safety ? "bad" : "" })), []);
    return box;
  }
  async function ropTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const load = async () => {
      const d = await api("res.rop", { project_id: S.project });
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Reorder point = daily demand × average lead time + safety stock. Demand comes from the schedule for the next 30 days when there is one (else the last 90 days of issues); lead time and its worst case come from your POs and GRNs."),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "unit", label: "Unit" }, { k: "basis", label: "Demand from" }, { k: "daily_schedule", label: "Per day (schedule)", fmt: "qty" }, { k: "daily_history", label: "Per day (history)", fmt: "qty" },
          { label: "Lead avg / max", v: (r) => fmtN(r.lead_avg, 1) + " / " + fmtN(r.lead_max, 0) + (r.lead_measured ? "" : " (typed)") }, { k: "safety", label: "Safety", fmt: "qty" }, { k: "rop", label: "New reorder point", fmt: "qty" }, { k: "current_rop", label: "Now", fmt: "qty" }, { k: "stock", label: "Stock", fmt: "qty" }],
        d.rows, { name: "reorder_points", rowClass: (r) => r.stock < r.rop ? "flag" : "" }),
        can("inventory", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { const r = await run("res.rop", { project_id: S.project, apply: 1 }); toast(r.updated + " reorder levels updated", "ok"); load(); } }, "Use these reorder points")) : "");
    };
    await load();
    return box;
  }
  bcoTabbed("inv/risk", "Material forecast & planning", "Shortage risk now reads schedule demand and measured lead times. The material plan orders from the CPM dates.",
    { firstLabel: "Shortage risk", tabs: [["Material plan (MRP)", mrpTab], ["Reorder points", ropTab]] });

  /* ── Material reconciliation › Theoretical vs actual ── */
  async function consumptionTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    let v = { basis: "executed", month: "" };
    const load = async () => {
      const d = await api("res.consumption", Object.assign({ project_id: S.project }, v));
      box.innerHTML = "";
      const f = form([{ k: "basis", label: "Work done", type: "select", noBlank: true, options: [["executed", "Executed (approved DPRs)"], ["measured", "Verified measurement"]] },
        { k: "month", label: "Month", type: "select", options: d.months.map((m) => [m, m]), blank: "To date" }], v);
      f.className = "bar";
      f.append(h("button", { class: "btn primary", onclick: () => { v = f.values(); load(); } }, "Show"));
      box.append(f, h("p", { class: "hint" }, "Theoretical = work done × coefficient. Allowed = theoretical + the wastage allowed on the coefficient. Beyond the allowance plus " + d.tolerance + "% tolerance is abnormal waste (NAS 2 para 16a): expense it and keep it out of the cost used for progress. A month's figures depend on when material was issued against when the work was reported."),
        h("div", { class: "tiles" }, tile("Abnormal waste", fmtMoney(d.abnormal_total), { cls: d.abnormal_total > 0 ? "bad" : "" }), ...d.materials.slice(0, 4).map((m) => tile(m.mat_name, m.wastage_pct == null ? "—" : m.wastage_pct + "%", { sub: "material CPI " + fmtN(m.mat_cpi) }))),
        h("h2", { class: "sec" }, "By material"),
        table([{ k: "mat_code", label: "Code" }, { k: "mat_name", label: "Material" }, { k: "unit", label: "Unit" }, { k: "theoretical", label: "Theoretical", fmt: "qty" }, { k: "allowed", label: "Allowed", fmt: "qty" }, { k: "actual", label: "Issued (net)", fmt: "qty" },
          { label: "Wastage %", v: (r) => r.wastage_pct == null ? "—" : r.wastage_pct + "%" }, { label: "Material CPI", v: (r) => fmtN(r.mat_cpi) }, { k: "variance_value", label: "Over (−under) allowance", fmt: "money" }, { k: "abnormal_value", label: "Abnormal waste", fmt: "money" }],
        d.materials, { name: "consumption_by_material", totals: ["variance_value", "abnormal_value"], rowClass: (r) => r.abnormal_value > 0 ? "flag" : "" }),
        h("h2", { class: "sec" }, "By BOQ item"),
        table([{ k: "boq_code", label: "BOQ" }, { label: "Item", v: (r) => (r.description || "").slice(0, 50) }, { k: "mat_name", label: "Material" }, { label: "Work done", v: (r) => fmtN(r.work_done) + " " + (r.boq_unit || "") }, { k: "coefficient", label: "Coef.", fmt: "qty" },
          { k: "theoretical", label: "Theoretical", fmt: "qty" }, { k: "actual", label: "Issued", fmt: "qty" }, { label: "Wastage %", v: (r) => r.wastage_pct == null ? "—" : r.wastage_pct + "% (allowed " + fmtN(r.allowed_pct) + ")" },
          { k: "abnormal_value", label: "Abnormal", fmt: "money" }, { label: "Cause", v: (r) => r.cause ? (d.causes.find((x) => x[0] === r.cause) || [0, r.cause])[1] : (r.flag && can("inventory", "edit") ? h("select", { onclick: (e) => e.stopPropagation(), onchange: async (e) => { await run("res.cause_save", { row: { project_id: S.project, boq_item_id: r.boq_item_id, material_id: r.material_id, month: v.month, cause: e.target.value, value: r.abnormal_value || r.variance_value } }, "Cause recorded"); } }, h("option", { value: "" }, "— give a cause —"), d.causes.map(([k, l]) => h("option", { value: k }, l))) : "") }],
        d.rows, { name: "consumption_by_item", totals: ["abnormal_value"], rowClass: (r) => r.flag ? "flag" : "" }));
      if (d.abnormal_total > 0 && can("accounts", "edit") && !v.month) box.append(h("div", { class: "actions" }, h("button", { class: "btn warn", onclick: async () => {
        if (!(await ask("Post abnormal waste", "Post " + fmtMoney(d.abnormal_total) + " as a period expense (abnormal material waste) and take it out of this project's material cost?", { danger: true, ok: "Post" }))) return;
        await run("res.post_waste", { project_id: S.project, rows: d.rows.filter((r) => r.abnormal_value > 0).map((r) => ({ boq_item_id: r.boq_item_id, value: r.abnormal_value, label: r.boq_code + " " + r.mat_name })) }, "Posted"); load();
      } }, "Post abnormal waste to expense")));
      const par = await api("res.cause_pareto", { project_id: S.project });
      if (par.length) box.append(h("div", { class: "panel" }, h("h2", {}, "Causes of wastage and shortage (Pareto)"), table([{ k: "label", label: "Cause" }, { k: "n", label: "Records", fmt: "num" }, { k: "v", label: "Value", fmt: "money" }, { label: "Cumulative", v: (r) => r.cum_pct + "%" }], par, { search: false, export: false })));
    };
    await load();
    return box;
  }
  bcoTabbed("inv/recon", "Material reconciliation", "Issued against theoretical use, per BOQ item and material.",
    { firstLabel: "Reconciliation", tabs: [["Theoretical vs actual & waste", consumptionTab]] });

  /* ── Vendor performance › lead times & scorecard ── */
  async function leadTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("res.leadtimes", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Measured from the PO date to the first goods received, for POs since " + d.since + ". On time = received by the PO delivery date. Score = 50% on time + 30% full supply + 20% quality (rejections)."),
        h("h2", { class: "sec" }, "Supplier scorecard"),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Supplier" }, { k: "po_lines", label: "PO lines", fmt: "num" }, { label: "Lead avg ± sd (max)", v: (r) => fmtN(r.avg_lead, 1) + " ± " + fmtN(r.sd_lead, 1) + " (" + fmtN(r.max_lead, 0) + ")" },
          { label: "On time", v: (r) => r.on_time_pct == null ? "—" : r.on_time_pct + "%" }, { label: "Short supply", v: (r) => r.short_supply_pct == null ? "—" : r.short_supply_pct + "%" }, { label: "Rejected", v: (r) => r.rejection_pct == null ? "—" : r.rejection_pct + "%" },
          { k: "score", label: "Score", fmt: "num" }, { label: "Grade", v: (r) => r.grade ? h("b", { class: r.grade === "A" ? "green" : r.grade === "D" ? "red" : "" }, r.grade) : "" }], d.vendors, { name: "supplier_scorecard" }),
        h("h2", { class: "sec" }, "Lead time by material"),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "orders", label: "Orders", fmt: "num" }, { k: "avg_lead", label: "Average (days)", fmt: "num" }, { k: "sd_lead", label: "Spread (sd)", fmt: "num" }, { k: "max_lead", label: "Longest", fmt: "num" }, { k: "typed_lead", label: "Lead time on the material", fmt: "num" }],
        d.materials, { name: "lead_times", rowClass: (r) => r.typed_lead != null && r.avg_lead != null && Math.abs(r.typed_lead - r.avg_lead) > 5 ? "flag" : "" }),
        can("inventory", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { const r = await run("res.leadtimes_apply", {}); toast(r.updated + " materials now use the measured lead time", "ok"); load(); } }, "Use measured lead times on the materials")) : "");
    };
    await load();
    return box;
  }
  bcoTabbed("proc/vendors", "Vendor performance", "Ratings, lead times and the supplier scorecard.", { firstLabel: "Ratings", tabs: [["Lead times & scorecard", leadTab]] });

  /* ── Labour trades › labour burden ── */
  async function burdenTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("burden.list", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Burdened hourly rate = everything a worker costs in a year ÷ productive hours. Applying it sets the trade's rate per hour, which DPR labour costing uses (the bare rate is kept). " + d.note),
        table([{ k: "name", label: "Trade" }, { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "All" }, { label: "Rate now / h", fmt: "money", v: (r) => r.rate_hour }, { label: "Bare rate / h", fmt: "money", v: (r) => r.calc ? r.calc.bare_hour : r.base_rate_hour },
          { label: "Burdened / h", fmt: "money", v: (r) => r.calc ? r.calc.burdened_hour : null }, { label: "Burden", v: (r) => r.calc && r.calc.burden_pct != null ? r.calc.burden_pct + "%" : "—" }, { label: "Applied", v: (r) => (r.applied || "").slice(0, 10) }],
        d.rows, { name: "labour_burden", onRow: (r) => edit(r, d) }));
    };
    const edit = (r, d) => {
      const f = form([{ k: "pay_basis", label: "Paid", type: "select", noBlank: true, options: [["monthly", "Monthly basic"], ["daily", "Daily wage (× 26 days)"]] },
        { k: "basic", label: "Basic wage (month or day)", type: "number", req: true }, { k: "allowance_month", label: "Allowances per month (site, food, dearness)", type: "number" },
        { k: "bonus_months", label: "Festival bonus (months of basic a year)", type: "number" }, { k: "ssf_employer_pct", label: "SSF employer share % of basic [confirm]", type: "number" },
        { k: "insurance_year", label: "Accident & medical insurance per year", type: "number" }, { k: "ppe_year", label: "PPE and tools per year", type: "number" }, { k: "other_year", label: "Other per year (camp, travel, training)", type: "number" },
        { k: "working_days_year", label: "Days worked a year", type: "number" }, { k: "hours_day", label: "Hours a day", type: "number" }, { k: "productive_pct", label: "Productive share of hours %", type: "number" },
        { k: "pool_code", label: "Resource pool labour code to update (optional, e.g. L-001)" }, { k: "remarks", label: "Remarks", wide: true }],
      Object.assign({}, d.defaults, { pay_basis: "daily", productive_pct: 100 }, r));
      const out = h("div", { class: "panel" });
      const calc = async () => {
        const c = await api("burden.calc", { row: f.values() });
        out.innerHTML = "";
        out.append(table([{ k: "k", label: "Cost a year" }, { k: "v", label: "Amount", fmt: "money" }], Object.entries(c.parts).map(([k, v]) => ({ k, v })).concat([{ k: "Total", v: c.annual_cost }]), { search: false, export: false }),
          kv([["Productive hours a year", fmtN(c.productive_hours)], ["Bare rate per hour", fmtMoney(c.bare_hour)], ["Burdened rate per hour", h("b", {}, fmtMoney(c.burdened_hour))], ["Burdened rate per day", fmtMoney(c.burdened_day)], ["Burden on the bare rate", (c.burden_pct ?? "—") + "%"]]));
      };
      f.addEventListener("change", calc);
      calc();
      modal("Labour burden — " + r.name, h("div", {}, f, out), can("project", "edit") ? [
        { label: "Save", act: async () => { await run("burden.save", { row: Object.assign(f.values(), { trade_id: r.trade_id }) }, "Saved"); load(); } },
        { label: "Save and use this rate", cls: "primary", act: async () => { await run("burden.save", { row: Object.assign(f.values(), { trade_id: r.trade_id }), apply: 1 }, "Trade rate updated"); await loadProjectLists(); load(); } }] : []);
    };
    await load();
    return box;
  }
  bcoTabbed("m/trades", "Labour trades & rates", "Hourly rates used to cost DPR labour. Overtime is costed at 1.5×. Use the labour burden tab to set burdened rates.", { firstLabel: "Trades", tabs: [["Labour burden", burdenTab]] });
})();
