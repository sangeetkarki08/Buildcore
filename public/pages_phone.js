/* BuildCore 2.57 — Site on the phone (#/phone): big buttons for today's DPR (copied from yesterday), goods received with
   challan photo, material issue, machine hours, petty cash slip, site issue with photo and location. Same actions,
   rights and checks as the desktop screens. Also: weighbridge number on the GRN form, more items in "+ New". */
(function () {
"use strict";
if (window.__bco257) return; window.__bco257 = true;
const css = ".ph{max-width:560px;margin:0 auto}.ph h2{margin:8px 0 12px}.ph-tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px}" +
  ".ph-tile{display:flex;flex-direction:column;justify-content:center;min-height:96px;border-radius:14px;padding:14px;border:1px solid var(--line,#d0d5dd);background:var(--panel,#fff);font-size:17px;font-weight:600;color:inherit;text-decoration:none;cursor:pointer}" +
  ".ph-tile small{font-weight:400;color:var(--muted,#667085);font-size:13px;margin-top:4px}.ph-tile .i{font-size:26px;margin-bottom:4px}" +
  ".ph label.f{display:block;margin:10px 0}.ph label.f>span{display:block;font-size:14px;margin-bottom:4px}.ph input,.ph select,.ph textarea{width:100%;font-size:17px;padding:10px;box-sizing:border-box;border-radius:10px}" +
  ".ph .big{width:100%;font-size:18px;padding:14px;border-radius:12px;margin-top:12px}.ph .row{display:grid;grid-template-columns:1fr 92px;gap:8px;align-items:center;border-bottom:1px solid var(--line,#eaecf0);padding:8px 0}" +
  ".ph .row b{font-size:15px}.ph .row small{display:block;color:var(--muted,#667085)}.ph .back{display:inline-block;margin:4px 0 8px;font-size:16px}.ph .ok{background:#e3f4e8;color:#1d6b35;padding:12px;border-radius:10px;margin:10px 0}";
document.head.append(h("style", {}, css));
const projects = () => ((S.L && S.L.projects) || []).filter((p) => (!p.kind || p.kind === "project") && p.status !== "closed");
let PID = null, HOME = null;
const num = (v, ph) => h("input", { type: "number", inputmode: "decimal", step: "any", value: v == null ? "" : v, placeholder: ph || "" });
const fld = (label, el) => h("label", { class: "f" }, h("span", {}, label), el);
const sel = (rows, val, blank) => h("select", {}, blank ? h("option", { value: "" }, blank) : null, rows.map(([v, l]) => h("option", { value: v, selected: String(v) === String(val) }, l)));
const photoIn = () => h("input", { type: "file", accept: "image/*", capture: "environment" });

/* make a photo smaller on the phone before it is sent (long side 1600 px, JPEG) */
async function shrink(file) {
  if (!file || !/^image\//.test(file.type)) return file;
  try {
    const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = URL.createObjectURL(file); });
    const k = Math.min(1, 1600 / Math.max(img.width, img.height));
    const cv = document.createElement("canvas"); cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
    cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
    const blob = await new Promise((ok) => cv.toBlob(ok, "image/jpeg", 0.72));
    return blob && blob.size < file.size ? new File([blob], (file.name || "photo").replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch (e) { return file; }
}
async function sendPhoto(inp, meta) {
  if (!inp || !inp.files || !inp.files[0]) return 0;
  const f = await shrink(inp.files[0]);
  return uploadFiles([f], Object.assign({ project_id: PID, date: today(), kind: "photo" }, meta));
}

PAGES["phone"] = async (root, params) => {
  const view = (params && params.do) || "";
  root.append(h("div", { class: "ph", id: "ph" }));
  const box = root.querySelector("#ph");
  PID = PID || S.project || (projects()[0] || {}).id;
  if (!PID) { box.append(h("p", {}, "No project.")); return; }
  HOME = await api("ph.home", { project_id: PID });
  const back = () => h("a", { class: "back", href: "#/phone" }, "‹ Back");
  const V = { dpr: dprView, grn: grnView, issue: issueView, log: logView, slip: slipView, issue_site: siteIssueView };
  if (V[view]) { box.append(back()); await V[view](box); return; }
  const ps = h("select", { onchange: (e) => { PID = Number(e.target.value); go(); } }, projects().map((p) => h("option", { value: p.id, selected: String(p.id) === String(PID) }, p.code + " · " + p.name)));
  const m = HOME.mine, r = HOME.rights;
  const tile = (icon, label, sub, href, ok) => ok === false ? null : h("a", { class: "ph-tile", href }, h("span", { class: "i" }, icon), label, h("small", {}, sub));
  box.append(h("h2", {}, "Site entries"), fld("Project", ps),
    h("div", { class: "ph-tiles" },
      tile("📝", "Today's DPR", HOME.dpr ? (HOME.dpr.no || "draft") + " · " + HOME.dpr.status : "not started — copies yesterday", "#/phone?do=dpr", r["project.edit"]),
      tile("🚚", "Goods received", "challan photo · " + m.grn + " today", "#/phone?do=grn", r["inventory.edit"]),
      tile("📦", "Material issue", m.issue + " today", "#/phone?do=issue", r["inventory.edit"]),
      tile("🚜", "Machine hours", m.log + " today", "#/phone?do=log", r["equipment.edit"]),
      tile("🧾", "Petty cash slip", HOME.imprests.length ? "with photo" : "no petty cash float", "#/phone?do=slip", r["accounts.edit"] && HOME.imprests.length > 0),
      tile("⚠️", "Site issue", "photo and location", "#/phone?do=issue_site"),
      tile("👷", "Attendance", "mark who is on site", "#/py/attendance", r["project.edit"] && !!PAGES["py/attendance"]),
      tile("🖥️", "Full screens", "the desktop menu", "#/dashboard")));
  box.append(h("p", { class: "hint", style: "margin-top:14px" }, "Tip: add this page to the phone's home screen (browser menu › Add to Home screen). Photos are made smaller before sending."));
};

/* ── today's DPR ── */
async function dprView(box) {
  const t = today();
  if (HOME.dpr && HOME.dpr.status !== "draft") { box.append(h("div", { class: "ok" }, "Today's DPR " + (HOME.dpr.no || "") + " is " + HOME.dpr.status + ". "), h("a", { href: "#/p/dpr" }, "Open the DPR screen ›")); return; }
  if (HOME.dpr) { box.append(h("p", {}, "Today's DPR is already started as a draft. "), h("a", { href: "#/p/dpr" }, "Finish it on the DPR screen ›")); return; }
  const [pf, bq] = await Promise.all([api("dpr.prefill", { project_id: PID, date: t }), api("ph.boq", { project_id: PID })]);
  const acts = Object.fromEntries(bq.activities.map((a) => [a.id, a]));
  const boq = Object.fromEntries(bq.rows.map((b) => [b.id, b]));
  const trades = Object.fromEntries(HOME.trades.map((x) => [x.id, x.name]));
  const eqs = Object.fromEntries(HOME.equipment.map((x) => [x.id, x]));
  box.append(h("h2", {}, "DPR " + t), h("p", { class: "hint" }, pf.previous_label ? "Gangs, machines and work lines copied from " + pf.previous_label + ". Type today's quantities; leave 0 for work not done." : "No earlier DPR to copy."));
  const work = pf.work.map((w) => { const a = acts[w.activity_id] || {}; const b = boq[w.boq_item_id] || {}; const q = num("", w.planned_qty ? "plan " + Math.round(Number(w.planned_qty)) : "qty");
    box.append(h("div", { class: "row" }, h("div", {}, h("b", {}, a.code ? a.code + " " + a.name : (b.code || "") + " " + (b.name || "")), h("small", {}, (w.location || a.location || "") + (b.unit ? " · " + b.unit : ""))), q)); return [w, q]; });
  if (pf.labour.length) box.append(h("h3", {}, "Gangs (heads)"));
  const lab = pf.labour.map((l) => { const n = num(l.count); box.append(h("div", { class: "row" }, h("div", {}, h("b", {}, trades[l.trade_id] || "Trade " + l.trade_id), h("small", {}, (l.hours || 8) + " h" + (l.party_id ? " · contractor" : ""))), n)); return [l, n]; });
  if (pf.equipment.length) box.append(h("h3", {}, "Machines (hours)"));
  const eq = pf.equipment.map((e) => { const n = num("", "hours"); const x = eqs[e.equipment_id] || {}; box.append(h("div", { class: "row" }, h("div", {}, h("b", {}, (x.code || "") + " " + (x.name || "Machine " + e.equipment_id)), h("small", {}, e.operator || "")), n)); return [e, n]; });
  const weather = sel([["clear", "Clear"], ["cloudy", "Cloudy"], ["rain", "Rain"], ["heavy_rain", "Heavy rain"]], "clear");
  const rem = h("textarea", { rows: 3, placeholder: "Remarks, hold-ups, visitors" });
  box.append(fld("Weather", weather), fld("Remarks", rem));
  const btn = h("button", { class: "btn primary big", onclick: async () => {
    btn.disabled = true;
    try {
      const r = await run("dpr.save", { header: { project_id: PID, date: t, shift: "day", weather: weather.value, remarks: rem.value },
        work: work.filter(([, q]) => Number(q.value) > 0).map(([w, q]) => ({ activity_id: w.activity_id, boq_item_id: w.boq_item_id, location: w.location, planned_qty: w.planned_qty, actual_qty: Number(q.value) })),
        labour: lab.filter(([, n]) => Number(n.value) > 0).map(([l, n]) => Object.assign({}, l, { count: Number(n.value) })),
        equipment: eq.filter(([, n]) => Number(n.value) > 0).map(([e, n]) => ({ activity_id: e.activity_id, equipment_id: e.equipment_id, operator: e.operator, hours: Number(n.value) })) });
      box.replaceChildren(h("div", { class: "ok" }, "DPR saved as a draft. The engineer checks and submits it on the DPR screen."), h("a", { class: "btn big", href: "#/phone" }, "Done"));
      void r;
    } catch (e) { btn.disabled = false; }
  } }, "Save today's DPR");
  box.append(btn);
}

/* ── goods received ── */
async function grnView(box) {
  const v = await api("ph.vendors", { project_id: PID });
  const vrows = v.recent.map((x) => [x.id, x.name]).concat(v.all.filter((x) => !v.recent.some((y) => y.id === x.id)).map((x) => [x.id, x.name]));
  const vend = sel(vrows, "", "Choose the supplier");
  const store = sel(HOME.stores.map((s) => [s.id, s.name]), (HOME.stores[0] || {}).id);
  const ch = h("input", { placeholder: "Challan / bill no." }), veh = h("input", { placeholder: "e.g. Ba 2 Kha 1234" }), wb = h("input", { placeholder: "Weighbridge ticket (if weighed)" });
  const mats = HOME.materials_used.map((m) => [m.id, m.name + " (" + m.unit + ")"]);
  const lines = h("div");
  const addLine = () => { const m = sel(mats, "", "Material"), q = num("", "Qty"), r = num("", "Rate (optional)"); lines.append(h("div", { class: "panel", style: "padding:8px;margin:8px 0" }, m, h("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px" }, q, r))); lines._rows = (lines._rows || []).concat([[m, q, r]]); };
  addLine();
  const ph = photoIn(), post = h("input", { type: "checkbox", style: "width:auto" });
  box.append(h("h2", {}, "Goods received"), fld("Supplier", vend), fld("Into store", store), fld("Challan no.", ch), fld("Vehicle no.", veh), fld("Weighbridge ticket", wb),
    h("h3", {}, "Materials"), lines, h("button", { class: "btn", onclick: addLine }, "+ another material"),
    fld("Photo of the challan", ph), h("label", { style: "display:flex;gap:8px;align-items:center;margin:10px 0" }, post, "Post now (stock and accounts update)"));
  const btn = h("button", { class: "btn primary big", onclick: async () => {
    btn.disabled = true;
    try {
      const r = await run("ph.grn", { project_id: PID, vendor_id: vend.value, store_id: store.value, challan_no: ch.value, vehicle_no: veh.value, weighbridge_no: wb.value, post: post.checked ? 1 : 0,
        lines: lines._rows.map(([m, q, rt]) => ({ material_id: m.value, qty: q.value, rate: rt.value })) });
      const n = await sendPhoto(ph, { entity: "grn", entity_id: r.id, caption: "Challan " + (ch.value || "") });
      box.replaceChildren(h("div", { class: "ok" }, (r.posted ? "GRN " + r.no + " posted." : "GRN saved as a draft (store keeper posts it).") + (n ? " Challan photo attached." : "")), h("a", { class: "btn big", href: "#/phone" }, "Done"));
    } catch (e) { btn.disabled = false; }
  } }, "Save goods received");
  box.append(btn);
}

/* ── material issue ── */
async function issueView(box) {
  const [st, bq] = await Promise.all([api("ph.stock", { project_id: PID }), api("ph.boq", { project_id: PID })]);
  const mat = sel(st.rows.map((m) => [m.material_id, m.name + " — " + Number(m.qty).toFixed(2) + " " + m.unit + " in stock"]), "", "Material");
  const qty = num("", "Quantity");
  const use = sel([["boq", "Work (BOQ item)"], ["equipment", "Machine"], ["overhead", "Site overhead"]], "boq");
  const boq = sel(bq.rows.map((b) => [b.id, b.code + " " + (b.name || "").slice(0, 60)]), "", "BOQ item");
  const eq = sel(HOME.equipment.map((e) => [e.id, e.code + " " + e.name]), "", "Machine");
  const wB = fld("BOQ item", boq), wE = fld("Machine", eq); wE.style.display = "none";
  use.onchange = () => { wB.style.display = use.value === "boq" ? "" : "none"; wE.style.display = use.value === "equipment" ? "" : "none"; };
  const to = h("input", { placeholder: "Gang, foreman or operator" }), post = h("input", { type: "checkbox", style: "width:auto", checked: true });
  box.append(h("h2", {}, "Material issue"), fld("Material", mat), fld("Quantity", qty), fld("Used for", use), wB, wE, fld("Issued to", to),
    h("label", { style: "display:flex;gap:8px;align-items:center;margin:10px 0" }, post, "Post now"));
  const btn = h("button", { class: "btn primary big", onclick: async () => {
    btn.disabled = true;
    try {
      const r = await run("ph.issue", { project_id: PID, issued_to: to.value, post: post.checked ? 1 : 0,
        lines: [{ material_id: mat.value, qty: qty.value, target: use.value, boq_item_id: use.value === "boq" ? boq.value : null, equipment_id: use.value === "equipment" ? eq.value : null }] });
      box.replaceChildren(h("div", { class: "ok" }, r.posted ? "Issue " + r.no + " posted." : "Issue saved as a draft."), h("a", { class: "btn big", href: "#/phone?do=issue" }, "Another issue"), h("a", { class: "btn big", href: "#/phone" }, "Done"));
    } catch (e) { btn.disabled = false; }
  } }, "Save issue");
  box.append(btn);
}

/* ── machine hours ── */
async function logView(box) {
  const eq = sel(HOME.equipment.map((e) => [e.id, e.code + " " + e.name]), "", "Machine");
  const ms = num("", "Meter start"), me = num("", "Meter end"), hrs = num("", "or hours worked"), idle = num("", "Idle hours"), fuel = num("", "Diesel litres"), op = h("input", { placeholder: "Operator" });
  eq.onchange = () => { const x = HOME.equipment.find((e) => String(e.id) === eq.value); if (x && x.meter != null) ms.value = x.meter; };
  box.append(h("h2", {}, "Machine hours " + today()), fld("Machine", eq), fld("Meter start", ms), fld("Meter end", me), fld("Hours worked (when no meter)", hrs), fld("Idle hours", idle), fld("Diesel filled", fuel), fld("Operator", op));
  const btn = h("button", { class: "btn primary big", onclick: async () => {
    btn.disabled = true;
    try {
      await run("log.save", { row: { equipment_id: eq.value, project_id: PID, date: today(), shift: "day", meter_start: ms.value, meter_end: me.value, hours: hrs.value || (me.value && ms.value ? Number(me.value) - Number(ms.value) : ""),
        idle_hours: idle.value, fuel_qty: fuel.value, operator: op.value, origin: "phone" } });
      box.replaceChildren(h("div", { class: "ok" }, "Machine hours saved (draft until the equipment in-charge approves)."), h("a", { class: "btn big", href: "#/phone?do=log" }, "Another machine"), h("a", { class: "btn big", href: "#/phone" }, "Done"));
    } catch (e) { btn.disabled = false; }
  } }, "Save hours");
  box.append(btn);
}

/* ── petty cash slip ── */
async function slipView(box) {
  const imp = sel(HOME.imprests.map((x) => [x.id, x.holder || "Float " + x.id]), (HOME.imprests[0] || {}).id);
  const amt = num("", "Amount"), desc = h("input", { placeholder: "What was bought / paid" }), ph = photoIn();
  box.append(h("h2", {}, "Petty cash slip"), fld("Petty cash float", imp), fld("Amount", amt), fld("For", desc), fld("Photo of the bill", ph));
  const btn = h("button", { class: "btn primary big", onclick: async () => {
    btn.disabled = true;
    try {
      const r = await run("mn.slip_save", { imprest_id: imp.value, amount: amt.value, description: desc.value, project_id: PID, overhead: 1 });
      const n = await sendPhoto(ph, { entity: "mn_slips", entity_id: r && r.id, caption: desc.value });
      box.replaceChildren(h("div", { class: "ok" }, "Slip saved (accounts posts it)." + (n ? " Photo attached." : "")), h("a", { class: "btn big", href: "#/phone" }, "Done"));
    } catch (e) { btn.disabled = false; }
  } }, "Save slip");
  box.append(btn);
}

/* ── site issue with photo and location ── */
async function siteIssueView(box) {
  const title = h("input", { placeholder: "What is wrong" }), desc = h("textarea", { rows: 3, placeholder: "Details" }), loc = h("input", { placeholder: "Chainage or place" });
  const pr = sel([["low", "Low"], ["medium", "Medium"], ["high", "High"]], "medium"), ph = photoIn();
  const gps = h("button", { class: "btn", onclick: () => {
    if (!navigator.geolocation) return toast("This phone gives no location.", "err");
    navigator.geolocation.getCurrentPosition((p) => { loc.value = (loc.value ? loc.value + " · " : "") + p.coords.latitude.toFixed(6) + ", " + p.coords.longitude.toFixed(6); }, () => toast("Location not allowed.", "err"), { enableHighAccuracy: true, timeout: 15000 });
  } }, "📍 Add my location");
  box.append(h("h2", {}, "Site issue"), fld("Issue", title), fld("Details", desc), fld("Where", loc), gps, fld("Priority", pr), fld("Photo", ph));
  const btn = h("button", { class: "btn primary big", onclick: async () => {
    btn.disabled = true;
    try {
      const r = await run("fld.issue_save", { row: { project_id: PID, type: "site", title: title.value, description: desc.value, location: loc.value, priority: pr.value } });
      const n = await sendPhoto(ph, { entity: "fld_issues", entity_id: r.id, caption: title.value, location: loc.value });
      box.replaceChildren(h("div", { class: "ok" }, "Issue " + r.no + " reported." + (n ? " Photo attached." : "")), h("a", { class: "btn big", href: "#/phone" }, "Done"));
    } catch (e) { btn.disabled = false; }
  } }, "Report issue");
  box.append(btn);
}

/* ── "+ New": more shortcuts; on a phone: a way to the phone page ── */
const addNew = () => {
  const menu = document.querySelector(".qamenu");
  if (!menu || menu.querySelector("[data-bco257]")) return;
  const items = [["Phone entry page", "#/phone", true], ["Petty cash slip", "#/acc/payments", can("accounts", "edit")], ["Site attendance", "#/py/attendance", can("project", "edit") && !!PAGES["py/attendance"]],
    ["Site issue", "#/phone?do=issue_site", can("project", "view")]];
  items.filter((x) => x[2]).forEach(([l, href]) => menu.append(h("a", { href, "data-bco257": 1, onclick: () => { menu.hidden = true; } }, l)));
};
const phoneHint = () => {
  if (window.innerWidth > 720 || !S || !S.token || location.hash.startsWith("#/phone") || sessionStorage.getItem("bco_ph_hint")) return;
  try { sessionStorage.setItem("bco_ph_hint", "1"); } catch (e) { /* ignore */ }
  const b = h("div", { class: "sf-banner", style: "position:fixed;left:8px;right:8px;bottom:8px;z-index:50" }, "On a phone? ", h("a", { href: "#/phone", onclick: () => b.remove() }, "Open the phone page ›"), " ", h("button", { class: "btn small", onclick: () => b.remove() }, "×"));
  document.body.append(b);
};
window.addEventListener("hashchange", () => { addNew(); phoneHint(); });
(window.bcoBootHooks = window.bcoBootHooks || []).push(() => { setTimeout(() => { addNew(); phoneHint(); }, 500); });
})();
