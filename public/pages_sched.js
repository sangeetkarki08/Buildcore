/* BuildCore 1.9 — schedule core inside Work > Schedule & WBS, the DPR, Events and Cost & earned value.
   CPM network and floats, calendars, contract time, baselines and updates, look-ahead with PPC,
   submittals and the cost-loaded S-curve envelope. Everything is added to the existing screens. */
(function () {
  "use strict";
  const css = `
  .gantt .g-base{position:absolute;top:13px;height:3px;background:#6b7b84;border-radius:2px}
  .gantt .g-late{position:absolute;top:1px;height:14px;border:1.5px dashed #9aa9b1;border-radius:3px;box-sizing:border-box}
  .gantt .g-plan.near{background:#f1d39a}
  .gantt .g-ms{position:absolute;top:1px;width:10px;height:10px;transform:rotate(45deg);background:#0f3a55}
  .gantt .g-ms.crit{background:#b3392c}
  .badge{display:inline-block;font-size:11px;font-weight:650;padding:0 6px;border-radius:9px;line-height:17px;margin-left:4px}
  .badge.crit{background:#fbe9e6;color:#b3392c}.badge.near{background:#fdf3dd;color:#8a5d00}.badge.ok{background:#e3f1e8;color:#2f7a4d}
  .badge.loe{background:#e6eff5;color:#1b5e86}
  table.la td.d{padding:0;width:16px;min-width:16px;border-left:1px solid #eef1ef}
  table.la td.d i{display:block;height:14px;margin:3px 0}
  table.la td.d i.w{background:#1b5e86}table.la td.d i.w.crit{background:#b3392c}table.la td.d i.n{background:#d6ddd8}
  table.la th.d{font-size:10px;padding:2px 0;text-align:center;width:16px}
  table.la th.d.we,table.la td.d.we{background:#f5f7f5}
  table.la td.d.today{box-shadow:inset 2px 0 0 #b3392c}
  .chk{display:inline-block;width:18px;height:18px;border-radius:50%;text-align:center;line-height:18px;font-size:12px;font-weight:700;margin-right:3px;cursor:help}
  .chk.ok{background:#e3f1e8;color:#2f7a4d}.chk.no{background:#fbe9e6;color:#b3392c}
  .weekgrid label{display:inline-flex;align-items:center;gap:4px;margin-right:10px;color:var(--ink)}
  .weekgrid input{width:auto}
  .monthgrid{display:grid;grid-template-columns:repeat(6,minmax(90px,1fr));gap:6px 10px}
  .clock-late{color:#b3392c;font-weight:650}.clock-due{color:#8a5d00;font-weight:650}
  .mini{font-size:12px;color:var(--muted)}
  `;
  document.head.append(h("style", {}, css));

  const DAY = 864e5;
  const dd = (s) => (s ? new Date(s + "T00:00:00") : null);
  const days = (a, b) => Math.round((dd(b) - dd(a)) / DAY);
  const addDays = (s, n) => { const x = dd(s); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
  let OPTS = null;
  const opts = async () => { if (!OPTS) OPTS = await api("sched.options", { project_id: S.project }); return OPTS; };
  const calOpts = () => ((OPTS && OPTS.calendars) || []).map((c) => [c.id, c.name + (c.is_default ? " (default)" : "")]);
  const wtOpts = () => ((OPTS && OPTS.work_types) || []).filter((w) => w[0]).map((w) => [w[0], w[1]]);
  const fl = (v) => (v == null ? "—" : fmtN(v, 0));
  const critBadge = (a) => a.critical ? h("span", { class: "badge crit" }, "critical")
    : a.near_critical ? h("span", { class: "badge near" }, "near-critical")
      : a.work_type === "loe" ? h("span", { class: "badge loe" }, "level of effort") : null;

  /* ── activity form with the scheduling fields ── */
  function activityForm2(a, done) {
    const base = [
      { k: "wbs_id", label: "WBS", type: "select", options: wbsOpts, req: true }, { k: "code", label: "Code" }, { k: "name", label: "Activity", req: true },
      { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), search: true }, { k: "location", label: "Location / chainage" }, { k: "unit", label: "Unit" },
      { k: "planned_qty", label: "Planned quantity", type: "number" }, { k: "planned_start", label: "Planned start (CPM early start after calculation)", type: "date" },
      { k: "planned_finish", label: "Planned finish (CPM early finish after calculation)", type: "date" },
      { k: "weight", label: "Weight (blank = by BOQ value)", type: "number" }, { k: "responsible", label: "Responsible" }, { k: "foreman", label: "Foreman (look-ahead)" },
      { k: "std_labour_prod", label: "Standard output per man-hour", type: "number" }, { k: "std_equip_prod", label: "Standard output per machine-hour", type: "number" },
      { k: "test_required", label: "Test required after work", ph: "e.g. Cube test" }, { k: "is_milestone", label: "Milestone", type: "check" },
      { k: "delay_reason", label: "Delay reason", wide: true }];
    const sch = [
      { k: "duration", label: "Duration (working days; blank = from dates)", type: "number" },
      { k: "predecessors", label: "Predecessors, e.g. 2.01.1, 2.02.1SS+5, 3.01.1FF-2", wide: true },
      { k: "calendar_id", label: "Calendar (blank = project calendar)", type: "select", options: calOpts },
      { k: "work_type", label: "Work type (monsoon windows, weather)", type: "select", options: wtOpts },
      { k: "weather_sensitive", label: "Weather allowance", type: "select", options: [["1", "Add weather days"], ["0", "Not weather sensitive"]], blank: "By work type" },
      { k: "constraint_type", label: "Date constraint", type: "select", options: [["SNET", "Start no earlier than"], ["FNLT", "Finish no later than"], ["MSO", "Must start on"]] },
      { k: "constraint_date", label: "Constraint date", type: "date" },
      { k: "remaining_override", label: "Remaining duration (override, working days)", type: "number" },
      { k: "act_start_override", label: "Actual start (only if DPR has none)", type: "date" },
      { k: "act_finish_override", label: "Actual finish / milestone achieved on", type: "date" },
      { k: "baseline_start", label: "Baseline start", type: "date" }, { k: "baseline_finish", label: "Baseline finish", type: "date" }];
    const risk = [
      { k: "normal_cost", label: "Direct cost at normal duration", type: "number" },
      { k: "crash_dur", label: "Crash duration (working days)", type: "number" }, { k: "crash_cost", label: "Direct cost when crashed", type: "number" },
      { k: "dur_opt", label: "Optimistic duration (PERT)", type: "number" }, { k: "dur_likely", label: "Most likely duration", type: "number" },
      { k: "dur_pess", label: "Pessimistic duration", type: "number" },
      { k: "chainage_from", label: "Chainage from (m, linear works)", type: "number" }, { k: "chainage_to", label: "Chainage to (m)", type: "number" },
      { k: "linear_order", label: "Crew order on the line (1 = leads)", type: "number" }, { k: "norm_code", label: "Norm code (resources)" }];
    const ro = !can("project", "edit");
    const vals = Object.assign({ planned_start: today() }, a || {});
    if (vals.weather_sensitive != null) vals.weather_sensitive = String(vals.weather_sensitive);
    const f1 = form(base.map((x) => Object.assign(x, { readonly: ro })), vals, () => {
      const b = byId(S.L.boq, f1.values().boq_item_id);
      if (b && !f1.values().unit) f1.set("unit", b.unit);
    });
    const f2 = form(sch.map((x) => Object.assign(x, { readonly: ro })), vals);
    const f3 = form(risk.map((x) => Object.assign(x, { readonly: ro })), vals);
    const cpm = a && a.es ? h("div", { class: "panel" }, h("h3", {}, "Calculated (data date ", a.data_date || "last run", ")"), kv([
      ["Early start / finish", (a.es || "—") + " → " + (a.ef || "—")], ["Late start / finish", (a.ls || "—") + " → " + (a.lf || "—")],
      ["Total float", fl(a.tf) + " working days"], ["Free float", fl(a.ff)], ["Independent / interfering float", fl(a.indep_float) + " / " + fl(a.interf_float)],
      ["Remaining duration", fl(a.remaining_dur)], ["% complete", a.pct_complete == null ? "—" : a.pct_complete + "%"],
      ["Weather days added", fl(a.weather_days)], ["Status", critBadge(a) || "has float"]])) : h("p", { class: "hint" }, "Press “Calculate schedule” to get early and late dates and floats.");
    const body = tabs([["Activity", () => f1], ["Scheduling", () => h("div", {}, cpm, f2)], ["Cost, risk & linear", () => f3],
      ["Documents & history", () => a ? recordPanel("activities", a.id, { project_id: S.project, activity_id: a.id, wbs_id: a.wbs_id }) : h("p", { class: "hint" }, "Save first.")]]);
    const vals2 = () => Object.assign({}, f1.values(), f2.values(), f3.values());
    const btns = !ro ? [{ label: "Save", cls: "primary", act: async () => {
      const r = await run("master.save", { table: "activities", row: Object.assign(vals2(), { id: a && a.id, project_id: S.project }) }, "Saved");
      if (r && r.warning) toast(r.warning, "err");
      await loadProjectLists(); done();
    } },
    a ? { label: "+ DPR for this activity", act: () => { location.hash = "#/p/dpr?new=1&activity=" + a.id; } } : null,
    a ? { label: "Delete", cls: "warn", act: async () => { await run("master.delete", { table: "activities", id: a.id }, "Deleted"); await loadProjectLists(); done(); } } : null] : [];
    opts().then(() => {});
    drawer(a ? "Activity " + (a.code || "") + " " + a.name : "New activity", body, btns);
  }
  window.activityForm = (a, done) => { opts().then(() => activityForm2(a, done)); };

  /* ── calculate dialog ── */
  async function calcDialog(after) {
    const f = form([{ k: "data_date", label: "Data date (progress up to)", type: "date", default: today() },
      { k: "notes", label: "Note for this update", wide: true }]);
    modal("Calculate schedule", h("div", {}, h("p", { class: "hint" },
      "Forward and backward pass over the network on the project calendar. Progress comes from approved DPRs: finished work keeps its actual dates, work in progress runs its remaining duration from the data date, and nothing unstarted can start before it. Planned dates on the activities are replaced by the early dates; the first run saves baseline 0 from the dates you had, so nothing is lost."), f),
    [{ label: "Calculate", cls: "primary", act: async () => {
      const r = await run("sched.calc", Object.assign(f.values(), { project_id: S.project }));
      const late = r.late_days;
      toast("Finish " + r.finish + (late != null ? (late > 0 ? " — " + late + " days after contract completion" : " — on time") : ""), late > 0 ? "err" : "ok");
      if (r.warnings && r.warnings.length) setTimeout(() => toast(r.warnings.slice(0, 2).join(" · "), "err"), 400);
      if (after) after(r);
    } }], { narrow: true });
  }

  /* ── the Schedule & WBS page, now with tabs ── */
  const origSchedule = PAGES["p/schedule"];
  PAGES["p/schedule"] = async (root, params) => {
    if (projectGuard(root, "Schedule & WBS")) return;
    await loadProjectLists();
    await opts();
    const editable = can("project", "edit");
    const n = await run("sched.network", { project_id: S.project });
    const run0 = n.run;
    const late = run0 && n.contract.revised ? days(n.contract.revised, run0.finish) : null;
    root.append(pageHead("Schedule & WBS", "Critical path schedule on working-day calendars. Actual quantities come from approved DPRs; press Calculate to update dates, floats and the forecast.",
      editable ? h("button", { class: "btn primary", onclick: () => calcDialog(() => go()) }, "Calculate schedule") : null,
      editable ? h("button", { class: "btn", onclick: () => activityForm(null, go) }, "New activity") : null,
      editable ? h("button", { class: "btn", onclick: () => wbsForm(null, go) }, "New WBS element") : null,
      editable ? h("button", { class: "btn", onclick: () => pasteActivities() }, "Import from Excel / CSV") : null),
    h("div", { class: "tiles" },
      tile("Data date", run0 ? run0.data_date : "not calculated", { sub: run0 ? "last run " + (run0.created || "").slice(0, 16).replace("T", " ") : "press Calculate schedule" }),
      tile("Forecast finish (CPM)", run0 ? run0.finish : "—", { cls: late > 0 ? "bad" : "", sub: run0 && run0.prev_finish && run0.prev_finish !== run0.finish ? "was " + run0.prev_finish : null }),
      tile("Contract completion", n.contract.revised || "not set", { sub: n.contract.eot_days ? "incl. " + fmtN(n.contract.eot_days) + " days EOT" : null }),
      tile(late > 0 ? "Days late" : "Days to spare", late == null ? "—" : Math.abs(late), { cls: late > 0 ? "bad" : "" }),
      tile("LD exposure", fmtMoney(n.ld.amount), { cls: n.ld.amount > 0 ? "bad" : "", sub: n.ld.capped ? "capped" : (n.ld.rate ? fmtMoney(n.ld.rate) + " per day" : "set LD in Contract time") }),
      tile("Critical activities", run0 ? run0.critical_count : "—", { sub: run0 && run0.warnings.length ? run0.warnings.length + " logic warnings" : null })));
    const programme = async () => {
      const box = h("div");
      await origSchedule(box, params);
      const head = box.querySelector("h1");
      if (head) head.closest(".bar").remove();
      return box;
    };
    root.append(tabs([["Programme", programme], ["CPM & floats", () => cpmTab(n)], ["Logic", logicTab], ["Calendars", calendarsTab],
      ["Contract time", contractTab], ["Baselines & updates", baselinesTab], ["Look-ahead & PPC", lookaheadTab],
      ["Submittals", submittalsTab], ["S-curve envelope", envelopeTab]].concat((window.SCHED_TABS || []).map((t) => [t[0], () => t[1](n)])), Number(params.tab || 0)));
    if (params.open) { const x = byId(S.P.activities, params.open); if (x) activityForm(x, go); }
  };

  function cpmTab(n) {
    const acts = n.activities;
    if (!acts.length) return h("div", { class: "panel" }, "No activities yet.");
    const box = h("div");
    if (n.run && n.run.warnings.length) box.append(h("div", { class: "panel" }, h("b", {}, "Logic check"), h("ul", {}, n.run.warnings.map((w) => h("li", {}, w)))));
    const all = acts.flatMap((a) => [a.es || a.planned_start, a.lf || a.ef || a.planned_finish, a.bl_start, a.bl_finish]).filter(Boolean).sort();
    const d0 = all[0], d1 = all[all.length - 1];
    const span = d0 && d1 ? days(d0, d1) + 1 : 0;
    const pos = (s) => (days(d0, s) / span) * 100;
    const bar = (a) => {
      if (!span) return "";
      const s = a.es || a.planned_start, f = a.ef || a.planned_finish;
      const parts = [];
      if (a.bl_start && a.bl_finish) parts.push(h("i", { class: "g-base", style: `left:${pos(a.bl_start)}%;width:${Math.max(0.3, (days(a.bl_start, a.bl_finish) + 1) / span * 100)}%`, title: "Baseline " + a.bl_start + " → " + a.bl_finish }));
      if (a.ls && a.lf && !a.critical) parts.push(h("i", { class: "g-late", style: `left:${pos(a.ls)}%;width:${Math.max(0.3, (days(a.ls, a.lf) + 1) / span * 100)}%`, title: "Late " + a.ls + " → " + a.lf }));
      if (s && f) {
        if (a.is_milestone || s === f && !a.duration) parts.push(h("i", { class: "g-ms" + (a.critical ? " crit" : ""), style: `left:calc(${pos(s)}% - 5px)`, title: s }));
        else parts.push(h("i", { class: "g-plan" + (a.critical ? " crit" : a.near_critical ? " near" : ""), style: `left:${pos(s)}%;width:${Math.max(0.3, (days(s, f) + 1) / span * 100)}%`, title: s + " → " + f },
          h("i", { class: "g-done", style: `width:${Math.min(a.pct_complete || 0, 100)}%` })));
      }
      const t = pos(today());
      if (t >= 0 && t <= 100) parts.push(h("i", { class: "g-today", style: `left:${t}%` }));
      return h("div", { class: "gantt", style: "min-width:260px" }, parts);
    };
    let show = "all";
    const holder = h("div");
    const render = () => {
      holder.innerHTML = "";
      const rows = acts.filter((a) => show === "all" || (show === "critical" ? a.critical : show === "near" ? (a.critical || a.near_critical) : show === "late" ? (a.variance_days || 0) > 0 : !a.actual_finish));
      holder.append(table([
        { label: "Activity", v: (a) => h("span", {}, (a.code || "") + " " + a.name, critBadge(a)) },
        { k: "wbs_code", label: "WBS" },
        { label: "Dur", fmt: "num", v: (a) => a.duration == null ? "" : fmtN(a.duration, 0) },
        { label: "Rem", fmt: "num", v: (a) => a.actual_finish ? 0 : (a.remaining_dur == null ? "" : fmtN(a.remaining_dur, 0)) },
        { label: "%", fmt: "num", v: (a) => a.pct_complete == null ? "" : fmtN(a.pct_complete, 0) },
        { k: "es", label: "Early start" }, { k: "ef", label: "Early finish" }, { k: "ls", label: "Late start" }, { k: "lf", label: "Late finish" },
        { label: "Total float", fmt: "num", v: (a) => a.tf == null ? "" : h("b", { class: a.tf < 0 ? "red" : "" }, fmtN(a.tf, 0)) },
        { label: "Free", fmt: "num", v: (a) => fl(a.ff) }, { label: "Indep.", fmt: "num", v: (a) => fl(a.indep_float) }, { label: "Interf.", fmt: "num", v: (a) => fl(a.interf_float) },
        { label: "vs baseline (d)", fmt: "num", v: (a) => a.variance_days == null ? "" : h("b", { class: a.variance_days > 0 ? "red" : "green" }, (a.variance_days > 0 ? "+" : "") + a.variance_days) },
        { label: "Driven by", v: (a) => { const d = a.driver_id && byId(acts, a.driver_id); return d ? d.code || d.name : ""; } },
        { label: "Timeline (baseline line, late window dashed)", v: bar },
      ], rows, { name: "cpm_floats", onRow: (a) => activityForm(byId(S.P.activities, a.id) ? Object.assign({}, byId(S.P.activities, a.id), { data_date: n.run && n.run.data_date }) : a, go),
        rowClass: (a) => a.critical ? "bad" : a.near_critical ? "flag" : "" }));
    };
    const sel = h("select", { style: "max-width:220px", onchange: (e) => { show = e.target.value; render(); } },
      [["all", "All activities"], ["open", "Not finished"], ["critical", "Critical only"], ["near", "Critical and near-critical"], ["late", "Late against baseline"]].map(([v, l]) => h("option", { value: v }, l)));
    box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Show"), sel), h("div", { class: "grow" }),
      h("span", { class: "hint" }, "Floats in working days. Critical = least total float (0 or negative). Near-critical = within " + n.near_days + " days of it.")), holder);
    render();
    return box;
  }

  /* ── logic ── */
  async function logicTab() {
    const box = h("div");
    const load = async () => {
      const rows = await api("sched.links", { project_id: S.project });
      box.innerHTML = "";
      const editable = can("project", "edit");
      const actList = () => (S.P.activities || []).map((a) => [a.id, (a.code ? a.code + " " : "") + a.name]);
      const f = form([{ k: "pred_id", label: "Predecessor", type: "select", options: actList, search: true },
        { k: "succ_id", label: "Successor", type: "select", options: actList, search: true },
        { k: "type", label: "Type", type: "select", noBlank: true, options: [["FS", "Finish to start"], ["SS", "Start to start"], ["FF", "Finish to finish"], ["SF", "Start to finish"]] },
        { k: "lag", label: "Lag (working days, may be negative)", type: "number", default: 0 }]);
      box.append(h("div", { class: "panel" }, h("h2", {}, "Add a link"),
        h("p", { class: "hint" }, "FS: the successor starts after the predecessor finishes. SS: starts after the predecessor has started (+ lag). FF: finishes after it finishes. SF: finishes after it starts. Loops are refused."),
        f, editable ? h("div", { class: "actions" },
          h("button", { class: "btn primary", onclick: async () => { await run("sched.link_save", { row: f.values() }, "Linked"); await loadProjectLists(); load(); } }, "Add link"),
          h("button", { class: "btn", onclick: pasteLinks }, "Import links from Excel / CSV"),
          h("button", { class: "btn", onclick: async () => {
            if (!(await ask("Suggest first-cut logic", "Inside each WBS element, link each activity to the one before it (finish-to-start, or start-to-start with a lag where they overlap). Existing links stay. Review the result — this is a starting point, not the engineer's logic."))) return;
            const r = await run("sched.links_suggest", { project_id: S.project });
            toast(r.created + " links added", "ok"); await loadProjectLists(); load();
          } }, "Suggest links from dates")) : null));
      box.append(table([{ label: "Successor", v: (r) => (r.succ_code || "") + " " + r.succ_name }, { label: "Predecessor", v: (r) => (r.pred_code || "") + " " + r.pred_name },
        { k: "type", label: "Type" }, { k: "lag", label: "Lag", fmt: "num" },
        { label: "", v: (r) => editable ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("sched.link_delete", { id: r.id }, "Removed"); load(); } }, "Remove") : "" }],
      rows, { name: "schedule_links", empty: "No links yet. Without links every activity keeps its own planned start (start-no-earlier-than) and the critical path is only the longest single activity." }));
    };
    const pasteLinks = () => window.bcoImport({ kind: "links", title: "links", onDone: async () => { await loadProjectLists(); load(); } });
    const pasteLinksOld = () => {
      const ta = h("textarea", { style: "min-height:180px;font-family:monospace", placeholder: "successor\tpredecessor\ttype\tlag" });
      modal("Paste links", h("div", {}, h("p", { class: "hint" }, "One link per line: successor code, predecessor code, type (FS/SS/FF/SF, blank = FS), lag in working days. Tabs or commas."), ta),
        [{ label: "Import", cls: "primary", act: async () => { const r = await run("sched.links_paste", { project_id: S.project, text: ta.value }); toast(r.created + " links added" + (r.errors.length ? "; " + r.errors.length + " lines skipped" : ""), r.errors.length ? "err" : "ok"); load(); } }]);
    };
    await load();
    return box;
  }

  /* ── calendars ── */
  async function calendarsTab() {
    const box = h("div");
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const load = async () => {
      const d = await api("sched.cal_list", { project_id: S.project });
      OPTS = null; await opts();
      box.innerHTML = "";
      const editable = can("project", "edit");
      const projSel = h("select", { disabled: !editable, onchange: async (e) => { await run("sched.project_calendar", { project_id: S.project, calendar_id: e.target.value }, "Project calendar set"); load(); } },
        h("option", { value: "" }, "Company default"), d.calendars.map((c) => h("option", { value: c.id, selected: String(c.id) === String(d.project_calendar) }, c.name)));
      box.append(h("div", { class: "panel" }, h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Calendar for this project"), projSel), h("div", { class: "grow" }),
        editable ? h("button", { class: "btn", onclick: () => calEdit(null) }, "New calendar") : null),
      table([{ k: "name", label: "Calendar" }, { label: "Working days", v: (c) => WEEKDAYS.filter((_, i) => c.week[i] === "1").join(" ") },
        { label: "Weather days / year", fmt: "num", v: (c) => fmtN(Object.values(c.weather || {}).reduce((a, b) => a + Number(b || 0), 0), 1) },
        { label: "Default", v: (c) => c.is_default ? "Yes" : "" }, { label: "For", v: (c) => c.project_id ? nm.pcode(c.project_id) : "All projects" }, { k: "notes", label: "Notes" }],
      d.calendars, { search: false, export: false, onRow: editable ? calEdit : null })));
      // holidays
      const hf = form([{ k: "date", label: "Date (AD 2026-10-17 or BS 2083-06-31; a range: from..to)" }, { k: "name", label: "Holiday" },
        { k: "kind", label: "Kind", type: "select", noBlank: true, options: [["public", "Public holiday"], ["festival", "Festival shutdown"], ["site", "Site shutdown / strike"]] },
        { k: "calendar_id", label: "Calendar", type: "select", options: d.calendars.map((c) => [c.id, c.name]), blank: "All calendars" }]);
      box.append(h("div", { class: "panel" }, h("h2", {}, "Holidays and shutdowns"),
        h("p", { class: "hint" }, "Public holidays for 2083 BS and the Dashain and Tihar days are loaded. Check them against the government notice each year, add Eid and local festivals, and add bandh or strike days as site shutdowns."),
        editable ? h("div", {}, hf, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { const r = await run("sched.hol_save", { rows: [hf.values()] }); toast(r.saved + " day(s) added", "ok"); load(); } }, "Add"),
          h("button", { class: "btn", onclick: pasteHolidays }, "Import holidays from Excel / CSV"))) : null,
        table([{ k: "date", label: "Date (AD)" }, { k: "bs", label: "BS" }, { label: "Day", v: (x) => WEEKDAYS[(dd(x.date).getDay() + 6) % 7] }, { k: "name", label: "Holiday" }, { k: "kind", label: "Kind" },
          { label: "Calendar", v: (x) => x.calendar_id ? (d.calendars.find((c) => c.id === x.calendar_id) || {}).name : "All" },
          { label: "", v: (x) => editable ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("sched.hol_delete", { id: x.id }); load(); } }, "Remove") : "" }],
        d.holidays, { name: "holidays" })));
      // monsoon and other windows
      const wf = form([{ k: "work_type", label: "Work type", type: "select", noBlank: true, options: d.work_types.filter((w) => w[0]) },
        { k: "bs_from", label: "From (BS month-day, e.g. 03-01 = Asar 1)" }, { k: "bs_to", label: "To (BS month-day, e.g. 05-31)" },
        { k: "calendar_id", label: "Calendar", type: "select", options: d.calendars.map((c) => [c.id, c.name]), blank: "All calendars" }, { k: "reason", label: "Reason", wide: true }]);
      box.append(h("div", { class: "panel" }, h("h2", {}, "No-work windows by work type (monsoon and seasons)"),
        h("p", { class: "hint" }, "Every year in these Nepali months, activities of that work type cannot be worked (e.g. river diversion Asar to Bhadra). Other work goes on."),
        table([{ k: "work_type", label: "Work type" }, { label: "From – to (BS)", v: (w) => w.bs_from + " → " + w.bs_to }, { label: "Next", v: (w) => (w.next || []).join("; ") }, { k: "reason", label: "Reason" },
          { label: "", v: (w) => editable ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("sched.win_delete", { id: w.id }); load(); } }, "Remove") : "" }], d.windows, { search: false, export: false }),
        editable ? h("div", {}, wf, h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("sched.win_save", { row: wf.values() }, "Window saved"); load(); } }, "Add window"))) : null));
      // weather allowance learnt from DPR
      const wbox = h("div", { class: "panel" }, h("h2", {}, "Weather allowance from DPR records"), h("p", { class: "muted" }, "Loading…"));
      box.append(wbox);
      const ws = await api("sched.weather_stats", { project_id: S.project });
      wbox.lastChild.remove();
      const target = h("select", {}, d.calendars.map((c) => h("option", { value: c.id, selected: String(c.id) === String(d.project_calendar || d.default) }, c.name)));
      wbox.append(h("p", { class: "hint" }, "A day counts as lost when the DPR marks it lost, when the weather was heavy rain or snow, or in proportion to the weather delay hours. Weather-sensitive activities (earthwork, river, open concrete, blacktop, lines) get these days added to their duration."),
        table([{ k: "name", label: "Month" }, { k: "dpr_days", label: "DPR days", fmt: "num" }, { k: "rain_days", label: "Rain days", fmt: "num" }, { k: "lost_days", label: "Lost days", fmt: "num" },
          { label: "Expected lost days / month", fmt: "num", v: (x) => x.expected_lost == null ? "no data" : fmtN(x.expected_lost, 1) }], ws, { search: false, name: "weather_allowance" }),
        editable ? h("div", { class: "bar", style: "margin-top:8px" }, h("label", { class: "f" }, h("span", {}, "Apply to calendar"), target),
          h("button", { class: "btn", onclick: async () => { await run("sched.weather_stats", { project_id: S.project, apply_to: target.value }, "Weather allowance saved on the calendar"); load(); } }, "Use these figures")) : null);
    };
    const calEdit = (c) => {
      const week = h("div", { class: "weekgrid" }, WEEKDAYS.map((d, i) => h("label", {}, h("input", { type: "checkbox", checked: c ? c.week[i] === "1" : i !== 5, "data-i": i }), d)));
      const f = form([{ k: "name", label: "Name", req: true }, { k: "hours_day", label: "Hours per day", type: "number", default: 8 },
        { k: "project_id", label: "Only for project", type: "select", options: opt.projects }, { k: "is_default", label: "Company default calendar", type: "check" }, { k: "notes", label: "Notes", wide: true }], c || {});
      const w = (c && c.weather) || {};
      const mg = h("div", { class: "monthgrid" }, MONTHS.map((m, i) => h("label", { class: "f" }, h("span", {}, m + " lost days"), h("input", { type: "number", step: "any", value: w[String(i + 1)] ?? "", "data-m": i + 1 }))));
      modal(c ? "Calendar " + c.name : "New calendar", h("div", {}, f, h("h3", {}, "Working days"), week, h("h3", {}, "Weather allowance (working days lost per month)"), mg),
        [{ label: "Save", cls: "primary", act: async () => {
          const wk = [...week.querySelectorAll("input")].map((i) => (i.checked ? "1" : "0")).join("");
          const wea = {}; mg.querySelectorAll("input").forEach((i) => { if (i.value !== "") wea[i.dataset.m] = i.value; });
          await run("sched.cal_save", { row: Object.assign(f.values(), { id: c && c.id, week: wk, weather: wea }) }, "Calendar saved"); load();
        } }, c ? { label: "Delete", cls: "warn", act: async () => { await run("sched.cal_delete", { id: c.id }, "Deleted"); load(); } } : null]);
    };
    const pasteHolidays = () => window.bcoImport({ kind: "holidays", title: "holidays", onDone: load });
    const pasteHolidaysOld = () => {
      const ta = h("textarea", { style: "min-height:180px;font-family:monospace", placeholder: "2083-07-22\tTihar\tfestival" });
      modal("Paste holidays", h("div", {}, h("p", { class: "hint" }, "One per line: date (AD or BS, or a range from..to), name, kind. Tabs or commas."), ta),
        [{ label: "Add", cls: "primary", act: async () => { const r = await run("sched.hol_save", { text: ta.value }); toast(r.saved + " day(s) added" + (r.bad.length ? "; could not read " + r.bad.join(", ") : ""), r.bad.length ? "err" : "ok"); load(); } }]);
    };
    await load();
    return box;
  }
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  /* ── contract time register ── */
  async function contractTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("ctime.get", { project_id: S.project });
      box.innerHTML = "";
      const editable = can("project", "approve");
      const p = d.project;
      const f = form([{ k: "ntp_date", label: "Notice to proceed (commencement)", type: "date" }, { k: "tfc_days", label: "Time for completion (days)", type: "number" },
        { k: "tfc_basis", label: "Counted in", type: "select", noBlank: true, options: [["calendar", "Calendar days"], ["working", "Working days (project calendar)"]] },
        { k: "completion_date", label: "Completion date (if stated instead)", type: "date" },
        { k: "ld_per_day", label: "Liquidated damages per day", type: "number" }, { k: "ld_cap_pct", label: "LD cap (% of contract price)", type: "number" },
        { k: "notice_days", label: "Notice period for claims (days)", type: "number", ph: String(d.notice_default) },
        { k: "float_owner", label: "Float belongs to", type: "select", options: d.float_owners.filter((x) => x[0]) },
        { k: "near_crit_days", label: "Near-critical threshold (working days)", type: "number" }, { k: "indirect_per_day", label: "Site overhead (indirect cost) per day", type: "number" },
        { k: "time_notes", label: "Contract clauses on time (e.g. GCC 8.2, 8.4, 8.7, 20.1)", type: "textarea", wide: true }].map((x) => Object.assign(x, { readonly: !editable })), Object.assign({ tfc_basis: "calendar" }, p));
      const c = d.contract;
      box.append(h("div", { class: "tiles" },
        tile("Original completion", c.original || "—"), tile("EOT granted", fmtN(c.eot_days) + " days", { sub: "events " + fmtN(c.eot_events) + " · variations " + fmtN(c.eot_variations) }),
        tile("Revised completion", c.revised || "—"), tile("Forecast finish", d.forecast_finish || "calculate first", { cls: d.ld.days > 0 ? "bad" : "", sub: d.data_date ? "data date " + d.data_date : null }),
        tile("Days to completion", d.days_to_completion == null ? "—" : d.days_to_completion),
        tile("LD exposure", fmtMoney(d.ld.amount), { cls: d.ld.amount > 0 ? "bad" : "", sub: d.ld.days + " days" + (d.ld.capped ? " (cap " + fmtMoney(d.ld.cap) + ")" : "") })));
      box.append(h("div", { class: "panel" }, h("h2", {}, "Contract time register"), f,
        editable ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("ctime.save", { project_id: S.project, row: f.values() }, "Saved"); load(); } }, "Save")) : null));
      // milestones
      const mf = form([{ k: "name", label: "Milestone / section", req: true }, { k: "due_date", label: "Due date", type: "date", req: true },
        { k: "activity_id", label: "Schedule activity that achieves it", type: "select", options: () => actOpts(), search: true },
        { k: "ld_per_day", label: "LD per day for this milestone", type: "number" }, { k: "section", label: "Section" }]);
      box.append(h("div", { class: "panel" }, h("h2", {}, "Sectional completion and milestones"),
        table([{ k: "name", label: "Milestone" }, { k: "due_date", label: "Due" }, { label: "Activity", v: (m) => (m.act_code || "") + " " + (m.act_name || "") },
          { k: "forecast", label: "Forecast / achieved" }, { label: "Late (d)", fmt: "num", v: (m) => m.late_days ? h("b", { class: "red" }, m.late_days) : (m.late_days === 0 ? "0" : "") },
          { k: "ld", label: "LD", fmt: "money" }, { label: "", v: (m) => editable ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("ctime.ms_delete", { id: m.id }); load(); } }, "Remove") : "" }],
        d.milestones, { search: false, export: false, empty: "No milestones. Add the sectional completion dates from the contract." }),
        editable ? h("div", {}, mf, h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("ctime.ms_save", { row: Object.assign(mf.values(), { project_id: S.project }) }, "Milestone saved"); load(); } }, "Add milestone"))) : null));
      // notice clock
      box.append(h("div", { class: "panel" }, h("h2", {}, "Notice clock"), h("p", { class: "hint" }, "The clock starts when an event is logged (in the DPR or the Events register). Mark the notice as sent once the letter has gone."),
        table([{ k: "no", label: "Event" }, { k: "title", label: "Title" }, { k: "date", label: "Logged" }, { k: "deadline", label: "Notice by" },
          { label: "Days left", v: (x) => h("span", { class: x.state === "late" ? "clock-late" : x.state === "due" ? "clock-due" : "" }, x.days_left) },
          { label: "", v: (x) => can("project", "edit") ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("ctime.notice_sent", { id: x.id }, "Marked as sent"); load(); } }, "Notice sent") : "" }],
        d.notice_clock, { search: false, name: "notice_clock", empty: "No open events waiting for notice.", rowClass: (x) => x.state === "late" ? "bad" : x.state === "due" ? "flag" : "", onRow: () => { location.hash = "#/p/events"; } })));
      if (d.eot.length) box.append(h("div", { class: "panel" }, h("h2", {}, "Extension of time"), table([{ k: "no", label: "Event" }, { k: "title", label: "Title" }, { k: "status", label: "Status", fmt: "status" },
        { k: "eot_claimed", label: "Days claimed", fmt: "num" }, { k: "eot_granted", label: "Days granted", fmt: "num" }, { k: "prolongation_cost", label: "Prolongation cost", fmt: "money" }], d.eot, { search: false, name: "eot" })));
    };
    await load();
    return box;
  }

  /* ── baselines, updates, recovery, as-built ── */
  async function baselinesTab() {
    const box = h("div");
    const load = async () => {
      const [d, cmp, rec] = await Promise.all([api("base.list", { project_id: S.project }), api("base.compare", { project_id: S.project }), api("base.recovery", { project_id: S.project })]);
      box.innerHTML = "";
      const editable = can("project", "approve");
      box.append(h("div", { class: "panel" }, h("div", { class: "bar" }, h("h2", { class: "grow" }, "Baselines"),
        editable ? h("button", { class: "btn primary", onclick: async () => { const nmv = await ask("Save baseline", "Save the current calculated schedule as a new baseline and measure progress against it from now on?", { input: "Name, e.g. Baseline 1 — approved programme", required: true }); if (nmv === null) return; await run("base.save", { project_id: S.project, name: nmv }, "Baseline saved"); load(); } }, "Save current as baseline") : null),
      table([{ k: "no", label: "No." }, { k: "name", label: "Name" }, { k: "data_date", label: "Data date" }, { k: "start", label: "Start" }, { k: "finish", label: "Finish" },
        { label: "In use", v: (b) => b.is_current ? h("b", { class: "green" }, "current") : (editable ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("base.set_current", { id: b.id }, "Baseline in use"); load(); } }, "Use this") : "") },
        { label: "", v: (b) => editable && !b.is_current ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("base.delete", { id: b.id }, "Deleted"); load(); } }, "Delete") : "" }],
      d.baselines, { search: false, export: false, empty: "Baseline 0 is saved automatically at the first calculation." })));
      box.append(h("div", { class: "panel" }, h("h2", {}, "Updates (each calculation)"), table([{ k: "data_date", label: "Data date" }, { k: "finish", label: "Forecast finish" }, { k: "prev_finish", label: "Previous" },
        { label: "Moved (d)", fmt: "num", v: (r) => r.prev_finish ? days(r.prev_finish, r.finish) : "" }, { k: "target", label: "Contract" }, { k: "critical_count", label: "Critical", fmt: "num" },
        { label: "By", v: (r) => nm.user(r.user_id) }, { k: "notes", label: "Note" }], d.updates, { search: false, name: "schedule_updates" })));
      box.append(h("div", { class: "panel" }, h("h2", {}, "Slipped against the current baseline (" + cmp.slipped + ")"),
        table([{ label: "Activity", v: (r) => (r.code || "") + " " + r.name }, { k: "status", label: "Status" }, { k: "bl_start", label: "Baseline start" }, { k: "start", label: "Start" },
          { k: "bl_finish", label: "Baseline finish" }, { k: "finish", label: "Forecast / actual finish" },
          { label: "Finish variance (d)", fmt: "num", v: (r) => r.finish_var == null ? "" : h("b", { class: r.finish_var > 0 ? "red" : "green" }, (r.finish_var > 0 ? "+" : "") + r.finish_var) },
          { label: "Float then / now", v: (r) => fl(r.bl_tf) + " / " + fl(r.tf) }], cmp.rows.filter((r) => (r.finish_var || 0) > 0), { name: "slipped_activities", empty: "Nothing has slipped against the baseline." })));
      box.append(h("div", { class: "panel" }, h("h2", {}, "Float change since the previous update"), table([{ label: "Activity", v: (r) => (r.code || "") + " " + r.name }, { k: "old_tf", label: "Float before", fmt: "num" }, { k: "tf", label: "Float now", fmt: "num" },
        { label: "Change", fmt: "num", v: (r) => h("b", { class: r.change < 0 ? "red" : "green" }, (r.change > 0 ? "+" : "") + r.change) }, { k: "old_finish", label: "Finish before" }, { k: "finish", label: "Finish now" }],
      cmp.float_change, { name: "float_change", empty: "Needs two calculations to compare." })));
      box.append(h("div", { class: "panel" }, h("h2", {}, "Recovery schedule"), h("p", {}, rec.advice),
        table([{ label: "Activity", v: (r) => (r.code || "") + " " + r.name }, { k: "tf", label: "Total float", fmt: "num" }, { k: "gain_needed", label: "Days to gain", fmt: "num" },
          { k: "remaining", label: "Remaining", fmt: "num" }, { k: "can_crash", label: "Can crash (d)", fmt: "num" }, { k: "cost_per_day", label: "Crash cost / day", fmt: "money" }, { k: "foreman", label: "Foreman" }],
        rec.activities, { name: "recovery", empty: "No negative float." })));
      const ab = h("div", { class: "panel" }, h("h2", {}, "As-built schedule (from DPR history)"), h("button", { class: "btn small", onclick: async () => {
        const rows = await api("base.asbuilt", { project_id: S.project });
        ab.lastChild.remove();
        ab.append(table([{ label: "Activity", v: (r) => (r.code || "") + " " + r.name }, { k: "bl_start", label: "Baseline start" }, { k: "start", label: "Actual start" },
          { k: "bl_finish", label: "Baseline finish" }, { label: "Actual finish", v: (r) => r.finish || "in progress (last " + r.last_work + ")" }, { k: "days_worked", label: "Days worked", fmt: "num" },
          { k: "span", label: "Calendar span", fmt: "num" }, { label: "Done", v: (r) => fmtN(r.qty) + " / " + fmtN(r.planned_qty) + " " + (r.unit || "") }, { label: "Stoppages ≥ 7 days", v: (r) => r.gaps.join("; ") }],
        rows, { name: "as_built" }));
      } }, "Build from DPRs"));
      box.append(ab);
    };
    await load();
    return box;
  }

  /* ── look-ahead and PPC ── */
  async function lookaheadTab() {
    const box = h("div");
    const O = await opts();
    const reasons = O.reasons;
    let week = null;
    const load = async () => {
      const d = await api("look.get", { project_id: S.project, week_start: week, weeks: 3 });
      week = d.week_start;
      box.innerHTML = "";
      const editable = can("project", "edit");
      const wk = h("input", { type: "date", value: d.week_start, style: "max-width:170px" });
      box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Week starting (Sunday)"), wk),
        h("button", { class: "btn", onclick: () => { week = wk.value; load(); } }, "Show"),
        h("button", { class: "btn", onclick: () => { week = addDays(d.week_start, -7); load(); } }, "‹ Week"), h("button", { class: "btn", onclick: () => { week = addDays(d.week_start, 7); load(); } }, "Week ›"),
        h("div", { class: "grow" }), h("span", { class: "hint" }, d.ready + " ready · " + d.blocked + " blocked"),
        h("button", { class: "btn", onclick: () => window.print() }, "Print for the site meeting")));
      const tdy = today();
      const head = h("tr", {}, h("th", {}, "Task"), h("th", {}, "Foreman"), h("th", { class: "num" }, "This week"), h("th", {}, "Checks"),
        d.days.map((x) => { const wd = dd(x).getDay(); return h("th", { class: "d" + (wd === 6 ? " we" : ""), title: x }, x.slice(8)); }));
      const foremen = {};
      const tb = h("tbody", {}, d.rows.map((r) => {
        const fm = h("input", { value: r.foreman || "", style: "min-width:90px", disabled: !editable });
        foremen[r.id] = { fm, r };
        return h("tr", { class: r.ready ? "" : "flag" },
          h("td", {}, (r.code || "") + " " + r.name, critBadge(r), h("div", { class: "mini" }, (r.es || "") + " → " + (r.ef || "") + (r.location ? " · " + r.location : ""))),
          h("td", {}, fm), h("td", { class: "num" }, fmtN(r.qty_week1) + " " + (r.unit || "")),
          h("td", {}, r.checks.map((ch) => h("span", { class: "chk " + (ch.ok ? "ok" : "no"), title: ch.label + ": " + ch.why + (ch.manual ? " (set by hand)" : "") }, ch.ok ? "✓" : "✗"))),
          r.bar.map((v, i) => { const x = d.days[i]; const wd = dd(x).getDay(); return h("td", { class: "d" + (wd === 6 ? " we" : "") + (x === tdy ? " today" : "") }, v ? h("i", { class: v === 2 ? "w" + (r.critical ? " crit" : "") : "n" }) : null); }));
      }));
      box.append(h("div", { class: "tablewrap" }, h("table", { class: "la" }, h("thead", {}, head), tb)),
        h("p", { class: "hint" }, "Checks, left to right: drawings & approvals · material in stock or on order · machines available · inspection / no QA hold · preceding work done. Hover a mark for the reason. The first week after the look-back week is the one foremen commit to; PPC is measured on it."));
      if (editable && d.rows.length) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        const rows = Object.values(foremen).filter(({ r }) => r.qty_week1 > 0 || r.ready).map(({ fm, r }) => ({ activity_id: r.id, planned_qty: r.qty_week1, foreman: fm.value }));
        const res = await run("look.commit", { project_id: S.project, week_start: d.week_start, rows, replace: 1 });
        toast(res.tasks + " tasks committed for the week of " + res.week_start, "ok");
      } }, "Commit next week's plan (" + d.week_start + ")")));
      // PPC review of last week
      const rv = await api("look.review", { project_id: S.project, week_start: addDays(d.week_start, -7) });
      const ppc = await api("look.ppc", { project_id: S.project });
      box.append(h("div", { class: "cols" },
        h("div", { class: "panel" }, h("h2", {}, "Week of " + rv.week_start + ": PPC " + (rv.ppc == null ? "—" : rv.ppc + "%")),
          table([{ label: "Task", v: (r) => (r.code || "") + " " + r.name }, { k: "foreman", label: "Foreman" }, { label: "Promised", v: (r) => fmtN(r.planned_qty) + " " + (r.unit || "") },
            { label: "Done", v: (r) => fmtN(r.actual) }, { label: "Complete?", v: (r) => r.is_done ? h("b", { class: "green" }, "Yes") : h("b", { class: "red" }, "No") },
            { label: "Why not", v: (r) => r.is_done || !editable ? (reasons.find((x) => x[0] === r.reason) || [0, r.reason || ""])[1] : h("select", { onchange: async (e) => { await run("look.mark", { id: r.id, done: 0, reason: e.target.value }); } }, h("option", { value: "" }, "—"), reasons.map(([k, l]) => h("option", { value: k, selected: r.reason === k }, l))) },
            { label: "", v: (r) => editable ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("look.mark", { id: r.id, done: r.is_done ? 0 : 1, reason: r.reason }); load(); } }, r.is_done ? "Mark not done" : "Mark done") : "" }],
          rv.rows, { search: false, name: "ppc_week", empty: "Nothing was committed for that week." })),
        h("div", { class: "panel" }, h("h2", {}, "Percent plan complete by week"),
          ppc.weeks.length ? lineChart(ppc.weeks.map((w) => w.week_start.slice(5)), [{ name: "PPC %", color: "#1b5e86", values: ppc.weeks.map((w) => w.ppc) }], { max: 100, unit: "%" }) : h("p", { class: "muted" }, "PPC appears after the first committed week has passed."),
          ppc.reasons.length ? h("div", {}, h("h3", {}, "Reasons for tasks not done"), table([{ k: "reason", label: "Reason" }, { k: "count", label: "Times", fmt: "num" }], ppc.reasons, { search: false, export: false })) : null)));
    };
    await load();
    return box;
  }

  /* ── submittals (drawings, method statements, material approvals) ── */
  const SUB_KINDS = [["drawing", "Drawing"], ["method", "Method statement"], ["material", "Material approval"], ["sample", "Sample / mock-up"], ["design", "Design submission"], ["other", "Other"]];
  const SUB_STATUS = [["planned", "Planned"], ["submitted", "Submitted"], ["approved", "Approved"], ["approved_as_noted", "Approved as noted"], ["revise", "Revise & resubmit"], ["rejected", "Rejected"]];
  const submittalsPage = registerPage({ table: "submittals", module: "project", title: "Submittals", single: "submittal",
    sub: "Drawings, method statements and material approvals with the review period from the contract. Late approvals are flagged against the activity that needs them, and open ones block that activity in the look-ahead.",
    filters: [{ k: "status", label: "Status", type: "select", options: SUB_STATUS, blank: "All" }],
    cols: [{ k: "no", label: "No." }, { k: "kind", label: "Type" }, { k: "title", label: "Title" }, { k: "ref", label: "Reference" }, { label: "Activity", v: (r) => nmAct(r.activity_id) },
      { k: "required_by", label: "Needed by" }, { k: "submitted_date", label: "Submitted" }, { label: "Due back", v: (r) => r.due_back || (r.submitted_date && r.review_days ? addDays(r.submitted_date, Number(r.review_days)) : "") },
      { k: "returned_date", label: "Returned" }, { k: "status", label: "Status", fmt: "status" }],
    rowClass: (r) => { const due = r.due_back || (r.submitted_date && r.review_days ? addDays(r.submitted_date, Number(r.review_days)) : null); return !["approved", "approved_as_noted"].includes(r.status) && ((r.required_by && r.required_by < today()) || (due && due < today())) ? "bad" : ""; },
    defaults: () => ({ kind: "drawing", status: "planned", review_days: 14 }),
    fields: () => [{ k: "kind", label: "Type", type: "select", noBlank: true, options: SUB_KINDS }, { k: "title", label: "Title", req: true, wide: true }, { k: "ref", label: "Drawing / document no." }, { k: "revision", label: "Revision" },
      { k: "activity_id", label: "Activity that needs it", type: "select", options: () => actOpts(), search: true }, { k: "required_by", label: "Needed by", type: "date" },
      { k: "submitted_date", label: "Submitted on", type: "date" }, { k: "review_days", label: "Review period (days)", type: "number" }, { k: "due_back", label: "Due back (blank = submitted + review)", type: "date" },
      { k: "returned_date", label: "Returned on", type: "date" }, { k: "status", label: "Status", type: "select", noBlank: true, options: SUB_STATUS }, { k: "party", label: "Reviewer / consultant" }, { k: "remarks", label: "Remarks", type: "textarea", wide: true }] });
  async function submittalsTab() {
    const b = h("div");
    await submittalsPage(b, {});
    const t = b.querySelector("h1"); if (t) { const p = t.parentElement.querySelector(".sub"); t.remove(); if (p) p.classList.add("hint"); }
    return b;
  }

  /* ── cost-loaded S-curve envelope (also on Cost & earned value) ── */
  async function envelopeChart() {
    const d = await api("sched.envelope", { project_id: S.project });
    if (!d.points.length) return h("p", { class: "muted" }, "Add activities with dates and calculate the schedule to see the envelope.");
    const money = d.unit === "money";
    const sc = money ? 1e6 : 1;
    const v = (k) => d.points.map((p) => (p[k] == null ? null : Math.round(p[k] / sc * 10) / 10));
    const series = [{ name: "Early start", color: "#1b5e86", values: v("early") }, { name: "Late start", color: "#7c93a1", values: v("late"), dash: true },
      { name: "Baseline (planned value)", color: "#2f7a4d", values: v("baseline") }, { name: "Earned value", color: "#d9950f", values: v("ev") }];
    if (money && d.points.some((p) => p.ac != null)) series.push({ name: "Actual cost", color: "#b3392c", values: v("ac") });
    const last = [...d.points].reverse().find((p) => p.ev != null) || {};
    return h("div", {}, lineChart(d.points.map((p) => p.date.slice(2, 7)), series, { unit: money ? "M" : "%", height: 260 }),
      h("p", { class: "hint" }, "Budget at completion " + (money ? fmtMoney(d.bac) : "100%") + ". Values in " + (money ? "millions" : "% of weight") + ". " + d.note +
        (last.date ? " At " + last.date + ": planned " + fmtMoney(last.baseline) + ", earned " + fmtMoney(last.ev) + (last.ac != null ? ", actual cost " + fmtMoney(last.ac) : "") + "." : "")),
      h("p", { class: "hint" }, "Earned value inside the envelope means the job is within its float; below the late-start curve it is behind the latest schedule that still finishes on time."));
  }
  async function envelopeTab() { return h("div", { class: "panel" }, h("h2", {}, "Cost-loaded S-curves: early, late, baseline, earned and actual"), await envelopeChart()); }

  const origEvm = PAGES["p/evm"];
  PAGES["p/evm"] = async (root, params) => {
    await origEvm(root, params);
    if (!S.project) return;
    const panel = h("div", { class: "panel" }, h("h2", {}, "S-curve envelope (from the CPM schedule)"), h("p", { class: "muted" }, "Loading…"));
    const firstTable = root.querySelector(".tablewrap");
    const anchor = firstTable ? firstTable.closest("div") : null;
    if (anchor && anchor.parentElement === root) root.insertBefore(panel, anchor); else root.append(panel);
    try { panel.lastChild.replaceWith(await envelopeChart()); } catch (e) { panel.lastChild.textContent = e.message; }
  };

  /* ── events: activities affected, notice clock, excusable / compensable ── */
  const EVENT_TYPES2 = [["delay", "Delay"], ["instruction", "Instruction"], ["notice", "Notice"], ["claim", "Claim"], ["eot", "Extension of time"], ["variation", "Variation request"], ["escalation", "Price escalation"], ["other", "Other"]];
  const EVENT_STATUS2 = [["open", "Open"], ["notified", "Notice sent"], ["claimed", "Claim submitted"], ["agreed", "Agreed"], ["rejected", "Rejected"], ["closed", "Closed"]];
  const actCodes = (ids) => String(ids || "").split(",").filter(Boolean).map((i) => { const a = byId(S.P.activities, i); return a ? a.code || a.name : "#" + i; }).join(", ");
  PAGES["p/events"] = registerPage({ table: "events", module: "commercial", alsoProject: true, title: "Events, notices & claims", single: "event",
    sub: "Contract events with the activities they affect, the notice clock (it starts when the event is logged), time and cost impact, and the delay class used for EOT. Delays from DPRs arrive here automatically.",
    filters: [{ k: "status", label: "Status", type: "select", options: EVENT_STATUS2, blank: "All" }, { k: "type", label: "Type", type: "select", options: EVENT_TYPES2, blank: "All" }],
    cols: [{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "type", label: "Type" }, { k: "title", label: "Title" }, { label: "Activities", v: (r) => [nmAct(r.activity_id), actCodes(r.activity_ids)].filter(Boolean).join(", ") },
      { k: "notice_deadline", label: "Notice by" }, { k: "notice_sent", label: "Notice sent" },
      { label: "Class", v: (r) => [r.excusable === 1 ? "excusable" : r.excusable === 0 ? "non-excusable" : "", r.compensable ? "compensable" : "", r.concurrent ? "concurrent" : ""].filter(Boolean).join(", ") },
      { k: "delay_days", label: "Delay d", fmt: "qty" }, { k: "eot_claimed", label: "EOT claimed", fmt: "qty" }, { k: "eot_granted", label: "EOT granted", fmt: "qty" }, { k: "cost_impact", label: "Cost impact", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
    rowClass: (r) => r.notice_deadline && r.notice_deadline <= today() && r.status === "open" && !r.notice_sent ? "bad" : "",
    defaults: () => ({ date: today(), type: "delay", status: "open" }),
    fields: () => [{ k: "date", label: "Date", type: "date" }, { k: "type", label: "Type", type: "select", noBlank: true, options: EVENT_TYPES2 }, { k: "status", label: "Status", type: "select", noBlank: true, options: EVENT_STATUS2 }, { k: "title", label: "Title", req: true, wide: true }, { k: "description", label: "What happened", type: "textarea", wide: true },
      { k: "wbs_id", label: "WBS", type: "select", options: wbsOpts }, { k: "activity_id", label: "Main activity affected", type: "select", options: () => actOpts() },
      { k: "activity_ids", label: "Other activities affected (ids, filled from the list below)", hint: "Codes: pick in the schedule; ids separated by commas" },
      { k: "responsible_party", label: "Responsible party" }, { k: "clause", label: "Contract clause" },
      { k: "notice_days", label: "Notice period (days)", type: "number" }, { k: "notice_deadline", label: "Notice deadline (blank = date + period)", type: "date" }, { k: "notice_sent", label: "Notice sent on", type: "date" },
      { k: "excusable", label: "Excusable?", type: "select", options: [["1", "Excusable (not the contractor's risk)"], ["0", "Non-excusable (contractor's risk)"]] },
      { k: "compensable", label: "Compensable (time and money)", type: "check" }, { k: "concurrent", label: "Concurrent with a contractor delay", type: "check" },
      { k: "delay_days", label: "Delay days", type: "number" }, { k: "eot_claimed", label: "EOT claimed (days)", type: "number" }, { k: "eot_granted", label: "EOT granted (days)", type: "number" },
      { k: "cost_impact", label: "Cost impact", type: "number" }, { k: "prolongation_cost", label: "Prolongation cost (days × site overhead)", type: "number" },
      { k: "claim_value", label: "Claim value (money claimed)", type: "number" }, { k: "highly_probable", label: "Highly probable to be agreed (counts in NFRS 15 revenue)", type: "check" },
      { k: "mitigation", label: "Mitigation", type: "textarea", wide: true }],
    actions: (r, load) => r && r.status === "open" && !r.notice_sent && can("project", "edit") ? [{ label: "Notice sent today", act: async () => { await run("ctime.notice_sent", { id: r.id }, "Notice recorded"); await load(); } }] : [] });

  /* ── DPR: weather and lost time, chainage, foreman delay survey (Hinze ch. 11) ── */
  const SURVEY = [["materials", "Waiting for materials"], ["tools", "Waiting for tools"], ["design_rework", "Rework from design errors"], ["field_rework", "Rework from field errors"],
    ["instructions", "Waiting for instructions"], ["inspection", "Waiting for inspection"], ["area_not_ready", "Work area not ready"], ["overcrowded", "Work area overcrowded"],
    ["equipment_wait", "Waiting for equipment"], ["breakdown", "Equipment breakdown"], ["owner_change", "Owner change"], ["interference", "Interference from another crew"]];
  window.SURVEY_CAUSES = SURVEY;
  /* put an existing page into the first tab and add more tabs beside it (used by the later phases) */
  window.BCO_TABS = window.BCO_TABS || {};
  window.bcoTabbed = function (route, title, sub, extra) {
    const orig = PAGES[route];
    if (!orig) return;
    if (orig.__bco) { orig.__bco.tabs.push(...extra.tabs); return; }  /* already tabbed: a later phase adds its tabs */
    PAGES[route] = async (root, params) => {
      const first = async () => {
        const box = h("div");
        await orig(box, params || {});
        const h1 = box.querySelector("h1");
        if (h1) { const bar = h1.closest(".bar"); const sb = bar && bar.querySelector(".sub"); h1.remove(); if (sb) sb.remove(); }
        return box;
      };
      root.append(pageHead(title, sub));
      const defs = [[extra.firstLabel || title, first]].concat(extra.tabs.concat(window.BCO_TABS[route] || []).map(([l, fn]) => [l, () => fn(params || {})]));
      const start = params && params.tab ? Number(params.tab) : 0;
      root.append(tabs(defs, start));
    };
    PAGES[route].__bco = { tabs: extra.tabs };
  };
  window.dprWizard = async function dprWizard2(dpr, ctx) {
    await loadProjectLists();
    ctx = ctx || {};
    const isNew = !dpr;
    let pre = null;
    if (isNew) {
      pre = await api("dpr.prefill", { project_id: S.project, date: today() });
      dpr = { status: "draft", date: today(), shift: "day", project_id: S.project, work: pre.work, labour: pre.labour, equipment: pre.equipment, delays: [], survey: [], materials: pre.materials, photos: [], receipts: [], tests: [], vouchers: [] };
      if (ctx.activity) {
        const a = byId(S.P.activities, ctx.activity);
        if (a) dpr.work = [{ activity_id: a.id, boq_item_id: a.boq_item_id, location: a.location, planned_qty: "", actual_qty: "", chainage_from: a.chainage_from ?? "", chainage_to: "" }];
      }
    }
    dpr.survey = dpr.survey || [];
    const editable = dpr.status === "draft" && can("project", "edit");
    const hf = form([{ k: "date", label: "Date", type: "date", req: true }, { k: "shift", label: "Shift", type: "select", noBlank: true, options: [["day", "Day"], ["night", "Night"]] },
      { k: "weather", label: "Weather", type: "select", options: [["Clear", "Clear"], ["Cloudy", "Cloudy"], ["Rain", "Rain"], ["Heavy rain", "Heavy rain"], ["Snow", "Snow"]] },
      { k: "rain_mm", label: "Rainfall (mm, if measured)", type: "number" }, { k: "weather_lost_hours", label: "Hours lost to weather", type: "number" },
      { k: "lost_day", label: "Whole day lost (weather / bandh / flood)", type: "check" },
      { k: "site_condition", label: "Site condition" }, { k: "remarks", label: "General remarks", wide: true }].map((x) => Object.assign(x, { readonly: !editable })), dpr);
    let TOOLS = [];
    try { TOOLS = (await api("tool.list", {})).rows; } catch (e) { TOOLS = []; }
    const toolsOf = (eid) => TOOLS.filter((t) => String(t.equipment_id) === String(eid));
    const toolOf = (id) => TOOLS.find((t) => String(t.id) === String(id));
    const eqOpts = () => S.L.equipment.filter((e) => e.active && String(e.project_id) === String(S.project)).map((e) => [e.id, e.code + " " + e.name]);
    const allEq = () => S.L.equipment.filter((e) => e.active).map((e) => [e.id, e.code + " " + e.name]);
    const work = lineEditor([
      { k: "activity_id", label: "Activity (WBS)", type: "select", options: () => actOpts(), w: 230, key: "activity", onChange: (r) => { const a = byId(S.P.activities, r.activity_id); if (a) { r.boq_item_id = a.boq_item_id; r.location = r.location || a.location; } }, rerender: true },
      { label: "WBS", show: (r) => { const a = byId(S.P.activities, r.activity_id); return a ? nmWbs(a.wbs_id) : ""; } },
      { k: "boq_item_id", label: "BOQ item", type: "select", options: () => opt.boq(S.project), w: 190, key: "boq" },
      { k: "location", label: "Location", w: 100 }, { k: "chainage_from", label: "Ch. from (m)", type: "number", w: 70 }, { k: "chainage_to", label: "Ch. to (m)", type: "number", w: 70 },
      { k: "planned_qty", label: "Planned", type: "number", w: 70 }, { k: "actual_qty", label: "Actual", type: "number", w: 70 },
      { label: "Unit", show: (r) => { const a = byId(S.P.activities, r.activity_id); return (a && a.unit) || (byId(S.L.boq, r.boq_item_id) || {}).unit || ""; } },
      { label: "Var.", num: true, show: (r) => r.planned_qty && r.actual_qty !== "" && r.actual_qty != null ? fmtN(r.actual_qty - r.planned_qty) + " (" + Math.round(100 * r.actual_qty / r.planned_qty) + "%)" : "" },
      { k: "remarks", label: "Remarks", w: 120 }], dpr.work, { readonly: !editable });
    const labour = lineEditor([
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 200, key: "activity" },
      { k: "trade_id", label: "Trade", type: "select", options: tradeOpts, w: 160, key: "trade" },
      { k: "party_id", label: "Subcontractor (if any)", type: "select", options: () => opt.parties(["subcontractor"]), w: 150 },
      { k: "count", label: "No.", type: "number", w: 60 }, { k: "hours", label: "Hours", type: "number", w: 60 }, { k: "ot_hours", label: "OT h", type: "number", w: 60 },
      { label: "Man-hours", num: true, show: (r) => fmtN((Number(r.count) || 0) * ((Number(r.hours) || 0) + (Number(r.ot_hours) || 0))) },
      { k: "amount", label: "Cost", readonly: true, type: "number" }], dpr.labour, { readonly: !editable, blank: { hours: 8 } });
    /* 2.35: opening = last closing, operator from the equipment list, hours = closing − opening, idle / breakdown asked */
    const mt = window.bcoDprMeter ? window.bcoDprMeter.create({ dprId: () => dpr.id }) : null;
    const eqCols = [
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 190, key: "activity" },
      { k: "equipment_id", label: "Equipment", type: "select", options: () => (eqOpts().length ? eqOpts() : allEq()), w: 170, key: "equipment", onChange: (r) => { const e = byId(S.L.equipment, r.equipment_id); if (mt) mt.pick(r); else if (e && (r.meter_start === undefined || r.meter_start === "")) r.meter_start = e.meter; const ts = toolsOf(r.equipment_id); if (!ts.some((t) => String(t.id) === String(r.tool_id))) r.tool_id = (ts.find((t) => t.is_default) || ts[0] || {}).id || ""; }, rerender: true },
      { k: "tool_id", label: "Output / attachment", type: "select", options: (r) => toolsOf(r.equipment_id).map((t) => [t.id, t.name]), w: 130, rerender: true },
      { label: "Type / meter now", show: (r) => { const e = byId(S.L.equipment, r.equipment_id); return e ? (e.category || "") + " · " + fmtN(e.meter) + " " + e.meter_type : ""; } },
      { k: "operator", label: "Operator", w: 100 }, { k: "meter_start", label: "Open meter", type: "number", w: 80, onChange: (r, tr) => { if (mt) mt.meters(r, tr, "meter_start"); } }, { k: "meter_end", label: "Close meter", type: "number", w: 80, onChange: (r, tr) => { if (mt) mt.meters(r, tr, "meter_end"); } },
      { k: "hours", label: "Work h", type: "number", w: 60 }, { k: "output_qty", label: "Qty done", type: "number", w: 70 }, { label: "Unit", show: (r) => (toolOf(r.tool_id) || {}).output_unit || "" },
      { k: "idle_hours", label: "Idle h", type: "number", w: 60 }, { k: "breakdown_hours", label: "Down h", type: "number", w: 60 },
      { label: "From store today", show: (r) => { if (!r.equipment_id) return ""; const agg = {}; (dpr.materials || []).filter((x) => String(x.equipment_id) === String(r.equipment_id)).forEach((x) => { agg[x.material_id] = (agg[x.material_id] || 0) + (Number(x.qty) || 0) - (Number(x.returned_qty) || 0); }); return Object.entries(agg).map(([mid, qq]) => fmtN(qq) + " " + (nm.unit(mid) || "") + " " + (nm.mat(mid) || "")).join(" · "); } },
      { k: "amount", label: "Cost", readonly: true, type: "number" }];
    const equipment = lineEditor(eqCols, dpr.equipment, { readonly: !editable });
    if (mt) mt.attach(equipment, eqCols, hf, { editable, isNew, date: dpr.date, shift: dpr.shift });
    const eqBox = h("div", {}, h("p", { class: "hint" }, "This is where machine logsheets are made: on approval each machine gets its logsheet day from these lines (hours, meters, idle and breakdown time, operator, output). Fuel and oil are issued from the store to the machine (Inventory › Issues) and show in “From store today”. One machine, several jobs: an excavator that dug with the bucket and broke rock with the breaker gets one line for each output (and activity)." + (mt ? " " + window.bcoDprMeter.HINT : "")), equipment);
    const delays = lineEditor([
      { k: "category", label: "Reason", type: "select", options: DELAY_CATS, w: 170 }, { k: "activity_id", label: "Affected activity", type: "select", options: () => actOpts(), w: 190, key: "activity" },
      { k: "hours", label: "Hours lost", type: "number", w: 70 }, { k: "description", label: "What happened", w: 260 },
      { k: "create_event", label: "Create event?", type: "select", noBlank: true, options: [["0", "No"], ["1", "Yes, record as contract event"]] },
      { label: "Event", show: (r) => r.event_id ? "#" + r.event_id : "" }], (dpr.delays || []).map((x) => Object.assign({}, x, { create_event: String(x.create_event || 0) })), { readonly: !editable, blank: { create_event: "1" } });
    const survey = lineEditor([
      { k: "cause", label: "Cause (foreman survey)", type: "select", options: SURVEY, w: 220 },
      { k: "trade_id", label: "Crew / trade", type: "select", options: tradeOpts, w: 150, key: "trade" },
      { k: "activity_id", label: "Activity", type: "select", options: () => actOpts(), w: 170, key: "activity" },
      { k: "area", label: "Area / location", w: 100 }, { k: "workers", label: "Workers", type: "number", w: 60 }, { k: "hours", label: "Hours lost each", type: "number", w: 70 },
      { label: "Worker-hours", num: true, show: (r) => fmtN((Number(r.workers) || 0) * (Number(r.hours) || 0)) },
      { k: "remarks", label: "Note", w: 140 }], dpr.survey, { readonly: !editable, blank: { workers: 1 } });
    const surveyBox = h("div", {}, h("p", { class: "hint" }, "Each foreman records worker-hours lost against the twelve standard causes. Run it for one to three weeks, act on the Pareto (Cost & earned value → Delay survey), and repeat after about six months. The same record is evidence for claims."), survey);
    const matBox = h("div", {}, h("p", { class: "hint" }, "Taken automatically from store issues and receipts dated this day, so nothing is typed twice. Issue material from the store with the activity or BOQ item to charge it."),
      h("h4", {}, "Issued today"), table([{ k: "no", label: "Issue" }, { label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { label: "Unit", v: (r) => nm.unit(r.material_id) }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Cost", fmt: "money" }, { label: "For", v: (r) => r.boq_item_id ? nm.boq(r.boq_item_id) : r.equipment_id ? nm.eq(r.equipment_id) : r.target }], dpr.materials || [], { search: false, export: false, empty: "No material issued on this date." }),
      h("h4", {}, "Received today"), table([{ k: "no", label: "GRN" }, { label: "Material", v: (r) => nm.mat(r.material_id) }, { k: "accepted_qty", label: "Qty", fmt: "qty" }], dpr.receipts || [], { search: false, export: false, empty: "No receipts on this date." }),
      can("inventory", "edit") ? h("button", { class: "btn small", onclick: () => { location.hash = "#/inv/issue?new=1"; } }, "Issue material now") : null);
    const photoBox = h("div");
    const loadPhotos = async () => {
      photoBox.innerHTML = "";
      if (!dpr.id) return photoBox.append(h("p", { class: "hint" }, "Save the draft first, then add photos."));
      const rows = await api("files.list", { dpr_id: dpr.id });
      photoBox.append(uploadButton({ entity: "dpr", entity_id: dpr.id, dpr_id: dpr.id, project_id: S.project, date: dpr.date, kind: "photo" }, loadPhotos, "Add photos", "image/*"), fileList(rows, loadPhotos));
    };
    loadPhotos();
    const qaBox = h("div", {}, table([{ k: "no", label: "Test" }, { k: "test_type", label: "Type" }, { label: "Activity", v: (r) => nmAct(r.activity_id) }, { k: "status", label: "Status", fmt: "status" }], dpr.tests || [], { search: false, export: false, empty: "Tests required by activities are created automatically when the DPR is approved." }),
      can("quality", "edit") ? h("button", { class: "btn small", onclick: () => { location.hash = "#/p/quality?new=1"; } }, "Request a test") : null);
    const review = h("div");
    const renderReview = () => {
      const w = work.lines(), l = labour.lines(), e = equipment.lines(), sv = survey.lines();
      review.innerHTML = "";
      review.append(kv([["Work lines", w.filter((x) => x.activity_id || x.boq_item_id).length], ["Man-hours", fmtN(l.reduce((a, x) => a + (Number(x.count) || 0) * ((Number(x.hours) || 0) + (Number(x.ot_hours) || 0)), 0))], ["Machine hours", fmtN(e.reduce((a, x) => a + (Number(x.meter_end) && Number(x.meter_start) ? x.meter_end - x.meter_start : Number(x.hours) || 0), 0))], ["Issues / delays", delays.lines().filter((x) => x.category).length],
        ["Worker-hours lost (survey)", fmtN(sv.reduce((a, x) => a + (Number(x.workers) || 0) * (Number(x.hours) || 0), 0))], ["Material cost today", fmtMoney((dpr.materials || []).reduce((a, x) => a + x.amount, 0))]]),
      h("p", { class: "hint" }, "On approval BuildCore updates BOQ executed quantity, activity progress, labour and equipment cost (voucher), equipment logsheets (without duplicates), events for delays, and QA test requests. Press Calculate schedule afterwards to move the forecast."),
      dpr.vouchers && dpr.vouchers.length ? h("p", {}, "Posted vouchers: ", dpr.vouchers.map((v) => v.no + " (" + v.status + ")").join(", ")) : null,
      recordPanel("dpr", dpr.id, { project_id: S.project, dpr_id: dpr.id }));
    };
    const steps = tabs([["1 Basic & weather", () => hf], ["2 Work", () => work], ["3 Labour", () => labour], ["4 Equipment", () => eqBox], ["5 Materials", () => matBox], ["6 QA", () => qaBox], ["7 Issues & delays", () => delays], ["8 Delay survey", () => surveyBox], ["9 Photos", () => photoBox], ["10 Review", () => { renderReview(); return review; }]]);
    const draftKey = () => "bco_dpr_draft_" + S.project + "_" + (dpr.id || "new");
    const payload = () => ({ header: Object.assign(hf.values(), { id: dpr.id, project_id: S.project }),
      work: work.lines(), labour: labour.lines(), equipment: equipment.lines(), delays: delays.lines(), survey: survey.lines() });
    const keepLocal = () => { try { localStorage.setItem(draftKey(), JSON.stringify({ saved: new Date().toISOString(), data: payload() })); } catch (e) { /* full disk */ } };
    const dropLocal = () => { try { localStorage.removeItem(draftKey()); } catch (e) { /* ignore */ } };
    const save = async (quiet) => {
      if (mt && editable && !(await mt.resolve())) throw new Error("machine lines not answered");
      keepLocal();
      let r;
      try {
        r = await run("dpr.save", payload(), quiet ? null : "Draft saved");
      } catch (e) {
        toast("Not saved to the server — your typing is kept on this computer and this window stays open. Press Save draft again when the connection is back.", "err");
        throw e;
      }
      dropLocal(); dpr.id = r.id; dropLocal();
      return r;
    };
    const autoKeep = setInterval(keepLocal, 20000);
    let m;
    const reopenDpr = async () => { m.close(); if (PAGES._dprReload) PAGES._dprReload(); window.dprWizard(await api("dpr.get", { id: dpr.id })); };
    const step = (label, fn, o) => ({ label, cls: (o || {}).cls, act: async () => {
      if (o && o.ask) { const r = await ask(label, o.ask, { input: o.reason, required: !!o.reason }); if (r === null) return false; o.value = r; }
      if (editable) await save(true);
      await fn(o && o.value);
      await reopenDpr();
    } });
    const b = [];
    if (editable) {
      b.push({ label: "Save draft", act: async () => { await save(); await reopenDpr(); } });
      b.push(step("Submit", () => run("dpr.submit", { id: dpr.id }, "Submitted"), { cls: "primary" }));
    }
    if (dpr.status === "submitted" && can("project", "edit")) b.push(step("Mark checked", () => run("dpr.check", { id: dpr.id }, "Checked")));
    if (["submitted", "checked"].includes(dpr.status) && can("project", "approve")) b.push(step("Approve & post", () => run("dpr.approve", { id: dpr.id }, "Approved — progress and costs updated"), { cls: "primary" }));
    if (["submitted", "checked"].includes(dpr.status) && can("project", "edit")) b.push(step("Return for correction", (r) => run("dpr.return", { id: dpr.id, reason: r }, "Returned"), { ask: "Send back to the engineer?", reason: "What to correct" }));
    if (dpr.status === "approved" && can("admin", "edit")) b.push(step("Reopen (admin)", (r) => run("dpr.reopen", { id: dpr.id, reason: r }, "Reopened; postings reversed"), { ask: "Reopen this approved DPR? Its cost postings are reversed and re-posted on the next approval.", reason: "Reason" }));
    if (dpr.id) b.push({ label: "Print", act: () => { printDoc("Daily Progress Report " + (dpr.no || ""), [["Project", nm.project(S.project)], ["Date", dpr.date], ["Shift", dpr.shift], ["Weather", (dpr.weather || "") + (dpr.weather_lost_hours ? " (" + dpr.weather_lost_hours + " h lost)" : "")], ["Status", dpr.status]], [{ label: "Activity", v: (r) => nmAct(r.activity_id) }, { label: "BOQ", v: (r) => nm.boq(r.boq_item_id) }, { k: "location", label: "Location" }, { label: "Chainage", v: (r) => r.chainage_from != null ? r.chainage_from + "–" + (r.chainage_to ?? "") : "" }, { k: "planned_qty", label: "Planned", fmt: "qty" }, { k: "actual_qty", label: "Actual", fmt: "qty" }, { k: "remarks", label: "Remarks" }], dpr.work, [["Man-hours", fmtN(dpr.labour.reduce((a, x) => a + x.count * (x.hours + (x.ot_hours || 0)), 0))], ["Machine hours", fmtN(dpr.equipment.reduce((a, x) => a + (x.hours || 0), 0))]], [dpr.remarks, ...(dpr.delays || []).map((x) => "Delay: " + x.category + " — " + (x.description || "")), ...(dpr.survey || []).map((x) => "Lost: " + ((SURVEY.find((s) => s[0] === x.cause) || [0, x.cause])[1]) + " — " + x.workers + " × " + x.hours + " h")].filter(Boolean).join("\n")); return false; } });
    m = modal("DPR " + (dpr.no || "(new)") + " · " + nm.pcode(S.project), h("div", {}, isNew && pre && pre.previous_dpr ? h("p", { class: "hint" }, "Planned work is taken from today's schedule (working days only); labour and equipment are copied from the previous DPR. Change what differs.") : null, steps), b,
      { head: stamp(dpr.status), onClose: () => clearInterval(autoKeep) });
    try {
      const held = JSON.parse(localStorage.getItem(draftKey()) || "null");
      if (held && editable) {
        toast("Unsent work from " + held.saved.slice(0, 16).replace("T", " ") + " was found on this computer.", "err");
        hf.set("date", held.data.header.date); hf.set("shift", held.data.header.shift);
        hf.set("weather", held.data.header.weather); hf.set("remarks", held.data.header.remarks);
        work.setLines(held.data.work || []); labour.setLines(held.data.labour || []);
        equipment.setLines(held.data.equipment || []); delays.setLines(held.data.delays || []); survey.setLines(held.data.survey || []);
      }
    } catch (e) { /* nothing held */ }
  };
  /* the DPR list page calls dprWizard by its global name; route those calls to the new wizard */
  try { dprWizard = window.dprWizard; } catch (e) { /* declared as a function: window property already replaced */ }
})();
