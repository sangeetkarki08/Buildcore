/* BuildCore - Job and Where.
 *
 *   Administration › Users ................ one screen: name, username, password, Job, Where, Active; Check access
 *   Administration › Users & roles ........ Edit jobs: See / Enter / Approve per area, and the menu groups a job shows
 *   Master data › Projects ................ tab "Team": who works on a project; add, remove, copy from another project
 *   menu .................................. only the job's groups (same names and order); "Show all my screens"
 *
 * The engine decides what a person may open, exactly as before; the menu only hides groups.
 */
(function () {
  "use strict";
  const SHOW_ALL = "bco_show_all_screens";
  const LSg = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const LSs = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  const panel = (...k) => h("div", { class: "panel" }, ...k);
  const hint = (t) => h("p", { class: "hint" }, t);
  const AREA = (m) => m.charAt(0).toUpperCase() + m.slice(1);
  const workProjects = () => (S.L.projects || []).filter((p) => !["trading", "general"].includes(p.kind || ""));

  /* ── the menu: the job's groups only, unless "Show all my screens" ── */
  window.bcoJobMenu = function (groups) {
    const ws = S.user && S.user.workspace;
    const keep = ws && ws.menus;
    if (!keep || LSg(SHOW_ALL) === "1") return groups;
    return groups.filter((g) => g[0] === "Overview" || keep.includes(g[0]));
  };
  function showAllLink() {
    const nav = document.querySelector("nav.nav");
    const ws = S.user && S.user.workspace;
    if (!nav || !ws || !ws.menus || nav.querySelector(".nav-showall")) return;
    const all = LSg(SHOW_ALL) === "1";
    nav.append(h("a", { href: "#", class: "nav-showall", style: "display:block;margin:10px 12px;font-size:12px;opacity:.8",
      onclick: (e) => { e.preventDefault(); LSs(SHOW_ALL, all ? null : "1"); location.reload(); } },
      all ? "Show only my job's screens" : "Show all my screens"));
  }
  new MutationObserver(showAllLink).observe(document.documentElement, { childList: true, subtree: true });

  /* ── plain words for a job ── */
  function jobText(job, groups) {
    if (!job) return "";
    const areas = Object.entries(job.perms || {}).filter(([, a]) => a && a.length).map(([m, a]) => {
      const w = [a.includes("view") && "see", (a.includes("edit") || a.includes("create") || a.includes("submit")) && "enter",
        (a.includes("approve") || a.includes("post")) && "approve"].filter(Boolean);
      return AREA(m) + " (" + w.join(", ") + ")";
    });
    return [
      job.description || null,
      "Works in: " + (job.company ? "the Company Workspace and projects" : "projects only") + ".",
      "Menu: " + (job.menus && job.menus.length ? ["Overview"].concat(job.menus.filter((g) => g !== "Overview")).join(", ") : "all " + (groups || []).length + " groups") + ".",
      "May: " + (areas.length ? areas.join("; ") : "nothing yet") + ".",
    ].filter(Boolean).join(" ");
  }

  function whereLabel(r) {
    if (r.where === "all") return "Head office (all projects)";
    if (r.where === "unset") return h("span", { class: "red" }, "All projects (nothing ticked)");
    const ids = String(r.project_ids || "").split(",").filter(Boolean);
    return ids.map((i) => nm.pcode(i)).join(", ");
  }

  /* ── one person: name, username, password, Job, Where, Active ── */
  function personEditor(u0, rd, done) {
    const isNew = !u0;
    const u = u0 || { active: 1, role: "storekeeper", project_ids: "" };
    const jobs = rd.roles.filter((r) => r.active || r.key === u.role);
    const job = () => jobs.find((r) => r.key === sel.value);
    const name = h("input", { value: u.name || "" }), user = h("input", { value: u.username || "", autocomplete: "off" });
    const pw = h("input", { type: "password", autocomplete: "new-password", placeholder: isNew ? "6 or more characters" : "leave blank to keep" });
    const active = h("input", { type: "checkbox", checked: !!u.active });
    const sel = h("select", {}, jobs.map((r) => h("option", { value: r.key, selected: r.key === u.role }, r.name)));
    const about = h("div", { class: "hint", style: "background:var(--panel2, rgba(128,128,128,.12));padding:8px 10px;border-radius:6px" });
    const showAbout = () => { about.textContent = jobText(job(), rd.groups); };
    sel.addEventListener("change", () => { showAbout(); if (isNew) setWhere((job() || {}).where_usual || "projects"); });
    const picked = new Set(String(u.project_ids || "").split(",").filter(Boolean));
    const search = h("input", { placeholder: "Search projects", style: "max-width:260px" });
    const count = h("span", { class: "hint" });
    const list = h("div", { style: "max-height:220px;overflow:auto;border:1px solid var(--line, #ccc);border-radius:6px;padding:6px" });
    const drawList = () => {
      const t = search.value.trim().toLowerCase();
      list.innerHTML = "";
      workProjects().filter((p) => !t || (p.code + " " + p.name).toLowerCase().includes(t)).forEach((p) => {
        const i = h("input", { type: "checkbox", checked: picked.has(String(p.id)), onchange: () => { if (i.checked) picked.add(String(p.id)); else picked.delete(String(p.id)); count.textContent = picked.size + " ticked"; } });
        list.append(h("label", { class: "f check", style: "display:block" }, i, " " + p.code + " — " + p.name));
      });
      count.textContent = picked.size + " ticked";
    };
    search.addEventListener("input", drawList);
    const rOffice = h("input", { type: "radio", name: "where" }), rProj = h("input", { type: "radio", name: "where" });
    const rAsBefore = u.where === "unset" ? h("input", { type: "radio", name: "where" }) : null;
    const projBox = h("div", { style: "margin:6px 0 0 22px" }, h("div", { class: "bar", style: "gap:8px" }, search, count), list);
    const setWhere = (w) => { rOffice.checked = w === "all"; rProj.checked = w === "projects"; if (rAsBefore) rAsBefore.checked = w === "unset"; projBox.hidden = w !== "projects"; };
    [rOffice, rProj, rAsBefore].filter(Boolean).forEach((r) => r.addEventListener("change", () => setWhere(r === rOffice ? "all" : r === rProj ? "projects" : "unset")));
    setWhere(isNew ? (job() || {}).where_usual || "projects" : (u.where || "projects"));
    drawList();
    showAbout();
    const lab = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
    modal(isNew ? "New person" : "Edit " + u.name, h("div", {},
      h("div", { class: "grid" }, lab("Full name", name), lab("Username (they sign in with this)", user), lab(isNew ? "Password" : "New password", pw)),
      lab("Job", sel), about,
      h("h4", { style: "margin:12px 0 6px" }, "Where do they work?"),
      h("label", { class: "f check" }, rOffice, " Head office — all projects"),
      h("label", { class: "f check" }, rProj, " These projects"), projBox,
      rAsBefore ? h("label", { class: "f check" }, rAsBefore, " As before: all projects, because nothing is ticked (fix this: choose one of the two above)") : null,
      h("label", { class: "f check", style: "margin-top:10px" }, active, " Active (may sign in)")),
    [{ label: "Save", cls: "primary", act: async () => {
      const where = rOffice.checked ? "all" : rProj.checked ? "projects" : null;
      if (!name.value.trim() || !user.value.trim()) { toast("Fill in the name and the username.", "err"); throw new Error("x"); }
      if (isNew && pw.value.length < 6) { toast("The password needs at least 6 characters.", "err"); throw new Error("x"); }
      if (where === "projects" && !picked.size) { toast("Tick at least one project, or choose Head office.", "err"); throw new Error("x"); }
      const row = { id: u.id, username: user.value.trim(), name: name.value.trim(), role: sel.value, active: active.checked ? 1 : 0,
        location: u.location, phone: u.phone, email: u.email };
      if (pw.value) row.password = pw.value;
      if (where) { row.access = where; row.project_ids = where === "projects" ? [...picked] : []; }
      try { await api("admin.user_save", { row }); } catch (e) { toast(e.message, "err"); throw e; }
      toast("Saved");
      try { await reloadLookups(); } catch (e) { /* fine */ }
      done && done();
    } }], {});
  }

  /* ── Administration › Users ── */
  async function usersPage(root) {
    const [users, rd] = await Promise.all([run("admin.users", {}), api("ws.roles", {})]);
    let chk = [];
    try { chk = await api("ws.access_check", {}); } catch (e) { /* fine */ }
    const edit = can("admin", "edit");
    root.append(pageHead("Users", "Each person has a Job (what they do) and a Where (head office, or the projects they work on). The job decides the menu and the rights; you edit jobs in Users & roles.",
      edit ? h("button", { class: "btn primary", onclick: () => personEditor(null, rd, go) }, "New person") : null));
    if (chk.length) {
      root.append(panel(h("h3", {}, "Check access (" + chk.length + ")"),
        hint("These people were set up before Job and Where. They see every project only because no project is ticked. Open each one and choose Head office or their projects."),
        table([{ k: "name", label: "Name" }, { k: "username", label: "Username" }, { k: "job", label: "Job" }, { k: "why", label: "Why" }],
          chk, { name: "access_check", search: false, onRow: edit ? (r) => personEditor(users.find((x) => x.id === r.id), rd, go) : null })));
    }
    root.append(table([{ k: "name", label: "Name" }, { k: "username", label: "Username" }, { k: "job", label: "Job" },
      { label: "Where", v: whereLabel }, { k: "active", label: "Active", fmt: "yes" }],
      users, { name: "users_jobs", onRow: edit ? (r) => personEditor(r, rd, go) : null }));
  }

  /* ── Administration › Users & roles: Edit jobs ── */
  async function jobsPage(root) {
    const d = await run("ws.roles", {});
    const edit = can("admin", "edit");
    const editJob = (r) => {
      const isNew = !r.id;
      const name = h("input", { value: r.name || "" }), desc = h("input", { value: r.description || "", placeholder: "One line: what this job does" });
      const comp = h("input", { type: "checkbox", checked: !!r.company });
      const usual = h("select", {}, h("option", { value: "all", selected: r.projects === "all" }, "Head office (all projects)"),
        h("option", { value: "assigned", selected: r.projects !== "all" }, "Chosen projects"));
      const COLS = [["view", "See"], ["edit", "Enter"], ["approve", "Approve"]];
      const has = (m, a) => { const x = (r.perms || {})[m] || []; return a === "edit" ? x.some((y) => ["edit", "create", "submit"].includes(y)) : a === "approve" ? x.some((y) => ["approve", "post", "delete"].includes(y)) : x.includes(a); };
      const grid = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Area"), COLS.map(([, l]) => h("th", {}, l)))),
        h("tbody", {}, d.modules.map((m) => h("tr", {}, h("td", {}, AREA(m)), COLS.map(([a]) => {
          const i = h("input", { type: "checkbox", checked: has(m, a) }); i.dataset.m = m; i.dataset.a = a; return h("td", {}, i);
        })))));
      const menus = new Set(r.menus && r.menus.length ? r.menus : d.groups);
      const mbox = h("div", { class: "grid" }, d.groups.map((g) => h("label", { class: "f check" },
        h("input", { type: "checkbox", checked: g === "Overview" || menus.has(g), disabled: g === "Overview", onchange: (e) => { if (e.target.checked) menus.add(g); else menus.delete(g); } }), " " + g)));
      const lab = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
      modal(isNew ? "New job" : "Edit job: " + r.name, h("div", {},
        h("div", { class: "grid" }, lab("Job name", name), lab("Usual place of work", usual)), lab("Description", desc),
        h("label", { class: "f check" }, comp, " May enter the Company Workspace (only for people at Head office)"),
        h("h4", { style: "margin:12px 0 6px" }, "What this job may do"),
        hint("See = open and read. Enter = create, change and submit. Approve = approve and post. The engine checks exactly these three."),
        h("div", { class: "tablewrap" }, grid),
        h("h4", { style: "margin:12px 0 6px" }, "Menu groups this job shows"),
        hint("Group names and order stay as they are. People can still open any screen their rights allow with Show all my screens."), mbox),
      [{ label: "Save", cls: "primary", act: async () => {
        if (!name.value.trim()) { toast("Give the job a name.", "err"); throw new Error("x"); }
        const perms = {};
        grid.querySelectorAll("input:checked").forEach((i) => {
          const p = (perms[i.dataset.m] = perms[i.dataset.m] || []);
          p.push(i.dataset.a);
          if (i.dataset.a !== "view" && !p.includes("view")) p.push("view");
        });
        const key = r.key || name.value.trim().toLowerCase().replace(/\W+/g, "_");
        try {
          await api("ws.role_save", { row: { key, name: name.value.trim(), description: desc.value, company: comp.checked ? 1 : 0,
            projects: usual.value, perms, menus: [...menus], active: r.active == null ? 1 : r.active } });
        } catch (e) { toast(e.message, "err"); throw e; }
        toast("Saved");
        go();
      } }], {});
    };
    root.append(pageHead("Edit jobs", "A job is what a person does. It decides their rights and the menu groups they see. Where they work is set per person in Administration › Users.",
      edit ? h("button", { class: "btn primary", onclick: () => editJob({ perms: {}, projects: "assigned", company: 0, active: 1 }) }, "New job") : null,
      h("a", { class: "btn", href: "#/admin/users" }, "People")));
    root.append(table([{ k: "name", label: "Job" },
      { label: "Usual place", v: (r) => r.projects === "all" ? "Head office" : "Chosen projects" },
      { label: "Company Workspace", v: (r) => r.company ? "yes (at head office)" : "no" },
      { label: "Menu groups", v: (r) => r.menus && r.menus.length ? ["Overview"].concat(r.menus.filter((g) => g !== "Overview")).join(", ") : "All" },
      { k: "users", label: "People", fmt: "num" }, { k: "active", label: "Active", fmt: "yes" }],
      d.roles, { name: "ws_jobs", search: false, onRow: edit ? (r) => { if (r.key === "admin") return toast("The Administrator job cannot be changed.", "err"); editJob(r); } : null }));
  }

  /* ── Master data › Projects › Team ── */
  async function teamTab() {
    const projs = workProjects();
    if (!projs.length) return hint("No projects yet.");
    let pid = String((projs.find((p) => String(p.id) === String(S.project)) || projs[0]).id);
    const box = h("div");
    const sel = h("select", { onchange: () => { pid = sel.value; load(); } }, projs.map((p) => h("option", { value: p.id, selected: String(p.id) === pid }, p.code + " — " + p.name)));
    const out = h("div");
    const edit = can("admin", "edit");
    const load = async () => {
      let d;
      try { d = await api("ws.team", { project_id: pid }); } catch (e) { out.innerHTML = ""; out.append(hint(e.message)); return; }
      out.innerHTML = "";
      out.append(panel(h("h3", {}, "Team (" + d.members.length + ")"),
        table([{ k: "name", label: "Name" }, { k: "username", label: "Username" }, { k: "job", label: "Job" },
          edit ? { label: "", v: (r) => h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); try { await api("ws.team_remove", { project_id: pid, user_id: r.id }); toast("Removed"); load(); } catch (x) { toast(x.message, "err"); } } }, "Remove") } : null].filter(Boolean),
        d.members, { name: "team_members", search: false, empty: "Nobody is assigned to this project yet." })));
      if (edit) {
        const add = h("select", {}, h("option", { value: "" }, "Choose a person…"), d.others.map((r) => h("option", { value: r.id }, r.name + " — " + r.job + (r.unset ? " (now sees all projects)" : ""))));
        const from = h("select", {}, h("option", { value: "" }, "Copy team from…"), projs.filter((p) => String(p.id) !== pid).map((p) => h("option", { value: p.id }, p.code + " — " + p.name)));
        out.append(panel(h("h3", {}, "Add people"),
          h("div", { class: "bar", style: "gap:8px;flex-wrap:wrap" }, add, h("button", { class: "btn primary", onclick: async () => {
            if (!add.value) return;
            const r = d.others.find((x) => String(x.id) === add.value);
            if (r && r.unset && !(await ask("Limit " + r.name + " to projects", r.name + " now sees every project because nothing is ticked. Adding them here limits them to the projects they are on.", { ok: "Add and limit" }))) return;
            try { await api("ws.team_add", { project_id: pid, user_ids: [add.value] }); toast("Added"); load(); } catch (x) { toast(x.message, "err"); }
          } }, "Add"), from, h("button", { class: "btn", onclick: async () => {
            if (!from.value) return;
            try { const r = await api("ws.team_copy", { project_id: pid, from_project: from.value }); toast(r.added + " added"); load(); } catch (x) { toast(x.message, "err"); }
          } }, "Copy team")),
          hint("Adding someone gives them this project as well as their others. New people are made in Administration › Users.")));
      }
      out.append(panel(h("h3", {}, "Head office (" + d.head_office.length + ")"), hint("They see every project, so they are not listed in the team."),
        table([{ k: "name", label: "Name" }, { k: "job", label: "Job" }], d.head_office, { name: "team_office", search: false })));
    };
    box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Project"), sel)), out);
    await load();
    return box;
  }

  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    if (PAGES["admin/users"]) PAGES["admin/users"] = usersPage;           // the sign-in status panel is added after this
    if (PAGES["ws/roles"]) PAGES["ws/roles"] = jobsPage;
    if (PAGES["m/projects"] && typeof window.bcoTabbed === "function" && can("admin", "view"))
      window.bcoTabbed("m/projects", "Projects", "", { firstLabel: "Projects", tabs: [["Team", teamTab]] });
  });
})();
