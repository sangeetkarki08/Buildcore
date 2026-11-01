/* BuildCore 2.21 — how the work is executed, approved, posted and measured.
   Accounts posting queue (site raises, manager approves, accounts posts), subcontract work orders with
   material issued to the subcontractor and running bills with recoveries, the execution plan by BOQ item,
   rental deductions on hired machines, owned equipment cost per hour (cash and economic view), delays by
   responsibility, and returns (ROA / ROE, per machine, small-asset pools). */
(function () {
  "use strict";
  const VER = "2.21.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  let META = null;
  const meta = async () => { if (!META) META = await api("exec.meta", {}); return META; };
  const right = (m, a) => !!(META && (META.rights[m] || []).includes(a)) || can(m, a);
  const label = (list, k) => ((list || []).find((x) => x[0] === k) || [k, k || "—"])[1];
  const money = (v) => fmtMoney(v);
  const pct = (v) => v == null ? "—" : fmtN(v, 1) + "%";
  const mos = () => today().slice(0, 7);

  const css = document.createElement("style");
  css.textContent = [
    ".xt{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin:0 0 14px}",
    ".xt .t{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-left:4px solid #1769aa;border-radius:12px;padding:10px 14px}",
    ".xt .t.click{cursor:pointer}.xt .t b{display:block;font-size:19px;font-variant-numeric:tabular-nums}.xt .t span{color:var(--muted,#5b7183);font-size:12.5px}",
    ".xt .t.warn{border-left-color:#b7791f}.xt .t.bad{border-left-color:#c0392b}.xt .t.good{border-left-color:#2f7a4d}.xt .t.grey{border-left-color:#8796a3}",
    ".xnote{background:rgba(23,105,170,.07);border:1px solid rgba(23,105,170,.25);border-radius:10px;padding:9px 13px;margin:0 0 12px;font-size:13.5px}",
    ".xflow{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:0 0 12px;font-size:13px}",
    ".xflow span{padding:4px 10px;border-radius:999px;background:var(--panel,#fff);border:1px solid var(--line,#d6dee5)}",
    ".xflow span.on{background:#1769aa;color:#fff;border-color:#1769aa}.xflow i{color:var(--muted,#5b7183);font-style:normal}",
    ".xdu{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:0 0 14px}",
    ".xdu .c{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-radius:12px;padding:12px 16px}",
    ".xdu .c h4{margin:0 0 8px;font-size:13px;color:var(--muted,#5b7183);font-weight:600}",
    ".xdu .big{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}.xdu .eq{font-size:13px;color:var(--muted,#5b7183);margin-top:6px;line-height:1.5}",
    ".xmode{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;margin:1px 3px 1px 0;background:rgba(23,105,170,.1);color:#1769aa;white-space:nowrap}",
    ".xmode.labour_sc{background:rgba(183,121,31,.12);color:#8a5a14}.xmode.supplied_sc{background:rgba(47,122,77,.12);color:#226040}",
    ".xmode.b2b_sc{background:rgba(120,72,160,.12);color:#5c3a86}.xmode.unplanned{background:rgba(135,150,163,.15);color:#5b7183}",
    ".xbar{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:6px 0 14px;background:rgba(135,150,163,.18)}",
    ".xbar i{display:block;height:100%}",
    ".xr{color:#c0392b}.xg{color:#2f7a4d}",
  ].join("\n");
  document.head.append(css);

  const tile = (v, l, cls, onclick) => h("div", { class: "t " + (cls || "") + (onclick ? " click" : ""), onclick }, h("b", {}, v), h("span", {}, l));
  const MODE_COL = { direct: "#1769aa", labour_sc: "#c08a2c", supplied_sc: "#2f7a4d", b2b_sc: "#7848a0", unplanned: "#b9c4cd" };
  const pidNow = () => S.project || "";

  /* ───────────────────────── accounts posting queue ───────────────────────── */
  function flow(stage) {
    const st = [["review", "Raised by site"], ["approved", "Approved by manager"], ["posted", "Posted by accounts"]];
    const i = stage === "posted" ? 2 : stage === "approved" ? 1 : 0;
    return h("div", { class: "xflow" }, st.map(([, l], j) => [h("span", { class: j <= i ? "on" : "" }, l), j < 2 ? h("i", {}, "›") : null]));
  }

  async function entryDialog(r, reload) {
    const d = await run("pq.get", { id: r.voucher_id });
    const canPost = r.can_post || (d.stage === "approved" && right("accounts", "post"));
    const accs = opt.accounts();
    const le = lineEditor([
      { k: "account_id", label: "Account", type: "select", options: accs, w: 260, readonly: !canPost },
      { k: "debit", label: "Debit", show: (x) => x.debit ? fmtMoney(x.debit) : "", num: true },
      { k: "credit", label: "Credit", show: (x) => x.credit ? fmtMoney(x.credit) : "", num: true },
      { k: "pcode", label: "Project", show: (x) => x.pcode || "" },
      { k: "eq_code", label: "Machine", show: (x) => x.eq_code || "" },
      { k: "narration", label: "Narration", show: (x) => x.narration || "" },
    ], d.lines, { fixed: true });
    const dateF = form([{ k: "date", label: "Posting date", type: "date", default: d.date }], {});
    const btns = [];
    if (r.can_approve) btns.push({ label: "Approve", cls: "primary", act: async () => { await run("pq.approve", { id: d.voucher_id }, "Approved — now with accounts"); reload(); } });
    if (canPost) {
      btns.push({ label: "Save account changes", act: async () => {
        await run("pq.recode", { id: d.voucher_id, lines: le.lines().map((x) => ({ id: x.id, account_id: x.account_id })) }, "Saved"); return false; } });
      btns.push({ label: "Post to ledger", cls: "primary", act: async () => {
        await run("pq.recode", { id: d.voucher_id, lines: le.lines().map((x) => ({ id: x.id, account_id: x.account_id })) });
        await run("pq.post", { id: d.voucher_id, date: dateF.values().date }, (x) => "Posted " + x.posted.join(", ")); reload(); } });
    }
    if (r.can_approve || canPost) btns.push({ label: "Return with a note", cls: "warn", act: async () => {
      const note = await ask("Return " + (d.label || "entry"), "Say what must be corrected. A bill goes back to draft; for a store issue or DPR the site corrects or cancels the document.", { input: "Reason", required: true, ok: "Return" });
      if (!note) return false;
      await run("pq.return", { id: d.voucher_id, note }, "Returned"); reload(); } });
    modal((d.gate_label || "Entry") + " — " + fmtMoney(d.amount), h("div", {}, flow(d.stage),
      kv([["Document", d.label], ["Date", d.date], ["Project", d.pcode || "—"], ["Raised by", d.created_name || "—"],
        ["Approved by", d.approved_name || (d.stage === "approved" ? "—" : "waiting")], d.note ? ["Note", h("b", { class: "xr" }, d.note)] : null]),
      h("p", { class: "hint" }, canPost ? "Check the coding. You can change the account before posting; amounts stay as raised. The voucher number is given when you post." :
        "This entry is complete and balanced but is not in the books until accounts posts it."),
      le, canPost ? dateF : null), btns);
    setTimeout(() => { const a = document.activeElement; if (a && a.blur && a.closest(".modal")) a.blur(); document.querySelectorAll(".modal .cbmenu").forEach((x) => { x.hidden = true; }); }, 0);
  }

  PAGES["x/queue"] = async (root) => {
    await meta();
    const holder = h("div");
    let stage = LSg("bco_x_queue_tab", "todo");
    const load = async () => {
      const [s, open] = await Promise.all([run("pq.summary", {}), run("pq.list", { stage: stage === "posted" ? "posted" : "open", project_id: pidNow() })]);
      holder.innerHTML = "";
      holder.append(h("div", { class: "xt" },
        tile(s.review, "Waiting for manager approval", s.review ? "warn" : "good", () => { stage = "review"; LSs("bco_x_queue_tab", stage); load(); }),
        tile(s.approved, "Approved, waiting for accounts", s.approved ? "warn" : "good", () => { stage = "approved"; LSs("bco_x_queue_tab", stage); load(); }),
        tile(money(s.amount), "Not yet in the books"),
        tile(s.oldest_days + " d", "Oldest waiting entry", s.oldest_days > 7 ? "bad" : s.oldest_days > 3 ? "warn" : "good"),
        tile(s.mine_to_approve + " / " + s.mine_to_post, "For you: approve / post", "grey", () => { stage = "todo"; LSs("bco_x_queue_tab", stage); load(); })));
      const tabsBar = h("div", { class: "tabs" }, [["todo", "For me"], ["review", "Waiting approval"], ["approved", "Ready to post"], ["returned", "Returned"], ["posted", "Posted"]].map(([k, l]) =>
        h("button", { class: k === stage ? "on" : "", onclick: () => { stage = k; LSs("bco_x_queue_tab", k); load(); } }, l)));
      let rows = open;
      if (stage === "todo") rows = open.filter((r) => r.can_approve || r.can_post);
      else if (stage === "review") rows = open.filter((r) => r.stage === "review");
      else if (stage === "approved") rows = open.filter((r) => r.stage === "approved");
      else if (stage === "returned") rows = open.filter((r) => r.stage === "returned");
      const bulk = [];
      if (rows.some((r) => r.can_approve)) bulk.push(h("button", { class: "btn", onclick: async () => {
        const ids = rows.filter((r) => r.can_approve).map((r) => r.voucher_id);
        if (!(await ask("Approve " + ids.length + " entries", "Approve every listed entry you are allowed to approve?"))) return;
        await run("pq.approve", { ids }, (x) => x.approved + " approved"); load(); } }, "Approve all listed"));
      if (rows.some((r) => r.can_post)) bulk.push(h("button", { class: "btn primary", onclick: async () => {
        const ids = rows.filter((r) => r.can_post).map((r) => r.voucher_id);
        if (!(await ask("Post " + ids.length + " entries", "Post every listed approved entry to the ledger, each on its own date?"))) return;
        await run("pq.post", { ids }, (x) => x.posted.length + " posted"); load(); } }, "Post all listed"));
      holder.append(tabsBar, bulk.length ? h("div", { class: "actions", style: "margin:8px 0" }, bulk) : null,
        table([{ k: "date", label: "Date" }, { k: "gate_label", label: "Kind" }, { k: "label", label: "Document" },
          { k: "pcode", label: "Project" }, { k: "amount", label: "Amount", fmt: "money" },
          { label: "Stage", v: (r) => stamp(r.stage === "review" ? "waiting_approval" : r.stage === "approved" ? "waiting_accounts" : r.stage) },
          { k: "created_name", label: "Raised by" }, stage === "posted" ? { k: "posted_no", label: "Voucher" } : { k: "age_days", label: "Days waiting", fmt: "num" },
          { label: "Note", v: (r) => r.note || "" }],
        rows, { name: "posting_queue", totals: ["amount"], onRow: (r) => stage === "posted" ? null : entryDialog(r, load),
          empty: stage === "todo" ? "Nothing waits for you." : "Nothing here." }));
    };
    const settings = h("button", { class: "btn small", onclick: () => gateSettings() }, "Which costs wait for accounts");
    root.append(pageHead("Accounts posting queue", "Operational costs reach the books in three steps: the site raises them, the manager approves, accounts checks the coding and posts.", settings));
    root.append(h("div", { class: "xnote" }, "Waiting entries are complete and balanced but stay out of every report, balance and statement until accounts posts them. A bill waiting here cannot be paid yet."));
    root.append(holder);
    await load();
  };

  async function gateSettings() {
    const m = await meta();
    const f = form(m.gates.map((g) => ({ k: g.key, label: g.label, type: "check" })), Object.fromEntries(m.gates.map((g) => [g.key, g.on ? 1 : 0])));
    modal("Which costs wait for accounts", h("div", {}, h("p", { class: "hint" }, "Ticked: the entry waits in the posting queue (approve, then post). Not ticked: it posts the moment the site acts, as before 2.21. Goods receipts, material bills, sales, IPCs, payments and manual vouchers always work as before."), f),
      right("accounts", "approve") ? [{ label: "Save", cls: "primary", act: async () => { await run("gate.save", { gates: f.values() }, "Saved"); META = null; } }] : [], { narrow: true });
  }

  /* ───────────────────────── subcontract work orders ───────────────────────── */
  const SC_TYPES = () => (META && META.sc_types) || [];
  const recBasis = [["bill_oh", "Our bill rate + overhead %"], ["fixed", "One agreed rate per material"]];

  async function orderDialog(o, reload) {
    await meta();
    const isNew = !o || !o.id;
    const d = isNew ? { type: "supplied", recovery_basis: "bill_oh", date: today(), project_id: pidNow(), items: [], mats: [], status: "draft" } : await run("sco.get", { id: o.id });
    const ro = d.status !== "draft" && d.status !== "approved";
    let hf;
    const sync = () => {
      const v = hf.values();
      boqs = v.project_id ? opt.boq(v.project_id) : [];
      items.rebuild(); mats.rebuild();
    };
    let boqs = d.project_id ? opt.boq(d.project_id) : [];
    hf = form([
      { k: "project_id", label: "Project", type: "select", options: opt.projects(), req: true, readonly: !isNew && d.bills && d.bills.length },
      { k: "party_id", label: "Subcontractor", type: "select", options: opt.parties(["subcontractor", "vendor"]), req: true },
      { k: "type", label: "Type of subcontract", type: "select", options: SC_TYPES(), noBlank: true, req: true },
      { k: "title", label: "Scope / title", wide: true },
      { k: "date", label: "Date", type: "date", req: true }, { k: "start_date", label: "Start", type: "date" }, { k: "end_date", label: "Finish", type: "date" },
      { k: "retention_pct", label: "Retention %", type: "number" }, { k: "vat_rate", label: "VAT % on work", type: "number" },
      { k: "advance", label: "Mobilisation advance agreed", type: "number" },
      { k: "recovery_basis", label: "Material recovery basis", type: "select", options: recBasis, noBlank: true },
      { k: "overhead_pct", label: "Overhead % on our bill rate", type: "number", hint: "Used with 'bill rate + overhead'" },
      { k: "equip_terms", label: "Our equipment: terms", wide: true, ph: "e.g. Excavator at Rs 3,000 per hour, deducted from the bill" },
      { k: "remarks", label: "Remarks", wide: true },
    ], d, sync);
    const items = lineEditor([
      { k: "boq_item_id", label: "BOQ item", type: "select", options: () => boqs, w: 220, onChange: (r) => {
        const b = byId(S.L.boq, r.boq_item_id); if (b) { r.description = r.description || b.description; r.unit = r.unit || b.unit; } }, rerender: true },
      { k: "description", label: "Description", w: 200 }, { k: "unit", label: "Unit", w: 60 },
      { k: "qty", label: "Quantity", type: "number", w: 90 }, { k: "rate", label: "Rate", type: "number", w: 90 },
      { k: "amt", label: "Amount", show: (r) => fmtMoney((Number(r.qty) || 0) * (Number(r.rate) || 0)), num: true },
      { k: "done", label: "Billed so far", show: (r) => r.done ? fmtQty(r.done) : "", num: true },
    ], d.items, { readonly: ro });
    const mats = lineEditor([
      { k: "material_id", label: "Material we supply", type: "select", options: opt.materials(), w: 220 },
      { k: "order_item_id", label: "For item", type: "select", options: () => (d.items || []).map((i) => [i.id, i.description]), w: 160 },
      { k: "per_unit", label: "Use per unit of work", type: "number", w: 90 },
      { k: "wastage_pct", label: "Wastage allowed %", type: "number", w: 80 },
      { k: "fixed_rate", label: "Agreed recovery rate", type: "number", w: 100 },
    ], d.mats, { readonly: ro });
    const parts = [h("p", { class: "hint" }, "Labour supply: the gang is paid quantity × labour rate. Item rate with our material: the subcontractor is paid quantity × full rate, and the material and equipment we supplied are deducted. Back-to-back: the subcontractor brings everything."),
      hf, h("h3", {}, "Items and rates"), items,
      h("h3", {}, "Material we supply (for recovery and reconciliation)"),
      h("p", { class: "hint" }, "'Use per unit' is the norm, e.g. 6.5 bags of cement per m³; with the wastage allowance it gives the theoretical use in the reconciliation. The agreed recovery rate is needed only for 'one agreed rate'."), mats];
    const btns = [];
    if (!ro && right("commercial", "edit")) btns.push({ label: "Save", cls: "primary", act: async () => {
      const r = await run("sco.save", { header: Object.assign(hf.values(), { id: d.id }), items: items.lines(), mats: mats.lines() }, "Work order saved");
      reload(); if (isNew) orderPage(r.id, reload); } });
    if (d.id && d.status === "draft" && right("commercial", "approve")) btns.push({ label: "Approve work order", act: async () => { await run("sco.approve", { id: d.id }, "Approved"); reload(); } });
    modal(isNew ? "New subcontract work order" : "Work order " + d.no, h("div", {}, parts), btns);
  }

  async function orderPage(id, reload) {
    const o = await run("sco.get", { id });
    const typeName = label(SC_TYPES(), o.type);
    const done = o.items.reduce((a, i) => a + (i.done || 0) * (i.rate || 0), 0);
    const held = o.recon.reduce((a, r) => a + (r.balance_value || 0), 0);
    const posted = o.bills.filter((b) => b.status === "posted");
    const body = h("div", {},
      h("div", { class: "xt" }, tile(money(o.value), "Work order value"), tile(money(done), "Billed (gross)", "good"),
        tile(money(posted.reduce((a, b) => a + b.net, 0)), "Net payable posted"),
        tile(money(held), "Our material with the subcontractor", held > 0 ? "warn" : "grey"),
        tile(money(posted.reduce((a, b) => a + b.retention, 0)), "Retention held", "grey")),
      kv([["Subcontractor", o.party], ["Project", nm.project(o.project_id)], ["Type", typeName], ["Status", stamp(o.status)],
        ["Recovery", o.type === "b2b" ? "Not applicable" : (o.recovery_basis === "fixed" ? "One agreed rate per material" : "Bill rate + " + (o.overhead_pct || 0) + "% overhead")],
        ["Retention", (o.retention_pct || 0) + "%"]]),
      tabs([
        ["Running bills", () => table([{ k: "no", label: "Bill" }, { k: "date", label: "Date" }, { k: "gross", label: "Gross", fmt: "money" },
          { k: "material_recovery", label: "Material", fmt: "money" }, { k: "equipment_recovery", label: "Equipment", fmt: "money" },
          { k: "other_deduction", label: "Other", fmt: "money" }, { k: "advance_recovery", label: "Advance", fmt: "money" },
          { k: "retention", label: "Retention", fmt: "money" }, { k: "net", label: "Net payable", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
          o.bills, { name: "subcontract_bills", totals: ["gross", "material_recovery", "net"], onRow: (b) => billDialog(o, b.id, () => orderPage(id, reload)), empty: "No bills yet." })],
        ["Items", () => table([{ k: "boq_code", label: "BOQ" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" },
          { k: "qty", label: "Order qty", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "done", label: "Billed qty", fmt: "qty" },
          { label: "Balance", fmt: "qty", v: (r) => (r.qty || 0) - (r.done || 0) }], o.items, { search: false })],
        ["Material with subcontractor", () => table([{ k: "material", label: "Material" }, { k: "unit", label: "Unit" }, { k: "issued", label: "Issued", fmt: "qty" },
          { k: "returned", label: "Returned", fmt: "qty" }, { k: "recovered", label: "Recovered in bills", fmt: "qty" }, { k: "balance", label: "Still with them", fmt: "qty" },
          { k: "balance_value", label: "Value (our cost)", fmt: "money" }, { k: "theoretical", label: "Should have used", fmt: "qty" },
          { k: "allowed", label: "Allowed with wastage", fmt: "qty" },
          { label: "Excess use", v: (r) => r.excess == null ? "—" : h("b", { class: r.excess > 0 ? "xr" : "xg" }, fmtQty(r.excess)) },
          { k: "excess_value", label: "Excess value", fmt: "money" }], o.recon, { search: false, empty: "No material issued." })],
        ["Issues and returns", () => table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "kind", label: "Kind" }, { k: "mname", label: "Material" },
          { k: "qty", label: "Qty", fmt: "qty" }, { k: "rate", label: "Cost rate", fmt: "money" }, { k: "value", label: "Value", fmt: "money" }], o.moves, { search: false })],
      ]));
    const btns = [];
    if (o.status === "approved" && right("commercial", "edit")) btns.push({ label: "New running bill", cls: "primary", act: () => { billDialog(o, null, () => orderPage(id, reload)); } });
    if (o.status === "approved" && o.type !== "b2b" && right("inventory", "edit")) {
      btns.push({ label: "Issue material", act: () => { moveDialog(o, "issue", () => orderPage(id, reload)); } });
      btns.push({ label: "Take material back", act: () => { moveDialog(o, "return", () => orderPage(id, reload)); } });
    }
    btns.push({ label: o.status === "draft" ? "Edit / approve" : "Work order details", act: () => { orderDialog(o, reload); } });
    if (o.status === "approved" && right("commercial", "approve")) btns.push({ label: "Close work order", act: async () => { await run("sco.close", { id: o.id }, "Closed"); reload(); } });
    modal("Work order " + o.no + " — " + o.party, body, btns);
  }

  function moveDialog(o, kind, after) {
    const f = form([{ k: "store_id", label: "Store", type: "select", options: opt.stores(o.project_id), req: true },
      { k: "date", label: "Date", type: "date", default: today() }, { k: "remarks", label: "Remarks", wide: true }], {});
    const le = lineEditor([{ k: "material_id", label: "Material", type: "select", options: opt.materials(), w: 260 },
      { k: "qty", label: "Quantity", type: "number", w: 100 }], (o.mats || []).map((m) => ({ material_id: m.material_id })));
    modal(kind === "issue" ? "Issue material to " + o.party : "Material back from " + o.party, h("div", {},
      h("p", { class: "hint" }, kind === "issue" ? "Stock leaves the store at its average cost and is held as 'Material with subcontractors' until it is recovered in their bill. It is not expensed." :
        "Unused material comes back into the store at the cost it went out."), f, le),
    [{ label: kind === "issue" ? "Issue" : "Receive back", cls: "primary", act: async () => {
      await run("sco.issue", Object.assign(f.values(), { order_id: o.id, kind, lines: le.lines() }), (r) => "Posted " + r.no); after(); } }]);
  }

  async function billDialog(o, billId, after) {
    let b, items, recs;
    if (billId) {
      b = await run("sco.bill_get", { id: billId });
      items = o.items.map((i) => { const x = b.items.find((y) => y.order_item_id === i.id); return { order_item_id: i.id, description: i.description, unit: i.unit, order_qty: i.qty, prev_qty: x ? x.prev_qty : (i.done || 0), qty: x ? x.qty : 0, rate: i.rate }; });
      recs = b.recoveries.map((r) => Object.assign({}, r, { unit: r.munit }));
    } else {
      const p = await run("sco.bill_prefill", { order_id: o.id });
      b = { status: "draft", date: today(), order_id: o.id };
      items = p.items; recs = p.recoveries;
      if (p.advance_open > 0) b.advance_hint = p.advance_open;
    }
    const ro = b.status !== "draft";
    const hf = form([{ k: "date", label: "Bill date", type: "date", req: true, readonly: ro }, { k: "period_to", label: "Work up to", type: "date", readonly: ro },
      { k: "party_bill_no", label: "Subcontractor's bill no.", readonly: ro },
      { k: "advance_recovery", label: "Advance recovery" + (b.advance_hint ? " (open " + fmtMoney(b.advance_hint) + ")" : ""), type: "number", readonly: ro },
      { k: "retention", label: "Retention (blank = " + (o.retention_pct || 0) + "%)", type: "number", readonly: ro },
      { k: "remarks", label: "Remarks", wide: true, readonly: ro }], b);
    const tot = h("div", { class: "panel" });
    const calc = () => {
      const L = it.lines(), R = rc.lines();
      const gross = L.reduce((a, x) => a + (Number(x.qty) || 0) * (Number(x.rate) || 0), 0);
      const mat = R.filter((x) => x.kind === "material").reduce((a, x) => a + (Number(x.qty) || 0) * (Number(x.rate) || 0), 0);
      const eq = R.filter((x) => x.kind === "equipment").reduce((a, x) => a + (Number(x.qty) || 0) * (Number(x.rate) || 0), 0);
      const oth = R.filter((x) => x.kind !== "material" && x.kind !== "equipment").reduce((a, x) => a + (Number(x.amount) || (Number(x.qty) || 0) * (Number(x.rate) || 0)), 0);
      const v = hf.values();
      const ret = v.retention !== "" && v.retention != null ? Number(v.retention) : gross * (o.retention_pct || 0) / 100;
      const vat = gross * (o.vat_rate || 0) / 100;
      const adv = Number(v.advance_recovery) || 0;
      const net = gross + vat - mat - eq - oth - adv - ret;
      tot.innerHTML = "";
      tot.append(kv([["Work done this bill", fmtMoney(gross)], vat ? ["VAT", fmtMoney(vat)] : null, ["Less material recovered", fmtMoney(mat)],
        ["Less equipment recovered", fmtMoney(eq)], ["Less other deductions", fmtMoney(oth)], ["Less advance recovery", fmtMoney(adv)],
        ["Less retention", fmtMoney(ret)], ["Net payable", h("b", { class: net < 0 ? "xr" : "" }, fmtMoney(net))]]));
    };
    const it = lineEditor([
      { k: "description", label: "Item", show: (r) => r.description },
      { k: "order_qty", label: "Order qty", show: (r) => fmtQty(r.order_qty), num: true },
      { k: "prev_qty", label: "Previous", show: (r) => fmtQty(r.prev_qty), num: true },
      { k: "qty", label: "This bill", type: "number", w: 90, readonly: ro },
      { k: "cum", label: "Cumulative", show: (r) => fmtQty((Number(r.prev_qty) || 0) + (Number(r.qty) || 0)), num: true },
      { k: "rate", label: "Rate", show: (r) => fmtMoney(r.rate), num: true },
      { k: "amt", label: "Amount", show: (r) => fmtMoney((Number(r.qty) || 0) * (Number(r.rate) || 0)), num: true },
    ], items, { fixed: true, onChange: () => setTimeout(calc, 0) });
    const rc = lineEditor([
      { k: "kind", label: "Deduction", type: "select", options: [["material", "Material we supplied"], ["equipment", "Our equipment"], ["other", "Other deduction"], ["penalty", "Penalty / excess use"]], noBlank: true, w: 150, readonly: ro, rerender: true },
      { k: "material_id", label: "Material", type: "select", options: opt.materials(), w: 170, readonly: ro },
      { k: "equipment_id", label: "Machine", type: "select", options: opt.equipment(), w: 150, readonly: ro },
      { k: "description", label: "Description", w: 150, readonly: ro },
      { k: "qty", label: "Qty / hours", type: "number", w: 80, readonly: ro },
      { k: "rate", label: "Recovery rate", type: "number", w: 90, readonly: ro },
      { k: "cost_rate", label: "Our cost rate", show: (r) => r.kind === "material" && r.cost_rate ? fmtMoney(r.cost_rate) : "", num: true },
      { k: "amount", label: "Amount", type: "number", w: 100, readonly: ro },
    ], recs, { blank: { kind: "other" }, readonly: ro, onChange: () => setTimeout(calc, 0) });
    hf.addEventListener("change", calc);
    setTimeout(calc, 0);
    const btns = [];
    if (!ro && right("commercial", "edit")) {
      btns.push({ label: "Save draft", act: async () => {
        const r = await run("sco.bill_save", { header: Object.assign(hf.values(), { order_id: o.id, id: b.id }), items: it.lines(), recoveries: rc.lines() }, "Saved");
        b.id = r.id; return false; } });
      btns.push({ label: "Save and submit", cls: "primary", act: async () => {
        const r = await run("sco.bill_save", { header: Object.assign(hf.values(), { order_id: o.id, id: b.id }), items: it.lines(), recoveries: rc.lines() });
        await run("sco.bill_submit", { id: r.id }, "Submitted for approval"); after(); } });
    }
    if (b.status === "submitted" && right("commercial", "approve")) btns.push({ label: "Approve", cls: "primary", act: async () => { await run("sco.bill_approve", { id: b.id }, "Approved — now with accounts"); after(); } });
    if (b.status === "approved" && right("accounts", "post")) btns.push({ label: "Post (accounts)", cls: "primary", act: async () => {
      const r = await run("sco.bill_post", { id: b.id }, (x) => "Posted as purchase bill " + x.invoice_no); void r; after(); } });
    if ((b.status === "submitted" || b.status === "approved") && (right("commercial", "approve") || right("accounts", "post"))) btns.push({ label: "Return to draft", act: async () => {
      const note = await ask("Return bill", "Why is it returned?", { input: "Reason", required: true, ok: "Return" }); if (!note) return false;
      await run("sco.bill_return", { id: b.id, note }, "Returned"); after(); } });
    if (b.id && ["draft", "submitted"].includes(b.status) && right("commercial", "edit")) btns.push({ label: "Cancel bill", cls: "warn", act: async () => { await run("sco.bill_cancel", { id: b.id }, "Cancelled"); after(); } });
    const flowStage = b.status === "posted" ? "posted" : b.status === "approved" ? "approved" : "review";
    modal((b.no ? "Running bill " + b.no : "New running bill") + " — " + o.no, h("div", {}, flow(flowStage),
      b.note ? h("div", { class: "xnote" }, h("b", {}, "Returned: "), b.note) : null, hf,
      h("h3", {}, "Work done"), it, h("h3", {}, "Deductions"),
      h("p", { class: "hint" }, o.recovery_basis === "fixed" ? "Material is recovered at the agreed rate of the work order." : "Material is recovered at our average cost + " + (o.overhead_pct || 0) + "% overhead. Everything still with the subcontractor is offered; reduce the quantity to recover part of it now."),
      rc, tot), btns);
  }

  PAGES["x/sub"] = async (root) => {
    await meta();
    let filt = { project_id: pidNow() };
    const holder = h("div");
    const load = async () => {
      const [rows, bills] = await Promise.all([run("sco.list", filt), run("sco.bills", filt)]);
      holder.innerHTML = "";
      const waiting = bills.filter((b) => b.status === "submitted").length, toPost = bills.filter((b) => b.status === "approved").length;
      holder.append(h("div", { class: "xt" },
        tile(rows.length, "Work orders"), tile(money(rows.reduce((a, r) => a + r.value, 0)), "Order value"),
        tile(money(rows.reduce((a, r) => a + r.billed, 0)), "Billed (gross)", "good"),
        tile(money(rows.reduce((a, r) => a + r.with_sub, 0)), "Our material with subcontractors", "warn"),
        tile(waiting + " / " + toPost, "Bills to approve / to post", waiting + toPost ? "warn" : "good")),
        tabs([["Work orders", () => table([{ k: "no", label: "No." }, { k: "pcode", label: "Project" }, { k: "party", label: "Subcontractor" },
          { k: "type_name", label: "Type" }, { k: "title", label: "Scope" }, { k: "value", label: "Value", fmt: "money" },
          { k: "billed", label: "Billed", fmt: "money" }, { label: "% billed", v: (r) => r.value ? pct(r.billed / r.value * 100) : "—" },
          { k: "with_sub", label: "Material with them", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }],
          rows, { name: "work_orders", totals: ["value", "billed", "with_sub"], onRow: (r) => orderPage(r.id, load),
            empty: "No work orders. Use New work order for labour supply, item-rate or back-to-back subcontracts." })],
        ["Running bills", () => table([{ k: "no", label: "Bill" }, { k: "date", label: "Date" }, { k: "order_no", label: "Work order" },
          { k: "party", label: "Subcontractor" }, { k: "gross", label: "Gross", fmt: "money" }, { k: "material_recovery", label: "Material", fmt: "money" },
          { k: "retention", label: "Retention", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "status", label: "Status", fmt: "status" },
          { k: "invoice_no", label: "Purchase bill" }], bills, { name: "subcontract_bills", totals: ["gross", "net"],
            onRow: async (r) => { const o = await run("sco.get", { id: r.order_id }); billDialog(o, r.id, load); } })]]));
    };
    root.append(pageHead("Subcontract work orders", "Labour supply by quantity, item rate with our material and equipment, or back-to-back — with material recovery and running bills.",
      right("commercial", "edit") ? h("button", { class: "btn primary", onclick: () => orderDialog(null, load) }, "New work order") : null));
    root.append(filterBar([{ k: "project_id", label: "Project", type: "select", options: opt.projects() },
      { k: "party_id", label: "Subcontractor", type: "select", options: opt.parties(["subcontractor", "vendor"]) }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────────────── execution plan ───────────────────────── */
  PAGES["x/plan"] = async (root) => {
    const m = await meta();
    if (!pidNow()) { root.append(pageHead("Execution plan"), projectNotice()); return; }
    const pid = pidNow();
    const holder = h("div");
    const load = async () => {
      const d = await run("exec.plan", { project_id: pid });
      holder.innerHTML = "";
      const tot = Object.values(d.summary).reduce((a, x) => a + x, 0) || 1;
      holder.append(h("div", { class: "xt" }, Object.entries(d.summary).map(([k, v]) => tile(money(v), (k === "unplanned" ? "Not planned yet" : label(m.work_modes, k)) + " · " + pct(v / tot * 100), k === "unplanned" ? "grey" : ""))),
        h("div", { class: "xbar" }, Object.entries(d.summary).map(([k, v]) => h("i", { title: label(m.work_modes, k), style: "width:" + (v / tot * 100) + "%;background:" + MODE_COL[k] }))),
        tabs([["Plan by BOQ item", () => table([{ k: "code", label: "Item" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" },
          { k: "qty", label: "Qty", fmt: "qty" }, { label: "Value", fmt: "money", v: (r) => (r.qty || 0) * (r.rate || 0) },
          { label: "How it is executed", v: (r) => h("span", {}, r.modes.map((x) => h("span", { class: "xmode " + x.work_mode, title: label(m.equip_modes, x.equip_mode) },
            fmtN(x.share_pct, 0) + "% " + label(m.work_modes, x.work_mode).split(" (")[0] + (x.order_no ? " · " + x.order_no : ""))),
            r.planned_pct < 99.99 ? h("span", { class: "xmode unplanned" }, fmtN(100 - r.planned_pct, 0) + "% not planned") : null) }],
          d.items, { name: "execution_plan", onRow: right("project", "edit") ? (r) => planDialog(r, load) : null })],
        ["Cost per unit by way of working", modeReport]]));
    };
    const modeReport = async () => {
      const rows = await run("exec.mode_report", { project_id: pid });
      const flat = [];
      rows.forEach((r) => {
        flat.push({ item: r.code + " " + (r.description || "").slice(0, 40), mode: "All", qty: r.executed, unit: r.unit, labour: r.labour, material: r.material,
          equipment: r.equipment, sub: r.modes.reduce((a, x) => a + (x.net_subcontract || 0), 0), total: r.total_cost, unit_cost: r.unit_cost, rate: r.rate, margin: r.margin_pct, bold: true });
        r.modes.forEach((x) => flat.push({ item: "", mode: label(m.work_modes, x.mode), qty: x.qty, unit: r.unit, labour: x.labour, sub: x.net_subcontract,
          unit_cost: x.unit_labour != null ? x.unit_labour : x.unit_subcontract, unit_label: x.unit_labour != null ? "labour / unit" : "subcontract / unit" }));
      });
      return h("div", {}, h("p", { class: "hint" }, "Executed quantity comes from approved measurements and DPRs; subcontract quantity from approved and posted running bills; the rest is direct work. Costs are from the posted ledger by BOQ item. Use the unit costs to price the next tender."),
        table([{ k: "item", label: "BOQ item" }, { k: "mode", label: "Way of working" }, { k: "qty", label: "Executed", fmt: "qty" }, { k: "unit", label: "Unit" },
          { k: "labour", label: "Direct labour", fmt: "money" }, { k: "material", label: "Material", fmt: "money" }, { k: "equipment", label: "Equipment", fmt: "money" },
          { k: "sub", label: "Subcontract (net)", fmt: "money" }, { k: "total", label: "Total cost", fmt: "money" },
          { label: "Cost per unit", v: (r) => r.unit_cost == null ? "" : h("span", { title: r.unit_label || "" }, fmtMoney(r.unit_cost)) },
          { k: "rate", label: "BOQ rate", fmt: "money" }, { label: "Margin", v: (r) => r.margin == null ? "" : h("b", { class: r.margin < 0 ? "xr" : "xg" }, pct(r.margin)) }],
        flat, { name: "cost_by_mode", rowClass: (r) => r.bold ? "strong" : "" }));
    };
    root.append(pageHead("Execution plan", "How each BOQ item is executed in this project — several ways can share one item. Approved work orders are added here by themselves."));
    root.append(holder);
    await load();
  };

  function planDialog(item, after) {
    const m = META;
    const le = lineEditor([
      { k: "work_mode", label: "Way of working", type: "select", options: m.work_modes, w: 260 },
      { k: "share_pct", label: "Share %", type: "number", w: 80 },
      { k: "equip_mode", label: "Equipment", type: "select", options: m.equip_modes, w: 170 },
      { k: "remarks", label: "Remarks", w: 160 },
    ], item.modes.length ? item.modes : [{ work_mode: "direct", share_pct: 100, equip_mode: "owned" }], { blank: { share_pct: 0 } });
    modal(item.code + " " + (item.description || "").slice(0, 60), h("div", {}, h("p", { class: "hint" }, "Split the item between ways of working, e.g. 60% direct labour with own equipment and 40% piece-rate gang with rented equipment. Shares cannot add up to more than 100%."), le),
      [{ label: "Save", cls: "primary", act: async () => { await run("exec.plan_save", { project_id: pidNow(), boq_item_id: item.id, rows: le.lines() }, "Saved"); after(); } }]);
  }

  /* ───────────────────────── rental deductions ───────────────────────── */
  PAGES["x/rent"] = async (root) => {
    const m = await meta();
    const holder = h("div");
    const load = async () => {
      const rows = await run("rent.agreements", { refresh: 1 });
      holder.innerHTML = "";
      holder.append(h("div", { class: "xt" }, tile(rows.length, "Hire agreements"),
        tile(money(rows.reduce((a, r) => a + (r.open_deductions || 0), 0)), "To deduct from owners", "warn"),
        tile(money(rows.reduce((a, r) => a + (r.deducted || 0), 0)), "Already deducted", "good")),
      table([{ k: "eq_code", label: "Machine" }, { k: "eq_name", label: "Name" }, { k: "owner", label: "Owner" }, { k: "pcode", label: "Project" },
        { label: "Rate", v: (r) => fmtMoney(r.rate) + " / " + (r.unit || "") },
        { label: "Servicing & repairs", v: (r) => label(m.terms, r.maint_terms || "ours") }, { label: "Fuel", v: (r) => label(m.terms, r.fuel_terms || "ours") },
        { label: "Operator", v: (r) => label(m.terms, r.operator_terms || "ours") },
        { k: "open_deductions", label: "To deduct", fmt: "money" }, { k: "deducted", label: "Deducted", fmt: "money" }],
      rows, { name: "rental_deductions", totals: ["open_deductions", "deducted"], onRow: (r) => rentDialog(r, load), empty: "No hire agreements yet (Equipment › Hired equipment)." }));
    };
    root.append(pageHead("Rental deductions", "Servicing, repairs, spares and fuel we provide on a hired machine come off the owner's monthly hire bill."));
    root.append(h("div", { class: "xnote" }, "Set the terms once per agreement. Every store issue or repair bill booked on that machine then becomes a deduction, added as a minus line the next time the hire bill is made (Equipment › Hired equipment › Bill month). Each deduction credits the cost it was first booked to, so only the net hire stays as our cost."));
    root.append(holder);
    await load();
  };

  async function rentDialog(ag, after) {
    const m = META;
    const d = await run("rent.deductions", { agreement_id: ag.id });
    const st = await run("rent.statement", { agreement_id: ag.id });
    const terms = form([{ k: "maint_terms", label: "Servicing, repairs & spares", type: "select", options: m.terms, noBlank: true },
      { k: "fuel_terms", label: "Fuel & lubricants", type: "select", options: m.terms, noBlank: true },
      { k: "operator_terms", label: "Operator", type: "select", options: m.terms, noBlank: true }],
    { maint_terms: ag.maint_terms || "ours", fuel_terms: ag.fuel_terms || "ours", operator_terms: ag.operator_terms || "ours" });
    const add = form([{ k: "date", label: "Date", type: "date", default: today() }, { k: "kind", label: "Kind", type: "select", noBlank: true,
      options: [["servicing", "Servicing"], ["repair", "Repair"], ["spares", "Spares"], ["fuel", "Fuel"], ["operator", "Operator"], ["other", "Other"]] },
    { k: "amount", label: "Amount", type: "number" }, { k: "account_id", label: "Cost account it was booked to", type: "select", options: opt.accounts(["expense"]) },
    { k: "description", label: "Description", wide: true }], {});
    const body = h("div", {},
      h("h3", {}, "Terms of the agreement"), terms,
      h("h3", {}, "Deductions"),
      table([{ k: "date", label: "Date" }, { k: "kind", label: "Kind" }, { k: "description", label: "From" }, { k: "aname", label: "Credited to" },
        { k: "amount", label: "Amount", fmt: "money" }, { k: "status", label: "Status", fmt: "status" }, { k: "invoice_no", label: "Hire bill" }],
      d.rows, { search: false, totals: ["amount"], onRow: right("equipment", "approve") ? async (r) => {
        if (r.status === "billed") return;
        if (await ask(r.status === "waived" ? "Deduct again" : "Waive this deduction", r.status === "waived" ? "Deduct it on the next hire bill again?" : "Do not deduct this from the owner (we bear the cost)?")) {
          await run("rent.deduction_waive", { id: r.id }, "Saved"); rentDialog(ag, after); } } : null, empty: "No deductions." }),
      d.candidates.length ? h("div", {}, h("h3", {}, "Other costs booked on this machine"),
        h("p", { class: "hint" }, "Not deducted under the current terms. Click one to deduct it anyway."),
        table([{ k: "date", label: "Date" }, { k: "kind", label: "Kind" }, { k: "description", label: "Document" }, { k: "amount", label: "Amount", fmt: "money" }],
          d.candidates, { search: false, onRow: right("equipment", "edit") ? async (x) => { await run("rent.deduction_add", { agreement_id: ag.id, source: x.source, source_id: x.source_id }, "Added"); rentDialog(ag, after); } : null })) : null,
      h("h3", {}, "Add a deduction by hand"), add,
      h("h3", {}, "Statement"),
      table([{ k: "month", label: "Month" }, { k: "billed_units", label: "Units billed", fmt: "qty" }, { k: "gross", label: "Gross hire", fmt: "money" },
        { k: "deductions", label: "Deductions", fmt: "money" }, { k: "net", label: "Net", fmt: "money" }, { k: "invoice_no", label: "Bill" }, { k: "status", label: "Status", fmt: "status" }],
      st.rows, { search: false, totals: ["gross", "deductions", "net"], empty: "No hire bills yet." }));
    const btns = [];
    if (right("equipment", "edit")) {
      btns.push({ label: "Save terms", cls: "primary", act: async () => { await run("rent.terms_save", Object.assign({ id: ag.id }, terms.values()), "Terms saved"); after(); } });
      btns.push({ label: "Add deduction", act: async () => { await run("rent.deduction_add", Object.assign({ agreement_id: ag.id }, add.values()), "Deduction added"); rentDialog(ag, after); } });
    }
    modal("Hired " + (ag.eq_code || "") + " — " + (ag.owner || ""), body, btns);
  }

  /* ───────────────────────── equipment cost per hour ───────────────────────── */
  const BASIS = { hour: "hour", km: "km", day: "day", output: "unit of output" };
  PAGES["x/eqcost"] = async (root) => {
    await meta();
    let filt = { from: today().slice(0, 8) + "01", to: today() };
    const holder = h("div");
    const load = async () => {
      const d = await run("eqc.report", filt);
      holder.innerHTML = "";
      const R = d.rows;
      const hrs = R.reduce((a, r) => a + (r.hours || 0), 0), av = R.reduce((a, r) => a + (r.available_hours || 0), 0);
      holder.append(h("div", { class: "xt" }, tile(R.length, "Own machines"), tile(pct(av ? hrs / av * 100 : null), "Utilisation (worked ÷ available hours)", hrs / av < 0.5 ? "warn" : "good"),
        tile(money(R.reduce((a, r) => a + r.operating, 0)), "Running cost (actual)"), tile(money(R.reduce((a, r) => a + r.emi_paid, 0)), "EMI paid"),
        tile(money(R.reduce((a, r) => a + r.employer_idle_cost, 0)), "Idle cost on employer-delay days", "warn")),
      table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { label: "Per", v: (r) => BASIS[r.basis] || r.basis },
        { k: "units", label: "Units worked", fmt: "qty" }, { label: "Utilisation", v: (r) => pct(r.utilisation_pct) },
        { k: "operating", label: "Running cost", fmt: "money" }, { k: "emi_paid", label: "EMI paid", fmt: "money" }, { k: "down_share", label: "Down payment share", fmt: "money" },
        { k: "cash_per_unit", label: "Cash cost / unit", fmt: "money" }, { k: "economic_per_unit", label: "Economic cost / unit", fmt: "money" },
        { k: "internal_rate", label: "Charged to projects", fmt: "money" }, { k: "market_rate", label: "Market hire", fmt: "money" },
        { label: "Own vs hire", v: (r) => r.own_vs_rent == null ? "—" : h("b", { class: r.own_vs_rent < 0 ? "xr" : "xg" }, fmtMoney(r.own_vs_rent)) },
        { k: "idle_hours", label: "Idle h", fmt: "qty" }, { k: "breakdown_hours", label: "Breakdown h", fmt: "qty" }, { k: "employer_idle_hours", label: "Idle on employer delay h", fmt: "qty" }],
      R, { name: "equipment_cost", totals: ["operating", "emi_paid", "down_share"], onRow: (r) => machineDialog(r.equipment_id, load), empty: "No own machines." }));
    };
    root.append(pageHead("Equipment cost per hour", "Own machines: actual running cost plus financing, per hour, km, day or unit of output — shown two ways."));
    root.append(h("div", { class: "xdu" },
      h("div", { class: "c" }, h("h4", {}, "Cash cost per unit"), h("div", { class: "eq" }, "Running cost actually spent (fuel, lubricants, repairs, spares, operator) + EMI actually paid + down payment ÷ planned life units × units worked. Answers: does the machine pay its way month by month?")),
      h("div", { class: "c" }, h("h4", {}, "Economic cost per unit (use for charging projects)"), h("div", { class: "eq" }, "Running cost + depreciation + only the interest part of the EMI. The principal part repays the machine's price, which depreciation already counts — adding both would charge the machine twice."))));
    root.append(filterBar([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }, { k: "project_id", label: "Project", type: "select", options: opt.projects() }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  async function machineDialog(eid, after) {
    const f = await run("eqf.get", { equipment_id: eid });
    const tr = await run("eqc.trend", { equipment_id: eid });
    const ff = form([{ k: "price", label: "Purchase price", type: "number" }, { k: "down_payment", label: "Down payment", type: "number" },
      { k: "loan_amount", label: "Loan amount", type: "number" }, { k: "lender", label: "Lender" }, { k: "emi", label: "EMI", type: "number" },
      { k: "emi_count", label: "Number of EMIs", type: "number" }, { k: "first_emi_date", label: "First EMI", type: "date" },
      { k: "interest_rate", label: "Interest % a year", type: "number" },
      { k: "basis", label: "Cost per", type: "select", noBlank: true, options: [["hour", "Hour (meter)"], ["km", "Km (vehicles)"], ["day", "Day (gensets, pumps)"], ["output", "Unit of output (crusher, plant)"]] },
      { k: "life_units", label: "Planned working life (in that unit)", type: "number", hint: "e.g. 10,000 hours" }, { k: "output_unit", label: "Output unit (m³, t)" },
      { k: "market_rate", label: "Market hire rate per unit", type: "number" }, { k: "notes", label: "Notes", wide: true }], f);
    const emi = form([{ k: "date", label: "Paid on", type: "date", default: today() }, { k: "amount", label: "Amount", type: "number", default: f.emi || "" },
      { k: "principal", label: "Principal (blank = work it out)", type: "number" }, { k: "bank_account_id", label: "Paid from (sends to accounts to post)", type: "select", options: opt.money() },
      { k: "remarks", label: "Remarks", wide: true }], {});
    const labels = tr.map((x) => x.month.slice(2));
    const body = h("div", {},
      h("div", { class: "xt" }, tile(money(f.paid), "EMIs paid so far"), tile(money(f.loan_left), "Loan left", f.loan_left > 0 ? "warn" : "good"),
        tile(money((f.down_payment || 0) + (f.paid || 0)), "Cash put in so far")),
      h("h3", {}, "Cost per unit, last 12 months"),
      signedChart(labels, [{ name: "Cash cost / unit", color: "#c0392b", values: tr.map((x) => x.cash_per_unit) },
        { name: "Economic cost / unit", color: "#1769aa", values: tr.map((x) => x.economic_per_unit) },
        { name: "Charged to projects", color: "#2f7a4d", values: tr.map((x) => x.units ? (x.internal_rate || null) : null) }], ""),
      table([{ k: "month", label: "Month" }, { k: "units", label: "Units", fmt: "qty" }, { label: "Utilisation", v: (r) => pct(r.utilisation_pct) },
        { k: "operating", label: "Running", fmt: "money" }, { k: "depreciation", label: "Depreciation", fmt: "money" }, { k: "emi_paid", label: "EMI", fmt: "money" },
        { k: "interest", label: "Interest", fmt: "money" }, { k: "cash_per_unit", label: "Cash / unit", fmt: "money" }, { k: "economic_per_unit", label: "Economic / unit", fmt: "money" },
        { k: "earned", label: "Earned", fmt: "money" }], tr, { search: false, name: "machine_trend" }),
      h("h3", {}, "Finance"), ff,
      h("h3", {}, "EMIs paid"),
      table([{ k: "date", label: "Date" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "principal", label: "Principal", fmt: "money" },
        { k: "interest", label: "Interest", fmt: "money" }, { label: "Voucher", v: (r) => r.vno || (r.vstatus === "submitted" ? stamp("waiting_accounts") : "—") }],
      f.emis, { search: false, totals: ["amount", "principal", "interest"], empty: "No EMI recorded." }),
      h("h3", {}, "Record an EMI"), emi);
    const btns = right("equipment", "edit") ? [
      { label: "Save finance", cls: "primary", act: async () => { await run("eqf.save", Object.assign({ equipment_id: eid }, ff.values()), "Saved"); after(); } },
      { label: "Record EMI", act: async () => { await run("eqf.emi_add", Object.assign({ equipment_id: eid }, emi.values()), (r) => "Recorded: principal " + fmtMoney(r.principal) + ", interest " + fmtMoney(r.interest)); machineDialog(eid, after); } }] : [];
    modal(f.equipment.code + " " + f.equipment.name, body, btns);
  }

  /* ───────────────────────── delays by responsibility ───────────────────────── */
  const RCOL = { employer: "good", contractor: "bad", neutral: "grey", concurrent: "warn" };
  PAGES["x/delays"] = async (root) => {
    const m = await meta();
    if (!pidNow()) { root.append(pageHead("Delays by responsibility"), projectNotice()); return; }
    const pid = pidNow();
    const holder = h("div");
    const load = async () => {
      const [s, l] = await Promise.all([run("delay.summary", { project_id: pid }), run("delay.list", { project_id: pid })]);
      holder.innerHTML = "";
      const by = Object.fromEntries(s.by.map((x) => [x.resp, x]));
      holder.append(h("div", { class: "xt" }, m.resp.map(([k, n]) => tile(fmtN(by[k] ? (by[k].event_days || by[k].days) : 0, 1) + " d", n + " · " + fmtN(by[k] ? by[k].hours : 0, 0) + " h on DPRs", RCOL[k]))),
        h("div", { class: "xdu" },
          h("div", { class: "c" }, h("h4", {}, "Claimable from the employer"), h("div", { class: "big xg" }, money(s.claimable_idle_cost + s.prolongation_cost)),
            h("div", { class: "eq" }, "Idle machines on employer-delay days " + money(s.claimable_idle_cost) + " + site overheads " + fmtN(s.employer_days, 1) + " d × " + money(s.indirect_per_day) + ". Supports an extension of time and cost claim (Events & claims).")),
          h("div", { class: "c" }, h("h4", {}, "Liquidated damages exposure"), h("div", { class: "big xr" }, money(s.ld_exposure)),
            h("div", { class: "eq" }, "Own delays " + fmtN(s.own_days, 1) + " d × " + money(s.ld_per_day) + " per day (contract time register). Own causes: breakdowns, material, labour, subcontractors."))),
        tabs([["DPR delays", () => table([{ k: "date", label: "Date" }, { k: "dpr_no", label: "DPR" }, { k: "category", label: "Cause", v: (r) => (r.category || "").replace(/_/g, " ") },
          { k: "hours", label: "Hours", fmt: "qty" }, { k: "activity", label: "Activity" }, { k: "description", label: "Description" },
          { label: "Responsibility", v: (r) => respSelect(r, "dpr", load) }], l.dpr, { name: "dpr_delays", totals: ["hours"] })],
        ["Delay events", () => table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "title", label: "Event" }, { k: "delay_days", label: "Days", fmt: "qty" },
          { k: "eot_claimed", label: "EOT claimed", fmt: "qty" }, { k: "eot_granted", label: "EOT granted", fmt: "qty" }, { k: "cost_impact", label: "Cost", fmt: "money" },
          { label: "Responsibility", v: (r) => respSelect(r, "event", load) }], l.events, { name: "delay_events", totals: ["delay_days", "cost_impact"], empty: "No delay events (Events & claims)." })],
        ["Idle machines on employer delays", () => table([{ k: "code", label: "Machine" }, { k: "h", label: "Idle / standby hours", fmt: "qty" },
          { k: "rate", label: "Rate", fmt: "money" }, { k: "cost", label: "Cost", fmt: "money" }], s.idle_equipment, { search: false, totals: ["cost"], empty: "None recorded on logsheets." })]]));
    };
    root.append(pageHead("Delays by responsibility", "Every DPR delay and delay event is the employer's, ours, neutral or concurrent — so time, claims and damages add up."));
    root.append(h("div", { class: "xnote" }, "Old delays are classified from their cause (drawings, access and instructions → employer; breakdowns, material and labour shortage → own; weather and geology → neutral). Change any of them in the list; delay events also get their excusable and compensable flags from it."));
    root.append(holder);
    await load();
  };
  function respSelect(r, kind, after) {
    const s = h("select", { onchange: async () => { await run("delay.classify", { kind, id: r.id, responsibility: s.value }, "Saved"); after(); },
      disabled: !right("project", "edit") }, (META.resp || []).map(([k, n]) => h("option", { value: k, selected: k === r.resp }, n)));
    s.addEventListener("click", (e) => e.stopPropagation());
    return s;
  }

  /* ───────────────────────── returns ───────────────────────── */
  function signedChart(labels, series, unit) {
    const W = 720, H = 200, P = 40;
    const all = series.flatMap((s) => s.values.filter((v) => v != null));
    if (!all.length) return h("p", { class: "hint" }, "Not enough posted months yet.");
    let max = Math.max(0, ...all), min = Math.min(0, ...all);
    if (max === min) max = min + 1;
    const pad = (max - min) * 0.08; max += pad; if (min < 0) min -= pad;
    const x = (i) => P + (W - 2 * P) * (labels.length > 1 ? i / (labels.length - 1) : 0);
    const y = (v) => H - P - (H - 2 * P) * ((v - min) / (max - min));
    let inner = "";
    for (let g = 0; g <= 4; g++) { const gv = min + (max - min) * g / 4; inner += '<line x1="' + P + '" x2="' + (W - P) + '" y1="' + y(gv) + '" y2="' + y(gv) + '" class="grid"/><text x="2" y="' + (y(gv) + 4) + '" class="ax">' + fmtN(gv, 0) + unit + "</text>"; }
    if (min < 0) inner += '<line x1="' + P + '" x2="' + (W - P) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="#8796a3" stroke-width="1.5"/>';
    const step = Math.max(1, Math.ceil(labels.length / 8));
    labels.forEach((l, i) => { if (i % step === 0 || i === labels.length - 1) inner += '<text x="' + x(i) + '" y="' + (H - 12) + '" class="ax" text-anchor="middle">' + l + "</text>"; });
    series.forEach((s) => {
      const pts = s.values.map((v, i) => (v == null ? null : x(i) + "," + y(v))).filter(Boolean).join(" ");
      inner += '<polyline points="' + pts + '" fill="none" stroke="' + s.color + '" stroke-width="2.5"/>';
      s.values.forEach((v, i) => { if (v != null) inner += '<circle cx="' + x(i) + '" cy="' + y(v) + '" r="3" fill="' + s.color + '"><title>' + labels[i] + ": " + fmtN(v, 1) + unit + "</title></circle>"; });
    });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("class", "chart"); svg.innerHTML = inner;
    return h("div", {}, svg, h("div", { class: "legend" }, series.map((s) => h("span", {}, h("i", { style: "background:" + s.color }), s.name))));
  }
  function dupont(p) {
    return h("div", { class: "c" }, h("h4", {}, p.label + (p.annualised ? " (annualised)" : "")),
      h("div", { class: "big" }, pct(p.roe_pct), h("span", { style: "font-size:13px;font-weight:400" }, " ROE")),
      h("div", { class: "eq" }, "ROA " + pct(p.roa_pct) + " · net profit " + fmtMoney(p.net_profit), h("br"),
        "= margin " + pct(p.net_margin_pct) + " × asset turnover " + fmtN(p.asset_turnover, 2) + " × assets ÷ equity " + fmtN(p.equity_multiplier, 2), h("br"),
        "avg assets " + fmtMoney(p.avg_assets) + " · avg equity " + fmtMoney(p.avg_equity)));
  }
  PAGES["x/returns"] = async (root) => {
    await meta();
    const holder = h("div");
    let filt = { to: today() };
    const load = async () => {
      holder.innerHTML = "";
      let comp = null;
      try { comp = await api("ret.company", filt); } catch (e) { comp = null; }
      const as = await run("ret.assets", { to: filt.to });
      if (comp) {
        holder.append(h("h3", {}, "Company"), h("div", { class: "xdu" }, dupont(comp.fy), dupont(comp.ttm), dupont(comp.last_fy)),
          h("h4", { style: "margin:4px 0" }, "Rolling 12 months, month by month"),
          signedChart(comp.trend.map((x) => x.month.slice(2)), [{ name: "ROE %", color: "#1769aa", values: comp.trend.map((x) => x.roe_pct) },
            { name: "ROA %", color: "#2f7a4d", values: comp.trend.map((x) => x.roa_pct) }, { name: "Net margin %", color: "#b7791f", values: comp.trend.map((x) => x.net_margin_pct) }], "%"),
          h("p", { class: "hint" }, "Internal equipment hire is netted out of revenue and cost. Equity = assets − liabilities from the posted ledger (this year's profit included). Where ROE moved, the three factors say why: price and cost (margin), use of assets (turnover) or borrowing (assets ÷ equity)."));
      }
      holder.append(h("h3", {}, "Own machines — return on book value (" + as.from + " to " + as.to + ")"),
        table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "hours", label: "Hours", fmt: "qty" }, { label: "Utilisation", v: (r) => pct(r.utilisation_pct) },
          { k: "earned", label: "Earned (hire)", fmt: "money" }, { k: "operating", label: "Running cost", fmt: "money" }, { k: "depreciation", label: "Depreciation", fmt: "money" },
          { k: "contribution", label: "Contribution", fmt: "money" }, { k: "avg_nbv", label: "Avg book value", fmt: "money" },
          { label: "Return % a year", v: (r) => r.roa_pct == null ? "—" : h("b", { class: r.roa_pct < 0 ? "xr" : "xg" }, pct(r.roa_pct)) },
          { k: "cash_invested", label: "Cash put in", fmt: "money" }, { label: "Cash back", v: (r) => r.payback_pct == null ? fmtMoney(r.cash_back) : fmtMoney(r.cash_back) + " (" + pct(r.payback_pct) + ")" }],
        as.machines, { name: "machine_returns", totals: ["earned", "operating", "depreciation", "contribution"], onRow: (r) => machineDialog(r.equipment_id, load) }),
        h("h3", {}, "Small assets — mixers, tools, scaffolding, shuttering"),
        table([{ k: "code", label: "Pool" }, { k: "name", label: "Name" }, { k: "owned", label: "Owned", fmt: "qty" }, { k: "deployed_now", label: "At sites now", fmt: "qty" },
          { label: "Utilisation", v: (r) => pct(r.utilisation_pct) }, { k: "earned", label: "Hire earned", fmt: "money" }, { k: "depreciation", label: "Wear (depreciation)", fmt: "money" },
          { k: "losses", label: "Losses & damage", fmt: "money" }, { k: "contribution", label: "Contribution", fmt: "money" }, { k: "nbv", label: "Book value", fmt: "money" },
          { label: "Return % a year", v: (r) => r.roa_pct == null ? "—" : h("b", { class: r.roa_pct < 0 ? "xr" : "xg" }, pct(r.roa_pct)) }],
        as.pools, { name: "pool_returns", totals: ["earned", "contribution"], empty: "No small-asset pools yet (Small assets)." }));
    };
    root.append(pageHead("Returns (ROA / ROE)", "Return on assets and equity for the company, every own machine and every pool of small assets."));
    root.append(filterBar([{ k: "to", label: "As at", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────────────── small-asset pools ───────────────────────── */
  PAGES["x/pools"] = async (root) => {
    const m = await meta();
    const holder = h("div");
    const load = async () => {
      const [rows, rep] = await Promise.all([run("sa.pools", {}), run("sa.report", {})]);
      const rp = Object.fromEntries(rep.rows.map((x) => [x.pool_id, x]));
      holder.innerHTML = "";
      holder.append(h("div", { class: "xt" }, tile(rows.length, "Pools"), tile(money(rows.reduce((a, r) => a + (r.cost || 0), 0)), "Cost"),
        tile(money(rep.rows.reduce((a, r) => a + r.earned, 0)), "Hire earned this FY", "good"), tile(money(rep.rows.reduce((a, r) => a + r.losses, 0)), "Losses & damage", "bad")),
      table([{ k: "code", label: "Code" }, { k: "name", label: "Name" }, { label: "Class", v: (r) => label(m.sa_classes, r.class) }, { k: "unit", label: "Unit" },
        { k: "owned", label: "Owned", fmt: "qty" }, { k: "in_yard", label: "In yard", fmt: "qty" },
        { label: "At projects", v: (r) => Object.entries(r.deployed).map(([p, q]) => nm.pcode(p) + " " + fmtQty(q)).join(", ") },
        { label: "Hire rate", v: (r) => fmtMoney(r.rate) + " / unit / " + r.rate_basis }, { label: "Utilisation", v: (r) => pct((rp[r.id] || {}).utilisation_pct) },
        { label: "Return % a year", v: (r) => pct((rp[r.id] || {}).roa_pct) }],
      rows, { name: "small_assets", onRow: (r) => poolDialog(r, load), empty: "No pools yet. Add mixers, vibrators, tools, scaffolding, shuttering or props as quantity pools." }));
    };
    const runBtn = right("assets", "edit") ? h("button", { class: "btn", onclick: async () => {
      const mo = prompt("Charge projects for which month (YYYY-MM)?", mos()); if (!mo) return;
      const r = await run("sa.run", { month: mo }, (x) => x.length + " charges sent to accounts"); void r; load(); } }, "Monthly hire charge") : null;
    root.append(pageHead("Small assets", "Mixers, tools, scaffolding, shuttering and props as quantity pools: deployed by project, charged by the day or month, with losses and return.",
      runBtn, right("assets", "edit") ? h("button", { class: "btn primary", onclick: () => poolDialog(null, load) }, "New pool") : null));
    root.append(holder);
    await load();
  };

  function poolDialog(p, after) {
    const m = META;
    const f = form([{ k: "code", label: "Code", req: true }, { k: "name", label: "Name", req: true, wide: true },
      { k: "class", label: "Class", type: "select", options: m.sa_classes, noBlank: true }, { k: "unit", label: "Unit", req: true, ph: "no., set, m²" },
      { k: "qty", label: "Quantity owned", type: "number" }, { k: "cost", label: "Total cost", type: "number" }, { k: "purchase_date", label: "Bought on", type: "date" },
      { k: "life_months", label: "Life (months)", type: "number" }, { k: "residual_pct", label: "Residual %", type: "number" },
      { k: "rate", label: "Hire rate per unit", type: "number" }, { k: "rate_basis", label: "per", type: "select", noBlank: true, options: [["day", "day"], ["month", "month"]] },
      { k: "notes", label: "Notes", wide: true }], p || { class: "scaffolding", rate_basis: "day", life_months: 36 });
    const mv = form([{ k: "kind", label: "Movement", type: "select", noBlank: true, options: [["deploy", "Send to project"], ["return", "Back to yard"], ["loss", "Lost at project"], ["damage", "Damaged (value)"], ["buy", "Bought more"], ["dispose", "Scrapped / sold"]] },
      { k: "project_id", label: "Project", type: "select", options: opt.projects() }, { k: "date", label: "Date", type: "date", default: today() },
      { k: "qty", label: "Quantity", type: "number" }, { k: "value", label: "Value (losses, purchases)", type: "number" }, { k: "remarks", label: "Remarks", wide: true }], {});
    const btns = [];
    if (right("assets", "edit")) {
      btns.push({ label: "Save pool", cls: "primary", act: async () => { await run("sa.save", Object.assign({ id: p && p.id }, f.values()), "Saved"); after(); } });
      if (p) btns.push({ label: "Record movement", act: async () => { await run("sa.move", Object.assign({ pool_id: p.id }, mv.values()), "Recorded"); after(); } });
    }
    modal(p ? p.code + " " + p.name : "New small-asset pool", h("div", {}, f, p ? h("div", {}, h("h3", {}, "Movement"), mv) : null), btns);
  }

  /* ───────────────────────── menus (classic and workspace) ───────────────────────── */
  const ADD = [
    // group, after, [path, label, module]
    ["Finance & Accounts", "acc/vouchers", ["x/queue", "Accounts posting queue", "accounts"]],
    ["Finance & Accounts", "acc/cash", ["x/returns", "Returns (ROA / ROE)", "accounts"]],
    ["Central Operations", "eq/hire", ["x/rent", "Rental deductions", "equipment"]],
    ["Central Operations", "x/rent", ["x/eqcost", "Equipment cost per hour", "equipment"]],
    ["Central Operations", "as/dep", ["x/pools", "Small assets (scaffolding, tools)", "assets"]],
    ["Projects", "c/contracts", ["x/sub", "Subcontract work orders", "commercial"]],
    ["Projects", "x/sub", ["x/plan", "Execution plan", "project"]],
    ["Projects", "x/plan", ["x/delays", "Delays by responsibility", "project"]],
    ["Cost & Commercial", "c/contracts", ["x/sub", "Subcontract work orders", "commercial"]],
    ["Cost & Commercial", "x/sub", ["x/plan", "Execution plan", "project"]],
    ["Cost & Commercial", "p/events", ["x/delays", "Delays by responsibility", "project"]],
    ["Cost & Commercial", "acc/budget", ["x/queue", "Waiting for accounts", null]],
    ["Resources", "eq/kpi", ["x/eqcost", "Equipment cost per hour", "equipment"]],
    ["Resources", "x/eqcost", ["x/rent", "Rental deductions", "equipment"]],
  ];
  function inject() {
    if (typeof MENU === "undefined") return;
    ADD.forEach(([group, after, item]) => {
      const g = MENU.find((x) => x[0] === group);
      if (!g || g[2].some((y) => y[0] === item[0])) return;
      const i = g[2].findIndex((y) => y[0] === after);
      g[2].splice(i >= 0 ? i + 1 : g[2].length, 0, item);
    });
  }
  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    if (typeof window.renderNav === "function" && !window.renderNav._bco221) {
      const orig = window.renderNav;
      const rn = function () { try { inject(); } catch (e) { /* ignore */ } return orig.apply(this, arguments); };
      rn._bco221 = true;
      window.renderNav = rn;
      try { renderNav = rn; } catch (e) { /* ignore */ } // eslint-disable-line no-global-assign
    }
  });

  /* What's new */
  function whatsNew() {
    if (LSg("bco_seen_" + VER, "")) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_" + VER, "1");
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:580px" },
      h("p", {}, "One project, several ways of working — and costs reach the books only after approval."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("Accounts posting queue.", "DPR labour and machine charges, fuel and spares to machines, internal hire, service and hire bills now wait: the manager approves, accounts checks the coding and posts. Switch any kind back to direct posting."),
        li("Subcontract work orders.", "Labour supply by quantity, item rate with our material and equipment, or back-to-back. Material issued to the subcontractor is held until it is recovered in their running bill, at our bill rate plus overhead or one agreed rate."),
        li("Execution plan.", "Split each BOQ item between direct labour and subcontracts, and compare the cost per unit of each way of working."),
        li("Rental deductions.", "Servicing, repairs, spares and fuel we give a hired machine come off the owner's hire bill."),
        li("Equipment cost per hour.", "Down payment, loan and EMIs per machine; cash cost and economic cost per hour, km, day or output; utilisation and idle time."),
        li("Delays by responsibility.", "Employer, own, neutral or concurrent — claimable idle cost and LD exposure."),
        li("Returns.", "ROA and ROE with the DuPont split, return per machine, and small-asset pools (scaffolding, shuttering, mixers, tools).")),
      h("p", { class: "hint" }, "Nothing already posted changes. Accounts can find the switches under Accounts posting queue › Which costs wait for accounts.")),
    [{ label: "Open the posting queue", cls: "primary", act: () => { location.hash = "#/x/queue"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 3600); } }, 900);
})();
