/* BuildCore 2.15 — field and quality tools (drawings, issues, RFIs, meetings, inspections), My work,
   a simpler home and shorter forms. */
(function () {
"use strict";

const LSg = (k, d) => { try { const x = localStorage.getItem(k); return x === null ? d : x; } catch (e) { return d; } };
const LSs = (k, x) => { try { localStorage.setItem(k, x); } catch (e) { /* ignore */ } };
const pill = (txt, col) => h("span", { style: "display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff;background:" + col }, txt);
const ST_COL = { open: "#c05621", in_progress: "#b7791f", ready: "#1769aa", closed: "#2f7a4d", void: "#98a2b3", draft: "#98a2b3", answered: "#1769aa", pass: "#2f7a4d", fail: "#b42318", incomplete: "#b7791f" };
const label = (list, k) => ((list || []).find((x) => x[0] === k) || [k, k])[1];
const need = (root, title) => { if (S.project) return false; root.append(pageHead(title), h("div", { class: "panel" }, "Choose a project at the top first.")); return true; };
let META = null;
async function meta(force) { if (!META || force || META._p !== S.project) { META = await run("fld.meta", { project_id: S.project || null }); META._p = S.project; } return META; }
const userOpts = () => META.users.map((x) => [x.id, x.name]);
const partyOpts = () => META.parties.map((x) => [x.id, x.name]);
const drawOpts = () => META.drawings.map((x) => [x.id, x.number + (x.revision ? " rev " + x.revision : "") + " " + (x.title || "")]);
const due = (r) => (r.due_date ? h("span", { style: r.overdue ? "color:#b42318;font-weight:700" : "" }, r.due_date + (r.overdue ? " · late" : "")) : "");
async function uploadOne(file, meta_) {
  const qs = new URLSearchParams(Object.assign({ filename: file.name, mime: file.type || "" }, meta_ || {}));
  const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: file });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error);
  return j.data.id;
}

/* ── My work ── */
PAGES.mywork = async (root) => {
  const d = await run("fld.mywork", {});
  const ap = typeof approvalsCount !== "undefined" ? approvalsCount : 0;
  const sf = h("input", { type: "checkbox" }); sf.checked = LSg("bco_simple_forms", "1") === "1";
  sf.onchange = () => { LSs("bco_simple_forms", sf.checked ? "1" : "0"); toast(sf.checked ? "Forms show the main fields first; the rest are under “More details”." : "Forms show every field.", "ok"); };
  root.append(pageHead("My work", "Everything waiting for you, in one list - overdue first. Open any line to act on it.",
    h("label", { class: "hint", style: "display:flex;gap:6px;align-items:center", title: "Long forms show the main fields; the rest open with “More details”" }, sf, "Short forms")));
  root.append(h("div", { class: "tiles" }, tile("Overdue", d.counts.overdue, { cls: d.counts.overdue ? "bad" : "" }), tile("Due this week", d.counts.this_week),
    tile("All my open items", d.counts.total), tile("Waiting for my approval", ap, { href: "#/approvals" })));
  root.append(table([{ label: "", v: (r) => (r.overdue ? h("b", { class: "red" }, "LATE") : r.this_week ? h("b", { style: "color:#b7791f" }, "this week") : "") },
    { k: "kind", label: "What" }, { k: "title", label: "Item" }, { label: "Project", v: (r) => (r.project_id ? nm.pcode(r.project_id) : "") },
    { k: "due", label: "Due" }, { k: "status", label: "Status" }, { k: "extra", label: "" }],
  d.items, { name: "my_work", title: "My work", empty: "Nothing waiting for you. Well done.", rowClass: (r) => (r.overdue ? "flag" : ""),
    onRow: (r) => { if (r.project_id && r.project_id !== S.project && typeof setProject === "function") { try { setProject(r.project_id); } catch (e) { /* ignore */ } } location.hash = r.link; } }));
};

/* ── Drawings ── */
PAGES["f/drawings"] = async (root, params) => {
  if (need(root, "Drawings")) return;
  await meta(true);
  let v = { discipline: "", q: "", all: "" };
  const holder = h("div");
  const load = async () => {
    let rows = await run("fld.drawings", { project_id: S.project, all: v.all ? 1 : 0 });
    if (v.discipline) rows = rows.filter((r) => r.discipline === v.discipline);
    if (v.q) { const t = v.q.toLowerCase(); rows = rows.filter((r) => ((r.number || "") + " " + (r.title || "")).toLowerCase().includes(t)); }
    holder.innerHTML = "";
    holder.append(table([{ k: "number", label: "Drawing no." }, { k: "title", label: "Title" }, { k: "discipline", label: "Discipline" }, { k: "revision", label: "Rev" },
      { k: "rev_date", label: "Date" }, { label: "Status", v: (r) => (r.current ? r.status.replace(/_/g, " ") : "superseded") }, { label: "Revisions", v: (r) => r.revs },
      { label: "Open issues", v: (r) => (r.open_issues ? h("b", { class: "red" }, r.open_issues) : "") }, { k: "filename", label: "File" }],
    rows, { name: "drawings", title: "Drawing register", empty: "No drawing yet. Add the drawings you build from.", rowClass: (r) => (r.current ? "" : "muted"),
      onRow: (r) => viewer(r, load) }));
  };
  root.append(pageHead("Drawings", "The drawing register: the current revision of every sheet, its history, and the issues pinned on it. A new revision supersedes the old one by itself.",
    can("project", "edit") ? h("button", { class: "btn primary", onclick: () => drawingDialog(null, load) }, "Add drawing / new revision") : null),
  filterBar([{ k: "discipline", label: "Discipline", type: "select", blank: "All", options: META.disciplines.map((x) => [x, x]) }, { k: "q", label: "Search" },
    { k: "all", label: "Show", type: "select", options: [["", "Current only"], ["1", "All revisions"]], noBlank: true }], v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.id) { const r = (await run("fld.drawings", { project_id: S.project, all: 1 })).find((x) => String(x.id) === String(params.id)); if (r) viewer(r, load); }
};

function drawingDialog(base, done) {
  const file = h("input", { type: "file", accept: ".pdf,.png,.jpg,.jpeg" });
  const f = form([{ k: "number", label: "Drawing number", req: true }, { k: "title", label: "Title", req: true }, { k: "discipline", label: "Discipline", type: "select", options: META.disciplines.map((x) => [x, x]) },
    { k: "revision", label: "Revision", req: true }, { k: "rev_date", label: "Revision date", type: "date" },
    { k: "status", label: "Status", type: "select", noBlank: true, options: [["for_construction", "For construction"], ["for_approval", "For approval"], ["for_information", "For information"], ["as_built", "As built"]] },
    { k: "transmittal", label: "Received with (transmittal / letter)" }, { k: "remarks", label: "Remarks" }],
  base ? { number: base.number, title: base.title, discipline: base.discipline, status: "for_construction", rev_date: today() } : { status: "for_construction", rev_date: today() });
  modal(base ? "New revision of " + base.number : "Add a drawing", h("div", {}, h("p", { class: "hint" }, "PDF or image (JPG / PNG). For a new revision use the same drawing number - the old one is kept as superseded and its open issues move to the new sheet."), f, h("label", {}, "Drawing file ", file)),
    [{ label: "Save", cls: "primary", act: async () => {
      const v = f.values();
      let fid = null;
      if (file.files[0]) fid = await uploadOne(file.files[0], { entity: "fld_drawings", project_id: S.project, caption: v.number + " rev " + v.revision });
      await run("fld.drawing_save", { row: Object.assign(v, { project_id: S.project, file_id: fid }) }, (r) => (r.superseded ? "New revision saved; the old one is superseded" : "Drawing saved"));
      await meta(true); done && done();
    } }]);
}

/* the sheet viewer: PDF (pdf.js) or image, with the issues pinned on it */
let PDFJS = null;
async function pdfjs() {
  if (!PDFJS) { PDFJS = await import("/pdfjs/pdf.min.js"); PDFJS.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.js"; }
  return PDFJS;
}
async function viewer(d, reload) {
  await meta();
  const ov = h("div", { class: "overlay", style: "align-items:stretch" });
  const sheet = h("div", { style: "position:relative;display:inline-block;margin:10px auto;box-shadow:0 2px 12px rgba(0,0,0,.2);background:#fff" });
  const scrollBox = h("div", { style: "flex:1;overflow:auto;background:#d0d5dd;text-align:center" }, sheet);
  let scale = 1.4, page = 1, pages = 1, pinMode = false, pdf = null;
  const info = h("span", { class: "muted", style: "margin:0 8px" });
  const pinBtn = h("button", { class: "btn small", onclick: () => { pinMode = !pinMode; pinBtn.classList.toggle("primary", pinMode); sheet.style.cursor = pinMode ? "crosshair" : "default"; } }, "📍 Add issue on the sheet");
  const close = () => ov.remove();
  const bar = h("div", { style: "display:flex;gap:8px;align-items:center;padding:8px 12px;background:#fff;border-bottom:1px solid #eaecf0;flex-wrap:wrap" },
    h("b", {}, d.number + " rev " + (d.revision || "-") + " — " + (d.title || "")), h("span", { class: "grow", style: "flex:1" }),
    h("button", { class: "btn small", onclick: () => { scale = Math.max(0.4, scale - 0.3); draw(); } }, "−"), h("button", { class: "btn small", onclick: () => { scale += 0.3; draw(); } }, "+"),
    h("button", { class: "btn small", onclick: () => { if (page > 1) { page--; draw(); } } }, "‹"), info, h("button", { class: "btn small", onclick: () => { if (page < pages) { page++; draw(); } } }, "›"),
    pinBtn, can("project", "edit") ? h("button", { class: "btn small", onclick: () => { close(); drawingDialog(d, reload); } }, "New revision") : null,
    h("button", { class: "btn small", onclick: async () => { const hs = await run("fld.drawing_history", { id: d.id }); modal("Revisions of " + d.number, table([{ k: "revision", label: "Rev" }, { k: "rev_date", label: "Date" }, { k: "status", label: "Status" }, { k: "transmittal", label: "Received with" }, { label: "File", v: (x) => (x.file_id ? h("a", { href: fileUrl(x.file_id), target: "_blank" }, x.filename || "open") : "") }], hs, { search: false, export: false }), []); } }, "History"),
    d.file_id ? h("a", { class: "btn small", href: fileUrl(d.file_id), target: "_blank" }, "Open file") : null,
    h("button", { class: "btn small", onclick: close }, "Close"));
  ov.append(h("div", { style: "position:fixed;inset:0;display:flex;flex-direction:column;background:#fff;z-index:1000" }, bar, scrollBox));
  document.body.append(ov);
  const pins = async () => {
    sheet.querySelectorAll(".fpin").forEach((x) => x.remove());
    const list = await run("fld.issues", { project_id: S.project, drawing_id: d.id });
    list.filter((x) => x.pin_x != null && (x.pin_page || 1) === page).forEach((x) => {
      const p = h("div", { class: "fpin", title: x.no + " " + x.title + " (" + x.status + ")", style: `position:absolute;left:${x.pin_x * 100}%;top:${x.pin_y * 100}%;transform:translate(-50%,-100%);cursor:pointer;font-size:22px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.4))`,
        onclick: (e) => { e.stopPropagation(); issueDialog(x, () => pins()); } }, x.status === "closed" ? "✅" : x.status === "ready" ? "🔵" : "📍");
      sheet.append(p);
    });
  };
  async function draw() {
    sheet.querySelectorAll("canvas,img").forEach((x) => x.remove());
    if (!d.file_id) { sheet.textContent = "No file attached to this revision."; return; }
    const isPdf = /pdf/i.test(d.mime || "") || /\.pdf$/i.test(d.filename || "");
    if (isPdf) {
      try {
        const lib = await pdfjs();
        if (!pdf) { pdf = await lib.getDocument({ url: fileUrl(d.file_id) }).promise; pages = pdf.numPages; }
        const pg = await pdf.getPage(page);
        const vp = pg.getViewport({ scale });
        const cv = h("canvas", {}); cv.width = vp.width; cv.height = vp.height; cv.style.display = "block";
        sheet.prepend(cv);
        await pg.render({ canvasContext: cv.getContext("2d"), viewport: vp }).promise;
      } catch (e) { sheet.prepend(h("p", { style: "padding:20px" }, "This PDF could not be shown here (" + e.message + "). Use “Open file”.")); }
    } else {
      const img = h("img", { src: fileUrl(d.file_id), style: "display:block;width:" + Math.round(900 * scale) + "px;max-width:none" });
      sheet.prepend(img);
    }
    info.textContent = "page " + page + " / " + pages;
    pins();
  }
  sheet.addEventListener("click", (e) => {
    if (!pinMode) return;
    const r = sheet.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    pinMode = false; pinBtn.classList.remove("primary"); sheet.style.cursor = "default";
    issueDialog({ drawing_id: d.id, pin_x: Math.round(x * 10000) / 10000, pin_y: Math.round(y * 10000) / 10000, pin_page: page, location: d.number }, () => pins());
  });
  draw();
}

/* ── Issues & punch list ── */
function issueDialog(r, done) {
  const isNew = !r || !r.id;
  const f = form([{ k: "title", label: "What is wrong", req: true, wide: true }, { k: "type", label: "Type", type: "select", noBlank: true, options: META.issue_types },
    { k: "location", label: "Where (floor, room, chainage)" }, { k: "assignee_user_id", label: "Who fixes it (BuildCore user)", type: "select", options: userOpts },
    { k: "party_id", label: "Or sub-contractor", type: "select", options: partyOpts }, { k: "due_date", label: "Fix by", type: "date" },
    { k: "priority", label: "Priority", type: "select", noBlank: true, options: [["normal", "Normal"], ["high", "High"], ["low", "Low"]] },
    { k: "description", label: "Details", wide: true }, { k: "drawing_id", label: "Drawing", type: "select", options: drawOpts },
    { k: "assignee", label: "Or name (outside BuildCore)" }, { k: "root_cause", label: "Cause" }, { k: "cost", label: "Cost to fix (Rs)", type: "number" }],
  Object.assign({ type: "quality", priority: "normal" }, r || {}));
  const btns = [];
  const save = async (extra, msg) => { const res = await run("fld.issue_save", { row: Object.assign(f.values(), { id: r && r.id, project_id: S.project, pin_x: r && r.pin_x, pin_y: r && r.pin_y, pin_page: r && r.pin_page }, extra || {}) }, msg || "Saved"); done && done(); return res; };
  btns.push({ label: isNew ? "Report the issue" : "Save", cls: "primary", act: () => save() });
  if (!isNew) {
    if (["open"].includes(r.status)) btns.push({ label: "Being fixed", act: () => save({ status: "in_progress" }, "Marked as being fixed") });
    if (["open", "in_progress"].includes(r.status)) btns.push({ label: "Fixed - ready to check", act: () => save({ status: "ready" }, "Ready to check") });
    if (r.status !== "closed" && can("project", "edit")) btns.push({ label: "Checked - close", act: () => save({ status: "closed" }, "Closed") });
    if (r.status === "closed") btns.push({ label: "Reopen", act: () => save({ status: "open" }, "Reopened") });
  }
  modal(isNew ? "Report an issue" : r.no + " — " + r.title, h("div", {}, f, isNew ? h("p", { class: "hint" }, "Save first, then add photos of the problem and of the fix.") :
    h("div", { style: "margin-top:12px" }, recordPanel("fld_issues", r.id, { project_id: S.project }))), btns);
}
PAGES["f/issues"] = async (root, params) => {
  if (need(root, "Issues & punch list")) return;
  await meta(true);
  let v = { type: params.type || "", status: "", open: "1" };
  const holder = h("div");
  const load = async () => {
    const rows = await run("fld.issues", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    const all = rows.length, late = rows.filter((x) => x.overdue).length;
    holder.append(summaryStrip([["Shown", all], ["Late", late], ["Ready to check", rows.filter((x) => x.status === "ready").length]]));
    holder.append(table([{ k: "no", label: "No." }, { label: "Type", v: (r) => label(META.issue_types, r.type) }, { k: "title", label: "Issue" }, { k: "location", label: "Where" },
      { k: "who", label: "Who fixes" }, { label: "Fix by", v: due }, { label: "Status", v: (r) => pill(label(META.issue_status, r.status), ST_COL[r.status] || "#667085") },
      { label: "Drawing", v: (r) => (r.drawing_no ? h("a", { href: "#/f/drawings?id=" + r.drawing_id, onclick: (e) => e.stopPropagation() }, r.drawing_no) : "") }],
    rows, { name: "issues", title: "Issues & punch list", empty: "No issue. Report problems as you see them - with a photo.", rowClass: (r) => (r.overdue ? "flag" : ""), onRow: (r) => issueDialog(r, load) }));
  };
  root.append(pageHead("Issues & punch list", "Quality problems, safety observations, snags before handover and defects after it - each with who fixes it, by when, photos, and a check before it is closed.",
    h("button", { class: "btn primary", onclick: () => issueDialog(null, load) }, "Report an issue"),
    h("button", { class: "btn", onclick: () => issueDialog({ type: "punch" }, load) }, "Add a snag")),
  filterBar([{ k: "type", label: "Type", type: "select", blank: "All", options: META.issue_types }, { k: "status", label: "Status", type: "select", blank: "All", options: META.issue_status },
    { k: "open", label: "Show", type: "select", noBlank: true, options: [["1", "Not closed"], ["", "Everything"]] }], v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.id) { const r = (await run("fld.issues", { project_id: S.project })).find((x) => String(x.id) === String(params.id)); if (r) issueDialog(r, load); }
};

/* ── RFIs ── */
function rfiDialog(r, done) {
  const isNew = !r || !r.id;
  const f = form([{ k: "subject", label: "Subject", req: true, wide: true }, { k: "question", label: "Question", req: true, wide: true },
    { k: "party_id", label: "Ask (consultant / designer)", type: "select", options: partyOpts }, { k: "assignee_user_id", label: "Or a BuildCore user", type: "select", options: userOpts },
    { k: "due_date", label: "Answer needed by", type: "date" }, { k: "drawing_id", label: "Drawing", type: "select", options: drawOpts },
    { k: "location", label: "Location" }, { k: "discipline", label: "Discipline", type: "select", options: META.disciplines.map((x) => [x, x]) },
    { k: "spec_ref", label: "Specification clause" }, { k: "priority", label: "Priority", type: "select", noBlank: true, options: [["normal", "Normal"], ["high", "High - work held up"]] },
    { k: "assignee", label: "Or name" }, { k: "ball_in_court", label: "Ball in court" }].concat(isNew ? [] : [
    { k: "answer", label: "Answer", wide: true }, { k: "answered_by", label: "Answered by" }, { k: "answered_on", label: "Answered on", type: "date" },
    { k: "cost_impact", label: "Cost impact", type: "select", options: [["no", "No"], ["yes", "Yes"], ["tbd", "To be decided"]] },
    { k: "schedule_impact", label: "Time impact", type: "select", options: [["no", "No"], ["yes", "Yes"], ["tbd", "To be decided"]] }]),
  Object.assign({ priority: "normal" }, r || {}));
  const save = async (extra, msg) => { await run("fld.rfi_save", { row: Object.assign(f.values(), { id: r && r.id, project_id: S.project }, extra || {}) }, msg || "Saved"); done && done(); };
  const btns = [{ label: isNew ? "Send the RFI" : "Save", cls: "primary", act: () => save(isNew ? { status: "open" } : {}) }];
  if (isNew) btns.push({ label: "Save as draft", act: () => save({ status: "draft" }) });
  if (!isNew) {
    if (r.status === "draft") btns.push({ label: "Send", act: () => save({ status: "open" }, "Sent") });
    if (r.status === "open") btns.push({ label: "Record the answer", act: () => save({ status: "answered" }, "Answer recorded") });
    if (r.status === "answered") btns.push({ label: "Close", act: () => save({ status: "closed" }, "Closed") });
    if (!r.event_id && (r.cost_impact === "yes" || r.schedule_impact === "yes") && can("commercial", "edit")) btns.push({ label: "Make an event (cost / time)", act: async () => { await run("fld.rfi_to_event", { id: r.id }, (x) => "Event " + x.no + " made"); done && done(); } });
    btns.push({ label: "Print", act: () => printFrame("RFI " + r.no, h("div", {}, kv([["RFI", r.no], ["Subject", r.subject], ["To", r.who], ["Answer needed by", r.due_date || ""], ["Drawing", r.drawing_no || ""], ["Location", r.location || ""]]),
      h("h3", {}, "Question"), h("p", { style: "white-space:pre-wrap" }, r.question), h("h3", {}, "Answer"), h("p", { style: "white-space:pre-wrap;min-height:120px" }, r.answer || "")), [["Status", r.status]]) });
  }
  modal(isNew ? "New RFI (request for information)" : r.no + " — " + r.subject, h("div", {}, f, isNew ? null : h("div", { style: "margin-top:12px" }, recordPanel("fld_rfis", r.id, { project_id: S.project }))), btns);
}
PAGES["f/rfis"] = async (root, params) => {
  if (need(root, "RFIs")) return;
  await meta(true);
  let v = { status: "" };
  const holder = h("div");
  const load = async () => {
    const rows = await run("fld.rfis", Object.assign({ project_id: S.project }, v));
    holder.innerHTML = "";
    holder.append(summaryStrip([["Waiting for answer", rows.filter((x) => x.status === "open").length], ["Late", rows.filter((x) => x.overdue).length], ["Answered, to close", rows.filter((x) => x.status === "answered").length]]));
    holder.append(table([{ k: "no", label: "No." }, { k: "subject", label: "Subject" }, { k: "who", label: "Asked" }, { label: "Needed by", v: due },
      { label: "Status", v: (r) => pill(label(META.rfi_status, r.status), ST_COL[r.status] || "#667085") }, { label: "Days", v: (r) => r.days_open ?? "" },
      { label: "Impact", v: (r) => [r.cost_impact === "yes" ? "cost" : "", r.schedule_impact === "yes" ? "time" : ""].filter(Boolean).join(" + ") }],
    rows, { name: "rfis", title: "RFIs", empty: "No RFI yet. Ask the designer here instead of by phone - the answer is then on record.", rowClass: (r) => (r.overdue ? "flag" : ""), onRow: (r) => rfiDialog(r, load) }));
  };
  root.append(pageHead("RFIs", "Questions to the engineer or designer, with who has to answer, by when, and the answer on record. An answer that changes cost or time becomes an event.",
    can("project", "edit") ? h("button", { class: "btn primary", onclick: () => rfiDialog(null, load) }, "New RFI") : null),
  filterBar([{ k: "status", label: "Status", type: "select", blank: "All", options: META.rfi_status }], v, (x) => { v = x; load(); }), holder);
  await load();
  if (params.id) { const r = (await run("fld.rfis", { project_id: S.project })).find((x) => String(x.id) === String(params.id)); if (r) rfiDialog(r, load); }
};

/* ── Meetings ── */
async function meetingEditor(id, done) {
  const m = await run("fld.meeting_get", { id });
  const f = form([{ k: "title", label: "Title", req: true }, { k: "kind", label: "Kind" }, { k: "date", label: "Date", type: "date" }, { k: "time", label: "Time" },
    { k: "place", label: "Place" }, { k: "attendees", label: "Present (names, organisation)", wide: true }, { k: "notes", label: "General notes", wide: true }, { k: "next_date", label: "Next meeting", type: "date" }], m);
  const tb = h("tbody");
  const addRow = (it) => {
    const inp = (k, w) => { const i = h("input", { value: it[k] || "", style: "width:" + (w || 140) + "px" }); return i; };
    const topic = inp("topic", 140), disc = h("textarea", { rows: 2, style: "width:220px" }); disc.value = it.discussion || "";
    const act = h("textarea", { rows: 2, style: "width:200px" }); act.value = it.action || "";
    const owner = h("select", {}, h("option", { value: "" }, "—"), META.users.map((x) => h("option", { value: x.id }, x.name))); owner.value = it.owner_user_id || "";
    const ownerTxt = inp("owner", 110); ownerTxt.placeholder = "or name";
    const dd = h("input", { type: "date", value: it.due_date || "" });
    const st = h("select", {}, h("option", { value: "open" }, "open"), h("option", { value: "done" }, "done")); st.value = it.status || "open";
    const tr = h("tr", {}, h("td", {}, topic), h("td", {}, disc), h("td", {}, act), h("td", {}, owner, ownerTxt), h("td", {}, dd), h("td", {}, st), h("td", {}, it.carried_from ? h("span", { class: "hint" }, "carried") : "", h("button", { class: "btn small", onclick: () => tr.remove() }, "✕")));
    tr._v = () => ({ id: it.id, topic: topic.value, discussion: disc.value, action: act.value, owner_user_id: owner.value, owner: ownerTxt.value, due_date: dd.value, status: st.value });
    tb.append(tr);
  };
  m.items.forEach(addRow);
  if (!m.items.length) addRow({});
  const body = h("div", {}, f, h("h3", {}, "Points and actions"), h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Topic", "Discussion / decision", "Action", "Who", "By", "Status", ""].map((x) => h("th", {}, x)))), tb)),
    h("button", { class: "btn small", onclick: () => addRow({}) }, "+ point"), h("p", { class: "hint" }, "An action given to a BuildCore user becomes a task in their My work. Open actions carry forward to the next meeting of the same kind."));
  const save = async (extra) => run("fld.meeting_save", { row: Object.assign(f.values(), { id }, extra || {}), items: [...tb.children].map((t) => t._v()) }, "Minutes saved");
  modal(m.no + " — " + (m.title || "Meeting"), body, [{ label: "Save", cls: "primary", act: async () => { await save(); done && done(); } },
    { label: "Save and issue", act: async () => { await save({ status: "issued" }); done && done(); } },
    { label: "Print minutes", act: async () => { const x = await save(); printDoc("Minutes of meeting " + x.no, [["Meeting", x.title], ["Date", (x.date || "") + " " + (x.time || "")], ["Place", x.place || ""], ["Present", x.attendees || ""]],
      [{ k: "topic", label: "Topic" }, { k: "discussion", label: "Discussion / decision" }, { k: "action", label: "Action" }, { label: "By", v: (i) => (META.users.find((u_) => String(u_.id) === String(i.owner_user_id)) || {}).name || i.owner || "" }, { k: "due_date", label: "Due" }, { k: "status", label: "Status" }],
      x.items, [], x.notes || ""); return false; } }]);
}
PAGES["f/meetings"] = async (root) => {
  if (need(root, "Meetings")) return;
  await meta(true);
  const holder = h("div");
  const load = async () => {
    const rows = await run("fld.meetings", { project_id: S.project });
    holder.innerHTML = "";
    holder.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "kind", label: "Kind" }, { k: "title", label: "Title" }, { k: "status", label: "Status" },
      { label: "Open actions", v: (r) => (r.open_actions ? h("b", {}, r.open_actions) : "") }], rows, { name: "meetings", title: "Meetings", empty: "No meeting yet.", onRow: (r) => meetingEditor(r.id, load) }));
  };
  const kinds = ["Site progress", "Client / consultant", "Safety", "Sub-contractors", "Design coordination"];
  root.append(pageHead("Meetings", "Minutes with decisions and actions. Actions go to the owner's My work; open ones carry to the next meeting of the same kind.",
    can("project", "edit") ? h("span", {}, ...kinds.slice(0, 3).map((k) => h("button", { class: "btn " + (k === "Site progress" ? "primary" : ""), onclick: async () => { const r = await run("fld.meeting_new", { project_id: S.project, kind: k }, (x) => "Meeting " + x.no + (x.carried ? " - " + x.carried + " open action(s) carried forward" : "")); load(); meetingEditor(r.id, load); } }, "New " + k.toLowerCase() + " meeting"))) : null), holder);
  await load();
};

/* ── Inspections ── */
async function inspectionForm(tpl, existing, done) {
  const answers = existing ? existing.answers : tpl.items.map((x) => ({ text: x.text, kind: x.kind, value: "", note: "" }));
  const f = form([{ k: "title", label: "Title" }, { k: "date", label: "Date", type: "date" }, { k: "location", label: "Location / element" },
    { k: "party_id", label: "Sub-contractor", type: "select", options: partyOpts }, { k: "inspector", label: "Inspected by" }, { k: "remarks", label: "Remarks", wide: true }],
  existing || { title: tpl.name, date: today(), inspector: S.user && S.user.name });
  const rows = answers.map((a) => {
    let el;
    if (a.kind === "pf") {
      el = h("span", { class: "pfbtns" });
      [["pass", "✓ Pass", "#2f7a4d"], ["fail", "✕ Fail", "#b42318"], ["na", "N/A", "#667085"]].forEach(([k, l, col]) => {
        const b = h("button", { class: "btn small", style: a.value === k ? "background:" + col + ";color:#fff" : "", onclick: () => { a.value = k; [...el.children].forEach((x) => { x.style.background = ""; x.style.color = ""; }); b.style.background = col; b.style.color = "#fff"; } }, l);
        el.append(b);
      });
    } else {
      el = h("input", { type: a.kind === "num" ? "number" : "text", value: a.value || "", style: "width:160px", oninput: (e) => { a.value = e.target.value; } });
    }
    const note = h("input", { value: a.note || "", placeholder: "note", style: "width:200px", oninput: (e) => { a.note = e.target.value; } });
    return h("tr", {}, h("td", {}, a.text), h("td", {}, el), h("td", {}, note));
  });
  modal((existing ? existing.no + " — " : "") + tpl.name, h("div", {}, f, h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Check"), h("th", {}, "Result"), h("th", {}, "Note"))), h("tbody", {}, rows))),
    h("p", { class: "hint" }, "Every item marked Fail becomes an issue by itself, assigned to the sub-contractor chosen above.")),
  [{ label: "Save", cls: "primary", act: async () => {
    const r = await run("fld.inspection_save", { row: Object.assign(f.values(), { id: existing && existing.id, project_id: S.project, template_id: tpl.id }), answers },
      (x) => x.no + ": " + x.result + (x.issues_raised.length ? " - issues raised: " + x.issues_raised.join(", ") : ""));
    done && done(); return r;
  } }]);
}
function templateEditor(t, done) {
  const f = form([{ k: "name", label: "Form name", req: true }, { k: "category", label: "Category", type: "select", noBlank: true, options: [["Quality", "Quality"], ["Safety", "Safety"], ["Handover", "Handover"], ["Environment", "Environment"], ["Other", "Other"]] }], t || { category: "Quality" });
  const ta = h("textarea", { rows: 12, placeholder: "One check per line. End a line with  [num]  for a number or  [text]  for words; others are pass / fail / N/A." });
  ta.value = ((t && t.items) || []).map((x) => x.text + (x.kind === "num" ? " [num]" : x.kind === "text" ? " [text]" : "")).join("\n");
  modal(t ? "Edit form " + t.name : "New inspection form", h("div", {}, f, ta), [{ label: "Save", cls: "primary", act: async () => {
    const items = ta.value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => ({ text: l.replace(/\s*\[(num|text)\]\s*$/i, ""), kind: /\[num\]\s*$/i.test(l) ? "num" : /\[text\]\s*$/i.test(l) ? "text" : "pf" }));
    await run("fld.template_save", { row: Object.assign(f.values(), { id: t && t.id, items }) }, "Form saved"); done && done();
  } }]);
}
PAGES["f/inspections"] = async (root) => {
  if (need(root, "Inspections")) return;
  await meta(true);
  const holder = h("div");
  let tpls = [];
  const load = async () => {
    tpls = await run("fld.templates", {});
    const rows = await run("fld.inspections", { project_id: S.project });
    holder.innerHTML = "";
    holder.append(h("div", { class: "scrgrid", style: "margin-bottom:16px" }, tpls.map((t) => h("a", { class: "scr", href: "javascript:void 0", onclick: () => can("project", "edit") ? inspectionForm(t, null, load) : null },
      h("span", { class: "dot", style: "background:" + (t.category === "Safety" ? "#b42318" : t.category === "Handover" ? "#7a4fb3" : "#1769aa") }), h("span", {}, h("b", {}, t.name), h("br"), h("small", { class: "muted" }, t.category + " · " + t.items.length + " checks"))))));
    holder.append(table([{ k: "no", label: "No." }, { k: "date", label: "Date" }, { k: "template", label: "Form" }, { k: "location", label: "Where" }, { k: "party", label: "Sub-contractor" },
      { k: "inspector", label: "By" }, { label: "Result", v: (r) => pill(r.result + (r.failed ? " (" + r.failed + ")" : ""), ST_COL[r.result] || "#667085") }],
    rows, { name: "inspections", title: "Inspections", empty: "No inspection yet - pick a form above.", onRow: async (r) => { const x = await run("fld.inspection_get", { id: r.id }); const t = tpls.find((y) => y.id === x.template_id) || { id: x.template_id, name: r.template, items: [] }; inspectionForm(t, x, load); } }));
  };
  root.append(pageHead("Inspections", "Check-list forms on site: pour cards, excavation and scaffold safety, weekly safety walk, masonry, house handover - or your own. A failed check becomes an issue.",
    can("project", "edit") ? h("button", { class: "btn", onclick: () => templateEditor(null, load) }, "New form") : null), holder);
  await load();
};

/* ── Quality dashboard ── */
PAGES["f/quality"] = async (root) => {
  if (need(root, "Quality dashboard")) return;
  const d = await run("fld.quality", { project_id: S.project });
  root.append(pageHead("Quality dashboard", "Issues opened and closed each week, who has open items, and how fast RFIs are answered."));
  root.append(h("div", { class: "tiles" }, tile("Open issues", d.open), tile("Late", d.overdue, { cls: d.overdue ? "bad" : "" }), tile("Closed", d.closed), tile("Days to close (avg)", d.avg_days_to_close ?? "—"), tile("RFIs waiting", d.rfi_open)));
  const mx = Math.max(1, ...d.weeks.map((w) => Math.max(w.opened, w.closed)));
  root.append(h("div", { class: "panel" }, h("h3", {}, "Issues each week (opened / closed)"), h("div", { style: "display:flex;gap:6px;align-items:flex-end;height:140px" },
    d.weeks.map((w) => h("div", { style: "flex:1;display:flex;flex-direction:column;align-items:center;gap:2px", title: w.week + ": " + w.opened + " opened, " + w.closed + " closed" },
      h("div", { style: "display:flex;gap:2px;align-items:flex-end;height:110px" }, h("div", { style: "width:10px;background:#c05621;height:" + (100 * w.opened / mx) + "%" }), h("div", { style: "width:10px;background:#2f7a4d;height:" + (100 * w.closed / mx) + "%" })),
      h("small", { class: "muted" }, w.week.slice(5))))), h("p", { class: "hint" }, "Orange opened, green closed. If orange keeps beating green, the list is growing.")));
  root.append(h("div", { class: "cols" }, h("div", {}, h("h3", {}, "Who has open issues"), table([{ k: "who", label: "Who" }, { k: "open", label: "Open", fmt: "num" }, { k: "overdue", label: "Late", fmt: "num" }], d.by_party, { search: false, export: false, empty: "None open." })),
    h("div", {}, h("h3", {}, "RFI answers by party"), table([{ k: "who", label: "Party" }, { k: "rfis", label: "RFIs", fmt: "num" }, { k: "open", label: "Waiting", fmt: "num" }, { k: "overdue", label: "Late", fmt: "num" }, { label: "Avg days to answer", v: (r) => r.avg_days ?? "—" }], d.rfi_response, { search: false, export: false, empty: "No RFI yet." }))));
};

/* ── Client progress report ── */
PAGES["f/report"] = async (root) => {
  if (need(root, "Client progress report")) return;
  const f = form([{ k: "from", label: "From", type: "date" }, { k: "to", label: "To", type: "date" }], { from: new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10), to: today() });
  const out = h("div");
  const make = async () => {
    const d = await run("fld.client_report", Object.assign({ project_id: S.project }, f.values()));
    out.innerHTML = "";
    const ta = h("textarea", { rows: 18, style: "width:100%;font-family:inherit" }); ta.value = d.text;
    const gal = h("div", { class: "gallery" }, d.photos.map((p) => h("figure", {}, h("img", { src: fileUrl(p.id), loading: "lazy" }), h("figcaption", {}, (p.date || "") + " " + (p.caption || p.location || "")))));
    out.append(h("div", { class: "panel" }, h("p", { class: "hint" }, "Written from the DPRs, photos, issues and bills of the period. Change any words before you send it."), ta,
      d.photos.length ? h("div", {}, h("h3", {}, "Photos of the period"), gal) : h("p", { class: "muted" }, "No photos in this period - add some in Documents & photos."),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => printFrame("Progress report " + d.project, h("div", {}, h("pre", { style: "white-space:pre-wrap;font-family:inherit;font-size:14px" }, ta.value), gal.cloneNode(true)), [["Period", d.from + " to " + d.to]]) }, "Print / save as PDF"),
        h("button", { class: "btn", onclick: (e) => { navigator.clipboard && navigator.clipboard.writeText(ta.value); e.target.textContent = "Copied ✓"; } }, "Copy text"))));
  };
  root.append(pageHead("Client progress report", "A plain progress report for the client or house owner - work done, time lost, what comes next, snags and bills, with the photos."),
    h("div", { class: "panel" }, f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: make }, "Write the report"))), out);
  await make();
};

/* ── simpler: shorter forms ── */
if (typeof form === "function" && !form._bco215) {
  const _form = form;
  const simple = function (fields, values, onchange) {
    const el = _form(fields, values, onchange);
    try {
      if (LSg("bco_simple_forms", "1") !== "1") return el;
      const vis = (fields || []).filter((f) => !f.hide);
      if (vis.length <= 8 || el.children.length !== vis.length) return el;
      const vals = values || {};
      const keep = (f, i) => i < 4 || f.req || (vals[f.k] != null && vals[f.k] !== "" && vals[f.k] !== 0) || f.type === "check" && vals[f.k];
      const extra = [];
      vis.forEach((f, i) => { if (!keep(f, i)) extra.push(el.children[i]); });
      if (extra.length < 3) return el;
      const inner = h("div", { class: "grid" });
      extra.forEach((x) => inner.append(x));
      const det = h("details", { style: "grid-column:1/-1;margin-top:2px" }, h("summary", { style: "cursor:pointer;color:var(--muted);font-size:13px" }, "More details (" + extra.length + ")"), inner);
      el.append(det);
      // a required field moved? keep it visible
      el.set = ((s) => (k, v) => { s(k, v); if (v) det.open = det.open || !!inner.querySelector(`[name="${k}"]`); })(el.set);
    } catch (e) { /* never break a form */ }
    return el;
  };
  simple._bco215 = true;
  window.form = simple;
  try { form = simple; } catch (e) { /* ignore */ }
}

/* ── menu, home and + New ── */
function ensureItems() {
  if (typeof MENU === "undefined") return;
  const add = (group, after, item, first) => {
    const g = MENU.find((x) => x[0] === group); if (!g || g[2].some((y) => y[0] === item[0])) return;
    if (first) { g[2].unshift(item); return; }
    const i = g[2].findIndex((y) => y[0] === after); g[2].splice(i >= 0 ? i + 1 : g[2].length, 0, item);
  };
  add("Overview", null, ["mywork", "My work", null], true);
  let prev = "p/docs";
  [["f/drawings", "Drawings"], ["f/issues", "Issues & punch list"], ["f/rfis", "RFIs"], ["f/inspections", "Inspections"], ["f/meetings", "Meetings"],
    ["f/quality", "Quality dashboard"], ["f/report", "Client progress report"]].forEach((it) => { add("Work", prev, it); prev = it[0]; });
}
(window.bcoBootHooks = window.bcoBootHooks || []).unshift(() => { try { ensureItems(); } catch (e) { /* ignore */ } });
try { ensureItems(); } catch (e) { /* MENU not loaded yet */ }

const _home = PAGES.home;
if (_home && !_home._bco215) {
  PAGES.home = async (root) => {
    await _home(root);
    try {
      const d = await api("fld.mywork", {});
      const hero = root.querySelector(".modhero");
      const strip = h("div", { style: "display:flex;gap:12px;flex-wrap:wrap;margin:0 0 16px;align-items:stretch" },
        h("a", { href: "#/mywork", class: "panel", style: "flex:1;min-width:260px;text-decoration:none;color:inherit;margin:0;border-left:4px solid " + (d.counts.overdue ? "#b42318" : "#1769aa") },
          h("b", { style: "font-size:17px" }, "My work: " + d.counts.total + " open"), h("div", { class: "muted" }, d.counts.overdue + " late · " + d.counts.this_week + " due this week" + (typeof approvalsCount !== "undefined" && approvalsCount ? " · " + approvalsCount + " to approve" : "")),
          h("div", { style: "margin-top:6px;font-size:13px" }, d.items.slice(0, 3).map((x) => h("div", { style: x.overdue ? "color:#b42318" : "" }, "• " + x.kind + ": " + x.title)))),
        h("div", { class: "panel", style: "flex:2;min-width:300px;margin:0" }, h("b", {}, "Quick entry"), typeof window.quickActions === "function" ? window.quickActions(false) : null));
      if (hero) hero.after(strip); else root.prepend(strip);
    } catch (e) { /* home still works without it */ }
  };
  PAGES.home._bco215 = true;
}

const NEW_EXTRA = [["Issue / snag", "#/f/issues?new=1", "project", "view"], ["RFI", "#/f/rfis?new=1", "project", "edit"], ["Inspection", "#/f/inspections", "project", "edit"],
  ["Meeting minutes", "#/f/meetings", "project", "edit"], ["Drawing", "#/f/drawings?new=1", "project", "edit"]];
setInterval(() => {
  const m = document.querySelector(".qamenu");
  if (!m || m._bco215) return;
  m._bco215 = true;
  NEW_EXTRA.filter(([, , mod, a]) => can(mod, a)).forEach(([l, href]) => m.append(h("a", { href, onclick: () => { m.hidden = true; } }, l)));
}, 1000);
/* "?new=1" on the new screens opens the entry form */
window.addEventListener("hashchange", () => {
  const hs = location.hash;
  setTimeout(() => {
    if (location.hash !== hs || document.querySelector(".overlay") || !/new=1/.test(hs)) return;
    const page = document.getElementById("page");
    const b = page && [...page.querySelectorAll("button.btn.primary")].find((x) => /^(report an issue|new rfi|add drawing)/i.test(x.textContent.trim()));
    if (b) b.click();
  }, 1200);
});

/* the shorter-forms switch, in Configure (the person menu) */
window.bcoSimpleForms = (on) => { LSs("bco_simple_forms", on ? "1" : "0"); };

})();
