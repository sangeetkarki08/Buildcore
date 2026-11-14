/* BuildCore 2.7 — work like Tally.
   1. Every list: tick rows (Space, Ctrl+Space, Shift+Space, click the box, Ctrl/Shift+click), move with ↑ ↓,
      open with Enter, hide rows (Alt+R) and bring them back (Alt+U), filter on several conditions (Alt+F12)
      and by ticking values (Ctrl+F12), then print (Alt+P), export (Alt+E) or — administrator — delete (Alt+D)
      just the ticked rows.
   2. Tally's voucher keys (F4 contra … Ctrl+F9 debit note), the other Alt / Ctrl keys, a calculator (Ctrl+N),
      and the Gateway letters (DD day book, DAL ledger, ALC create ledger, ALA alter ledger …).
   Nothing here replaces a screen; it sits on top of all of them. */
(function () {
  "use strict";
  const LS = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSset = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } };

  const css = document.createElement("style");
  css.textContent = [
    ".klist tbody tr.kf>td{background:#fff4cc!important}",
    ".klist tbody tr.ks>td{background:#dcebf8!important}",
    ".klist tbody tr.ks.kf>td{background:#cfe2f5!important}",
    ".klist td.kc,.klist th.kc{width:24px;min-width:24px;text-align:center;padding-left:6px!important;padding-right:0!important}",
    ".klist td.kc input,.klist th.kc input{margin:0;cursor:pointer;width:auto}",
    ".klist:focus{outline:none}",
    ".kbar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}",
    ".kbar input[type=search]{max-width:240px;margin:0}",
    ".kchip{display:inline-flex;gap:6px;align-items:center;background:#eef3f8;border:1px solid #cdd9e5;border-radius:12px;padding:1px 4px 1px 9px;font-size:12px;white-space:nowrap}",
    ".kchip button{border:0;background:none;cursor:pointer;font-size:14px;line-height:1;padding:0 4px;color:#555}",
    ".kbulk{display:inline-flex;gap:6px;align-items:center;background:#fff4cc;border:1px solid #ecd58a;border-radius:6px;padding:2px 6px;font-size:13px}",
    ".kcount{font-size:12px;color:var(--muted,#6b7280)}",
    ".kgate{position:fixed;right:18px;bottom:18px;z-index:9998;background:#1f2d3d;color:#fff;border-radius:8px;padding:8px 12px;font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.25);max-width:320px}",
    ".kgate b{font-family:monospace;font-size:15px;letter-spacing:2px;color:#ffd666}.kgate div{opacity:.85;margin-top:2px}",
    ".kcalc{position:fixed;left:18px;bottom:18px;z-index:9999;background:var(--panel,#fff);border:1px solid var(--line,#ccc);border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:10px;width:280px;font-size:13px}",
    ".kcalc h4{margin:0 0 6px;display:flex;justify-content:space-between}.kcalc h4 button{border:0;background:none;cursor:pointer;font-size:16px}",
    ".kcalc .hist{max-height:150px;overflow:auto;font-family:monospace;margin-bottom:6px}.kcalc .hist div{display:flex;justify-content:space-between;gap:8px}",
    ".kcalc input{width:100%;font-family:monospace;font-size:15px}",
    ".kvlist a{display:flex;gap:10px;align-items:center;padding:6px 8px;border-radius:5px;cursor:pointer;text-decoration:none;color:inherit}",
    ".kvlist a.on,.kvlist a:hover{background:#dcebf8}.kvlist a i{font-style:normal;font-family:monospace;font-weight:700;width:18px;color:#1f6fb2}",
    ".khelp h4{margin:12px 0 4px}.khelp td.kbd{white-space:nowrap;font-family:monospace}",
    ".kcond{display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap}.kcond select,.kcond input{width:auto;min-width:90px;margin:0}",
    ".kvals{max-height:320px;overflow:auto;border:1px solid var(--line,#ddd);border-radius:6px;padding:6px}.kvals label{display:flex;gap:8px;align-items:center;padding:2px 0}.kvals label input{width:auto}",
    ".klist [hidden],.kcond [hidden],.kbulk[hidden],.kconf [hidden]{display:none!important}",
    "@media print{.kc,.kbar{display:none!important}}",
  ].join("");
  document.head.append(css);

  /* ───────────────────────────── admin: which lists can be deleted from ───────────────────────────── */
  const ADM = { uid: null, p: null };
  function admKinds() {
    if (typeof S === "undefined" || !S.user || S.user.role !== "admin") return Promise.resolve(new Set());
    if (ADM.uid !== S.user.id || !ADM.p) {
      ADM.uid = S.user.id;
      ADM.p = api("adm.kinds", {}).then((r) => new Set(r.kinds || [])).catch(() => { ADM.p = null; return new Set(); });
    }
    return ADM.p;
  }
  window.bcoAdmKinds = admKinds;

  /* ───────────────────────────── the list ───────────────────────────── */
  const NUMF = ["money", "qty", "num"];
  const isNum = (c) => NUMF.includes(c.fmt);
  const rawOf = (c, r) => { const v = typeof c.v === "function" ? c.v(r) : r[c.k]; return v instanceof Node ? v.textContent : v; };
  const shown = (c, r) => { const v = cellValue(c, r); return v instanceof Node ? v.textContent : (v == null ? "" : String(v)); };
  const bsIn = (x) => {                      // a BS date typed into a filter is compared as AD
    x = String(x == null ? "" : x).trim();
    if (/^\d{4}-\d\d-\d\d$/.test(x) && Number(x.slice(0, 4)) > 2050 && typeof window.bsToAd === "function") return window.bsToAd(x) || x;
    return x;
  };
  const numOf = (v) => { if (typeof v === "number") return v; const n = Number(String(v == null ? "" : v).replace(/,/g, "").trim()); return String(v == null ? "" : v).trim() === "" ? NaN : n; };
  const OPS = [["has", "contains"], ["nhas", "does not contain"], ["eq", "="], ["ne", "≠"], ["gt", ">"], ["ge", "≥"], ["lt", "<"], ["le", "≤"], ["bt", "between"], ["empty", "is empty"], ["full", "is not empty"]];
  const opLabel = (op) => (OPS.find((x) => x[0] === op) || [0, op])[1];
  function cmp(a, b, numeric) {
    const na = numOf(a), nb = numOf(b);
    if ((numeric || (!isNaN(na) && !isNaN(nb))) && !isNaN(na) && !isNaN(nb)) return na - nb;
    return String(a == null ? "" : a).localeCompare(String(b == null ? "" : b), undefined, { numeric: true, sensitivity: "base" });
  }
  function testCond(k, r) {
    const c = k.cols[k.ci];
    if (!c) return true;
    const raw = rawOf(c, r), txt = shown(c, r);
    const v1 = bsIn(k.v1), v2 = bsIn(k.v2);
    const low = (s) => String(s == null ? "" : s).toLowerCase();
    switch (k.op) {
      case "has": return low(txt).includes(low(k.v1)) || low(raw).includes(low(v1));
      case "nhas": return !(low(txt).includes(low(k.v1)) || low(raw).includes(low(v1)));
      case "eq": return cmp(raw, v1, isNum(c)) === 0 || low(txt) === low(k.v1);
      case "ne": return !(cmp(raw, v1, isNum(c)) === 0 || low(txt) === low(k.v1));
      case "gt": return cmp(raw, v1, isNum(c)) > 0;
      case "ge": return cmp(raw, v1, isNum(c)) >= 0;
      case "lt": return cmp(raw, v1, isNum(c)) < 0;
      case "le": return cmp(raw, v1, isNum(c)) <= 0;
      case "bt": return cmp(raw, v1, isNum(c)) >= 0 && cmp(raw, v2, isNum(c)) <= 0;
      case "empty": return String(txt).trim() === "";
      case "full": return String(txt).trim() !== "";
      default: return true;
    }
  }

  let ACTIVE = null;
  const ticksOn = () => LS("bco_ticks", "1") === "1";

  function klist(cols, rows, o) {
    o = o || {};
    const K = { cols, o, all: (rows || []).slice(), sel: new Set(), hidden: [], conds: [], join: "and", vals: {}, q: "", focus: -1, anchor: -1, vis: [] };
    const hid = () => new Set(K.hidden.flat());
    const ticks = ticksOn() && o.select !== false && K.all.length > 1 && !!(o.onRow || o.name);
    const wrap = h("div", { class: "klist", tabindex: "-1" });
    wrap._k = K;
    K.el = wrap;
    if (o.name) wrap.dataset.name = o.name;
    const body = h("tbody");
    const headBox = ticks ? h("input", { type: "checkbox", title: "Tick all rows shown (Ctrl+Space)", onclick: (e) => { e.stopPropagation(); K.selectAll(headBox.checked); } }) : null;
    let foot = null;
    const tfoot = h("tfoot");
    const pass = (r) => {
      if (K.q) {
        const t = K.q.toLowerCase();
        if (!cols.some((c) => String(textOf(c, r)).toLowerCase().includes(t))) return false;
      }
      for (const [ci, set] of Object.entries(K.vals)) {
        if (!set.has(shown(cols[ci], r))) return false;
      }
      if (K.conds.length) {
        const res = K.conds.map((k) => testCond(Object.assign({ cols }, k), r));
        if (K.join === "or" ? !res.some(Boolean) : !res.every(Boolean)) return false;
      }
      return true;
    };
    const paintTotals = () => {
      tfoot.innerHTML = "";
      if (!o.totals) return;
      tfoot.append(h("tr", {}, ticks ? h("td", { class: "kc" }) : null, cols.map((c, i) => {
        if (i === 0) return h("td", {}, "Total");
        if (!o.totals.includes(c.k)) return h("td");
        const s = K.vis.reduce((a, r) => a + Number((typeof c.v === "function" ? c.v(r) : r[c.k]) || 0), 0);
        return h("td", { class: "num" }, c.fmt === "qty" ? fmtQty(s) : fmtMoney(s));
      })));
    };
    const rowEl = (r, i) => {
      const cb = ticks ? h("input", { type: "checkbox", checked: K.sel.has(r), tabindex: "-1" }) : null;
      const tr = h("tr", { class: (o.onRow ? "click " : "") + (o.rowClass ? o.rowClass(r) || "" : "") + (K.sel.has(r) ? " ks" : "") + (i === K.focus ? " kf" : "") },
        ticks ? h("td", { class: "kc", onclick: (e) => {
          e.stopPropagation();
          if (e.shiftKey && K.anchor >= 0) K.range(K.anchor, i, true); else { K.toggle(r); K.anchor = i; }
          K.setFocus(i, true);
        } }, cb) : null,
        cols.map((c) => h("td", { class: isNum(c) ? "num" : "" }, cellValue(c, r))));
      tr._r = r;
      tr.addEventListener("click", (e) => {
        if (e.target.closest("a,button,input,select,textarea")) return;
        if (e.ctrlKey || e.metaKey) { K.toggle(r); K.anchor = i; K.setFocus(i, true); return; }
        if (e.shiftKey && K.anchor >= 0) { K.range(K.anchor, i, true); K.setFocus(i, true); return; }
        K.setFocus(i, true);
        K.anchor = i;
        if (o.onRow) o.onRow(r);
      });
      return tr;
    };
    K.render = () => {
      const hs = hid();
      K.vis = K.all.filter((r) => !hs.has(r) && pass(r));
      body.innerHTML = "";
      if (K.focus >= K.vis.length) K.focus = K.vis.length - 1;
      if (!K.vis.length) body.append(h("tr", {}, h("td", { class: "empty", colspan: cols.length + (ticks ? 1 : 0) }, o.empty || (K.all.length ? "No rows match the filter." : "Nothing here yet."))));
      K.vis.forEach((r, i) => body.append(rowEl(r, i)));
      paintTotals();
      K.paintBar();
    };
    K.rowAt = (i) => { const r = K.vis[i]; if (r === undefined) return null; for (const tr of body.children) if (tr._r === r) return tr; return null; };
    K.setFocus = (i, keepScroll) => {
      if (!K.vis.length) { K.focus = -1; return; }
      i = Math.max(0, Math.min(K.vis.length - 1, i));
      const old = K.rowAt(K.focus);
      if (old) old.classList.remove("kf");
      K.focus = i;
      const tr = K.rowAt(i);
      if (tr) { tr.classList.add("kf"); if (!keepScroll) tr.scrollIntoView({ block: "nearest" }); }
      ACTIVE = K;
    };
    const paintRow = (r) => {
      const i = K.vis.indexOf(r);
      const tr = K.rowAt(i);
      if (!tr) return;
      tr.classList.toggle("ks", K.sel.has(r));
      const cb = tr.querySelector("td.kc input");
      if (cb) cb.checked = K.sel.has(r);
    };
    K.toggle = (r, on) => {
      if (!r) return;
      const want = on === undefined ? !K.sel.has(r) : on;
      if (want) K.sel.add(r); else K.sel.delete(r);
      paintRow(r);
      K.paintBar();
    };
    K.range = (a, b, on) => {
      const [x, y] = a < b ? [a, b] : [b, a];
      for (let i = x; i <= y; i++) { const r = K.vis[i]; if (r) { if (on) K.sel.add(r); else K.sel.delete(r); paintRow(r); } }
      K.paintBar();
    };
    K.selectAll = (on) => {
      if (on === undefined) on = !(K.vis.length && K.vis.every((r) => K.sel.has(r)));
      K.vis.forEach((r) => { if (on) K.sel.add(r); else K.sel.delete(r); paintRow(r); });
      K.paintBar();
    };
    K.selected = () => K.all.filter((r) => K.sel.has(r));
    K.working = () => { const s = K.vis.filter((r) => K.sel.has(r)); return s.length ? s : K.vis; };
    K.open = () => { const r = K.vis[K.focus]; if (r && o.onRow) o.onRow(r); };
    K.hide = () => {
      let list = K.vis.filter((r) => K.sel.has(r));
      if (!list.length && K.vis[K.focus]) list = [K.vis[K.focus]];
      if (!list.length) return toast("Move to a row (↑ ↓) or tick rows first.", "err");
      K.hidden.push(list);
      list.forEach((r) => K.sel.delete(r));
      K.render();
      if (K.vis.length) K.setFocus(K.focus < 0 ? 0 : K.focus);
      toast(list.length + " row" + (list.length > 1 ? "s" : "") + " hidden — Alt+U brings back", "ok");
    };
    K.unhide = (all) => {
      if (!K.hidden.length) return toast("No hidden rows.", "err");
      const n = all ? K.hidden.flat().length : K.hidden[K.hidden.length - 1].length;
      if (all) K.hidden = []; else K.hidden.pop();
      K.render();
      toast(n + " row" + (n > 1 ? "s" : "") + " shown again", "ok");
    };
    K.clearFilters = () => { K.conds = []; K.vals = {}; K.q = ""; if (K.search) K.search.value = ""; K.render(); };
    K.title = () => {
      if (o.title) return o.title;
      const ov = wrap.closest(".overlay");
      const hd = ov ? ov.querySelector("header h3") : document.querySelector("#page h1");
      return (hd && hd.textContent.trim()) || (o.name ? o.name.replace(/_/g, " ") : "List");
    };
    K.exportRows = () => exportCsv(o.name || "export", cols, K.working(), o);
    K.printRows = () => {
      const rs = K.working();
      const meta = [["Rows", rs.length + (rs.length !== K.all.length ? " of " + K.all.length : "")]];
      const f = K.describe();
      if (f) meta.push(["Filter", f]);
      if (S.project && typeof nm !== "undefined" && nm.project) meta.push(["Project", nm.project(S.project)]);
      const tot = (o.totals || []).map((k) => {
        const c = cols.find((x) => x.k === k);
        if (!c) return null;
        const s = rs.reduce((a, r) => a + Number((typeof c.v === "function" ? c.v(r) : r[c.k]) || 0), 0);
        return [c.label, c.fmt === "qty" ? fmtQty(s) : fmtMoney(s)];
      }).filter(Boolean);
      printDoc(K.title(), meta, cols, rs, tot);
    };
    K.deleteRows = async () => {
      const kinds = await admKinds();
      if (!S.user || S.user.role !== "admin") return toast("Only an administrator can delete from a list. Open the record to delete it.", "err");
      if (!o.name || !kinds.has(o.name)) return toast("Rows in this list cannot be deleted from here.", "err");
      let list = K.vis.filter((r) => K.sel.has(r));
      if (!list.length && K.vis[K.focus]) list = [K.vis[K.focus]];
      const ids = list.map((r) => r.id).filter((x) => x != null);
      if (!ids.length) return toast("Tick the rows to delete (Space), then press Alt+D.", "err");
      const ok = await ask("Delete " + ids.length + " record" + (ids.length > 1 ? "s" : ""),
        "Delete the ticked record" + (ids.length > 1 ? "s" : "") + "? Anything already posted, approved or used elsewhere is kept and listed with the reason. This cannot be undone.",
        { danger: true, ok: "Delete " + ids.length });
      if (!ok) return;
      const res = await run("adm.delete", { kind: o.name, ids });
      const gone = new Set(res.deleted);
      K.all = K.all.filter((r) => !gone.has(r.id));
      K.sel = new Set([...K.sel].filter((r) => !gone.has(r.id)));
      K.hidden = K.hidden.map((l) => l.filter((r) => !gone.has(r.id))).filter((l) => l.length);
      K.render();
      if (res.label === "master" || res.label === "record") { try { await reloadLookups(); } catch (e) { /* ignore */ } }
      toast(res.deleted.length + " deleted" + (res.refused.length ? ", " + res.refused.length + " kept" : ""), res.refused.length ? "err" : "ok");
      if (res.refused.length) {
        const byId = {}; list.forEach((r) => { byId[r.id] = r; });
        const name = (r) => r ? cols.slice(0, 2).map((c) => shown(c, r)).filter(Boolean).join(" · ") : "";
        modal("Not deleted — " + res.refused.length, h("div", {},
          h("p", { class: "hint" }, "These were kept because they have moved money or stock, or are used by other records. Reverse or cancel them, or mark them inactive."),
          h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Record"), h("th", {}, "Why it was kept"))),
            h("tbody", {}, res.refused.map((x) => h("tr", {}, h("td", {}, name(byId[x.id]) || "#" + x.id), h("td", {}, x.reason))))))), [], { narrow: true });
      }
    };
    K.describe = () => {
      const parts = [];
      if (K.q) parts.push("“" + K.q + "”");
      K.conds.forEach((k) => { const c = cols[k.ci]; if (c) parts.push(c.label + " " + opLabel(k.op) + (["empty", "full"].includes(k.op) ? "" : " " + k.v1 + (k.op === "bt" ? " – " + k.v2 : ""))); });
      Object.entries(K.vals).forEach(([ci, set]) => { const c = cols[ci]; if (c) parts.push(c.label + ": " + [...set].slice(0, 4).join(", ") + (set.size > 4 ? " +" + (set.size - 4) : "")); });
      return parts.join(K.join === "or" && K.conds.length > 1 ? " · any of " : " · ");
    };

    /* the bar above the list */
    const canBar = K.all.length > 0 && (o.search !== false || o.export !== false);
    const bar = h("div", { class: "kbar bar" });
    const chips = h("span", { style: "display:contents" });
    const bulk = h("span", { class: "kbulk", hidden: true });
    const count = h("span", { class: "kcount" });
    if (o.search !== false && K.all.length > 8) {
      K.search = h("input", { type: "search", placeholder: "Filter these rows", oninput: () => { K.q = K.search.value; K.render(); } });
      bar.append(K.search);
    }
    if (o.search !== false && K.all.length > 5) {
      bar.append(h("button", { class: "btn small", title: "Filter on one or more conditions (Alt+F12)", onclick: () => K.rangeDialog() }, "Filter…"),
        h("button", { class: "btn small", title: "Pick the values to show (Ctrl+F12)", onclick: () => K.valueDialog() }, "Pick values…"));
    }
    bar.append(chips, h("div", { class: "grow" }), count, bulk);
    if (o.export !== false || K.all.length > 8) bar.append(h("button", { class: "btn small", onclick: () => K.exportRows() }, "Export CSV"));
    K.paintBar = () => {
      chips.innerHTML = "";
      const chip = (txt, clear) => chips.append(h("span", { class: "kchip" }, txt, h("button", { title: "Remove", onclick: () => { clear(); K.render(); } }, "×")));
      K.conds.forEach((k, i) => { const c = cols[k.ci]; if (c) chip((i && K.join === "or" ? "or " : "") + c.label + " " + opLabel(k.op) + (["empty", "full"].includes(k.op) ? "" : " " + k.v1 + (k.op === "bt" ? " – " + k.v2 : "")), () => K.conds.splice(i, 1)); });
      Object.entries(K.vals).forEach(([ci, set]) => { const c = cols[ci]; if (c) chip(c.label + ": " + [...set].slice(0, 3).join(", ") + (set.size > 3 ? " +" + (set.size - 3) : ""), () => { delete K.vals[ci]; }); });
      const nh = K.hidden.flat().length;
      if (nh) chip(nh + " hidden", () => { K.hidden = []; });
      const filtered = K.vis.length !== K.all.length;
      count.textContent = filtered ? K.vis.length + " of " + K.all.length + " rows" : "";
      const ns = K.vis.filter((r) => K.sel.has(r)).length;
      bulk.hidden = !ns;
      bulk.innerHTML = "";
      if (ns) {
        bulk.append(h("b", {}, ns + " ticked"),
          h("button", { class: "btn small", title: "Alt+P", onclick: () => K.printRows() }, "Print ticked"),
          h("button", { class: "btn small", title: "Alt+E", onclick: () => K.exportRows() }, "Export ticked"));
        if (S.user && S.user.role === "admin" && o.name) {
          const del = h("button", { class: "btn small warn", title: "Alt+D", hidden: true, onclick: () => K.deleteRows().catch(() => {}) }, "Delete ticked");
          bulk.append(del);
          admKinds().then((kinds) => { if (kinds.has(o.name)) del.hidden = false; });
        }
        bulk.append(h("button", { class: "btn small", title: "Untick all", onclick: () => K.selectAll(false) }, "Clear"));
      }
      if (headBox) { headBox.checked = K.vis.length > 0 && K.vis.every((r) => K.sel.has(r)); headBox.indeterminate = ns > 0 && !headBox.checked; }
    };

    /* Alt+F12 — conditions */
    K.rangeDialog = () => {
      const list = h("div");
      const work = (K.conds.length ? K.conds : [{ ci: Math.max(0, cols.findIndex((c) => isNum(c))), op: "ge", v1: "", v2: "" }]).map((x) => Object.assign({}, x));
      let join = K.join;
      const draw = () => {
        list.innerHTML = "";
        work.forEach((k, i) => {
          const csel = h("select", {}, cols.map((c, j) => h("option", { value: j, selected: j === Number(k.ci) }, c.label || "(column " + (j + 1) + ")")));
          const osel = h("select", {}, OPS.map(([v, l]) => h("option", { value: v, selected: v === k.op }, l)));
          const v1 = h("input", { value: k.v1 || "", placeholder: "value", oninput: () => { k.v1 = v1.value; } });
          const v2 = h("input", { value: k.v2 || "", placeholder: "and", hidden: k.op !== "bt", oninput: () => { k.v2 = v2.value; } });
          csel.onchange = () => { k.ci = Number(csel.value); };
          osel.onchange = () => { k.op = osel.value; v2.hidden = k.op !== "bt"; v1.hidden = ["empty", "full"].includes(k.op); };
          v1.hidden = ["empty", "full"].includes(k.op);
          list.append(h("div", { class: "kcond" }, i ? h("b", { style: "width:34px" }, join === "or" ? "or" : "and") : h("b", { style: "width:34px" }, "where"), csel, osel, v1, v2,
            h("button", { class: "btn small", title: "Remove", onclick: () => { work.splice(i, 1); draw(); } }, "×")));
        });
      };
      draw();
      const joinSel = h("select", { style: "width:auto", onchange: () => { join = joinSel.value; draw(); } },
        h("option", { value: "and", selected: join === "and" }, "Rows matching ALL conditions"), h("option", { value: "or", selected: join === "or" }, "Rows matching ANY condition"));
      modal("Filter — " + K.title(), h("div", {},
        h("p", { class: "hint" }, "Like Tally's range filter (Alt+F12): add as many conditions as you need. Dates can be typed in AD or BS (YYYY-MM-DD). Ctrl+A applies."),
        list, h("div", { class: "bar" }, h("button", { class: "btn small", onclick: () => { work.push({ ci: 0, op: "has", v1: "", v2: "" }); draw(); } }, "+ Add condition"), h("div", { class: "grow" }), joinSel)),
      [{ label: "Apply filter", cls: "primary", act: () => {
        K.conds = work.filter((k) => ["empty", "full"].includes(k.op) || String(k.v1 || "").trim() !== "");
        K.join = join; K.render(); K.setFocus(0);
      } }, { label: "Clear all filters", act: () => { K.clearFilters(); } }], { narrow: true });
    };
    /* Ctrl+F12 — tick values */
    K.valueDialog = (ciStart) => {
      const pickCol = () => {
        if (ciStart !== undefined) return ciStart;
        const keys = Object.keys(K.vals);
        if (keys.length) return Number(keys[0]);
        let best = 0, bestN = 1e9;
        cols.forEach((c, j) => {
          if (isNum(c)) return;
          const n = new Set(K.all.map((r) => shown(c, r))).size;
          if (n > 1 && n < bestN) { best = j; bestN = n; }
        });
        return best;
      };
      let ci = pickCol();
      const work = {};
      Object.entries(K.vals).forEach(([k, s]) => { work[k] = new Set(s); });
      const csel = h("select", { style: "width:auto" }, cols.map((c, j) => h("option", { value: j, selected: j === ci }, c.label || "(column " + (j + 1) + ")")));
      const find = h("input", { type: "search", placeholder: "Find a value", style: "max-width:200px" });
      const box = h("div", { class: "kvals" });
      const hs = hid();
      const draw = () => {
        box.innerHTML = "";
        const counts = new Map();
        K.all.forEach((r) => { if (hs.has(r)) return; const t = shown(cols[ci], r); counts.set(t, (counts.get(t) || 0) + 1); });
        const vals = [...counts.keys()].sort((a, b) => cmp(a, b, isNum(cols[ci])));
        const cur = work[ci];
        const t = find.value.toLowerCase();
        vals.filter((v) => !t || v.toLowerCase().includes(t)).slice(0, 1000).forEach((v) => {
          const cb = h("input", { type: "checkbox", checked: !cur || cur.has(v), onchange: () => {
            if (!work[ci]) work[ci] = new Set(vals);
            if (cb.checked) work[ci].add(v); else work[ci].delete(v);
          } });
          box.append(h("label", {}, cb, h("span", {}, v === "" ? "(blank)" : v), h("span", { class: "kcount" }, "(" + counts.get(v) + ")")));
        });
        box._vals = vals;
      };
      csel.onchange = () => { ci = Number(csel.value); draw(); };
      find.oninput = draw;
      draw();
      const setAll = (on) => { work[ci] = on ? new Set(box._vals) : new Set(); draw(); };
      modal("Pick values — " + K.title(), h("div", {},
        h("p", { class: "hint" }, "Like Tally's Ctrl+F12: tick the values to keep. Pick another column to filter on it too; the filters work together."),
        h("div", { class: "bar" }, csel, find, h("div", { class: "grow" }), h("button", { class: "btn small", onclick: () => setAll(true) }, "All"), h("button", { class: "btn small", onclick: () => setAll(false) }, "None")), box),
      [{ label: "Apply", cls: "primary", act: () => {
        const next = {};
        Object.entries(work).forEach(([k, s]) => {
          const all = new Set(K.all.map((r) => shown(cols[k], r)));
          if (s.size < all.size) next[k] = s;
        });
        K.vals = next; K.render(); K.setFocus(0);
      } }, { label: "Clear all filters", act: () => { K.clearFilters(); } }], { narrow: true });
      setTimeout(() => find.focus(), 30);
    };

    const tbl = h("table", {}, h("thead", {}, h("tr", {}, ticks ? h("th", { class: "kc" }, headBox) : null, cols.map((c) => h("th", { class: isNum(c) ? "num" : "" }, c.label)))), body, tfoot);
    if (canBar) wrap.append(bar);
    wrap.append(h("div", { class: "tablewrap" }, tbl));
    wrap.addEventListener("mousedown", (e) => { ACTIVE = K; if (!e.target.closest("input,select,textarea,button,a")) setTimeout(() => wrap.focus({ preventScroll: true }), 0); });
    wrap.addEventListener("focusin", () => { ACTIVE = K; });
    K.render();
    return wrap;
  }
  window.table = klist;
  try { table = klist; } catch (e) { /* strict mode */ }

  /* printouts of the page never carry the tick boxes or the list bar; Nepali mode shows BS dates */
  if (typeof window.printFrame === "function") {
    const _pf = window.printFrame;
    window.printFrame = function (title, node, extra) {
      let n = node;
      try {
        n = node.cloneNode(true);
        n.querySelectorAll(".kc,.kbar,.kbulk,button").forEach((x) => x.remove());
        if (typeof window.bcoDateMode === "function" && window.bcoDateMode() === "bs" && typeof window.adToBs === "function") {
          const re = /\b(20[0-4]\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b/g;
          const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
          const hits = [];
          for (let t = w.nextNode(); t; t = w.nextNode()) hits.push(t);
          hits.forEach((t) => { t.nodeValue = t.nodeValue.replace(re, (m) => window.adToBs(m) || m); });
        }
      } catch (e) { n = node; }
      return _pf(title, n, extra);
    };
  }

  /* ───────────────────────────── the list you are working in ───────────────────────────── */
  const overlayTop = () => { const all = document.querySelectorAll(".overlay"); return all.length ? all[all.length - 1] : null; };
  function activeList() {
    const scope = overlayTop() || document.querySelector("#page");
    if (!scope) return null;
    if (ACTIVE && ACTIVE.el.isConnected && scope.contains(ACTIVE.el) && ACTIVE.el.offsetParent !== null) return ACTIVE;
    const el = [...scope.querySelectorAll(".klist")].find((x) => x.offsetParent !== null && x._k && x._k.all.length);
    return el ? el._k : null;
  }
  window.bcoActiveList = activeList;

  /* ───────────────────────────── vouchers and documents (Tally keys) ───────────────────────────── */
  const NEWRE = /^(\+\s*)?(New|Add|Create)\b/i;
  const ACT = {
    contra: { path: "acc/vouchers", btn: /^New voucher/, type: "contra", label: "Contra voucher" },
    pay: { path: "acc/payments", btn: /^Make payment/, label: "Payment" },
    receive: { path: "acc/payments", btn: /^Receive payment/, label: "Receipt" },
    journal: { path: "acc/vouchers", btn: /^New voucher/, type: "journal", label: "Journal voucher" },
    sales: { path: "acc/sales", label: "Sales — client invoice" },
    credit_note: { path: "acc/vouchers", btn: /^New voucher/, type: "credit_note", label: "Credit note" },
    purchase: { path: "proc/invoices", label: "Purchase bill" },
    debit_note: { path: "acc/vouchers", btn: /^New voucher/, type: "debit_note", label: "Debit note" },
    po: { path: "proc/po", label: "Purchase order" },
    mrq: { path: "inv/mrq", label: "Material requisition" },
    measure: { path: "p/measure", label: "Measurement sheet" },
    transfer: { path: "inv/transfer", label: "Stock transfer (stock journal)" },
    count: { path: "inv/count", label: "Physical stock count" },
    issue: { path: "inv/issue", label: "Material issue (delivery note)" },
    grn: { path: "inv/grn", label: "Goods receipt (receipt note)" },
    run: { path: "pl/runs", label: "Plant production run" },
    asset: { path: "as/register", label: "Asset" },
    dpr: { path: "p/dpr", label: "Daily progress report (DPR)" },
    ipc: { path: "p/ipc", label: "IPC — client bill" },
    logday: { path: "eq/logs", label: "Machine log (one day)" },
    variation: { path: "p/variations", label: "Variation" },
    event: { path: "p/events", label: "Event / claim" },
    ret: { path: "inv/return", label: "Material return" },
    pr: { path: "proc/pr", label: "Purchase request" },
    task: { path: "p/tasks", label: "Task" },
  };
  const FKEYS = {
    F4: "contra", F5: "pay", F6: "receive", F7: "journal", F8: "sales", "Ctrl+F8": "credit_note", F9: "purchase", "Ctrl+F9": "debit_note",
    "Alt+F4": "po", "Alt+F5": "mrq", "Alt+F6": "measure", "Alt+F7": "transfer", "Ctrl+F7": "count", "Alt+F8": "issue", "Alt+F9": "grn",
    "Alt+F10": "run", "Ctrl+F10": "asset",
  };
  const OTHER = [["D", "dpr"], ["I", "ipc"], ["M", "measure"], ["L", "logday"], ["R", "mrq"], ["T", "transfer"], ["U", "ret"], ["Q", "pr"], ["O", "po"], ["G", "grn"], ["S", "issue"], ["P", "run"], ["V", "variation"], ["E", "event"], ["K", "task"], ["A", "asset"]];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(fn, ms) {
    const end = Date.now() + (ms || 6000);
    while (Date.now() < end) { const x = fn(); if (x) return x; await sleep(90); }
    return null;
  }
  const pathNow = () => (location.hash.replace(/^#\/?/, "").split("?")[0]);
  async function runAction(key) {
    const a = ACT[key];
    if (!a) return;
    if (typeof PAGES !== "undefined" && !PAGES[a.path]) return toast(a.label + " is not available in this version.", "err");
    try { history.replaceState(null, "", "#/" + a.path); } catch (e) { /* ignore */ }
    await sleep(80);
    const btn = await waitFor(() => {
      if (pathNow() !== a.path) return null;
      const page = document.querySelector("#page");
      if (!page) return null;
      const head = page.querySelector(".bar");
      const all = [...page.querySelectorAll("button")].filter((b) => !b.disabled && b.offsetParent !== null);
      const re = a.btn || NEWRE;
      return (head && [...head.querySelectorAll("button")].find((b) => re.test(b.textContent.trim()))) || all.find((b) => re.test(b.textContent.trim()));
    });
    if (!btn) {
      const page = document.querySelector("#page");
      if (page && page.textContent.match(/select a project|choose a project/i)) return toast("Choose a project first (F3), then press the key again.", "err");
      return toast("You cannot make a new " + a.label.toLowerCase() + " here (check your role).", "err");
    }
    const before = document.querySelectorAll(".overlay").length;
    btn.click();
    toast(a.label, "ok");
    if (a.type) {
      const m = await waitFor(() => { const o = overlayTop(); return document.querySelectorAll(".overlay").length > before && o && o.querySelector("select[name=type]") ? o : null; }, 3000);
      if (m) {
        const sel = m.querySelector("select[name=type]");
        sel.value = a.type;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        const hd = m.querySelector("header h3");
        if (hd) hd.textContent = "New " + a.label.toLowerCase();
        const first = m.querySelector("input[name=narration]") || m.querySelector("input:not([type=hidden]):not([readonly])");
        if (first) first.focus();
      }
    }
  }
  function startAction(key) {
    const a = ACT[key];
    if (!a) return;
    if (!S.user) return;
    const target = "#/" + a.path + "?knew=" + key;
    if (location.hash === target) { runAction(key); if (typeof go === "function") go(); return; }
    location.hash = target;
  }
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/[?&]knew=([a-z_]+)/);
    if (m) runAction(m[1]);
  });
  function otherVouchers() {
    if (document.querySelector(".overlay .kvlist")) return;
    const items = OTHER.filter(([, k]) => typeof PAGES === "undefined" || PAGES[ACT[k].path]);
    let on = 0;
    const box = h("div", { class: "kvlist" });
    let m = null;
    const pick = (k) => { m.close(); startAction(k); };
    const draw = () => {
      box.innerHTML = "";
      items.forEach(([letter, k], i) => box.append(h("a", { class: i === on ? "on" : "", onclick: () => pick(k) }, h("i", {}, letter), h("span", {}, ACT[k].label))));
    };
    draw();
    box._key = (e) => {
      if (e.key === "ArrowDown") { on = Math.min(items.length - 1, on + 1); draw(); return true; }
      if (e.key === "ArrowUp") { on = Math.max(0, on - 1); draw(); return true; }
      if (e.key === "Enter") { pick(items[on][1]); return true; }
      const hit = e.key.length === 1 && items.find(([l]) => l === e.key.toUpperCase());
      if (hit && !e.ctrlKey && !e.altKey) { pick(hit[1]); return true; }
      return false;
    };
    m = modal("Other vouchers (F10)", h("div", {}, h("p", { class: "hint" }, "Press the letter, or ↑ ↓ and Enter."), box), [], { narrow: true });
  }

  /* ───────────────────────────── Gateway letters (DD, DAL, ALC …) ───────────────────────────── */
  const route = (p) => () => { if (typeof PAGES !== "undefined" && !PAGES[p]) return toast("Not available in this version.", "err"); location.hash = "#/" + p; };
  const create = (table, path) => async () => {
    if (typeof MASTERS_UI !== "undefined" && MASTERS_UI[table] && typeof masterDialog === "function") return masterDialog(table, {});
    location.hash = "#/" + path;
    const b = await waitFor(() => pathNow() === path && [...document.querySelectorAll("#page button")].find((x) => NEWRE.test(x.textContent.trim())));
    if (b) b.click(); else toast("You cannot create that here.", "err");
  };
  const GATE = {
    DD: ["Day book", route("acc/daybook")], DAL: ["Account ledger", route("acc/ledger")], DAP: ["Party statement", route("acc/party")],
    DAG: ["Ageing", route("acc/ageing")], DT: ["Trial balance", route("acc/tb")], DB: ["Balance sheet", route("acc/bs")], DP: ["Profit & loss", route("acc/pl")],
    DS: ["Stock summary", route("inv/stock")], DC: ["Stock card", route("inv/card")], DV: ["VAT books", route("acc/vat")], DX: ["TDS register", route("acc/tds")],
    DR: ["Material reconciliation", route("inv/recon")], DE: ["Equipment performance", route("eq/kpi")], DQ: ["Cost & earned value", route("p/evm")],
    ALC: ["Create ledger (account)", create("accounts", "acc/coa")], ALA: ["Alter ledgers — chart of accounts", route("acc/coa")],
    AIC: ["Create stock item (material)", create("materials", "m/materials")], AIA: ["Alter stock items — materials", route("m/materials")],
    APC: ["Create party", create("parties", "m/parties")], APA: ["Alter parties", route("m/parties")],
    AEC: ["Create machine", create("equipment", "eq/register")], AEA: ["Alter machines", route("eq/register")],
    ABC: ["Create BOQ item", create("boq_items", "m/boq")], ABA: ["Alter BOQ items", route("m/boq")],
    CL: ["Create ledger", create("accounts", "acc/coa")], CI: ["Create stock item", create("materials", "m/materials")],
    CP: ["Create party", create("parties", "m/parties")], CE: ["Create machine", create("equipment", "eq/register")],
    V: ["Vouchers", route("acc/vouchers")], K: ["Day book", route("acc/daybook")], H: ["Chart of accounts", route("acc/coa")],
    B: ["Balance sheet", route("acc/bs")], P: ["Profit & loss", route("acc/pl")], S: ["Stock summary", route("inv/stock")],
    T: ["Trial balance", route("acc/tb")], L: ["Account ledger", route("acc/ledger")], F: ["Modules (home)", () => { location.hash = "#/home"; }],
  };
  let gbuf = "", gtimer = null, gbox = null;
  const gateOn = () => LS("bco_gate", "1") === "1";
  const gateHide = () => { if (gbox) { gbox.remove(); gbox = null; } };
  function gateKey(ch) {
    clearTimeout(gtimer);
    const next = gbuf + ch;
    const cands = Object.keys(GATE).filter((k) => k.startsWith(next));
    if (!cands.length) { gbuf = ""; gateHide(); return false; }
    gbuf = next;
    const exact = GATE[gbuf];
    const longer = cands.filter((k) => k !== gbuf);
    if (exact && !longer.length) { const f = exact[1]; toast(exact[0], "ok"); gbuf = ""; gateHide(); f(); return true; }
    if (!gbox) { gbox = h("div", { class: "kgate" }); document.body.append(gbox); }
    gbox.innerHTML = "";
    gbox.append(h("b", {}, gbuf), ...cands.slice(0, 8).map((k) => h("div", {}, k + " — " + GATE[k][0])));
    gtimer = setTimeout(() => {
      const hit = GATE[gbuf];
      gbuf = ""; gateHide();
      if (hit) { toast(hit[0], "ok"); hit[1](); }
    }, exact ? 900 : 1600);
    return true;
  }

  /* ───────────────────────────── calculator (Ctrl+N) ───────────────────────────── */
  let lastField = null;
  document.addEventListener("focusin", (e) => {
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA") && !t.closest(".kcalc") && !["checkbox", "radio", "hidden", "file"].includes(t.type)) lastField = t;
  });
  let calc = null;
  function calcEval(s) {
    s = String(s).replace(/,/g, "").replace(/×/g, "*").replace(/÷/g, "/").replace(/(\d+(?:\.\d+)?)\s*%/g, "($1/100)");
    if (!/^[\d+\-*/().\s]+$/.test(s)) throw new Error("Only numbers and + − × ÷ ( ) %");
    const v = Function('"use strict";return (' + s + ")")();
    if (typeof v !== "number" || !isFinite(v)) throw new Error("Not a number");
    return Math.round(v * 10000) / 10000;
  }
  function calculator() {
    if (calc) { calc.querySelector("input").focus(); return; }
    const hist = h("div", { class: "hist" });
    let last = null;
    const inp = h("input", { placeholder: "e.g. 12.5*4+10%" });
    const target = lastField;
    const use = () => {
      if (last == null) return toast("Work something out first.", "err");
      const t = target && target.isConnected ? target : null;
      if (!t) { try { navigator.clipboard.writeText(String(last)); } catch (e) { /* ignore */ } toast("Copied " + last, "ok"); return; }
      t.value = String(last);
      t.dispatchEvent(new Event("input", { bubbles: true }));
      t.dispatchEvent(new Event("change", { bubbles: true }));
      close(); t.focus();
    };
    const close = () => { if (calc) { calc.remove(); calc = null; } };
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); if (target && target.isConnected) target.focus(); return; }
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.stopPropagation(); if (inp.value.trim()) { try { last = calcEval(inp.value); } catch (x) { /* keep last */ } } use(); return; }
      if (e.key === "Enter") {
        e.preventDefault(); e.stopPropagation();
        const src = inp.value.trim() || (last != null ? String(last) : "");
        if (!src) return;
        try { last = calcEval(/^[+\-*/]/.test(src) && last != null ? last + src : src); hist.append(h("div", {}, h("span", {}, src), h("b", {}, fmtQty ? fmtQty(last) : last))); hist.scrollTop = 1e6; inp.value = ""; } catch (x) { toast(x.message, "err"); }
      }
    });
    calc = h("div", { class: "kcalc" }, h("h4", {}, "Calculator", h("button", { title: "Close (Esc)", onclick: close }, "×")), hist, inp,
      h("div", { class: "bar", style: "margin-top:6px" }, h("span", { class: "hint" }, "Enter = work out · Ctrl+Enter = put in the field"), h("div", { class: "grow" }), h("button", { class: "btn small primary", onclick: use }, "Use")));
    document.body.append(calc);
    setTimeout(() => inp.focus(), 10);
  }
  window.bcoCalculator = calculator;

  /* ───────────────────────────── repeat narration (Ctrl+R) ───────────────────────────── */
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t && (t.name === "narration" || t.name === "remarks") && t.value && t.value.trim()) LSset("bco_last_" + t.name, t.value.trim());
  }, true);

  /* ───────────────────────────── Alt+2 duplicate voucher ───────────────────────────── */
  let lastV = null;
  if (typeof window.voucherView === "function") {
    const _vv = window.voucherView;
    window.voucherView = async function (id, reload) {
      const n = document.querySelectorAll(".overlay").length;
      const r = await _vv(id, reload);
      const all = document.querySelectorAll(".overlay");
      lastV = { id, reload, el: all.length > n ? all[all.length - 1] : null };
      return r;
    };
    try { voucherView = window.voucherView; } catch (e) { /* ignore */ }
  }
  async function duplicate() {
    const top = overlayTop();
    let id = null, reload = null;
    if (top && lastV && lastV.el === top) { id = lastV.id; reload = lastV.reload; }
    else if (!top) {
      const k = activeList();
      const r = k && k.vis[k.focus];
      if (k && k.o.name === "vouchers" && r) id = r.id;
    }
    if (!id) return toast("Alt+2 copies a voucher: open one (or stand on it in Vouchers) first.", "err");
    const res = await run("voucher.dup", { id }, "Copied to a new draft dated today");
    if (top) { const x = top.querySelector("header .x"); if (x) x.click(); }
    if (reload) try { reload(); } catch (e) { /* ignore */ }
    window.voucherView(res.id, reload);
  }

  /* ───────────────────────────── F12 configure ───────────────────────────── */
  async function configure() {
    if (document.querySelector(".overlay .kconf")) return;
    const dm = document.querySelector(".date-mode");
    const rows = [];
    const dsel = h("select", {}, [["ad", "English (AD)"], ["bs", "Nepali (BS)"], ["both", "Both"]].map(([v, l]) => h("option", { value: v, selected: (window.bcoDateMode ? window.bcoDateMode() : "ad") === v }, l)));
    rows.push(h("label", { class: "f" }, h("span", {}, "Dates on every screen"), dsel));
    const chk = (label, key, def) => { const c = h("input", { type: "checkbox", checked: LS(key, def) === "1" }); rows.push(h("label", { class: "f check" }, c, label)); return () => LSset(key, c.checked ? "1" : "0"); };
    const s1 = chk("Tick boxes in lists (Space still ticks when off)", "bco_ticks", "1");
    const s2 = chk("Gateway letters — DD day book, DAL ledger, ALC create ledger …", "bco_gate", "1");
    const s3 = chk("Esc goes back to the previous screen when nothing is open", "bco_escback", "1");
    const zsel = h("select", {}, ["0.9", "1", "1.1", "1.2", "1.3"].map((z) => h("option", { value: z, selected: LS("bco_zoom", "1") === z }, Math.round(z * 100) + "%")));
    rows.push(h("label", { class: "f" }, h("span", {}, "Screen size (Alt+Z cycles)"), zsel));
    let dpr = null;
    if (S.user && S.user.role === "admin") {
      try {
        const m = await api("life.log_mode", {});
        dpr = h("input", { type: "checkbox", checked: !!m.dpr_only });
        rows.push(h("label", { class: "f check" }, dpr, "Machine logsheets come only from the DPR (administrator)"));
      } catch (e) { dpr = null; }
    }
    modal("Configure (F12)", h("div", { class: "kconf form" }, rows), [{ label: "Save", cls: "primary", act: async () => {
      s1(); s2(); s3();
      LSset("bco_zoom", zsel.value); applyZoom();
      if (dpr) await run("life.log_mode", { set: dpr.checked ? 1 : 0 });
      if (dm && dm.value !== dsel.value) { dm.value = dsel.value; dm.dispatchEvent(new Event("change", { bubbles: true })); }
      else if (!dm) { LSset("bco_date_mode", dsel.value); location.reload(); }
      else if (typeof go === "function") go();
      toast("Saved", "ok");
    } }], { narrow: true });
  }
  function applyZoom() { const z = Number(LS("bco_zoom", "1")) || 1; document.body.style.zoom = z === 1 ? "" : String(z); }
  if (document.body) applyZoom(); else document.addEventListener("DOMContentLoaded", applyZoom);
  function cycleZoom() {
    const zs = ["1", "1.1", "1.2", "1.3", "0.9"];
    const i = zs.indexOf(LS("bco_zoom", "1"));
    LSset("bco_zoom", zs[(i + 1) % zs.length]);
    applyZoom();
    toast("Screen size " + Math.round(Number(LS("bco_zoom", "1")) * 100) + "%", "ok");
  }

  /* ───────────────────────────── help (F1 / Alt+H) ───────────────────────────── */
  const HELP = [
    ["Vouchers — same keys as Tally", [
      ["Contra", "F4"], ["Payment", "F5"], ["Receipt", "F6"], ["Journal", "F7"], ["Sales (client invoice)", "F8"], ["Credit note", "Ctrl+F8"],
      ["Purchase (bill)", "F9"], ["Debit note", "Ctrl+F9"], ["Other vouchers: DPR, IPC, measurement, logsheet …", "F10"],
      ["Purchase order", "Alt+F4"], ["Material requisition", "Alt+F5"], ["Measurement sheet", "Alt+F6"], ["Stock transfer (stock journal)", "Alt+F7"],
      ["Physical stock count", "Ctrl+F7"], ["Material issue (delivery note)", "Alt+F8"], ["Goods receipt (receipt note)", "Alt+F9"],
      ["Plant production run", "Alt+F10"], ["Asset", "Ctrl+F10"], ["Monthly machine logsheets", "Alt+F11"]]],
    ["Lists — tick, filter, hide", [
      ["Move up / down, first / last", "↑ ↓  Home End"], ["Open the row", "Enter"], ["Tick / untick the row", "Space"],
      ["Tick all / untick all", "Ctrl+Space"], ["Tick from the last ticked row to here", "Shift+Space  /  Shift+click"],
      ["Tick one more row with the mouse", "Ctrl+click"], ["Filter on one or more conditions (range)", "Alt+F12"], ["Pick values to show", "Ctrl+F12"],
      ["Hide the ticked rows (or this row)", "Alt+R"], ["Bring back the last hidden rows / all of them", "Alt+U  /  Alt+S"],
      ["Print the ticked rows (or the list)", "Alt+P"], ["Export the ticked rows (or the list)", "Alt+E"],
      ["Delete the ticked rows (administrator)", "Alt+D"]]],
    ["Entering", [
      ["Accept — save the form", "Ctrl+A"], ["Back / close without saving", "Esc  /  Ctrl+Q"], ["Create the master in this field (ledger, item, party …)", "Alt+C"],
      ["Alter the master in this field", "Alt+A  /  Ctrl+Enter"], ["Add a voucher / new record on this screen", "Alt+A  /  Alt+C  /  Alt+N"], ["Insert a line", "Alt+I"],
      ["Duplicate this voucher", "Alt+2"], ["Delete / cancel the record that is open", "Alt+D  /  Alt+X"], ["Repeat the last narration", "Ctrl+R"],
      ["Calculator (Enter works out, Ctrl+Enter puts it in the field)", "Ctrl+N"]]],
    ["Getting around", [
      ["Go to any screen or record", "Alt+G  /  Ctrl+G"], ["Search everything", "Ctrl+F"], ["Modules screen (all modules)", "Ctrl+M"], ["Change dates", "F2"], ["Change project", "F3"],
      ["Company features (settings)", "F11"], ["Configure: dates AD/BS, tick boxes, letters, size", "F12"], ["Bigger / smaller screen", "Alt+Z"],
      ["Print what is on screen", "Alt+P  /  Ctrl+P"], ["Export", "Alt+E  /  Ctrl+E"],
      ["Find a screen (menu search)", "Ctrl+K"], ["Switch company", "Alt+F3"], ["Help: AI assistant, keys, my shortcuts", "F1  /  Alt+H"], ["Shortcut key directory", "Ctrl+/"]]],
    ["Window (desktop app)", [
      ["Reload the screen", "Ctrl+Shift+R"], ["Full screen", "Shift+F11"], ["Bigger / smaller text of the window", "Ctrl+=  /  Ctrl+-  /  Ctrl+0"]]],
    ["Gateway letters (press on the screen, not in a box)", [
      ["Day book", "D D   or  K"], ["Account ledger", "D A L   or  L"], ["Party statement / ageing", "D A P  /  D A G"], ["Trial balance", "D T   or  T"],
      ["Balance sheet", "D B   or  B"], ["Profit & loss", "D P   or  P"], ["Stock summary / stock card", "D S   or  S  /  D C"], ["VAT / TDS", "D V  /  D X"],
      ["Create ledger / alter ledgers", "A L C  /  A L A"], ["Create stock item / alter items", "A I C  /  A I A"], ["Create party / alter parties", "A P C  /  A P A"],
      ["Create machine / alter machines", "A E C  /  A E A"], ["Create BOQ item / alter", "A B C  /  A B A"], ["Vouchers list", "V"], ["Chart of accounts", "H"]]],
  ];
  function help() {
    if (document.querySelector(".overlay .khelp")) return;
    modal("Keyboard — like Tally", h("div", { class: "khelp" },
      h("p", { class: "hint" }, "BuildCore follows Tally's keys. Vouchers open from anywhere; in any list tick rows with Space and act on them together."),
      HELP.map(([title, rows]) => [h("h4", {}, title), h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, rows.map(([w, k]) => h("tr", {}, h("td", {}, w), h("td", { class: "kbd" }, k))))))])), [], {});
  }
  /* quick.js loads after this file: point its Go-to list and help at the new keys once everything is loaded */
  function late() {
    try {
      if (typeof DOC_KEYS === "object") {
        Object.keys(DOC_KEYS).forEach((k) => { delete DOC_KEYS[k]; });
        Object.entries(FKEYS).forEach(([k, key]) => { DOC_KEYS[k] = ["#/" + ACT[key].path + "?knew=" + key, ACT[key].label]; });
        DOC_KEYS.F10 = ["#/" + ACT.dpr.path + "?knew=dpr", "Daily progress report (F10, D)"];
        DOC_KEYS["Alt+F11"] = ["#/eq/books", "Machine logsheets"];
      }
    } catch (e) { /* older quick.js */ }
    try { if (typeof KEYMAP !== "undefined" && Array.isArray(KEYMAP)) { KEYMAP.length = 0; HELP.forEach(([, rows]) => rows.forEach((r) => KEYMAP.push(r))); } } catch (e) { /* ignore */ }
    window.shortcutHelp = help;
    window.bcoKeyHelp = HELP; window.bcoActs = ACT; window.bcoFKeys = FKEYS; window.bcoKeyName = name;
    window.bcoKeyCmd = { calculator, configure, otherVouchers, oldHelp: help, zoom: cycleZoom };
    window.bcoRunAction = (key) => startAction(key);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", late); else setTimeout(late, 0);

  /* ───────────────────────────── the key handler (runs before the older one) ───────────────────────────── */
  const isTyping = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
  const listKeyOK = (el) => !el || el === document.body || el.classList.contains("klist") || (el.closest && el.closest(".klist") && !el.closest("a,button,input,select,textarea"));
  function name(e) {
    let k = e.key === " " ? "Space" : (e.key.length === 1 ? e.key.toUpperCase() : e.key);
    return (e.ctrlKey || e.metaKey ? "Ctrl+" : "") + (e.altKey ? "Alt+" : "") + (e.shiftKey && (k === "Space" || /^F\d+$/.test(k)) ? "Shift+" : "") + k;
  }
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); };
  const clickText = (root, re) => {
    if (!root) return false;
    const b = [...root.querySelectorAll("button")].find((x) => !x.disabled && x.offsetParent !== null && re.test(x.textContent.trim()));
    if (b) { b.click(); return true; }
    return false;
  };

  function onKey(e) {
    if (!S || !S.user) return;
    if (e.isComposing) return;
    const k = name(e);
    const tgt = e.target;
    const typing = isTyping(tgt);
    const top = overlayTop();
    if (calc && calc.contains(tgt)) return;               // the calculator handles its own keys
    /* 2.9: the user's own shortcut keys come first */
    if (!(top && top.querySelector(".sc-capture")) && window.bcoUserKey && window.bcoUserKey(e, k, typing)) { stop(e); return; }

    /* the F10 list */
    const vl = top && top.querySelector(".kvlist");
    if (vl && vl._key && !typing) { if (vl._key(e)) stop(e); return; }

    /* voucher keys work everywhere, even from inside a form */
    if (FKEYS[k]) { stop(e); return startAction(FKEYS[k]); }
    switch (k) {
      case "F1": case "Alt+H": stop(e); return window.bcoHelp ? window.bcoHelp("ask") : help();
      case "Ctrl+/": stop(e); return window.bcoHelp ? window.bcoHelp("keys") : help();
      case "F10": stop(e); return otherVouchers();
      case "F11": stop(e); location.hash = "#/admin/settings"; return;
      case "F12": stop(e); return configure();
      case "Alt+F11": stop(e); location.hash = "#/eq/books"; return;
      case "Alt+F12": case "Ctrl+F12": {
        const l = activeList();
        stop(e);
        if (!l) return toast("No list on this screen to filter.", "err");
        return k === "Alt+F12" ? l.rangeDialog() : l.valueDialog();
      }
      case "Ctrl+N": stop(e); return calculator();
      case "Alt+Z": stop(e); return cycleZoom();
      case "Ctrl+M": if (!top) { stop(e); location.hash = "#/home"; } return;
      case "Alt+2": stop(e); return duplicate().catch(() => {});
      case "Ctrl+R": {
        if (typing && (tgt.name === "narration" || tgt.name === "remarks")) {
          stop(e);
          const v = LS("bco_last_" + tgt.name, "");
          if (!v) return toast("No earlier narration yet.", "err");
          tgt.value = v; tgt.dispatchEvent(new Event("input", { bubbles: true })); tgt.dispatchEvent(new Event("change", { bubbles: true }));
        }
        return;
      }
      case "Ctrl+Enter": {
        if (typing) {
          const cell = tgt.closest(".combo, label.f, td");
          if (cell && cell._alterMaster) { stop(e); cell._alterMaster(); }
          return;
        }
        const l = activeList();
        if (l && !top) { stop(e); l.open(); }
        return;
      }
      case "Alt+I": {
        const root = top || document.querySelector("#page");
        if (clickText(root, /^(\+\s*)?(Add line|Add row|Insert)/i)) stop(e);
        return;
      }
      case "Alt+P": {
        stop(e);
        if (top) { if (clickText(top.querySelector("footer"), /^Print/) || clickText(top, /^Print/)) return; }
        const l = activeList();
        if (l && l.vis.some((r) => l.sel.has(r))) return l.printRows();
        if (!top && clickText(document.querySelector("#page"), /^Print/)) return;
        if (l && top) return l.printRows();
        if (typeof printPage === "function") return printPage();
        return;
      }
      case "Alt+E": {
        stop(e);
        const l = activeList();
        if (l) return l.exportRows();
        if (clickText(top || document.querySelector("#page"), /Export/)) return;
        return toast("Nothing to export on this screen.", "err");
      }
      case "Alt+C": case "Alt+N": case "Alt+A":
        if (!typing && !top) {
          stop(e);
          if (!clickText(document.querySelector("#page .bar"), NEWRE) && !clickText(document.querySelector("#page"), NEWRE)) toast("Nothing to create on this screen.", "err");
        }
        return;   // in a field, Alt+C / Alt+A make or alter the master (older handler)
      case "Alt+D": {
        if (top && !top.querySelector(".klist .ks")) return;   // the open record: older handler presses Delete / Cancel
        const l = activeList();
        if (l && (l.vis.some((r) => l.sel.has(r)) || (!top && l.focus >= 0))) { stop(e); l.deleteRows().catch(() => {}); }
        return;
      }
      case "Alt+R": case "Alt+U": case "Alt+S": case "Ctrl+Alt+U": {
        const l = activeList();
        if (!l) return;
        stop(e);
        if (k === "Alt+R") return l.hide();
        return l.unhide(k === "Ctrl+Alt+U" || k === "Alt+S");
      }
      default: break;
    }

    /* moving and ticking inside a list */
    if (!typing && listKeyOK(document.activeElement) && ["ArrowDown", "ArrowUp", "Home", "End", "PageDown", "PageUp", "Space", "Ctrl+Space", "Shift+Space", "Enter"].includes(k)) {
      const l = activeList();
      if (l && l.vis.length && (!top || top.contains(l.el))) {
        const f = l.focus;
        switch (k) {
          case "ArrowDown": stop(e); return l.setFocus(f + 1);
          case "ArrowUp": stop(e); return l.setFocus(f < 0 ? 0 : f - 1);
          case "Home": stop(e); return l.setFocus(0);
          case "End": stop(e); return l.setFocus(l.vis.length - 1);
          case "PageDown": stop(e); return l.setFocus(f + 15);
          case "PageUp": stop(e); return l.setFocus(f - 15);
          case "Space": {
            stop(e);
            const i = f < 0 ? 0 : f;
            l.toggle(l.vis[i]); l.anchor = i; return l.setFocus(i + 1);
          }
          case "Ctrl+Space": stop(e); return l.selectAll();
          case "Shift+Space": stop(e); { const i = f < 0 ? 0 : f; l.range(l.anchor >= 0 ? l.anchor : i, i, true); return; }
          case "Enter": if (f >= 0) { stop(e); return l.open(); } return;
          default: break;
        }
      }
    }

    /* Esc: close the letter hint, else go back like Tally */
    if (k === "Escape" && !top && !typing) {
      if (gbuf) { gbuf = ""; gateHide(); stop(e); return; }
      if (document.querySelector(".bspick,.combo-list:not([hidden]),.combo .list:not([hidden])")) return;
      if (LS("bco_escback", "1") === "1" && history.length > 1 && pathNow()) { stop(e); history.back(); }
      return;
    }

    /* Gateway letters */
    if (!typing && !top && !e.ctrlKey && !e.altKey && !e.metaKey && /^[a-zA-Z]$/.test(e.key) && gateOn() && listKeyOK(document.activeElement)) {
      if (gateKey(e.key.toUpperCase())) stop(e);
    }
  }
  window.addEventListener("keydown", (e) => { try { onKey(e); } catch (err) { /* a shortcut must never break the screen */ } }, true);
})();
