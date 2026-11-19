/* BuildCore 2.52 — Complete forecast (CVR tab), Make the control budget (Control budget tab),
   Project control budgets (Budget vs actual tab). */
(function () {
"use strict";
const M = (v) => (v == null ? "—" : fmtMoney(v));
const P = (v) => (v == null ? "—" : Number(v).toFixed(1) + "%");
const addTabs = (route, title, sub, first, list) => {
  window.BCO_TABS = window.BCO_TABS || {};
  if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
  else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
};
const projSel = (pid, onch) => {
  const projects = (S.L && S.L.projects ? S.L.projects : []).filter((p) => !p.kind || p.kind === "project");
  return h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Project"), h("select", { onchange: (e) => onch(Number(e.target.value)) },
    projects.map((p) => h("option", { value: p.id, selected: String(p.id) === String(pid) }, p.code + " · " + p.name)))));
};
const firstPid = () => S.project || (((S.L && S.L.projects) || []).find((p) => !p.kind || p.kind === "project") || {}).id;

/* ── Complete forecast ── */
async function forecastTab() {
  const box = h("div");
  let pid = firstPid();
  const load = async () => {
    box.innerHTML = "";
    box.append(projSel(pid, (v) => { pid = v; load(); }));
    if (!pid) return;
    const d = await api("fc.additions", { project_id: pid });
    box.append(h("p", { class: "hint" }, "Costs everyone knows will come but the item-by-item forecast leaves out: overhead and site staff for the months left, preliminaries without a budget, defects and demobilisation, price rise on the remaining materials, and liquidated damages. Months left: " + d.months_left + " (to " + (d.finish || "—") + (d.completion && d.finish !== d.completion ? ", contract completion " + d.completion : "") + "). " +
      (d.switch_on ? "Switched on: every screen that reads the project position shows the forecast after these lines." : "Display only until accounts switches it on below.")));
    box.append(summaryStrip([["Final cost now", M(d.before.eac)], ["Added", M(d.add_cost)], ["Final cost complete", M(d.after.eac)],
      ["Forecast value", M(d.after.value)], ["Profit now → complete", M(d.before.profit) + " → " + M(d.after.profit)], ["Margin", P(d.before.margin_pct) + " → " + P(d.after.margin_pct)]]));
    box.append(h("h3", {}, "Lines added"), d.lines.length ? table([{ k: "label", label: "Line" }, { k: "cost", label: "Cost", fmt: "money" }, { k: "value", label: "Value", fmt: "money" }, { k: "basis", label: "How it is worked out" }], d.lines, { name: "fc_lines", search: false })
      : h("p", { class: "panel" }, "Nothing to add for this project."));
    if (d.unit_checks.length) box.append(h("h3", {}, "Actual cost per unit far from the estimate"), h("p", { class: "hint" }, "Items at least 20% done whose actual cost per unit is below 70% or above 130% of the estimate. Below usually means bills or store issues are late."),
      table([{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "done_pct", label: "Done %", fmt: "num" }, { k: "actual_unit", label: "Actual per unit", fmt: "money" }, { k: "budget_unit", label: "Estimate per unit", fmt: "money" }, { k: "ratio", label: "Ratio", fmt: "num" }, { k: "note", label: "" }], d.unit_checks, { name: "fc_unit", search: false }));
    if (d.potential.length) box.append(h("h3", {}, "Potential (not added)"), table([{ k: "ref", label: "Variation" }, { k: "title", label: "Title" }, { k: "status", label: "Status" }, { k: "amount", label: "Amount", fmt: "money" }], d.potential, { name: "fc_pot", search: false }));
    if (can("accounts", "approve")) {
      const st = await api("fc.settings", {});
      const f = form([{ k: "defects_pct", label: "Defects-period provision, % of contract", type: "number" }, { k: "demob_pct", label: "Demobilisation, % of contract", type: "number" },
        { k: "demob_amt", label: "or demobilisation lump sum (overrides %)", type: "number" }, { k: "staff", label: "Add site staff from the staff list when salaries are unallocated", type: "check" }],
        { defects_pct: st.defects_pct, demob_pct: st.demob_pct, demob_amt: st.demob_amt || "", staff: st.staff ? 1 : 0 });
      box.append(h("div", { class: "panel" }, h("h3", {}, "Settings (accounts)"), f, h("div", { class: "bar" },
        h("button", { class: "btn", onclick: async () => { const v = f.values(); await run("fc.save", { defects_pct: v.defects_pct, demob_pct: v.demob_pct, demob_amt: v.demob_amt || 0, staff: v.staff ? 1 : 0 }); toast("Saved", "ok"); load(); } }, "Save"),
        h("div", { class: "grow" }), h("span", {}, "Complete forecast on every screen: ", h("b", {}, st.fc_on ? "On" : "Off")),
        h("button", { class: "btn " + (st.fc_on ? "" : "primary"), onclick: async () => {
          if (!(await ask(st.fc_on ? "Switch off? Screens go back to the item-by-item forecast." : "Switch on? The project position (and every screen that reads it) will include these lines in the final cost, profit and margin."))) return;
          await run("fc.save", { fc_on: st.fc_on ? 0 : 1 }); load();
        } }, st.fc_on ? "Switch off" : "Switch on"))));
    }
  };
  await load();
  return box;
}
addTabs("cl/cvr", "CVR and forecast", "What engineering earned against what accounts spent, item by item, and the forecast final profit.", "CVR", [["Complete forecast", forecastTab]]);

/* ── Make the control budget ── */
async function wizardTab() {
  const box = h("div");
  let pid = firstPid();
  const load = async () => {
    box.innerHTML = "";
    box.append(projSel(pid, (v) => { pid = v; load(); }));
    if (!pid) return;
    const d = await api("fc.budget_wizard", { project_id: pid });
    const ck = d.checks, st = d.state, oh = d.overhead;
    box.append(h("p", { class: "hint" }, "Makes the draft Original budget from the rate analysis (when there is none) and fills the site overhead head from the staff list and the run rate. Then accounts submits and approves it as usual."));
    box.append(kv([["Budget now", st.original ? "Original approved" + (st.current ? ", current approved" : "") : st.draft ? "Draft (version " + (st.draft.version_no || 1) + ", " + st.draft.status + ")" : "None"],
      ["Site overhead suggested", M(oh.amount) + " = " + M(oh.monthly) + " a month × " + oh.months + " months (staff " + M(oh.monthly_staff) + ", run rate " + M(oh.monthly_run_rate) + ")"],
      ["BOQ total / contract value", M(ck.boq_total) + " / " + M(ck.contract_value) + (ck.contract_differs ? " — they differ" : " — agree")],
      ["Until approved, alerts use the draft", d.draft_switch ? "Yes" : "No (accounts switch below)"]]));
    const sec = (title, rows, cols) => rows.length ? h("details", { class: "panel" }, h("summary", {}, h("b", {}, title + " — " + rows.length)), table(cols, rows, { search: false, export: false })) : h("div", { class: "panel" }, "✓ " + title + ": none");
    box.append(sec("BOQ items with no estimate", ck.no_estimate, [{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "value", label: "Value", fmt: "money" }]),
      sec("Estimate below 40% of the BOQ rate", ck.low, [{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "estimate", label: "Estimate", fmt: "money" }, { k: "rate", label: "BOQ rate", fmt: "money" }, { k: "pct", label: "%", fmt: "num" }]),
      sec("Estimate above the BOQ rate", ck.high, [{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "estimate", label: "Estimate", fmt: "money" }, { k: "rate", label: "BOQ rate", fmt: "money" }, { k: "pct", label: "%", fmt: "num" }]),
      sec("Analyses with no labour and no machine lines", ck.no_lab_eq, [{ k: "code", label: "Item" }, { k: "name", label: "Description" }]));
    const bar = h("div", { class: "bar" });
    if (!st.original) bar.append(h("button", { class: "btn primary", onclick: async () => {
      const r = await run("fc.budget_wizard", { project_id: pid, apply: 1 });
      toast("Draft budget ready" + (r.applied && r.applied.length ? ": " + r.applied.join("; ") : "") + ". Open the Control budget tab to review and submit.", "ok"); load();
    } }, st.draft ? "Fill the overhead head in the draft" : "Make the draft budget"));
    if (can("accounts", "approve")) {
      const s2 = await api("fc.settings", {});
      bar.append(h("div", { class: "grow" }), h("button", { class: "btn", onclick: async () => {
        if (!(await ask(s2.fc_draft ? "Stop using draft budgets for the CVR and alerts?" : "Use the draft budget for the CVR, cost to complete and cost-overrun alert until a budget is approved? It is labelled \"draft budget\"."))) return;
        await run("fc.save", { fc_draft: s2.fc_draft ? 0 : 1 }); load();
      } }, s2.fc_draft ? "Stop using the draft for alerts" : "Use the draft for alerts until approved"));
    }
    box.append(bar);
  };
  await load();
  return box;
}
addTabs("cl/budget", "Control budget", "", "Control budget", [["Make the budget", wizardTab]]);

/* ── one budget: project control budgets on Budget vs actual ── */
async function budgetsTab() {
  const box = h("div", {}, h("p", { class: "hint" }, "One budget per project: the control budget (Commercial › Control budget). The ledger budgets on the first tab stay for head-office overheads. No separate funds-control budget is kept."));
  const holder = h("div");
  box.append(h("button", { class: "btn", onclick: async () => {
    holder.innerHTML = "";
    const d = await api("fc.budgets", {});
    holder.append(table([{ k: "code", label: "Project" }, { k: "basis", label: "Budget" }, { k: "budget", label: "Control budget", fmt: "money" }, { k: "cost", label: "Cost to date", fmt: "money" },
      { k: "used_pct", label: "Used %", fmt: "num" }, { k: "committed", label: "Open orders", fmt: "money" }, { k: "eac", label: "Forecast final cost", fmt: "money" },
      { label: "Budget − forecast", v: (r) => r.variance == null ? "" : h("b", { class: r.variance < 0 ? "red" : "green" }, M(r.variance)) }, { label: "", v: () => h("a", { href: "#/cl/budget" }, "Open ›") }], d.projects, { name: "fc_budgets" }));
  } }, "Show every project's control budget"), holder);
  return box;
}
addTabs("acc/budget", "Budget vs actual", "", "Ledger budgets", [["Project control budgets", budgetsTab]]);
})();
