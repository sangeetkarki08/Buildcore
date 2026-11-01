/* The machine logsheet: one machine, one month, one signed sheet. */
"use strict";

const SHEET_KINDS = [
  ["owned", "Company machine"], ["rental", "Rented machine"], ["hired_out", "Working for another company"],
  ["vehicle", "Vehicle, tipper or transit mixer"], ["genset", "Generator"], ["drilling", "Drilling jumbo"],
  ["dewatering", "Dewatering pump"], ["hoist", "Hoist or lift"],
];
const METER_KINDS = [
  ["hour", "Hour meter"], ["km", "Kilometre"], ["kwh", "Energy meter (kW)"], ["boom1", "Boom 1"],
  ["boom2", "Boom 2"], ["drum", "Drum / batch counter"], ["strokes", "Strokes"], ["load", "Load counter"],
  ["pump", "Pump running"],
];
const METER_UNIT = { hour: "h", km: "km", kwh: "kWh", boom1: "h", boom2: "h", drum: "no", strokes: "no", load: "no", pump: "h" };
const CHECK_RESULTS = [["ok", "OK"], ["low", "Low"], ["topped_up", "Filled"], ["repair", "Repair"], ["na", "n/a"]];
const CHECK_MARK = { ok: "✓", low: "L", topped_up: "T", repair: "✗", na: "–" };

function meterLabel(code) { return (METER_KINDS.find(([k]) => k === code) || [null, code])[1]; }
function thisPeriod() { return today().slice(0, 7); }
function periodName(p) {
  if (!p) return "";
  const d = new Date(Number(p.slice(0, 4)), Number(p.slice(5, 7)) - 1, 1);
  const n = d.toLocaleString("en-GB", { month: "long", year: "numeric" });
  if (typeof window.bcoNepaliMonths === "function" && window.bcoNepaliMonths() && typeof window.bcoBsSpan === "function") {
    const last = new Date(Date.UTC(d.getFullYear(), d.getMonth() + 1, 0)).toISOString().slice(0, 10);
    const span = window.bcoBsSpan(p.slice(0, 7) + "-01", last);
    if (span) return n + " (" + span + ")";
  }
  return n;
}

/* the sheet's month as written on it; with Nepali dates the Nepali days it covers are added (2.30) */
function sheetMonth(b) {
  if (b.calendar === "bs") return (b.month_name || b.period_label) + " (" + b.english_span + ")";   /* 2.32: a Nepali-month sheet */
  const n = b.period_label || periodName(b.period);
  if (!b.period_label || /\(/.test(n) || !(typeof window.bcoNepaliMonths === "function" && window.bcoNepaliMonths()) || typeof window.bcoBsSpan !== "function") return n;
  const span = window.bcoBsSpan(b.from_date, b.to_date);
  return span ? n + " (" + span + ")" : n;
}

/* ── the register of monthly sheets ── */
/* 2.30: with Nepali dates the month is a Nepali month, the total row has the days, and days an approved DPR added after
   a sheet was approved are shown as waiting for that sheet.
   2.32: sheets can be kept per Nepali month (an administrator chooses once); the register shows the same figures as
   the sheet itself, and machine lines on DPRs not approved yet are shown apart. */
let LB_CAL = null;
async function lbCalendar(fresh) {
  if (!LB_CAL || fresh) { try { LB_CAL = await api("lb.calendar", {}); } catch (e) { LB_CAL = { calendar: "ad", preview: {} }; } }
  return LB_CAL;
}
const nepaliDates = () => typeof window.bcoNepaliMonths === "function" && window.bcoNepaliMonths();
function bsKeyOf(iso) { const r = window.bcoBsRange && window.bcoBsRange(iso); return r ? r.key : null; }

PAGES["eq/books"] = async (root, params) => {
  const cal = (await lbCalendar(true)).calendar;
  const nepali = nepaliDates();
  if ((cal === "bs" || nepali) && window.bcoLoadBS) await window.bcoLoadBS();
  // bs: Nepali-month sheets; range: a Nepali month read across English-month sheets; otherwise an English month
  let mode = cal === "bs" ? "bs" : (nepali && typeof window.bcoMonthBox === "function" ? "range" : "ad");
  let v = { period: params.period || thisPeriod(), status: "", sheet_type: "" };
  let range = null;
  if (mode === "bs") {
    const explicit = params.period && /^BS/i.test(params.period);
    v.period = explicit ? params.period : "BS" + bsKeyOf(params.period ? params.period.slice(0, 7) + "-15" : today());
    if (!explicit) {
      const first = await run("rep.logbooks", { project_id: S.project || null, period: v.period });
      if (!first.rows.length && /^BS/.test(first.latest || "")) v.period = first.latest;
    }
  } else {
    const first = await run("rep.logbooks", { project_id: S.project || null, period: params.period || thisPeriod() });
    if (!params.period && !first.rows.length && first.latest && !/^BS/.test(first.latest)) v.period = first.latest;
    if (mode === "range") range = window.bcoBsRange(v.period === thisPeriod() ? today() : v.period + "-15");
  }
  const holder = h("div");
  const load = async () => {
    const d = mode === "range" && range ? await run("rep.logbooks", { project_id: S.project || null, from: range.from, to: range.to, label: range.label })
      : await run("rep.logbooks", { project_id: S.project || null, period: v.period });
    let rows = d.rows;
    if (v.status) rows = rows.filter((r) => r.status === v.status);
    if (v.sheet_type) rows = rows.filter((r) => r.sheet_type === v.sheet_type);
    const title = d.label || periodName(v.period);
    const waiting = rows.reduce((a, r) => a + (r.waiting || 0), 0);
    const pend = rows.reduce((a, r) => a + (Number(r.pending_hours) || 0), 0);
    const anyPart = rows.some((r) => r.part);
    holder.innerHTML = "";
    holder.append(h("p", { class: "hint no-bs" }, title + " = English dates " + d.english_span
      + (cal === "bs" ? ". Sheets are kept per Nepali month." : ". Sheets are kept per English month.")));
    holder.append(summaryStrip([
      ["Sheets", rows.length],
      ["Days worked", fmtQty(rows.reduce((a, r) => a + (Number(r.days) || 0), 0))],
      ["Working hours", fmtQty(rows.reduce((a, r) => a + (Number(r.hours) || 0), 0))],
      pend ? ["Hours on DPRs not yet approved", fmtQty(pend)] : null,
      ["Breakdown hours", fmtQty(rows.reduce((a, r) => a + (Number(r.breakdown) || 0), 0))],
      ["Fuel (litres)", fmtQty(rows.reduce((a, r) => a + (Number(r.fuel) || 0), 0))],
      ["Kilometres", fmtQty(rows.reduce((a, r) => a + (Number(r.km) || 0), 0))],
      d.totals.amount ? ["Hire for the month", fmtMoney(rows.reduce((a, r) => a + (Number(r.amount) || 0), 0))] : null,
      ["Not started", d.no_sheet.length],
    ].filter(Boolean)));
    if (d.note) holder.append(h("p", { class: "hint" }, d.note));
    if (pend) holder.append(h("p", { class: "hint" }, "Hours on DPRs not yet approved are shown apart: they join the sheet's hours, hire and costing when the DPR is approved."));
    if (waiting) holder.append(h("p", { class: "hint", style: "color:#b3392c" }, waiting + " machine day(s) from approved DPRs came after their sheet was approved and are not counted on it. Reopen the sheet to take them in."));
    const hours = rows.reduce((a, r) => a + (Number(r.hours) || 0), 0), fuel = rows.reduce((a, r) => a + (Number(r.fuel) || 0), 0);
    holder.append(table([
      { k: "no", label: "Sheet no." },
      anyPart || cal === "bs" ? { label: "Sheet month", v: (r) => r.sheet_label + (r.part ? " (part)" : "") } : null,
      { label: "Machine", v: (r) => drillTo("equipment", r.equipment_id, r.eq_code + " " + r.eq_name) },
      { k: "reg_no", label: "Reg. no." }, { k: "kind", label: "Kind of sheet" },
      { k: "operator", label: "Operator / driver" }, { k: "owner", label: "Owner" },
      { k: "days", label: "Days", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" },
      pend ? { k: "pending_hours", label: "Hours on DPRs not approved", fmt: "qty" } : null,
      { k: "km", label: "Km", fmt: "qty" }, { k: "breakdown", label: "Breakdown h", fmt: "qty" },
      { k: "standby", label: "Standby h", fmt: "qty" }, { k: "payable_days", label: "Payable days", fmt: "qty" },
      { k: "fuel", label: "Fuel", fmt: "qty" }, { k: "ratio", label: "L per hour", fmt: "qty" },
      { k: "availability", label: "Available %", fmt: "qty" },
      { label: "Checks flagged", v: (r) => r.flagged || "" },
      { k: "amount", label: "Hire", fmt: "money" },
      { k: "status", label: "Status", fmt: "status" },
      waiting ? { k: "waiting", label: "DPR days waiting", fmt: "qty" } : null,
    ].filter(Boolean), rows, {
      name: "logsheet_register", title: "Machine logsheets — " + title,
      totals: ["days", "hours", "pending_hours", "km", "breakdown", "standby", "fuel", "payable_days", "amount", "waiting"],
      rowClass: (r) => r.waiting ? "flag" : r.status === "approved" ? "" : (r.flagged ? "flag" : ""),
      empty: "No sheets for this month yet. Use “Open a sheet”.",
      onRow: (r) => { location.hash = "#/eq/book?id=" + r.id; },
    }));
    if (rows.length && hours) holder.append(h("p", { class: "hint" }, "All machines: " + fmtQty(fuel) + " L over " + fmtQty(hours) + " h = " + fmtQty(Math.round(100 * fuel / hours) / 100) + " L per hour."));
    if ((d.loose || []).length) {
      holder.append(h("h2", { class: "sec" }, "Machine days with no sheet"),
        h("p", { class: "muted" }, d.loose.map((x) => x.code + " " + x.name + ": " + x.n + " day(s), " + fmtQty(x.h) + " h").join(" · ")));
    }
    if ((d.pending_loose || []).length) {
      holder.append(h("h2", { class: "sec" }, "Machines on DPRs not yet approved, with no sheet"),
        h("p", { class: "muted" }, d.pending_loose.map((x) => x.code + " " + x.name + ": " + x.pending_days + " day(s), " + fmtQty(x.pending_hours) + " h").join(" · ")));
    }
    if (d.no_sheet.length) {
      holder.append(h("h2", { class: "sec" }, "Machines with no sheet this month"),
        h("p", { class: "muted" }, d.no_sheet.map((e) => e.code + " " + e.name).join(" · ")),
        can("equipment", "edit") ? h("button", { class: "btn small", onclick: () => openDialog(load, d.no_sheet[0].id, mode === "bs" ? v.period : null) }, "Open a sheet for one of them") : null);
    }
  };
  const kindStatus = [
    { k: "sheet_type", label: "Kind", type: "select", options: SHEET_KINDS, blank: "All" },
    { k: "status", label: "Status", type: "select", options: [["draft", "Draft"], ["submitted", "Submitted"], ["approved", "Approved"]], blank: "All" },
  ];
  let bar;
  if (mode === "bs") {
    const mb = window.bcoMonthBox({ bs: true, from: bsFrom(v.period) || today(), fireOnLoad: false, onChange: (sel) => { if (sel.bs) { v.period = "BS" + sel.key; load(); } } });
    const fb = filterBar(kindStatus, v, (x) => { v = Object.assign(v, x); load(); });
    bar = h("div", { class: "bar", style: "align-items:flex-end" }, h("label", { class: "f" }, h("span", {}, "Month (Nepali)"), mb), fb);
  } else if (mode === "range") {
    const mb = window.bcoMonthBox({ from: range ? range.from : today(), fireOnLoad: false, onChange: (sel) => { range = sel.bs ? sel : null; if (!sel.bs) v.period = sel.key; load(); } });
    const fb = filterBar(kindStatus, v, (x) => { v = Object.assign(v, x); load(); });
    bar = h("div", { class: "bar", style: "align-items:flex-end" }, h("label", { class: "f" }, h("span", {}, "Month (Nepali)"), mb), fb);
  } else {
    bar = filterBar([{ k: "period", label: "Month", type: "month" }].concat(kindStatus), v, (x) => { v = x; load(); });
  }
  const calBox = h("div");
  if (can("equipment", "approve") && (cal === "bs" || nepali)) {
    const to = cal === "bs" ? "ad" : "bs";
    const pv = LB_CAL.preview || {};
    const what = to === "bs" ? "Nepali month (Baishakh, Jestha … Chaitra)" : "English month";
    const btn = h("button", { class: cal === "bs" ? "btn small" : "btn primary small", onclick: async () => {
      const ok = await ask("Keep monthly logsheets per " + what, (pv.drafts ? pv.drafts + " draft sheet(s) are moved: each day goes to the sheet of its "
        + (to === "bs" ? "Nepali" : "English") + " month (a draft keeps its number where it can). " : "No draft sheet needs moving. ")
        + (pv.kept ? pv.kept + " submitted or approved sheet(s) stay as they are. " : "")
        + "Nothing posts and no hours change. You can change back the same way.", { ok: "Change" });
      if (ok === null || ok === false) return;
      const res = await run("lb.calendar_set", { calendar: to }, (x) => "Sheets are now kept per " + (to === "bs" ? "Nepali" : "English") + " month");
      if (res) go();
    } }, cal === "bs" ? "Keep sheets per English month instead" : "Keep sheets per Nepali month");
    calBox.append(cal === "bs" ? h("div", { class: "bar" }, h("div", { class: "grow" }), btn)
      : h("div", { class: "panel lf-warn" }, h("b", {}, "Monthly sheets are kept per English month. "),
        "Below, a Nepali month shows the part of each English-month sheet that falls in it. Choose Nepali months to have one sheet per machine per Nepali month instead. ", btn));
  }
  root.append(pageHead("Machine logsheets",
    "One sheet per machine per month — the paper the site keeps. Open a sheet, fill a line a day, tick the daily checks, "
    + "record servicing and oil, then have it checked and approved. Hours and kilometres go straight into hire bills, costing and KPIs.",
    can("equipment", "edit") ? h("button", { class: "btn primary", onclick: () => openDialog(load, null, mode === "bs" ? v.period : null) }, "Open a sheet") : null,
    h("button", { class: "btn", onclick: () => printPage() }, "Print register")),
    calBox, bar, holder);
  await load();
};
function bsFrom(key) {
  if (!key || !/^BS/i.test(key) || !window.bcoBsMonth) return null;
  const r = window.bcoBsMonth(key.slice(2, 6), key.slice(7, 9));
  return r ? r.from : null;
}

function openDialog(done, eqId, bsPeriod) {
  const eqOpts = () => S.L.equipment.filter((e) => e.active && (!S.project || !e.project_id || String(e.project_id) === String(S.project)))
    .map((e) => [e.id, e.code + " " + e.name + (e.reg_no ? " (" + e.reg_no + ")" : "")]);
  /* 2.32: with Nepali-month sheets the month is a Nepali month */
  const bs = !!bsPeriod || (LB_CAL && LB_CAL.calendar === "bs");
  let bsSel = null;
  const mb = bs && window.bcoMonthBox ? window.bcoMonthBox({ bs: true, from: bsFrom(bsPeriod) || today(), onChange: (sel) => { bsSel = sel; } }) : null;
  const f = form([
    { k: "equipment_id", label: "Machine", type: "select", options: eqOpts, req: true, search: true, default: eqId },
    bs ? null : { k: "period", label: "Month", type: "month", default: thisPeriod(), req: true },
    { k: "sheet_type", label: "Kind of sheet", type: "select", noBlank: true, options: SHEET_KINDS },
    bs ? null : { k: "period_label", label: "Month as the site writes it", ph: "Kartik 2081" },
    { k: "site", label: "Site" }, { k: "location", label: "Location / adit" },
    { k: "operator", label: "Operator / driver" },
  ].filter(Boolean), {}, () => {
    const v = f.values();
    const e = byId(S.L.equipment, v.equipment_id);
    if (e) {
      if (e.operator && !f.values().operator) f.set("operator", e.operator);
      if (e.ownership === "hired") f.set("sheet_type", "rental");
      else if ((e.meter_type || "") === "km") f.set("sheet_type", "vehicle");
    }
    if (v.period && !bs) f.set("period_label", f.values().period_label || periodName(v.period));
  });
  modal("Open a monthly logsheet", h("div", {}, mb ? h("label", { class: "f" }, h("span", {}, "Nepali month"), mb) : null, f,
    h("p", { class: "hint" }, "The kind of sheet decides which meters start on it — an hour meter for an excavator, "
      + "kilometres and hours for a tipper, an energy meter for a generator, two booms for a jumbo. You can change the meters on the sheet afterwards.")),
    [{ label: "Open the sheet", cls: "primary", act: async () => {
      const args = Object.assign(f.values(), { project_id: S.project });
      if (bs) {
        const sel = bsSel || (mb && mb._sel);
        if (!sel || !sel.bs) return toast("Choose the Nepali month.", "err");
        args.bs_period = sel.key;
      }
      const r = await run("book.open", args, (x) => x.new ? "Sheet opened" : "That sheet was already open");
      location.hash = "#/eq/book?id=" + r.id;
      if (done) done();
    } }], { narrow: true });
}

/* ── one sheet ── */
PAGES["eq/book"] = async (root, params) => {
  if (typeof window.bcoNepaliMonths === "function" && window.bcoNepaliMonths() && window.bcoLoadBS) await window.bcoLoadBS();
  const id = params.id;
  if (!id) { location.hash = "#/eq/books"; return; }
  const d = await run("book.get", { id });
  const b = d.book, eq = d.equipment, codes = d.meters;
  const ro = b.status === "approved" || !can("equipment", "edit");
  const kind = (SHEET_KINDS.find(([k]) => k === b.sheet_type) || [null, b.sheet_type])[1];

  const reload = () => go();
  root.append(pageHead(eq.code + " " + eq.name + " — " + sheetMonth(b),
    kind + " · sheet " + b.no + " · " + b.from_date + " to " + b.to_date,
    h("button", { class: "btn", onclick: () => printBook(d) }, "Print the sheet"),
    ro ? null : h("button", { class: "btn", onclick: () => headerDialog(b, reload) }, "Sheet header"),
    b.status === "draft" && can("equipment", "edit") ? h("button", { class: "btn", onclick: async () => { await run("book.submit", { id: b.id }, "Sent for approval"); reload(); } }, "Submit") : null,
    b.status === "submitted" && can("equipment", "approve") ? h("button", { class: "btn primary", onclick: async () => { await run("book.approve", { id: b.id }, "Approved"); reload(); } }, "Approve") : null,
    b.status === "approved" && can("equipment", "approve") ? h("button", { class: "btn warn", onclick: async () => { const r = await ask("Reopen the sheet", "The month is signed off. Reopening puts every day line back to draft.", { input: "Why is it being reopened?", required: true, ok: "Reopen" }); if (r === null) return; await run("book.reopen", { id: b.id, reason: r }, "Reopened"); reload(); } }, "Reopen") : null));

  root.append(h("div", { class: "stamprow" }, stamp(b.status)));
  root.append(kv([
    ["Machine", drillTo("equipment", eq.id, eq.code + " " + eq.name)],
    ["Registration no.", eq.reg_no || "—"], ["Model", eq.model || "—"],
    ["Capacity", eq.rating || "—"],
    ["Operator / driver", b.operator || eq.operator || "—"],
    b.operator2 ? ["Second operator", b.operator2] : null,
    ["Owner of the machine", b.owner_name || (b.owner_party_id ? nm.party(b.owner_party_id) : (eq.ownership === "hired" ? "—" : "Own machine"))],
    b.sheet_type === "hired_out" ? ["Work requested by", b.hirer_name || (b.hirer_party_id ? nm.party(b.hirer_party_id) : "—")] : null,
    ["Site", b.site || "—"], ["Location", b.location || "—"],
    ["Cost code", b.cost_code || "—"],
    ["Meters on this sheet", codes.map(meterLabel).join(", ")],
    b.rate ? ["Agreed rate", fmtMoney(b.rate) + " per " + (b.rate_basis || "hour")] : null,
  ]));

  const sum = h("div");
  const paintSummary = (s) => {
    sum.innerHTML = "";
    sum.append(summaryStrip([
      ["Working days", fmtQty(s.working_days)],
      ["Day + night", fmtQty(s.day_and_night)],
      ["Idle days", fmtQty(s.idle_days)],
      ["Standby days", fmtQty(s.standby_days)],
      ["Breakdown days", fmtQty(s.breakdown_days)],
      ["Payable days", fmtQty(s.payable_days)],
      ["Working hours", fmtQty(s.hours)],
      ["Breakdown hours", fmtQty(s.breakdown_hours)],
      ["Fuel (litres)", fmtQty(s.fuel)],
      s.hours ? ["Litres per hour", fmtQty(s.fuel_per_hour)] : null,
      s.km ? ["Kilometres", fmtQty(s.km)] : null,
      s.km ? ["Litres per km", fmtQty(s.fuel_per_km)] : null,
      ["Availability %", fmtQty(s.availability)],
      s.amount ? ["Hire for the month", fmtMoney(s.amount)] : null,
      s.pending_hours ? ["Hours on DPRs not yet approved", fmtQty(s.pending_hours) + " h (" + s.pending_days + " day" + (s.pending_days === 1 ? "" : "s") + ")"] : null,
    ].concat(codes.filter((x) => x !== "hour" && x !== "km").map((x) => [meterLabel(x) + " (" + METER_UNIT[x] + ")", fmtQty(s["meter_" + x])]))
      .concat((s.outputs || []).filter((o) => o.hours || o.qty).map((o) => [o.name, fmtQty(o.hours) + " h" + (o.qty ? " · " + fmtQty(o.qty) + (o.unit ? " " + o.unit : "") : "")]))));
  };
  paintSummary(d.summary);
  root.append(h("h2", { class: "sec" }, "The month at a glance"), sum);

  root.append(tabs([
    ["Day by day", () => dayTab(d, paintSummary)],
    ["Daily checks", () => checkTab(d)],
    ["Servicing", () => serviceTab(d)],
    ["Oil and grease", () => fluidTab(d)],
    ["By output (bucket, breaker…)", () => outputSheets({ equipment_id: b.equipment_id, from: b.from_date, to: b.to_date, month: b.period, title: (eq.code || "") + " " + (eq.name || "") })],
    ["Notes", () => noteTab(d, reload)],
  ]));
};

/* every date of the month, whether or not it has been filled in */
function monthRows(d) {
  const by = {};
  d.rows.forEach((r) => { (by[r.date] = by[r.date] || []).push(r); });
  const out = [];
  d.dates.forEach((dt) => {
    const got = by[dt];
    if (got && got.length) got.forEach((r) => out.push(Object.assign({}, r)));
    else out.push({ date: dt, shift: "day" });
  });
  return out;
}

/* 2.32: a read-only sheet is a list with a total line. Every date of the month is there; each day shows its DPR, its
   output / attachment and quantity; days on DPRs not approved yet are shown (in italics) with their hours apart, and
   days of these dates kept on another sheet say where they are. Only the sheet's own days are in its totals. */
const DPR_STATE = { draft: "draft", submitted: "submitted", checked: "checked", returned: "returned for correction" };
function sheetLines(d) {
  const own = d.rows.map((r) => Object.assign({ src: r.dpr_no ? r.dpr_no : (r.status === "approved" ? "Approved" : "Entered on the sheet") }, r));
  const pend = (d.pending || []).map((p) => ({ date: p.date, shift: p.shift, work: p.work, out_text: p.out_text, p_hours: p.hours, pending: true,
    operator: p.operator,
    src: p.dpr_no + " · " + (DPR_STATE[p.dpr_status] || p.dpr_status) + " — not approved yet"
      + (p.idle_hours ? " · idle " + fmtQty(p.idle_hours) + " h" : "") + (p.breakdown_hours ? " · breakdown " + fmtQty(p.breakdown_hours) + " h" : ""),
    ms_hour: p.meter_start, me_hour: p.meter_end, p_qty: p.output_qty, output_unit: p.output_unit }));
  const other = (d.elsewhere || []).map((x) => ({ date: x.date, shift: x.shift, elsewhere: true, src: "Not on this sheet: " + x.why + " (" + fmtQty(x.hours) + " h)" }));
  const all = own.concat(pend, other);
  const by = {};
  all.forEach((r) => { (by[r.date] = by[r.date] || []).push(r); });
  const out = [];
  d.dates.forEach((dt) => {
    const got = (by[dt] || []).sort((a, z) => (a.shift === "night") - (z.shift === "night"));
    if (got.length) out.push(...got); else out.push({ date: dt, shift: "" });
  });
  return out;
}
function sheetTable(d) {
  const codes = d.meters, rows = sheetLines(d);
  const units = [...new Set(d.rows.filter((r) => r.output_qty).map((r) => r.output_unit || ""))];
  const pend = (d.pending || []).length;
  const cols = [
    { k: "date", label: "Date" },
    { label: "Day / night", v: (r) => r.shift === "night" ? "Night" : r.shift ? "Day" : "" },
    { label: "From", v: (r) => r.src || "" },
    { label: "Work", v: (r) => r.activity || r.work || "" },
    { label: "Output / attachment", v: (r) => r.out_text || "" },
    { k: "output_qty", label: "Output qty" + (units.length === 1 && units[0] ? " (" + units[0] + ")" : ""), fmt: "qty" },
  ];
  codes.forEach((code) => {
    const nm2 = meterLabel(code);
    cols.push({ label: nm2 + " start", fmt: "qty", v: (r) => r["ms_" + code] || null });
    cols.push({ label: nm2 + " stop", fmt: "qty", v: (r) => r["me_" + code] || null });
    if (code !== "hour") cols.push({ k: "mt_" + code, label: nm2 + " total", fmt: "qty" });
  });
  cols.push({ k: "hours", label: "Working hours", fmt: "qty" });
  if (pend) cols.push({ k: "p_hours", label: "Hours on DPR not approved", fmt: "qty" });
  cols.push(
    { k: "trips", label: "Trips", fmt: "qty" }, { k: "idle_hours", label: "Idle h", fmt: "qty" },
    { k: "standby_hours", label: "Standby h", fmt: "qty" }, { k: "breakdown_hours", label: "Breakdown h", fmt: "qty" },
    { k: "down_reason", label: "Reason for stoppage" }, { k: "fuel_qty", label: "Fuel", fmt: "qty" },
    { k: "fuel_req_no", label: "Req. no." }, { k: "operator", label: "Operator" });
  const totals = ["hours", "p_hours", "trips", "idle_hours", "standby_hours", "breakdown_hours", "fuel_qty"]
    .concat(units.length === 1 ? ["output_qty"] : []).concat(codes.filter((c) => c !== "hour").map((c) => "mt_" + c));
  return h("div", { class: "lb-sheet" }, table(cols, rows, { name: "logsheet_" + (d.book.no || "").replace(/\W+/g, "_"), totals, search: false,
    rowClass: (r) => r.pending ? "lb-pend" : r.elsewhere ? "lb-else" : "" }));
}
(function () {
  const st = document.createElement("style");
  st.textContent = "tr.lb-pend td{font-style:italic;color:var(--muted,#6b7280)}tr.lb-else td{color:var(--muted,#6b7280)}.lb-sheet td,.lb-sheet th{white-space:nowrap}";
  document.head.append(st);
})();

function dayTab(d, paintSummary) {
  const b = d.book, codes = d.meters;
  const ro = b.status === "approved" || !can("equipment", "edit") || !!b.dpr_only;
  const cols = [
    { k: "date", label: "Date", type: "date", w: 120, readonly: true },
    { k: "work", label: "Work description", w: 200 },
    { k: "cost_code", label: "Cost code", w: 90 },
    { k: "boq_item_id", label: "BOQ item", type: "select", w: 170, options: () => opt.boq(b.project_id) },
    { k: "shift", label: "Day / night", type: "select", noBlank: true, w: 90, options: [["day", "Day"], ["night", "Night"]] },
    { k: "time_start", label: "Start", type: "time", w: 80 },
    { k: "time_stop", label: "Stop", type: "time", w: 80 },
  ];
  codes.forEach((code) => {
    const nm2 = meterLabel(code);
    cols.push({ k: "ms_" + code, label: nm2 + " start", type: "number", num: true, w: 90 });
    cols.push({ k: "me_" + code, label: nm2 + " stop", type: "number", num: true, w: 90 });
    cols.push({ label: nm2 + " total", num: true, w: 80, show: (r) => {
      const t = (Number(r["me_" + code]) || 0) - (Number(r["ms_" + code]) || 0);
      return t > 0 ? fmtQty(t) : "";
    } });
  });
  if (!codes.includes("hour")) cols.push({ k: "hours", label: "Working hours", type: "number", num: true, w: 90 });
  cols.push(
    { k: "trips", label: "Trips", type: "number", num: true, w: 70 },
    { k: "idle_hours", label: "Idle h", type: "number", num: true, w: 70 },
    { k: "standby_hours", label: "Standby h", type: "number", num: true, w: 80 },
    { k: "breakdown_hours", label: "Breakdown h", type: "number", num: true, w: 90 },
    { k: "down_reason", label: "Reason for stoppage", w: 150 },
    { k: "fuel_qty", label: "Fuel", type: "number", num: true, w: 70 },
    { k: "fuel_req_no", label: "Req. no.", w: 85 },
    { k: "sign_store", label: "Store", w: 90 },
    { k: "sign_operator", label: "Driver / operator", w: 110 },
    { k: "sign_incharge", label: "In-charge", w: 100 });
  if (b.sheet_type === "hired_out") cols.push({ k: "sign_hirer", label: "Other company", w: 110 });

  if (!ro) cols.splice(2, 0, { label: "DPR", w: 110, show: (r) => r.dpr_no || "" }, { label: "Output / attachment", w: 160, show: (r) => r.out_text || "" });
  const ed = ro ? sheetTable(d) : lineEditor(cols.map((c) => Object.assign({}, c, { readonly: c.readonly })), monthRows(d),
    { fixed: true, readonly: ro });
  const apart = (d.pending || []).length + (d.elsewhere || []).length;
  const others = !ro && apart ? h("div", {}, h("h3", {}, "Days kept apart from this sheet"),
    table([{ k: "date", label: "Date" }, { label: "Day / night", v: (r) => r.shift === "night" ? "Night" : "Day" }, { label: "Where", v: (r) => r.src },
      { label: "Output / attachment", v: (r) => r.out_text || "" }, { k: "p_hours", label: "Hours on DPR not approved", fmt: "qty" }],
    sheetLines(d).filter((r) => r.pending || r.elsewhere), { search: false, export: false, name: "days_apart", totals: ["p_hours"], rowClass: (r) => r.pending ? "lb-pend" : "lb-else" })) : null;
  const storeTbl = (d.store_issues || []).length ? h("div", {}, h("h3", {}, "Issued from the store to this machine"),
    table([{ k: "date", label: "Date" }, { k: "no", label: "Issue" }, { k: "name", label: "Material" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "amount", label: "Value", fmt: "money" }],
      d.store_issues, { search: false, name: "store_issues_to_machine", totals: ["amount"] })) : h("p", { class: "muted" }, "Nothing issued from the store to this machine this month.");
  if (b.dpr_only) return h("div", {}, h("div", { class: "panel" }, h("b", {}, "This sheet is filled automatically. "),
    "Hours, meters, idle and breakdown time come from the approved DPRs (Daily progress › Equipment); fuel is the diesel / petrol issued from the store to this machine that day. "
    + "Lines in italics are on DPRs not approved yet: they are shown, but join the hours, hire and costing only when the DPR is approved. ",
    h("a", { href: "#/p/dpr" }, "Open Daily progress")), ed, storeTbl);
  const box = h("div", {}, h("p", { class: "hint" },
    "Every day of the month is already here — fill in only the days the machine worked and leave the rest empty. "
    + "With an hour meter, hours are the closing reading minus the opening one, and the opening reading cannot be below "
    + "yesterday's closing. A day left empty is not saved."), ed, others);
  if (!ro) {
    box.append(h("div", { class: "actions" },
      h("button", { class: "btn primary", onclick: async () => {
        const r = await run("book.rows", { id: b.id, rows: ed.lines() }, (x) => "Saved " + x.saved + " day" + (x.saved === 1 ? "" : "s"));
        (r.warnings || []).forEach((w) => toast(w));
        const s = await run("book.summary", { id: b.id });
        paintSummary(s);
      } }, "Save the month"),
      h("span", { class: "muted" }, "Tip: Alt+C on a picker makes the master without leaving the line.")));
  }
  return box;
}

function checkTab(d) {
  const b = d.book;
  const ro = b.status === "approved" || !can("equipment", "edit");
  if (!d.checklist) {
    return h("div", { class: "panel" }, h("b", {}, "No check list on this sheet"),
      h("p", { class: "muted" }, "Pick one in “Sheet header”, or make one in Masters → Daily check lists."));
  }
  const items = d.checklist.items;
  const state = {};
  d.dates.forEach((dt) => { state[dt] = Object.assign({}, (d.checks[dt] || {})); });
  const head = h("tr", {}, h("th", {}, "Date"), items.map((it) => h("th", { class: "vert", title: it }, it)),
    h("th", {}, "Checked by"), h("th", {}, "Remarks"));
  const body = h("tbody");
  d.dates.forEach((dt) => {
    const tr = h("tr", {}, h("td", {}, dt.slice(8) + " " + new Date(dt).toLocaleString("en-GB", { weekday: "short" })));
    items.forEach((it) => {
      const cell = (state[dt][it] || {});
      const sel = h("select", { disabled: ro, class: "ckcell" },
        h("option", { value: "" }, ""),
        CHECK_RESULTS.map(([v, l]) => h("option", { value: v, selected: cell.result === v }, CHECK_MARK[v] + " " + l)));
      sel.addEventListener("change", () => {
        if (!sel.value) delete state[dt][it];
        else state[dt][it] = Object.assign(state[dt][it] || {}, { result: sel.value });
        sel.className = "ckcell r-" + (sel.value || "none");
      });
      sel.className = "ckcell r-" + (cell.result || "none");
      tr.append(h("td", {}, sel));
    });
    const who = h("input", { value: (Object.values(state[dt])[0] || {}).checked_by || "", readonly: ro, style: "width:100px" });
    const rem = h("input", { value: (Object.values(state[dt])[0] || {}).remarks || "", readonly: ro, style: "width:150px" });
    tr._who = who; tr._rem = rem; tr._date = dt;
    tr.append(h("td", {}, who), h("td", {}, rem));
    body.append(tr);
  });
  const wrap = h("div", {},
    h("p", { class: "hint" }, "Before starting the engine: " + d.checklist.name + ". Leave a cell empty if it was not checked; "
      + "“Needs repair” shows up in red and is counted on the register so nothing is quietly ignored."),
    h("div", { class: "tablewrap" }, h("table", { class: "checkgrid" }, h("thead", {}, head), body)));
  if (!ro) {
    wrap.append(h("div", { class: "actions" },
      h("button", { class: "btn small", onclick: () => {
        body.querySelectorAll("tr").forEach((tr) => tr.querySelectorAll("select").forEach((s) => { if (!s.value) { s.value = "ok"; s.dispatchEvent(new Event("change")); } }));
      } }, "Mark everything OK"),
      h("button", { class: "btn primary", onclick: async () => {
        const checks = [];
        [...body.querySelectorAll("tr")].forEach((tr) => {
          const dt = tr._date;
          items.forEach((it) => {
            const c = state[dt][it];
            if (c && c.result) checks.push({ date: dt, item: it, result: c.result, remarks: tr._rem.value, checked_by: tr._who.value });
            else checks.push({ date: dt, item: it, clear: 1 });
          });
        });
        await run("book.checks", { id: b.id, checks }, "Checks saved");
      } }, "Save the checks")));
  }
  return wrap;
}

function serviceTab(d) {
  const b = d.book;
  const ro = b.status === "approved" || !can("equipment", "edit");
  const rows = d.service.length ? d.service : [
    { description: "Fuel filter 1st" }, { description: "Fuel filter 2nd" }, { description: "Engine oil filter" },
    { description: "Air filter 1st" }, { description: "Air filter 2nd" }, { description: "Engine oil" },
  ];
  const ed = lineEditor([
    { k: "date", label: "Date", type: "date", w: 125 },
    { k: "description", label: "What was done / part", w: 200 },
    { k: "part_no", label: "Part no.", w: 110 },
    { k: "qty", label: "Qty", type: "number", num: true, w: 70 },
    { k: "unit", label: "Unit", w: 60 },
    { k: "brand", label: "Brand", w: 100 },
    { k: "material_id", label: "Store item", type: "select", w: 170, options: opt.materials },
    { k: "at_hour", label: "At hour meter", type: "number", num: true, w: 100 },
    { k: "at_km", label: "At km", type: "number", num: true, w: 90 },
    { k: "remarks", label: "Remarks", w: 150 },
  ].map((c) => Object.assign({}, c, { readonly: ro })), rows, { readonly: ro, blank: {} });
  const box = h("div", {}, h("p", { class: "hint" },
    "What was serviced this month and which parts went in. Link a store item and the same part shows on the machine's "
    + "cost passport and on the stock card."), ed);
  if (!ro) {
    box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      await run("book.service", { id: b.id, service: ed.lines() }, "Servicing saved");
    } }, "Save servicing")));
  }
  return box;
}

function fluidTab(d) {
  const b = d.book;
  const ro = b.status === "approved" || !can("equipment", "edit") || !!b.dpr_only;
  const ed = lineEditor([
    { k: "date", label: "Date", type: "date", w: 125 },
    { k: "engine_oil", label: "Engine oil", type: "number", num: true, w: 90 },
    { k: "gear_oil", label: "Gear oil", type: "number", num: true, w: 85 },
    { k: "brake_oil", label: "Brake oil", type: "number", num: true, w: 85 },
    { k: "hydraulic_oil", label: "Hydraulic oil", type: "number", num: true, w: 95 },
    { k: "transmission_oil", label: "Transmission oil", type: "number", num: true, w: 110 },
    { k: "crown_oil", label: "Crown oil", type: "number", num: true, w: 90 },
    { k: "grease", label: "Grease", type: "number", num: true, w: 80 },
    { k: "coolant", label: "Coolant", type: "number", num: true, w: 80 },
    { k: "other_name", label: "Other", w: 110 },
    { k: "other_qty", label: "Other qty", type: "number", num: true, w: 85 },
    { k: "remarks", label: "Remarks", w: 140 },
  ].map((c) => Object.assign({}, c, { readonly: ro })), d.fluids, { readonly: ro, blank: {} });
  if (b.dpr_only) return h("div", {}, h("p", { class: "hint" }, "Oil, grease and coolant come from store issues to this machine (Inventory › Issues, issue to the machine). Lines marked “from store issues” are filled automatically."), ed);
  const box = h("div", {}, h("p", { class: "hint" }, "Litres of each oil put into the machine. Quantities here are the "
    + "sheet's own record; issuing the same oil from the store keeps the money side right."), ed);
  if (!ro) {
    box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      await run("book.fluids", { id: b.id, fluids: ed.lines() }, "Saved");
    } }, "Save oil and grease")));
  }
  return box;
}

function noteTab(d, reload) {
  const b = d.book;
  const ro = b.status === "approved" || !can("equipment", "edit");
  const f = form([
    { k: "issues", label: "Comments and problems", type: "textarea", wide: true, readonly: ro },
    { k: "remarks", label: "Remarks for the month", type: "textarea", wide: true, readonly: ro },
  ], b);
  const box = h("div", {}, f);
  if (!ro) {
    box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      await run("book.save", { row: Object.assign({}, b, f.values()) }, "Saved");
      reload();
    } }, "Save notes")));
  }
  return box;
}

function headerDialog(b, done) {
  const f = form([
    { k: "period_label", label: "Month as the site writes it", ph: "Kartik 2081" },
    { k: "operator", label: "Operator / driver" }, { k: "operator2", label: "Second operator" },
    { k: "site", label: "Site" }, { k: "location", label: "Location / adit" },
    { k: "cost_code", label: "Cost code" },
    { k: "meters", label: "Meters on this sheet", wide: true, ph: "hour,km", hint: "Any of: " + METER_KINDS.map(([k]) => k).join(", ") },
    { k: "checklist_id", label: "Daily check list", type: "select", options: () => (S.L.checklists || []).map((x) => [x.id, x.name]) },
    { k: "owner_party_id", label: "Owner of the machine", type: "select", options: () => opt.parties(["vendor", "subcontractor"]) },
    { k: "owner_name", label: "…or the owner's name as written" },
    { k: "hirer_party_id", label: "Work requested by", type: "select", options: () => opt.parties() },
    { k: "hirer_name", label: "…or that company's name as written" },
    { k: "rate", label: "Agreed rate", type: "number" },
    { k: "rate_basis", label: "Rate per", type: "select", options: [["hour", "Hour"], ["day", "Payable day"], ["km", "Kilometre"]] },
    { k: "payable_days", label: "Payable days agreed", type: "number", hint: "Leave empty to use working + standby days" },
  ], b);
  modal("Sheet header", f, [{ label: "Save", cls: "primary", act: async () => {
    await run("book.save", { row: Object.assign({ id: b.id }, f.values()) }, "Saved");
    done();
  } }], { narrow: true });
}

/* ── the printed sheet: the same paper the samples use ── */
function printBook(d) {
  const b = d.book, eq = d.equipment, codes = d.meters, s = d.summary;
  const esc = escHtml;
  const kind = (SHEET_KINDS.find(([k]) => k === b.sheet_type) || [null, b.sheet_type])[1];
  const rows = monthRows(d).filter((r) => r.id);
  const mcols = codes.map((c) => meterLabel(c));
  const th = ["Date", "Work description", "Output / attachment", "Cost code", "Day/Night", "Start", "Stop"]
    .concat([].concat(...mcols.map((m) => [m + " start", m + " stop", m + " total"])))
    .concat(["Trips", "Idle", "Standby", "B/down", "Fuel", "Req. no.", "Store", "Driver", "In-charge", "Remarks"]);
  const line = (r) => {
    const cells = [r.date, r.work || "", r.out_text || "", r.cost_code || "", r.shift === "night" ? "Night" : "Day",
      r.time_start || "", r.time_stop || ""];
    codes.forEach((c) => {
      const a = Number(r["ms_" + c]) || 0, z = Number(r["me_" + c]) || 0;
      cells.push(a || "", z || "", z > a ? fmtQty(z - a) : "");
    });
    cells.push(r.trips || "", r.idle_hours || "", r.standby_hours || "", r.breakdown_hours || "",
      r.fuel_qty || "", r.fuel_req_no || "", r.sign_store || "", r.sign_operator || "", r.sign_incharge || "",
      r.down_reason || "");
    return "<tr>" + cells.map((x, i) => `<td class="${i > 6 ? "n" : ""}">${esc(x)}</td>`).join("") + "</tr>";
  };
  const hdr = [
    ["Equipment name", eq.name], ["Equipment code", eq.code], ["Registration no.", eq.reg_no || ""],
    ["Model", eq.model || ""], ["Operator / driver", b.operator || eq.operator || ""],
    ["Kind of sheet", kind],
    ["Owner of equipment", b.owner_name || (b.owner_party_id ? nm.party(b.owner_party_id) : (eq.ownership === "hired" ? "" : "Own machine"))],
    b.sheet_type === "hired_out" ? ["Requested by", b.hirer_name || (b.hirer_party_id ? nm.party(b.hirer_party_id) : "")] : null,
    ["Month", sheetMonth(b)], ["Site", b.site || ""], ["Location", b.location || ""],
    ["Sheet no.", b.no], ["Cost code", b.cost_code || ""],
  ].filter(Boolean);
  const monthly = [
    ["Total working days", s.working_days], ["Total working day + night", s.day_and_night],
    ["Total idle days", s.idle_days], ["Total stand-by days", s.standby_days],
    ["Total breakdown days", s.breakdown_days], ["Total payable days", s.payable_days],
    ["Total fuel consumption", fmtQty(s.fuel)], ["Fuel consumption ratio", fmtQty(s.fuel_per_hour) + " L / hour"],
    ["Total running kilometres", fmtQty(s.km)], ["Total working hour meter", fmtQty(s.hours)],
  ].concat(codes.filter((c) => c !== "hour" && c !== "km").map((c) => ["Total " + meterLabel(c), fmtQty(s["meter_" + c]) + " " + METER_UNIT[c]]))
    .concat((s.outputs || []).filter((o) => o.hours || o.qty).map((o) => ["Total " + o.name, fmtQty(o.hours) + " h" + (o.qty ? " · " + fmtQty(o.qty) + (o.unit ? " " + o.unit : "") : "")]))
    .concat(b.rate ? [["Hire for the month", fmtMoney(s.amount)]] : []);

  const checkTable = d.checklist ? `<h2>Daily check list — ${esc(d.checklist.name)}</h2>
    <table class="chk"><thead><tr><th>Date</th>${d.checklist.items.map((i) => `<th class="v">${esc(i)}</th>`).join("")}<th>Sign</th></tr></thead>
    <tbody>${d.dates.map((dt) => {
    const row = d.checks[dt] || {};
    if (!Object.keys(row).length) return "";
    return `<tr><td>${esc(dt)}</td>${d.checklist.items.map((i) => `<td class="n">${esc(CHECK_MARK[(row[i] || {}).result] || "")}</td>`).join("")}<td></td></tr>`;
  }).join("")}</tbody></table>` : "";

  const svc = d.service.length ? `<h2>Servicing details</h2><table><thead><tr><th>S.N.</th><th>Date</th>
    <th>Description</th><th>Part no.</th><th class="n">Qty</th><th>Brand</th><th class="n">At hour</th>
    <th class="n">At km</th><th>Remarks</th></tr></thead><tbody>${d.service.map((r, i) =>
    `<tr><td>${i + 1}</td><td>${esc(r.date || "")}</td><td>${esc(r.description || "")}</td><td>${esc(r.part_no || "")}</td>
     <td class="n">${esc(fmtQty(r.qty))}</td><td>${esc(r.brand || "")}</td><td class="n">${esc(r.at_hour || "")}</td>
     <td class="n">${esc(r.at_km || "")}</td><td>${esc(r.remarks || "")}</td></tr>`).join("")}</tbody></table>` : "";

  const FL = [["engine_oil", "Engine oil"], ["gear_oil", "Gear oil"], ["brake_oil", "Brake oil"],
    ["hydraulic_oil", "Hydraulic oil"], ["transmission_oil", "Transmission oil"], ["crown_oil", "Crown oil"],
    ["grease", "Grease"], ["coolant", "Coolant"]];
  const flu = d.fluids.length ? `<h2>Used fluid</h2><table><thead><tr><th>Date</th>
    ${FL.map(([, l]) => `<th class="n">${esc(l)}</th>`).join("")}<th>Other</th><th class="n">Qty</th><th>Remarks</th></tr></thead>
    <tbody>${d.fluids.map((r) => `<tr><td>${esc(r.date || "")}</td>${FL.map(([k]) => `<td class="n">${r[k] ? esc(fmtQty(r[k])) : ""}</td>`).join("")}
      <td>${esc(r.other_name || "")}</td><td class="n">${r.other_qty ? esc(fmtQty(r.other_qty)) : ""}</td><td>${esc(r.remarks || "")}</td></tr>`).join("")}
    </tbody></table>` : "";

  const html = `<div class="meta">${hdr.map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(v)}</div>`).join("")}</div>
    <table class="days"><thead><tr>${th.map((t) => `<th>${esc(t)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(line).join("") || '<tr><td colspan="' + th.length + '">Nothing entered yet.</td></tr>'}</tbody></table>
    <h2>Monthly working details</h2>
    <div class="meta">${monthly.map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(v)}</div>`).join("")}</div>
    ${checkTable}${svc}${flu}
    ${b.issues ? "<h2>Comments and problems</h2><pre>" + esc(b.issues) + "</pre>" : ""}
    ${b.remarks ? "<h2>Remarks</h2><pre>" + esc(b.remarks) + "</pre>" : ""}
    <div class="sign"><div>Prepared by</div><div>Checked by</div><div>Approved by</div></div>`;
  const w = window.open("", "_blank");
  if (!w) return toast("Allow pop-ups to print.", "err");
  w.document.write(`<html><head><title>${esc("Logsheet " + eq.code + " " + (b.month_name || b.period))}</title>
    <style>${PRINT_CSS}
    table.days,table.chk{font-size:9.5px}
    table.days td,table.days th,table.chk td,table.chk th{padding:2px 3px}
    table.chk td.n{text-align:center;font-weight:700}
    th.v{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;font-weight:600;
         height:92px;vertical-align:bottom;font-size:9px}
    @page{size:A4 landscape;margin:8mm}</style></head><body>`
    + headingHtml("Equipment / vehicle logsheet", [["Machine", eq.code], ["Month", sheetMonth(b)]])
    + html + `<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

/* ── the check lists themselves ── */
PAGES["m/checklists"] = async (root) => {
  const load = async () => {
    const rows = await run("check.templates", {});
    holder.innerHTML = "";
    holder.append(table([
      { k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "category", label: "For" },
      { label: "Items", v: (r) => (r.items || "").split("\n").filter(Boolean).length },
      { label: "", v: (r) => (r.items || "").split("\n").filter(Boolean).slice(0, 4).join(" · ") + "…" },
    ], rows, { name: "check_lists", onRow: (r) => clDialog(r, load), empty: "No check lists yet." }));
  };
  const holder = h("div");
  const clDialog = (row, done) => {
    const f = form([
      { k: "code", label: "Code" }, { k: "name", label: "Name", req: true },
      { k: "category", label: "For which machines", ph: "vehicle, tracked, hoist, genset" },
      { k: "items", label: "Items, one to a line", type: "textarea", wide: true, req: true },
      { k: "active", label: "Active", type: "check", default: 1 },
    ], row || { active: 1 });
    modal(row ? "Check list: " + row.name : "New check list", f, [{ label: "Save", cls: "primary", act: async () => {
      await run("check.save", { row: Object.assign({ id: row && row.id }, f.values()) }, "Saved");
      await reloadLookups();
      done();
    } }], { narrow: true });
  };
  root.append(pageHead("Daily check lists",
    "“Before starting the engine, check the following.” One list per kind of machine; the list shows across the top of "
    + "the monthly sheet so the operator ticks it every morning.",
    can("masters", "edit") ? h("button", { class: "btn primary", onclick: () => clDialog(null, load) }, "New check list") : null), holder);
  await load();
};


/* ── 2.7  one logsheet for each output of a machine (bucket, breaker, …) ── */
async function outputSheets(o) {
  const box = h("div");
  const d = await api("tool.sheet", { equipment_id: o.equipment_id, from: o.from, to: o.to, month: o.month, project_id: o.project_id || null });
  const eq = d.equipment;
  const title = (eq.code + " " + eq.name).trim();
  const outs = d.outputs;
  if (!outs.length) {
    box.append(h("p", { class: "hint" }, "This machine has no outputs yet. Open the machine (Masters → Equipment) and add them — e.g. Bucket and Hydraulic breaker for an excavator. Until then all its hours are one logsheet."));
    return box;
  }
  const unitQ = (x) => x.unit ? " " + x.unit : "";
  box.append(h("p", { class: "hint" }, "Each output of the machine has its own logsheet: the days it worked with that output, the hours and the quantity done, taken from the DPR. Fuel is the month's store issues shared by hours. Hours that were not split on the DPR go to the default output."),
    summaryStrip(outs.map((x) => [x.name, fmtQty(x.hours) + " h · " + fmtQty(x.output_qty) + unitQ(x)])
      .concat([["Machine hours", fmtQty(d.total_hours)], ["Fuel issued", fmtQty(d.total_fuel) + " L"]])));

  /* days × outputs */
  const dates = [...new Set(outs.flatMap((x) => x.days.map((y) => y.date + "|" + y.shift)))].sort();
  const cell = (x, key) => x.days.filter((y) => y.date + "|" + y.shift === key);
  const mcols = [{ label: "Date", v: (r) => r.date }, { label: "Shift", v: (r) => r.shift }];
  outs.forEach((x, i) => {
    mcols.push({ label: x.name + " h", fmt: "qty", v: (r) => r["h" + i] });
    mcols.push({ label: x.name + " qty" + (x.unit ? " (" + x.unit + ")" : ""), fmt: "qty", v: (r) => r["q" + i] });
  });
  const mrows = dates.map((key) => {
    const [dt, sh] = key.split("|");
    const r = { date: dt, shift: sh };
    outs.forEach((x, i) => { const c = cell(x, key); r["h" + i] = c.reduce((a, y) => a + (y.hours || 0), 0) || null; r["q" + i] = c.reduce((a, y) => a + (y.output_qty || 0), 0) || null; });
    return r;
  });
  const mtot = [];
  outs.forEach((x, i) => { mtot.push("h" + i, "q" + i); });
  mcols.forEach((c, i) => { if (i > 1) c.k = mtot[i - 2]; });
  box.append(h("h3", { style: "margin:14px 0 6px" }, "Day by output"), table(mcols, mrows, { name: "logsheet_by_output", totals: mtot, empty: "No working days in this period." }));

  /* one sheet per output */
  const sheetCols = (x) => [{ k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { k: "operator", label: "Operator" },
    { k: "dpr_no", label: "DPR" }, { k: "day_hours", label: "Machine h (day)", fmt: "qty" }, { k: "hours", label: x.name + " h", fmt: "qty" },
    { k: "output_qty", label: "Quantity" + (x.unit ? " (" + x.unit + ")" : ""), fmt: "qty" }, { k: "work", label: "Work done" }];
  const facts = (x) => [["Machine", title], eq.reg_no ? ["Reg. no.", eq.reg_no] : null, ["Output / attachment", x.name + (x.kind ? " (" + x.kind + ")" : "")],
    ["Period", d.from + " to " + d.to], ["Days worked", fmtQty(x.days_worked)], ["Hours", fmtQty(x.hours)],
    ["Quantity done", fmtQty(x.output_qty) + unitQ(x)], ["Output per hour", fmtQty(x.output_per_hour) + unitQ(x)],
    x.norm_output_hr ? ["Norm per hour", fmtQty(x.norm_output_hr) + unitQ(x)] : null,
    ["Fuel share", fmtQty(x.fuel) + " L (" + fmtQty(x.fuel_per_hour) + " L/h)"], ["Rate per hour", fmtMoney(x.rate_hr)], ["Amount", fmtMoney(x.amount)]].filter(Boolean);
  const printable = (x) => {
    const n = h("div", { style: "page-break-after:always" });
    n.append(h("h2", {}, "Logsheet — " + x.name), h("div", { class: "meta" }, facts(x).map(([k, v]) => h("div", {}, h("b", {}, k + ": "), v))));
    const t = h("table", {}, h("thead", {}, h("tr", {}, sheetCols(x).map((c) => h("th", {}, c.label)))),
      h("tbody", {}, x.days.map((r) => h("tr", {}, sheetCols(x).map((c) => h("td", { class: c.fmt ? "n" : "" }, c.fmt ? fmtQty(r[c.k]) : (r[c.k] ?? "")))))),
      h("tfoot", {}, h("tr", {}, sheetCols(x).map((c, i) => h("td", { class: c.fmt ? "n" : "" }, i === 0 ? "Total" : (c.k === "hours" ? fmtQty(x.hours) : c.k === "output_qty" ? fmtQty(x.output_qty) : ""))))));
    n.append(t, h("div", { class: "sign" }, h("div", {}, "Operator"), h("div", {}, "Site in-charge"), h("div", {}, "Equipment engineer")));
    return n;
  };
  const printAll = (list) => { const n = h("div"); list.forEach((x) => n.append(printable(x))); printFrame("Logsheet by output — " + title, n); };
  box.append(h("div", { class: "bar", style: "margin-top:12px" }, h("h3", { style: "margin:0" }, "Separate logsheet for each output"), h("div", { class: "grow" }),
    h("button", { class: "btn", onclick: () => printAll(outs.filter((x) => x.days.length)) }, "Print all output logsheets")));
  outs.forEach((x) => {
    const p = h("div", { class: "panel", style: "margin-top:10px" });
    p.append(h("div", { class: "bar" }, h("h3", { style: "margin:0" }, "Logsheet — " + x.name), h("div", { class: "grow" }),
      h("button", { class: "btn small", onclick: () => printAll([x]) }, "Print " + x.name + " logsheet")),
    kv(facts(x)), table(sheetCols(x), x.days, { name: "logsheet_" + x.name.toLowerCase().replace(/\W+/g, "_"), totals: ["hours", "output_qty"], empty: "Did not work with " + x.name + " in this period." }));
    box.append(p);
  });
  return box;
}
window.outputSheets = outputSheets;
