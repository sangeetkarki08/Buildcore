/* BuildCore 2.20/2.22 — Company Workspace and Project Workspace.
   After sign-in you work in one of two places. The Company Workspace holds the whole company:
   accounting, payables and receivables, VAT, central store, trading, equipment, assets, HR
   masters, the project portfolio and administration. The Project Workspace holds one project:
   its dashboard, BOQ, DPR, schedule, store, procurement, costs, billing, documents and reports.
   Same screens, same records, same books — only organised by where you work, with the engine
   refusing what a role may not reach. */
(function () {
  "use strict";
  const VER = "2.22.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };

  /* ───────────────────────── the workspace menus ─────────────────────────
     Section → [path, label?]. A path that is not loaded (older install) simply does not show.
     Labels fall back to the existing menu's own labels. */
  const C_MENU = [
    ["Dashboard", null, [["ws/company", "Company overview"], ["dashboard"], ["command", "Portfolio"], ["p/kpi"], ["dc"], ["risks", "Risk register"],
      ["copilot"], ["dashboard/classic", "Classic dashboard"], ["action"], ["approvals"], ["mywork"], ["inbox"], ["p/live"], ["help"]]],
    ["Finance & Accounts", "accounts", [["acc/coa"], ["acc/ledger"], ["acc/daybook"], ["acc/tb"], ["acc/integrity"],
      ["acc/payments"], ["acc/bank"], ["acc/sales"], ["acc/ageing"], ["acc/party"], ["proc/invoices", "Purchase bills (payable)"],
      ["acc/vouchers"], ["acc/pl"], ["acc/bs"], ["acc/vat"], ["acc/tds"], ["acc/tdsrates"],
      ["acc/budget"], ["acc/cash"], ["ws/projcost", "Project cost vs ledger"], ["acc/periods"], ["acc/fy"]]],
    ["Procurement & Trading", "procurement", [["m/parties", "Suppliers & customers"], ["proc/vendors"], ["proc/prices"],
      ["proc/pr"], ["proc/cs"], ["proc/po"], ["proc/pending"], ["proc/split"], ["proc/trade"], ["ws/trading", "Trading stock"]]],
    ["Central Operations", "inventory", [["ws/central", "Central store"], ["ws/inventory", "Stock by location"],
      ["inv/stock"], ["inv/store"], ["inv/transfer"], ["inv/card"], ["inv/risk"], ["fa/inventory"], ["m/materials"], ["m/stores"],
      ["eq/register", "Equipment register"], ["eq/kpi"], ["eq/history"], ["eq/hire"], ["eq/rates"], ["eq/dep"],
      ["fa/register"], ["fa/dep"], ["fa/costing"], ["fa/maint"], ["fa/leases"], ["fa/impair"], ["fa/tax"], ["fa/movement"],
      ["as/register"], ["as/dep"], ["pl/register"], ["pl/mix"], ["pl/report"], ["m/staff", "Employees (HR)"], ["m/trades"]]],
    ["Projects", "project", [["m/projects", "Project register"], ["p/control", "Project portfolio"], ["ws/compare", "Project comparison"],
      ["p/evm", "Consolidated earned value"], ["m/boq"], ["c/contracts"], ["ca/securities"], ["c/docs"],
      ["c/bids"], ["dc/house"], ["rp/pool"], ["rp/norms"], ["rp/books"], ["rp/ra"], ["rp/items"], ["rp/hire"]]],
    ["Administration", "admin", [["admin/users"], ["ws/roles", "Users & roles (workspaces)"], ["admin/settings"], ["admin/companies"],
      ["admin/audit"], ["dm", "Document management"], ["dm/transmittals"], ["cm"], ["cm/directory"], ["admin/ai"], ["admin/team"],
      ["admin/remote"], ["admin/sync"], ["admin/licence"], ["admin/backup"], ["m/checklists"], ["m/fields"]]],
  ];
  const P_MENU = [
    ["Project Dashboard", null, [["ws/project", "Project overview"], ["p/control", "Control room"], ["p/kpi"], ["p/today"], ["risks", "Risk register"],
      ["action"], ["approvals"], ["mywork"], ["inbox"], ["site"], ["p/live"], ["help"]]],
    ["Planning & Execution", "project", [["p/boq", "BOQ & quantities"], ["m/boq", "BOQ items"], ["p/measure", "Work progress (measurements)"],
      ["p/dpr"], ["p/schedule", "Schedule & milestones"], ["p/quality"], ["f/inspections"], ["f/quality"], ["f/issues"], ["f/rfis"], ["p/tasks"], ["f/report"]]],
    ["Project Store", "inventory", [["inv/grn", "Store receipt (GRN)"], ["inv/grnimport"], ["inv/issue", "Material issue"],
      ["inv/transfer", "Material transfer"], ["inv/return", "Material return"], ["inv/stock", "Stock balance"], ["inv/store"],
      ["inv/card"], ["inv/risk"], ["inv/opening"], ["m/stores"], ["inv/count", "Physical stock verification"]]],
    ["Project Procurement", "procurement", [["inv/mrq", "Material requests"], ["proc/pr"], ["proc/cs"], ["proc/po"],
      ["proc/pending", "Supplier deliveries"], ["proc/invoices", "Project purchase records"], ["proc/split"]]],
    ["Cost & Commercial", "commercial", [["ws/projcost", "Project expenses"], ["c/contracts", "Subcontractors"], ["p/ipc", "IPC & billing"],
      ["p/variations"], ["p/events", "Events & claims"], ["ca/timebars"], ["acc/budget", "Budget vs actual"], ["p/evm"]]],
    ["Resources", "equipment", [["eq/books", "Equipment logsheets"], ["eq/logs"], ["eq/kpi", "Equipment utilization"], ["eq/wo"], ["eq/maint"],
      ["hs", "Manpower & safety"], ["m/staff", "Project staff"], ["inv/recon", "Materials consumption"], ["pl/runs", "Plant production"]]],
    ["Documents & Reports", "project", [["ca", "Correspondence"], ["ca/letters"], ["ca/securities"], ["f/drawings"], ["p/docs"],
      ["dm"], ["dm/transmittals"], ["cm", "Discussions"], ["cm/directory"], ["c/docs"], ["f/meetings", "Meetings & reports"]]],
  ];
  // screens that belong to the company only: opening one from a Project Workspace shows a notice
  const COMPANY_ONLY = new Set();
  C_MENU.forEach(([, , items]) => items.forEach(([p]) => COMPANY_ONLY.add(p.split("?")[0])));
  P_MENU.forEach(([, , items]) => items.forEach(([p]) => COMPANY_ONLY.delete(p.split("?")[0])));
  ["help", "search", "home", "mod", "verify"].forEach((p) => COMPANY_ONLY.delete(p));

  const WS = { info: null };          // S.user.workspace, kept fresh by start/auth.me
  const active = () => (WS.info && WS.info.active) || null;
  const FULL_LABELS = {};             // path -> label from the original menu

  const css = document.createElement("style");
  css.textContent = [
    ".wslogin{max-width:860px;margin:7vh auto;padding:0 16px}.wslogin h1{margin:0 0 4px}",
    ".wscards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:22px}",
    ".wscard{background:var(--panel,#fff);border:2px solid var(--line,#d6dee5);border-radius:16px;padding:22px;cursor:pointer;text-align:left;transition:border-color .12s,box-shadow .12s}",
    ".wscard:hover,.wscard.on{border-color:#1769aa;box-shadow:0 10px 28px rgba(16,42,60,.12)}",
    ".wscard b{font-size:18px;display:block;margin-bottom:6px}.wscard p{margin:0;color:var(--muted,#5b7183);font-size:13.5px;line-height:1.5}",
    ".wscard .tag{display:inline-block;margin-bottom:10px;font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:#1769aa}",
    ".wsproj{margin-top:14px;display:grid;gap:8px}.wsproj a{display:flex;justify-content:space-between;border:1px solid var(--line,#d6dee5);border-radius:10px;padding:10px 14px;text-decoration:none;color:inherit}",
    ".wsproj a:hover{border-color:#1769aa;background:rgba(23,105,170,.06)}",
    ".wsbadge{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:3px 12px;font-size:12.5px;font-weight:600;cursor:pointer;border:1px solid transparent}",
    ".wsbadge.co{background:#10324a;color:#cfe6f5}.wsbadge.pr{background:#1c5e3a;color:#d9f2e3}",
    ".wsbadge:hover{filter:brightness(1.15)}.wsbadge .sw{opacity:.75;font-weight:400}",
    ".wscrumb{font-size:12px;color:var(--muted,#5b7183);margin:0 0 8px}.wscrumb b{color:inherit;font-weight:600}",
    ".wstiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin:0 0 16px}",
    ".wstiles .t{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-left:4px solid #1769aa;border-radius:12px;padding:10px 14px;cursor:pointer}",
    ".wstiles .t b{display:block;font-size:19px}.wstiles .t span{color:var(--muted,#5b7183);font-size:12.5px}",
    ".wstiles .t.warn{border-left-color:#b7791f}.wstiles .t.bad{border-left-color:#c0392b}.wstiles .t.good{border-left-color:#2f7a4d}",
    ".wsnote{background:rgba(23,105,170,.07);border:1px solid rgba(23,105,170,.25);border-radius:10px;padding:10px 14px;margin:0 0 14px;font-size:13.5px}",
  ].join("\n");
  document.head.append(css);

  /* ───────────────────────── choosing the workspace ───────────────────────── */
  function chooser(afterSwitch) {
    const w = WS.info || {};
    const projs = w.projects || [];
    const body = h("div", { class: "wscards" });
    const projList = (into) => {
      into.innerHTML = "";
      projs.forEach((p) => into.append(h("a", { href: "#", onclick: async (e) => {
        e.preventDefault();
        await enter("project", p.id, afterSwitch);
      } }, h("span", {}, h("b", {}, p.code), " " + p.name), h("span", { class: "muted" }, "Open ›"))));
    };
    if (w.company) {
      body.append(h("button", { class: "wscard" + (w.default === "company" ? " on" : ""), onclick: () => enter("company", null, afterSwitch) },
        h("span", { class: "tag" }, "Company Workspace"), h("b", {}, S.L && S.L.settings ? S.L.settings.company_name : "The company"),
        h("p", {}, "Consolidated accounts and statements, cash and bank, payables and receivables, VAT, central store, trading, equipment and assets, HR masters, the project portfolio and administration.")));
    }
    if (projs.length) {
      const list = h("div", { class: "wsproj" });
      const card = h("div", { class: "wscard" + (w.default === "project" ? " on" : ""), style: "cursor:default" },
        h("span", { class: "tag", style: "color:#1c5e3a" }, "Project Workspace"),
        h("b", {}, projs.length === 1 ? projs[0].code + " — " + projs[0].name : "Choose a project"),
        h("p", {}, "The project's dashboard, BOQ and progress, DPR, schedule, store, procurement, costs and billing, equipment, documents and reports."), list);
      projList(list);
      body.append(card);
    }
    if (!w.company && !projs.length) {
      body.append(h("div", { class: "panel" }, h("b", {}, "Nothing is assigned to you yet"),
        h("p", { class: "muted" }, "Ask an administrator to assign you to a project or give your role company access (Administration › Users and roles).")));
    }
    return body;
  }

  async function enter(ws, pid, afterSwitch) {
    try {
      const r = await api("ws.enter", { workspace: ws, project_id: pid || null });
      WS.info.active = r.workspace;
      WS.info.active_project = r.project_id;
      if (r.workspace === "project" && r.project_id) setProjectLocal(r.project_id);
      applyMenu();
      const land = "#/" + wsHome();
      try { history.replaceState(null, "", land); } catch (e) { location.hash = land; }
      if (afterSwitch) afterSwitch();
      else if (typeof shell === "function") shell();
    } catch (e) {
      toast(e.message, "err");
    }
  }

  /* where a workspace opens: the familiar modules screen; the company side honours the
     2.18 "Open BuildCore here" dashboard preference */
  function wsHome() {
    if (active() !== "project" && LSg("bco_start_dash", "1") === "1" && PAGES.dashboard) return "dashboard";
    if (PAGES.home) return "home";
    return active() === "project" ? "ws/project" : "ws/company";
  }

  function setProjectLocal(pid) {
    S.project = String(pid || "");
    LSs("bco_project", S.project);
  }

  function chooserScreen() {
    const app = $("#app");
    app.innerHTML = "";
    const w = WS.info || {};
    app.append(h("div", { class: "wslogin" },
      h("h1", {}, "Where will you work?"),
      h("p", { class: "muted" }, (S.user ? S.user.name + " · " + (w.role_name || S.user.role) : "") +
        " — your workspace decides which screens you see. You can switch any time from the bar at the top."),
      chooser()));
  }

  /* ───────────────────────── menu by workspace ─────────────────────────
     2.22: the menu keeps the familiar modules (Overview, Site work, Store & inventory,
     Procurement, Accounts, Equipment …) exactly as before — same groups, same names,
     same order, same badges. The workspace only decides which screens show inside them,
     and the few new workspace screens sit inside their natural modules. */
  let ORIG = null;                    // the familiar menu, captured once at boot
  function rememberLabels() {
    if (typeof MENU === "undefined") return;
    if (!ORIG) ORIG = MENU.map(([g, m, items]) => [g, m, items.map((it) => it.slice())]);
    MENU.forEach(([, , items]) => items.forEach(([p, l]) => { if (!FULL_LABELS[p]) FULL_LABELS[p] = l; }));
  }
  const NEW_LABELS = { "ws/company": "Company overview", "ws/project": "Project overview", "ws/inventory": "Stock by location",
    "ws/central": "Central store", "ws/compare": "Project comparison", "ws/projcost": "Project cost vs ledger", "ws/roles": "Users & roles (workspaces)" };
  // screens that belong to projects only: hidden in the Company Workspace menu
  const PROJECT_ONLY = new Set();
  P_MENU.forEach(([, , items]) => items.forEach(([p]) => PROJECT_ONLY.add(p.split("?")[0])));
  C_MENU.forEach(([, , items]) => items.forEach(([p]) => PROJECT_ONLY.delete(p.split("?")[0])));
  ["help", "search", "home", "mod", "verify"].forEach((p) => PROJECT_ONLY.delete(p));

  // the workspace screens, placed inside the familiar modules: [group, after which path (null = first), [path, label, module]]
  const INJECT_CO = [
    ["Overview", null, ["ws/company", "Company overview", "accounts"]],
    ["Overview", "command", ["ws/compare", "Project comparison", "project"]],
    ["Inventory", null, ["ws/inventory", "Stock by location", "inventory"]],
    ["Inventory", "ws/inventory", ["ws/central", "Central store", "inventory"]],
    ["Procurement", "proc/trade", ["ws/trading", "Trading stock", "inventory"]],
    ["Accounts", "acc/budget", ["ws/projcost", "Project cost vs ledger", "accounts"]],
    ["Administration", "admin/users", ["ws/roles", "Users & roles (workspaces)", "admin"]],
  ];
  const INJECT_PR = [
    ["Overview", null, ["ws/project", "Project overview", "project"]],
  ];
  function applyMenu() {
    if (typeof MENU === "undefined" || !S.user) return;
    rememberLabels();
    if (!ORIG) return;
    const projWs = WS.info && active() === "project";
    const hide = projWs ? COMPANY_ONLY : PROJECT_ONLY;
    const out = [];
    ORIG.forEach(([group, gmod, items]) => {
      const links = items.filter((it) => !hide.has(it[0].split("?")[0])).map((it) => it.slice());
      if (links.length) out.push([group, gmod, links]);
    });
    (projWs ? INJECT_PR : INJECT_CO).forEach(([group, after, item]) => {
      const g = out.find((x) => x[0] === group);
      if (!g || g[2].some((y) => y[0] === item[0])) return;
      const i = after ? g[2].findIndex((y) => y[0] === after) : -1;
      g[2].splice(after ? (i >= 0 ? i + 1 : g[2].length) : 0, 0, item.slice());
    });
    MENU.length = 0;
    (window.bcoJobMenu ? window.bcoJobMenu(out) : out).forEach((g) => MENU.push(g));
    // permission filtering stays where it always was: renderNav checks each module right
  }

  /* ───────────────────────── header: badge, switcher, locked project ───────────────────────── */
  function decorateTop() {
    const top = document.querySelector(".top");
    if (!top || top.querySelector(".wsbadge") || !WS.info) return;
    const aw = active();
    const pid = WS.info.active_project;
    const label = aw === "project" ? ("Project · " + (nm.project(pid) || nm.pcode(pid) || "")).trim() : "Company Workspace";
    const canSwitch = (WS.info.company && (WS.info.projects || []).length) || (WS.info.projects || []).length > 1;
    const badge = h("button", { class: "wsbadge " + (aw === "project" ? "pr" : "co"),
      title: canSwitch ? "Switch workspace" : "Your workspace",
      onclick: () => { if (!canSwitch && !(WS.info.projects || []).length) return; modal("Switch workspace", chooser(() => { document.querySelectorAll(".overlay").forEach((o) => o.remove()); shell(); }), [], {}); } },
      label, canSwitch ? h("span", { class: "sw" }, "⇄") : null);
    const menuBtn = top.querySelector(".menu-btn");
    if (menuBtn) menuBtn.after(badge); else top.prepend(badge);
    const sel = top.querySelector("#projsel");
    if (sel && aw === "project") {
      if (pid) { sel.value = String(pid); S.project = String(pid); }
      sel.disabled = true;
      sel.title = "This workspace works in one project. Use the workspace switcher to change it.";
      const allOpt = sel.querySelector('option[value=""]');
      if (allOpt) allOpt.remove();
    }
  }

  /* ───────────────────────── breadcrumbs and the workspace gate ───────────────────────── */
  function crumbOf(path) {
    const spec = active() === "project" ? P_MENU : C_MENU;
    const wsName = active() === "project" ? "Project Workspace" : "Company Workspace";
    for (const [group, , items] of spec) {
      const hit = items.find(([p]) => p.split("?")[0] === path);
      if (hit) return [wsName, group, hit[1] || FULL_LABELS[path] || NEW_LABELS[path] || ""];
    }
    return null;
  }
  function wrapPages() {
    Object.keys(PAGES).forEach((path) => {
      const f = PAGES[path];
      if (typeof f !== "function" || f._bco220) return;
      const wrapped = async (root, params) => {
        if (WS.info && active() === "project" && COMPANY_ONLY.has(path)) {
          root.append(pageHead("Company screen"),
            h("div", { class: "panel" }, h("b", {}, "This screen belongs to the Company Workspace."),
              h("p", { class: "muted" }, WS.info.company
                ? "Switch to the Company Workspace to open it."
                : "Your role works in the Project Workspace. Ask an administrator if you need company access."),
              WS.info.company ? h("div", { class: "actions" }, h("button", { class: "btn primary",
                onclick: () => enter("company") }, "Switch to the Company Workspace")) : null));
          return;
        }
        /* 2.18's shell already prepends a "Modules \u203a \u2026" crumb for any screen in MENU;
           add ours only for screens the current menu does not list */
        const inMenu = typeof MENU !== "undefined" && MENU.some((g) => (g[2] || []).some((it) => it[0] === path));
        if (!inMenu) {
          const cr = WS.info && crumbOf(path);
          if (cr && path !== "home" && path !== "mod") {
            root.append(h("div", { class: "wscrumb" }, cr[0] + " › " + cr[1] + (cr[2] ? " › " : ""), h("b", {}, cr[2] || "")));
          }
        }
        return f(root, params);
      };
      wrapped._bco220 = true;
      PAGES[path] = wrapped;
    });
  }

  /* a company-wide money entry from inside a project: ask first */
  const CONFIRM_FNS = { "voucher.save": "a journal voucher", "payment.create": "a payment or receipt" };
  function wrapMoneyConfirm() {
    Object.keys(CONFIRM_FNS).forEach(() => { /* applied through run() below */ });
    if (window.run && !window.run._bco220) {
      const orig = window.run;
      const run2 = async function (fn, args, okMsg) {
        if (WS.info && active() === "project" && CONFIRM_FNS[fn] && !run2._asked) {
          const yes = await ask("Company-wide entry", "You are in the " + (nm.pcode(WS.info.active_project) || "project") +
            " Project Workspace, but " + CONFIRM_FNS[fn] + " posts in the company's books. Continue?", { ok: "Yes, continue" });
          if (!yes) throw new Error("Cancelled.");
        }
        return orig(fn, args, okMsg);
      };
      run2._bco220 = true;
      try { window.run = run2; run = run2; } catch (e) { window.run = run2; }
    }
  }

  /* ───────────────────────── Company overview ───────────────────────── */
  const tile = (label, value, href, cls) => h("div", { class: "t " + (cls || ""), onclick: href ? () => { location.hash = href; } : null },
    h("b", {}, value == null ? "—" : value), h("span", {}, label));

  PAGES["ws/company"] = async (root) => {
    const d = await run("ws.company_overview", {});
    const k = d.kpis || {};
    root.append(pageHead(d.company || "Company overview", "The whole company on " + d.as_of + ". Figures come from the books as they stand."));
    const money = d.money !== false;
    const fin = {};
    (d.finance || []).forEach((x) => { fin[x.label] = x.value; });
    const tiles = [];
    if (fin["Cash and bank"] != null) tiles.push(tile("Cash and bank", fmtMoney(fin["Cash and bank"]), "#/acc/bank"));
    if (fin["Receivable from clients"] != null) tiles.push(tile("Receivable from clients", fmtMoney(fin["Receivable from clients"]), "#/acc/ageing"));
    if (fin["Payable to suppliers"] != null) tiles.push(tile("Payable to suppliers", fmtMoney(fin["Payable to suppliers"]), "#/acc/ageing", "warn"));
    if (fin["Profit"] != null) tiles.push(tile("Profit (this year)", fmtMoney(fin["Profit"]), "#/acc/pl", (fin["Profit"] || 0) < 0 ? "bad" : "good"));
    if (k.forecast_profit != null) tiles.push(tile("Forecast profit at completion", fmtMoney(k.forecast_profit), "#/dashboard", k.forecast_profit < 0 ? "bad" : ""));
    if (d.stock_value != null) tiles.push(tile("Stock value", fmtMoney(d.stock_value), "#/ws/inventory"));
    if (d.open_po_value != null) tiles.push(tile("Open purchase orders", fmtMoney(d.open_po_value), "#/proc/pending"));
    if (d.receivables_due != null) tiles.push(tile("Receivables overdue", fmtMoney(d.receivables_due), "#/acc/ageing", d.receivables_due ? "bad" : ""));
    if (d.payables_due != null) tiles.push(tile("Payables overdue", fmtMoney(d.payables_due), "#/acc/ageing", d.payables_due ? "warn" : ""));
    tiles.push(tile("Waiting for approval", String(d.approvals || 0), "#/approvals", d.approvals ? "warn" : ""));
    if (d.breakdowns) tiles.push(tile("Machines down", String(d.breakdowns), "#/eq/wo", "bad"));
    root.append(h("div", { class: "wstiles" }, tiles));
    const cols = h("div", { class: "cols" });
    if ((d.projects || []).length) {
      cols.append(h("div", { class: "panel" }, h("h2", {}, "Projects"),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Project" },
          { label: "Progress", v: (r) => r.actual_pct != null ? fmtQty(r.actual_pct) + "% of " + fmtQty(r.planned_pct) + "%" : "" },
          { k: "spi", label: "SPI" }, { k: "cpi", label: "CPI" },
          money ? { k: "forecast_margin", label: "Margin %", fmt: "qty" } : null,
          money ? { k: "receivable", label: "Receivable", fmt: "money" } : null].filter(Boolean),
        d.projects, { search: false, name: "ws_projects", onRow: (r) => { setProjectLocal(r.id); location.hash = "#/p/control?project_id=" + r.id; } })));
    }
    if ((d.budget || []).length && money) {
      cols.append(h("div", { class: "panel" }, h("h2", {}, "Budget vs actual by project"),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Project" }, { k: "budget", label: "Budget", fmt: "money" },
          { k: "actual", label: "Actual cost", fmt: "money" },
          { label: "Used", v: (r) => r.budget ? Math.round(100 * (r.actual || 0) / r.budget) + "%" : "" }],
        d.budget, { search: false, name: "ws_budget", totals: ["budget", "actual"] })));
    }
    const sl = d.stock_locations || {};
    const slRows = ["project", "central", "trading", "transit"].map((g) => ({ g, label: { project: "Project stores", central: "Central store", trading: "Trading stock", transit: "Goods in transit" }[g], stores: (sl[g] || {}).stores || 0, value: (sl[g] || {}).value || 0 }));
    cols.append(h("div", { class: "panel" }, h("h2", {}, "Stock by location"),
      table([{ k: "label", label: "Where" }, { k: "stores", label: "Stores", fmt: "num" }, { k: "value", label: "Value", fmt: "money" }],
        slRows, { search: false, export: false, totals: ["value"], onRow: () => { location.hash = "#/ws/inventory"; } }),
      (d.cash_bank || []).length ? h("div", {}, h("h3", { style: "margin-top:12px" }, "Cash & bank"),
        table([{ k: "name", label: "Account" }, { k: "balance", label: "Balance", fmt: "money" }], d.cash_bank, { search: false, export: false })) : null));
    root.append(cols);
  };

  /* ───────────────────────── Project overview ───────────────────────── */
  PAGES["ws/project"] = async (root) => {
    const pid = (WS.info && WS.info.active_project) || S.project;
    if (!pid) { root.append(projectNotice()); return; }
    const d = await run("ws.project_overview", { project_id: pid });
    const p = d.project || {};
    root.append(pageHead(p.code + " — " + p.name, "Project overview on " + d.as_of + (p.client ? " · " + p.client : "")));
    const pr = d.progress || {}, co = d.cost || {}, bi = d.billing || {};
    const tiles = [
      tile("Progress (actual vs planned)", (pr.actual_pct != null ? fmtQty(pr.actual_pct) + "% / " + fmtQty(pr.planned_pct) + "%" : "—"), "#/p/schedule", (pr.variance || 0) < 0 ? "warn" : "good"),
      tile("SPI", pr.spi != null ? pr.spi : "—", "#/p/control", pr.spi && pr.spi < 0.95 ? "bad" : ""),
      tile("CPI", co.cpi != null ? co.cpi : "—", "#/p/evm", co.cpi && co.cpi < 0.95 ? "bad" : ""),
      tile("Cost to date", co.ac != null ? fmtMoney(co.ac) : "—", "#/ws/projcost"),
      tile("Budget (BOQ)", co.bac != null ? fmtMoney(co.bac) : "—", "#/acc/budget"),
      tile("Billed", bi.billed != null ? fmtMoney(bi.billed) : "—", "#/p/ipc"),
      tile("Receivable", bi.receivable != null ? fmtMoney(bi.receivable) : "—", "#/p/ipc", bi.receivable ? "warn" : ""),
      tile("Open site issues", String(d.issues_open || 0), "#/f/issues", d.issues_open ? "warn" : ""),
      tile("Waiting for approval", String((d.approvals || []).length), "#/approvals", (d.approvals || []).length ? "warn" : ""),
    ];
    if (pr.forecast_finish) tiles.push(tile("Forecast finish", pr.forecast_finish, "#/p/schedule"));
    root.append(h("div", { class: "wstiles" }, tiles));
    const cols = h("div", { class: "cols" });
    if ((d.store || []).length) {
      cols.append(h("div", { class: "panel" }, h("h2", {}, "Project store"),
        table([{ k: "label", label: "Kind" }, { k: "items", label: "Items", fmt: "num" }, { k: "value", label: "Value", fmt: "money" }],
          d.store.filter((s) => s.items), { search: false, export: false, empty: "The store is empty." }),
        h("div", { class: "actions" }, h("a", { class: "btn", href: "#/inv/grn" }, "Receive"), h("a", { class: "btn", href: "#/inv/issue" }, "Issue"), h("a", { class: "btn", href: "#/inv/stock" }, "Stock balance"))));
    }
    if ((d.milestones || []).length) {
      cols.append(h("div", { class: "panel" }, h("h2", {}, "Milestones"),
        table([{ k: "name", label: "Milestone" }, { k: "planned_finish", label: "Planned" }, { k: "actual_finish", label: "Actual" }],
          d.milestones, { search: false, export: false })));
    }
    if ((d.attention || []).length) {
      cols.append(h("div", { class: "panel" }, h("h2", {}, "Needs attention"),
        table([{ k: "category", label: "What" }, { k: "title", label: "Item" }, { k: "due", label: "Due" }],
          d.attention, { search: false, export: false, onRow: (r) => { if (r.link) location.hash = r.link; } })));
    }
    root.append(cols);
  };

  /* ───────────────────────── Stock by location ───────────────────────── */
  PAGES["ws/inventory"] = async (root, params) => {
    const d = await run("ws.stock_locations", {});
    const only = (params || {}).kind || "";
    root.append(pageHead(only === "trading" ? "Trading stock" : "Stock by location",
      "Project stores, the central store, trading stock and goods in transit — added once, next to the inventory accounts in the ledger."));
    const order = only === "trading" ? ["trading"] : ["project", "central", "trading", "transit"];
    const names = { project: "Project stores", central: "Central store", trading: "Trading stock", transit: "Goods in transit" };
    order.forEach((g) => {
      const grp = (d.groups || {})[g] || { rows: [], value: 0 };
      root.append(h("h2", { class: "sec" }, names[g], h("span", { class: "muted" }, "  " + fmtMoney(grp.value))));
      root.append(table([{ k: "pcode", label: "Cost centre" }, { k: "pname", label: "Name" }, { k: "store", label: "Store" },
        { k: "items", label: "Items", fmt: "num" }, { k: "value", label: "Value", fmt: "money" }],
        grp.rows, { name: "ws_stock_" + g, search: false, totals: ["value"], empty: "Nothing here.",
          onRow: (r) => { setProjectLocal(r.project_id); location.hash = "#/inv/stock"; } }));
    });
    if (!only) {
      const okRec = Math.abs(d.difference || 0) < 1;
      root.append(h("div", { class: "wsnote" }, h("b", {}, "Reconciliation: "),
        "stock in all locations " + fmtMoney(d.total) + " · inventory accounts in the ledger " + fmtMoney(d.ledger_inventory) +
        (okRec ? " · agreed ✓" : " · difference " + fmtMoney(d.difference) + " — check Integrity checks and unposted receipts.")));
    }
  };

  /* ───────────────────────── Central store ───────────────────────── */
  PAGES["ws/central"] = async (root) => {
    root.append(pageHead("Central store", "The company's own store: receive centrally, then transfer to project stores with dispatch and receipt records."));
    const cc = (S.L.projects || []).find((p) => (p.kind || "") === "general") ||
      (await (async () => { try { const m = await api("proc.meta", {}); return (m.cost_centres || []).find((x) => x.kind === "general"); } catch (e) { return null; } })());
    if (!cc) {
      root.append(h("div", { class: "panel" }, h("b", {}, "The central store is not set up yet."),
        h("p", { class: "muted" }, "One click creates the GENERAL cost centre with its Central Store. Nothing else changes."),
        can("masters", "edit") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
          await run("ws.central_setup", {}, "Central store ready");
          await reloadLookups(); go();
        } }, "Set up the central store")) : h("p", { class: "hint" }, "Ask an administrator to set it up.")));
      return;
    }
    const rows = await run("stock.report", { project_id: cc.id });
    root.append(h("div", { class: "actions", style: "margin-bottom:12px" },
      h("button", { class: "btn primary", onclick: () => { setProjectLocal(cc.id); location.hash = "#/inv/grn?new=1"; } }, "+ Receive (GRN)"),
      h("button", { class: "btn", onclick: () => { setProjectLocal(cc.id); location.hash = "#/inv/transfer?new=1"; } }, "Transfer to a project"),
      h("button", { class: "btn", onclick: () => { setProjectLocal(cc.id); location.hash = "#/inv/issue?new=1"; } }, "Issue for company use"),
      h("button", { class: "btn", onclick: () => { setProjectLocal(cc.id); location.hash = "#/inv/count"; } }, "Stock count")));
    root.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { k: "store", label: "Store", v: (r) => nm.store(r.store_id) },
      { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "value", label: "Value", fmt: "money" }],
      rows, { name: "ws_central", totals: ["value"], empty: "The central store is empty. Receive goods into it, or transfer from a project." }));
  };

  /* ───────────────────────── Project comparison ───────────────────────── */
  PAGES["ws/trading"] = async (root) => PAGES["ws/inventory"](root, { kind: "trading" });

  PAGES["ws/compare"] = async (root) => {
    const d = await run("ws.compare", {});
    root.append(pageHead("Project comparison", "One row per project on " + d.as_of + ". Click a project to open its control room."));
    root.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Project" },
      { k: "contract_value", label: "Contract", fmt: "money" },
      { label: "Progress", v: (r) => r.actual_pct != null ? fmtQty(r.actual_pct) + "%" : "" },
      { k: "spi", label: "SPI" }, { k: "cpi", label: "CPI" },
      { k: "budget", label: "Budget", fmt: "money" }, { k: "cost", label: "Cost to date", fmt: "money" },
      { k: "forecast_margin", label: "Margin %", fmt: "qty" },
      { k: "stock_value", label: "Stock", fmt: "money" }, { k: "receivable", label: "Receivable", fmt: "money" }],
      d.rows || [], { name: "ws_compare", totals: ["contract_value", "budget", "cost", "stock_value", "receivable"],
        onRow: (r) => { setProjectLocal(r.id); location.hash = "#/p/control"; },
        empty: "No active projects." }));
  };

  /* ───────────────────────── Project cost vs ledger ───────────────────────── */
  PAGES["ws/projcost"] = async (root) => {
    let v = {};
    const holder = h("div");
    const load = async () => {
      const d = await run("ws.project_cost", v);
      holder.innerHTML = "";
      holder.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Project / cost centre" },
        { k: "kind", label: "Kind", v: (r) => r.kind || (r.project_id ? "construction" : "") },
        { k: "cost", label: "Cost (posted)", fmt: "money" }, { k: "income", label: "Income (posted)", fmt: "money" }],
        d.rows, { name: "ws_projcost", totals: ["cost", "income"], onRow: (r) => { if (r.project_id) { setProjectLocal(r.project_id); location.hash = "#/acc/budget"; } } }),
        h("div", { class: "wsnote" }, h("b", {}, "Adds back to the books: "), "cost " + fmtMoney(d.total_cost) + " and income " +
          fmtMoney(d.total_income) + " are the company ledger's own totals for the period — project views never change the consolidated figures."));
    };
    root.append(pageHead("Project cost vs ledger", "Cost and income by project, straight from posted vouchers, with the unallocated part shown."),
      filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], v, (x) => { v = x; load(); }), holder);
    await load();
  };

  /* ───────────────────────── Users & roles ───────────────────────── */
  const ACTS = ["view", "create", "edit", "submit", "approve", "post", "export", "delete"];
  PAGES["ws/roles"] = async (root) => {
    const d = await run("ws.roles", {});
    const editRole = (r) => {
      const f = form([{ k: "name", label: "Role name", req: true },
        { k: "company", label: "May enter the Company Workspace", type: "check" },
        { k: "projects", label: "Projects", type: "select", noBlank: true, options: [["assigned", "Only assigned projects"], ["all", "All projects"], ["none", "None (company only)"]] },
        { k: "active", label: "Active", type: "check" }], r || { active: 1, projects: "assigned" });
      const grid = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Module"), ACTS.map((a) => h("th", { style: "font-size:11px" }, a)))),
        h("tbody", {}, d.modules.map((m) => h("tr", {}, h("td", {}, m), ACTS.map((a) => {
          const i = h("input", { type: "checkbox", checked: !!(r && (r.perms[m] || []).includes(a)) });
          i.dataset.m = m; i.dataset.a = a; return h("td", {}, i);
        })))));
      modal(r ? "Edit role template" : "New role template", h("div", {}, f,
        h("h4", { style: "margin:12px 0 6px" }, "What this role may do"), h("div", { class: "tablewrap" }, grid),
        h("p", { class: "hint" }, "create / edit / submit also allow edit; approve / post / delete also allow approve; export allows view.")),
      [{ label: "Save", cls: "primary", act: async () => {
        const perms = {};
        grid.querySelectorAll("input:checked").forEach((i) => { (perms[i.dataset.m] = perms[i.dataset.m] || []).push(i.dataset.a); });
        await run("ws.role_save", { row: Object.assign(f.values(), { key: r ? r.key : undefined, perms }) }, "Saved");
        go();
      } }], {});
    };
    root.append(pageHead("Users and roles", "Role templates decide the workspace, the projects and the actions. Assign people to projects below.",
      can("admin", "edit") ? h("button", { class: "btn primary", onclick: () => {
        const name = prompt("Name of the new role template:");
        if (name) editRole({ key: name.toLowerCase().replace(/\W+/g, "_"), name, perms: {}, projects: "assigned", active: 1, company: 0 });
      } }, "New role template") : null));
    root.append(table([{ k: "name", label: "Role template" }, { k: "key", label: "Key" },
      { label: "Workspace", v: (r) => r.company ? (r.projects === "none" ? "Company" : "Company + Project") : "Project" },
      { label: "Projects", v: (r) => ({ all: "All", assigned: "Assigned only", none: "—" })[r.projects] || r.projects },
      { k: "users", label: "Users", fmt: "num" }, { k: "active", label: "Active", fmt: "yes" },
      { label: "", v: (r) => r.builtin ? "built-in" : "" }],
      d.roles, { name: "ws_roles", search: false, onRow: can("admin", "edit") ? editRole : null }));
    /* people and their projects */
    const users = await run("admin.users", {});
    const projs = (S.L.projects || []).filter((p) => (p.kind || "") !== "trading" && (p.kind || "") !== "general");
    const me = await api("auth.me");
    const assign = (u2) => {
      const roleOpts = d.roles.filter((r) => r.active).map((r) => [r.key, r.name]);
      const f = form([{ k: "role", label: "Role template", type: "select", noBlank: true, options: roleOpts }], u2);
      const boxes = projs.map((p) => { const i = h("input", { type: "checkbox", checked: ((u2.project_ids || "") + "").split(",").includes(String(p.id)) }); i.dataset.id = p.id; return h("label", { class: "f check" }, i, p.code + " — " + p.name); });
      modal("Workspace access — " + u2.name, h("div", {}, f, h("h4", { style: "margin:12px 0 6px" }, "Assigned projects"),
        h("div", { class: "grid" }, boxes), h("p", { class: "hint" }, "Nothing ticked = all projects (as before the update), until you assign some.")),
      [{ label: "Save", cls: "primary", act: async () => {
        const ids = boxes.filter((b) => b.querySelector("input").checked).map((b) => b.querySelector("input").dataset.id);
        await run("admin.user_save", { row: { id: u2.id, username: u2.username, name: u2.name, role: f.values().role, active: u2.active, project_ids: ids } }, "Saved");
        go();
      } }], { narrow: true });
    };
    let rows2 = users;
    try { rows2 = await api("adm.users2", {}); } catch (e) { /* fine */ }
    // admin.users does not return project_ids; read them through auth of each? keep from users list when present
    root.append(h("h2", { class: "sec" }, "People"),
      table([{ k: "username", label: "Username" }, { k: "name", label: "Name" },
        { label: "Role", v: (r) => (d.roles.find((x) => x.key === r.role) || { name: r.role }).name },
        { label: "Workspace", v: (r) => { const t = d.roles.find((x) => x.key === r.role); return t ? (t.company ? (t.projects === "none" ? "Company" : "Company + Project") : "Project") : ""; } },
        { label: "Projects", v: (r) => r.project_ids ? String(r.project_ids).split(",").filter(Boolean).map((i) => nm.pcode(i)).join(", ") : "All" },
        { k: "active", label: "Active", fmt: "yes" }],
        rows2, { name: "ws_users", onRow: can("admin", "edit") ? assign : null }));
    void me;
  };

  /* ───────────────────────── boot ───────────────────────── */
  function afterLogin() {
    WS.info = (S.user && S.user.workspace) || null;
    if (!WS.info) return true;                       // engine without 2.20: behave as before
    applyMenu();
    if (!active()) {
      // one place to land: company-only or single-project users go straight in
      const auto = (!WS.info.company && (WS.info.projects || []).length === 1) ? "project"
        : (WS.info.company && !(WS.info.projects || []).length) ? "company" : null;
      if (auto) { enter(auto, auto === "project" ? WS.info.projects[0].id : null); return false; }
      chooserScreen();
      return false;                                  // shell is drawn after the choice
    }
    if (active() === "project" && WS.info.active_project) setProjectLocal(WS.info.active_project);
    try {
      const land = wsHome();
      if (typeof HOME === "object") Object.keys(HOME).forEach((k) => { HOME[k] = land; });
    } catch (e) { /* ignore */ }
    return true;
  }

  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    rememberLabels();
    wrapPages();
    wrapMoneyConfirm();
    /* the company-profile menu focus (2.14) is superseded by the workspace menus */
    window.bcoApplyFocus = function () { applyMenu(); };
    const _shell = window.shell;
    const shell2 = function () {
      if (!afterLogin()) return;
      _shell();
      decorateTop();
      wrapPages();                                   // pages registered after boot
    };
    window.shell = shell2;
    try { shell = shell2; } catch (e) { /* ignore */ }
    });

  /* default landing: the workspace's own overview */
  const _parse = () => (location.hash.replace(/^#\/?/, "").split("?")[0]) || "";
  window.addEventListener("hashchange", () => {
    if (!WS.info || !active()) return;
    if (_parse() === "" || (_parse() === "home" && !LSg("bco_ws_home", ""))) { /* keep modules screen reachable */ }
  });

  /* What's new */
  function whatsNew() {
    if (LSg("bco_seen_2.22.0", "")) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_2.22.0", "1");
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:560px" },
      h("p", {}, "The workspaces now keep the familiar screens."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "Your modules, as before."), " After choosing a workspace you land on the modules screen — Store, BOQ, DPR, Accounts and the rest, with the same names, groups and order as always. The workspace only decides which of them you see."),
        h("li", {}, h("b", {}, "Company Workspace."), " The company modules open ready to work: accounts, procurement, central store and trading, equipment and assets, masters and administration, plus Company overview, Stock by location and Project cost vs ledger inside them."),
        h("li", {}, h("b", {}, "Project Workspace."), " One project at a time, with its full module set; the project selector stays locked to your project."),
        h("li", {}, h("b", {}, "Same rules underneath."), " Role templates and the engine-level protection from 2.20 are unchanged.")),
      h("p", { class: "hint" }, "Switch workspace any time from the coloured badge at the top.")),
    [{ label: "Open my modules", cls: "primary", act: () => { location.hash = "#/" + wsHome(); } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && WS.info && active()) { clearInterval(seen); setTimeout(whatsNew, 1200); } }, 800);
})();
