/* BuildCore 2.17 — modern screen and power tools, on top of every module.
   1. Appearance: light, dark or follow Windows; six accent colours; comfortable or compact rows; striped rows.
   2. Command palette (Ctrl+K, Ctrl+Shift+P, Ctrl+F): every screen, every "+ New" entry, commands and records in one box.
   3. Pinned screens: star any screen and it stays at the top of the side menu and the palette.
   4. Smarter lists: click a column heading to sort (remembered per list), choose the columns to show, copy for Excel.
   5. A calmer top bar, a hideable side menu (Ctrl+B), a loading line while BuildCore works, clearer messages,
      dashboard figures with icons and a cost-against-revenue chart.
   Nothing here changes data or replaces a screen; every part steps aside if the screen it decorates is missing. */
(function () {
  "use strict";
  const VER = "2.17.0";
  const LS = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSset = (k, v) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private window */ } };
  const LSjson = (k, d) => { try { return JSON.parse(LS(k, "") || "null") || d; } catch (e) { return d; } };
  const root = document.documentElement;

  /* ───────────────────────── icons ───────────────────────── */
  const ICON = {
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    screen: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    doc: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5v.5"/>',
    truck: '<path d="M2 6h11v10H2zM13 10h4l4 4v2h-8"/><circle cx="6" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/>',
    cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.5 12h11L21 7H6"/>',
    up: '<path d="M7 17L17 7M9 7h8v8"/>',
    down: '<path d="M17 7L7 17M15 17H7V9"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-2.5z"/>',
    stop: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    coins: '<ellipse cx="9" cy="6" rx="6" ry="2.5"/><path d="M3 6v5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V6"/><path d="M9 16.5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-5c0-1.4-2.7-2.5-6-2.5"/>',
    palette: '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="10" r="1.2"/><circle cx="12" cy="7.5" r="1.2"/><circle cx="16" cy="10" r="1.2"/><path d="M12 21a3 3 0 0 1 0-6h2a3 3 0 0 0 3-3"/>',
    columns: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
    copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    arrowup: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    gift: '<rect x="3" y="8" width="18" height="13" rx="1.5"/><path d="M12 8v13M3 12h18M12 8c-2-4-6-4-6-1.5S9 8 12 8zm0 0c2-4 6-4 6-1.5S15 8 12 8z"/>',
  };
  const svg = (name, size) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
    s.setAttribute("stroke-width", "1.9"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
    s.setAttribute("aria-hidden", "true"); s.setAttribute("width", size || 16); s.setAttribute("height", size || 16);
    s.innerHTML = ICON[name] || ICON.info;
    return s;
  };
  const el = (tag, attrs, ...kids) => {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v == null || v === false) return;
      if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "class") e.className = v;
      else e.setAttribute(k, v === true ? "" : v);
    });
    kids.flat(Infinity).forEach((x) => { if (x != null && x !== false) e.append(x instanceof Node ? x : document.createTextNode(String(x))); });
    return e;
  };

  /* ───────────────────────── appearance ───────────────────────── */
  const ACCENTS = {
    blue: { n: "Blue", c: "#1769aa", d: "#0d3550", l: "#5aa9e6", rgb: "23,105,170" },
    indigo: { n: "Indigo", c: "#4f46e5", d: "#272163", l: "#8b85ff", rgb: "79,70,229" },
    teal: { n: "Teal", c: "#0f7b74", d: "#073b38", l: "#3cc7bb", rgb: "15,123,116" },
    green: { n: "Green", c: "#2b7a3f", d: "#123820", l: "#5fc27a", rgb: "43,122,63" },
    violet: { n: "Violet", c: "#7c3aed", d: "#34186a", l: "#b38cff", rgb: "124,58,237" },
    slate: { n: "Slate", c: "#3b4a5a", d: "#1b232c", l: "#94a8bd", rgb: "59,74,90" },
  };
  const P = {
    theme: () => LS("bco_theme", "light"),            // light | dark | auto
    accent: () => (ACCENTS[LS("bco_accent", "blue")] ? LS("bco_accent", "blue") : "blue"),
    density: () => LS("bco_density", "comfortable"),  // comfortable | compact
    zebra: () => LS("bco_zebra", "0") === "1",
    side: () => LS("bco_side_hidden", "0") === "1",
    palette: () => LS("bco_palette", "1") === "1",
  };
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => P.theme() === "dark" || (P.theme() === "auto" && dark.matches);
  function applyLook() {
    const a = ACCENTS[P.accent()];
    root.dataset.bcoTheme = isDark() ? "dark" : "light";
    root.dataset.bcoAccent = P.accent();
    root.dataset.bcoDensity = P.density();
    root.classList.toggle("bco-zebra", P.zebra());
    root.classList.toggle("bco-noside", P.side());
    root.style.setProperty("--acc", isDark() ? a.l : a.c);
    root.style.setProperty("--acc-strong", a.c);
    root.style.setProperty("--acc-deep", a.d);
    root.style.setProperty("--acc-rgb", a.rgb);
    root.style.colorScheme = isDark() ? "dark" : "light";
    document.querySelectorAll(".bco-themebtn").forEach((b) => { b.innerHTML = ""; b.append(svg(isDark() ? "sun" : "moon", 17)); b.title = isDark() ? "Light screen (Ctrl+Shift+L)" : "Dark screen (Ctrl+Shift+L)"; });
  }
  const setPref = (k, v) => { LSset(k, v); applyLook(); };
  try { dark.addEventListener("change", applyLook); } catch (e) { /* old engine */ }
  const toggleDark = () => setPref("bco_theme", isDark() ? "light" : "dark");
  const toggleSide = () => setPref("bco_side_hidden", P.side() ? "0" : "1");

  /* ───────────────────────── stylesheet ───────────────────────── */
  const css = el("style", { id: "bco-ui-217" });
  css.textContent = `
:root{--acc:#1769aa;--acc-strong:#1769aa;--acc-deep:#0d3550;--acc-rgb:23,105,170;--blue:var(--acc-strong);--blue-deep:var(--acc-deep);
  --blue-wash:rgba(var(--acc-rgb),.09);--ring:0 0 0 3px rgba(var(--acc-rgb),.22);--radius:10px;--r-lg:14px;
  --shadow:0 1px 2px rgba(16,32,48,.05),0 2px 8px rgba(16,32,48,.04);--shadow-lg:0 18px 50px rgba(10,25,40,.22);
  --top-bg:rgba(255,255,255,.82);--side-bg:linear-gradient(180deg,var(--acc-deep) 0%,color-mix(in srgb,var(--acc-deep) 82%,var(--acc-strong)) 100%);
  --th-bg:#f5f7fa;--th-ink:#47566a;--hover:rgba(var(--acc-rgb),.05);--zebra:rgba(16,32,48,.022);--ctl-h:34px;--cell-y:8px;--cell-x:11px}
html[data-bco-density=compact]{--ctl-h:30px;--cell-y:4px;--cell-x:8px}
html[data-bco-density=compact] body{font-size:13px}
html[data-bco-theme=dark]{--ink:#e4ebf2;--muted:#94a3b3;--paper:#0d141c;--panel:#141e29;--line:#273444;--line-soft:#1d2935;
  --blue-wash:rgba(var(--acc-rgb),.18);--amber-wash:#382c12;--green-wash:#12301d;--red-wash:#3a1b18;--amber:#f0b43c;--green:#4cc38a;--red:#f2786c;
  --top-bg:rgba(16,24,33,.82);--side-bg:linear-gradient(180deg,#0a1017 0%,#0e1620 100%);--th-bg:#18232f;--th-ink:#9fb0c1;--hover:rgba(255,255,255,.035);--zebra:rgba(255,255,255,.02);
  --shadow:0 1px 2px rgba(0,0,0,.35);--shadow-lg:0 22px 60px rgba(0,0,0,.55)}
html[data-bco-theme=dark] .page h1,html[data-bco-theme=dark] h2,html[data-bco-theme=dark] h3{color:#f1f5f9}
body{background:var(--paper);color:var(--ink);text-rendering:optimizeLegibility}
::selection{background:rgba(var(--acc-rgb),.25)}
*{scrollbar-width:thin;scrollbar-color:rgba(120,135,150,.45) transparent}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:rgba(120,135,150,.38);border-radius:10px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background-color:rgba(120,135,150,.6)}::-webkit-scrollbar-track{background:transparent}
a{color:var(--acc)}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}

/* shell */
.side{background:var(--side-bg)!important}
.nav a.on{background:rgba(255,255,255,.12)!important;box-shadow:inset 3px 0 0 #f0b43c!important}
html.bco-noside .shell{grid-template-columns:1fr!important}
html.bco-noside .side{display:none}
html.bco-noside .side.open{display:block}
.top{background:var(--top-bg)!important;-webkit-backdrop-filter:saturate(1.6) blur(10px);backdrop-filter:saturate(1.6) blur(10px);border-bottom:1px solid var(--line)!important;box-shadow:none!important;min-height:56px}
.top .searchwrap{display:none!important}
.menu-btn{display:none!important}
.top{gap:8px!important;padding:9px 18px!important}
.top #projsel{max-width:190px!important}
.top .cochip{max-width:160px!important}
.top .fysel{max-width:170px!important}
.top select.date-mode{max-width:120px!important}
.livewrap b+*{display:none}
.top select,.top .btn,.top input{height:var(--ctl-h)}
.bco-iconbtn{display:inline-flex;align-items:center;justify-content:center;width:var(--ctl-h);height:var(--ctl-h);border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--muted);cursor:pointer;flex:none}
.bco-iconbtn:hover{color:var(--ink);border-color:color-mix(in srgb,var(--line) 50%,var(--acc))}
.bcp-trigger{display:flex;align-items:center;gap:8px;flex:1 1 240px;min-width:190px;max-width:440px;height:var(--ctl-h);padding:0 8px 0 11px;border:1px solid var(--line);border-radius:10px;
  background:var(--panel);color:var(--muted);cursor:text;font-size:13.5px;text-align:left;flex-shrink:1!important}
.bcp-trigger:hover{border-color:color-mix(in srgb,var(--line) 40%,var(--acc));color:var(--ink)}
.bcp-trigger span{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bcp-trigger kbd,.bcp kbd{font:600 11px/1 ui-monospace,Consolas,monospace;padding:4px 6px;border-radius:6px;border:1px solid var(--line);background:var(--paper);color:var(--muted)}
.helpbtn{width:var(--ctl-h)!important;height:var(--ctl-h)!important;border-radius:9px!important}
.usermenu .avatar{background:linear-gradient(135deg,var(--acc-strong),var(--acc-deep))!important;box-shadow:0 0 0 2px var(--panel),0 0 0 3px rgba(var(--acc-rgb),.35)}
.usermenu-list{background:var(--panel)!important;border-color:var(--line)!important;box-shadow:var(--shadow-lg)!important}
.usermenu-list button{color:var(--ink)}.usermenu-list button:hover{background:var(--blue-wash)!important}
.usermenu-list .um-sep{height:1px;background:var(--line);margin:4px 6px}
@media (max-width:1180px){.top .cochip{max-width:120px!important}.top .fysel{max-width:150px!important}.top select.date-mode{max-width:92px!important}.livewrap{display:none!important}}
@media (max-width:1380px){.top select.date-mode{max-width:100px!important}.top .cochip{max-width:130px!important}.top #projsel{max-width:170px!important}}
@media (max-width:860px){.top{flex-wrap:wrap!important;row-gap:8px!important;padding:8px 12px!important}.top>*{flex-shrink:1!important}.top #projsel{max-width:46vw!important}.top .cochip{max-width:40vw!important}
  .tiles{grid-template-columns:repeat(2,minmax(0,1fr))!important}.tile b{font-size:18px!important;white-space:normal;overflow-wrap:anywhere}.bcp-foot{display:none}.page h1{font-size:21px}
  .menu-btn{display:inline-flex!important}.bcp-trigger span,.bcp-trigger kbd{display:none}.bcp-trigger{flex:0 0 var(--ctl-h);min-width:0;padding:0;justify-content:center}.bco-sidetoggle{display:none!important}}

/* pages */
.page{animation:bco-in .18s ease-out}
@keyframes bco-in{from{opacity:.0;transform:translateY(3px)}to{opacity:1;transform:none}}
.page h1{display:flex;align-items:center;gap:10px;font-size:24px;letter-spacing:-.3px}
.bco-pin{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;border:1px solid transparent;background:none;color:var(--muted);cursor:pointer;flex:none;opacity:.55;transition:opacity .12s,color .12s,background .12s}
.page h1:hover .bco-pin,.bco-pin.on,.bco-pin:focus-visible{opacity:1}.bco-pin:hover{background:var(--blue-wash);color:var(--ink)}
.bco-pin.on{color:#e3a008}.bco-pin.on svg{fill:#f0b43c}
.panel,.tablewrap,.tile,.hcard,.modcard{background:var(--panel)!important;border-color:var(--line)!important;border-radius:var(--r-lg)!important}
.panel{box-shadow:var(--shadow)}
.btn{height:auto;min-height:var(--ctl-h);display:inline-flex;align-items:center;justify-content:center;gap:6px;background:var(--panel);color:var(--ink);border-color:var(--line);border-radius:9px;font-weight:550}
.btn.small{min-height:calc(var(--ctl-h) - 8px)}
.btn.primary{background:linear-gradient(180deg,color-mix(in srgb,var(--acc-strong) 88%,#fff),var(--acc-strong))!important;border-color:var(--acc-strong)!important;color:#fff!important;box-shadow:0 1px 2px rgba(var(--acc-rgb),.35),inset 0 1px 0 rgba(255,255,255,.18)}
.btn.primary:hover{filter:brightness(1.06)}
.btn.warn{color:var(--red);border-color:color-mix(in srgb,var(--red) 40%,var(--line))}
input,select,textarea{background:var(--panel);color:var(--ink);border-color:var(--line)}
input:not([type=checkbox]):not([type=radio]):not([type=file]),select{min-height:var(--ctl-h)}
input:focus,select:focus,textarea:focus{border-color:var(--acc)!important;box-shadow:var(--ring)!important;outline:none}
input[readonly]{background:var(--paper)}
input::placeholder,textarea::placeholder{color:color-mix(in srgb,var(--muted) 75%,transparent)}
label.f{color:var(--muted)}
th{background:var(--th-bg)!important;color:var(--th-ink)!important;border-bottom:1px solid var(--line)!important;padding:var(--cell-y) var(--cell-x)!important}
td{padding:var(--cell-y) var(--cell-x)!important;border-bottom-color:var(--line-soft)!important}
.lines td{padding:3px 4px!important}
tbody tr:hover>td{background:var(--hover)!important}
html.bco-zebra tbody tr:nth-child(even)>td{background:var(--zebra)}
html.bco-zebra tbody tr:nth-child(even):hover>td{background:var(--hover)!important}
tfoot td{background:var(--th-bg)!important}
.tablewrap{box-shadow:var(--shadow)}
.tabs{border-bottom-color:var(--line)!important}.tabs button{color:var(--muted)}.tabs button.on{color:var(--acc)!important;border-bottom-color:var(--acc)!important}
.modal{background:var(--panel)!important;color:var(--ink);border:1px solid var(--line);border-radius:16px!important;box-shadow:var(--shadow-lg)!important;animation:bco-pop .16s ease-out}
@keyframes bco-pop{from{opacity:0;transform:translateY(8px) scale(.985)}to{opacity:1;transform:none}}
.modal header{background:var(--panel)!important;border-bottom-color:var(--line)!important}
.modal footer{background:color-mix(in srgb,var(--panel) 92%,var(--paper))!important;border-top-color:var(--line)!important}
.overlay{background:rgba(8,18,28,.48)!important;-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px)}
.stamp{background:color-mix(in srgb,currentColor 9%,transparent)}
.chip,.flow a{background:var(--panel)!important;border-color:var(--line)!important;color:var(--ink)!important}
.chip.on{background:var(--acc-strong)!important;color:#fff!important;border-color:var(--acc-strong)!important}
.flow{gap:6px!important}.flow a{border-radius:999px!important;padding:3px 11px!important}.flow a:hover{border-color:var(--acc)!important;color:var(--acc)!important}
.crumb a:hover{color:var(--acc)!important}

/* dashboard figures */
.tiles{gap:12px!important}
.tile{position:relative;border:1px solid var(--line)!important;border-left:1px solid var(--line)!important;padding:14px 16px 13px 16px!important;box-shadow:var(--shadow);transition:transform .12s,box-shadow .12s,border-color .12s;overflow:hidden}
.tile:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--acc)}
.tile.warn:before{background:var(--amber)}.tile.bad:before{background:var(--red)}
.tile:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(16,32,48,.10);border-color:color-mix(in srgb,var(--line) 50%,var(--acc))!important}
.tile{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px}
.tile>span:not(.bco-ti){order:1;flex:1;min-width:0}
.tile b{order:3;width:100%;font-size:22px!important;letter-spacing:-.4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile small{order:4;width:100%}
.tile .bco-ti{order:2;width:30px;height:30px;border-radius:9px;display:flex;align-items:center;justify-content:center;background:var(--blue-wash);color:var(--acc);flex:none}
.tile.warn .bco-ti{background:var(--amber-wash);color:#b7791f}.tile.bad .bco-ti{background:var(--red-wash);color:var(--red)}
html[data-bco-theme=dark] .tile.warn .bco-ti{color:var(--amber)}
.bco-chart{width:100%;height:auto;display:block}.bco-chart text{fill:var(--muted);font-size:10.5px}.bco-chart .gl{stroke:var(--line-soft)}
.bco-chart rect.c{fill:var(--acc)}.bco-chart rect.r{fill:var(--green);opacity:.85}.bco-chart rect:hover{opacity:.75}
.bco-legend{display:flex;gap:16px;font-size:12px;color:var(--muted);margin:6px 0 2px}.bco-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}

/* smart lists */
.klist th.bco-sortable{cursor:pointer;user-select:none}
.klist th.bco-sortable:hover{color:var(--ink)!important}
.klist th .bco-sort{display:none;width:10px;margin-left:4px;opacity:.45;font-size:10px}
.klist th.bco-sortable:hover .bco-sort,.klist th.bco-sortable:focus-visible .bco-sort{display:inline-block}
.klist th.bco-asc .bco-sort,.klist th.bco-desc .bco-sort{display:inline-block;opacity:1;color:var(--acc)}
.bco-colpop{position:fixed;z-index:130;background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow-lg);padding:8px;min-width:220px;max-height:60vh;overflow:auto}
.bco-colpop label{display:flex;gap:8px;align-items:center;padding:5px 8px;border-radius:7px;font-size:13px;cursor:pointer;color:var(--ink)}
.bco-colpop label:hover{background:var(--blue-wash)}.bco-colpop input{width:auto;min-height:0!important}
.bco-colpop .ft{display:flex;justify-content:space-between;gap:8px;border-top:1px solid var(--line);margin-top:6px;padding-top:6px}

/* side menu: pinned screens */
.navpinned{padding:2px 0 6px;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:4px}
.navpinned .lbl{padding:6px 18px 4px;font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:#f0c46a;display:flex;align-items:center;gap:6px}
.navpinned a{display:flex;align-items:center;gap:8px;margin:1px 10px;padding:6px 10px 6px 14px;border-radius:8px;color:#e3edf4;text-decoration:none;font-size:13.5px}
.navpinned a:hover{background:rgba(255,255,255,.08)}
.navpinned a svg{color:#f0b43c;fill:#f0b43c;flex:none}

/* loading line, back to top, toasts */
#bco-load{position:fixed;left:0;top:0;height:3px;width:0;z-index:300;background:linear-gradient(90deg,var(--acc),#f0b43c);box-shadow:0 0 8px rgba(var(--acc-rgb),.6);transition:width .3s ease,opacity .3s ease;opacity:0;pointer-events:none}
#bco-load.on{opacity:1}
#bco-top{position:fixed;right:18px;bottom:76px;z-index:80;width:38px;height:38px;border-radius:50%;border:1px solid var(--line);background:var(--panel);color:var(--ink);box-shadow:var(--shadow-lg);cursor:pointer;display:flex;align-items:center;justify-content:center}
#bco-top[hidden]{display:none}
.toast{display:flex!important;align-items:flex-start;gap:10px;padding:11px 12px 11px 14px!important;border-radius:12px!important;background:#18222d!important;color:#f1f5f9!important;border:1px solid rgba(255,255,255,.08);box-shadow:0 14px 40px rgba(0,0,0,.28)!important;animation:bco-toast .2s ease-out;min-width:240px}
.toast .ti{flex:none;margin-top:1px;color:#93c5fd}.toast.ok .ti{color:#4ade80}.toast.err .ti{color:#fca5a5}
.toast.ok{background:#14261c!important}.toast.err{background:#2c1513!important}
.toast .tm{flex:1}.toast .tx{flex:none;border:0;background:none;color:inherit;opacity:.6;cursor:pointer;padding:0 0 0 6px}.toast .tx:hover{opacity:1}
@keyframes bco-toast{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}

/* command palette */
.bcp-wrap{position:fixed;inset:0;z-index:400;background:rgba(8,18,28,.45);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);display:flex;justify-content:center;align-items:flex-start;padding:11vh 14px 14px}
.bcp{width:min(680px,100%);background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow-lg);overflow:hidden;display:flex;flex-direction:column;max-height:72vh;animation:bco-pop .14s ease-out}
.bcp-in{display:flex;align-items:center;gap:10px;padding:13px 16px;border-bottom:1px solid var(--line);color:var(--muted)}
.bcp-in input{border:0!important;box-shadow:none!important;background:none!important;font-size:16px;padding:4px 0;min-height:0!important;color:var(--ink)}
.bcp-list{overflow-y:auto;padding:6px}
.bcp-g{padding:10px 10px 4px;font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--muted)}
.bcp-i{display:flex;align-items:center;gap:11px;padding:8px 10px;border-radius:10px;cursor:pointer;color:var(--ink);text-decoration:none}
.bcp-i .ic{flex:none;width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:var(--paper);color:var(--muted);border:1px solid var(--line-soft)}
.bcp-i .tx{flex:1;min-width:0}.bcp-i .tx b{display:block;font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bcp-i .tx small{display:block;color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bcp-i mark{background:none;color:var(--acc);font-weight:700}
.bcp-i.on{background:var(--blue-wash)}.bcp-i.on .ic{background:var(--acc-strong);color:#fff;border-color:transparent}
.bcp-i .k{flex:none;font-size:11px;color:var(--muted)}
.bcp-empty{padding:26px 16px;text-align:center;color:var(--muted)}
.bcp-foot{display:flex;gap:14px;flex-wrap:wrap;padding:8px 14px;border-top:1px solid var(--line);font-size:11.5px;color:var(--muted);background:color-mix(in srgb,var(--panel) 92%,var(--paper))}
.bcp-foot span{display:inline-flex;gap:5px;align-items:center}

/* appearance dialog and what's new */
.bco-appear .row{display:grid;grid-template-columns:150px 1fr;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line-soft)}
.bco-appear .row:last-child{border-bottom:0}.bco-appear .row>b{font-weight:600;font-size:13.5px}
.bco-seg{display:inline-flex;border:1px solid var(--line);border-radius:10px;padding:3px;gap:3px;background:var(--paper);flex-wrap:wrap}
.bco-seg button{border:0;background:none;color:var(--muted);padding:6px 12px;border-radius:7px;cursor:pointer;font-weight:550;display:inline-flex;gap:6px;align-items:center}
.bco-seg button.on{background:var(--panel);color:var(--ink);box-shadow:var(--shadow)}
.bco-sw{display:flex;gap:10px;flex-wrap:wrap}
.bco-sw button{width:30px;height:30px;border-radius:50%;border:2px solid var(--panel);cursor:pointer;box-shadow:0 0 0 1px var(--line)}
.bco-sw button.on{box-shadow:0 0 0 2px var(--ink)}
.bco-new ul{margin:6px 0 0 0;padding:0;list-style:none}.bco-new li{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--line-soft)}
.bco-new li .ic{flex:none;width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;background:var(--blue-wash);color:var(--acc)}
.bco-new li b{display:block}.bco-new li span{color:var(--muted);font-size:13px}

/* dark screen: colours the older modules wrote straight into their own styles */
html[data-bco-theme=dark] .modal header,html[data-bco-theme=dark] .login,html[data-bco-theme=dark] .way,html[data-bco-theme=dark] .cbmenu,html[data-bco-theme=dark] .searchpanel,
html[data-bco-theme=dark] .qamenu,html[data-bco-theme=dark] .kcalc,html[data-bco-theme=dark] .aimsg.bot,html[data-bco-theme=dark] .topic,html[data-bco-theme=dark] .cop-ex button,
html[data-bco-theme=dark] .aichips button,html[data-bco-theme=dark] .quick .btn,html[data-bco-theme=dark] .helpbtn,html[data-bco-theme=dark] .cf-grid td input,html[data-bco-theme=dark] .cf-grid td select{background:var(--panel)!important;color:var(--ink)!important;border-color:var(--line)!important}
html[data-bco-theme=dark] .cbfoot,html[data-bco-theme=dark] .searchpanel .sgroup,html[data-bco-theme=dark] .searchpanel .sfoot,html[data-bco-theme=dark] tr.wbsrow td,
html[data-bco-theme=dark] .locgroup td,html[data-bco-theme=dark] .locsub td,html[data-bco-theme=dark] .feed-row i,html[data-bco-theme=dark] .kchip,html[data-bco-theme=dark] .cop-sql,
html[data-bco-theme=dark] .pgtext,html[data-bco-theme=dark] kbd.k,html[data-bco-theme=dark] .scwarn,html[data-bco-theme=dark] .fybadge,html[data-bco-theme=dark] .cbar .trk,
html[data-bco-theme=dark] table.la td.d.we,html[data-bco-theme=dark] table.la th.d.we{background:#1b2733!important;color:var(--ink)!important;border-color:var(--line)!important}
html[data-bco-theme=dark] .cbopt b,html[data-bco-theme=dark] .pgtext mark,html[data-bco-theme=dark] .hit{background:rgba(240,180,60,.25)!important;color:#ffe2a8!important}
html[data-bco-theme=dark] .klist tbody tr.kf>td{background:rgba(240,180,60,.16)!important}
html[data-bco-theme=dark] .klist tbody tr.ks>td,html[data-bco-theme=dark] .klist tbody tr.ks.kf>td{background:rgba(var(--acc-rgb),.24)!important}
html[data-bco-theme=dark] .kbulk{background:#3a2f12!important;border-color:#6b5420!important;color:#ffe2a8}
html[data-bco-theme=dark] .kvlist a.on,html[data-bco-theme=dark] .kvlist a:hover,html[data-bco-theme=dark] .absrow:hover{background:var(--blue-wash)!important}
html[data-bco-theme=dark] tr.flag td{background:var(--amber-wash)!important}html[data-bco-theme=dark] tr.bad td{background:var(--red-wash)!important}
html[data-bco-theme=dark] select.ckcell.r-none{background:var(--panel)}
html[data-bco-theme=dark] .gantt,html[data-bco-theme=dark] .pbar{background:#22303d}
html[data-bco-theme=dark] .kbd,html[data-bco-theme=dark] .drill{color:#9cc8f0}
html[data-bco-theme=dark] .drill{border-bottom-color:#4b6a86}
html[data-bco-theme=dark] .who-chip,html[data-bco-theme=dark] .tag{background:var(--blue-wash);color:var(--ink)}
html[data-bco-theme=dark] [style*="background:#fff;"],html[data-bco-theme=dark] [style*="background:#fff\\""],html[data-bco-theme=dark] [style*="background: #fff"],
html[data-bco-theme=dark] [style*="background:#ffffff"],html[data-bco-theme=dark] [style*="background:white"],html[data-bco-theme=dark] [style*="background:#fafcfd"],
html[data-bco-theme=dark] [style*="background:#f7f9fa"],html[data-bco-theme=dark] [style*="background:#f4f7f9"],html[data-bco-theme=dark] [style*="background:#f2f4f7"],
html[data-bco-theme=dark] [style*="background:#eef3f6"],html[data-bco-theme=dark] [style*="background:#f9fafb"],html[data-bco-theme=dark] [style*="background:#f6f8fa"]{background:var(--panel)!important;color:var(--ink)!important}
html[data-bco-theme=dark] [style*="background:#fff4cc"],html[data-bco-theme=dark] [style*="background:#fffaeb"],html[data-bco-theme=dark] [style*="background:#fff9e6"],html[data-bco-theme=dark] [style*="background:#fdf3dd"]{background:var(--amber-wash)!important;color:#ffe2a8!important}
html[data-bco-theme=dark] [style*="background:#fdeceb"],html[data-bco-theme=dark] [style*="background:#fbe9e6"]{background:var(--red-wash)!important;color:#ffc9c2!important}
html[data-bco-theme=dark] [style*="background:#e3f1e8"],html[data-bco-theme=dark] [style*="background:#e9f7ef"]{background:var(--green-wash)!important;color:#bdf0d0!important}
html[data-bco-theme=dark] [style*="background:#eef4ff"],html[data-bco-theme=dark] [style*="background:#f5f9ff"],html[data-bco-theme=dark] [style*="background:#e8f0f7"],html[data-bco-theme=dark] [style*="background:#e6eff5"],html[data-bco-theme=dark] [style*="background:#eef3f8"],html[data-bco-theme=dark] [style*="background:#eef2f6"]{background:var(--blue-wash)!important;color:var(--ink)!important}
html[data-bco-theme=dark] [style*="color:#111"],html[data-bco-theme=dark] [style*="color:#222"],html[data-bco-theme=dark] [style*="color:#333"]{color:var(--ink)!important}
html[data-bco-theme=dark] .dprdoc,html[data-bco-theme=dark] .dprdoc *{color-scheme:light}
html[data-bco-theme=dark] img{filter:none}
html[data-bco-theme=dark] .modcard .foot i{color:color-mix(in srgb,var(--mc,#94a3b8) 55%,#fff)!important}
@media print{html[data-bco-theme=dark]{--ink:#111;--muted:#555;--paper:#fff;--panel:#fff;--line:#ccc;--line-soft:#ddd;--th-bg:#f2f2f2;--th-ink:#333}
  .bcp-trigger,.bco-iconbtn,.bco-pin,#bco-top,#bco-load,.bco-colbtn{display:none!important}}
@media (prefers-reduced-motion:reduce){.page,.modal,.bcp,.toast{animation:none!important}.tile{transition:none!important}}
`;
  document.head.append(css);
  applyLook();

  /* ───────────────────────── helpers that know the app ───────────────────────── */
  const ready = () => typeof S !== "undefined" && S.user && typeof MENU !== "undefined";
  const curPath = () => (location.hash.replace(/^#\/?/, "").split("?")[0]) || "";
  const modTitle = (g) => (window.bcoModTitle ? window.bcoModTitle(g) : g);
  function screens() {
    const out = [];
    if (typeof MENU === "undefined") return out;
    MENU.forEach(([group, module, items]) => {
      if (module && typeof can === "function" && !can(module, "view")) return;
      items.forEach(([path, label, mod]) => {
        if ((!mod || can(mod, "view")) && typeof PAGES !== "undefined" && PAGES[path]) out.push({ path, label, group: modTitle(group) });
      });
    });
    return out;
  }
  const screenOf = (path) => screens().find((x) => x.path === path);
  const pins = () => LSjson("bco_pins", []).filter((p) => typeof p === "string");
  const isPinned = (p) => pins().includes(p);
  function togglePin(path) {
    path = path || curPath();
    const s = screenOf(path);
    if (!s) { toastSafe("This screen cannot be pinned.", "err"); return; }
    const list = pins().filter((x) => x !== path);
    if (!isPinned(path)) list.unshift(path);
    LSset("bco_pins", JSON.stringify(list.slice(0, 12)));
    toastSafe(isPinned(path) ? "Pinned “" + s.label + "” to the side menu" : "Removed “" + s.label + "” from pinned screens", "ok");
    paintPins(); paintStar();
  }
  const toastSafe = (m, k) => { try { toast(m, k); } catch (e) { /* toasts not ready */ } };
  const clickTop = (text) => { const b = [...document.querySelectorAll(".top button")].find((x) => x.textContent.trim() === text); if (b) { b.click(); return true; } return false; };

  /* ───────────────────────── command palette ───────────────────────── */
  function fuzzy(text, q) {
    if (!q) return { s: 1, m: null };
    const t = text.toLowerCase(); q = q.toLowerCase();
    const at = t.indexOf(q);
    if (at >= 0) return { s: 1000 - at * 3 - (t.length - q.length) * 0.2 + (at === 0 || t[at - 1] === " " ? 200 : 0), m: [[at, at + q.length]] };
    let ti = 0, score = 0, last = -2; const m = [];
    for (const ch of q) {
      if (ch === " ") continue;
      const j = t.indexOf(ch, ti);
      if (j < 0) return null;
      score += j === last + 1 ? 12 : (j === 0 || t[j - 1] === " " ? 9 : 1);
      if (j === last + 1 && m.length) m[m.length - 1][1] = j + 1; else m.push([j, j + 1]);
      last = j; ti = j + 1;
    }
    return { s: score - t.length * 0.05, m };
  }
  function marked(text, m) {
    if (!m) return [text];
    const out = []; let i = 0;
    m.forEach(([a, b]) => { if (a > i) out.push(text.slice(i, a)); out.push(el("mark", {}, text.slice(a, b))); i = b; });
    if (i < text.length) out.push(text.slice(i));
    return out;
  }
  function commands() {
    const list = [
      ["Dark screen / light screen", "Toggle the colours", "moon", toggleDark, "Ctrl+Shift+L"],
      ["Appearance…", "Theme, accent colour, row size, stripes", "palette", appearance],
      ["Show / hide the side menu", "More room for wide lists", "menu", toggleSide, "Ctrl+B"],
      ["Pin or unpin this screen", "Keep it at the top of the side menu", "star", () => togglePin()],
      ["Compact rows / comfortable rows", "Fit more rows on the screen", "columns", () => setPref("bco_density", P.density() === "compact" ? "comfortable" : "compact")],
      ["Striped rows on / off", "Alternate row shading in every list", "columns", () => setPref("bco_zebra", P.zebra() ? "0" : "1")],
      ["All modules", "The modules screen", "screen", () => { location.hash = "#/home"; }, "Ctrl+M"],
      ["Refresh lists", "Reload projects, materials, parties…", "clock", () => clickTop("⟳") || clickTop("Refresh")],
      ["Print this screen", "", "doc", () => window.print(), "Ctrl+P"],
      ["Shortcut keys", "Every key BuildCore knows", "info", () => (window.bcoHelp ? window.bcoHelp("keys") : (window.shortcutHelp && window.shortcutHelp())), "Ctrl+/"],
      ["Ask the help assistant", "", "info", () => window.bcoHelp && window.bcoHelp("ask"), "F1"],
      ["What's new in BuildCore " + VER, "", "gift", whatsNew],
    ];
    if (window.bcoSwitchCompany) list.push(["Switch company", "", "screen", () => window.bcoSwitchCompany(), "Alt+F3"]);
    list.push(["Change password", "", "info", () => clickTop("Password")], ["Sign out", "", "x", () => clickTop("Sign out")]);
    return list.map(([label, sub, icon, run, key]) => ({ kind: "cmd", label, sub, icon, run, key }));
  }
  function creates() {
    return [...document.querySelectorAll(".qamenu a")].map((a) => ({ kind: "new", label: "New " + a.textContent.trim().replace(/^\+\s*/, "").replace(/^([A-Z])(?=[a-z])/, (m) => m.toLowerCase()), sub: "Start an entry", icon: "plus", href: a.getAttribute("href") }));
  }
  let PAL = null;
  function palette(prefill) {
    if (!ready()) return;
    if (PAL) { PAL.input.focus(); PAL.input.select(); return; }
    const input = el("input", { type: "text", placeholder: "Type a screen, an entry, a command — or search records…", "aria-label": "Command palette", autocomplete: "off", spellcheck: "false" });
    const list = el("div", { class: "bcp-list", role: "listbox" });
    const box = el("div", { class: "bcp", role: "dialog", "aria-label": "Command palette" },
      el("div", { class: "bcp-in" }, svg("search", 18), input, el("kbd", {}, "Esc")), list,
      el("div", { class: "bcp-foot" }, el("span", {}, el("kbd", {}, "↑"), el("kbd", {}, "↓"), "move"), el("span", {}, el("kbd", {}, "Enter"), "open"),
        el("span", {}, el("kbd", {}, ">"), "commands only"), el("span", {}, el("kbd", {}, "Ctrl+B"), "side menu"), el("span", { style: "margin-left:auto" }, "BuildCore " + VER)));
    const wrap = el("div", { class: "bcp-wrap", onmousedown: (e) => { if (e.target === wrap) close(); } }, box);
    document.body.append(wrap);
    let items = [], cur = 0, recTimer = null, recSeq = 0, records = [];
    const close = () => { clearTimeout(recTimer); wrap.remove(); PAL = null; };
    const go = (it) => {
      if (!it) return;
      close();
      if (it.kind === "cmd") { try { it.run(); } catch (e) { toastSafe(e.message, "err"); } return; }
      if (it.kind === "rec") { if (typeof goResult === "function") goResult(it.r); else location.hash = it.r.link; return; }
      location.hash = it.href || ("#/" + it.path);
    };
    const paint = () => {
      list.innerHTML = "";
      if (!items.length) { list.append(el("div", { class: "bcp-empty" }, input.value.trim().length >= 2 ? "Nothing matches yet — still searching records…" : "Nothing matches.")); return; }
      let g = null;
      items.forEach((it, i) => {
        if (it.group !== g) { g = it.group; list.append(el("div", { class: "bcp-g" }, g)); }
        const row = el("a", { class: "bcp-i" + (i === cur ? " on" : ""), role: "option", href: it.href || (it.path ? "#/" + it.path : "javascript:void 0"),
          onclick: (e) => { e.preventDefault(); go(it); }, onmousemove: () => { if (cur !== i) { cur = i; hi(); } } },
        el("span", { class: "ic" }, svg(it.icon || "screen", 15)),
        el("span", { class: "tx" }, el("b", {}, marked(it.label, it.m)), it.sub ? el("small", {}, it.sub) : null),
        it.key ? el("span", { class: "k" }, it.key) : null);
        row._i = i;
        list.append(row);
      });
    };
    const hi = () => {
      list.querySelectorAll(".bcp-i").forEach((a) => a.classList.toggle("on", a._i === cur));
      const on = list.querySelector(".bcp-i.on");
      if (on) on.scrollIntoView({ block: "nearest" });
    };
    const build = () => {
      const raw = input.value;
      const cmdOnly = raw.trim().startsWith(">");
      const q = raw.replace(/^\s*>/, "").trim();
      const out = [];
      const all = screens();
      const add = (group, arr, limit) => {
        const scored = arr.map((x) => { const f = fuzzy(x.label + (x.kw ? " " + x.kw : ""), q); return f ? Object.assign({}, x, { group, s: f.s, m: f.m && f.m[0][1] <= x.label.length ? f.m : null }) : null; })
          .filter(Boolean);
        if (q) scored.sort((a, b) => b.s - a.s);
        const direct = q.length >= 3 && scored.some((x) => x.s >= 500);
        out.push(...(direct ? scored.filter((x) => x.s >= 500) : scored).slice(0, limit));
      };
      if (cmdOnly) add("Commands", commands(), 30);
      else if (!q) {
        const pinned = pins().map((p) => all.find((x) => x.path === p)).filter(Boolean);
        add("Pinned", pinned.map((x) => ({ kind: "screen", path: x.path, label: x.label, sub: x.group, icon: "star" })), 12);
        const rec = LSjson("bco_recent_pages", []).filter((p) => !pins().includes(p)).map((p) => all.find((x) => x.path === p)).filter(Boolean);
        add("Recent", rec.map((x) => ({ kind: "screen", path: x.path, label: x.label, sub: x.group, icon: "clock" })), 5);
        add("Create", creates(), 6);
        add("Commands", commands(), 6);
      } else {
        add("Screens", all.map((x) => ({ kind: "screen", path: x.path, label: x.label, sub: x.group, kw: x.group, icon: isPinned(x.path) ? "star" : "screen" })), 9);
        add("Create", creates(), 5);
        add("Commands", commands(), 5);
        if (records.length && records.q === q) out.push(...records.slice(0, 12).map((r) => ({ kind: "rec", r, group: "Records — " + r.group, label: r.label, sub: [r.sub, r.date, r.project_id && typeof nm !== "undefined" ? nm.pcode(r.project_id) : ""].filter(Boolean).join(" · "), icon: "doc" })));
      }
      items = out; cur = Math.min(cur, Math.max(0, items.length - 1));
      paint();
    };
    const findRecords = () => {
      clearTimeout(recTimer);
      const q = input.value.replace(/^\s*>/, "").trim();
      if (input.value.trim().startsWith(">") || q.length < 2) { records = []; return; }
      const seq = ++recSeq;
      recTimer = setTimeout(async () => {
        try {
          const rows = await api("search", { q, project_id: S.project || null });
          if (seq !== recSeq || !PAL) return;
          records = (rows || []).slice(); records.q = q; build();
        } catch (e) { /* search is optional */ }
      }, 220);
    };
    input.addEventListener("input", () => { cur = 0; build(); findRecords(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); e.stopPropagation(); if (items.length) { cur = (cur + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length; hi(); } }
      else if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); go(items[cur]); }
      else if (e.key === "Tab") { e.preventDefault(); }
      e.stopPropagation();
    });
    PAL = { input, close };
    input.value = prefill || "";
    build(); findRecords();
    setTimeout(() => input.focus(), 0);
  }
  window.bcoPalette = palette;

  /* ───────────────────────── appearance dialog, what's new ───────────────────────── */
  function seg(options, value, onpick) {
    const b = el("div", { class: "bco-seg", role: "radiogroup" });
    const draw = (v) => { b.innerHTML = ""; options.forEach(([val, label, icon]) => b.append(el("button", { type: "button", class: val === v ? "on" : "", role: "radio", "aria-checked": val === v ? "true" : "false",
      onclick: () => { onpick(val); draw(val); } }, icon ? svg(icon, 14) : null, label))); };
    draw(value);
    return b;
  }
  function appearance() {
    const sw = el("div", { class: "bco-sw" });
    const drawSw = () => { sw.innerHTML = ""; Object.entries(ACCENTS).forEach(([k, a]) => sw.append(el("button", { type: "button", class: P.accent() === k ? "on" : "", title: a.n, "aria-label": a.n, style: "background:" + a.c,
      onclick: () => { setPref("bco_accent", k); drawSw(); } }))); };
    drawSw();
    const body = el("div", { class: "bco-appear" },
      el("div", { class: "row" }, el("b", {}, "Screen"), seg([["light", "Light", "sun"], ["dark", "Dark", "moon"], ["auto", "Follow Windows", "screen"]], P.theme(), (v) => setPref("bco_theme", v))),
      el("div", { class: "row" }, el("b", {}, "Accent colour"), sw),
      el("div", { class: "row" }, el("b", {}, "Rows"), seg([["comfortable", "Comfortable"], ["compact", "Compact"]], P.density(), (v) => setPref("bco_density", v))),
      el("div", { class: "row" }, el("b", {}, "Striped rows"), seg([["0", "Off"], ["1", "On"]], P.zebra() ? "1" : "0", (v) => setPref("bco_zebra", v))),
      el("div", { class: "row" }, el("b", {}, "Side menu"), seg([["0", "Show"], ["1", "Hide"]], P.side() ? "1" : "0", (v) => setPref("bco_side_hidden", v))),
      el("p", { class: "hint", style: "margin:10px 0 0" }, "These settings belong to this computer and this window. Printouts always come out on white paper."));
    if (typeof modal === "function") modal("Appearance", body, [], { narrow: true });
  }
  function whatsNew() {
    const items = [
      ["moon", "Dark screen and accent colours", "Light, dark or follow Windows, six accent colours, compact rows and striped rows. Ctrl+Shift+L switches light and dark."],
      ["search", "Command palette", "Ctrl+K (or the search box at the top) finds any screen, starts any new entry, runs commands and searches your records."],
      ["star", "Pinned screens", "Click the star next to a screen's title. Pinned screens stay at the top of the side menu and the palette."],
      ["columns", "Smarter lists", "Click a column heading to sort, choose the columns to show, and copy the rows straight into Excel. BuildCore remembers this per list."],
      ["menu", "More room", "Ctrl+B hides the side menu. A thin line at the top shows when BuildCore is working; long screens get a back-to-top button."],
      ["chart", "Dashboard", "Figures with icons and a cost-against-revenue chart for the last six months."],
    ];
    if (typeof modal === "function") modal("What's new in BuildCore " + VER, el("div", { class: "bco-new" },
      el("ul", {}, items.map(([i, t, d]) => el("li", {}, el("span", { class: "ic" }, svg(i, 17)), el("div", {}, el("b", {}, t), el("span", {}, d)))))),
    [{ label: "Choose my look…", act: () => { setTimeout(appearance, 50); } }, { label: "Got it", cls: "primary", act: () => {} }], { narrow: true });
    LSset("bco_seen_" + VER, "1");
  }
  window.bcoAppearance = appearance;

  /* ───────────────────────── top bar, side menu, page title ───────────────────────── */
  function decorateTop() {
    const top = document.querySelector(".top");
    if (!top || top._bco217) return;
    top._bco217 = true;
    const sideBtn = el("button", { class: "bco-iconbtn bco-sidetoggle", type: "button", title: "Show / hide the side menu (Ctrl+B)", "aria-label": "Show or hide the side menu", onclick: toggleSide }, svg("menu", 17));
    top.insertBefore(sideBtn, top.firstChild);
    const trig = el("button", { class: "bcp-trigger", type: "button", title: "Search or jump to (Ctrl+K)", onclick: () => palette() }, svg("search", 15), el("span", {}, "Search anything…"), el("kbd", {}, "Ctrl K"));
    const sw = top.querySelector(".searchwrap");
    if (sw) top.insertBefore(trig, sw); else top.append(trig);
    const theme = el("button", { class: "bco-iconbtn bco-themebtn", type: "button", onclick: toggleDark });
    const um = top.querySelector(".helpbtn") || top.querySelector(".usermenu");
    if (um) top.insertBefore(theme, um); else top.append(theme);
    applyLook();
  }
  function decorateUserMenu() {
    const list = document.querySelector(".usermenu-list");
    if (!list || list._bco217) return;
    list._bco217 = true;
    const anchor = [...list.querySelectorAll("button")].find((b) => /Sign out/.test(b.textContent));
    const add = (label, fn) => list.insertBefore(el("button", { type: "button", onclick: () => { list.hidden = true; fn(); } }, label), anchor);
    add("Appearance…", appearance);
    add("Dark / light screen  (Ctrl+Shift+L)", toggleDark);
    add("What's new in " + VER, whatsNew);
    if (anchor) list.insertBefore(el("div", { class: "um-sep" }), anchor);
  }
  function paintPins() {
    const side = document.querySelector(".side");
    if (!side) return;
    let box = side.querySelector(".navpinned");
    const list = pins().map((p) => screenOf(p)).filter(Boolean);
    if (!list.length) { if (box) box.remove(); return; }
    if (!box) {
      box = el("div", { class: "navpinned" });
      const anchor = side.querySelector(".navrecent") || side.querySelector(".nav");
      if (!anchor) return;
      side.insertBefore(box, anchor);
    }
    const sig = list.map((x) => x.path).join("|");
    if (box._sig === sig) return;
    box._sig = sig;
    box.innerHTML = "";
    box.append(el("div", { class: "lbl" }, "Pinned"), ...list.map((x) => el("a", { href: "#/" + x.path, title: x.group }, svg("star", 13), x.label)));
  }
  function paintStar() {
    const page = document.querySelector("#page");
    const h1 = page && page.querySelector("h1");
    if (!h1) return;
    const path = curPath();
    if (!screenOf(path)) { const old = h1.querySelector(".bco-pin"); if (old) old.remove(); return; }
    let b = h1.querySelector(".bco-pin");
    if (!b) {
      b = el("button", { class: "bco-pin", type: "button", onclick: (e) => { e.preventDefault(); togglePin(path); } }, svg("star", 17));
      h1.append(b);
    }
    const on = isPinned(path);
    b.classList.toggle("on", on);
    b.title = on ? "Unpin this screen" : "Pin this screen to the side menu";
    b.setAttribute("aria-label", b.title);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }

  /* ───────────────────────── smarter lists ───────────────────────── */
  const NUMFMT = ["money", "qty", "num"];
  const cellText = (c, r) => {
    const v = typeof c.v === "function" ? c.v(r) : r[c.k];
    return v instanceof Node ? v.textContent : v;
  };
  const numOf = (v) => { if (typeof v === "number") return v; const s = String(v == null ? "" : v).replace(/,/g, "").replace(/%$/, "").trim(); return s === "" ? NaN : Number(s); };
  function sorter(c, dir) {
    const numeric = NUMFMT.includes(c.fmt);
    return (a, b) => {
      const x = cellText(c, a), y = cellText(c, b);
      const nx = numOf(x), ny = numOf(y);
      let d;
      if ((numeric || (!isNaN(nx) && !isNaN(ny)))) {
        if (isNaN(nx) && isNaN(ny)) d = 0; else if (isNaN(nx)) d = 1; else if (isNaN(ny)) d = -1; else d = nx - ny;
        if (isNaN(nx) || isNaN(ny)) return d;
      } else {
        const ex = x == null || x === "", ey = y == null || y === "";
        if (ex || ey) return ex === ey ? 0 : (ex ? 1 : -1);
        d = String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: "base" });
      }
      return dir === "desc" ? -d : d;
    };
  }
  let STYLE_SEQ = 0;
  function colStyle(wrap) {
    const K = wrap._k;
    const hidden = wrap._bcoHide || [];
    if (!wrap._bcoSid) { wrap._bcoSid = "bcol" + (++STYLE_SEQ); wrap.setAttribute("data-bcol", wrap._bcoSid); }
    let st = document.getElementById(wrap._bcoSid);
    if (!hidden.length) { if (st) st.remove(); return; }
    if (!st) { st = el("style", { id: wrap._bcoSid }); document.head.append(st); }
    const off = wrap.querySelector("thead th.kc") ? 1 : 0;
    st.textContent = hidden.filter((i) => i < K.cols.length).map((i) => '[data-bcol="' + wrap._bcoSid + '"] table tr>:nth-child(' + (i + 1 + off) + ")").join(",") + "{display:none}";
  }
  function columnsPopover(wrap, anchor) {
    document.querySelectorAll(".bco-colpop").forEach((x) => x.remove());
    const K = wrap._k;
    const name = wrap.dataset.name;
    const hidden = new Set(wrap._bcoHide || []);
    const pop = el("div", { class: "bco-colpop", role: "dialog", "aria-label": "Columns" });
    K.cols.forEach((c, i) => {
      if (!c.label) return;
      const cb = el("input", { type: "checkbox" }); cb.checked = !hidden.has(i);
      cb.addEventListener("change", () => {
        if (cb.checked) hidden.delete(i); else hidden.add(i);
        if (hidden.size >= K.cols.filter((x) => x.label).length) { hidden.delete(i); cb.checked = true; return; }
        wrap._bcoHide = [...hidden].sort((a, b) => a - b);
        if (name) LSset("bco_cols_" + name, wrap._bcoHide.length ? JSON.stringify(wrap._bcoHide) : null);
        colStyle(wrap);
      });
      pop.append(el("label", {}, cb, c.label));
    });
    pop.append(el("div", { class: "ft" }, el("button", { class: "btn small", type: "button", onclick: () => {
      wrap._bcoHide = []; if (name) LSset("bco_cols_" + name, null); colStyle(wrap); pop.remove(); } }, "Show all"),
    el("button", { class: "btn small primary", type: "button", onclick: () => pop.remove() }, "Done")));
    document.body.append(pop);
    const r = anchor.getBoundingClientRect();
    pop.style.top = Math.min(innerHeight - 40, r.bottom + 6) + "px";
    pop.style.left = Math.max(8, Math.min(innerWidth - pop.offsetWidth - 8, r.right - pop.offsetWidth)) + "px";
    setTimeout(() => document.addEventListener("mousedown", function off(e) { if (!pop.contains(e.target) && e.target !== anchor) { pop.remove(); document.removeEventListener("mousedown", off); } }), 0);
  }
  function copyRows(wrap, btn) {
    const K = wrap._k;
    const hidden = new Set(wrap._bcoHide || []);
    const cols = K.cols.map((c, i) => [c, i]).filter(([c, i]) => !hidden.has(i) && c.label !== undefined);
    const rows = (K.sel && K.sel.size ? K.vis.filter((r) => K.sel.has(r)) : K.vis) || [];
    const clean = (v) => String(v == null ? "" : v).replace(/[\t\r\n]+/g, " ").trim();
    const raw = (c, r) => { if (NUMFMT.includes(c.fmt)) { const v = typeof c.v === "function" ? c.v(r) : r[c.k]; return v instanceof Node ? v.textContent : v; } return cellText(c, r); };
    const text = [cols.map(([c]) => clean(c.label)).join("\t"), ...rows.map((r) => cols.map(([c]) => clean(raw(c, r))).join("\t"))].join("\r\n");
    const done = () => { toastSafe(rows.length + " row(s) copied — paste them into Excel", "ok"); if (btn) { const t = btn.lastChild.textContent; btn.lastChild.textContent = "Copied"; setTimeout(() => { btn.lastChild.textContent = t; }, 1400); } };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    else fallbackCopy(text, done);
  }
  function fallbackCopy(text, done) {
    const ta = el("textarea", { style: "position:fixed;left:-9999px;top:0" }); ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { toastSafe("Copy is blocked here — use Export CSV.", "err"); }
    ta.remove();
  }
  function smartList(wrap) {
    if (wrap._bco217 || !wrap._k) return;
    const K = wrap._k;
    if (!K.cols || !K.all) return;
    const ths = [...wrap.querySelectorAll(":scope > .tablewrap > table > thead > tr > th")];
    if (!ths.length) return;
    wrap._bco217 = true;
    const off = ths[0] && ths[0].classList.contains("kc") ? 1 : 0;
    const name = wrap.dataset.name || "";
    const orig = K.all.slice();
    const state = { ci: -1, dir: "" };
    const paint = () => ths.forEach((th, j) => {
      const i = j - off;
      th.classList.toggle("bco-asc", i === state.ci && state.dir === "asc");
      th.classList.toggle("bco-desc", i === state.ci && state.dir === "desc");
      const s = th.querySelector(".bco-sort");
      if (s) s.textContent = i === state.ci ? (state.dir === "asc" ? "▲" : "▼") : "↕";
      if (th.classList.contains("bco-sortable")) th.setAttribute("aria-sort", i === state.ci ? (state.dir === "asc" ? "ascending" : "descending") : "none");
    });
    const apply = (ci, dir, quiet) => {
      state.ci = ci; state.dir = dir;
      const keep = new Set(K.all);
      const base = orig.filter((r) => keep.has(r)).concat(K.all.filter((r) => !orig.includes(r)));
      const next = ci < 0 || !dir ? base : base.slice().sort(sorter(K.cols[ci], dir));
      K.all.length = 0; next.forEach((r) => K.all.push(r));
      try { K.render(); } catch (e) { /* list redrawn elsewhere */ }
      paint();
      if (name && !quiet) LSset("bco_sort_" + name, ci < 0 || !dir ? null : JSON.stringify([ci, dir]));
    };
    if (K.all.length > 1) ths.forEach((th, j) => {
      const i = j - off;
      const c = K.cols[i];
      if (!c || !c.label || th.classList.contains("kc")) return;
      th.classList.add("bco-sortable");
      th.tabIndex = 0;
      th.title = "Sort by " + c.label + " (click again to reverse, a third time to undo)";
      th.append(el("span", { class: "bco-sort", "aria-hidden": "true" }, "↕"));
      /* numbers sort biggest first, text A to Z; the third click puts the list back as it came */
      const cycle = () => {
        if (state.ci !== i) return apply(i, NUMFMT.includes(c.fmt) ? "desc" : "asc");
        const first = NUMFMT.includes(c.fmt) ? "desc" : "asc", second = first === "asc" ? "desc" : "asc";
        if (state.dir === first) return apply(i, second);
        return apply(-1, "");
      };
      th.addEventListener("click", (e) => { if (e.target.closest("input,button,a")) return; cycle(); });
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); cycle(); } });
    });
    if (name) {
      const saved = LSjson("bco_sort_" + name, null);
      if (Array.isArray(saved) && K.cols[saved[0]] && K.all.length > 1) apply(saved[0], saved[1], true);
      const hid = LSjson("bco_cols_" + name, []);
      if (Array.isArray(hid) && hid.length) { wrap._bcoHide = hid.filter((i) => Number.isInteger(i) && i < K.cols.length); colStyle(wrap); }
    }
    const bar = wrap.querySelector(":scope > .kbar");
    if (bar && K.all.length) {
      const exp = [...bar.querySelectorAll(":scope > button")].find((b) => /Export CSV/.test(b.textContent));
      const copyB = el("button", { class: "btn small bco-colbtn", type: "button", title: "Copy the rows shown (or the ticked rows) to paste into Excel", onclick: () => copyRows(wrap, copyB) }, svg("copy", 13), el("span", {}, "Copy"));
      const colB = K.cols.filter((c) => c.label).length > 2 ? el("button", { class: "btn small bco-colbtn", type: "button", title: "Choose the columns to show", onclick: () => columnsPopover(wrap, colB) }, svg("columns", 13), el("span", {}, "Columns")) : null;
      if (exp) { bar.insertBefore(copyB, exp); if (colB) bar.insertBefore(colB, copyB); } else { bar.append(...[colB, copyB].filter(Boolean)); }
    }
  }
  function scanLists(rootEl) { (rootEl || document).querySelectorAll(".klist").forEach(smartList); }

  /* ───────────────────────── dashboard ───────────────────────── */
  const LAST = {};
  function wrapRun() {
    if (typeof run !== "function" || run._bco217) return;
    const orig = run;
    const r2 = async function (fn, args, okMsg) { const d = await orig(fn, args, okMsg); if (fn === "dash.summary") LAST.dash = d; return d; };
    r2._bco217 = true;
    window.run = r2;
    try { run = r2; } catch (e) { /* strict mode */ }
  }
  const TILE_ICON = [[/approv/i, "check"], [/stock value/i, "box"], [/reorder|negative/i, "alert"], [/transit|transfer/i, "truck"], [/late|overdue deliver/i, "clock"],
    [/PO|purchase|deliver/i, "cart"], [/payable/i, "up"], [/receivable/i, "down"], [/cost|revenue|profit|cash/i, "coins"], [/service|maint/i, "wrench"], [/down|breakdown/i, "stop"]];
  function decorateTiles(rootEl) {
    (rootEl || document).querySelectorAll(".tile").forEach((t) => {
      if (t._bco217) return;
      t._bco217 = true;
      const label = (t.querySelector("span") || t).textContent || "";
      const hit = TILE_ICON.find(([re]) => re.test(label));
      t.append(el("span", { class: "bco-ti", "aria-hidden": "true" }, svg(hit ? hit[1] : "chart", 17)));
    });
  }
  const monthName = (m) => { const d = new Date(m + "-01T00:00:00"); return isNaN(d) ? m : d.toLocaleString("en", { month: "short" }) + " " + String(d.getFullYear()).slice(2); };
  const short = (n) => { const a = Math.abs(n); return a >= 1e7 ? (n / 1e7).toFixed(a >= 1e8 ? 0 : 1) + " Cr" : a >= 1e5 ? (n / 1e5).toFixed(a >= 1e6 ? 0 : 1) + " L" : a >= 1e3 ? (n / 1e3).toFixed(0) + "k" : String(Math.round(n)); };
  function costChart(trend, width) {
    const W = Math.max(300, Math.round(width || 420)), H = 200, L = 44, R = 6, T = 10, B = 24;
    const max = Math.max(1, ...trend.map((x) => Math.max(x.cost || 0, x.revenue || 0)));
    const step = Math.pow(10, Math.floor(Math.log10(max)));
    const top = Math.ceil(max / step) * step;
    const ns = "http://www.w3.org/2000/svg";
    const s = document.createElementNS(ns, "svg");
    s.setAttribute("viewBox", "0 0 " + W + " " + H); s.setAttribute("class", "bco-chart"); s.setAttribute("role", "img");
    s.setAttribute("aria-label", "Cost and revenue by month");
    const mk = (tag, a, txt) => { const e = document.createElementNS(ns, tag); Object.entries(a).forEach(([k, v]) => e.setAttribute(k, v)); if (txt != null) e.textContent = txt; s.append(e); return e; };
    for (let i = 0; i <= 4; i++) {
      const y = T + (H - T - B) * (1 - i / 4);
      mk("line", { x1: L, x2: W - R, y1: y, y2: y, class: "gl" });
      mk("text", { x: L - 6, y: y + 3.5, "text-anchor": "end" }, short(top * i / 4));
    }
    const gw = (W - L - R) / trend.length, bw = Math.min(26, gw * 0.3);
    trend.forEach((x, i) => {
      const cx = L + gw * i + gw / 2;
      [["c", x.cost || 0, -bw - 1.5, "Cost"], ["r", x.revenue || 0, 1.5, "Revenue"]].forEach(([cls, v, dx, lab]) => {
        const hh = (H - T - B) * v / top;
        const rc = mk("rect", { x: cx + dx, y: H - B - hh, width: bw, height: Math.max(0.5, hh), rx: 3, class: cls });
        const tt = document.createElementNS(ns, "title"); tt.textContent = monthName(x.month) + " — " + lab + ": " + (typeof fmtMoney === "function" ? fmtMoney(v) : v); rc.append(tt);
      });
      mk("text", { x: cx, y: H - 8, "text-anchor": "middle" }, monthName(x.month));
    });
    return s;
  }
  function upgradeDashboard() {
    if (curPath() !== "dashboard" && !(curPath() === "" && document.querySelector("#page .tiles"))) return;
    const d = LAST.dash;
    const bars = document.querySelector("#page .bars");
    if (!d || !d.cost_trend || !bars || bars._bco217) return;
    bars._bco217 = true;
    const h2 = bars.previousElementSibling;
    if (h2 && h2.tagName === "H2") h2.textContent = "Cost and revenue by month";
    const legend = el("div", { class: "bco-legend" }, el("span", {}, el("i", { style: "background:var(--acc)" }), "Cost"), el("span", {}, el("i", { style: "background:var(--green)" }), "Revenue"));
    const w = (bars.parentElement && bars.parentElement.clientWidth) || 420;
    bars.replaceWith(el("div", {}, legend, costChart(d.cost_trend, w - 34)));
  }

  /* ───────────────────────── loading line, back to top, toasts ───────────────────────── */
  const bar = el("div", { id: "bco-load", "aria-hidden": "true" });
  let pending = 0, barTimer = null, grow = null;
  const startLoad = () => {
    pending++;
    if (pending === 1) {
      clearTimeout(barTimer);
      barTimer = setTimeout(() => { bar.classList.add("on"); bar.style.width = "18%"; let w = 18; clearInterval(grow); grow = setInterval(() => { w = Math.min(88, w + (90 - w) * 0.08); bar.style.width = w + "%"; }, 200); }, 160);
    }
  };
  const endLoad = () => {
    pending = Math.max(0, pending - 1);
    if (!pending) { clearTimeout(barTimer); clearInterval(grow); if (bar.classList.contains("on")) { bar.style.width = "100%"; setTimeout(() => { bar.classList.remove("on"); bar.style.width = "0"; }, 260); } }
  };
  const _fetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    const mine = /\/api(\?|$)/.test(String(url));
    if (mine) startLoad();
    const p = _fetch(url, opts);
    if (mine) p.then(endLoad, endLoad);
    return p;
  };
  const topBtn = el("button", { id: "bco-top", type: "button", hidden: true, title: "Back to the top", "aria-label": "Back to the top", onclick: () => window.scrollTo({ top: 0, behavior: "smooth" }) }, svg("arrowup", 17));
  window.addEventListener("scroll", () => { topBtn.hidden = window.scrollY < 700; }, { passive: true });
  function decorateToasts(box) {
    box.querySelectorAll(".toast").forEach((t) => {
      if (t._bco217) return;
      t._bco217 = true;
      const msg = el("span", { class: "tm" }, ...t.childNodes);
      const icon = t.classList.contains("ok") ? "check" : t.classList.contains("err") ? "alert" : "info";
      t.append(el("span", { class: "ti" }, svg(icon, 16)), msg, el("button", { class: "tx", type: "button", "aria-label": "Close", onclick: () => t.remove() }, svg("x", 14)));
      if (t.classList.contains("err")) t.setAttribute("role", "alert");
    });
  }

  /* ───────────────────────── keys ───────────────────────── */
  const typingIn = (e) => { const t = e.target; return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable); };
  window.addEventListener("keydown", (e) => {
    if (!ready()) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && !e.altKey && ((k === "k" && !e.shiftKey) || (k === "p" && e.shiftKey) || (k === "f" && !e.shiftKey && !document.querySelector(".overlay")))) {
      if (!P.palette() && k !== "p") return;
      e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); palette(); return;
    }
    if (ctrl && !e.altKey && !e.shiftKey && k === "b" && !typingIn(e)) { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); toggleSide(); return; }
    if (ctrl && e.shiftKey && !e.altKey && k === "l") { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); toggleDark(); }
  }, true);
  function addKeyHelp() {
    const rows = [["Command palette: screens, new entries, commands, records", "Ctrl+K  /  Ctrl+Shift+P  /  Ctrl+F"], ["Commands only (in the palette)", "type  >"],
      ["Show / hide the side menu", "Ctrl+B"], ["Dark / light screen", "Ctrl+Shift+L"], ["Sort a list by a column", "click the heading (again to reverse)"]];
    try {
      if (Array.isArray(window.bcoKeyHelp) && !window.bcoKeyHelp.some((x) => x && x[0] === "Modern screen (2.17)")) window.bcoKeyHelp.unshift(["Modern screen (2.17)", rows]);
      if (typeof KEYMAP !== "undefined" && Array.isArray(KEYMAP) && !KEYMAP.some((r) => r[1] === "Ctrl+B")) rows.forEach((r) => KEYMAP.push(r));
    } catch (e) { /* older help */ }
  }

  /* ───────────────────────── watch the screen ───────────────────────── */
  let tick = null;
  function pass() {
    tick = null;
    if (!document.body.contains(bar)) document.body.append(bar, topBtn);
    const toasts = document.getElementById("toasts");
    if (toasts) decorateToasts(toasts);
    if (!ready()) return;
    wrapRun();
    decorateTop();
    decorateUserMenu();
    paintPins();
    paintStar();
    const page = document.getElementById("page");
    if (page) { scanLists(page); decorateTiles(page); upgradeDashboard(); }
    document.querySelectorAll(".overlay .klist").forEach(smartList);
    if (!pass.welcomed && LS("bco_seen_" + VER, "") !== "1" && document.querySelector(".top") && !document.querySelector(".overlay")) {
      pass.welcomed = true;
      setTimeout(() => { if (!document.querySelector(".overlay")) whatsNew(); }, 1500);
    }
  }
  const schedule = () => { if (!tick) tick = requestAnimationFrame(pass); };
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("hashchange", () => { const p = document.getElementById("page"); if (p) { p.style.animation = "none"; void p.offsetWidth; p.style.animation = ""; } schedule(); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { wrapRun(); setTimeout(addKeyHelp, 50); schedule(); });
  else { wrapRun(); setTimeout(addKeyHelp, 50); schedule(); }
  window.bcoModern = { version: VER, palette, appearance, whatsNew, togglePin, toggleDark, toggleSide };
})();
