/* App shell, navigation, dashboard, approvals and administration */
"use strict";

const MENU = [
  ["Overview", null, [["command", "Command centre", "commercial"], ["action", "Action centre", null, "approvals"], ["mywork", "My work", null], ["inbox", "Inbox & mentions", null],
                      ["p/control", "Project control room", "project"], ["p/kpi", "KPI dashboard", "inventory"], ["p/today", "Today", "project"],
                      ["site", "Site mode", "project"], ["p/live", "Live activity", "project"],
                      ["dashboard", "Company dashboard", "accounts"], ["cl/health", "Company health", "accounts"], ["cl/league", "Project league", "accounts"],
                      ["approvals", "Approvals list", null], ["help", "Help, AI assistant & keys", null], ["copilot", "Copilot (AI reports & writing)", null], ["dc", "Decision centre", "commercial"], ["dc/house", "House & small job estimate", "commercial"], ["rg", "Report generator", null]]],
  ["Work", "project", [["p/dpr", "Daily progress (DPR)"], ["p/schedule", "Schedule & WBS"],
                       ["p/quality", "Quality & NCR", "quality"], ["p/docs", "Documents & photos"], ["f/drawings", "Drawings"], ["f/issues", "Issues & punch list"], ["f/rfis", "RFIs"], ["f/inspections", "Inspections"], ["f/meetings", "Meetings"], ["f/quality", "Quality dashboard"], ["f/report", "Client progress report"], ["dm", "Document control"], ["dm/transmittals", "Transmittals"], ["dl", "Document library"], ["cm", "Discussions"], ["cm/directory", "Project directory & lists"],
                       ["p/tasks", "Tasks"], ["p/events", "Events & claims", "commercial"], ["x/delays", "Delays by responsibility", "project"], ["hs", "Workers & safety"]]],
  ["Commercial", "commercial", [["p/boq", "BOQ control"], ["cl/codes", "Cost codes"], ["p/measure", "Measurements"], ["p/ipc", "IPC billing"],
                                ["p/variations", "Variations"], ["c/contracts", "Contracts & letters"], ["x/sub", "Subcontract work orders"], ["x/plan", "Execution plan"], ["ca", "Contract administration"], ["ca/letters", "Correspondence register"], ["ca/timebars", "Notices & time bars"], ["cr", "Claims register"], ["ca/securities", "Bonds, guarantees & insurance"], ["c/docs", "Contract documents (AI)"], ["p/evm", "Cost & earned value"], ["mg/project", "Project cost & exposure"], ["cl/budget", "Control budget"], ["cl/cvr", "CVR and forecast"], ["cl/close", "Project close"], ["cl/board", "Close status board"], ["cl/cvrall", "CVR, all projects"], ["c/bids", "Bids & markup"]]],
  ["Inventory", "inventory", [["inv/stock", "Stock on hand"], ["inv/store", "Store by kind"], ["mg/stores", "Stock by segment"], ["inv/risk", "Material forecast"],
                              ["inv/mrq", "Requisitions"], ["inv/grn", "Goods received"], ["inv/grnimport", "Import GRNs from Excel"], ["inv/issue", "Issues"],
                              ["inv/return", "Returns"], ["inv/transfer", "Transfers"], ["inv/count", "Stock count"],
                              ["inv/card", "Stock card"], ["inv/recon", "Material reconciliation"],
                              ["inv/opening", "Opening stock"], ["m/stores", "Stores & locations"]]],
  ["Procurement", "procurement", [["proc/pr", "Purchase requests"], ["proc/cs", "Quotation comparison"],
                                  ["proc/po", "Purchase orders"], ["proc/pending", "Pending deliveries"],
                                  ["proc/invoices", "Purchase bills"], ["proc/split", "Project & trading purchases"], ["proc/trade", "Trading sales"], ["proc/vendors", "Vendor performance"],
                                  ["proc/prices", "Price history"]]],
  ["Accounts", "accounts", [["acc/vouchers", "Vouchers"], ["x/queue", "Accounts posting queue"], ["cl/accruals", "Accruals register"], ["mg/modes", "Costs by way of working"], ["acc/payments", "Payments & receipts"],
                            ["acc/sales", "Client invoices"], ["acc/coa", "Chart of accounts"],
                            ["acc/tb", "Trial balance"], ["acc/ledger", "Account ledger"], ["acc/daybook", "Day book"],
                            ["acc/pl", "Profit & loss"], ["acc/bs", "Balance sheet"], ["acc/party", "Party statement"],
                            ["acc/ageing", "Ageing"], ["acc/vat", "VAT books"], ["acc/tds", "TDS register"],
                            ["acc/bank", "Bank reconciliation"], ["acc/budget", "Budget vs actual"], ["acc/cash", "Cash forecast & ratios"], ["x/returns", "Returns (ROA / ROE)"], ["mg/segments", "Finance by segment"],
                            ["acc/periods", "Periods"], ["cl/settings", "Control settings"], ["acc/fy", "Fiscal years"], ["acc/tdsrates", "TDS rates"],
                            ["acc/integrity", "Integrity checks"]]],
  ["Plant", "plant", [["pl/register", "Plant register"], ["pl/mix", "Mix designs"],
                      ["pl/runs", "Production runs"], ["pl/report", "Plant performance"]]],
  ["Assets", "assets", [["as/register", "Asset register"], ["as/dep", "Asset depreciation"], ["x/pools", "Small assets (scaffolding, tools)"]]],
  ["Fixed assets", "assets", [["fa/register", "Capital register"], ["fa/dep", "Depreciation run"],
                             ["fa/costing", "Equipment costing"], ["fa/maint", "Maintenance plan"],
                             ["fa/leases", "Leases (NFRS 16)"], ["fa/impair", "Impairment watch"],
                             ["fa/tax", "Tax depreciation"], ["fa/movement", "PPE note"],
                             ["fa/inventory", "Inventory analysis"]]],
  ["Resources & rates", "masters", [["rp/pool", "Resource pool"], ["rp/norms", "Norms library"],
                                   ["rp/books", "Rate books"], ["rp/ra", "Rate analysis"], ["rp/items", "Item rates (all norms)"], ["rp/hire", "Machine hire rates (DoR)"]]],
  ["Equipment", "equipment", [["eq/register", "Register"], ["eq/books", "Monthly logsheets"],
                              ["eq/logs", "Day-by-day log"], ["eq/rates", "Rate cards"],
                              ["eq/maint", "Maintenance"], ["eq/wo", "Work orders"], ["eq/history", "Repairs & history"], ["eq/hire", "Hired equipment"], ["x/rent", "Rental deductions"], ["x/eqcost", "Equipment cost per hour"], ["mg/eqpool", "Own equipment recovery"], ["cl/equipment", "Equipment business"],
                              ["eq/dep", "Depreciation & hire charges"], ["eq/kpi", "Performance"]]],
  ["Master data", "masters", [["m/projects", "Projects"], ["m/materials", "Materials"],
                              ["m/parties", "Vendors & clients"], ["m/boq", "BOQ items"], ["m/trades", "Labour trades"],
                              ["m/staff", "Staff"], ["m/checklists", "Daily check lists"], ["m/fields", "Extra fields"]]],
  ["Administration", "admin", [["admin/users", "Users"], ["admin/companies", "Companies"], ["admin/ai", "AI assistant settings"], ["admin/team", "Team & devices"],
                               ["admin/remote", "Remote access"], ["admin/sync", "Site packs"], ["admin/licence", "Licence keys"],
                               ["admin/settings", "Settings"],
                               ["admin/backup", "Backup & restore"], ["admin/audit", "Audit log"]]],
];
/* Landing page per role, so each person starts where their work is (spec 44). */
const HOME = { director: "command", project_manager: "p/control", site_engineer: "p/today",
               quantity_surveyor: "p/boq", storekeeper: "inv/stock", procurement_officer: "proc/pr",
               equipment_manager: "eq/kpi", accountant: "dashboard", admin: "command", viewer: "command" };

let approvalsCount = 0;

function parseHash() {
  const home = (S.user && HOME[S.user.role]) || "command";
  const raw = location.hash.replace(/^#\/?/, "") || (PAGES[home] ? home : "dashboard");
  const [path, qs] = raw.split("?");
  const params = {};
  new URLSearchParams(qs || "").forEach((v, k) => { params[k] = v; });
  return { path, params };
}

async function go() {
  const { path, params } = parseHash();
  const root = $("#page");
  if (!root) return;
  root.innerHTML = "";
  document.querySelectorAll(".nav a").forEach((a) => {
    const on = a.dataset.path === path;
    a.classList.toggle("on", on);
    if (on && a.parentElement && a.parentElement.hidden) {
      a.parentElement.hidden = false;
      const head = a.parentElement.previousElementSibling;
      if (head) { head.classList.add("open"); head.setAttribute("aria-expanded", "true"); }
    }
  });
  $(".side").classList.remove("open");
  const page = PAGES[path];
  if (!page) { root.append(pageHead("Page not found"), h("p", {}, h("a", { href: "#/dashboard" }, "Go to the dashboard"))); return; }
  try { await page(root, params); } catch (e) { root.append(h("div", { class: "panel" }, h("b", { class: "red" }, "This page could not load."), h("p", {}, e.message))); }
}

/* The menu stays shut until you want it: only the group you are working in is open,
   and BuildCore remembers which ones you like open. */
function openGroups() {
  try { return JSON.parse(localStorage.getItem("bco_nav_open") || "[]"); } catch (e) { return []; }
}
function setGroupOpen(group, on) {
  const list = openGroups().filter((g) => g !== group);
  if (on) list.push(group);
  try { localStorage.setItem("bco_nav_open", JSON.stringify(list)); } catch (e) { /* ignore */ }
}
function groupOfPath(path) {
  for (const [group, , items] of MENU) {
    if (items.some(([p]) => p === path)) return group;
  }
  return null;
}
function renderNav() {
  const nav = h("nav", { class: "nav" });
  const here = parseHash().path;
  const hereGroup = groupOfPath(here);
  const remembered = openGroups();
  MENU.forEach(([group, module, items]) => {
    if (module && !can(module, "view")) return;
    const links = items.filter(([, , mod]) => !mod || can(mod, "view")).filter(([path]) => PAGES[path]);
    if (!links.length) return;
    const open = group === hereGroup || remembered.includes(group);
    const body = h("div", { class: "nav-items" }, links.map(([path, label, , badge]) =>
      h("a", { href: "#/" + path, "data-path": path }, label,
        badge && approvalsCount ? h("span", { class: "count" }, approvalsCount) : null)));
    const head = h("button", { class: "nav-group" + (open ? " open" : ""), type: "button",
      "aria-expanded": open ? "true" : "false",
      onclick: (e) => {
        const on = !head.classList.contains("open");
        head.classList.toggle("open", on);
        head.setAttribute("aria-expanded", on ? "true" : "false");
        body.hidden = !on;
        setGroupOpen(group, on);
        e.stopPropagation();
      } }, h("i", { class: "caret" }), group,
      links.some(([, , , badge]) => badge) && approvalsCount && !open ? h("span", { class: "count" }, approvalsCount) : null);
    body.hidden = !open;
    nav.append(head, body);
  });
  return nav;
}

function setProject(id, silent) {
  S.project = String(id || "");
  localStorage.setItem("bco_project", S.project);
  const sel = $("#projsel");
  if (sel) sel.value = S.project;
  if (!silent) go();
}

/* Global search (spec 27): one box, results grouped by record type. */
/* Universal search: one box that reaches every record in every module.
   Type two letters and the matches appear grouped, newest first; up and down move
   through them, Enter opens one, and "See all" opens the full results page. */
function goResult(r) {
  if (r.project_id) setProject(r.project_id, true);
  location.hash = r.link;
}
function searchBox() {
  const inp = h("input", { type: "search", placeholder: "Search anything — a bill, a machine, a material, a name, an amount…",
    "aria-label": "Search everything", autocomplete: "off" });
  const panel = h("div", { class: "searchpanel", hidden: true });
  let rows = [], cur = -1, timer = null;
  const close = () => { panel.hidden = true; cur = -1; };
  const hi = () => {
    const links = [...panel.querySelectorAll("a")];
    links.forEach((a, i) => a.classList.toggle("on", i === cur));
    if (links[cur]) links[cur].scrollIntoView({ block: "nearest" });
  };
  const runSearch = async () => {
    const term = inp.value.trim();
    if (term.length < 2) return close();
    try { rows = await api("search", { q: term, project_id: S.project || null }); } catch (e) { return; }
    panel.innerHTML = ""; cur = -1;
    if (!rows.length) {
      panel.append(h("div", { class: "sgroup" }, "Nothing found for “" + term + "”"),
        h("div", { class: "sfoot" }, "Try part of a code, a name, a document number or an amount."));
      panel.hidden = false;
      return;
    }
    const groups = {};
    rows.forEach((r) => { (groups[r.group] = groups[r.group] || []).push(r); });
    Object.entries(groups).forEach(([g, list]) => {
      panel.append(h("div", { class: "sgroup" }, g, h("span", {}, list.length)));
      list.forEach((r) => panel.append(h("a", { href: r.link, onclick: (e) => {
        e.preventDefault(); close(); inp.value = ""; inp.blur(); goResult(r);
      } },
      h("b", {}, r.label),
      h("span", { class: "ssub" }, [r.sub, r.date, r.project_id ? nm.pcode(r.project_id) : ""].filter(Boolean).join(" · ")))));
    });
    panel.append(h("div", { class: "sfoot" },
      h("a", { href: "#/search?q=" + encodeURIComponent(term), onclick: () => { close(); inp.value = ""; } },
        "See every match for “" + term + "” →"),
      h("span", {}, "↑↓ move · Enter open")));
    panel.hidden = false;
  };
  inp.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(runSearch, 200); });
  inp.addEventListener("focus", () => { if (rows.length && inp.value.trim().length >= 2) panel.hidden = false; });
  inp.addEventListener("keydown", (e) => {
    const links = [...panel.querySelectorAll("a")];
    if (e.key === "Escape") { close(); inp.blur(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (panel.hidden || !links.length) return;
      e.preventDefault();
      cur = Math.max(0, Math.min(links.length - 1, cur + (e.key === "ArrowDown" ? 1 : -1)));
      hi();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (cur >= 0 && links[cur]) links[cur].click();
      else if (inp.value.trim().length >= 2) { close(); location.hash = "#/search?q=" + encodeURIComponent(inp.value.trim()); inp.value = ""; inp.blur(); }
    }
  });
  document.addEventListener("click", (e) => { if (!panel.contains(e.target) && e.target !== inp) close(); });
  return h("div", { class: "searchwrap" }, inp, panel);
}

/* Everything that matched, module by module. */
PAGES["search"] = async (root, params) => {
  const term = params.q || "";
  const only = params.group || "";
  const box = h("div");
  const head = pageHead("Search results",
    term ? "Everything that matches “" + term + "” anywhere in BuildCore." : "Type something to search for.");
  const again = h("input", { type: "search", value: term, placeholder: "Search anything…", style: "min-width:320px" });
  again.addEventListener("keydown", (e) => { if (e.key === "Enter") location.hash = "#/search?q=" + encodeURIComponent(again.value.trim()); });
  root.append(head, h("div", { class: "bar" }, again,
    h("button", { class: "btn primary", onclick: () => { location.hash = "#/search?q=" + encodeURIComponent(again.value.trim()); } }, "Search"),
    only ? h("a", { class: "btn", href: "#/search?q=" + encodeURIComponent(term) }, "← all modules") : null), box);
  if (term.length < 2) return;
  const d = await run("search", { q: term, full: 1, group: only || null, limit: only ? 300 : 40 });
  if (!d.rows.length) {
    box.append(h("div", { class: "panel" }, h("b", {}, "Nothing found"),
      h("p", { class: "muted" }, "Nothing anywhere matches “" + term + "”. Search works on codes, names, document "
        + "numbers, narrations, registration numbers, remarks and amounts.")));
    return;
  }
  const counts = d.counts;
  box.append(h("div", { class: "chips" }, Object.entries(counts).map(([g, n]) =>
    h("a", { class: "chip" + (only === g ? " on" : ""), href: "#/search?q=" + encodeURIComponent(term) + "&group=" + encodeURIComponent(g) },
      g, h("i", {}, n)))));
  const groups = {};
  d.rows.forEach((r) => { (groups[r.group] = groups[r.group] || []).push(r); });
  Object.entries(groups).forEach(([g, list]) => {
    box.append(h("h2", { class: "sec" }, g, h("span", { class: "muted" }, "  " + list.length
      + (list.length >= 40 && !only ? "+ — open the group to see them all" : ""))));
    box.append(table([
      { label: "What", v: (r) => h("a", { href: r.link, onclick: (e) => { e.preventDefault(); goResult(r); } }, r.label) },
      { k: "sub", label: "Detail" },
      { k: "date", label: "Date" },
      { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "" },
    ], list, { name: "search_" + g.toLowerCase().replace(/\W+/g, "_"), title: g + " matching " + term,
      onRow: (r) => goResult(r) }));
  });
};

/* Quick add (spec 28): context-sensitive + New. */
function quickAdd() {
  const items = [
    ["DPR", "#/p/dpr?new=1", "project", "edit"], ["Material issue", "#/inv/issue?new=1", "inventory", "edit"],
    ["Goods received", "#/inv/grn?new=1", "inventory", "edit"], ["Requisition", "#/inv/mrq?new=1", "inventory", "edit"],
    ["Purchase request", "#/proc/pr?new=1", "procurement", "edit"], ["Equipment log (month)", "#/eq/books", "equipment", "edit"],
    ["Equipment log (one day)", "#/eq/logs?new=1", "equipment", "edit"],
    ["Measurement", "#/p/measure?new=1", "commercial", "edit"], ["IPC", "#/p/ipc", "commercial", "edit"],
    ["Variation", "#/p/variations?new=1", "commercial", "edit"], ["Event / claim", "#/p/events?new=1", "project", "view"],
    ["Test request", "#/p/quality?new=1", "quality", "edit"], ["Task", "#/p/tasks?new=1", "project", "view"],
    ["Production run", "#/pl/runs?new=1", "plant", "edit"], ["Asset", "#/as/register?new=1", "assets", "edit"],
    ["Photo", "#/p/docs?photo=1", "project", "view"], ["Payment", "#/acc/payments", "accounts", "edit"],
    ["Voucher", "#/acc/vouchers", "accounts", "edit"],
  ].filter(([, , m, a]) => can(m, a));
  if (!items.length) return null;
  const menu = h("div", { class: "qamenu", hidden: true }, items.map(([l, href]) => h("a", { href, onclick: () => { menu.hidden = true; } }, l)));
  const btn = h("button", { class: "btn primary", onclick: (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; } }, "+ New");
  document.addEventListener("click", () => { menu.hidden = true; });
  return h("div", { class: "qawrap" }, btn, menu);
}

function shell() {
  const app = $("#app");
  app.innerHTML = "";
  const projSel = h("select", { id: "projsel", "aria-label": "Current project", onchange: (e) => setProject(e.target.value) },
    h("option", { value: "" }, "All projects"),
    S.L.projects.filter((p) => p.status === "active" || String(p.id) === String(S.project))
      .map((p) => h("option", { value: p.id, selected: String(p.id) === String(S.project) }, p.code + " — " + p.name)));
  const side = h("aside", { class: "side" }, h("div", { class: "brand" }, h("b", {}, "BuildCore"), h("span", {}, S.L.settings.company_name)), renderNav());
  app.append(h("div", { class: "shell" }, side,
    h("div", { class: "main" },
      h("div", { class: "top" },
        h("button", { class: "btn menu-btn", onclick: (e) => { e.stopPropagation(); side.classList.toggle("open"); } }, "Menu"),
        h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:8px" }, h("span", {}, "Project"), projSel),
        searchBox(),
        h("div", { class: "grow" }),
        quickAdd(),
        h("button", { class: "btn small", onclick: async () => { try { await reloadLookups(); shell(); toast("Refreshed"); } catch (e) { /* offline banner already shown */ } } }, "Refresh"),
        liveBadge(),
        h("span", { class: "muted who" }, S.user.name + " · " + S.user.role.replace(/_/g, " ")
          + (S.user.location ? " · " + S.user.location : "")),
        h("button", { class: "btn small", onclick: changePassword }, "Password"),
        h("button", { class: "btn small", onclick: async () => { try { await api("auth.logout"); } catch (e) { /* ignore */ } localStorage.removeItem("bco_token"); location.reload(); } }, "Sign out")),
      h("main", { class: "page", id: "page" }))));
  go();
  startLive();
}

function changePassword() {
  const f = form([{ k: "old", label: "Current password", type: "password" }, { k: "new", label: "New password (6+ characters)", type: "password" }]);
  modal("Change password", f, [{ label: "Change password", cls: "primary", act: () => run("auth.password", f.values(), "Password changed") }], { narrow: true });
}

/* ── dashboard ── */
PAGES.dashboard = async (root) => {
  const d = await run("dash.summary", { project_id: S.project || null });
  approvalsCount = d.approvals;
  const tile = (label, value, href, cls) => h("div", { class: "tile " + (cls || ""), onclick: () => { location.hash = href; } }, h("b", {}, value), h("span", {}, label));
  const tiles = [tile("Waiting for approval", d.approvals, "#/approvals", d.approvals ? "warn" : "")];
  if (d.stock_value != null) tiles.push(tile("Stock value", fmtMoney(d.stock_value), "#/inv/stock"), tile("Items at reorder level", d.low_stock.length, "#/inv/stock", d.low_stock.length ? "warn" : ""), tile("Transfers in transit", d.in_transit, "#/inv/transfer", d.in_transit ? "warn" : ""));
  if (d.pending_deliveries != null) tiles.push(tile("PO lines pending", d.pending_deliveries, "#/proc/pending"), tile("Late deliveries", d.overdue_deliveries, "#/proc/pending", d.overdue_deliveries ? "bad" : ""), tile("Open PO value", fmtMoney(d.open_po_value), "#/proc/pending"));
  if (d.payables_due != null) tiles.push(tile("Payables overdue", fmtMoney(d.payables_due), "#/acc/ageing", d.payables_due ? "warn" : ""), tile("Receivables overdue", fmtMoney(d.receivables_due), "#/acc/ageing", d.receivables_due ? "bad" : ""), tile("Cost this month", fmtMoney(d.month_cost), "#/acc/pl"));
  if (d.maintenance_due) tiles.push(tile("Services due", d.maintenance_due.length, "#/eq/maint", d.maintenance_due.length ? "warn" : ""), tile("Machines down", d.breakdowns.length, "#/eq/wo", d.breakdowns.length ? "bad" : ""));
  root.append(pageHead(S.project ? nm.project(S.project) : "All projects", "Today, " + today()));
  root.append(h("div", { class: "flow" }, "Material flow:", ...[["#/inv/mrq", "Requisition"], ["#/proc/pr", "Purchase request"], ["#/proc/cs", "Quotes"], ["#/proc/po", "Purchase order"], ["#/inv/grn", "Goods received"], ["#/proc/invoices", "Bill"], ["#/acc/payments", "Payment"]].flatMap(([hr, l], i) => [i ? h("i", {}, "›") : null, h("a", { href: hr }, l)]),
    h("span", { style: "margin-left:14px" }, "Site use:"), ...[["#/inv/issue", "Issue"], ["#/inv/return", "Return"], ["#/inv/count", "Count"], ["#/inv/recon", "Reconcile"]].flatMap(([hr, l], i) => [i ? h("i", {}, "›") : null, h("a", { href: hr }, l)])));
  root.append(h("div", { class: "tiles" }, tiles));
  const cols = h("div", { class: "cols" });
  if (d.cost_trend) {
    const max = Math.max(1, ...d.cost_trend.map((x) => Math.max(x.cost, x.revenue)));
    cols.append(h("div", { class: "panel" }, h("h2", {}, "Cost by month (last six)"), h("div", { class: "bars" }, d.cost_trend.map((x) => h("div", { title: "Cost " + fmtMoney(x.cost) + " / revenue " + fmtMoney(x.revenue) }, h("i", { style: "height:" + (100 * x.cost / max) + "%" }), x.month.slice(2)))),
      h("h2", { style: "margin-top:14px" }, "Cash & bank"), table([{ k: "name", label: "Account" }, { k: "balance", label: "Balance", fmt: "money" }], d.cash_bank, { search: false, export: false })));
  }
  if (d.low_stock) cols.append(h("div", { class: "panel" }, h("h2", {}, "Reorder or negative stock"), table([{ label: "Project", v: (r) => r.project_code }, { k: "name", label: "Material" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "reorder_level", label: "Reorder at", fmt: "qty" }], d.low_stock, { search: false, export: false, empty: "All items are above reorder level." })));
  if (d.maintenance_due) {
    cols.append(h("div", { class: "panel" }, h("h2", {}, "Equipment attention"),
      table([{ label: "Equipment", v: (r) => nm.eq(r.equipment_id) }, { k: "title", label: "Service" }, { k: "state", label: "State" }], d.maintenance_due, { search: false, export: false, empty: "No services due." }),
      d.compliance.length ? h("div", {}, h("h3", {}, "Documents expiring within 30 days"), table([{ k: "code", label: "Code" }, { k: "insurance_expiry", label: "Insurance" }, { k: "registration_expiry", label: "Registration" }], d.compliance, { search: false, export: false })) : null,
      d.idle.length ? h("div", {}, h("h3", {}, "Working machines with no logsheet for 7 days"), h("p", {}, d.idle.map((x) => x.code).join(", "))) : null,
      d.breakdowns.length ? h("div", {}, h("h3", {}, "Down now"), h("p", { class: "red" }, d.breakdowns.map((x) => x.code + " " + x.name).join(", "))) : null));
  }
  root.append(cols);
  const nb = document.querySelector('.nav a[data-path="approvals"]');
  if (nb) { nb.querySelector(".count")?.remove(); if (approvalsCount) nb.append(h("span", { class: "count" }, approvalsCount)); }
};

/* ── approvals inbox ── */
PAGES.approvals = async (root) => {
  const rows = await run("dash.approvals", {});
  const open = async (r) => {
    if (r.kind === "voucher") return voucherView(r.id, go);
    if (r.kind === "cs") return csEditor({ id: r.id });
    if (r.kind === "log") { if (r.project_id) setProject(r.project_id, true); location.hash = "#/eq/logs"; return; }
    const cfg = { mrq: MRQ, pr: PR, po: PO, count: COUNT }[r.kind];
    if (r.project_id && String(r.project_id) !== String(S.project)) setProject(r.project_id, true);
    openDoc(Object.assign({}, cfg, { refresh: go }), r.id);
  };
  root.append(pageHead("Approvals", "Everything waiting for someone to approve, across all projects."),
    table([{ k: "label", label: "Type" }, { label: "No.", v: (r) => r.kind === "log" ? r.no + " logsheets" : (r.no || "Draft #" + r.id) }, { k: "date", label: "Date" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "amount", label: "Amount", fmt: "money" }, { label: "", v: (r) => r.can_approve ? "You can approve" : "" }], rows, { onRow: open, empty: "Nothing is waiting for approval." }));
};

/* ── administration ── */
const ROLE_OPTS = [["admin", "Administrator"], ["director", "Director"], ["project_manager", "Project manager"],
  ["site_engineer", "Site engineer"], ["quantity_surveyor", "Quantity surveyor (QS)"], ["accountant", "Accountant"],
  ["storekeeper", "Storekeeper"], ["procurement_officer", "Procurement officer"],
  ["equipment_manager", "Equipment manager"], ["viewer", "Viewer (read only)"]];
const PERM_MODULES = ["masters", "project", "commercial", "inventory", "procurement", "accounts", "equipment", "plant", "assets", "quality", "admin"];
PAGES["admin/users"] = async (root) => {
  const rows = await run("admin.users", {});
  const edit = (u) => {
    const f = form([{ k: "username", label: "Username", req: true }, { k: "name", label: "Full name", req: true }, { k: "role", label: "Role", type: "select", noBlank: true, options: ROLE_OPTS }, { k: "password", label: u ? "New password (leave blank to keep)" : "Password", type: "password" }, { k: "active", label: "Active", type: "check" }], u || { active: 1, role: "storekeeper" });
    modal(u ? "Edit user" : "New user", f, [{ label: "Save", cls: "primary", act: async () => { await run("admin.user_save", { row: Object.assign(f.values(), { id: u && u.id }) }, "Saved"); await reloadLookups(); go(); } }], { narrow: true });
  };
  const perm = h("div", { class: "tablewrap", style: "margin-top:18px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Role"), PERM_MODULES.map((m) => h("th", {}, m)))),
    h("tbody", {}, h("tr", {}, h("td", { colspan: PERM_MODULES.length + 1, class: "hint" }, "view / edit / approve per module")), ...ROLE_OPTS.map(([r, l]) => h("tr", {}, h("td", {}, l), PERM_MODULES.map((m) => h("td", {}, ((ROLE_TABLE[r] || {})[m] || []).join(", ") || "—")))))));
  root.append(pageHead("Users", "Separate duties: the person who creates a voucher cannot approve it unless they are an administrator.", h("button", { class: "btn primary", onclick: () => edit(null) }, "New user")),
    table([{ k: "username", label: "Username" }, { k: "name", label: "Name" }, { k: "role", label: "Role" }, { k: "active", label: "Active", fmt: "yes" }], rows, { onRow: edit, search: false }), perm);
};
const A3 = ["view", "edit", "approve"], VE = ["view", "edit"], VA = ["view", "approve"], V1 = ["view"];
const ROLE_TABLE = {
  admin: Object.fromEntries(PERM_MODULES.map((m) => [m, A3])),
  director: Object.fromEntries(PERM_MODULES.filter((m) => m !== "admin").map((m) => [m, VA])),
  project_manager: { masters: VE, inventory: VA, procurement: VA, accounts: V1, equipment: VA, project: A3, commercial: A3, quality: A3, plant: VA, assets: V1 },
  site_engineer: { masters: V1, inventory: VE, procurement: V1, equipment: VE, project: VE, commercial: V1, quality: VE, plant: VE, assets: V1 },
  quantity_surveyor: { masters: VE, inventory: V1, procurement: V1, accounts: V1, equipment: V1, project: VE, commercial: VE, quality: V1, plant: V1, assets: V1 },
  accountant: { masters: VE, inventory: V1, procurement: VE, accounts: A3, equipment: V1, project: V1, commercial: VE, quality: V1, plant: V1, assets: A3 },
  storekeeper: { masters: V1, inventory: VE, procurement: V1, equipment: V1, project: V1, plant: VE, assets: V1 },
  procurement_officer: { masters: VE, inventory: V1, procurement: VE, equipment: V1, project: V1 },
  equipment_manager: { masters: V1, inventory: VE, procurement: V1, equipment: A3, project: V1, plant: A3, assets: VE },
  viewer: Object.fromEntries(PERM_MODULES.filter((m) => m !== "admin").map((m) => [m, V1])),
};

PAGES["admin/settings"] = async (root) => {
  const s = S.L.settings;
  const f = form([
    { k: "company_name", label: "Company name" }, { k: "company_pan", label: "Company PAN" }, { k: "company_address", label: "Address", wide: true },
    { k: "vat_rate", label: "Default VAT %", type: "number" }, { k: "price_tol_pct", label: "Invoice vs PO rate tolerance %", type: "number" },
    { k: "over_receipt_pct", label: "Allowed over-receipt on PO %", type: "number" }, { k: "min_quotes", label: "Quotes needed without a reason", type: "number" },
    { k: "high_value_po", label: "POs above this need an administrator", type: "number" }, { k: "shift_hours", label: "Scheduled hours per day (equipment)", type: "number" },
    { k: "voucher_approval", label: "Manual vouchers need a second approver", type: "check" },
    { k: "allow_negative_stock", label: "Allow negative stock (not recommended)", type: "check" },
    { k: "po_terms", label: "Default PO terms", type: "textarea", wide: true },
  ], s);
  root.append(pageHead("Settings"), h("div", { class: "panel" }, f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("admin.settings", { values: f.values() }, "Settings saved"); await reloadLookups(); shell(); } }, "Save settings"))));
};

PAGES["admin/backup"] = async (root) => {
  const list = await run("admin.backups", {});
  const up = h("input", { type: "file", accept: ".db" });
  root.append(pageHead("Backup & restore", "A backup is made automatically every day while BuildCore runs (the last 30 are kept in the backups folder" + (IS_DESKTOP ? ", menu File → Open backups folder" : "") + "). Copy backups to a USB drive or another computer regularly."),
    h("div", { class: "panel" }, h("h2", {}, "Make a backup"), h("div", { class: "actions" },
      h("button", { class: "btn primary", onclick: () => { window.location = "/api/backup/download?token=" + encodeURIComponent(S.token); } }, "Download a backup now"),
      h("button", { class: "btn", onclick: async () => { const r = await run("admin.backup", {}, "Backup saved"); go(); return r; } }, "Save a backup in the backups folder"))),
    h("div", { class: "panel" }, h("h2", {}, "Restore"), h("p", { class: "red" }, "Restoring replaces all current data with the backup. The current data is backed up first."), up,
      h("div", { class: "actions" }, h("button", { class: "btn warn", onclick: async () => {
        if (!up.files[0]) return toast("Choose a backup file.", "err");
        if (!(await ask("Restore backup", "Replace ALL current data with " + up.files[0].name + "?", { danger: true, ok: "Restore" }))) return;
        const r = await fetch("/api/restore", { method: "POST", headers: { "X-Token": S.token }, body: await up.files[0].arrayBuffer() });
        const j = await r.json();
        if (!j.ok) return toast(j.error, "err");
        toast("Restored. Please sign in again.", "ok");
        setTimeout(() => { localStorage.removeItem("bco_token"); location.reload(); }, 1500);
      } }, "Restore from file"))),
    h("h2", {}, "Saved backups"), table([{ k: "file", label: "File" }, { label: "Size", v: (r) => (r.size / 1024).toFixed(0) + " KB" }, { label: "", v: (r) => h("a", { href: "/api/backup/download?file=" + encodeURIComponent(r.file) + "&token=" + encodeURIComponent(S.token) }, "Download") }], list, { empty: "No backups yet." }));
};

PAGES["admin/audit"] = async (root) => {
  let v = {};
  const holder = h("div");
  const load = async () => {
    const rows = await run("admin.audit", v);
    holder.innerHTML = "";
    holder.append(table([{ k: "ts", label: "When" }, { label: "User", v: (r) => nm.user(r.user_id) }, { k: "action", label: "Action" }, { k: "entity", label: "Record" }, { k: "entity_id", label: "Id" }, { label: "Detail", v: (r) => (r.detail || "").slice(0, 140) }], rows, { name: "audit", onRow: (r) => modal("Audit entry", h("pre", { style: "white-space:pre-wrap" }, JSON.stringify(JSON.parse(r.detail || "null"), null, 2)), [], { narrow: true }) }));
  };
  root.append(pageHead("Audit log", "Who created, changed, posted, approved or cancelled what."), filterBar([{ k: "entity", label: "Record type", ph: "e.g. grn, vouchers" }, { k: "user_id", label: "User", type: "select", options: () => S.L.users.map((u) => [u.id, u.name]) }], v, (x) => { v = x; load(); }), holder);
  load();
};

/* ── sign-in & first run ── */
async function loginScreen() {
  const st = await api("auth.status");
  const app = $("#app");
  app.innerHTML = "";
  if (st.needs_setup) {
    const f = form([{ k: "company_name", label: "Company name" }, { k: "name", label: "Your name" }, { k: "username", label: "Administrator username", default: "admin" }, { k: "password", label: "Password (6+ characters)", type: "password" }]);
    app.append(h("div", { class: "login" }, h("h1", {}, "Set up BuildCore"), h("p", { class: "muted" }, "Create the first administrator. Everything is stored in your own Supabase database."), f,
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { const r = await run("auth.setup", f.values()); S.token = r.token; localStorage.setItem("bco_token", r.token); start(); } }, "Create administrator"))));
    return;
  }
  const u = h("input", { name: "u", autocomplete: "username" });
  const p = h("input", { name: "p", type: "password", autocomplete: "current-password" });
  app.append(h("div", { class: "login" }, h("h1", {}, "BuildCore"), h("p", { class: "muted" }, st.company),
    h("form", { onsubmit: async (e) => { e.preventDefault(); const r = await run("auth.login", { username: u.value, password: p.value }); S.token = r.token; localStorage.setItem("bco_token", r.token); start(); } },
      h("label", { class: "f" }, h("span", {}, "Username"), u), h("label", { class: "f" }, h("span", {}, "Password"), p), h("button", { class: "btn primary", type: "submit" }, "Sign in"))));
  u.focus();
}

async function start() {
  if (!S.token) return loginScreen();
  try {
    S.user = await api("auth.me");
    await reloadLookups();
    if (S.project && !byId(S.L.projects, S.project)) { S.project = ""; localStorage.removeItem("bco_project"); }
    try { approvalsCount = (await api("dash.approvals")).filter((x) => x.can_approve).length; } catch (e) { approvalsCount = 0; }
  } catch (e) {
    localStorage.removeItem("bco_token"); S.token = null;
    return loginScreen();
  }
  shell();
}

window.addEventListener("hashchange", go);
if (window.bcoBoot) window.bcoBoot(); else start();
