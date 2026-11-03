/* BuildCore 2.46 — Tally-style accounting.
   Accounts › Gateway (one new menu item; nothing else moves). From the Gateway, with the letters accountants know:
     Masters: C Create, A Alter, H Chart of Accounts · Transactions: V Vouchers, K Day Book · Utilities: N Banking
     Reports: B Balance Sheet, P Profit & Loss A/c, T Trial Balance, S Stock Summary, R Ratio Analysis, D Display More
     Settings: F11 Features, F12 Configure, M Group mapping, Y Voucher types, L Edit Log, X Controls
   Keyboard voucher entry: F4 Contra, F5 Payment, F6 Receipt, F7 Journal (F8/F9, Ctrl+F8/F9 keep opening BuildCore's
   client invoice / purchase bill screens, so the VAT books stay right). Every voucher saves through BuildCore's own
   engine functions; nothing is copied. */
(function () {
  "use strict";
  if (window.__bcoTally) return;
  window.__bcoTally = true;

  const M = (v) => (v == null || v === "" ? "" : fmtMoney(v));
  const DC = (b) => (b == null ? "" : Math.abs(b) < 0.005 ? "" : fmtMoney(Math.abs(b)) + (b > 0 ? " Dr" : " Cr"));
  const N = (v) => { const x = Number(String(v == null ? "" : v).replace(/,/g, "")); return isFinite(x) ? Math.round(x * 100) / 100 : 0; };
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } };
  const pathNow = () => location.hash.replace(/^#\/?/, "").split("?")[0];
  const bsOf = (iso) => { try { const b = window.adToBs ? window.adToBs(iso) : ""; if (!b) return ""; const [y, m, d] = b.split("-"); return Number(d) + " " + ((window.BS_MONTHS || [])[Number(m) - 1] || m) + " " + y; } catch (e) { return ""; } };
  const TL = { meta: null, ledgers: null, vtypes: null };

  const css = document.createElement("style");
  css.textContent = [
    ".tlgw{display:grid;grid-template-columns:1fr 210px;gap:16px}.tlgw .menu{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}",
    ".tlgw .col{background:var(--panel,#fff);border:1px solid var(--line,#dde3ea);border-radius:8px;padding:10px 12px}",
    ".tlgw .col h4{margin:0 0 6px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted,#6b7280)}",
    ".tlgw .col a{display:flex;justify-content:space-between;padding:5px 6px;border-radius:5px;cursor:pointer;text-decoration:none;color:inherit}",
    ".tlgw .col a:hover,.tlgw .col a:focus{background:#e8f0f7;outline:none}.tlgw .col a b{font-family:monospace;color:var(--blue,#1f6fb2)}",
    ".tlkeys{background:var(--panel,#fff);border:1px solid var(--line,#dde3ea);border-radius:8px;padding:8px;font-size:12.5px;align-self:start;position:sticky;top:8px}",
    ".tlkeys a{display:flex;gap:8px;padding:4px 6px;border-radius:4px;cursor:pointer;color:inherit;text-decoration:none}.tlkeys a:hover{background:#e8f0f7}",
    ".tlkeys a b{font-family:monospace;min-width:58px;color:var(--blue,#1f6fb2)}",
    ".tlv{display:grid;grid-template-columns:1fr 200px;gap:14px}.tlv .sheet{background:var(--panel,#fff);border:1px solid var(--line,#dde3ea);border-radius:8px;padding:12px}",
    ".tlv .hd{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;border-bottom:1px solid var(--line,#dde3ea);padding-bottom:8px;margin-bottom:8px}",
    ".tlv .hd .ty{font-size:18px;font-weight:700}.tlv .hd label{display:flex;gap:6px;align-items:center;margin:0}.tlv .hd input,.tlv .hd select{width:auto;margin:0}",
    ".tlv table.g{width:100%;border-collapse:collapse}.tlv table.g th{font-size:12px;text-align:left;color:var(--muted,#6b7280);border-bottom:1px solid var(--line,#dde3ea);padding:4px}",
    ".tlv table.g td{padding:2px 4px;vertical-align:top}.tlv table.g td input{margin:0;width:100%}.tlv table.g td.n input{text-align:right}",
    ".tlv table.g td.side input{width:44px;text-transform:capitalize}.tlv .bal{font-size:11.5px;color:var(--muted,#6b7280);white-space:nowrap}",
    ".tlv .sub{font-size:11.5px;color:#1f6fb2;margin:0 0 2px 6px}.tlv .tot{display:flex;justify-content:flex-end;gap:24px;border-top:1px solid var(--line,#dde3ea);margin-top:6px;padding-top:6px;font-weight:600}",
    ".tlv .words{font-size:12.5px;color:var(--muted,#6b7280);text-align:right;margin-top:2px}.tlv .lock{background:#fff4cc;border:1px solid #ecd58a;border-radius:6px;padding:6px 10px;margin-bottom:8px}",
    ".tlv .pend{background:#e8f0f7;border:1px solid #c5d8ea;border-radius:6px;padding:6px 10px;margin-bottom:8px}",
    ".tlpick{position:absolute;z-index:9990;background:var(--panel,#fff);border:1px solid var(--line,#ccc);border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.18);max-height:340px;overflow:auto;min-width:360px;font-size:13px}",
    ".tlpick div{display:flex;justify-content:space-between;gap:12px;padding:4px 8px;cursor:pointer}.tlpick div.on{background:#dcebf8}.tlpick div i{font-style:normal;color:var(--muted,#6b7280);font-size:11.5px}",
    ".tlpick div.cr{color:#1f6fb2;font-weight:600;border-bottom:1px solid var(--line,#eee)}.tlpick div.off{opacity:.45;cursor:not-allowed}",
    ".tlrep table{width:100%}.tlrep tr.g td:first-child{font-weight:600}.tlrep tr.l td:first-child{color:#374151}.tlrep tr[tabindex]:focus td{background:#fff4cc}",
    ".tlrep tr.tot td{font-weight:700;border-top:2px solid var(--line,#ccc)}.tlrep td.num{text-align:right;white-space:nowrap}.tlrep tr.click{cursor:pointer}",
    ".tlhz{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid var(--line,#dde3ea);border-radius:8px;overflow:hidden;background:var(--panel,#fff)}",
    ".tlhz>div{padding:6px 10px}.tlhz>div+div{border-left:1px solid var(--line,#dde3ea)}.tlhz h4{margin:4px 0 6px}",
    ".tlhz .r{display:flex;justify-content:space-between;padding:3px 0;cursor:pointer}.tlhz .r.sub{padding-left:16px;color:#4b5563;font-size:12.5px}.tlhz .r.big{font-weight:700;border-top:1px solid var(--line,#ddd);margin-top:6px}",
    ".tlnote{font-size:12px;color:var(--muted,#6b7280);margin-top:6px}",
    "@media (max-width:860px){.tlgw,.tlv{grid-template-columns:1fr}.tlkeys{position:static}.tlhz{grid-template-columns:1fr}.tlhz>div+div{border-left:0;border-top:1px solid var(--line,#dde3ea)}}",
    "@media print{.tlkeys,.tlv .hd select{display:none!important}}",
  ].join("\n");
  document.head.append(css);

  async function meta(force) { if (!TL.meta || force) TL.meta = await api("tl.meta", {}); return TL.meta; }
  async function ledgers(force) { if (!TL.ledgers || force) TL.ledgers = await api("tl.ledgers", {}); return TL.ledgers; }
  async function vtypes(force) { if (!TL.vtypes || force) TL.vtypes = await api("tl.vtypes", {}); return TL.vtypes; }
  const cfg = (k) => { const c = (TL.meta && TL.meta.cfg) || {}; return c[k]; };
  const feat = (k) => !!((TL.meta && TL.meta.features) || []).find((f) => f.key === k && f.on);
  const sideLabel = (s) => (cfg("drcr") === "1" ? (s === "dr" ? "Dr" : "Cr") : (s === "dr" ? "By" : "To"));

  function keyBar(items) {
    return h("div", { class: "tlkeys" }, items.filter(Boolean).map(([k, label, fn]) => h("a", { onclick: fn }, h("b", {}, k), h("span", {}, label))));
  }
  function offPanel(m) {
    return h("div", { class: "panel" }, h("b", {}, "Tally-style accounting is off for this company."),
      h("p", { class: "hint" }, "The Gateway reports below still open (they only read the books). Keyboard voucher entry, the audit lock date, back-date limits and the Edit Log start when accounts turns it on. Nothing already entered changes."),
      m.can_change ? h("button", { class: "btn primary", onclick: async () => { await run("tl.settings_save", { on: 1 }, "Tally-style accounting is on"); TL.meta = null; go(); } }, "Turn it on") : h("p", { class: "hint" }, "Ask someone with Accounts approve rights to turn it on."));
  }

  /* ───────────────────────────── Gateway ───────────────────────────── */
  const GW = [
    ["Masters", [["C", "Create", () => createMenu()], ["A", "Alter", () => alterMenu()], ["H", "Chart of Accounts", () => nav("tl/coa")]]],
    ["Transactions", [["V", "Vouchers", () => openVoucher(LSg("bco_tl_last", "payment"))], ["K", "Day Book", () => nav("tl/daybook")]]],
    ["Utilities", [["N", "Banking (bank reconciliation)", () => nav("acc/bank")]]],
    ["Reports", [["B", "Balance Sheet", () => nav("tl/bs")], ["P", "Profit & Loss A/c", () => nav("tl/pl")], ["T", "Trial Balance", () => nav("tl/tb")],
      ["S", "Stock Summary", () => nav("inv/stock")], ["R", "Ratio Analysis", () => nav("acc/cash")], ["D", "Display More Reports", () => moreReports()]]],
    ["Settings", [["F", "Features (F11)", () => nav("tl/features")], ["G", "Configure (F12)", () => configure()], ["M", "Group mapping", () => nav("tl/map")],
      ["Y", "Voucher types", () => nav("tl/vtypes")], ["L", "Edit Log", () => nav("tl/editlog")], ["X", "Controls: lock date, back-date", () => nav("tl/controls")]]],
  ];
  const nav = (p) => { location.hash = "#/" + p; };
  async function gateway(root) {
    const m = await meta(true);
    root.append(pageHead("Gateway", (m.company || "Company") + " · FY " + m.fy + " · " + m.today + (bsOf(m.today) ? " (" + bsOf(m.today) + ")" : "")));
    if (!m.on) root.append(offPanel(m));
    if (m.on && m.unconfirmed) root.append(h("div", { class: "panel" }, h("b", {}, m.unconfirmed + " ledgers have a proposed group that nobody has confirmed. "), h("a", { href: "#/tl/map" }, "Check the group mapping (M)"), h("span", { class: "hint" }, " — the reports work meanwhile.")));
    const menu = h("div", { class: "menu" }, GW.map(([title, items]) => h("div", { class: "col" }, h("h4", {}, title),
      items.map(([k, label, fn]) => h("a", { tabindex: 0, onclick: fn, onkeydown: (e) => { if (e.key === "Enter") fn(); } }, h("span", {}, label), h("b", {}, k))))));
    root.append(h("div", { class: "tlgw" }, menu, keyBar([["F4", "Contra", () => openVoucher("contra")], ["F5", "Payment", () => openVoucher("payment")], ["F6", "Receipt", () => openVoucher("receipt")],
      ["F7", "Journal", () => openVoucher("journal")], ["F8", "Sales (client invoice)", () => nav("acc/sales")], ["F9", "Purchase (bill)", () => nav("proc/invoices")],
      ["F10", "Other vouchers", null], ["F11", "Features", () => nav("tl/features")], ["F12", "Configure", () => configure()], ["Alt+G", "Go To", null]])));
    root.append(h("p", { class: "tlnote" }, "Press the letter. F8 / F9 and Ctrl+F8 / Ctrl+F9 open BuildCore's client invoice and purchase bill screens so the VAT books stay right. Version " + m.version + "."));
  }
  function createMenu() {
    const items = [["G", "Group", () => groupDialog({})], ["L", "Ledger", () => newLedger()], ["P", "Party (vendor / client)", () => masterNew("parties", "m/parties")],
      ["V", "Voucher type", () => vtypeDialog({})], ["I", "Stock item", () => masterNew("materials", "m/materials")], ["C", "Cost centre: project", () => masterNew("projects", "m/projects")],
      ["B", "Cost centre: BOQ item", () => masterNew("boq_items", "m/boq")], ["E", "Cost centre: machine", () => masterNew("equipment", "eq/register")], ["T", "TDS nature of payment", () => nav("acc/tdsrates")]];
    pickMenu("Create", items);
  }
  function alterMenu() {
    pickMenu("Alter", [["G", "Groups", () => nav("tl/coa")], ["L", "Ledgers", () => nav("tl/coa")], ["P", "Parties", () => nav("m/parties")], ["V", "Voucher types", () => nav("tl/vtypes")],
      ["I", "Stock items", () => nav("m/materials")], ["C", "Projects", () => nav("m/projects")], ["B", "BOQ items", () => nav("m/boq")], ["E", "Machines", () => nav("eq/register")]]);
  }
  function moreReports() {
    pickMenu("Display More Reports", [["T", "Trial Balance", () => nav("tl/tb")], ["D", "Day Book", () => nav("tl/daybook")], ["L", "Ledger (account books)", () => nav("acc/ledger")],
      ["C", "Cash / Bank book", () => nav("acc/ledger")], ["P", "Party statement (statement of accounts)", () => nav("acc/party")], ["O", "Outstandings (ageing)", () => nav("acc/ageing")],
      ["V", "VAT books", () => nav("acc/vat")], ["X", "TDS register", () => nav("acc/tds")], ["B", "Budget vs actual", () => nav("acc/budget")], ["E", "Edit Log", () => nav("tl/editlog")], ["I", "Integrity checks", () => nav("acc/integrity")]]);
  }
  function pickMenu(title, items) {
    let on = 0, m = null;
    const box = h("div", { class: "kvlist" });
    const pick = (i) => { m.close(); items[i][2](); };
    const draw = () => { box.innerHTML = ""; items.forEach(([k, l], i) => box.append(h("a", { class: i === on ? "on" : "", onclick: () => pick(i) }, h("i", {}, k), h("span", {}, l)))); };
    draw();
    box._key = (e) => {
      if (e.key === "ArrowDown") { on = Math.min(items.length - 1, on + 1); draw(); return true; }
      if (e.key === "ArrowUp") { on = Math.max(0, on - 1); draw(); return true; }
      if (e.key === "Enter") { pick(on); return true; }
      const i = e.key.length === 1 ? items.findIndex(([k]) => k === e.key.toUpperCase()) : -1;
      if (i >= 0 && !e.ctrlKey && !e.altKey) { pick(i); return true; }
      return false;
    };
    m = modal(title, h("div", {}, h("p", { class: "hint" }, "Press the letter, or ↑ ↓ and Enter."), box), [], { narrow: true });
  }
  async function masterNew(table, path) {
    if (typeof MASTERS_UI !== "undefined" && MASTERS_UI[table] && typeof masterDialog === "function") {
      const r = masterDialog(table, {});
      if (r && r.then) await r;
      TL.ledgers = null;
      return;
    }
    nav(path);
  }
  async function newLedger(after) {
    if (typeof MASTERS_UI !== "undefined" && MASTERS_UI.accounts && typeof masterDialog === "function") {
      try { const r = masterDialog("accounts", {}, async () => { TL.ledgers = null; if (after) after(); }); if (r && r.then) await r; } catch (e) { /* closed */ }
      TL.ledgers = null;
      return;
    }
    nav("acc/coa");
  }

  /* ───────────────────────────── Configure (F12) ───────────────────────────── */
  async function configure() {
    const m = await meta();
    const c = Object.assign({}, m.cfg);
    const box = h("div", {});
    const chk = (k, label) => { const i = h("input", { type: "checkbox", checked: c[k] === "1", onchange: () => { c[k] = i.checked ? "1" : "0"; } }); box.append(h("label", { style: "display:flex;gap:8px;align-items:center" }, i, label)); };
    chk("keys", "F4 / F5 / F6 / F7 open the keyboard voucher screen (off = BuildCore's voucher dialogs, as before)");
    chk("drcr", "Use Dr / Cr instead of To / By during voucher entry");
    chk("show_balance", "Show the ledger's current balance during voucher entry");
    chk("line_narration", "Narration for each ledger line");
    ["payment", "receipt", "contra", "journal"].forEach((b) => {
      const s = h("select", { onchange: () => { c["mode_" + b] = s.value; } }, h("option", { value: "single" }, "Single entry"), h("option", { value: "double" }, "Double entry (Dr / Cr)"));
      s.value = c["mode_" + b] || (b === "journal" ? "double" : "single");
      box.append(h("label", { class: "f" }, h("span", {}, "Voucher mode for " + b), s));
    });
    modal("Configure (F12) — your own settings", box, [{ label: "Save", cls: "primary", act: async () => { await run("tl.cfg_save", { cfg: c }, "Saved"); TL.meta = null; await meta(true); } }], { narrow: true });
  }

  /* ───────────────────────────── Features (F11) and controls ───────────────────────────── */
  async function featuresPage(root) {
    const m = await meta(true);
    root.append(pageHead("Features (F11)", "Switch on what this company uses. Advanced features stay off until you need them."));
    const st = { on: m.on ? 1 : 0, policy: m.policy, features: {} };
    m.features.forEach((f) => { st.features[f.key] = f.on ? 1 : 0; });
    const box = h("div", { class: "panel" });
    const onI = h("input", { type: "checkbox", checked: m.on, disabled: !m.can_change, onchange: () => { st.on = onI.checked ? 1 : 0; } });
    box.append(h("label", { style: "display:flex;gap:8px;align-items:center;font-weight:600" }, onI, "Tally-style accounting for this company (keyboard voucher entry, lock date, Edit Log)"));
    const pol = h("select", { disabled: !m.can_change, onchange: () => { st.policy = pol.value; } }, h("option", { value: "reverse_only" }, "Reverse only — posted vouchers are cancelled by reversal and entered again (BuildCore's rule until now)"),
      h("option", { value: "edit_with_log" }, "Edit with log — a manual voucher can be altered while it is not locked; the number stays and every version is kept"));
    pol.value = m.policy;
    box.append(h("label", { class: "f" }, h("span", {}, "Alteration of posted vouchers"), pol));
    box.append(h("p", { class: "hint" }, "Posted vouchers stay permanent in both cases: an alteration reverses the old version on its own date and posts the new one under the same number; the Day Book shows only the latest version and the Edit Log shows them all."));
    root.append(box);
    let grp = "";
    const list = h("div", { class: "panel" });
    m.features.forEach((f) => {
      if (f.group !== grp) { grp = f.group; list.append(h("h4", {}, grp)); }
      const i = h("input", { type: "checkbox", checked: f.on, disabled: !f.live || !m.can_change, onchange: () => { st.features[f.key] = i.checked ? 1 : 0; } });
      list.append(h("label", { style: "display:flex;gap:8px;align-items:center" + (f.live ? "" : ";opacity:.6") }, i, f.label, f.live ? null : h("span", { class: "hint" }, " — comes in " + (f.later || "a later version"))));
    });
    root.append(list);
    if (m.can_change) root.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("tl.settings_save", st, "Features saved"); TL.meta = null; go(); } }, "Save (Ctrl+A)")));
    else root.append(h("p", { class: "hint" }, "Only someone with Accounts approve rights can change features."));
  }

  async function controlsPage(root) {
    const m = await meta(true);
    root.append(pageHead("Controls", "Audit lock date, back-dated entries and alteration limits per job. 0 = no limit. The administrator is never limited."));
    if (!m.on) root.append(offPanel(m));
    const st = { lock_date: m.lock_date, backdate: Object.assign({}, m.backdate), alterdays: Object.assign({}, m.alterdays) };
    const lk = h("input", { type: "date", value: m.lock_date || "", disabled: !m.can_change, onchange: () => { st.lock_date = lk.value; } });
    root.append(h("div", { class: "panel" }, h("label", { class: "f" }, h("span", {}, "Audit lock date: no voucher dated on or before this date can be created, altered or cancelled"), lk),
      h("p", { class: "hint" }, "Only the administrator can move the lock date back or remove it. Closed periods (Accounts › Periods) stay closed as before.")));
    const rows = m.jobs.map((j) => ({ job: j }));
    const tb = h("tbody", {}, rows.map((r) => {
      const b = h("input", { type: "number", min: 0, value: st.backdate[r.job] || "", disabled: !m.can_change, style: "width:90px", onchange: () => { st.backdate[r.job] = b.value || 0; } });
      const a = h("input", { type: "number", min: 0, value: st.alterdays[r.job] || "", disabled: !m.can_change, style: "width:90px", onchange: () => { st.alterdays[r.job] = a.value || 0; } });
      return h("tr", {}, h("td", {}, r.job.replace(/_/g, " ")), h("td", {}, b), h("td", {}, a));
    }));
    root.append(h("div", { class: "panel" }, h("h4", {}, "Per job"), h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Job"), h("th", {}, "Enter vouchers dated up to N days before today"), h("th", {}, "Alter vouchers up to N days old"))), tb))));
    if (m.can_change) root.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("tl.settings_save", st, "Controls saved"); TL.meta = null; go(); } }, "Save")));
  }

  /* ───────────────────────────── groups, chart of accounts, mapping ───────────────────────────── */
  async function groupDialog(g, done) {
    const d = await api("tl.groups", {});
    const f = form([{ k: "name", label: "Name" }, { k: "parent_id", label: "Under", type: "select", noBlank: true, options: d.groups.filter((x) => x.id !== g.id).map((x) => [x.id, x.name + (x.parent ? " (" + x.parent + ")" : "")]) }], { name: g.name || "", parent_id: g.parent_id || (d.groups.find((x) => x.name === "Current Assets") || {}).id });
    if (g.system) { const sel = f.querySelector("[name=parent_id]"); if (sel) sel.disabled = true; }
    modal(g.id ? "Alter group" : "Create group", h("div", {}, f, g.system ? h("p", { class: "hint" }, "A predefined group: it can be renamed; its place and nature are fixed.") : h("p", { class: "hint" }, "A new group takes its nature (asset, liability, income, expense) from the group it sits under.")),
      [{ label: "Accept", cls: "primary", act: async () => { await run("tl.group_save", Object.assign({ id: g.id }, f.values()), "Group saved"); if (done) done(); } },
        g.id && !g.system ? { label: "Delete", cls: "warn", act: async () => { await run("tl.group_delete", { id: g.id }, "Deleted"); if (done) done(); } } : null], { narrow: true });
  }

  async function coaPage(root) {
    root.append(pageHead("Chart of Accounts", "Groups (the 28 predefined groups and your own) with their ledgers. Parties appear as ledgers under Sundry Creditors / Sundry Debtors in the reports.",
      h("button", { class: "btn", onclick: () => groupDialog({}, () => go()) }, "Create group"), h("button", { class: "btn", onclick: () => newLedger(() => go()) }, "Create ledger"),
      h("button", { class: "btn", onclick: async () => { const r = await run("tl.pack", {}); toast(r.created.length ? "Added: " + r.created.join(", ") : "The contractor pack is already there.", "ok"); go(); } }, "Add contractor pack"),
      h("a", { class: "btn", href: "#/tl/map" }, "Group mapping")));
    const [d, mp] = await Promise.all([api("tl.groups", {}), api("tl.map", {})]);
    const kids = (pid) => d.groups.filter((g) => (g.parent_id || null) === (pid || null));
    const accs = (gid) => mp.rows.filter((r) => r.tl_group_id === gid);
    const tb = h("tbody");
    const add = (g, depth) => {
      tb.append(h("tr", { class: "g click", tabindex: 0, onclick: () => groupDialog(g, () => go()) }, h("td", { style: "padding-left:" + (8 + depth * 18) + "px" }, g.name), h("td", {}, g.nature), h("td", {}, g.system ? "predefined" : g.pack ? "contractor pack" : "yours"), h("td", { class: "num" }, String(g.accounts || ""))));
      accs(g.id).forEach((a) => tb.append(h("tr", { class: "l click", tabindex: 0, onclick: () => ledgerDialog(a.id, () => go()) }, h("td", { style: "padding-left:" + (26 + depth * 18) + "px" }, a.code + " · " + a.name + (a.active ? "" : " (inactive)")), h("td", {}, a.type), h("td", {}, a.confirmed ? "" : h("span", { class: "hint" }, "proposed")), h("td"))));
      kids(g.id).forEach((x) => add(x, depth + 1));
    };
    kids(null).forEach((g) => add(g, 0));
    root.append(h("div", { class: "tlrep" }, h("div", { class: "tablewrap" }, h("table", { onkeydown: rowKeys }, h("thead", {}, h("tr", {}, h("th", {}, "Group / ledger"), h("th", {}, "Nature"), h("th", {}, ""), h("th", { class: "num" }, "Ledgers"))), tb))));
  }

  async function ledgerDialog(accountId, done) {
    const [d, gs] = await Promise.all([api("tl.ledger_get", { account_id: accountId }), api("tl.groups", {})]);
    const S0 = S.L || {};
    const e = d.extra || {};
    const f = form([{ k: "tl_group_id", label: "Under (group)", type: "select", noBlank: true, options: gs.groups.map((x) => [x.id, x.name]) },
      { k: "alias", label: "Alias" }, { k: "billwise", label: "Maintain balances bill-by-bill", type: "select", noBlank: true, options: [[0, "No"], [1, "Yes"]] },
      { k: "credit_days", label: "Default credit period (days)", type: "number" }, { k: "credit_limit", label: "Credit limit", type: "number" },
      { k: "cc_on", label: "Cost centres are applicable", type: "select", noBlank: true, options: [[1, "Yes"], [0, "No"]] },
      { k: "pan", label: "PAN (9 digits)" }, { k: "tds_rate_id", label: "TDS nature of payment", type: "select", options: (S0.tds || []).map((t) => [t.id, t.section + " · " + t.description + " · " + t.rate + "%"]) },
      { k: "note", label: "Note", wide: true }], Object.assign({}, e, { tl_group_id: d.map ? d.map.tl_group_id : "" }));
    modal("Ledger: " + d.account.code + " · " + d.account.name, h("div", {}, h("p", { class: "hint" }, "Name, code, type and opening balance are changed in Accounts › Chart of accounts as before. Here: the Tally-style details."), f),
      [{ label: "Accept", cls: "primary", act: async () => { await run("tl.ledger_save", Object.assign({ account_id: accountId }, f.values()), "Ledger saved"); TL.ledgers = null; if (done) done(); } },
        { label: "Edit Log", act: () => { editLogModal("ledger", accountId); return false; }, keep: true }]);
  }

  async function mapPage(root, params) {
    root.append(pageHead("Group mapping", "Each account of your chart of accounts under one of the Tally groups. BuildCore proposed a group from the account's role and BuildCore group; confirm or change it. Only the reports' grouping changes; no voucher line or balance moves."));
    const d = await api("tl.map", {});
    const only = params.all !== "1";
    const rows = only && d.unconfirmed ? d.rows.filter((r) => !r.confirmed) : d.rows;
    const st = {};
    const opts = d.groups.map((g) => [g.id, g.name]);
    const tb = h("tbody", {}, rows.map((r) => {
      const s = h("select", { onchange: () => { st[r.id] = Number(s.value); } }, opts.map((o) => h("option", { value: o[0] }, o[1])));
      s.value = r.tl_group_id;
      return h("tr", {}, h("td", {}, r.code), h("td", {}, r.name + (r.active ? "" : " (inactive)")), h("td", {}, r.buildcore_group || ""), h("td", {}, r.role || ""), h("td", {}, s), h("td", {}, r.confirmed ? "confirmed" : h("b", { class: "amber" }, "proposed")));
    }));
    root.append(h("p", {}, d.unconfirmed ? d.unconfirmed + " not confirmed yet. " : "All confirmed. ", h("a", { href: only ? "#/tl/map?all=1" : "#/tl/map" }, only ? "Show all accounts" : "Show only the unconfirmed")));
    root.append(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Code", "Account", "BuildCore group", "Role", "Tally group", "State"].map((x) => h("th", {}, x)))), tb)));
    if (can("accounts", "edit")) root.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const out = rows.map((r) => ({ account_id: r.id, tl_group_id: st[r.id] || r.tl_group_id }));
      const res = await run("tl.map_save", { rows: out });
      toast(res.saved + " saved; " + res.unconfirmed + " still to confirm.", "ok"); go();
    } }, "Confirm the groups shown")));
  }

  /* ───────────────────────────── voucher types ───────────────────────────── */
  async function vtypesPage(root) {
    const rows = await vtypes(true);
    root.append(pageHead("Voucher types", "The 24 predefined voucher types, BuildCore's own types and yours. Create a child type (e.g. Site Payment - SMK under Payment) with its own numbering.",
      can("accounts", "approve") ? h("button", { class: "btn primary", onclick: () => vtypeDialog({}, () => go()) }, "Create voucher type") : null));
    root.append(table([{ k: "name", label: "Name" }, { k: "parent", label: "Type of voucher" }, { k: "category", label: "Kind" }, { k: "abbr", label: "Abbr." },
      { label: "Numbering", v: (r) => r.method.replace(/_/g, " ") + (r.prefix || r.suffix ? " · " + (r.prefix || "") + "0001" + (r.suffix || "") : "") + (r.series_by === "project" ? " · per project" : "") + (r.restart !== "yearly" ? " · " + r.restart : "") },
      { label: "Statutory", v: (r) => r.statutory ? "yes" : "" }, { label: "Entered in", v: (r) => r.can_enter ? "Voucher screen (F4–F7)" : r.entry === "later" ? "later version" : r.entry },
      { k: "used", label: "Used", fmt: "num" }, { label: "Active", v: (r) => r.active ? "yes" : "no" }], rows,
    { name: "tl_vtypes", onRow: can("accounts", "approve") ? (r) => vtypeDialog(r, () => go()) : null }));
  }
  async function vtypeDialog(vt, done) {
    const all = await vtypes(true);
    const isNew = !vt.id;
    const f = form([{ k: "name", label: "Name", readonly: !!(vt.system && !vt.parent_id) },
      isNew ? { k: "parent_id", label: "Type of voucher", type: "select", noBlank: true, options: all.filter((x) => !x.parent_id).map((x) => [x.id, x.name]) } : null,
      { k: "abbr", label: "Abbreviation" }, { k: "active", label: "Active", type: "select", noBlank: true, options: [[1, "Yes"], [0, "No"]] },
      { k: "method", label: "Method of voucher numbering", type: "select", noBlank: true, options: [["automatic", "Automatic"], ["automatic_manual_override", "Automatic (manual override)"], ["manual", "Manual"], ["none", "None"]].map(([v, l]) => [v, l]) },
      { k: "prevent_dup", label: "Prevent duplicates", type: "select", noBlank: true, options: [[1, "Yes"], [0, "No"]] },
      { k: "prefix", label: "Prefix ({FY} {MM} {YYYY} {PROJECT})" }, { k: "suffix", label: "Suffix" }, { k: "width", label: "Width of number", type: "number" }, { k: "start_no", label: "Starting number", type: "number" },
      { k: "restart", label: "Restart numbering", type: "select", noBlank: true, options: [["yearly", "Every fiscal year"], ["monthly", "Every month"], ["never", "Never"]].map(([v, l]) => [v, l]) },
      { k: "series_by", label: "Numbering series", type: "select", noBlank: true, options: [["none", "One series"], ["project", "One series per project"]].map(([v, l]) => [v, l]) },
      { k: "default_mode", label: "Default entry mode", type: "select", options: [["single", "Single entry"], ["double", "Double entry"]].map(([v, l]) => [v, l]) },
      { k: "line_narration", label: "Narration for each line", type: "select", noBlank: true, options: [[0, "No"], [1, "Yes"]] },
      { k: "print_title", label: "Title to print" }].filter(Boolean), Object.assign({ active: 1, method: "automatic", prevent_dup: 1, width: 4, start_no: 1, restart: "yearly", series_by: "none", line_narration: 0 }, vt));
    const prev = h("p", { class: "hint" });
    const showPrev = async () => { if (!vt.id) { prev.textContent = "The first number shows after you save."; return; } const r = await api("tl.next_no", { vtype_id: vt.id, date: today() }); prev.textContent = "Next number today: " + (r.no || "(typed by hand)") + (r.buildcore ? " — BuildCore's own numbering" : ""); };
    showPrev();
    modal(isNew ? "Create voucher type" : "Alter voucher type: " + vt.name, h("div", {}, vt.statutory ? h("p", { class: "hint" }, "Statutory type (tax invoice / note): numbering is always automatic, never renumbered, and its vouchers are never deleted, only cancelled by a credit or debit note.") : null,
      h("p", { class: "hint" }, "BuildCore always keeps its own gapless number on every voucher (PV/2083-84/0001). A type with its own prefix, suffix, series or restart gets its number beside it, shown on all the Tally screens and prints."), f, prev),
    [{ label: "Accept", cls: "primary", act: async () => { await run("tl.vtype_save", Object.assign({ id: vt.id }, f.values()), "Voucher type saved"); TL.vtypes = null; if (done) done(); } },
      vt.id && !vt.system ? { label: "Delete", cls: "warn", act: async () => { await run("tl.vtype_delete", { id: vt.id }, "Deleted"); TL.vtypes = null; if (done) done(); } } : null,
      vt.id ? { label: "Edit Log", keep: true, act: () => { editLogModal("voucher_type", vt.id); return false; } } : null]);
  }

  /* ───────────────────────────── Edit Log ───────────────────────────── */
  const fmtVal = (v) => (v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
  async function editLogModal(entity, id) {
    const d = await api("tl.editlog", { entity, entity_id: id });
    const body = h("div", {});
    if (!d.versions.length) { body.append(h("p", {}, "No versions recorded yet. Changes are recorded while Tally-style accounting and the Edit Log feature are on.")); modal("Edit Log", body, [], { narrow: true }); return; }
    const v1 = h("select", {}, d.versions.map((v) => h("option", { value: v.version }, "Version " + v.version)));
    const v2 = h("select", {}, d.versions.map((v) => h("option", { value: v.version }, "Version " + v.version)));
    v2.value = d.versions[d.versions.length - 1].version;
    v1.value = Math.max(1, Number(v2.value) - 1);
    const out = h("div", {});
    const cmp = async () => {
      const r = await run("tl.compare", { entity, entity_id: id, v1: v1.value, v2: v2.value });
      out.innerHTML = "";
      out.append(r.changes.length ? table([{ k: "field", label: "Field" }, { label: "Version " + r.v1, v: (x) => fmtVal(x.old) }, { label: "Version " + r.v2, v: (x) => fmtVal(x.new) }], r.changes, { search: false, export: false }) : h("p", {}, "No difference."));
    };
    body.append(table([{ k: "version", label: "Version" }, { k: "activity", label: "Activity" }, { k: "user", label: "User" }, { k: "ts", label: "Date / time" }, { k: "reason", label: "Reason" }], d.versions, { search: false, export: false }));
    body.append(h("div", { class: "bar" }, h("b", {}, "Compare "), v1, h("span", {}, " with "), v2, h("button", { class: "btn small", onclick: cmp }, "Compare")), out);
    modal("Edit Log (Alt+Q)", body, []);
    if (d.versions.length > 1) cmp();
  }
  async function editLogPage(root, params) {
    root.append(pageHead("Edit Log", "Every voucher and master created, altered, cancelled or deleted, by whom and when. Click a line to see its versions and compare two of them."));
    const f = filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" },
      { k: "entity", label: "What", type: "select", options: ["voucher", "ledger", "party", "group", "voucher_type", "item", "project", "boq_item", "machine", "company_settings"].map((x) => [x, x.replace(/_/g, " ")]) },
      { k: "activity", label: "Activity", type: "select", options: ["created", "altered", "posted", "cancelled", "deleted"].map((x) => [x, x]) }],
    { from: params.from || monthAgo(), to: params.to || today(), entity: params.entity || "", activity: params.activity || "" }, (v) => { location.hash = "#/tl/editlog?" + new URLSearchParams(v).toString(); });
    root.append(f);
    const rows = await api("tl.editlog_company", { from: params.from || monthAgo(), to: params.to || today(), entity: params.entity, activity: params.activity });
    root.append(table([{ k: "ts", label: "Date / time" }, { k: "entity", label: "What" }, { k: "label", label: "Record" }, { k: "version", label: "Version" }, { k: "activity", label: "Activity" }, { k: "user", label: "User" }, { k: "reason", label: "Reason" }],
      rows, { name: "tl_editlog", onRow: (r) => editLogModal(r.entity, r.entity_id) }));
  }

  /* ───────────────────────────── reports ───────────────────────────── */
  function rowKeys(e) {
    const rows = [...e.currentTarget.querySelectorAll("tr[tabindex]")].filter((r) => r.offsetParent !== null);
    const i = rows.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); (rows[i + 1] || rows[0]).focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (rows[i - 1] || rows[rows.length - 1]).focus(); }
    else if (e.key === "Enter" && i >= 0) { e.preventDefault(); rows[i].click(); }
  }
  function openLedgerRow(r, from, to) {
    const q = new URLSearchParams({ from: from || "", to: to || "" });
    if (r.party_id) { q.set("party", r.party_id); location.hash = "#/acc/party?" + q; }
    else { q.set("account", r.account_id); location.hash = "#/acc/ledger?" + q; }
  }
  function periodBar(params, base, extra) {
    const fs = [{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "project_id", label: "Cost centre (project)", type: "select", options: (S.L.projects || []).map((p) => [p.id, p.code + " · " + p.name]) }].concat(extra || []);
    return filterBar(fs, params, (v) => { location.hash = "#/" + base + "?" + new URLSearchParams(Object.assign({}, params, v)).toString(); });
  }
  const fyFrom = () => (TL.meta && TL.meta.fy_start) || fyStart();

  async function tbPage(root, params) {
    await meta();
    params = Object.assign({ from: fyStart(), to: today(), detail: "1" }, params);
    root.append(pageHead("Trial Balance", "In Tally groups. Enter or click a group to open it; a ledger opens its vouchers. Esc goes back.",
      h("button", { class: "btn", title: "Alt+F1 / Alt+F5", onclick: () => { params.detail = params.detail === "1" ? "0" : "1"; location.hash = "#/tl/tb?" + new URLSearchParams(params); } }, params.detail === "1" ? "Condensed (Alt+F5)" : "Detailed (Alt+F1)"),
      h("a", { class: "btn", href: "#/acc/tb" }, "BuildCore trial balance")));
    root.append(periodBar(params, "tl/tb"));
    const d = await api("tl.tb", { from: params.from, to: params.to, project_id: params.project_id || null, parties: params.parties !== "0" });
    if (d.unconfirmed) root.append(h("p", { class: "hint" }, d.unconfirmed + " ledgers sit under a proposed group. ", h("a", { href: "#/tl/map" }, "Confirm the mapping")));
    const tb = h("tbody");
    const open = new Set(JSON.parse(LSg("bco_tl_tbopen", "[]")));
    const draw = () => {
      tb.innerHTML = "";
      const add = (g, depth) => {
        const isOpen = params.detail === "1" || open.has(g.id);
        tb.append(h("tr", { class: "g click", tabindex: 0, onclick: () => { if (params.detail === "1") return; open.has(g.id) ? open.delete(g.id) : open.add(g.id); LSs("bco_tl_tbopen", JSON.stringify([...open])); draw(); } },
          h("td", { style: "padding-left:" + (6 + depth * 16) + "px" }, (params.detail === "1" ? "" : (isOpen ? "▾ " : "▸ ")) + g.name), h("td", { class: "num" }, DC(g.opening)), h("td", { class: "num" }, M(g.debit)), h("td", { class: "num" }, M(g.credit)), h("td", { class: "num" }, DC(g.closing))));
        if (!isOpen) return;
        g.groups.forEach((x) => add(x, depth + 1));
        g.ledgers.forEach((l) => tb.append(h("tr", { class: "l click", tabindex: 0, onclick: () => openLedgerRow(l, params.from, params.to) },
          h("td", { style: "padding-left:" + (22 + depth * 16) + "px" }, l.name + (l.under_account ? "" : "")), h("td", { class: "num" }, DC(l.opening)), h("td", { class: "num" }, M(l.debit)), h("td", { class: "num" }, M(l.credit)), h("td", { class: "num" }, DC(l.closing)))));
      };
      d.groups.forEach((g) => add(g, 0));
      tb.append(h("tr", { class: "tot" }, h("td", {}, "Grand Total"), h("td", { class: "num" }, DC(d.totals.opening)), h("td", { class: "num" }, M(d.totals.debit)), h("td", { class: "num" }, M(d.totals.credit)), h("td", { class: "num" }, M(d.closing_dr) + " Dr / " + M(d.closing_cr) + " Cr")));
    };
    draw();
    root.append(h("div", { class: "tlrep" }, h("div", { class: "tablewrap" }, h("table", { onkeydown: rowKeys }, h("thead", {}, h("tr", {}, h("th", {}, "Particulars"), h("th", { class: "num" }, "Opening"), h("th", { class: "num" }, "Debit"), h("th", { class: "num" }, "Credit"), h("th", { class: "num" }, "Closing balance"))), tb))));
    if (Math.abs(d.difference) > 0.01) root.append(h("p", { class: "red" }, "Difference " + M(d.difference) + ": opening balances do not agree."));
    setTimeout(() => { const f = root.querySelector("tr[tabindex]"); if (f) f.focus(); }, 30);
  }

  function hzSide(title, items, params, extraRows) {
    const box = h("div", {}, h("h4", {}, title));
    items.forEach((it) => {
      const sub = h("div", { hidden: true });
      const fill = (g, depth) => {
        (g.groups || []).forEach((x) => { if (Math.abs(x.closing) > 0.004 || Math.abs(x.debit - x.credit) > 0.004) { sub.append(h("div", { class: "r sub", style: "padding-left:" + (16 + depth * 14) + "px" }, h("span", {}, x.name), h("span", {}, M(Math.abs(x.closing))))); fill(x, depth + 1); } });
        (g.ledgers || []).forEach((l) => sub.append(h("div", { class: "r sub", style: "padding-left:" + (16 + depth * 14) + "px", onclick: () => openLedgerRow(l, params.from, params.to) }, h("span", {}, l.name), h("span", {}, DC(it.pl ? l.debit - l.credit : l.closing)))));
      };
      if (it.group) fill(it.group, 0);
      box.append(h("div", { class: "r", tabindex: 0, onclick: () => { sub.hidden = !sub.hidden; } }, h("span", {}, it.name), h("span", {}, M(it.amount))), sub);
    });
    (extraRows || []).forEach((r) => box.append(h("div", { class: "r" + (r.big ? " big" : "") }, h("span", {}, r.name), h("span", {}, M(r.amount)))));
    return box;
  }

  async function plPage(root, params) {
    await meta();
    params = Object.assign({ from: fyStart(), to: today() }, params);
    root.append(pageHead("Profit & Loss A/c", "Trading part (gross profit) then indirect items (net profit). Click a group to open it.", h("a", { class: "btn", href: "#/acc/pl" }, "BuildCore P&L")));
    root.append(periodBar(params, "tl/pl"));
    const d = await api("tl.pl", { from: params.from, to: params.to, project_id: params.project_id || null });
    const gp = d.gross_profit;
    const trDr = d.trading_dr.map((x) => Object.assign({ pl: true }, x)), trCr = d.trading_cr.map((x) => Object.assign({ pl: true }, x));
    const totT = Math.max(trDr.reduce((a, x) => a + x.amount, 0) + Math.max(gp, 0), trCr.reduce((a, x) => a + x.amount, 0) + Math.max(-gp, 0));
    root.append(h("div", { class: "tlhz" },
      hzSide("Particulars (Dr)", trDr, params, [gp >= 0 ? { name: "Gross Profit c/o", amount: gp } : null, { name: "", amount: totT, big: true }].filter(Boolean)),
      hzSide("Particulars (Cr)", trCr, params, [gp < 0 ? { name: "Gross Loss c/o", amount: -gp } : null, { name: "", amount: totT, big: true }].filter(Boolean))));
    const np = d.net_profit;
    const inDr = d.indirect_dr.map((x) => Object.assign({ pl: true }, x)), inCr = d.indirect_cr.map((x) => Object.assign({ pl: true }, x));
    const l = (gp < 0 ? -gp : 0) + inDr.reduce((a, x) => a + x.amount, 0), r = (gp >= 0 ? gp : 0) + inCr.reduce((a, x) => a + x.amount, 0);
    const tot = Math.max(l + Math.max(np, 0), r + Math.max(-np, 0));
    root.append(h("div", { class: "tlhz", style: "margin-top:-1px" },
      hzSide("", inDr, params, [gp < 0 ? { name: "Gross Loss b/f", amount: -gp } : null, np >= 0 ? { name: "Net Profit", amount: np, big: false } : null, { name: "Total", amount: tot, big: true }].filter(Boolean)),
      hzSide("", inCr, params, [gp >= 0 ? { name: "Gross Profit b/f", amount: gp } : null, np < 0 ? { name: "Net Loss", amount: -np } : null, { name: "Total", amount: tot, big: true }].filter(Boolean))));
    root.append(h("p", { class: "tlnote" }, d.note));
  }

  async function bsPage(root, params) {
    await meta();
    params = Object.assign({ to: today() }, params);
    root.append(pageHead("Balance Sheet", "As at " + params.to + (bsOf(params.to) ? " (" + bsOf(params.to) + ")" : "") + ". Click a group to open it; a ledger opens its vouchers.", h("a", { class: "btn", href: "#/acc/bs" }, "BuildCore balance sheet")));
    root.append(filterBar([{ k: "to", label: "As at", type: "date" }], params, (v) => { location.hash = "#/tl/bs?" + new URLSearchParams(v); }));
    const d = await api("tl.bs", { as_of: params.to });
    const pl = d.liabilities.find((x) => x.name === "Profit & Loss A/c");
    const L = d.liabilities.filter((x) => x !== pl);
    const box = hzSide("Liabilities", L, { from: "", to: params.to }, [{ name: "Profit & Loss A/c", amount: pl.amount }]);
    box.append(h("div", { class: "r sub" }, h("span", {}, "Opening balance"), h("span", {}, M(pl.opening))), h("div", { class: "r sub" }, h("span", {}, "Current period"), h("span", {}, M(pl.current))));
    box.append(h("div", { class: "r big" }, h("span", {}, "Total"), h("span", {}, M(d.total_liabilities))));
    root.append(h("div", { class: "tlhz" }, box, hzSide("Assets", d.assets, { from: "", to: params.to }, [{ name: "Total", amount: d.total_assets, big: true }])));
    if (d.difference_note) root.append(h("p", { class: "red" }, d.difference_note));
    root.append(h("p", { class: "tlnote" }, "Tally layout: Duties & Taxes is shown net under Current Liabilities (VAT input reduces it). BuildCore's own balance sheet keeps VAT input under assets; both balance."));
  }

  async function daybookPage(root, params) {
    await meta();
    params = Object.assign({ from: today(), to: today() }, params);
    root.append(pageHead("Day Book", "All vouchers of the period, with their voucher type. Enter or click to open. " + (can("accounts", "edit") && TL.meta.on ? "Alt+I inserts a voucher on this date." : "")));
    const d = await api("tl.daybook", { from: params.from, to: params.to, vtype: params.vtype || null, show_altered: params.altered === "1" ? 1 : 0 });
    root.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "vtype", label: "Voucher type", type: "select", options: d.types.map((t) => [t, t]) },
      { k: "altered", label: "Altered versions", type: "select", options: [["1", "Show"]] }], params, (v) => { location.hash = "#/tl/daybook?" + new URLSearchParams(v); }));
    root.append(table([{ k: "date", label: "Date" }, { label: "Particulars", v: (r) => r.particulars + (r.narration ? " — " + r.narration : "") }, { k: "voucher_type", label: "Vch Type" },
      { label: "Vch No.", v: (r) => r.shown_no || r.no || "(pending)" }, { k: "debit", label: "Debit amount", fmt: "money" }, { k: "credit", label: "Credit amount", fmt: "money" },
      { label: "", v: (r) => [r.state, r.altered ? "altered " + r.altered + "×" : ""].filter(Boolean).join(" · ") }], d.rows,
    { name: "tl_daybook", onRow: (r) => openExisting(r), totals: ["debit", "credit"], empty: "No vouchers in this period." }));
  }
  function openExisting(v) {
    if (v.source === "manual" || v.source === "payment") { location.hash = "#/tl/ve?id=" + v.id; return; }
    if (typeof voucherView === "function") voucherView(v.id); else openRecord("voucher", v.id);
  }

  /* ───────────────────────────── voucher entry ───────────────────────────── */
  const BASES = { contra: "Contra", payment: "Payment", receipt: "Receipt", journal: "Journal" };
  async function openVoucher(base, extra) {
    const m = await meta();
    if (!m.on) { toast("Tally-style accounting is off: turn it on in Gateway › Features (F11).", "err"); nav("acc/gw"); return; }
    const q = new URLSearchParams(Object.assign({ t: base }, extra || {}));
    location.hash = "#/tl/ve?" + q.toString();
  }

  function ledgerPicker(inp, getList, onPick, o) {
    o = o || {};
    let panel = null, items = [], on = 0;
    const close = () => { if (panel) { panel.remove(); panel = null; } };
    const draw = () => {
      if (!panel) return;
      panel.innerHTML = "";
      if (o.create) panel.append(h("div", { class: "cr" + (on === -1 ? " on" : ""), onmousedown: (e) => { e.preventDefault(); close(); o.create(); } }, h("span", {}, "+ Create ledger"), h("i", {}, "Alt+C")));
      items.forEach((x, i) => panel.append(h("div", { class: (i === on ? "on" : "") + (x.blocked ? " off" : ""), title: x.blocked || "", onmousedown: (e) => { e.preventDefault(); if (x.blocked) { toast(x.name + ": " + x.blocked, "err"); return; } pick(x); } },
        h("span", {}, x.name + (x.alias ? " (" + x.alias + ")" : "")), h("i", {}, (x.group || "") + (cfg("show_balance") !== "0" ? " · " + (DC(x.balance) || "0.00") : "")))));
      const sel = panel.querySelector("div.on");
      if (sel) sel.scrollIntoView({ block: "nearest" });
    };
    const filter = () => {
      const t = inp.value.trim().toLowerCase();
      const L = getList();
      const starts = [], has = [];
      L.forEach((x) => { const s = (x.name + " " + (x.alias || "") + " " + (x.code || "")).toLowerCase(); if (!t || s.startsWith(t) || (x.alias || "").toLowerCase().startsWith(t)) starts.push(x); else if (s.includes(t)) has.push(x); });
      items = starts.concat(has).slice(0, 80);
      on = items.findIndex((x) => !x.blocked);
      draw();
    };
    const open = () => {
      if (inp.readOnly) return;
      if (!panel) { panel = h("div", { class: "tlpick" }); document.body.append(panel); }
      const r = inp.getBoundingClientRect();
      panel.style.left = Math.min(window.innerWidth - 380, r.left + window.scrollX) + "px";
      panel.style.top = (r.bottom + window.scrollY + 2) + "px";
      filter();
    };
    const pick = (x) => { inp.value = x.name; inp._key = x.key; close(); onPick(x); };
    inp.addEventListener("focus", open);
    inp.addEventListener("input", () => { inp._key = null; open(); });
    inp.addEventListener("blur", () => setTimeout(close, 120));
    inp.addEventListener("keydown", (e) => {
      if (!panel) return;
      if (e.key === "ArrowDown") { e.preventDefault(); on = Math.min(items.length - 1, on + 1); draw(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); on = Math.max(o.create ? -1 : 0, on - 1); draw(); }
      else if (e.key === "Enter" || e.key === "Tab") {
        if (on === -1 && o.create) { e.preventDefault(); e.stopPropagation(); close(); o.create(); return; }
        const x = items[on];
        if (x && inp.value.trim()) { e.preventDefault(); e.stopPropagation(); pick(x); }
        else if (!inp.value.trim()) { close(); }
      } else if (e.key === "Escape") { close(); }
    }, true);
    return { close, open };
  }

  async function vePage(root, params) {
    const m = await meta(true);
    const [types, L] = await Promise.all([vtypes(true), ledgers(true)]);
    const byKey = {};
    L.forEach((x) => { byKey[x.key] = x; });
    const tdsLedger = L.find((x) => x.role === "tds_payable");
    const pickType = (t) => types.find((x) => String(x.id) === String(t)) || types.find((x) => x.base === t && !x.parent_id) || types.find((x) => x.name === "Payment");
    let ex = null;
    if (params.id) {
      ex = await api("tl.get", { id: params.id });
    }
    if (!m.on && !ex) { root.append(pageHead("Voucher entry"), offPanel(m)); return; }
    const st = { vt: pickType(ex ? (ex.vtype_id || ex.type) : params.t || "payment"), date: params.date || LSg("bco_tl_date", today()), project_id: "", ref_no: "", narration: "", lines: [], account: null, dirty: false };
    if (st.date < "2000") st.date = today();
    const baseOf = (vt) => { let x = vt; while (x && x.parent_id) x = types.find((y) => y.id === x.parent_id); return x ? x.base : "journal"; };
    const modeFor = (vt) => (ex && ex.mode) || cfg("mode_" + baseOf(vt)) || vt.default_mode || (baseOf(vt) === "journal" ? "double" : "single");
    st.mode = modeFor(st.vt);
    const readOnly = ex && (ex.lock || ex.source !== "manual" || ex.status !== "posted");
    const editing = ex && !readOnly;
    if (ex) {
      st.date = ex.date; st.project_id = ex.project_id || ""; st.ref_no = ex.ref_no || ""; st.narration = ex.narration || "";
      st.mode = "double";
      const bills = ex.bills || [];
      st.lines = ex.lines.map((l) => {
        const key = l.party_id && byKey["p:" + l.party_id] && byKey["p:" + l.party_id].account_id === l.account_id ? "p:" + l.party_id : "a:" + l.account_id;
        const amt = l.debit || l.credit;
        const myBills = bills.filter((b) => b.party_id && b.party_id === l.party_id && Math.abs(Math.abs(b.amount) - amt) < 0.005 && b.ref_type !== "onaccount").map((b) => ({ ref_type: b.ref_type, name: b.bill_name, amount: Math.abs(b.amount), invoice_id: b.invoice_id, due_date: b.due_date }));
        return { side: l.debit ? "dr" : "cr", key, amount: amt, narration: l.narration || "", bills: myBills, cc: [{ project_id: l.project_id || "", boq_item_id: l.boq_item_id || "", equipment_id: l.equipment_id || "", amount: amt }] };
      });
    }
    const base = () => baseOf(st.vt);
    const single = () => st.mode === "single" && ["payment", "receipt", "contra"].includes(base());
    const partSide = () => (base() === "receipt" ? "cr" : "dr");
    const isMoney = (k) => byKey[k] && byKey[k].money;
    if (!ex && single() && !st.account) { const c0 = L.find((x) => x.money && x.role === (base() === "contra" ? "bank" : "bank")) || L.find((x) => x.money); st.account = c0 ? c0.key : null; }

    root.innerHTML = "";
    const sheet = h("div", { class: "sheet" });
    const keys = keyBar([["F2", "Date", () => dateI.focus()], ["F4", "Contra", () => switchType("contra")], ["F5", "Payment", () => switchType("payment")], ["F6", "Receipt", () => switchType("receipt")], ["F7", "Journal", () => switchType("journal")],
      ["Ctrl+H", "Change mode", () => toggleMode()], ["Alt+C", "Create ledger", () => newLedger(async () => { TL.ledgers = null; })], ["Alt+R", "Previous narration", () => retrieve()], ["Alt+2", "Duplicate", () => duplicate()],
      ["PgUp", "Previous voucher", () => step("prev")], ["PgDn", "Next voucher", () => step("next")], ex ? ["Alt+X", "Cancel voucher", () => cancelV()] : null, ex ? ["Alt+Q", "Edit Log", () => editLogModal("voucher", ex.id)] : null,
      ex ? ["Alt+P", "Print", () => printV()] : null, ["F12", "Configure", () => configure()], ["Ctrl+A", "Accept", () => accept()], ["Esc", "Quit", () => quit()]]);
    root.append(h("div", { class: "tlv" }, sheet, keys));

    const typeSel = h("select", { onchange: () => { st.vt = types.find((x) => String(x.id) === typeSel.value); st.mode = modeFor(st.vt); draw(); } },
      types.filter((x) => ["contra", "payment", "receipt", "journal"].includes(baseOf(x)) && x.active && (!x.note || !ex || true)).filter((x) => !x.note).map((x) => h("option", { value: x.id }, x.name)));
    const dateI = h("input", { type: "date", value: st.date, onchange: () => { st.date = dateI.value; LSs("bco_tl_date", st.date); bsT.textContent = bsOf(st.date); numPrev(); } });
    const bsT = h("span", { class: "bal" }, bsOf(st.date));
    const noT = h("b", {}, "");
    const projSel = h("select", { onchange: () => { st.project_id = projSel.value; numPrev(); } }, h("option", { value: "" }, "— company —"), (S.L.projects || []).map((p) => h("option", { value: p.id }, p.code + " · " + p.name)));
    const refI = h("input", { placeholder: "Ref / cheque no.", value: st.ref_no, style: "width:150px", oninput: () => { st.ref_no = refI.value; st.dirty = true; } });
    const grid = h("tbody");
    const accBox = h("div", {});
    const narr = h("textarea", { rows: 2, placeholder: "Narration (Enter accepts the voucher, Shift+Enter for a new line, Alt+R previous narration)", style: "width:100%;margin-top:8px", oninput: () => { st.narration = narr.value; st.dirty = true; } });
    narr.value = st.narration;
    const totE = h("div", { class: "tot" });
    const words = h("div", { class: "words" });
    const banner = h("div", {});
    const typeT = h("span", { class: "ty" });

    async function numPrev() {
      if (ex) { noT.textContent = "No. " + (ex.shown_no || ex.no || ""); return; }
      try { const r = await api("tl.next_no", { vtype_id: st.vt.id, date: st.date, project_id: st.project_id || null }); noT.textContent = "No. " + (r.no || "(type it)"); } catch (e) { noT.textContent = ""; }
    }
    const listFor = (k) => (k === "account" ? L.filter((x) => x.money) : base() === "contra" ? L.filter((x) => x.money) : L);
    function lineRow(ln, i) {
      const tr = h("tr");
      const sideI = h("input", { value: sideLabel(ln.side), readOnly: readOnly, title: "D / C (or B / T)", onkeydown: (e) => {
        const k = e.key.toLowerCase();
        if (["d", "b"].includes(k)) { e.preventDefault(); ln.side = "dr"; sideI.value = sideLabel("dr"); }
        else if (["c", "t"].includes(k)) { e.preventDefault(); ln.side = "cr"; sideI.value = sideLabel("cr"); }
        else if (k === "enter") { e.preventDefault(); ledI.focus(); }
      } });
      const ledI = h("input", { value: ln.key && byKey[ln.key] ? byKey[ln.key].name : "", readOnly: readOnly, placeholder: i === 0 ? "Ledger (type to search)" : "" });
      ledI._key = ln.key;
      const bal = h("div", { class: "bal" }, ln.key && byKey[ln.key] && cfg("show_balance") !== "0" ? "Cur bal: " + (DC(byKey[ln.key].balance) || "0.00") : "");
      const amtI = h("input", { value: ln.amount ? fmtMoney(ln.amount) : "", readOnly: readOnly, inputmode: "decimal", onfocus: () => {
        if (!amtI.value && !single()) { const diff = balanceDiff(i); if (diff) { amtI.value = fmtMoney(Math.abs(diff)); } } amtI.select();
      }, oninput: () => { ln.amount = N(amtI.value); st.dirty = true; totals(); },
      onchange: () => { if ((ln.cc || []).length === 1 || (ln.bills || []).length === 1) { if ((ln.cc || []).length === 1) ln.cc[0].amount = ln.amount; if ((ln.bills || []).length === 1) ln.bills[0].amount = ln.amount; draw(true); } } });
      const nI = h("input", { value: ln.narration || "", readOnly: readOnly, placeholder: "line narration", oninput: () => { ln.narration = nI.value; } });
      const subs = h("div", {});
      const showSubs = () => {
        subs.innerHTML = "";
        (ln.bills || []).forEach((b) => subs.append(h("div", { class: "sub" }, ({ new: "New Ref", agst: "Agst Ref", advance: "Advance", onaccount: "On Account" })[b.ref_type] + (b.name ? " " + b.name : "") + " · " + fmtMoney(b.amount) + (b.due_date ? " · due " + b.due_date : ""))));
        if (ln.tds && ln.tds.amount) subs.append(h("div", { class: "sub" }, "TDS deducted " + fmtMoney(ln.tds.amount)));
        if ((ln.cc || []).length > 1 || ((ln.cc || [])[0] && ((ln.cc[0].boq_item_id || ln.cc[0].equipment_id) || (ln.cc[0].project_id && String(ln.cc[0].project_id) !== String(st.project_id))))) subs.append(h("div", { class: "sub" }, "Cost centres: " + ln.cc.map((c) => [ccName("p", c.project_id), ccName("b", c.boq_item_id), ccName("e", c.equipment_id)].filter(Boolean).join(" / ") + " " + fmtMoney(c.amount)).join("; ")));
      };
      showSubs();
      ledgerPicker(ledI, () => listFor("line").filter((x) => !(single() && x.money && base() !== "contra")), (x) => {
        ln.key = x.key; st.dirty = true; bal.textContent = cfg("show_balance") !== "0" ? "Cur bal: " + (DC(x.balance) || "0.00") : "";
        if (i === st.lines.length - 1) { st.lines.push(blank()); draw(true); focusCell(i, "amt"); return; }
        amtI.focus();
      }, { create: () => newLedger(async () => { TL.ledgers = await api("tl.ledgers", {}); L.length = 0; TL.ledgers.forEach((x) => { L.push(x); byKey[x.key] = x; }); }) });
      ledI.addEventListener("keydown", (e) => { if (e.key === "Enter" && !ledI.value.trim()) { e.preventDefault(); if (i === st.lines.length - 1) narr.focus(); else amtI.focus(); } });
      amtI.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        ln.amount = N(amtI.value); amtI.value = ln.amount ? fmtMoney(ln.amount) : "";
        totals();
        const x = byKey[ln.key];
        if (x && ln.amount) {
          if (x.party && feat("billWise")) await billwise(ln);
          else if (x.pl && feat("costCentres")) await costCentres(ln);
          showSubs(); totals();
        }
        if (cfg("line_narration") === "1" || st.vt.line_narration) { nI.focus(); return; }
        nextLine(i);
      });
      nI.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); nextLine(i); } });
      tr._amt = amtI; tr._led = ledI; tr._side = sideI;
      const cells = [];
      if (!single()) cells.push(h("td", { class: "side" }, sideI));
      cells.push(h("td", {}, ledI, bal, subs));
      if (!single()) { cells.push(h("td", { class: "n" }, ln.side === "dr" ? amtI : "")); cells.push(h("td", { class: "n" }, ln.side === "cr" ? amtI : "")); }
      else cells.push(h("td", { class: "n" }, amtI));
      if (cfg("line_narration") === "1" || st.vt.line_narration) cells.push(h("td", {}, nI));
      tr.append(...cells);
      sideI.addEventListener("change", () => draw(true));
      sideI.addEventListener("blur", () => { if ((ln.side === "dr") !== !!tr.querySelector("td:nth-child(3) input")) draw(true); });
      return tr;
    }
    const blank = () => ({ side: single() ? partSide() : (st.lines.length ? (balanceDiff(st.lines.length) > 0 ? "cr" : "dr") : (base() === "receipt" ? "cr" : "dr")), key: null, amount: 0, narration: "", bills: [], cc: [] });
    const ccName = (k, id) => { if (!id) return ""; const L0 = k === "p" ? S.L.projects : k === "b" ? S.L.boq : S.L.equipment; const r = (L0 || []).find((x) => String(x.id) === String(id)); return r ? (r.code || "") + (k === "b" ? "" : "") : "#" + id; };
    function balanceDiff(upto) {
      let d = 0;
      st.lines.forEach((l, j) => { if (j !== upto && l.key) d += (l.side === "dr" ? 1 : -1) * (l.amount || 0); });
      return Math.round(d * 100) / 100;
    }
    function nextLine(i) {
      if (i < st.lines.length - 1) { focusCell(i + 1, single() ? "led" : "side"); return; }
      if (!single() && Math.abs(balanceDiff(-1)) < 0.005 && st.lines.filter((l) => l.key).length >= 2) { narr.focus(); return; }
      st.lines.push(blank()); draw(true); focusCell(st.lines.length - 1, single() ? "led" : "side");
    }
    function focusCell(i, which) { setTimeout(() => { const tr = grid.children[i]; if (!tr) return; const el = which === "amt" ? tr._amt : which === "side" ? tr._side : tr._led; if (el) el.focus(); }, 20); }

    function totals() {
      const parts = st.lines.filter((l) => l.key && l.amount);
      let dr = 0, cr = 0;
      parts.forEach((l) => { if (single()) { if (partSide() === "dr") dr += l.amount; else cr += l.amount; } else if (l.side === "dr") dr += l.amount; else cr += l.amount; });
      const tds = st.lines.reduce((a, l) => a + ((l.tds && l.tds.amount) || 0), 0);
      totE.innerHTML = "";
      if (single()) {
        const net = (partSide() === "dr" ? dr : cr) - tds;
        totE.append(...[h("span", {}, "Total " + fmtMoney(partSide() === "dr" ? dr : cr)), tds ? h("span", {}, "TDS " + fmtMoney(tds)) : null].filter(Boolean), h("span", {}, (partSide() === "dr" ? "Paid from " : "Received in ") + (byKey[st.account] ? byKey[st.account].name : "?") + ": " + fmtMoney(net)));
        words.textContent = net ? wordsOf(net) : "";
      } else {
        totE.append(...[h("span", {}, "Dr " + fmtMoney(dr)), h("span", {}, "Cr " + fmtMoney(cr + tds)), Math.abs(dr - cr - tds) > 0.004 ? h("span", { class: "red" }, "Difference " + fmtMoney(Math.abs(dr - cr - tds))) : null].filter(Boolean));
        words.textContent = dr ? wordsOf(dr) : "";
      }
    }
    let wcache = {};
    function wordsOf(n) {
      const k = n.toFixed(2);
      if (wcache[k]) return wcache[k];
      api("tl.words", { amount: n }).then((r) => { wcache[k] = r.en + "  ·  " + r.ne; totals(); }).catch(() => {});
      return "";
    }

    function draw(keep) {
      typeSel.value = st.vt.id;
      typeT.textContent = st.vt.name + (single() ? " (single entry)" : "");
      projSel.value = st.project_id || "";
      dateI.value = st.date; bsT.textContent = bsOf(st.date);
      if (!st.lines.length) st.lines.push(blank());
      grid.innerHTML = "";
      accBox.innerHTML = "";
      if (single()) {
        const accI = h("input", { value: st.account && byKey[st.account] ? byKey[st.account].name : "", readOnly: readOnly, style: "max-width:360px" });
        const bal = h("span", { class: "bal" }, st.account && byKey[st.account] && cfg("show_balance") !== "0" ? " Cur bal: " + (DC(byKey[st.account].balance) || "0.00") : "");
        ledgerPicker(accI, () => listFor("account"), (x) => { st.account = x.key; bal.textContent = " Cur bal: " + (DC(x.balance) || "0.00"); focusCell(0, "led"); totals(); });
        accBox.append(h("label", { style: "display:flex;gap:8px;align-items:center;margin:0 0 6px" }, h("b", {}, "Account:"), accI, bal));
      }
      const head = single() ? [h("th", {}, "Particulars"), h("th", { class: "num" }, "Amount")] : [h("th", {}, cfg("drcr") === "1" ? "Dr/Cr" : "By/To"), h("th", {}, "Particulars"), h("th", { class: "num" }, "Debit"), h("th", { class: "num" }, "Credit")];
      if (cfg("line_narration") === "1" || st.vt.line_narration) head.push(h("th", {}, "Narration"));
      thead.innerHTML = ""; thead.append(h("tr", {}, head));
      st.lines.forEach((ln, i) => grid.append(lineRow(ln, i)));
      totals();
      numPrev();
      if (!keep) setTimeout(() => { (single() && !st.account ? accBox.querySelector("input") : grid.children[0] && (single() ? grid.children[0]._led : grid.children[0]._side) || dateI).focus(); }, 30);
    }
    const thead = h("thead");
    sheet.append(banner,
      h("div", { class: "hd" }, typeT, ex ? null : typeSel, noT, h("label", {}, "Date ", dateI, bsT), h("label", {}, "Cost centre ", projSel), refI),
      accBox, h("table", { class: "g" }, thead, grid), totE, words, narr,
      h("div", { class: "actions" }, readOnly ? null : h("button", { class: "btn primary", onclick: () => accept() }, editing ? "Accept alteration (Ctrl+A)" : "Accept (Ctrl+A)"), h("button", { class: "btn", onclick: () => quit() }, "Quit (Esc)")));
    if (ex) {
      if (readOnly) banner.append(h("div", { class: "lock" }, h("b", {}, ex.status === "reversed" ? "Cancelled / altered. " : "Display only. "), ex.lock || "", ex.source !== "manual" && ex.source !== "payment" ? "" : ""));
      else banner.append(h("div", { class: "pend" }, "Altering voucher " + (ex.shown_no || ex.no) + ". The old version is kept in the Edit Log (Alt+Q)."));
      if (ex.status === "draft") banner.append(h("div", { class: "pend" }, "Pending approval: someone with Accounts approve rights posts it (Accounts › Vouchers)."));
    }
    narr.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); accept(); } });
    draw();

    /* sub-screens */
    async function billwise(ln) {
      const x = byKey[ln.key];
      const d = await api("tl.pending_bills", { party_id: x.party_id, skip_voucher: ex ? ex.id : null });
      const sideDr = single() ? partSide() === "dr" : ln.side === "dr";
      const pend = d.bills.filter((b) => (sideDr ? b.balance < 0 : b.balance > 0));
      let rows = (ln.bills && ln.bills.length) ? ln.bills.map((b) => Object.assign({}, b)) : [];
      const credit = x.credit_days ? Number(x.credit_days) : 0;
      const due0 = () => { if (!credit) return ""; const dt = new Date(st.date); dt.setDate(dt.getDate() + credit); return dt.toISOString().slice(0, 10); };
      if (!rows.length) {
        if (pend.length && (base() === "payment" || base() === "receipt")) {
          let left = ln.amount;
          pend.forEach((b) => { if (left <= 0.004) return; const a = Math.min(left, Math.abs(b.balance)); rows.push({ ref_type: "agst", name: b.name, invoice_id: b.invoice_id || null, amount: Math.round(a * 100) / 100 }); left -= a; });
          if (left > 0.004) rows.push({ ref_type: base() === "payment" || base() === "receipt" ? "advance" : "new", name: "", amount: Math.round(left * 100) / 100 });
        } else rows.push({ ref_type: base() === "payment" || base() === "receipt" ? "advance" : "new", name: st.ref_no || "", amount: ln.amount, due_date: due0() });
      }
      const tdsSel = h("select", {}, h("option", { value: "" }, "— no TDS —"), (S.L.tds || []).map((t) => h("option", { value: t.id }, t.section + " · " + t.description + " · " + t.rate + "%" + (t.threshold ? " (from " + fmtMoney(t.threshold) + ")" : ""))));
      if (ln.tds && ln.tds.rate_id) tdsSel.value = ln.tds.rate_id;
      return new Promise((resolve) => {
        const body = h("div", {});
        const tb = h("tbody");
        const sum = h("p", { class: "hint" });
        const drawRows = () => {
          tb.innerHTML = "";
          rows.forEach((r, i) => {
            const t = h("select", { onchange: () => { r.ref_type = t.value; r.invoice_id = null; drawRows(); } }, [["new", "New Ref"], ["agst", "Agst Ref"], ["advance", "Advance"], ["onaccount", "On Account"]].map(([v, l]) => h("option", { value: v }, l)));
            t.value = r.ref_type;
            let nm;
            if (r.ref_type === "agst") {
              nm = h("select", { onchange: () => { const b = pend[Number(nm.value)]; if (b) { r.name = b.name; r.invoice_id = b.invoice_id || null; if (!r.amount) r.amount = Math.abs(b.balance); drawRows(); } } }, h("option", { value: "" }, "— choose a pending bill —"),
                pend.map((b, j) => h("option", { value: j }, b.name + " · " + b.bill_date + " · " + DC(b.balance) + (b.due_date ? " · due " + b.due_date : "") + (b.source === "invoice" ? " · BuildCore bill " + b.no : ""))));
              const j = pend.findIndex((b) => b.name === r.name && (b.invoice_id || null) === (r.invoice_id || null));
              nm.value = j >= 0 ? j : "";
            } else nm = h("input", { value: r.name || "", disabled: r.ref_type === "onaccount" || r.ref_type === "advance" && false, placeholder: r.ref_type === "new" ? "Bill name / no." : r.ref_type === "advance" ? "PO / contract (optional)" : "", oninput: () => { r.name = nm.value; } });
            const due = h("input", { type: "date", value: r.due_date || "", disabled: r.ref_type !== "new", onchange: () => { r.due_date = due.value; } });
            due.classList.add("no-bs");
            const am = h("input", { value: r.amount ? fmtMoney(r.amount) : "", style: "text-align:right", oninput: () => { r.amount = N(am.value); upd(); } });
            tb.append(h("tr", {}, h("td", {}, t), h("td", {}, nm), h("td", { class: "no-bs" }, due), h("td", {}, am), h("td", {}, h("button", { class: "btn small", onclick: () => { rows.splice(i, 1); drawRows(); } }, "×"))));
          });
          upd();
        };
        const upd = () => { const s = rows.reduce((a, r) => a + (r.amount || 0), 0); sum.textContent = "Allocated " + fmtMoney(s) + " of " + fmtMoney(ln.amount) + (Math.abs(s - ln.amount) > 0.004 ? " — difference " + fmtMoney(ln.amount - s) : " ✓"); };
        drawRows();
        body.append(h("p", {}, h("b", {}, x.name), " · " + (pend.length ? pend.length + " pending bill(s)" : "no pending bills") + (d.advance ? " · advance " + fmtMoney(d.advance) : "")),
          h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Type of Ref"), h("th", {}, "Name"), h("th", {}, "Due date"), h("th", {}, "Amount"), h("th"))), tb)),
          h("button", { class: "btn small", onclick: () => { const s = rows.reduce((a, r) => a + (r.amount || 0), 0); rows.push({ ref_type: "agst", name: "", amount: Math.max(0, Math.round((ln.amount - s) * 100) / 100) }); drawRows(); } }, "+ Add a line"), sum);
        if (base() === "payment" && x.kind !== "client" && tdsLedger) body.append(h("label", { class: "f" }, h("span", {}, "TDS deducted (nature of payment)"), tdsSel));
        let done = false;
        const mm = modal("Bill-wise details for " + x.name, body, [{ label: "Accept", cls: "primary", act: () => {
          const s = rows.reduce((a, r) => a + (r.amount || 0), 0);
          if (Math.abs(s - ln.amount) > 0.004) { toast("Bill-wise details must add up to " + fmtMoney(ln.amount) + ".", "err"); throw new Error("x"); }
          for (const r of rows) if (r.ref_type === "agst" && !r.name) { toast("Choose the pending bill for each Agst Ref.", "err"); throw new Error("x"); }
          ln.bills = rows.filter((r) => r.amount > 0);
          const t = (S.L.tds || []).find((q) => String(q.id) === tdsSel.value);
          ln.tds = t ? { rate_id: t.id, amount: ln.amount >= (t.threshold || 0) ? Math.round(ln.amount * t.rate) / 100 : 0 } : null;
          done = true; resolve(true);
        } }], { onClose: () => { if (!done) resolve(false); } });
        mm.el.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); e.stopPropagation(); mm.el.querySelector("footer .btn.primary").click(); } }, true);
      });
    }
    async function costCentres(ln) {
      let rows = (ln.cc && ln.cc.length) ? ln.cc.map((c) => Object.assign({}, c)) : [{ project_id: st.project_id || "", boq_item_id: "", equipment_id: "", amount: ln.amount }];
      if (rows.length === 1) rows[0].amount = ln.amount;
      return new Promise((resolve) => {
        const tb = h("tbody");
        const sum = h("p", { class: "hint" });
        const drawRows = () => {
          tb.innerHTML = "";
          rows.forEach((r, i) => {
            const p = h("select", { onchange: () => { r.project_id = p.value; r.boq_item_id = ""; drawRows(); } }, h("option", { value: "" }, "— company —"), (S.L.projects || []).map((x) => h("option", { value: x.id }, x.code + " · " + x.name)));
            p.value = r.project_id || "";
            const b = h("select", { onchange: () => { r.boq_item_id = b.value; } }, h("option", { value: "" }, "—"), (S.L.boq || []).filter((x) => String(x.project_id) === String(r.project_id)).map((x) => h("option", { value: x.id }, x.code + " · " + (x.description || "").slice(0, 40))));
            b.value = r.boq_item_id || "";
            const e = h("select", { onchange: () => { r.equipment_id = e.value; } }, h("option", { value: "" }, "—"), (S.L.equipment || []).map((x) => h("option", { value: x.id }, x.code + " · " + x.name)));
            e.value = r.equipment_id || "";
            const am = h("input", { value: r.amount ? fmtMoney(r.amount) : "", style: "text-align:right", oninput: () => { r.amount = N(am.value); upd(); } });
            tb.append(h("tr", {}, h("td", {}, p), h("td", {}, b), h("td", {}, e), h("td", {}, am), h("td", {}, rows.length > 1 ? h("button", { class: "btn small", onclick: () => { rows.splice(i, 1); drawRows(); } }, "×") : null)));
          });
          upd();
        };
        const upd = () => { const s = rows.reduce((a, r) => a + (r.amount || 0), 0); sum.textContent = "Allocated " + fmtMoney(s) + " of " + fmtMoney(ln.amount) + (Math.abs(s - ln.amount) > 0.004 ? " — difference " + fmtMoney(ln.amount - s) : " ✓"); };
        drawRows();
        let done = false;
        const mm = modal("Cost centre allocation for " + (byKey[ln.key] || {}).name, h("div", {}, h("p", { class: "hint" }, "Project, BOQ item and machine are BuildCore's cost centres; cost analysis and the budgets read the same allocation."),
          h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Project"), h("th", {}, "BOQ item"), h("th", {}, "Machine"), h("th", {}, "Amount"), h("th"))), tb)),
          h("button", { class: "btn small", onclick: () => { const s = rows.reduce((a, r) => a + (r.amount || 0), 0); rows.push({ project_id: st.project_id || "", boq_item_id: "", equipment_id: "", amount: Math.max(0, Math.round((ln.amount - s) * 100) / 100) }); drawRows(); } }, "+ Split to another cost centre"), sum),
        [{ label: "Accept", cls: "primary", act: () => {
          const s = rows.reduce((a, r) => a + (r.amount || 0), 0);
          if (Math.abs(s - ln.amount) > 0.004) { toast("The allocation must add up to " + fmtMoney(ln.amount) + ".", "err"); throw new Error("x"); }
          ln.cc = rows.filter((r) => r.amount > 0); done = true; resolve(true);
        } }], { onClose: () => { if (!done) resolve(false); } });
        mm.el.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); e.stopPropagation(); mm.el.querySelector("footer .btn.primary").click(); } }, true);
      });
    }

    /* actions */
    function payload() {
      const out = [];
      st.lines.filter((l) => l.key && l.amount).forEach((l) => {
        const side = single() ? partSide() : l.side;
        /* one bill-wise row or one cost-centre row follows a changed line amount (as when a voucher is altered) */
        const bl = (l.bills || []).map((b) => Object.assign({}, b));
        if (bl.length === 1) bl[0].amount = l.amount;
        const cc = (l.cc || []).filter((c) => c.amount > 0 || (l.cc || []).length === 1).map((c) => Object.assign({}, c));
        if (cc.length === 1) cc[0].amount = l.amount;
        out.push({ ledger: l.key, dr: side === "dr" ? l.amount : 0, cr: side === "cr" ? l.amount : 0, narration: l.narration || null, bills: bl, cc });
        if (l.tds && l.tds.amount && tdsLedger) {
          out.push({ ledger: tdsLedger.key, dr: 0, cr: l.tds.amount, narration: "TDS" });
          if (out[out.length - 2].bills.length) out[out.length - 2].bills[0].tds_rate_id = l.tds.rate_id;
        }
      });
      if (single()) {
        if (!st.account) throw new Error("Choose the cash / bank account at the top.");
        const tot = out.reduce((a, x) => a + (partSide() === "dr" ? x.dr - x.cr : x.cr - x.dr), 0);
        out.push({ ledger: st.account, dr: partSide() === "dr" ? 0 : Math.round(tot * 100) / 100, cr: partSide() === "dr" ? Math.round(tot * 100) / 100 : 0 });
      }
      return out;
    }
    async function accept() {
      if (readOnly) return toast("This voucher cannot be changed here. " + (ex && ex.lock ? ex.lock : ""), "err");
      let lines;
      try { lines = payload(); } catch (e) { return toast(e.message, "err"); }
      if (lines.length < 2) return toast("Enter at least one ledger and amount.", "err");
      const pr = ask(editing ? "Accept the alteration?" : "Accept?", editing ? "The voucher keeps its number; the old version stays in the Edit Log. Type the reason (optional) and press Enter." : "Save this " + st.vt.name.toLowerCase() + " voucher.", editing ? { input: "Reason for the alteration (optional)", ok: "Yes (Enter)" } : { ok: "Yes (Y)" });
      const ta = document.querySelector(".overlay:last-of-type .modal textarea") || document.querySelector(".modal textarea");
      if (ta) ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const b = ta.closest(".modal").querySelector("footer .btn.primary, .btn.primary"); if (b) b.click(); } });
      const ok = await pr;
      if (ok === null || ok === false) return;
      const args = { vtype_id: st.vt.id, date: st.date, project_id: st.project_id || null, ref_no: st.ref_no || null, narration: st.narration, mode: st.mode, lines };
      if (editing) { args.id = ex.id; if (typeof ok === "string") args.reason = ok; }
      const r = await run("tl.save", args);
      if (st.narration) LSs("bco_tl_narr_" + st.vt.id, st.narration);
      LSs("bco_tl_last", base());
      toast(st.vt.name + " " + (r.no || "") + (r.status === "pending approval" ? " saved — pending approval" : r.altered ? " altered" : " saved"), "ok");
      TL.ledgers = null;
      if (editing) { location.hash = "#/tl/ve?id=" + r.id; return; }
      st.lines = []; st.narration = ""; narr.value = ""; st.ref_no = ""; refI.value = ""; st.dirty = false;
      L.length = 0; (await ledgers(true)).forEach((x) => { L.push(x); byKey[x.key] = x; });
      draw();
    }
    async function quit() {
      if (st.dirty && !readOnly) { const ok = await ask("Quit?", "The voucher is not saved.", { ok: "Yes (Y)", danger: true }); if (!ok) return; }
      if (history.length > 1) history.back(); else nav("acc/gw");
    }
    function switchType(b) {
      if (ex) { openVoucher(b); return; }
      const vt = types.find((x) => x.base === b && !x.parent_id);
      if (!vt) return;
      st.vt = vt; st.mode = modeFor(vt);
      if (single() && (!st.account || !isMoney(st.account))) { const c0 = L.find((x) => x.money); st.account = c0 ? c0.key : null; }
      st.lines.forEach((l) => { if (single()) l.side = partSide(); });
      draw();
    }
    function toggleMode() {
      if (readOnly) return;
      if (!["payment", "receipt", "contra"].includes(base())) return toast("Journal vouchers are always double entry.", "err");
      if (single()) {
        st.mode = "double";
        st.lines.forEach((l) => { l.side = partSide(); });
        if (st.account) { const tot = st.lines.reduce((a, l) => a + (l.amount || 0), 0); st.lines = st.lines.filter((l) => l.key); st.lines.push({ side: partSide() === "dr" ? "cr" : "dr", key: st.account, amount: tot, bills: [], cc: [] }); }
      } else {
        const money = st.lines.filter((l) => isMoney(l.key) && base() !== "contra");
        if (money.length > 1) return toast("More than one cash / bank line: stay in double entry.", "err");
        st.mode = "single";
        if (money.length) { st.account = money[0].key; st.lines = st.lines.filter((l) => l !== money[0]); }
        st.lines.forEach((l) => { l.side = partSide(); });
      }
      draw();
    }
    function retrieve() { const v = LSg("bco_tl_narr_" + st.vt.id, ""); if (!v) return toast("No earlier narration for " + st.vt.name + ".", "err"); narr.value = v; st.narration = v; narr.focus(); }
    function duplicate() {
      if (!ex) return toast("Open a saved voucher first (Day Book), then Alt+2 to duplicate it.", "err");
      LSs("bco_tl_dup", JSON.stringify({ t: st.vt.id, lines: st.lines.map((l) => Object.assign({}, l, { bills: [], tds: null })), narration: st.narration, project_id: st.project_id }));
      location.hash = "#/tl/ve?t=" + st.vt.id + "&dup=1";
    }
    async function step(dir) {
      const r = await api("tl.nav", { id: ex ? ex.id : null, dir, vtype_id: st.vt.id });
      if (!r.id) return toast(dir === "prev" ? "No earlier voucher of this type." : "No later voucher of this type.", "err");
      location.hash = "#/tl/ve?id=" + r.id;
    }
    async function cancelV() {
      if (!ex) return;
      if (!can("accounts", "approve")) return toast("Cancelling a voucher needs Accounts approve rights.", "err");
      const why = await ask("Cancel voucher " + (ex.shown_no || ex.no) + "?", "The voucher keeps its number and is reversed on its date. Nothing is deleted.", { input: "Reason (required)", required: true, danger: true, ok: "Cancel the voucher" });
      if (!why) return;
      await run("tl.cancel", { id: ex.id, reason: why }, "Voucher cancelled");
      location.hash = "#/tl/ve?id=" + ex.id + "&r=" + Date.now();
    }
    function printV() {
      if (!ex) return;
      const node = h("div", {}, h("p", {}, h("b", {}, (st.vt.print_title || st.vt.name) + " voucher No. " + (ex.shown_no || ex.no)), "   Date: " + ex.date + (bsOf(ex.date) ? " (" + bsOf(ex.date) + " BS)" : "")),
        h("table", { class: "lines" }, h("thead", {}, h("tr", {}, h("th", {}, "Particulars"), h("th", { class: "num" }, "Debit"), h("th", { class: "num" }, "Credit"))),
          h("tbody", {}, ex.lines.map((l) => h("tr", {}, h("td", {}, (l.party || l.account) + (l.narration ? " — " + l.narration : "")), h("td", { class: "num" }, l.debit ? fmtMoney(l.debit) : ""), h("td", { class: "num" }, l.credit ? fmtMoney(l.credit) : "")))),
          h("tfoot", {}, h("tr", {}, h("td", {}, "Total"), h("td", { class: "num" }, fmtMoney(ex.total)), h("td", { class: "num" }, fmtMoney(ex.total))))),
        h("p", {}, "Amount in words: " + ex.words), h("p", {}, ex.words_ne), h("p", {}, "Narration: " + (ex.narration || "")),
        h("p", { style: "margin-top:48px;display:flex;justify-content:space-between" }, h("span", {}, "Prepared by"), h("span", {}, "Checked by"), h("span", {}, "Approved by")));
      printFrame((st.vt.print_title || st.vt.name) + " voucher", node);
    }
    if (params.dup === "1") {
      try { const d = JSON.parse(LSg("bco_tl_dup", "null")); if (d) { st.lines = d.lines; st.narration = d.narration || ""; narr.value = st.narration; st.project_id = d.project_id || ""; draw(); } } catch (e) { /* ignore */ }
    }
    vePage.cur = { accept, quit, switchType, toggleMode, retrieve, duplicate, step, cancelV, printV, editLog: () => ex && editLogModal("voucher", ex.id), date: () => dateI.focus(), newLedger: () => newLedger(async () => { L.length = 0; (await ledgers(true)).forEach((x) => { L.push(x); byKey[x.key] = x; }); }) };
  }

  /* ───────────────────────────── keys ───────────────────────────── */
  const FK = { F4: "contra", F5: "payment", F6: "receipt", F7: "journal" };
  function tlKey(e, k, typing) {
    if (!S || !S.user) return false;
    const path = pathNow();
    const ovs = document.querySelectorAll(".overlay");
    const top = ovs.length ? ovs[ovs.length - 1] : null;
    if (top && path !== "tl/ve") return false;
    const onVe = path === "tl/ve" && vePage.cur;
    const tlOn = TL.meta && TL.meta.on;
    if (FK[k] && tlOn && cfg("keys") !== "0" && can("accounts", "edit")) {
      if (top) return false;
      if (onVe) vePage.cur.switchType(FK[k]); else openVoucher(FK[k]);
      return true;
    }
    if ((path.startsWith("tl/") || path === "acc/gw") && !top) {
      if (k === "F11") { nav("tl/features"); return true; }
      if (k === "F12") { configure(); return true; }
    }
    if (onVe && !top) {
      const map = { "Ctrl+A": "accept", "Ctrl+H": "toggleMode", "Alt+R": "retrieve", "Alt+2": "duplicate", "Alt+X": "cancelV", "Alt+Q": "editLog", "Alt+P": "printV", F2: "date", "Alt+C": "newLedger" };
      if (map[k]) { vePage.cur[map[k]](); return true; }
      if (k === "PageUp" || k === "PageDown") { vePage.cur.step(k === "PageUp" ? "prev" : "next"); return true; }
      if (k === "Escape") { if (document.querySelector(".tlpick")) return false; vePage.cur.quit(); return true; }
    }
    if (onVe && top && (k === "Y" || k === "N") && top.querySelector("footer .btn") && (!typing || !top.contains(document.activeElement)) && !top.querySelector("textarea,input")) {
      const b = k === "Y" ? top.querySelector("footer .btn.primary, footer .btn.warn") : [...top.querySelectorAll("footer .btn")].pop();
      if (b) { b.click(); return true; }
    }
    if (path === "acc/gw" && !typing && !top && /^[A-Z]$/.test(k)) {
      for (const [, items] of GW) for (const [l, , fn] of items) if (l === k) { fn(); return true; }
    }
    if (path === "tl/daybook" && k === "Alt+I" && tlOn) {
      const p = new URLSearchParams(location.hash.split("?")[1] || "");
      openVoucher(LSg("bco_tl_last", "payment"), { date: p.get("from") || today() }); return true;
    }
    if (path === "tl/tb" && (k === "Alt+F1" || k === "Alt+F5")) {
      const p = new URLSearchParams(location.hash.split("?")[1] || "");
      p.set("detail", k === "Alt+F1" ? "1" : "0"); location.hash = "#/tl/tb?" + p; return true;
    }
    return false;
  }
  function installKeys() {
    if (window.bcoUserKey && window.bcoUserKey._bco246) return;
    const prev = window.bcoUserKey;
    const f = (e, k, typing) => { try { if (tlKey(e, k, typing)) return true; } catch (err) { /* a shortcut must never break the screen */ } return prev ? prev(e, k, typing) : false; };
    f._bco246 = true;
    window.bcoUserKey = f;
  }

  /* ───────────────────────────── boot ───────────────────────────── */
  (window.bcoBootHooks = window.bcoBootHooks || []).unshift(() => {
    PAGES["acc/gw"] = gateway;
    PAGES["tl/ve"] = vePage;
    PAGES["tl/tb"] = tbPage;
    PAGES["tl/pl"] = plPage;
    PAGES["tl/bs"] = bsPage;
    PAGES["tl/daybook"] = daybookPage;
    PAGES["tl/coa"] = coaPage;
    PAGES["tl/map"] = mapPage;
    PAGES["tl/vtypes"] = vtypesPage;
    PAGES["tl/features"] = featuresPage;
    PAGES["tl/controls"] = controlsPage;
    PAGES["tl/editlog"] = editLogPage;
    installKeys();
    try {
      if (typeof MENU !== "undefined") {
        const g = MENU.find((x) => x[0] === "Accounts");
        if (g && !g[2].some((it) => it[0] === "acc/gw")) g[2].splice(0, 0, ["acc/gw", "Gateway (Tally-style)"]);
      }
    } catch (e) { /* ignore */ }
    if (S && S.user && can("accounts", "view")) meta(true).catch(() => {});
  });
  window.bcoTally = { meta, openVoucher };
})();
