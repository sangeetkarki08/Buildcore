/* BuildCore Offline — UI toolkit (no external libraries) */
"use strict";

const S = { token: localStorage.getItem("bco_token"), user: null, L: null, project: localStorage.getItem("bco_project") || "" };
const PAGES = {};
const NAV = [];

const IS_DESKTOP = navigator.userAgent.includes("Electron");
const OFFLINE_MSG = IS_DESKTOP ? "Cannot reach the BuildCore engine. Close BuildCore and open it again." : "Cannot reach BuildCore. Check the internet connection and try again.";
let offlineTimer = null;
function showOffline() {
  if ($("#offline")) return;
  document.body.append(h("div", { id: "offline", role: "alert" },
    h("b", {}, "Cannot reach the BuildCore server"),
    IS_DESKTOP
      ? h("p", {}, "The BuildCore engine stopped or the server computer is not reachable. Close BuildCore and open it again. If you connect to another computer, make sure BuildCore is running there.")
      : h("p", {}, "The black BuildCore window must stay open while you work. If you closed it, double-click START_BuildCore_Windows.bat again. If you clicked inside that window, press Esc in it."),
    h("p", { class: "hint" }, "Reconnecting automatically…"),
    h("button", { class: "btn primary", onclick: () => location.reload() }, "Try again now")));
  offlineTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/ping", { cache: "no-store" });
      if (r.ok) { clearInterval(offlineTimer); offlineTimer = null; $("#offline").remove(); toast("Connected again", "ok"); }
    } catch (e) { /* still offline */ }
  }, 3000);
}
async function api(fn, args) {
  let r;
  try {
    r = await fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": S.token || "", "X-Fn": fn },
      body: JSON.stringify({ fn, args: args || {} }),
    });
  } catch (e) {
    showOffline();
    throw new Error(OFFLINE_MSG);
  }
  let j;
  try { j = await r.json(); } catch (e) { throw new Error("The server sent an unexpected reply (HTTP " + r.status + "). The details are in the Vercel logs."); }
  if (!j.ok) {
    if (j.error === "SESSION_EXPIRED") { localStorage.removeItem("bco_token"); S.token = null; location.hash = ""; location.reload(); }
    throw new Error(j.error);
  }
  return j.data;
}
async function run(fn, args, okMsg) {
  try {
    const d = await api(fn, args);
    if (okMsg) toast(typeof okMsg === "function" ? okMsg(d) : okMsg, "ok");
    return d;
  } catch (e) { toast(e.message, "err"); throw e; }
}
async function reloadLookups() { S.L = await api("lookups"); }

/* ── DOM ── */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (s, r) => (r || document).querySelector(s);
function toast(msg, kind) {
  const t = h("div", { class: "toast " + (kind || "") }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "err" ? 7000 : 3500);
}
function stamp(s) { return s ? h("span", { class: "stamp st-" + s }, String(s).replace(/_/g, " ")) : ""; }

/* ── formatting & names ── */
const fmtMoney = (n) => n == null || n === "" ? "" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtQty = (n) => n == null || n === "" ? "" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 3 });
const fmtPct = (n) => n == null ? "—" : n + "%";
const today = () => new Date().toISOString().slice(0, 10);
const monthAgo = () => { const d = new Date(); d.setDate(d.getDate() - 30); return d.toISOString().slice(0, 10); };
const fyStart = () => { const d = new Date(); const y = d.getMonth() > 6 || (d.getMonth() === 6 && d.getDate() >= 16) ? d.getFullYear() : d.getFullYear() - 1; return y + "-07-16"; };
function byId(list, id) { return (list || []).find((x) => String(x.id) === String(id)); }
const nm = {
  project: (id) => { const x = byId(S.L.projects, id); return x ? x.code + " " + x.name : ""; },
  pcode: (id) => (byId(S.L.projects, id) || {}).code || "",
  store: (id) => (byId(S.L.stores, id) || {}).name || "",
  mat: (id) => { const x = byId(S.L.materials, id); return x ? x.code + " " + x.name : ""; },
  unit: (id) => (byId(S.L.materials, id) || {}).unit || "",
  party: (id) => (byId(S.L.parties, id) || {}).name || "",
  acc: (id) => { const x = byId(S.L.accounts, id); return x ? x.code + " " + x.name : ""; },
  eq: (id) => { const x = byId(S.L.equipment, id); return x ? x.code + " " + x.name : ""; },
  boq: (id) => { const x = byId(S.L.boq, id); return x ? x.code + " " + (x.description || "").slice(0, 40) : ""; },
  user: (id) => (byId(S.L.users, id) || {}).name || "",
};
const opt = {
  projects: () => S.L.projects.map((p) => [p.id, p.code + " " + p.name]),
  stores: (pid, withTransit) => S.L.stores.filter((s) => String(s.project_id) === String(pid) && s.active && (withTransit || s.type !== "transit")).map((s) => [s.id, s.name]),
  materials: () => S.L.materials.filter((m) => m.active).map((m) => [m.id, m.code + " " + m.name + " (" + m.unit + ")"]),
  parties: (kinds) => S.L.parties.filter((p) => p.active && (!kinds || kinds.includes(p.kind))).map((p) => [p.id, p.name + (p.blacklisted ? " (blacklisted)" : "")]),
  accounts: (types) => S.L.accounts.filter((a) => a.active && (!types || types.includes(a.type))).map((a) => [a.id, a.code + " " + a.name]),
  money: () => S.L.accounts.filter((a) => a.active && ["cash", "bank"].includes(a.role)).map((a) => [a.id, a.code + " " + a.name]),
  equipment: () => S.L.equipment.filter((e) => e.active).map((e) => [e.id, e.code + " " + e.name]),
  boq: (pid) => S.L.boq.filter((b) => String(b.project_id) === String(pid)).map((b) => [b.id, b.code + " " + (b.description || "").slice(0, 50)]),
  tds: () => S.L.tds.map((t) => [t.id, t.section + " " + t.description + " (" + t.rate + "%)"]),
};
const can = (m, a) => !!(S.user && (S.user.perms[m] || []).includes(a));
function needProject() {
  if (S.project) return true;
  return false;
}
function projectNotice() {
  return h("div", { class: "panel" }, h("b", {}, "Select a project"), h("p", { class: "muted" }, "Choose a project in the bar at the top. Store documents always belong to one project."));
}

/* ── form fields ── */
/* Any list longer than this becomes the searchable picker instead of a plain drop-down,
   so "type cement and pick from what matches" works in filter bars as well as in lines. */
const COMBO_FROM = 8;
function field(f, value, onchange) {
  let input;
  const v = value == null ? (f.default ?? "") : value;
  if (f.type === "select" && !f.readonly) {
    const opts0 = typeof f.options === "function" ? f.options() : f.options;
    if (opts0.length > COMBO_FROM || f.search) {
      const cb = combo(opts0, v, onchange ? () => onchange() : null, { name: f.k, key: f.key || f.k });
      return h("label", { class: "f" + (f.req ? " req" : "") + (f.wide ? " wide" : "") }, h("span", {}, f.label), cb);
    }
  }
  if (f.type === "select") {
    const opts = typeof f.options === "function" ? f.options() : f.options;
    const tbl = f.master || (typeof masterOf === "function" ? masterOf(f.k) : null);
    input = h("select", { name: f.k, disabled: f.readonly }, f.noBlank ? null : h("option", { value: "" }, f.blank || "—"),
      opts.map(([ov, ol]) => h("option", { value: ov, selected: String(ov) === String(v) }, ol)),
      tbl && !f.readonly ? h("option", { value: NEW_VALUE, class: "newopt" }, NEW_TEXT) : null);
    if (tbl && !f.readonly) addCreateOption(input, tbl, onchange);
  } else if (f.type === "textarea") {
    input = h("textarea", { name: f.k, readonly: f.readonly }, v);
  } else if (f.type === "check") {
    input = h("input", { type: "checkbox", name: f.k, checked: Number(v) === 1 || v === true, disabled: f.readonly });
    const lab = h("label", { class: "f check" + (f.wide ? " wide" : "") }, input, f.label);
    if (onchange) input.addEventListener("change", onchange);
    return lab;
  } else {
    input = h("input", { name: f.k, type: f.type || "text", value: v, readonly: f.readonly, step: f.type === "number" ? "any" : null, placeholder: f.ph });
  }
  if (onchange) input.addEventListener("change", onchange);
  return h("label", { class: "f" + (f.req ? " req" : "") + (f.wide ? " wide" : "") }, h("span", {}, f.label), input,
    f.hint ? h("small", { class: "fhint" }, f.hint) : null);
}
function form(fields, values, onchange) {
  const el = h("div", { class: "grid" }, fields.filter((f) => !f.hide).map((f) => field(f, (values || {})[f.k], onchange)));
  el.values = () => {
    const out = {};
    el.querySelectorAll("[name]").forEach((i) => { out[i.name] = i.type === "checkbox" ? (i.checked ? 1 : 0) : i.value; });
    return out;
  };
  el.set = (k, v) => { const i = el.querySelector(`[name="${k}"]`); if (i) { if (i.type === "checkbox") i.checked = !!v; else i.value = v ?? ""; } };
  return el;
}

/* A select that can make its own master. Used by every picker with a short list. */
function addCreateOption(sel, tableName, onchange) {
  let last = sel.value;
  sel.dataset.master = tableName;
  sel.addEventListener("change", async () => {
    if (sel.value !== NEW_VALUE) { last = sel.value; return; }
    sel.value = last;
    const made = await masterDialog(tableName, {});
    if (made) {
      sel.insertBefore(h("option", { value: made.id }, made.label), sel.querySelector("option.newopt"));
      sel.value = made.id; last = sel.value;
      if (onchange) onchange();
    }
    sel.focus();
  });
  sel._createMaster = async () => {
    const made = await masterDialog(tableName, {});
    if (made) {
      sel.insertBefore(h("option", { value: made.id }, made.label), sel.querySelector("option.newopt"));
      sel.value = made.id;
      if (onchange) onchange();
    }
  };
}

/* A row of totals above any list, so the page answers "how much in all?" before the detail. */
function summaryStrip(pairs) {
  return h("div", { class: "sumstrip" }, pairs.filter(Boolean).map(([k, v]) =>
    h("div", {}, h("b", {}, v), h("span", {}, k))));
}

/* Anything shown anywhere can be opened: one link, one place that knows where each record lives. */
function drillTo(kind, id, label) {
  if (!id) return label || "";
  const text = label == null || label === "" ? "#" + id : label;
  return h("a", { class: "drill", href: "#", title: "Open this " + kind,
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); openRecord(kind, id); } }, text);
}
function openRecord(kind, id) {
  const go = (hash) => { location.hash = hash; };
  switch (kind) {
    case "voucher": return typeof voucherView === "function" ? voucherView(id) : go("#/acc/vouchers");
    case "invoice": return typeof docOpen === "function" ? docOpen("invoice", id) : go("#/proc/invoices");
    case "grn": return docOpen("grn", id);
    case "issue": return docOpen("issue", id);
    case "return": return docOpen("return", id);
    case "transfer": return docOpen("transfer", id);
    case "count": return docOpen("count", id);
    case "mrq": return docOpen("mrq", id);
    case "pr": return docOpen("pr", id);
    case "po": return docOpen("po", id);
    case "dpr": return go("#/p/dpr?open=" + id);
    case "ipc": return go("#/p/ipc?open=" + id);
    case "measurement": return go("#/p/measure?open=" + id);
    case "party": return go("#/acc/party?party=" + id);
    case "account": return go("#/acc/ledger?account=" + id);
    case "material": return go("#/inv/card?material=" + id);
    case "equipment": return go("#/eq/register?open=" + id);
    case "boq": return go("#/p/boq?open=" + id);
    case "activity": return go("#/p/schedule?open=" + id);
    case "project": return setProject(id);
    case "payment": return go("#/acc/payments?open=" + id);
    default: return toast("Nothing to open for " + kind + ".", "err");
  }
}

/* ── tables ── */
function cellValue(c, r) {
  const v = typeof c.v === "function" ? c.v(r) : r[c.k];
  if (c.fmt === "money") return fmtMoney(v);
  if (c.fmt === "qty") return fmtQty(v);
  if (c.fmt === "status") return stamp(v);
  if (c.fmt === "yes") return v ? "Yes" : "";
  return v == null ? "" : v;
}
function table(cols, rows, o) {
  o = o || {};
  const num = (c) => ["money", "qty", "num"].includes(c.fmt);
  const body = h("tbody");
  const render = (list) => {
    body.innerHTML = "";
    if (!list.length) body.append(h("tr", {}, h("td", { class: "empty", colspan: cols.length }, o.empty || "Nothing here yet.")));
    list.forEach((r) => body.append(h("tr", { class: (o.onRow ? "click " : "") + (o.rowClass ? o.rowClass(r) || "" : ""), onclick: o.onRow ? () => o.onRow(r) : null },
      cols.map((c) => h("td", { class: num(c) ? "num" : "" }, cellValue(c, r))))));
  };
  render(rows);
  let foot = null;
  if (o.totals) {
    foot = h("tfoot", {}, h("tr", {}, cols.map((c, i) => {
      if (i === 0) return h("td", {}, "Total");
      if (!o.totals.includes(c.k)) return h("td");
      const s = rows.reduce((a, r) => a + Number((typeof c.v === "function" ? c.v(r) : r[c.k]) || 0), 0);
      return h("td", { class: "num" }, c.fmt === "qty" ? fmtQty(s) : fmtMoney(s));
    })));
  }
  const tbl = h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: num(c) ? "num" : "" }, c.label)))), body, foot);
  const wrap = h("div", {});
  if (o.search !== false && rows.length > 8) {
    const box = h("input", { type: "search", placeholder: "Filter these rows", style: "max-width:260px;margin-bottom:8px", oninput: () => {
      const t = box.value.toLowerCase();
      render(rows.filter((r) => cols.some((c) => String(textOf(c, r)).toLowerCase().includes(t))));
    } });
    wrap.append(h("div", { class: "bar" }, box, h("div", { class: "grow" }), h("button", { class: "btn small", onclick: () => exportCsv(o.name || "export", cols, rows, o) }, "Export CSV")));
  } else if (o.export !== false && rows.length) {
    wrap.append(h("div", { class: "bar" }, h("div", { class: "grow" }), h("button", { class: "btn small", onclick: () => exportCsv(o.name || "export", cols, rows, o) }, "Export CSV")));
  }
  wrap.append(h("div", { class: "tablewrap" }, tbl));
  return wrap;
}
function textOf(c, r) {
  const v = cellValue(c, r);
  return v instanceof Node ? v.textContent : v;
}
function exportCsv(name, cols, rows, o) {
  o = o || {};
  const esc = (s) => { s = String(s ?? ""); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const raw = (c, r) => { const v = typeof c.v === "function" ? c.v(r) : r[c.k]; return v instanceof Node ? v.textContent : (c.fmt === "status" ? v : v); };
  const lines = docHeading(o.title || name.replace(/_/g, " "), o.extra).map(([k, v]) => esc(k) + "," + esc(v));
  lines.push("");
  lines.push(cols.map((c) => esc(c.label)).join(","));
  rows.forEach((r) => lines.push(cols.map((c) => esc(raw(c, r))).join(",")));
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv" });
  const a = h("a", { href: URL.createObjectURL(blob), download: name + "_" + today() + ".csv" });
  document.body.append(a); a.click(); a.remove();
}

/* ── line editor ── */
function lineEditor(cols, lines, o) {
  o = o || {};
  const tbody = h("tbody");
  const state = (lines || []).map((l) => ({ ...l }));
  const readonly = !!o.readonly;
  const makeRow = (row) => {
    const tr = h("tr");
    tr._row = row;
    cols.forEach((c) => {
      let el;
      const v = row[c.k];
      if (c.show) {
        el = h("span", { class: c.num ? "num" : "muted" });
        el._update = () => { const x = c.show(row); el.textContent = x == null ? "" : x; };
        el._update();
      } else if (readonly || c.readonly) {
        const txt = c.type === "select" ? ((typeof c.options === "function" ? c.options(row) : c.options).find(([ov]) => String(ov) === String(v)) || [null, ""])[1] : (c.type === "number" ? fmtQty(v) : v);
        el = h("span", {}, txt ?? "");
      } else if (c.type === "select" && (typeof c.options === "function" ? c.options(row) : c.options).length > COMBO_FROM) {
        el = combo(typeof c.options === "function" ? c.options(row) : c.options, v, (nv) => {
          row[c.k] = nv;
          if (c.onChange) c.onChange(row, tr);
          refresh();
          if (c.rerender) rebuild();
        }, { key: c.key || c.k, name: c.k, master: c.master });
        el.style.minWidth = (c.w || 160) + "px";
      } else if (c.type === "select") {
        const opts = typeof c.options === "function" ? c.options(row) : c.options;
        const tbl = c.master || (typeof masterOf === "function" ? masterOf(c.k) : null);
        el = h("select", { name: c.k }, c.noBlank ? null : h("option", { value: "" }, "—"),
          opts.map(([ov, ol]) => h("option", { value: ov, selected: String(ov) === String(v) }, ol)),
          tbl ? h("option", { value: NEW_VALUE, class: "newopt" }, NEW_TEXT) : null);
        if (tbl) {
          addCreateOption(el, tbl, () => {
            row[c.k] = el.value;
            if (c.onChange) c.onChange(row, tr);
            refresh();
            if (c.rerender) rebuild();
          });
        }
      } else {
        el = h("input", { type: c.type || "text", value: v ?? "", step: c.type === "number" ? "any" : null, style: c.w ? "min-width:" + c.w + "px" : null });
      }
      if (el.tagName === "SELECT" || el.tagName === "INPUT") {
        el.addEventListener("change", () => {
          row[c.k] = el.value;
          if (c.onChange) c.onChange(row, tr);
          refresh();
          if (c.rerender) rebuild();
        });
      }
      tr.append(h("td", { class: c.num ? "num" : "", style: c.w ? "min-width:" + c.w + "px" : null }, el));
    });
    if (!readonly && !o.fixed) tr.append(h("td", {}, h("button", { class: "del", title: "Remove line", onclick: () => { state.splice(state.indexOf(row), 1); rebuild(); } }, "×")));
    return tr;
  };
  const refresh = () => {
    tbody.querySelectorAll("span").forEach((s) => s._update && s._update());
    if (o.onChange) o.onChange(state);
  };
  const rebuild = () => { tbody.innerHTML = ""; state.forEach((r) => tbody.append(makeRow(r))); refresh(); };
  tbody.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || readonly || o.fixed || e.target.tagName !== "INPUT") return;
    const tr = e.target.closest("tr");
    if (tr && tr === tbody.lastElementChild) {
      e.preventDefault();
      e.target.dispatchEvent(new Event("change"));
      state.push({ ...(o.blank || {}) });
      rebuild();
      const f = tbody.lastElementChild.querySelector("input,select");
      if (f) f.focus();
    }
  });
  rebuild();
  const wrap = h("div", {},
    h("div", { class: "tablewrap lines" }, h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.num ? "num" : "" }, c.label)), !readonly && !o.fixed ? h("th") : null)), tbody)),
    !readonly && !o.fixed ? h("div", { class: "actions" }, h("button", { class: "btn small", onclick: () => { state.push({ ...(o.blank || {}) }); rebuild(); } }, "Add line")) : null);
  wrap.lines = () => state;
  wrap.setLines = (ls) => { state.splice(0, state.length, ...ls.map((l) => ({ ...l }))); rebuild(); };
  wrap.refresh = refresh;
  wrap.rebuild = rebuild;
  return wrap;
}

/* ── modal & dialogs ── */
function modal(title, body, buttons, o) {
  o = o || {};
  const ov = h("div", { class: "overlay" });
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey); if (o.onClose) o.onClose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  const foot = h("footer", {}, (buttons || []).filter(Boolean).map((b) => h("button", { class: "btn " + (b.cls || ""), disabled: b.disabled, onclick: async (e) => {
    e.target.disabled = true;
    try { const r = await b.act(); if (r !== false && !b.keep) close(); } catch (err) { /* toast already shown */ } finally { e.target.disabled = false; }
  } }, b.label)), h("button", { class: "btn", onclick: close }, "Close"));
  ov.append(h("div", { class: "modal" + (o.narrow ? " narrow" : "") }, h("header", {}, h("h3", {}, title), o.head || null, h("button", { class: "x", onclick: close, "aria-label": "Close" }, "×")), h("div", { class: "body" }, body), foot));
  document.body.append(ov);
  const first = ov.querySelector("input:not([readonly]),select,textarea");
  if (first) first.focus();
  return { close, el: ov };
}
function ask(title, text, o) {
  o = o || {};
  return new Promise((resolve) => {
    let done = false;
    const inp = o.input ? h("textarea", { placeholder: o.input }) : null;
    modal(title, h("div", {}, h("p", {}, text), inp), [{ label: o.ok || "Confirm", cls: o.danger ? "warn" : "primary", act: () => {
      if (inp && o.required && !inp.value.trim()) { toast("Please enter a reason.", "err"); throw new Error("x"); }
      done = true; resolve(inp ? inp.value : true);
    } }], { narrow: true, onClose: () => { if (!done) resolve(null); } });
  });
}

/* ── page scaffolding ── */
function pageHead(title, sub, ...right) {
  return h("div", { class: "bar", style: "align-items:flex-start" }, h("div", { class: "grow" }, h("h1", {}, title), sub ? h("p", { class: "sub" }, sub) : null), right);
}
function filterBar(fields, values, onApply) {
  const f = form(fields, values);
  f.className = "bar";
  f.append(h("button", { class: "btn primary", onclick: () => onApply(f.values()) }, "Show"));
  return f;
}
function kv(pairs) { return h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", {}, k), h("dd", {}, v ?? "")])); }


/* ── one heading for everything that leaves the screen ── */
function docHeading(title, extra) {
  const set = (S.L && S.L.settings) || {};
  const pr = S.project ? (S.L.projects || []).find((x) => String(x.id) === String(S.project)) : null;
  const out = [];
  out.push(["Company", set.company_name || "BuildCore"]);
  if (set.company_address) out.push(["Address", set.company_address]);
  if (set.company_pan) out.push(["PAN / VAT", set.company_pan]);
  out.push(["Project", pr ? pr.code + " — " + pr.name : "All projects"]);
  out.push(["Report", title || ""]);
  (extra || []).forEach((x) => out.push(x));
  out.push(["Printed", new Date().toLocaleString("en-GB") + (S.user ? " by " + S.user.name : "")]);
  return out;
}
const PRINT_CSS = `@font-face{font-family:"BuildCore Sans";src:url(${location.origin}/fonts/BuildCoreSans.ttf)}
  body{font:12.5px "Segoe UI",Arial,"BuildCore Sans",sans-serif;margin:26px;color:#111}
  .hd{border-bottom:2px solid #123;padding-bottom:8px;margin-bottom:12px}
  .hd .co{font-size:19px;font-weight:700}.hd .ad{color:#444}.hd .ti{font-size:15px;font-weight:600;margin-top:6px}
  .hd .pj{color:#234;font-weight:600}.hd .pt{color:#666;font-size:11px;margin-top:2px}
  h1{font-size:16px;margin:0 0 6px}h2{font-size:14px;margin:14px 0 6px}
  table{border-collapse:collapse;width:100%;margin-top:8px}td,th{border:1px solid #999;padding:4px 6px;text-align:left}
  th{background:#eef2ef}.n,.num{text-align:right}
  .meta{display:grid;grid-template-columns:repeat(2,1fr);gap:2px 20px;margin-top:8px}
  .sign{display:flex;justify-content:space-between;margin-top:56px}
  .sign div{border-top:1px solid #333;padding-top:4px;width:28%;text-align:center}
  pre{white-space:pre-wrap;font:inherit}
  .bar,button,input,.tabs,.actions,.qawrap,.searchwrap{display:none !important}
  @media print{@page{margin:12mm}}`;
const escHtml = (s) => String(s ?? "").replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
function headingHtml(title, extra) {
  const set = (S.L && S.L.settings) || {};
  const pr = S.project ? (S.L.projects || []).find((x) => String(x.id) === String(S.project)) : null;
  return `<div class="hd"><div class="co">${escHtml(set.company_name || "BuildCore")}</div>
    <div class="ad">${escHtml(set.company_address || "")}${set.company_pan ? " &nbsp;·&nbsp; PAN " + escHtml(set.company_pan) : ""}</div>
    <div class="pj">${escHtml(pr ? pr.code + " — " + pr.name : "All projects")}</div>
    <div class="ti">${escHtml(title || "")}</div>
    <div class="pt">${escHtml((extra || []).map(([k, v]) => k + ": " + v).join("  ·  "))}${(extra || []).length ? "  ·  " : ""}Printed ${escHtml(new Date().toLocaleString("en-GB"))}${S.user ? " by " + escHtml(S.user.name) : ""}</div></div>`;
}
/* Print anything already on the screen, under the same heading. */
function printFrame(title, node, extra) {
  const w = window.open("", "_blank");
  if (!w) return toast("Allow pop-ups to print.", "err");
  w.document.write(`<html><head><title>${escHtml(title)}</title><style>${PRINT_CSS}</style></head><body>`
    + headingHtml(title, extra) + `<div>${node.innerHTML || node.outerHTML || ""}</div>`
    + `<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

/* ── print ── */
function printDoc(title, meta, cols, rows, totals, note) {
  const set = S.L.settings;
  const w = window.open("", "_blank");
  if (!w) return toast("Allow pop-ups to print.", "err");
  const esc = escHtml;
  const val = (c, r) => { const v = typeof c.v === "function" ? c.v(r) : r[c.k]; return c.fmt === "money" ? fmtMoney(v) : c.fmt === "qty" ? fmtQty(v) : (v instanceof Node ? v.textContent : v); };
  w.document.write(`<html><head><title>${esc(title)}</title><style>${PRINT_CSS}</style></head><body>
    ${headingHtml(title, [])}
    <div class="meta">${meta.map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(v)}</div>`).join("")}</div>
    <table><thead><tr><th>#</th>${cols.map((c) => `<th class="${c.fmt ? "n" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead><tbody>
    ${rows.map((r, i) => `<tr><td>${i + 1}</td>${cols.map((c) => `<td class="${c.fmt ? "n" : ""}">${esc(val(c, r))}</td>`).join("")}</tr>`).join("")}
    </tbody></table>${(totals || []).map(([k, v]) => `<div style="text-align:right;margin-top:4px"><b>${esc(k)}:</b> ${esc(v)}</div>`).join("")}
    ${note ? `<pre>${esc(note)}</pre>` : ""}
    <div class="sign"><div>Prepared by</div><div>Checked by</div><div>Approved by</div></div>
    <script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

/* ── BuildCore 3 UI building blocks ── */
function recentKey(k) { return "bco_recent_" + k; }
function rememberPick(k, v) {
  if (!v) return;
  try {
    const r = JSON.parse(localStorage.getItem(recentKey(k)) || "[]").filter((x) => String(x) !== String(v));
    r.unshift(String(v));
    localStorage.setItem(recentKey(k), JSON.stringify(r.slice(0, 8)));
  } catch (e) { /* ignore */ }
}
function recentFirst(k, opts) {
  let r = [];
  try { r = JSON.parse(localStorage.getItem(recentKey(k)) || "[]"); } catch (e) { r = []; }
  const rank = (v) => { const i = r.indexOf(String(v)); return i < 0 ? 99 : i; };
  return opts.slice().sort((a, b) => rank(a[0]) - rank(b[0]));
}
/* ── the picker ──────────────────────────────────────────────────────────────
   One control for every "choose something" in BuildCore: click it and the whole
   list drops down; type "cement" and the list narrows to the lines that contain
   it, whole words in any order ("opc cem" finds "Cement OPC 43"). Up and down
   move, Enter takes, Esc closes and puts back what was there. Recent choices sit
   at the top. The last line is always "create a new one", so a storekeeper
   filling a goods receipt never has to leave the line to add a material. */
let comboSeq = 0;
const NEW_TEXT = "＋ Create new…";
function comboMatch(label, term) {
  if (!term) return true;
  const hay = String(label).toLowerCase();
  return term.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}
function comboMark(label, term) {
  const words = (term || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [String(label)];
  const hay = String(label);
  const hits = [];
  words.forEach((w) => {
    let from = 0, at;
    while ((at = hay.toLowerCase().indexOf(w, from)) >= 0) { hits.push([at, at + w.length]); from = at + w.length; }
  });
  hits.sort((a, b) => a[0] - b[0]);
  const out = [];
  let cur = 0;
  hits.forEach(([s, e]) => {
    if (s < cur) return;
    if (s > cur) out.push(hay.slice(cur, s));
    out.push(h("b", {}, hay.slice(s, e)));
    cur = e;
  });
  if (cur < hay.length) out.push(hay.slice(cur));
  return out;
}
function combo(opts, value, onchange, o) {
  o = o || {};
  const key = o.key || "x";
  const all = () => opts;
  opts = recentFirst(key, opts);
  const nRecent = (() => {
    let r = [];
    try { r = JSON.parse(localStorage.getItem(recentKey(key)) || "[]"); } catch (e) { r = []; }
    return opts.filter(([v]) => r.includes(String(v))).length;
  })();
  const table = o.master || (typeof masterOf === "function" ? masterOf(o.name || o.key) : null);
  const labelOf = (v) => (opts.find(([ov]) => String(ov) === String(v)) || [null, ""])[1];
  const hidden = h("input", { type: "hidden", name: o.name || null, value: value ?? "" });
  const inp = h("input", { class: "cbin", value: labelOf(value), placeholder: o.ph || "Type to search…",
    autocomplete: "off", readonly: o.readonly, role: "combobox", "aria-expanded": "false", "aria-autocomplete": "list" });
  const caret = h("button", { type: "button", class: "cbcaret", tabindex: -1, title: "Show the list", "aria-label": "Show the list" }, "▾");
  // the list lives on <body> so a scrolling table or a dialog cannot clip it
  const menu = h("div", { class: "cbmenu", hidden: true, role: "listbox" });
  const wrap = h("span", { class: "combo" }, inp, caret, hidden);
  if (table && !o.readonly) wrap.dataset.master = table;
  let shown = [], cur = -1, open = false, typed = "";

  const take = (id2, label) => {
    hidden.value = id2 == null ? "" : id2;
    inp.value = label || "";
    if (id2) rememberPick(key, id2);
    close();
    if (onchange) onchange(hidden.value);
  };
  const create = async (text) => {
    close();
    if (!table) return;
    const spec = (typeof MASTERS_UI !== "undefined" && MASTERS_UI[table]) || {};
    const guess = {};
    if (text && text !== NEW_TEXT) guess[spec.nameField || "name"] = text;
    const made = await masterDialog(table, guess);
    if (made) { opts.push([made.id, made.label]); take(made.id, made.label); }
    else { inp.value = labelOf(hidden.value); }
    inp.focus();
  };

  function close() {
    open = false; cur = -1; menu.hidden = true; menu.innerHTML = "";
    menu.remove();
    window.removeEventListener("scroll", place, true);
    window.removeEventListener("resize", place);
    inp.setAttribute("aria-expanded", "false");
    wrap.classList.remove("on");
  }
  function place() {
    if (!open) return;
    const r = inp.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) return close();
    const below = window.innerHeight - r.bottom - 8, above = r.top - 8;
    const up = below < 190 && above > below;
    const space = Math.max(120, Math.min(300, up ? above : below));
    // as wide as the box, and wider if the names need it, without running off the screen
    menu.style.minWidth = Math.max(r.width, 240) + "px";
    menu.style.maxWidth = Math.max(260, window.innerWidth - r.left - 14) + "px";
    menu.style.maxHeight = space + "px";
    menu.style.left = Math.max(4, Math.min(r.left, window.innerWidth - menu.offsetWidth - 6)) + "px";
    if (up) { menu.style.top = "auto"; menu.style.bottom = (window.innerHeight - r.top + 2) + "px"; }
    else { menu.style.bottom = "auto"; menu.style.top = (r.bottom + 2) + "px"; }
  }
  function paint() {
    menu.innerHTML = "";
    shown = opts.filter(([, l]) => comboMatch(l, typed));
    if (!shown.length) {
      menu.append(h("div", { class: "cbnone" }, typed ? "Nothing matches “" + typed + "”" : "The list is empty"));
    }
    shown.forEach(([v, l], i) => {
      const row = h("div", { class: "cbopt" + (i === cur ? " on" : ""), role: "option", "data-i": i,
        title: l }, comboMark(l, typed));
      if (!typed && nRecent && i < nRecent) row.append(h("span", { class: "cbtag" }, "recent"));
      if (String(v) === String(hidden.value) && hidden.value !== "") row.classList.add("sel");
      row.addEventListener("mousedown", (e) => { e.preventDefault(); take(v, l); });
      row.addEventListener("mousemove", () => { if (cur !== i) { cur = i; hi(); } });
      menu.append(row);
    });
    if (table && !o.readonly) {
      const ci = shown.length;
      const row = h("div", { class: "cbopt cbnew" + (ci === cur ? " on" : ""), role: "option", "data-i": ci },
        typed && !shown.some(([, l]) => l.toLowerCase() === typed.toLowerCase()) ? "＋ Create “" + typed + "”" : NEW_TEXT);
      row.addEventListener("mousedown", (e) => { e.preventDefault(); create(typed); });
      row.addEventListener("mousemove", () => { if (cur !== ci) { cur = ci; hi(); } });
      menu.append(row);
    }
    menu.append(h("div", { class: "cbfoot" }, shown.length + " of " + opts.length + " · ↑↓ move · Enter choose · Esc close"));
  }
  function hi() {
    menu.querySelectorAll(".cbopt").forEach((e, i) => e.classList.toggle("on", i === cur));
    const el = menu.querySelector(".cbopt.on");
    if (el) el.scrollIntoView({ block: "nearest" });
  }
  function mount() {
    if (!menu.isConnected) document.body.append(menu);
    menu.hidden = false; open = true; wrap.classList.add("on");
    inp.setAttribute("aria-expanded", "true");
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
  }
  function show(withText) {
    if (o.readonly) return;
    typed = withText ? inp.value.trim() : "";
    mount();
    paint();
    cur = shown.findIndex(([v]) => String(v) === String(hidden.value));
    if (cur < 0) cur = shown.length ? 0 : -1;
    hi(); place();
  }

  inp.addEventListener("focus", () => { if (!open) show(false); inp.select(); });
  inp.addEventListener("mousedown", () => { if (!open) setTimeout(() => show(false), 0); });
  caret.addEventListener("mousedown", (e) => { e.preventDefault(); if (open) { close(); } else { inp.focus(); show(false); } });
  inp.addEventListener("input", () => { typed = inp.value.trim(); mount(); paint(); cur = shown.length ? 0 : (table ? 0 : -1); hi(); place(); });
  inp.addEventListener("keydown", (e) => {
    const last = shown.length - (table && !o.readonly ? 0 : 1);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return show(false);
      cur = Math.max(0, Math.min(last, cur + (e.key === "ArrowDown" ? 1 : -1)));
      hi();
    } else if (e.key === "PageDown" || e.key === "PageUp") {
      if (!open) return;
      e.preventDefault();
      cur = Math.max(0, Math.min(last, cur + (e.key === "PageDown" ? 8 : -8)));
      hi();
    } else if (e.key === "Enter") {
      if (!open) return;
      e.preventDefault(); e.stopPropagation();
      if (cur >= 0 && cur < shown.length) take(shown[cur][0], shown[cur][1]);
      else if (table) create(typed);
    } else if (e.key === "Escape") {
      if (!open) return;
      e.preventDefault(); e.stopPropagation();
      inp.value = labelOf(hidden.value); close();
    } else if (e.key === "Tab") {
      if (open && cur >= 0 && cur < shown.length && typed) take(shown[cur][0], shown[cur][1]);
      else close();
    } else if (e.key === "Delete" && e.ctrlKey) {
      e.preventDefault(); take("", "");
    }
  });
  inp.addEventListener("blur", () => setTimeout(() => {
    if (!open) return;
    close();
    // leaving the box: keep an exact or single match, otherwise put back what was there
    const t = inp.value.trim();
    if (!t) return take("", "");
    const exact = opts.find(([, l]) => l.toLowerCase() === t.toLowerCase());
    const hits = opts.filter(([, l]) => comboMatch(l, t));
    if (exact) take(exact[0], exact[1]);
    else if (hits.length === 1) take(hits[0][0], hits[0][1]);
    else inp.value = labelOf(hidden.value);
  }, 120));

  wrap._createMaster = () => create(inp.value.trim());
  wrap._alterMaster = () => {
    if (!table || !hidden.value) return toast("Choose something first, then Alt+A to open it.", "err");
    location.hash = "#/m/" + (table === "boq_items" ? "boq" : table);
  };
  wrap._setOptions = (list) => { opts = recentFirst(key, list); if (open) paint(); else inp.value = labelOf(hidden.value); };
  wrap._options = all;
  Object.defineProperty(wrap, "value", { get: () => hidden.value, set: (v) => { hidden.value = v ?? ""; inp.value = labelOf(v); } });
  wrap.input = inp;
  wrap.focus = () => inp.focus();
  return wrap;
}
function drawer(title, body, buttons, o) {
  const m = modal(title, body, buttons, Object.assign({}, o || {}));
  m.el.classList.add("drawer");
  return m;
}
function tabs(defs, start) {
  const bar = h("div", { class: "tabs" });
  const body = h("div");
  const show = async (i) => {
    bar.querySelectorAll("button").forEach((b, j) => b.classList.toggle("on", i === j));
    body.innerHTML = "";
    const r = await defs[i][1]();
    if (r) body.append(r);
  };
  defs.forEach(([t], i) => bar.append(h("button", { type: "button", onclick: () => show(i) }, t)));
  show(start || 0);
  return h("div", {}, bar, body);
}
const fileUrl = (id) => "/files/" + id + "?token=" + encodeURIComponent(S.token);
async function uploadFiles(files, meta) {
  let n = 0;
  for (const f of files) {
    const qs = new URLSearchParams(Object.assign({ filename: f.name, mime: f.type || "" }, meta || {}));
    [...qs.keys()].forEach((k) => { const v = qs.get(k); if (v === "" || v === "null" || v === "undefined") qs.delete(k); });
    const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: f });
    const j = await r.json();
    if (!j.ok) { toast(f.name + ": " + j.error, "err"); continue; }
    n++;
  }
  if (n) toast(n + " file(s) saved", "ok");
  return n;
}
function uploadButton(meta, done, label, accept) {
  const inp = h("input", { type: "file", multiple: true, accept: accept || null, style: "display:none", onchange: async () => { await uploadFiles([...inp.files], meta); inp.value = ""; if (done) done(); } });
  return h("span", {}, inp, h("button", { class: "btn small", type: "button", onclick: () => inp.click() }, label || "Attach files"));
}
function fileList(rows, reload) {
  if (!rows.length) return h("p", { class: "muted" }, "No files yet.");
  const photos = rows.filter((f) => f.kind === "photo");
  const docs = rows.filter((f) => f.kind !== "photo");
  return h("div", {},
    photos.length ? h("div", { class: "gallery" }, photos.map((f) => h("figure", {}, h("a", { href: fileUrl(f.id), target: "_blank" }, h("img", { src: fileUrl(f.id), alt: f.caption || f.filename, loading: "lazy" })),
      h("figcaption", {}, (f.date || "") + " " + (f.caption || f.location || ""))))) : null,
    docs.length ? table([{ label: "File", v: (f) => h("a", { href: fileUrl(f.id), target: "_blank" }, f.filename) }, { k: "date", label: "Date" }, { k: "caption", label: "Note" }, { label: "Size", v: (f) => Math.round(f.size / 1024) + " KB" },
      { label: "", v: (f) => h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); if (await ask("Delete file", "Delete " + f.filename + "?", { danger: true })) { await run("files.delete", { id: f.id }, "Deleted"); if (reload) reload(); } } }, "Delete") }], docs, { search: false, export: false }) : null);
}
/* Documents | Comments | History panel for any record */
function recordPanel(entity, id, meta) {
  if (!id) return h("p", { class: "hint" }, "Save first to attach documents and comments.");
  const docs = async () => {
    const box = h("div");
    const load = async () => { box.innerHTML = ""; const rows = await api("files.list", { entity, entity_id: id }); box.append(uploadButton(Object.assign({ entity, entity_id: id }, meta || {}), load), fileList(rows, load)); };
    await load();
    return box;
  };
  const comm = async () => {
    const box = h("div");
    const load = async () => {
      const d = await api("comments.list", { entity, entity_id: id });
      box.innerHTML = "";
      const ta = h("textarea", { placeholder: "Add a comment" });
      box.append(h("div", { class: "comments" }, d.comments.map((x) => h("div", { class: "comment" }, h("b", {}, nm.user(x.user_id)), h("span", { class: "hint" }, " " + (x.ts || "").replace("T", " ")), h("p", {}, x.text)))),
        ta, h("button", { class: "btn small", onclick: async () => { await run("comments.add", { entity, entity_id: id, text: ta.value }); load(); } }, "Add comment"));
    };
    await load();
    return box;
  };
  const hist = async () => {
    const d = await api("comments.list", { entity, entity_id: id });
    return table([{ k: "ts", label: "When", v: (r) => (r.ts || "").replace("T", " ") }, { label: "Who", v: (r) => nm.user(r.user_id) }, { k: "action", label: "Action" }, { label: "Detail", v: (r) => (r.detail || "").slice(0, 120) }], d.history, { search: false, export: false, empty: "No history." });
  };
  return tabs([["Documents & photos", docs], ["Comments", comm], ["History", hist]]);
}
/* Simple SVG line chart: series = [{name, color, values}], labels = x labels */
function lineChart(labels, series, o) {
  o = o || {};
  const W = 720, H = o.height || 220, P = 34;
  const all = series.flatMap((s) => s.values.filter((v) => v != null));
  const max = o.max || Math.max(1, ...all);
  const x = (i) => P + (W - 2 * P) * (labels.length > 1 ? i / (labels.length - 1) : 0);
  const y = (v) => H - P - (H - 2 * P) * (v / max);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "chart");
  let inner = "";
  for (let g = 0; g <= 4; g++) { const gv = max * g / 4; inner += `<line x1="${P}" x2="${W - P}" y1="${y(gv)}" y2="${y(gv)}" class="grid"/><text x="4" y="${y(gv) + 4}" class="ax">${Math.round(gv)}${o.unit || ""}</text>`; }
  const step = Math.max(1, Math.ceil(labels.length / 8));
  labels.forEach((l, i) => { if (i % step === 0 || i === labels.length - 1) inner += `<text x="${x(i)}" y="${H - 10}" class="ax" text-anchor="middle">${l}</text>`; });
  series.forEach((s) => {
    const pts = s.values.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
    inner += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2.5" ${s.dash ? 'stroke-dasharray="6 4"' : ""}/>`;
  });
  svg.innerHTML = inner;
  return h("div", {}, svg, h("div", { class: "legend" }, series.map((s) => h("span", {}, h("i", { style: "background:" + s.color }), s.name))));
}
function progressBar(planned, actual) {
  return h("div", { class: "pbar", title: "Planned " + planned + "% / actual " + actual + "%" },
    h("i", { class: "pl", style: "width:" + Math.min(planned, 100) + "%" }), h("i", { class: "ac" + (actual + 0.5 < planned ? " late" : ""), style: "width:" + Math.min(actual, 100) + "%" }));
}
const LEVEL_TEXT = { ok: "Good", attention: "Attention", critical: "Critical" };
function levelStamp(l) { return h("span", { class: "stamp lv-" + l }, LEVEL_TEXT[l] || l); }
const fmtN = (n, d) => n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d ?? 2 });
