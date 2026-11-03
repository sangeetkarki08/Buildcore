/* BuildCore 2.44 - People and access: Job + Where.
   Administration › Users is the one place to set a person up: job, where they work (head office or chosen
   projects), password and active. Each job shows only its own menu groups (same names and order as always),
   with "Show all my screens" for anything else the person may open. Projects get a Team screen
   (acc/team) with Copy team from. The 2.20 engine checks are unchanged. */
(function () {
  "use strict";
  const VER = "2.44.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };

  const css = document.createElement("style");
  css.textContent = [
    ".acc-tags span{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11.5px;background:#e8f0fa;color:#2c6fb3;margin:1px 3px 1px 0}",
    ".acc-tags span.warn{background:#fff4e0;color:#9a5b00}",
    ".acc-about{font-size:12.5px;color:var(--muted);background:var(--bg,#f5f7fa);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:10px 0 4px}",
    ".acc-where{display:flex;gap:24px;margin:6px 0 8px;flex-wrap:wrap}.acc-where label{display:flex!important;flex-direction:row!important;gap:8px;align-items:center;cursor:pointer;white-space:nowrap;width:auto!important;font-weight:600}",
    ".acc-where label input{width:auto!important;margin:0}",
    ".acc-plist{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:4px 14px;max-height:240px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px;margin-top:6px}",
    ".acc-plist label{display:flex;gap:6px;align-items:center;font-size:13px}.acc-plist label.off{color:var(--muted)}.acc-plist label[hidden]{display:none}",
    ".acc-check{border-left:4px solid #e0a020}",
    ".acc-showall{display:block;margin:10px 18px 14px;font-size:12.5px;color:#9fb6cf!important;cursor:pointer;text-decoration:none}",
    ".acc-showall:hover{color:#fff!important}",
    ".acc-grid td,.acc-grid th{text-align:center;padding:4px 6px}.acc-grid td:first-child,.acc-grid th:first-child{text-align:left}",
    ".acc-menus{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:4px 12px;margin:6px 0}",
  ].join("");
  document.head.append(css);

  /* ───────────────────────── job menus ───────────────────────── */
  const wsInfo = () => (typeof S !== "undefined" && S.user && S.user.workspace) || null;
  const showAllKey = () => "bco_job_showall_" + ((S.user && S.user.username) || "");
  const showingAll = () => LSg(showAllKey(), "0") === "1";
  function jobMenu() {
    const w = wsInfo();
    if (!w || !Array.isArray(w.menu) || showingAll()) return null;
    return w.menu;
  }
  /* keep only the job's groups in MENU (every menu builder rebuilds MENU from its own copy, so this is
     re-applied after each rebuild) */
  function filterMenu() {
    if (typeof MENU === "undefined") return;
    MENU.forEach((g) => g[2].forEach((it) => { if (it[0] === "ws/roles") it[1] = "Jobs & permissions"; }));
    const keep = jobMenu();
    if (!keep) return;
    for (let i = MENU.length - 1; i >= 0; i--) if (!keep.includes(MENU[i][0])) MENU.splice(i, 1);
  }
  window.bcoJobMenu = { filter: filterMenu, active: () => !!jobMenu() };
  function toggleAll() {
    LSs(showAllKey(), showingAll() ? "0" : "1");
    try { if (typeof window.bcoApplyFocus === "function") window.bcoApplyFocus(); } catch (e) { /* ignore */ }
    filterMenu();
    try { if (typeof shell === "function") shell(); else location.reload(); } catch (e) { location.reload(); }
    setTimeout(() => { try { window.dispatchEvent(new HashChangeEvent("hashchange")); } catch (e) { /* ignore */ } }, 50);
  }
  function addShowAll() {
    const w = wsInfo();
    if (!w || !Array.isArray(w.menu)) return;
    const nav = document.querySelector(".side .nav");
    if (!nav || nav.querySelector(".acc-showall")) return;
    nav.append(h("a", { class: "acc-showall", title: "Your job shows only its own modules. Everything you may open stays available.",
      onclick: (e) => { e.preventDefault(); toggleAll(); } }, showingAll() ? "‹ Show only my job's modules" : "Show all my screens ›"));
  }
  new MutationObserver(() => addShowAll()).observe(document.documentElement, { childList: true, subtree: true });

  function hookMenus() {
    if (typeof window.renderNav === "function" && !window.renderNav._bco244) {
      const orig = window.renderNav;
      const rn = function () { filterMenu(); return orig.apply(this, arguments); };
      Object.keys(orig).forEach((k) => { try { rn[k] = orig[k]; } catch (e) { /* ignore */ } });
      rn._bco244 = true;
      window.renderNav = rn;
      try { renderNav = rn; } catch (e) { /* ignore */ } // eslint-disable-line no-global-assign
    }
    const f = window.bcoApplyFocus;
    if (typeof f === "function" && !f._bco244) {
      const g = function () { const r = f.apply(this, arguments); filterMenu(); return r; };
      g._bco244 = true;
      window.bcoApplyFocus = g;
    }
    ["home", "mod"].forEach((p) => {
      const pg = PAGES[p];
      if (!pg || pg._bco244) return;
      const w = async (root, params) => { filterMenu(); return pg(root, params); };
      w._bco244 = true;
      PAGES[p] = w;
    });
  }
  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    hookMenus();
    const _shell = window.shell;
    if (typeof _shell === "function" && !_shell._bco244) {
      const s2 = function () { const r = _shell.apply(this, arguments); hookMenus(); return r; };
      s2._bco244 = true;
      window.shell = s2;
      try { shell = s2; } catch (e) { /* ignore */ } // eslint-disable-line no-global-assign
    }
  });

  /* ───────────────────────── people ───────────────────────── */
  const tags = (list, warn) => h("span", { class: "acc-tags" }, list.map((x) => h("span", { class: warn ? "warn" : "" }, x)));
  const whereCell = (p) => p.sees === "unset" ? tags(["nothing ticked - sees all projects"], true)
    : p.sees === "all" ? "Head office - all projects" : (p.projects.length ? tags(p.projects) : tags(["no project"], true));

  async function personWindow(d, p, after) {
    const jobs = d.jobs;
    const isNew = !p;
    p = p || { active: 1, role: "storekeeper", project_ids: [], ws_where: "projects" };
    const jobSel = h("select", { name: "role" }, jobs.map((j) => h("option", { value: j.key, selected: j.key === p.role }, j.name)));
    const about = h("div", { class: "acc-about" });
    const jobOf = () => jobs.find((j) => j.key === jobSel.value) || {};
    let where = p.ws_where || (p.sees === "all" ? "all" : "projects");
    if (p.role === "admin") where = "all";
    const rAll = h("input", { type: "radio", name: "acc_where", checked: where === "all" });
    const rPrj = h("input", { type: "radio", name: "acc_where", checked: where !== "all" });
    const search = h("input", { type: "search", placeholder: "Search projects (code or name)…" });
    const count = h("span", { class: "hint" });
    const boxes = d.projects.map((x) => {
      const i = h("input", { type: "checkbox", checked: (p.project_ids || []).includes(x.id) });
      i.dataset.id = x.id;
      const l = h("label", { class: x.status === "active" ? "" : "off" }, i, x.code + " — " + x.name + (x.status === "active" ? "" : " (" + x.status + ")"));
      l._text = (x.code + " " + x.name).toLowerCase();
      i.onchange = () => upd();
      return l;
    });
    const plist = h("div", { class: "acc-plist" }, boxes);
    const pbox = h("div", {}, search, count, plist);
    search.oninput = () => { const t = search.value.trim().toLowerCase(); boxes.forEach((b) => { b.hidden = t && !b._text.includes(t); }); };
    function upd() {
      const j = jobOf();
      const menu = j.menu ? j.menu.filter((g) => !(d.always || []).includes(g)) : null;
      about.textContent = (j.about ? j.about + " " : "") + (j.key === "admin" ? "Sees every module." :
        (d.job_menus && menu ? "Menu: " + ["Dashboard"].concat(menu.map((g) => (window.bcoModTitle ? window.bcoModTitle(g) : g))).join(", ") + "." : "Menu: every module the job's rights allow."));
      const adm = jobSel.value === "admin";
      rAll.disabled = rPrj.disabled = adm;
      if (adm) rAll.checked = true;
      pbox.hidden = rAll.checked;
      const n = boxes.filter((b) => b.querySelector("input").checked).length;
      count.textContent = "  " + n + " of " + boxes.length + " chosen";
    }
    jobSel.onchange = upd; rAll.onchange = upd; rPrj.onchange = upd;
    const f = form([{ k: "name", label: "Full name", req: true }, { k: "username", label: "Username", req: true },
      { k: "password", label: isNew ? "Password (at least 6 characters)" : "New password (leave blank to keep)", type: "password" },
      { k: "active", label: "Active", type: "check" }], p);
    const body = h("div", {}, f,
      h("label", { class: "f", style: "margin-top:10px" }, h("span", {}, "Job"), jobSel), about,
      h("div", { class: "f", style: "margin-top:10px" }, h("span", {}, "Where does this person work?")),
      h("div", { class: "acc-where" }, h("label", {}, rAll, "Head office — all projects"), h("label", {}, rPrj, "These projects")),
      pbox);
    upd();
    modal(isNew ? "New person" : "Edit person — " + p.name, body, [{ label: "Save", cls: "primary", act: async () => {
      const v = f.values();
      const ids = boxes.filter((b) => b.querySelector("input").checked).map((b) => Number(b.querySelector("input").dataset.id));
      const w = jobSel.value === "admin" ? "" : (rAll.checked ? "all" : "projects");
      if (w === "projects" && !ids.length) { toast("Tick at least one project, or choose Head office — all projects.", "err"); throw new Error("x"); }
      const row = { id: isNew ? undefined : p.id, username: v.username, name: v.name, role: jobSel.value, active: v.active,
        ws_where: w, project_ids: w === "projects" ? ids : (p.project_ids || []) };
      if (v.password) row.password = v.password;
      await run("admin.user_save", { row }, "Saved");
      try { await reloadLookups(); } catch (e) { /* ignore */ }
      if (after) after();
    } }], {});
  }

  async function peoplePage(root) {
    const d = await run("acc.people", {});
    const again = () => { if (typeof go === "function") go(); };
    const edit = can("admin", "edit");
    root.append(pageHead("Users", "Each person has a job (what they do) and where they work (head office, or chosen projects). The job decides the rights and the menu.",
      edit ? h("button", { class: "btn", onclick: () => { location.hash = "#/acc/team"; } }, "Project teams") : null,
      h("button", { class: "btn", onclick: () => { location.hash = "#/ws/roles"; } }, "Jobs & permissions"),
      edit ? h("button", { class: "btn primary", onclick: () => personWindow(d, null, again) }, "New person") : null));
    if (d.check.length) {
      root.append(h("div", { class: "panel acc-check", style: "margin-bottom:14px" }, h("h3", {}, "Check access (" + d.check.length + ")"),
        h("p", { class: "hint", style: "margin-top:0" }, "These people were set up before 2.44 or have no project. Open each one and choose their projects or Head office."),
        table([{ k: "name", label: "Name" }, { k: "job", label: "Job" }, { k: "problem", label: "What to fix" }], d.check,
          { search: false, onRow: edit ? (r) => personWindow(d, d.people.find((x) => x.id === r.id), again) : null })));
    }
    root.append(table([{ k: "name", label: "Name" }, { k: "username", label: "Username" }, { k: "job", label: "Job" },
      { label: "Where", v: whereCell }, { label: "Last sign-in", v: (r) => (r.last_login || "never").replace("T", " ").slice(0, 16) },
      { k: "active", label: "Active", fmt: "yes" }], d.people, { name: "acc_people", onRow: edit ? (r) => personWindow(d, r, again) : null }));
    root.append(h("p", { class: "hint", style: "margin-top:10px" },
      "Job menus are " + (d.job_menus ? "on" : "off") + ": " + (d.job_menus ? "each person sees their job's modules, and can press Show all my screens. " : "everyone sees every module their rights allow. "),
      edit ? h("a", { href: "#", onclick: async (e) => { e.preventDefault(); await run("acc.settings", { job_menus: d.job_menus ? 0 : 1 }, d.job_menus ? "Job menus off" : "Job menus on"); again(); } },
        d.job_menus ? "Turn job menus off" : "Turn job menus on") : null));
  }
  peoplePage._bco244 = true;

  /* ───────────────────────── project teams ───────────────────────── */
  PAGES["acc/team"] = async (root, params) => {
    const d = await run("acc.people", {});
    const pj = d.projects.filter((p) => p.status === "active");
    let pid = Number(params.p || (S.project && pj.some((p) => String(p.id) === String(S.project)) ? S.project : (pj[0] || {}).id) || 0);
    const sel = h("select", { onchange: () => { location.hash = "#/acc/team?p=" + sel.value; } },
      d.projects.map((p) => h("option", { value: p.id, selected: p.id === pid }, p.code + " — " + p.name + (p.status === "active" ? "" : " (" + p.status + ")"))));
    root.append(pageHead("Project team", "Who works on each project. Adding someone here is the same as ticking the project on their user.",
      h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:8px" }, h("span", {}, "Project"), sel)));
    if (!pid) { root.append(h("p", {}, "No project yet.")); return; }
    const t = await run("acc.team", { project_id: pid });
    const edit = can("admin", "edit");
    const again = () => go();
    const add = () => {
      const cand = d.people.filter((p) => p.active && p.role !== "admin" && p.sees !== "all" && !p.project_ids.includes(pid));
      const boxes = cand.map((p) => { const i = h("input", { type: "checkbox" }); i.dataset.id = p.id; return h("label", {}, i, p.name + " · " + p.job + (p.projects.length ? " (" + p.projects.join(", ") + ")" : "")); });
      modal("Add people to " + t.project.code, h("div", {}, cand.length ? h("div", { class: "acc-plist" }, boxes) : h("p", {}, "Everyone who works on chosen projects is already on this one. Add a new person in Users."),
        h("p", { class: "hint" }, "Head-office people already see every project and are not listed.")),
      [{ label: "Add", cls: "primary", act: async () => {
        const ids = boxes.filter((b) => b.querySelector("input").checked).map((b) => Number(b.querySelector("input").dataset.id));
        if (!ids.length) return;
        await run("acc.team_set", { project_id: pid, add: ids }, (r) => "Added " + r.added.length);
        again();
      } }], { narrow: true });
    };
    const copy = () => {
      const src = h("select", {}, d.projects.filter((p) => p.id !== pid).map((p) => h("option", { value: p.id }, p.code + " — " + p.name)));
      modal("Copy team to " + t.project.code, h("div", {}, h("label", { class: "f" }, h("span", {}, "Copy everyone placed on"), src),
        h("p", { class: "hint" }, "People are added to this project; nobody is taken off any project.")),
      [{ label: "Copy team", cls: "primary", act: async () => {
        await run("acc.team_copy", { project_id: pid, from_project: Number(src.value) }, (r) => "Added " + r.added.length + (r.added.length ? ": " + r.added.join(", ") : ""));
        again();
      } }], { narrow: true });
    };
    if (edit) root.append(h("div", { class: "bar", style: "margin-bottom:10px" }, h("div", { class: "grow" }),
      h("button", { class: "btn", onclick: copy }, "Copy team from…"), h("button", { class: "btn primary", onclick: add }, "Add person")));
    root.append(table([{ k: "name", label: "Name" }, { k: "job", label: "Job" }, { label: "Also on", v: (r) => r.also.join(", ") || "—" },
      { label: "", v: (r) => edit ? h("button", { class: "btn small", onclick: async (e) => {
        e.stopPropagation();
        if (!(await ask("Take " + r.name + " off " + t.project.code + "?", r.also.length ? "They keep their other projects." : "This is their only project; they will not be able to open any project until you add one."))) return;
        await run("acc.team_set", { project_id: pid, remove: [r.id] }, "Removed"); again();
      } }, "Remove") : "" }], t.members, { search: false, empty: "Nobody is placed on this project yet." }));
    if (t.head_office.length) root.append(h("p", { class: "hint", style: "margin-top:12px" }, "Also see this project (head office): ",
      t.head_office.map((x) => x.name + " (" + x.job + (x.why === "nothing ticked" ? ", nothing ticked" : "") + ")").join(", ") + "."));
  };

  /* ───────────────────────── jobs & permissions ───────────────────────── */
  const SEE = ["view", "export"], ENTER = ["create", "edit", "submit"], APPROVE = ["approve", "post", "delete"];
  const COLS = [["See", SEE, "view"], ["Enter", ENTER, "edit"], ["Approve", APPROVE, "approve"]];
  const MOD_LABEL = { masters: "Master data", inventory: "Store & inventory", procurement: "Procurement", accounts: "Accounts", equipment: "Equipment",
    admin: "Administration", project: "Site work & DPR", commercial: "Commercial & billing", quality: "Quality", plant: "Plant", assets: "Assets",
    control: "Cost control", dpr: "DPR reports", dpr_setup: "DPR set-up", hse_private: "Safety (private)", payreq: "Payment requests", alerts: "Financial alerts", reports: "Report builder" };

  function jobEditor(d, r) {
    const isNew = !r.key || !d.roles.some((x) => x.key === r.key);
    const groups = (typeof MENU !== "undefined" ? (window.bcoMenuGroups || MENU.map((g) => g[0])) : []).filter((g) => !(d.always || []).includes(g));
    const f = form([{ k: "name", label: "Job name", req: true },
      { k: "company", label: "May enter the Company Workspace", type: "check" },
      { k: "projects", label: "Projects (when Where is not set on the person)", type: "select", noBlank: true, options: [["assigned", "Only assigned projects"], ["all", "All projects"], ["none", "None (company only)"]] },
      { k: "active", label: "Active", type: "check" }], r);
    const perms = JSON.parse(JSON.stringify(r.perms || {}));
    const grid = h("table", { class: "acc-grid" }, h("thead", {}, h("tr", {}, h("th", {}, "Area"), COLS.map(([l]) => h("th", {}, l)))),
      h("tbody", {}, d.modules.map((m) => h("tr", {}, h("td", {}, MOD_LABEL[m] || m), COLS.map(([, verbs, base]) => {
        const has = (perms[m] || []).some((x) => verbs.includes(x));
        const i = h("input", { type: "checkbox", checked: has });
        i.dataset.m = m; i.dataset.base = base; i.dataset.verbs = verbs.join(",");
        return h("td", {}, i);
      })))));
    const menuSet = new Set(r.menu || groups);
    const mboxes = groups.map((g) => { const i = h("input", { type: "checkbox", checked: menuSet.has(g) }); i.dataset.g = g; return h("label", { class: "f check" }, i, window.bcoModTitle ? window.bcoModTitle(g) : g); });
    modal(isNew ? "New job" : "Edit job — " + r.name, h("div", {}, f,
      h("h4", { style: "margin:12px 0 6px" }, "Modules in this job's menu"),
      h("p", { class: "hint", style: "margin:0" }, "Dashboard and Tools & views always show. Hidden modules stay open to the person through Show all my screens, if the rights below allow."),
      h("div", { class: "acc-menus" }, mboxes),
      h("h4", { style: "margin:12px 0 6px" }, "What this job may do"),
      h("div", { class: "tablewrap" }, grid),
      h("p", { class: "hint" }, "See = open and export. Enter = create, edit and submit. Approve = approve and post.")),
    [{ label: "Save", cls: "primary", act: async () => {
      grid.querySelectorAll("input").forEach((i) => {
        const m = i.dataset.m, verbs = i.dataset.verbs.split(",");
        const cur = perms[m] || [];
        const has = cur.some((x) => verbs.includes(x));
        if (i.checked && !has) perms[m] = cur.concat([i.dataset.base]);
        if (!i.checked && has) perms[m] = cur.filter((x) => !verbs.includes(x));
      });
      const menu = mboxes.filter((b) => b.querySelector("input").checked).map((b) => b.querySelector("input").dataset.g);
      await run("ws.role_save", { row: Object.assign(f.values(), { key: r.key, perms, menu: menu.length === groups.length ? [] : menu }) }, "Saved");
      go();
    } }], {});
  }

  const jobsPage = async (root) => {
    const d = await run("ws.roles", {});
    const edit = can("admin", "edit");
    root.append(pageHead("Jobs & permissions", "A job decides what a person may do and which modules their menu shows. People are set up in Administration › Users.",
      h("button", { class: "btn", onclick: () => { location.hash = "#/admin/users"; } }, "Users"),
      edit ? h("button", { class: "btn primary", onclick: () => {
        const name = prompt("Name of the new job:");
        if (name) jobEditor(d, { key: name.toLowerCase().replace(/\W+/g, "_"), name, perms: {}, projects: "assigned", active: 1, company: 0, menu: null });
      } }, "New job") : null));
    const title = (g) => (window.bcoModTitle ? window.bcoModTitle(g) : g);
    root.append(table([{ k: "name", label: "Job" }, { k: "about", label: "For" },
      { label: "Menu", v: (r) => r.key === "admin" || !r.menu || !d.job_menus ? "All modules" : r.menu.map(title).join(", ") },
      { label: "Usually", v: (r) => r.company ? "Head office" : "Projects" }, { k: "users", label: "People", fmt: "num" }, { k: "active", label: "Active", fmt: "yes" }],
      d.roles, { name: "acc_jobs", search: false, onRow: edit ? (r) => { if (r.key === "admin") { toast("The administrator job cannot be changed.", "err"); return; } jobEditor(d, r); } : null }));
  };

  /* app.js loads after the page scripts: put the screens and the menu entry in place at boot, first of all
     the boot hooks, so the workspace and focus menus copy the menu with Project teams in it */
  (window.bcoBootHooks = window.bcoBootHooks || []).unshift(() => {
    PAGES["admin/users"] = peoplePage;
    PAGES["ws/roles"] = jobsPage;
    teamButton();
    try {
      if (typeof MENU !== "undefined") {
        const g = MENU.find((x) => x[0] === "Administration");
        if (g && !g[2].some((it) => it[0] === "acc/team")) {
          const i = g[2].findIndex((it) => it[0] === "admin/users");
          g[2].splice(i >= 0 ? i + 1 : g[2].length, 0, ["acc/team", "Project teams"]);
        }
        if (!window.bcoMenuGroups) window.bcoMenuGroups = MENU.map((x) => x[0]);
      }
    } catch (e) { /* ignore */ }
  });

  /* a Team button on the project register */
  function teamButton() {
  const mp = PAGES["m/projects"];
  if (mp && !mp._bco244) {
    const w = async (root, params) => {
      await mp(root, params);
      if (!can("admin", "view")) return;
      const bar = root.querySelector(".bar");
      if (bar) bar.append(h("a", { class: "btn", href: "#/acc/team" }, "Project teams"));
    };
    w._bco244 = true;
    PAGES["m/projects"] = w;
  }
  }

  /* what's new */
  function whatsNew() {
    if (LSg("bco_seen_" + VER, "")) return;
    if (!S.user || S.user.role !== "admin") return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_" + VER, "1");
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:560px" },
      h("p", {}, "Setting people up is now one screen."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "Administration › Users."), " Each person has a job and where they work: Head office (all projects) or chosen projects, with a search box."),
        h("li", {}, h("b", {}, "Job menus."), " A storekeeper sees the store, an accountant sees accounts. Same module names and order; Show all my screens brings back the rest."),
        h("li", {}, h("b", {}, "Project teams."), " Add people from the project side, or copy a team from another project."),
        h("li", {}, h("b", {}, "Check access."), " Lists people who still see every project only because nothing was ticked.")),
      h("p", { class: "hint" }, "Nobody's rights, projects or data changed with this update.")),
    [{ label: "Open Users", cls: "primary", act: () => { location.hash = "#/admin/users"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user) { clearInterval(seen); setTimeout(whatsNew, 2500); } }, 1000);
})();
