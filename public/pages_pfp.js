/* BuildCore 2.39 — One project number.
   New tabs only; the menu, module names and groups are unchanged:
     Commercial › CVR and forecast ............ Project position (one figure for every screen, compare, switches)
     Equipment › Equipment cost per hour ...... Machine P&L
     Commercial › Control budget .............. From rate analysis (preview, fill only items without a line)
   The six monthly run screens show a Nepali month list when the company runs by Nepali month. */
(function () {
  "use strict";
  if (window.__bcoPfp) return;
  window.__bcoPfp = true;

  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const M = (v) => (v == null ? "—" : fmtMoney(v));
  const P = (v) => (v == null ? "—" : Number(v).toFixed(1) + "%");
  const pidNow = () => S.project || (S.P && S.P.project && S.P.project.id) || null;
  const info = (text) => h("span", { class: "hint", title: text, style: "cursor:help;margin-left:4px" }, "ⓘ");

  /* ───────── Project position ───────── */
  async function positionTab() {
    const box = h("div");
    const projects = (S.L && S.L.projects ? S.L.projects : []).filter((p) => !p.kind || p.kind === "project");
    let pid = pidNow() || (projects[0] && projects[0].id);
    const load = async () => {
      box.innerHTML = "";
      const sel = h("select", { onchange: (e) => { pid = Number(e.target.value); load(); } },
        projects.map((p) => h("option", { value: p.id, selected: String(p.id) === String(pid) }, p.code + " · " + p.name)));
      box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Project"), sel)));
      if (!pid) { box.append(h("p", { class: "hint" }, "Choose a project.")); return; }
      const [d, cmp] = await Promise.all([api("pfp.position", { project_id: pid }), api("pfp.compare", { project_id: pid }).catch(() => null)]);
      const e = d.explain || {};
      box.append(h("p", { class: "hint" }, d.switch_on
        ? "Every project screen shows these figures: Project overview, Control room, Insight, Company overview, Portfolio, Profit analysis, Project cost & exposure, Cost & earned value, CVR, Cost to complete, Command centre, League and Company health. Ledger reports keep the ledger and show this figure beside it."
        : "Not switched on yet: the screens still show their own figures. Below is what they would all show; the compare and the switch are at the bottom of this page."));
      box.append(summaryStrip([["Cost to date", M(d.cost.total)], ["Certified value", M(d.value.certified)], ["Margin to date", P(d.margin.certified_pct)],
        ["Forecast cost at completion", M(d.forecast.eac)], ["Forecast profit", M(d.forecast.profit)], ["Forecast margin", P(d.forecast.margin_pct)]]));
      box.append(h("div", { class: "grid2", style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:12px" },
        h("div", { class: "panel" }, h("h3", {}, "Cost to date", info(e.cost)), kv([["Posted", M(d.cost.posted)], ["Waiting in the accounts posting queue", M(d.cost.waiting)],
          ["Accrued at the month close", M(d.cost.accrued)], ["Total", h("b", {}, M(d.cost.total))],
          ["Labour · material · equipment", M(d.cost.labour) + " · " + M(d.cost.material) + " · " + M(d.cost.equipment)],
          ["Subcontract · other", M(d.cost.subcontract) + " · " + M(d.cost.other)]])),
        h("div", { class: "panel" }, h("h3", {}, "Value and margin", info(e.margin)), kv([["Certified (IPCs)", M(d.value.certified)], ["Measured", M(d.value.measured)],
          ["Billed (submitted and certified)", M(d.value.billed)], ["Earned (executed × rate)", M(d.value.earned)],
          ["Earned but not certified", M(d.value.earned_not_certified)],
          ["Margin on certified value", M(d.margin.certified) + " (" + P(d.margin.certified_pct) + ")"],
          ["Margin on earned value", M(d.margin.earned) + " (" + P(d.margin.earned_pct) + ")"]]))));
      box.append(h("h3", {}, "Forecast item by item", info(e.forecast)),
        h("p", { class: "hint" }, "Order: " + (d.forecast.rule || "") + ". The quantity still to do is the contract quantity less the physical progress (the larger of executed and measured)."),
        table([{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "basis", label: "Forecast basis" },
          { k: "unit_cost", label: "Unit cost", fmt: "money" }, { k: "remaining_qty", label: "Still to do", fmt: "qty" }, { k: "cost", label: "Cost to date", fmt: "money" },
          { k: "ctc", label: "Cost to complete", fmt: "money" }, { k: "eac", label: "At completion", fmt: "money" }, { k: "forecast_value", label: "Forecast value", fmt: "money" },
          { k: "forecast_margin", label: "Forecast margin", fmt: "money" }, { label: "Flag", v: (r) => (r.flags || []).includes("no_forecast") ? h("b", { class: "red" }, "No forecast") : ((r.flags || []).includes("no_budget") ? "No budget" : "") }],
        d.forecast.items, { name: "pfp_items", search: false }));
      if (d.forecast.no_forecast.length) box.append(h("p", { class: "red" }, "Items with no budget and no rate analysis: " + d.forecast.no_forecast.map((x) => x.code + " (" + M(x.revenue) + " of revenue with no cost)").join(", ")));
      box.append(h("h3", {}, "From the ledger to the project cost"),
        table([{ k: "label", label: "" }, { k: "amount", label: "Amount", fmt: "money" }], d.ledger.reconciliation.concat([{ label: "Project cost to date", amount: d.cost.total }]),
          { name: "pfp_rec", search: false, export: false }));
      if (cmp) box.append(compareBlock(cmp));
      box.append(await switchesBlock(load));
    };
    await load();
    return box;
  }

  function compareBlock(cmp) {
    const wrap = h("div", { class: "panel", style: "margin-top:16px" }, h("h3", {}, "Before and after, screen by screen"));
    const F = [["cost", "Cost to date"], ["value", "Value"], ["margin_pct", "Margin %"], ["eac", "Cost at completion"], ["forecast_profit", "Forecast profit"], ["forecast_margin_pct", "Forecast margin %"]];
    (cmp.rows || []).forEach((r) => {
      const rows = [];
      Object.keys(cmp.screens).forEach((s) => F.forEach(([k, lab]) => {
        const b = (r.before[s] || {})[k], a = (r.after[s] || {})[k];
        if (b === undefined && a === undefined) return;
        rows.push({ screen: cmp.screens[s], figure: lab, before: b, after: a, pctish: k.endsWith("pct") });
      }));
      wrap.append(h("h4", {}, r.code + " · " + r.name), table([{ k: "screen", label: "Screens" }, { k: "figure", label: "Figure" },
        { label: "Before", v: (x) => (x.pctish ? P(x.before) : M(x.before)) }, { label: "With one position", v: (x) => (x.pctish ? P(x.after) : M(x.after)) }], rows, { name: "pfp_cmp", search: false, export: false }));
    });
    wrap.append(h("h4", {}, "Why the figures change"), h("ul", {}, (cmp.reasons || []).map((t) => h("li", {}, t))));
    return wrap;
  }

  async function switchesBlock(reload) {
    const cmp = await api("pfp.compare", { project_id: -1 }).catch(() => null); /* settings and history only */
    const st = (cmp && cmp.settings) || {};
    const can = cmp && cmp.can_confirm;
    const wrap = h("div", { class: "panel", style: "margin-top:16px" }, h("h3", {}, "Switches (accounts)"));
    const row = (title, state, text, btn) => wrap.append(h("div", { style: "margin:10px 0" }, h("b", {}, title + ": "), state, h("div", { class: "hint" }, text), btn || null));
    row("One project position", st.pfp_on ? "on" : "off",
      "Every project screen reads the one position. Turn it on after checking the before and after above; it is recorded with the figures.",
      can ? h("button", { class: "btn " + (st.pfp_on ? "" : "primary"), onclick: async () => {
        if (!(await ask(st.pfp_on ? "Turn the one position off" : "Use the one project position", st.pfp_on ? "Screens go back to their own figures." : "Every project screen will show the figures on this page. The before and after are recorded."))) return;
        await run("pfp.confirm", { on: !st.pfp_on }, st.pfp_on ? "Switched off" : "Switched on"); reload(); } }, st.pfp_on ? "Switch off" : "Confirm and switch on") : null);
    const plan = can ? await api("pfp.runs_switch", { preview: 1 }).catch(() => null) : null;
    row("Monthly runs by Nepali month", st.run_months === "nepali" ? "Nepali months" : "English months",
      "Depreciation, Fixed assets allocation, Internal hire, Hire bills and Small-asset hire cover the same days as the month close. Runs already posted stay; the first Nepali run starts the day after the last day already charged." +
      (plan ? " Next: " + plan.plan.map((x) => x.label + " — " + x.next).join("; ") + "." : ""),
      can ? h("button", { class: "btn", onclick: async () => {
        const toN = st.run_months !== "nepali";
        if (!(await ask(toN ? "Run monthly charges by Nepali month" : "Back to English months", toN ? "From now on the six monthly runs take a Nepali month." : "The six monthly runs take English months again."))) return;
        await run("pfp.runs_switch", { nepali: toN }, "Done"); reload(); } }, st.run_months === "nepali" ? "Back to English months" : "Switch to Nepali months") : null);
    const dateIn = h("input", { type: "date", value: st.eqcc_from || "", style: "max-width:170px" });
    row("Equipment cost centre", st.eqcc_from ? "from " + st.eqcc_from : "off",
      "From this date the owning and running cost of each owned machine, and the credit side of every machine charge, post to the EQUIP cost centre with the machine. The using project keeps only its charge. Earlier postings stay; the position shares them by hours.",
      can ? h("span", {}, dateIn, h("button", { class: "btn", style: "margin-left:6px", onclick: async () => {
        await run("pfp.eqcc_set", { from: dateIn.value }, dateIn.value ? "Cost centre from " + dateIn.value : "Switched off"); reload(); } }, "Save")) : null);
    row("Over-budget purchase orders", st.po_budget_block ? "need an administrator" : "warning only",
      "Every PO approval runs the same budget check as the PO screen (control budget first). With this on, an order that takes the project over its budget needs an administrator.",
      can ? h("button", { class: "btn", onclick: async () => { await run("pfp.po_block", { on: !st.po_budget_block }, "Saved"); reload(); } }, st.po_budget_block ? "Warning only" : "Require an administrator") : null);
    if (cmp && cmp.history && cmp.history.length) wrap.append(h("h4", {}, "Changes"), table([{ k: "ts", label: "When" }, { k: "user", label: "Who" }, { k: "what", label: "What" }, { k: "value", label: "Set to" }], cmp.history, { name: "pfp_hist", search: false, export: false }));
    return wrap;
  }

  /* ───────── Machine P&L ───────── */
  async function machineTab() {
    const box = h("div"), out = h("div");
    let f = { from: "", to: today() };
    const load = async () => {
      const d = await api("pfp.machine_pl", f);
      out.innerHTML = "";
      out.append(h("p", { class: "hint" }, "Per owned machine and " + (d.months === "nepali" ? "Nepali" : "English") + " month: owning cost (depreciation, interest, insurance) and running cost (fuel, repairs, other) against the recovery charged to projects, wherever each was posted." +
        (d.eqcc_from ? " Machine postings go to the EQUIP cost centre from " + d.eqcc_from + "." : " The equipment cost centre is off (Commercial › CVR and forecast › Project position).")));
      out.append(summaryStrip([["Cost", M(d.total.cost)], ["Hours", fmtQty(d.total.hours)], ["Recovered", M(d.total.recovery)], ["Over (+) / under (−)", M(d.total.result)]]));
      out.append(table([{ k: "code", label: "Machine" }, { k: "label", label: "Month" }, { k: "owning", label: "Owning", fmt: "money" }, { k: "operating", label: "Running", fmt: "money" },
        { k: "cost", label: "Total cost", fmt: "money" }, { k: "hours", label: "Hours", fmt: "qty" }, { k: "cost_per_hour", label: "Cost per hour", fmt: "money" },
        { k: "recovery", label: "Recovered", fmt: "money" }, { k: "result", label: "Over / under", fmt: "money" }, { label: "", v: (r) => r.status === "under-recovered" ? h("span", { class: "red" }, "Under-recovered") : (r.status === "over-recovered" ? "Over-recovered" : "") }],
        d.rows, { name: "machine_pl", empty: "No machine cost or hours in this period." }));
    };
    box.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], f, (x) => { f = x; load(); }), out);
    await load();
    return box;
  }

  /* ───────── Control budget from rate analysis ───────── */
  async function fromRaTab() {
    const box = h("div");
    const pid = pidNow();
    if (!pid) { box.append(h("p", { class: "hint" }, "Choose a project.")); return box; }
    let d;
    try { d = await api("cl.budget_import", { project_id: pid, preview: 1 }); } catch (e) { box.append(h("p", { class: "hint" }, String(e.message || e))); return box; }
    box.append(h("p", { class: "hint" }, "What the draft Original budget would get from the rate analysis, item by item. Nothing is written until you choose. An approved budget is never changed here; changes to it go through a proposed change."),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Item" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "labour", label: "Labour /unit", fmt: "money" },
        { k: "material", label: "Material /unit", fmt: "money" }, { k: "equipment", label: "Equipment /unit", fmt: "money" }, { k: "other", label: "Other /unit", fmt: "money" },
        { k: "amount", label: "Amount", fmt: "money" }, { k: "source", label: "From" }], d.lines || [], { name: "cl_from_ra", search: false }));
    if (d.missing && d.missing.length) box.append(h("p", { class: "red" }, "No rate analysis: " + d.missing.join(", ") + " (a zero placeholder line is made)."));
    box.append(h("div", { class: "actions" },
      h("button", { class: "btn primary", onclick: async () => { await run("cl.budget_import", { project_id: pid, only_missing: 1 }, (x) => "Filled; kept " + (x.kept || 0) + " existing line(s)"); location.hash = "#/cl/budget"; } }, "Fill only items without a line" + (d.existing_lines ? " (keeps " + d.existing_lines + ")" : "")),
      h("button", { class: "btn", onclick: async () => { if (!(await ask("Rebuild the whole draft", "Every line of the draft is replaced from the rate analysis, including lines someone edited."))) return; await run("cl.budget_import", { project_id: pid }, "Draft rebuilt"); location.hash = "#/cl/budget"; } }, "Rebuild the whole draft")));
    return box;
  }

  addTabs("cl/cvr", "CVR and forecast", "What engineering earned against what accounts spent, item by item, and the forecast final profit.", "CVR", [["Project position", positionTab]]);
  addTabs("x/eqcost", "Equipment cost per hour", "What each machine costs per working hour, and whether it earned it back.", "Cost per hour", [["Machine P&L", machineTab]]);
  addTabs("cl/budget", "Control budget", "The project's budget item by item: original, current and forecast.", "Control budget", [["From rate analysis", fromRaTab]]);

  /* ───────── PR / PO budget box: the same check as the PO approval ───────── */
  try {
    if (typeof PR !== "undefined" && PR && !PR.__pfp) {
      PR.__pfp = true;
      PR.after = async (ctx) => {
        const b = await api("po.budget", { project_id: ctx.doc.project_id || S.project });
        if (b.budget) ctx.extra.append(h("div", { class: "panel" }, h("h2", {}, "Budget check (" + (b.basis || "budget") + ")"),
          kv([["Budget", fmtMoney(b.budget)], ["Committed (open POs)", fmtMoney(b.committed)], ["Cost to date", fmtMoney(b.actual)], b.stock ? ["In stock", fmtMoney(b.stock)] : null,
            ["Available", h("b", { class: b.available < 0 ? "red" : "" }, fmtMoney(b.available))]])));
      };
    }
  } catch (e) { /* the PR screen is not loaded */ }

  /* ───────── Nepali months on the monthly run screens ───────── */
  let MONTHS = null;
  const months = async () => { if (!MONTHS) MONTHS = await api("pfp.months", {}).catch(() => ({ nepali: false })); return MONTHS; };
  const RUN_ROUTES = ["eq/dep", "fa/dep", "fa/costing", "eq/hire"];
  async function nepaliPickers(root) {
    const m = await months();
    if (!m.nepali) return;
    root.querySelectorAll("input[type=month]").forEach((inp) => {
      if (inp.__pfp) return;
      inp.__pfp = true;
      const sel = h("select", { style: "max-width:260px" }, m.months.map((x) => h("option", { value: x.key }, x.label + " (" + x.from + " to " + x.to + ")" + (x.complete ? "" : " — not ended"))));
      sel.value = m.default;
      const push = () => { inp.value = sel.value; inp.dispatchEvent(new Event("input", { bubbles: true })); inp.dispatchEvent(new Event("change", { bubbles: true })); };
      sel.onchange = push;
      inp.style.display = "none";
      inp.parentNode.insertBefore(sel, inp);
      push();
    });
  }
  RUN_ROUTES.forEach((r) => {
    const orig = PAGES[r];
    if (!orig || orig.__pfp) return;
    PAGES[r] = async (root, params) => {
      const res = await orig(root, params);
      await nepaliPickers(root);
      setTimeout(() => nepaliPickers(root), 600);
      return res;
    };
    PAGES[r].__pfp = true;
    if (orig.__bco) PAGES[r].__bco = orig.__bco;
  });
  /* A run screen first opens on the last English month; when the company runs by Nepali month, its previews open on the
     last complete Nepali month instead. Posting with an English month is still refused by the engine. */
  const PREVIEWS = ["dep.preview", "internal.preview", "fa.dep_preview", "fa.alloc_preview", "fa.trueup_preview", "fa.ledger"];
  const _api = window.api;
  window.api = function (fn, args) {
    if (MONTHS && MONTHS.nepali && PREVIEWS.includes(fn) && args && /^\d{4}-\d{2}$/.test(args.month || "") && Number(args.month.slice(0, 4)) < 2070)
      args = Object.assign({}, args, { month: MONTHS.default });
    return _api.call(this, fn, args);
  };
  const _prompt = window.prompt;
  window.prompt = function (msg, def) {
    if (MONTHS && MONTHS.nepali && /which month/i.test(String(msg || ""))) {
      return _prompt.call(window, String(msg).replace("(YYYY-MM)", "(Nepali month, e.g. " + MONTHS.default + " = " + (MONTHS.months.find((x) => x.key === MONTHS.default) || {}).label + ")"), MONTHS.default);
    }
    return _prompt.call(window, msg, def);
  };

  /* open Commercial › CVR and forecast on its Project position tab */
  function openPosition() {
    location.hash = "#/cl/cvr";
    let n = 0;
    const t = setInterval(() => {
      const b = [...document.querySelectorAll(".tabs button, .tabs a, [role=tab]")].find((x) => x.textContent.trim() === "Project position");
      if (b) { clearInterval(t); b.click(); } else if (++n > 40) clearInterval(t);
    }, 250);
  }

  /* ───────── What's new ───────── */
  const VER = "2.39.0";
  function whatsNew() {
    try { if (localStorage.getItem("bco_seen_" + VER)) return; } catch (e) { return; }
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    const acc = can("accounts", "view"), pro = can("project", "view") || can("commercial", "view");
    if (!acc && !pro) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "One project number. "), "Commercial › CVR and forecast › ", h("b", {}, "Project position"), " shows one cost to date (posted, waiting, accrued), value (certified, earned), margin and forecast per project, with the basis of every item's forecast. After accounts confirms it there, every project screen shows the same figures."),
        h("li", {}, h("b", {}, "Forecast from the budget, then the rate analysis. "), "Items with no control budget are forecast from their rate analysis instead of at zero, and items with neither are flagged."),
        h("li", {}, h("b", {}, "Machine cost shared by hours. "), "Each own machine's cost is shared over the projects that used it, by hours. An optional equipment cost centre and a new Machine P&L tab (Equipment cost per hour) show what each machine cost and earned."),
        h("li", {}, h("b", {}, "One budget and Nepali months. "), "Control budget › From rate analysis has a preview and keeps edited lines. Purchase requests and PO approval use the same budget check. Monthly runs can move to Nepali months, the same as the month close.")),
      h("p", { class: "hint" }, "Nothing already posted is changed. In a company updated from an earlier version, each switch stays off until accounts turns it on.")),
    [{ label: "Open Project position", cls: "primary", act: () => openPosition() }], { narrow: true });
  }
  /* signed in: load the month list (never before sign-in: an unsigned call would end the session) */
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); months(); setTimeout(whatsNew, 13000); } }, 900);
})();
