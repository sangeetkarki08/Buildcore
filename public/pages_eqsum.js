/* BuildCore 2.33 — machine hours and output summary.
   Opening a machine (Equipment register › the machine, or its passport) shows its operating hours for a project as per
   the entries, month by month (Nepali months when sheets are kept per Nepali month or dates are shown in Nepali), with
   the output of each attachment (bucket, breaker…). Read only. */
"use strict";
(function () {
  const n0 = (x) => x == null || x === "" || Math.abs(Number(x)) < 0.005 ? "" : fmtN(x);
  const dateText = (d) => d ? cellValue({ k: "date" }, { date: d }) : "—";
  const asText = (v) => v instanceof Node ? v.textContent : String(v ?? "");

  async function startCalendar() {
    let cal = "";
    try { cal = typeof lbCalendar === "function" ? (await lbCalendar()).calendar : ""; } catch (e) { /* ignore */ }
    if (cal === "bs") return "bs";
    try { if (typeof nepaliDates === "function" && nepaliDates()) return "bs"; } catch (e) { /* ignore */ }
    return "";                                  /* the engine follows the logsheet setting */
  }

  /* o = { compact, project_id } */
  window.bcoEqSummary = function (eid, o) {
    o = o || {};
    const box = h("div", { class: "eqsum" });
    let v = { id: eid, calendar: null, project_id: o.project_id || (typeof S !== "undefined" && S.project) || null, all: 0 };
    const out = h("div");
    const load = async () => {
      if (v.calendar === null) v.calendar = await startCalendar();
      let d;
      try { d = await api("eq.summary", v); } catch (e) { out.innerHTML = ""; out.append(h("p", { class: "hint red" }, e.message)); return; }
      v.calendar = d.calendar;
      out.innerHTML = "";
      const t = d.totals;
      /* project and month pickers */
      const psel = h("select", { style: "width:auto" },
        h("option", { value: "all", selected: d.project_id == null }, "All projects" + (d.projects.length ? " (" + d.projects.length + ")" : "")),
        d.projects.map((p) => h("option", { value: p.project_id || "", selected: d.project_id === p.project_id }, (p.code || "No project") + " " + (p.name || "") + " · " + fmtN(p.hours) + " h")));
      if (d.project_id != null && !d.projects.some((p) => p.project_id === d.project_id))
        psel.append(h("option", { value: d.project_id, selected: true }, ((d.project || {}).code || "") + " " + ((d.project || {}).name || "") + " · no entries"));
      psel.onchange = () => { if (psel.value === "all") { v.project_id = null; v.all = 1; } else { v.project_id = Number(psel.value); v.all = 0; } load(); };
      const calBtn = (k, label) => h("button", { class: "btn small" + (d.calendar === k ? " primary" : ""), onclick: () => { v.calendar = k; load(); } }, label);
      out.append(h("div", { class: "bar" },
        h("label", { class: "f" }, h("span", {}, "Project"), psel),
        h("div", { class: "grow" }),
        h("span", { class: "hint" }, "Months:"), calBtn("bs", "Nepali"), calBtn("ad", "English")));
      if (!t.entries && !d.waiting.length) {
        out.append(h("p", { class: "hint" }, d.projects.length
          ? "No logsheet or DPR entries for this machine on this project yet. Choose another project above, or All projects."
          : "No logsheet or DPR entries for this machine yet. Hours appear here as soon as a DPR with this machine is approved or a logsheet day is entered."));
        return;
      }
      /* the totals */
      const scope = d.project_id == null ? "all projects" : ((d.project || {}).code || "this project");
      out.append(h("div", { class: "tiles" },
        tile("Operating hours · " + scope, fmtN(t.hours), { sub: t.entries + " entries, " + dateText(t.first) + " to " + dateText(t.last) }),
        tile("Days worked", fmtN(t.days, 0), { sub: t.avg_per_day != null ? fmtN(t.avg_per_day) + " h a day on average" : "" }),
        tile("Idle / breakdown hours", fmtN(t.idle) + " / " + fmtN(t.breakdown), { cls: t.breakdown > 0 ? "warn" : "" }),
        t.fuel ? tile("Fuel on the logsheets", fmtN(t.fuel), { sub: t.fuel_per_hour != null ? fmtN(t.fuel_per_hour) + " per hour" : "" }) : null,
        t.waiting_hours ? tile("On DPRs not approved yet", fmtN(t.waiting_hours) + " h", { cls: "warn", sub: "shown apart, in no total" }) : null,
        t.draft_hours ? tile("Of which logsheet days in draft", fmtN(t.draft_hours) + " h", { sub: "counted, waiting for approval" }) : null));
      /* output by attachment */
      const outs = d.outputs;
      if (outs.length) {
        out.append(h("h3", {}, "Output by attachment"),
          table([{ k: "name", label: "Output / attachment" }, { k: "hours", label: "Hours", fmt: "qty" },
            { label: "Quantity", v: (r) => r.has_qty ? fmtQty(r.qty) : "" }, { k: "unit", label: "Unit" },
            { label: "Output per hour (days with output)", v: (r) => r.per_hour == null ? "" : fmtN(r.per_hour) },
            { label: "Norm per hour", v: (r) => r.norm_output_hr ? fmtN(r.norm_output_hr) : "" }],
          outs, { search: false, name: "machine_output_" + d.equipment.code, empty: "" }));
      }
      /* month by month */
      const cols = [{ k: "label", label: d.calendar === "bs" ? "Nepali month" : "Month" },
        { k: "days", label: "Days", fmt: "qty" }, { k: "hours", label: "Hours", fmt: "qty" }];
      if (!o.compact) cols.push({ k: "idle", label: "Idle h", fmt: "qty" }, { k: "breakdown", label: "Breakdown h", fmt: "qty" });
      if (t.fuel) cols.push({ k: "fuel", label: "Fuel", fmt: "qty" });
      if (t.trips) cols.push({ k: "trips", label: "Trips", fmt: "qty" });
      const flat = d.months.map((m) => Object.assign({}, m));
      const short = (x) => x.name.length > 14 && x.kind && x.kind !== "other" ? x.kind.charAt(0).toUpperCase() + x.kind.slice(1).replace(/_/g, " ") : x.name;
      outs.forEach((x, i) => {
        const hk = "o" + i + "h", qk = "o" + i + "q";
        flat.forEach((m) => { const y = m.outputs[x.name] || {}; m[hk] = y.hours || 0; m[qk] = y.qty || 0; });
        if (outs.length > 1) cols.push({ k: hk, label: short(x) + " h", fmt: "qty", v: (r) => n0(r[hk]) });
        if (x.has_qty) cols.push({ k: qk, label: short(x) + " " + (x.unit || "output"), fmt: "qty", v: (r) => n0(r[qk]) });
      });
      if (t.waiting_hours) cols.push({ k: "waiting_hours", label: "DPR not approved h", fmt: "qty", v: (r) => n0(r.waiting_hours) });
      const totals = cols.filter((c) => c.fmt === "qty").map((c) => c.k);
      out.append(h("h3", {}, "Month by month" + (d.calendar === "bs" ? " (Nepali months)" : "")),
        table(cols, flat.slice().reverse(), { search: false, totals, name: "machine_hours_" + d.equipment.code,
          empty: "No entries.", onRow: o.compact ? null : (r) => { location.hash = "#/eq/books?period=" + encodeURIComponent(r.key); } }));
      if (!o.compact && d.waiting.length) {
        out.append(h("h3", {}, "DPR machine lines not approved yet"),
          table([{ k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { k: "dpr_no", label: "DPR" }, { k: "dpr_status", label: "DPR status", fmt: "status" },
            { k: "hours", label: "Hours", fmt: "qty" }, { k: "out_text", label: "Output / attachment" }], d.waiting, { search: false, export: false }));
      }
      out.append(h("p", { class: "hint" }, d.rule));
    };
    box.append(out);
    load();
    return box;
  };

  /* the machine passport: a first tab "Hours & output", open when the machine opens */
  const passport = PAGES["eq/passport"];
  if (passport && !passport._bco233) {
    PAGES["eq/passport"] = async (root, params) => {
      await passport(root, params);
      const bar = root.querySelector(".tabs");
      if (!bar || !params.id) return;
      const body = bar.nextElementSibling;
      const own = h("button", {}, "Hours & output");
      const mark = (b) => bar.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      bar.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => mark(b)));
      own.onclick = () => { mark(own); body.innerHTML = ""; body.append(window.bcoEqSummary(Number(params.id))); };
      bar.prepend(own);
      if (!params.tab) own.click();
    };
    PAGES["eq/passport"]._bco233 = true;
  }

  /* Equipment register › open a machine: the summary at the top of the machine's form */
  if (typeof MASTERS_UI !== "undefined" && MASTERS_UI.equipment && !MASTERS_UI.equipment._bco233) {
    const prevExtra = MASTERS_UI.equipment.extra;
    MASTERS_UI.equipment.extra = (row) => {
      const parts = [];
      if (row && row.id) {
        parts.push(h("div", { class: "panel", style: "margin-top:14px" },
          h("div", { class: "bar" }, h("h3", { class: "grow", style: "margin:0" }, "Operating hours and output"),
            h("button", { class: "btn small", onclick: (e) => { const ov = e.target.closest(".overlay"); const x = ov && ov.querySelector("header .x"); if (x) x.click(); location.hash = "#/eq/passport?id=" + row.id; } }, "Open full summary")),
          window.bcoEqSummary(row.id, { compact: true, project_id: (typeof S !== "undefined" && S.project) || row.project_id || null })));
      }
      return h("div", {}, ...parts, prevExtra ? prevExtra(row) : "");
    };
    MASTERS_UI.equipment._bco233 = true;
  }
})();
