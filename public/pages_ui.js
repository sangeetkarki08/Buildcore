/* BuildCore 2.8 — a cleaner, more modern look and easier navigation:
   menu search ("Find a screen"), recently used screens, a breadcrumb above every page, calmer tables and forms. */
(function () {
  "use strict";
  const css = document.createElement("style");
  css.id = "bco-ui-28";
  css.textContent = `
:root{--ink:#16212b;--muted:#5d6b75;--paper:#f2f5f8;--panel:#fff;--line:#dbe2e8;--line-soft:#edf1f4;--blue:#1769aa;--blue-deep:#0d3550;--blue-wash:#e7f0f8;
  --radius:10px;--shadow:0 1px 2px rgba(16,42,60,.06),0 4px 14px rgba(16,42,60,.05);
  --font:"Segoe UI Variable Text","Segoe UI","Noto Sans","Helvetica Neue",Arial,"BuildCore Sans",sans-serif}
body{font-size:14px;background:var(--paper);-webkit-font-smoothing:antialiased}
.shell{grid-template-columns:248px 1fr}
.side{background:linear-gradient(180deg,#0c2f47 0%,#0e3a57 55%,#0f4262 100%);padding:0 0 30px;box-shadow:inset -1px 0 0 rgba(255,255,255,.05)}
.brand{padding:18px 18px 14px;border-bottom:1px solid rgba(255,255,255,.08);margin-bottom:6px}
.brand b{font-size:18px;letter-spacing:.4px}.brand b:before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;background:#f0b43c;margin-right:8px;vertical-align:1px}
.brand span{display:block;margin-top:3px;color:#a9c4d6;font-size:12px;line-height:1.35}
.navfind{padding:8px 12px 6px}.navfind input{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);color:#fff;border-radius:8px;padding:7px 10px;font-size:13px}
.navfind input::placeholder{color:#9fbccd}.navfind input:focus{outline:none;border-color:#f0b43c;background:rgba(255,255,255,.12)}
.navresults{padding:2px 0 8px;border-bottom:1px solid rgba(255,255,255,.07)}.navresults a{display:block;margin:1px 10px;padding:6px 10px 6px 14px;border-radius:8px;color:#d8e6ef;text-decoration:none;font-size:13.5px}.navresults a:hover,.navresults a.hit{background:rgba(240,180,60,.18)}.navresults small{display:block;color:#8fb0c4;font-size:11px}.navresults .lbl{padding:6px 18px;color:#9fbccd;font-size:12px}\n.navrecent{padding:2px 0 6px;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:4px}
.navrecent .lbl{padding:4px 18px;font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:#7fa3ba}
.nav-group{width:100%;text-align:left;background:none;border:0;color:#9fbccd;font-size:11.5px;letter-spacing:.6px;text-transform:uppercase;font-weight:700;padding:10px 18px 5px;cursor:pointer;display:flex;align-items:center;gap:6px}
.nav-group:hover{color:#fff}
.nav a,.navrecent a{display:block;margin:1px 10px;padding:6px 10px 6px 14px;border-radius:8px;border-left:0;color:#d8e6ef;text-decoration:none;font-size:13.5px}
.nav a:hover,.navrecent a:hover{background:rgba(255,255,255,.08)}
.nav a.on{background:#1b6a98;color:#fff;box-shadow:inset 3px 0 0 #f0b43c}
.nav a.hit{background:rgba(240,180,60,.18)}
.top{padding:9px 22px;gap:10px;box-shadow:0 1px 0 var(--line),0 2px 10px rgba(16,42,60,.04);border-bottom:0;flex-wrap:wrap}
.top select,.top input{border-radius:8px}
.top .who{font-size:12.5px;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#projsel{max-width:240px;min-width:150px!important}.top label.f>span{display:none}.top .searchwrap{flex:1 1 160px;max-width:260px;min-width:130px}.top .searchwrap input{width:100%}
.top select.date-mode{min-width:0!important;max-width:122px!important;width:122px!important}.top .cochip{max-width:170px}.top{flex-wrap:nowrap}.top>*{flex-shrink:0}.top .searchwrap{flex-shrink:1!important;min-width:90px!important}.top label.f{flex-shrink:1}.top #projsel{min-width:110px!important}.livewrap .muted,.livewrap small{display:none}a.btn{text-decoration:none;color:inherit}.top .fysel{max-width:190px}
.page{padding:16px 26px 70px;max-width:1560px}
.crumb{font-size:12px;color:var(--muted);margin:2px 0 6px;display:flex;gap:6px;align-items:center}.crumb a{color:var(--muted);text-decoration:none}.crumb a:hover{color:var(--blue)}
.crumb span:before{content:"›";margin-right:6px;color:#aab6be}
.page h1{font-size:23px;font-weight:700;letter-spacing:-.2px}
.page .sub{font-size:13.5px;margin-bottom:16px}
.btn{border-radius:8px;padding:6px 13px;transition:background .12s,border-color .12s,box-shadow .12s;font-weight:500}
.btn:hover{border-color:#a9b8c2;box-shadow:0 1px 3px rgba(16,42,60,.08)}
.btn.primary{background:var(--blue);border-color:var(--blue)}.btn.primary:hover{background:#125a92;border-color:#125a92}
.btn.small{padding:3px 9px;border-radius:7px}
input,select,textarea{border-radius:8px;padding:6px 9px;border-color:#cfd8df;transition:border-color .12s,box-shadow .12s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px rgba(23,105,170,.15)}
label.f{font-size:12.5px;font-weight:500}
.panel{border-radius:12px;box-shadow:var(--shadow);border-color:var(--line);padding:16px}
.tablewrap{border-radius:12px;box-shadow:var(--shadow)}
th{background:#f4f7f9;color:#40505b;font-size:12px;text-transform:uppercase;letter-spacing:.35px;font-weight:700;border-bottom:1px solid var(--line)}
td{border-bottom:1px solid var(--line-soft)}
tbody tr:hover>td{background:#f6f9fc}
tr.click{cursor:pointer}
tfoot td{background:#f4f7f9;font-weight:700;border-top:1px solid var(--line)}
.tabs{gap:2px;border-bottom:1px solid var(--line);margin-bottom:14px}
.tabs button{padding:8px 14px;border-radius:8px 8px 0 0;color:var(--muted);font-weight:500;border-bottom:3px solid transparent}
.tabs button:hover{color:var(--ink);background:rgba(23,105,170,.05)}
.tabs button.on{color:var(--blue);border-bottom-color:var(--blue);font-weight:700}
.overlay{background:rgba(12,28,40,.45)}
.modal{border-radius:14px;box-shadow:0 24px 60px rgba(10,30,45,.28);overflow:hidden}
.modal header{padding:14px 18px;background:#fff}.modal header h3{font-size:17px;font-weight:700}
.modal .body{padding:16px 18px}
.modal footer{background:#f6f8fa;border-radius:0;padding:11px 18px}
.toast{border-radius:10px;padding:10px 16px;box-shadow:0 10px 30px rgba(0,0,0,.18)}
.tile{border-radius:12px;box-shadow:var(--shadow);border-left-width:5px}
.stamp{border-radius:999px;padding:0 9px;border-width:1px;font-weight:700;font-size:11.5px;text-transform:capitalize}
h2.sec{font-size:16px;border-bottom:1px solid var(--line)}
.kv dt{font-weight:500}
@media (max-width:900px){.shell{grid-template-columns:1fr}.page{padding:12px 14px 60px}}
`;
  document.head.append(css);

  const RKEY = "bco_recent_pages";
  const recent = () => { try { return JSON.parse(localStorage.getItem(RKEY) || "[]"); } catch (e) { return []; } };
  const labelOf = (path) => {
    for (const [group, , items] of (typeof MENU !== "undefined" ? MENU : [])) {
      const it = items.find(([p]) => p === path);
      if (it) return { group, label: it[1] };
    }
    return null;
  };
  function remember() {
    const path = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "";
    if (!path || !labelOf(path)) return;
    const list = recent().filter((p) => p !== path);
    list.unshift(path);
    try { localStorage.setItem(RKEY, JSON.stringify(list.slice(0, 5))); } catch (e) { /* ignore */ }
  }
  function crumb() {
    const page = document.querySelector("#page");
    if (!page) return;
    const path = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "";
    const l = labelOf(path);
    const old = page.querySelector(":scope > .crumb");
    if (old) old.remove();
    if (!l) return;
    const c = h("div", { class: "crumb" }, h("a", { href: "#/home" }, "Modules"), h("span", {}, h("a", { href: "#/mod?m=" + encodeURIComponent(l.group) }, window.bcoModTitle ? window.bcoModTitle(l.group) : l.group)), h("span", {}, l.label));
    page.prepend(c);
  }
  function decorateSide(side) {
    if (!side || side._bco28) return;
    side._bco28 = true;
    const nav = side.querySelector(".nav");
    if (!nav) return;
    const inp = h("input", { type: "search", placeholder: "Find a screen…  (Ctrl+K)", "aria-label": "Find a screen" });
    const find = h("div", { class: "navfind" }, inp);
    const rec = h("div", { class: "navrecent" });
    const paintRecent = () => {
      rec.innerHTML = "";
      const list = recent().map((p) => [p, labelOf(p)]).filter(([p, l]) => l && typeof PAGES !== "undefined" && PAGES[p]).slice(0, 4);
      if (!list.length) { rec.hidden = true; return; }
      rec.hidden = false;
      rec.append(h("div", { class: "lbl" }, "Recent"), ...list.map(([p, l]) => h("a", { href: "#/" + p }, l.label)));
    };
    paintRecent();
    side.insertBefore(find, nav);
    side.insertBefore(rec, nav);
    /* search every screen of every module, not only the module that is open */
    const res = h("div", { class: "navresults", hidden: true });
    side.insertBefore(res, rec.nextSibling);
    const all = () => {
      const out = [];
      (typeof MENU !== "undefined" ? MENU : []).forEach(([group, module, items]) => {
        if (module && typeof can === "function" && !can(module, "view")) return;
        items.forEach(([path, label, mod]) => { if ((!mod || can(mod, "view")) && PAGES[path]) out.push({ path, label, group }); });
      });
      return out;
    };
    inp.addEventListener("input", () => {
      const t = inp.value.trim().toLowerCase();
      res.innerHTML = "";
      const curNav = side.querySelector(".nav");
      if (!t) { res.hidden = true; if (curNav) curNav.hidden = false; rec.hidden = !rec.children.length; return; }
      const hits = all().filter((x) => (x.label + " " + x.group).toLowerCase().includes(t)).slice(0, 14);
      res.append(...(hits.length ? hits.map((x, i) => h("a", { href: "#/" + x.path, class: i === 0 ? "hit" : "", onclick: () => { inp.value = ""; inp.dispatchEvent(new Event("input")); } }, x.label, h("small", {}, x.group)))
        : [h("div", { class: "lbl" }, "No screen matches")]));
      res.hidden = false; rec.hidden = true;
      if (curNav) curNav.hidden = true;
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const a = res.querySelector("a"); if (a) { location.hash = a.getAttribute("href"); inp.value = ""; inp.dispatchEvent(new Event("input")); inp.blur(); } }
      if (e.key === "Escape") { inp.value = ""; inp.dispatchEvent(new Event("input")); inp.blur(); e.stopPropagation(); }
    });
    window.addEventListener("hashchange", () => setTimeout(paintRecent, 50));
  }
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K")) {
      const i = document.querySelector(".navfind input");
      if (i) { e.preventDefault(); e.stopPropagation(); i.focus(); i.select(); }
    }
  }, true);
  const mo = new MutationObserver(() => {
    const side = document.querySelector(".side");
    if (side && !side._bco28) decorateSide(side);
    const page = document.querySelector("#page");
    if (page && page.firstElementChild && !page.querySelector(":scope > .crumb") && page.querySelector("h1")) crumb();
  });
  const startObs = () => { const app = document.querySelector("#app") || document.body; mo.observe(app, { childList: true, subtree: true }); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startObs); else startObs();
  window.addEventListener("hashchange", remember);
  setTimeout(remember, 1500);
})();
