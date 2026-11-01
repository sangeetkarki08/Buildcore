/* BuildCore 2.9 — Help assistant (F1), shortcut key directory (Ctrl+/), the user's own shortcut keys,
   and the AI document reader for contracts and specifications (Commercial › Contract documents). */
(function () {
  "use strict";
  const SS = (k, d) => { try { const v = sessionStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const SSset = (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const css = document.createElement("style");
  css.textContent = [
    ".aipanel{position:fixed;top:0;right:0;bottom:0;width:min(440px,100vw);background:var(--panel,#fff);border-left:1px solid var(--line,#dbe2e8);box-shadow:-18px 0 50px rgba(16,42,60,.16);z-index:80;display:flex;flex-direction:column}",
    ".aipanel>header{display:flex;align-items:center;gap:8px;padding:12px 14px 0;}",
    ".aipanel>header b{font-size:16px;flex:1}.aipanel>header .x{border:0;background:none;font-size:22px;cursor:pointer;color:var(--muted)}",
    ".aitabs{display:flex;gap:4px;padding:8px 12px 0;border-bottom:1px solid var(--line)}.aitabs button{border:0;background:none;padding:8px 10px;cursor:pointer;color:var(--muted);font-weight:600;border-bottom:2px solid transparent}",
    ".aitabs button.on{color:var(--blue,#1769aa);border-bottom-color:var(--blue,#1769aa)}",
    ".aibody{flex:1;overflow:auto;padding:12px 14px}.aipanel .aifoot{border-top:1px solid var(--line);padding:10px 12px;display:flex;gap:8px;align-items:flex-end}",
    ".aifoot textarea{flex:1;min-height:42px;max-height:140px;resize:vertical;border-radius:10px;padding:8px 10px}",
    ".aimsg{margin:0 0 12px;line-height:1.5;font-size:13.5px}.aimsg.me{background:var(--blue-wash,#e7f0f8);border-radius:12px 12px 2px 12px;padding:8px 12px;margin-left:40px}",
    ".aimsg.bot{background:#fff;border:1px solid var(--line);border-radius:12px 12px 12px 2px;padding:10px 12px;margin-right:16px}",
    ".aimsg.bot p{margin:0 0 6px}.aimsg.bot ul,.aimsg.bot ol{margin:4px 0 6px 18px;padding:0}.aimsg.bot h4{margin:8px 0 4px;font-size:13.5px}",
    ".aimsg.bot a.go{display:inline-block;background:var(--blue-wash);border-radius:6px;padding:0 6px;text-decoration:none;color:var(--blue);font-weight:600;cursor:pointer}",
    ".aimsg .meta{font-size:11.5px;color:var(--muted);margin-top:6px}.aimsg.wait{color:var(--muted);font-style:italic}",
    ".aichips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 12px}.aichips button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 10px;cursor:pointer;font-size:12.5px}",
    ".aichips button:hover{border-color:var(--blue);color:var(--blue)}",
    ".aistate{font-size:12px;color:var(--muted);margin:0 0 10px;display:flex;gap:6px;align-items:center}.aistate i{width:8px;height:8px;border-radius:50%;background:#b9c4c9;display:inline-block}.aistate i.on{background:#2f9e5a}",
    ".topic{border:1px solid var(--line);border-radius:10px;margin:0 0 8px;background:#fff}.topic>b{display:block;padding:8px 10px;cursor:pointer}.topic>div{padding:0 12px 10px;font-size:13px;line-height:1.5}",
    ".topic .tk{font-size:11.5px;color:var(--muted);font-weight:400;margin-left:6px}",
    ".kdir h4{margin:14px 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted)}",
    ".kdir table{width:100%;border-collapse:collapse}.kdir td{padding:5px 6px;border-bottom:1px solid var(--line-soft,#edf1f4);font-size:13px;vertical-align:top}",
    ".kbd,kbd.k{font-family:Consolas,monospace;font-size:12px;white-space:nowrap}kbd.k{border:1px solid #c9d2d6;border-bottom-width:2px;border-radius:5px;padding:0 5px;background:#f7f9fa}",
    ".sc-capture{border:2px dashed var(--blue);border-radius:10px;padding:12px;text-align:center;font-size:15px;cursor:pointer;background:var(--blue-wash);margin-bottom:10px}",
    ".sc-capture.on{background:#fff4cc;border-color:#d4a21b}.scwarn{background:#fff4cc;border:1px solid #ecd58a;border-radius:8px;padding:8px 10px;font-size:12.5px;margin:6px 0}",
    ".helpbtn{width:34px;height:34px;border-radius:50%;border:1px solid var(--line);background:#fff;color:var(--blue);font-weight:800;cursor:pointer;font-size:15px}",
    ".helpbtn:hover{background:var(--blue);color:#fff}",
    ".docgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}",
    ".abs-cat{margin:16px 0 6px;font-size:14px;border-bottom:2px solid var(--line);padding-bottom:4px}",
    ".absrow{display:grid;grid-template-columns:22px 1fr auto;gap:8px;padding:9px 6px;border-bottom:1px solid var(--line-soft)}.absrow:hover{background:#fafcfd}",
    ".absrow .t{font-weight:600}.absrow .v{color:#0f766e;font-weight:700;margin-left:6px}.absrow .d{font-size:13px;color:#2d3b45;margin-top:2px;white-space:pre-wrap}",
    ".absrow .m{font-size:12px;color:var(--muted);margin-top:3px}.absrow .m a{cursor:pointer;color:var(--blue)}.absrow .acts{display:flex;gap:4px;align-items:flex-start}",
    ".absrow.rejected{opacity:.5}.absrow.approved .t:before{content:'✓ ';color:#2f9e5a}",
    ".pgtext{white-space:pre-wrap;font:12.5px/1.55 Consolas,monospace;background:#fafcfd;border:1px solid var(--line);border-radius:8px;padding:12px;max-height:65vh;overflow:auto}",
    ".pgtext mark{background:#ffe48a}",
    ".hit{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:0 0 8px;font-size:13px;background:#fff}.hit b{cursor:pointer;color:var(--blue)}",
    "@media print{.aipanel{display:none!important}}",
  ].join("");
  document.head.append(css);

  /* ───────────────────────── small helpers ───────────────────────── */
  async function waitJob(id, onStep) {
    const end = Date.now() + 15 * 60000;
    while (Date.now() < end) {
      await sleep(1100);
      const j = await api("ai.job", { id });
      if (onStep && j.step) onStep(j.step);
      if (j.status === "done") return j.result;
      if (j.status === "failed") throw new Error(j.error || "The AI request failed.");
    }
    throw new Error("The AI took too long. Try again.");
  }
  function goTo(path) { location.hash = path.startsWith("#") ? path : "#/" + path.replace(/^\/+/, ""); }

  /* very small Markdown: paragraphs, lists, bold, code, headings and links to BuildCore screens */
  function md(text) {
    const lines = esc(text || "").split(/\r?\n/);
    let out = "", list = null;
    const inline = (s) => s
      .replace(/\[([^\]]+)\]\((#\/[^)\s]*)\)/g, (m, t, href) => '<a class="go" data-go="' + href + '">' + t + " ›</a>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    const close = () => { if (list) { out += "</" + list + ">"; list = null; } };
    lines.forEach((ln) => {
      const t = ln.trim();
      let m;
      if (!t) { close(); return; }
      if ((m = t.match(/^#{1,4}\s+(.*)$/))) { close(); out += "<h4>" + inline(m[1]) + "</h4>"; return; }
      if ((m = t.match(/^[-*•]\s+(.*)$/))) { if (list !== "ul") { close(); out += "<ul>"; list = "ul"; } out += "<li>" + inline(m[1]) + "</li>"; return; }
      if ((m = t.match(/^\d+[.)]\s+(.*)$/))) { if (list !== "ol") { close(); out += "<ol>"; list = "ol"; } out += "<li>" + inline(m[1]) + "</li>"; return; }
      close(); out += "<p>" + inline(t) + "</p>";
    });
    close();
    const div = h("div", { html: out });
    div.querySelectorAll("a.go").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); goTo(a.dataset.go); }));
    return div;
  }

  /* every screen this user can open (for the assistant, the shortcut picker and the directory) */
  function screens() {
    const out = [];
    try {
      (typeof MENU !== "undefined" ? MENU : []).forEach(([group, module, items]) => {
        if (module && !can(module, "view")) return;
        items.forEach(([path, label, mod]) => {
          if (mod && !can(mod, "view")) return;
          if (typeof PAGES !== "undefined" && !PAGES[path]) return;
          out.push({ path, label, group: window.bcoModTitle ? window.bcoModTitle(group) : group });
        });
      });
    } catch (e) { /* menu not ready */ }
    return out;
  }
  function pageNow() {
    const p = location.hash.replace(/^#\/?/, "").split("?")[0];
    const s = screens().find((x) => x.path === p);
    return { path: p, title: s ? s.label : (document.querySelector("#page h1") || {}).textContent || "" };
  }

  let STATUS = null;
  async function status(force) {
    if (!STATUS || force) { try { STATUS = await api("ai.status", {}); } catch (e) { STATUS = { on: false, provider: "off" }; } }
    return STATUS;
  }

  /* ───────────────────────── the help panel ───────────────────────── */
  let panel = null;
  const CHAT_KEY = () => "bco_ai_chat_" + (S.user ? S.user.id : "x");
  const chat = () => { try { return JSON.parse(SS(CHAT_KEY(), "[]")); } catch (e) { return []; } };
  const saveChat = (c) => SSset(CHAT_KEY(), JSON.stringify(c.slice(-30)));

  function helpPanel(tab) {
    if (!S.user) return;
    if (panel && panel.isConnected) { panel._show(tab || "ask"); return; }
    const body = h("div", { class: "aibody" });
    const foot = h("div", { class: "aifoot", hidden: true });
    const tabsEl = h("div", { class: "aitabs" });
    const defs = [["ask", "Assistant"], ["keys", "Shortcut keys"], ["mine", "My shortcuts"], ["guide", "Guide"]];
    panel = h("aside", { class: "aipanel", role: "complementary", "aria-label": "Help" },
      h("header", {}, h("b", {}, "Help"), h("a", { href: "#/help", class: "btn small", title: "Open Help as a full screen", onclick: () => close() }, "Full screen"),
        h("button", { class: "x", title: "Close (Esc)", onclick: () => close() }, "×")), tabsEl, body, foot);
    const close = () => { panel.remove(); panel = null; };
    panel.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
    panel._show = (t) => {
      tabsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
      body.innerHTML = ""; foot.innerHTML = ""; foot.hidden = true;
      if (t === "ask") assistant(body, foot);
      else if (t === "keys") body.append(keyDirectory());
      else if (t === "mine") myShortcuts(body);
      else guideView(body);
    };
    defs.forEach(([k, l]) => tabsEl.append(h("button", { "data-t": k, onclick: () => panel._show(k) }, l)));
    document.body.append(panel);
    panel._show(tab || "ask");
  }
  window.bcoHelp = helpPanel;

  const SUGGEST = ["Explain this screen", "How do I receive material against a purchase order?", "How do I close the fiscal year?",
    "How do I make my own shortcut key?", "Which bonds or insurance expire soon?", "How do I add a new company?"];

  async function assistant(body, foot, full) {
    const st = await status();
    const log = h("div");
    const state = h("p", { class: "aistate" }, h("i", { class: st.on ? "on" : "" }),
      st.on ? "AI assistant on (" + (st.provider === "claude" ? "Claude" : "local AI") + (st.data ? ", can look up figures" : "") + ")" : "AI is off — answers come from the BuildCore guide",
      can("admin", "edit") ? h("a", { href: "#/admin/ai", style: "margin-left:auto" }, "AI settings") : null);
    const ta = h("textarea", { placeholder: "Ask how to do something in BuildCore…  (Enter to ask, Shift+Enter for a new line)" });
    const sendBtn = h("button", { class: "btn primary" }, "Ask");
    const useScreen = h("input", { type: "checkbox" });
    const screenRow = st.on ? h("label", { class: "aistate", style: "cursor:pointer" }, useScreen, "Let the assistant see what is on my screen (to explain it)") : null;
    const draw = () => {
      log.innerHTML = "";
      const c = chat();
      if (!c.length) {
        log.append(h("p", { class: "hint" }, "Ask in your own words, in English or Nepali. The assistant knows every BuildCore screen and key" +
          (st.on && st.data ? ", and can look up live figures your role may see (stock, contracts due, machines, approvals)." : ".")),
        h("div", { class: "aichips" }, SUGGEST.map((s) => h("button", { onclick: () => { ta.value = s; if (/this screen/i.test(s) && st.on) useScreen.checked = true; send(); } }, s))));
      }
      c.forEach((m) => log.append(bubble(m)));
      if (log.lastChild && log.lastChild.scrollIntoView) setTimeout(() => log.lastChild && log.lastChild.scrollIntoView({ block: "end" }), 20);
    };
    const bubble = (m) => {
      if (m.role === "user") return h("div", { class: "aimsg me" }, m.text);
      const b = h("div", { class: "aimsg bot" });
      if (m.text) b.append(md(m.text));
      if (m.topics && m.topics.length) {
        b.append(h("div", { class: "meta" }, m.text ? "From the guide:" : "These parts of the guide match your question:"));
        m.topics.forEach((t) => b.append(topicCard(t, !m.text)));
      }
      if (m.looked && m.looked.length) b.append(h("div", { class: "meta" }, "Looked up in BuildCore now: " + m.looked.join(", ")));
      return b;
    };
    const send = async () => {
      const qtext = ta.value.trim();
      if (!qtext) return;
      ta.value = "";
      const c = chat();
      c.push({ role: "user", text: qtext });
      saveChat(c); draw();
      const wait = h("div", { class: "aimsg bot wait" }, "Thinking…");
      log.append(wait); wait.scrollIntoView({ block: "end" });
      sendBtn.disabled = true;
      try {
        const pg = pageNow();
        const hist = c.slice(0, -1).filter((m) => m.text).slice(-8).map((m) => ({ role: m.role, text: m.text }));
        const scr = useScreen.checked ? (((document.querySelector("#page") || {}).innerText || "").slice(0, 20000)) : "";
        const r = await api("ai.ask", { question: qtext, page: pg.path, page_title: pg.title, history: hist, screens: st.on ? screens() : [], screen_text: scr });
        let ans;
        if (r.offline) ans = { role: "assistant", text: r.topics.length ? "" : "I found nothing in the guide for that. Try other words, or open the Guide tab.", topics: r.topics };
        else {
          const res = await waitJob(r.job, (s) => { wait.textContent = s; });
          ans = { role: "assistant", text: res.answer, topics: res.topics, looked: res.looked_up };
        }
        const c2 = chat(); c2.push(ans); saveChat(c2);
      } catch (e) {
        const c2 = chat(); c2.push({ role: "assistant", text: "Sorry — " + e.message }); saveChat(c2);
      } finally { sendBtn.disabled = false; draw(); ta.focus(); }
    };
    sendBtn.onclick = send;
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    const clear = h("button", { class: "btn small", title: "Start a new conversation", onclick: () => { saveChat([]); draw(); } }, "New");
    body.append(state, screenRow, log);
    foot.hidden = false;
    foot.append(ta, h("div", { style: "display:flex;flex-direction:column;gap:6px" }, sendBtn, clear));
    draw();
    setTimeout(() => ta.focus(), 30);
  }

  function topicCard(t, open) {
    const inner = h("div", { hidden: !open }, md(t.body), t.screens && t.screens.length ? h("p", {}, t.screens.map((s) => {
      const sc = screens().find((x) => x.path === s);
      return sc ? h("a", { class: "btn small", style: "margin:2px 4px 2px 0", onclick: () => goTo(s) }, sc.label + " ›") : null;
    })) : null);
    const head = h("b", { onclick: () => { inner.hidden = !inner.hidden; } }, t.title, t.keys ? h("span", { class: "tk" }, t.keys) : null);
    return h("div", { class: "topic" }, head, inner);
  }

  async function guideView(body) {
    const r = await api("help.guide", {});
    const box = h("div");
    const qbox = h("input", { type: "search", placeholder: "Search the guide", style: "width:100%;margin-bottom:10px", oninput: async () => {
      const t = qbox.value.trim();
      box.innerHTML = "";
      const list = t ? (await api("help.search", { q: t, n: 8 })).topics : r.topics;
      list.forEach((x) => box.append(topicCard(x, !!t)));
      if (!list.length) box.append(h("p", { class: "muted" }, "Nothing found."));
    } });
    r.topics.forEach((x) => box.append(topicCard(x, false)));
    body.append(qbox, box);
    setTimeout(() => qbox.focus(), 30);
  }

  /* ───────────────────────── shortcut directory ───────────────────────── */
  const keyPretty = (k) => String(k).split(/\s+\/\s+|\s{2,}/).map((part) => h("span", { style: "margin-right:8px" },
    part.split(/\s+/).map((x) => x === "or" || x === "then" ? h("span", { class: "muted" }, " " + x + " ") : h("kbd", { class: "k" }, x))));

  function keyDirectory() {
    const wrap = h("div", { class: "kdir" });
    const mine = SC.list || [];
    const filter = h("input", { type: "search", placeholder: "Find a key or an action", style: "width:100%;margin-bottom:6px" });
    const holder = h("div");
    const groups = [];
    if (mine.length) groups.push(["My shortcuts", mine.map((s) => [describe(s) + (s.everyone ? "  (for everyone)" : ""), s.combo])]);
    (window.bcoKeyHelp || []).forEach(([t, rows]) => groups.push([t, rows]));
    groups.push(["On the Modules screen", [["Open module 1 – 9", "1 … 9"], ["Back to all modules", "Ctrl+M"]]]);
    const draw = () => {
      const t = filter.value.trim().toLowerCase();
      holder.innerHTML = "";
      groups.forEach(([title, rows]) => {
        const rs = rows.filter(([w, k]) => !t || (w + " " + k).toLowerCase().includes(t));
        if (!rs.length) return;
        holder.append(h("h4", {}, title), h("table", {}, h("tbody", {}, rs.map(([w, k]) => h("tr", {}, h("td", {}, w), h("td", { style: "text-align:right" }, keyPretty(k)))))));
      });
      if (!holder.children.length) holder.append(h("p", { class: "muted" }, "No key matches."));
    };
    filter.addEventListener("input", draw);
    draw();
    wrap.append(h("div", { class: "bar" }, filter),
      h("div", { style: "display:flex;gap:6px;margin-bottom:6px" },
        h("button", { class: "btn small", onclick: () => printFrame("Shortcut keys", holder.cloneNode(true)) }, "Print the list"),
        h("button", { class: "btn small", onclick: () => (panel ? panel._show("mine") : goTo("#/help?tab=mine")) }, "Make my own shortcut…")), holder);
    setTimeout(() => filter.focus(), 30);
    return wrap;
  }

  /* ───────────────────────── the user's own shortcuts ───────────────────────── */
  const SC = { uid: null, list: [], map: {} };
  async function loadSC() {
    if (!S.user) return;
    try { SC.list = await api("sc.list", {}); } catch (e) { SC.list = []; }
    SC.uid = S.user.id;
    SC.map = {};
    // the user's own key wins over one shared with everyone
    SC.list.filter((s) => s.everyone).forEach((s) => { SC.map[s.combo] = s; });
    SC.list.filter((s) => !s.everyone).forEach((s) => { SC.map[s.combo] = s; });
  }
  const COMMANDS = [
    ["help", "Help assistant", () => helpPanel("ask")], ["keys", "Shortcut key directory", () => helpPanel("keys")],
    ["home", "Modules screen", () => goTo("#/home")], ["find", "Find a screen", () => { const i = document.querySelector(".navsearch input, .nav input[type=search]"); if (i) i.focus(); }],
    ["calc", "Calculator", () => window.bcoKeyCmd && window.bcoKeyCmd.calculator()], ["company", "Switch company", () => window.bcoSwitchCompany && window.bcoSwitchCompany()],
    ["configure", "Configure (dates, size)", () => window.bcoKeyCmd && window.bcoKeyCmd.configure()], ["vouchers", "Other vouchers list (F10)", () => window.bcoKeyCmd && window.bcoKeyCmd.otherVouchers()],
    ["zoom", "Bigger / smaller screen", () => window.bcoKeyCmd && window.bcoKeyCmd.zoom()], ["refresh", "Refresh lists", async () => { try { await reloadLookups(); if (typeof go === "function") go(); toast("Lists refreshed", "ok"); } catch (e) { /* ignore */ } }],
    ["back", "Back to the last screen", () => history.back()], ["print", "Print this screen", () => window.print()],
    ["docs", "Contract documents (AI)", () => goTo("#/c/docs")],
    ["copilot", "Copilot: ask for a report", () => goTo("#/copilot")], ["write", "Copilot: write a letter", () => goTo("#/copilot?tab=write")],
    ["myreports", "Copilot: my reports", () => goTo("#/copilot?tab=reports")], ["fields", "Extra fields", () => goTo("#/m/fields")],
  ];
  function describe(s) {
    if (s.label) return s.label;
    if (s.kind === "screen") { const x = screens().find((y) => y.path === s.target); return "Open " + (x ? x.label : s.target); }
    if (s.kind === "new") { const a = (window.bcoActs || {})[s.target]; return "New " + (a ? a.label : s.target); }
    if (s.kind === "command") { const c = COMMANDS.find((x) => x[0] === s.target); return c ? c[1] : s.target; }
    return "Type: " + String(s.target).slice(0, 40) + (String(s.target).length > 40 ? "…" : "");
  }
  function insertText(text) {
    const el = document.activeElement;
    if (!el || !(el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && /^(text|search|)$/.test(el.type || "")))) { toast("Click in a box first, then press the key.", "err"); return; }
    const s = el.selectionStart ?? el.value.length, e = el.selectionEnd ?? el.value.length;
    const t = String(text).replace(/\{today\}/g, today()).replace(/\{user\}/g, S.user ? S.user.name : "");
    el.value = el.value.slice(0, s) + t + el.value.slice(e);
    el.selectionStart = el.selectionEnd = s + t.length;
    el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  window.bcoUserKey = (e, k, typing) => {
    const s = SC.map[k];
    if (!s) return false;
    const strong = /Ctrl\+|Alt\+|^F\d+$|Shift\+F\d+/.test(k);
    if (typing && !strong && s.kind !== "text") return false;
    try {
      if (s.kind === "screen") goTo(s.target);
      else if (s.kind === "new") { if (window.bcoRunAction) window.bcoRunAction(s.target); }
      else if (s.kind === "command") { const c = COMMANDS.find((x) => x[0] === s.target); if (c) c[2](); }
      else if (s.kind === "text") insertText(s.target);
    } catch (err) { toast("Shortcut " + k + ": " + err.message, "err"); }
    return true;
  };

  /* keys BuildCore already uses, so a new shortcut can warn before it replaces one */
  function builtIn() {
    const out = {};
    (window.bcoKeyHelp || []).forEach(([g, rows]) => rows.forEach(([w, k]) => String(k).split(/\s+\/\s+|\s{2,}|\s+or\s+/).forEach((x) => { x = x.trim(); if (/^(Ctrl|Alt|Shift|F\d)/.test(x)) out[x] = w; })));
    ["Ctrl+M", "Ctrl+K", "Alt+F3", "Ctrl+/", "Ctrl+Shift+R", "Shift+F11", "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+A"].forEach((x) => { out[x] = out[x] || "used by BuildCore / Windows"; });
    out["Ctrl+C"] = "Copy"; out["Ctrl+V"] = "Paste"; out["Ctrl+X"] = "Cut"; out["Ctrl+Z"] = "Undo";
    return out;
  }

  function myShortcuts(body) {
    const list = h("div");
    const draw = async () => {
      await loadSC();
      list.innerHTML = "";
      if (!SC.list.length) list.append(h("p", { class: "muted" }, "No shortcuts of your own yet."));
      else list.append(h("table", { class: "kdir", style: "width:100%" }, h("tbody", {}, SC.list.map((s) => h("tr", {},
        h("td", {}, keyPretty(s.combo)), h("td", {}, describe(s), s.everyone ? h("small", { class: "muted" }, "  · everyone" + (s.owner ? " (by " + s.owner + ")" : "")) : null),
        h("td", { style: "text-align:right;white-space:nowrap" },
          s.user_id === S.user.id || S.user.role === "admin" ? [h("button", { class: "btn small", onclick: () => editor(s) }, "Edit"), " ",
            h("button", { class: "btn small", onclick: async () => { await run("sc.delete", { id: s.id }, "Shortcut removed"); draw(); } }, "×")] : null))))));
    };
    const editor = (row) => {
      row = row || {};
      let combo = row.combo || "";
      const bi = builtIn();
      const cap = h("div", { class: "sc-capture", tabindex: "0" }, combo ? "" : "Click here, then press the keys (e.g. Ctrl+Alt+G)");
      const warn = h("div", { class: "scwarn", hidden: true });
      const paint = () => {
        cap.innerHTML = "";
        if (combo) cap.append(...keyPretty(combo)); else cap.append("Click here, then press the keys (e.g. Ctrl+Alt+G)");
        const other = SC.list.find((s) => s.combo === combo && s.id !== row.id && !s.everyone);
        const msg = [];
        if (combo && bi[combo]) msg.push("BuildCore uses " + combo + " for “" + bi[combo] + "”. Your shortcut will replace it for you.");
        if (other) msg.push("You already have " + combo + " for “" + describe(other) + "”; it will be replaced.");
        warn.textContent = msg.join(" "); warn.hidden = !msg.length;
      };
      cap.addEventListener("focus", () => cap.classList.add("on"));
      cap.addEventListener("blur", () => cap.classList.remove("on"));
      cap.addEventListener("keydown", (e) => {
        if (["Control", "Alt", "Shift", "Meta"].includes(e.key)) return;
        e.preventDefault(); e.stopPropagation();
        if (e.key === "Tab") return;
        const nm = window.bcoKeyName ? window.bcoKeyName(e) : e.key;
        const k = (e.ctrlKey && e.shiftKey && !/Shift\+/.test(nm)) ? nm.replace("Ctrl+", "Ctrl+Shift+") : nm;
        combo = k; paint();
      }, true);
      paint();
      const kindSel = h("select", {}, [["screen", "Open a screen"], ["new", "Start a new entry"], ["command", "Run a command"], ["text", "Type a saved text into the box"]].map(([v, l]) => h("option", { value: v, selected: v === (row.kind || "screen") }, l)));
      const tgtBox = h("div");
      let tgt = null;
      const drawTarget = () => {
        tgtBox.innerHTML = "";
        const k = kindSel.value;
        if (k === "screen") {
          const opts = screens().map((s) => [s.path, s.group + " › " + s.label]);
          opts.push(["home", "Modules screen"], ["help", "Help"]);
          tgt = h("select", {}, opts.map(([v, l]) => h("option", { value: v, selected: v === row.target }, l)));
        } else if (k === "new") {
          tgt = h("select", {}, Object.entries(window.bcoActs || {}).filter(([, a]) => !PAGES || PAGES[a.path]).map(([v, a]) => h("option", { value: v, selected: v === row.target }, a.label)));
        } else if (k === "command") {
          tgt = h("select", {}, COMMANDS.map(([v, l]) => h("option", { value: v, selected: v === row.target }, l)));
        } else {
          tgt = h("textarea", { rows: 3, placeholder: "e.g. Being payment made to … as per bill no. …   ({today} = today's date, {user} = your name)" }, row.kind === "text" ? row.target : "");
        }
        tgtBox.append(h("label", { class: "f wide" }, h("span", {}, k === "text" ? "Text" : k === "screen" ? "Screen" : k === "new" ? "Entry" : "Command"), tgt));
      };
      kindSel.addEventListener("change", drawTarget);
      drawTarget();
      const label = h("input", { value: row.label || "", placeholder: "optional — shown in the key list" });
      const every = h("input", { type: "checkbox", checked: !!row.everyone });
      const m = modal(row.id ? "Change shortcut" : "New shortcut", h("div", { class: "form" }, cap, warn,
        h("label", { class: "f wide" }, h("span", {}, "What it does"), kindSel), tgtBox,
        h("label", { class: "f wide" }, h("span", {}, "Name"), label),
        S.user.role === "admin" ? h("label", { class: "f check" }, every, "Share with everyone in this company") : null,
        h("p", { class: "hint" }, "Keys with Ctrl or Alt, or a function key, work everywhere — also while typing in a box. Your shortcuts are saved with your user and work on every computer.")),
      [{ label: "Save", cls: "primary", act: async () => {
        if (!combo) { toast("Press the key you want first.", "err"); return false; }
        await run("sc.save", { row: { id: row.id, combo, kind: kindSel.value, target: tgt.value, label: label.value, everyone: every.checked } }, "Shortcut saved: " + combo);
        draw();
      } }], { narrow: true });
      setTimeout(() => cap.focus(), 50);
      return m;
    };
    body.append(h("p", { class: "hint" }, "Make a key for what you do most: open a screen, start an entry, run a command, or type a standard text (a narration, a remark)."),
      h("div", { style: "margin:0 0 10px" }, h("button", { class: "btn primary", onclick: () => editor() }, "+ New shortcut")), list);
    draw();
  }
  window.bcoShortcutEditor = () => helpPanel("mine");

  /* load the user's shortcuts after sign-in, and put a Help button in the top bar */
  setInterval(() => {
    if (typeof S === "undefined" || !S.user) { SC.uid = null; return; }
    if (SC.uid !== S.user.id) { SC.uid = S.user.id; loadSC(); status(true); }
    const top = document.querySelector(".top");
    if (top && !top.querySelector(".helpbtn")) {
      const b = h("button", { class: "helpbtn", title: "Help — assistant, shortcut keys (F1)", onclick: () => helpPanel("ask") }, "?");
      const um = top.querySelector(".usermenu");
      if (um) top.insertBefore(b, um); else top.append(b);
    }
  }, 800);

  /* ───────────────────────── Help as a full screen ───────────────────────── */
  PAGES["help"] = async (root, params) => {
    const want = (params && params.tab) || "ask";
    const order = ["ask", "keys", "mine", "guide"];
    root.append(pageHead("Help", "Ask the assistant, look up shortcut keys, make your own keys, or read the guide. F1 opens this beside any screen."));
    root.append(tabs([
      ["Assistant", async () => { const b = h("div", { style: "max-width:860px" }); const f = h("div", { class: "aifoot", style: "display:flex;gap:8px;align-items:flex-end;margin-top:10px" }); await assistant(b, f, true); return h("div", {}, b, f); }],
      ["Shortcut keys", () => h("div", { style: "max-width:860px" }, keyDirectory())],
      ["My shortcuts", () => { const b = h("div", { style: "max-width:860px" }); myShortcuts(b); return b; }],
      ["Guide", () => { const b = h("div", { style: "max-width:860px" }); guideView(b); return b; }],
    ], Math.max(0, order.indexOf(want))));
  };

  /* ───────────────────────── Administration › AI settings ───────────────────────── */
  PAGES["admin/ai"] = async (root) => {
    const d = await run("ai.config", {});
    const f = form([
      { k: "provider", label: "AI", type: "select", noBlank: true, options: [["off", "Off — Help answers from the guide only"], ["claude", "Claude (Anthropic, cloud)"], ["local", "Local AI on this computer / network (OpenAI-compatible, e.g. Ollama)"]], wide: true },
      { k: "key", label: "Claude API key", ph: d.has_key ? "saved — type a new key to replace it" : "sk-ant-…", type: "password", hint: "From console.anthropic.com › API keys. Stored only in this company's data file; never shown to users." },
      { k: "model", label: "Claude model", hint: "e.g. claude-sonnet-5 (balanced), claude-opus-5-5 (strongest), claude-haiku-4-5-20251001 (fastest, cheapest)" },
      { k: "local_url", label: "Local AI address", hint: "e.g. http://127.0.0.1:11434/v1 for Ollama" },
      { k: "local_model", label: "Local model name", hint: "e.g. llama3.1, qwen2.5:14b" },
      { k: "data", label: "Let the assistant look up live figures (read only, within each user's role)", type: "check", wide: true },
      { k: "docs", label: "Let the AI read contract documents (Commercial › Contract documents)", type: "check", wide: true },
      { k: "base_url", label: "Claude address (advanced)", hint: "Leave as https://api.anthropic.com unless your IT gives another." },
    ], Object.assign({}, d, { key: "" }));
    const result = h("div");
    root.append(pageHead("AI assistant settings", "The Help assistant (F1) and the contract document reader. Everything else in BuildCore keeps working offline."),
      h("div", { class: "panel" }, f,
        h("div", { class: "actions" },
          h("button", { class: "btn primary", onclick: async () => { const v = f.values(); await run("ai.config_save", { row: v }, "AI settings saved"); STATUS = null; go(); } }, "Save"),
          h("button", { class: "btn", onclick: async () => {
            result.innerHTML = ""; result.append(h("p", { class: "muted" }, "Testing…"));
            try { const r = await api("ai.test", {}); const x = await waitJob(r.job); result.innerHTML = ""; result.append(h("p", { class: "green" }, "✓ The AI answered: " + x.answer)); }
            catch (e) { result.innerHTML = ""; result.append(h("p", { class: "red" }, "✗ " + e.message)); }
          } }, "Test the connection"),
          d.has_key ? h("button", { class: "btn", onclick: async () => { if (await ask("Remove key", "Remove the saved Claude key?")) { await run("ai.config_save", { row: { clear_key: 1 } }, "Key removed"); go(); } } }, "Remove key") : null), result),
      h("div", { class: "panel" }, h("h3", {}, "What is sent, and what it costs"),
        h("ul", {},
          h("li", {}, "Claude: the question, the screen name and the BuildCore guide go to Anthropic over the internet; with document reading, the document's text (or the scanned PDF) goes too. Live figures are read on this computer and only the rows the AI asks for are sent."),
          h("li", {}, "Local AI: nothing leaves your computer or network; answers are weaker on long contracts and scanned PDFs cannot be read."),
          h("li", {}, "The AI only reads. It never posts, approves or deletes; people approve every item it finds in a document."),
          h("li", {}, "Claude is paid per use on your Anthropic account. Reading a long contract costs more than a question. The table shows how much was used."),
          h("li", {}, "Switch the AI off for a company whose documents must not leave the office."))),
      h("div", { class: "panel" }, h("h3", {}, "Use by month"),
        table([{ k: "month", label: "Month" }, { k: "kind", label: "Use" }, { k: "provider", label: "AI" }, { k: "calls", label: "Requests", fmt: "num" },
          { k: "in_tokens", label: "Tokens in", fmt: "num" }, { k: "out_tokens", label: "Tokens out", fmt: "num" }, { k: "failed", label: "Failed", fmt: "num" }],
        d.usage || [], { name: "ai_usage", search: false, empty: "Not used yet." })));
  };

  /* ───────────────────────── Commercial › Contract documents (AI) ───────────────────────── */
  const CAT = () => Object.fromEntries((STATUS && STATUS.categories) || []);
  async function uploadDoc(file, meta) {
    const qs = new URLSearchParams({ filename: file.name, mime: file.type || "", kind: "document", entity: "ai_doc" });
    const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: file });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    return j.data.id;
  }

  PAGES["c/docs"] = async (root, params) => {
    const st = await status(true);
    if (params && params.id) return docView(root, Number(params.id), st, params);
    const contracts = await api("con.list", {}).catch(() => []);
    root.append(pageHead("Contract documents", "Upload the contract, conditions (GCC / SCC), technical specifications and letters. BuildCore reads them; the AI makes a contract abstract and answers questions with clause and page.",
      can("commercial", "edit") ? h("button", { class: "btn primary", onclick: () => addDoc(contracts) }, "+ Upload document") : null));
    if (!st.on || !st.docs) root.append(h("div", { class: "panel", style: "background:#fff9e6" }, h("b", {}, "The AI reader is off. "),
      "You can upload documents and search their text. ", can("admin", "edit") ? h("a", { href: "#/admin/ai" }, "Switch the AI on in AI settings.") : "An administrator can switch the AI on in Administration › AI settings."));
    root.append(tabs([
      ["Documents", async () => {
        const rows = await run("doc.list", {});
        return table([{ k: "title", label: "Document" }, { k: "doc_type", label: "Type" }, { k: "contract", label: "Contract" }, { k: "pages", label: "Pages", fmt: "num" },
          { label: "Read", v: (r) => r.status === "ready" ? (r.scanned ? "scanned (AI reads the images)" : "text read") : r.status === "failed" ? h("span", { class: "red" }, "failed") : r.status },
          { label: "Abstract", v: (r) => r.items ? r.approved + " approved" + (r.to_check ? ", " + r.to_check + " to check" : "") : "—" },
          { k: "created", label: "Added", v: (r) => (r.created || "").slice(0, 10) }],
        rows, { name: "contract_documents", empty: "No documents yet. Upload the contract and specifications.", onRow: (r) => goTo("#/c/docs?id=" + r.id) });
      }],
      ["Approved conditions (all documents)", async () => {
        const rows = await run("item.all", {});
        return table([{ label: "Kind", v: (r) => CAT()[r.category] || r.category }, { k: "title", label: "Item" }, { k: "value", label: "Value" },
          { k: "detail", label: "What the document says" }, { k: "precondition_for", label: "Required before" }, { k: "due_date", label: "Date" },
          { label: "Where", v: (r) => (r.document || "") + (r.clause ? " · " + r.clause : "") + (r.page ? " · p." + r.page : "") }, { k: "contract", label: "Contract" }],
        rows, { name: "contract_conditions", empty: "Nothing approved yet.", onRow: (r) => r.doc_id && goTo("#/c/docs?id=" + r.doc_id) });
      }],
      ["Search all documents", () => searchBox(null)],
    ]));
  };

  function addDoc(contracts) {
    const inp = h("input", { type: "file", accept: ".pdf,.docx,.txt,.md", multiple: true });
    const f = form([
      { k: "doc_type", label: "Type of document", type: "select", noBlank: true, options: ((STATUS && STATUS.doc_types) || ["Other"]).map((x) => [x, x]) },
      { k: "contract_id", label: "Contract (optional)", type: "select", options: contracts.map((k) => [k.id, (k.ref_no ? k.ref_no + " — " : "") + k.title]) },
    ], {});
    modal("Upload document", h("div", {}, h("label", { class: "f wide" }, h("span", {}, "PDF, Word (.docx) or text — up to 60 MB each"), inp), f,
      h("p", { class: "hint" }, "Scanned PDFs (pictures of pages) are read by the Claude AI, up to 100 pages each; split bigger scans. Old .doc files: save as .docx or PDF first.")),
    [{ label: "Upload and read", cls: "primary", act: async () => {
      if (!inp.files.length) { toast("Choose a file.", "err"); return false; }
      const v = f.values();
      let last = null;
      for (const file of inp.files) {
        try {
          const fid = await uploadDoc(file);
          const r = await api("doc.add", { file_id: fid, doc_type: v.doc_type, contract_id: v.contract_id || null });
          last = r;
          toast("Reading " + file.name + "…", "ok");
          waitJob(r.job).then((x) => toast(file.name + ": " + x.pages + " pages read" + (x.scanned ? " (scanned — the AI will read the images)" : ""), "ok"), (e) => toast(file.name + ": " + e.message, "err"));
        } catch (e) { toast(file.name + ": " + e.message, "err"); }
      }
      if (last) { await sleep(400); goTo("#/c/docs?id=" + last.id); }
    } }], { narrow: true });
  }

  function searchBox(docId, onPage) {
    const box = h("div");
    const inp = h("input", { type: "search", placeholder: "Words to find, e.g. liquidated damages, retention, slump", style: "flex:1" });
    const res = h("div");
    const goSearch = async () => {
      res.innerHTML = "";
      const hits = await run("doc.search", docId ? { id: docId, q: inp.value } : { q: inp.value });
      if (!hits.length) res.append(h("p", { class: "muted" }, "Not found."));
      hits.forEach((x) => res.append(hitCard(x, onPage)));
    };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") goSearch(); });
    box.append(h("div", { class: "bar" }, inp, h("button", { class: "btn primary", onclick: goSearch }, "Search")), res);
    setTimeout(() => inp.focus(), 50);
    return box;
  }
  function hitCard(x, onPage) {
    return h("div", { class: "hit" }, h("b", { onclick: () => (onPage && !x.title ? onPage(x.page) : goTo("#/c/docs?id=" + x.doc_id + "&page=" + x.page)) }, (x.title ? x.title + " — " : "") + "page " + x.page + " ›"),
      h("div", {}, x.snippet));
  }

  async function docView(root, id, st, params) {
    const d = await run("doc.get", { id });
    const ed = can("commercial", "edit");
    const cats = CAT();
    let showPage = null;
    root.append(pageHead(d.title, [d.doc_type, d.contract ? "Contract: " + d.contract.title : "not linked to a contract", d.pages ? d.pages + " pages" : null,
      d.scanned ? "scanned PDF" : null, d.status !== "ready" ? "status: " + d.status : null].filter(Boolean).join(" · "),
      h("a", { class: "btn", href: "#/c/docs" }, "‹ All documents"),
      d.file ? h("a", { class: "btn", href: fileUrl(d.file.id), target: "_blank" }, "Open original") : null,
      ed ? h("button", { class: "btn", onclick: () => editDoc(d) }, "Details…") : null));
    if (d.status === "failed") root.append(h("div", { class: "panel", style: "background:#fdeceb" }, h("b", {}, "The text could not be read: "), d.error || "",
      ed ? h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { const r = await run("doc.reindex", { id }); await waitJob(r.job).catch((e) => toast(e.message, "err")); go(); } }, "Try again")) : null));
    if (d.status === "new" || d.status === "indexing") {
      const p = h("p", { class: "muted" }, "Reading the document…");
      root.append(p);
      setTimeout(() => { if (location.hash.includes("c/docs?id=" + id)) go(); }, 2500);
      return;
    }
    const t = tabs([
      ["Abstract" + (d.items.filter((x) => x.status === "proposed").length ? " (" + d.items.filter((x) => x.status === "proposed").length + " to check)" : ""), () => abstractTab(d, st, ed, cats, (pg) => { showPage = pg; t.querySelectorAll(".tabs button")[3].click(); })],
      ["Ask the document", () => askTab(d, st, (pg) => { showPage = pg; t.querySelectorAll(".tabs button")[3].click(); })],
      ["Search", () => searchBox(d.id, (pg) => { showPage = pg; t.querySelectorAll(".tabs button")[3].click(); })],
      ["Pages", () => pagesTab(d, showPage || Number((params && params.page) || 1), (params && params.q) || "")],
    ], params && params.page ? 3 : 0);
    root.append(t);
  }

  function editDoc(d) {
    api("con.list", {}).then((contracts) => {
      const f = form([{ k: "title", label: "Title", wide: true }, { k: "doc_type", label: "Type", type: "select", noBlank: true, options: ((STATUS && STATUS.doc_types) || []).map((x) => [x, x]) },
        { k: "contract_id", label: "Contract", type: "select", options: contracts.map((k) => [k.id, (k.ref_no ? k.ref_no + " — " : "") + k.title]) }], d);
      modal("Document details", f, [
        { label: "Save", cls: "primary", act: async () => { await run("doc.update", Object.assign({ id: d.id }, f.values()), "Saved"); go(); } },
        can("commercial", "approve") ? { label: "Delete document", cls: "warn", act: async () => {
          if (!(await ask("Delete document", "Delete " + d.title + " and the items found in it? Items already added to a contract's schedule stay there.", { danger: true, ok: "Delete" }))) return false;
          await run("doc.delete", { id: d.id }, "Deleted"); goTo("#/c/docs");
        } } : null], { narrow: true });
    });
  }

  function abstractTab(d, st, ed, cats, openPage) {
    const box = h("div");
    const ticked = new Set();
    const bar = h("div", { class: "bar" });
    const readBtn = h("button", { class: "btn primary", disabled: !ed || !st.on || !st.docs }, d.items.some((x) => x.source === "ai") ? "Read again with AI" : "Read with AI");
    const step = h("span", { class: "muted" });
    readBtn.onclick = async () => {
      if (d.items.some((x) => x.status === "proposed" && x.source === "ai") && !(await ask("Read again", "Items not yet checked will be replaced by a new reading. Approved and rejected items stay.", { ok: "Read again" }))) return;
      readBtn.disabled = true;
      try {
        const r = await api("doc.abstract", { id: d.id });
        const x = await waitJob(r.job, (s) => { step.textContent = s; });
        toast(x.items + " items found — check each one", "ok"); go();
      } catch (e) { toast(e.message, "err"); step.textContent = ""; readBtn.disabled = false; }
    };
    const sel = () => [...ticked];
    bar.append(readBtn, step, h("div", { class: "grow" }),
      ed ? h("button", { class: "btn small", onclick: async () => { if (!ticked.size) return toast("Tick items first (or use the buttons on each item).", "err"); await run("item.status", { ids: sel(), status: "approved" }, "Approved"); go(); } }, "Approve ticked") : null,
      ed ? h("button", { class: "btn small", onclick: async () => { if (!ticked.size) return toast("Tick items first.", "err"); await run("item.status", { ids: sel(), status: "rejected" }, "Rejected"); go(); } }, "Reject ticked") : null,
      ed ? h("button", { class: "btn small", title: "Approved items with a date go into the contract's letters / reports / deliveries schedule with reminders", onclick: async () => {
        const ids = ticked.size ? sel() : d.items.filter((x) => x.status === "approved" && x.due_date && !x.citem_id).map((x) => x.id);
        if (!ids.length) return toast("No approved item with a date to add.", "err");
        const r = await run("item.to_schedule", { ids });
        toast(r.made + " added to the contract schedule" + (r.skipped.length ? "; not added: " + r.skipped.join("; ") : ""), r.made ? "ok" : "err"); go();
      } }, "Add dated items to contract schedule") : null,
      ed ? h("button", { class: "btn small", onclick: () => itemEditor(d, {}, cats) }, "+ Add item") : null,
      h("button", { class: "btn small", onclick: () => printAbstract(d, cats) }, "Print abstract"));
    box.append(bar);
    if (!st.on || !st.docs) box.append(h("p", { class: "hint" }, "The AI is off, so items are not found automatically. You can add items by hand (+ Add item) while reading the Pages tab, and use Search."));
    if (!d.items.length) { box.append(h("p", { class: "muted", style: "margin-top:12px" }, st.on ? "Press “Read with AI”. It takes from half a minute to a few minutes for a long contract." : "No items yet.")); return box; }
    box.append(h("p", { class: "hint" }, "The AI can misread or miss things. Check each item against its clause (click the page) before approving. Only approved items are used elsewhere."));
    const groups = {};
    d.items.forEach((x) => { (groups[x.category] = groups[x.category] || []).push(x); });
    Object.keys(cats).concat(Object.keys(groups).filter((k) => !cats[k])).forEach((k) => {
      const list = groups[k];
      if (!list) return;
      box.append(h("h3", { class: "abs-cat" }, (cats[k] || k) + " (" + list.length + ")"));
      list.forEach((x) => {
        const cb = h("input", { type: "checkbox", onchange: () => (cb.checked ? ticked.add(x.id) : ticked.delete(x.id)) });
        box.append(h("div", { class: "absrow " + x.status },
          h("div", {}, ed ? cb : null),
          h("div", {}, h("div", {}, h("span", { class: "t" }, x.title), x.value ? h("span", { class: "v" }, x.value) : null, " ", stamp(x.status === "proposed" ? "to_check" : x.status)),
            x.detail ? h("div", { class: "d" }, x.detail) : null,
            h("div", { class: "m" }, [x.precondition_for ? "Required before: " + x.precondition_for : null, x.due_date ? "Date: " + x.due_date + (x.repeat && x.repeat !== "none" ? " (" + x.repeat + ")" : "") : (x.repeat && x.repeat !== "none" ? "Repeats " + x.repeat : null),
              x.clause ? "Clause " + x.clause : null].filter(Boolean).join(" · "),
              x.page ? [" · ", h("a", { onclick: () => openPage(x.page) }, "page " + x.page + " ›")] : null,
              x.citem_id ? " · in the contract schedule" : null, x.source === "manual" ? " · added by hand" : null)),
          h("div", { class: "acts" }, ed ? [
            x.status !== "approved" ? h("button", { class: "btn small primary", onclick: async () => { await run("item.status", { ids: [x.id], status: "approved" }); go(); } }, "Approve") : null,
            h("button", { class: "btn small", onclick: () => itemEditor(d, x, cats) }, "Edit"),
            x.status !== "rejected" ? h("button", { class: "btn small", title: "Reject", onclick: async () => { await run("item.status", { ids: [x.id], status: "rejected" }); go(); } }, "✗") : null] : null)));
      });
    });
    return box;
  }

  function itemEditor(d, x, cats) {
    const f = form([
      { k: "category", label: "Kind", type: "select", noBlank: true, options: Object.entries(cats) },
      { k: "title", label: "Item", req: true, wide: true }, { k: "value", label: "Value (amount, %, period)" },
      { k: "detail", label: "What the document says", type: "textarea", wide: true },
      { k: "precondition_for", label: "Required before (for preconditions)", wide: true },
      { k: "due_date", label: "Date", type: "date" },
      { k: "repeat", label: "Repeats", type: "select", noBlank: true, options: [["none", "No"], ["weekly", "Weekly"], ["fortnightly", "Fortnightly"], ["monthly", "Monthly"], ["quarterly", "Quarterly"], ["yearly", "Yearly"]] },
      { k: "clause", label: "Clause" }, { k: "page", label: "Page", type: "number" },
    ], Object.assign({ category: "other", repeat: "none" }, x));
    modal(x.id ? "Check / correct item" : "Add item", f, [{ label: x.id ? "Save and approve" : "Add", cls: "primary", act: async () => {
      const v = f.values();
      if (!v.title) { toast("Item is required.", "err"); return false; }
      await run("item.save", { row: Object.assign(v, { id: x.id, doc_id: d.id, status: "approved", page: v.page ? Number(v.page) : null }) }, "Saved");
      go();
    } }], {});
  }

  function printAbstract(d, cats) {
    const items = d.items.filter((x) => x.status === "approved");
    if (!items.length) return toast("Approve items first; the abstract prints approved items.", "err");
    const node = h("div", {}, h("p", {}, d.doc_type + (d.contract ? " · Contract: " + d.contract.title : "")),
      Object.keys(cats).map((k) => {
        const list = items.filter((x) => x.category === k);
        if (!list.length) return null;
        return [h("h3", {}, cats[k]), h("table", { border: "1", style: "border-collapse:collapse;width:100%" }, h("thead", {}, h("tr", {}, ["Item", "Value", "What the document says", "Required before / date", "Clause", "Page"].map((t) => h("th", { style: "text-align:left;padding:4px" }, t)))),
          h("tbody", {}, list.map((x) => h("tr", {}, [x.title, x.value, x.detail, [x.precondition_for, x.due_date].filter(Boolean).join(" · "), x.clause, x.page].map((t) => h("td", { style: "padding:4px;vertical-align:top" }, t == null ? "" : String(t)))))))];
      }),
      h("p", { style: "font-size:11px;color:#666" }, "Prepared with BuildCore from " + d.title + ". Items were checked and approved by users; the document itself governs."));
    printFrame("Contract abstract — " + d.title, node);
  }

  function askTab(d, st, openPage) {
    const box = h("div", { style: "max-width:900px" });
    const ta = h("textarea", { rows: 2, placeholder: "e.g. What is the liquidated damages rate and its maximum?  What tests are needed for shotcrete?  What must be done before concreting?" });
    const out = h("div");
    const btn = h("button", { class: "btn primary" }, "Ask");
    const askNow = async () => {
      const qtext = ta.value.trim();
      if (!qtext) return;
      out.innerHTML = "";
      const wait = h("p", { class: "muted" }, "Reading…");
      out.append(wait);
      btn.disabled = true;
      try {
        const r = await api("doc.ask", { id: d.id, question: qtext });
        out.innerHTML = "";
        if (r.offline) {
          out.append(h("p", { class: "hint" }, "The AI is off — these pages contain your words:"));
          (r.hits || []).forEach((x) => out.append(hitCard(Object.assign({}, x, { title: "" }), openPage)));
          if (!(r.hits || []).length) out.append(h("p", { class: "muted" }, "Not found."));
        } else {
          const x = await waitJob(r.job, (s) => { wait.textContent = s; });
          out.innerHTML = "";
          out.append(h("div", { class: "aimsg bot" }, md(x.answer)), h("p", { class: "hint" }, "Check the answer against the pages before acting on it. Pages that match your words:"));
          (x.hits || []).forEach((y) => out.append(hitCard(Object.assign({}, y, { title: "" }), openPage)));
        }
      } catch (e) { out.innerHTML = ""; out.append(h("p", { class: "red" }, e.message)); }
      finally { btn.disabled = false; }
    };
    btn.onclick = askNow;
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askNow(); } });
    box.append(h("div", { class: "bar", style: "align-items:flex-end" }, h("div", { class: "grow" }, ta), btn), out);
    setTimeout(() => ta.focus(), 50);
    return box;
  }

  async function pagesTab(d, start, word) {
    const box = h("div");
    let n = Math.max(1, start || 1);
    const txt = h("div", { class: "pgtext" });
    const label = h("b");
    const find = h("input", { type: "search", placeholder: "Mark a word on the page", value: word || "", style: "max-width:240px" });
    const draw = async () => {
      const r = await run("doc.page", { id: d.id, page: n });
      label.textContent = "Page " + r.page + " of " + r.pages;
      const w = find.value.trim();
      let html = esc(r.text || "(no text on this page" + (d.scanned ? " — the page is a scanned picture; open the original" : "") + ")");
      if (w.length > 1) html = html.replace(new RegExp("(" + esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
      txt.innerHTML = html;
      prev.disabled = n <= 1; next.disabled = n >= r.pages;
    };
    const prev = h("button", { class: "btn small", onclick: () => { n--; draw(); } }, "‹ Previous");
    const next = h("button", { class: "btn small", onclick: () => { n++; draw(); } }, "Next ›");
    const jump = h("input", { type: "number", min: 1, style: "width:80px", placeholder: "page", onchange: () => { n = Math.max(1, Number(jump.value) || 1); draw(); } });
    find.addEventListener("input", draw);
    box.append(h("div", { class: "bar" }, prev, label, next, jump, h("div", { class: "grow" }), find), txt);
    await draw();
    return box;
  }
})();
