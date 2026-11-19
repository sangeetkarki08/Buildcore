/* BuildCore 2.50 — Programme in fast: MS Project / Primavera import and export, first programme from the BOQ,
   programme check. Adds buttons to Schedule & WBS and a "Programme check" tab. */
(function () {
"use strict";

function save(name, b64, mime) {
  const a = document.createElement("a");
  a.href = "data:" + mime + ";base64," + b64; a.download = name; document.body.append(a); a.click(); a.remove();
}
const LV = { ok: ["OK", "#2f7a4d"], info: ["Look", "#1769aa"], warn: ["Fix", "#c05621"], bad: ["Problem", "#b42318"] };
const pill = (lv) => { const x = LV[lv] || LV.info; return h("span", { style: "display:inline-block;min-width:58px;text-align:center;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff;background:" + x[1] }, x[0]); };
const reloadSchedule = () => { if (window.go) go(); else location.reload(); };

/* ── import ── */
function importDialog() {
  let file = null;
  const fname = h("span", { class: "muted" }, "no file chosen");
  const out = h("div");
  const inp = h("input", { type: "file", accept: ".xml,.xer", style: "display:none", onchange: () => {
    const f = inp.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => { file = { filename: f.name, b64: String(r.result) }; fname.textContent = f.name; preview(); };
    r.readAsDataURL(f);
  } });
  const opts = form([{ k: "baseline", label: "Take the baseline dates (only where BuildCore has none)", type: "check" },
    { k: "calendar", label: "Use the file's working week and holidays (MS Project)", type: "check" },
    { k: "actuals", label: "Take actual start/finish from the file for activities with no DPR progress", type: "check" }],
    { baseline: 1, calendar: 1, actuals: 0 });
  const send = (apply) => run("prog.import", Object.assign({ project_id: S.project, filename: file.filename, b64: file.b64, apply: apply ? 1 : 0 }, opts.values()));
  async function preview() {
    out.innerHTML = "";
    const d = await send(false);
    const s = d.summary;
    out.append(h("div", { class: "panel" },
      kv([["File", s.source + (s.file_project ? " — " + s.file_project : "")],
        ["Activities", s.activities + " (" + s.add + " new, " + s.update + " already in BuildCore, updated)"],
        ["Links", s.links], ["WBS", s.wbs + " (" + s.wbs_new + " new)"],
        ["Tied to BOQ items", s.boq_matched + " of " + s.activities],
        ["With DPR progress", s.with_progress ? s.with_progress + " — their dates and progress stay as the DPRs say" : "none"],
        ["Only in BuildCore", s.only_in_buildcore ? s.only_in_buildcore + " activities are not in the file; they are kept" : "none"],
        ["Calendar", s.calendar ? s.calendar + (s.holidays ? ", " + s.holidays + " holidays" : "") : "the project calendar"]]),
      d.warnings.length ? h("ul", {}, d.warnings.map((w) => h("li", { class: "hint" }, w))) : null),
      table([{ k: "action", label: "", v: (r) => r.action === "add" ? "new" : "update" }, { k: "code", label: "Code" }, { k: "name", label: "Activity" },
        { k: "dur", label: "Days", fmt: "num" }, { k: "start", label: "Start" }, { k: "finish", label: "Finish" },
        { k: "constraint", label: "Constraint" }, { k: "boq", label: "BOQ item" }, { label: "DPR progress", v: (r) => r.has_progress ? "yes (kept)" : "" }],
        d.rows, { name: "prog_import" }));
    btn.disabled = false;
  }
  const btn = h("button", { class: "btn primary", disabled: true, onclick: async () => {
    const d = await send(true);
    toast("Programme imported: " + d.summary.add + " new, " + d.summary.update + " updated, " + d.summary.links_written + " links. Press Calculate schedule.", "ok");
    document.querySelectorAll(".overlay").forEach((o) => o.remove());
    reloadSchedule();
  } }, "Import into this project");
  modal("Import programme (MS Project or Primavera P6)", h("div", {},
    h("p", { class: "hint" }, "MS Project: File › Save As › XML. Primavera P6: File › Export › XER. Activities are matched to BuildCore's by code (then name), so you can import an updated programme again: the same activities are updated and their DPR history stays. Nothing in BuildCore is deleted. Links between the imported activities are replaced by the file's."),
    h("div", { class: "bar" }, h("button", { class: "btn", onclick: () => inp.click() }, "Choose file…"), fname, inp), opts, out, h("div", { class: "bar" }, btn)), [], { wide: true });
}

/* ── first programme from the BOQ ── */
function fromBoqDialog() {
  const out = h("div");
  const f = form([{ k: "crew", label: "Workers in a labour crew", type: "number" }, { k: "hours_day", label: "Machine hours per day", type: "number" },
    { k: "default_days", label: "Shortest duration when guessed (days)", type: "number" },
    { k: "links", label: "Links inside each WBS group", type: "select", noBlank: true, options: [["ss", "Start-to-start, 30% overlap (linear works)"], ["fs", "Finish-to-start (one after another)"], ["none", "No links"]] }],
    { crew: 15, hours_day: 8, default_days: 5, links: "ss" });
  let ok = false;
  const go1 = async () => {
    out.innerHTML = "";
    const d = await run("prog.from_boq", Object.assign({ project_id: S.project }, f.values()));
    ok = d.rows.length > 0;
    btn.disabled = !ok;
    out.append(h("p", {}, d.rows.length ? d.rows.length + " BOQ items have no activity yet" + (d.existing ? " (" + d.existing + " already have one)" : "") + ". Start " + d.start + (d.contract_finish ? ", contract completion " + d.contract_finish : "") + ". " + (d.guessed ? d.guessed + " durations are guessed because the item has no rate analysis — check them." : "") : "Every BOQ item already has an activity."),
      table([{ k: "boq", label: "BOQ" }, { k: "name", label: "Activity" }, { k: "qty", label: "Qty", fmt: "num" }, { k: "unit", label: "Unit" },
        { k: "dur", label: "Days", fmt: "num" }, { label: "How the duration was found", v: (r) => h("span", { class: r.guessed ? "red" : "" }, r.basis) }], d.rows, { name: "prog_boq" }));
  };
  const btn = h("button", { class: "btn primary", disabled: true, onclick: async () => {
    const d = await run("prog.from_boq", Object.assign({ project_id: S.project, apply: 1 }, f.values()));
    toast(d.created + " activities and " + d.links + " links made. Check durations and links, then Calculate schedule.", "ok");
    document.querySelectorAll(".overlay").forEach((o) => o.remove());
    reloadSchedule();
  } }, "Make these activities");
  modal("First programme from the BOQ", h("div", {},
    h("p", { class: "hint" }, "One activity per BOQ item that has none yet. Duration = quantity ÷ output per day; the output comes from the item's rate analysis norm (the busiest machine's hours, or labour days with the crew size below). Items with no rate analysis get a duration from their share of the BOQ value, shown in red. Time-related items (L.S., months) run for the contract period. Nothing existing changes."),
    f, h("div", { class: "bar" }, h("button", { class: "btn", onclick: go1 }, "Show the activities"), btn), out), [], { wide: true });
  go1();
}

async function exportXml() {
  const d = await run("prog.export", { project_id: S.project });
  save(d.filename, d.b64, "application/xml");
  toast(d.tasks + " lines and " + d.links + " links exported. Open in MS Project (File › Open, XML) or P6 (Import › MS Project).", "ok");
}

/* ── programme check (tab) ── */
async function checkTab() {
  const box = h("div");
  const d = await run("prog.check", { project_id: S.project });
  const editable = can("project", "edit");
  box.append(h("div", { class: "bar" },
    h("b", {}, d.passed + " of " + d.total + " checks pass"), h("span", { class: "hint" }, " · " + d.activities + " activities, " + d.links + " links"), h("div", { class: "grow" }),
    editable ? h("button", { class: "btn", onclick: importDialog }, "Import MS Project / P6") : null,
    h("button", { class: "btn", onclick: exportXml }, "Export to MS Project"),
    editable ? h("button", { class: "btn", onclick: fromBoqDialog }, "First programme from BOQ") : null));
  const openAct = (it) => { if (!it.id) return; const x = byId(S.P.activities || [], it.id); if (x && window.activityForm) activityForm(x, reloadSchedule); };
  for (const ck of d.checks) {
    const det = h("details", { class: "panel", style: "margin:6px 0" },
      h("summary", { style: "cursor:pointer" }, pill(ck.level), " ", h("b", {}, ck.title), ck.count ? " — " + ck.count : ""),
      h("p", { class: "hint" }, ck.help),
      ck.items.length ? h("ul", {}, ck.items.map((it) => h("li", {}, it.id ? h("a", { href: "javascript:void 0", onclick: () => openAct(it) }, (it.code || "") + " " + (it.name || "")) : (it.code ? it.code + " " : "") + (it.name || ""), it.note ? h("span", { class: "muted" }, " · " + it.note) : null))) : null,
      ck.count > ck.items.length ? h("p", { class: "muted" }, "… and " + (ck.count - ck.items.length) + " more") : null,
      ck.fix === "from_boq" && editable && ck.count ? h("button", { class: "btn", onclick: fromBoqDialog }, "Add activities from the BOQ") : null);
    box.append(det);
  }
  if (d.history.length) box.append(h("h3", {}, "Imports and exports"), table([{ k: "ts", label: "When", v: (r) => (r.ts || "").slice(0, 16).replace("T", " ") }, { k: "kind", label: "What" }, { k: "source", label: "Format" }, { k: "filename", label: "File" }], d.history, { name: "prog_hist" }));
  return box;
}

window.SCHED_TABS = (window.SCHED_TABS || []).concat([["Programme check", checkTab]]);

/* buttons on the Schedule & WBS head */
const wrap = () => {
  const orig = PAGES["p/schedule"];
  if (!orig || orig._bco250) return;
  const w = async (root, params) => {
    await orig(root, params);
    if (!S.project) return;
    const head = root.querySelector(".bar");
    if (!head || head.querySelector("[data-prog]")) return;
    const editable = can("project", "edit");
    const add = (label, fn) => head.append(h("button", { class: "btn", "data-prog": 1, onclick: fn }, label));
    if (editable) add("Import MS Project / P6", importDialog);
    add("Export to MS Project", exportXml);
    if (editable) add("From BOQ", fromBoqDialog);
  };
  w._bco250 = true;
  PAGES["p/schedule"] = w;
};
if (document.readyState === "complete") wrap(); else window.addEventListener("load", wrap);
})();
