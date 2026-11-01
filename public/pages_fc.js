/* BuildCore 2.26 — billing, receivables, payables and payment control.
   New tabs only; the menu, module names and groups are unchanged:
     Commercial › IPCs ............... Billing pipeline & collections
     Accounts › Ageing ............... Receivables: five buckets · Collection actions · Payables register
     Accounts › Payments & receipts .. Payment requests · Payment plan
     Accounts › Integrity checks ..... Financial data checks
   Payments are still made by the existing payment engine; a request only decides who may pay what, and when. */
(function () {
  "use strict";
  if (window.__bcoFc) return;
  window.__bcoFc = true;

  const css = h("style", {}, ".fc-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:0 0 12px}" +
    ".fc-card{border:1px solid #dde3ea;border-radius:8px;padding:8px 10px;background:#fff}.fc-card b{display:block;font-size:15px;margin-top:2px}" +
    ".fc-card small{color:#667}.fc-card.bad{border-color:#f2b8b5;background:#fdf3f2}.fc-card.est{background:#f7f9fb;border-style:dashed}" +
    ".fc-card.ok{border-color:#b7dfc3;background:#f1f9f3}.fc-note{padding:8px 12px;border-radius:6px;margin:0 0 10px;background:#fff7e6;border:1px solid #f0d9a8}" +
    ".fc-note.ok{background:#eaf6ee;border-color:#b7dfc3}.fc-note.bad{background:#fdecea;border-color:#f2b8b5}.fc-late{color:#b42318;font-weight:600}" +
    ".stamp.st-prepared,.stamp.st-requested{background:#eef1f6;color:#333}.stamp.st-under_review,.stamp.st-docs_verified,.stamp.st-accounts_verified,.stamp.st-cash_reviewed{background:#e6f0fb;color:#1b4f86}" +
    ".stamp.st-part_paid{background:#fff1d6;color:#8a5300}.stamp.st-paid,.stamp.st-reconciled{background:#e3f4e8;color:#1e6b34}" +
    ".stamp.st-returned{background:#fff1d6;color:#8a5300}.stamp.st-rejected,.stamp.st-overdue,.stamp.st-error{background:#fde2e1;color:#a01d16}" +
    ".stamp.st-warning{background:#fff1d6;color:#8a5300}.stamp.st-ok{background:#e3f4e8;color:#1e6b34}.fc-k{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}");
  document.head.append(css);

  let META = null;
  const meta = async (fresh) => { if (!META || fresh) META = await api("fc.meta", {}); return META; };
  const money = (n) => (n == null || n === "" ? "" : fmtMoney(n));
  const card = (label, value, sub, cls) => h("div", { class: "fc-card " + (cls || "") }, h("small", {}, label), h("b", {}, value), sub ? h("small", {}, sub) : "");
  const note = (t, cls) => h("div", { class: "fc-note " + (cls || "") }, t);
  const late = (n, word) => (n > 0 ? h("span", { class: "fc-late" }, n + " d " + (word || "late")) : "");
  const projOpts = () => (S.L.projects || []).map((p) => [p.id, p.code + " " + p.name]);
  const projName = (id) => (id ? nm.project(id) || "#" + id : "Company");
  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const OPEN = ["requested", "docs_verified", "accounts_verified", "cash_reviewed", "approved", "returned"];
  const ACTION_LABEL = { verify_docs: "Verify documents", verify_accounts: "Verify accounts", review_cash: "Cash reviewed", approve: "Approve",
    pay: "Pay now", link: "Link payment already made", return: "Return for correction", reject: "Reject", cancel: "Cancel request", resubmit: "Send again", edit: "Edit" };

  /* ═════════════ Commercial › IPCs: billing pipeline & collections ═════════════ */
  async function pipelineTab() {
    if (!S.project) return projectNotice();
    const box = h("div");
    const load = async () => {
      const [m, d] = await Promise.all([meta(), api("fc.ipc_board", { project_id: S.project })]);
      box.innerHTML = "";
      box.append(h("div", { class: "fc-strip" }, d.summary.map((s) => card(s.label, money(s.amount), s.estimate ? "estimate at BOQ rates" : s.count + " IPC" + (s.count === 1 ? "" : "s"),
        s.estimate ? "est" : s.key === "overdue" && s.amount > 0 ? "bad" : s.key === "paid" ? "ok" : ""))));
      box.append(h("p", { class: "hint" }, "Contract terms: certification within " + d.terms.cert_days + " days of submission, payment within " + d.terms.pay_days +
        " days of certification (the invoice due date follows the client's credit days). The first two cards are estimates for planning collections; only a certified IPC is billing."));
      const cols = [{ k: "no", label: "IPC" }, { k: "period_to", label: "Period to" }, { label: "Stage", v: (r) => stamp(r.stage) },
        { k: "claimed_net", label: "Claimed (net)", fmt: "money" }, { label: "Outstanding", fmt: "money", v: (r) => r.outstanding }, { label: "Submitted", v: (r) => r.submitted_at || (r.status !== "draft" ? "not recorded" : "") },
        { label: "Certification due", v: (r) => r.cert_due ? h("span", {}, r.cert_due, " ", late(r.cert_overdue_days)) : "" }, { k: "certified_at", label: "Certified" },
        { label: "Payment due", v: (r) => r.due_date ? h("span", {}, r.due_date, " ", late(r.pay_overdue_days, "overdue")) : "" }, { k: "expected_pay_date", label: "Expected" },
        { label: "Responsible", v: (r) => r.responsible || h("span", { class: "muted" }, "Not assigned") },
        { label: "Next action", v: (r) => [r.next_action || "", r.next_action_date ? " (" + r.next_action_date + ")" : ""].join("") }];
      box.append(h("h3", {}, "IPCs"), table(cols, d.ipcs, { name: "ipc_pipeline", empty: "No IPCs on this project yet.", onRow: (r) => ipcDrawer(r.id, m, load) }));
      if (d.unbilled.rows.length) {
        box.append(h("h3", {}, "Work not yet billed (estimate)"), table([{ k: "code", label: "BOQ" }, { k: "description", label: "Item" }, { k: "unit", label: "Unit" }, { k: "rate", label: "Rate", fmt: "money" },
          { k: "executed", label: "Executed", fmt: "qty" }, { k: "measured", label: "Measured (verified)", fmt: "qty" }, { k: "billed", label: "Billed", fmt: "qty" }, { k: "in_draft", label: "In draft IPC", fmt: "qty" },
          { k: "unmeasured_value", label: "Not measured", fmt: "money" }, { k: "unbilled_value", label: "Measured, not billed", fmt: "money" }], d.unbilled.rows, { name: "unbilled", totals: ["unmeasured_value", "unbilled_value"] }));
      }
    };
    await load();
    return box;
  }

  async function ipcDrawer(id, m, reload) {
    const d = await run("fc.ipc_detail", { id });
    const canEdit = m.rights.commercial_edit || m.rights.accounts_edit;
    const f = form([{ k: "responsible", label: "Responsible person" }, { k: "next_action", label: "Next action", wide: true }, { k: "next_action_date", label: "Next action by", type: "date" },
      { k: "review_at", label: "Under review since", type: "date", hide: d.status !== "submitted" }, { k: "review_by", label: "Reviewed by (consultant / engineer)", hide: d.status !== "submitted" },
      { k: "client_comments", label: "Client / consultant comments", type: "textarea", wide: true }, { k: "expected_pay_date", label: "Expected payment date (blank = invoice due date)", type: "date", hide: d.status !== "certified" },
      { k: "delay_reason", label: "Reason for delay", type: "textarea", wide: true }], Object.assign({}, d, { expected_pay_date: d.expected_set || "" }));
    if (!canEdit) f.querySelectorAll("input,textarea,select").forEach((x) => { x.disabled = true; });
    const noteIn = h("textarea", { placeholder: "Note: call, letter, meeting, reply received…" });
    const body = h("div", {},
      kv([["Stage", stamp(d.stage)], ["Project", nm.project(d.project_id)], ["Client", nm.party(d.party_id)], ["Claimed net", money(d.claimed_net)],
        d.invoice_no ? ["Invoice", d.invoice_no + " · payable " + money(d.payable) + " · received " + money(d.paid) + " · outstanding " + money(d.outstanding)] : null,
        d.cert_due ? ["Certification due", d.cert_due + (d.cert_overdue_days ? " (" + d.cert_overdue_days + " days late)" : "")] : null,
        d.due_date ? ["Payment due", d.due_date + (d.pay_overdue_days ? " (" + d.pay_overdue_days + " days overdue)" : "")] : null]),
      h("h4", {}, "Tracking"), f,
      canEdit ? h("div", {}, h("h4", {}, "Add a note"), noteIn) : null,
      d.receipts.length ? h("div", {}, h("h4", {}, "Receipts"), table([{ k: "date", label: "Date" }, { k: "no", label: "Receipt" }, { k: "amount", label: "Amount", fmt: "money" }], d.receipts, { search: false, export: false })) : null,
      h("h4", {}, "History"), table([{ label: "When", v: (r) => (r.ts || "").replace("T", " ").slice(0, 16) }, { k: "user_name", label: "By" }, { k: "kind", label: "What" }, { k: "text", label: "Detail" }], d.log, { search: false, export: false, empty: "Nothing recorded yet." }));
    drawer("IPC " + d.no, body, canEdit ? [
      { label: "Save tracking", cls: "primary", act: async () => { await run("fc.ipc_update", Object.assign({ id }, f.values()), "Saved"); reload && reload(); } },
      { label: "Add note", keep: true, act: async () => { if (!noteIn.value.trim()) { toast("Write the note first.", "err"); return false; } await run("fc.ipc_note", { id, text: noteIn.value }, "Note added"); noteIn.value = ""; } }] : []);
  }

  /* ═════════════ Accounts › Ageing: receivables in five buckets ═════════════ */
  let recvFilter = { project_id: "", as_of: "" };
  async function receivablesTab() {
    const box = h("div");
    const out = h("div");
    const load = async () => {
      const d = await api("fc.receivables", { project_id: recvFilter.project_id || null, as_of: recvFilter.as_of || null });
      out.innerHTML = "";
      const t = d.totals;
      out.append(h("div", { class: "fc-strip" },
        card("1 · Work done, not billed", money(t.unmeasured + t.unbilled + t.in_draft), "estimate at BOQ rates", "est"),
        card("2 · Submitted, awaiting certification", money(t.submitted)),
        card("3 · Certified, not yet due", money(t.not_due)),
        card("4 · Certified and overdue", money(t.overdue), "", t.overdue > 0 ? "bad" : ""),
        card("5 · Retention held", money(t.retention))));
      const cols = [{ label: "Project", v: (r) => h("span", { title: r.name }, r.code) },
        { label: "Not measured", fmt: "money", v: (r) => r.unmeasured }, { label: "Measured, not billed", fmt: "money", v: (r) => r.unbilled + r.in_draft },
        { k: "submitted", label: "Submitted", fmt: "money" }, { label: "Certification late", fmt: "money", v: (r) => r.cert_overdue },
        { k: "not_due", label: "Certified, not due", fmt: "money" }, { label: "Overdue 1-30", fmt: "money", v: (r) => r.ages.a30 }, { label: "31-60", fmt: "money", v: (r) => r.ages.a60 },
        { label: "61-90", fmt: "money", v: (r) => r.ages.a90 }, { label: "90+", fmt: "money", v: (r) => r.ages.a90p },
        { label: "Retention held", fmt: "money", v: (r) => r.retention.held }, { label: "Eligible now", fmt: "money", v: (r) => r.retention.eligible_now },
        { label: "Client advance", fmt: "money", v: (r) => r.client_advance }];
      out.append(table(cols, d.rows, { name: "receivables_5_buckets", title: "Receivables in five buckets", extra: [["As of", d.as_of]], onRow: (r) => recvDrawer(r, d.as_of), empty: "No receivables." }));
      out.append(h("p", { class: "hint" }, "Buckets 3 and 4 are the open sales invoices and agree with the debtors account. Retention release dates come from each project's completion date and defects liability period (Projects › contract terms); the release itself follows the certificates."));
    };
    box.append(filterBar([{ k: "project_id", label: "Project", type: "select", options: projOpts, blank: "All projects" }, { k: "as_of", label: "As of", type: "date" }], recvFilter, (v) => { recvFilter = v; load(); }), out);
    await load();
    return box;
  }
  function recvDrawer(r, asOf) {
    const ri = r.retention;
    drawer(r.code + " receivables", h("div", {},
      kv([["Not measured (estimate)", money(r.unmeasured)], ["Measured, not billed (estimate)", money(r.unbilled)], ["In draft IPCs", money(r.in_draft)],
        ["Submitted, awaiting certification", money(r.submitted) + (r.cert_overdue ? " (" + money(r.cert_overdue) + " past the certification period)" : "")],
        ["Certified, not due", money(r.not_due)], ["Overdue", money(r.overdue)], ["Retention held", money(ri.held)],
        ["Retention release", ri.completion_date ? ri.first_release_pct + "% at completion (" + ri.completion_date + "), the rest after the defects period (" + (ri.final_date || "-") + ")" : ri.note],
        ["Client advance outstanding", money(r.client_advance)]]),
      h("h4", {}, "Open invoices as of " + asOf),
      table([{ k: "no", label: "Invoice" }, { label: "Client", v: (x) => nm.party(x.party_id) }, { k: "date", label: "Date" }, { k: "due_date", label: "Due" }, { label: "Overdue", v: (x) => late(x.days_overdue, "") }, { k: "balance", label: "Balance", fmt: "money" }], r.invoices, { search: false, empty: "No open invoices." })), []);
  }

  /* ═════════════ Accounts › Ageing: collection actions ═════════════ */
  async function collectionsTab() {
    const box = h("div");
    const m = await meta();
    const load = async () => {
      const d = await api("fc.collections", { project_id: recvFilter.project_id || null });
      box.innerHTML = "";
      box.append(filterBar([{ k: "project_id", label: "Project", type: "select", options: projOpts, blank: "All projects" }], recvFilter, (v) => { recvFilter = Object.assign(recvFilter, v); load(); }));
      box.append(h("div", { class: "fc-strip" }, card("Actions", String(d.rows.length)), card("Past their target date", String(d.late), "", d.late ? "bad" : "ok"), card("Money behind the actions", money(d.total), "excluding work not measured")));
      box.append(table([{ label: "Action", v: (r) => h("b", {}, r.label_full) }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { label: "Client", v: (r) => r.party_id ? nm.party(r.party_id) : "" },
        { k: "amount", label: "Amount", fmt: "money" }, { k: "target_date", label: "Target" }, { label: "Late", v: (r) => late(r.late_days) }, { k: "responsible", label: "Responsible" },
        { label: "Last follow-up", v: (r) => r.last_follow ? (r.last_follow.ts || "").slice(0, 10) + " " + r.last_follow.note : "" },
        { label: "Promised", v: (r) => r.promised_date ? r.promised_date + (r.promised_amount ? " · " + money(r.promised_amount) : "") : "" }, { k: "detail", label: "Detail" }],
      d.rows, { name: "collection_actions", empty: "Nothing to collect.", rowClass: (r) => (r.late_days ? "bad" : ""), onRow: (r) => followModal(r, m, load) }));
    };
    await load();
    return box;
  }
  async function followModal(r, m, reload) {
    const hist = await api("fc.follow_list", { ref_type: r.ref_type, ref_id: r.ref_id });
    const canEdit = m.rights.accounts_edit || m.rights.commercial_edit;
    const f = form([{ k: "note", label: "What was done or agreed", type: "textarea", wide: true, req: true }, { k: "next_date", label: "Next follow-up", type: "date" },
      { k: "promised_date", label: "Payment promised for", type: "date" }, { k: "promised_amount", label: "Amount promised", type: "number" }], {});
    modal(r.label_full, h("div", {}, kv([["Project", nm.project(r.project_id)], ["Amount", money(r.amount)], ["Target", r.target_date || ""], ["Responsible", r.responsible], ["Detail", r.detail]]),
      canEdit ? f : null, h("h4", {}, "Follow-ups"),
      table([{ label: "When", v: (x) => (x.ts || "").slice(0, 16).replace("T", " ") }, { k: "user_name", label: "By" }, { k: "note", label: "Note" }, { k: "next_date", label: "Next" }, { k: "promised_date", label: "Promised" }, { k: "promised_amount", label: "Amount", fmt: "money" }], hist, { search: false, export: false, empty: "None yet." })),
    canEdit ? [{ label: "Save follow-up", cls: "primary", act: async () => { await run("fc.follow_save", Object.assign({ ref_type: r.ref_type, ref_id: r.ref_id, project_id: r.project_id, party_id: r.party_id }, f.values()), "Saved"); reload(); } },
      r.ref_type === "ipc" ? { label: "Open IPC tracking", act: async () => { ipcDrawer(r.ref_id, m, reload); } } : null] : []);
  }

  /* ═════════════ Accounts › Ageing: payables register ═════════════ */
  let payFilter = { project_id: "", category: "" };
  async function payablesTab() {
    const box = h("div");
    const m = await meta();
    const out = h("div");
    const load = async () => {
      const d = await api("fc.payables", { project_id: payFilter.project_id || null });
      out.innerHTML = "";
      out.append(h("div", { class: "fc-strip" }, d.buckets.map((b) => card(b.label, money(b.amount), "", b.key === "overdue" && b.amount > 0 ? "bad" : ""))));
      out.append(h("div", { class: "fc-k" }, d.by_category.map((x) => h("span", { class: "stamp" }, x.label + ": " + money(x.amount)))));
      const rows = d.rows.filter((r) => !payFilter.category || r.category === payFilter.category);
      const canReq = m.rights.payreq.create;
      out.append(table([{ label: "Type", v: (r) => (m.categories.find((c) => c[0] === r.category) || [0, r.category])[1] }, { k: "party_name", label: "Pay to" }, { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "Company" },
        { k: "ref_no", label: "Reference" }, { k: "party_ref", label: "Their bill" }, { k: "due_date", label: "Due" }, { label: "Overdue", v: (r) => late(r.days_overdue, "") },
        { k: "amount", label: "Amount", fmt: "money" }, { k: "requested", label: "In requests", fmt: "money" }, { k: "note", label: "Note" },
        { label: "", v: (r) => canReq && r.payable_now && r.unrequested > 0.5 ? h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); payreqForm(fromPayable(r), m, () => load()); } }, "Request payment") : "" }],
      rows, { name: "payables_register", totals: ["amount", "requested"], empty: "Nothing payable." }));
      if (!d.company_items) out.append(h("p", { class: "hint" }, "VAT, TDS and loan instalments are company-level; they show when all projects are selected, for people who see every project."));
      if (d.retention_payable.length || d.commitments.length) out.append(h("h3", {}, "For information (not yet payable)"));
      if (d.retention_payable.length) out.append(table([{ label: "Project", v: (r) => nm.project(r.project_id) }, { k: "amount", label: "Retention held from subcontractors and suppliers", fmt: "money" }], d.retention_payable, { search: false, export: false }));
      if (d.commitments.length) out.append(table([{ k: "no", label: "Purchase order" }, { k: "party_name", label: "Supplier" }, { label: "Project", v: (r) => nm.pcode(r.project_id) }, { k: "delivery_date", label: "Delivery" }, { k: "payment_terms", label: "Payment terms" }, { k: "pending_value", label: "Still to receive", fmt: "money" }], d.commitments, { name: "po_commitments", totals: ["pending_value"] }));
    };
    box.append(filterBar([{ k: "project_id", label: "Project", type: "select", options: projOpts, blank: "All projects" },
      { k: "category", label: "Type", type: "select", options: () => (META ? META.categories : []), blank: "All" }], payFilter, (v) => { payFilter = v; load(); }), out);
    await load();
    return box;
  }
  const fromPayable = (r) => ({ category: r.category === "equipment" || r.category === "subcontractor" || r.category === "supplier" ? r.category : r.category,
    party_id: r.party_id, project_id: r.project_id, invoice_id: r.ref_type === "invoice" ? r.ref_id : null, amount: r.unrequested, due_date: r.due_date,
    proposed_date: r.due_date && r.due_date > today() ? r.due_date : today(), obligation: r.obligation, ref: r.ref_type === "invoice" ? null : r.key,
    note: r.ref_type === "invoice" ? "" : r.ref_no, _label: r.ref_no });

  /* ═════════════ Accounts › Payments & receipts: payment requests ═════════════ */
  let reqStage = "open";
  async function requestsTab() {
    const box = h("div");
    const m = await meta();
    const load = async () => {
      const rows = await api("fc.payreq_list", { stage: reqStage });
      box.innerHTML = "";
      const sel = h("select", { style: "width:auto", onchange: () => { reqStage = sel.value; load(); } },
        [["open", "Open requests"]].concat(m.stages).concat([["all", "All"]]).map(([k, l]) => h("option", { value: k, selected: k === reqStage }, l)));
      box.append(h("div", { class: "bar" }, sel, h("div", { class: "grow" }),
        m.rights.payreq.create ? h("button", { class: "btn primary", onclick: () => payreqForm({ proposed_date: today(), obligation: "normal", category: "supplier" }, m, load) }, "New payment request") : null));
      box.append(h("p", { class: "hint" }, "Chain: " + ["docs", "accounts", "cash", "approve", "pay"].map((k) => m.step_label[k] + " (" + m.steps[k].join(" ") + ")").join(" → ") +
        ". The approver is never the person who asked. Paying uses the normal payment, so TDS, the cash limit and the books work as before."));
      box.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { label: "Pay to", v: (r) => r.party_id ? nm.party(r.party_id) : r.note || "" }, { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "Company" },
        { k: "category_label", label: "Type" }, { label: "Bill", v: (r) => r.invoice_no || "" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "due_date", label: "Due" },
        { label: "Proposed", v: (r) => r.deferred && OPEN.includes(r.stage) ? h("span", { class: "fc-late", title: "Later than the due date" }, r.proposed_date) : r.proposed_date || "" }, { label: "Obligation", v: (r) => r.obligation },
        { label: "Stage", v: (r) => stamp(r.stage) }, { label: "Next", v: (r) => r.next_step ? (r.can_act ? h("b", {}, m.step_label[r.next_step]) : m.step_label[r.next_step]) : "" }],
      rows, { name: "payment_requests", totals: ["amount"], onRow: (r) => payreqDrawer(r.id, m, load), empty: "No requests here.", rowClass: (r) => (r.late ? "bad" : "") }));
    };
    await load();
    return box;
  }

  async function payreqForm(v, m, reload) {
    v = Object.assign({}, v);
    const pay = await api("fc.payables", {}).catch(() => ({ rows: [], commitments: [] }));
    const invs = pay.rows.filter((r) => r.ref_type === "invoice" && r.payable_now);
    if (v.invoice_id && !invs.find((r) => String(r.ref_id) === String(v.invoice_id))) invs.push({ ref_id: v.invoice_id, ref_no: v._label || "#" + v.invoice_id, party_name: "", amount: v.amount });
    const fields = [{ k: "category", label: "Type", type: "select", noBlank: true, options: m.categories },
      { k: "invoice_id", label: "Against bill (open purchase bills)", type: "select", search: true, options: invs.map((r) => [r.ref_id, r.ref_no + " · " + (r.party_name || "") + " · open " + money(r.amount)]), blank: "No bill (advance or other)" },
      { k: "party_id", label: "Pay to (party)", type: "select", options: () => opt.parties(), search: true }, { k: "project_id", label: "Project", type: "select", options: projOpts },
      { k: "po_id", label: "Purchase order (for an advance)", type: "select", options: pay.commitments.map((c) => [c.po_id, c.no + " · " + (c.party_name || "")]) },
      { k: "amount", label: "Amount", type: "number", req: true }, { k: "due_date", label: "Due date", type: "date" }, { k: "proposed_date", label: "Proposed payment date", type: "date" },
      { k: "obligation", label: "Obligation", type: "select", noBlank: true, options: m.obligations }, { k: "terms", label: "Payment terms" }, { k: "tax_note", label: "Tax (VAT / TDS) note" },
      { k: "consequence", label: "Consequence if not paid on time", wide: true }, { k: "deferral_reason", label: "Reason for paying after the due date", wide: true },
      { k: "note", label: "Purpose / note", type: "textarea", wide: true }, { k: "ref", label: "ref", hide: true }];
    const f = form(fields, v);
    if (v.ref) f.append(h("input", { type: "hidden", name: "ref", value: v.ref }));
    modal(v.id ? "Edit payment request " + (v.no || "") : "New payment request", h("div", {}, f,
      h("p", { class: "hint" }, "Against a bill, the party and project come from the bill and the amount cannot be more than what is open and not already requested. Tax, wage, safety and contractual payments proposed after their due date need a reason, and the approver must confirm it.")),
    [{ label: v.id ? "Save" : "Request", cls: "primary", act: async () => {
      const x = f.values();
      Object.keys(x).forEach((k) => { if (x[k] === "") x[k] = null; });
      const r = await run("fc.payreq_save", Object.assign(x, { id: v.id || null }), (d) => "Saved " + d.no);
      reload && reload();
      if (!v.id) payreqDrawer(r.id, m, reload);
    } }]);
  }

  async function payreqDrawer(id, m, reload) {
    const g = await run("fc.payreq_get", { id });
    const refresh = () => { reload && reload(); };
    const doAct = async (action, extra, okMsg) => { await run("fc.payreq_act", Object.assign({ id, action }, extra || {}), okMsg || "Done"); refresh(); };
    const btns = g.actions.map((a) => {
      if (a === "edit") return { label: "Edit", act: async () => { payreqForm(g, m, reload); } };
      if (a === "pay") return { label: "Pay now", cls: "primary", act: async () => { payDialog(g, m, refresh); } };
      if (a === "link") return { label: "Link payment already made", act: async () => { linkDialog(g, refresh); } };
      const needNote = a === "return" || a === "reject" || (a === "approve" && g.deferred && ["statutory", "payroll", "safety", "contractual"].includes(g.obligation));
      return { label: ACTION_LABEL[a] || a, cls: a === "approve" ? "primary" : a === "reject" || a === "cancel" ? "warn" : "", act: async () => {
        const n = await ask(ACTION_LABEL[a], a === "approve" && g.deferred ? "This " + g.obligation + " payment is proposed after its due date (" + g.due_date + "). Reason given: " + (g.deferral_reason || "") + ". Write your approval note." :
          "Request " + g.no + " for " + money(g.amount) + ".", { input: needNote ? "Note (required)" : "Note (optional)", required: needNote, ok: ACTION_LABEL[a], danger: a === "reject" || a === "cancel" });
        if (n === null) return false;
        await doAct(a, { note: n }, ACTION_LABEL[a] + ": done");
      } };
    });
    drawer("Payment request " + g.no, h("div", {},
      g.late ? note("Past its due date (" + g.due_date + ").", "bad") : null,
      g.deferred && OPEN.includes(g.stage) ? note("Proposed for " + g.proposed_date + ", after the due date " + g.due_date + "." + (g.deferral_reason ? " Reason: " + g.deferral_reason : "")) : null,
      kv([["Stage", stamp(g.stage)], ["Next step", g.next_step ? m.step_label[g.next_step] + " (" + m.steps[g.next_step].join(" ") + ")" : "—"], ["Type", g.category_label],
        ["Pay to", g.party_id ? nm.party(g.party_id) : "—"], ["Project", projName(g.project_id)], ["Bill", g.invoice_no ? g.invoice_no + " · open " + money(g.invoice_outstanding) + (g.other_open ? " · other requests " + money(g.other_open) : "") : "—"],
        ["Amount", money(g.amount)], ["Due", g.due_date || "—"], ["Proposed", g.proposed_date || "—"], ["Obligation", g.obligation], ["Terms", g.terms], ["Tax", g.tax_note], ["If not paid", g.consequence], ["Purpose / note", g.note],
        g.payment_no || g.voucher_no ? ["Paid by", (g.payment_no || "") + (g.voucher_no ? " (voucher " + g.voucher_no + ")" : "")] : null, ["Requested by", g.created_by_name]]),
      h("h4", {}, "Approval trail"),
      table([{ label: "When", v: (x) => (x.ts || "").replace("T", " ").slice(0, 16) }, { k: "user_name", label: "By" }, { label: "Step", v: (x) => ACTION_LABEL[x.action] || x.action }, { label: "To", v: (x) => stamp(x.to_stage) }, { k: "note", label: "Note" }], g.log, { search: false, export: false })), btns);
  }

  function payDialog(g, m, done) {
    const f = form([{ k: "date", label: "Payment date", type: "date" }, { k: "bank_account_id", label: "Pay from", type: "select", noBlank: true, options: () => opt.money() },
      { k: "mode", label: "Mode", type: "select", noBlank: true, options: [["cheque", "Cheque"], ["bank transfer", "Bank transfer"], ["cash", "Cash"]] }, { k: "cheque_no", label: "Cheque / transfer reference" },
      { k: "tds_rate_id", label: "TDS", type: "select", options: () => opt.tds(), blank: "No TDS" }, { k: "cash_override", label: "Cash-limit override reason (cash above the limit only)", wide: true },
      { k: "allow_duplicate", label: "Allow a reference already used for this party (accounts approver)", type: "check", hide: !m.rights.accounts_approve }],
    { date: today(), mode: "cheque", bank_account_id: ((S.L.accounts || []).find((a) => a.active && a.role === "bank") || {}).id });
    modal("Pay " + g.no + ": " + money(g.amount), h("div", {}, f, h("p", { class: "hint" }, g.invoice_no ? "Allocated to bill " + g.invoice_no + "." : "Paid as an advance to the party.", " The payment and its voucher are made by the normal payment engine.")),
      [{ label: "Pay", cls: "primary", act: async () => { const x = f.values(); if (!x.tds_rate_id) delete x.tds_rate_id; const r = await run("fc.payreq_act", Object.assign({ id: g.id, action: "pay" }, x), (d) => "Paid: " + d.payment_no); done && done(); return r; } }], { narrow: true });
  }

  async function linkDialog(g, done) {
    const [pays, vous] = await Promise.all([api("payment.list", { kind: "pay" }).catch(() => []), api("voucher.list", { type: "payment", status: "posted", limit: 300 }).catch(() => [])]);
    const f = form([{ k: "payment_id", label: "Payment", type: "select", search: true, options: pays.filter((p) => p.status === "posted" && (!g.party_id || p.party_id === g.party_id)).map((p) => [p.id, p.no + " · " + p.date + " · " + nm.party(p.party_id) + " · " + money(p.gross)]), blank: "—" },
      { k: "voucher_id", label: "or payment voucher (tax deposits, instalments, wages)", type: "select", search: true, options: vous.map((v) => [v.id, v.no + " · " + v.date + " · " + (v.narration || "").slice(0, 50) + " · " + money(v.total)]), blank: "—" }], {});
    modal("Link " + g.no + " to the payment made", f, [{ label: "Link", cls: "primary", act: async () => { const x = f.values(); await run("fc.payreq_act", { id: g.id, action: "link", payment_id: x.payment_id || null, voucher_id: x.payment_id ? null : x.voucher_id || null }, "Linked"); done && done(); } }], { narrow: true });
  }

  /* ═════════════ Accounts › Payments & receipts: payment plan ═════════════ */
  let planDays = 30;
  async function planTab() {
    const box = h("div");
    const m = await meta();
    const load = async () => {
      const d = await api("fc.pay_plan", { days: planDays });
      box.innerHTML = "";
      const daysIn = h("input", { type: "number", value: planDays, style: "max-width:90px" });
      box.append(h("div", { class: "bar" }, h("label", { class: "f" }, h("span", {}, "Dues within (days)"), daysIn), h("button", { class: "btn", onclick: () => { planDays = Number(daysIn.value) || 30; load(); } }, "Show"), h("div", { class: "grow" }),
        m.rights.accounts_approve ? h("button", { class: "btn", onclick: () => settingsModal(m, load) }, "Payment-control settings") : null));
      box.append(h("div", { class: "fc-strip" }, card("Cash and bank", money(d.cash)), card("Reserve kept back", money(d.reserve)), card("Available to pay", money(d.available)),
        card("Requested and due", money(d.total)), card("Shortfall", money(d.shortfall), "", d.shortfall > 0 ? "bad" : "ok")));
      box.append(note(d.note));
      box.append(table([{ k: "rank", label: "#" }, { label: "Obligation", v: (r) => (m.obligations.find((o) => o[0] === r.obligation) || [0, r.obligation])[1] }, { k: "label", label: "Item" },
        { label: "Pay to", v: (r) => r.party_id ? nm.party(r.party_id) : r.party_name || "" }, { label: "Project", v: (r) => r.project_id ? nm.pcode(r.project_id) : "Company" },
        { label: "Due", v: (r) => r.due_date ? h("span", { class: r.late ? "fc-late" : "" }, r.due_date) : "" }, { k: "proposed_date", label: "Proposed" }, { k: "amount", label: "Amount", fmt: "money" },
        { k: "cumulative", label: "Cumulative", fmt: "money" }, { label: "Within cash", v: (r) => stamp(r.fits ? "ok" : "overdue") }, { k: "stage", label: "Request" }],
      d.items, { name: "payment_plan", title: "Payment plan", extra: [["Cash and bank", fmtMoney(d.cash)], ["Reserve", fmtMoney(d.reserve)]], empty: "Nothing requested or due in this window." }));
    };
    await load();
    return box;
  }

  function settingsModal(m, done) {
    const s = m.settings;
    let steps = {};
    try { steps = JSON.parse(s.fc_payreq_steps || "{}"); } catch (e) { steps = m.steps; }
    const f = form([{ k: "fc_cash_reserve", label: "Cash reserve kept back in the plan", type: "number" }, { k: "fc_statutory_due_day", label: "VAT and TDS deposit day of the next month", type: "number" },
      { k: "fc_stale_days", label: "Flag bank and queue items older than (days)", type: "number" }, { k: "fc_payreq_strict", label: "Strict separation: one person, one step per request", type: "check" },
      { k: "fc_payreq_self_approve", label: "Allow the requester to approve (one-person offices only)", type: "check" }], s);
    const rows = Object.keys(m.step_label).map((k) => {
      const mod = h("select", { name: "m_" + k }, ["payreq", "accounts", "procurement", "commercial"].map((x) => h("option", { value: x, selected: (steps[k] || m.steps[k])[0] === x }, x)));
      const act = h("select", { name: "a_" + k }, ["view", "create", "edit", "approve", "post"].map((x) => h("option", { value: x, selected: (steps[k] || m.steps[k])[1] === x }, x)));
      return h("tr", {}, h("td", {}, m.step_label[k]), h("td", {}, mod), h("td", {}, act));
    });
    const tbl = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Step"), h("th", {}, "Module"), h("th", {}, "Right needed"))), h("tbody", {}, rows));
    modal("Payment-control settings", h("div", {}, f, h("h4", {}, "Who may do each step"), tbl, h("p", { class: "hint" }, "Rights are given to roles in Administration › Users and roles (row 'payreq'). Paying also always needs accounts edit.")),
      [{ label: "Save", cls: "primary", act: async () => {
        const st = {};
        Object.keys(m.step_label).forEach((k) => { st[k] = [tbl.querySelector("[name=m_" + k + "]").value, tbl.querySelector("[name=a_" + k + "]").value]; });
        await run("fc.settings_save", Object.assign(f.values(), { fc_payreq_steps: st }), "Saved");
        await meta(true);
        done && done();
      } }], { narrow: true });
  }

  /* ═════════════ Accounts › Integrity checks: financial data checks ═════════════ */
  async function checksTab() {
    const d = await api("fc.checks", {});
    const s = d.summary;
    return h("div", {},
      h("div", { class: "fc-strip" }, card("Errors", String(s.error), "must be corrected", s.error ? "bad" : "ok"), card("Warnings", String(s.warning), "to look at"), card("Passed", String(s.ok), "", "ok")),
      table([{ k: "area", label: "Area" }, { k: "check", label: "Check" }, { label: "Result", v: (r) => stamp(r.severity) }, { k: "detail", label: "Detail" }, { label: "Where to correct", v: (r) => r.fix || "" }],
        d.checks, { name: "financial_data_checks", search: false, rowClass: (r) => (r.severity === "error" ? "bad" : ""), onRow: (r) => {
          if (!r.items.length) return;
          drawer(r.check, h("div", {}, h("p", {}, r.detail), table([{ k: "ref", label: "Reference" }, { k: "date", label: "Date" }, { k: "detail", label: "Detail" }, { k: "amount", label: "Amount", fmt: "money" }], r.items, { name: "check_items" }),
            r.count > r.items.length ? h("p", { class: "hint" }, "First " + r.items.length + " of " + r.count + " shown.") : null), []);
        } }),
      h("p", { class: "hint" }, "These checks only read the books. They add to the integrity checks on the first tab; nothing is changed or corrected automatically."));
  }

  /* ═════════════ wiring: tabs on the existing pages ═════════════ */
  addTabs("p/ipc", "Interim payment certificates", "Measurement → IPC → consultant certification → accounts → payment.", "IPCs", [["Billing pipeline & collections", pipelineTab]]);
  addTabs("acc/ageing", "Ageing", "Open invoice balances by days past due, and the expected credit loss allowance.", "Ageing",
    [["Receivables: five buckets", receivablesTab], ["Collection actions", collectionsTab], ["Payables register", payablesTab]]);
  addTabs("acc/payments", "Payments & receipts", "Pay suppliers bill-wise with TDS, give advances, and record client receipts.", "Payments & receipts",
    [["Payment requests", requestsTab], ["Payment plan", planTab]]);
  addTabs("acc/integrity", "Integrity checks", "Checks that the books agree with themselves, and NFRS compliance.", "Checks", [["Financial data checks", checksTab]]);

  /* What's new */
  const VER = "2.26.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!can("accounts", "view") && !can("commercial", "view")) return;
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("p", {}, "Billing, collections and payments are now followed from start to finish, in the screens you already use."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("Billing pipeline.", "Commercial › IPCs: every IPC from prepared to paid, with dates, the person responsible, the next action and a history."),
        li("Receivables and collections.", "Accounts › Ageing: five buckets per project, retention release dates, and a collection action list with follow-ups and promised dates."),
        li("Payables register.", "Supplier, subcontractor and hire bills, wages, VAT and TDS, loan and equipment instalments, by due date."),
        li("Payment requests.", "Accounts › Payments & receipts: documents, accounts, cash, approval, payment and reconciliation, with a payment plan against the bank balance."),
        li("Financial data checks.", "Accounts › Integrity checks: controls by project, duplicates, unreconciled bank items, IPCs against invoices.")),
      h("p", { class: "hint" }, "No entry, account or balance changed. A payment is still made by the normal payment screen's engine.")),
    [{ label: "Open Payments & receipts", cls: "primary", act: () => { location.hash = "#/acc/payments?tab=1"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 7000); } }, 900);
})();
