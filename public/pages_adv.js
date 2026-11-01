/* BuildCore 2.3 — advanced analysis and the remaining NFRS items, inside existing screens:
   Schedule & WBS (linear schedule, delay analysis & EOT, crashing & acceleration, schedule risk, learning curve),
   Cost & earned value (delay survey, profit centres, close-out audit), Inventory (classification, slow-moving stock,
   EOQ sensitivity, item/bin QR labels, cycle counting, joint replenishment, material cost curve) and Accounts
   (NFRS compliance, expected credit loss, provisions, deferred tax, NFRS 18 view, TDS by year, JV shares, CBMS). */
(function () {
  "use strict";
  const bars = (...a) => window.bcoBars(...a);
  const need = () => S.project ? null : projectNotice();
  const addTabs = (route, title, sub, first, list) => {
    if (PAGES[route] && PAGES[route].__bco) { window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list }); return; }
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route]) window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const panel = (...k) => h("div", { class: "panel" }, ...k);
  const hint = (t) => h("p", { class: "hint" }, t);
  const numIn = (v, w) => h("input", { type: "number", value: v ?? "", style: "max-width:" + (w || 110) + "px" });
  const lab = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
  const dayDiff = (a, b) => Math.round((new Date(b) - new Date(a)) / 864e5);
  const svgEl = (w, hh, inner) => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", `0 0 ${w} ${hh}`); s.setAttribute("class", "chart"); s.innerHTML = inner; return s; };

  /* ══════════ SCHEDULE ══════════ */
  /* linear (time-chainage) schedule */
  async function linearTab() {
    if (need()) return need();
    const box = h("div");
    const tb = numIn(5, 80), db = numIn(50, 80);
    const out = h("div");
    const load = async () => {
      const d = await api("adv.linear", { project_id: S.project, time_buffer: tb.value, distance_buffer: db.value });
      out.innerHTML = "";
      if (!d.lines.length) { out.append(panel(h("b", {}, "No linear activities yet"), hint("Give road, canal, pipeline or tunnel activities a chainage from / to and a crew order (Activity › Cost, risk & linear). DPR work lines with chainage draw the actual progress."))); return; }
      const all = d.lines.flatMap((l) => [l.start, l.finish, l.bl_start, l.bl_finish].concat(l.actual.map((p) => p.date))).filter(Boolean).sort();
      const t0 = all[0], t1 = all[all.length - 1], span = Math.max(1, dayDiff(t0, t1) + 1);
      const chs = d.lines.flatMap((l) => [l.ch_from, l.ch_to]);
      const c0 = Math.min(...chs), c1 = Math.max(...chs), cs = Math.max(1, c1 - c0);
      const W = 760, H = 380, P = 50;
      const X = (ch) => P + (W - 2 * P) * (ch - c0) / cs, Y = (dt) => P + (H - 2 * P) * dayDiff(t0, dt) / span;
      const COL = ["#1f6fb2", "#c77d12", "#2d8a4e", "#8e44ad", "#b3392c", "#16a085", "#7f8c8d"];
      let inner = "";
      for (let g = 0; g <= 5; g++) { const ch = c0 + cs * g / 5; inner += `<line x1="${X(ch)}" x2="${X(ch)}" y1="${P}" y2="${H - P}" class="grid"/><text x="${X(ch)}" y="${H - P + 16}" class="ax" text-anchor="middle">${Math.round(ch)}</text>`; }
      for (let g = 0; g <= 6; g++) { const dt = new Date(new Date(t0).getTime() + span * g / 6 * 864e5).toISOString().slice(0, 10); inner += `<line x1="${P}" x2="${W - P}" y1="${Y(dt)}" y2="${Y(dt)}" class="grid"/><text x="2" y="${Y(dt) + 4}" class="ax">${dt.slice(2)}</text>`; }
      const td = today();
      if (td >= t0 && td <= t1) inner += `<line x1="${P}" x2="${W - P}" y1="${Y(td)}" y2="${Y(td)}" stroke="#b3392c" stroke-dasharray="4 3"/>`;
      d.lines.forEach((l, i) => {
        const col = COL[i % COL.length];
        if (l.bl_start && l.bl_finish) inner += `<line x1="${X(l.ch_from)}" y1="${Y(l.bl_start)}" x2="${X(l.ch_to)}" y2="${Y(l.bl_finish)}" stroke="${col}" stroke-width="1.5" stroke-dasharray="5 4" opacity=".6"/>`;
        inner += `<line x1="${X(l.ch_from)}" y1="${Y(l.start)}" x2="${X(l.ch_to)}" y2="${Y(l.finish)}" stroke="${col}" stroke-width="${l.critical ? 4 : 2.5}"><title>${escHtml(l.code + " " + l.name)} — ${l.rate_per_day} m/day</title></line>`;
        l.actual.forEach((p) => { if (p.ct != null) inner += `<circle cx="${X(p.ct)}" cy="${Y(p.date)}" r="3" fill="${col}"><title>${p.date}: ch ${p.cf}–${p.ct}</title></circle>`; });
      });
      out.append(panel(svgEl(W, H, inner), h("div", { class: "legend" }, d.lines.map((l, i) => h("span", {}, h("i", { style: "background:" + COL[i % COL.length] }), l.code + " " + l.name))),
        hint("Chainage across, time down. Solid = current plan (thick = critical), dashed = baseline, dots = DPR progress. Red line = today.")),
      h("h2", { class: "sec" }, "Following crews (" + d.conflicts.filter((x) => x.clash).length + " too close)"),
      table([{ k: "leader", label: "Leading crew" }, { k: "follower", label: "Following crew" }, { k: "at_chainage", label: "Closest at chainage", fmt: "num" }, { k: "min_time_gap", label: "Time gap (days)", fmt: "num" }, { k: "distance_gap", label: "Distance gap (m)", fmt: "num" },
        { label: "Check", v: (x) => x.crosses ? h("b", { class: "red" }, "lines cross — follower overtakes") : x.clash ? h("b", { class: "red" }, "inside the buffer") : "ok" }],
        d.conflicts, { search: false, name: "linear_conflicts", rowClass: (x) => x.clash ? "flag" : "", empty: "Give the crews an order on the line to check them." }),
      h("h2", { class: "sec" }, "Production"),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Activity" }, { label: "Chainage", v: (l) => l.ch_from + " – " + l.ch_to }, { k: "start", label: "Start" }, { k: "finish", label: "Finish" }, { k: "rate_per_day", label: "Planned m/day", fmt: "num" },
        { k: "planned_front", label: "Should be at (today)", fmt: "num" }, { label: "Actually at", v: (l) => l.actual_front == null ? "—" : h("b", { class: l.actual_front < l.planned_front ? "red" : "green" }, fmtN(l.actual_front)) }], d.lines, { search: false, name: "linear_production" }));
    };
    box.append(hint("Line-of-balance view for roads, canals, pipelines and tunnels: each crew is a production line; lines that converge mean the following crew will catch up."),
      h("div", { class: "bar" }, lab("Time buffer (days)", tb), lab("Distance buffer (m)", db), h("button", { class: "btn", onclick: load }, "Check")), out);
    await load();
    return box;
  }

  /* delay analysis and EOT */
  async function delayTab() {
    if (need()) return need();
    const box = h("div");
    const load = async () => {
      const d = await api("adv.delay", { project_id: S.project });
      box.innerHTML = "";
      const c = d.claim;
      box.append(h("div", { class: "tiles" }, tile("Excusable delay (impacted)", c.eot_days + " days", { sub: "time extension to claim" }), tile("Compensable", c.compensable_days + " days", { sub: "time and money" }),
        tile("Prolongation cost", fmtMoney(c.prolongation_cost), { sub: fmtMoney(c.indirect_per_day) + " per day site overhead" }), tile("Forecast late", c.forecast_late_days == null ? "—" : c.forecast_late_days + " days", { cls: c.forecast_late_days > 0 ? "bad" : "" }),
        tile("LD avoided by the claim", fmtMoney(c.ld_saved)), tile("EOT already granted", c.already_granted || 0)),
      hint(d.note),
      h("h2", { class: "sec" }, "Events — impacted as-planned"),
      table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "title", label: "Event" }, { label: "Fragnet", v: (e) => e.fragnet ? e.fragnet + " activities" : h("span", { class: "muted" }, "none") },
        { k: "impact_days", label: "Impact (days)", fmt: "num" }, { label: "Excusable", v: (e) => e.excusable ? "Yes" : "" }, { label: "Compensable", v: (e) => e.compensable ? "Yes" : "" }, { label: "Concurrent", v: (e) => e.concurrent ? "Yes" : "" },
        { k: "claimed", label: "EOT claimed", fmt: "num" }, { k: "granted", label: "EOT granted", fmt: "num" }], d.events,
      { name: "delay_events", onRow: can("commercial", "edit") ? (e) => fragnetEdit(e, load) : "", empty: "Log delay events in Events & claims." }),
      h("h2", { class: "sec" }, "Windows between schedule updates"),
      table([{ k: "from", label: "From" }, { k: "to", label: "To" }, { k: "finish_before", label: "Finish before" }, { k: "finish_after", label: "Finish after" }, { k: "slip_days", label: "Slip (days)", fmt: "num" }, { k: "events", label: "Events in the window" }, { k: "attributed_to", label: "Attributed to" }],
        d.windows, { search: false, name: "delay_windows", empty: "Calculate the schedule after each update to build windows." }),
      h("h2", { class: "sec" }, "As-planned vs as-built — baseline critical path"),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Activity" }, { k: "planned_start", label: "Planned start" }, { k: "planned_finish", label: "Planned finish" }, { k: "actual_start", label: "Actual / forecast start" }, { k: "finish", label: "Actual / forecast finish" },
        { label: "Delay (days)", v: (r) => r.delay == null ? "" : h("b", { class: r.delay > 0 ? "red" : "green" }, r.delay) }], d.as_planned_as_built, { search: false, name: "as_planned_as_built", empty: "Save baseline 0 first (Baselines & updates)." }),
      h("div", { class: "bar" }, h("button", { class: "btn", onclick: () => printDoc("Extension of time claim", [["Project", nm.project(S.project)], ["Excusable delay", c.eot_days + " days"], ["Compensable", c.compensable_days + " days"], ["Prolongation cost", fmtMoney(c.prolongation_cost)]],
        [{ k: "no", label: "Event" }, { k: "date", label: "Date" }, { k: "title", label: "Description" }, { k: "impact_days", label: "Impact (days)" }], d.events.filter((e) => e.excusable), null, d.note) }, "Print EOT claim summary")));
    };
    await load();
    return box;
  }
  function fragnetEdit(e, done) {
    let items = [];
    try { items = JSON.parse(e.fragnet_json || "[]"); } catch (x) { items = []; }
    const ed = lineEditor([{ k: "code", label: "Code", w: 70 }, { k: "name", label: "Fragnet activity", w: 220 }, { k: "dur", label: "Working days", type: "number", w: 70 }, { k: "start", label: "Not before", type: "date", w: 120 },
      { k: "preds", label: "Tied after (activity codes)", w: 150 }, { k: "succs", label: "Holds up (activity codes)", w: 150 }], items.length ? items : [{ name: "", dur: 1 }]);
    modal("Fragnet — " + e.no + " " + e.title, h("div", {}, hint("Model the delay as a few activities (e.g. wait for instruction → redesign → re-mobilise), with the schedule activities they follow and hold up. Mark the event excusable / compensable in Events & claims."), ed),
      [{ label: "Save fragnet", cls: "primary", act: async () => { await run("adv.fragnet_save", { id: e.id, items: ed.lines() }, "Saved"); done(); } }]);
  }

  /* crashing and acceleration */
  async function crashTab() {
    if (need()) return need();
    const box = h("div");
    const ind = numIn("", 140), ld = numIn("", 140);
    const out = h("div"), acc = h("div");
    const act = h("select", {}, h("option", { value: "" }, "— choose an activity —"), (S.P.activities || []).filter((a) => !a.actual_finish).map((a) => h("option", { value: a.id }, (a.code || "") + " " + a.name)));
    const crew = numIn("", 80), dur = numIn("", 80), wage = numIn("", 80);
    const load = async () => {
      const d = await api("adv.crash", { project_id: S.project, indirect_per_day: ind.value || undefined, ld_per_day: ld.value || undefined });
      out.innerHTML = "";
      if (d.empty) { out.append(panel(d.note)); return; }
      out.append(h("div", { class: "tiles" }, tile("Normal finish", d.steps[0] ? d.steps[0].finish : "—"), tile("Least-cost finish", d.best.finish, { sub: fmtMoney(d.best.total) + " total" }), tile("Contract completion", d.contract_finish || "—"), tile("Activities that can be crashed", d.crashable)),
        d.note ? hint(d.note) : "",
        d.steps.length > 1 ? bars(d.steps.map((s) => String(s.duration)), [{ name: "Direct", values: d.steps.map((s) => s.direct) }, { name: "Site overhead", values: d.steps.map((s) => s.indirect) }, { name: "LD", values: d.steps.map((s) => s.ld) }]) : "",
        table([{ k: "duration", label: "Duration (working days)", fmt: "num" }, { k: "finish", label: "Finish" }, { k: "crashed", label: "Shortened" }, { k: "direct", label: "Direct cost", fmt: "money" }, { k: "indirect", label: "Site overhead", fmt: "money" }, { k: "ld", label: "LD", fmt: "money" }, { k: "total", label: "Total", fmt: "money" }],
          d.steps, { search: false, name: "crash_steps", rowClass: (s) => s.duration === d.best.duration ? "flag" : "" }));
    };
    const accel = async () => {
      if (!act.value) { acc.innerHTML = ""; acc.append(hint("Choose an activity to compare overtime, a bigger crew, more work faces or a second shift.")); return; }
      const d = await api("adv.accelerate", { project_id: S.project, activity_id: act.value, crew: crew.value || undefined, dur_days: dur.value || undefined, wage_hour: wage.value || undefined, indirect_per_day: ind.value || undefined, ld_per_day: ld.value || undefined });
      acc.innerHTML = "";
      acc.append(kv([["Remaining work", fmtN(d.base_calendar_days) + " calendar days"], ["Labour cost at normal hours", fmtMoney(d.base_labour_cost)], ["Normal-week efficiency", fmtPct(d.normal_week_efficiency)]]),
        table([{ k: "option", label: "Option" }, { k: "days_gained", label: "Days gained", fmt: "num" }, { k: "extra_cost", label: "Extra cost", fmt: "money" }, { k: "ld_indirect_saved", label: "LD + overhead saved", fmt: "money" }, { k: "net_benefit", label: "Net benefit", fmt: "money" }, { k: "cost_per_day_gained", label: "Cost per day gained", fmt: "money" },
          { label: "Worth it", v: (r) => r.worth_it ? h("b", { class: "green" }, "Yes") : "No" }], d.options, { search: false, name: "acceleration" }),
        hint("Overtime loses productivity (fatigue) and bigger crews lose it to crowding, so the days gained are less than the hours added."));
    };
    act.onchange = accel;
    box.append(h("div", { class: "bar" }, lab("Site overhead per day (blank = project)", ind), lab("LD per day (blank = contract)", ld), h("button", { class: "btn", onclick: () => { load(); accel(); } }, "Recalculate")),
      h("h2", { class: "sec" }, "Least-cost crashing (time-cost trade-off)"), out,
      h("h2", { class: "sec" }, "Acceleration options for one activity"), h("div", { class: "bar" }, lab("Activity", act), lab("Crew (blank = DPR average)", crew), lab("Remaining working days", dur), lab("Wage per hour", wage)), acc);
    await load(); await accel();
    return box;
  }

  /* schedule risk */
  async function riskTab() {
    if (need()) return need();
    const box = h("div");
    const lo = numIn(10, 70), hi = numIn(30, 70), runs = numIn(1000, 90);
    const out = h("div");
    const load = async () => {
      out.innerHTML = ""; out.append(h("p", { class: "muted" }, "Running…"));
      const d = await api("adv.risk", { project_id: S.project, spread_low: lo.value, spread_high: hi.value, runs: runs.value });
      out.innerHTML = "";
      if (d.empty) { out.append(panel(d.note)); return; }
      const m = d.monte_carlo;
      out.append(h("div", { class: "tiles" }, tile("Contract completion", d.contract_finish || "—"), tile("PERT expected finish", d.pert.expected, { sub: "σ " + d.pert.sigma_days + " working days" }), tile("PERT chance on time", fmtPct(d.pert.probability)),
        tile("Monte Carlo P50", m.p50), tile("P80", m.p80, { sub: "P90 " + m.p90 }), tile("Chance on time (simulated)", fmtPct(m.probability), { cls: m.probability != null && m.probability < 50 ? "bad" : "" })),
      bars(m.histogram.map((x) => x.finish.slice(2)), [{ name: "Runs finishing that day", values: m.histogram.map((x) => x.runs) }]),
      hint("PERT uses only the critical path, so it is optimistic when paths merge; the simulation samples every activity (triangular distribution) " + m.runs + " times."),
      h("h2", { class: "sec" }, "Criticality index — how often each activity was critical"),
      table([{ k: "activity", label: "Activity" }, { k: "index", label: "Critical in % of runs", fmt: "num" }], d.criticality, { search: false, name: "criticality" }));
    };
    box.append(hint("Blank three-point durations on an activity (Activity › Cost, risk & linear) use the spread below around the calculated duration."),
      h("div", { class: "bar" }, lab("Optimistic −%", lo), lab("Pessimistic +%", hi), lab("Runs", runs), h("button", { class: "btn primary", onclick: load }, "Run")), out);
    await load();
    return box;
  }

  /* learning curve */
  async function learningTab() {
    if (need()) return need();
    const box = h("div");
    const act = h("select", {}, h("option", { value: "" }, "— choose a repetitive activity —"), (S.P.activities || []).map((a) => h("option", { value: a.id }, (a.code || "") + " " + a.name)));
    const out = h("div");
    const lostU = numIn("", 80);
    const show = async () => {
      out.innerHTML = "";
      if (!act.value) return;
      const d = await api("adv.learning", { activity_id: act.value, units_lost: lostU.value || undefined });
      if (!d.t1) { out.append(hint(d.note)); return; }
      out.append(h("div", { class: "tiles" }, tile("Learning rate", d.learning_rate + "%", { sub: "each doubling takes this share of the time" }), tile("First unit", fmtN(d.t1) + " man-hours"), tile("Next unit", fmtN(d.next_unit_time) + " man-hours"),
        tile("Remaining", fmtN(d.remaining) + " " + (d.activity.unit || ""), { sub: fmtN(d.remaining_hours) + " man-hours forecast" })),
      lineChart(d.points.map((p) => fmtN(p.cum)), [{ name: "Actual man-hours per unit", color: "#1f6fb2", values: d.points.map((p) => p.unit_time) }, { name: "Fitted curve", color: "#c77d12", dash: 1, values: d.fitted.map((p) => p.fit) }]),
      d.lost_learning ? kv([["Learning lost after the stoppage", fmtN(d.lost_learning.extra_hours) + " extra man-hours"], ["Cost of the lost learning", fmtMoney(d.lost_learning.extra_cost)]]) : "",
      table([{ k: "date", label: "Date" }, { k: "units", label: "Units", fmt: "num" }, { k: "cum", label: "Cumulative", fmt: "num" }, { k: "unit_time", label: "Man-hours per unit", fmt: "num" }], d.points, { search: false, name: "learning_points" }));
    };
    act.onchange = show; lostU.onchange = show;
    box.append(hint("For repetitive work (culverts, piers, floors, bays): a straight line on log–log axes gives the learning rate and forecasts the remaining units better than the average."),
      h("div", { class: "bar" }, lab("Activity", act), lab("Units of learning lost to a stoppage (for a claim)", lostU)), out);
    return box;
  }
  window.SCHED_TABS = (window.SCHED_TABS || []).concat([["Linear schedule", linearTab], ["Delay analysis & EOT", delayTab], ["Crashing & acceleration", crashTab], ["Schedule risk", riskTab], ["Learning curve", learningTab]]);

  /* ══════════ COST & EARNED VALUE ══════════ */
  async function surveyTab() {
    if (need()) return need();
    const box = h("div");
    const f = form([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], { from: new Date(Date.now() - 28 * 864e5).toISOString().slice(0, 10), to: today() });
    const out = h("div");
    const load = async () => {
      const d = await api("adv.survey", Object.assign({ project_id: S.project }, f.values()));
      out.innerHTML = "";
      out.append(h("div", { class: "tiles" }, tile("Hours lost", fmtN(d.total_hours)), tile("Share of paid hours", fmtPct(d.lost_pct)), tile("Cost of lost time", fmtMoney(d.total_cost)), tile("Employer-risk hours", fmtN(d.employer_hours), { sub: "support a claim" }), tile("Survey lines", d.records)),
        hint(d.note + " Foremen record it in the DPR (Delay survey section)."),
        d.by_cause.length ? bars(d.by_cause.map((x) => x.key.slice(0, 14)), [{ name: "Hours lost", values: d.by_cause.map((x) => x.hours) }]) : "",
        h("div", { class: "grid2" },
          h("div", {}, h("h3", {}, "By cause (Pareto)"), table([{ k: "key", label: "Cause" }, { k: "hours", label: "Hours", fmt: "num" }, { k: "pct", label: "%", fmt: "num" }, { k: "cum_pct", label: "Cumulative %", fmt: "num" }, { k: "cost", label: "Cost", fmt: "money" }], d.by_cause, { search: false, name: "survey_cause" })),
          h("div", {}, h("h3", {}, "By crew"), table([{ k: "key", label: "Crew / trade" }, { k: "hours", label: "Hours", fmt: "num" }, { k: "pct", label: "%", fmt: "num" }], d.by_crew, { search: false, name: "survey_crew" }),
            h("h3", {}, "By area"), table([{ k: "key", label: "Area" }, { k: "hours", label: "Hours", fmt: "num" }, { k: "pct", label: "%", fmt: "num" }], d.by_area, { search: false, name: "survey_area" }))));
    };
    f.addEventListener("change", load);
    box.append(f, out);
    await load();
    return box;
  }
  async function profitTab() {
    const box = h("div");
    const alloc = h("select", {}, [["revenue", "by revenue"], ["cost", "by direct cost"], ["labour", "by direct labour"], ["time", "by months on site"]].map(([v, l]) => h("option", { value: v }, l)));
    const f = form([{ k: "from", label: "Overhead from", type: "date" }, { k: "to", label: "To", type: "date" }], { from: new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10), to: today() });
    const out = h("div");
    const load = async () => {
      const d = await api("adv.profit", Object.assign({ alloc: alloc.value }, f.values()));
      out.innerHTML = "";
      const g = (rows, name, label) => table([{ k: "key", label }, { k: "projects", label: "Projects", fmt: "num" }, { k: "revenue", label: "Revenue", fmt: "money" }, { k: "gross", label: "Gross", fmt: "money" }, { k: "net", label: "After overhead", fmt: "money" }, { k: "margin_pct", label: "Margin %", fmt: "num" }, { k: "profit_per_mgmt_hour", label: "Profit / mgmt hour", fmt: "money" }].concat(name === "client" ? [{ k: "quadrant", label: "Quadrant" }] : []), rows, { search: false, name: "profit_" + name });
      out.append(kv([["Head-office overhead in the period", fmtMoney(d.overhead)], ["Allocated", "by " + d.alloc]]),
        table([{ k: "code", label: "Project" }, { k: "client", label: "Client" }, { k: "revenue", label: "Revenue", fmt: "money" }, { k: "cost", label: "Cost", fmt: "money" }, { k: "from_markup", label: "From markup", fmt: "money" }, { k: "from_buyout", label: "From buy-out", fmt: "money" },
          { k: "from_labour", label: "From labour", fmt: "money" }, { k: "from_equipment", label: "From equipment", fmt: "money" }, { k: "overhead", label: "Overhead share", fmt: "money" }, { k: "net", label: "Net profit", fmt: "money" }, { k: "margin_pct", label: "Margin %", fmt: "num" }], d.rows, { name: "profit_centres", totals: ["revenue", "cost", "overhead", "net"] }),
        hint("Profit is split into where it came from: the markup in the price, buying materials below the estimate, and labour and equipment beating (or losing to) their budgets. " + d.note),
        h("h3", {}, "By client"), g(d.by_client, "client", "Client"), h("h3", {}, "By project type"), g(d.by_type, "type", "Type"), h("h3", {}, "By project manager"), g(d.by_pm, "pm", "Project manager"));
    };
    alloc.onchange = load; f.addEventListener("change", load);
    box.append(h("div", { class: "bar" }, lab("Allocate overhead", alloc), f), out);
    await load();
    return box;
  }
  async function closeoutTab() {
    if (need()) return need();
    const box = h("div");
    const load = async () => {
      const d = await api("adv.closeout", { project_id: S.project });
      box.innerHTML = "";
      const r = d.review;
      box.append(h("div", { class: "tiles" }, tile("Estimate for the work done", fmtMoney(d.totals.estimate)), tile("Actual cost", fmtMoney(d.totals.actual), { cls: d.totals.actual > d.totals.estimate ? "bad" : "" }), tile("Variance", fmtMoney(d.totals.estimate - d.totals.actual)),
        tile("Review", r ? r.status : "not signed", { sub: r ? r.reviewed_by + " " + r.date : null })), hint(d.note),
      h("h2", { class: "sec" }, "Estimate against actual by cost code"),
      table([{ k: "code", label: "Code" }, { k: "description", label: "Item" }, { k: "estimate", label: "Estimate (done qty)", fmt: "money" }, { k: "actual", label: "Actual", fmt: "money" }, { k: "variance", label: "Variance", fmt: "money" },
        { label: "Over %", v: (x) => x.variance_pct == null ? "" : h("b", { class: x.variance_pct > 10 ? "red" : x.variance_pct < -10 ? "green" : "" }, x.variance_pct) }], d.cost_codes, { name: "closeout_costs", totals: ["estimate", "actual", "variance"] }),
      h("h2", { class: "sec" }, "Productivity against the norm"),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Activity" }, { k: "done", label: "Done", fmt: "num" }, { k: "norm_code", label: "Norm" }, { k: "norm_md_per_unit", label: "Norm man-days / unit", fmt: "num" }, { k: "actual_md_per_unit", label: "Achieved man-days / unit", fmt: "num" }, { k: "factor", label: "Factor", fmt: "num" },
        { label: "", v: (x) => x.factor && x.norm_code && can("masters", "edit") ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); const nc = await ask("Company norm from site records", "Copy norm " + x.norm_code + " and scale its labour by " + x.factor + "? The published norm stays unchanged.", { input: "New norm code", value: "CO-" + x.norm_code }); if (nc === null) return; const r2_ = await run("adv.norm_feedback", { norm_code: x.norm_code, factor: x.factor, new_code: nc || undefined, basis: "project " + nm.project(S.project) }); toast("Norm " + r2_.code + " created", "ok"); } }, "Make company norm") : "" }],
      d.productivity, { name: "closeout_productivity", empty: "Needs DPR labour on activities." }),
      h("div", { class: "bar" }, h("h2", { class: "sec grow" }, "Lessons learned"), can("commercial", "edit") ? h("button", { class: "btn", onclick: () => lesson(null) }, "Add lesson") : ""),
      table([{ k: "category", label: "Area" }, { k: "what", label: "What happened" }, { k: "fix", label: "What to do next time" }, { k: "owner", label: "Owner" }, { k: "cost_code", label: "Cost code" }, { k: "date", label: "Date" }], d.lessons, { search: false, name: "lessons", onRow: can("commercial", "edit") ? lesson : "", empty: "No lessons recorded yet." }),
      can("commercial", "approve") ? h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { const s = await ask("Sign off the close-out review", "Summary of the review", { input: "Summary", value: (r && r.summary) || "" }); if (s === null) return; await run("adv.closeout_sign", { project_id: S.project, summary: s }, "Signed"); load(); } }, r ? "Update sign-off" : "Sign off the review")) : "");
    };
    const lesson = (x) => {
      const f = form([{ k: "category", label: "Area", type: "select", options: [["estimate", "Estimate"], ["planning", "Planning"], ["procurement", "Procurement"], ["site", "Site"], ["equipment", "Equipment"], ["commercial", "Commercial"], ["safety", "Safety"], ["quality", "Quality"]] },
        { k: "cost_code", label: "Cost code" }, { k: "what", label: "What happened", type: "textarea", wide: true, req: true }, { k: "fix", label: "What to do next time", type: "textarea", wide: true }, { k: "owner", label: "Owner" }], x || {});
      modal(x ? "Lesson" : "New lesson", f, [{ label: "Save", cls: "primary", act: async () => { await run("adv.lesson_save", { row: Object.assign(f.values(), { id: x && x.id, project_id: S.project }) }, "Saved"); load(); } }], { narrow: true });
    };
    await load();
    return box;
  }
  addTabs("p/evm", "Cost control & earned value", "", "Earned value", [["Delay survey", surveyTab], ["Profit centres", profitTab], ["Close-out audit", closeoutTab]]);

  /* ══════════ INVENTORY ══════════ */
  function qrSvg(text, size) {
    const qr = window.qrcode(0, "M"); qr.addData(text); qr.make();
    const n = qr.getModuleCount(), c = size / (n + 8);
    let d = "";
    for (let r = 0; r < n; r++) for (let k = 0; k < n; k++) if (qr.isDark(r, k)) d += `M${(k + 4) * c},${(r + 4) * c}h${c}v${c}h-${c}z`;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"><rect width="100%" height="100%" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  }
  async function classTab() {
    const box = h("div");
    const w = { value: 35, lead: 20, critical: 25, ageing: 10, price: 10 };
    const ins = Object.fromEntries(Object.keys(w).map((k) => [k, numIn(w[k], 70)]));
    const out = h("div");
    const load = async () => {
      const d = await api("books.classify", { project_id: S.project || undefined, weights: Object.fromEntries(Object.entries(ins).map(([k, i]) => [k, Number(i.value) / 100])) });
      out.innerHTML = "";
      out.append(h("div", { class: "tiles" }, tile("Class A (70% of value)", d.summary ? d.summary.A : 0), tile("Class B", d.summary ? d.summary.B : 0), tile("Class C", d.summary ? d.summary.C : 0), tile("ABC and multi-criteria agree", fmtPct(d.agreement_pct), { sub: "the rest need a second look" })),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "annual_value", label: "Annual use (value)", fmt: "money" }, { k: "unit_price", label: "Unit price", fmt: "money" }, { k: "lead_days", label: "Lead days", fmt: "num" }, { k: "days_since_issue", label: "Days since issue", fmt: "num" },
          { k: "abc", label: "ABC" }, { k: "ved", label: "VED" }, { k: "hml", label: "HML" }, { k: "score", label: "Score", fmt: "num" }, { label: "Multi-criteria", v: (r) => h("b", { class: r.agree ? "" : "red" }, r.mc_class) }], d.rows, { name: "stock_classification" }),
        hint("ABC ranks by annual use value, VED by how critical (set in Fixed assets › Inventory analysis), HML by unit price. The score weighs all five so a cheap but vital, long-lead item still gets class A control."));
    };
    box.append(h("div", { class: "bar" }, lab("Weight: annual value %", ins.value), lab("Lead time %", ins.lead), lab("Criticality %", ins.critical), lab("Ageing %", ins.ageing), lab("Unit price %", ins.price), h("button", { class: "btn", onclick: load }, "Rank")), out);
    await load();
    return box;
  }
  async function slowTab() {
    const d = await api("books.slow", {});
    return h("div", {}, h("div", { class: "tiles" }, tile("Slow-moving stock", fmtMoney(d.total)), ...Object.entries(d.bands).map(([k, v]) => tile(k, fmtMoney(v)))), hint(d.note),
      table([{ label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "store", label: "Store" }, { k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "value", label: "Value", fmt: "money" },
        { k: "last_movement", label: "Last movement" }, { k: "days", label: "Days idle", fmt: "num" }, { k: "band", label: "Band" }, { k: "transfer_to", label: "Needed elsewhere" }], d.rows, { name: "slow_moving", totals: ["value"], empty: "Nothing idle for 90 days." }));
  }
  async function eoqTab() {
    const oc = numIn(2500, 100);
    const out = h("div");
    const load = async () => {
      const d = await api("books.eoq", { project_id: S.project || undefined, order_cost: oc.value });
      out.innerHTML = "";
      out.append(hint(d.note), table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "annual_demand", label: "Annual use", fmt: "qty" }, { k: "unit_price", label: "Price", fmt: "money" }, { k: "eoq", label: "EOQ", fmt: "qty" },
        { k: "eoq_demand_minus10", label: "Demand −10%", fmt: "qty" }, { k: "eoq_demand_plus10", label: "Demand +10%", fmt: "qty" }, { k: "eoq_holding_minus25", label: "Holding −25%", fmt: "qty" }, { k: "eoq_holding_plus25", label: "Holding +25%", fmt: "qty" },
        { k: "truck_qty", label: "Current reorder qty", fmt: "qty" }, { label: "Extra cost at that qty", v: (r) => r.truck_penalty_pct == null ? "" : h("b", { class: r.truck_penalty_pct > 10 ? "red" : "" }, r.truck_penalty_pct + "%") }], d.rows, { name: "eoq_sensitivity" }));
    };
    const box = h("div", {}, h("div", { class: "bar" }, lab("Cost of placing an order (default)", oc), h("button", { class: "btn", onclick: load }, "Recalculate")), out);
    await load();
    return box;
  }
  async function labelsTab() {
    if (need()) return need();
    const d = await api("books.item_tags", { project_id: S.project });
    const base = h("input", { value: location.origin, style: "min-width:260px" });
    const printIt = (list) => {
      const cells = list.map((t) => `<div class="lab">${qrSvg(base.value.replace(/\/$/, "") + "/#/inv/stock?" + t.q, 110)}<div><b>${escHtml(t.code)}</b><br>${escHtml(t.name)}<br><small>${escHtml(t.sub || "")}</small></div></div>`).join("");
      const w = window.open("", "_blank");
      if (!w) return toast("Allow pop-ups to print labels.", "err");
      w.document.write(`<html><head><title>Labels</title><style>body{font:12px Arial;margin:8mm}.lab{display:inline-flex;gap:8px;align-items:center;width:62mm;height:32mm;border:1px dashed #999;margin:2mm;padding:2mm;box-sizing:border-box;page-break-inside:avoid;vertical-align:top}svg{flex:none}</style></head><body>${cells}<script>setTimeout(()=>print(),300)<\/script></body></html>`);
      w.document.close();
    };
    return h("div", {}, hint("Labels for store bins and items. Scanning opens BuildCore's Stock on hand on a phone, for counts and issues."),
      lab("Address in the QR code", base),
      h("div", { class: "bar" }, h("button", { class: "btn", onclick: () => printIt(d.stores.map((s) => ({ code: s.code || s.name, name: s.name, sub: nm.pcode(S.project), q: "store=" + s.id }))) }, "Print store / bin labels (" + d.stores.length + ")"),
        h("button", { class: "btn primary", onclick: () => printIt(d.items.map((m) => ({ code: m.code, name: m.name, sub: m.unit, q: "material=" + m.id }))) }, "Print item labels (" + d.items.length + ")")),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Item" }, { k: "unit", label: "Unit" }], d.items, { name: "item_labels" }));
  }
  addTabs("inv/stock", "Stock on hand", "Balances by store with value; classification, slow-moving stock, EOQ and labels.", "Stock", [["Classification (ABC · VED · HML)", classTab], ["Slow-moving & ageing", slowTab], ["EOQ sensitivity", eoqTab], ["Item & bin labels", labelsTab]]);

  async function cycleTab() {
    if (need()) return need();
    const box = h("div");
    const load = async () => {
      const d = await api("books.cycle", { project_id: S.project });
      box.innerHTML = "";
      const stores = [...new Map(d.rows.filter((r) => r.overdue).map((r) => [r.store_id, r.store])).entries()];
      box.append(h("div", { class: "tiles" }, tile("Items due to count", d.due, { cls: d.due ? "warn" : "" }), ...d.accuracy.map((a) => tile("Record accuracy — " + a.store, a.accuracy_pct == null ? "no counts" : a.accuracy_pct + "%", { sub: a.lines_counted + " lines in 12 months, ±" + d.tolerance_pct + "%", cls: a.accuracy_pct != null && a.accuracy_pct < 95 ? "bad" : "" }))),
        hint("Count class A every " + d.frequency.A + " days, B every " + d.frequency.B + ", C every " + d.frequency.C + " instead of one big year-end count. A line is accurate when the count is within the tolerance."),
        h("div", { class: "bar" }, ...stores.map(([id, name]) => can("inventory", "edit") ? h("button", { class: "btn", onclick: async () => { const r = await run("books.cycle_sheet", { project_id: S.project, store_id: id }, "Count sheet created"); location.hash = "#/inv/count?open=" + r.id; } }, "Make count sheet: " + name) : ""),
          can("inventory", "approve") ? h("button", { class: "btn small", onclick: async () => {
            const f = form([{ k: "A", label: "Class A every (days)", type: "number" }, { k: "B", label: "Class B every", type: "number" }, { k: "C", label: "Class C every", type: "number" }, { k: "tol", label: "Tolerance %", type: "number" }], Object.assign({ tol: d.tolerance_pct }, d.frequency));
            modal("Cycle-count settings", f, [{ label: "Save", cls: "primary", act: async () => { const v = f.values(); await run("books.cycle_settings", { frequency: { A: v.A, B: v.B, C: v.C }, tolerance_pct: v.tol }, "Saved"); load(); } }], { narrow: true });
          } }, "Settings") : ""),
        table([{ k: "store", label: "Store" }, { k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "class", label: "Class" }, { k: "qty", label: "Book qty", fmt: "qty" }, { k: "value", label: "Value", fmt: "money" }, { k: "last_counted", label: "Last counted" }, { k: "due", label: "Due" }],
          d.rows, { name: "cycle_count_plan", rowClass: (r) => r.overdue ? "flag" : "" }));
    };
    await load();
    return box;
  }
  addTabs("inv/count", "Stock count", "Physical stock verification against the books.", "Counts", [["Cycle counting & accuracy", cycleTab]]);

  async function jointTab() {
    if (need()) return need();
    const hz = numIn(21, 70), cov = numIn(14, 70);
    const out = h("div");
    const load = async () => {
      const d = await api("books.joint", { project_id: S.project, horizon_days: hz.value, cover_days: cov.value });
      out.innerHTML = "";
      out.append(hint(d.note));
      if (!d.groups.length) out.append(panel("Nothing to order in the next " + d.horizon_days + " days."));
      d.groups.forEach((g) => out.append(panel(h("div", { class: "bar" }, h("h3", { class: "grow" }, g.vendor), h("span", {}, fmtMoney(g.value) + " · first need " + g.first_need + (g.orders_saved ? " · saves " + g.orders_saved + " separate orders" : ""))),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "qty", label: "Order qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "order_by", label: "Order by" }, { k: "need_date", label: "Needed" }, { k: "value", label: "Value", fmt: "money" },
          { label: "Deliveries (paced)", v: (l) => l.deliveries.map((x) => x.date.slice(5) + ": " + fmtN(x.qty)).join(" · ") }], g.lines, { search: false, name: "joint_order" }))));
    };
    const box = h("div", {}, h("div", { class: "bar" }, lab("Order window (days)", hz), lab("Each delivery covers (days)", cov), h("button", { class: "btn", onclick: load }, "Group")), out);
    await load();
    return box;
  }
  addTabs("inv/risk", "Material forecast & planning", "", "Shortage risk", [["Joint orders & delivery pacing", jointTab]]);

  async function matCurveTab() {
    if (need()) return need();
    const d = await api("books.mat_curve", { project_id: S.project });
    if (!d.points.length) return panel("Needs activities with BOQ items and baseline or planned dates.");
    const last = d.points.filter((p) => p.cpi != null).slice(-1)[0];
    return h("div", {}, h("div", { class: "tiles" }, tile("Material CPI (to date)", last ? last.cpi : "—", { cls: last && last.cpi < 0.95 ? "bad" : "", sub: "earned ÷ actual material cost" })),
      lineChart(d.points.map((p) => p.month), [{ name: "Planned", color: "#7f8c8d", dash: 1, values: d.points.map((p) => p.planned) }, { name: "Earned", color: "#2d8a4e", values: d.points.map((p) => p.earned) }, { name: "Actual", color: "#b3392c", values: d.points.map((p) => p.actual) }]),
      hint(d.note),
      table([{ k: "month", label: "Month" }, { k: "planned", label: "Planned (cum.)", fmt: "money" }, { k: "earned", label: "Earned (cum.)", fmt: "money" }, { k: "actual", label: "Actual (cum.)", fmt: "money" }, { k: "cpi", label: "Material CPI", fmt: "num" }], d.points, { search: false, name: "material_s_curve" }));
  }
  addTabs("inv/recon", "Material reconciliation", "", "Reconciliation", [["Material cost curve & CPI", matCurveTab]]);

  /* ══════════ ACCOUNTS / NFRS ══════════ */
  async function nfrsTab() {
    const box = h("div");
    const load = async () => {
      const [t, s] = await Promise.all([api("books.tier", {}), api("books.nfrs_status", {})]);
      box.innerHTML = "";
      box.append(h("div", { class: "tiles" }, tile("Reporting framework", t.label, { cls: t.tier === "NFRS" ? "warn" : "" }), tile("Fiscal year", t.fy + "/" + String(t.fy + 1).slice(2)),
        tile("Cash payments over the limit (this year)", s.cash_over_limit.length, { sub: fmtMoney(s.cash_over_limit_total) + " not deductible", cls: s.cash_over_limit.length ? "bad" : "" })),
      t.warning ? panel(h("b", { class: "red" }, t.warning)) : "",
      h("h2", { class: "sec" }, "Entity tier — the last three years"),
      table([{ label: "Year", v: (r) => r.fy + "/" + String(r.fy + 1).slice(2) + (r.auto ? " (from the books)" : "") }, { k: "turnover", label: "Turnover", fmt: "money" }, { k: "borrowings", label: "Borrowings", fmt: "money" }, { k: "total_assets", label: "Total assets", fmt: "money" }, { k: "employees", label: "Employees", fmt: "num" },
        { label: "Public accountability / over a limit", v: (r) => r.significant ? h("b", { class: "red" }, r.hits.join(", ") || "yes") : "no" }, { label: "Within micro limits", v: (r) => r.micro ? "yes" : "no" }], t.years,
      { search: false, export: false, onRow: can("accounts", "edit") ? (r) => {
        const f = form([{ k: "turnover", label: "Turnover", type: "number" }, { k: "borrowings", label: "Borrowings", type: "number" }, { k: "total_assets", label: "Total assets", type: "number" }, { k: "employees", label: "Employees (average, incl. site)", type: "number" }, { k: "fiduciary", label: "Assets held in a fiduciary capacity", type: "number" },
          { k: "listed", label: "Listed or applying to list", type: "check" }, { k: "fi", label: "Bank / insurance / financial institution", type: "check" }, { k: "gbe", label: "Government business entity", type: "check" },
          { k: "previous_tier", label: "Framework used before this period", type: "select", options: [["SME", "NFRS for SMEs"], ["NFRS", "Full NFRS"], ["MICRO", "NAS for Micro Entities"]] }, { k: "remarks", label: "Remarks", wide: true }], r);
        modal("Tier facts " + r.fy + "/" + String(r.fy + 1).slice(2), f, [{ label: "Save", cls: "primary", act: async () => { await run("books.tier_save", { row: Object.assign(f.values(), { fy: r.fy }) }, "Saved"); load(); } }], { narrow: true });
      } : null }),
      hint("A company moves to full NFRS after crossing any one limit (turnover NPR 1,000m, borrowings 500m, total assets 1,000m, 300 employees) in two years in a row, and moves back only after two years below all of them. Micro: all micro limits two years in a row. " + t.note),
      h("h2", { class: "sec" }, "NFRS checklist — where each item is"),
      table([{ k: "no", label: "#" }, { k: "item", label: "Requirement" }, { k: "where", label: "In BuildCore" }], s.items, { search: false, name: "nfrs_checklist" }),
      h("h2", { class: "sec" }, "Cash payments above the limit"), hint(s.note),
      table([{ k: "no", label: "Payment" }, { k: "date", label: "Date" }, { k: "party", label: "Paid to" }, { k: "gross", label: "Amount", fmt: "money" }], s.cash_over_limit, { search: false, name: "cash_over_limit", totals: ["gross"], empty: "None this year." }));
    };
    await load();
    return box;
  }
  addTabs("acc/integrity", "Integrity checks", "Checks that the books agree with themselves, and NFRS compliance.", "Checks", [["NFRS compliance", nfrsTab]]);

  async function eclTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("books.ecl", {});
      box.innerHTML = "";
      const rates = Object.fromEntries(d.buckets.map((b) => [b, numIn(d.rates[b], 70)]));
      box.append(h("div", { class: "tiles" }, tile("Allowance needed", fmtMoney(d.required)), tile("Booked", fmtMoney(d.booked)), tile("Adjustment", fmtMoney(d.adjustment), { cls: Math.abs(d.adjustment) > 1 ? "warn" : "" })), hint(d.note),
        h("div", { class: "bar" }, ...d.buckets.map((b) => lab(b + " %", rates[b])),
          can("accounts", "edit") ? h("button", { class: "btn", onclick: async () => { await run("books.ecl_rates", { rates: Object.fromEntries(Object.entries(rates).map(([k, i]) => [k, i.value])) }, "Rates saved"); load(); } }, "Save rates") : "",
          can("accounts", "approve") && Math.abs(d.adjustment) > 0.5 ? h("button", { class: "btn primary", onclick: async () => { await run("books.ecl_post", {}, "Posted"); load(); } }, "Post the adjustment") : ""),
        h("h3", {}, "Provision matrix"),
        table([{ k: "bucket", label: "Age" }, { k: "kind", label: "Balance" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "rate", label: "Loss rate %", fmt: "num" }, { k: "ecl", label: "Expected loss", fmt: "money" }], d.matrix, { search: false, name: "ecl_matrix", totals: ["amount", "ecl"] }),
        h("h3", {}, "Detail"),
        table([{ k: "no", label: "Invoice" }, { label: "Client", v: (r) => nm.party ? nm.party(r.party_id) : r.party_id }, { k: "kind", label: "Balance" }, { k: "age", label: "Days", fmt: "num" }, { k: "bucket", label: "Age band" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "ecl", label: "Expected loss", fmt: "money" }], d.rows, { name: "ecl_detail" }));
    };
    await load();
    return box;
  }
  addTabs("acc/ageing", "Ageing", "Open invoice balances by days past due, and the expected credit loss allowance.", "Ageing", [["Expected credit loss (NFRS 9)", eclTab]]);

  async function provTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("books.prov_list", {});
      box.innerHTML = "";
      box.append(h("div", { class: "bar" }, hint("NAS 37: a provision when an obligation exists, an outflow is probable and the amount can be estimated. Each movement posts a voucher."),
        can("accounts", "edit") ? h("button", { class: "btn primary", onclick: () => edit(null, d.kinds) }, "New provision") : ""),
      h("h3", {}, "Movement for FY " + d.fy + "/" + String(d.fy + 1).slice(2)),
      table([{ k: "label", label: "Class" }, { k: "opening", label: "Opening", fmt: "money" }, { k: "additions", label: "Added", fmt: "money" }, { k: "used", label: "Used", fmt: "money" }, { k: "reversed", label: "Reversed unused", fmt: "money" }, { k: "unwinding", label: "Unwinding", fmt: "money" }, { k: "closing", label: "Closing", fmt: "money" }],
        d.movement, { search: false, name: "provision_movement", totals: ["opening", "additions", "used", "reversed", "unwinding", "closing"], empty: "No provisions." }),
      h("h3", {}, "Register"),
      table([{ k: "no", label: "No." }, { k: "title", label: "Provision" }, { label: "Class", v: (r) => (d.kinds.find((k) => k[0] === r.kind) || [0, r.kind])[1] }, { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "" }, { k: "probability", label: "Probability" }, { k: "closing", label: "Balance", fmt: "money" }], d.rows,
        { name: "provisions", onRow: (r) => edit(r, d.kinds) }));
    };
    const edit = (r, kinds) => {
      const f = form([{ k: "title", label: "Provision", req: true, wide: true }, { k: "kind", label: "Class", type: "select", noBlank: true, options: kinds }, { k: "project_id", label: "Project", type: "select", options: opt.projects },
        { k: "probability", label: "Probability", type: "select", options: [["probable", "Probable (provide)"], ["possible", "Possible (disclose only)"], ["remote", "Remote"]] }, { k: "basis", label: "Basis of the estimate", type: "textarea", wide: true }, { k: "remarks", label: "Remarks", wide: true }], r || { kind: "defects" });
      const mv = r ? form([{ k: "kind", label: "Movement", type: "select", noBlank: true, options: [["add", "Add (charge to expense)"], ["use", "Use (paid out)"], ["reverse", "Reverse unused"], ["unwind", "Unwind discount (finance cost)"]] }, { k: "amount", label: "Amount", type: "number" }, { k: "date", label: "Date", type: "date" }, { k: "account_id", label: "Paid from (for Use)", type: "select", options: () => S.L.accounts.filter((a) => ["bank", "cash"].includes(a.role)).map((a) => [a.id, a.name]) }, { k: "note", label: "Note", wide: true }], { kind: "add", date: today() }) : null;
      const b = [];
      if (can("accounts", "edit")) b.push({ label: "Save", act: async () => { await run("books.prov_save", { row: Object.assign(f.values(), { id: r && r.id }) }, "Saved"); load(); } });
      if (r && can("accounts", "approve")) b.push({ label: "Post movement", cls: "primary", act: async () => { await run("books.prov_move", Object.assign(mv.values(), { id: r.id }), "Posted"); load(); } });
      drawer(r ? r.no + " " + r.title : "New provision", h("div", {}, f, r ? h("div", {}, h("h3", {}, "Movements"), table([{ k: "date", label: "Date" }, { k: "kind", label: "Movement" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "note", label: "Note" }], r.moves, { search: false, export: false }), h("h3", {}, "New movement"), mv) : ""), b);
    };
    await load();
    return box;
  }
  async function deferredTab() {
    const d = await api("books.deferred", {});
    return h("div", {}, h("div", { class: "tiles" }, tile("Net deferred tax " + d.position, fmtMoney(Math.abs(d.net))), tile("Tax rate", d.rate + "%")), hint(d.note),
      table([{ k: "item", label: "Item" }, { k: "carrying", label: "Carrying amount", fmt: "money" }, { k: "tax_base", label: "Tax base", fmt: "money" }, { k: "difference", label: "Temporary difference", fmt: "money" }, { k: "kind", label: "Kind" }, { k: "deferred_tax", label: "Deferred tax (+ liability / − asset)", fmt: "money" }], d.items, { search: false, name: "deferred_tax", totals: ["deferred_tax"] }));
  }
  async function n18Tab() {
    const box = h("div");
    const f = form([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], {});
    const out = h("div");
    const load = async () => {
      const d = await api("books.nfrs18", f.values());
      out.innerHTML = "";
      const cat = Object.fromEntries(d.categories);
      const sec = (k) => d.lines.filter((l) => l.category === k);
      const rows = [];
      d.categories.forEach(([k, l]) => {
        const xs = sec(k);
        if (!xs.length) return;
        rows.push({ label: h("b", {}, l), amount: null });
        xs.forEach((x) => rows.push({ label: "   " + x.code + " " + x.name, amount: x.amount, line: x }));
        if (k === "operating") rows.push({ label: h("b", {}, "Operating profit or loss"), amount: d.operating_profit, bold: 1 });
        if (k === "investing") rows.push({ label: h("b", {}, "Profit before financing and income tax"), amount: d.profit_before_financing_and_tax, bold: 1 });
        if (k === "financing") rows.push({ label: h("b", {}, "Profit before income tax"), amount: d.profit_before_tax, bold: 1 });
      });
      rows.push({ label: h("b", {}, "Profit or loss for the period"), amount: d.profit, bold: 1 });
      out.append(table([{ label: "", v: (r) => r.label }, { label: "Amount", fmt: "money", v: (r) => r.amount }, { label: "Category", v: (r) => r.line && can("accounts", "edit") ? h("select", { onclick: (e) => e.stopPropagation(), onchange: async (e) => { await run("books.nfrs18_map", { map: { [r.line.id]: e.target.value } }, "Saved"); load(); } }, d.categories.map(([k, l]) => h("option", { value: k, selected: k === r.line.category }, l))) : (r.line ? cat[r.line.category] : "") }],
        rows, { search: false, name: "nfrs18_pl", rowClass: (r) => r.bold ? "flag" : "" }),
      h("h3", {}, "Management-defined performance measures"), table([{ k: "name", label: "Measure" }, { k: "value", label: "Value", fmt: "money" }, { k: "reconciliation", label: "Reconciliation" }], d.mpm, { search: false, export: false }),
      hint("NFRS 18 (IFRS 18) replaces NAS 1 presentation: income and expenses go into operating, investing, financing and income-tax categories with fixed subtotals. The ledger is unchanged; pick the category per account here. Still at exposure-draft stage in Nepal."));
    };
    f.addEventListener("change", load);
    box.append(f, out);
    await load();
    return box;
  }
  addTabs("acc/bs", "Balance sheet", "Company position on a date.", "Balance sheet", [["Provisions (NAS 37)", provTab], ["Deferred tax (NAS 12)", deferredTab], ["NFRS 18 view of profit or loss", n18Tab]]);

  async function tdsFyTab() {
    const box = h("div");
    let fy = null;
    const load = async () => {
      const d = await api("books.tds_fy", fy ? { fy } : {});
      fy = d.fy;
      box.innerHTML = "";
      const ysel = h("select", { onchange: (e) => { fy = Number(e.target.value); load(); } }, [...new Set(d.years.concat([d.fy]))].sort().map((y) => h("option", { value: y, selected: y === d.fy }, y + "/" + String(y + 1).slice(2))));
      const ed = lineEditor([{ k: "section", label: "Section", w: 70 }, { k: "description", label: "Payment", w: 260 }, { k: "rate", label: "Rate %", type: "number", w: 70 }, { k: "threshold", label: "Threshold", type: "number", w: 90 }, { k: "final", label: "Final (1/0)", type: "number", w: 60 }, { k: "notes", label: "Notes / reference", w: 220 }], d.rows, { readonly: !can("accounts", "edit") });
      box.append(h("div", { class: "bar" }, lab("Fiscal year", ysel),
        can("accounts", "edit") ? h("button", { class: "btn primary", onclick: async () => { await run("books.tds_fy_save", { fy, rows: ed.lines() }, "Saved"); load(); } }, "Save this year") : "",
        can("accounts", "edit") ? h("button", { class: "btn", onclick: async () => { const y = await ask("Start the next year", "Copy " + fy + " rates into a new year, then edit what the Finance Act changed.", { input: "Fiscal year (BS)", value: String(fy + 1) }); if (!y) return; await run("books.tds_fy_save", { fy: Number(y), copy_from: fy }, "Copied"); fy = Number(y); load(); } }, "Copy to a new year") : ""),
      hint(d.note), ed,
      d.differences.length ? h("div", {}, h("h3", {}, "Differs from the rates used on payments now"), table([{ k: "master", label: "Rate in use" }, { k: "master_rate", label: "In use %", fmt: "num" }, { k: "fy_rate", label: "This year %", fmt: "num" }], d.differences, { search: false, export: false })) : "");
    };
    await load();
    return box;
  }
  addTabs("acc/tdsrates", "TDS rates", "Check each rate against the current Income Tax Act before use.", "Rates in use", [["By fiscal year", tdsFyTab]]);

  async function jvTab() {
    if (need()) return need();
    const f = form([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], {});
    const out = h("div");
    const load = async () => {
      out.innerHTML = "";
      let d;
      try { d = await api("books.jv", Object.assign({ project_id: S.project }, f.values())); } catch (e) { out.append(panel(e.message)); return; }
      out.append(hint(d.project.code + " — " + d.partners.map((p) => p.name + " " + p.share + "%").join(", ") + ". " + d.note),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Account" }, { k: "type", label: "Type" }, { k: "total", label: "Total", fmt: "money" }].concat(d.partners.map((p) => ({ k: p.name, label: p.name, fmt: "money" }))), d.rows, { name: "jv_partner_shares" }));
    };
    f.addEventListener("change", load);
    const box = h("div", {}, f, out);
    await load();
    return box;
  }
  addTabs("acc/pl", "Profit & loss", "Income less expenses for the period.", "Profit & loss", [["JV partner shares", jvTab]]);

  async function cbmsTab() {
    const f = form([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], {});
    const out = h("div");
    const load = async () => {
      const d = await api("books.cbms", f.values());
      out.innerHTML = "";
      const dl = (name, text, type) => { const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name }); document.body.append(a); a.click(); a.remove(); };
      out.append(h("div", { class: "tiles" }, tile("Invoices", d.count), tile("Sales in the range", fmtMoney(d.total)), tile("Sales this fiscal year", fmtMoney(d.year_total), { sub: d.linked_required ? "above NPR 100m — CBMS link required" : "below the NPR 100m threshold", cls: d.linked_required ? "warn" : "" })),
        hint(d.note),
        h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: () => dl("cbms_sales_" + today() + ".json", JSON.stringify(d.rows, null, 2), "application/json") }, "Download JSON")),
        table([{ k: "invoice_number", label: "Invoice" }, { k: "invoice_date", label: "Date (BS)" }, { k: "buyer_name", label: "Buyer" }, { k: "buyer_pan", label: "Buyer PAN" }, { k: "taxable_sales_vat", label: "Taxable", fmt: "money" }, { k: "vat", label: "VAT", fmt: "money" }, { k: "total_sales", label: "Total", fmt: "money" }, { k: "status", label: "Status" }], d.rows, { name: "cbms_sales", totals: ["taxable_sales_vat", "vat", "total_sales"] }));
    };
    f.addEventListener("change", load);
    const box = h("div", {}, f, out);
    await load();
    return box;
  }
  addTabs("acc/sales", "Client invoices", "Sales invoices to clients.", "Invoices", [["CBMS e-invoice export", cbmsTab]]);
  /* ══════════ IMPORT FROM AN EXCEL / CSV FILE (replaces "Paste from Excel") ══════════ */
  const TABLE_KIND = { materials: "materials", parties: "parties", staff: "staff", equipment: "equipment", boq_items: "boq_items" };
  const IMPORT_HELP = "In Excel: File › Save As › “CSV UTF-8 (Comma delimited)”, or pick the .xlsx itself. The first row must be the column headings (a title row above it is fine). Codes that already exist are updated, new ones are added.";
  window.bcoImport = function (o) {
    let file = null, prev = null;
    const info = h("div");
    const out = h("div");
    const dsel = h("select", {}, [["auto", "Dates: detect"], ["dmy", "Dates are day/month/year"], ["mdy", "Dates are month/day/year"]].map(([v, l]) => h("option", { value: v }, l)));
    const fname = h("b", {}, "no file chosen");
    const call = (apply) => api("imp.file", { kind: o.kind, filename: file.filename, b64: file.b64, project_id: S.project || undefined, apply: apply ? 1 : 0, date_order: dsel.value, calendar_id: o.calendar_id });
    const check = async () => {
      if (!file) return;
      out.innerHTML = ""; out.append(h("p", { class: "muted" }, "Checking every row…"));
      try { prev = await call(false); } catch (e) { out.innerHTML = ""; out.append(h("div", { class: "panel" }, h("b", { class: "red" }, e.message))); prev = null; return; }
      out.innerHTML = "";
      const ok = prev.added + prev.updated;
      out.append(h("div", { class: "tiles" }, tile("New", prev.added), tile("Update existing", prev.updated), tile("Cannot import", prev.failed, { cls: prev.failed ? "bad" : "" })),
        h("p", { class: "hint" }, "Columns read: " + prev.columns.join(", ") + (prev.ignored_columns.length ? " · ignored: " + prev.ignored_columns.join(", ") : "") + " · " + prev.date_order + ". Nothing is saved until you press Import."),
        table([{ k: "line", label: "Row" }, { k: "key", label: "Code" }, { k: "name", label: "Name" }].concat(o.kind === "activities" ? [{ k: "start", label: "Start" }, { k: "finish", label: "Finish" }] : [])
          .concat([{ label: "Result", v: (r) => r.error ? h("b", { class: "red" }, r.error) : r.warning ? h("span", { class: "red" }, (r.action === "update" ? "update · " : "new · ") + r.warning) : (r.action === "update" ? "update" : "new") }]),
        prev.rows, { search: prev.rows.length > 8, name: o.kind + "_import_check", rowClass: (r) => r.error ? "bad" : "" }));
      imp.textContent = ok ? (o.kind === "opening" ? "Load " : "Import ") + ok + " row" + (ok === 1 ? "" : "s") + (prev.failed ? " (skip " + prev.failed + ")" : "") : "Nothing to import";
      imp.disabled = !ok;
    };
    const pick = () => {
      const i = h("input", { type: "file", accept: ".csv,.xlsx,.xlsm,.txt", style: "display:none" });
      i.addEventListener("change", () => {
        const f = i.files[0]; if (!f) return;
        const r = new FileReader();
        r.onload = () => { file = { filename: f.name, b64: String(r.result) }; fname.textContent = f.name; check(); };
        r.readAsDataURL(f);
      });
      document.body.append(i); i.click(); setTimeout(() => i.remove(), 120000);
    };
    dsel.onchange = check;
    const imp = h("button", { class: "btn primary", disabled: true }, "Import");
    const tpl = async () => { const t = await api("imp.template", { kind: o.kind }); const a = h("a", { href: URL.createObjectURL(new Blob(["﻿" + t.csv], { type: "text/csv" })), download: t.filename }); document.body.append(a); a.click(); a.remove(); };
    api("imp.template", { kind: o.kind }).then((t) => info.append(h("p", {}, "Columns: ", ...t.columns.map((c, k) => [k ? ", " : "", c.required ? h("b", {}, c.field) : c.field]), h("span", { class: "muted" }, " (bold = needed; headings in other words like “Quantity”, “Start date” are recognised)"))));
    const m = modal("Import " + o.title + " from Excel / CSV", h("div", {}, h("p", { class: "hint" }, IMPORT_HELP), info,
      h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: pick }, "Choose file…"), fname, dsel, h("div", { class: "grow" }), h("button", { class: "btn small", onclick: tpl }, "Download blank template")), out), []);
    imp.onclick = async () => {
      if (!file || !prev) return;
      imp.disabled = true;
      try {
        const r = await call(true);
        if (o.kind === "opening") { m.close(); o.onLines && o.onLines(r); return; }
        toast((r.added ? r.added + " added" : "") + (r.added && r.updated ? ", " : "") + (r.updated ? r.updated + " updated" : "") + (r.failed ? ", " + r.failed + " skipped" : "") || "Nothing imported", r.failed ? "err" : "ok");
        m.close();
        if (o.onDone) await o.onDone(r);
      } catch (e) { toast(e.message, "err"); imp.disabled = false; }
    };
    m.el.querySelector("footer").prepend(imp);
  };
  const _origPasteImport = window.pasteImport;
  window.pasteImport = function (o, load) {
    const kind = TABLE_KIND[o.table];
    if (!kind) return _origPasteImport(o, load);
    if (o.byProject && !S.project) return toast("Select a project first.", "err");
    window.bcoImport({ kind, title: o.title.toLowerCase(), onDone: async () => { await reloadLookups(); load(); } });
  };
  window.pasteActivities = function () {
    if (!S.project) return toast("Select a project first.", "err");
    window.bcoImport({ kind: "activities", title: "activities", onDone: async () => { await loadProjectLists(); go(); } });
  };
  /* the buttons keep their place; only their words change */
  const relabel = (root) => {
    root.querySelectorAll && root.querySelectorAll("button, summary").forEach((b) => {
      if (b.textContent === "Paste from Excel") b.textContent = b.tagName === "SUMMARY" ? "Paste rows instead" : "Import from Excel / CSV";
    });
  };
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => n.nodeType === 1 && relabel(n)))).observe(document.body, { childList: true, subtree: true });
  /* Inventory › Opening stock: fill the lines from a file */
  const _open = PAGES["inv/opening"];
  if (_open) PAGES["inv/opening"] = async (root, params) => {
    await _open(root, params);
    const ta = root.querySelector("textarea");
    const det = ta && ta.closest("details");
    if (!det || !can("inventory", "edit")) return;
    const loadBtn = [...det.querySelectorAll("button")].find((b) => /Load pasted/.test(b.textContent));
    det.before(h("div", { class: "bar", style: "margin-top:10px" }, h("button", { class: "btn", onclick: () => window.bcoImport({ kind: "opening", title: "opening stock", onLines: (r) => {
      ta.value = r.rows.filter((x) => !x.error).map((x, k) => [x.key, r.lines[k].qty, r.lines[k].rate].join("\t")).join("\n");
      if (loadBtn) loadBtn.click();
      toast(r.lines.length + (r.lines.length === 1 ? " line" : " lines") + " loaded — check them and post" + (r.failed ? "; " + r.failed + " skipped" : ""), r.failed ? "err" : "ok");
    } }) }, "Import lines from Excel / CSV"), h("span", { class: "hint" }, "Columns: material_code, qty, rate")));
  };
  /* ══════════ NEPALI (BS) OR ENGLISH (AD) DATES — ONE SWITCH FOR THE WHOLE APP ══════════
     English: every date is shown and typed in AD. Nepali: every date is shown and typed in BS (with a BS calendar),
     in lists, panels, headings, printouts and CSV exports. The database keeps AD, so sorting and reports stay right. */
  let BST = null, bsLoading = null;
  const loadBS = () => bsLoading || (bsLoading = api("bs.table", {}).then((t) => {
    BST = Object.entries(t.years).map(([y, v]) => ({ y: Number(y), start: Date.UTC(...v.start.split("-").map((x, i) => Number(x) - (i === 1 ? 1 : 0))), m: v.months })).sort((a, b) => a.y - b.y);
    window.BS_MONTHS = t.months; applyMode(); enhanceAll(); convertTree(document.body); if (MODE !== "ad" && !document.querySelector(".overlay")) rerender();
  }).catch(() => { bsLoading = null; }));
  const utc = (iso) => { const [y, m, d] = iso.slice(0, 10).split("-").map(Number); return Date.UTC(y, m - 1, d); };
  const pad = (n) => String(n).padStart(2, "0");
  window.adToBs = function (iso) {
    if (!BST || !/^\d{4}-\d\d-\d\d/.test(iso || "")) return null;
    const t = utc(iso);
    for (let i = BST.length - 1; i >= 0; i--) {
      if (t >= BST[i].start) {
        let off = Math.round((t - BST[i].start) / 864e5);
        for (let k = 0; k < 12; k++) { if (off < BST[i].m[k]) return BST[i].y + "-" + pad(k + 1) + "-" + pad(off + 1); off -= BST[i].m[k]; }
        return null;
      }
    }
    return null;
  };
  window.bsToAd = function (txt) {
    const m = String(txt || "").trim().match(/^(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})$/);
    if (!m || !BST) return null;
    const y = BST.find((x) => x.y === Number(m[1]));
    const mo = Number(m[2]), d = Number(m[3]);
    if (!y || mo < 1 || mo > 12 || d < 1 || d > y.m[mo - 1]) return null;
    const off = y.m.slice(0, mo - 1).reduce((a, b) => a + b, 0) + d - 1;
    return new Date(y.start + off * 864e5).toISOString().slice(0, 10);
  };
  const bsLabel = (iso) => { const b = window.adToBs(iso); if (!b) return ""; const [y, m, d] = b.split("-"); return Number(d) + " " + ((window.BS_MONTHS || [])[Number(m) - 1] || m) + " " + y; };
  window.bsLabel = bsLabel;
  let MODE = "ad";
  try { MODE = localStorage.getItem("bco_date_mode") || "ad"; } catch (e) { /* private window */ }
  if (!["ad", "bs", "both"].includes(MODE)) MODE = "ad";
  window.bcoDateMode = () => MODE;
  const ISO_RE = /\b(20[0-4]\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b/g;
  const toBsText = (txt) => txt.replace(ISO_RE, (m0) => window.adToBs(m0) || m0);
  const applyMode = () => { document.body.classList.remove("dm-ad", "dm-bs", "dm-both"); document.body.classList.add("dm-" + MODE); };
  const rerender = () => { if (typeof window.go === "function" && document.querySelector("#page")) try { window.go(); } catch (e) { /* not ready */ } };

  /* lists */
  const _cellValue = window.cellValue;
  window.cellValue = function (c, r) {
    const v = _cellValue(c, r);
    if (MODE === "ad" || typeof v !== "string" || !/^\d{4}-\d\d-\d\d$/.test(v) || Number(v.slice(0, 4)) > 2050) return v;
    const b = window.adToBs(v);
    if (!b) { if (!BST) loadBS(); return v; }
    return MODE === "bs" ? b : h("span", { class: "dual-date" }, v, h("small", {}, b + " BS"));
  };
  /* everything else on screen (panels, headings, notes, drop-downs, messages) in Nepali mode */
  const SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1, NOSCRIPT: 1 };
  const convertTree = (root) => {
    if (MODE !== "bs" || !BST || !root) return;
    if (root.nodeType === 3) { if (ISO_RE.test(root.nodeValue)) { ISO_RE.lastIndex = 0; root.nodeValue = toBsText(root.nodeValue); } ISO_RE.lastIndex = 0; return; }
    if (root.nodeType !== 1 || SKIP[root.tagName] || (root.closest && root.closest(".no-bs"))) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement && (SKIP[n.parentElement.tagName] || n.parentElement.closest(".no-bs"))) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    const hits = [];
    for (let n = w.nextNode(); n; n = w.nextNode()) { ISO_RE.lastIndex = 0; if (ISO_RE.test(n.nodeValue)) hits.push(n); }
    ISO_RE.lastIndex = 0;
    hits.forEach((n) => { n.nodeValue = toBsText(n.nodeValue); });
  };
  /* printouts and CSV files follow the switch too */
  const convVal = (v) => (MODE === "bs" && typeof v === "string") ? toBsText(v) : v;
  if (typeof window.printDoc === "function") {
    const _print = window.printDoc;
    window.printDoc = function (title, meta, cols, rows, totals, note) {
      if (MODE !== "bs") return _print(title, meta, cols, rows, totals, note);
      const m2 = (meta || []).map((x) => Array.isArray(x) ? x.map(convVal) : x);
      const c2 = (cols || []).map((c) => typeof c.v === "function" ? Object.assign({}, c, { v: (r) => convVal(c.v(r)) }) : c);
      const r2 = (rows || []).map((r) => { const o = {}; Object.keys(r || {}).forEach((k) => { o[k] = convVal(r[k]); }); return o; });
      return _print(convVal(title), m2, c2, r2, totals, convVal(note));
    };
  }
  if (typeof window.exportCsv === "function") {
    const _csv = window.exportCsv;
    window.exportCsv = function (name, cols, rows, o) {
      if (MODE !== "bs") return _csv(name, cols, rows, o);
      const c2 = (cols || []).map((c) => typeof c.v === "function" ? Object.assign({}, c, { v: (r) => { const x = c.v(r); return x instanceof Node ? toBsText(x.textContent) : convVal(x); } }) : c);
      const r2 = (rows || []).map((r) => { const o2 = {}; Object.keys(r || {}).forEach((k) => { o2[k] = convVal(r[k]); }); return o2; });
      return _csv(name, c2, r2, o);
    };
  }

  /* date boxes: English = the normal date box; Nepali = a BS box with a BS calendar; both = the two */
  const style = document.createElement("style");
  style.textContent = ".dual-date{display:inline-flex;flex-direction:column;line-height:1.15;white-space:nowrap}.dual-date small{color:var(--muted,#6b7280);font-size:11px}.date-mode{width:auto!important;max-width:190px}" +
    ".bsbox{display:block;margin-top:3px;width:100%;max-width:170px;font-size:12px!important;padding:3px 6px!important;border-style:dashed!important}.bsbox.bad{border-color:#b3392c!important;color:#b3392c}" +
    ".bshint{display:block;font-size:11px;color:var(--muted,#6b7280);margin-top:1px}" +
    "body.dm-ad .bsbox,body.dm-ad .bshint{display:none!important}" +
    "body.dm-bs input[type=date]{display:none!important}body.dm-bs .bsbox{margin-top:0;max-width:none;font-size:inherit!important;padding:5px 8px!important;border-style:solid!important}" +
    ".bspick{position:absolute;z-index:9999;background:var(--panel,#fff);border:1px solid var(--line,#ccc);border-radius:6px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:8px;width:252px;font-size:13px}" +
    ".bspick .hd{display:flex;gap:4px;align-items:center;margin-bottom:6px}.bspick .hd select{padding:2px 4px;width:auto}.bspick .hd button{border:1px solid var(--line,#ccc);background:none;border-radius:4px;cursor:pointer;padding:1px 7px}" +
    ".bspick .gr{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;text-align:center}.bspick .gr b{font-size:11px;color:var(--muted,#6b7280);font-weight:600}" +
    ".bspick .gr span{padding:4px 0;border-radius:4px;cursor:pointer}.bspick .gr span:hover{background:#e8f0f7}.bspick .gr span.on{background:var(--blue,#1f6fb2);color:#fff}.bspick .gr span.td{outline:1px solid var(--blue,#1f6fb2)}" +
    ".bspick .ft{display:flex;justify-content:space-between;margin-top:6px}.bspick .ft a{cursor:pointer;color:var(--blue,#1f6fb2)}";
  document.head.append(style);
  let picker = null;
  const closePicker = () => { if (picker) { picker.remove(); picker = null; } };
  document.addEventListener("mousedown", (e) => { if (picker && !picker.contains(e.target) && !(e.target.classList && e.target.classList.contains("bsbox"))) closePicker(); }, true);
  const openPicker = (bs, apply) => {
    closePicker();
    if (!BST) return;
    let cur = window.bsToAd(bs.value) ? bs.value : (window.adToBs(today()) || "");
    let [yy, mm] = cur.split("-").map(Number);
    picker = h("div", { class: "bspick" });
    const draw = () => {
      picker.innerHTML = "";
      const yr = BST.find((x) => x.y === yy) || BST[BST.length - 1];
      const first = new Date(window.bsToAd(yy + "-" + pad(mm) + "-01") + "T00:00:00Z").getUTCDay();
      const ysel = h("select", { onchange: (e) => { yy = Number(e.target.value); draw(); } }, BST.map((x) => h("option", { value: x.y, selected: x.y === yy }, x.y)));
      const msel = h("select", { onchange: (e) => { mm = Number(e.target.value); draw(); } }, (window.BS_MONTHS || []).map((n, k) => h("option", { value: k + 1, selected: k + 1 === mm }, n)));
      const step = (d) => { mm += d; if (mm < 1) { mm = 12; yy--; } if (mm > 12) { mm = 1; yy++; } if (!BST.find((x) => x.y === yy)) { mm -= d; yy = Math.min(Math.max(yy, BST[0].y), BST[BST.length - 1].y); } draw(); };
      const grid = h("div", { class: "gr" }, ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => h("b", {}, d.slice(0, 2))));
      for (let k = 0; k < first; k++) grid.append(h("i"));
      const tdy = window.adToBs(today());
      for (let d = 1; d <= yr.m[mm - 1]; d++) {
        const v = yy + "-" + pad(mm) + "-" + pad(d);
        grid.append(h("span", { class: (v === bs.value ? "on " : "") + (v === tdy ? "td" : ""), onclick: () => { bs.value = v; closePicker(); apply(); } }, d));
      }
      picker.append(h("div", { class: "hd" }, h("button", { type: "button", onclick: () => step(-1) }, "‹"), msel, ysel, h("button", { type: "button", onclick: () => step(1) }, "›")), grid,
        h("div", { class: "ft" }, h("a", { onclick: () => { bs.value = tdy; closePicker(); apply(); } }, "Today"), h("a", { onclick: () => { bs.value = ""; closePicker(); apply(true); } }, "Clear")));
    };
    draw();
    document.body.append(picker);
    const r = bs.getBoundingClientRect();
    picker.style.left = Math.max(4, Math.min(window.innerWidth - 260, r.left + window.scrollX)) + "px";
    picker.style.top = (r.bottom + window.scrollY + 3) + "px";
  };
  const watched = new Set();
  const enhance = (inp) => {
    if (inp._bs || inp.closest(".no-bs")) return;
    inp._bs = true;
    const bs = h("input", { type: "text", class: "bsbox", placeholder: "YYYY-MM-DD (BS)", title: "Nepali date (Bikram Sambat)", inputmode: "numeric", autocomplete: "off" });
    const tip = h("span", { class: "bshint" });
    const fromAd = () => { if (document.activeElement === bs) return; const b = window.adToBs(inp.value); bs.value = b || ""; bs.classList.remove("bad"); tip.textContent = b ? bsLabel(inp.value) + (MODE === "both" ? "" : "") : ""; inp._last = inp.value; };
    const fromBs = (clear) => {
      if (clear === true || !bs.value.trim()) { if (clear === true || MODE === "bs") { inp.value = ""; inp._last = ""; tip.textContent = ""; inp.dispatchEvent(new Event("input", { bubbles: true })); inp.dispatchEvent(new Event("change", { bubbles: true })); } return; }
      const ad = window.bsToAd(bs.value);
      if (!ad) { bs.classList.add("bad"); tip.textContent = "Not a BS date (use 2083-06-11)"; return; }
      bs.classList.remove("bad");
      inp.value = ad; inp._last = ad;
      inp.dispatchEvent(new Event("input", { bubbles: true })); inp.dispatchEvent(new Event("change", { bubbles: true }));
      tip.textContent = bsLabel(ad) + (MODE === "both" ? " = " + ad + " AD" : "");
    };
    bs.addEventListener("change", () => fromBs());
    bs.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fromBs(); closePicker(); } if (e.key === "Escape") closePicker(); });
    bs.addEventListener("blur", () => setTimeout(fromAd, 150));
    bs.addEventListener("focus", () => { if (!bs.disabled && !bs.readOnly) openPicker(bs, (clr) => fromBs(clr)); });
    bs.addEventListener("click", () => { if (!picker && !bs.disabled && !bs.readOnly) openPicker(bs, (clr) => fromBs(clr)); });
    inp.addEventListener("input", fromAd); inp.addEventListener("change", fromAd);
    if (inp.disabled || inp.readOnly) { bs.disabled = true; }
    inp.after(bs, tip);
    inp._sync = fromAd;
    fromAd();
    watched.add(inp);
  };
  const enhanceAll = (root) => { if (!BST) return; const r = root || document; if (r.querySelectorAll) r.querySelectorAll('input[type="date"]').forEach(enhance); if (r.matches && r.matches('input[type="date"]')) enhance(r); };
  setInterval(() => { watched.forEach((inp) => { if (!inp.isConnected) { watched.delete(inp); return; } if (inp.value !== inp._last && inp._sync) inp._sync(); }); }, 700);
  new MutationObserver((ms) => {
    let need = false;
    ms.forEach((m) => {
      if (m.type === "characterData") { convertTree(m.target); return; }
      m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) { if (!BST && (n.matches('input[type="date"]') || n.querySelector('input[type="date"]') || MODE === "bs")) need = true; enhanceAll(n); }
        convertTree(n);
      });
    });
    if (need) loadBS();
    if (!document.querySelector(".date-mode")) addSwitch();
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
  /* the switch in the top bar */
  const addSwitch = () => {
    const top = document.querySelector(".top");
    if (!top || top.querySelector(".date-mode")) return;
    const sel = h("select", { class: "date-mode", title: "Show and enter every date in English (AD) or Nepali (BS)", onchange: (e) => { MODE = e.target.value; try { localStorage.setItem("bco_date_mode", MODE); } catch (x) { /* ignore */ } applyMode(); loadBS(); rerender(); } },
      [["ad", "Dates: English (AD)"], ["bs", "मिति: नेपाली (BS)"], ["both", "Dates: both"]].map(([v, l]) => h("option", { value: v, selected: v === MODE }, l)));
    const grow = top.querySelector(".grow");
    if (grow) grow.after(sel); else top.append(sel);
    loadBS();
  };
  applyMode();
  setTimeout(addSwitch, 500);

  /* ══════════ COMPONENT-WISE BOQ AND MONITORING (hydropower: headworks, headrace, penstock, powerhouse …) ══════════ */
  const cstyle = document.createElement("style");
  cstyle.textContent = ".cbar{display:grid;grid-template-columns:minmax(160px,260px) 1fr 150px;gap:10px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line-soft,#eee);cursor:pointer}" +
    ".cbar .trk{position:relative;height:16px;background:#eef2ef;border-radius:3px}.cbar .pl{position:absolute;top:0;bottom:0;left:0;border-right:2px solid #555;background:rgba(80,80,80,.12)}" +
    ".cbar .ac{position:absolute;top:4px;bottom:4px;left:0;border-radius:2px;background:var(--blue,#1f6fb2)}.cbar .ac.late{background:#b3392c}.cbar small{color:var(--muted,#6b7280)}";
  document.head.append(cstyle);
  let COMPS = { pid: null, rows: [] };
  const loadComps = async (force) => { if (!S.project) return []; if (force || COMPS.pid !== S.project) { const d = await api("comp.list", { project_id: S.project }); COMPS = { pid: S.project, rows: d.rows, unassigned: d.unassigned }; } return COMPS.rows; };
  window.bcoComps = loadComps;
  const compOpts = () => (COMPS.pid === S.project ? COMPS.rows : []).map((x) => [x.id, (x.code ? x.code + " " : "") + x.name]);

  async function compMonitorTab() {
    if (need()) return need();
    const box = h("div");
    const load = async () => {
      const [d, cv] = await Promise.all([api("comp.summary", { project_id: S.project }), api("comp.curve", { project_id: S.project })]);
      box.innerHTML = "";
      if (!d.has_components) {
        box.append(panel(h("b", {}, "No components yet"), hint("Set up the project's components (headworks, headrace, penstock, powerhouse …) in BOQ › Components. BOQ items are then assigned from their WBS or bill number."),
          can("commercial", "edit") ? h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { const r = await run("comp.setup", { project_id: S.project, source: "hydro" }); toast(r.created + " components, " + r.assigned + " BOQ items assigned", "ok"); await loadComps(true); load(); } }, "Set up hydropower components"),
            h("button", { class: "btn", onclick: async () => { const r = await run("comp.setup", { project_id: S.project, source: "wbs" }); toast(r.created + " components, " + r.assigned + " BOQ items assigned", "ok"); await loadComps(true); load(); } }, "One component per WBS element")) : ""));
        return;
      }
      const t = d.totals;
      const behind = d.rows.filter((r) => r.status === "late").length;
      box.append(h("div", { class: "tiles" }, tile("Project progress", t.progress_pct + "%", { sub: "planned " + t.planned_pct + "%", cls: t.progress_pct < t.planned_pct - 5 ? "bad" : "" }),
        tile("Work done", fmtMoney(t.done_value), { sub: "of " + fmtMoney(t.revised_amount) }), tile("Billed / certified", fmtMoney(t.billed_value), { sub: fmtMoney(t.certified_value) + " certified" }),
        tile("SPI / CPI", (t.spi ?? "—") + " / " + (t.cpi ?? "—")), tile("Components behind plan", behind, { cls: behind ? "bad" : "" })),
      h("h2", { class: "sec" }, "Progress by component (bar = done, line = planned today)"),
      panel(...d.rows.filter((r) => r.revised_amount).map((r) => h("div", { class: "cbar", onclick: () => compDrawer(r) }, h("div", {}, h("b", {}, (r.code ? r.code + " " : "") + r.name), h("br"), h("small", {}, "weight " + r.weight_pct + "% · " + r.items + " items")),
        h("div", { class: "trk" }, h("div", { class: "pl", style: "width:" + Math.min(100, r.planned_pct) + "%" }), h("div", { class: "ac" + (r.status === "late" ? " late" : ""), style: "width:" + Math.min(100, r.progress_pct) + "%" })),
        h("div", {}, h("b", { class: r.status === "late" ? "red" : "" }, r.progress_pct + "%"), h("small", {}, " of " + r.planned_pct + "% planned"))))),
      table([{ k: "code", label: "Bill" }, { k: "name", label: "Component" }, { k: "items", label: "Items", fmt: "num" }, { k: "revised_amount", label: "Value (revised)", fmt: "money" }, { k: "weight_pct", label: "Weight %", fmt: "num" },
        { k: "done_value", label: "Work done", fmt: "money" }, { k: "progress_pct", label: "Done %", fmt: "num" }, { k: "planned_pct", label: "Planned %", fmt: "num" },
        { label: "Gap", v: (r) => r.revised_amount ? h("b", { class: r.progress_gap < -5 ? "red" : r.progress_gap >= 0 ? "green" : "" }, (r.progress_gap > 0 ? "+" : "") + r.progress_gap) : "" },
        { k: "billed_value", label: "Billed", fmt: "money" }, { k: "certified_value", label: "Certified", fmt: "money" }, { k: "unbilled_done", label: "Done, not billed", fmt: "money" },
        { k: "ac", label: "Actual cost", fmt: "money" }, { k: "cpi", label: "CPI", fmt: "num" }, { k: "spi", label: "SPI", fmt: "num" }, { k: "forecast_margin_pct", label: "Forecast margin %", fmt: "num" },
        { k: "planned_finish", label: "Planned finish" }, { k: "forecast_finish", label: "Forecast finish" },
        { label: "Issues", v: (r) => (r.open_events || r.open_ncrs) ? h("span", { class: "red" }, [r.open_events ? r.open_events + " events" : "", r.open_ncrs ? r.open_ncrs + " NCR" : ""].filter(Boolean).join(", ")) : "" },
        { label: "Status", v: (r) => r.status ? h("b", { class: r.status === "late" ? "red" : "green" }, r.status) : "" }],
      d.rows, { name: "component_monitoring", onRow: compDrawer, totals: ["revised_amount", "done_value", "billed_value", "certified_value", "unbilled_done", "ac"], rowClass: (r) => r.status === "late" ? "flag" : "" }),
      hint(d.note));
      if (cv.series.length) {
        const sel = h("select", { style: "width:auto" }, cv.series.map((x, i) => h("option", { value: i }, x.name)));
        const chart = h("div");
        const draw = () => { const x = cv.series[Number(sel.value)]; chart.innerHTML = ""; chart.append(lineChart(cv.months, [{ name: "Planned %", color: "#7f8c8d", dash: 1, values: x.planned }, { name: "Actual %", color: "#1f6fb2", values: x.actual }], { max: 100 })); };
        sel.onchange = draw;
        box.append(h("h2", { class: "sec" }, "Progress curve of a component"), h("div", { class: "bar" }, lab("Component", sel)), chart);
        draw();
      }
    };
    const compDrawer = async (r) => {
      const [items, fig] = await Promise.all([api("comp.items", { project_id: S.project }), api("boq.control", { project_id: S.project })]);
      const ids = new Set(items.filter((x) => (x.effective_component_id || null) === (r.id || null)).map((x) => x.id));
      const rows = fig.filter((x) => ids.has(x.id));
      drawer((r.code ? "Bill " + r.code + " · " : "") + r.name, h("div", {}, kv([["Value (revised)", fmtMoney(r.revised_amount)], ["Work done", fmtMoney(r.done_value) + " (" + r.progress_pct + "%, planned " + r.planned_pct + "%)"], ["Billed / certified", fmtMoney(r.billed_value) + " / " + fmtMoney(r.certified_value)],
        ["Actual cost / forecast cost", fmtMoney(r.ac) + " / " + fmtMoney(r.eac)], ["Dates", (r.planned_start || "—") + " → " + (r.planned_finish || "—") + " planned; forecast finish " + (r.forecast_finish || "—")]]),
      table([{ k: "code", label: "Item" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" }, { k: "revised_qty", label: "Qty", fmt: "qty" }, { k: "revised_rate", label: "Rate", fmt: "money" }, { k: "revised_amount", label: "Amount", fmt: "money" },
        { k: "executed_qty", label: "Done", fmt: "qty" }, { label: "%", v: (x) => x.progress_pct + "%" }, { k: "billed_qty", label: "Billed", fmt: "qty" }, { k: "ac", label: "Actual cost", fmt: "money" }, { k: "cpi", label: "CPI", fmt: "num" }],
      rows, { name: "component_items", totals: ["revised_amount", "ac"] })), []);
    };
    await load();
    return box;
  }

  async function compSetupTab() {
    if (need()) return need();
    const box = h("div");
    const editable = can("commercial", "edit");
    const load = async () => {
      await loadComps(true);
      const items = await api("comp.items", { project_id: S.project });
      box.innerHTML = "";
      const wbsOpts2 = () => (S.P.wbs || []).filter((w) => !w.parent_id).map((w) => [w.id, w.code + " " + w.name]);
      const edit = (r) => {
        const f = form([{ k: "code", label: "Bill / component no." }, { k: "name", label: "Component", req: true }, { k: "wbs_id", label: "Linked WBS element (activities, dates)", type: "select", options: wbsOpts2 }, { k: "sort", label: "Order", type: "number" }, { k: "remarks", label: "Remarks", wide: true }], r || { sort: COMPS.rows.length });
        const b = [{ label: "Save", cls: "primary", act: async () => { await run("comp.save", { row: Object.assign(f.values(), { id: r && r.id, project_id: S.project }) }, "Saved"); load(); } }];
        if (r) b.push({ label: "Remove", cls: "warn", act: async () => { await run("comp.delete", { id: r.id }, "Removed; its BOQ items are unassigned"); load(); } });
        modal(r ? "Component " + (r.code || "") + " " + r.name : "New component", f, b, { narrow: true });
      };
      box.append(h("div", { class: "bar" }, h("p", { class: "hint grow" }, "Components (bills) of the contract. Each BOQ item belongs to one; progress, billing and cost are watched by component. Link a component to its top-level WBS element so its activities and dates follow."),
        editable ? h("button", { class: "btn primary", onclick: () => edit(null) }, "New component") : ""),
      editable ? h("div", { class: "bar" }, h("button", { class: "btn", onclick: async () => { const r = await run("comp.setup", { project_id: S.project, source: "hydro" }); toast(r.created + " components added, " + r.assigned + " BOQ items assigned", "ok"); load(); } }, "Add standard hydropower components"),
        h("button", { class: "btn", onclick: async () => { const r = await run("comp.setup", { project_id: S.project, source: "wbs" }); toast(r.created + " components added, " + r.assigned + " BOQ items assigned", "ok"); load(); } }, "One component per top-level WBS element"),
        h("button", { class: "btn", onclick: async () => { const r = await run("comp.assign", { project_id: S.project }); toast(r.assigned + " BOQ items assigned", "ok"); load(); } }, "Assign BOQ items automatically")) : "",
      table([{ k: "code", label: "Bill" }, { k: "name", label: "Component" }, { label: "WBS", v: (r) => r.wbs && r.wbs.code ? r.wbs.code + " " + r.wbs.name : h("span", { class: "muted" }, "not linked") }, { k: "items", label: "BOQ items", fmt: "num" }],
        COMPS.rows, { search: false, name: "components", onRow: editable ? edit : null, empty: "No components yet — use the buttons above." }));
      const changed = {};
      const unassigned = items.filter((x) => !x.effective_component_id).length;
      box.append(h("h2", { class: "sec" }, "BOQ items by component" + (unassigned ? " — " + unassigned + " not assigned" : "")),
        table([{ k: "code", label: "Item" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" }, { k: "amount", label: "Amount", fmt: "money" },
          { label: "Component", v: (x) => editable ? h("select", { style: "min-width:220px", onclick: (e) => e.stopPropagation(), onchange: (e) => { changed[x.id] = e.target.value; } }, h("option", { value: "" }, "— not assigned —"), compOpts().map(([v, l]) => h("option", { value: v, selected: String(v) === String(x.effective_component_id) }, l)))
            : ((COMPS.rows.find((c2) => c2.id === x.effective_component_id) || {}).name || "") }], items, { name: "boq_components", rowClass: (x) => x.effective_component_id ? "" : "flag" }),
        editable ? h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { if (!Object.keys(changed).length) return toast("Nothing changed.", "err"); await run("comp.assign", { project_id: S.project, items: changed }, Object.keys(changed).length + " items saved"); load(); } }, "Save assignments")) : "",
        hint("Importing a BOQ from Excel / CSV: add a column “Component” or “Bill” (e.g. Headworks, Penstock or the bill no.) and the items are filed under it; a new name creates the component."));
    };
    await load();
    return box;
  }

  async function compIpcTab() {
    if (need()) return need();
    const box = h("div");
    let sel = null;
    const load = async () => {
      const d = await api("comp.ipc", { project_id: S.project, ipc_id: sel || undefined });
      box.innerHTML = "";
      if (!d.ipcs.length) { box.append(panel("No IPC yet.")); return; }
      sel = d.ipc_id;
      const s2 = h("select", { style: "width:auto", onchange: (e) => { sel = e.target.value; load(); } }, d.ipcs.map((i) => h("option", { value: i.id, selected: i.id === d.ipc_id }, i.no + " · " + i.date + " · " + i.status)));
      const ipc = d.ipcs.find((i) => i.id === d.ipc_id);
      box.append(h("div", { class: "bar" }, lab("IPC", s2), h("div", { class: "grow" }), h("button", { class: "btn", onclick: () => printDoc("Summary of bills — " + ipc.no, [["Project", nm.project(S.project)], ["IPC", ipc.no], ["Date", ipc.date]],
        [{ k: "code", label: "Bill" }, { k: "name", label: "Component" }, { k: "contract_value", label: "Contract value" }, { k: "previous", label: "Previous" }, { k: "this", label: "This IPC" }, { k: "cumulative", label: "Cumulative" }, { k: "billed_pct", label: "% billed" }],
        d.rows.map((r) => Object.assign({}, r, { contract_value: fmtMoney(r.contract_value), previous: fmtMoney(r.previous), this: fmtMoney(r.this), cumulative: fmtMoney(r.cumulative) })), null, "Amounts before VAT, retention and deductions.") }, "Print summary of bills")),
      table([{ k: "code", label: "Bill" }, { k: "name", label: "Component" }, { k: "contract_value", label: "Contract value", fmt: "money" }, { k: "previous", label: "Up to previous IPC", fmt: "money" }, { k: "this", label: "This IPC", fmt: "money" },
        { k: "cumulative", label: "Cumulative", fmt: "money" }, { k: "billed_pct", label: "% billed", fmt: "num" }], d.rows, { name: "ipc_summary_of_bills", totals: ["contract_value", "previous", "this", "cumulative"] }),
      hint("Gross work amounts by component, before VAT, retention, advance recovery and other deductions."));
    };
    await load();
    return box;
  }

  addTabs("p/boq", "BOQ — commercial master", "Contract, revised, executed, measured, billed and certified quantities with budget and actual unit cost — by item and by component.", "BOQ items", [["By component", compMonitorTab], ["Components", compSetupTab]]);
  addTabs("p/evm", "Cost control & earned value", "", "Earned value", [["By component", compMonitorTab]]);
  addTabs("p/ipc", "Interim payment certificates", "", "IPCs", [["Summary by component", compIpcTab]]);
  addTabs("p/control", "Project control room", "Everything about the selected project on one screen.", "Control room", [["Components", compMonitorTab]]);
  /* the BOQ item form gets a Component field */
  if (typeof MASTERS_UI !== "undefined" && MASTERS_UI.boq_items && !MASTERS_UI.boq_items._comp) {
    const o = MASTERS_UI.boq_items;
    o._comp = true;
    const fld = { k: "component_id", label: "Component / bill", type: "select", options: compOpts };
    if (typeof o.fields === "function") { const f0 = o.fields; o.fields = (r) => f0(r).concat([fld]); } else if (Array.isArray(o.fields)) o.fields.splice(3, 0, fld);
    if (Array.isArray(o.cols)) o.cols.splice(2, 0, { label: "Component", v: (r) => ((COMPS.rows.find((x) => x.id === r.component_id) || {}).name || "") });
    const pg = PAGES["m/boq"];
    if (pg) PAGES["m/boq"] = async (root, params) => { try { await loadComps(true); } catch (e) { /* no project */ } return pg(root, params); };
  }
})();
