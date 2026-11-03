/* BuildCore 2.41 — Papers with transactions.
   New tabs and panels only; the menu, module names and groups are unchanged:
     Bills, GRNs, POs (document window) and vouchers ....... Papers panel (attachments + library documents)
     Accounts › Payments & receipts ......................... Papers rules
     Document library ........................................ Linked to records
     Commercial › Contracts .................................. One contract register
     Field › Drawings ......................................... each sheet's Document control number */
(function () {
  "use strict";
  if (window.__bcoPapers) return;
  window.__bcoPapers = true;

  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const M = (v) => (v == null ? "—" : fmtMoney(v));
  const cap = (x) => (x ? x.charAt(0).toUpperCase() + x.slice(1) : x);

  /* upload that returns the new file ids (for a payment not yet made) */
  async function uploadIds(files, meta) {
    const ids = [];
    for (const f of files) {
      const qs = new URLSearchParams(Object.assign({ filename: f.name, mime: f.type || "" }, meta || {}));
      const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: f });
      const j = await r.json();
      if (!j.ok) { toast(f.name + ": " + j.error, "err"); continue; }
      ids.push(j.data.id);
    }
    return ids;
  }

  /* pick library documents: returns a promise of [{id,title}] */
  function pickLibrary(title) {
    return new Promise((resolve) => {
      let picked = [], done = false;
      const box = h("div");
      const inp = h("input", { type: "search", placeholder: "Search the library: bill number, party, words in the document", style: "width:100%" });
      const load = async () => {
        let d;
        try { d = await api("dl.search", { q: inp.value, per_page: 25 }); } catch (e) { box.innerHTML = ""; box.append(h("p", { class: "red" }, e.message)); return; }
        box.innerHTML = "";
        box.append(table([{ k: "title", label: "Document" }, { label: "File", v: (r) => r.file_name || "" }, { label: "Project", v: (r) => r.project_code || "" },
          { label: "Date", v: (r) => r.doc_date || "" },
          { label: "", v: (r) => h("button", { class: "btn small primary", onclick: (e) => { e.stopPropagation(); picked = [{ id: r.id, title: r.title }]; done = true; m.close(); resolve(picked); } }, "Link") }],
        d.rows || [], { search: false, export: false, empty: "Nothing found. Add the file in Document library first, or attach it here directly." }));
      };
      let t = null;
      inp.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 300); });
      const m = modal(title || "Link a library document", h("div", {}, inp, h("br"), box), [], { onClose: () => { if (!done) resolve([]); } });
      load();
    });
  }

  /* the Papers panel for one record */
  function papersPanel(entity, id) {
    const box = h("div", { class: "panel", style: "margin-top:10px" });
    const load = async () => {
      let d;
      try { d = await api("pp.papers", { entity, id }); } catch (e) { box.innerHTML = ""; box.append(h("p", { class: "muted" }, e.message)); return; }
      box.innerHTML = "";
      box.append(h("div", { class: "bar" }, h("b", { class: "grow" }, "Papers" + (d.of ? " (of the " + d.label + ")" : "")),
        d.needs ? h("span", { class: d.ok ? "green" : "red" }, d.ok ? "Paper attached" : "Needs its paper before posting") : null));
      if (d.needs) box.append(h("p", { class: "hint" }, d.needs));
      const rows = d.files.map((f) => ({ kind: "Attached", name: h("a", { href: fileUrl(f.id), target: "_blank" }, f.filename), date: f.date, del: null }))
        .concat(d.links.map((k) => ({ kind: "From the library", name: k.file_id ? h("a", { href: fileUrl(k.file_id), target: "_blank" }, k.title || k.file_name) : (k.title || "(removed from the library)"), date: (k.ts || "").slice(0, 10),
          del: d.can_edit ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("pp.unlink", { id: k.id }, "Unlinked"); load(); } }, "Unlink") : null })));
      box.append(rows.length ? table([{ k: "kind", label: "" }, { label: "Paper", v: (r) => r.name }, { k: "date", label: "Date" }, { label: "", v: (r) => r.del }], rows, { search: false, export: false })
        : h("p", { class: "muted" }, "No papers yet."));
      if (d.can_edit) {
        box.append(h("div", { class: "bar" }, uploadButton({ entity: d.entity, entity_id: d.id }, load, "Attach scan or photo"),
          h("button", { class: "btn small", type: "button", onclick: async () => {
            const p = await pickLibrary();
            if (p.length) { await run("pp.link", { entity: d.entity, entity_id: d.id, dl_ids: p.map((x) => x.id) }, "Linked"); load(); }
          } }, "Link from library")));
      }
    };
    load();
    return box;
  }
  window.bcoPapersPanel = papersPanel;

  /* bills, GRNs and POs: the panel under the lines of the document window */
  const DOC_ENT = { invoice: "invoices", grn: "grn", po: "po" };
  if (typeof window.docEditor === "function" && !window.docEditor.__pp) {
    const orig = window.docEditor;
    const wrapped = function (cfg, doc) {
      const ent = cfg && DOC_ENT[cfg.type];
      if (!ent || !doc || !doc.id) return orig(cfg, doc);
      const cfg2 = Object.assign({}, cfg, { after: (ctx) => { if (cfg.after) cfg.after(ctx); ctx.extra.append(papersPanel(ent, doc.id)); } });
      return orig(cfg2, doc);
    };
    wrapped.__pp = true;
    window.docEditor = wrapped;
  }

  /* vouchers: the panel at the foot of the voucher window (a payment's or bill's voucher shows that record's papers) */
  if (typeof window.voucherView === "function" && !window.voucherView.__pp) {
    const orig = window.voucherView;
    const wrapped = async function (id, reload) {
      const r = await orig(id, reload);
      const ovs = document.querySelectorAll(".overlay .modal .body");
      const body = ovs[ovs.length - 1];
      if (body) body.append(papersPanel("vouchers", id));
      return r;
    };
    wrapped.__pp = true;
    window.voucherView = wrapped;
  }

  /* a rule refused the posting: attach the paper here, then post again */
  const GATED = { "invoice.post": "invoices", "grn.post": "grn", "ipc.certify": "ipc", "voucher.post": "vouchers", "payment.create": "payments" };
  const _api = window.api;
  window.api = function (fn, args) {
    const p = _api.call(this, fn, args);
    if (!GATED[fn]) return p;
    return p.catch((err) => {
      if (!/^Papers needed:/.test(err.message || "")) throw err;
      return new Promise((resolve, reject) => {
        let settled = false;
        const ent = GATED[fn];
        const pending = [], pendingDl = [];
        const list = h("div");
        const showPending = () => { list.innerHTML = ""; list.append(pending.length || pendingDl.length ? h("p", {}, "Ready: " + pending.length + " file(s), " + pendingDl.length + " library document(s).") : h("p", { class: "muted" }, "Nothing attached yet.")); };
        let body;
        if (fn === "payment.create") {
          const inp = h("input", { type: "file", multiple: true, style: "display:none", onchange: async () => { pending.push(...(await uploadIds([...inp.files], { entity: "pp_pending" }))); inp.value = ""; showPending(); } });
          body = h("div", {}, h("p", {}, cap(err.message.replace(/^Papers needed: /, ""))), inp,
            h("div", { class: "bar" }, h("button", { class: "btn", type: "button", onclick: () => inp.click() }, "Attach scan or photo"),
              h("button", { class: "btn", type: "button", onclick: async () => { const x = await pickLibrary(); pendingDl.push(...x.map((y) => y.id)); showPending(); } }, "Link from library")), list);
          showPending();
        } else {
          body = h("div", {}, h("p", {}, cap(err.message.replace(/^Papers needed: /, ""))), papersPanel(ent, args.id));
        }
        modal("Attach the paper", body, [{ label: fn === "payment.create" ? "Post payment" : "Post again", cls: "primary", act: async () => {
          const a2 = fn === "payment.create" ? Object.assign({}, args, { file_ids: pending, dl_ids: pendingDl }) : args;
          try { const d = await _api.call(this, fn, a2); settled = true; resolve(d); } catch (e) { toast(e.message, "err"); throw e; }
        } }], { onClose: () => { if (!settled) { settled = true; reject(err); } } });
      });
    });
  };

  /* ───────── Accounts › Payments & receipts › Papers rules ───────── */
  async function rulesTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("pp.settings", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Which records need their paper (a scan or photo, or a document from the library) before they are posted. When a rule refuses, the screen asks for the paper and posts again. Records posted before a rule was switched on are listed in the data checks but do not fail them."));
      const f = h("div");
      d.rules.forEach((r) => f.append(h("label", { class: "f check", style: "display:block;margin:6px 0" }, h("input", { type: "checkbox", name: r.key, checked: r.on, disabled: !d.can_edit }),
        " " + r.label + (r.on && r.from ? " (since " + r.from + ")" : ""))));
      const over = h("input", { type: "number", value: d.journal_over, style: "max-width:160px", disabled: !d.can_edit });
      f.append(h("label", { class: "f" }, h("span", {}, "Manual voucher amount from which a paper is needed"), over));
      box.append(f);
      if (d.can_edit) box.append(h("button", { class: "btn primary", onclick: async () => {
        const v = { journal_over: over.value };
        f.querySelectorAll("input[type=checkbox]").forEach((i) => { v[i.name] = i.checked ? 1 : 0; });
        await run("pp.settings_save", v, "Saved"); load();
      } }, "Save rules"));
      else box.append(h("p", { class: "hint" }, "An accounts approver changes these rules."));
      const ch = (await api("fc.checks", {}).catch(() => ({ checks: [] }))).checks.filter((x) => x.area === "Documents");
      if (ch.length) box.append(h("h3", {}, "Posted records without their paper"), table([{ k: "check", label: "Check" }, { label: "Result", v: (r) => stamp(r.severity) }, { k: "detail", label: "Detail" }],
        ch, { search: false, export: false, onRow: (r) => { if (r.items.length) drawer(r.check, table([{ k: "ref", label: "Reference" }, { k: "date", label: "Date" }, { k: "detail", label: "Party / narration" }, { k: "amount", label: "Amount", fmt: "money" }], r.items, { name: "pp_missing" }), []); } }));
    };
    await load();
    return box;
  }

  /* ───────── Document library › Linked to records ───────── */
  async function linksTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("pp.links", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Library documents tied to vouchers, bills, payments, GRNs, POs, IPCs, measurements, claims and contracts. One document can be tied to several records; the library entry itself does not change."));
      if (d.can_link) {
        const kind = h("select", {}, d.kinds.map(([k, l]) => h("option", { value: k }, l)));
        const num = h("input", { placeholder: "Number, e.g. PI/2083-84/0004", list: "pp_nums" });
        const dl = h("datalist", { id: "pp_nums" });
        num.addEventListener("input", async () => {
          if (num.value.length < 2) return;
          const r = await api("pp.find", { entity: kind.value, q: num.value }).catch(() => []);
          dl.innerHTML = "";
          r.filter((x) => x.no).forEach((x) => dl.append(h("option", { value: x.no }, x.label)));
        });
        box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Record"), kind), h("label", { class: "f" }, h("span", {}, "Its number"), num), dl,
          h("button", { class: "btn primary", onclick: async () => {
            if (!num.value.trim()) return toast("Write the record's number.", "err");
            const p = await pickLibrary("Library document for " + num.value);
            if (!p.length) return;
            const r = await run("pp.link", { entity: kind.value, number: num.value.trim(), dl_ids: p.map((x) => x.id) });
            toast("Linked to " + r.label, "ok"); load();
          } }, "Choose the document and link")));
      }
      box.append(table([{ k: "kind", label: "Record" }, { k: "record", label: "Number" }, { label: "Document", v: (r) => r.file_id ? h("a", { href: fileUrl(r.file_id), target: "_blank" }, r.title || r.file_name) : r.title },
        { label: "Linked", v: (r) => (r.ts || "").slice(0, 10) + " " + (r.by_name || "") },
        { label: "", v: (r) => d.can_link ? h("button", { class: "btn small warn", onclick: async (e) => { e.stopPropagation(); await run("pp.unlink", { id: r.id }, "Unlinked"); load(); } }, "Unlink") : "" }],
      d.rows, { name: "pp_links", empty: "No library document is linked to a record yet." }));
    };
    await load();
    return box;
  }

  /* ───────── Commercial › Contracts › One contract register ───────── */
  const F5 = [["contract_value", "Value", "money"], ["start_date", "Start"], ["end_date", "End"], ["retention_pct", "Retention %"], ["advance_pct", "Advance %"]];
  async function registerTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("pp.con_overview", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, d.on
        ? "Contracts is the contract record (since " + d.from + "). A client contract's value, dates, retention and advance are written to its project; Claims and the command centre read them; bonds and insurance are kept in Contract admin › Securities; subcontract work orders take their terms from the subcontract."
        : "Today each project keeps its own contract value, and the Claims register, securities and work orders keep their own copies. Make a client contract for each project, check that the figures agree, then switch on."));
      const fig = (o, k, f) => (o && o[k] != null ? (f === "money" ? M(o[k]) : o[k]) : "—");
      box.append(h("h3", {}, "Projects and their client contracts"), table([{ k: "code", label: "Project" },
        ...F5.map(([k, l, f]) => ({ label: l, v: (r) => h("span", {}, fig(r.project, k, f), r.register ? h("br") : null, r.register ? h("span", { class: r.differs.includes(k) ? "red" : "muted" }, "Contracts: " + fig(r.register, k, f)) : null) })),
        { label: "Status", v: (r) => h("span", { class: r.status === "agrees" ? "green" : r.status === "differs" ? "red" : "muted" }, r.status) },
        { label: "", v: (r) => !r.register && d.can_edit ? h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("pp.con_create_client", { project_id: r.project_id }, "Client contract made"); load(); } }, "Make client contract from the project") : "" }],
      d.rows, { search: false, name: "pp_con" }));
      if (d.can_edit && d.rows.some((r) => !r.register)) box.append(h("button", { class: "btn", onclick: async () => { const r = await run("pp.con_create_client", {}); toast(r.made + " client contract(s) made", "ok"); load(); } }, "Make client contracts for every project without one"));
      if (d.work_orders.length) box.append(h("h3", {}, "Subcontract work orders"), table([{ k: "no", label: "Work order" }, { k: "project", label: "Project" }, { k: "party", label: "Subcontractor" },
        { k: "retention_pct", label: "Retention %", fmt: "qty" }, { k: "advance", label: "Advance", fmt: "money" }, { label: "Subcontract", v: (r) => r.contract_id ? (r.ref_no || "") + " " + (r.contract || "") : h("span", { class: "muted" }, "not linked") }], d.work_orders, { search: false, export: false }));
      if (d.bonds.length) box.append(h("h3", {}, "Bonds and insurance on contracts"), table([{ k: "title", label: "Contract" }, { k: "bond_no", label: "Bond no." }, { k: "bond_expiry", label: "Bond expires" }, { k: "insurance_expiry", label: "Insurance expires" },
        { label: "In Securities", v: (r) => (r.in_securities ? "yes" : "not yet") }], d.bonds, { search: false, export: false }));
      if (d.can_switch) box.append(h("div", { class: "bar", style: "margin-top:12px" }, d.on
        ? h("button", { class: "btn warn", onclick: async () => { if (!(await ask("Switch off", "Projects, Claims and work orders keep their current figures, and keep their own copies from now on.", { danger: true }))) return; await run("pp.con_switch", { on: 0 }, "Switched off"); load(); } }, "Switch off")
        : h("button", { class: "btn primary", onclick: async () => {
          const ch = d.rows.filter((r) => r.status === "differs").map((r) => r.code + ": " + r.differs.join(", ")).join("; ");
          if (!(await ask("Contracts becomes the contract record", (ch ? "These project figures will change to the contract's: " + ch + ". " : "No project figure changes. ") + "Bonds and insurance on contracts are copied to Contract admin › Securities.", {}))) return;
          const r = await run("pp.con_switch", { on: 1 }, "Switched on");
          toast(Object.keys(r.changed).length + " project(s) updated, " + r.bonds_copied + " bond / insurance record(s) copied", "ok"); load();
        } }, "Confirm and switch on")));
      const said = (r) => {
        let x = {};
        try { x = JSON.parse(r.detail || "{}"); } catch (e) { return r.detail || ""; }
        if (r.what === "con_register") return (x.on ? "Switched on" : "Switched off") + (x.on ? ": " + Object.keys(x.changed || {}).length + " project(s) updated" + (Object.keys(x.changed || {}).length ? " (" + Object.entries(x.changed).map(([p, ch]) => p + ": " + Object.keys(ch).join(", ")).join("; ") + ")" : "") + ", " + (x.bonds_copied || 0) + " bond / insurance record(s) copied to Securities" : "");
        if (r.what === "con_create") return (x.made || []).length + " client contract(s) made from the project record";
        if (r.what === "project_from_contract") {
          const pc = (d.rows.find((y) => y.project_id === x.project_id) || {}).code || "project";
          return pc + ": " + Object.keys(x.after || {}).filter((k) => String((x.before || {})[k]) !== String(x.after[k])).map((k) => k.replace(/_/g, " ") + " " + ((x.before || {})[k] ?? "—") + " → " + x.after[k]).join(", ") + " (" + (x.why || "") + ")";
        }
        return r.detail || "";
      };
      if (d.log.length) box.append(h("h3", {}, "Record"), table([{ k: "ts", label: "When", v: (r) => (r.ts || "").replace("T", " ").slice(0, 16) }, { k: "by_name", label: "Who" }, { label: "What", v: said }], d.log, { search: false, export: false }));
    };
    await load();
    return box;
  }

  /* contract window: bond and insurance read-only once Securities keeps them, with the contract's securities listed */
  let lastCon = null;
  const _api2 = window.api;
  window.api = function (fn, args) {
    const p = _api2.call(this, fn, args);
    if (fn === "con.get") p.then((k) => { lastCon = k; }).catch(() => {});
    return p;
  };
  new MutationObserver(() => {
    const bond = document.querySelector('.overlay input[name="bond_no"]:not([data-pp])');
    if (!bond) return;
    bond.dataset.pp = "1";
    const k = lastCon;
    if (!k || !k.register_on) return;
    ["bond_no", "bond_expiry", "insurance_expiry"].forEach((n) => { const i = document.querySelector('.overlay [name="' + n + '"]'); if (i) { i.readOnly = true; i.title = "Kept in Contract admin › Securities"; } });
    const form = bond.closest("form") || bond.closest(".form") || bond.parentElement.parentElement;
    if (form && k.securities) form.after(h("div", { class: "panel", style: "margin:8px 0" }, h("b", {}, "Bonds and insurance (Contract admin › Securities)"),
      k.securities.length ? table([{ k: "kind", label: "What" }, { k: "number", label: "Number" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "expiry_date", label: "Expires" }, { k: "status", label: "Status" }], k.securities, { search: false, export: false })
        : h("p", { class: "muted" }, "None yet: add them in Contract admin › Securities and choose this contract.")));
  }).observe(document.body, { childList: true, subtree: true });

  /* Field › Drawings: each sheet's Document control number */
  const origDw = PAGES["f/drawings"];
  if (origDw && !origDw.__pp) {
    const page = async (root, params) => {
      await origDw(root, params);
      const head = root.querySelector(".bar");
      if (head) head.after(h("p", { class: "hint" }, "Every sheet is also a card in Document control, with the same revisions: a revision added on either screen appears on the other. Reviews and transmittals are done in Document control."));
    };
    Object.keys(origDw).forEach((k) => { page[k] = origDw[k]; });
    page.__pp = true;
    PAGES["f/drawings"] = page;
  }

  addTabs("acc/payments", "Payments & receipts", "Pay and receive against invoices, with TDS and advances.", "Payments & receipts", [["Papers rules", rulesTab]]);
  addTabs("dl", "Document library", "Files added here, attachments on records and Document control revisions, searchable by the words inside them.", "Library", [["Linked to records", linksTab]]);
  addTabs("c/contracts", "Contracts & letters", "Every contract with its letters, reports, bills, deliveries and milestones as the contract requires — what is due, what is late, bonds and insurance expiring.", "Contracts", [["One contract register", registerTab]]);

  /* What's new */
  const VER = "2.41.0";
  function whatsNew() {
    try { if (localStorage.getItem("bco_seen_" + VER)) return; } catch (e) { return; }
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!can("accounts", "view") && !can("commercial", "view")) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "Papers on money records. "), "Bills, GRNs, POs and vouchers have a ", h("b", {}, "Papers"), " panel: attach the scan, or link a document from the library. ", h("b", {}, "Papers rules"), " (Payments & receipts) say which records need one before posting."),
        h("li", {}, h("b", {}, "Library documents tied to records "), "(Document library › Linked to records): one document, as many records as it supports."),
        h("li", {}, h("b", {}, "One drawing register. "), "Field › Drawings and Document control now hold the same sheets and revisions."),
        h("li", {}, h("b", {}, "One contract register "), "(Commercial › Contracts): the project, Claims, the command centre, securities and work orders read the contract.")),
      h("p", { class: "hint" }, "Nothing already posted is changed. In a company updated from an earlier version, the rules and the contract register stay off until accounts turns them on.")),
    [{ label: "Open Papers rules", cls: "primary", act: () => { location.hash = "#/acc/payments"; let n = 0; const t = setInterval(() => { const b = [...document.querySelectorAll(".tabs button")].find((x) => x.textContent.trim() === "Papers rules"); if (b) { clearInterval(t); b.click(); } else if (++n > 40) clearInterval(t); }, 250); } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 15000); } }, 900);
})();
