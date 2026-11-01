/* BuildCore 2.30: the window fits the screen, month boxes follow the Nepali (BS) date switch, and Events & claims
   lists the events that no DPR delay line points to any more. */
"use strict";
(function () {
  /* ══════════ 1. the top bar never makes the page wider than the window ══════════
     A long project name in the workspace badge pushed the whole page wider than the screen, so a maximised or full
     screen window still scrolled sideways and hid the right end of the bar and of every list. The badge now shortens
     the name (the full name shows on hover) and the bar wraps to a second line before anything goes off screen. */
  const css = document.createElement("style");
  css.textContent =
    ".main{min-width:0;max-width:100%}" +
    ".top{flex-wrap:wrap!important;row-gap:6px!important;min-width:0;max-width:100%}" +
    ".top>*{min-width:0}" +
    ".top>button,.top>.btn,.top .bco-iconbtn,.top .helpbtn,.top .usermenu,.top .menu-btn{flex-shrink:0}" +
    ".top .wsbadge{flex:0 1 auto;min-width:120px;max-width:min(38vw,560px);overflow:hidden}" +
    ".top .wsbadge .wsl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}" +
    ".top .wsbadge .sw{flex-shrink:0}" +
    ".top .cochip{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    ".tablewrap{max-width:100%;overflow-x:auto}" +
    ".bsmonth{display:inline-flex;flex-wrap:wrap;gap:4px 6px;align-items:center}.bsmonth .bsmonth-hint{flex-basis:100%}.bsmonth select{width:auto!important;min-width:0!important}" +
    ".bsmonth-hint{display:block;font-size:11px;color:var(--muted,#6b7280);margin-top:2px}" +
    ".lf-warn{border-left:3px solid #c98a1b;padding:10px 14px;margin:10px 0}";
  document.head.append(css);
  const fitBadge = () => {
    const b = document.querySelector(".top .wsbadge");
    if (!b || b._lf) return;
    const t = [...b.childNodes].find((n) => n.nodeType === 3 && n.nodeValue.trim());
    if (!t) return;
    b._lf = true;
    const full = t.nodeValue;
    const s = document.createElement("span");
    s.className = "wsl";
    s.textContent = full;
    t.replaceWith(s);
    b.title = full + (b.title ? " — " + b.title : "");
  };
  new MutationObserver(fitBadge).observe(document.body, { childList: true, subtree: true });

  /* ══════════ 2. months in Nepali (BS) when the Nepali date switch is on ══════════ */
  let BST = null, loading = null;
  const loadBS = () => loading || (loading = api("bs.table", {}).then((t) => {
    BST = { names: t.months, years: Object.entries(t.years).map(([y, v]) => ({ y: Number(y), start: v.start, m: v.months })).sort((a, b) => a.y - b.y) };
    return BST;
  }).catch(() => { loading = null; return null; }));
  const pad = (n) => String(n).padStart(2, "0");
  const addDays = (iso, n) => { const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const bsRange = (y, m) => {
    const yr = BST && BST.years.find((x) => x.y === y);
    if (!yr) return null;
    const off = yr.m.slice(0, m - 1).reduce((a, b) => a + b, 0);
    const from = addDays(yr.start, off);
    return { from, to: addDays(from, yr.m[m - 1] - 1), label: BST.names[m - 1] + " " + y, key: y + "-" + pad(m) };
  };
  const bsOf = (iso) => {
    if (!BST || !iso) return null;
    for (let i = BST.years.length - 1; i >= 0; i--) {
      const yr = BST.years[i];
      if (iso >= yr.start) {
        let off = Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(yr.start + "T00:00:00Z")) / 864e5);
        for (let k = 0; k < 12; k++) { if (off < yr.m[k]) return { y: yr.y, m: k + 1, d: off + 1 }; off -= yr.m[k]; }
        return null;
      }
    }
    return null;
  };
  /* "17 Aug – 16 Sep 2026": not an ISO date, so the Nepali date switch never turns it into a Nepali one (2.32) */
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const enSpan = (f, t) => {
    const a = f.split("-").map(Number), b = t.split("-").map(Number);
    return a[2] + " " + MON[a[1] - 1] + (a[0] !== b[0] ? " " + a[0] : "") + " – " + b[2] + " " + MON[b[1] - 1] + " " + b[0];
  };
  window.bcoEnSpan = enSpan;
  const monthEnd = (p) => { const [y, m] = p.split("-").map(Number); return p + "-" + pad(new Date(Date.UTC(y, m, 0)).getUTCDate()); };
  const adName = (p) => new Date(Date.UTC(Number(p.slice(0, 4)), Number(p.slice(5, 7)) - 1, 1)).toLocaleString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  const nepali = () => typeof window.bcoDateMode === "function" && window.bcoDateMode() !== "ad";
  window.bcoNepaliMonths = nepali;
  window.bcoLoadBS = loadBS;
  window.bcoBsMonth = (y, m) => bsRange(Number(y), Number(m));
  window.bcoBsRange = (iso) => { const b = bsOf(iso); return b ? bsRange(b.y, b.m) : null; };
  /* "Bhadra 16 – Ashoj 14, 2083" for an English month, once the calendar is loaded */
  window.bcoBsSpan = (from, to) => {
    const a = bsOf(from), b = bsOf(to);
    if (!a || !b) return "";
    const n = (x) => BST.names[x.m - 1];
    return a.y === b.y ? n(a) + " " + a.d + " – " + n(b) + " " + b.d + ", " + b.y : n(a) + " " + a.d + ", " + a.y + " – " + n(b) + " " + b.d + ", " + b.y;
  };

  /* A month box that follows the date switch. English: the normal month box. Nepali: BS month and year.
     o = { value: "2026-10" | {from}, onChange(sel), label } ; sel = { from, to, label, key, bs } */
  window.bcoMonthBox = function (o) {
    const wrap = h("span", { class: "bsmonth" });
    const fire = (sel) => { wrap._sel = sel; if (o.onChange) o.onChange(sel); };
    const english = (p) => {
      const inp = h("input", { type: "month", value: p, style: "width:auto", onchange: (e) => { if (e.target.value) fire({ from: e.target.value + "-01", to: monthEnd(e.target.value), label: adName(e.target.value), key: e.target.value, bs: false }); } });
      wrap.append(inp);
      wrap._sel = { from: p + "-01", to: monthEnd(p), label: adName(p), key: p, bs: false };
    };
    const startIso = (o.from || ((o.value || today().slice(0, 7)) + "-01"));
    const p0 = (o.value || startIso).slice(0, 7);
    if (!nepali() && !o.bs) { english(p0); return wrap; }
    english(p0);                                    /* until the BS calendar is loaded */
    loadBS().then((t) => {
      if (!t) return;
      const b = bsOf(o.from || today()) || bsOf(today());
      if (!b) return;
      wrap.innerHTML = "";
      const ms = h("select", { title: "Nepali month" }, t.names.map((n, i) => h("option", { value: i + 1, selected: i + 1 === b.m }, n)));
      const ys = h("select", { title: "Nepali year" }, t.years.map((x) => h("option", { value: x.y, selected: x.y === b.y }, x.y)));
      const hint = h("span", { class: "bsmonth-hint no-bs" });
      const upd = (go) => { const r = bsRange(Number(ys.value), Number(ms.value)); if (!r) return; hint.textContent = "English dates " + enSpan(r.from, r.to); const sel = Object.assign({ bs: true }, r); if (go) fire(sel); else wrap._sel = sel; };
      ms.onchange = () => upd(true); ys.onchange = () => upd(true);
      wrap.append(ms, ys, hint);
      upd(o.fireOnLoad !== false);
    });
    return wrap;
  };

  /* any other month box (hire bills, depreciation, charges …) keeps its English month — those documents are kept by
     English month — and shows the Nepali dates it covers underneath */
  const hintMonth = (inp) => {
    if (inp._lf || inp.closest(".bsmonth")) return;
    inp._lf = true;
    const tip = h("span", { class: "bsmonth-hint" });
    const show = () => { if (!nepali() || !inp.value) { tip.textContent = ""; return; } loadBS().then(() => { tip.textContent = window.bcoBsSpan(inp.value + "-01", monthEnd(inp.value)) + " (BS)"; }); };
    inp.addEventListener("change", show); inp.addEventListener("input", show);
    inp.after(tip);
    show();
  };
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
    if (n.nodeType !== 1) return;
    if (n.matches && n.matches('input[type="month"]')) hintMonth(n);
    n.querySelectorAll && n.querySelectorAll('input[type="month"]').forEach(hintMonth);
  }))).observe(document.body, { childList: true, subtree: true });
  if (nepali()) loadBS();

  /* ══════════ 3. Events & claims: events whose DPR delay line is gone ══════════ */
  const evPage = PAGES["p/events"];
  if (evPage && !evPage.__lf) {
    PAGES["p/events"] = async (root, params) => {
      await evPage(root, params);
      if (!S.project) return;
      let d;
      try { d = await api("lf.event_check", { project_id: S.project }); } catch (e) { return; }
      if (!d.rows.length) return;
      const box = h("div", { class: "panel lf-warn" });
      const canTidy = can("commercial", "edit") || can("project", "edit");
      box.append(h("b", {}, d.rows.length + (d.rows.length === 1 ? " event no longer matches" : " events no longer match") + " a DPR delay line"),
        h("p", { class: "hint" }, "BuildCore makes a contract event when a DPR delay line is marked as a contract event. Before 2.30, saving the DPR again (after a return or a reopen) lost that link, so an event stayed after its delay line was removed and approving again made a second copy. "
          + (d.removable ? d.removable + " of them nobody has worked on and can be removed. " : "") + (d.kept ? d.kept + " have been worked on (notice, status, claim or EOT) and stay; review them yourself." : "")),
        table([{ k: "no", label: "Event" }, { k: "date", label: "Date" }, { k: "title", label: "Title" }, { k: "dpr_no", label: "DPR" }, { k: "why", label: "Why it does not match" },
          { label: "Worked on", v: (r) => r.worked_on ? h("b", {}, "Yes — stays") : "No" }], d.rows, { search: false, export: false, name: "events_not_on_dpr" }),
        canTidy && d.removable ? h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => {
          if (!(await confirmBox("Remove " + d.removable + " event(s) nobody worked on? Their review tasks are closed. Events that were worked on stay."))) return;
          const r = await run("lf.event_tidy", { project_id: S.project }, (x) => x.removed + " event(s) removed");
          if (r) go();
        } }, "Remove the " + d.removable + " nobody worked on")) : "");
      const first = root.querySelector(".tablewrap");
      const anchor = first ? first.closest("div") : null;
      if (anchor && anchor.parentElement) anchor.parentElement.insertBefore(box, anchor); else root.append(box);
    };
    PAGES["p/events"].__lf = true;
    if (evPage.__bco) PAGES["p/events"].__bco = evPage.__bco;
  }
  async function confirmBox(text) {
    if (typeof ask === "function") { const r = await ask("Please confirm", text, { ok: "Yes, remove" }); return r !== null && r !== false; }
    return window.confirm(text);
  }
})();
