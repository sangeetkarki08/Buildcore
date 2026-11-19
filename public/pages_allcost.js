/* BuildCore 2.51 — Count all the cost: "Cost not yet in the books" tab on CVR and forecast, cost completeness score
   on the dashboard and the project control room. */
(function () {
"use strict";
const M = (v) => (v == null ? "—" : fmtMoney(v));
const col = (s) => (s == null ? "#667085" : s >= 80 ? "#2f7a4d" : s >= 60 ? "#c05621" : "#b42318");
const badge = (s) => h("span", { style: "display:inline-block;min-width:44px;text-align:center;padding:2px 10px;border-radius:999px;font-weight:700;color:#fff;background:" + col(s) }, s == null ? "—" : String(s));
const addTabs = (route, title, sub, first, list) => {
  window.BCO_TABS = window.BCO_TABS || {};
  if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
  else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
};

function scoreBox(sc) {
  return h("div", { class: "panel" }, h("h3", {}, "Cost completeness ", badge(sc.score), h("span", { class: "hint" }, " of 100")),
    table([{ label: "", v: (p) => p.ok ? "✓" : "✗" }, { k: "label", label: "Check" }, { label: "Points", v: (p) => p.points + " / " + p.weight }, { k: "detail", label: "Now" },
      { label: "", v: (p) => p.ok ? "" : h("a", { href: "#/" + p.link }, "Fix ›") }], sc.parts, { name: "ac_score", search: false, export: false }));
}

async function missingTab() {
  const box = h("div");
  const projects = (S.L && S.L.projects ? S.L.projects : []).filter((p) => !p.kind || p.kind === "project");
  let pid = S.project || (projects[0] && projects[0].id);
  const load = async () => {
    box.innerHTML = "";
    const sel = h("select", { onchange: (e) => { pid = Number(e.target.value); load(); } },
      projects.map((p) => h("option", { value: p.id, selected: String(p.id) === String(pid) }, p.code + " · " + p.name)));
    box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Project"), sel)));
    if (!pid) { box.append(h("p", { class: "hint" }, "Choose a project.")); return; }
    const d = await api("ac.missing", { project_id: pid });
    box.append(h("p", { class: "hint" }, "Cost that is real but not yet in the books: material used on site but not issued from the store, DPR lines that posted no cost because the rate is missing, DPRs waiting approval and monthly runs not done. Each line says where it comes from and how to fix it. " +
      (d.switch_on ? "Switched on: material, no-rate and run lines are counted in cost to date (as accrued) on the CVR and project position and are accrued at the month close." : "Display only: nothing is posted and no other figure changes until accounts switches it on below.")));
    const kinds = [["material_not_issued", "Material used, not issued"], ["dpr_no_rate", "DPR lines with no rate"], ["dpr_waiting", "DPRs waiting approval"], ["run_missing", "Monthly runs not done"]];
    box.append(summaryStrip(kinds.map(([k, l]) => [l, M(d.by_kind[k] || 0)]).concat([["Total (estimated)", M(d.total)]])));
    box.append(h("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;margin-top:12px" },
      h("div", {}, h("h3", {}, "Lines"), d.lines.length ? table([{ k: "label", label: "What" }, { k: "detail", label: "Detail" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "", v: (x) => x.estimated ? h("span", { class: "hint" }, "estimate") : "" }, { label: "How to fix", v: (x) => h("a", { href: "#/" + x.link }, x.fix) }], d.lines, { name: "ac_lines" })
        : h("p", { class: "panel" }, "Nothing missing found for this project.")),
      scoreBox(d.score)));
    if (can("accounts", "approve")) {
      const st = await api("ac.settings", {});
      const f = form([{ k: "lab_rate", label: "Default labour rate per worker-hour (blank = project's average trade rate)", type: "number" },
        { k: "eq_rate", label: "Default own-machine rate per hour (rate costing only)", type: "number" }], { lab_rate: st.lab_rate || "", eq_rate: st.eq_rate || "" });
      box.append(h("div", { class: "panel" }, h("h3", {}, "Settings (accounts)"), f,
        h("div", { class: "bar" }, h("button", { class: "btn", onclick: async () => { await run("ac.save", f.values()); toast("Saved", "ok"); load(); } }, "Save rates"),
          h("div", { class: "grow" }), h("span", {}, "Count these in cost and at the close: ", h("b", {}, st.on ? "On" : "Off")),
          h("button", { class: "btn " + (st.on ? "" : "primary"), onclick: async () => {
            if (!(await ask(st.on ? "Switch off? The lines stay visible here but are no longer counted in cost or accrued." : "Switch on? Material used not issued, DPR lines with no rate and missing salary / small-asset runs will count in cost to date (as accrued) and be accrued at the month close. Nothing is posted until a close's accruals are posted."))) return;
            await run("ac.save", { on: st.on ? 0 : 1 }); load();
          } }, st.on ? "Switch off" : "Switch on"))));
    }
  };
  await load();
  return box;
}
addTabs("cl/cvr", "CVR and forecast", "What engineering earned against what accounts spent, item by item, and the forecast final profit.", "CVR", [["Cost not yet in the books", missingTab]]);

/* score on the dashboard (all projects) and on the project control room */
const inject = (route, where) => {
  const orig = PAGES[route];
  if (!orig || orig._bco251) return;
  const w = async (root, params) => {
    const r = await orig(root, params);
    try {
      const pid = route === "p/control" ? S.project : null;
      if (route === "p/control" && !pid) return r;
      const holder = h("div");
      document.querySelectorAll("#ac-panel-" + route.replace("/", "-")).forEach((x) => x.remove());   /* 2.55: never twice */
      const panel = h("div", { class: "panel", id: "ac-panel-" + route.replace("/", "-"), style: "margin-top:12px" }, h("h3", {}, "Cost completeness", h("span", { class: "hint" }, " · how much of the real cost is in BuildCore")), holder);
      const fill = async () => {
        holder.innerHTML = "";
        holder.append(h("p", { class: "hint" }, "Working it out…"));
        const d = await api("ac.scores", pid ? { project_id: pid } : {});
        holder.innerHTML = "";
        holder.append(d.projects.length ? table([{ k: "code", label: "Project" }, { label: "Score", v: (p) => badge(p.score) }, { k: "missing_total", label: "Cost not yet in the books", fmt: "money" },
          { label: "Weakest", v: (p) => p.weakest.join(" · ") }, { label: "", v: () => h("a", { href: "#/cl/cvr" }, "Open ›") }], d.projects, { name: "ac_scores", search: false, export: false })
          : h("p", { class: "hint" }, "No active projects."));
      };
      if (pid) fill(); else holder.append(h("button", { class: "btn", onclick: fill }, "Check cost completeness of every project"));
      (root.querySelector(where) || root).append(panel);
    } catch (e) { /* the score never stops the page */ }
    return r;
  };
  w._bco251 = true;
  for (const k of Object.keys(orig)) w[k] = orig[k];
  PAGES[route] = w;
};
const go2 = () => { inject("dashboard", "#page"); inject("p/control", "#page"); };
if (document.readyState === "complete") go2(); else window.addEventListener("load", go2);
(window.bcoBootHooks = window.bcoBootHooks || []).push(() => { try { go2(); } catch (e) { /* ignore */ } });
})();
