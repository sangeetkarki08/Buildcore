/* BuildCore 2.61 — Group view, Cheques & PDC, Approval limits, VAT & TDS return files, Year-end checklist, Tally XML, Alternate units. */
(function () {
"use strict";
if (window.__bco261) return; window.__bco261 = true;
const lbl = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
const empty = (t) => h("p", { class: "muted" }, t);
const n2 = (x) => x == null ? "—" : Number(x).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n0 = (x) => x == null ? "—" : Number(x).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const td = () => new Date().toISOString().slice(0, 10);
const m1 = () => td().slice(0, 8) + "01";
const dl = (name, text, type) => { const a = h("a", { href: URL.createObjectURL(new Blob([(type || "").includes("csv") ? "﻿" + text : text], { type: type || "text/plain" })), download: name }); document.body.append(a); a.click(); a.remove(); };
const range = (onch, st) => h("span", { class: "bar" },
  lbl("From", h("input", { type: "date", value: st.from, onchange: (e) => { st.from = e.target.value; onch(); } })),
  lbl("To", h("input", { type: "date", value: st.to, onchange: (e) => { st.to = e.target.value; onch(); } })));

/* ═════════════ Accounts › Group view ═════════════ */
PAGES["gp/group"] = async (root) => {
  root.append(pageHead("Group view (all companies)", "Every company on this BuildCore added up: profit, assets and liabilities, a combined trial balance, and what the companies show against each other. Each company file is only read."));
  const st = { from: "", to: td() };
  const box = h("div");
  const load = async () => {
    const d = await api("gp.group", { to: st.to, from: st.from || undefined });
    box.replaceChildren(h("div", { class: "bar" }, lbl("As at", h("input", { type: "date", value: st.to, onchange: (e) => { st.to = e.target.value; load(); } }))));
    box.append(summaryStrip([["Companies", String(d.companies.length)], ["Income", n0(d.total.income)], ["Expense", n0(d.total.expense)], ["Profit", n0(d.total.profit)],
      ["Assets", n0(d.total.assets)], ["Liabilities & capital", n0(d.total.liabilities)], ["Inter-company to cancel", n0(d.eliminate)]]));
    box.append(tabs([
      ["Companies", () => table([{ k: "code", label: "Code" }, { k: "name", label: "Company" }, { label: "Income", v: (r) => n0(r.income), num: true }, { label: "Expense", v: (r) => n0(r.expense), num: true },
        { label: "Profit", v: (r) => h("span", { class: r.profit < 0 ? "neg" : "" }, n0(r.profit)), num: true }, { label: "Assets", v: (r) => n0(r.assets), num: true }, { label: "Liabilities & capital", v: (r) => n0(r.liabilities), num: true },
        { label: "Books balance", v: (r) => r.balanced ? "✓" : h("span", { class: "neg" }, "No") }], d.companies, { search: false, name: "gp_cos" })],
      ["Combined trial balance", () => {
        const cols = [{ k: "type", label: "Type" }, { k: "name", label: "Account" }, { k: "codes", label: "Codes" }];
        d.codes.forEach((c) => cols.push({ label: d.names[c] || c, v: (r) => r.by[c] == null ? "" : n2(r.by[c]), num: true }));
        cols.push({ label: "Group total (Dr + / Cr −)", v: (r) => h("b", {}, n2(r.total)), num: true });
        return h("div", {}, h("p", { class: "hint" }, "Accounts are lined up by type and name across companies. Debit balances are positive, credit balances negative."), table(cols, d.tb, { name: "gp_tb" }));
      }],
      ["Inter-company", () => h("div", {}, h("p", { class: "hint" }, "A party in one company whose PAN or name is another company's. Both sides should show the same amount with opposite signs; the difference is what needs checking before the balances are cancelled on consolidation."),
        d.pairs.length ? table([{ k: "a", label: "Company" }, { label: "Shows", v: (r) => n2(r.a_shows), num: true }, { k: "b", label: "Other company" }, { label: "Other shows", v: (r) => r.b_shows == null ? "not found" : n2(r.b_shows), num: true },
          { label: "Difference", v: (r) => r.difference == null ? "—" : h("span", { class: Math.abs(r.difference) > 1 ? "neg" : "" }, n2(r.difference)), num: true }, { k: "matched_by", label: "Matched by" }], d.pairs, { search: false })
          : empty("No company is set up as a party in another company. Add each sister company as a party with its PAN (Company settings › PAN) to see these."))],
    ]));
  };
  await load();
  root.append(box);
};

/* ═════════════ Accounts › Cheques & post-dated cheques ═════════════ */
const CH_TXT = { held: "Held (not deposited)", deposited: "Deposited", cleared: "Cleared", bounced: "Bounced", returned: "Returned to party", cancelled: "Cancelled", issued: "Issued (not presented)", presented: "Presented", void: "Void" };
PAGES["st/cheques"] = async (root, params) => {
  root.append(pageHead("Cheques & post-dated cheques", "Cheques received from clients and given to suppliers with their dates, cheque books per bank, and the cheque to print. Nothing is posted here: enter the receipt or payment as before and link it."));
  root.append(tabs([["Cheques received", () => chqTab("received")], ["Cheques given", () => chqTab("given")], ["Cheque books", bookTab]], params && params.tab ? Number(params.tab) : 0));
};
async function chqTab(dir) {
  const box = h("div");
  const load = async () => {
    const d = await api("chq.list", { direction: dir });
    const rows = d.rows;
    box.replaceChildren(summaryStrip(dir === "received" ? [["Post-dated held", n0(d.summary.pdc_received)], ["Deposited, not cleared", n0(d.summary.deposited)], ["Bounced", n0(d.summary.bounced)]]
      : [["Issued, not presented", n0(d.summary.pdc_given)], ["Presented, not cleared", n0(d.summary.presented)], ["Bounced", n0(d.summary.bounced)]]));
    if (can("accounts", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => chqDlg(dir, d.books, null, load) }, dir === "received" ? "Record a cheque received" : "Write a cheque")));
    box.append(rows.length ? table([{ k: "cheque_no", label: "Cheque no" }, { k: "cheque_date", label: "Cheque date" },
      { label: "Days", v: (r) => r.days == null ? "" : h("span", { class: r.due ? "neg" : "" }, r.pdc ? "in " + r.days : (r.due ? (r.days === 0 ? "today" : -r.days + " ago") : "")) },
      { label: dir === "received" ? "From" : "To", v: (r) => r.party || r.payee || "" }, dir === "received" ? { k: "drawer_bank", label: "Drawn on" } : { k: "bank", label: "Our bank" },
      { label: "Amount", v: (r) => n2(r.amount), num: true }, { label: "Status", v: (r) => CH_TXT[r.status] || r.status }, { k: "status_date", label: "Since" }, { k: "project", label: "Project" }, { k: "payment_no", label: "Receipt / payment" },
      { label: "", v: (r) => h("span", {}, can("accounts", "edit") ? h("button", { class: "btn sm", onclick: () => stDlg(r, d.statuses[dir], load) }, "Status") : "",
        can("accounts", "edit") ? h("button", { class: "btn sm", onclick: () => chqDlg(dir, d.books, r, load) }, "Edit") : "",
        dir === "given" ? h("button", { class: "btn sm", onclick: () => printChq(r.id) }, "Print") : "") }], rows, { name: "chq_" + dir })
      : empty(dir === "received" ? "No cheques received recorded yet." : "No cheques written yet."));
  };
  await load();
  return box;
}
function chqDlg(dir, books, r, reload) {
  const fields = [{ k: "party_id", label: dir === "received" ? "From (client)" : "To (supplier / subcontractor)", type: "select", options: () => opt.parties(dir === "received" ? ["client"] : null) },
    { k: "payee", label: "Or name on the cheque" }, { k: "cheque_date", label: "Cheque date", type: "date", req: true }, { k: "amount", label: "Amount", type: "number", req: true }];
  if (dir === "given") fields.push({ k: "book_id", label: "Cheque book (next number)", type: "select", options: books.filter((b) => b.active).map((b) => [b.id, b.bank + " · next " + b.next_no]) },
    { k: "bank_account_id", label: "Our bank", type: "select", options: opt.money });
  else fields.push({ k: "drawer_bank", label: "Drawn on bank" }, { k: "bank_account_id", label: "Deposit into", type: "select", options: opt.money });
  fields.push({ k: "cheque_no", label: "Cheque no" + (dir === "given" ? " (blank = next from the book)" : ""), req: dir === "received" }, { k: "project_id", label: "Project", type: "select", options: opt.projects },
    { k: "payment_id", label: "Receipt / payment id (when entered)", type: "number" }, { k: "note", label: "Note", wide: true });
  const f = form(fields, r || { cheque_date: td() });
  modal(r ? "Cheque " + r.cheque_no : (dir === "received" ? "Cheque received" : "Cheque given"), f, [{ label: "Save", cls: "primary", act: async () => { await run("chq.save", Object.assign({ direction: dir, id: r && r.id }, f.values()), "Saved."); reload(); } }]);
}
function stDlg(r, sts, reload) {
  const f = form([{ k: "status", label: "Status", type: "select", noBlank: true, options: sts.map((s) => [s, CH_TXT[s] || s]) }, { k: "date", label: "Date", type: "date" },
    { k: "payment_id", label: "Receipt / payment id", type: "number" }, { k: "note", label: "Note", wide: true }], { status: r.status, date: td(), payment_id: r.payment_id });
  modal("Cheque " + r.cheque_no, f, [{ label: "Save", cls: "primary", act: async () => { await run("chq.status", Object.assign({ id: r.id }, f.values()), "Saved."); reload(); } }]);
}
async function printChq(id) {
  const d = await api("chq.print", { id });
  const dd = (d.date || "").split("-").reverse().join("");
  const html = '<div style="font-family:Arial;width:200mm;height:90mm;position:relative;border:1px dashed #bbb">' +
    '<div style="position:absolute;right:12mm;top:8mm;letter-spacing:4mm;font-size:14pt">' + escHtml(dd) + "</div>" +
    '<div style="position:absolute;left:25mm;top:24mm;font-size:13pt">' + escHtml(d.payee || "") + "</div>" +
    '<div style="position:absolute;left:30mm;top:36mm;width:120mm;font-size:11pt;line-height:9mm">' + escHtml(d.words) + "</div>" +
    '<div style="position:absolute;right:14mm;top:44mm;font-size:14pt;border:1px solid #000;padding:2mm 4mm">' + escHtml(n2(d.amount)) + "/-</div></div>" +
    '<p style="font:9pt Arial;color:#666">Cheque ' + escHtml(d.cheque_no || "") + ". Positions suit most Nepali bank cheques; print a test on plain paper first.</p>";
  const w = window.open("", "_blank");
  if (!w) return toast("Allow pop-ups to print.", "err");
  w.document.write("<html><head><title>Cheque " + escHtml(d.cheque_no || "") + "</title><style>@page{size:A4;margin:10mm}body{margin:0}</style></head><body>" + html + "<script>window.onload=()=>window.print()<\/script></body></html>");
  w.document.close();
}
async function bookTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("chq.list", {});
    box.replaceChildren();
    if (can("accounts", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => bookDlg(null, load) }, "Add a cheque book")));
    box.append(d.books.length ? table([{ k: "bank", label: "Bank account" }, { k: "from_no", label: "From" }, { k: "to_no", label: "To" }, { k: "next_no", label: "Next" }, { k: "received_on", label: "Received" },
      { label: "Active", v: (r) => r.active ? "✓" : "used up" }, { label: "", v: (r) => can("accounts", "edit") ? h("button", { class: "btn sm", onclick: () => bookDlg(r, load) }, "Edit") : "" }], d.books, { search: false })
      : empty("No cheque book yet."));
  };
  await load();
  return box;
}
function bookDlg(r, reload) {
  const f = form([{ k: "bank_account_id", label: "Bank account", type: "select", options: opt.money, req: true }, { k: "from_no", label: "First cheque no", req: true }, { k: "to_no", label: "Last cheque no", req: true },
    { k: "next_no", label: "Next to use" }, { k: "received_on", label: "Received on", type: "date" }, { k: "active", label: "In use", type: "check" }, { k: "note", label: "Note", wide: true }], r || { active: 1, received_on: td() });
  modal("Cheque book", f, [{ label: "Save", cls: "primary", act: async () => { await run("chq.book_save", Object.assign({ id: r && r.id }, f.values()), "Saved."); reload(); } }]);
}

/* ═════════════ Accounts › Approval limits ═════════════ */
PAGES["st/limits"] = async (root) => {
  root.append(pageHead("Approval limits", "The largest purchase order, purchase bill, payment, voucher and subcontract bill each person or job may approve, with a stand-in while they are away. The administrator is never limited."));
  const box = h("div");
  const load = async () => {
    const d = await api("ap.list", {});
    box.replaceChildren(h("div", { class: "sf-banner" }, d.on ? "Approval limits are ON." : "Approval limits are OFF: the limits below are kept but not checked.",
      can("admin", "edit") ? h("button", { class: "btn sm", style: "margin-left:1em", onclick: async () => { await run("ap.switch", { on: d.on ? 0 : 1 }, d.on ? "Turned off." : "Turned on."); load(); } }, d.on ? "Turn off" : "Turn on") : ""));
    box.append(h("p", { class: "hint" }, "A document with no limit row at all is not checked. Once a document has any row, a person with no row for it cannot approve it."));
    if (can("admin", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => limDlg(d, null, load) }, "Add a limit")));
    const dl_ = Object.fromEntries(d.docs.map((x) => [x.key, x.label]));
    box.append(d.rows.length ? table([{ label: "Document", v: (r) => dl_[r.doc] || r.doc }, { label: "Who", v: (r) => r.user || ("Job: " + (r.role || "")) }, { label: "Up to", v: (r) => n2(r.max_amount), num: true },
      { k: "standin", label: "Stand-in" }, { label: "Stand-in dates", v: (r) => r.standin_user_id ? (r.standin_from || "…") + " to " + (r.standin_to || "…") : "" }, { label: "Active", v: (r) => r.active ? "✓" : "" },
      { label: "", v: (r) => can("admin", "edit") ? h("button", { class: "btn sm", onclick: () => limDlg(d, r, load) }, "Edit") : "" }], d.rows, { search: false }) : empty("No limits yet."));
    if (d.log.length) box.append(h("h3", {}, "Approvals checked against a limit"), table([{ k: "ts", label: "When" }, { label: "Document", v: (r) => dl_[r.doc] || r.doc }, { k: "doc_id", label: "Id" },
      { label: "Amount", v: (r) => n2(r.amount), num: true }, { k: "user", label: "By" }, { k: "behalf", label: "Standing in for" }], d.log, { search: false }));
  };
  await load();
  root.append(box);
};
function limDlg(d, r, reload) {
  const us = d.users.map((x) => [x.id, x.name + " (" + x.username + ")"]);
  const f = form([{ k: "doc", label: "Document", type: "select", noBlank: true, options: d.docs.map((x) => [x.key, x.label]) }, { k: "user_id", label: "User", type: "select", options: us },
    { k: "role", label: "Or job", type: "select", options: d.roles.map((x) => [x, x]) }, { k: "max_amount", label: "May approve up to (Rs)", type: "number", req: true },
    { k: "standin_user_id", label: "Stand-in user", type: "select", options: us }, { k: "standin_from", label: "Stand-in from", type: "date" }, { k: "standin_to", label: "Stand-in to", type: "date" },
    { k: "active", label: "Active", type: "check" }, { k: "note", label: "Note", wide: true }], r || { active: 1, doc: "po" });
  modal("Approval limit", f, [{ label: "Save", cls: "primary", act: async () => { await run("ap.save", Object.assign({ id: r && r.id }, f.values()), "Saved."); reload(); } }]);
}

/* ═════════════ Accounts › VAT & TDS return files ═════════════ */
PAGES["st/files"] = async (root, params) => {
  root.append(pageHead("VAT & TDS return files", "The monthly VAT return worksheet and the TDS return list per deductee, with Excel-ready files (CSV) for the IRD portal. Figures come from posted bills and payments."));
  const st = { from: m1(), to: td() };
  root.append(tabs([["VAT return", () => vatTab(st)], ["TDS return", () => tdsTab(st)]], params && params.tab ? Number(params.tab) : 0));
};
async function vatTab(st) {
  const box = h("div");
  const load = async () => {
    const d = await api("st.vat_return", st);
    box.replaceChildren(range(load, st));
    box.append(summaryStrip([["Sales taxable", n0(d.sales.taxable)], ["Sales exempt", n0(d.sales.exempt)], ["Output VAT", n0(d.sales.vat)], ["Purchase taxable", n0(d.purchase.taxable)],
      ["Purchase exempt", n0(d.purchase.exempt)], ["Input VAT", n0(d.purchase.vat)], [d.payable ? "VAT payable" : "VAT credit to carry", n0(d.payable || d.credit)]]));
    const csvBtn = (k, t) => h("button", { class: "btn", onclick: async () => { const x = await api("st.csv", Object.assign({ kind: k }, st)); dl(x.name, x.text, "text/csv"); } }, t);
    box.append(h("div", { class: "actions" }, csvBtn("sales", "Sales book (CSV)"), csvBtn("purchase", "Purchase book (CSV)")));
    const cols = [{ k: "date", label: "Date" }, { k: "no", label: "No" }, { k: "party_inv_no", label: "Party inv no" }, { k: "party", label: "Party" }, { k: "pan", label: "PAN" },
      { label: "Taxable", v: (r) => n2(r.taxable), num: true }, { label: "Exempt", v: (r) => n2(r.exempt), num: true }, { label: "VAT", v: (r) => n2(r.vat), num: true }, { label: "Total", v: (r) => n2(r.total), num: true }];
    box.append(h("h3", {}, "Sales (" + d.sales.count + ")"), d.sales.lines.length ? table(cols, d.sales.lines, { name: "vat_s" }) : empty("No posted sales invoices in these dates."));
    box.append(h("h3", {}, "Purchases (" + d.purchase.count + ")"), d.purchase.lines.length ? table(cols, d.purchase.lines, { name: "vat_p" }) : empty("No posted purchase bills in these dates."));
  };
  await load();
  return box;
}
async function tdsTab(st) {
  const box = h("div");
  const load = async () => {
    const d = await api("st.tds_return", st);
    box.replaceChildren(range(load, st));
    box.append(summaryStrip([["TDS deducted", n0(d.total_tds)], ["Deposited", n0(d.deposited)], ["Not deposited", n0(d.not_deposited)], ["Payments without PAN", String(d.missing_pan)]]));
    box.append(h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => { const x = await api("st.csv", Object.assign({ kind: "tds" }, st)); dl(x.name, x.text, "text/csv"); } }, "TDS return list (CSV)")));
    box.append(d.rows.length ? table([{ k: "pan", label: "PAN" }, { k: "name", label: "Deductee" }, { k: "section", label: "Section" }, { k: "rate", label: "Rate %" }, { k: "payments", label: "Payments" },
      { label: "Amount paid", v: (r) => n2(r.amount), num: true }, { label: "TDS", v: (r) => n2(r.tds), num: true }], d.rows, { name: "tds_ret" }) : empty("No TDS deducted in these dates."));
  };
  await load();
  return box;
}

/* ═════════════ Accounts › Year-end checklist ═════════════ */
PAGES["st/yearend"] = async (root) => {
  root.append(pageHead("Year-end checklist", "Everything to finish before and after closing a fiscal year, each with a link to the screen that fixes it."));
  const box = h("div");
  let fy = null;
  const load = async () => {
    const d = await api("ye.check", fy ? { fy } : {});
    fy = d.fy;
    box.replaceChildren(h("div", { class: "bar" }, lbl("Fiscal year", h("select", { onchange: (e) => { fy = e.target.value; load(); } }, d.years.map((y) => h("option", { value: y, selected: y === d.fy }, y)))),
      h("span", { class: "muted" }, d.start + " to " + d.end)));
    box.append(h("div", { class: "sf-banner" }, d.ready ? "Everything checked is in order for " + d.fy + "." : "Some items still need work before " + d.fy + " can be closed cleanly."));
    box.append(table([{ label: "", v: (r) => r.ok === true ? "✓" : (r.ok === false ? h("span", { class: "neg" }, "✗") : "…") }, { k: "label", label: "Item" }, { k: "detail", label: "Where it stands" },
      { label: "", v: (r) => h("a", { href: r.route }, "Open") }], d.items, { search: false }));
  };
  await load();
  root.append(box);
};

/* ═════════════ Accounts › Tally XML ═════════════ */
PAGES["tx/tally"] = async (root) => {
  root.append(pageHead("Tally XML export / import", "Send the chart and the vouchers of a period to Tally (Gateway › Import Data), or bring vouchers exported from Tally in as draft journal vouchers."));
  root.append(tabs([["Export to Tally", txExport], ["Import from Tally", txImport]]));
};
async function txExport() {
  const st = { from: m1(), to: td() };
  const box = h("div");
  const out = h("div");
  box.append(range(() => {}, st), h("p", { class: "hint" }, "Import the masters file first (ledgers under the Tally groups chosen on the Gateway; parties as their own Sundry Debtors / Creditors ledgers), then the vouchers file. Debits are written as negative amounts, as Tally expects."),
    h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const d = await run("tx.export", st);
      const co = ((S.L && S.L.settings && S.L.settings.company_name) || "BuildCore").toString().replace(/[^A-Za-z0-9]+/g, "_");
      out.replaceChildren(summaryStrip([["Ledgers", String(d.ledgers)], ["Vouchers", String(d.count)], ["Dates", d.from + " to " + d.to]]),
        h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => dl(co + "_masters.xml", d.masters, "application/xml") }, "Download masters XML"),
          h("button", { class: "btn", onclick: () => dl(co + "_vouchers_" + d.from + "_" + d.to + ".xml", d.vouchers, "application/xml") }, "Download vouchers XML")));
    } }, "Make the Tally files")), out);
  return box;
}
async function txImport() {
  const box = h("div");
  const ta = h("textarea", { rows: 6, style: "width:100%", placeholder: "Paste the Tally XML here, or choose the file" });
  const file = h("input", { type: "file", accept: ".xml,.txt", onchange: async (e) => { const f = e.target.files[0]; if (f) ta.value = await f.text(); } });
  const out = h("div");
  const show = (d) => {
    out.replaceChildren(summaryStrip([["Vouchers in file", String(d.count)], ["Ready to bring in", String(d.ready)], ["Ledgers not found", String(d.unmatched.length)]]));
    if (d.unmatched.length) out.append(h("p", { class: "hint" }, "Vouchers that use a ledger not found here are skipped. Add the account (Chart of accounts) or party with exactly the same name and preview again."),
      table([{ k: "ledger", label: "Tally ledger" }, { k: "uses", label: "Lines" }], d.unmatched, { search: false }));
    out.append(table([{ k: "date", label: "Date" }, { k: "type", label: "Type" }, { k: "no", label: "No" }, { k: "narration", label: "Narration" },
      { label: "Amount", v: (r) => n2(r.lines.reduce((s, l) => s + l.debit, 0)), num: true }, { label: "Ready", v: (r) => r.ready ? "✓" : h("span", { class: "neg" }, "no: " + (r.why || "")) }], d.vouchers, { name: "tx_prev" }));
    if (d.ready && can("accounts", "edit")) out.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const r = await run("tx.import", { text: ta.value }); toast(r.made + " draft journal voucher(s) made; check and post them under Vouchers."); out.replaceChildren();
    } }, "Bring in " + d.ready + " voucher(s) as drafts")));
  };
  box.append(file, ta, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => show(await run("tx.preview", { text: ta.value })) }, "Preview")), out);
  return box;
}

/* ═════════════ Store › Alternate units ═════════════ */
PAGES["au/units"] = async (root) => {
  root.append(pageHead("Alternate units", "Other units for a material (cement bag = 50 kg, sand truck = 100 cft …). Stock is always kept in the material's own unit; documents sent with an alternate unit are converted, and stock is shown in both."));
  root.append(tabs([["Units", auTab], ["Stock in other units", auStock], ["Converter", auConv]]));
};
async function auTab() {
  const box = h("div");
  const load = async () => {
    const d = await api("au.list", {});
    box.replaceChildren();
    if (can("inventory", "edit")) box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => auDlg(null, load) }, "Add a unit")));
    box.append(d.rows.length ? table([{ k: "code", label: "Code" }, { k: "material", label: "Material" }, { label: "1 unit", v: (r) => "1 " + r.unit }, { label: "equals", v: (r) => r.factor + " " + r.base },
      { k: "note", label: "Note" }, { label: "", v: (r) => can("inventory", "edit") ? h("span", {}, h("button", { class: "btn sm", onclick: () => auDlg(r, load) }, "Edit"),
        h("button", { class: "btn sm", onclick: async () => { await run("au.save", { material_id: r.material_id, unit: r.unit, delete: 1 }, "Removed."); load(); } }, "Remove")) : "" }], d.rows, { name: "au_units" })
      : empty("No alternate unit yet."));
  };
  await load();
  return box;
}
function auDlg(r, reload) {
  const f = form([{ k: "material_id", label: "Material", type: "select", options: opt.materials, req: true }, { k: "unit", label: "Other unit (e.g. bag, truck)", req: true },
    { k: "factor", label: "How many of the material's own unit in one", type: "number", req: true }, { k: "note", label: "Note", wide: true }], r || {});
  modal("Alternate unit", f, [{ label: "Save", cls: "primary", act: async () => { await run("au.save", f.values(), "Saved."); reload(); } }]);
}
async function auStock() {
  const d = await api("au.stock", {});
  return d.rows.length ? table([{ k: "code", label: "Code" }, { k: "name", label: "Material" }, { label: "Stock", v: (r) => n2(r.qty) + " " + r.unit },
    { label: "In other units", v: (r) => r.other.map((x) => x.qty + " " + x.unit).join(" · ") }], d.rows, { name: "au_stock" }) : empty("No stock of materials that have an alternate unit.");
}
async function auConv() {
  const d = await api("au.list", {});
  const out = h("b");
  const qty = h("input", { type: "number", value: 1 });
  const sel = h("select", {}, d.rows.map((r, i) => h("option", { value: i }, r.material + ": " + r.unit + " → " + r.base)));
  const calc = () => { const r = d.rows[Number(sel.value)]; out.textContent = r ? (Number(qty.value || 0) * r.factor).toLocaleString("en-IN") + " " + r.base : ""; };
  qty.oninput = calc; sel.onchange = calc; calc();
  return d.rows.length ? h("div", {}, h("div", { class: "bar" }, lbl("Quantity", qty), lbl("Unit", sel)), h("p", {}, "= ", out),
    h("p", { class: "hint" }, "Goods received, issues, returns, transfers, requisitions, PRs and POs sent with an alternate unit (from the Excel import or a phone) are stored in the material's own unit, with the entered quantity kept in the line remarks.")) : empty("Add an alternate unit first.");
}
})();
