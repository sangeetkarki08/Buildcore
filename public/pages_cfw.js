/* BuildCore 2.27 — thirteen-week rolling cash forecast.
   One new tab on Accounts › Cash forecast & ratios, after the three that are there. The menu is unchanged. */
(function () {
  "use strict";
  if (window.__bcoCfw) return;
  window.__bcoCfw = true;

  const css = h("style", {}, ".cfw-wrap{overflow-x:auto}.cfw{border-collapse:collapse;font-size:12px;min-width:100%}.cfw th,.cfw td{padding:4px 6px;border-bottom:1px solid #e5e9ef;white-space:nowrap}" +
    ".cfw th{position:sticky;top:0;background:#f6f8fb;text-align:right}.cfw th:first-child,.cfw td:first-child{text-align:left;position:sticky;left:0;background:#fff;min-width:260px;white-space:normal}" +
    ".cfw td{text-align:right}.cfw tr.sec td{background:#f6f8fb;font-weight:600}.cfw tr.tot td{font-weight:600;border-top:1px solid #9aa7b5}.cfw tr.bal td{font-weight:700}" +
    ".cfw td.neg{color:#b42318}.cfw tr.click:hover td{background:#f0f5fb}.cfw .conf{font-size:10px;padding:1px 5px;border-radius:8px;margin-left:6px}" +
    ".conf.confirmed{background:#e3f4e8;color:#1e6b34}.conf.likely{background:#e6f0fb;color:#1b4f86}.conf.estimate{background:#f1f1f1;color:#555}.conf.uncertain{background:#fff1d6;color:#8a5300}" +
    ".cfw-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin:8px 0 12px}.cfw-card{border:1px solid #dde3ea;border-radius:8px;padding:8px 10px;background:#fff}" +
    ".cfw-card b{display:block;font-size:15px;margin-top:2px}.cfw-card small{color:#667}.cfw-card.bad{border-color:#f2b8b5;background:#fdf3f2}.cfw-card.ok{border-color:#b7dfc3;background:#f1f9f3}");
  document.head.append(css);

  const M = (n) => (n == null ? "" : fmtMoney(n));
  const K = (n) => (n == null ? "" : (n / 1e5).toFixed(2) + " L");
  const card = (l, v, sub, cls) => h("div", { class: "cfw-card " + (cls || "") }, h("small", {}, l), h("b", {}, v), sub ? h("small", {}, sub) : "");
  const dshort = (s) => { const d = new Date(s + "T00:00:00"); return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };
  let state = { scenario: "base", delay: 15, overrun: 0, lakh: true };

  async function forecastTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("cfw.forecast", { scenario: state.scenario, delay: state.delay, overrun: state.overrun });
      box.innerHTML = "";
      const fm = state.lakh ? K : M;
      const sel = h("select", { style: "width:auto" }, d.scenario_list.map(([k, l]) => h("option", { value: k, selected: k === state.scenario }, l)));
      const dl = h("input", { type: "number", value: state.delay, style: "max-width:80px" });
      const ov = h("input", { type: "number", value: state.overrun, style: "max-width:80px" });
      const custom = h("span", { style: state.scenario === "custom" ? "" : "display:none" }, " receipts late by ", dl, " days, costs over by ", ov, " % ");
      sel.onchange = () => { custom.style.display = sel.value === "custom" ? "" : "none"; };
      const lk = h("input", { type: "checkbox", checked: state.lakh });
      box.append(h("div", { class: "bar" }, h("b", {}, "Scenario "), sel, custom,
        h("button", { class: "btn primary", onclick: () => { state = Object.assign(state, { scenario: sel.value, delay: Number(dl.value) || 0, overrun: Number(ov.value) || 0 }); load(); } }, "Show"),
        h("label", { style: "margin-left:12px" }, lk, " amounts in lakh"), h("div", { class: "grow" }),
        d.can_edit ? h("button", { class: "btn", onclick: () => itemsModal(load) }, "Items entered by hand") : null,
        d.can_edit ? h("button", { class: "btn", onclick: () => restrictedModal(load) }, "Restricted funds") : null,
        d.can_edit ? h("button", { class: "btn", onclick: async () => { const l = await ask("Save this forecast", "Saved forecasts are compared later with the cash that actually moved.", { input: "Name (optional)", ok: "Save" }); if (l === null) return; await run("cfw.snapshot_save", { label: l, scenario: state.scenario, delay: state.delay, overrun: state.overrun }, "Forecast saved"); } }, "Save forecast") : null,
        h("button", { class: "btn", onclick: () => snapshotsModal() }, "Forecast vs actual")));
      lk.onchange = () => { state.lakh = lk.checked; load(); };
      const last = d.weeks[d.weeks.length - 1];
      box.append(h("div", { class: "cfw-strip" },
        card("Cash and bank today", M(d.opening)),
        card("Lowest closing", M(d.lowest.closing), "week " + d.lowest.week + " (" + dshort(d.lowest.start) + ")", d.lowest.closing < d.reserve ? "bad" : ""),
        card("Closing in week 13", M(last.closing)),
        card("Funding gap", d.first_gap ? M(d.max_gap) : "None", d.first_gap ? "from week " + d.first_gap : "after reserve " + M(d.reserve) + " and restricted funds", d.first_gap ? "bad" : "ok"),
        card("Prudent view", d.prudent_first_gap ? "Gap " + M(d.prudent_max_gap) : "No gap", "only confirmed and likely receipts; lowest " + M(d.prudent_lowest), d.prudent_first_gap ? "bad" : "ok")));
      /* grid */
      const head = h("tr", {}, h("th", {}, "Week"), d.weeks.map((w) => h("th", { title: w.start + " to " + w.end }, "W" + w.week + " " + dshort(w.start))), h("th", {}, "13 weeks"));
      const body = h("tbody");
      const rowEl = (label, vals, total, cls, onclick, badge) => h("tr", { class: (cls || "") + (onclick ? " click" : ""), onclick }, h("td", {}, label, badge || ""),
        vals.map((v) => h("td", { class: v < -0.5 && cls && cls.includes("bal") ? "neg" : "" }, v ? fm(v) : "–")), h("td", {}, total == null ? "" : fm(total)));
      body.append(rowEl("Opening balance", d.weeks.map((w) => w.opening), null, "bal"));
      for (const kind of ["in", "out"]) {
        body.append(h("tr", { class: "sec" }, h("td", { colspan: 15 }, kind === "in" ? "Money in" : "Money out")));
        d.lines.filter((l) => l.kind === kind).forEach((l) => body.append(rowEl(l.label, l.values, l.total, "", () => drill(l), h("span", { class: "conf " + l.confidence }, l.confidence_label))));
        body.append(rowEl(kind === "in" ? "Total in" : "Total out", d.weeks.map((w) => w[kind]), d.weeks.reduce((a, w) => a + w[kind], 0), "tot"));
      }
      body.append(rowEl("Net cash flow", d.weeks.map((w) => w.net), d.weeks.reduce((a, w) => a + w.net, 0), "tot"));
      body.append(rowEl("Closing balance", d.weeks.map((w) => w.closing), null, "bal"));
      body.append(rowEl("Kept back: reserve", d.weeks.map((w) => -w.reserve), null, ""));
      body.append(rowEl("Kept back: restricted funds", d.weeks.map((w) => -w.restricted), null, ""));
      body.append(rowEl("Available to spend", d.weeks.map((w) => w.available), null, "bal"));
      body.append(rowEl("Prudent closing (confirmed and likely receipts only)", d.weeks.map((w) => w.prudent_closing), null, "bal"));
      box.append(h("div", { class: "cfw-wrap" }, h("table", { class: "cfw" }, h("thead", {}, head), body)));
      box.append(h("h3", {}, "Scenarios"), table([{ k: "label", label: "Scenario" }, { label: "Lowest closing", fmt: "money", v: (r) => r.lowest.closing }, { label: "Lowest in week", v: (r) => r.lowest.week },
        { label: "Closing week 13", fmt: "money", v: (r) => r.closing }, { label: "Funding gap from week", v: (r) => r.first_gap || "none" }, { k: "max_gap", label: "Largest gap", fmt: "money" }, { k: "prudent_max_gap", label: "Largest gap (prudent)", fmt: "money" }],
      d.scenarios, { search: false, name: "cash_scenarios", rowClass: (r) => (r.first_gap ? "bad" : "") }));
      box.append(h("p", { class: "hint" }, "Confirmed: certified bills, promised receipts, supplier and subcontract bills, wages, VAT and TDS, instalments, approved payment requests. Likely: IPCs awaiting certification, retention due, purchase-order deliveries, requests in the chain. Estimate: future work and overhead from the schedule and terms (monthly, spread over the weeks). Uncertain: overdue receivables with no promised date, assumed collected " + d.overdue_days + " days from today. Overdue payments are shown in week 1." + (d.notes.length ? " " + d.notes.join("; ") : "")));
    };
    await load();
    return box;
  }

  function drill(l) {
    drawer(l.label + " (" + l.confidence_label + ")", h("div", {},
      table([{ k: "week", label: "Week" }, { k: "date", label: "Due or expected" }, { k: "ref", label: "Reference" }, { label: "Project", v: (r) => (r.project_id ? nm.pcode(r.project_id) : "") }, { k: "amount", label: "Amount", fmt: "money" }],
        l.items, { name: "cash_line", totals: ["amount"] })), []);
  }

  async function itemsModal(reload) {
    const rows = await api("cfw.items", {});
    const f = form([{ k: "date", label: "Date", type: "date", req: true }, { k: "kind", label: "Money", type: "select", noBlank: true, options: [["in", "In"], ["out", "Out"]] },
      { k: "amount", label: "Amount", type: "number", req: true }, { k: "label", label: "What it is", req: true, wide: true },
      { k: "category", label: "Type", type: "select", noBlank: true, options: [["financing", "Financing (loan, overdraft, equity)"], ["capital", "Capital purchase or sale"], ["land", "Land"], ["tax", "Tax"], ["other", "Other"]] },
      { k: "confidence", label: "Confidence", type: "select", noBlank: true, options: [["confirmed", "Confirmed"], ["likely", "Likely"], ["estimate", "Estimate"], ["uncertain", "Uncertain"]] },
      { k: "project_id", label: "Project", type: "select", options: () => opt.projects() }, { k: "note", label: "Note", wide: true }], { date: today(), kind: "in", category: "financing", confidence: "likely" });
    modal("Items entered by hand", h("div", {}, h("p", { class: "hint" }, "For money no document shows yet: a loan or overdraft drawdown, an equity injection, a land or machine purchase. Financing is never delayed by the late-receipt scenarios."), f,
      table([{ k: "date", label: "Date" }, { k: "kind", label: "In / out" }, { k: "label", label: "What" }, { k: "category", label: "Type" }, { k: "confidence", label: "Confidence" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "", v: (r) => h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("cfw.item_delete", { id: r.id }, "Removed"); e.target.closest(".overlay").remove(); reload(); } }, "Remove") }], rows, { search: false, export: false, empty: "None yet." })),
    [{ label: "Add", cls: "primary", act: async () => { await run("cfw.item_save", f.values(), "Added"); reload(); } }]);
  }

  async function restrictedModal(reload) {
    const rows = await api("cfw.restricted", {});
    const f = form([{ k: "name", label: "Restricted fund", req: true, wide: true }, { k: "amount", label: "Amount", type: "number", req: true },
      { k: "from_date", label: "From", type: "date" }, { k: "until_date", label: "Until", type: "date" }, { k: "account_id", label: "Held in account", type: "select", options: () => opt.money() }, { k: "note", label: "Note", wide: true }], {});
    modal("Restricted funds", h("div", {}, h("p", { class: "hint" }, "Money in the bank that cannot be spent: margin money for guarantees, escrow, a minimum balance the bank requires. It is kept back from 'available to spend' between the dates. The general reserve is in Payments & receipts › Payment plan › Payment-control settings."), f,
      table([{ k: "name", label: "Fund" }, { k: "from_date", label: "From" }, { k: "until_date", label: "Until" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "", v: (r) => h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("cfw.restricted_delete", { id: r.id }, "Removed"); e.target.closest(".overlay").remove(); reload(); } }, "Remove") }], rows, { search: false, export: false, empty: "None." })),
    [{ label: "Add", cls: "primary", act: async () => { await run("cfw.restricted_save", f.values(), "Added"); reload(); } }]);
  }

  async function snapshotsModal() {
    const rows = await api("cfw.snapshots", {});
    const out = h("div");
    const show = async (s) => {
      const d = await run("cfw.snapshot_compare", { id: s.id });
      out.innerHTML = "";
      out.append(h("h4", {}, d.snapshot.label + " (saved " + d.snapshot.ts.slice(0, 16).replace("T", " ") + " by " + (d.snapshot.user_name || "") + ")"),
        d.receipts_achieved_pct != null ? h("p", {}, "Receipts achieved in completed weeks: " + d.receipts_achieved_pct + "% of the forecast.") : h("p", { class: "hint" }, "No week of this forecast is complete yet."),
        h("p", { class: "hint" }, "The week the forecast was saved in counts only money entered after saving; its opening already holds the rest."),
        table([{ k: "week", label: "Week" }, { k: "start", label: "From" }, { k: "f_in", label: "Forecast in", fmt: "money" }, { k: "a_in", label: "Actual in", fmt: "money" }, { k: "v_in", label: "Difference", fmt: "money" },
          { k: "f_out", label: "Forecast out", fmt: "money" }, { k: "a_out", label: "Actual out", fmt: "money" }, { k: "v_out", label: "Difference", fmt: "money" }, { k: "f_closing", label: "Forecast closing", fmt: "money" }, { k: "a_closing", label: "Actual closing", fmt: "money" }],
        d.weeks, { search: false, name: "forecast_vs_actual" }));
    };
    modal("Forecast vs actual", h("div", {}, table([{ k: "label", label: "Saved forecast" }, { k: "week0", label: "Week 1 from" }, { k: "scenario", label: "Scenario" }, { k: "opening", label: "Opening", fmt: "money" }, { k: "user_name", label: "By" }, { label: "Saved", v: (r) => (r.ts || "").slice(0, 16).replace("T", " ") }],
      rows, { search: false, export: false, onRow: show, empty: "No forecast saved yet. Use 'Save forecast'." }), out), []);
  }

  /* add the tab to Accounts › Cash forecast & ratios without changing its other tabs */
  const orig = PAGES["acc/cash"];
  if (orig && !orig.__cfw) {
    const page = async (root, params) => {
      await orig(root, Object.assign({}, params, { tab: Number(params && params.tab) === 3 ? 0 : params && params.tab }));
      const bar = root.querySelector(".tabs");
      if (!bar) return;
      const body = bar.nextSibling;
      const btn = h("button", { type: "button", onclick: async () => {
        bar.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
        body.innerHTML = "";
        body.append(await forecastTab());
      } }, "13-week cash forecast");
      bar.append(btn);
      if (params && Number(params.tab) === 3) {
        /* let the first tab finish drawing, then open the forecast, so the two never land in the same place */
        let n = 0; const t = setInterval(() => { if (body.childNodes.length || ++n > 40) { clearInterval(t); btn.click(); } }, 150);
      }
    };
    page.__cfw = true;
    PAGES["acc/cash"] = page;
  }

  /* What's new */
  const VER = "2.27.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!can("accounts", "view")) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:600px" },
      h("p", {}, "Accounts › Cash forecast & ratios has a new tab: the 13-week cash forecast."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, "Week by week from today's cash and bank: bills, wages, tax, instalments and requests going out; certified bills, promises, IPCs and future work coming in."),
        h("li", {}, "Every line marked confirmed, likely, estimate or uncertain, with a prudent view that leaves out estimates."),
        h("li", {}, "Reserve and restricted funds kept back, the funding gap and the week it starts, and client receipts 15, 30 or 45 days late."),
        h("li", {}, "Save a forecast and compare it later with the cash that actually moved.")),
      h("p", { class: "hint" }, "Nothing is posted and no balance changes.")),
    [{ label: "Open the forecast", cls: "primary", act: () => { location.hash = "#/acc/cash?tab=3"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 7500); } }, 900);
})();
