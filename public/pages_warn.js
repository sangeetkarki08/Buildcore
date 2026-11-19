/* BuildCore 2.54 — one alerts engine: the forecast kept day by day (CVR tab "Forecast trend") and the switch for the
   ten new alert kinds (they live in Action centre › Alerts with the others). */
(function () {
"use strict";
const M = (v) => (v == null ? "—" : fmtMoney(v));
const addTabs = (route, title, sub, first, list) => {
  window.BCO_TABS = window.BCO_TABS || {};
  if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
  else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
};

async function trendTab() {
  const box = h("div");
  const projects = (S.L && S.L.projects ? S.L.projects : []).filter((p) => !p.kind || p.kind === "project");
  let pid = S.project || (projects[0] && projects[0].id);
  const load = async () => {
    box.innerHTML = "";
    box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Project"), h("select", { onchange: (e) => { pid = Number(e.target.value); load(); } },
      projects.map((p) => h("option", { value: p.id, selected: String(p.id) === String(pid) }, p.code + " · " + p.name))))));
    const st = await api("wn.state", {});
    const sw = h("div", { class: "panel" }, h("b", {}, "Alerts from 2.54: " + st.on + " of " + st.total + " kinds on"), " ",
      h("span", { class: "hint" }, st.kinds.map((k) => (k.enabled ? "✓ " : "✗ ") + k.label).join(" · ")), " ",
      can("admin", "edit") ? h("button", { class: "btn" + (st.on ? "" : " primary"), onclick: async () => { await run("wn.enable", { on: st.on ? 0 : 1 }); toast("Saved. They appear in Action centre › Alerts at the next check.", "ok"); load(); } }, st.on ? "Turn them off" : "Turn them on") : null,
      " ", h("a", { href: "#/action?tab=1" }, "Open the alerts ›"));
    box.append(sw);
    if (!pid) return;
    const d = await api("wn.trend", { project_id: pid });
    box.append(h("p", { class: "hint" }, "The forecast is kept once a day when the alerts are checked, so the margin can be followed month by month without waiting for a locked close. The 'forecast margin dropped' alert compares today with the last day of last month."));
    if (!d.rows.length) { box.append(h("p", { class: "panel" }, "Nothing kept yet: it starts at the next alert check.")); return; }
    const rows = d.rows.slice().reverse();
    const vals = d.rows.map((r) => r.margin).filter((x) => x != null);
    if (vals.length > 1) {
      const lo = Math.min(...vals), hi = Math.max(...vals), w = 600, ht = 120;
      const pts = d.rows.filter((r) => r.margin != null).map((r, i, a) => [(i / Math.max(1, a.length - 1)) * w, ht - ((r.margin - lo) / Math.max(0.1, hi - lo)) * (ht - 10) - 5]);
      const svg = '<svg viewBox="0 0 ' + w + " " + ht + '" style="width:100%;max-width:640px;height:130px"><polyline fill="none" stroke="currentColor" stroke-width="2" points="' + pts.map((p) => p.join(",")).join(" ") + '"/></svg>';
      const g = h("div", { class: "panel" }, h("b", {}, "Forecast margin " + lo.toFixed(1) + "% to " + hi.toFixed(1) + "%"));
      const holder = document.createElement("div"); holder.innerHTML = svg; g.append(holder); box.append(g);
    }
    box.append(table([{ k: "day", label: "Day" }, { k: "cost", label: "Cost to date", fmt: "money" }, { k: "eac", label: "Final cost", fmt: "money" }, { k: "value", label: "Forecast value", fmt: "money" },
      { k: "profit", label: "Profit", fmt: "money" }, { label: "Margin", v: (r) => r.margin == null ? "—" : r.margin.toFixed(1) + "%" }, { label: "Margin to date", v: (r) => r.margin_to_date == null ? "—" : r.margin_to_date.toFixed(1) + "%" }, { k: "finish", label: "Forecast finish" }], rows, { name: "wn_trend" }));
  };
  await load();
  return box;
}
addTabs("cl/cvr", "CVR and forecast", "What engineering earned against what accounts spent, item by item, and the forecast final profit.", "CVR", [["Forecast trend", trendTab]]);
})();
