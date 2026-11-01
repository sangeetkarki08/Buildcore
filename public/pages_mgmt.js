/* BuildCore 2.23 — accounts, project KPIs and finance on the combined execution model.
   Cost by way of working (direct labour, labour-supply / item-rate / back-to-back subcontracts, our material,
   own and rented equipment), project cost with entries waiting for accounts, commitments, exposure and the
   return on the money a project ties up; finance and stock by segment (projects, trading, company); own
   equipment recovery. Nothing here posts or changes an entry: the screens read the one ledger. */
(function () {
  "use strict";
  const VER = "2.23.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  let META = null;
  const meta = async (fresh) => { if (!META || fresh) META = await api("mg.meta", {}); return META; };
  const money = (v) => (v == null ? "—" : fmtMoney(v));
  const n1 = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 1 }));
  const pct = (v) => (v == null ? "—" : n1(v) + "%");
  const lab = (k) => (((META && META.modes) || []).concat([["untagged", "Not tagged (before 2.23)"]]).find((x) => x[0] === k) || [k, k])[1];
  const COL = { direct_labour: "#1769aa", labour_sc: "#c08a2c", supplied_sc: "#2f7a4d", b2b_sc: "#7848a0", sc_other: "#9a6b4f",
    material: "#3f8f9e", own_eq: "#c0392b", rented_eq: "#e07b39", overhead: "#8796a3", trading: "#5b7183", untagged: "#c9d2d9" };
  const ORDER = ["direct_labour", "labour_sc", "supplied_sc", "b2b_sc", "sc_other", "material", "own_eq", "rented_eq", "overhead", "trading", "untagged"];
  const SEGL = { project: "Projects", trading: "Trading", company: "Company" };

  const css = document.createElement("style");
  css.textContent = [
    ".mt{display:grid;grid-template-columns:repeat(auto-fill,minmax(178px,1fr));gap:10px;margin:0 0 14px}",
    ".mt .t{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-left:4px solid #1769aa;border-radius:12px;padding:10px 14px}",
    ".mt .t.click{cursor:pointer}.mt .t b{display:block;font-size:19px;font-variant-numeric:tabular-nums}.mt .t span{color:var(--muted,#5b7183);font-size:12.5px}",
    ".mt .t small{display:block;color:var(--muted,#5b7183);font-size:11.5px;margin-top:2px}",
    ".mt .t.warn{border-left-color:#b7791f}.mt .t.bad{border-left-color:#c0392b}.mt .t.good{border-left-color:#2f7a4d}.mt .t.grey{border-left-color:#8796a3}",
    ".mnote{background:rgba(23,105,170,.07);border:1px solid rgba(23,105,170,.25);border-radius:10px;padding:9px 13px;margin:0 0 12px;font-size:13.5px}",
    ".mnote.warn{background:rgba(183,121,31,.08);border-color:rgba(183,121,31,.35)}",
    ".mbar{display:flex;height:14px;border-radius:7px;overflow:hidden;margin:6px 0 4px;background:rgba(135,150,163,.18)}.mbar i{display:block;height:100%}",
    ".mleg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;margin:0 0 12px;color:var(--muted,#5b7183)}.mleg span{display:inline-flex;align-items:center;gap:5px}",
    ".mleg i{width:10px;height:10px;border-radius:3px;display:inline-block}",
    ".mcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:0 0 14px}",
    ".mcard{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-radius:12px;padding:12px 16px}",
    ".mcard h4{margin:0 0 8px;font-size:13px;color:var(--muted,#5b7183);font-weight:600;text-transform:uppercase;letter-spacing:.03em}",
    ".mcard .big{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}",
    ".mrows{width:100%;border-collapse:collapse;font-size:13.5px}.mrows td{padding:4px 0;border-bottom:1px solid var(--line,#eef2f5)}",
    ".mrows td.n{text-align:right;font-variant-numeric:tabular-nums}.mrows tr.tot td{font-weight:700;border-bottom:0;border-top:2px solid var(--line,#d6dee5)}",
    ".mrows a{color:inherit}",
    ".mr{color:#c0392b}.mg{color:#2f7a4d}",
    ".mchip{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;color:#fff;white-space:nowrap}",
  ].join("\n");
  document.head.append(css);

  const tile = (v, l, cls, sub, onclick) => h("div", { class: "t " + (cls || "") + (onclick ? " click" : ""), onclick }, h("b", {}, v), h("span", {}, l), sub ? h("small", {}, sub) : null);
  const chip = (m) => h("span", { class: "mchip", style: "background:" + (COL[m] || "#8796a3") }, lab(m));
  function stack(parts) {
    const tot = parts.reduce((a, p) => a + Math.max(0, p.v), 0) || 1;
    return h("div", {}, h("div", { class: "mbar" }, parts.filter((p) => p.v > 0).map((p) => h("i", { style: "width:" + (100 * p.v / tot) + "%;background:" + (COL[p.k] || "#8796a3"), title: lab(p.k) + ": " + money(p.v) }))),
      h("div", { class: "mleg" }, parts.filter((p) => Math.abs(p.v) > 0.004).map((p) => h("span", {}, h("i", { style: "background:" + (COL[p.k] || "#8796a3") }), lab(p.k) + " " + Math.round(100 * p.v / tot) + "%"))));
  }
  function rowsTable(rows, total) {
    return h("table", { class: "mrows" }, rows.map((r) => h("tr", {}, h("td", {}, r.link ? h("a", { href: r.link }, r.label) : r.label), h("td", { class: "n" }, money(r.amount)))),
      total ? h("tr", { class: "tot" }, h("td", {}, total[0]), h("td", { class: "n" }, money(total[1]))) : null);
  }
  const pidNow = () => S.project || "";

  /* ───────────────────────── project cost & exposure ───────────────────────── */
  PAGES["mg/project"] = async (root, params) => {
    await meta();
    const pid = (params && params.project) || pidNow();
    root.append(pageHead("Project cost & exposure", "One project on the way it is really executed: cost posted and waiting for accounts, commitments, cost by way of working, exposure, delays and the return on the money it ties up."));
    if (!pid) { root.append(projectNotice()); return; }
    let filt = { as_of: today() };
    const holder = h("div");
    const load = async () => {
      const d = await run("mg.project", { project_id: pid, as_of: filt.as_of });
      const e = d.evm;
      holder.innerHTML = "";
      if (d.project.kind && d.project.kind !== "project") holder.append(h("div", { class: "mnote warn" }, d.project.code + " is a " + d.project.kind + " cost centre, not a construction project. See Accounts › Finance by segment."));
      holder.append(h("div", { class: "mt" },
        tile(money(e.earned_revenue), "Earned value (work done at contract rates)", "", pct(e.progress_value_pct) + " of contract"),
        tile(money(e.ac_posted), "Cost posted", "grey"),
        tile(money(e.waiting), "Waiting for accounts", e.waiting > 0 ? "warn" : "good", d.waiting_entries + (d.waiting_entries === 1 ? " entry" : " entries") + " approved by site, not yet posted", () => { location.hash = "#/x/queue"; }),
        tile(money(e.ac), "Cost to date (posted + waiting)", "", e.eq_costing === "rate" ? "Own machines at rate per hour" : null),
        tile(money(e.eac), "Forecast final cost", "", "Still to spend " + money(e.etc)),
        tile(money(e.forecast_profit), "Forecast profit", e.forecast_profit < 0 ? "bad" : "good", "Margin " + pct(e.forecast_margin) + (e.tender_margin != null ? " · tender " + pct(e.tender_margin) : "")),
        tile(money(e.committed), "Committed, not yet billed", "", "Purchase orders " + money(e.committed_po) + " · subcontracts " + money(e.committed_sc)),
        tile(e.cpi == null ? "—" : n1(e.cpi), "Cost performance (CPI)", e.cpi != null && e.cpi < 0.95 ? "bad" : "good", "Earned ÷ cost on BOQ items")));
      if (!d.kpi_waiting) holder.append(h("div", { class: "mnote" }, "Waiting entries are not counted in project cost on this computer's settings (Accounts › Costs by way of working › Settings)."));
      // ways of working
      const modes = d.modes.filter((m) => m.mode !== "untagged" || Math.abs(m.amount) > 0);
      holder.append(h("h3", {}, "Cost by way of working"), stack(modes.map((m) => ({ k: m.mode, v: m.amount }))),
        table([{ label: "Way of working", v: (r) => chip(r.mode) }, { k: "amount", label: "Cost to date", fmt: "money" }, { k: "waiting", label: "of which waiting", fmt: "money" },
          { label: "Share", v: (r) => pct(r.share_pct) }],
        modes, { name: "project_cost_by_way", totals: ["amount", "waiting"], search: false,
          onRow: (r) => linesDialog({ project_id: pid, mode: r.mode, from: "0000-01-01", to: filt.as_of }, lab(r.mode) + " — " + d.project.code),
          empty: "No cost booked to this project yet." }));
      if (d.plan && d.plan.length) {
        holder.append(h("p", { class: "hint", style: "margin:6px 0 2px" }, "Planned split of the work (Execution plan, by contract value):"),
          h("div", { class: "mleg" }, d.plan.map((p) => h("span", {}, h("i", { style: "background:" + ({ direct: COL.direct_labour, labour_sc: COL.labour_sc, supplied_sc: COL.supplied_sc, b2b_sc: COL.b2b_sc }[p.mode] || "#c9d2d9") }),
            ({ direct: "Direct", labour_sc: "Labour supply", supplied_sc: "Item rate, our material", b2b_sc: "Back-to-back", unplanned: "Not planned" }[p.mode] || p.mode) + " " + pct(p.share_pct)))));
      }
      // exposure, delays, capital
      const ex = d.exposure.filter((x) => Math.abs(x.amount) > 0.004);
      const dl = d.delays;
      const cap = d.capital;
      holder.append(h("div", { class: "mcols" },
        h("div", { class: "mcard" }, h("h4", {}, "Exposure"), ex.length ? rowsTable(ex) : h("p", { class: "muted" }, "Nothing outstanding."),
          h("p", { class: "hint" }, "Money out with others: recover it in their next bill or collect it.")),
        dl ? h("div", { class: "mcard" }, h("h4", {}, "Delays in money"),
          rowsTable([{ label: "Employer delay (days)", amount: dl.employer_days }, { label: "Idle machines on employer-delay days (claimable)", amount: dl.claimable_idle_cost },
            { label: "Prolongation cost of employer delay", amount: dl.prolongation_cost }, { label: "Cost claimed in events", amount: dl.claimed_cost },
            { label: "Own delay (days)", amount: dl.own_days }, { label: "Liquidated damages exposure (own delay)", amount: dl.ld_exposure }]),
          h("p", { class: "hint" }, h("a", { href: "#/x/delays" }, "Delays by responsibility"), " has the detail.")) : null,
        h("div", { class: "mcard" }, h("h4", {}, "Money tied up in the project"), rowsTable(cap.assets.filter((x) => Math.abs(x.amount) > 0.004), ["Assets employed", cap.gross]),
          h("div", { style: "height:6px" }), rowsTable(cap.less.filter((x) => Math.abs(x.amount) > 0.004).map((x) => ({ label: "less " + x.label.toLowerCase(), amount: x.amount })), ["Net capital employed", cap.net]),
          h("div", { class: "mt", style: "margin:10px 0 0" },
            tile(money(d.return.margin_to_date), "Margin to date", d.return.margin_to_date < 0 ? "bad" : "good", "Earned value less cost, " + n1(d.return.months) + " months"),
            tile(pct(d.return.roce_pct), "Return on capital employed a year", d.return.roce_pct != null && d.return.roce_pct < 0 ? "bad" : "good", "ROA on assets employed " + pct(d.return.roa_pct))))));
      if (e.eq_costing === "rate") holder.append(h("div", { class: "mnote" }, "Own machines are costed at their rate per hour: charged " + money(e.own_eq_charged) + " instead of running costs booked here " + money(e.own_eq_actual) + " (difference " + money(e.own_eq_adjustment) + "). Equipment › Own equipment recovery shows each machine."));
    };
    root.append(filterBar([{ k: "as_of", label: "As at", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────────────── lines behind a figure (and retagging) ───────────────────────── */
  async function linesDialog(args, title, after) {
    const d = await run("mg.lines", Object.assign({ include_waiting: 1 }, args));
    const editable = can("accounts", "edit");
    const pick = new Set();
    const cols = [];
    if (editable) cols.push({ label: "", v: (r) => h("input", { type: "checkbox", onclick: (ev) => { ev.stopPropagation(); if (ev.target.checked) pick.add(r.id); else pick.delete(r.id); } }) });
    cols.push({ k: "date", label: "Date" }, { label: "Voucher", v: (r) => r.waiting ? h("span", { class: "muted" }, "waiting") : drillTo("voucher", r.voucher_id, r.no) },
      { label: "Account", v: (r) => r.acode + " " + r.aname }, { k: "pcode", label: "Project" }, { label: "Narration", v: (r) => r.narration || r.vnar || "" },
      { label: "Way of working", v: (r) => r.mode ? chip(r.mode) : chip("untagged") }, { label: "Set by", v: (r) => ({ auto: "BuildCore", manual: "Accounts", backfill: "Back-fill" }[r.how] || "—") },
      { k: "amount", label: "Amount", fmt: "money" });
    const sel = h("select", {}, h("option", { value: "" }, "— choose —"), (META.modes || []).map(([k, l]) => h("option", { value: k }, l)));
    const body = h("div", {}, h("p", { class: "hint" }, d.count + " lines, total " + money(d.total) + (d.count > d.rows.length ? " (first " + d.rows.length + " shown)" : "")),
      table(cols, d.rows, { name: "cost_lines", totals: ["amount"] }),
      editable ? h("div", { class: "bar", style: "margin-top:8px" }, h("span", {}, "Change the way of working of the ticked lines to "), sel) : null);
    modal(title, body, editable ? [{ label: "Change", cls: "primary", act: async () => {
      if (!pick.size) { toast("Tick the lines first.", "err"); return false; }
      if (!sel.value) { toast("Choose the way of working.", "err"); return false; }
      await run("mg.retag", { line_ids: Array.from(pick), mode: sel.value }, (x) => x.tagged + " lines changed. Amounts and accounts are untouched.");
      if (after) after();
    } }] : [], {});
  }

  /* ───────────────────────── accounts: costs by way of working ───────────────────────── */
  PAGES["mg/modes"] = async (root) => {
    await meta(true);
    let filt = { from: META.fy_from, to: today(), segment: "", project_id: "", include_waiting: 1 };
    const holder = h("div");
    const load = async () => {
      const d = await run("mg.modes", filt);
      holder.innerHTML = "";
      const cols = d.cols;
      holder.append(h("div", { class: "mt" }, tile(money(d.total), "Cost in the period" + (d.include_waiting ? " (with waiting)" : "")),
        cols.map((m) => tile(money(d.totals[m]), lab(m), m === "untagged" ? "grey" : "", d.waiting[m] ? "waiting " + money(d.waiting[m]) : null,
          () => linesDialog({ from: d.from, to: d.to, segment: filt.segment, project_id: filt.project_id, mode: m, include_waiting: filt.include_waiting }, lab(m), load)))),
      stack(cols.map((m) => ({ k: m, v: d.totals[m] || 0 }))));
      const cell = (scope) => (m) => ({ label: lab(m), fmt: "money", k: "m_" + m, v: (r) => (r.by[m] || 0) || null, _m: m, _s: scope });
      const accRows = d.accounts.map((r) => Object.assign({}, r, Object.fromEntries(cols.map((m) => ["m_" + m, r.by[m] || 0]))));
      holder.append(h("h3", {}, "By account"),
        table([{ label: "Account", v: (r) => r.code + " " + r.name }].concat(cols.map(cell("a"))).concat([{ k: "total", label: "Total", fmt: "money" }]),
          accRows, { name: "cost_by_account_and_way", totals: cols.map((m) => "m_" + m).concat(["total"]),
            onRow: (r) => linesDialog({ from: d.from, to: d.to, segment: filt.segment, project_id: filt.project_id, account_id: r.account_id, include_waiting: filt.include_waiting }, r.code + " " + r.name, load) }));
      const prRows = d.projects.map((r) => Object.assign({}, r, Object.fromEntries(cols.map((m) => ["m_" + m, r.by[m] || 0]))));
      holder.append(h("h3", {}, "By project and cost centre"),
        table([{ label: "Project / cost centre", v: (r) => (r.code || "—") + " " + (r.name || "") }, { label: "Segment", v: (r) => SEGL[r.segment] || r.segment }].concat(cols.map(cell("p"))).concat([{ k: "total", label: "Total", fmt: "money" }]),
          prRows, { name: "cost_by_project_and_way", totals: cols.map((m) => "m_" + m).concat(["total"]),
            onRow: (r) => linesDialog({ from: d.from, to: d.to, project_id: r.project_id || "", include_waiting: filt.include_waiting }, (r.code || "") + " " + (r.name || ""), load) }));
      holder.append(h("p", { class: "hint" }, "Every ledger line carries its way of working, set by BuildCore from the source document (subcontract bill and its work-order type, hire bill, DPR, store issue, machine). Accounts can change it line by line: click a figure, tick the lines, choose. Amounts and accounts never change. Internal hire of own machines is netted against own-equipment cost, as in project cost."));
    };
    const segOpts = [["", "All segments"]].concat((META.segments || []).map(([k, l]) => [k, l]));
    root.append(pageHead("Costs by way of working", "The books read the way the work is done: direct labour, labour-supply, item-rate and back-to-back subcontracts, our material, own and rented equipment.",
      can("accounts", "view") ? h("button", { class: "btn", onclick: () => settingsDialog(load) }, "Settings & back-fill") : null));
    if (META.legacy_untagged > 0) root.append(h("div", { class: "mnote" }, META.legacy_untagged + " cost lines posted before 2.23 are not tagged yet. ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); settingsDialog(load); } }, "Preview the back-fill"), " to tag them the same way (you approve it; it can be undone)."));
    root.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" },
      { k: "segment", label: "Segment", type: "select", options: segOpts, noBlank: true },
      { k: "project_id", label: "Project / cost centre", type: "select", options: () => (S.L && S.L.projects ? S.L.projects.map((p) => [p.id, p.code + " " + p.name]) : []), blank: "All" },
      { k: "include_waiting", label: "Include entries waiting for accounts", type: "check" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  async function settingsDialog(after) {
    const m = await meta(true);
    const pv = await run("mg.backfill_preview", {});
    const approve = can("accounts", "approve");
    const f = form([{ k: "kpi_waiting", label: "Count entries waiting for accounts in project cost and KPIs", type: "check", readonly: !approve },
      { k: "eq_costing", label: "Own machines in project cost", type: "select", noBlank: true, readonly: !approve,
        options: [["actual", "Running costs booked to the project (as before)"], ["rate", "Rate per hour from logsheets (equipment pool)"]] }],
    { kpi_waiting: m.kpi_waiting ? 1 : 0, eq_costing: m.eq_costing });
    const body = h("div", { style: "max-width:640px" }, h("h3", {}, "Settings"), f,
      h("p", { class: "hint" }, "Rate per hour: each project carries its own machines at the internal rate for the hours worked; the fuel, repairs and depreciation of own machines stay with the equipment pool (Equipment › Own equipment recovery). Nothing is posted either way."),
      h("h3", {}, "Back-fill lines posted before 2.23"),
      pv.rows.length ? table([{ label: "Way of working", v: (r) => chip(r.mode) }, { k: "lines", label: "Lines", fmt: "qty" }, { k: "amount", label: "Cost", fmt: "money" }], pv.rows, { search: false, export: false })
        : h("p", { class: "muted" }, pv.backfilled ? pv.backfilled + " older lines are already back-filled." : "No older lines to tag."),
      h("p", { class: "hint" }, "Back-fill applies the same rules to older lines. Only the tags are written; no voucher, amount or balance changes. Undo removes the back-filled tags again (tags set by hand stay)."));
    const btns = [];
    if (approve) {
      btns.push({ label: "Save settings", cls: "primary", act: async () => { const v = f.values(); await run("mg.settings_save", { kpi_waiting: v.kpi_waiting, eq_costing: v.eq_costing }, "Saved"); META = null; if (after) after(); } });
      if (pv.rows.length) btns.push({ label: "Tag " + pv.lines + " older lines", act: async () => { await run("mg.backfill_apply", {}, (x) => x.tagged + " lines tagged"); META = null; if (after) after(); } });
      if (pv.backfilled) btns.push({ label: "Undo back-fill", cls: "warn", act: async () => { await run("mg.backfill_undo", {}, (x) => x.removed + " back-filled tags removed"); META = null; if (after) after(); } });
    }
    modal("Costs by way of working — settings", body, btns, {});
  }

  /* ───────────────────────── finance by segment ───────────────────────── */
  PAGES["mg/segments"] = async (root) => {
    await meta();
    let filt = { from: META.fy_from, to: today() };
    const holder = h("div");
    const load = async () => {
      const d = await run("mg.segments", filt);
      holder.innerHTML = "";
      const tot = d.segments.reduce((a, s) => a + s.profit, 0);
      holder.append(h("div", { class: "mt" }, tile(money(tot), "Profit, all segments (posted)", tot < 0 ? "bad" : "good", "Same as Profit & loss"),
        d.segments.map((s) => tile(money(s.profit), s.label, s.profit < 0 ? "bad" : "good", "Margin " + pct(s.margin_pct) + " · waiting " + money(s.waiting))),
        d.company ? tile(pct(d.company.roe_pct), "Return on equity (company)", d.company.roe_pct != null && d.company.roe_pct < 0 ? "bad" : "good", "ROA " + pct(d.company.roa_pct) + (d.company.annualised ? " · annualised" : "")) : null));
      holder.append(h("div", { class: "mcols" }, d.segments.map((s) => h("div", { class: "mcard" }, h("h4", {}, s.label),
        rowsTable([{ label: "Income", amount: s.income }, { label: "less cost", amount: s.cost }], ["Profit (posted)", s.profit]),
        Math.abs(s.waiting) > 0.004 ? h("p", { class: "hint" }, "Plus " + money(s.waiting) + " of cost waiting for accounts.") : null,
        Object.keys(s.modes).length ? stack(ORDER.filter((k) => k in s.modes).map((k) => ({ k, v: s.modes[k] }))) : null,
        h("div", { style: "height:6px" }),
        rowsTable(s.balance.assets.filter((x) => Math.abs(x.amount) > 0.004), ["Assets employed", s.balance.gross]),
        h("div", { style: "height:4px" }),
        rowsTable(s.balance.liabilities.filter((x) => Math.abs(x.amount) > 0.004).map((x) => ({ label: "less " + x.label.toLowerCase(), amount: x.amount })), ["Net capital employed", s.balance.net]),
        h("div", { class: "mt", style: "margin:10px 0 0" }, tile(pct(s.roa_pct), "Return on assets employed", s.roa_pct != null && s.roa_pct < 0 ? "bad" : ""),
          tile(pct(s.roce_pct), "Return on capital employed", s.roce_pct != null && s.roce_pct < 0 ? "bad" : "")))) ));
      const t = d.trading;
      holder.append(h("h3", {}, "Trading"), h("div", { class: "mt" }, tile(money(t.net_sales), "Net sales", "", "Returns " + money(t.returns)), tile(money(t.cogs), "Cost of goods sold", "grey"),
        tile(money(t.gross_profit), "Gross profit", t.gross_profit < 0 ? "bad" : "good", "GP " + pct(t.gp_pct)), tile(money(t.stock), "Trading stock", "", "Turns " + n1(t.turns) + " a year · " + n1(t.days_on_hand) + " days on hand")));
      holder.append(h("h3", {}, "Projects compared"),
        table([{ k: "code", label: "Project" }, { k: "name", label: "Name" }, { k: "earned", label: "Earned value", fmt: "money" }, { k: "cost", label: "Cost (with waiting)", fmt: "money" },
          { k: "margin", label: "Margin to date", fmt: "money" }, { label: "Forecast margin", v: (r) => pct(r.forecast_margin) }, { k: "committed", label: "Committed", fmt: "money" },
          { k: "capital_net", label: "Net capital employed", fmt: "money" },
          { label: "Return a year", v: (r) => r.roce_pct == null ? "—" : h("b", { class: r.roce_pct < 0 ? "mr" : "mg" }, pct(r.roce_pct)) }],
        d.projects, { name: "projects_return", totals: ["earned", "cost", "margin", "committed", "capital_net"], onRow: (r) => { location.hash = "#/mg/project?project=" + r.id; } }));
      holder.append(h("p", { class: "hint" }, "Profit is from the posted ledger; costs waiting for accounts are shown beside it. Segment: projects are construction projects, trading is the trading cost centre (2.19), company is head office, the central store and anything without a project. Internal hire of own machines is netted against cost. Return a year: margin to date per year of the project's life over the money it ties up today (work done not billed, receivables, retention, stock, material with subcontractors, advances, own machines and small assets at site, less payables and advances received)."));
    };
    root.append(pageHead("Finance by segment", "Projects, trading and company side by side: profit, waiting costs, money employed and return; every project's return on the money it ties up."));
    root.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────────────── stock by segment ───────────────────────── */
  PAGES["mg/stores"] = async (root) => {
    await meta();
    let filt = { from: META.fy_from, to: today() };
    const holder = h("div");
    const load = async () => {
      const d = await run("mg.stores", filt);
      holder.innerHTML = "";
      holder.append(h("div", { class: "mt" }, d.segments.map((s) => tile(money(s.value), s.label + " stock", s.segment === "trading" ? "warn" : "",
        s.stores + " stores · issued " + money(s.issued) + " · turns " + n1(s.turns) + (s.with_subcontractors ? " · with subcontractors " + money(s.with_subcontractors) : "")))));
      holder.append(h("h3", {}, "Stores"),
        table([{ k: "pcode", label: "Project / cost centre" }, { label: "Segment", v: (r) => SEGL[r.segment] }, { k: "store", label: "Store" }, { k: "items", label: "Items", fmt: "qty" },
          { k: "value", label: "Stock value", fmt: "money" }, { k: "issued", label: "Issued in period", fmt: "money" }, { label: "Turns a year", v: (r) => n1(r.turns) }, { label: "Days on hand", v: (r) => n1(r.days_on_hand) }],
        d.stores.filter((r) => r.value || r.issued), { name: "stock_by_segment", totals: ["value", "issued"], empty: "No stock yet." }));
      holder.append(h("h3", {}, "Material with subcontractors"),
        table([{ k: "pcode", label: "Project" }, { k: "pname", label: "Name" }, { k: "value", label: "Value at our cost", fmt: "money" }],
          d.with_subcontractors, { name: "material_with_subcontractors", totals: ["value"], search: false, empty: "No material is out with subcontractors.", onRow: () => { location.hash = "#/x/sub"; } }));
      const t = d.trading;
      holder.append(h("p", { class: "hint" }, "Trading: net sales " + money(t.net_sales) + ", cost of sales " + money(t.cogs) + ", gross profit " + money(t.gross_profit) + " (" + pct(t.gp_pct) + "). Trading stock never counts in project material cost; project stock never counts in trading."));
    };
    root.append(pageHead("Stock by segment", "Project stores, the trading store, the central store and material lying with subcontractors, with turnover and days on hand."));
    root.append(filterBar([{ k: "from", label: "Issues from", type: "date" }, { k: "to", label: "As at", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────────────── own equipment recovery ───────────────────────── */
  PAGES["mg/eqpool"] = async (root) => {
    await meta(true);
    let filt = { from: META.fy_from, to: today() };
    const holder = h("div");
    const load = async () => {
      const d = await run("mg.eqpool", filt);
      holder.innerHTML = "";
      holder.append(h("div", { class: "mt" }, tile(money(d.totals.economic_cost), "Own machines cost (economic)", "grey", "Running cost + depreciation + loan interest"),
        tile(money(d.totals.charged), "Charged to projects at rate", ""), tile(money(d.totals.over_under), d.totals.over_under >= 0 ? "Over-recovered" : "Under-recovered", d.totals.over_under >= 0 ? "good" : "bad"),
        tile(d.eq_costing === "rate" ? "Rate per hour" : "Running costs", "Project cost uses", "", can("accounts", "approve") ? "Change in Settings" : null, can("accounts", "view") ? () => settingsDialog(load) : null)));
      holder.append(h("h3", {}, "Machines"),
        table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "hours", label: "Hours", fmt: "qty" }, { label: "Utilisation", v: (r) => pct(r.utilisation_pct) },
          { k: "rate", label: "Rate per hour", fmt: "money" }, { k: "economic_cost", label: "Cost (economic)", fmt: "money" }, { k: "charged", label: "Charged to projects", fmt: "money" },
          { label: "Over / under", v: (r) => h("b", { class: r.over_under < 0 ? "mr" : "mg" }, money(r.over_under)) }, { label: "Recovered", v: (r) => pct(r.recovery_pct) }],
        d.machines, { name: "own_equipment_recovery", totals: ["economic_cost", "charged"], empty: "No owned machines." }));
      holder.append(h("h3", {}, "Projects"),
        table([{ k: "pcode", label: "Project" }, { k: "pname", label: "Name" }, { k: "at_rate", label: "Own machines at rate", fmt: "money" }, { k: "actual_booked", label: "Running costs booked there", fmt: "money" },
          { k: "difference", label: "Difference", fmt: "money" }], d.projects, { name: "own_equipment_by_project", totals: ["at_rate", "actual_booked", "difference"], search: false, empty: "No own-machine costs in this period." }));
      holder.append(h("p", { class: "hint" }, "Under-recovery means the rate per hour is too low for what the machine really costs, or the machine stood idle; over-recovery means projects paid more than the machine cost. Rates come from Equipment › Rate cards; cost per hour from Equipment cost per hour."));
    };
    root.append(pageHead("Own equipment recovery", "What every owned machine cost against what it charged the projects at its rate per hour."));
    root.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────── company-only screens stay out of the Project Workspace ───────────────── */
  const CO_ONLY = ["mg/segments", "mg/stores", "mg/eqpool"];
  const projWs = () => !!(S.user && S.user.workspace && S.user.workspace.active === "project");
  CO_ONLY.forEach((p) => {
    const f = PAGES[p];
    PAGES[p] = async (root, params) => {
      if (projWs()) {
        root.append(pageHead("Company screen"), h("div", { class: "panel" }, h("b", {}, "This screen belongs to the Company Workspace."),
          h("p", { class: "muted" }, "It shows the whole company. Switch to the Company Workspace to open it.")));
        return;
      }
      return f(root, params);
    };
  });
  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    if (typeof window.renderNav === "function" && !window.renderNav._bco223) {
      const orig = window.renderNav;
      const rn = function () {
        try {
          if (projWs() && typeof MENU !== "undefined") MENU.forEach((g) => { g[2] = g[2].filter((it) => !CO_ONLY.includes(it[0])); });
        } catch (e) { /* ignore */ }
        return orig.apply(this, arguments);
      };
      rn._bco223 = true;
      Object.keys(orig).forEach((k) => { try { rn[k] = orig[k]; } catch (e) { /* ignore */ } });
      window.renderNav = rn;
      try { renderNav = rn; } catch (e) { /* ignore */ } // eslint-disable-line no-global-assign
    }
  });

  /* What's new */
  function whatsNew() {
    if (LSg("bco_seen_" + VER, "")) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_" + VER, "1");
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:600px" },
      h("p", {}, "Accounts, project KPIs and finance now read the books the way the work is done."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("Costs by way of working (Accounts).", "Every ledger line is tagged: direct labour, labour-supply, item-rate or back-to-back subcontract, our material, own or rented equipment. Click any figure to see the lines; accounts can correct a tag."),
        li("Project cost includes what is waiting for accounts.", "Dashboards, earned value and margins count approved site costs that accounts has not posted yet, shown separately. Commitments include unbilled subcontract work orders."),
        li("Project cost & exposure (Commercial).", "Cost by way of working against the execution plan, material with subcontractors, advances, retention, delay money and the return on the money the project ties up."),
        li("Finance by segment (Accounts).", "Projects, trading and company side by side, with return on assets employed and company ROE. Trading and company cost centres no longer show as projects on dashboards."),
        li("Stock by segment (Inventory) and Own equipment recovery (Equipment).", "Project, trading and central stock; machines' cost against what they charged.")),
      h("p", { class: "hint" }, "No entry, account or balance changed. Lines posted before today can be tagged from Accounts › Costs by way of working › Settings & back-fill.")),
    [{ label: "Open Costs by way of working", cls: "primary", act: () => { location.hash = "#/mg/modes"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 4200); } }, 900);
})();
