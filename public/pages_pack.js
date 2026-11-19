/* BuildCore 2.55 — Management pack and fewer screens.
   Commercial › Monthly review pack (project page + company page ranked by risk), Accounts › Data health
   (one traffic light per area), "Time and site" panel on the Project control room, and the optional simpler menu
   (Administration › Setup & switches; off until an administrator turns it on, nothing is deleted). */
(function () {
"use strict";
if (window.__bco255) return; window.__bco255 = true;
const M = (v) => (v == null ? "—" : fmtMoney(v));
const P = (v) => (v == null ? "—" : Number(v).toFixed(1) + "%");
const LC = { green: "#2f7a4d", amber: "#c05621", red: "#b42318", grey: "#98a2b3" };
const dot = (l, txt) => h("span", { class: "pk-dot", style: "background:" + (LC[l] || LC.grey) }, txt || "");
const css = ".pk-dot{display:inline-block;min-width:14px;height:14px;border-radius:999px;vertical-align:middle;color:#fff;font-size:11px;font-weight:700;padding:0 4px;text-align:center;line-height:14px}" +
  ".pk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.pk-card{border:1px solid var(--line,#e4e7ec);border-radius:10px;padding:12px 14px;background:var(--panel,#fff)}" +
  ".pk-card h3{margin:0 0 6px;font-size:15px;display:flex;gap:8px;align-items:center}.pk-card .s{color:var(--muted,#667085);font-size:13px}" +
  ".pk-tabs{display:flex;gap:6px;margin:6px 0 12px}.pk-tabs button.on{background:var(--accent,#1f4fd6);color:#fff}" +
  ".pk-risk{display:inline-block;min-width:34px;text-align:center;border-radius:6px;font-weight:700;color:#fff;padding:1px 6px}" +
  "@media print{.pk-noprint,nav,header,.sidebar,#side{display:none!important}.pk-page{font-size:12px}.pk-card{break-inside:avoid}}";
document.head.append(h("style", {}, css));
const riskBadge = (r) => h("span", { class: "pk-risk", style: "background:" + (r >= 40 ? LC.red : r >= 15 ? LC.amber : LC.green) }, String(r));
const projects = () => ((S.L && S.L.projects) || []).filter((p) => !p.kind || p.kind === "project");
const thisMonth = () => new Date().toISOString().slice(0, 7);

/* ═════════════ simpler menu (off by default) ═════════════ */
let menuStyle = null;
async function applyMenu() {
  if (typeof S === "undefined" || !S || !S.token) return;   /* never before sign-in: a refused call would reload the page */
  let d;
  try { d = await api("pk.menu", {}); } catch (e) { return; }
  if (!menuStyle) { menuStyle = h("style", { id: "pk-menu" }); document.head.append(menuStyle); }
  const sel = [];
  (d.hidden || []).forEach((r) => {
    sel.push('a[data-path="' + r + '"]', 'a.scr[href="#/' + r + '"]');
    if (r === "dashboard/classic") sel.push('a[href="#/dashboard/classic"]');
  });
  menuStyle.textContent = sel.length ? sel.join(",") + "{display:none!important}" : "";
}
window.bcoApplyMenu = applyMenu;

function menuPanel() {
  const box = h("div", { class: "panel", id: "pk-menu-panel" });
  const load = async () => {
    const d = await api("pk.menu_options", {});
    const edit = can("admin", "edit");
    const ticks = {};
    const rows = d.rows.map((r) => {
      const cb = h("input", { type: "checkbox", checked: r.hidden, disabled: !edit });
      ticks[r.route] = cb;
      return h("tr", {}, h("td", {}, cb), h("td", {}, h("a", { href: "#/" + r.route }, r.label)), h("td", {}, r.group), h("td", { class: "hint" }, r.why),
        h("td", {}, r.suggested ? "suggested" : ""));
    });
    box.replaceChildren(h("h2", {}, "Simpler menu ", h("span", { class: "sf-pill " + (d.on ? "ok" : "off") }, d.on ? "On" : "Off")),
      h("p", { class: "hint" }, "Takes the ticked screens out of the menus for everyone. " + d.note + " The menu layout itself does not change."),
      h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, h("th", {}, "Hide"), h("th", {}, "Screen"), h("th", {}, "Area"), h("th", {}, "Why"), h("th", {}, ""))), h("tbody", {}, rows)),
      edit ? h("div", { class: "actions" },
        h("button", { class: "btn", onclick: async () => {
          const hidden = Object.keys(ticks).filter((k) => ticks[k].checked);
          await run("pk.menu_save", { hidden }, "Saved"); await applyMenu(); load();
        } }, "Save the list"),
        h("button", { class: "btn" + (d.on ? "" : " primary"), onclick: async () => {
          const hidden = Object.keys(ticks).filter((k) => ticks[k].checked);
          if (!(await ask(d.on ? "Turn the simpler menu off? Every screen comes back in the menus." : "Turn the simpler menu on? The " + hidden.length + " ticked screen(s) leave the menus for everyone. Nothing is deleted."))) return;
          await run("pk.menu_save", { hidden, on: d.on ? 0 : 1 }, d.on ? "Every screen is back" : "Simpler menu on"); await applyMenu(); load();
        } }, d.on ? "Turn off" : "Turn on")) : h("p", { class: "hint" }, "Only an administrator can change this."));
  };
  load().catch((e) => box.append(h("p", { class: "red" }, e.message)));
  return box;
}

/* ═════════════ Monthly review pack ═════════════ */
PAGES["pk/review"] = async (root, params) => {
  root.classList.add("pk-page");
  let mode = (params && params.get && params.get("tab")) === "company" ? "company" : "project";
  let pid = S.project || (projects()[0] || {}).id;
  let month = thisMonth();
  root.append(pageHead("Monthly review pack", "One page per project for the monthly review, and a company page that ranks the projects by risk. Read from the screens that already exist; nothing is posted.",
    h("button", { class: "btn pk-noprint", onclick: () => window.print() }, "Print / PDF")));
  const bar = h("div", { class: "bar pk-noprint" });
  const body = h("div");
  root.append(bar, body);
  const drawBar = () => {
    bar.replaceChildren(
      h("div", { class: "pk-tabs" }, h("button", { class: "btn" + (mode === "project" ? " on" : ""), onclick: () => { mode = "project"; drawBar(); load(); } }, "Project page"),
        h("button", { class: "btn" + (mode === "company" ? " on" : ""), onclick: () => { mode = "company"; drawBar(); load(); } }, "Company page (ranked by risk)")),
      mode === "project" ? h("label", { class: "f" }, h("span", {}, "Project"), h("select", { onchange: (e) => { pid = Number(e.target.value); load(); } },
        projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(pid) }, p.code + " · " + p.name)))) : null,
      h("label", { class: "f" }, h("span", {}, "Month"), h("input", { type: "month", value: month, onchange: (e) => { month = e.target.value || thisMonth(); load(); } })));
  };
  const load = async () => {
    body.replaceChildren(h("p", { class: "hint" }, "Putting the pack together…"));
    try {
      body.replaceChildren(mode === "company" ? await companyPage(month) : await projectPage(pid, month, load));
    } catch (e) { body.replaceChildren(h("p", { class: "red" }, e.message)); }
  };
  drawBar(); await load();
};

function card(title, light, ...kids) {
  return h("div", { class: "pk-card" }, h("h3", {}, light ? dot(light) : null, title), ...kids);
}

async function projectPage(pid, month, reload) {
  if (!pid) return h("p", {}, "Choose a project.");
  const d = await api("pk.review", { project_id: pid, month });
  const r = d.row, f = d.forecast, t = d.time;
  const box = h("div");
  box.append(h("h2", {}, r.code + " · " + r.name + " — " + d.month + " ", riskBadge(r.risk), h("span", { class: "hint" }, " risk " + (r.risk_why.join(", ") || "low"))));
  box.append(summaryStrip([["Contract", M(r.contract_value)], ["Cost to date", M(r.cost)], ["Certified", M(r.certified)], ["Final cost (forecast)", M(f.eac)],
    ["Forecast profit", M(f.profit)], ["Margin", P(f.margin_pct) + (r.margin_change != null ? " (" + (r.margin_change >= 0 ? "+" : "") + r.margin_change.toFixed(1) + " pts)" : "")]]));
  let g = h("div", { class: "pk-grid", style: "margin-top:12px" });
  const mLight = f.margin_pct == null ? "grey" : f.margin_pct < 0 ? "red" : (f.bid_margin_pct != null && f.margin_pct < f.bid_margin_pct) ? "amber" : "green";
  g.append(card("Money", mLight, kv([["Margin to date (certified)", P(r.margin_to_date)], ["Forecast margin / at bid", P(f.margin_pct) + " / " + P(f.bid_margin_pct)],
    ["Last month end", r.prev_margin == null ? "—" : P(r.prev_margin) + " on " + r.prev_day], ["Cost to complete", M(f.cost_to_complete)],
    d.complete ? ["Complete forecast (2.52)", M(d.complete.profit) + " · " + P(d.complete.margin_pct) + " after " + M(d.complete.add_cost) + " more cost"] : null]),
    h("a", { class: "pk-noprint", href: "#/cl/cvr" }, "CVR and forecast ›")));
  const tl = t.late_days == null ? "grey" : t.late_days > 0 ? "red" : "green";
  g.append(card("Time", tl, kv([["Completion (contract)", t.completion || "—"], ["Forecast finish", t.finish ? t.finish + (t.data_date ? " (data date " + t.data_date + ")" : "") : "no schedule calculated"],
    ["Days late", t.late_days == null ? "—" : t.late_days > 0 ? h("b", { class: "red" }, t.late_days + " days") : "on time (" + -t.late_days + " days spare)"],
    t.ld ? ["LD exposure", M(t.ld)] : null, ["DPRs this month", d.dprs + " (" + d.dprs_approved + " approved)"],
    ["Delay hours this month", d.delays.length ? d.delays.map((x) => x.who + " " + x.hours + " h").join(" · ") : "none"]]),
    h("a", { class: "pk-noprint", href: "#/p/schedule" }, "Schedule ›")));
  const sc = d.score;
  g.append(card("Cost completeness", sc.score == null ? "grey" : sc.score >= 80 ? "green" : sc.score >= 60 ? "amber" : "red",
    kv([["Score", sc.score == null ? "—" : sc.score + " of 100"], ["Cost not yet in the books", M(sc.missing_total)], ["Weakest", sc.weakest.join(" · ") || "—"]]),
    h("a", { class: "pk-noprint", href: "#/cl/cvr" }, "Cost not yet in the books ›")));
  if (d.checks) g.append(card("Project checks", d.checks.fails.some((x) => x.blocking) ? "red" : d.checks.fails.length ? "amber" : "green",
    h("div", { class: "s" }, (d.checks.total - d.checks.fails.length) + " of " + d.checks.total + " pass"),
    d.checks.fails.length ? h("ul", {}, d.checks.fails.map((x) => h("li", {}, h("b", {}, x.name), x.blocking ? " (blocks the close)" : ""))) : null));
  if (d.cash) box.append(g), g = h("div", { class: "pk-grid", style: "margin-top:12px;grid-template-columns:1fr" }), g.append(card("Cash, next months", "", d.cash.rows.length ? table([{ k: "month", label: "Month" }, { k: "in", label: "In", fmt: "money" }, { k: "out", label: "Out", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "cumulative", label: "Cumulative", fmt: "money" }],
    d.cash.rows, { search: false, export: false }) : h("p", { class: "s" }, "No cash plan."), h("div", { class: "s" }, "Peak cash need " + M(d.cash.peak_cash) + (d.cash.peak_month ? " in " + d.cash.peak_month : "") + " · retention held " + M(d.cash.retention_held))));
  box.append(g);
  if (d.trend.length > 1) {
    const vals = d.trend.map((x) => x.margin).filter((x) => x != null);
    if (vals.length > 1) {
      const lo = Math.min(...vals), hi = Math.max(...vals), w = 600, ht = 100;
      const pts = d.trend.filter((x) => x.margin != null).map((x, i, a) => [(i / Math.max(1, a.length - 1)) * w, ht - ((x.margin - lo) / Math.max(0.1, hi - lo)) * (ht - 10) - 5]);
      const hold = document.createElement("div");
      hold.innerHTML = '<svg viewBox="0 0 ' + w + " " + ht + '" style="width:100%;max-width:640px;height:110px"><polyline fill="none" stroke="currentColor" stroke-width="2" points="' + pts.map((p) => p.join(",")).join(" ") + '"/></svg>';
      box.append(h("h3", {}, "Forecast margin by month (" + lo.toFixed(1) + "% to " + hi.toFixed(1) + "%)"), hold);
    }
  }
  box.append(h("h3", {}, "Trend"), d.trend.length ? table([{ k: "day", label: "Month end" }, { k: "cost", label: "Cost to date", fmt: "money" }, { k: "eac", label: "Final cost", fmt: "money" },
    { k: "profit", label: "Profit", fmt: "money" }, { label: "Margin", v: (x) => P(x.margin) }, { k: "finish", label: "Forecast finish" }], d.trend, { search: false, export: false })
    : h("p", { class: "hint" }, "The forecast is kept daily from 2.54 (when the alerts are checked); the trend fills in from there."));
  if (d.worst_items.length) box.append(h("h3", {}, "Items losing most"), table([{ k: "code", label: "Item" }, { k: "name", label: "Description" }, { k: "eac", label: "Final cost", fmt: "money" }, { k: "value", label: "Value", fmt: "money" }, { k: "loss", label: "Forecast loss", fmt: "money" }, { k: "basis", label: "Forecast from" }], d.worst_items, { search: false, export: false }));
  box.append(h("h3", {}, "Top alerts"), d.alerts.length ? table([{ k: "severity", label: "Level" }, { k: "title", label: "Alert" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "target_date", label: "Target" }, { k: "status", label: "Status" }],
    d.alerts, { search: false, export: false }) : h("p", { class: "hint" }, "No open alerts on this project."));
  box.append(decisionsBlock(d, pid, month, reload));
  return box;
}

function decisionsBlock(d, pid, month, reload) {
  const box = h("div", {}, h("h3", {}, "Decisions"), h("p", { class: "hint" }, "Agreed at the review, with an owner and a date. Open ones come back on next month's page until they are done or dropped."));
  box.append(d.decisions.length ? table([{ k: "month", label: "Agreed" }, { k: "text", label: "Decision" }, { k: "owner", label: "Owner" }, { k: "due_date", label: "Due" }, { k: "status", label: "Status" },
    { label: "", v: (x) => d.can_edit && x.status === "open" ? h("span", { class: "pk-noprint" }, h("button", { class: "btn small", onclick: async () => { await run("pk.decision_save", { id: x.id, status: "done" }, "Done"); reload(); } }, "Done"), " ",
      h("button", { class: "btn small", onclick: async () => { await run("pk.decision_save", { id: x.id, status: "dropped" }, "Dropped"); reload(); } }, "Drop")) : "" }], d.decisions, { search: false, export: false })
    : h("p", { class: "hint" }, "None yet."));
  if (d.can_edit) {
    const f = form([{ k: "text", label: "Decision" }, { k: "owner", label: "Owner" }, { k: "due_date", label: "Due", type: "date" }], {});
    box.append(h("div", { class: "panel pk-noprint" }, f, h("button", { class: "btn primary", onclick: async () => { await run("pk.decision_save", Object.assign(f.values(), { project_id: pid, month }), "Decision kept"); reload(); } }, "Add decision")));
  }
  return box;
}

async function companyPage(month) {
  const d = await api("pk.company", { month });
  const box = h("div");
  const t = d.total;
  box.append(summaryStrip([["Projects", String(d.rows.length)], ["Contracts", M(t.contract_value)], ["Cost to date", M(t.cost)], ["Certified", M(t.certified)],
    ["Forecast profit", M(t.profit)], ["Margin", P(t.margin_pct)], ["Cost not yet in the books", M(t.missing_total)]]));
  box.append(h("h3", {}, "Projects, highest risk first"), h("p", { class: "hint" }, "Risk points: loss forecast 30, margin below bid 15, margin fell 3+ points since last month 15, finish late 20 (25 if over 60 days), 5 per high alert (up to 20), cost completeness below 60: 15 (below 80: 8)."),
    table([{ label: "Risk", v: (r) => riskBadge(r.risk) }, { label: "Project", v: (r) => h("a", { href: "#/pk/review", onclick: () => { S.project = r.project_id; } }, r.code) }, { k: "name", label: "Name" },
      { k: "contract_value", label: "Contract", fmt: "money" }, { k: "profit", label: "Forecast profit", fmt: "money" }, { label: "Margin", v: (r) => P(r.margin_pct) },
      { label: "Change", v: (r) => r.margin_change == null ? "—" : (r.margin_change >= 0 ? "+" : "") + r.margin_change.toFixed(1) },
      { label: "Days late", v: (r) => r.late_days == null ? "—" : r.late_days > 0 ? h("b", { class: "red" }, String(r.late_days)) : "0" },
      { k: "high_alerts", label: "High alerts", fmt: "num" }, { label: "Completeness", v: (r) => r.score == null ? "—" : String(r.score) }, { label: "Why", v: (r) => r.risk_why.join(", ") }],
    d.rows, { name: "pk_company" }));
  if (d.cash) {
    const c = d.cash;
    box.append(h("h3", {}, "Company cash, next 13 weeks"), kv([["Opening", M(c.opening)], ["Lowest balance", c.lowest && typeof c.lowest === "object" ? M(c.lowest.closing) + " (week of " + c.lowest.start + ")" : M(c.lowest)], ["First week short", c.first_gap ? "week of " + (c.first_gap.start || c.first_gap.week || c.first_gap) : "none"],
      ["Largest shortfall", M(c.max_gap)]]),
      table([{ k: "week", label: "Week" }, { k: "start", label: "From" }, { k: "in", label: "In", fmt: "money" }, { k: "out", label: "Out", fmt: "money" }, { k: "closing", label: "Closing", fmt: "money" }], c.weeks, { search: false, export: false }));
  }
  box.append(h("h3", {}, "Open decisions"), d.decisions.length ? table([{ k: "code", label: "Project" }, { k: "month", label: "Agreed" }, { k: "text", label: "Decision" }, { k: "owner", label: "Owner" }, { k: "due_date", label: "Due" }], d.decisions, { search: false, export: false })
    : h("p", { class: "hint" }, "None."));
  if (d.errors.length) box.append(h("p", { class: "red" }, "Could not read: " + d.errors.join("; ")));
  return box;
}

/* ═════════════ Data health ═════════════ */
PAGES["pk/health"] = async (root) => {
  root.append(pageHead("Data health", "One light per area, from the checks that already exist. Red: figures are wrong until fixed. Amber: worth a look. Open an area to see what failed and where to fix it."));
  const body = h("div", {}, h("p", { class: "hint" }, "Running the checks…"));
  root.append(body);
  const d = await api("pk.health", {});
  body.replaceChildren(summaryStrip([["Red", String(d.red)], ["Amber", String(d.amber)], ["Green", String(d.green)], ["Checked", d.as_of.replace("T", " ").slice(0, 16)]]));
  const order = { red: 0, amber: 1, grey: 3, green: 2 };
  const g = h("div", { class: "pk-grid", style: "margin-top:12px" });
  d.areas.slice().sort((a, b) => order[a.light] - order[b.light]).forEach((a) => {
    const det = a.rows.length ? h("details", {}, h("summary", {}, "Details (" + a.rows.length + ")"),
      table(a.cols.map((k) => k === "light" ? { label: "", v: (r) => dot(r.light) } : { k, label: k[0].toUpperCase() + k.slice(1) }), a.rows, { search: false, export: false })) : null;
    g.append(card(a.label, a.light, h("div", { class: "s" }, a.summary), det, h("a", { href: "#/" + a.link }, "Open ›")));
  });
  body.append(g);
};

/* ═════════════ Time and site panel on the control room; simpler-menu panel on Setup & switches ═════════════ */
const wrap = (route, fn) => {
  const orig = PAGES[route];
  if (!orig || orig._bco255) return;
  const w = async (root, params) => { const r = await orig(root, params); try { await fn(root, params); } catch (e) { /* never stops the page */ } return r; };
  for (const k of Object.keys(orig)) w[k] = orig[k];
  w._bco255 = true;
  PAGES[route] = w;
};
async function sitePanel(root) {
  const pid = S.project;
  if (!pid) return;
  document.querySelectorAll("#pk-site").forEach((x) => x.remove());   /* the page can draw twice when the project changes */
  const holder = h("div", { class: "panel", id: "pk-site", style: "margin-top:12px" }, h("h3", {}, "Time and site"), h("p", { class: "hint" }, "Reading…"));
  (root.querySelector("#page") || root).append(holder);
  const d = await api("pk.site", { project_id: pid });
  const t = d.time;
  const dl = !d.last_dpr ? "red" : (new Date(d.today) - new Date(d.last_dpr)) / 864e5 > 3 ? "amber" : "green";
  holder.replaceChildren(h("h3", {}, "Time and site"),
    h("div", { class: "pk-grid" },
      card("Daily reports", dl, kv([["Last DPR", (d.last_dpr || "none") + (d.last_dpr_status ? " (" + d.last_dpr_status + ")" : "")], ["Days reported, last 7 / 30", d.dpr_7 + " / " + d.dpr_30], ["Waiting approval", String(d.dpr_waiting)]]), h("a", { href: "#/p/dpr" }, "DPR ›")),
      card("Finish", t.late_days == null ? "grey" : t.late_days > 0 ? "red" : "green", kv([["Completion", t.completion || "—"], ["Forecast finish", t.finish || "not calculated"],
        ["Days late", t.late_days == null ? "—" : String(Math.max(0, t.late_days))], t.ld ? ["LD exposure", M(t.ld)] : null, ["Schedule data date", t.data_date || "—"]]), h("a", { href: "#/p/schedule" }, "Schedule ›")),
      card("Next weeks", (d.acts_late || 0) > 0 ? "amber" : "green", kv([["Activities late", d.acts_late == null ? "—" : String(d.acts_late)], ["Due in 14 days", d.acts_due == null ? "—" : String(d.acts_due)],
        d.lookahead ? ["Look-ahead this week", d.lookahead.done + " of " + d.lookahead.planned + " done"] : null, ["Open site issues", d.issues == null ? "—" : String(d.issues)]])),
      card("Delays, last 30 days", d.delays.length ? "amber" : "green", d.delays.length ? table([{ k: "who", label: "Responsibility" }, { k: "hours", label: "Hours", fmt: "num" }, { k: "n", label: "Times", fmt: "num" }], d.delays, { search: false, export: false }) : h("p", { class: "s" }, "None reported."))),
    d.milestones.length ? h("div", {}, h("b", {}, "Milestones in the next 60 days or overdue: "), d.milestones.map((m) => m.name + " " + m.due_date + (m.forecast && m.forecast > m.due_date ? " (forecast " + m.forecast + ")" : "")).join(" · ")) : null);
}
async function setupPanel(root) {
  if (!can("admin", "view")) return;
  document.querySelectorAll("#pk-menu-panel").forEach((x) => x.remove());
  (root.querySelector("#page") || root).append(menuPanel());
}
const go = () => { wrap("p/control", sitePanel); wrap("admin/setup", setupPanel); };
if (document.readyState === "complete") go(); else window.addEventListener("load", go);
(window.bcoBootHooks = window.bcoBootHooks || []).push(() => { try { go(); applyMenu(); } catch (e) { /* ignore */ } });
window.addEventListener("hashchange", () => { if (!menuStyle) applyMenu(); });
})();
