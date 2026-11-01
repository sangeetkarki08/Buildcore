/* BuildCore 2.12 — site mode you choose, and site packs that carry any site work to head office. */
(function () {
"use strict";

/* Everything that is usually done at site. [id, label, link, module, permission, group, pack kind] */
const SITE_FEATURES = [
  ["dpr", "Daily progress (DPR)", "#/p/dpr?new=1", "project", "edit", "Work", "dpr"],
  ["photo", "Photo", "#/p/docs?photo=1", "project", "view", "Work", null],
  ["event", "Event / hindrance / notice", "#/p/events?new=1", "project", "view", "Work", "events"],
  ["task", "Task", "#/p/tasks?new=1", "project", "view", "Work", "tasks"],
  ["measure", "Measurement", "#/p/measure?new=1", "commercial", "edit", "Work", "measure"],
  ["today", "Today's summary", "#/p/today", "project", "view", "Work", null],
  ["mrq", "Requisition", "#/inv/mrq?new=1", "inventory", "edit", "Store", "mrq"],
  ["issue", "Material issue", "#/inv/issue?new=1", "inventory", "edit", "Store", "issues"],
  ["grn", "Goods received (GRN)", "#/inv/grn?new=1", "inventory", "edit", "Store", "grn"],
  ["return", "Material return", "#/inv/return?new=1", "inventory", "edit", "Store", "returns"],
  ["transfer", "Stock transfer", "#/inv/transfer?new=1", "inventory", "edit", "Store", "transfers"],
  ["count", "Stock count", "#/inv/count?new=1", "inventory", "edit", "Store", "counts"],
  ["stock", "Stock on hand", "#/inv/stock", "inventory", "view", "Store", null],
  ["pr", "Purchase request", "#/proc/pr?new=1", "procurement", "edit", "Procurement", "pr"],
  ["bill", "Purchase bill (local purchase)", "#/proc/invoices?new=1", "procurement", "edit", "Procurement", "bills"],
  ["pending", "Pending deliveries", "#/proc/pending", "procurement", "view", "Procurement", null],
  ["eqlog", "Equipment log (one day)", "#/eq/logs?new=1", "equipment", "edit", "Equipment", "logsheets"],
  ["eqbook", "Equipment log (month)", "#/eq/books", "equipment", "edit", "Equipment", "logsheets"],
  ["wo", "Breakdown / work order", "#/eq/wo?new=1", "equipment", "edit", "Equipment", "wo"],
  ["run", "Plant production run", "#/pl/runs?new=1", "plant", "edit", "Plant", "runs"],
  ["test", "Test request", "#/p/quality?new=1", "quality", "edit", "Quality", "tests"],
  ["ncr", "Quality & NCR", "#/p/quality", "quality", "view", "Quality", "ncrs"],
  ["fissue", "Report an issue / snag", "#/f/issues?new=1", "project", "view", "Quality", "fissues"],
  ["finsp", "Inspection (check list)", "#/f/inspections", "project", "edit", "Quality", "finsp"],
  ["frfi", "RFI to the engineer", "#/f/rfis?new=1", "project", "edit", "Work", "frfis"],
  ["fdraw", "Drawings", "#/f/drawings", "project", "view", "Work", null],
  ["fmeet", "Meeting minutes", "#/f/meetings", "project", "edit", "Work", "fmeet"],
  ["mywork", "My work", "#/mywork", "project", "view", "Work", null],
];
const DEFAULT_ITEMS = ["dpr", "issue", "mrq", "eqlog", "photo", "fissue", "finsp", "event", "task", "test", "measure"];
let SITE_CFG = null;

async function siteCfg(force) {
  if (!SITE_CFG || force) SITE_CFG = await run("site.cfg_get", {});
  return SITE_CFG;
}
const chosenIds = (cfg) => cfg.mine || cfg.company || DEFAULT_ITEMS;

/* every screen in the menu this user may open, for "any other screen" */
function menuScreens() {
  const out = [];
  try {
    (typeof MENU !== "undefined" ? MENU : []).forEach(([grp, mod, items]) => (items || []).forEach((it) => {
      const m = it[2] || mod;
      if (it[0] === "site") return;
      if (!m || can(m, "view") || (it[3] && can(it[3], "view"))) out.push({ id: "screen:" + it[0], label: it[1], href: "#/" + it[0], group: grp });
    }));
  } catch (e) { /* the menu is not loaded yet */ }
  return out;
}

function resolve(ids) {
  const scr = menuScreens();
  return ids.map((id) => {
    const f = SITE_FEATURES.find((x) => x[0] === id);
    if (f) return can(f[3], f[4]) || (f[4] === "edit" && can(f[3], "view")) ? { id, label: f[1], href: f[2], kind: f[6], group: f[5] } : null;
    return scr.find((x) => x.id === id) || null;
  }).filter(Boolean);
}

function chooser(cfg, done) {
  const sel = new Set(chosenIds(cfg));
  const box = h("div", { class: "site-choose" });
  const groups = {};
  SITE_FEATURES.forEach((f) => { (groups[f[5]] = groups[f[5]] || []).push({ id: f[0], label: f[1], ok: can(f[3], "view") }); });
  const tick = (it) => {
    const i = h("input", { type: "checkbox" }); i.checked = sel.has(it.id); i.disabled = it.ok === false;
    i.onchange = () => { if (i.checked) sel.add(it.id); else sel.delete(it.id); };
    return h("label", { style: "display:block;margin:3px 0" + (it.ok === false ? ";opacity:.5" : "") }, i, " ", it.label,
      it.ok === false ? h("span", { class: "hint" }, " (your role cannot open this)") : null);
  };
  Object.entries(groups).forEach(([g, items]) => box.append(h("div", { class: "panel", style: "margin-bottom:8px" }, h("h3", {}, g), items.map(tick))));
  const scr = menuScreens();
  const search = h("input", { placeholder: "Search any screen — e.g. stock card, payments, BOQ, logsheet …" });
  const list = h("div", { style: "max-height:260px;overflow:auto" });
  const draw = () => {
    list.innerHTML = "";
    const t = (search.value || "").toLowerCase();
    scr.filter((x) => !t || (x.label + " " + x.group).toLowerCase().includes(t))
      .forEach((x) => list.append(tick({ id: x.id, label: x.group + " › " + x.label })));
  };
  search.oninput = draw; draw();
  box.append(h("div", { class: "panel" }, h("h3", {}, "Any other screen"), h("p", { class: "hint" }, "Add any screen of BuildCore to your site mode — it is not limited to the list above."), search, list));
  let scope = "mine";
  const scopeSel = cfg.is_admin ? h("select", { onchange: (e) => { scope = e.target.value; } },
    h("option", { value: "mine" }, "Only for me"), h("option", { value: "company" }, "For everybody (default for all users)")) : null;
  modal("Choose what is in site mode", h("div", {},
    h("p", { class: "hint" }, "Tick the work you do at site. The buttons appear in Site mode and in Today, and the same kinds of records are offered when you make a site pack for head office."),
    scopeSel ? h("p", {}, "Save ", scopeSel) : null, box), [
    { label: "Save", cls: "primary", act: async () => {
      const order = SITE_FEATURES.map((f) => f[0]).concat(scr.map((x) => x.id));
      const items = order.filter((id) => sel.has(id)).concat([...sel].filter((id) => !order.includes(id)));
      SITE_CFG = await run("site.cfg_save", { scope, items }, "Site mode saved");
      if (done) done();
    } },
    { label: "Back to the standard set", act: async () => {
      SITE_CFG = await run("site.cfg_save", { scope, items: null }, "Back to the standard set");
      if (done) done();
    } }]);
}

/* the kinds a pack can carry, with tick boxes */
function kindPicker(cfg, preselect) {
  const picks = {};
  const wrap = h("div", { class: "cols" });
  const groups = {};
  cfg.kinds.forEach((k) => { (groups[k.group] = groups[k.group] || []).push(k); });
  Object.entries(groups).forEach(([g, ks]) => wrap.append(h("div", {}, h("b", {}, g), ks.map((k) => {
    const i = h("input", { type: "checkbox" }); i.checked = preselect.has(k.key); picks[k.key] = i;
    return h("label", { style: "display:block;margin:3px 0" }, i, " ", k.label);
  }))));
  return { el: wrap, values: () => Object.keys(picks).filter((k) => picks[k].checked) };
}

function downloadPack(d) {
  const blob = new Blob([JSON.stringify(d.pack)], { type: "application/json" });
  const a = h("a", { href: URL.createObjectURL(blob), download: d.filename });
  document.body.append(a); a.click(); a.remove();
  toast("Pack saved: " + (Object.entries(d.counts).map(([k, n]) => n + " " + k).join(", ") || "nothing in these dates"), "ok");
}

function packPanel(cfg, preselect, title, hint) {
  const ef = form([
    { k: "project_id", label: "Project", type: "select", options: S.L.projects.map((p) => [p.id, p.code + " — " + p.name]), noBlank: true },
    { k: "from", label: "From date", type: "date" }, { k: "to", label: "To date", type: "date" }, { k: "note", label: "Note for head office" },
  ], { project_id: S.project || (S.L.projects[0] || {}).id, from: today(), to: today() });
  const kp = kindPicker(cfg, preselect);
  return h("div", { class: "panel" }, h("h2", {}, title), h("p", { class: "hint" }, hint), ef,
    h("h3", {}, "What goes in the pack"), kp.el,
    h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const kinds = kp.values();
      if (!kinds.length) return toast("Tick at least one kind of record.", "err");
      downloadPack(await run("team.pack_export", Object.assign(ef.values(), { kinds })));
    } }, "Make the pack file")));
}

/* ── Site mode ── */
PAGES.site = async (root) => {
  const cfg = await siteCfg(true);
  const items = resolve(chosenIds(cfg));
  const pre = new Set(items.map((x) => x.kind).filter(Boolean));
  root.append(h("div", { class: "sitemode" },
    h("div", { style: "display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap" },
      h("h1", {}, "Site mode"),
      h("button", { class: "btn", onclick: () => chooser(cfg, go) }, "⚙ Choose what is here")),
    h("p", { class: "muted" }, S.project ? nm.project(S.project) : "Choose a project at the top first."),
    items.length ? h("div", { class: "bigbtns" }, items.map((x) => h("button", { class: "btn big", onclick: () => { location.hash = x.href; } }, x.label)))
      : h("p", {}, "Nothing chosen yet — press “Choose what is here”."),
    h("p", {}, h("a", { href: "#/p/today" }, "Today's summary"), " · ", h("a", { href: "#/p/control" }, "Control room"), " · ",
      h("a", { href: "#/admin/sync" }, "Site packs history"))));
  if (!cfg.site_code) root.append(h("div", { class: "panel warn" }, h("b", {}, "This computer has no site code yet. "),
    "Give it one in Administration → Remote access (e.g. the project code) before sending packs, so head office can tell sites apart."));
  root.append(packPanel(cfg, pre.size ? pre : new Set(["dpr", "issues", "logsheets"]), "Send this work to head office (site pack)",
    "No internet at site? Make a pack file for the dates, send it by pen drive, e-mail or phone, and head office loads it in Administration → Site packs. "
    + "Only finished records go (drafts stay here). Loading the same pack twice never doubles anything."));
};

/* Today's quick buttons follow the same choice */
window.quickActions = function (big) {
  const items = SITE_CFG ? resolve(chosenIds(SITE_CFG)) : resolve(DEFAULT_ITEMS);
  if (!SITE_CFG) siteCfg().catch(() => {});
  return h("div", { class: big ? "bigbtns" : "quick" }, items.map((x) => h("button", { class: "btn " + (big ? "big" : ""), onclick: () => { location.hash = x.href; } }, (big || !/new=/.test(x.href) ? "" : "+ ") + x.label)));
};

/* "?new=1" on list screens that do not open a new form by themselves: press their “New” button once the
   page is drawn, so a site button goes straight to an empty entry form */
const AUTO_NEW = ["inv/issue", "inv/grn", "inv/mrq", "inv/return", "inv/transfer", "inv/count", "proc/pr", "proc/po",
  "proc/invoices", "eq/logs", "eq/wo"];
function autoNew() {
  const m = /^#\/([^?]+)\?(.*)$/.exec(location.hash || "");
  if (!m || !AUTO_NEW.includes(m[1]) || !/(^|&)new=1(&|$)/.test(m[2])) return;
  const want = location.hash;
  let tries = 0;
  const t = setInterval(() => {
    tries++;
    if (location.hash !== want || tries > 40 || document.querySelector(".overlay")) return clearInterval(t);
    if (tries < 2) return;
    const page = document.getElementById("page");
    const btn = page && [...page.querySelectorAll("button.btn.primary")].find((b) => /^(\+\s*)?(new|report breakdown)\b/i.test(b.textContent.trim()));
    if (btn) { clearInterval(t); btn.click(); }
  }, 200);
}
window.addEventListener("hashchange", autoNew);
setTimeout(autoNew, 1500);

function packCounts(c) {
  const lab = {};
  ((SITE_CFG && SITE_CFG.kinds) || []).forEach((k) => { lab[k.key] = k.label; });
  const one = (o) => Object.entries(o || {}).filter(([, n]) => n).map(([k, n]) => n + " " + (lab[k] || k)).join(", ");
  if (c && (c.added || c.skipped)) {
    const a = one(c.added), sk = one(c.skipped);
    return [a ? "loaded: " + a : "nothing new", sk ? "already here: " + sk : ""].filter(Boolean).join(" · ");
  }
  return one(c) || "—";
}

/* ── Site packs (Administration) ── */
PAGES["admin/sync"] = async (root) => {
  const [i, packs, cfg] = await Promise.all([run("server.info", {}), run("team.packs", {}), siteCfg(true)]);
  root.append(pageHead("Site packs", "Carry site work between two BuildCore computers that cannot reach each other"));
  if (!i.site_code) {
    root.append(h("div", { class: "panel warn" }, h("b", {}, "Name this copy first."),
      h("p", {}, "Give this computer a short code (Administration → Remote access) so packs can never be mixed up. Head office is usually HO; a site is usually the project code."),
      h("button", { class: "btn primary", onclick: () => { location.hash = "#/admin/remote"; } }, "Go to Remote access")));
  }
  const pre = new Set(resolve(chosenIds(cfg)).map((x) => x.kind).filter(Boolean));
  root.append(packPanel(cfg, pre.size ? pre : new Set(cfg.kinds.map((k) => k.key)), "1 · Make a pack (at site)",
    "Choose what to send. Ticked by default: the kinds of work chosen for Site mode. Only finished records go; drafts stay on this computer."));

  const file = h("input", { type: "file", accept: ".bcpack,.json" });
  const out = h("div");
  const label = (labels, k) => (labels && labels[k]) || k;
  root.append(h("div", { class: "panel" }, h("h2", {}, "2 · Load a pack (at head office)"),
    h("p", { class: "hint" }, "Every record is matched by code (material, store, vendor, BOQ item, activity, machine) and loaded once only. "
      + "DPRs arrive as “submitted”; issues, goods received, returns, transfers, stock counts, purchase bills and production runs arrive as drafts — "
      + "check them and post them here, so stock and accounts move in the head-office books. Materials and vendors the site added are created here and listed."),
    h("div", { class: "bar" }, file, h("button", { class: "btn", onclick: async () => {
      if (!file.files[0]) return toast("Choose the pack file first.", "err");
      const text = await file.files[0].text();
      let prev;
      try { prev = await run("team.pack_preview", { pack: text }); } catch (e) { return; }
      out.innerHTML = "";
      const nmx = prev.new_masters || {};
      out.append(kv([["From", (prev.site_name || prev.site_code) + " · made " + (prev.made || "").replace("T", " ")],
        ["Made by", prev.made_by], ["Project", prev.project_code + " " + (prev.project_name || "")], ["Dates", prev.from + " to " + prev.to],
        ["In the pack", Object.entries(prev.counts || {}).map(([k, n]) => n + " " + label(prev.labels, k)).join(", ") || "nothing"],
        ["New here", Object.entries(prev.new || {}).map(([k, n]) => n + " " + label(prev.labels, k)).join(", ") || "nothing new"],
        ["New masters", [(nmx.materials || []).length ? (nmx.materials.length + " materials: " + nmx.materials.slice(0, 10).join(", ")) : "",
          (nmx.parties || []).length ? (nmx.parties.length + " vendors: " + nmx.parties.slice(0, 10).join(", ")) : ""].filter(Boolean).join(" · ") || "none"]]));
      if (!prev.project_known) {
        out.append(h("p", { class: "red" }, "Project " + prev.project_code + " does not exist on this computer. Create it with exactly that code first."));
        return;
      }
      out.append(h("button", { class: "btn primary", onclick: async () => {
        const r = await run("team.pack_import", { pack: text, filename: file.files[0].name },
          (d) => "Loaded " + (Object.entries(d.added).filter(([, n]) => n).map(([k, n]) => n + " " + label(prev.labels, k)).join(", ") || "nothing new"));
        if (r.problems.length) {
          modal("Loaded, with notes", h("div", {}, h("p", {}, "Everything that could be matched was loaded. These need attention:"),
            h("ul", {}, r.problems.map((x) => h("li", {}, x)))), [], {});
        }
        go();
      } }, "Load these records"));
    } }, "Check the file")), out));

  root.append(h("div", { class: "panel" }, h("h2", {}, "History"),
    table([{ label: "When", v: (r) => (r.ts || "").slice(0, 16).replace("T", " ") },
      { label: "Direction", v: (r) => r.direction === "out" ? "made here" : "loaded here" },
      { k: "site_code", label: "Site" }, { label: "Project", v: (r) => nm.pcode(r.project_id) },
      { k: "filename", label: "File" },
      { label: "Records", v: (r) => packCounts(r.counts) },
      { k: "note", label: "Note" }], packs, { search: false, empty: "No packs yet." })));
};

})();
