/* BuildCore 2.8 — company and year, sign-in, store by kind, KPIs, contracts, machine history, DPR view and print,
   BOQ by location. Everything sits inside the existing menu groups. */
(function () {
  "use strict";
  const LS = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSset = (k, v) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private window */ } };
  const esc = (s) => String(s == null ? "" : s);
  const money = (v) => (v == null || v === "" ? "—" : fmtMoney(v));
  const qty = (v) => (v == null || v === "" ? "—" : fmtQty(v));

  /* ───────────────────────── company: every request names its company ───────────────────────── */
  let CO = LS("bco_company", "");
  const setCookie = (code) => { try { document.cookie = "bco_co=" + (code || "") + "; path=/; max-age=31536000; SameSite=Lax"; } catch (e) { /* ignore */ } };
  if (CO) setCookie(CO);
  const _fetch = window.fetch.bind(window);
  let lastProblem = "";
  window.fetch = function (url, opts) {
    if (typeof url === "string" && url.indexOf("/api") === 0) {
      opts = Object.assign({}, opts || {});
      if (CO) opts.headers = Object.assign({}, opts.headers || {}, { "X-Company": CO });
      /* a request never waits forever: after 60 s it fails with a clear message instead of a blank screen */
      const long = /\/api\/(upload|restore|backup)/.test(url);
      if (!opts.signal && typeof AbortController !== "undefined") {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), long ? 600000 : 60000);
        opts.signal = ctl.signal;
        return _fetch(url, opts).then((r) => { clearTimeout(t); return r; }, (e) => { clearTimeout(t); lastProblem = e && e.name === "AbortError" ? "The engine did not answer within 60 seconds." : String(e); throw e; });
      }
    }
    return _fetch(url, opts);
  };
  window.addEventListener("error", (e) => { lastProblem = (e && e.message) || lastProblem; });
  window.addEventListener("unhandledrejection", (e) => { lastProblem = (e && e.reason && (e.reason.message || String(e.reason))) || lastProblem; });

  /* never a blank window: if the first screen has not appeared, say why and offer a way out */
  function recovery(reason) {
    const app = $("#app");
    if (!app) return;
    let engine = "checking…";
    const eng = h("span", {}, engine);
    _fetch("/api/ping", { cache: "no-store" }).then((r) => { eng.textContent = r.ok ? "running" : "not answering (HTTP " + r.status + ")"; }, () => { eng.textContent = "not reachable"; });
    const clearCo = () => { try { localStorage.removeItem("bco_company"); localStorage.removeItem("bco_token"); } catch (e) { /* ignore */ } setCookie(""); location.hash = ""; location.reload(); };
    app.innerHTML = "";
    app.append(h("div", { style: "max-width:620px;margin:60px auto;background:#fff;border:1px solid #dbe2e8;border-radius:14px;padding:26px 28px;font:14px/1.55 'Segoe UI',Arial,sans-serif;color:#16212b;box-shadow:0 18px 50px rgba(16,42,60,.10)" },
      h("h2", { style: "margin:0 0 6px" }, "BuildCore could not open the screen"),
      h("p", { style: "color:#5d6b75;margin:0 0 14px" }, reason || "The first screen did not appear."),
      h("p", { style: "margin:0 0 4px" }, h("b", {}, "Engine: "), eng),
      h("p", { style: "margin:0 0 4px" }, h("b", {}, "Company being opened: "), CO || "main company"),
      lastProblem ? h("p", { style: "margin:0 0 14px;color:#b3392c" }, h("b", {}, "Details: "), lastProblem) : null,
      /locked|busy/i.test(lastProblem) ? h("p", { style: "margin:0 0 14px" }, "The data file is being held by another BuildCore that is still running (often a BuildCore that did not close properly). Close every BuildCore window; if that does not help, restart the computer.") : null,
      h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;margin-top:14px" },
        h("button", { class: "btn primary", onclick: () => location.reload() }, "Try again"),
        h("button", { class: "btn", onclick: clearCo }, "Open the main company"),
        h("button", { class: "btn", onclick: () => { try { localStorage.removeItem("bco_token"); } catch (e) { /* ignore */ } location.hash = ""; location.reload(); } }, "Sign in again")),
      h("p", { style: "color:#5d6b75;font-size:12.5px;margin:16px 0 0" }, "If this keeps happening, close BuildCore and open it again. The engine writes what it was doing to error.log (Help › Open error log) — send that file to support.")));
  }
  window.bcoRecovery = recovery;
  if (typeof api === "function") {
    const _api = api;
    const api2 = async function (fn, args) {
      try { return await _api(fn, args); } catch (e) { lastProblem = fn + ": " + (e && e.message); throw e; }
    };
    try { api = api2; } catch (e) { window.api = api2; }
  }
  function setCompany(code) { CO = code || ""; LSset("bco_company", CO || null); setCookie(CO); }
  window.bcoCompany = () => CO;

  const css = document.createElement("style");
  css.textContent = [
    ".auth{min-height:100vh;display:grid;grid-template-columns:minmax(280px,42%) 1fr;background:var(--paper)}",
    ".auth .brandside{background:linear-gradient(155deg,#0d2f45 0%,#16557a 60%,#1d6f8f 100%);color:#e6f0f6;padding:48px 44px;display:flex;flex-direction:column;justify-content:space-between}",
    ".auth .brandside h1{font-size:30px;margin:0 0 8px;color:#fff;letter-spacing:.3px}.auth .brandside p{margin:0;color:#b9d2e1;max-width:36ch;line-height:1.55}",
    ".auth .brandside ul{list-style:none;padding:0;margin:28px 0 0;display:grid;gap:10px}.auth .brandside li{display:flex;gap:10px;align-items:center;color:#d4e5ef}",
    ".auth .brandside li:before{content:'';width:8px;height:8px;border-radius:50%;background:#f0b43c;flex:none}",
    ".auth .card{align-self:center;justify-self:center;width:min(420px,92vw);background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:30px 30px 24px;box-shadow:0 18px 50px rgba(16,42,60,.10)}",
    ".auth .card h2{margin:0 0 4px;font-size:22px}.auth .card .muted{margin:0 0 18px}",
    ".auth label.f{margin-bottom:12px}.auth .pw{position:relative}.auth .pw button{position:absolute;right:6px;top:50%;transform:translateY(-50%);border:0;background:none;cursor:pointer;color:var(--muted);font-size:12px;padding:4px 6px}",
    ".auth .err{background:var(--red-wash);color:var(--red);border:1px solid #efc4bd;border-radius:8px;padding:9px 12px;margin:4px 0 12px;font-size:13px}",
    ".auth .warnline{color:#8a5a00;font-size:12px;margin-top:4px}",
    ".auth .btn.primary{width:100%;padding:10px 12px;font-size:15px;border-radius:8px}",
    ".auth .foot{margin-top:16px;font-size:12px;color:var(--muted);line-height:1.5}",
    "@media (max-width:820px){.auth{grid-template-columns:1fr}.auth .brandside{padding:26px 24px}.auth .brandside ul{display:none}}",
    ".cochip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:3px 10px 3px 8px;background:var(--panel);cursor:pointer;font-size:13px;white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis}",
    ".cochip:hover{border-color:#9fb0b8}.cochip i{font-style:normal;background:var(--blue);color:#fff;border-radius:5px;padding:0 5px;font-size:11px;font-weight:700}",
    ".fysel{width:auto!important;min-width:0!important;padding:4px 6px!important}",
    ".fybadge{background:#fff4cc;border:1px solid #ecd58a;color:#6b4e00;border-radius:999px;padding:2px 10px;font-size:12px;white-space:nowrap}",
    ".kpigrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:8px 0 18px}",
    ".kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer;position:relative;border-left:5px solid #b9c4c9}",
    ".kpi:hover{box-shadow:0 6px 18px rgba(16,42,60,.08)}.kpi b{display:block;font-size:22px;line-height:1.2}.kpi span{display:block;font-weight:600;margin-top:2px}",
    ".kpi small{display:block;color:var(--muted);margin-top:4px;font-size:12px;line-height:1.35}.kpi em{position:absolute;right:10px;top:10px;font-style:normal;font-size:11px;color:var(--muted)}",
    ".kpi.good{border-left-color:var(--green)}.kpi.warn{border-left-color:var(--amber)}.kpi.bad{border-left-color:var(--red)}",
    ".kpi.good b{color:var(--green)}.kpi.bad b{color:var(--red)}.kpi.warn b{color:#9a6a00}",
    ".kindtiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin:10px 0 16px}",
    ".kindtile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer}.kindtile.on{border-color:var(--blue);box-shadow:inset 0 0 0 1px var(--blue)}",
    ".kindtile b{display:block;font-size:15px}.kindtile span{display:block;font-size:20px;font-weight:700;margin:4px 0}.kindtile small{color:var(--muted)}",
    ".entrybar{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 4px}.entrybar .btn{border-radius:999px}",
    ".dprdoc{background:#fff;color:#111;font-size:13px}.dprdoc h2{font-size:18px;margin:0 0 6px}.dprdoc h3{font-size:14px;margin:16px 0 6px;border-bottom:2px solid #1b5e86;padding-bottom:3px}",
    ".dprdoc table{width:100%;border-collapse:collapse;margin-bottom:6px}.dprdoc th,.dprdoc td{border:1px solid #c9d2d6;padding:4px 6px;text-align:left;vertical-align:top}.dprdoc th{background:#eef3f6}",
    ".dprdoc td.n,.dprdoc th.n{text-align:right}.dprdoc .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 16px;margin:6px 0 4px}",
    ".dprdoc .sign{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-top:40px}.dprdoc .sign div{border-top:1px solid #333;padding-top:4px;text-align:center}",
    ".locgroup td{background:#eef3f6!important;font-weight:700}.locsub td{background:#f7f9fa!important;font-weight:600}",
    ".hist-ev td:first-child{white-space:nowrap}",
    ".usermenu{position:relative}.usermenu .avatar{width:34px;height:34px;border-radius:50%;border:0;background:var(--blue);color:#fff;font-weight:700;cursor:pointer;font-size:13px}",
    ".usermenu-list{position:absolute;right:0;top:40px;background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 14px 40px rgba(16,42,60,.18);min-width:230px;padding:6px;z-index:60}",
    ".usermenu-list .um-head{padding:8px 10px 10px;border-bottom:1px solid var(--line);margin-bottom:4px}.usermenu-list .um-head b{display:block}.usermenu-list .um-head span{font-size:12px;color:var(--muted);text-transform:capitalize}",
    ".usermenu-list button{display:block;width:100%;text-align:left;border:0;background:none;padding:8px 10px;border-radius:8px;cursor:pointer}.usermenu-list button:hover{background:var(--blue-wash)}.usermenu-list button.danger{color:var(--red)}",
  ].join("");
  document.head.append(css);

  /* ───────────────────────── sign-in ───────────────────────── */
  const pwBox = (name, placeholder) => {
    const i = h("input", { name, type: "password", autocomplete: name === "p" ? "current-password" : "new-password", placeholder: placeholder || "" });
    const b = h("button", { type: "button", tabindex: "-1", onclick: () => { i.type = i.type === "password" ? "text" : "password"; b.textContent = i.type === "password" ? "Show" : "Hide"; } }, "Show");
    const caps = h("div", { class: "warnline", hidden: true }, "Caps Lock is on.");
    i.addEventListener("keyup", (e) => { try { caps.hidden = !e.getModifierState("CapsLock"); } catch (x) { /* old browser */ } });
    return { input: i, el: h("div", {}, h("div", { class: "pw" }, i, b), caps) };
  };
  const brandSide = (company) => h("div", { class: "brandside" },
    h("div", {}, h("h1", {}, "BuildCore"), h("p", {}, company || "Construction project control, stores, equipment and accounts — one place, offline or across your offices.")),
    h("ul", {}, ["Daily progress, BOQ and billing", "Store, procurement and machines", "Accounts by fiscal year, like Tally", "Several companies, one login screen"].map((t) => h("li", {}, t))),
    h("small", { style: "color:#9fc0d4" }, "Your data stays in your own Supabase database."));

  async function loginScreen2(message) {
    const app = $("#app");
    let cos = { companies: [], current: "main" };
    try { cos = await api("co.list"); } catch (e) { /* old engine */ }
    const list = cos.companies || [];
    if (CO && !list.find((x) => x.code === CO && !x.broken)) setCompany("");
    if (!CO && list.length > 1) { const d = list.find((x) => x.default) || list[0]; setCompany(d.code); }
    let st = {};
    try { st = await api("auth.status"); } catch (e) { st = { needs_setup: false }; }
    app.innerHTML = "";
    const err = h("div", { class: "err", hidden: !message }, message || "");
    const showErr = (m) => { err.textContent = m; err.hidden = !m; };
    const coSel = list.length > 1 ? h("select", { name: "company", onchange: () => { setCompany(coSel.value); loginScreen2(); } },
      list.map((x) => h("option", { value: x.code, selected: x.code === (CO || cos.current), disabled: !!x.broken }, x.name + (x.broken ? " (cannot be opened — see Administration › Companies)" : "")))) : null;
    const coField = coSel ? h("label", { class: "f" }, h("span", {}, "Company"), coSel) : null;
    if (st.needs_setup) {
      const name = h("input", { name: "name" }), co = h("input", { name: "company_name", value: st.company || "" }), user = h("input", { name: "username", value: "admin", autocomplete: "username" });
      const p1 = pwBox("password", "6 or more characters"), p2 = pwBox("password2", "type it again");
      const go2 = async () => {
        showErr("");
        if (!user.value.trim()) return showErr("Choose a username.");
        if (p1.input.value.length < 6) return showErr("The password needs at least 6 characters.");
        if (p1.input.value !== p2.input.value) return showErr("The two passwords are not the same.");
        try {
          const r = await api("auth.setup", { company_name: co.value, name: name.value || user.value, username: user.value, password: p1.input.value });
          S.token = r.token; LSset("bco_token", r.token); start2();
        } catch (e) { showErr(e.message); }
      };
      app.append(h("div", { class: "auth" }, brandSide(st.company),
        h("form", { class: "card", onsubmit: (e) => { e.preventDefault(); go2(); } }, h("h2", {}, "Set up BuildCore"),
          h("p", { class: "muted" }, "Create the first administrator for " + (list.length > 1 ? "this company" : "your company") + "."), coField, err,
          h("label", { class: "f" }, h("span", {}, "Company name"), co), h("label", { class: "f" }, h("span", {}, "Your full name"), name),
          h("label", { class: "f" }, h("span", {}, "Username (you sign in with this)"), user),
          h("label", { class: "f" }, h("span", {}, "Password"), p1.el), h("label", { class: "f" }, h("span", {}, "Password again"), p2.el),
          h("button", { class: "btn primary", type: "submit" }, "Create administrator"),
          h("div", { class: "foot" }, "Write down the username and password. Usernames are not case-sensitive; passwords are."))));
      name.focus();
      return;
    }
    const u = h("input", { name: "u", autocomplete: "username", value: LS("bco_last_user", "") });
    const p = pwBox("p");
    const submit = async () => {
      showErr("");
      if (!u.value.trim()) { showErr("Type your username."); u.focus(); return; }
      if (!p.input.value) { showErr("Type your password."); p.input.focus(); return; }
      btn.disabled = true; btn.textContent = "Signing in…";
      try {
        const r = await api("auth.login", { username: u.value.trim(), password: p.input.value });
        S.token = r.token; LSset("bco_token", r.token); LSset("bco_last_user", u.value.trim());
        await start2();
      } catch (e) {
        showErr(e.message); p.input.select(); btn.disabled = false; btn.textContent = "Sign in";
      }
    };
    const btn = h("button", { class: "btn primary", type: "submit" }, "Sign in");
    app.append(h("div", { class: "auth" }, brandSide(st.company),
      h("form", { class: "card", onsubmit: (e) => { e.preventDefault(); submit(); } }, h("h2", {}, "Sign in"),
        h("p", { class: "muted" }, st.company || ""), err, coField || h("p", { class: "hint", style: "margin:0 0 12px" },
          "One company so far. To keep another company's books, an administrator adds it in Administration › Companies; then you choose the company here."),
        h("label", { class: "f" }, h("span", {}, "Username (or your full name)"), u), h("label", { class: "f" }, h("span", {}, "Password"), p.el), btn,
        h("div", { class: "foot" }, "Forgot the password? An administrator sets a new one in Administration › Users (and can unlock you after 5 wrong tries)."))));
    (u.value ? p.input : u).focus();
  }

  async function start2() {
    if (!S.token) return loginScreen2();
    try {
      S.user = await api("auth.me");
    } catch (e) {
      LSset("bco_token", null); S.token = null;
      return loginScreen2(e.message === "SESSION_EXPIRED" ? "" : "Signed in, but BuildCore could not open your account: " + e.message);
    }
    let problem = null;
    try { await reloadLookups(); } catch (e) {
      problem = e.message;
      S.L = { projects: [], stores: [], materials: [], parties: [], accounts: [], groups: [], equipment: [], checklists: [], boq: [], staff: [], tds: [], users: [], settings: {} };
    }
    if (S.project && !byId(S.L.projects, S.project)) { S.project = ""; LSset("bco_project", null); }
    try { approvalsCount = (await api("dash.approvals")).filter((x) => x.can_approve).length; } catch (e) { try { approvalsCount = 0; } catch (x) { /* ignore */ } }
    try { shell(); } catch (e) { lastProblem = e.message; return recovery("The main screen could not be drawn."); }
    if (problem) toast("Some lists could not load: " + problem + " — see Help › Open error log.", "err");
  }

  /* ───────────────────────── fiscal year chosen at the top ───────────────────────── */
  const FYKEY = () => "bco_fy_" + (CO || "main");
  let FY = null;            // {fy, start_date, end_date, current}
  let YEARS = [];
  async function loadYears() {
    if (!can("accounts", "view")) { YEARS = []; return; }
    try { const r = await api("fy.list", {}); YEARS = r.years || []; } catch (e) { YEARS = []; }
    const want = LS(FYKEY(), "");
    FY = YEARS.find((y) => y.fy === want) || YEARS.find((y) => y.current) || null;
  }
  window.bcoFY = () => FY;
  const applied = new WeakSet();
  function applyFy() {
    if (!FY || FY.current) return;
    const page = $("#page");
    if (!page) return;
    const bars = [...page.querySelectorAll(".bar")].filter((b) => b.querySelector("input[name=from], input[name=to], input[name=as_of]"));
    bars.forEach((bar) => {
      if (applied.has(bar)) return;
      applied.add(bar);
      const set = (n, v) => { const i = bar.querySelector("input[name=" + n + "]"); if (i && v) { i.value = v; i.dispatchEvent(new Event("input", { bubbles: true })); i.dispatchEvent(new Event("change", { bubbles: true })); } };
      set("from", FY.start_date); set("to", FY.end_date); set("as_of", FY.end_date);
      const show = [...bar.querySelectorAll("button")].find((b) => /^Show$/.test(b.textContent.trim()));
      if (show) show.click();
    });
  }
  let fyTimer = null;
  const fyObserver = new MutationObserver(() => { clearTimeout(fyTimer); fyTimer = setTimeout(applyFy, 250); });

  function switchCompanyDialog() {
    api("co.list").then((r) => {
      const list = r.companies || [];
      const box = h("div", { class: "kvlist" });
      list.forEach((x, i) => box.append(h("a", { class: x.code === (CO || r.current) ? "on" : "", onclick: async () => {
        if (x.code === (CO || r.current)) { m.close(); return; }
        try { await api("auth.logout"); } catch (e) { /* ignore */ }
        LSset("bco_token", null); setCompany(x.code); location.hash = ""; location.reload();
      } }, h("i", {}, String(i + 1)), h("span", {}, x.name + (x.default ? "  (first at sign-in)" : "")))));
      const m = modal("Select company (Alt+F3)", h("div", {}, h("p", { class: "hint" }, "Each company has its own data, users and fiscal years. You sign in again in the company you choose."), box,
        can("admin", "edit") ? h("p", {}, h("a", { href: "#/admin/companies", onclick: () => m.close() }, "Create or rename companies…")) : null), [], { narrow: true });
    });
  }
  window.bcoSwitchCompany = switchCompanyDialog;
  document.addEventListener("keydown", (e) => {
    if (e.altKey && !e.ctrlKey && e.key === "F3" && S.user) { e.preventDefault(); e.stopPropagation(); switchCompanyDialog(); }
  }, true);

  function shellExtras() {
    const top = $(".top");
    if (!top || top.querySelector(".cochip")) return;
    const name = (S.L.settings && S.L.settings.company_name) || "Company";
    const chip = h("span", { class: "cochip", title: "Company — click or Alt+F3 to switch", onclick: switchCompanyDialog }, h("i", {}, "CO"), name);
    const anchor = top.querySelector("label.f") || top.firstChild;
    top.insertBefore(chip, anchor);
    if (YEARS.length) {
      const sel = h("select", { class: "fysel", title: "Fiscal year — reports and lists open on this year", onchange: () => {
        FY = YEARS.find((y) => y.fy === sel.value) || null; LSset(FYKEY(), FY ? FY.fy : null); paintBadge(); if (typeof go === "function") go();
      } }, YEARS.map((y) => h("option", { value: y.fy, selected: FY && y.fy === FY.fy }, "FY " + y.fy + (y.current ? " (current)" : y.closed ? " (closed)" : ""))));
      const badge = h("span", { class: "fybadge", hidden: true });
      const paintBadge = () => { badge.hidden = !FY || FY.current; badge.textContent = FY ? "Showing FY " + FY.fy + " (" + FY.start_date + " to " + FY.end_date + ")" : ""; };
      paintBadge();
      top.insertBefore(h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:6px" }, sel), anchor.nextSibling);
      top.insertBefore(badge, sel.parentNode.nextSibling);
    }
    /* name, password and sign-out in one small menu so the top bar stays on one line */
    const who = top.querySelector(".who");
    const pwBtn = [...top.querySelectorAll("button")].find((b) => b.textContent.trim() === "Password");
    const outBtn = [...top.querySelectorAll("button")].find((b) => b.textContent.trim() === "Sign out");
    if (who && pwBtn && outBtn && !top.querySelector(".usermenu")) {
      const initials = (S.user.name || S.user.username || "?").replace(/\(.*?\)/g, "").trim().split(/\s+/).map((x) => x[0]).slice(0, 2).join("").toUpperCase();
      const menu = h("div", { class: "usermenu-list", hidden: true },
        h("div", { class: "um-head" }, h("b", {}, S.user.name), h("span", {}, S.user.role.replace(/_/g, " ") + (S.user.location ? " · " + S.user.location : ""))),
        h("button", { onclick: () => { menu.hidden = true; switchCompanyDialog(); } }, "Switch company  (Alt+F3)"),
        h("button", { onclick: () => { menu.hidden = true; pwBtn.click(); } }, "Change password"),
        h("button", { onclick: () => { menu.hidden = true; if (typeof shortcutHelp === "function") shortcutHelp(); } }, "Keyboard keys  (F1)"),
        h("button", { class: "danger", onclick: () => outBtn.click() }, "Sign out"));
      const um = h("div", { class: "usermenu" }, h("button", { class: "avatar", title: S.user.name + " — " + S.user.role, onclick: (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; } }, initials), menu);
      document.addEventListener("click", (e) => { if (!um.contains(e.target)) menu.hidden = true; });
      who.style.display = "none"; pwBtn.style.display = "none"; outBtn.style.display = "none";
      top.append(um);
    }
    const ref = [...top.querySelectorAll("button")].find((b) => b.textContent.trim() === "Refresh");
    if (ref) { ref.textContent = "⟳"; ref.title = "Refresh lists"; }
    const page = $("#page");
    if (page) fyObserver.observe(page, { childList: true, subtree: true });
  }

  /* ───────────────────────── Administration › Users: unlock and last sign-in ───────────────────────── */
  function hookUsers() {
  const _users = PAGES["admin/users"];
  if (!_users || _users._bco28) return;
  PAGES["admin/users"] = async (root, params) => {
    await _users(root, params);
    let rows = [];
    try { rows = await api("adm.users2", {}); } catch (e) { return; }
    const locked = rows.filter((r) => r.locked || r.failed);
    const box = h("div", { class: "panel", style: "margin-top:14px" }, h("h3", {}, "Sign-in status"),
      table([{ k: "username", label: "Username" }, { k: "name", label: "Name" }, { k: "role", label: "Role" }, { k: "active", label: "Active", fmt: "yes" },
        { label: "Last sign-in", v: (r) => (r.last_login || "never").replace("T", " ").slice(0, 16) },
        { label: "Wrong tries", v: (r) => r.failed || "" }, { label: "", v: (r) => r.locked || r.failed ? h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); await run("adm.unlock", { id: r.id }, "Unlocked " + r.username); go(); } }, r.locked ? "Unlock" : "Clear tries") : "" }],
      rows, { name: "users_signin", search: false, empty: "No users." }),
      h("p", { class: "hint" }, locked.length ? locked.length + " user(s) have wrong tries. After 5 wrong passwords a user is locked for the time set in Settings; Unlock clears it." :
        "Users sign in with their username or full name. If someone cannot sign in, check the company, that the user is Active, and set a new password here."));
    root.append(box);
  };
  PAGES["admin/users"]._bco28 = true;
  }

  window.bcoBoot = function () {
    (window.bcoBootHooks || []).forEach((f) => { try { f(); } catch (e) { /* a hook must never stop sign-in */ } });
    hookUsers();
    window.loginScreen = loginScreen2;
    try { loginScreen = loginScreen2; } catch (e) { /* ignore */ }
    window.start = start2;
    try { start = start2; } catch (e) { /* ignore */ }
    const _shell = window.shell;
    const shell2 = function () { _shell(); loadYears().then(() => { shellExtras(); applyFy(); }).catch(() => shellExtras()); };
    window.shell = shell2;
    try { shell = shell2; } catch (e) { /* ignore */ }
    const watch = setTimeout(() => { const app = $("#app"); if (app && !app.children.length) recovery("The first screen did not appear within 20 seconds."); }, 20000);
    Promise.resolve().then(() => start2()).then(() => clearTimeout(watch), (e) => { clearTimeout(watch); lastProblem = (e && e.message) || String(e); recovery("Opening BuildCore stopped with an error."); });
  };

  /* ───────────────────────── Administration › Companies ───────────────────────── */
  PAGES["admin/companies"] = async (root) => {
    const r = await run("co.list", {});
    const info = await api("co.info", {});
    const newCo = () => {
      const f = form([{ k: "name", label: "Company name", req: true, wide: true }, { k: "pan", label: "PAN" }, { k: "address", label: "Address" },
        { k: "fy", label: "First fiscal year (e.g. 2083-84)", ph: "2083-84" }, { k: "fy_start", label: "It starts on (AD, Shrawan 1)", type: "date" }]);
      const cb = (k, label, on) => { const i = h("input", { type: "checkbox", checked: !!on }); i.dataset.k = k; return h("label", { class: "f check" }, i, label); };
      const copies = h("div", { class: "grid" }, cb("accounts", "Chart of accounts and TDS rates", 1), cb("materials", "Materials", 1), cb("parties", "Vendors, subcontractors and clients", 1),
        cb("equipment", "Machines and their outputs", 0), cb("staff", "Staff and labour trades", 0), cb("users", "All users (else only you, as administrator)", 0));
      modal("New company", h("div", {}, f, h("h4", { style: "margin:14px 0 6px" }, "Copy from " + (info.name || "this company")), copies,
        h("p", { class: "hint" }, "The new company gets its own data file, backups, users and fiscal years. Nothing is shared afterwards. Opening balances start at zero.")),
      [{ label: "Create company", cls: "primary", act: async () => {
        const v = f.values();
        const copy = {}; copies.querySelectorAll("input[type=checkbox]").forEach((i) => { copy[i.dataset.k] = i.checked ? 1 : 0; });
        const res = await run("co.create", Object.assign(v, { copy }), (x) => "Created " + x.name);
        go();
        if (await ask("Open " + res.name + "?", "Sign in to the new company now? You can come back with Alt+F3.", { ok: "Open it" })) {
          try { await api("auth.logout"); } catch (e) { /* ignore */ }
          LSset("bco_token", null); setCompany(res.code); location.hash = ""; location.reload();
        }
      } }], {});
    };
    root.append(pageHead("Companies", "Like Tally: each company keeps its own books, stores, projects, users and fiscal years in its own data file. Choose the company at sign-in or press Alt+F3.",
      can("admin", "edit") ? h("button", { class: "btn primary", onclick: newCo }, "New company") : null),
      table([{ k: "name", label: "Company" }, { k: "code", label: "Code" }, { label: "Opens first", v: (x) => x.default ? "Yes" : "" }, { label: "You are in", v: (x) => x.current ? "●" : "" },
        { label: "Created", v: (x) => (x.created || "").slice(0, 10) }, { label: "State", v: (x) => x.broken ? h("span", {}, h("span", { class: "red", title: x.broken }, "cannot be opened "), can("admin", "edit") ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("co.update", { code: x.code, retry: 1 }, "Will try to open it again"); go(); } }, "Try again") : null) : "ok" },
        { label: "", v: (x) => can("admin", "edit") ? h("span", {}, h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); const n = await ask("Rename company", "New name for " + x.name, { input: x.name, ok: "Rename" }); if (n && n.trim()) { await run("co.update", { code: x.code, name: n.trim() }, "Renamed"); go(); } } }, "Rename"),
          x.default ? null : h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("co.update", { code: x.code, default: 1 }, "Opens first at sign-in"); go(); } }, "Open first")) : "" }],
      r.companies, { name: "companies", search: false, onRow: (x) => { if (!x.current) switchCompanyDialog(); } }),
      h("p", { class: "hint" }, "Data folders: the first company uses the usual data folder; others are in …\\BuildCore\\companies\\<code>\\. Back up each company from Administration › Backup & restore while you are in it; extra companies are also copied every day automatically."));
  };

  /* ───────────────────────── Accounts › Fiscal years ───────────────────────── */
  async function yearsTab() {
    const r = await run("fy.list", {});
    const box = h("div");
    const close = async (y) => {
      const ok = await ask("Close fiscal year " + y.fy, "Year-end close freezes every account's balance and the stock at " + y.end_date + ", locks the year's 12 periods (no entry can be dated in it) and makes sure the next year exists. The next year opens with these closing balances: asset, liability and equity accounts carry forward; income and expense start at zero and the profit is brought forward. An administrator can reopen the year.", { ok: "Close the year" });
      if (!ok) return;
      let res = await run("fy.close", { fy: y.fy });
      if (res.needs_confirm) {
        const again = await ask("Not everything is finished in " + y.fy, "Found: " + res.warnings.join("; ") + ". Close anyway? Unfinished drafts stay as drafts and can no longer be posted in this year.", { ok: "Close anyway", danger: true });
        if (!again) return;
        res = await run("fy.close", { fy: y.fy, force: 1 });
      }
      toast("Closed " + res.fy + ": profit " + fmtMoney(res.profit) + ", " + res.accounts + " accounts and " + res.stock_items + " stock lines frozen" + (res.next ? "; " + res.next + " is open" : ""), "ok");
      go();
    };
    box.append(table([{ k: "fy", label: "Fiscal year" }, { k: "start_date", label: "From" }, { k: "end_date", label: "To" }, { k: "state", label: "State", fmt: "status" },
      { k: "vouchers", label: "Vouchers", fmt: "num" }, { k: "drafts", label: "Drafts", fmt: "num" }, { k: "profit", label: "Profit / (loss)", fmt: "money" },
      { label: "Closed", v: (y) => (y.closed_at || "").slice(0, 10) },
      { label: "", v: (y) => h("span", { style: "display:flex;gap:6px" },
        h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); location.hash = "#/acc/fy?tab=1&fy=" + encodeURIComponent(y.fy); } }, "Opening"),
        h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); location.hash = "#/acc/fy?tab=2&fy=" + encodeURIComponent(y.fy); } }, "Tax"),
        !y.closed && can("accounts", "approve") && y.start_date <= today() ? h("button", { class: "btn small primary", onclick: (e) => { e.stopPropagation(); close(y); } }, "Close year") : null,
        y.closed && can("admin", "edit") ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); const why = await ask("Reopen " + y.fy, "Reopen this closed year? Its periods become open again.", { input: "Reason", required: true, danger: true }); if (why === null) return; await run("fy.reopen", { fy: y.fy, reason: why }, "Reopened"); go(); } }, "Reopen") : null) }],
    r.years, { name: "fiscal_years", search: false, empty: "No fiscal year yet. Create one in Accounts › Periods (Create fiscal year).", rowClass: (y) => y.current ? "flag" : "" }));
    box.append(h("p", { class: "hint" }, "Choose the year at the top of the screen (Year) to open every report and list on that year — like changing the period in Tally. Closing a year is optional but stops back-dated changes; numbering of vouchers and documents already restarts each year."));
    return box;
  }
  async function openingTab(params) {
    const r0 = await run("fy.list", {});
    const box = h("div");
    const pick = params.fy || (FY && FY.fy) || ((r0.years.find((y) => y.current) || r0.years[r0.years.length - 1] || {}).fy);
    const sel = h("select", { style: "width:auto" }, r0.years.map((y) => h("option", { value: y.fy, selected: y.fy === pick }, y.fy)));
    const holder = h("div");
    const load = async () => {
      holder.innerHTML = "";
      if (!sel.value) return;
      const r = await run("fy.opening", { fy: sel.value });
      holder.append(h("p", { class: "hint" }, "Opening balances on " + r.start + " = closing balances of " + (r.previous || "the earlier entries") + (r.previous_closed ? " (that year is closed; its frozen closing is shown beside the live figure — they must agree)" : "") + "."),
        table([{ k: "code", label: "Code" }, { k: "name", label: "Account" }, { k: "type", label: "Type" }, { k: "debit", label: "Debit", fmt: "money" }, { k: "credit", label: "Credit", fmt: "money" },
          r.previous_closed ? { label: "Frozen at close", v: (x) => x.frozen == null ? "" : fmtMoney(Math.abs(x.frozen)) + (x.frozen < 0 ? " Cr" : " Dr") } : null,
          r.previous_closed ? { label: "Check", v: (x) => x.differs ? h("b", { class: "red" }, "differs") : "✓" } : null].filter(Boolean),
        r.rows, { name: "opening_" + r.fy, totals: ["debit", "credit"], title: "Opening balances " + r.fy }),
        h("p", { class: Math.abs(r.difference) > 0.01 ? "red" : "hint" }, "Total debit " + fmtMoney(r.total_debit) + " · credit " + fmtMoney(r.total_credit) + (Math.abs(r.difference) > 0.01 ? " · difference " + fmtMoney(r.difference) : " · balanced")),
        r.stock.length ? h("h3", { style: "margin-top:16px" }, "Stock carried forward (frozen at the close of " + r.previous + ") — " + fmtMoney(r.stock_value)) : null,
        r.stock.length ? table([{ k: "code", label: "Item" }, { k: "name", label: "Name" }, { label: "Store", v: (x) => nm.store(x.store_id) }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "value", label: "Value", fmt: "money" }],
          r.stock, { name: "opening_stock_" + r.fy, totals: ["value"] }) : null);
    };
    sel.onchange = load;
    box.append(h("div", { class: "bar" }, h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:6px" }, h("span", {}, "Fiscal year"), sel)), holder);
    await load();
    return box;
  }
  async function taxTab(params) {
    const r0 = await run("fy.list", {});
    const pick = params.fy || (FY && FY.fy) || ((r0.years.find((y) => y.current) || {}).fy);
    const sel = h("select", { style: "width:auto" }, r0.years.map((y) => h("option", { value: y.fy, selected: y.fy === pick }, y.fy)));
    const holder = h("div");
    const load = async () => {
      holder.innerHTML = "";
      if (!sel.value) return;
      const r = await run("fy.tax", { fy: sel.value });
      holder.append(summaryStrip([["Sales / income", fmtMoney(r.totals.sales)], ["Output VAT", fmtMoney(r.totals.output_vat)], ["Input VAT", fmtMoney(r.totals.input_vat)],
        ["Net VAT", fmtMoney(r.totals.net_vat)], ["TDS deducted (to deposit)", fmtMoney(r.totals.tds_deducted)], ["TDS deducted from us", fmtMoney(r.totals.tds_suffered)],
        ["Book profit", fmtMoney(r.profit)], ["VAT balance at year end", fmtMoney(r.vat_balance_end)]]),
      table([{ k: "period", label: "Month" }, { k: "from", label: "From" }, { k: "to", label: "To" }, { k: "sales", label: "Sales", fmt: "money" }, { k: "output_vat", label: "Output VAT", fmt: "money" },
        { k: "input_vat", label: "Input VAT", fmt: "money" }, { k: "net_vat", label: "Net VAT", fmt: "money" }, { k: "tds_deducted", label: "TDS deducted", fmt: "money" },
        { k: "tds_suffered", label: "TDS suffered", fmt: "money" }, { k: "status", label: "Period", fmt: "status" }],
      r.months, { name: "tax_" + r.fy, totals: ["sales", "output_vat", "input_vat", "net_vat", "tds_deducted", "tds_suffered"], title: "Tax summary FY " + r.fy }),
      h("p", { class: "hint" }, r.note + " Monthly VAT and TDS books: Accounts › VAT books / TDS register (choose this year at the top)."));
    };
    sel.onchange = load;
    holder.append();
    const box = h("div", {}, h("div", { class: "bar" }, h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:6px" }, h("span", {}, "Fiscal year"), sel)), holder);
    await load();
    return box;
  }
  PAGES["acc/fy"] = async (root, params) => {
    root.append(pageHead("Fiscal years", "Books kept year by year like Tally: choose the year at the top, close a finished year, see the opening balances it carries into the next year and the year's tax summary."));
    root.append(tabs([["Years", () => yearsTab(params)], ["Opening balances", () => openingTab(params)], ["Tax summary by year", () => taxTab(params)]], params.tab ? Number(params.tab) : 0));
  };

  /* ───────────────────────── Store by kind (one page) ───────────────────────── */
  const KIND_OPTS = [["consumable", "Regular consumable"], ["tool", "Tool"], ["spare", "Spare part"], ["other", "Other"]];
  if (typeof MASTERS_UI !== "undefined" && MASTERS_UI.materials && !MASTERS_UI.materials._kind) {
    const o = MASTERS_UI.materials;
    o._kind = true;
    const fld = { k: "kind", label: "Kind of item", type: "select", noBlank: true, options: KIND_OPTS };
    if (typeof o.fields === "function") { const f0 = o.fields; o.fields = (r) => f0(r).concat([fld]); } else if (Array.isArray(o.fields)) o.fields.splice(4, 0, fld);
    const d0 = o.defaults;
    o.defaults = () => Object.assign({ kind: "consumable" }, d0 ? d0() : {});
    if (Array.isArray(o.cols)) o.cols.splice(3, 0, { label: "Kind", v: (r) => ({ consumable: "Consumable", tool: "Tool", spare: "Spare", other: "Other" })[r.kind] || "" });
  }
  PAGES["inv/store"] = async (root, params) => {
    const proj = S.project || null;
    root.append(pageHead("Store", (proj ? nm.project(proj) + " — " : "All projects — ") + "every item in one place, kept separately as regular consumables, tools, spare parts and other items."));
    const entry = (label, key) => h("button", { class: "btn", onclick: () => { location.hash = "#/" + key[0] + "?knew=" + key[1]; } }, label);
    root.append(h("div", { class: "entrybar" },
      can("inventory", "edit") ? [entry("+ Receive (GRN)  Alt+F9", ["inv/grn", "grn"]), entry("+ Issue  Alt+F8", ["inv/issue", "issue"]), entry("+ Return", ["inv/return", "ret"]),
        entry("+ Transfer  Alt+F7", ["inv/transfer", "transfer"]), entry("+ Requisition  Alt+F5", ["inv/mrq", "mrq"]), entry("+ Stock count  Ctrl+F7", ["inv/count", "count"])] : null,
      can("masters", "edit") ? h("button", { class: "btn", onclick: () => masterDialog("materials", { kind: cur === "all" ? "consumable" : cur }).then((x) => { if (x) go(); }) }, "+ New item") : null,
      h("button", { class: "btn", onclick: () => { location.hash = "#/inv/card"; } }, "Stock card"), h("button", { class: "btn", onclick: () => { location.hash = "#/p/kpi"; } }, "Store KPIs")));
    const d = await run("store.view", { project_id: proj });
    let cur = params.kind || LS("bco_store_kind", "consumable");
    const tiles = h("div", { class: "kindtiles" });
    const holder = h("div");
    const paintTiles = () => {
      tiles.innerHTML = "";
      d.summary.concat([{ kind: "all", label: "All items", items: d.summary.reduce((a, x) => a + x.items, 0), value: d.summary.reduce((a, x) => a + x.value, 0), below: d.summary.reduce((a, x) => a + x.below, 0) }])
        .forEach((s) => tiles.append(h("div", { class: "kindtile" + (s.kind === cur ? " on" : ""), onclick: () => { cur = s.kind; LSset("bco_store_kind", cur); paintTiles(); paint(); } },
          h("b", {}, s.label), h("span", {}, fmtMoney(s.value)), h("small", {}, s.items + " items" + (s.below ? " · " + s.below + " to reorder" : "") + (s.out_with_people ? " · " + fmtQty(s.out_with_people) + " with people" : "") + (s.idle_value ? " · idle " + fmtMoney(s.idle_value) : "")))));
    };
    const base = [{ k: "code", label: "Code" }, { k: "name", label: "Item" }, { k: "category", label: "Category" }, { k: "unit", label: "Unit" }, { k: "qty", label: "In store", fmt: "qty" }, { k: "value", label: "Value", fmt: "money" }];
    const COLS = {
      consumable: base.concat([{ k: "reorder_level", label: "Reorder at", fmt: "qty" }, { k: "used_30", label: "Used 30 days", fmt: "qty" }, { label: "Days of cover", v: (r) => r.cover_days == null ? "" : fmtN(r.cover_days, 0) }, { k: "last_in", label: "Last receipt" }, { k: "last_out", label: "Last issue" }]),
      tool: base.concat([{ k: "out_with_people", label: "With people", fmt: "qty" }, { k: "total_owned", label: "Total owned", fmt: "qty" }, { k: "holders", label: "Held by" }, { k: "last_out", label: "Last issued" }]),
      spare: base.concat([{ k: "fits", label: "Fits / used on" }, { k: "min_level", label: "Minimum", fmt: "qty" }, { k: "reorder_level", label: "Reorder at", fmt: "qty" }, { k: "last_in", label: "Last receipt" }, { k: "last_out", label: "Last issue" }]),
      other: base.concat([{ k: "last_in", label: "Last receipt" }, { k: "last_out", label: "Last issue" }]),
      all: base.concat([{ label: "Kind", v: (r) => ({ consumable: "Consumable", tool: "Tool", spare: "Spare", other: "Other" })[r.kind] }, { k: "last_out", label: "Last issue" }]),
    };
    const paint = async () => {
      holder.innerHTML = "";
      const rows = cur === "all" ? [].concat(...Object.values(d.groups)) : d.groups[cur] || [];
      holder.append(table(COLS[cur], rows, { name: "store_" + cur, totals: ["value"], onRow: (r) => { location.hash = "#/inv/card?material=" + r.id; },
        rowClass: (r) => r.below ? "bad" : r.idle ? "flag" : "", empty: cur === "tool" || cur === "spare" ? "No item is marked as " + (cur === "tool" ? "a tool" : "a spare part") + " yet. Use “Move items to this kind” below, or set Kind of item on the material." : "Nothing here." }));
      holder.append(h("p", { class: "hint" }, "Red: at or below the reorder level. Amber: in stock but not issued for 90 days. Click a row for its stock card." + (cur === "tool" ? " Tools are issued to a person (Issued to) and come back on a Return (Returned by) — the same name keeps the custody right." : "")));
      if (can("masters", "edit") && cur !== "all") holder.append(h("button", { class: "btn small", onclick: () => moveKind(cur) }, "Move items to this kind…"));
      if (cur === "tool") {
        const c = await api("store.custody", { project_id: proj });
        holder.append(h("h3", { style: "margin-top:18px" }, "Tools with people (" + c.length + ")"),
          table([{ k: "who", label: "Person / crew" }, { k: "code", label: "Tool" }, { k: "name", label: "Name" }, { k: "issued", label: "Issued", fmt: "qty" }, { k: "returned", label: "Returned", fmt: "qty" },
            { k: "holding", label: "Holding now", fmt: "qty" }, { k: "damaged", label: "Came back damaged", fmt: "qty" }, { k: "last_issue", label: "Last issued" }, { k: "days_out", label: "Days", fmt: "num" }],
          c, { name: "tool_custody", rowClass: (r) => (r.days_out || 0) > 30 ? "flag" : "", empty: "No tool is out with anyone." }));
      }
    };
    const moveKind = (target) => {
      const all = [].concat(...Object.values(d.groups)).filter((r) => r.kind !== target);
      const find = h("input", { type: "search", placeholder: "Find items" });
      const list = h("div", { class: "kvals" });
      const pickd = new Set();
      const draw = () => {
        list.innerHTML = "";
        const t = find.value.toLowerCase();
        all.filter((r) => !t || (r.code + " " + r.name + " " + (r.category || "")).toLowerCase().includes(t)).slice(0, 400).forEach((r) => {
          const cb = h("input", { type: "checkbox", checked: pickd.has(r.id), onchange: () => { if (cb.checked) pickd.add(r.id); else pickd.delete(r.id); } });
          list.append(h("label", {}, cb, h("span", {}, r.code + " " + r.name), h("span", { class: "kcount" }, (r.category || "") + " · now " + r.kind)));
        });
      };
      find.oninput = draw; draw();
      modal("Move items to: " + (KIND_OPTS.find((k) => k[0] === target) || [0, target])[1], h("div", {}, find, list), [{ label: "Move ticked items", cls: "primary", act: async () => {
        if (!pickd.size) { toast("Tick the items first.", "err"); return false; }
        await run("store.set_kind", { kind: target, ids: [...pickd] }, (x) => x.updated + " items moved");
        await reloadLookups(); go();
      } }], { narrow: true });
    };
    root.append(tiles, holder);
    paintTiles(); await paint();
  };

  /* ───────────────────────── KPI dashboard ───────────────────────── */
  const kpiCard = (k, open) => {
    const shown = k.value == null ? "—" : k.fmt === "money" || k.unit === "NPR" ? fmtMoney(k.value) : fmtN(k.value, 1) + (k.unit === "%" ? "%" : "");
    const unit = k.value == null || k.unit === "NPR" || k.unit === "%" ? "" : " " + k.unit;
    return h("div", { class: "kpi " + (k.status || "info"), onclick: open, title: "Click for the detail" },
      k.target != null ? h("em", {}, "target " + (k.higher_better === false ? "≤ " : "≥ ") + fmtN(k.target) + (k.unit === "%" ? "%" : "")) : null,
      h("b", {}, shown + unit), h("span", {}, k.label), h("small", {}, k.note || ""));
  };
  const kpiDetail = (k) => {
    const rows = k.detail || [];
    const cols = rows.length ? Object.keys(rows[0]).map((c) => ({ k: c, label: c, fmt: typeof rows[0][c] === "number" ? (/value|cost|amount/i.test(c) ? "money" : "qty") : undefined })) : [];
    modal(k.label, h("div", {}, h("p", {}, k.note || ""), rows.length ? table(cols, rows, { name: "kpi_" + (k.key || "detail"), title: k.label }) : h("p", { class: "hint" }, "No detail rows.")), [], {});
  };
  async function storeKpiTab(v) {
    const r = await run("kpi.store", v);
    const box = h("div");
    box.append(summaryStrip([["Period", r.from + " to " + r.to], ["Stock value now", fmtMoney(r.stock_value)], ["Items at or below reorder", r.below_reorder]]));
    const groups = [...new Set(r.kpis.map((k) => k.group))];
    groups.forEach((g) => {
      box.append(h("h3", { style: "margin:14px 0 2px" }, g));
      box.append(h("div", { class: "kpigrid" }, r.kpis.filter((k) => k.group === g).map((k) => kpiCard(k, () => kpiDetail(k)))));
    });
    box.append(h("p", { class: "hint" }, "Green meets the target, amber is close, red needs action. Times come from when documents were saved and posted, so post GRNs and issues the day they happen. Wastage needs material norms on BOQ items and approved DPR quantities."));
    return box;
  }
  async function financeKpiTab() {
    const r = await run("kpi.finance", {});
    const box = h("div", {}, h("p", { class: "hint" }, "As of " + r.as_of + (r.fy ? " · fiscal year " + r.fy + " from " + r.from : "") + "."));
    [...new Set(r.kpis.map((k) => k.group))].forEach((g) => {
      box.append(h("h3", { style: "margin:14px 0 2px" }, g), h("div", { class: "kpigrid" }, r.kpis.filter((k) => k.group === g).map((k) => kpiCard(k, () => {
        const go2 = { "Receivable from clients": "acc/ageing", "Overdue receivables": "acc/ageing", "Payable to suppliers": "acc/ageing", "Overdue payables": "acc/ageing", "VAT payable (output less input)": "acc/vat", "TDS to deposit": "acc/tds", "Profit": "acc/pl", "Income": "acc/pl", "Cash and bank": "acc/cash" }[k.label];
        if (go2) location.hash = "#/" + go2;
      }))));
    });
    return box;
  }
  async function contractsDueTab(v) {
    const r = await run("con.schedule", { project_id: v.project_id, days: 30 });
    const od = r.items.filter((x) => x.state === "overdue").length;
    return h("div", {}, h("div", { class: "kpigrid" },
      kpiCard({ label: "Letters / reports / deliveries overdue", value: od, unit: "items", status: od ? "bad" : "good", note: "Click to open the contract register." }, () => { location.hash = "#/c/contracts"; }),
      kpiCard({ label: "Due in the next 30 days", value: r.items.length - od, unit: "items", status: "info", note: "" }, () => { location.hash = "#/c/contracts"; }),
      kpiCard({ label: "Bonds / insurance / contracts expiring", value: r.expiring.length, unit: "", status: r.expiring.some((x) => x.state === "expired") ? "bad" : r.expiring.length ? "warn" : "good", note: r.expiring.slice(0, 3).map((x) => x.what + " " + x.date).join("; ") }, () => { location.hash = "#/c/contracts"; }),
      kpiCard({ label: "Deliveries late or due", value: r.deliveries.length, unit: "PO lines", status: r.deliveries.some((x) => x.state === "late") ? "bad" : "good", note: "" }, () => { location.hash = "#/proc/pending"; })));
  }
  async function fleetKpiTab(v) {
    const r = await run("eq.history", { from: v.from, to: v.to });
    const s = r.summary.filter((x) => x.worked || x.breakdowns);
    const sum = (k) => s.reduce((a, x) => a + (x[k] || 0), 0);
    const worked = sum("worked"), bd = sum("breakdowns"), down = sum("downtime");
    return h("div", {}, h("div", { class: "kpigrid" },
      kpiCard({ label: "Machine hours worked", value: worked, unit: "h", status: "info" }, () => { location.hash = "#/eq/history"; }),
      kpiCard({ label: "Breakdowns", value: bd, unit: "", status: bd ? "warn" : "good", note: "Downtime " + fmtN(down, 1) + " h" }, () => { location.hash = "#/eq/history"; }),
      kpiCard({ label: "MTBF (hours between breakdowns)", value: bd ? worked / bd : null, unit: "h", status: "info" }, () => { location.hash = "#/eq/history"; }),
      kpiCard({ label: "Repair cost", value: sum("repair_cost"), unit: "NPR", fmt: "money", status: "info" }, () => { location.hash = "#/eq/history"; })));
  }
  PAGES["p/kpi"] = async (root, params) => {
    const fy = FY && !FY.current ? FY : null;
    let v = { from: params.from || (fy ? fy.start_date : new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10)), to: params.to || (fy ? fy.end_date : today()), project_id: S.project || null };
    root.append(pageHead("KPI dashboard", "Store, procurement, wastage, money and contracts at a glance" + (S.project ? " — " + nm.project(S.project) : " — all projects") + ". Click a card for the detail."));
    const holder = h("div");
    const draw = () => {
      holder.innerHTML = "";
      const defs = [];
      if (can("inventory", "view")) defs.push(["Store & procurement", () => storeKpiTab(v)]);
      if (can("accounts", "view")) defs.push(["Finance & accounts", () => financeKpiTab(v)]);
      if (can("commercial", "view")) defs.push(["Contracts & deliveries", () => contractsDueTab(v)]);
      if (can("equipment", "view")) defs.push(["Machines", () => fleetKpiTab(v)]);
      holder.append(tabs(defs, Number(params.tab || 0)));
    };
    root.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], v, (x) => { v = Object.assign({}, v, x); draw(); }), holder);
    draw();
  };

  /* ───────────────────────── Contracts, letters, reports, deliveries ───────────────────────── */
  const CON_KINDS = [["subcontract", "Subcontract"], ["supply", "Supply"], ["hire", "Equipment hire"], ["client", "Main contract (client)"], ["consultant", "Consultant"], ["other", "Other"]];
  const ITEM_KINDS = [["letter", "Letter"], ["report", "Report"], ["delivery", "Delivery"], ["milestone", "Milestone"], ["payment", "Bill / payment"], ["notice", "Notice"], ["other", "Other"]];
  const REPEATS = [["none", "Once"], ["weekly", "Every week"], ["fortnightly", "Every 2 weeks"], ["monthly", "Every month"], ["quarterly", "Every 3 months"], ["yearly", "Every year"]];
  const DIRS = [["we_send", "We send"], ["they_send", "They send"], ["both", "Both / meeting"]];
  const lbl = (opts, v) => (opts.find((o) => o[0] === v) || [0, v || ""])[1];
  function itemDialog(it, contractId, done) {
    const f = form([{ k: "kind", label: "Type", type: "select", noBlank: true, options: ITEM_KINDS }, { k: "title", label: "What", req: true, wide: true }, { k: "due_date", label: "Due", type: "date" },
      { k: "repeat", label: "Repeats", type: "select", noBlank: true, options: REPEATS }, { k: "direction", label: "Who", type: "select", noBlank: true, options: DIRS }, { k: "responsible", label: "Responsible person" },
      { k: "qty", label: "Quantity (deliveries)", type: "number" }, { k: "unit", label: "Unit" }, { k: "ref_no", label: "Letter / reference no." }, { k: "remarks", label: "Remarks", type: "textarea", wide: true }],
    it || { kind: "report", repeat: "monthly", direction: "we_send", due_date: today() });
    const b = [{ label: "Save", cls: "primary", act: async () => { await run("citem.save", { row: Object.assign(f.values(), { id: it && it.id, contract_id: contractId }) }, "Saved"); done(); } }];
    if (it && it.status === "pending") b.push({ label: "Mark done", act: async () => { const ref = await ask("Done", "Reference / letter no. (optional)", { input: "e.g. HN/2083/045" }); if (ref === null) return false; const r = await run("citem.done", { id: it.id, ref_no: ref }, "Done"); if (r.next_id) toast("Next one is scheduled", "ok"); done(); } });
    if (it) b.push({ label: "Delete", cls: "warn", act: async () => { await run("citem.delete", { id: it.id }, "Deleted"); done(); } });
    modal(it ? "Letter / report / delivery" : "Add letter, report, delivery or milestone", f, b, { narrow: true });
  }
  async function contractDrawer(id, reload) {
    const k = id ? await run("con.get", { id }) : null;
    const tpl = await api("con.templates", {});
    const f = form([{ k: "title", label: "Contract", req: true, wide: true }, { k: "kind", label: "Type", type: "select", noBlank: true, options: CON_KINDS }, { k: "ref_no", label: "Agreement / reference no." },
      { k: "party_id", label: "With (party)", type: "select", options: () => opt.parties(), search: true }, { k: "project_id", label: "Project", type: "select", options: opt.projects },
      { k: "value", label: "Contract value", type: "number" }, { k: "start_date", label: "Start", type: "date" }, { k: "end_date", label: "End", type: "date" }, { k: "retention_pct", label: "Retention %", type: "number" },
      { k: "advance", label: "Advance", type: "number" }, { k: "bond_no", label: "Performance bond / BG no." }, { k: "bond_expiry", label: "Bond expires", type: "date" }, { k: "insurance_expiry", label: "Insurance expires", type: "date" },
      { k: "contact", label: "Contact person / phone" }, { k: "status", label: "Status", type: "select", noBlank: true, options: [["active", "Active"], ["completed", "Completed"], ["terminated", "Terminated"]] },
      { k: "remarks", label: "Remarks", type: "textarea", wide: true }], k || { kind: "subcontract", status: "active", project_id: S.project, start_date: today() });
    const tplBox = h("div");
    const tplPick = () => {
      const kind = f.values().kind;
      tplBox.innerHTML = "";
      if (k) return;
      const items = (tpl[kind] || []);
      if (!items.length) return;
      tplBox.append(h("h4", { style: "margin:12px 0 4px" }, "Start with these letters / reports (tick to add)"), ...items.map((x, i) => { const cb = h("input", { type: "checkbox", checked: true }); cb.dataset.i = i; return h("label", { class: "f check" }, cb, x.title + " — " + lbl(REPEATS, x.repeat).toLowerCase() + ", " + lbl(DIRS, x.direction).toLowerCase()); }));
    };
    f.addEventListener("change", (e) => { if (e.target && e.target.name === "kind") tplPick(); });
    tplPick();
    const body = h("div", {}, f, tplBox);
    let dr;
    const refresh = async () => { dr.close(); await reload(); contractDrawer(k.id, reload); };
    if (k) {
      const fig = k.figures;
      body.append(h("h3", { style: "margin:16px 0 6px" }, "Money"), summaryStrip([["Value", fmtMoney(k.value)], ["Billed", fmtMoney(fig.billed) + (fig.billed_pct != null ? " (" + fmtN(fig.billed_pct, 1) + "%)" : "")], ["Paid", fmtMoney(fig.paid)], ["Retention held", fmtMoney(fig.retention_held)], ["Orders placed", fmtMoney(fig.po_value)]]));
      body.append(h("div", { class: "bar", style: "margin-top:14px" }, h("h3", { style: "margin:0" }, "Letters, reports, deliveries and milestones"), h("div", { class: "grow" }),
        can("commercial", "edit") ? h("button", { class: "btn small primary", onclick: () => itemDialog(null, k.id, refresh) }, "+ Add") : null),
      table([{ k: "due_date", label: "Due" }, { label: "Type", v: (x) => lbl(ITEM_KINDS, x.kind) }, { k: "title", label: "What" }, { label: "Who", v: (x) => lbl(DIRS, x.direction) }, { label: "Repeats", v: (x) => lbl(REPEATS, x.repeat) },
        { k: "responsible", label: "Responsible" }, { k: "status", label: "Status", fmt: "status" }, { k: "done_date", label: "Done" }, { k: "ref_no", label: "Ref." }],
      k.items, { name: "contract_items", onRow: (x) => itemDialog(x, k.id, refresh), rowClass: (x) => x.status === "pending" && x.due_date && x.due_date < today() ? "bad" : "", empty: "Nothing scheduled yet." }));
      if (k.deliveries.length) body.append(h("h3", { style: "margin:16px 0 6px" }, "Deliveries on purchase orders"), table([{ k: "no", label: "PO" }, { k: "delivery_date", label: "Due" }, { label: "Item", v: (x) => x.material || x.description }, { k: "qty", label: "Ordered", fmt: "qty" }, { k: "received_qty", label: "Received", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "last_grn", label: "Last delivery" }],
        k.deliveries, { name: "contract_deliveries", rowClass: (x) => (x.received_qty || 0) < x.qty && x.delivery_date && x.delivery_date < today() ? "bad" : "" }));
    }
    const btns = can("commercial", "edit") ? [{ label: "Save", cls: "primary", act: async () => {
      const v = f.values();
      const template = [];
      if (!k) tplBox.querySelectorAll("input[type=checkbox]").forEach((cb) => { if (cb.checked) { const x = (tpl[v.kind] || [])[Number(cb.dataset.i)]; if (x) template.push(Object.assign({}, x, { due_date: v.start_date || today() })); } });
      const r = await run("con.save", { row: Object.assign(v, { id: k && k.id }), template }, "Saved");
      dr.close(); await reload(); contractDrawer(r.id, reload); return false;
    } }] : [];
    if (k && can("commercial", "approve")) btns.push({ label: "Delete", cls: "warn", act: async () => { await run("con.delete", { id: k.id }, "Deleted"); await reload(); } });
    if (k) btns.push({ label: "Print", act: () => { printFrame("Contract " + (k.ref_no || "") + " " + k.title, body, [["Party", k.party || ""], ["Value", fmtMoney(k.value)]]); return false; } });
    dr = drawer(k ? k.title : "New contract", body, btns, { head: k ? stamp(k.status) : null });
  }
  async function dueTab() {
    const r = await run("con.schedule", { project_id: S.project || null, days: 30 });
    const box = h("div");
    const doneBtn = (x) => can("commercial", "edit") ? h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); const ref = await ask("Mark done", x.title + " — reference / letter no. (optional)", { input: "e.g. HN/2083/045" }); if (ref === null) return; const res = await run("citem.done", { id: x.id, ref_no: ref }, "Done"); if (res.next_id) toast("The next one is scheduled", "ok"); go(); } }, "Done") : "";
    box.append(h("h3", {}, "Letters, reports, bills and deliveries due (next 30 days and overdue)"),
      table([{ k: "due_date", label: "Due" }, { label: "When", v: (x) => x.state === "overdue" ? h("b", { class: "red" }, Math.abs(x.days) + " days late") : x.state === "today" ? "today" : "in " + x.days + " days" },
        { label: "Type", v: (x) => lbl(ITEM_KINDS, x.kind) }, { k: "title", label: "What" }, { label: "Who", v: (x) => lbl(DIRS, x.direction) }, { k: "contract", label: "Contract" }, { k: "party", label: "Party" }, { k: "responsible", label: "Responsible" }, { label: "", v: doneBtn }],
      r.items, { name: "contract_due", rowClass: (x) => x.state === "overdue" ? "bad" : x.state === "today" ? "flag" : "", empty: "Nothing due. Add letters and reports to each contract." }));
    box.append(h("h3", { style: "margin-top:18px" }, "Bonds, insurance and contracts expiring"),
      table([{ k: "date", label: "Date" }, { k: "what", label: "What" }, { k: "contract", label: "Contract" }, { k: "ref_no", label: "Ref." }, { k: "party", label: "Party" }, { k: "state", label: "State", fmt: "status" }],
        r.expiring, { name: "contract_expiring", rowClass: (x) => x.state === "expired" ? "bad" : "flag", empty: "Nothing expires in the next 30 days." }));
    box.append(h("h3", { style: "margin-top:18px" }, "Deliveries late or due (purchase orders)"),
      table([{ k: "delivery_date", label: "Due" }, { k: "no", label: "PO" }, { k: "party", label: "Supplier" }, { k: "item", label: "Item" }, { k: "qty", label: "Ordered", fmt: "qty" }, { k: "received_qty", label: "Received", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "state", label: "State", fmt: "status" }],
        r.deliveries, { name: "deliveries_due", rowClass: (x) => x.state === "late" ? "bad" : "", empty: "No delivery is late." }));
    return box;
  }
  async function registerTab() {
    const box = h("div");
    const load = async () => {
      const rows = await run("con.list", { project_id: S.project || null });
      box.innerHTML = "";
      box.append(table([{ k: "ref_no", label: "Ref." }, { k: "title", label: "Contract" }, { label: "Type", v: (x) => lbl(CON_KINDS, x.kind) }, { k: "party", label: "Party" }, { k: "value", label: "Value", fmt: "money" },
        { k: "billed", label: "Billed", fmt: "money" }, { label: "Billed %", v: (x) => x.billed_pct == null ? "" : fmtN(x.billed_pct, 1) + "%" }, { k: "end_date", label: "Ends" },
        { k: "next_due", label: "Next due" }, { label: "Overdue", v: (x) => x.overdue ? h("b", { class: "red" }, x.overdue) : "" }, { k: "flags", label: "Watch" }, { k: "status", label: "Status", fmt: "status" }],
      rows, { name: "contracts", onRow: (x) => contractDrawer(x.id, load), rowClass: (x) => x.overdue ? "bad" : x.flags ? "flag" : "", empty: "No contract yet. Add subcontracts, supply and hire agreements and the main contract to track their letters, reports and deliveries." }));
    };
    await load();
    return h("div", {}, can("commercial", "edit") ? h("div", { class: "bar" }, h("div", { class: "grow" }), h("button", { class: "btn primary", onclick: () => contractDrawer(null, load) }, "New contract")) : null, box);
  }
  PAGES["c/contracts"] = async (root, params) => {
    root.append(pageHead("Contracts & letters", "Every contract with its letters, reports, bills, deliveries and milestones as the contract requires — what is due, what is late, bonds and insurance expiring."));
    root.append(tabs([["Due now", dueTab], ["Contract register", registerTab]], Number(params.tab || 0)));
  };

  /* ───────────────────────── Machines: repairs and complete history ───────────────────────── */
  function recordRepair(eqId, done) {
    const f = form([{ k: "equipment_id", label: "Machine", type: "select", options: opt.equipment, req: true, default: eqId },
      { k: "type", label: "Type", type: "select", noBlank: true, options: [["breakdown", "Breakdown / repair"], ["preventive", "Service (maintenance plan)"], ["inspection", "Inspection"]] },
      { k: "reported_at", label: "Broke down / started", type: "datetime-local" }, { k: "completed_at", label: "Back at work", type: "datetime-local" },
      { k: "description", label: "Problem / service", req: true, wide: true }, { k: "cause_detail", label: "Cause", wide: true }, { k: "action_taken", label: "Repair done", type: "textarea", wide: true },
      { k: "parts_replaced", label: "Parts replaced", wide: true }, { k: "workshop", label: "Workshop / mechanic" }, { k: "meter", label: "Meter reading", type: "number" },
      { k: "parts_cost", label: "Parts bought outside (cost)", type: "number" }, { k: "labour_cost", label: "Labour cost", type: "number" }, { k: "external_cost", label: "Outside workshop bill", type: "number" },
      { k: "downtime_hours", label: "Downtime hours (blank = from the times)", type: "number" }]);
    modal("Record a repair or service already done", h("div", {}, f, h("p", { class: "hint" }, "For a machine that is down now, use Equipment › Work orders › Report breakdown instead, then issue spares from the store against the work order.")),
      [{ label: "Save", cls: "primary", act: async () => { const v = f.values(); ["reported_at", "completed_at"].forEach((k) => { if (v[k] && v[k].length === 16) v[k] += ":00"; }); v.project_id = S.project || null; await run("wo.record", v, (x) => "Saved " + x.no); done && done(); } }], {});
  }
  function repairDetails(w, done) {
    const f = form([{ k: "cause_detail", label: "Cause", wide: true }, { k: "failure_code", label: "Failure type", type: "select", options: [["hydraulic", "Hydraulic"], ["engine", "Engine"], ["electrical", "Electrical"], ["transmission", "Transmission / drive"], ["undercarriage", "Undercarriage / tyres"], ["attachment", "Attachment (bucket, breaker…)"], ["structural", "Structural / welding"], ["operator", "Operator error"], ["other", "Other"]] },
      { k: "action_taken", label: "Repair done", type: "textarea", wide: true }, { k: "parts_replaced", label: "Parts replaced", wide: true }, { k: "workshop", label: "Workshop / mechanic" }, { k: "technician", label: "Technician" },
      { k: "parts_cost", label: "Parts bought outside", type: "number" }, { k: "labour_cost", label: "Labour cost", type: "number" }, { k: "external_cost", label: "Outside workshop bill", type: "number" },
      { k: "downtime_hours", label: "Downtime hours", type: "number" }, { k: "repair_remarks", label: "Remarks", type: "textarea", wide: true }], w);
    modal("Repair record — " + (w.no || ""), h("div", {}, f, h("p", { class: "hint" }, "Spares issued from the store against this work order are added to its cost automatically.")),
      [{ label: "Save", cls: "primary", act: async () => { await run("wo.repair", Object.assign(f.values(), { id: w.id }), "Saved"); done && done(); } }], { narrow: true });
  }
  if (typeof window.woDialog === "function") {
    const _wo = window.woDialog;
    window.woDialog = function (w, done) {
      const n = document.querySelectorAll(".overlay").length;
      const r = _wo(w, done);
      const all = document.querySelectorAll(".overlay");
      if (w && w.id && all.length > n && can("equipment", "edit")) {
        const foot = all[all.length - 1].querySelector("footer");
        if (foot) foot.insertBefore(h("button", { class: "btn", onclick: () => repairDetails(w, done) }, "Repair record"), foot.firstChild);
      }
      return r;
    };
    try { woDialog = window.woDialog; } catch (e) { /* ignore */ }
  }
  const histCols = [{ k: "date", label: "Date" }, { k: "machine", label: "Machine" }, { k: "kind", label: "What happened" }, { k: "ref", label: "Ref." }, { k: "what", label: "Problem / item" },
    { k: "cause", label: "Cause" }, { k: "action", label: "Repair / action" }, { k: "parts", label: "Parts / qty" }, { k: "workshop", label: "Workshop" }, { k: "downtime", label: "Down h", fmt: "qty" }, { k: "cost", label: "Cost", fmt: "money" }];
  PAGES["eq/history"] = async (root, params) => {
    let v = { equipment_id: params.equipment || "", from: params.from || "", to: params.to || "" };
    const holder = h("div");
    root.append(pageHead("Repairs & machine history", "The complete maintenance and repair history of every machine: breakdowns, repairs, services, parts and oil issued, downtime and cost.",
      can("equipment", "edit") ? h("button", { class: "btn primary", onclick: () => recordRepair(v.equipment_id, load) }, "Record repair / service done") : null,
      h("button", { class: "btn", onclick: () => { location.hash = "#/eq/wo"; } }, "Work orders"), h("button", { class: "btn", onclick: () => { location.hash = "#/eq/maint"; } }, "Maintenance plans")),
    filterBar([{ k: "equipment_id", label: "Machine", type: "select", options: opt.equipment, blank: "All machines" }, { k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], v, (x) => { v = x; load(); }), holder);
    async function load() {
      holder.innerHTML = "";
      const r = await run("eq.history", Object.assign({}, v, { timeline: v.equipment_id ? 1 : 0 }));
      if (!v.equipment_id) {
        holder.append(table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "status", label: "Now", fmt: "status" }, { k: "worked", label: "Hours worked", fmt: "qty" },
          { k: "breakdowns", label: "Breakdowns", fmt: "num" }, { k: "services", label: "Services", fmt: "num" }, { k: "downtime", label: "Downtime h", fmt: "qty" },
          { label: "MTBF h", v: (x) => x.mtbf == null ? "" : fmtN(x.mtbf, 0) }, { label: "MTTR h", v: (x) => x.mttr == null ? "" : fmtN(x.mttr, 1) },
          { label: "Availability", v: (x) => x.availability == null ? "" : fmtN(x.availability, 1) + "%" }, { k: "repair_cost", label: "Repair cost", fmt: "money" },
          { k: "store_issues", label: "Fuel, oil & parts issued", fmt: "money" }, { k: "last_repair", label: "Last repair" }],
        r.summary, { name: "fleet_history", totals: ["worked", "downtime", "repair_cost", "store_issues"], onRow: (x) => { v = Object.assign({}, v, { equipment_id: String(x.equipment_id) }); location.hash = "#/eq/history?equipment=" + x.equipment_id; },
          rowClass: (x) => x.status === "breakdown" ? "bad" : "" }));
        return;
      }
      const s = r.summary[0] || {};
      holder.append(h("div", { class: "bar" }, h("h2", { class: "sec", style: "margin:0" }, (s.code || "") + " " + (s.name || "")), h("div", { class: "grow" }),
        h("button", { class: "btn", onclick: () => printFrame("Machine history card — " + s.code + " " + s.name, card, [["Period", (r.from === "0000-01-01" ? "start" : r.from) + " to " + r.to]]) }, "Print history card")));
      const card = h("div");
      card.append(summaryStrip([["Now", s.status || ""], ["Hours worked", fmtQty(s.worked)], ["Breakdowns", s.breakdowns], ["Services", s.services], ["Downtime h", fmtQty(s.downtime)],
        ["MTBF h", s.mtbf == null ? "—" : fmtN(s.mtbf, 0)], ["MTTR h", s.mttr == null ? "—" : fmtN(s.mttr, 1)], ["Availability", s.availability == null ? "—" : fmtN(s.availability, 1) + "%"],
        ["Repair cost", fmtMoney(s.repair_cost)], ["Repair cost / hour", s.cost_per_hour == null ? "—" : fmtMoney(s.cost_per_hour)]]));
      if (r.plans && r.plans.length) card.append(h("h3", { style: "margin:14px 0 6px" }, "Maintenance plan"),
        table([{ k: "title", label: "Service" }, { k: "interval_type", label: "Every" }, { k: "interval", label: "Interval", fmt: "qty" }, { label: "Last done", v: (x) => x.last_date || fmtQty(x.last_meter) },
          { label: "Due", v: (x) => x.interval_type === "days" ? (x.due_date || "now") : fmtQty(x.due_meter) }, { k: "state", label: "State", fmt: "status" }], r.plans, { name: "plan_status", search: false }));
      card.append(h("h3", { style: "margin:14px 0 6px" }, "History"), table(histCols.filter((c) => c.k !== "machine"), r.events.filter((x) => !x.oil_fuel || params.all), { name: "machine_history", totals: ["downtime", "cost"],
        onRow: (x) => { if (x.wo_id) api("wo.list", {}).then((ws) => { const w = (ws || []).find((y) => y.id === x.wo_id); if (w) repairDetails(w, load); }); },
        empty: "No repair or service recorded in this period." }));
      const oil = r.events.filter((x) => x.oil_fuel);
      if (oil.length) card.append(h("h3", { style: "margin:14px 0 6px" }, "Fuel, oil and parts issued from the store (" + fmtMoney(oil.reduce((a, x) => a + (x.cost || 0), 0)) + ")"),
        table([{ k: "date", label: "Date" }, { k: "ref", label: "Issue" }, { k: "what", label: "Item" }, { k: "parts", label: "Qty" }, { k: "cost", label: "Value", fmt: "money" }], oil, { name: "machine_issues", totals: ["cost"] }));
      holder.append(card);
    }
    await load();
  };

  /* ───────────────────────── DPR: view and print ───────────────────────── */
  const actName = (id) => { const a = ((S.P && S.P.activities) || []).find((x) => x.id === id); return a ? (a.code ? a.code + " " : "") + a.name : ""; };
  const tradeName = (id) => { const t = ((S.P && S.P.trades) || []).find((x) => x.id === id); return t ? t.name : ""; };
  const delayName = (k) => { try { const d = (typeof DELAY_CATS !== "undefined" ? DELAY_CATS : []).find((x) => x[0] === k); return d ? d[1] : k || ""; } catch (e) { return k || ""; } };
  const tbl = (cols, rows) => h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.n ? "n" : "" }, c.l)))),
    h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, cols.map((c) => h("td", { class: c.n ? "n" : "" }, esc(c.v(r)))))) : h("tr", {}, h("td", { colspan: cols.length }, "—"))));
  async function dprDoc(d) {
    if (typeof loadProjectLists === "function") { const keep = S.project; if (String(S.project) !== String(d.project_id)) S.project = d.project_id; try { await loadProjectLists(); } finally { S.project = keep; } }
    const n = (x) => (x == null || x === "" ? "" : fmtQty(x));
    const doc = h("div", { class: "dprdoc" });
    doc.append(h("h2", {}, "Daily Progress Report " + (d.no || "")),
      h("div", { class: "meta" }, [["Project", nm.project(d.project_id)], ["Date", d.date], ["Shift", d.shift], ["Weather", (d.weather || "") + (d.rainfall_mm ? " · rain " + d.rainfall_mm + " mm" : "")],
        ["Site condition", d.site_condition || ""], ["Status", (d.status || "").replace(/_/g, " ")], ["Prepared by", nm.user(d.created_by) || ""], ["Checked by", nm.user(d.checked_by) || ""], ["Approved by", nm.user(d.approved_by) || ""]]
        .map(([k, v]) => h("div", {}, h("b", {}, k + ": "), esc(v)))));
    doc.append(h("h3", {}, "1. Work done"), tbl([{ l: "Activity", v: (r) => actName(r.activity_id) }, { l: "BOQ item", v: (r) => r.boq_item_id ? nm.boq(r.boq_item_id) : "" }, { l: "Location / chainage", v: (r) => [r.location, r.chainage_from != null ? r.chainage_from + "–" + (r.chainage_to ?? "") : ""].filter(Boolean).join(" ") },
      { l: "Planned", n: 1, v: (r) => n(r.planned_qty) }, { l: "Done", n: 1, v: (r) => n(r.actual_qty) }, { l: "Remarks", v: (r) => r.remarks || "" }], d.work || []));
    const lab = d.labour || [];
    doc.append(h("h3", {}, "2. Labour (" + fmtQty(lab.reduce((a, x) => a + (Number(x.count) || 0), 0)) + " workers)"), tbl([{ l: "Trade", v: (r) => tradeName(r.trade_id) }, { l: "Subcontractor", v: (r) => r.party_id ? nm.party(r.party_id) : "Own" },
      { l: "Activity", v: (r) => actName(r.activity_id) }, { l: "Workers", n: 1, v: (r) => n(r.count) }, { l: "Hours", n: 1, v: (r) => n(r.hours) }, { l: "OT hours", n: 1, v: (r) => n(r.ot_hours) }], lab));
    doc.append(h("h3", {}, "3. Equipment"), tbl([{ l: "Machine", v: (r) => nm.eq(r.equipment_id) }, { l: "Operator", v: (r) => r.operator || "" }, { l: "Activity", v: (r) => actName(r.activity_id) },
      { l: "Meter start", n: 1, v: (r) => n(r.meter_start) }, { l: "Meter end", n: 1, v: (r) => n(r.meter_end) }, { l: "Working h", n: 1, v: (r) => n(r.hours) }, { l: "Idle h", n: 1, v: (r) => n(r.idle_hours) },
      { l: "Breakdown h", n: 1, v: (r) => n(r.breakdown_hours) }, { l: "Output", v: (r) => r.output_qty ? n(r.output_qty) : "" }], d.equipment || []));
    doc.append(h("h3", {}, "4. Materials used today"), tbl([{ l: "Material", v: (r) => nm.mat(r.material_id) }, { l: "Qty", n: 1, v: (r) => n(r.qty) }, { l: "Unit", v: (r) => nm.unit ? nm.unit(r.material_id) : "" }, { l: "Value", n: 1, v: (r) => r.amount != null ? fmtMoney(r.amount) : "" }], d.materials || []));
    if ((d.receipts || []).length) doc.append(h("h3", {}, "Materials received"), tbl([{ l: "GRN", v: (r) => r.no }, { l: "Material", v: (r) => nm.mat(r.material_id) }, { l: "Qty", n: 1, v: (r) => n(r.accepted_qty) }], d.receipts));
    doc.append(h("h3", {}, "5. Delays and issues"), tbl([{ l: "Reason", v: (r) => delayName(r.category) }, { l: "Activity", v: (r) => actName(r.activity_id) }, { l: "Hours lost", n: 1, v: (r) => n(r.hours) }, { l: "Description", v: (r) => r.description || "" }], d.delays || []));
    if ((d.tests || []).length) doc.append(h("h3", {}, "6. Quality tests"), tbl([{ l: "Test", v: (r) => r.no || "" }, { l: "Type", v: (r) => r.test_type || "" }, { l: "Location", v: (r) => r.location || "" }, { l: "Status", v: (r) => r.status || "" }], d.tests));
    if (d.remarks) doc.append(h("h3", {}, "Remarks"), h("p", {}, d.remarks));
    if ((d.photos || []).length) doc.append(h("p", {}, (d.photos.length) + " photo(s) attached in BuildCore."));
    doc.append(h("div", { class: "sign" }, h("div", {}, "Site engineer"), h("div", {}, "Checked by"), h("div", {}, "Project manager"), h("div", {}, "Consultant / client")));
    return doc;
  }
  const PRINT_DPR_CSS = "<style>.dprdoc h2{font-size:17px;margin:0 0 6px}.dprdoc h3{font-size:13px;margin:12px 0 4px;border-bottom:2px solid #1b5e86}.dprdoc table{width:100%;border-collapse:collapse}.dprdoc th,.dprdoc td{border:1px solid #999;padding:3px 5px;font-size:11px;text-align:left}.dprdoc td.n,.dprdoc th.n{text-align:right}.dprdoc .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:2px 12px;font-size:12px}.dprdoc .sign{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:36px;font-size:11px}.dprdoc .sign div{border-top:1px solid #333;text-align:center;padding-top:3px}.pb{page-break-after:always}</style>";
  async function viewDpr(id) {
    const d = await run("dpr.get", { id });
    const doc = await dprDoc(d);
    modal("DPR " + (d.no || "") + " · " + d.date, doc, [{ label: "Print", cls: "primary", act: () => { const wrap = h("div", { html: PRINT_DPR_CSS }); wrap.append(doc.cloneNode(true)); printFrame("Daily Progress Report " + (d.no || ""), wrap); return false; } },
      { label: "Open to edit", act: () => { if (typeof dprWizard === "function") dprWizard(d); } }], { head: stamp(d.status) });
  }
  window.bcoViewDpr = viewDpr;
  async function printDprs(rows) {
    if (!rows.length) return toast("No DPR to print.", "err");
    toast("Preparing " + rows.length + " DPR(s)…", "ok");
    const wrap = h("div", { html: PRINT_DPR_CSS });
    for (const r of rows) { const d = await api("dpr.get", { id: r.id }); const doc = await dprDoc(d); doc.classList.add("pb"); wrap.append(doc); }
    printFrame("Daily Progress Reports", wrap);
  }
  async function dprReportsTab() {
    if (!S.project) return projectNotice();
    const fy = FY && !FY.current ? FY : null;
    let v = { from: fy ? fy.start_date : new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10), to: fy ? fy.end_date : today(), status: "" };
    const holder = h("div");
    const load = async () => {
      const rows = await run("dpr.list", Object.assign({ project_id: S.project }, v));
      holder.innerHTML = "";
      const t = table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "shift", label: "Shift" }, { k: "weather", label: "Weather" }, { k: "work_lines", label: "Work lines", fmt: "num" },
        { k: "manhours", label: "Man-hours", fmt: "qty" }, { k: "machine_hours", label: "Machine h", fmt: "qty" }, { k: "status", label: "Status", fmt: "status" },
        { label: "", v: (r) => h("span", { style: "display:flex;gap:6px" }, h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); viewDpr(r.id); } }, "View"), h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); printDprs([r]); } }, "Print")) }],
      rows, { name: "dpr_reports", onRow: (r) => viewDpr(r.id), empty: "No DPR in this period." });
      holder.append(h("div", { class: "bar" }, h("span", { class: "hint grow" }, rows.length + " DPR(s). Tick rows (Space) and press “Print ticked DPRs”, or print them all."),
        h("button", { class: "btn", onclick: () => { const sel = t._k ? t._k.selected() : []; if (!sel.length) return toast("Tick DPRs first (click the boxes or press Space).", "err"); printDprs(sel); } }, "Print ticked DPRs"),
        h("button", { class: "btn primary", onclick: () => printDprs(rows) }, "Print all " + rows.length)), t);
    };
    const box = h("div", {}, filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "status", label: "Status", type: "select", options: [["draft", "Draft"], ["submitted", "Submitted"], ["checked", "Checked"], ["approved", "Approved"]], blank: "All" }], v, (x) => { v = x; load(); }), holder);
    await load();
    return box;
  }
  if (typeof window.bcoTabbed === "function" && PAGES["p/dpr"]) window.bcoTabbed("p/dpr", "Daily progress (DPR)", "Enter, check and approve the daily report; view and print any DPR.", { firstLabel: "Daily reports", tabs: [["View & print", dprReportsTab]] });
  if (typeof window.dprWizard === "function") {
    const _dw = window.dprWizard;
    window.dprWizard = async function (dpr, ctx) {
      const n = document.querySelectorAll(".overlay").length;
      const r = await _dw(dpr, ctx);
      const all = document.querySelectorAll(".overlay");
      if (dpr && dpr.id && all.length > n) {
        const foot = all[all.length - 1].querySelector("footer");
        if (foot) foot.insertBefore(h("button", { class: "btn", onclick: () => viewDpr(dpr.id) }, "View report"), foot.firstChild);
      }
      return r;
    };
    try { dprWizard = window.dprWizard; } catch (e) { /* ignore */ }
  }

  /* ───────────────────────── BOQ items by location / component, inside the entry sheet ───────────────────────── */
  const _boq = PAGES["m/boq"];
  if (_boq) PAGES["m/boq"] = async (root, params) => {
    if (!S.project) return _boq(root, params);
    let comps = [];
    try { comps = (await api("comp.list", { project_id: S.project })).rows || []; } catch (e) { comps = []; }
    const o = (typeof MASTERS_UI !== "undefined" && MASTERS_UI.boq_items) || null;
    let loc = params.loc || LS("bco_boq_loc_" + S.project, "");
    if (loc && loc !== "none" && !comps.find((c) => String(c.id) === String(loc))) loc = "";
    /* new items open with the location being viewed */
    if (o && !o._locDef) {
      o._locDef = true;
      const d0 = o.defaults;
      o.defaults = () => Object.assign({}, d0 ? d0() : {}, window.__bcoBoqLoc && window.__bcoBoqLoc !== "none" ? { component_id: window.__bcoBoqLoc } : {});
    }
    window.__bcoBoqLoc = loc;
    const sel = h("select", { style: "width:auto;min-width:220px", onchange: () => {
      if (sel.value === "__new") { sel.value = loc; newLoc(); return; }
      LSset("bco_boq_loc_" + S.project, sel.value || null);
      const want = "#/m/boq?loc=" + encodeURIComponent(sel.value || "");
      if (location.hash === want) { if (typeof go === "function") go(); } else location.hash = want;
    } }, h("option", { value: "" }, "All locations / components"), comps.map((c) => h("option", { value: c.id, selected: String(c.id) === String(loc) }, (c.code ? c.code + " " : "") + c.name + " (" + c.items + ")")),
      h("option", { value: "none", selected: loc === "none" }, "Not assigned"), can("commercial", "edit") ? h("option", { value: "__new" }, "+ New location…") : null);
    const newLoc = async () => {
      const name = await ask("New location / component", "Name (e.g. Headworks, Headrace alignment, Powerhouse, Tailrace, Switchyard)", { input: "Location name", required: true, ok: "Add" });
      if (!name || !name.trim()) return;
      await run("comp.save", { row: { project_id: S.project, name: name.trim(), code: "" } }, "Added " + name.trim());
      go();
    };
    const box = h("div");
    await _boq(box, params);
    const idx = new Map(comps.map((c, i) => [c.id, i]));
    const keep = (r) => !loc ? true : loc === "none" ? !r.component_id : String(r.component_id) === String(loc);
    const decorate = (lt) => {
      const K = lt && lt._k;
      if (!K || lt._locDone) return;
      lt._locDone = true;
      K.all = K.all.filter(keep).sort((a, b) => (idx.has(a.component_id) ? idx.get(a.component_id) : 1e6) - (idx.has(b.component_id) ? idx.get(b.component_id) : 1e6) || String(a.code).localeCompare(String(b.code), undefined, { numeric: true }));
      const paintGroups = () => {
        if (loc) return;
        const body = lt.querySelector("tbody");
        const amt = (r) => (Number(r.qty) || 0) * (Number(r.rate) || 0);
        let last;
        [...body.children].forEach((tr) => {
          const r = tr._r;
          if (!r) return;
          if (r.component_id !== last) {
            last = r.component_id;
            const c = comps.find((x) => x.id === r.component_id);
            const items = K.vis.filter((x) => x.component_id === r.component_id);
            tr.before(h("tr", { class: "locgroup" }, h("td", { colspan: tr.children.length }, (c ? (c.code ? c.code + " " : "") + c.name : "Not assigned to a location") + " — " + items.length + " items · " + fmtMoney(items.reduce((a, x) => a + amt(x), 0)))));
          }
        });
      };
      const r0 = K.render;
      K.render = () => { r0(); paintGroups(); };
      K.render();
    };
    if (window.__bcoBoqWatch) window.__bcoBoqWatch.disconnect();
    const watch = new MutationObserver(() => { if (!location.hash.startsWith("#/m/boq")) { watch.disconnect(); return; } const lt = root.querySelector(".klist"); if (lt && !lt._locDone) decorate(lt); });
    window.__bcoBoqWatch = watch;
    decorate(box.querySelector(".klist"));
    root.append(h("div", { class: "bar", style: "margin-bottom:6px" }, h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:8px" }, h("span", {}, "Location / component"), sel),
      h("span", { class: "hint grow" }, loc ? "New items are filed under this location." : "Items are grouped by location with subtotals. Choose one to work on it alone."),
      can("commercial", "view") ? h("button", { class: "btn small", onclick: () => { location.hash = "#/p/boq?tab=1"; } }, "Monitoring by location") : null));
    root.append(...box.childNodes);
    watch.observe(root, { childList: true, subtree: true });
  };
})();
