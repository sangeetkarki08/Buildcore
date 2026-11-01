/* BuildCore 2.14 — Decision centre, house estimate, workers & safety, and the screens each kind of company needs. */
(function () {
"use strict";

const money = (n) => (n == null || n === "" ? "—" : "Rs " + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 }));
const pct = (n) => (n == null ? "—" : n + "%");
const BAND = { Healthy: "#2f7a4d", Watch: "#b7791f", "At risk": "#c05621", Critical: "#b42318" };
const STAT = { pass: ["✓", "#2f7a4d"], warn: ["!", "#b7791f"], stop: ["✕", "#b42318"] };
const pill = (txt, col) => h("span", { style: "display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff;background:" + col }, txt);
const note = (t) => (t ? h("p", { class: "hint", style: "margin-top:10px" }, t) : null);
const kpis = (pairs) => h("div", { class: "tiles" }, pairs.map(([l, v, sub]) => tile(l, v, sub ? { sub } : {})));

/* simple charts drawn as SVG, no library */
function bars(rows, label, value, o) {
  o = o || {};
  const max = Math.max(1, ...rows.map((r) => Number(r[value]) || 0));
  return h("div", { style: "margin:8px 0" }, rows.map((r) => h("div", { style: "display:flex;align-items:center;gap:8px;margin:3px 0;font-size:13px" },
    h("span", { style: "width:" + (o.lw || 190) + "px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", title: r[label] }, r[label]),
    h("span", { style: "flex:1;background:#eef2f6;border-radius:4px;height:14px;position:relative" },
      h("span", { style: "position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:" + (o.color ? o.color(r) : "#1769aa") + ";width:" + (100 * (Number(r[value]) || 0) / max) + "%" })),
    h("span", { style: "width:110px;text-align:right" }, o.fmt ? o.fmt(r[value], r) : fmtN(r[value])))));
}
function lineChart(rows, x, ys, o) {
  o = o || {};
  const W = 720, H = 220, P = 40;
  const xs = rows.map((r) => r[x]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("style", "width:100%;max-width:760px;background:#fff;border:1px solid var(--line);border-radius:10px");
  const el = (t, a) => { const e = document.createElementNS(ns, t); Object.entries(a).forEach(([k, v]) => e.setAttribute(k, v)); svg.append(e); return e; };
  const sx = (v) => P + (W - 2 * P) * (v - minX) / Math.max(1e-9, maxX - minX);
  ys.forEach(({ k, color, max }) => {
    const mx = max || Math.max(1e-9, ...rows.map((r) => Number(r[k]) || 0));
    const sy = (v) => H - P - (H - 2 * P) * (Number(v) || 0) / mx;
    el("polyline", { points: rows.map((r) => sx(r[x]) + "," + sy(r[k])).join(" "), fill: "none", stroke: color, "stroke-width": 2.5 });
  });
  el("line", { x1: P, y1: H - P, x2: W - P, y2: H - P, stroke: "#98a2b3" });
  [0, 0.25, 0.5, 0.75, 1].forEach((t) => { const v = minX + t * (maxX - minX); const tx = el("text", { x: sx(v), y: H - P + 16, "font-size": 11, "text-anchor": "middle", fill: "#475467" }); tx.textContent = (o.xfmt ? o.xfmt(v) : v.toFixed(1)); });
  if (o.mark != null) { el("line", { x1: sx(o.mark), y1: P - 10, x2: sx(o.mark), y2: H - P, stroke: "#b42318", "stroke-dasharray": "4 3" }); }
  const lg = h("div", { style: "display:flex;gap:14px;font-size:12px;margin-top:4px" }, ys.map((y) => h("span", {}, h("span", { style: "display:inline-block;width:12px;height:3px;background:" + y.color + ";vertical-align:middle;margin-right:4px" }), y.label)));
  return h("div", {}, svg, lg);
}

/* ── Decision centre ── */
PAGES.dc = async (root, params) => {
  root.append(pageHead("Decision centre", "Figures for decisions, from your own records: which jobs are slipping, which clients pay late, whether to bid and at what price, escalation, sub-contractors, and what past projects teach."));
  const names = ["Portfolio radar", "Client payments", "Bid decision", "Bid capacity", "Price adjustment", "Sub-contractors", "Benchmarks", "Company profile"];
  const start = Math.max(0, names.findIndex((n) => n.toLowerCase().startsWith((params.tab || "").toLowerCase())));
  root.append(tabs([
    ["Portfolio radar", radarTab], ["Client payments", paymentsTab], ["Bid decision", bidTab], ["Bid capacity", capacityTab],
    ["Price adjustment", escalationTab], ["Sub-contractors", subconTab], ["Benchmarks", benchTab], ["Company profile", profileTab]], params.tab ? start : 0));
};

async function radarTab() {
  const d = await run("dc.radar", {});
  const box = h("div");
  box.append(kpis([["Critical", d.counts.Critical || 0], ["At risk", d.counts["At risk"] || 0], ["Watch", d.counts.Watch || 0], ["Healthy", d.counts.Healthy || 0]]));
  box.append(table([
    { label: "Project", v: (r) => h("b", {}, r.code) }, { k: "name", label: "Name" },
    { label: "Health", v: (r) => h("span", {}, pill(r.band, BAND[r.band]), " ", r.score) },
    { label: "Time gone", v: (r) => pct(r.time_pct) }, { label: "Work done", v: (r) => pct(r.progress_pct) },
    { label: "SPI", v: (r) => (r.spi == null ? "—" : r.spi) }, { label: "Days since DPR", v: (r) => (r.days_since_dpr ?? "never") },
    { label: "Unpaid certified", v: (r) => money(r.unpaid_certified) }, { label: "Advance to recover", v: (r) => money(r.advance_outstanding) },
    { label: "Why", v: (r) => r.reasons.length ? h("ul", { style: "margin:0;padding-left:16px" }, r.reasons.map((x) => h("li", {}, x))) : "—" }],
  d.rows, { name: "portfolio_radar", title: "Portfolio radar", empty: "No running projects.", onRow: (r) => { if (typeof setProject === "function") { try { setProject(r.id); } catch (e) { /* ignore */ } } location.hash = "#/p/control"; } }));
  box.append(note(d.note));
  return box;
}

async function paymentsTab() {
  const box = h("div");
  let rate = "";
  const load = async () => {
    const d = await run("dc.payments", rate ? { interest_pct: rate } : {});
    box.innerHTML = "";
    const out = d.clients.reduce((a, x) => a + x.outstanding, 0);
    box.append(kpis([["Certified, not paid", money(out)], ["Interest you can claim", money(d.clients.reduce((a, x) => a + x.interest_claimable, 0)), "at " + d.interest_pct + "% a year"],
      ["Clients", d.clients.length]]));
    const ri = h("input", { type: "number", step: "any", value: d.interest_pct, style: "width:90px" });
    box.append(h("div", { class: "bar" }, h("span", {}, "Interest rate on late payment % a year "), ri, h("button", { class: "btn small", onclick: () => { rate = ri.value; load(); } }, "Recalculate")));
    box.append(h("h3", {}, "How each client pays"), table([{ k: "client", label: "Client" }, { label: "Grade", v: (r) => pill(r.grade, { A: "#2f7a4d", B: "#3f8a5d", C: "#b7791f", D: "#c05621", E: "#b42318" }[r.grade]) },
      { k: "ipcs", label: "IPCs", fmt: "num" }, { label: "Days to certify", v: (r) => r.avg_days_to_certify ?? "—" }, { label: "Days to pay", v: (r) => r.avg_days_to_pay ?? "—" },
      { label: "Paid late", v: (r) => pct(r.late_pct) }, { k: "outstanding", label: "Outstanding", fmt: "money" }, { label: "Oldest waiting", v: (r) => (r.oldest_waiting_days ? r.oldest_waiting_days + " days" : "—") },
      { k: "interest_claimable", label: "Interest claimable", fmt: "money" }], d.clients, { name: "client_payments", title: "Client payment behaviour", empty: "No IPC yet." }));
    box.append(h("h3", {}, "Every IPC"), table([{ k: "ipc", label: "IPC" }, { k: "project", label: "Project" }, { k: "client", label: "Client" }, { k: "submitted", label: "Submitted" },
      { k: "certified", label: "Certified" }, { k: "paid", label: "Paid" }, { k: "amount", label: "Amount", fmt: "money" }, { label: "Days to certify", v: (r) => r.days_to_certify ?? "—" },
      { label: "Days to pay", v: (r) => r.days_to_pay ?? "—" }, { label: "Waiting", v: (r) => (r.waiting_days ? r.waiting_days + " days" : "") }, { k: "interest", label: "Interest", fmt: "money" }],
    d.ipcs, { name: "ipc_timeline", title: "IPC timeline", empty: "No IPC yet." }));
    if (S.project && can("commercial", "edit")) {
      box.append(h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
        const r = await run("dc.payments_apply", { project_id: S.project }, (x) => "Cash forecast now uses " + (x.cert_days ?? "—") + " days to certify and " + (x.pay_days ?? "—") + " days to pay");
        return r;
      } }, "Use this client's real days in the cash forecast of " + nm.project(S.project))));
    }
    box.append(note(d.note));
  };
  await load();
  return box;
}

async function bidTab() {
  const box = h("div");
  let bids = [];
  try { bids = await run("bid.list", {}); } catch (e) { bids = []; }
  const f = form([
    { k: "bid_id", label: "From the bid register (optional)", type: "select", options: bids.map((b) => [b.id, b.no + " " + (b.title || "")]) },
    { k: "ee", label: "Engineer's estimate (Rs)", type: "number" }, { k: "our_cost", label: "Your cost (Rs)", type: "number" },
    { k: "client", label: "Client" }, { k: "work_type", label: "Work type" }, { k: "bidders", label: "Expected bidders", type: "number" },
    { k: "years", label: "Years to complete", type: "number" }, { k: "advance_pct", label: "Mobilisation advance %", type: "number" },
    { k: "rule", label: "Award rule", type: "select", noBlank: true, options: [["average", "Closest to the average of the bids (PPA 2083)"], ["lowest", "Lowest bid"]] },
    { k: "floor_pct", label: "Bids below this % of estimate are out", type: "number" }, { k: "min_markup_pct", label: "Lowest markup you accept %", type: "number" }],
  { rule: "average", floor_pct: 70, min_markup_pct: 3, years: 1, advance_pct: 10 }, () => {
    const v = f.values(); const b = bids.find((x) => String(x.id) === String(v.bid_id));
    if (b && !f._filled) { f._filled = b.id; ["ee", "our_cost", "client", "work_type"].forEach((k) => { if (b[k] != null) f.set(k, b[k]); }); }
  });
  const out = h("div");
  box.append(h("div", { class: "panel" }, h("h3", {}, "Should we bid, and at what price?"), f,
    h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const v = f.values();
      out.innerHTML = "";
      const sim = await run("dc.bid_sim", v);
      const chk = await run("dc.bid_check", Object.assign({}, v, { bid_value: (sim.best || {}).price || v.ee }));
      out.append(h("div", { class: "panel" }, h("h3", {}, "Go / no-go: ", pill(chk.verdict, chk.verdict === "Go" ? "#2f7a4d" : chk.verdict === "No-go" ? "#b42318" : "#b7791f")),
        h("ul", { style: "list-style:none;padding:0" }, chk.items.map((x) => h("li", { style: "margin:6px 0" }, h("b", { style: "color:" + STAT[x.status][1] + ";margin-right:6px" }, STAT[x.status][0]), h("b", {}, x.check + ": "), x.detail)))));
      const best = sim.best, like = sim.most_likely_win;
      out.append(kpis([["Your cost", sim.cost_pct_ee + "% of estimate", money(sim.cost)],
        ["Best price (most expected profit)", best ? best.pct_ee + "% of estimate" : "—", best ? money(best.price) + " · win " + best.win_prob + "% · markup " + best.markup_pct + "%" : "no price meets your markup"],
        ["Highest chance to win", like ? like.pct_ee + "% of estimate" : "—", like ? "win " + like.win_prob + "% · markup " + like.markup_pct + "%" : ""],
        ["Competitor bids used", sim.history.samples || "none", sim.history.basis + " · avg " + (sim.history.mean * 100).toFixed(1) + "% of estimate"]]));
      out.append(h("h3", {}, "Chance of winning and expected profit at each price"),
        lineChart(sim.rows, "pct_ee", [{ k: "win_prob", label: "Chance to win (%)", color: "#1769aa", max: 100 }, { k: "expected_profit", label: "Expected profit", color: "#2f7a4d" }],
          { xfmt: (v) => v.toFixed(0) + "%", mark: best ? best.pct_ee : null }));
      out.append(table([{ label: "% of estimate", v: (r) => r.pct_ee + "%" }, { k: "price", label: "Bid price", fmt: "money" }, { label: "Markup on cost", v: (r) => r.markup_pct + "%" },
        { label: "Chance to win", v: (r) => r.win_prob + "%" }, { k: "expected_profit", label: "Expected profit", fmt: "money" }], sim.rows,
      { name: "bid_prices", title: "Bid price simulation", rowClass: (r) => (best && r.pct_ee === best.pct_ee ? "flag" : "") }));
      out.append(note(sim.note + (sim.history.assumed ? " With no history, competitors are assumed to bid " + (sim.history.mean * 100).toFixed(0) + "% ± " + (sim.history.sd * 100).toFixed(0) + "% of the estimate — enter past tenders in Commercial › Bids & markup to make this yours." : "")));
    } }, "Work it out")), out));
  return box;
}

async function capacityTab() {
  const box = h("div");
  const f = form([{ k: "bid_value", label: "Bid amount to check (Rs)", type: "number" }, { k: "years", label: "Years to complete (N)", type: "number" }, { k: "m", label: "M", type: "number" }], { years: 1 });
  const out = h("div");
  const show = async () => {
    const d = await run("dc.capacity", f.values());
    out.innerHTML = "";
    out.append(kpis([["Bid capacity", money(d.capacity), d.bid_value ? (d.ok ? "enough for this bid" : "NOT enough for this bid") : ""], ["A (best year, today's prices)", money(d.A)],
      ["N × M", d.N + " × " + d.M], ["B (work in hand)", money(d.B)], ["Licence class", d.licence_class || "not set", d.class_limit ? "up to " + money(d.class_limit) : ""]]));
    out.append(h("div", { class: "cols" }, h("div", {}, h("h3", {}, "Turnover by fiscal year"), table([{ k: "fy", label: "Year" }, { k: "turnover", label: "Turnover", fmt: "money" }, { k: "updated", label: "At today's prices", fmt: "money" }], d.turnover, { search: false, export: false, empty: "No sales invoices yet — enter past turnover in Company profile." })),
      h("div", {}, h("h3", {}, "Work in hand (B)"), table([{ k: "project", label: "Contract" }, { k: "contract_value", label: "Value", fmt: "money" }, { k: "remaining", label: "Still to do", fmt: "money" }], d.commitments, { search: false, export: false, totals: ["remaining"] }))));
    out.append(note(d.formula));
  };
  box.append(h("div", { class: "panel" }, f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: show }, "Work it out"))), out);
  await show();
  return box;
}

async function escalationTab() {
  const box = h("div");
  if (!S.project) { box.append(h("p", {}, "Choose a project at the top first.")); return box; }
  const draw = async () => {
    box.innerHTML = "";
    const [fm, idx] = await Promise.all([run("dc.pa_get", { project_id: S.project }), run("dc.idx_list", {})]);
    const rowsBox = h("tbody");
    const addRow = (x) => { const c = h("input", { value: x.code || "", style: "width:110px" }); const w = h("input", { type: "number", step: "any", value: x.weight ?? "", style: "width:90px" });
      const tr = h("tr", {}, h("td", {}, c), h("td", {}, w), h("td", {}, h("button", { class: "btn small", onclick: () => tr.remove() }, "✕"))); tr._v = () => ({ code: c.value, weight: w.value }); rowsBox.append(tr); };
    (fm.coeffs.length ? fm.coeffs : [{ code: "L", weight: 0.30 }, { code: "M", weight: 0.35 }, { code: "F", weight: 0.10 }, { code: "E", weight: 0.10 }]).forEach(addRow);
    const ff = form([{ k: "base_period", label: "Base month (index month before the bid), YYYY-MM" }, { k: "fixed_a", label: "Fixed part a (not adjusted)", type: "number" }, { k: "start_after_months", label: "Applies after months from start", type: "number" }, { k: "remarks", label: "Contract clause / remarks" }], fm);
    box.append(h("div", { class: "panel" }, h("h3", {}, "Price adjustment formula of " + nm.project(S.project)), h("p", { class: "hint" }, "Pn = a + Σ (weight × index now ÷ base index). a + weights must add up to 1.00. Use the index codes you enter below (e.g. L labour, M materials, F fuel, E equipment, CEM cement, STL steel)."),
      ff, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Index code"), h("th", {}, "Weight"), h("th"))), rowsBox),
      h("button", { class: "btn small", onclick: () => addRow({}) }, "+ index"),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("dc.pa_save", { row: Object.assign(ff.values(), { project_id: S.project, coeffs: [...rowsBox.children].map((t) => t._v()) }) }, "Formula saved"); draw(); } }, "Save formula"))));
    const it = h("textarea", { rows: 5, placeholder: "code\tmonth (YYYY-MM)\tvalue\tsource\nL\t2083-01\t112.4\tNRB\nM\t2083-01\t131.0\tNSO" });
    box.append(h("div", { class: "panel" }, h("h3", {}, "Price indices"), table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "period", label: "Month" }, { k: "value", label: "Index", fmt: "num" }, { k: "source", label: "Source" }], idx, { name: "pa_indices", title: "Price indices", empty: "No index entered yet." }),
      h("p", { class: "hint" }, "Paste rows from Excel: code, month (YYYY-MM), index value, source. A month already entered is replaced."), it,
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
        const rows = it.value.split(/\r?\n/).map((l) => l.split("\t")).filter((c) => c[0] && c[0].toLowerCase() !== "code").map((c) => ({ code: c[0], period: c[1], value: c[2], source: c[3] }));
        await run("dc.idx_save", { rows }, (x) => x.saved + " index values saved"); draw(); } }, "Save indices"))));
    if (fm.coeffs.length && fm.base_period) {
      try {
        const r = await run("dc.pa_calc", { project_id: S.project });
        box.append(h("div", { class: "panel" }, h("h3", {}, "Price adjustment by IPC — total ", money(r.total)),
          table([{ k: "ipc", label: "IPC" }, { k: "month", label: "Month" }, { k: "work_value", label: "Work value", fmt: "money" }, { label: "Factor Pn", v: (x) => x.factor ?? "missing " + x.missing.join(", ") },
            { k: "adjustment", label: "Adjustment", fmt: "money" }, { k: "indices", label: "Indices used" }], r.rows, { name: "price_adjustment", title: "Price adjustment", totals: ["adjustment"] }),
          note(r.note), can("commercial", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { await run("dc.pa_claim", { project_id: S.project }, (x) => "Claim " + x.no + " raised for " + money(x.amount)); } }, "Raise a claim in Events & claims")) : null));
      } catch (e) { /* shown by run */ }
    }
  };
  await draw();
  return box;
}

async function subconTab() {
  const d = await run("dc.subcons", {});
  const box = h("div");
  box.append(table([{ k: "name", label: "Sub-contractor" }, { label: "Score", v: (r) => pill(r.score, r.score >= 75 ? "#2f7a4d" : r.score >= 50 ? "#b7791f" : "#b42318") },
    { k: "man_days", label: "Man-days", fmt: "num" }, { k: "days_on_site", label: "Days on site", fmt: "num" }, { k: "last_on_site", label: "Last on site" },
    { k: "billed", label: "Billed", fmt: "money" }, { k: "paid", label: "Paid", fmt: "money" }, { k: "outstanding", label: "Outstanding", fmt: "money" },
    { k: "incidents", label: "Incidents", fmt: "num" }, { label: "LTIFR", v: (r) => r.ltifr ?? "—" }, { k: "workers", label: "Workers", fmt: "num" },
    { label: "SSF", v: (r) => pct(r.ssf_pct) }, { label: "Bank", v: (r) => pct(r.bank_pct) }, { label: "Insured", v: (r) => pct(r.insured_pct) }],
  d.rows, { name: "subcontractors", title: "Sub-contractor scorecard", empty: "No sub-contractor yet. Book DPR labour against the sub-contractor (party) to see them here." }));
  box.append(note(d.note));
  return box;
}

async function benchTab() {
  const d = await run("dc.bench", {});
  const box = h("div");
  box.append(h("h3", {}, "What stops work — delay causes across all projects (last 2 years)"));
  box.append(d.delay_causes.length ? bars(d.delay_causes, "cause", "hours", { fmt: (v, r) => fmtN(v, 0) + " h · " + r.share_pct + "%" }) : h("p", { class: "muted" }, "No delays recorded in DPRs yet."));
  if (d.delay_causes.length) {
    const top = d.delay_causes.filter((x) => x.cumulative_pct <= 80 || x === d.delay_causes[0]).map((x) => x.cause);
    box.append(h("p", { class: "hint" }, "About 80% of the lost hours come from: " + top.join(", ") + ". Fixing these first gives the most time back."));
  }
  if (d.weather.length) box.append(h("h3", {}, "Weather by month (all projects)"), bars(d.weather.map((w) => Object.assign({ m: "Month " + w.month }, w)), "m", "lost_hours", { fmt: (v, r) => fmtN(v, 0) + " h lost · " + (r.lost_days || 0) + " days", color: () => "#4a7fb5", lw: 90 }));
  box.append(h("h3", {}, "Productivity against the standard"), table([{ k: "project", label: "Project" }, { k: "activity", label: "Activity" }, { k: "qty", label: "Done", fmt: "qty" }, { k: "unit", label: "Unit" },
    { k: "man_hours", label: "Man-hours", fmt: "num" }, { k: "output_per_mh", label: "Output / man-hour", fmt: "num" }, { label: "Standard", v: (r) => r.standard ?? "—" },
    { label: "Against standard", v: (r) => (r.vs_standard_pct == null ? "—" : h("b", { style: "color:" + (r.vs_standard_pct < -10 ? "#b42318" : r.vs_standard_pct > 10 ? "#2f7a4d" : "inherit") }, (r.vs_standard_pct > 0 ? "+" : "") + r.vs_standard_pct + "%")) }],
  d.productivity, { name: "productivity", title: "Productivity", empty: "Needs DPR work quantities and labour hours booked to activities." }));
  const areaBox = h("div");
  box.append(h("h3", {}, "Building cost per sq ft (your own jobs)"), table([{ k: "project", label: "Project" }, { k: "name", label: "Name" }, { k: "status", label: "Status" }, { k: "area_sqft", label: "Built-up sq ft", fmt: "num" },
    { k: "cost", label: "Cost so far", fmt: "money" }, { k: "cost_per_sqft", label: "Cost / sq ft", fmt: "money" }], d.cost_per_sqft, { name: "cost_per_sqft", title: "Cost per sq ft", empty: "Give a building project its built-up area below to start this benchmark." }), areaBox);
  if (can("commercial", "edit")) {
    const af = form([{ k: "project_id", label: "Project", type: "select", noBlank: true, options: S.L.projects.map((p) => [p.id, p.code + " — " + p.name]) }, { k: "area_sqft", label: "Built-up area (sq ft)", type: "number" }], { project_id: S.project });
    areaBox.append(af, h("button", { class: "btn small", onclick: async () => { await run("dc.set_area", af.values(), "Saved"); } }, "Save area"));
  }
  return box;
}

async function profileTab() {
  const d = await run("dc.profile_get", {});
  const p = d.profile;
  const box = h("div");
  const f = form([{ k: "kind", label: "What kind of company are you?", type: "select", options: d.profiles.map((x) => [x.key, x.label]) },
    { k: "licence_class", label: "Contractor licence class", type: "select", options: [["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"]] },
    { k: "bid_m", label: "Bid capacity M (from the bid document)", type: "number" }, { k: "bid_years_back", label: "Years of turnover to look back (A)", type: "number" },
    { k: "turnover_escalation_pct", label: "Bring past turnover to today's prices, % a year", type: "number" }, { k: "other_commitments", label: "Other work in hand not in BuildCore (Rs)", type: "number" },
    { k: "late_interest_pct", label: "Interest on late client payment, % a year", type: "number" }], p);
  const tv = h("textarea", { rows: 4, placeholder: "2079-80\t125000000\n2080-81\t180000000" });
  tv.value = Object.entries(p.turnover_manual || {}).map(([k, v]) => k + "\t" + v).join("\n");
  const lim = h("textarea", { rows: 2 }); lim.value = JSON.stringify(p.class_limits);
  box.append(h("div", { class: "panel" }, h("h3", {}, "Company profile"), h("p", { class: "hint" }, "The kind of company decides which screens the menus show (the rest stay one click away with “Show all screens”), and feeds bid capacity and the licence check."), f,
    h("h3", {}, "Turnover of years before BuildCore (fiscal year, amount)"), tv,
    h("h3", {}, "Licence class limits (Rs; null = no limit) — check against the current Construction Business rules"), lim,
    can("admin", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const v = f.values();
      const tm = {}; tv.value.split(/\r?\n/).forEach((l) => { const c = l.split(/\t|,|\s{2,}/); if (c[0] && c[1]) tm[c[0].trim()] = Number(String(c[1]).replace(/,/g, "")); });
      let cl = p.class_limits; try { cl = JSON.parse(lim.value); } catch (e) { return toast("Class limits are not valid.", "err"); }
      const r = await run("dc.profile_save", { profile: Object.assign(v, { turnover_manual: tm, class_limits: cl }) }, "Profile saved");
      window.bcoApplyFocus && window.bcoApplyFocus(r.profile.kind, true);
    } }, "Save profile")) : h("p", { class: "hint" }, "Only an administrator can change the profile.")));
  return box;
}

/* ── House & small job estimate ── */
PAGES["dc/house"] = async (root) => {
  root.append(pageHead("House & small job estimate", "A first estimate in a minute: area, storeys and quality, priced from your rate book, with a stage payment plan. Turn it into a project to bill by stage and to measure the real cost per sq ft."));
  let books = [];
  try { books = (await run("respool.meta", {})).books || []; } catch (e) { books = []; }
  const f = form([{ k: "client", label: "Client" }, { k: "location", label: "Location" }, { k: "plinth_sqft", label: "Floor area per storey (sq ft)", type: "number", req: true },
    { k: "floors", label: "Storeys", type: "number" }, { k: "quality", label: "Quality", type: "select", noBlank: true, options: [["basic", "Basic"], ["standard", "Standard"], ["premium", "Premium"]] },
    { k: "book_id", label: "Rate book", type: "select", options: books.map((b) => [b.id, b.name + (b.is_default ? " (default)" : "")]) },
    { k: "contingency_pct", label: "Contingency %", type: "number" }, { k: "labour_pct", label: "Labour share % (blank = default)", type: "number" },
    { k: "finish_pct", label: "Finishing share %", type: "number" }, { k: "services_pct", label: "Services share %", type: "number" }], { floors: 2, quality: "standard", contingency_pct: 5 });
  const out = h("div");
  const listBox = h("div");
  const show = (r) => {
    out.innerHTML = "";
    out.append(kpis([["Estimate", money(r.total_with_contingency)], ["Per sq ft", money(r.per_sqft), r.inputs.built_sqft + " sq ft built-up"], ["Materials (structure)", money(r.materials)],
      ["Your own houses", r.own_benchmark_per_sqft ? money(r.own_benchmark_per_sqft) + " / sq ft" : "—", r.own_jobs ? r.own_jobs + " job(s)" : "no finished job with area yet"]]));
    out.append(h("div", { class: "cols" }, h("div", {}, h("h3", {}, "Cost build-up"), table([{ k: "item", label: "Item" }, { label: "Qty", v: (x) => (x.qty == null ? "" : fmtN(x.qty, 1) + " " + x.unit) }, { label: "Rate", v: (x) => (x.rate == null ? (x.qty == null ? x.unit : "no rate") : money(x.rate)) },
      { k: "amount", label: "Amount", fmt: "money" }, { k: "source", label: "Source" }], r.lines, { search: false, name: "house_estimate", title: "House estimate", totals: ["amount"] })),
    h("div", {}, h("h3", {}, "Stage payments for the client"), table([{ k: "stage", label: "Stage" }, { label: "%", v: (x) => x.pct + "%" }, { k: "amount", label: "Amount", fmt: "money" }], r.stages, { search: false, name: "stage_payments", title: "Stage payments", totals: ["amount"] }))));
    out.append(note(r.note));
  };
  const listLoad = async () => {
    const rows = await run("dc.house_list", {});
    listBox.innerHTML = "";
    listBox.append(h("h3", {}, "Saved estimates"), table([{ k: "no", label: "No." }, { k: "client", label: "Client" }, { k: "location", label: "Location" }, { k: "total", label: "Total", fmt: "money" }, { k: "per_sqft", label: "Per sq ft", fmt: "money" },
      { label: "Project", v: (r) => (r.project_id ? nm.pcode(r.project_id) : can("commercial", "edit") ? h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); toProject(r); } }, "Make it a project") : "") }, { label: "When", v: (r) => (r.ts || "").slice(0, 10) }],
    rows, { name: "house_estimates", empty: "No saved estimate yet.", onRow: async (r) => { const g = await run("dc.house_get", { id: r.id }); show(g.result); } }));
  };
  const toProject = (r) => {
    const pf = form([{ k: "code", label: "Project code", req: true }, { k: "name", label: "Project name" }, { k: "start_date", label: "Start", type: "date" }, { k: "end_date", label: "Finish", type: "date" }], { name: "House - " + (r.client || "") });
    modal("Make " + r.no + " a project", pf, [{ label: "Create project", cls: "primary", act: async () => { const x = await run("dc.house_to_project", Object.assign(pf.values(), { id: r.id }), (y) => "Project " + y.code + " created with one BOQ line per stage"); try { await reloadLookups(); } catch (e) { /* ignore */ } listLoad(); return x; } }], { narrow: true });
  };
  root.append(h("div", { class: "panel" }, f, h("div", { class: "actions" },
    h("button", { class: "btn primary", onclick: async () => show(await run("dc.house_estimate", f.values())) }, "Estimate"),
    can("commercial", "edit") ? h("button", { class: "btn", onclick: async () => { const r = await run("dc.house_estimate", Object.assign(f.values(), { save: 1 }), (x) => "Saved as " + x.no); show(r); listLoad(); } }, "Estimate and save") : null)), out, listBox);
  await listLoad();
};

/* ── Workers & safety ── */
PAGES.hs = async (root, params) => {
  const meta = await run("hs.meta", {});
  root.append(pageHead("Workers & safety", "Who is on site (SSF, bank account, accident insurance), every incident and near miss, and the safety figures from DPR man-hours."));
  root.append(tabs([["Safety figures", () => hsStats(meta)], ["Incidents", () => hsIncidents(meta)], ["Workers", () => hsWorkers(meta)]], params.tab === "workers" ? 2 : params.tab === "incidents" ? 1 : 0));
};

async function hsStats() {
  const d = await run("hs.stats", S.project ? { project_id: S.project } : {});
  const box = h("div");
  box.append(kpis([["Man-hours (12 months)", fmtN(d.total.man_hours, 0)], ["Lost-time injuries", d.total.lti], ["LTIFR", d.total.ltifr ?? "—", "per million man-hours"], ["Incidents recorded", d.total.incidents]]));
  box.append(table([{ k: "project", label: "Project" }, { k: "man_hours", label: "Man-hours", fmt: "num" }, { k: "near_miss", label: "Near miss", fmt: "num" }, { k: "first_aid", label: "First aid", fmt: "num" },
    { k: "recordable", label: "Recordable", fmt: "num" }, { k: "lti", label: "LTI", fmt: "num" }, { k: "fatalities", label: "Fatal", fmt: "num" }, { label: "LTIFR", v: (r) => r.ltifr ?? "—" }, { label: "TRIR", v: (r) => r.trir ?? "—" },
    { label: "Days since LTI", v: (r) => r.days_since_lti ?? "none" }, { k: "workers", label: "Workers", fmt: "num" }, { label: "SSF", v: (r) => pct(r.ssf_pct) }, { label: "Bank", v: (r) => pct(r.bank_pct) }, { label: "Insured", v: (r) => pct(r.insured_pct) }],
  d.rows, { name: "safety_stats", title: "Safety figures" }));
  if (d.causes.length) box.append(h("h3", {}, "Causes"), bars(d.causes, "cause", "n", { fmt: (v, r) => v + " (" + r.serious + " serious)", color: (r) => (r.serious ? "#b42318" : "#b7791f") }));
  box.append(h("h3", {}, "Open actions"), table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "project", label: "Project" }, { k: "kind", label: "Kind" }, { k: "corrective_action", label: "Action" }, { k: "action_owner", label: "Owner" }, { k: "action_due", label: "Due" }], d.open, { search: false, empty: "No open action." }));
  box.append(note(d.note));
  return box;
}

function incidentForm(meta, r, done) {
  const f = form([{ k: "project_id", label: "Project", type: "select", noBlank: true, options: S.L.projects.map((p) => [p.id, p.code + " — " + p.name]), req: true },
    { k: "date", label: "Date", type: "date", req: true }, { k: "time", label: "Time" }, { k: "kind", label: "Kind", type: "select", noBlank: true, options: meta.kinds },
    { k: "person", label: "Person involved" }, { k: "party_id", label: "Sub-contractor", type: "select", options: meta.parties.map((p) => [p.id, p.name]) },
    { k: "location", label: "Location / chainage" }, { k: "cause", label: "Cause", type: "select", options: meta.causes.map((x) => [x, x]) },
    { k: "injury", label: "Injury" }, { k: "days_lost", label: "Days lost", type: "number" }, { k: "description", label: "What happened", wide: true },
    { k: "immediate_action", label: "Immediate action", wide: true }, { k: "corrective_action", label: "Action so it does not happen again", wide: true },
    { k: "action_owner", label: "Action owner" }, { k: "action_due", label: "Action due", type: "date" }, { k: "insurance_claim", label: "Insurance claim no. / status" },
    { k: "reported_labour_office", label: "Reported to the labour office", type: "check" }, { k: "cost", label: "Cost (Rs)", type: "number" },
    { k: "status", label: "Status", type: "select", noBlank: true, options: [["open", "Open"], ["closed", "Closed"]] }], r || { project_id: S.project, date: today(), kind: "near_miss", status: "open" });
  modal(r ? "Incident " + r.no : "Record an incident", f, [{ label: "Save", cls: "primary", act: async () => { await run("hs.incident_save", { row: Object.assign(f.values(), { id: r && r.id }) }, "Saved"); done(); } }]);
}
async function hsIncidents(meta) {
  const box = h("div");
  const load = async () => {
    const rows = await run("hs.incidents", S.project ? { project_id: S.project } : {});
    box.innerHTML = "";
    box.append(h("div", { class: "actions" }, can("project", "edit") ? h("button", { class: "btn primary", onclick: () => incidentForm(meta, null, load) }, "Record an incident or near miss") : null));
    const kn = Object.fromEntries(meta.kinds);
    box.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "project", label: "Project" }, { label: "Kind", v: (r) => pill(kn[r.kind] || r.kind, ["lti", "fatality"].includes(r.kind) ? "#b42318" : r.kind === "near_miss" ? "#4a7fb5" : "#b7791f") },
      { k: "person", label: "Person" }, { k: "party", label: "Sub-contractor" }, { k: "cause", label: "Cause" }, { k: "days_lost", label: "Days lost", fmt: "num" }, { k: "status", label: "Status" }],
    rows, { name: "incidents", title: "Incidents", empty: "No incident recorded.", onRow: (r) => incidentForm(meta, r, load) }));
  };
  await load();
  return box;
}

function workerForm(meta, r, done) {
  const f = form([{ k: "name", label: "Name", req: true }, { k: "code", label: "Code" }, { k: "trade", label: "Trade" },
    { k: "party_id", label: "Sub-contractor (blank = own worker)", type: "select", options: meta.parties.map((p) => [p.id, p.name]) },
    { k: "project_id", label: "Project", type: "select", options: S.L.projects.map((p) => [p.id, p.code]) }, { k: "phone", label: "Phone" },
    { k: "ssf_no", label: "SSF number" }, { k: "bank_name", label: "Bank" }, { k: "bank_acno", label: "Bank account no." },
    { k: "insurance_policy", label: "Accident insurance policy" }, { k: "insurance_sum", label: "Insured sum (Rs)", type: "number" }, { k: "insurance_expiry", label: "Insurance expiry", type: "date" },
    { k: "skill_cert", label: "Skill certificate (NSTB level)" }, { k: "daily_wage", label: "Daily wage", type: "number" }, { k: "joined", label: "Joined", type: "date" },
    { k: "emergency_contact", label: "Emergency contact" }, { k: "active", label: "Active", type: "check" }], r || { project_id: S.project, active: 1 });
  modal(r ? r.name : "Add a worker", f, [{ label: "Save", cls: "primary", act: async () => { await run("hs.worker_save", { row: Object.assign(f.values(), { id: r && r.id }) }, "Saved"); done(); } }]);
}
async function hsWorkers(meta) {
  const box = h("div");
  const load = async () => {
    const rows = await run("hs.workers", S.project ? { project_id: S.project } : {});
    box.innerHTML = "";
    const n = rows.length || 1;
    box.append(kpis([["Workers", rows.length], ["With SSF number", pct(Math.round(100 * rows.filter((r) => r.ssf_no).length / n))], ["Bank account", pct(Math.round(100 * rows.filter((r) => r.bank_acno).length / n))],
      ["Insured now", pct(Math.round(100 * rows.filter((r) => !r.gaps.includes("insurance")).length / n))]]));
    const pt = h("textarea", { rows: 3, placeholder: "name\ttrade\tsub-contractor code\tphone\tSSF no\tbank\taccount no\tinsurance expiry" });
    if (can("project", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => workerForm(meta, null, load) }, "Add a worker"),
      h("details", {}, h("summary", {}, "Paste many from Excel"), pt, h("button", { class: "btn small", onclick: async () => { await run("hs.workers_paste", { text: pt.value, project_id: S.project }, (x) => x.added + " workers added"); load(); } }, "Add them"))));
    box.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { k: "trade", label: "Trade" }, { k: "party", label: "Sub-contractor" }, { k: "phone", label: "Phone" },
      { k: "ssf_no", label: "SSF" }, { k: "insurance_expiry", label: "Insured until" }, { label: "Missing", v: (r) => (r.gaps.length ? h("b", { class: "red" }, r.gaps.join(", ")) : "—") }],
    rows, { name: "workers", title: "Workers", empty: "No worker registered.", rowClass: (r) => (r.gaps.length ? "flag" : ""), onRow: (r) => workerForm(meta, r, load) }));
    box.append(note("Labour Act 2074 s.55: accident insurance of at least Rs 7 lakh per worker. Public Procurement Act 2083 amendment: workers on public works in the Social Security Fund and paid through banks."));
  };
  await load();
  return box;
}

/* ── the screens each kind of company needs: menu focus by company profile ── */
const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
let FULL = null;
let PROFILES = null;
function ensureItems() {
  if (typeof MENU === "undefined") return;
  const add = (group, after, item) => {
    const g = MENU.find((x) => x[0] === group); if (!g || g[2].some((y) => y[0] === item[0])) return;
    const i = g[2].findIndex((y) => y[0] === after); g[2].splice(i >= 0 ? i + 1 : g[2].length, 0, item);
  };
  add("Overview", "copilot", ["dc", "Decision centre", "commercial"]);
  add("Overview", "dc", ["dc/house", "House & small job estimate", "commercial"]);
  add("Work", "p/events", ["hs", "Workers & safety"]);
}
window.bcoApplyFocus = function (kind, rerender) {
  if (typeof MENU === "undefined") return;
  ensureItems();
  if (!FULL) FULL = JSON.parse(JSON.stringify(MENU));
  if (kind != null) LSs("bco_profile_kind", kind || "");
  kind = LSg("bco_profile_kind", "");
  const all = LSg("bco_show_all", "0") === "1";
  const pr = (PROFILES || []).find((x) => x.key === kind) || JSON.parse(LSg("bco_profile_def", "null") || "null");
  MENU.length = 0;
  JSON.parse(JSON.stringify(FULL)).forEach((g) => {
    if (!all && pr && pr.hide_groups.includes(g[0])) return;
    if (!all && pr) g[2] = g[2].filter((it) => !pr.hide_items.includes(it[0]));
    MENU.push(g);
  });
  if (rerender) {
    try { window.dispatchEvent(new HashChangeEvent("hashchange")); } catch (e) { /* ignore */ }
    try { if (typeof go === "function") go(); } catch (e) { /* ignore */ }
  }
};
(window.bcoBootHooks = window.bcoBootHooks || []).push(() => { try { window.bcoApplyFocus(null, false); } catch (e) { /* ignore */ } });
let fetched = false;
setInterval(async () => {
  if (fetched || typeof S === "undefined" || !S.token || !S.user) return;
  fetched = true;
  try {
    const d = await api("dc.profile_get", {});
    PROFILES = d.profiles;
    const pr = d.profiles.find((x) => x.key === d.profile.kind);
    LSs("bco_profile_def", JSON.stringify(pr || null));
    const before = LSg("bco_profile_kind", "");
    window.bcoApplyFocus(d.profile.kind || "", before !== (d.profile.kind || ""));
    addToggle();
  } catch (e) { fetched = false; }
}, 1000);
function addToggle() {
  if (document.getElementById("bco-showall")) return;
  const kind = LSg("bco_profile_kind", "");
  if (!kind || kind === "large" || kind === "medium") return;
  const all = LSg("bco_show_all", "0") === "1";
  const b = h("button", { id: "bco-showall", class: "btn small", style: "position:fixed;left:12px;bottom:12px;z-index:50;opacity:.85",
    title: "The menus show the screens for your kind of company (Decision centre › Company profile)",
    onclick: () => { LSs("bco_show_all", all ? "0" : "1"); location.reload(); } }, all ? "Show my screens only" : "Show all screens");
  document.body.append(b);
}

})();
