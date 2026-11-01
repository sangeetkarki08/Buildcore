/* Working fast: create a master without leaving the line you are on, and a keyboard
   layout that follows Tally so an accountant does not have to learn a new one. */
"use strict";

/* ── which master sits behind each field ───────────────────────────────────── */
const FIELD_MASTER = {
  material_id: "materials", party_id: "parties", vendor_id: "parties", client_id: "parties",
  supplier_id: "parties", subcontractor_id: "parties", account_id: "accounts", boq_item_id: "boq_items",
  activity_id: "activities", wbs_id: "wbs", equipment_id: "equipment", trade_id: "trades",
  store_id: "stores", project_id: "projects", staff_id: "staff", group_id: "account_groups",
  from_store: "stores", to_store: "stores", plant_id: "plants", asset_id: "assets",
};
const MASTER_LABEL = {
  materials: "material", parties: "vendor or client", accounts: "account", boq_items: "BOQ item",
  activities: "activity", wbs: "WBS item", equipment: "machine", trades: "labour trade",
  stores: "store", projects: "project", staff: "staff member", account_groups: "account group",
  plants: "plant", assets: "asset",
};
const NEW_VALUE = "__new__";

function masterOf(key) {
  return key ? FIELD_MASTER[key] : null;
}

/* Opens the ordinary master form in a dialog and hands back the record it created. */
function masterDialog(tableName, prefill) {
  return new Promise((resolve) => {
    const o = (typeof MASTERS_UI !== "undefined" && MASTERS_UI[tableName]) || null;
    if (!o) { toast("This list is not one you can add to here.", "err"); return resolve(null); }
    if (!can(o.module || "masters", "edit")) { toast("Your role cannot add a " + (o.single || tableName) + ".", "err"); return resolve(null); }
    if (o.byProject && !S.project) { toast("Choose a project first.", "err"); return resolve(null); }
    const fields = (typeof o.fields === "function" ? o.fields(null) : o.fields);
    const f = form(fields, Object.assign({ active: 1 }, o.defaults ? o.defaults() : {}, prefill || {}));
    let made = null;
    modal("New " + (o.single || tableName), h("div", {},
      h("p", { class: "hint" }, "Added straight into the list you were filling in. Alt+C opens this from any picker."), f),
      [{ label: "Save", cls: "primary", act: async () => {
        const v = f.values();
        if (o.byProject) v.project_id = S.project;
        const r = await run("master.save", { table: tableName, row: v }, "Saved");
        await reloadLookups();
        if (typeof loadProjectLists === "function" && ["activities", "wbs", "trades"].includes(tableName)) {
          await loadProjectLists();
        }
        made = { id: r.id, label: labelForMaster(tableName, Object.assign({ id: r.id }, v)) };
      } }], { narrow: !o.wide, onClose: () => resolve(made) });
  });
}

function labelForMaster(tableName, row) {
  const name = row.name || row.description || row.code || "";
  return row.code && name !== row.code ? row.code + " " + name : String(name || row.code || "");
}

/* ── the keyboard, laid out the way Tally does it ─────────────────────────── */
const KEYMAP = [
  ["Go to — jump to any screen, record or new document", "Alt+G  /  Ctrl+G"],
  ["Search everything", "Ctrl+F"],
  ["Create the master you are standing on (material, party, account…)", "Alt+C"],
  ["Open (alter) the master you are standing on", "Alt+A"],
  ["Accept — save the form that is open", "Ctrl+A"],
  ["Back / close without saving", "Esc  /  Ctrl+Q"],
  ["New record on this screen", "Alt+N"],
  ["Print", "Ctrl+P"],
  ["Export to CSV", "Ctrl+E"],
  ["Delete or cancel the record that is open", "Alt+D  /  Alt+X"],
  ["Change the dates of this report", "F2"],
  ["Change project", "F3"],
  ["Stock transfer", "F4"],
  ["Payment", "F5"],
  ["Receipt", "F6"],
  ["Journal voucher", "F7"],
  ["Client invoice / IPC", "F8"],
  ["Purchase bill", "F9"],
  ["Daily progress report", "F10"],
  ["Goods receipt (receipt note)", "Alt+F9"],
  ["Purchase order", "Ctrl+F9"],
  ["Material issue (delivery note)", "Alt+F8"],
  ["Material requisition", "Alt+F7"],
  ["Stock count (physical stock)", "Ctrl+F7"],
  ["Measurement sheet", "Alt+F6"],
  ["Plant production run", "Alt+F10"],
  ["Machine logsheet for the month", "Alt+F11"],
  ["New asset", "Ctrl+F10"],
  ["Settings (company features)", "F11"],
  ["This help", "F1"],
];
const GOTO_KEYS = { F2: "period", F3: "project" };
const DOC_KEYS = {
  F4: ["#/inv/transfer?new=1", "Stock transfer"], F5: ["#/acc/payments?new=pay", "Payment"],
  F6: ["#/acc/payments?new=receive", "Receipt"], F7: ["#/acc/vouchers?new=1", "Journal voucher"],
  F8: ["#/p/ipc?new=1", "Client billing"], F9: ["#/proc/invoices?new=1", "Purchase bill"],
  F10: ["#/p/dpr?new=1", "Daily progress report"], F11: ["#/admin/settings", "Settings"],
  "Alt+F9": ["#/inv/grn?new=1", "Goods receipt"], "Ctrl+F9": ["#/proc/po?new=1", "Purchase order"],
  "Alt+F8": ["#/inv/issue?new=1", "Material issue"], "Alt+F7": ["#/inv/mrq?new=1", "Requisition"],
  "Ctrl+F7": ["#/inv/count?new=1", "Stock count"], "Alt+F6": ["#/p/measure?new=1", "Measurement"],
  "Alt+F10": ["#/pl/runs?new=1", "Plant production run"], "Ctrl+F10": ["#/as/register?new=1", "Asset"],
  "Alt+F11": ["#/eq/books", "Machine logsheets"],
};

function keyName(e) {
  const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  return (e.ctrlKey || e.metaKey ? "Ctrl+" : "") + (e.altKey ? "Alt+" : "") + k;
}
const typing = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");

/* The dialog on top wins: Ctrl+A presses its primary button, Esc closes it. */
function topModal() {
  const all = document.querySelectorAll(".overlay");
  return all.length ? all[all.length - 1] : null;
}
function clickIn(root, re, cls) {
  const btns = [...(root || document).querySelectorAll("button")];
  const hit = btns.find((b) => (cls ? b.classList.contains(cls) : true) && re.test(b.textContent.trim()));
  if (hit && !hit.disabled) { hit.click(); return true; }
  return false;
}

function handleKey(e) {
  const k = keyName(e);
  const mod = topModal();
  const inField = typing(e.target);

  if (k === "Alt+C" || k === "Alt+A") {
    const cell = e.target.closest(".combo, label.f, td");
    const hidden = cell && cell.querySelector("input[type=hidden], select");
    const fieldKey = (hidden && (hidden.name || hidden.dataset.k)) || (e.target && e.target.name);
    const tableName = masterOf(fieldKey) || (cell && cell.dataset && masterOf(cell.dataset.master));
    if (tableName) {
      e.preventDefault();
      if (k === "Alt+C" && cell && cell._createMaster) return cell._createMaster();
      if (k === "Alt+A" && cell && cell._alterMaster) return cell._alterMaster();
      e.preventDefault();
      masterDialog(tableName, {});
      return;
    }
  }
  if (inField && !e.altKey && !e.ctrlKey && !e.metaKey && !/^F\d+$/.test(e.key)) return;

  switch (k) {
    case "F1":
      e.preventDefault(); return shortcutHelp();
    case "Alt+G": case "Ctrl+G":
      e.preventDefault(); return goTo();
    case "Ctrl+F":
      e.preventDefault(); { const s = $(".searchwrap input"); if (s) { s.focus(); s.select(); } } return;
    case "Ctrl+A":
      if (mod) { e.preventDefault(); clickIn(mod.querySelector("footer"), /.+/, "primary"); }
      return;
    case "Ctrl+Q":
      if (mod) { e.preventDefault(); clickIn(mod.querySelector("footer"), /^Close$/); }
      return;
    case "Alt+N":
      e.preventDefault();
      if (!clickIn($("#page"), /^\+?\s*New\b/)) toast("Nothing to add on this screen.", "err");
      return;
    case "Ctrl+P":
      e.preventDefault();
      if (mod && clickIn(mod.querySelector("footer"), /^Print/)) return;
      if (clickIn($("#page"), /^Print/)) return;
      printPage();
      return;
    case "Ctrl+E":
      e.preventDefault();
      if (!clickIn(mod || $("#page"), /Export CSV/)) toast("Nothing to export on this screen.", "err");
      return;
    case "Alt+D": case "Alt+X":
      if (mod) { e.preventDefault(); clickIn(mod.querySelector("footer"), /^(Delete|Cancel|Reverse|Void)/); }
      return;
    case "F2": {
      e.preventDefault();
      const from = $("#page input[name=from]") || $("#page input[type=date]");
      if (from) { from.focus(); from.select && from.select(); } else toast("This screen has no date filter.", "err");
      return;
    }
    case "F3":
      e.preventDefault(); { const sel = $("#projsel"); if (sel) sel.focus(); } return;
    default:
      if (DOC_KEYS[k]) {
        e.preventDefault();
        location.hash = DOC_KEYS[k][0];
        toast(DOC_KEYS[k][1], "ok");
      }
  }
}

function shortcutHelp() {
  if ($(".overlay .keyhelp")) return;
  const rows = KEYMAP.map(([what, keys]) => h("tr", {}, h("td", {}, what), h("td", { class: "kbd" }, keys)));
  modal("Keyboard — the same keys as Tally",
    h("div", { class: "keyhelp" },
      h("p", { class: "hint" }, "Alt+C on any picker makes the master there and then, so you never have to leave "
        + "what you are entering. Press Esc to close this."),
      h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, rows)))), [], {});
}

/* Go to: one box that reaches every screen, every record and every new document. */
function goTo() {
  if ($(".overlay .gotobox")) return;
  const inp = h("input", { type: "search", placeholder: "Type a screen, a record, or “new payment”…", autocomplete: "off" });
  const list = h("div", { class: "gotolist" });
  const pages = [];
  (typeof MENU !== "undefined" ? MENU : []).forEach(([group, module, items]) => {
    if (module && !can(module, "view")) return;
    items.forEach(([path, label, mod]) => {
      if ((mod && !can(mod, "view")) || !PAGES[path]) return;
      pages.push({ group: group, label: label, hash: "#/" + path });
    });
  });
  Object.entries(DOC_KEYS).forEach(([k, [hash, label]]) => pages.push({ group: "New", label: "New " + label.toLowerCase(), hash, key: k }));

  const draw = async () => {
    const term = inp.value.trim().toLowerCase();
    list.innerHTML = "";
    const hits = pages.filter((p) => !term || (p.label + " " + p.group).toLowerCase().includes(term)).slice(0, 12);
    hits.forEach((p, i) => list.append(h("a", { href: p.hash, class: i === 0 ? "on" : "", onclick: () => m.close() },
      h("b", {}, p.label), h("span", {}, p.group), p.key ? h("i", { class: "kbd" }, p.key) : null)));
    if (term.length >= 2) {
      let rows = [];
      try { rows = await api("search", { q: term, project_id: S.project || null }); } catch (e) { rows = []; }
      rows.slice(0, 14).forEach((r) => list.append(h("a", { href: r.link, onclick: () => {
        if (r.project_id) setProject(r.project_id, true);
        m.close();
      } }, h("b", {}, r.label), h("span", {}, r.group + (r.sub ? " · " + r.sub : "")))));
      if (rows.length > 14) {
        list.append(h("a", { href: "#/search?q=" + encodeURIComponent(term), onclick: () => m.close() },
          h("b", {}, "See all " + rows.length + " matches"), h("span", {}, "Search results")));
      }
    }
    if (!list.children.length) list.append(h("div", { class: "hint" }, "Nothing matches “" + term + "”."));
  };
  let timer = null;
  inp.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(draw, 160); });
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { const a = list.querySelector("a"); if (a) { e.preventDefault(); a.click(); location.hash = a.getAttribute("href"); } }
  });
  const m = modal("Go to", h("div", { class: "gotobox" }, inp, list), [], { narrow: true });
  draw();
  setTimeout(() => inp.focus(), 30);
}

/* Print whatever is on screen, with the company heading on top. */
function printPage() {
  const page = $("#page");
  if (!page) return;
  const title = (page.querySelector("h1") || {}).textContent || document.title;
  printFrame(title, page.cloneNode(true));
}

document.addEventListener("keydown", (e) => {
  try { handleKey(e); } catch (err) { /* a shortcut must never break the screen */ }
});
