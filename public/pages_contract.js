/* BuildCore 2.16 — machine hire rate sheets (DoR method), contract administration (letters, time bars, bonds),
   communication (discussions, mentions, inbox, lists, directory) and document control (folders, numbers,
   revisions, reviews, transmittals). */
(function () {
"use strict";

const pill = (txt, col) => h("span", { style: "display:inline-block;white-space:nowrap;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff;background:" + col }, txt);
const COL = { open: "#c05621", replied: "#2f7a4d", info: "#1769aa", closed: "#667085", void: "#98a2b3", running: "#b7791f", done: "#2f7a4d", late: "#b42318",
  waived: "#98a2b3", not_needed: "#98a2b3", active: "#2f7a4d", extended: "#1769aa", reduced: "#1769aa", released: "#667085", expired: "#b42318", encashed: "#b42318",
  draft: "#98a2b3", for_info: "#1769aa", in_review: "#b7791f", approved: "#2f7a4d", approved_comments: "#3f8f5f", revise: "#c05621", rejected: "#b42318",
  superseded: "#98a2b3", withdrawn: "#98a2b3", sent: "#1769aa", acknowledged: "#2f7a4d", responded: "#2f7a4d", pending: "#b7791f", waiting: "#98a2b3", skipped: "#98a2b3" };
const st = (s, list) => (s ? pill(((list || []).find((x) => x[0] === s) || [s, String(s).replace(/_/g, " ")])[1], COL[s] || "#667085") : "");
const lab = (list, k) => ((list || []).find((x) => String(x[0]) === String(k)) || [k, k || ""])[1];
const need = (root, title) => { if (S.project) return false; root.append(pageHead(title), h("div", { class: "panel" }, "Choose a project at the top first.")); return true; };
const money = (n) => (n == null || n === "" ? "" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const late = (d, isLate) => (d ? h("span", { style: isLate ? "color:#b42318;font-weight:700" : "" }, d + (isLate ? " · late" : "")) : "");
let CM = null;
async function cmeta(force) { if (!CM || force || CM._p !== S.project) { CM = await run("ca.meta", { project_id: S.project || null }); CM._p = S.project; } return CM; }
const userOpts = () => CM.users.map((x) => [x.id, x.name + " (@" + x.username + ")"]);
const partyOpts = () => CM.parties.map((x) => [x.id, x.name]);
const listOpts = () => CM.lists.map((x) => [x.id, x.name]);
function dl(x) {
  if (!x || !x.b64) return;
  const a = document.createElement("a");
  a.href = "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + x.b64;
  a.download = x.filename; document.body.append(a); a.click(); a.remove();
}
async function upload1(file, meta) {
  const qs = new URLSearchParams(Object.assign({ filename: file.name, mime: file.type || "" }, meta || {}));
  [...qs.keys()].forEach((k) => { const v = qs.get(k); if (v === "" || v === "null" || v === "undefined") qs.delete(k); });
  const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: file });
  const j = await r.json();
  if (!j.ok) { toast(j.error, "err"); throw new Error(j.error); }
  return j.data.id;
}
const T = (s) => h("p", { class: "hint" }, s);

/* ═══════════════ machine hire rate sheet ═══════════════ */
PAGES["rp/hire"] = async (root) => {
  let bookId = "";
  let meta = await run("mh.meta", {});
  bookId = meta.book_id || "";
  const holder = h("div");
  const bookSel = h("select", { onchange: async () => { bookId = bookSel.value; meta = await run("mh.meta", { book_id: bookId }); load(); } },
    meta.books.map((b) => h("option", { value: b.id, selected: String(b.id) === String(bookId) }, b.code + " — " + b.name)));
  const load = async () => {
    const d = await run("mh.list", { book_id: bookId });
    holder.innerHTML = "";
    const pr = meta.prices || {};
    holder.append(h("div", { class: "panel" }, h("b", {}, "Prices used from the rate book: "),
      ["diesel", "petrol", "skilled", "helper"].map((k) => h("span", { style: "margin-right:16px" }, (pr[k] ? pr[k].name.split(" (")[0] + " Rs " + money(pr[k].rate) + "/" + pr[k].unit : k + ": not in book"))),
      T("Fuel is taken without VAT (÷1.13) as in the DoR sheets; crew per hour = daily wage × 30 / (8 × 26). Change them in Rate books, or type a different price on a sheet.")));
    holder.append(table([{ k: "code", label: "Code" }, { k: "name", label: "Machine" }, { k: "capacity", label: "Capacity" },
      { label: "Purchase price", fmt: "money", v: (r) => r.params.purchase }, { label: "Ownership / h", fmt: "money", v: (r) => r.calc && r.calc.ownership_h },
      { label: "Operating / h", fmt: "money", v: (r) => r.calc && r.calc.operating_h }, { label: "Crew / h", fmt: "money", v: (r) => r.calc && r.calc.crew_h },
      { label: "Hire rate / h", v: (r) => (r.live_rate != null ? h("b", {}, money(r.live_rate)) : h("span", { class: "red" }, r.error || "—")) },
      { label: "Rate-book item", v: (r) => r.res_code || "" }, { label: "Now in book", fmt: "money", v: (r) => r.book_rate },
      { label: "Price", v: (r) => (r.category === "DoR sample" && /2077/.test(r.remarks || "") ? pill("2077 price - update", "#c05621") : h("small", { class: "muted" }, r.remarks || "")) }],
    d.rows, { name: "machine_hire_rates", empty: "No sheet yet.", onRow: (r) => sheet(r, load) }));
  };
  root.append(pageHead("Machine hire rates (DoR method)", "Hourly hire charge = ownership (depreciation, interest, insurance, tax) + operating (repair, servicing, fuel, tyres, wear) + crew - the method of the DoR guideline for equipment ownership and operating cost. Put the result into the rate book or make a rate card for your own machine.",
    h("label", { class: "f", style: "flex-direction:row;gap:6px;align-items:center" }, h("span", {}, "Rate book"), bookSel),
    can("masters", "edit") ? h("button", { class: "btn primary", onclick: () => sheet(null, load) }, "New sheet") : null,
    can("masters", "edit") && meta.equipment.length ? h("button", { class: "btn", onclick: () => fromRegister(load) }, "From my equipment register") : null,
    h("button", { class: "btn", onclick: async () => dl(await run("mh.xlsx", { book_id: bookId })) }, "Excel")));
  root.append(h("div", { class: "panel warn" }, "The 25 DoR sample machines carry the guideline's parameters (life, hours, RF, SF, hp, fuel factors). Their purchase prices are the 2077 examples - open each machine you use and enter today's quotation before you rely on the rate."), holder);
  await load();

  async function fromRegister(done) {
    const f = form([{ k: "equipment_id", label: "Machine", type: "select", options: meta.equipment.map((e) => [e.id, e.code + " " + e.name]), req: true }]);
    modal("Start a sheet from the equipment register", f, [{ label: "Start", cls: "primary", act: async () => {
      const x = await run("mh.from_equipment", f.values());
      toast(x.note, "ok");
      sheet({ name: x.name, equipment_id: x.equipment_id, params: x.params, capacity: "" }, done);
    } }], { narrow: true });
  }

  function sheet(r, done) {
    r = r || { name: "", capacity: "", params: Object.assign({}, meta.defaults) };
    const p = Object.assign({}, meta.defaults, r.params || {});
    const head = form([{ k: "name", label: "Machine", req: true }, { k: "capacity", label: "Capacity / size" },
      { k: "res_code", label: "Rate-book item it prices", type: "select", options: meta.resources.map((x) => [x.code, x.code + " " + x.name + " /" + x.unit]), search: true },
      { k: "equipment_id", label: "My machine (for a rate card)", type: "select", options: meta.equipment.map((e) => [e.id, e.code + " " + e.name]) },
      { k: "remarks", label: "Remarks / price source", wide: true }], r);
    const g = (t) => h("h3", { style: "margin:12px 0 4px" }, t);
    const F = (list) => form(list, p, () => calc());
    const own = [F([{ k: "purchase", label: "Purchase price incl. tyres (P)", type: "number", req: true }, { k: "salvage", label: "Salvage value (S) - blank = %", type: "number" },
      { k: "salvage_pct", label: "Salvage % of P", type: "number" }, { k: "life_years", label: "Economic life (N, years)", type: "number" },
      { k: "hours_year", label: "Working hours per year (h)", type: "number" }]),
    F([{ k: "interest_pct", label: "Interest %", type: "number" },
      { k: "interest_basis", label: "Interest on", type: "select", noBlank: true, options: [["dor", "P / N (DoR sample sheets)"], ["avg", "Average investment (P(N+1)+S(N-1))/2N"]] },
      { k: "insurance_pct", label: "Insurance % of P / year", type: "number" }, { k: "tax_pct", label: "Tax, licence % of P / year", type: "number" },
      { k: "storage_pct", label: "Storage % of P / year", type: "number" }])];
    const op = [F([{ k: "rf", label: "Repair factor RF", type: "number" }, { k: "sf", label: "Servicing factor SF (oil, grease, filters)", type: "number" },
      { k: "fuel", label: "Fuel", type: "select", noBlank: true, options: [["diesel", "Diesel"], ["petrol", "Petrol"], ["electric", "Electricity"], ["none", "None"]] },
      { k: "hp", label: "Engine hp", type: "number" }, { k: "sfc", label: "SFC litre / hp-hour", type: "number", hint: "DoR sheets: diesel 0.16, petrol 0.22" },
      { k: "load_factor", label: "Load factor", type: "number" }, { k: "time_factor", label: "Time factor", type: "number" },
      { k: "fuel_ex_vat", label: "Take VAT out of the fuel price (÷1.13)", type: "check" }]),
    F([{ k: "fuel_lph", label: "OR litres per hour (measured)", type: "number" }, { k: "fuel_rate", label: "Fuel price / litre (blank = rate book)", type: "number" },
      { k: "kwh_per_h", label: "Electric: kWh per hour", type: "number" }, { k: "power_rate", label: "Electric: Rs per kWh", type: "number" }]),
    F([{ k: "tyre_no", label: "Number of tyres", type: "number" }, { k: "tyre_cost", label: "Cost of one tyre", type: "number" },
      { k: "tyre_life_h", label: "Tyre life (hours)", type: "number", hint: "Not given in the DoR sheets - 3000 h is BuildCore's starting figure" },
      { k: "special_wear_h", label: "Special wear items / h", type: "number" }, { k: "other_h", label: "Other running cost / h", type: "number" }])];
    const crew = form([{ k: "include_crew", label: "Include crew (DoR: hire charge includes crew)", type: "check" },
      { k: "skilled_h", label: "Operator / driver hours per machine hour", type: "number" }, { k: "skilled_day", label: "Operator daily wage (blank = rate book)", type: "number" },
      { k: "helper_h", label: "Helper hours per machine hour", type: "number" }, { k: "helper_day", label: "Helper daily wage (blank = rate book)", type: "number" },
      { k: "overhead_pct", label: "Overhead / profit % (normally 0 - added on the item rate)", type: "number" }], p, () => calc());
    const out = h("div", { class: "panel", style: "margin-top:10px" });
    const params = () => Object.assign({}, ...own.map((x) => x.values()), ...op.map((x) => x.values()), crew.values());
    let lastCalc = null;
    async function calc() {
      try {
        const x = await api("mh.calc", { params: params(), book_id: bookId });
        lastCalc = x;
        out.innerHTML = "";
        out.append(h("div", { class: "tiles" }, tile("Hire rate per hour", "Rs " + money(x.rate)), tile("Per 8-hour day", "Rs " + money(x.rate_day8)),
          tile("Ownership / h", money(x.ownership_h)), tile("Operating / h", money(x.operating_h)), tile("Crew / h", money(x.crew_h))),
        table([{ k: "group", label: "" }, { k: "label", label: "Cost head" }, { k: "per_hour", label: "Rs / hour", fmt: "money" }, { k: "how", label: "Working" }], x.lines, { search: false, export: false }),
        x.notes.length ? h("ul", { class: "hint" }, x.notes.map((n) => h("li", {}, n))) : null);
      } catch (e) { out.innerHTML = ""; out.append(h("p", { class: "red" }, e.message)); }
    }
    const body = h("div", {}, head, g("Ownership"), ...own, g("Operating"), ...op, g("Crew and overhead"), crew, out);
    const btns = [];
    if (can("masters", "edit")) btns.push({ label: "Save", cls: "primary", keep: true, act: async () => {
      const x = await run("mh.save", { row: Object.assign(head.values(), { id: r.id, params: params(), book_id: bookId }) }, "Saved");
      r.id = x.id; done && done();
    } });
    if (r.id && meta.can_book) btns.push({ label: "Put into rate book", keep: true, act: async () => {
      await run("mh.save", { row: Object.assign(head.values(), { id: r.id, params: params(), book_id: bookId }) });
      const x = await run("mh.apply_book", { id: r.id, book_id: bookId, res_code: head.values().res_code }, (y) => "Rate book now has Rs " + money(y.rate) + " / " + y.unit + " for " + y.res_code);
      done && done(); return x;
    } });
    if (r.id && meta.can_card) btns.push({ label: "Make rate card", keep: true, act: async () => {
      await run("mh.save", { row: Object.assign(head.values(), { id: r.id, params: params(), book_id: bookId }) });
      await run("mh.apply_card", { id: r.id, equipment_id: head.values().equipment_id, book_id: bookId }, "Rate card made - DPR and logsheet hours are costed from today");
    } });
    btns.push({ label: "Print", keep: true, act: () => {
      if (!lastCalc) return;
      const v = head.values();
      const box = h("div", {}, h("p", {}, h("b", {}, v.name), " ", v.capacity || ""),
        h("table", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Cost head"), h("th", {}, "Rs / hour"), h("th", {}, "Working")),
          lastCalc.lines.map((l) => h("tr", {}, h("td", {}, l.group), h("td", {}, l.label), h("td", { style: "text-align:right" }, money(l.per_hour)), h("td", {}, l.how))),
          h("tr", {}, h("td", {}, ""), h("td", {}, h("b", {}, "Hire rate per hour")), h("td", { style: "text-align:right" }, h("b", {}, money(lastCalc.rate))), h("td", {}, "per 8-h day " + money(lastCalc.rate_day8)))),
        h("p", {}, "Method: DoR Norms for Rate Analysis, guideline 1.C(ii) - hire charge = ownership + operating (fuel, crew, maintenance); DoR guideline for estimating equipment ownership and operating costs."));
      printFrame("Machine hire rate - " + v.name, box);
    } });
    if (r.id && can("masters", "edit")) btns.push({ label: r.active === 0 ? "Bring back" : "Archive", act: async () => { await run("mh.archive", { id: r.id }, "Done"); done && done(); } });
    modal((r.code ? r.code + " · " : "") + (r.name || "New machine hire sheet"), body, btns);
    calc();
  }
};

/* ═══════════════ contract administration ═══════════════ */
PAGES.ca = async (root) => {
  if (need(root, "Contract administration")) return;
  await cmeta(true);
  const d = await run("ca.dash", { project_id: S.project });
  const c = d.counts;
  root.append(pageHead("Contract administration", "What the contract needs from you now: letters to answer, notices before the time bar, bonds and insurance to extend, events without a notice, variations waiting.",
    h("a", { class: "btn primary", href: "#/ca/letters?new=in" }, "Log incoming letter"), h("a", { class: "btn", href: "#/ca/letters?new=out" }, "Write a letter")));
  root.append(h("div", { class: "tiles" },
    tile("Replies overdue", c.replies_overdue, { cls: c.replies_overdue ? "bad" : "", href: "#/ca/letters?open=1" }), tile("Letters waiting for our reply", c.replies_due, { href: "#/ca/letters?open=1" }),
    tile("Time bars running", c.timebars, { cls: c.timebars_7d ? "bad" : "", sub: c.timebars_7d + " due within 7 days", href: "#/ca/timebars" }),
    tile("Bonds / insurance to act on", c.securities, { cls: c.securities ? "warn" : "", href: "#/ca/securities" }),
    tile("Events without a notice", c.events_no_notice, { cls: c.events_no_notice ? "warn" : "", href: "#/p/events" }),
    tile("Variations not yet approved", c.variations, { href: "#/p/variations" }), tile("Contract items due (14 d)", c.contract_items, { href: "#/c/contracts" }),
    tile("Transmittals awaiting reply", c.transmittals_due, { href: "#/dm/transmittals" }),
    tile("Letters this month", d.flow.in_month + " in · " + d.flow.out_month + " out")));
  const sec = (t, node) => h("div", { class: "panel" }, h("h2", {}, t), node);
  if (d.timebars.length) root.append(sec("Notices and time bars", table([{ label: "", v: (r) => (r.days_left < 0 ? pill("MISSED", "#b42318") : r.days_left <= 7 ? pill(r.state, "#c05621") : r.state) },
    { k: "clause", label: "Clause" }, { k: "title", label: "What must be given" }, { k: "party", label: "By" }, { k: "trigger_date", label: "From" }, { k: "due_date", label: "Last day" },
    { k: "event_no", label: "Event" }, { k: "notes", label: "Notes" }], d.timebars, { search: false, onRow: () => { location.hash = "#/ca/timebars"; } })));
  if (d.letters.length) root.append(sec("Letters waiting for our reply", table([{ k: "our_no", label: "Reg. no." }, { k: "their_ref", label: "Their ref" }, { k: "date", label: "Date" }, { k: "who", label: "From" },
    { k: "subject", label: "Subject" }, { k: "assignee", label: "With" }, { label: "Reply by", v: (r) => late(r.reply_by, r.overdue) }], d.letters, { search: false, onRow: (r) => { location.hash = "#/ca/letters?id=" + r.id; } })));
  if (d.events.length) root.append(sec("Events with a notice deadline and no notice letter yet", table([{ k: "no", label: "Event" }, { k: "title", label: "Title" }, { k: "date", label: "Date" },
    { k: "clause", label: "Clause" }, { label: "Notice by", v: (r) => late(r.notice_deadline, r.days_left < 0) }, { label: "", v: (r) => h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); location.hash = "#/ca/letters?new=out&event=" + r.id; } }, "Write notice") }],
  d.events, { search: false })));
  if (d.securities.length) root.append(sec("Bonds, guarantees and insurance", table([{ label: "What", v: (r) => lab(CM.sec_kinds, r.kind) }, { k: "number", label: "Number" }, { k: "issuer", label: "Bank / insurer" },
    { k: "amount", label: "Amount", fmt: "money" }, { k: "expiry_date", label: "Expiry" }, { label: "", v: (r) => h("b", { class: "red" }, r.alert) }], d.securities, { search: false, onRow: () => { location.hash = "#/ca/securities"; } })));
  if (d.variations.length) root.append(sec("Variations waiting", table([{ k: "no", label: "No." }, { k: "title", label: "Title" }, { k: "date", label: "Date" }, { k: "status", label: "Status" },
    { label: "Days waiting", v: (r) => r.age }], d.variations, { search: false, onRow: () => { location.hash = "#/p/variations"; } })));
  if (d.contract_items.length) root.append(sec("Contract register - due in 14 days", table([{ k: "contract", label: "Contract" }, { k: "title", label: "Item" }, { k: "due_date", label: "Due" }, { k: "state", label: "" }], d.contract_items, { search: false })));
  if (!d.timebars.length && !d.letters.length && !d.events.length && !d.securities.length) root.append(h("div", { class: "panel" }, "Nothing urgent on this project. Keep logging every letter in and out - the register is your evidence."));
};

/* ── correspondence register ── */
PAGES["ca/letters"] = async (root, params) => {
  if (need(root, "Correspondence register")) return;
  await cmeta(true);
  let v = { direction: "", category: "", status: "", q: "", open: params.open ? "1" : "" };
  const holder = h("div");
  const load = async () => {
    const d = await run("ca.letters", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    holder.append(table([{ label: "", v: (r) => (r.direction === "in" ? pill("IN", "#1769aa") : pill("OUT", "#2f7a4d")) }, { k: "our_no", label: "Reg. no." }, { k: "their_ref", label: "Their ref" },
      { k: "date", label: "Date" }, { k: "who", label: "From / to" }, { k: "subject", label: "Subject" }, { label: "Type", v: (r) => lab(CM.categories, r.category) },
      { k: "clause", label: "Clause" }, { label: "Reply by", v: (r) => (r.reply_needed && r.status === "open" ? late(r.reply_by, r.overdue) : "") }, { k: "assignee", label: "With" },
      { label: "Status", v: (r) => st(r.status, CM.status) }],
    d.rows, { name: "correspondence", title: "Correspondence register", empty: "No letter logged yet.", rowClass: (r) => (r.overdue ? "flag" : ""), onRow: (r) => letterView(r.id, load) }));
    if (d.reply_stats.length) holder.append(h("div", { class: "panel" }, h("h2", {}, "How fast letters are answered"),
      table([{ k: "who", label: "" }, { k: "n", label: "Letters answered" }, { k: "avg_days", label: "Average days" }, { k: "late", label: "Answered after the reply-by date" }], d.reply_stats, { search: false })));
  };
  root.append(pageHead("Correspondence register", "Every letter in and out with its register number, reply-by date, who must act and the letter it answers. Attach the scanned copy.",
    CM.can_edit ? h("button", { class: "btn primary", onclick: () => letterForm({ direction: "in" }, load) }, "Log incoming") : null,
    CM.can_edit ? h("button", { class: "btn", onclick: () => letterForm({ direction: "out" }, load) }, "Write outgoing") : null),
  filterBar([{ k: "direction", label: "In / out", type: "select", blank: "Both", options: [["in", "Incoming"], ["out", "Outgoing"]] },
    { k: "category", label: "Type", type: "select", blank: "All", options: CM.categories }, { k: "status", label: "Status", type: "select", blank: "All", options: CM.status },
    { k: "open", label: "Show", type: "select", noBlank: true, options: [["", "All letters"], ["1", "Waiting for our reply"]] }, { k: "q", label: "Search" }], v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.id) letterView(params.id, load);
  if (params.new && CM.can_edit) {
    const base = { direction: params.new === "out" ? "out" : "in" };
    if (params.event) {
      base.event_id = params.event; base.category = "notice";
      const dr = await run("ca.draft", { kind: "claim_notice", event_id: params.event });
      Object.assign(base, { subject: dr.subject, body: dr.body });
    }
    letterForm(base, load);
  }
};

function letterForm(r, done) {
  const out = r.direction === "out";
  const fields = [
    { k: "date", label: out ? "Letter date" : "Letter date (on the letter)", type: "date", req: true },
    out ? null : { k: "their_ref", label: "Their reference no." },
    { k: "party_id", label: out ? "To (party)" : "From (party)", type: "select", options: partyOpts },
    out ? null : { k: "assigned_to", label: "Who acts on it", type: "select", options: userOpts },
    out ? null : { k: "received_on", label: "Received on", type: "date" },
    { k: out ? "to_name" : "from_name", label: out ? "To (name / office, if not a party)" : "From (name / office, if not a party)" },
    { k: "subject", label: "Subject", req: true, wide: true },
    { k: "category", label: "Type", type: "select", noBlank: true, options: CM.categories },
    { k: "clause", label: "Contract clause" },
    { k: "summary", label: "Summary (what they say / what we ask)", type: "textarea", wide: true },
    { k: "reply_needed", label: out ? "We expect a reply" : "We must reply", type: "check" },
    { k: "reply_by", label: "Reply by", type: "date" },
    out ? { k: "assigned_to", label: "Who follows it up", type: "select", options: userOpts } : null,
    { k: "priority", label: "Priority", type: "select", noBlank: true, options: [["normal", "Normal"], ["high", "High"], ["urgent", "Urgent"]] },
    { k: "list_id", label: "Copy to (distribution list)", type: "select", options: listOpts },
    { k: "cc", label: "Copy to (others, text)" },
    { k: "contract_id", label: "Contract", type: "select", options: () => CM.contracts.map((x) => [x.id, (x.ref_no || "") + " " + x.title]) },
    { k: "event_id", label: "Event / claim", type: "select", options: () => CM.events.map((x) => [x.id, x.no + " " + x.title]) },
    out ? { k: "timebar_id", label: "This is the notice for time bar", type: "select", options: [] } : null,
    out ? { k: "body", label: "Letter text", type: "textarea", wide: true } : null,
  ].filter(Boolean);
  const wk = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  const vals = Object.assign({ date: today(), category: "general", priority: "normal", reply_needed: out ? 0 : 1 }, out || r.id ? {} : { reply_by: wk, received_on: today() }, r);
  const f = form(fields, vals);
  const tbSel = f.querySelector('[name="timebar_id"]');
  if (tbSel) run("ca.timebars", { project_id: S.project, running: 1 }).then((rows) => rows.forEach((t) => tbSel.append(h("option", { value: t.id, selected: String(t.id) === String(r.timebar_id) }, (t.clause || "") + " " + t.title + " - by " + t.due_date))));
  const file = h("input", { type: "file", multiple: true });
  const draftBar = out ? h("div", { class: "bar" }, h("span", { class: "hint" }, "Start from a draft: "),
    [["claim_notice", "Notice of claim"], ["eot_request", "EOT request"], ["instruction_request", "Request for instruction"], ["variation_notice", "Notice of variation"], ["payment_reminder", "Payment reminder"], ["acknowledge", "Acknowledgement"]]
      .map(([k, t]) => h("button", { class: "btn small", type: "button", onclick: async () => {
        const v = f.values();
        const dr = await run("ca.draft", { kind: k, event_id: v.event_id || null, letter_id: r.in_reply_to || null, timebar_id: v.timebar_id || null, clause: v.clause || null });
        f.set("subject", v.subject || dr.subject); f.set("category", dr.category); f.set("body", dr.body);
      } }, t))) : null;
  modal(r.id ? "Letter " + (r.our_no || "") : out ? "Write outgoing letter" : "Log incoming letter",
    h("div", {}, out ? T("BuildCore gives the register number. Write or paste the text, print it on letterhead, and attach the signed copy.") : T("Write what it says in two lines, set who must act and the reply-by date. Attach the scan."), draftBar, f,
      h("label", {}, "Scanned letter / attachments ", file)),
    [{ label: "Save", cls: "primary", act: async () => {
      const v = f.values();
      const x = await run("ca.letter_save", { row: Object.assign({}, r, v, { project_id: S.project }) }, (y) => "Saved as " + y.our_no);
      for (const fl of file.files) await upload1(fl, { entity: "ca_letters", entity_id: x.id, project_id: S.project, caption: v.subject });
      done && done();
    } }]);
}

async function letterView(id, done) {
  const r = await run("ca.letter_get", { id });
  const body = h("div", {},
    kv([["Register no.", r.our_no], ["Their reference", r.their_ref], ["Date", r.date + (r.received_on && r.received_on !== r.date ? " (received " + r.received_on + ")" : "")],
      [r.direction === "in" ? "From" : "To", r.who], ["Type", lab(CM.categories, r.category)], ["Clause", r.clause], ["Status", st(r.status, CM.status)],
      ["Reply by", r.reply_needed ? late(r.reply_by, r.overdue) : "not needed"], ["With", r.assignee], ["Copies", [r.list_text, r.cc].filter(Boolean).join("; ")],
      r.timebar ? ["Time bar", r.timebar.title + " - due " + r.timebar.due_date + " (" + r.timebar.status + ")"] : null]),
    r.summary ? h("p", {}, h("b", {}, "Summary: "), r.summary) : null,
    r.body ? h("pre", { style: "white-space:pre-wrap;font-family:inherit;background:#f9fafb;padding:10px;border-radius:6px" }, r.body) : null,
    r.chain.length > 1 ? h("div", {}, h("h3", {}, "The whole exchange"), table([{ label: "", v: (x) => (x.direction === "in" ? "IN" : "OUT") }, { k: "our_no", label: "No." }, { k: "date", label: "Date" }, { k: "who", label: "From / to" }, { k: "subject", label: "Subject" }, { label: "", v: (x) => st(x.status, CM.status) }],
      r.chain, { search: false, export: false, rowClass: (x) => (x.id === r.id ? "flag" : ""), onRow: (x) => { if (x.id !== r.id) letterView(x.id, done); } })) : null,
    recordPanel("ca_letters", r.id, { project_id: S.project }));
  const btns = [];
  if (CM.can_edit) {
    btns.push({ label: r.direction === "in" ? "Reply" : "Log their reply", cls: "primary", act: () => letterForm({ direction: r.direction === "in" ? "out" : "in", in_reply_to: r.id, party_id: r.party_id,
      subject: "Re: " + r.subject, clause: r.clause, contract_id: r.contract_id, event_id: r.event_id, category: r.category }, done) });
    btns.push({ label: "Edit", act: () => letterForm(r, done) });
    if (r.status === "open") btns.push({ label: "Close (no reply needed)", act: async () => { await run("ca.letter_save", { row: { id: r.id, status: "closed" } }, "Closed"); done && done(); } });
  }
  btns.push({ label: "Discuss", act: () => discuss("ca_letters", r.id, r.our_no + " " + r.subject) });
  if (r.direction === "out") btns.push({ label: "Print letter", keep: true, act: () => {
    const box = h("div", {}, h("p", {}, "Ref: " + r.our_no, h("span", { style: "float:right" }, "Date: " + r.date)), h("p", {}, "To: ", r.who), h("p", {}, h("b", {}, "Subject: " + r.subject)),
      r.clause ? h("p", {}, "Contract clause: " + r.clause) : null, h("div", { style: "white-space:pre-wrap;margin:14px 0" }, r.body || r.summary || ""), h("p", { style: "margin-top:40px" }, "......................................", h("br"), "Authorised signatory"),
      r.list_text || r.cc ? h("p", { style: "font-size:12px" }, "Copy: " + [r.list_text, r.cc].filter(Boolean).join("; ")) : null);
    printFrame("Letter " + r.our_no, box);
  } });
  modal((r.direction === "in" ? "Incoming " : "Outgoing ") + r.our_no + " — " + r.subject, body, btns);
}

/* ── notices and time bars ── */
PAGES["ca/timebars"] = async (root) => {
  if (need(root, "Notices and time bars")) return;
  await cmeta(true);
  const runningTab = async () => {
    const rows = await run("ca.timebars", { project_id: S.project });
    return table([{ label: "", v: (r) => (r.status === "running" ? (r.days_left < 0 ? pill("MISSED", "#b42318") : r.days_left <= 7 ? pill(r.state, "#c05621") : r.state) : st(r.status)) },
      { k: "clause", label: "Clause" }, { k: "title", label: "Notice / submission" }, { k: "party", label: "By" }, { k: "trigger_date", label: "Clock started" }, { k: "due_date", label: "Last day" },
      { k: "done_date", label: "Given on" }, { k: "letter_no", label: "Letter" }, { k: "event_no", label: "Event" }, { k: "notes", label: "Notes" }],
    rows, { name: "time_bars", empty: "No clock running. Start one when something happens that the contract gives a time limit for.", onRow: (r) => tbDialog(r) });
  };
  const libTab = async () => {
    const rows = await run("ca.clauses", { project_id: S.project });
    return h("div", {}, T("Starter time limits from the published FIDIC forms. Your contract's Particular Conditions (and the Nepal PPMO standard bidding documents) can change the days - add your own clauses for this contract."),
      CM.can_edit ? h("button", { class: "btn", onclick: () => clauseDialog(null) }, "Add a clause of this contract") : null,
      table([{ k: "form", label: "Form" }, { k: "clause", label: "Clause" }, { k: "title", label: "What" }, { k: "party", label: "Who" }, { k: "days", label: "Days" },
        { k: "trigger", label: "Counted from" }, { label: "Then", v: (r) => (r.follow_title ? r.follow_title + " - " + r.follow_days + " days" : "") }], rows, { name: "contract_clauses", onRow: (r) => (CM.can_edit ? clauseDialog(r) : null) }));
  };
  root.append(pageHead("Notices and time bars", "Miss a notice and the claim can be lost. Start the clock when the event happens; the notice letter you write against it stops the clock.",
    CM.can_edit ? h("button", { class: "btn primary", onclick: () => startDialog() }, "Start a clock") : null), tabs([["Running and past", runningTab], ["Clause library", libTab]]));

  function startDialog() {
    const f = form([{ k: "clause_id", label: "Clause", type: "select", req: true, options: CM.clauses.map((x) => [x.id, x.form + " " + x.clause + " - " + x.title + " (" + x.days + " d)"]), search: true },
      { k: "trigger_date", label: "Event happened / we became aware on", type: "date", default: today(), req: true },
      { k: "event_id", label: "Event", type: "select", options: CM.events.map((x) => [x.id, x.no + " " + x.title]) }, { k: "notes", label: "What happened", type: "textarea", wide: true }]);
    modal("Start a time-bar clock", f, [{ label: "Start", cls: "primary", act: async () => { await run("ca.timebar_start", Object.assign(f.values(), { project_id: S.project }), (x) => "Clock started - last day " + x.due_date); go(); } }]);
  }
  function tbDialog(r) {
    const f = form([{ k: "status", label: "Status", type: "select", noBlank: true, options: [["running", "Running"], ["done", "Notice given"], ["waived", "Waived / agreed"], ["not_needed", "Not needed"]] },
      { k: "done_date", label: "Given on", type: "date" }, { k: "notes", label: "Notes", type: "textarea", wide: true }], r);
    const btns = CM.can_edit ? [{ label: "Save", cls: "primary", act: async () => { await run("ca.timebar_set", Object.assign(f.values(), { id: r.id }), (x) => (x.status === "late" ? "Saved - given after the last day" : "Saved")); go(); } },
      { label: "Write the notice letter", act: () => { location.hash = "#/ca/letters?new=out" + (r.event_id ? "&event=" + r.event_id : ""); } }] : [];
    modal((r.clause || "") + " " + r.title, h("div", {}, kv([["Clock started", r.trigger_date], ["Last day", r.due_date], ["By", r.party], ["Letter", r.letter_no]]), f), btns);
  }
  function clauseDialog(r) {
    const f = form([{ k: "form", label: "Contract / form", default: "This contract" }, { k: "clause", label: "Clause no.", req: true }, { k: "title", label: "What must be given / done", req: true },
      { k: "party", label: "Who" }, { k: "days", label: "Days", type: "number", req: true }, { k: "trigger", label: "Counted from" },
      { k: "follow_title", label: "Then (e.g. detailed claim)" }, { k: "follow_days", label: "Days for that (from the same start)", type: "number" }, { k: "consequence", label: "If missed", wide: true }], r || {});
    modal(r ? "Clause " + r.clause : "Add a clause", f, [{ label: "Save", cls: "primary", act: async () => { await run("ca.clause_save", { row: Object.assign(f.values(), { id: r && r.id, project_id: S.project }) }, "Saved"); await cmeta(true); go(); } }]);
  }
};

/* ── bonds, guarantees and insurance ── */
PAGES["ca/securities"] = async (root) => {
  await cmeta(true);
  const d = await run("ca.securities", { project_id: S.project || null });
  root.append(pageHead("Bonds, guarantees and insurance", "Performance security, advance and retention guarantees, CAR / third-party / workers insurance - with the expiry date, so none lapses unnoticed (and none is left with the bank after it should be returned).",
    CM.can_edit ? h("button", { class: "btn primary", onclick: () => secDialog({ project_id: S.project, status: "active", currency: "NPR" }) }, "Add") : null));
  const tot = Object.entries(d.live_total);
  if (tot.length) root.append(h("div", { class: "tiles" }, tot.map(([k, v]) => tile(lab(CM.sec_kinds, k), "Rs " + money(v)))));
  root.append(table([{ label: "What", v: (r) => lab(CM.sec_kinds, r.kind) }, { k: "number", label: "Number" }, { k: "issuer", label: "Bank / insurer" }, { k: "beneficiary", label: "In favour of" },
    { k: "project", label: "Project" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "issue_date", label: "Issued" }, { k: "expiry_date", label: "Expiry" },
    { label: "", v: (r) => (r.alert ? h("b", { class: "red" }, r.alert) : "") }, { label: "Status", v: (r) => st(r.status, CM.sec_status) }],
  d.rows, { name: "bonds_insurance", empty: "Nothing recorded yet.", rowClass: (r) => (r.alert ? "flag" : ""), onRow: (r) => secDialog(r) }));

  function secDialog(r) {
    const f = form([{ k: "kind", label: "What", type: "select", req: true, options: CM.sec_kinds }, { k: "number", label: "Guarantee / policy no." }, { k: "issuer", label: "Bank / insurer" },
      { k: "beneficiary", label: "In favour of" }, { k: "party_id", label: "Party", type: "select", options: partyOpts }, { k: "project_id", label: "Project", type: "select", options: opt.projects },
      { k: "contract_id", label: "Contract", type: "select", options: () => CM.contracts.map((x) => [x.id, (x.ref_no || "") + " " + x.title]) },
      { k: "amount", label: "Amount", type: "number" }, { k: "currency", label: "Currency" }, { k: "issue_date", label: "Issue date", type: "date" },
      { k: "expiry_date", label: "Expiry date", type: "date", req: true }, { k: "claim_until", label: "Claim period ends", type: "date" },
      { k: "status", label: "Status", type: "select", noBlank: true, options: CM.sec_status }, { k: "released_on", label: "Released / returned on", type: "date" }, { k: "remarks", label: "Remarks", wide: true }], r);
    let hist = [];
    try { hist = JSON.parse(r.history || "[]"); } catch (e) { hist = []; }
    modal(r.id ? lab(CM.sec_kinds, r.kind) + " " + (r.number || "") : "Add bond / guarantee / insurance", h("div", {}, f,
      hist.length ? h("div", {}, h("h3", {}, "Changes"), table([{ k: "date", label: "Date" }, { k: "what", label: "Changed" }, { k: "from", label: "From" }, { k: "to", label: "To" }, { k: "by", label: "By" }], hist, { search: false, export: false })) : null,
      r.id ? recordPanel("ca_securities", r.id, { project_id: r.project_id || S.project }) : null),
    CM.can_edit ? [{ label: "Save", cls: "primary", act: async () => { await run("ca.security_save", { row: Object.assign(f.values(), { id: r.id }) }, "Saved"); go(); } }] : []);
  }
};

/* ═══════════════ communication ═══════════════ */
async function discuss(entity, id, title) {
  const list = await run("cm.threads", { entity, entity_id: id, closed: 1 });
  if (list.length) { location.hash = "#/cm?id=" + list[0].id; document.querySelectorAll(".overlay").forEach((x) => x.remove()); return; }
  await cmeta();
  const f = form([{ k: "body", label: "First message (use @username to call someone in)", type: "textarea", wide: true, req: true }]);
  modal("Start a discussion on " + title, f, [{ label: "Post", cls: "primary", act: async () => {
    const x = await run("cm.thread_new", { title, entity, entity_id: id, project_id: S.project || null, body: f.values().body }, (y) => (y.mentioned ? "Posted - " + y.mentioned + " person(s) told" : "Posted"));
    document.querySelectorAll(".overlay").forEach((o) => o.remove());
    location.hash = "#/cm?id=" + x.id;
  } }]);
}
window.bcoDiscuss = discuss;

PAGES.cm = async (root, params) => {
  await cmeta();
  if (params.id) return threadPage(root, params.id);
  let v = { q: "", closed: "" };
  const holder = h("div");
  const load = async () => {
    const rows = await run("cm.threads", Object.assign({ project_id: S.project || null }, v));
    holder.innerHTML = "";
    if (!rows.length) { holder.append(h("div", { class: "panel" }, "No discussion yet. Start one - for a site problem, a decision, a drawing question. Use @username to call people in.")); return; }
    rows.forEach((t) => holder.append(h("div", { class: "panel", style: "cursor:pointer;margin-bottom:8px" + (t.unread ? ";border-left:4px solid #1769aa" : ""), onclick: () => { location.hash = "#/cm?id=" + t.id; } },
      h("div", { class: "bar" }, t.pinned ? h("span", {}, "📌") : null, t.kind === "announcement" ? pill("Announcement", "#7a5af8") : null, h("b", {}, t.title), h("div", { class: "grow" }),
        t.unread ? pill(t.unread + " new", "#1769aa") : null, h("small", { class: "muted" }, (t.project || "") + " · " + t.posts + " messages · " + (t.last_ts || "").slice(0, 16).replace("T", " "))),
      h("small", { class: "muted" }, (t.last_by ? t.last_by + ": " : "") + t.last_body))));
  };
  root.append(pageHead("Discussions", "Talk about the work where everyone can see it - instead of scattered phone calls. Mention people with @username; they get it in their bell and in My work.",
    h("button", { class: "btn primary", onclick: () => newThread() }, "New discussion"), h("a", { class: "btn", href: "#/inbox" }, "My inbox")),
  filterBar([{ k: "q", label: "Search" }, { k: "closed", label: "Show", type: "select", noBlank: true, options: [["", "Open"], ["1", "Open and closed"]] }], v, (x) => { v = x; load(); }), holder);
  await load();

  function newThread() {
    const f = form([{ k: "title", label: "Subject", req: true, wide: true }, { k: "body", label: "Message (use @username)", type: "textarea", wide: true, req: true },
      { k: "list_id", label: "Tell this distribution list", type: "select", options: listOpts },
      can("project", "approve") ? { k: "kind", label: "Kind", type: "select", noBlank: true, options: [["discussion", "Discussion"], ["announcement", "Announcement to everyone (pinned)"]] } : null].filter(Boolean));
    modal("New discussion", h("div", {}, f, h("p", { class: "hint" }, "People: " + CM.users.map((u) => "@" + u.username).join("  "))), [{ label: "Post", cls: "primary", act: async () => {
      const x = await run("cm.thread_new", Object.assign(f.values(), { project_id: S.project || null }), "Posted");
      location.hash = "#/cm?id=" + x.id;
    } }]);
  }
};

async function threadPage(root, id) {
  const t = await run("cm.thread_get", { id });
  const box = h("div");
  const esc = (s) => String(s || "").replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
  const fmt = (s) => esc(s).replace(/@([A-Za-z0-9_.\-]{2,40})/g, '<b style="color:#1769aa">@$1</b>').replace(/\n/g, "<br>");
  t.posts.forEach((p) => {
    const b = h("div", {}); b.innerHTML = fmt(p.body);
    box.append(h("div", { class: "panel", style: "margin-bottom:8px" + (p.user_id === S.user.id ? ";background:#f5f9ff" : "") },
      h("div", { class: "bar" }, h("b", {}, p.author || "?"), h("small", { class: "muted" }, "@" + (p.username || "") + " · " + (p.ts || "").slice(0, 16).replace("T", " "))), b,
      p.files.length ? h("div", {}, p.files.map((f) => h("a", { href: fileUrl(f.id), target: "_blank", style: "margin-right:10px" }, "📎 " + f.filename))) : null));
  });
  const ta = h("textarea", { placeholder: "Write a reply. @username calls someone in.", style: "width:100%;min-height:80px" });
  const file = h("input", { type: "file", multiple: true });
  const send = h("button", { class: "btn primary", onclick: async () => {
    if (!ta.value.trim()) return;
    send.disabled = true;
    try {
      const x = await run("cm.post", { thread_id: t.id, body: ta.value });
      for (const fl of file.files) await upload1(fl, { entity: "cm_posts", entity_id: x.id, project_id: t.project_id || S.project });
      go();
    } finally { send.disabled = false; }
  } }, "Send");
  const mine = t.created_by === S.user.id || can("project", "approve");
  root.append(pageHead(t.title, (t.project ? t.project + " · " : "") + "started by " + (t.started_by || "") + (t.closed ? " · closed" : ""),
    t.link ? h("a", { class: "btn", href: t.link }, "Open the record") : null, h("a", { class: "btn", href: "#/cm" }, "All discussions"),
    mine ? h("button", { class: "btn", onclick: async () => { await run("cm.thread_set", { id: t.id, pinned: t.pinned ? 0 : 1 }); go(); } }, t.pinned ? "Unpin" : "Pin") : null,
    mine ? h("button", { class: "btn", onclick: async () => { await run("cm.thread_set", { id: t.id, closed: t.closed ? 0 : 1 }); go(); } }, t.closed ? "Open again" : "Close") : null),
  box, t.closed ? h("p", { class: "muted" }, "This discussion is closed.") : h("div", { class: "panel" }, ta, h("div", { class: "bar" }, file, h("div", { class: "grow" }), send),
    h("p", { class: "hint" }, "People: " + CM.users.map((u) => "@" + u.username).join("  "))));
  ta.focus();
}

PAGES.inbox = async (root) => {
  const d = await run("cm.inbox", { all: 1 });
  const rv = await run("dm.review_queue", {});
  root.append(pageHead("Inbox & mentions", "Mentions, replies, letters given to you, documents to review and transmittals - newest first.",
    h("button", { class: "btn", onclick: async () => { await run("cm.mark_read", {}, "All marked read"); bell.refresh(); go(); } }, "Mark all read"), h("a", { class: "btn", href: "#/cm" }, "Discussions")));
  root.append(h("div", { class: "tiles" }, tile("Unread", d.unread, { cls: d.unread ? "warn" : "" }), tile("Discussions with new messages", d.unread_threads, { href: "#/cm" }), tile("Documents to review", rv.length, { cls: rv.some((x) => x.overdue) ? "bad" : "" })));
  if (rv.length) root.append(h("div", { class: "panel" }, h("h2", {}, "Documents waiting for your review"), table([{ k: "project", label: "Project" }, { k: "doc_no", label: "Document" }, { k: "rev", label: "Rev" }, { k: "title", label: "Title" },
    { label: "Due", v: (r) => late(r.due_date, r.overdue) }], rv, { search: false, onRow: (r) => { location.hash = "#/dm?doc=" + r.doc_id; } })));
  root.append(table([{ label: "", v: (n) => (n.read_at ? "" : pill("new", "#1769aa")) }, { label: "What", v: (n) => ({ mention: "Mention", reply: "Reply", letter: "Letter", review: "Review", transmittal: "Transmittal" }[n.kind] || n.kind) },
    { k: "title", label: "" }, { label: "", v: (n) => h("small", { class: "muted" }, (n.body || "").slice(0, 120)) }, { k: "project", label: "Project" }, { label: "When", v: (n) => (n.ts || "").slice(0, 16).replace("T", " ") }],
  d.notes, { name: "inbox", empty: "Nothing here.", rowClass: (n) => (n.read_at ? "" : "flag"), onRow: async (n) => { await api("cm.mark_read", { id: n.id }); bell.refresh(); location.hash = n.link; } }));
};

PAGES["cm/directory"] = async (root) => {
  await cmeta(true);
  const d = await run("cm.contacts", { project_id: S.project || null });
  const lists = await run("cm.lists", { project_id: S.project || null });
  const ed = can("project", "edit");
  const peopleTab = () => h("div", {}, ed ? h("button", { class: "btn", onclick: () => contact({ project_id: S.project }) }, "Add a person") : null,
    table([{ k: "name", label: "Name" }, { k: "org", label: "Organisation" }, { k: "role", label: "Role" }, { k: "phone", label: "Phone" }, { k: "email", label: "Email" }, { k: "party", label: "Party" }],
      d.contacts, { name: "project_directory", empty: "Add the client's engineer, consultant, subcontractor and supplier contacts.", onRow: ed ? (r) => contact(r) : null }),
    h("h3", {}, "BuildCore users"), table([{ k: "name", label: "Name" }, { label: "Mention as", v: (u) => "@" + u.username }, { label: "Role", v: (u) => u.role.replace(/_/g, " ") }], d.users, { search: false }));
  const listTab = () => h("div", {}, ed ? h("button", { class: "btn", onclick: () => listDialog({ project_id: S.project, members: [] }) }, "New distribution list") : null,
    table([{ k: "name", label: "List" }, { k: "text", label: "Members" }], lists, { empty: "A list sends copies of letters, transmittals and discussions to a group in one pick.", onRow: ed ? (r) => listDialog(r) : null }));
  root.append(pageHead("Project directory & distribution lists", "Everyone on the project in one place, and the groups you copy letters and transmittals to."), tabs([["People", peopleTab], ["Distribution lists", listTab]]));

  function contact(r) {
    const f = form([{ k: "name", label: "Name", req: true }, { k: "org", label: "Organisation" }, { k: "role", label: "Role" }, { k: "phone", label: "Phone" }, { k: "email", label: "Email" },
      { k: "party_id", label: "Party", type: "select", options: partyOpts }, { k: "project_id", label: "Project (blank = all)", type: "select", options: opt.projects }, { k: "notes", label: "Notes", wide: true },
      r.id ? { k: "active", label: "Active", type: "check" } : null].filter(Boolean), r);
    modal(r.id ? r.name : "Add a person", f, [{ label: "Save", cls: "primary", act: async () => { await run("cm.contact_save", { row: Object.assign(f.values(), { id: r.id }) }, "Saved"); go(); } }]);
  }
  function listDialog(r) {
    const name = h("input", { value: r.name || "" });
    const mem = (r.members || []).slice();
    const box = h("div");
    const draw = () => { box.innerHTML = ""; mem.forEach((m, i) => box.append(h("div", { class: "bar" }, h("span", {}, m.user_id ? "👤 " + (CM.users.find((u) => u.id === m.user_id) || {}).name : "✉ " + m.name + (m.org ? " (" + m.org + ")" : "") + (m.email ? " " + m.email : "")),
      h("button", { class: "btn small", onclick: () => { mem.splice(i, 1); draw(); } }, "Remove")))); };
    draw();
    const us = h("select", {}, h("option", { value: "" }, "— add a BuildCore user —"), CM.users.map((u) => h("option", { value: u.id }, u.name)));
    us.onchange = () => { if (us.value) { mem.push({ user_id: Number(us.value) }); us.value = ""; draw(); } };
    const ext = form([{ k: "name", label: "Outside person - name" }, { k: "org", label: "Organisation" }, { k: "email", label: "Email" }]);
    modal(r.id ? "List " + r.name : "New distribution list", h("div", {}, h("label", { class: "f" }, h("span", {}, "List name"), name), box, us, ext,
      h("button", { class: "btn small", onclick: () => { const v = ext.values(); if (v.name) { mem.push(v); ["name", "org", "email"].forEach((k) => ext.set(k, "")); draw(); } } }, "Add outside person")),
    [{ label: "Save", cls: "primary", act: async () => { await run("cm.list_save", { row: { id: r.id, name: name.value, project_id: r.project_id || S.project || null, members: mem } }, "Saved"); await cmeta(true); go(); } }]);
  }
};

/* the bell in the top bar */
const bell = { n: 0, el: null, refresh: async () => { try { const x = await api("cm.unread", {}); bell.n = x.unread; bell.draw(); } catch (e) { /* offline */ } },
  draw: () => { if (!bell.el) return; bell.el.textContent = "🔔" + (bell.n ? " " + bell.n : ""); bell.el.classList.toggle("primary", !!bell.n); } };
setInterval(() => {
  const top = document.querySelector(".main .top");
  if (!top || !S.user || document.getElementById("bcoBell")) return;
  bell.el = h("button", { id: "bcoBell", class: "btn small", title: "Inbox & mentions", onclick: () => { location.hash = "#/inbox"; } }, "🔔");
  const who = top.querySelector(".who");
  top.insertBefore(bell.el, who || null);
  bell.refresh();
}, 1200);
setInterval(() => { if (S.user && document.getElementById("bcoBell")) bell.refresh(); }, 60000);

/* ═══════════════ document control ═══════════════ */
PAGES.dm = async (root, params) => {
  if (need(root, "Document control")) return;
  await cmeta(true);
  let F = await run("dm.folders", { project_id: S.project });
  let folder = params.folder || "";
  let v = { q: "", doc_type: "", status: "", discipline: "" };
  const side = h("div", { class: "panel", style: "min-width:220px;flex:0 0 240px" });
  const holder = h("div", { style: "flex:1;min-width:0" });
  const drawSide = () => {
    side.innerHTML = "";
    side.append(h("b", {}, "Folders"));
    const it = (id, name, n) => h("div", { style: "padding:5px 6px;border-radius:5px;cursor:pointer;" + (String(folder) === String(id) ? "background:#eef4ff;font-weight:700" : ""), onclick: () => { folder = id; drawSide(); load(); } }, "📁 " + name + (n != null ? " (" + n + ")" : ""));
    side.append(it("", "All documents", null));
    F.folders.forEach((x) => side.append(it(x.id, x.name, x.docs)));
    if (can("project", "edit")) side.append(h("button", { class: "btn small", style: "margin-top:8px", onclick: async () => {
      const n = await ask("New folder", "Name of the folder", { input: "e.g. 11 Survey data", required: true });
      if (n) { await run("dm.folder_save", { row: { project_id: S.project, name: n } }, "Folder made"); F = await run("dm.folders", { project_id: S.project }); drawSide(); }
    } }, "+ Folder"));
    side.append(h("p", { class: "hint", style: "margin-top:10px" }, "Number pattern: ", h("code", {}, F.settings.pattern)),
      can("project", "approve") ? h("button", { class: "btn small", onclick: () => numbering() }, "Change numbering") : null);
  };
  const load = async () => {
    const rows = await run("dm.docs", Object.assign({ project_id: S.project, folder_id: folder || null }, v));
    holder.innerHTML = "";
    holder.append(table([{ k: "doc_no", label: "Document no." }, { k: "title", label: "Title" }, { label: "Type", v: (r) => lab(CM.doc_types, r.doc_type) }, { k: "discipline", label: "Discipline" },
      { k: "current_rev", label: "Rev" }, { label: "Status", v: (r) => st(r.rev_status || r.status, CM.rev_status) }, { label: "Reviews open", v: (r) => r.reviews_open || "" },
      { k: "folder", label: "Folder" }, { label: "File", v: (r) => (r.file_id ? h("a", { href: fileUrl(r.file_id), target: "_blank", onclick: (e) => e.stopPropagation() }, r.filename || "open") : "") },
      { label: "Updated", v: (r) => (r.updated || "").slice(0, 10) }],
    rows, { name: "document_register", title: "Document register", empty: "No document here yet.", onRow: (r) => docView(r.id, load) }));
  };
  root.append(pageHead("Document control", "One register for every controlled document: its number, current revision, review status and who it was sent to. New revisions supersede the old; nothing is deleted.",
    can("project", "edit") ? h("button", { class: "btn primary", onclick: () => newDoc() }, "Add document") : null,
    h("a", { class: "btn", href: "#/dm/transmittals" }, "Transmittals"),
    h("button", { class: "btn", onclick: async () => dl(await run("dm.register_xlsx", Object.assign({ project_id: S.project, folder_id: folder || null }, v))) }, "Register to Excel")),
  F.pending_reviews ? h("div", { class: "panel warn" }, F.pending_reviews + " review(s) open in this project.") : null,
  filterBar([{ k: "q", label: "Search number / title" }, { k: "doc_type", label: "Type", type: "select", blank: "All", options: CM.doc_types },
    { k: "discipline", label: "Discipline", type: "select", blank: "All", options: CM.disciplines.map((x) => [x, x]) }, { k: "status", label: "Status", type: "select", blank: "All", options: CM.rev_status }], v, (x) => { v = x; load(); }),
  h("div", { style: "display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap" }, side, holder));
  drawSide();
  await load();
  if (params.doc) docView(params.doc, load);

  function numbering() {
    const f = form([{ k: "pattern", label: "Pattern", req: true, hint: "{P} project code, {ORG} originator, {DISC} discipline, {TYPE} document type, {SEQ} running number" }, { k: "org", label: "Our originator code (for {ORG})" }], F.settings);
    modal("Document numbering", f, [{ label: "Save", cls: "primary", act: async () => { await run("dm.settings_save", Object.assign(f.values(), { project_id: S.project }), "Saved"); F = await run("dm.folders", { project_id: S.project }); drawSide(); } }], { narrow: true });
  }
  function newDoc() {
    const file = h("input", { type: "file" });
    const f = form([{ k: "title", label: "Title", req: true, wide: true }, { k: "doc_type", label: "Type", type: "select", noBlank: true, options: CM.doc_types },
      { k: "discipline", label: "Discipline", type: "select", noBlank: true, options: CM.disciplines.map((x) => [x, x]) },
      { k: "folder_id", label: "Folder", type: "select", options: F.folders.map((x) => [x.id, x.name]) }, { k: "doc_no", label: "Document no. (blank = BuildCore makes it)" },
      { k: "originator", label: "Originator (who made it)" }, { k: "rev", label: "First revision", default: "0" },
      { k: "rev_status", label: "Start as", type: "select", noBlank: true, options: [["draft", "Draft (to review)"], ["for_info", "Issued / for information"], ["approved", "Already approved"]] },
      { k: "tags", label: "Keywords" }, { k: "confidential", label: "Confidential (managers only)", type: "check" }], { doc_type: "DRG", discipline: "Civil", folder_id: folder || "", rev: "0", rev_status: "draft" });
    modal("Add a controlled document", h("div", {}, f, h("label", {}, "File ", file)), [{ label: "Save", cls: "primary", act: async () => {
      const vv = f.values();
      let fid = null;
      if (file.files[0]) fid = await upload1(file.files[0], { project_id: S.project, kind: "document", caption: vv.title });
      const x = await run("dm.doc_save", { row: Object.assign(vv, { project_id: S.project, file_id: fid }) }, (y) => "Saved as " + y.doc_no);
      F = await run("dm.folders", { project_id: S.project }); drawSide(); await load(); docView(x.id, load);
    } }]);
  }
};

async function docView(id, done) {
  await cmeta();
  const d = await run("dm.doc_get", { id });
  const ed = can("project", "edit");
  const mineOpen = d.reviews.filter((r) => r.status === "pending" && (r.reviewer_id === S.user.id || S.user.role === "admin"));
  const revs = table([{ k: "rev", label: "Rev" }, { label: "Status", v: (r) => st(r.status, CM.rev_status) }, { k: "purpose", label: "Purpose" }, { k: "note", label: "Note" },
    { label: "File", v: (r) => (r.file_id ? h("a", { href: fileUrl(r.file_id), target: "_blank" }, r.filename || "open") : "") }, { k: "by_name", label: "By" }, { label: "Date", v: (r) => (r.ts || "").slice(0, 10) },
    { k: "review_due", label: "Review due" }, { label: "Result", v: (r) => r.result || "" },
    { label: "", v: (r) => (ed && ["draft", "for_info", "revise"].includes(r.status) && r.id === d.current_rev_id ? h("button", { class: "btn small", onclick: () => reviewStart(r) }, "Send for review") : "") }],
  d.revisions, { search: false, export: false });
  const reviews = d.reviews.length ? table([{ k: "rev", label: "Rev" }, { k: "step", label: "Step" }, { k: "reviewer", label: "Reviewer" }, { label: "Status", v: (r) => st(r.status) }, { k: "due_date", label: "Due" },
    { label: "Decision", v: (r) => (r.decision ? lab(CM.decisions, r.decision) : "") }, { k: "comment", label: "Comments" }, { k: "decided_on", label: "On" }], d.reviews, { search: false, export: false }) : h("p", { class: "muted" }, "Not reviewed yet.");
  const decideBox = mineOpen.length ? (() => {
    const f = form([{ k: "decision", label: "Your decision", type: "select", req: true, options: CM.decisions }, { k: "comment", label: "Comments", type: "textarea", wide: true }]);
    return h("div", { class: "panel warn" }, h("h3", {}, "Your review of rev " + mineOpen[0].rev), f, h("button", { class: "btn primary", onclick: async () => {
      const x = await run("dm.review_decide", Object.assign(f.values(), { id: mineOpen[0].id }), (y) => (y.finished ? "Decided - the review is complete" : "Decided - passed to the next reviewer"));
      document.querySelectorAll(".overlay").forEach((o) => o.remove()); bell.refresh(); done && done(); docView(id, done); return x;
    } }, "Submit decision"));
  })() : null;
  const trs = d.transmittals.length ? table([{ k: "no", label: "Transmittal" }, { k: "date", label: "Date" }, { k: "to_name", label: "To" }, { k: "rev", label: "Rev" }, { label: "Purpose", v: (r) => lab(CM.tr_purpose, r.purpose) }, { label: "Status", v: (r) => st(r.status) }],
    d.transmittals, { search: false, export: false, onRow: (r) => { location.hash = "#/dm/transmittals?id=" + r.id; } }) : h("p", { class: "muted" }, "Not sent out yet.");
  const body = h("div", {}, kv([["Document no.", h("b", {}, d.doc_no)], ["Title", d.title], ["Type", lab(CM.doc_types, d.doc_type)], ["Discipline", d.discipline], ["Folder", d.folder], ["Originator", d.originator],
    ["Current revision", (d.current_rev || "-") + " "], ["Status", st(d.rev_status || d.status, CM.rev_status)], ["Keywords", d.tags], d.confidential ? ["Confidential", "yes"] : null]),
  decideBox, h("h3", {}, "Revisions"), revs, h("h3", {}, "Reviews"), reviews, h("h3", {}, "Sent with transmittals"), trs);
  const btns = [];
  if (ed && d.active) {
    btns.push({ label: "New revision " + d.next_rev, cls: "primary", act: () => newRev() });
    btns.push({ label: "Edit card", act: () => editCard() });
    btns.push({ label: "Send (transmittal)", act: () => { location.hash = "#/dm/transmittals?new=1&doc=" + d.id; } });
  }
  btns.push({ label: "Discuss", act: () => discuss("dm_docs", d.id, d.doc_no + " " + d.title) });
  modal(d.doc_no + " — " + d.title, body, btns);

  function newRev() {
    const file = h("input", { type: "file" });
    const f = form([{ k: "rev", label: "Revision", default: d.next_rev, req: true }, { k: "purpose", label: "Purpose / reason" }, { k: "note", label: "What changed", wide: true },
      { k: "status", label: "Start as", type: "select", noBlank: true, options: [["draft", "Draft (to review)"], ["for_info", "Issued / for information"], ["approved", "Already approved"]] }]);
    modal("New revision of " + d.doc_no, h("div", {}, T("The current revision becomes superseded (one under review stays as it is)."), f, h("label", {}, "File ", file)), [{ label: "Save", cls: "primary", act: async () => {
      if (!file.files[0]) { toast("Attach the file of the new revision.", "err"); return false; }
      const fid = await upload1(file.files[0], { project_id: S.project, kind: "document", caption: d.doc_no + " rev " + f.values().rev });
      await run("dm.rev_add", Object.assign(f.values(), { doc_id: d.id, file_id: fid }), "Revision saved");
      document.querySelectorAll(".overlay").forEach((o) => o.remove()); done && done(); docView(id, done);
    } }]);
  }
  function editCard() {
    const f = form([{ k: "title", label: "Title", req: true, wide: true }, { k: "doc_type", label: "Type", type: "select", noBlank: true, options: CM.doc_types },
      { k: "discipline", label: "Discipline", type: "select", options: CM.disciplines.map((x) => [x, x]) }, { k: "folder_id", label: "Folder", type: "select", options: [] },
      { k: "originator", label: "Originator" }, { k: "tags", label: "Keywords" }, { k: "confidential", label: "Confidential", type: "check" }, { k: "active", label: "In use (untick to withdraw)", type: "check" }], d);
    run("dm.folders", { project_id: S.project }).then((F) => { const s = f.querySelector('[name="folder_id"]'); if (s && s.tagName === "SELECT") F.folders.forEach((x) => s.append(h("option", { value: x.id, selected: String(x.id) === String(d.folder_id) }, x.name))); });
    modal("Document card " + d.doc_no, f, [{ label: "Save", cls: "primary", act: async () => { await run("dm.doc_save", { row: Object.assign(f.values(), { id: d.id }) }, "Saved"); document.querySelectorAll(".overlay").forEach((o) => o.remove()); done && done(); } }]);
  }
  function reviewStart(rv) {
    const picks = h("div", {}, CM.users.map((u) => h("label", { style: "display:block" }, h("input", { type: "checkbox", value: u.id }), " " + u.name + " · " + u.role.replace(/_/g, " "))));
    const f = form([{ k: "mode", label: "How", type: "select", noBlank: true, options: [["parallel", "All at the same time"], ["sequential", "One after another (in the order ticked)"]] },
      { k: "due_date", label: "Review due", type: "date" }]);
    const order = [];
    picks.addEventListener("change", (e) => { const v = Number(e.target.value); const i = order.indexOf(v); if (e.target.checked && i < 0) order.push(v); if (!e.target.checked && i >= 0) order.splice(i, 1); });
    modal("Send " + d.doc_no + " rev " + rv.rev + " for review", h("div", {}, T("Each reviewer answers A approved, B approved with comments, C revise and resubmit, or D rejected. The worst answer is the result."), f, h("b", {}, "Reviewers"), picks),
      [{ label: "Send for review", cls: "primary", act: async () => {
        await run("dm.review_start", Object.assign(f.values(), { rev_id: rv.id, reviewers: order }), (x) => "Sent to " + x.reviewers + " reviewer(s), due " + x.due_date);
        document.querySelectorAll(".overlay").forEach((o) => o.remove()); done && done(); docView(id, done);
      } }]);
  }
}

PAGES["dm/transmittals"] = async (root, params) => {
  if (need(root, "Transmittals")) return;
  await cmeta(true);
  const rows = await run("dm.transmittals", { project_id: S.project });
  root.append(pageHead("Transmittals", "A transmittal is the cover sheet that records which documents (which revision) went to whom, why, and when they acknowledged it.",
    can("project", "edit") ? h("button", { class: "btn primary", onclick: () => trForm(null) }, "New transmittal") : null, h("a", { class: "btn", href: "#/dm" }, "Document control")),
  table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { label: "To", v: (r) => r.party || r.to_name }, { k: "subject", label: "Subject" }, { label: "Purpose", v: (r) => lab(CM.tr_purpose, r.purpose) },
    { k: "items", label: "Documents" }, { label: "Reply due", v: (r) => late(r.response_due, r.overdue) }, { label: "Status", v: (r) => st(r.status) }, { k: "ack_on", label: "Acknowledged" }],
  rows, { name: "transmittals", empty: "No transmittal yet.", rowClass: (r) => (r.overdue ? "flag" : ""), onRow: (r) => trView(r.id) }));
  if (params.id) trView(params.id);
  if (params.new) trForm(params.doc ? [Number(params.doc)] : []);

  async function trForm(preset) {
    const docs = await run("dm.docs", { project_id: S.project });
    const f = form([{ k: "party_id", label: "To (party)", type: "select", options: partyOpts }, { k: "to_name", label: "To (name / office)" }, { k: "attention", label: "Attention" },
      { k: "purpose", label: "Purpose", type: "select", noBlank: true, options: CM.tr_purpose }, { k: "subject", label: "Subject", wide: true }, { k: "date", label: "Date", type: "date", default: today() },
      { k: "response_due", label: "Reply due (for review / approval)", type: "date" }, { k: "list_id", label: "Copy to list", type: "select", options: listOpts }, { k: "remarks", label: "Remarks", wide: true }], { purpose: "for_information" });
    const sel = new Set(preset || []);
    const pick = table([{ label: "", v: (r) => { const c = h("input", { type: "checkbox", checked: sel.has(r.id) }); c.onclick = (e) => { e.stopPropagation(); if (c.checked) sel.add(r.id); else sel.delete(r.id); }; return c; } },
      { k: "doc_no", label: "Document" }, { k: "title", label: "Title" }, { k: "current_rev", label: "Rev" }, { label: "Status", v: (r) => st(r.rev_status || r.status, CM.rev_status) }], docs, { export: false });
    modal("New transmittal", h("div", {}, f, h("h3", {}, "Documents (the current revision of each goes)"), pick), [{ label: "Save draft", cls: "primary", act: async () => {
      const x = await run("dm.transmittal_save", { row: Object.assign(f.values(), { project_id: S.project }), items: [...sel].map((i) => ({ doc_id: i })) }, (y) => "Saved " + y.no);
      location.hash = "#/dm/transmittals?id=" + x.id;
    } }]);
  }
  async function trView(id) {
    const t = await run("dm.transmittal_get", { id });
    const btns = [];
    const ed = can("project", "edit");
    if (ed && t.status === "draft") btns.push({ label: "Mark as sent", cls: "primary", act: async () => { await run("dm.transmittal_send", { id: t.id }, "Sent"); go(); } });
    if (ed && t.status !== "draft" && t.status !== "closed") btns.push({ label: "Record acknowledgement / reply", act: () => {
      const f = form([{ k: "ack_on", label: "Acknowledged on", type: "date", default: today() }, { k: "ack_by", label: "Received by (name)" }, { k: "response", label: "Their reply / comments", type: "textarea", wide: true }, { k: "close", label: "Close this transmittal", type: "check" }]);
      modal("Acknowledgement " + t.no, f, [{ label: "Save", cls: "primary", act: async () => { await run("dm.transmittal_ack", Object.assign(f.values(), { id: t.id }), "Saved"); go(); } }]);
    } });
    btns.push({ label: "Print cover sheet", keep: true, act: () => {
      const box = h("div", {}, h("p", {}, h("b", {}, "TRANSMITTAL " + t.no), h("span", { style: "float:right" }, "Date: " + t.date)), h("p", {}, "Project: " + (t.project || "") + " " + (t.project_name || "")),
        h("p", {}, "To: " + (t.party || t.to_name || "") + (t.attention ? " - Attn: " + t.attention : "")), h("p", {}, "Purpose: " + lab(CM.tr_purpose, t.purpose) + (t.response_due ? " · reply by " + t.response_due : "")),
        t.subject ? h("p", {}, "Subject: " + t.subject) : null,
        h("table", {}, h("tr", {}, ["#", "Document no.", "Title", "Rev", "Copies", "Format"].map((x) => h("th", {}, x))), t.items.map((x, i) => h("tr", {}, [i + 1, x.doc_no, x.title, x.rev || "", x.copies, x.format].map((y) => h("td", {}, String(y)))))),
        t.remarks ? h("p", {}, "Remarks: " + t.remarks) : null, t.list_text ? h("p", { style: "font-size:12px" }, "Copy: " + t.list_text) : null,
        h("p", { style: "margin-top:30px" }, "Sent by: " + (t.by_name || "") + "  ..........................", h("span", { style: "float:right" }, "Received by: ..........................  Date: ..........")));
      printFrame("Transmittal " + t.no, box);
    } });
    modal("Transmittal " + t.no, h("div", {}, kv([["To", (t.party || t.to_name || "") + (t.attention ? " - Attn: " + t.attention : "")], ["Purpose", lab(CM.tr_purpose, t.purpose)], ["Date", t.date], ["Status", st(t.status)],
      ["Sent on", t.sent_on], ["Reply due", t.response_due], ["Acknowledged", t.ack_on ? t.ack_on + " by " + (t.ack_by || "") : ""], ["Their reply", t.response], ["Copy to", t.list_text]]),
    table([{ k: "doc_no", label: "Document" }, { k: "title", label: "Title" }, { k: "rev", label: "Rev" }, { k: "copies", label: "Copies" }, { k: "format", label: "Format" },
      { label: "File", v: (x) => (x.file_id ? h("a", { href: fileUrl(x.file_id), target: "_blank" }, "open") : "") }], t.items, { search: false, export: false, onRow: (x) => docView(x.doc_id) })), btns);
  }
};

})();
