/* BuildCore 2.29 — financial command centre, alerts, financing options and the report builder.
   New tabs only; the menu, module names and groups are unchanged:
     Overview › Command centre ............... Financial command centre · Report builder
     Overview › Action centre ................ Financial alerts · My financial view
     Accounts › Cash forecast & ratios ....... Funding gap & financing
   Everything shown is worked out by the engine, which also decides what each person may see. Nothing here posts. */
(function () {
  "use strict";
  if (window.__bcoFcc) return;
  window.__bcoFcc = true;

  document.head.append(h("style", {}, ".fc-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:0 0 12px}" +
    ".fc-card{border:1px solid #dde3ea;border-radius:8px;padding:8px 10px;background:#fff;cursor:default}.fc-card[data-go]{cursor:pointer}.fc-card[data-go]:hover{border-color:#1f6fb2}" +
    ".fc-card b{display:block;font-size:15px;margin-top:2px}.fc-card small{color:#667}.fc-card.bad{border-color:#f2b8b5;background:#fdf3f2}" +
    ".fc-card.warn{border-color:#f0d9a8;background:#fff9ec}.fc-card.ok{border-color:#b7dfc3;background:#f1f9f3}.fc-card.est{background:#f7f9fb;border-style:dashed}" +
    ".fc-sec{margin:0 0 18px}.fc-sec>h2{display:flex;align-items:center;gap:8px;font-size:16px;margin:0 0 8px}.fc-sec>h2 a{font-size:12px;font-weight:400}" +
    ".fc-note{padding:8px 12px;border-radius:6px;margin:0 0 8px;background:#fff7e6;border:1px solid #f0d9a8}.fc-note.ok{background:#eaf6ee;border-color:#b7dfc3}" +
    ".fc-note.bad{background:#fdecea;border-color:#f2b8b5}.fc-sev{display:inline-block;font-size:10px;padding:1px 7px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px}" +
    ".fc-sev.high{background:#fde2e1;color:#a01d16}.fc-sev.medium{background:#fff1d6;color:#8a5300}.fc-sev.low{background:#e8f0f7;color:#24557d}" +
    ".fc-bar{display:flex;gap:8px;align-items:end;flex-wrap:wrap;margin-bottom:10px}.fc-bar label{display:flex;flex-direction:column;font-size:12px;color:#556}" +
    ".fc-log{border-left:2px solid #dde3ea;margin:6px 0;padding:0 0 0 10px;font-size:13px}.fc-log div{margin:0 0 6px}.fc-log small{color:#667}" +
    ".fc-src a{margin-right:10px}.fc-grid2{display:grid;grid-template-columns:280px 1fr;gap:14px}@media(max-width:900px){.fc-grid2{grid-template-columns:1fr}}" +
    ".fc-list button{display:block;width:100%;text-align:left;border:1px solid #e3e8ee;background:#fff;border-radius:6px;padding:6px 8px;margin:0 0 4px;cursor:pointer}" +
    ".fc-list button.on{border-color:#1f6fb2;background:#eef5fb}.fc-list small{color:#667;display:block}.fc-cols{columns:2;font-size:13px}.fc-cols label{display:block;break-inside:avoid}" +
    ".fc-rep td.n{text-align:right}.fc-rep tr.g td{font-weight:600;background:#f3f6f9}.fc-rep tr.st td{font-weight:600;border-top:1px solid #ccd}.fc-rep tr.tt td{font-weight:700;border-top:2px solid #99a}" +
    ".fc-chart{width:100%;max-width:900px;height:auto}.fc-chart text{font-size:10px;fill:#556}"));

  const money = (n) => (n == null || n === "" ? "Not available" : fmtMoney(n));
  const L = (n) => (n == null ? "Not available" : (n / 1e5).toFixed(2) + " L");
  const goTo = (route, pid) => { if (pid) setProject(pid, true); location.hash = route; };
  const card = (label, value, sub, cls, route, pid) => {
    const el = h("div", { class: "fc-card " + (cls || ""), title: route ? "Open the records behind this" : null }, h("small", {}, label), h("b", {}, value), sub ? h("small", {}, sub) : "");
    if (route) { el.dataset.go = route; el.onclick = () => goTo(route, pid); }
    return el;
  };
  const note = (t, cls) => h("div", { class: "fc-note " + (cls || "") }, t);
  const sev = (s) => h("span", { class: "fc-sev " + s }, s);
  const open = (route, pid) => h("a", { href: "#", onclick: (e) => { e.preventDefault(); goTo(route, pid); } }, "Open");
  const sec = (title, route, ...kids) => h("div", { class: "fc-sec" }, h("h2", {}, title, route ? open(route) : ""), ...kids);
  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const xdl = (x) => {
    if (!x || !x.b64) return;
    const a = document.createElement("a");
    a.href = "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + x.b64;
    a.download = x.filename; document.body.append(a); a.click(); a.remove();
  };

  /* a small line chart of the 13 weeks, drawn here so it never depends on another screen's chart helper */
  function weekChart(series, lines) {
    const W = 860, H = 210, L0 = 70, B = 24, T = 10;
    const all = lines.flatMap((l) => series.map((s) => s[l.k])).filter((v) => v != null);
    let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
    if (hi === lo) hi = lo + 1;
    const x = (i) => L0 + (i * (W - L0 - 10)) / Math.max(1, series.length - 1);
    const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("class", "fc-chart");
    const add = (tag, at, txt) => { const e = document.createElementNS(ns, tag); Object.entries(at).forEach(([k, v]) => e.setAttribute(k, v)); if (txt != null) e.textContent = txt; svg.append(e); return e; };
    [lo, (lo + hi) / 2, hi].forEach((v) => { add("line", { x1: L0, x2: W - 10, y1: y(v), y2: y(v), stroke: "#e3e8ee" }); add("text", { x: 4, y: y(v) + 3 }, (v / 1e5).toFixed(1) + " L"); });
    add("line", { x1: L0, x2: W - 10, y1: y(0), y2: y(0), stroke: "#99a" });
    series.forEach((s, i) => add("text", { x: x(i) - 8, y: H - 6 }, "W" + s.week));
    lines.forEach((l) => add("polyline", { points: series.map((s, i) => x(i) + "," + y(s[l.k])).join(" "), fill: "none", stroke: l.color, "stroke-width": 2, "stroke-dasharray": l.dash || "" }));
    const lg = h("div", { class: "hint" }, lines.map((l) => h("span", { style: "margin-right:14px;color:" + l.color }, "━ " + l.label)));
    return h("div", {}, svg, lg);
  }

  /* ═════════════ the dashboard, one view per role ═════════════ */
  async function dashboard(params, o) {
    o = o || {};
    const box = h("div");
    const meta = await api("fcc.meta", {});
    let view = (params && params.view) || o.view || meta.default_view;
    let scope = o.scoped && S.project ? "project" : "all";
    const holder = h("div");
    const vsel = h("select", { onchange: (e) => { view = e.target.value; load(); } }, meta.views.map(([k, l]) => h("option", { value: k, selected: k === view }, l)));
    const psel = o.scoped ? h("select", { onchange: (e) => { scope = e.target.value; load(); } }, h("option", { value: "project", selected: scope === "project" }, "This project"),
      h("option", { value: "all", selected: scope === "all" }, "All my projects")) : null;
    box.append(h("div", { class: "fc-bar" }, h("label", {}, "View", vsel), psel ? h("label", {}, "Projects", psel) : null,
      h("button", { class: "btn", onclick: () => load() }, "Refresh"),
      h("span", { class: "hint", style: "flex:1" }, "Each figure opens the records behind it. Sections your role may not see are left out by the engine.")), holder);
    async function load() {
      holder.innerHTML = "";
      holder.append(h("p", { class: "muted" }, "Working out the figures…"));
      let d;
      try { d = await api("fcc.summary", { view, project_id: scope === "project" ? S.project : null }); } catch (e) { holder.innerHTML = ""; holder.append(note(e.message, "bad")); return; }
      holder.innerHTML = "";
      if (d.hidden.length) holder.append(h("p", { class: "hint" }, "Not shown for your role" + (scope === "project" ? " or for one project" : "") + ": " + d.hidden.map((k) => (d.labels[k] || k).toLowerCase()).join(", ") + "."));
      d.sections.forEach((k) => { const x = d.data[k]; holder.append(x && x.error ? sec(d.labels[k], null, note(x.error, "bad")) : SECTION[k](x, d.labels[k])); });
    }
    await load();
    return box;
  }

  const SECTION = {
    cash: (x, t) => sec(t, x.route,
      h("div", { class: "fc-strip" },
        card("Cash and bank today", money(x.opening), "the forecast's opening", "", x.route),
        card("Reserve kept back", money(x.reserve), "set in the payment plan", "est", "#/acc/payments?tab=2"),
        card("Restricted funds", money(x.restricted), "this week", "est", x.route),
        card("Available to spend", money(x.available_now), "now", x.available_now < 0 ? "bad" : "ok", x.route),
        card("Lowest closing cash", money(x.lowest.closing), "week " + x.lowest.week + " (" + x.lowest.start + ")", x.lowest.closing < 0 ? "bad" : "", x.route),
        card("Lowest available", money(x.lowest_available.available), "week " + x.lowest_available.week + " (" + x.lowest_available.start + ")", x.lowest_available.available < 0 ? "bad" : "", x.route),
        card("Prudent lowest", money(x.prudent_lowest), "confirmed and likely receipts only", x.prudent_lowest < 0 ? "bad" : "est", x.route)),
      weekChart(x.series, [{ k: "closing", label: "Closing cash", color: "#1f6fb2" }, { k: "available", label: "Available to spend", color: "#2e8b57" },
        { k: "prudent_closing", label: "Prudent closing", color: "#c27c0e", dash: "5,4" }])),
    funding: (x, t) => sec(t, x.route,
      x.gap > 0.5 ? note("Funding gap of " + fmtMoney(x.gap) + " on the prudent view, weeks " + x.first_week + " to " + x.last_week + " (" + x.weeks_short + " week(s) short).", "bad")
        : note("No funding gap in the 13 weeks on the prudent view.", "ok"),
      h("div", { class: "fc-strip" }, card("Funding gap (prudent)", money(x.gap), x.weeks_short ? x.weeks_short + " week(s) short" : "none", x.gap > 0.5 ? "bad" : "ok", x.route),
        card("Funding gap (as expected)", money(x.expected_gap), "all receipts, estimates included", x.expected_gap > 0.5 ? "bad" : "est", x.route)),
      h("p", { class: "hint" }, x.formula)),
    receivables: (x, t) => sec(t, x.route,
      h("div", { class: "fc-strip" },
        card("Overdue", money(x.totals.overdue), "certified, past due", x.totals.overdue > 0.5 ? "bad" : "", "#/acc/ageing?tab=1"),
        card("Not yet due", money(x.totals.not_due), "certified", "", "#/acc/ageing?tab=1"),
        card("Awaiting certification", money(x.totals.submitted), "IPCs submitted", "", "#/p/ipc?tab=1"),
        card("Measured, not billed", money(x.totals.unbilled), "estimate", "est", "#/p/ipc?tab=1"),
        card("Done, not measured", money(x.totals.unmeasured), "estimate", "est", "#/p/ipc?tab=1"),
        card("Retention held", money(x.retention), "not available cash", "est", "#/acc/ageing?tab=1"),
        card("Client advance to recover", money(x.client_advance), "through IPCs", "est", "#/acc/ageing?tab=1")),
      h("div", { class: "fc-strip" }, card("1-30 days overdue", money(x.ages.a30)), card("31-60 days", money(x.ages.a60), "", x.ages.a60 > 0.5 ? "warn" : ""),
        card("61-90 days", money(x.ages.a90), "", x.ages.a90 > 0.5 ? "bad" : ""), card("Over 90 days", money(x.ages.a90p), "", x.ages.a90p > 0.5 ? "bad" : ""))),
    payables: (x, t) => sec(t, x.route, h("div", { class: "fc-strip" },
      card("Overdue", money(x.overdue), "", x.overdue > 0.5 ? "bad" : "", x.route), card("Due in 7 days", money(x.d7), "", "", x.route),
      card("Due in 30 days", money(x.d30), "including the 7", "", x.route), card("Due in 90 days", money(x.d90), "including the 30", "", x.route),
      card("All payables", money(x.total), "already in payment requests " + fmtMoney(x.requested), "", "#/acc/payments?tab=1"))),
    ipcs: (x, t) => sec(t, x.route,
      h("div", { class: "fc-strip" },
        card("Awaiting submission", x.submission.count + " IPC(s)", money(x.submission.amount), x.submission.count ? "warn" : "", x.route),
        card("Awaiting certification", x.certification.count + " IPC(s)", money(x.certification.amount), x.certification.items.some((i) => i.late) ? "bad" : "", x.route),
        card("Awaiting payment", x.payment.count + " IPC(s)", money(x.payment.amount), x.payment.items.some((i) => i.late) ? "bad" : "", x.route)),
      table([{ k: "project", label: "Project" }, { k: "no", label: "IPC" }, { k: "stage", label: "Stage", fmt: "status" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "Days in stage", v: (r) => r.days ?? "" }, { label: "Late by", v: (r) => (r.late ? r.late + " days" : "") }],
        [...x.submission.items, ...x.certification.items, ...x.payment.items], { search: false, export: false, name: "fcc_ipcs", onRow: (r) => goTo("#/p/ipc?tab=1", r.project_id), empty: "No IPC waiting." })),
    projects: (x, t) => sec(t, x.route,
      table([{ k: "code", label: "Project" }, { k: "revenue", label: "Revenue", fmt: "money" }, { k: "cost", label: "Cost to date", fmt: "money" }, { k: "eac", label: "Final cost", fmt: "money" },
        { label: "Net profit", v: (r) => (r.error ? r.error : r.net == null ? "Not available" : fmtMoney(r.net)) }, { label: "Net %", v: (r) => (r.net_pct == null ? "—" : r.net_pct + "%" + (r.incomplete ? " (incomplete)" : "")) },
        x.cash_shown ? { label: "Cash in − out to date", v: (r) => h("span", { class: r.cash_net < 0 ? "bad" : "" }, money(r.cash_net)) } : null,
        x.cash_shown ? { label: "Funding need", v: (r) => (r.funding_need == null ? "Not available" : fmtMoney(r.funding_need) + (r.funding_month ? " (" + r.funding_month + ")" : "")) } : null,
        { k: "alerts", label: "Cost alerts" }].filter(Boolean), x.rows,
        { search: false, name: "fcc_projects", rowClass: (r) => (r.net != null && r.net < 0 ? "bad" : ""), onRow: (r) => goTo("#/cl/cvr?tab=1", r.project_id) }),
      h("p", { class: "hint" }, x.basis + (x.unattributed_cash ? " Cash with no project on the voucher: " + fmtMoney(x.unattributed_cash) + "." : ""))),
    commitments: (x, t) => sec(t, x.route,
      h("div", { class: "fc-strip" }, card("Open orders", money(x.total), x.count + " order(s)", "", x.route)),
      table([{ k: "project", label: "Project" }, { label: "Kind", v: (r) => (r.kind === "po" ? "Purchase order" : "Subcontract") }, { k: "doc_no", label: "Document" }, { k: "party", label: "Party" },
        { k: "due", label: "Due" }, { k: "amount", label: "Open value", fmt: "money" }], x.top, { search: false, export: false, name: "fcc_commit",
        onRow: (r) => goTo(r.kind === "po" ? "#/proc/po" : "#/x/sub", r.project_id), empty: "No open orders." }),
      h("p", { class: "hint" }, x.basis)),
    loans: (x, t) => sec(t, x.route,
      h("div", { class: "fc-strip" }, card("Instalments in 13 weeks", money(x.instalments_13w), "loans and equipment finance", "", "#/acc/cash?tab=3"),
        card("Client advances to recover", money(x.advances.client_advance)), card("Advances to suppliers", money(x.advances.supplier_advance)),
        card("Advances to subcontractors", money(x.advances.subcon_advance))),
      table([{ k: "name", label: "Loan" }, { k: "lender", label: "Lender" }, { k: "balance", label: "Balance", fmt: "money" }, { label: "Rate", v: (r) => (r.rate == null ? "" : r.rate + "%") },
        { k: "emi", label: "Instalment", fmt: "money" }, { k: "next_date", label: "Next" }, { k: "limit", label: "Limit", fmt: "money" }], x.loans, { search: false, export: false, name: "fcc_loans", empty: "No loans recorded." }),
      x.equipment.length ? table([{ k: "code", label: "Machine" }, { k: "lender", label: "Lender" }, { k: "emi", label: "Instalment", fmt: "money" }, { label: "Left", v: (r) => r.left ?? "" },
        { k: "remaining", label: "Remaining instalments", fmt: "money" }], x.equipment, { search: false, export: false, name: "fcc_eqfin" }) : "",
      h("p", { class: "hint" }, x.basis)),
    alerts: (x, t) => sec(t + " (" + x.count + " open, " + x.high + " high)", x.route,
      x.top.length ? table([{ label: "", v: (r) => sev(r.severity) }, { k: "title", label: "Alert" }, { k: "project_code", label: "Project" }, { label: "Amount", v: (r) => (r.amount == null ? "" : fmtMoney(r.amount)) },
        { label: "Owner", v: (r) => r.owner_name || "Not assigned" }, { label: "Target", v: (r) => h("span", { class: r.overdue_days ? "bad" : "" }, r.target_date || "") }, { k: "status_label", label: "Status" }],
        x.top, { search: false, export: false, name: "fcc_top", onRow: (r) => alertDrawer(r.id) }) : note("No open alerts you can see.", "ok"),
      h("p", { class: "hint" }, "Last check " + (x.last_scan || "never").replace("T", " ").slice(0, 16) + ".")),
    actions: (x, t) => sec(t, x.route,
      table([{ k: "owner", label: "Responsible person" }, { k: "count", label: "Open" }, { k: "high", label: "High" }, { label: "Past target", v: (r) => h("span", { class: r.overdue ? "bad" : "" }, String(r.overdue)) },
        { k: "escalated", label: "Escalated" }], x.owners, { search: false, export: false, name: "fcc_owners", empty: "Nothing assigned." }),
      x.mine.length ? h("div", {}, h("h3", {}, "Mine"), table([{ label: "", v: (r) => sev(r.severity) }, { k: "title", label: "Alert" }, { k: "target_date", label: "Target" }, { k: "status_label", label: "Status" }],
        x.mine, { search: false, export: false, name: "fcc_mine", onRow: (r) => alertDrawer(r.id) })) : ""),
    procurement: (x, t) => sec(t, x.route,
      table([{ k: "project", label: "Project" }, { k: "no", label: "Order" }, { k: "vendor", label: "Vendor" }, { k: "total", label: "Total", fmt: "money" }, { k: "delivery_date", label: "Delivery" },
        { k: "pay_date", label: "Payment" }, { label: "Budget left after", v: (r) => money(r.budget_left_after) }, { k: "warning_text", label: "Check" }], x.rows,
        { search: false, export: false, name: "fcc_pos", onRow: (r) => goTo("#/proc/po?tab=1", r.project_id), empty: "No order waiting for approval." })),
    stores: (x, t) => sec(t, x.route,
      table([{ k: "project", label: "Project" }, { k: "code", label: "Material" }, { k: "name", label: "Name" }, { k: "available", label: "In stock" }, { label: "Days left", v: (r) => r.days_left ?? "" },
        { k: "lead_days", label: "Lead days" }, { k: "why", label: "Why" }], x.shortages, { search: false, export: false, name: "fcc_short", onRow: (r) => goTo("#/inv/risk", r.project_id), empty: "No shortage foreseen." }),
      h("div", { class: "fc-strip", style: "margin-top:8px" }, card("Stock not moved 90+ days", money(x.slow.total), (x.slow.count || 0) + " line(s)", x.slow.total > 0.5 ? "warn" : "", "#/inv/stock"))),
    site: (x, t) => sec(t, x.route,
      table([{ k: "code", label: "Project" }, { k: "last_dpr", label: "Last DPR" }, { label: "Days since", v: (r) => h("span", { class: r.days_since > 2 ? "bad" : "" }, r.days_since == null ? "never" : String(r.days_since)) },
        { k: "waiting_approval", label: "Waiting approval" }, { k: "drafts", label: "Drafts" }, { label: "Items behind plan", v: (r) => (r.behind == null ? "Not available" : String(r.behind)) },
        { label: "Billing held by delay", v: (r) => money(r.billing_held) }, { label: "Done, not measured", v: (r) => money(r.unmeasured) }], x.rows,
        { search: false, export: false, name: "fcc_site", onRow: (r) => goTo("#/p/dpr", r.project_id) })),
  };

  /* ═════════════ the alert register ═════════════ */
  async function alertsTab(params) {
    const box = h("div");
    const st = { status: "live", domain: "", mine: false, scope: S.project && params && params.scope === "project" ? "project" : "all" };
    const holder = h("div");
    const sSel = h("select", { onchange: (e) => { st.status = e.target.value; load(); } }, [["live", "Open (all open states)"], ["closed", "Closed"], ["all", "All"], ["open", "Open"], ["acknowledged", "Acknowledged"],
      ["in_progress", "In progress"], ["escalated", "Escalated"], ["resolved", "Resolved"], ["dismissed", "Dismissed"], ["cleared", "Cleared"]].map(([k, l]) => h("option", { value: k }, l)));
    const dSel = h("select", { onchange: (e) => { st.domain = e.target.value; load(); } }, h("option", { value: "" }, "All areas"));
    const pSel = h("select", { onchange: (e) => { st.scope = e.target.value; load(); } }, h("option", { value: "all" }, "All my projects"), h("option", { value: "project" }, "This project"));
    pSel.value = st.scope;
    const mine = h("input", { type: "checkbox", onchange: (e) => { st.mine = e.target.checked; load(); } });
    let last = null;
    box.append(h("div", { class: "fc-bar" }, h("label", {}, "Status", sSel), h("label", {}, "Area", dSel), h("label", {}, "Projects", pSel),
      h("label", { style: "flex-direction:row;align-items:center;gap:4px" }, mine, "Mine only"),
      h("button", { class: "btn", onclick: () => load(true) }, "Check now"),
      h("button", { class: "btn", onclick: () => rulesDialog() }, "Alert rules"),
      h("button", { class: "btn", onclick: () => last && printAlerts(last) }, "Print")), holder);
    async function load(scan) {
      holder.innerHTML = "";
      holder.append(h("p", { class: "muted" }, scan ? "Running the fifteen checks…" : "Loading…"));
      let d;
      try { d = await api("fcc.alerts", { status: st.status, domain: st.domain, mine: st.mine ? 1 : 0, scan: scan ? 1 : 0, project_id: st.scope === "project" ? S.project : null }); }
      catch (e) { holder.innerHTML = ""; holder.append(note(e.message, "bad")); return; }
      last = d;
      if (dSel.options.length === 1) d.domains.forEach(([k, l]) => dSel.append(h("option", { value: k }, l)));
      holder.innerHTML = "";
      if (d.scan) holder.append(note("Checked: " + d.scan.raised + " new, " + d.scan.reopened + " open again, " + d.scan.cleared + " cleared, " + d.scan.escalated + " escalated." +
        (d.scan.errors && d.scan.errors.length ? " Some checks could not run: " + d.scan.errors.join("; ") : ""), d.scan.errors && d.scan.errors.length ? "" : "ok"));
      const c = d.counts;
      holder.append(h("div", { class: "fc-strip" }, card("Open", String(c.live)), card("High", String(c.high), "", c.high ? "bad" : "ok"), card("Mine", String(c.mine)),
        card("Past target date", String(c.overdue), "", c.overdue ? "bad" : ""), card("Escalated", String(c.escalated), "", c.escalated ? "warn" : ""),
        card("Not assigned", String(c.unassigned), "", c.unassigned ? "warn" : "")));
      holder.append(table([{ label: "", v: (r) => sev(r.severity) }, { k: "title", label: "Alert" }, { k: "project_code", label: "Project" }, { k: "domain_label", label: "Area" },
        { label: "Amount", v: (r) => (r.amount == null ? "" : fmtMoney(r.amount)) }, { k: "due_date", label: "Expected" }, { label: "Responsible", v: (r) => r.owner_name || "Not assigned" },
        { label: "Target", v: (r) => h("span", { class: r.overdue_days ? "bad" : "" }, (r.target_date || "") + (r.overdue_days ? " (" + r.overdue_days + " days late)" : "")) },
        { k: "status_label", label: "Status" }, { label: "Level", v: (r) => (r.escalation_level ? "L" + r.escalation_level : "") }], d.rows,
      { name: "fin_alerts", onRow: (r) => alertDrawer(r.id, () => load()), empty: st.status === "live" ? "No open alerts you can see." : "Nothing here." }));
      holder.append(h("p", { class: "hint" }, "Checked automatically when this list opens (at most every hour) and with Check now. Last check " + (d.last_scan || "never").replace("T", " ").slice(0, 16) +
        ". An alert is never deleted: when its condition goes away it is cleared, and it opens again if the condition comes back."));
    }
    await load();
    if (params && params.alert) alertDrawer(Number(params.alert), () => load());
    return box;
  }

  function printAlerts(d) {
    printDoc("Financial alerts", [["Printed", new Date().toISOString().slice(0, 16).replace("T", " ")], ["Open", String(d.counts.live)]],
      [{ k: "severity", label: "Severity" }, { k: "title", label: "Alert" }, { k: "project_code", label: "Project" }, { k: "amount", label: "Amount", fmt: "money" },
        { k: "owner_name", label: "Responsible" }, { k: "target_date", label: "Target" }, { k: "status_label", label: "Status" }], d.rows, [], "");
  }

  async function alertDrawer(id, after) {
    let a;
    try { a = await api("fcc.alert_get", { id }); } catch (e) { toast(e.message, "err"); return; }
    const body = h("div", { style: "max-width:760px" });
    const draw = () => {
      body.innerHTML = "";
      body.append(h("p", {}, sev(a.severity), " ", h("b", {}, a.kind_label), " · ", a.domain_label, a.project_code ? " · " + a.project_code : " · company", " · ", h("b", {}, a.status_label),
        a.escalation_level ? " · escalation level " + a.escalation_level + (a.escalated_to_name ? " (" + a.escalated_to_name + ")" : "") : ""));
      body.append(h("div", { class: "fc-strip" }, card("Amount", a.amount == null ? "Not applicable" : fmtMoney(a.amount)), card("Expected date", a.due_date || "—"),
        card("Responsible", a.owner_name || "Not assigned", "", a.owner_id ? "" : "warn"), card("Target date", a.target_date || "—", a.overdue_days ? a.overdue_days + " days late" : "", a.overdue_days ? "bad" : "")));
      if (a.detail) body.append(h("p", {}, a.detail));
      body.append(h("p", {}, h("b", {}, "How it is worked out: "), a.basis || ""), h("p", {}, h("b", {}, "Next action: "), a.action || ""));
      if (a.sources.length) body.append(h("div", { class: "fc-src" }, h("b", {}, "Source records: "), a.sources.map((s) => h("a", { href: "#", onclick: (e) => { e.preventDefault(); goTo(s.route, s.project_id); } }, s.no || s.type))));
      body.append(h("h4", {}, "History"), h("div", { class: "fc-log" }, a.log.map((l) => h("div", {}, h("small", {}, (l.ts || "").replace("T", " ").slice(0, 16) + " · " + (l.user_name || "BuildCore") + " · "),
        h("b", {}, l.action), l.from_status && l.to_status && l.from_status !== l.to_status ? " (" + l.from_status + " → " + l.to_status + ")" : "", l.note ? ": " + l.note : ""))));
    };
    draw();
    const act = async (action, extra) => { a = await run("fcc.alert_act", Object.assign({ id: a.id, action }, extra || {}), "Saved"); draw(); m.close(); alertDrawer(a.id, after); if (after) after(); };
    const live = ["open", "acknowledged", "in_progress", "escalated"].includes(a.status);
    const btns = [];
    if (a.can_act && live && ["open", "escalated"].includes(a.status)) btns.push({ label: "Acknowledge", act: () => act("acknowledge"), keep: true });
    if (a.can_act && live && a.status !== "in_progress") btns.push({ label: "Working on it", act: () => act("start"), keep: true });
    if (a.can_act && live) btns.push({ label: "Resolve", cls: "primary", keep: true, act: async () => {
      const f = form([{ k: "note", label: "How was it resolved?", type: "textarea" }, { k: "hold_days", label: "Check again after (days)", type: "number" }], { hold_days: 7 });
      modal("Resolve alert", f, [{ label: "Resolve", cls: "primary", act: async () => { const v = f.values(); await act("resolve", v); } }], { narrow: true });
    } });
    if (a.can_act) btns.push({ label: "Comment", keep: true, act: async () => { const t = await ask("Comment", "Add a note to this alert's history.", { input: "Comment", required: true }); if (t) await act("comment", { note: t }); } });
    if (live && (a.can_manage || a.can_act)) btns.push({ label: "Escalate", keep: true, act: async () => { const t = await ask("Escalate", "Tell the next person up the escalation chain.", { input: "Why (optional)" }); if (t !== null) await act("escalate", { note: t }); } });
    if (a.can_manage) btns.push({ label: "Assign", keep: true, act: () => {
      const f = form([{ k: "owner_id", label: "Responsible person", type: "select", options: (a.owners || []).map((o) => [o.id, o.name + " (" + o.role + ")"]) },
        { k: "target_date", label: "Target date", type: "date" }, { k: "note", label: "Note", type: "textarea" }], { owner_id: a.owner_id, target_date: a.target_date });
      modal("Assign alert", h("div", {}, f, h("p", { class: "hint" }, "Only people whose role can see this kind of figure and this project are listed.")),
        [{ label: "Assign", cls: "primary", act: async () => { await act("assign", f.values()); } }], { narrow: true });
    } });
    if (a.can_manage && live) btns.push({ label: "Dismiss", cls: "warn", keep: true, act: () => {
      const f = form([{ k: "note", label: "Reason", type: "textarea" }, { k: "until", label: "Dismissed until (at most 90 days)", type: "date" }], {});
      modal("Dismiss alert", h("div", {}, f, h("p", { class: "hint" }, "If the condition is still there after this date, the alert opens again.")),
        [{ label: "Dismiss", cls: "warn", act: async () => { await act("dismiss", f.values()); } }], { narrow: true });
    } });
    if (a.can_manage && !live) btns.push({ label: "Reopen", keep: true, act: () => act("reopen") });
    const m = modal(a.title, body, btns);
  }

  async function rulesDialog() {
    const d = await run("fcc.rules", {});
    const rows = d.rules.map((r) => Object.assign({}, r));
    const ed = (r, k, type) => d.can_edit ? h("input", { type: type || "text", value: type === "checkbox" ? null : r[k], checked: type === "checkbox" ? r[k] : null, style: type === "checkbox" ? "" : "width:" + (k === "owner_role" ? "210px" : "70px"),
      onchange: (e) => { r[k] = type === "checkbox" ? e.target.checked : e.target.value; } }) : String(r[k] ?? "");
    const tb = h("table", {}, h("thead", {}, h("tr", {}, ["On", "Alert", "Limit", "", "Owner roles (first found)", "Target days", "Escalate every (days past target)"].map((x) => h("th", {}, x)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, ed(r, "enabled", "checkbox")), h("td", {}, r.label), h("td", {}, r.threshold_label ? ed(r, "threshold", "number") : ""), h("td", { class: "hint" }, r.threshold_label),
        h("td", {}, ed(r, "owner_role")), h("td", {}, ed(r, "target_days", "number")), h("td", {}, ed(r, "escalate_days", "number"))))));
    const esc = form([{ k: "fcc_escalation_finance", label: "Escalation chain: cash, receivables, payables" }, { k: "fcc_escalation_project", label: "Escalation chain: project alerts" },
      { k: "fcc_scan_minutes", label: "Check automatically every (minutes)", type: "number" }].map((f) => Object.assign(f, { readonly: !d.can_edit })), d.escalation);
    modal("Alert rules", h("div", {}, h("div", { class: "tablewrap" }, tb), esc,
      h("p", { class: "hint" }, "Roles: " + d.roles.join(", ") + ". Escalation level 1 goes to the first role in the chain, level 2 to the next. A rule switched off stops new alerts of that kind; existing ones are cleared at the next check.")),
    d.can_edit ? [{ label: "Save", cls: "primary", act: async () => { await run("fcc.rules_save", Object.assign({ rules: rows }, esc.values()), "Rules saved"); } }] : []);
  }

  /* ═════════════ funding gap and financing options (Accounts › Cash forecast & ratios) ═════════════ */
  async function fundingTab() {
    const box = h("div");
    const d = await api("fcc.funding", {});
    const f = d.funding;
    box.append(note(d.note));
    box.append(h("div", { class: "fc-strip" },
      card("Funding gap (prudent)", money(f.gap), f.weeks_short ? "weeks " + f.first_week + " to " + f.last_week : "no week short", f.gap > 0.5 ? "bad" : "ok"),
      card("Weeks short", String(f.weeks_short), "of 13"), card("Gap as expected", money(f.expected_gap), "estimates and uncertain receipts included", "est"),
      card("Cash today", money(f.opening)), card("Reserve", money(f.reserve), "", "est")));
    box.append(h("p", { class: "hint" }, f.formula));
    box.append(h("details", {}, h("summary", {}, "Week by week"), table([{ k: "week", label: "Week" }, { k: "start", label: "From" }, { k: "required", label: "Payments + reserve + restricted (to date)", fmt: "money" },
      { k: "available", label: "Cash today", fmt: "money" }, { k: "reliable_receipts", label: "Confirmed and likely receipts (to date)", fmt: "money" }, { k: "shortfall", label: "Funding gap", fmt: "money" },
      { k: "expected_gap", label: "Gap as expected", fmt: "money" }], f.rows, { search: false, name: "funding_gap" })));
    box.append(h("h3", {}, "What can be done, in this order"),
      table([{ k: "step", label: "#" }, { k: "label", label: "Action" }, { label: "Amount behind it", v: (r) => (r.amount == null ? "—" : fmtMoney(r.amount)) }, { k: "basis", label: "From the records" },
        { label: "", v: (r) => open(r.route) }], d.actions, { search: false, export: false, name: "fund_actions" }),
      h("p", { class: "hint" }, "Amounts are what the records hold, not what will be collected or saved."));
    const opts = [d.base, ...d.options];
    box.append(h("h3", {}, "Financing options compared"),
      d.can_edit ? h("div", { class: "fc-bar" }, h("button", { class: "btn primary", onclick: () => optionDialog(null, d) }, "+ Option")) : "",
      table([{ k: "name", label: "Option" }, { label: "Amount", v: (r) => (r.amount == null ? "—" : fmtMoney(r.amount)) }, { label: "Rate", v: (r) => (r.rate_pct == null ? (r.id ? "Not available" : "") : r.rate_pct + "%") },
        { label: "Lowest available", v: (r) => h("span", { class: r.lowest_available < 0 ? "bad" : "" }, fmtMoney(r.lowest_available)) }, { label: "Largest gap", v: (r) => money(r.max_gap) },
        { label: "Weeks short", v: (r) => String(r.gap_weeks) }, { label: "Closes the gap", v: (r) => (r.closes_gap ? "Yes" : "No") }, { label: "Cost in 13 weeks", v: (r) => money(r.cost_13w) },
        { label: "Total cost", v: (r) => (r.total_cost == null ? (r.kind === "equity" ? "Ownership, not interest" : "—") : fmtMoney(r.total_cost)) },
        { label: "Repayment", v: (r) => (r.first_repayment ? r.first_repayment + (r.last_repayment !== r.first_repayment ? " to " + r.last_repayment : "") : "") },
        { k: "collateral", label: "Collateral" }, { k: "risks", label: "Risks" }], opts,
      { search: false, name: "fin_options", onRow: (r) => (r.id && d.can_edit ? optionDialog(r, d) : null) }),
      h("p", { class: "hint" }, "Each option is added to the 13-week forecast as expected: the money in on its date, then interest, fees and repayments on theirs. Nothing is borrowed or posted, and no option is recommended."));
    return box;
  }

  function optionDialog(r, d) {
    const f = form([{ k: "name", label: "Name", req: true }, { k: "kind", label: "Kind", type: "select", noBlank: true, options: d.kinds },
      { k: "amount", label: "Amount", type: "number" }, { k: "draw_date", label: "Money comes in on", type: "date" }, { k: "rate_pct", label: "Interest % a year", type: "number" },
      { k: "tenor_months", label: "Term (months)", type: "number" }, { k: "repayment", label: "Repayment", type: "select", noBlank: true, options: d.repayments },
      { k: "fee_pct", label: "Fees % of amount", type: "number" }, { k: "fee_fixed", label: "Fixed fees", type: "number" },
      { k: "collateral", label: "Collateral", type: "textarea" }, { k: "risks", label: "Main risks", type: "textarea" }, { k: "notes", label: "Notes", type: "textarea" }],
    r || { kind: "overdraft", repayment: "bullet", draw_date: d.weeks[0].start });
    modal(r ? "Financing option" : "New financing option", h("div", {}, f, h("p", { class: "hint" }, "Longer supplier credit: the amount of payments moved later by the term; equity: no interest or repayment. A comparison only.")),
      [{ label: "Save", cls: "primary", act: async () => { await run("fcc.option_save", { row: Object.assign({ id: r && r.id }, f.values()) }, "Saved"); location.hash = "#/acc/cash?tab=4&r=" + Date.now(); } },
        r ? { label: "Remove", cls: "warn", act: async () => { await run("fcc.option_delete", { id: r.id }, "Removed"); location.hash = "#/acc/cash?tab=4&r=" + Date.now(); } } : null]);
  }

  /* ═════════════ the report builder ═════════════ */
  async function reportsTab(params) {
    const box = h("div", { class: "fc-grid2" });
    const meta = await api("fcc.report_meta", {});
    const left = h("div", { class: "fc-list" });
    const right = h("div");
    box.append(left, right);
    let cur = null;
    const drawList = () => {
      left.innerHTML = "";
      left.append(h("h3", {}, "Templates and saved reports"));
      left.append(h("button", { onclick: () => edit(null) }, h("b", {}, "+ New report"), h("small", {}, "Choose the data, columns and grouping")));
      meta.reports.forEach((r) => left.append(h("button", { class: cur && cur.id === r.id ? "on" : "", onclick: () => edit(r) }, r.name,
        h("small", {}, (r.builtin ? "Built-in template" : r.shared ? "Shared by " + (r.owner || "—") : "Mine") + " · " + ((meta.datasets.find((x) => x.key === r.dataset) || {}).label || r.dataset)))));
    };
    function edit(r) {
      cur = r;
      drawList();
      right.innerHTML = "";
      const def = JSON.parse(JSON.stringify((r && r.definition) || { dataset: meta.datasets[0].key, period: "last_30", columns: [], filters: [], group_by: [], sort: [], summaries: {}, orientation: "portrait" }));
      def.filters = def.filters || []; def.group_by = def.group_by || []; def.sort = def.sort || []; def.summaries = def.summaries || {}; def.project_ids = def.project_ids || [];
      const name = h("input", { value: (r && !r.builtin && r.name) || "", placeholder: r && r.builtin ? r.name + " (copy)" : "Report name" });
      const dsSel = h("select", { onchange: (e) => { def.dataset = e.target.value; def.columns = []; def.filters = []; def.group_by = []; def.sort = []; def.summaries = {}; drawForm(); } },
        meta.datasets.map((x) => h("option", { value: x.key, selected: x.key === def.dataset }, x.label)));
      const form1 = h("div");
      const out = h("div");
      const DS = () => meta.datasets.find((x) => x.key === def.dataset) || meta.datasets[0];
      function drawForm() {
        form1.innerHTML = "";
        const ds = DS();
        const cols = ds.columns;
        if (!def.columns.length) def.columns = cols.slice(0, 8).map((c) => c.k);
        const opt = (sel, list, blank) => [blank ? h("option", { value: "" }, blank) : null, ...list.map((c) => h("option", { value: c.k, selected: c.k === sel }, c.label))];
        const per = h("select", { onchange: (e) => { def.period = e.target.value; } }, meta.periods.map(([k, l]) => h("option", { value: k, selected: k === (def.period || "custom") }, l)));
        const frm = h("input", { type: "date", value: def.from || "", onchange: (e) => { def.from = e.target.value; def.period = "custom"; per.value = "custom"; } });
        const to = h("input", { type: "date", value: def.to || "", onchange: (e) => { def.to = e.target.value; def.period = "custom"; per.value = "custom"; } });
        const proj = h("select", { multiple: true, size: Math.min(5, meta.projects.length + 1), onchange: (e) => { def.project_ids = [...e.target.selectedOptions].map((o) => Number(o.value)); } },
          meta.projects.map((p) => h("option", { value: p.id, selected: def.project_ids.includes(p.id) }, p.code + " " + p.name)));
        form1.append(h("div", { class: "fc-bar" }, h("label", {}, "Report name", name), h("label", {}, "Data", dsSel),
          ds.period ? h("label", {}, "Period", per) : "", ds.period ? h("label", {}, "From", frm) : "", ds.period ? h("label", {}, "To", to) : "",
          ds.company ? h("span", { class: "hint" }, "Company-wide") : h("label", {}, "Projects (none = all you may see)", proj)));
        const colBox = h("div", { class: "fc-cols" }, cols.map((c) => h("label", {}, h("input", { type: "checkbox", checked: def.columns.includes(c.k), onchange: (e) => {
          if (e.target.checked) def.columns.push(c.k); else def.columns = def.columns.filter((x) => x !== c.k); } }), " ", c.label)));
        form1.append(h("details", { open: true }, h("summary", {}, "Columns (in the order ticked)" + (ds.dynamic ? "; project fields from the DPR templates are added when you run it" : "")), colBox));
        const fl = h("div");
        const drawF = () => {
          fl.innerHTML = "";
          def.filters.forEach((x, i) => fl.append(h("div", { class: "fc-bar" }, h("select", { onchange: (e) => { x.field = e.target.value; } }, opt(x.field, cols)),
            h("select", { onchange: (e) => { x.op = e.target.value; } }, meta.ops.map((o) => h("option", { value: o, selected: o === x.op }, { eq: "is", ne: "is not", contains: "contains", gt: ">", gte: "≥", lt: "<", lte: "≤", in: "is one of (a, b)", empty: "is empty", notempty: "is not empty" }[o]))),
            h("input", { value: x.value || "", onchange: (e) => { x.value = e.target.value; } }), h("button", { class: "btn small", onclick: () => { def.filters.splice(i, 1); drawF(); } }, "Remove"))));
          fl.append(h("button", { class: "btn small", onclick: () => { def.filters.push({ field: cols[0].k, op: "eq", value: "" }); drawF(); } }, "+ Filter"));
        };
        drawF();
        form1.append(h("details", { open: def.filters.length > 0 }, h("summary", {}, "Filters"), fl));
        const g1 = h("select", { onchange: (e) => { def.group_by[0] = e.target.value; def.group_by = def.group_by.filter(Boolean); } }, opt(def.group_by[0], cols, "No grouping"));
        const g2 = h("select", { onchange: (e) => { def.group_by[1] = e.target.value; def.group_by = def.group_by.filter(Boolean); } }, opt(def.group_by[1], cols, "—"));
        const s1 = h("select", { onchange: (e) => { def.sort = e.target.value ? [{ field: e.target.value, dir: sd.value }] : []; } }, opt((def.sort[0] || {}).field, cols, "As the data comes"));
        const sd = h("select", { onchange: (e) => { if (def.sort[0]) def.sort[0].dir = e.target.value; } }, h("option", { value: "asc" }, "Ascending"), h("option", { value: "desc", selected: (def.sort[0] || {}).dir === "desc" }, "Descending"));
        form1.append(h("div", { class: "fc-bar" }, h("label", {}, "Group by", g1), h("label", {}, "then by", g2), h("label", {}, "Sort by", s1), h("label", {}, "Direction", sd)));
        const nums = cols.filter((c) => ["number", "money"].includes(c.type));
        form1.append(h("details", { open: Object.keys(def.summaries).length > 0 }, h("summary", {}, "Totals"), h("div", { class: "fc-bar" },
          [...nums, ...cols.filter((c) => !["number", "money"].includes(c.type)).slice(0, 1)].map((c) => h("label", {}, c.label, h("select", { onchange: (e) => { if (e.target.value) def.summaries[c.k] = e.target.value; else delete def.summaries[c.k]; } },
            [["", "—"], ["sum", "Sum"], ["avg", "Average"], ["min", "Smallest"], ["max", "Largest"], ["count", "Count"]].filter(([k]) => ["number", "money"].includes(c.type) || ["", "count"].includes(k))
              .map(([k, l]) => h("option", { value: k, selected: def.summaries[c.k] === k }, l))))))));
        const orient = h("select", { onchange: (e) => { def.orientation = e.target.value; } }, h("option", { value: "portrait" }, "Portrait"), h("option", { value: "landscape", selected: def.orientation === "landscape" }, "Landscape"));
        form1.append(h("div", { class: "fc-bar" }, h("label", {}, "Page", orient), h("label", {}, "Header", h("input", { value: def.header || "", onchange: (e) => { def.header = e.target.value; } })),
          h("label", {}, "Footer", h("input", { value: def.footer || "", onchange: (e) => { def.footer = e.target.value; } })),
          def.dataset === "dpr" ? h("label", { style: "flex-direction:row;align-items:center;gap:4px" }, h("input", { type: "checkbox", checked: !!def.attachments, onchange: (e) => { def.attachments = e.target.checked; } }), "List photos and attachments") : ""));
      }
      drawForm();
      const payload = () => ({ definition: Object.assign({}, def, { title: name.value || (r && r.name) || "" }) });
      let res = null;
      const runIt = async () => { res = await run("fcc.report_run", payload()); drawResult(); };
      function drawResult() {
        out.innerHTML = "";
        if (!res) return;
        out.append(h("h3", {}, res.title), h("p", { class: "hint" }, res.dataset_label + " · " + (res.from || res.to ? (res.from || "start") + " to " + (res.to || "today") + " · " : "") + res.projects + " · " + res.rows + " row(s)" +
          (res.truncated ? " (the first " + res.limit + " shown; Excel has all)" : "")));
        out.append(resultTable(res));
      }
      const saveIt = async (asNew) => {
        const nm = name.value.trim() || (r && !r.builtin ? r.name : "");
        if (!nm) { toast("Give the report a name.", "err"); return; }
        let shared = r && !r.builtin ? r.shared : 0;
        if (meta.rights.share) shared = (await ask("Share", "Share this report with everyone who may see its data?", { ok: "Share with everyone" })) ? 1 : 0;
        const x = await run("fcc.report_save", { id: !asNew && r && !r.builtin ? r.id : null, name: nm, shared, definition: payload().definition }, "Report saved");
        const m2 = await api("fcc.report_meta", {});
        meta.reports = m2.reports;
        edit(meta.reports.find((y) => y.id === x.id));
      };
      right.append(form1, h("div", { class: "fc-bar" }, h("button", { class: "btn primary", onclick: runIt }, "Run"),
        meta.rights.export ? h("button", { class: "btn", onclick: async () => xdl(await run("fcc.report_xlsx", payload())) }, "Excel") : "",
        h("button", { class: "btn", onclick: async () => { if (!res) await runIt(); printReport(res); } }, "Print / PDF"),
        meta.rights.create && r && !r.builtin && r.can_edit ? h("button", { class: "btn", onclick: () => saveIt(false) }, "Save") : "",
        meta.rights.create ? h("button", { class: "btn", onclick: () => saveIt(true) }, r ? "Save as new" : "Save") : "",
        r && !r.builtin && r.can_edit ? h("button", { class: "btn warn", onclick: async () => { await run("fcc.report_delete", { id: r.id }, "Removed"); meta.reports = meta.reports.filter((y) => y.id !== r.id); edit(null); } }, "Remove") : ""), out);
      if (r) runIt();
    }
    drawList();
    edit(meta.reports[0] || null);
    return box;
  }

  const fmtCell = (c, v) => (v == null || v === "" ? "" : c.type === "money" ? fmtMoney(v) : c.type === "number" ? (typeof v === "number" ? String(Math.round(v * 10000) / 10000) : v) : String(v));
  function resultTable(res) {
    const cols = res.columns;
    const tb = h("tbody");
    res.lines.forEach((ln) => {
      if (ln.type === "group") tb.append(h("tr", { class: "g" }, h("td", { colspan: cols.length, style: "padding-left:" + (8 + 14 * ln.level) + "px" }, ln.label)));
      else if (ln.type === "row") tb.append(h("tr", {}, cols.map((c) => h("td", { class: ["number", "money"].includes(c.type) ? "n" : "" }, fmtCell(c, ln.values[c.k])))));
      else tb.append(h("tr", { class: ln.type === "total" ? "tt" : "st" }, cols.map((c, i) => h("td", { class: ["number", "money"].includes(c.type) ? "n" : "" },
        i === 0 ? ln.label + " (" + ln.count + ")" : fmtCell(c, (ln.values || {})[c.k])))));
    });
    if (!res.lines.length) tb.append(h("tr", {}, h("td", { colspan: cols.length, class: "empty" }, "Nothing matches.")));
    return h("div", { class: "tablewrap fc-rep" }, h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: ["number", "money"].includes(c.type) ? "n" : "" }, c.label)))), tb));
  }

  function printReport(res) {
    if (!res) return;
    const w = window.open("", "_blank");
    if (!w) { toast("Allow pop-ups to print.", "err"); return; }
    const esc = escHtml;
    const cols = res.columns;
    const num = (c) => ["number", "money"].includes(c.type);
    const body = res.lines.map((ln) => ln.type === "group" ? `<tr><td colspan="${cols.length}" style="font-weight:600;background:#eef2f6;padding-left:${6 + 12 * ln.level}px">${esc(ln.label)}</td></tr>`
      : ln.type === "row" ? `<tr>${cols.map((c) => `<td class="${num(c) ? "n" : ""}">${esc(fmtCell(c, ln.values[c.k]))}</td>`).join("")}</tr>`
        : `<tr style="font-weight:${ln.type === "total" ? 700 : 600}">${cols.map((c, i) => `<td class="${num(c) ? "n" : ""}">${esc(i === 0 ? ln.label + " (" + ln.count + ")" : fmtCell(c, (ln.values || {})[c.k]))}</td>`).join("")}</tr>`).join("");
    w.document.write(`<html><head><title>${esc(res.title)}</title><style>${PRINT_CSS}@page{size:A4 ${res.orientation === "landscape" ? "landscape" : "portrait"};margin:12mm}
      td.n,th.n{text-align:right}.hdr{margin:0 0 6px}.ftr{margin-top:10px;font-size:11px;color:#555;display:flex;justify-content:space-between}</style></head><body>
      ${headingHtml(res.title, [])}${res.header ? `<div class="hdr">${esc(res.header)}</div>` : ""}
      <div class="meta"><div><b>Data:</b> ${esc(res.dataset_label)}</div><div><b>Projects:</b> ${esc(res.projects)}</div>${res.from || res.to ? `<div><b>Period:</b> ${esc((res.from || "start") + " to " + (res.to || "today"))}</div>` : ""}<div><b>Rows:</b> ${res.rows}</div></div>
      <table><thead><tr>${cols.map((c) => `<th class="${num(c) ? "n" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>
      <div class="ftr"><span>${esc(res.footer || "")}</span><span>Generated ${esc((res.generated || "").replace("T", " ").slice(0, 16))} by ${esc(res.by || "")}</span></div>
      <script>window.onload=()=>window.print()<\/script></body></html>`);
    w.document.close();
  }

  /* ═════════════ placing the tabs ═════════════ */
  if (PAGES.command) {
    const wasLive = !!PAGES.command.live;
    addTabs("command", "Command centre", "All projects at a glance, and the company's money. Click a figure to open the records behind it.", "Portfolio",
      [["Financial command centre", (p) => dashboard(p, {})], ["Report builder", (p) => (window.bcoReports ? window.bcoReports(p) : reportsTab(p))]]);
    /* the portfolio tab still refreshes itself with the team's live activity; the other tabs never jump back */
    let tabNow = 0;
    document.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest(".tabs button");
      if (b && location.hash.startsWith("#/command")) tabNow = [...b.parentNode.children].indexOf(b);
    }, true);
    window.addEventListener("hashchange", () => { if (!location.hash.startsWith("#/command")) tabNow = 0; });
    if (wasLive) Object.defineProperty(PAGES.command, "live", { get: () => tabNow === 0, configurable: true });
  }
  addTabs("action", "Action centre", "Everything that needs a person: approvals, overdue work, risks and deadlines, and the financial alerts with their owners.", "Action centre",
    [["Financial alerts", (p) => alertsTab(p)], ["My financial view", (p) => dashboard(p, { scoped: true })]]);

  /* Accounts › Cash forecast & ratios: a fifth tab after the 13-week forecast */
  const orig = PAGES["acc/cash"];
  if (orig && !orig.__fcc) {
    const page = async (root, params) => {
      const want = Number(params && params.tab) === 4;
      await orig(root, Object.assign({}, params, { tab: want ? 0 : params && params.tab }));
      const bar = root.querySelector(".tabs");
      if (!bar) return;
      const body = bar.nextSibling;
      const btn = h("button", { type: "button", onclick: async () => {
        bar.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
        body.innerHTML = "";
        try { body.append(await fundingTab()); } catch (e) { body.append(note(e.message, "bad")); }
      } }, "Funding gap & financing");
      bar.append(btn);
      if (want) { let n = 0; const t = setInterval(() => { if (body.childNodes.length || ++n > 40) { clearInterval(t); btn.click(); } }, 150); }
    };
    page.__fcc = true;
    page.__cfw = true;
    PAGES["acc/cash"] = page;
  }

  /* What's new */
  const VER = "2.29.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    const fin = can("accounts", "view");
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("p", {}, "New tabs bring the money and the warnings together. The menu is unchanged."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        fin ? h("li", {}, "Command centre › Financial command centre: cash, the 13-week low point, the funding gap, receivables, payables due, IPCs, project profit and cash use, orders, loans, alerts and who owns them. One view per role.") : null,
        h("li", {}, "Action centre › Financial alerts: fifteen checks with a responsible person, target date, escalation and full history."),
        h("li", {}, "Action centre › My financial view: the figures that matter for your role."),
        fin ? h("li", {}, "Accounts › Cash forecast & ratios › Funding gap & financing: the gap, what can be done in order, and financing options compared. Nothing is borrowed.") : null,
        h("li", {}, "Command centre › Report builder: your own reports from DPRs, cash, IPCs, payables, project health, resources, the ledger and alerts; Excel and print.")),
      h("p", { class: "hint" }, "Nothing is posted and no balance changes.")),
    [{ label: "Open the alerts", cls: "primary", act: () => { location.hash = "#/action?tab=1"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 8500); } }, 900);
})();
