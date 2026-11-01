/* BuildCore 2.8.1 — work one module at a time.
   After sign-in you see every module as a box (Dashboard, Site work, Store, Equipment, Accounts …).
   Open one and you get that module's own home (its screens, quick entries and figures) and a side menu
   with only that module's screens. "All modules" (or Ctrl+M) brings you back. */
(function () {
  "use strict";
  const LS = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSset = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  const svg = (d) => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.8"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); s.innerHTML = d; return s; };
  const I = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    helmet: '<path d="M4 16a8 8 0 0 1 16 0"/><path d="M2 16h20v2H2z"/><path d="M12 8V5"/><path d="M9 9V6.5M15 9V6.5"/>',
    bill: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/>',
    box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.5 12h11L21 7H6"/>',
    coins: '<ellipse cx="9" cy="6" rx="6" ry="2.5"/><path d="M3 6v5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V6"/><path d="M9 16.5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-5c0-1.4-2.7-2.5-6-2.5"/>',
    factory: '<path d="M3 21V10l6 3V9l6 3V5h6v16z"/><path d="M7 17h2M12 17h2M17 17h2"/>',
    building: '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M8 7h2M14 7h2M8 11h2M14 11h2M8 15h2M14 15h2M11 21v-3h2v3"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    ruler: '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
    excavator: '<path d="M2 18h12v-4H6l-1-3h5"/><circle cx="5" cy="19" r="1.6"/><circle cx="11" cy="19" r="1.6"/><path d="M14 14l3-7 4 2-2 5"/><path d="M19 14l2 3h-4"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  };
  const META = {
    "Overview": { t: "Dashboard", d: "Company and project overview, approvals and what needs attention today.", c: "#1769aa", i: "grid" },
    "Work": { t: "Site work & DPR", d: "Daily progress reports, schedule, quality, documents, tasks, events and claims.", c: "#2f7a4d", i: "helmet", q: [["dpr", "+ DPR"], ["event", "+ Event / claim"], ["task", "+ Task"]] },
    "Commercial": { t: "Commercial & billing", d: "BOQ, measurements, IPC bills, variations, cost control, contracts and bids.", c: "#7a4fb3", i: "bill", q: [["measure", "+ Measurement"], ["ipc", "+ IPC bill"], ["variation", "+ Variation"]] },
    "Inventory": { t: "Store & inventory", d: "Stock, receipts, issues, returns, transfers, counts — consumables, tools and spare parts.", c: "#b7791f", i: "box", q: [["grn", "+ Receive (GRN)"], ["issue", "+ Issue"], ["ret", "+ Return"], ["transfer", "+ Transfer"], ["mrq", "+ Requisition"], ["count", "+ Stock count"]] },
    "Procurement": { t: "Procurement", d: "Purchase requests, quotation comparison, purchase orders, deliveries and bills.", c: "#c05621", i: "cart", q: [["pr", "+ Purchase request"], ["po", "+ Purchase order"], ["purchase", "+ Purchase bill"]] },
    "Accounts": { t: "Accounts", d: "Vouchers, payments, ledgers, VAT and TDS, fiscal years and financial statements.", c: "#0f766e", i: "coins", q: [["pay", "+ Payment F5"], ["receive", "+ Receipt F6"], ["journal", "+ Journal F7"], ["contra", "+ Contra F4"], ["sales", "+ Sales F8"]] },
    "Plant": { t: "Plant (crusher, batching)", d: "Plant register, mix designs, production runs and performance.", c: "#4a5568", i: "factory", q: [["run", "+ Production run"]] },
    "Assets": { t: "Assets", d: "Asset register and depreciation.", c: "#2b6cb0", i: "building", q: [["asset", "+ Asset"]] },
    "Fixed assets": { t: "Fixed assets (NFRS)", d: "Capital register, depreciation runs, leases, impairment and tax depreciation.", c: "#2c5282", i: "chart" },
    "Resources & rates": { t: "Resources & rates", d: "Resource pool, norms library, rate books and rate analysis.", c: "#975a16", i: "ruler" },
    "Equipment": { t: "Equipment & machines", d: "Machine register, logsheets, maintenance, repairs and history, hire and performance.", c: "#b83280", i: "excavator", q: [["logday", "+ Machine log"]] },
    "Master data": { t: "Master data", d: "Projects, materials, vendors and clients, BOQ items, trades, staff and check lists.", c: "#2d3748", i: "list" },
    "Administration": { t: "Administration", d: "Users, companies, team and devices, settings, backup and the audit log.", c: "#4a5568", i: "gear" },
  };
  const meta = (g) => META[g] || { t: g, d: "", c: "#4a5568", i: "grid" };
  window.bcoModTitle = (g) => meta(g).t;

  const css = document.createElement("style");
  css.textContent = [
    ".modhero{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap;margin:4px 0 18px}.modhero h1{margin:0}.modhero .grow{flex:1}",
    ".modgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}",
    ".modcard{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 18px 16px;cursor:pointer;box-shadow:0 1px 2px rgba(16,42,60,.05);transition:transform .12s,box-shadow .12s,border-color .12s;display:flex;flex-direction:column;gap:8px;min-height:170px;text-decoration:none;color:inherit}",
    ".modcard:hover,.modcard:focus{transform:translateY(-2px);box-shadow:0 12px 30px rgba(16,42,60,.12);border-color:var(--mc);outline:none}",
    ".modcard .ic{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;background:var(--mc);color:#fff}.modcard .ic svg{width:26px;height:26px}",
    ".modcard b{font-size:17px}.modcard p{margin:0;color:var(--muted);font-size:13px;line-height:1.45;flex:1}",
    ".modcard .foot{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--muted)}.modcard .foot i{font-style:normal;color:var(--mc);font-weight:700}",
    ".modcard .badge{position:absolute;right:14px;top:14px;background:#f0b43c;color:#2b1d00;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700}",
    ".modcard kbd{font-family:monospace;font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 4px;color:var(--muted)}",
    ".scrgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-top:8px}",
    ".scr{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer;text-decoration:none;color:inherit;display:flex;gap:10px;align-items:center;transition:box-shadow .12s,border-color .12s}",
    ".scr:hover{border-color:var(--mc);box-shadow:0 8px 20px rgba(16,42,60,.08)}.scr .dot{width:8px;height:8px;border-radius:50%;background:var(--mc);flex:none}",
    ".quick{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 16px}.quick .btn{border-radius:999px;border-color:var(--mc);color:var(--mc);background:#fff}.quick .btn:hover{background:var(--mc);color:#fff}",
    ".glance{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin:0 0 18px}",
    ".glance div{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--mc);border-radius:12px;padding:10px 14px}.glance b{display:block;font-size:19px}.glance span{color:var(--muted);font-size:12.5px}",
    ".navback{display:flex!important;align-items:center;gap:6px;color:#f0b43c!important;font-weight:600}",
    ".modhead{display:flex;align-items:center;gap:10px;padding:10px 18px 8px;color:#fff;font-weight:700;font-size:15px}.modhead .ic{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;background:var(--mc)}.modhead svg{width:18px;height:18px}",
    ".nav .navmod{display:flex!important;align-items:center;gap:10px}.nav .navmod .ic{width:24px;height:24px;border-radius:6px;display:grid;place-items:center;background:var(--mc);flex:none}.nav .navmod svg{width:15px;height:15px;color:#fff}",
    ".recentrow{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}.recentrow a{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:4px 12px;text-decoration:none;font-size:13px;color:var(--ink)}",
  ].join("");
  document.head.append(css);

  const groups = () => (typeof MENU !== "undefined" ? MENU : []).map(([g, module, items]) => {
    if (module && !can(module, "view")) return null;
    const links = items.filter(([, , mod]) => !mod || can(mod, "view")).filter(([p]) => PAGES[p]);
    return links.length ? { g, module, links } : null;
  }).filter(Boolean);
  const parse = () => { const raw = location.hash.replace(/^#\/?/, ""); const [path, qs] = raw.split("?"); const p = {}; new URLSearchParams(qs || "").forEach((v, k) => { p[k] = v; }); return { path, p }; };
  const groupOf = (path) => { for (const x of groups()) if (x.links.some(([p]) => p === path)) return x.g; return null; };
  function moduleNow() {
    const { path, p } = parse();
    if (!path || path === "home") return null;
    if (path === "mod") return p.m || null;
    return groupOf(path) || LS("bco_module", null);
  }
  const icon = (g, cls) => h("span", { class: cls || "ic", style: "--mc:" + meta(g).c + ";background:" + meta(g).c }, svg(I[meta(g).i] || I.grid));

  /* ── the side menu: only the open module ── */
  function renderNav2() {
    const nav = h("nav", { class: "nav" });
    const mod = moduleNow();
    const gs = groups();
    if (!mod || !gs.find((x) => x.g === mod)) {
      nav.append(h("div", { class: "modhead" }, "Modules"));
      gs.forEach((x) => nav.append(h("a", { href: "#/mod?m=" + encodeURIComponent(x.g), class: "navmod", "data-path": "mod-" + x.g }, icon(x.g), meta(x.g).t)));
      nav._mod = null;
      return nav;
    }
    LSset("bco_module", mod);
    const x = gs.find((y) => y.g === mod);
    nav.append(h("a", { href: "#/home", class: "navback" }, "‹ All modules"),
      h("div", { class: "modhead", style: "--mc:" + meta(mod).c }, icon(mod), meta(mod).t),
      h("a", { href: "#/mod?m=" + encodeURIComponent(mod), "data-path": "mod" }, "Module home"),
      ...x.links.map(([path, label, , badge]) => h("a", { href: "#/" + path, "data-path": path }, label,
        badge && typeof approvalsCount !== "undefined" && approvalsCount ? h("span", { class: "count" }, approvalsCount) : null)));
    nav._mod = mod;
    return nav;
  }
  function syncNav() {
    const nav = document.querySelector(".side .nav");
    if (!nav) return;
    const want = moduleNow();
    if (nav._mod === want && nav._built) return;
    const fresh = renderNav2();
    fresh._built = true;
    nav.replaceWith(fresh);
    const { path } = parse();
    fresh.querySelectorAll("a").forEach((a) => a.classList.toggle("on", a.dataset.path === path || (path === "home" && false)));
  }
  window.addEventListener("hashchange", syncNav);

  /* ── the modules screen ── */
  const hello = () => { const hr = new Date().getHours(); return hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening"; };
  PAGES.home = async (root) => {
    const first = ((S.user && S.user.name) || "").replace(/\(.*?\)/g, "").trim().split(/\s+/)[0] || "";
    root.append(h("div", { class: "modhero" }, h("div", {}, h("h1", {}, hello() + (first ? ", " + first : "")),
      h("p", { class: "sub", style: "margin:2px 0 0" }, "Choose a module to work in. " + ((S.L && S.L.settings && S.L.settings.company_name) || "") + (S.project ? " · project " + nm.project(S.project) : " · all projects"))),
      h("div", { class: "grow" }), h("span", { class: "hint" }, "Ctrl+M brings you back here · Ctrl+K finds any screen")));
    const grid = h("div", { class: "modgrid" });
    groups().forEach((x, i) => {
      const m = meta(x.g);
      const badge = x.g === "Overview" && typeof approvalsCount !== "undefined" && approvalsCount ? h("span", { class: "badge", title: "Waiting for your approval" }, approvalsCount) : null;
      grid.append(h("a", { class: "modcard", href: "#/mod?m=" + encodeURIComponent(x.g), style: "--mc:" + m.c, tabindex: "0" }, badge,
        h("span", { class: "ic" }, svg(I[m.i] || I.grid)), h("b", {}, m.t), h("p", {}, m.d),
        h("div", { class: "foot" }, h("span", {}, x.links.length + " screens"), i < 9 ? h("kbd", { title: "Press this number to open" }, String(i + 1)) : h("i", {}, "Open ›"))));
    });
    root.append(grid);
    let rec = [];
    try { rec = JSON.parse(localStorage.getItem("bco_recent_pages") || "[]"); } catch (e) { rec = []; }
    const labels = {};
    groups().forEach((x) => x.links.forEach(([p, l]) => { labels[p] = l; }));
    rec = rec.filter((p) => labels[p]).slice(0, 6);
    if (rec.length) root.append(h("div", { class: "recentrow" }, h("span", { class: "hint", style: "align-self:center" }, "Continue:"), ...rec.map((p) => h("a", { href: "#/" + p }, labels[p]))));
  };
  /* number keys open a module from the modules screen */
  document.addEventListener("keydown", (e) => {
    if (parse().path !== "home" || e.ctrlKey || e.altKey || e.metaKey || !/^[1-9]$/.test(e.key)) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") || document.querySelector(".overlay")) return;
    const x = groups()[Number(e.key) - 1];
    if (x) { e.preventDefault(); e.stopPropagation(); location.hash = "#/mod?m=" + encodeURIComponent(x.g); }
  }, true);

  /* ── a module's own home ── */
  async function glance(g, box) {
    const add = (label, val) => box.append(h("div", {}, h("b", {}, val), h("span", {}, label)));
    try {
      if (g === "Inventory" && can("inventory", "view")) {
        const r = await api("store.view", { project_id: S.project || null });
        r.summary.forEach((s) => { if (s.items) add(s.label + " (" + s.items + ")", fmtMoney(s.value)); });
        add("Items to reorder", String(r.summary.reduce((a, s) => a + s.below, 0)));
      } else if (g === "Accounts" && can("accounts", "view")) {
        const r = await api("kpi.finance", {});
        ["Cash and bank", "Receivable from clients", "Payable to suppliers", "VAT payable (output less input)", "Profit"].forEach((l) => { const k = r.kpis.find((x) => x.label === l); if (k) add(l + (l === "Profit" ? " (this year)" : ""), fmtMoney(k.value)); });
      } else if (g === "Equipment" && can("equipment", "view")) {
        const r = await api("eq.history", {});
        const s = r.summary;
        add("Machines", String(s.length));
        add("Broken down now", String(s.filter((x) => x.status === "breakdown").length));
        add("Hours worked (all time)", fmtQty(s.reduce((a, x) => a + (x.worked || 0), 0)));
        add("Repair cost (all time)", fmtMoney(s.reduce((a, x) => a + (x.repair_cost || 0), 0)));
      } else if (g === "Commercial" && can("commercial", "view")) {
        const r = await api("con.schedule", { project_id: S.project || null, days: 30 });
        add("Letters / reports overdue", String(r.items.filter((x) => x.state === "overdue").length));
        add("Due in 30 days", String(r.items.filter((x) => x.state !== "overdue").length));
        add("Bonds / insurance expiring", String(r.expiring.length));
      } else if (g === "Work" && can("project", "view") && S.project) {
        const rows = await api("dpr.list", { project_id: S.project });
        add("DPRs waiting to be checked / approved", String(rows.filter((x) => ["submitted", "checked"].includes(x.status)).length));
        add("DPR drafts", String(rows.filter((x) => x.status === "draft").length));
        add("Last DPR", (rows[0] && rows[0].date) || "—");
      } else if (g === "Overview") {
        add("Waiting for your approval", String((typeof approvalsCount !== "undefined" && approvalsCount) || 0));
      }
    } catch (e) { /* figures are a help, never a blocker */ }
    box.hidden = !box.children.length;
  }
  PAGES.mod = async (root, params) => {
    const g = params.m;
    const x = groups().find((y) => y.g === g);
    if (!x) { location.hash = "#/home"; return; }
    const m = meta(g);
    root.style.setProperty("--mc", m.c);
    root.append(h("div", { class: "modhero" }, h("span", { class: "ic", style: "width:48px;height:48px;border-radius:12px;display:grid;place-items:center;background:" + m.c + ";color:#fff" }, svg(I[m.i] || I.grid)),
      h("div", {}, h("h1", {}, m.t), h("p", { class: "sub", style: "margin:2px 0 0" }, m.d)), h("div", { class: "grow" }),
      h("a", { href: "#/home", class: "btn" }, "‹ All modules")));
    const q = (m.q || []).filter(([k]) => true);
    if (q.length) root.append(h("div", { class: "quick", style: "--mc:" + m.c }, ...q.map(([k, label]) => h("button", { class: "btn", onclick: () => { location.hash = "#/" + (({ dpr: "p/dpr", event: "p/events", task: "p/tasks", measure: "p/measure", ipc: "p/ipc", variation: "p/variations", grn: "inv/grn", issue: "inv/issue", ret: "inv/return", transfer: "inv/transfer", mrq: "inv/mrq", count: "inv/count", pr: "proc/pr", po: "proc/po", purchase: "proc/invoices", pay: "acc/payments", receive: "acc/payments", journal: "acc/vouchers", contra: "acc/vouchers", sales: "acc/sales", logday: "eq/logs", run: "pl/runs", asset: "as/register" })[k]) + "?knew=" + k; } }, label))));
    const gl = h("div", { class: "glance", style: "--mc:" + m.c, hidden: true });
    root.append(gl);
    glance(g, gl);
    root.append(h("h2", { class: "sec" }, "Screens"), h("div", { class: "scrgrid", style: "--mc:" + m.c },
      ...x.links.map(([path, label]) => h("a", { class: "scr", href: "#/" + path }, h("span", { class: "dot" }), h("span", {}, label)))));
  };

  /* after sign-in: land on the modules screen and use the one-module side menu */
  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    try { if (typeof HOME === "object") Object.keys(HOME).forEach((k) => { HOME[k] = "home"; }); } catch (e) { /* ignore */ }
    window.renderNav = renderNav2;
    try { renderNav = renderNav2; } catch (e) { /* ignore */ }
    try { if (typeof MENU !== "undefined" && !MENU.some((x) => x[2].some((y) => y[0] === "home"))) { /* home is reached by its own link */ } } catch (e) { /* ignore */ }
  });
  /* keep the side menu in step after the shell is drawn (Refresh redraws it) */
  const mo = new MutationObserver(() => { const nav = document.querySelector(".side .nav"); if (nav && !nav._built) { nav._built = true; nav._mod = moduleNow(); } });
  const startObs = () => mo.observe(document.querySelector("#app") || document.body, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startObs); else startObs();
})();
