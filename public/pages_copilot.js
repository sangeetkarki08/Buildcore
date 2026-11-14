/* BuildCore 2.10 — Copilot: ask for a report in plain words, write letters / notices / reports from the data,
   saved reports and drafts, Word and Excel files, and extra fields of your own (Master data › Extra fields). */
(function () {
  "use strict";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const css = document.createElement("style");
  css.textContent = [
    ".cop-ask{display:flex;gap:8px;align-items:flex-end}.cop-ask textarea{flex:1;min-height:56px;border-radius:10px;padding:10px 12px;font-size:14px}",
    ".cop-ex{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 14px}.cop-ex button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 11px;cursor:pointer;font-size:12.5px}",
    ".cop-ex button:hover{border-color:var(--blue);color:var(--blue)}",
    ".cop-res{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-top:14px}",
    ".cop-res h2{margin:0 0 4px;font-size:18px}.cop-res .desc{color:var(--muted);margin:0 0 10px}",
    ".cop-res .acts{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 10px}",
    ".cop-sql{font:12px/1.5 Consolas,monospace;width:100%;min-height:110px;border-radius:8px;background:#fafcfd}",
    ".cop-chart{margin:6px 0 12px;overflow-x:auto}.cop-chart svg text{font-size:11px;fill:#40505b}",
    ".cop-wait{color:var(--muted);margin-top:12px;font-style:italic}",
    ".cop-write{display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:16px;align-items:start}",
    "@media (max-width:980px){.cop-write{grid-template-columns:1fr}}",
    ".cop-doc{background:#fff;border:1px solid var(--line);border-radius:10px;padding:22px 26px;min-height:300px;line-height:1.55;font-size:14px}",
    ".cop-doc h4{margin:12px 0 6px}.cop-doc p{margin:0 0 8px}",
    ".cop-edit{width:100%;min-height:380px;font:13.5px/1.55 'Segoe UI',Arial,sans-serif;border-radius:10px;padding:12px}",
    ".cf-grid td input,.cf-grid td select{width:100%;min-width:110px;border:1px solid transparent;background:transparent;padding:4px 6px;border-radius:6px}",
    ".cf-grid td input:hover,.cf-grid td select:hover{border-color:var(--line)}.cf-grid td input:focus,.cf-grid td select:focus{border-color:var(--blue);background:#fff}",
    ".cf-grid td.saved input,.cf-grid td.saved select{background:#e9f7ef}.cf-grid td.bad input{background:#fdeceb}",
  ].join("");
  document.head.append(css);

  async function waitJob(id, onStep) {
    const end = Date.now() + 10 * 60000;
    while (Date.now() < end) {
      await sleep(1100);
      const j = await api("ai.job", { id });
      if (onStep && j.step) onStep(j.step);
      if (j.status === "done") return j.result;
      if (j.status === "failed") throw new Error(j.error || "Copilot could not finish.");
    }
    throw new Error("Copilot took too long. Try again.");
  }
  function download(name, b64, mime) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr], { type: mime }));
    const a = h("a", { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function md(text) {
    const lines = esc(text || "").split(/\r?\n/);
    let out = "", list = null;
    const inline = (s) => s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\[([^\]]+)\]\((#\/[^)\s]*)\)/g, '<a href="$2">$1</a>');
    const close = () => { if (list) { out += "</" + list + ">"; list = null; } };
    lines.forEach((ln) => {
      const t = ln.trim(); let m;
      if (!t) { close(); out += ""; return; }
      if ((m = t.match(/^#{1,4}\s+(.*)$/))) { close(); out += "<h4>" + inline(m[1]) + "</h4>"; return; }
      if ((m = t.match(/^[-*•]\s+(.*)$/))) { if (list !== "ul") { close(); out += "<ul>"; list = "ul"; } out += "<li>" + inline(m[1]) + "</li>"; return; }
      if ((m = t.match(/^\d+[.)]\s+(.*)$/))) { if (list !== "ol") { close(); out += "<ol>"; list = "ol"; } out += "<li>" + inline(m[1]) + "</li>"; return; }
      close(); out += "<p>" + inline(t) + "</p>";
    });
    close();
    return h("div", { html: out });
  }

  let AIST = null;
  async function aiOn() { if (!AIST) { try { AIST = await api("ai.status", {}); } catch (e) { AIST = { on: false }; } } return AIST; }

  /* ───────────────────────── a report on screen ───────────────────────── */
  const isNum = (v) => typeof v === "number";
  function reportTable(res, title) {
    const numCol = res.columns.map((_, i) => res.rows.length && res.rows.every((r) => r[i] == null || isNum(r[i])) && res.rows.some((r) => isNum(r[i])));
    const cols = res.columns.map((c, i) => ({ label: c, fmt: numCol[i] ? "num" : null,
      v: (r) => { const x = r["c" + i]; return x == null ? "" : numCol[i] ? (Number.isInteger(x) && !/amount|value|cost|total|rate|npr|vat|price/i.test(c) ? fmtN(x, 0) : fmtN(x, 2)) : String(x); } }));
    const rows = res.rows.map((r) => Object.fromEntries(r.map((x, i) => ["c" + i, x])));
    return table(cols, rows, { name: title || "report", empty: "No rows — nothing matches." });
  }
  function chartOf(res, ch) {
    if (!ch || !ch.type || ch.type === "none" || !res.rows.length || res.rows.length > 60) return null;
    const xi = Math.max(0, res.columns.indexOf(ch.x));
    let yi = res.columns.indexOf(ch.y);
    if (yi < 0) yi = res.columns.findIndex((c, i) => i !== xi && res.rows.every((r) => r[i] == null || typeof r[i] === "number"));
    if (yi < 0) return null;
    const pts = res.rows.map((r) => [String(r[xi] ?? ""), Number(r[yi]) || 0]);
    const W = Math.max(520, pts.length * (ch.type === "bar" ? 46 : 30)), H = 240, L = 70, B = 60, T = 14;
    const max = Math.max(...pts.map((p) => p[1]), 0), min = Math.min(...pts.map((p) => p[1]), 0);
    const span = max - min || 1;
    const y = (v) => T + (H - T - B) * (1 - (v - min) / span);
    const step = (W - L - 10) / pts.length;
    let s = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '">';
    for (let k = 0; k <= 4; k++) { const v = min + span * k / 4; s += '<line x1="' + L + '" x2="' + (W - 10) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="#e6ecef"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + esc(fmtN(v, v > 100 ? 0 : 2)) + "</text>"; }
    if (ch.type === "line") {
      s += '<polyline fill="none" stroke="#1769aa" stroke-width="2.5" points="' + pts.map((p, i) => (L + step * (i + 0.5)) + "," + y(p[1])).join(" ") + '"/>';
      pts.forEach((p, i) => { s += '<circle cx="' + (L + step * (i + 0.5)) + '" cy="' + y(p[1]) + '" r="3" fill="#1769aa"><title>' + esc(p[0] + ": " + fmtN(p[1], 2)) + "</title></circle>"; });
    } else {
      pts.forEach((p, i) => { const x0 = L + step * i + step * 0.15, h0 = Math.abs(y(p[1]) - y(0)); s += '<rect x="' + x0 + '" y="' + Math.min(y(p[1]), y(0)) + '" width="' + step * 0.7 + '" height="' + Math.max(h0, 1) + '" rx="3" fill="#1769aa"><title>' + esc(p[0] + ": " + fmtN(p[1], 2)) + "</title></rect>"; });
    }
    pts.forEach((p, i) => { const lbl = p[0].length > 14 ? p[0].slice(0, 13) + "…" : p[0]; s += '<text transform="translate(' + (L + step * (i + 0.5)) + "," + (H - B + 14) + ') rotate(35)">' + esc(lbl) + "</text>"; });
    s += "</svg>";
    return h("div", { class: "cop-chart", html: s });
  }

  function showReport(box, res, opts) {
    opts = opts || {};
    box.innerHTML = "";
    const card = h("div", { class: "cop-res" });
    const sqlBox = h("textarea", { class: "cop-sql", spellcheck: "false" }, res.sql || "");
    const sqlWrap = h("details", {}, h("summary", { style: "cursor:pointer;color:var(--muted);font-size:12.5px" }, "The query behind this report (read-only)"), sqlBox,
      h("div", { class: "actions" }, h("button", { class: "btn small", onclick: async () => {
        try { const r = await api("cop.run", { sql: sqlBox.value }); showReport(box, Object.assign({}, res, r, { sql: sqlBox.value }), opts); } catch (e) { toast(e.message, "err"); }
      } }, "Run this query")));
    const follow = h("input", { placeholder: "Change it… e.g. only Headworks, add the unit, by month", style: "flex:1" });
    const acts = h("div", { class: "acts" },
      h("button", { class: "btn small primary", onclick: () => saveDialog(res) }, opts.saved ? "Save changes" : "Save as my report"),
      h("button", { class: "btn small", onclick: async () => { const r = await run("cop.xlsx", { title: res.title, columns: res.columns, rows: res.rows }); download(r.filename, r.b64, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); } }, "Excel"),
      h("button", { class: "btn small", onclick: () => printFrame(res.title || "Report", h("div", {}, res.description ? h("p", {}, res.description) : null, reportTable(res, res.title))) }, "Print"));
    card.append(h("h2", {}, res.title || "Report"), res.description ? h("p", { class: "desc" }, res.description) : null,
      h("p", { class: "hint" }, res.rows.length + " row(s)" + (res.truncated ? " — only the first 2000 shown; ask for less" : "")),
      acts, chartOf(res, res.chart), reportTable(res, res.title));
    if (opts.allowFollow !== false) {
      const go2 = async () => { if (!follow.value.trim()) return; await askReport(box, follow.value.trim(), res); };
      follow.addEventListener("keydown", (e) => { if (e.key === "Enter") go2(); });
      card.append(h("div", { class: "bar", style: "margin-top:10px" }, follow, h("button", { class: "btn small", onclick: go2 }, "Change")));
    }
    card.append(sqlWrap);
    box.append(card);
  }

  function saveDialog(res) {
    const f = form([{ k: "title", label: "Report name", wide: true, req: true }, { k: "description", label: "What it shows", type: "textarea", wide: true }].concat(
      S.user.role === "admin" ? [{ k: "shared", label: "Everyone in this company can use it", type: "check", wide: true }] : []), res);
    modal("Save report", f, [{ label: "Save", cls: "primary", act: async () => {
      const v = f.values();
      await run("cop.save_report", { row: { id: res.saved_id, title: v.title, description: v.description, shared: v.shared, sql: res.sql, question: res.question, chart: res.chart } }, "Saved in My reports");
    } }], { narrow: true });
  }

  async function askReport(box, question, previous) {
    const wait = h("p", { class: "cop-wait" }, "Copilot is working…");
    if (previous) box.append(wait); else { box.innerHTML = ""; box.append(wait); }
    try {
      const r = await api("cop.report", { question, previous: previous ? { title: previous.title, sql: previous.sql } : null, project_id: S.project || null });
      const res = await waitJob(r.job, (s) => { wait.textContent = s; });
      res.question = question;
      showReport(box, res);
    } catch (e) { wait.className = "red"; wait.textContent = e.message; }
  }

  const EXAMPLES = ["Cement issued per site last month", "Diesel used per machine this month", "Stock value by store and kind",
    "Purchase orders late for delivery", "Top 10 vendors by purchase this fiscal year", "Machines idle or under breakdown with days down",
    "Monthly expenses by account this year", "BOQ items executed more than the contract quantity", "VAT on purchases and sales per month"];

  /* ───────────────────────── Copilot page ───────────────────────── */
  PAGES["copilot"] = async (root, params) => {
    const st = await aiOn();
    root.append(pageHead("Copilot", "Ask for a report in your own words, or have a letter, notice or progress report written from BuildCore's data. Copilot only reads; it never changes your data."));
    if (!st.on) root.append(h("div", { class: "panel", style: "background:#fff9e6" }, h("b", {}, "The AI is off. "), "Saved reports, drafts and extra fields still work. ",
      can("admin", "edit") ? h("a", { href: "#/admin/ai" }, "Switch the AI on in AI assistant settings.") : "An administrator can switch it on in Administration › AI assistant settings."));
    const order = ["report", "reports", "write", "drafts"];
    root.append(tabs([
      ["Ask for a report", () => reportTab(st)],
      ["My reports", () => myReports()],
      ["Write", () => writeTab(st, params)],
      ["My drafts", () => myDrafts()],
    ], Math.max(0, order.indexOf((params && params.tab) || "report"))));
  };

  function reportTab(st) {
    const wrap = h("div", { style: "max-width:1200px" });
    const ta = h("textarea", { placeholder: "What do you want to see?  e.g.  cement issued per site last month, with the value" });
    const out = h("div");
    const go1 = () => { const t = ta.value.trim(); if (t) askReport(out, t); };
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go1(); } });
    wrap.append(h("div", { class: "cop-ask" }, ta, h("button", { class: "btn primary", disabled: !st.on, onclick: go1 }, "Show")),
      h("div", { class: "cop-ex" }, EXAMPLES.map((x) => h("button", { onclick: () => { ta.value = x; if (st.on) go1(); } }, x))),
      h("p", { class: "hint" }, "Copilot sees only what your role may see. Check the figures before you rely on them; the query is shown under each report."), out);
    setTimeout(() => ta.focus(), 50);
    return wrap;
  }

  async function myReports() {
    const box = h("div");
    const list = await run("cop.reports", {});
    const out = h("div");
    box.append(table([{ k: "title", label: "Report" }, { k: "description", label: "What it shows" },
      { label: "For", v: (r) => r.shared ? "everyone" : "me" }, { label: "", v: (r) => (r.user_id === S.user.id || S.user.role === "admin") ? h("button", { class: "btn small", onclick: async (e) => {
        e.stopPropagation(); if (await ask("Delete report", "Delete “" + r.title + "”?", { danger: true, ok: "Delete" })) { await run("cop.delete_report", { id: r.id }, "Deleted"); go(); }
      } }, "Delete") : "" }],
    list, { name: "my_reports", empty: "No saved reports yet. Ask for a report and press “Save as my report”.", onRow: async (r) => {
      out.innerHTML = ""; out.append(h("p", { class: "cop-wait" }, "Running…"));
      try {
        const res = await api("cop.run", { id: r.id });
        let ch = {}; try { ch = JSON.parse(r.chart || "{}"); } catch (e) { /* ignore */ }
        showReport(out, Object.assign(res, { title: r.title, description: r.description, sql: r.sql, chart: ch, saved_id: r.user_id === S.user.id ? r.id : null, question: r.question }), { saved: r.user_id === S.user.id, allowFollow: !!(AIST && AIST.on) });
        out.scrollIntoView({ behavior: "smooth" });
      } catch (e) { out.innerHTML = ""; out.append(h("p", { class: "red" }, e.message)); }
    } }), out);
    return box;
  }

  /* ───────────────────────── writing ───────────────────────── */
  const KINDS = [["letter_client", "Letter to client / engineer"], ["letter_vendor", "Letter to supplier / subcontractor"], ["notice", "Notice (delay, claim, variation, EOT)"],
    ["progress", "Monthly progress report text"], ["minutes", "Minutes of meeting"], ["summary", "Summary for management"], ["other", "Other"]];

  async function writeTab(st, params) {
    const contracts = await api("con.list", {}).catch(() => []);
    const draft = { id: null };
    const f = form([
      { k: "kind", label: "What to write", type: "select", noBlank: true, options: KINDS, wide: true },
      { k: "contract_id", label: "Contract (optional)", type: "select", options: contracts.map((k) => [k.id, (k.ref_no ? k.ref_no + " — " : "") + k.title]), wide: true },
      { k: "language", label: "Language", type: "select", noBlank: true, options: [["English", "English"], ["Nepali", "नेपाली (Nepali)"]], wide: true },
      { k: "instructions", label: "What should it say?", type: "textarea", wide: true, ph: "e.g. Request extension of time of 45 days for the powerhouse due to the landslide on 12 Sept that blocked access for 18 days; mention the DPR delay records." },
      { k: "screen", label: "Also use what is on my last screen", type: "check", wide: true },
    ], { kind: "letter_client", language: "English" });
    const title = h("input", { placeholder: "Title of the draft", style: "flex:1" });
    const editor = h("textarea", { class: "cop-edit", placeholder: "The text appears here. You can edit it freely." });
    const preview = h("div", { class: "cop-doc", hidden: true });
    const step = h("span", { class: "muted" });
    let lastScreen = window.__bcoLastScreenText || "";
    const btnWrite = h("button", { class: "btn primary", disabled: !st.on }, "Write");
    const doWrite = async (change) => {
      const v = f.values();
      const instr = change ? change : v.instructions;
      if (!instr || !instr.trim()) return toast("Say what it should say.", "err");
      btnWrite.disabled = true; step.textContent = "Copilot is writing…";
      try {
        const r = await api("cop.write", { kind: v.kind, contract_id: v.contract_id || null, project_id: S.project || null, language: v.language, instructions: instr,
          previous: change ? editor.value : null, screen_text: v.screen ? lastScreen : "" });
        const x = await waitJob(r.job, (s) => { step.textContent = s; });
        editor.value = x.text;
        if (!title.value) title.value = (KINDS.find((k) => k[0] === v.kind) || ["", "Draft"])[1] + " — " + today();
        preview.hidden = true; editor.hidden = false; step.textContent = "Done — check every fact and [placeholder] before sending.";
      } catch (e) { step.textContent = ""; toast(e.message, "err"); }
      finally { btnWrite.disabled = !st.on; }
    };
    btnWrite.onclick = () => doWrite(null);
    const change = h("input", { placeholder: "Change it… e.g. shorter, more formal, add the cube test results", style: "flex:1" });
    change.addEventListener("keydown", (e) => { if (e.key === "Enter" && change.value.trim()) { doWrite(change.value.trim()); change.value = ""; } });
    const save = async () => {
      const v = f.values();
      const r = await run("cop.draft_save", { row: { id: draft.id, title: title.value || "Draft", kind: v.kind, body: editor.value, contract_id: v.contract_id || null, project_id: S.project || null } }, "Draft saved");
      draft.id = r.id;
    };
    const right = h("div", {},
      h("div", { class: "bar" }, title,
        h("button", { class: "btn small", onclick: () => { preview.innerHTML = ""; preview.append(md(editor.value)); preview.hidden = !preview.hidden; editor.hidden = !preview.hidden; } }, "Preview / edit"),
        h("button", { class: "btn small", onclick: save }, "Save draft"),
        h("button", { class: "btn small", onclick: async () => { if (!editor.value.trim()) return; const r = await run("cop.docx", { title: title.value || "Letter", body: editor.value }); download(r.filename, r.b64, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"); } }, "Word"),
        h("button", { class: "btn small", onclick: () => printFrame(title.value || "Letter", md(editor.value)) }, "Print"),
        h("button", { class: "btn small", onclick: async () => { try { await navigator.clipboard.writeText(editor.value); toast("Copied", "ok"); } catch (e) { editor.select(); document.execCommand("copy"); toast("Copied", "ok"); } } }, "Copy")),
      editor, preview, h("div", { class: "bar", style: "margin-top:8px" }, change, h("button", { class: "btn small", disabled: !st.on, onclick: () => { if (change.value.trim()) { doWrite(change.value.trim()); change.value = ""; } } }, "Change")));
    if (params && params.draft) {
      try {
        const d = await api("cop.draft", { id: Number(params.draft) });
        draft.id = d.id; title.value = d.title; editor.value = d.body; f.set("kind", d.kind); if (d.contract_id) f.set("contract_id", d.contract_id);
      } catch (e) { /* gone */ }
    }
    return h("div", { class: "cop-write" }, h("div", { class: "panel" }, f, h("div", { class: "actions" }, btnWrite), step,
      h("p", { class: "hint" }, "Copilot uses the contract, its approved conditions and BuildCore's figures. Missing facts come as [placeholders]. You check and send.")), right);
  }

  async function myDrafts() {
    const list = await run("cop.drafts", {});
    return table([{ k: "title", label: "Draft" }, { label: "Kind", v: (r) => (KINDS.find((k) => k[0] === r.kind) || ["", r.kind])[1] },
      { label: "Changed", v: (r) => (r.updated || "").replace("T", " ").slice(0, 16) },
      { label: "", v: (r) => h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); if (await ask("Delete draft", "Delete “" + r.title + "”?", { danger: true, ok: "Delete" })) { await run("cop.draft_delete", { id: r.id }, "Deleted"); go(); } } }, "Delete") }],
    list, { name: "drafts", empty: "No drafts yet.", onRow: (r) => { location.hash = "#/copilot?tab=write&draft=" + r.id; } });
  }

  /* remember the last real screen's text, so "use what is on my last screen" works from the Copilot page */
  setInterval(() => {
    try {
      if (!/^#\/copilot/.test(location.hash)) {
        const pg = document.querySelector("#page");
        if (pg) window.__bcoLastScreenText = ((document.querySelector("#page h1") || {}).textContent || "") + "\n" + pg.innerText.slice(0, 15000);
      }
    } catch (e) { /* ignore */ }
  }, 2000);

  /* ───────────────────────── Master data › Extra fields ───────────────────────── */
  PAGES["m/fields"] = async (root, params) => {
    const ents = (await run("cf.entities", {})).filter((x) => x.can_view);
    const ent = (params && params.e) || (ents[0] && ents[0].entity);
    root.append(pageHead("Extra fields", "Your own fields on materials, machines, parties, projects, contracts, staff and BOQ items — like Tally's user-defined fields. Copilot reports can use them."));
    const sel = h("select", { onchange: () => { location.hash = "#/m/fields?e=" + sel.value; } }, ents.map((x) => h("option", { value: x.entity, selected: x.entity === ent }, x.label)));
    root.append(h("div", { class: "bar" }, h("label", { class: "f", style: "flex-direction:row;align-items:center;gap:8px" }, h("b", {}, "List"), sel),
      h("div", { class: "grow" }), can("admin", "edit") ? h("button", { class: "btn", onclick: () => defsDialog(ent, ents) }, "Add or change fields…") : null));
    if (!ent) return;
    const g = await run("cf.grid", { entity: ent });
    if (!g.fields.length) {
      root.append(h("div", { class: "panel" }, h("p", {}, "No extra fields for " + g.label.toLowerCase() + " yet."),
        can("admin", "edit") ? h("button", { class: "btn primary", onclick: () => defsDialog(ent, ents) }, "+ Add a field") : h("p", { class: "hint" }, "An administrator adds the fields.")));
      return;
    }
    const filter = h("input", { type: "search", placeholder: "Find a row", style: "max-width:260px" });
    const tb = h("tbody");
    const cell = (r, f) => {
      const v = r.values[String(f.id)] || "";
      let inp;
      if (f.kind === "choice") inp = h("select", { disabled: !g.can_edit }, h("option", { value: "" }, ""), (f.options || "").split(",").map((o) => o.trim()).filter(Boolean).map((o) => h("option", { value: o, selected: o === v }, o)));
      else if (f.kind === "yesno") inp = h("select", { disabled: !g.can_edit }, [["", ""], ["Yes", "Yes"], ["No", "No"]].map(([a, b]) => h("option", { value: a, selected: a === v }, b)));
      else inp = h("input", { type: f.kind === "date" ? "date" : "text", value: v, readonly: !g.can_edit, inputmode: f.kind === "number" ? "decimal" : null });
      const td = h("td", {}, inp);
      inp.addEventListener("change", async () => {
        td.classList.remove("saved", "bad");
        try { const x = await api("cf.set", { entity: ent, entity_id: r.id, field_id: f.id, value: inp.value }); r.values[String(f.id)] = x.value; inp.value = x.value; td.classList.add("saved"); setTimeout(() => td.classList.remove("saved"), 1200); }
        catch (e) { td.classList.add("bad"); toast(e.message, "err"); }
      });
      return td;
    };
    const draw = () => {
      const t = filter.value.trim().toLowerCase();
      tb.innerHTML = "";
      g.rows.filter((r) => !t || ((r.code || "") + " " + (r.name || "") + " " + Object.values(r.values).join(" ")).toLowerCase().includes(t)).slice(0, 800)
        .forEach((r) => tb.append(h("tr", {}, h("td", { class: "muted", style: "white-space:nowrap" }, r.code || ""), h("td", {}, r.name || ""), g.fields.map((f) => cell(r, f)))));
    };
    filter.addEventListener("input", draw);
    draw();
    root.append(h("div", { class: "bar" }, filter, h("span", { class: "hint" }, g.can_edit ? "Type in a cell; it is saved when you leave it." : "Your role can look but not change these."),
      h("div", { class: "grow" }), h("button", { class: "btn small", onclick: async () => {
        const cols = ["Code", "Name"].concat(g.fields.map((f) => f.label));
        const rows = g.rows.map((r) => [r.code || "", r.name || ""].concat(g.fields.map((f) => { const v = r.values[String(f.id)]; return f.kind === "number" && v !== undefined && v !== "" ? Number(v) : (v || ""); })));
        const x = await run("cop.xlsx", { title: "Extra fields — " + g.label, columns: cols, rows });
        download(x.filename, x.b64, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
      } }, "Excel")),
    h("div", { class: "tablewrap" }, h("table", { class: "cf-grid" }, h("thead", {}, h("tr", {}, h("th", {}, "Code"), h("th", {}, "Name"), g.fields.map((f) => h("th", {}, f.label)))), tb)));
  };

  async function defsDialog(ent, ents) {
    const defs = await api("cf.defs", { entity: ent, all: 1 });
    const box = h("div");
    const KIND = [["text", "Text"], ["number", "Number"], ["date", "Date"], ["choice", "Choice from a list"], ["yesno", "Yes / No"]];
    const drawList = () => {
      box.innerHTML = "";
      box.append(defs.length ? table([{ k: "label", label: "Field" }, { label: "Type", v: (d) => (KIND.find((k) => k[0] === d.kind) || ["", d.kind])[1] }, { k: "options", label: "Choices" },
        { label: "In use", v: (d) => d.active ? "yes" : "switched off" }], defs, { search: false, export: false, onRow: (d) => edit(d) }) : h("p", { class: "muted" }, "No fields yet."));
    };
    const edit = (d) => {
      d = d || { entity: ent, kind: "text", active: 1 };
      const f = form([{ k: "label", label: "Field name", req: true, wide: true }, { k: "kind", label: "Type", type: "select", noBlank: true, options: KIND },
        { k: "options", label: "Choices (for a choice field), separated by commas", wide: true, ph: "e.g. Imported, Local" }, { k: "sort", label: "Order", type: "number" },
        { k: "active", label: "In use", type: "check" }], d);
      modal(d.id ? "Change field" : "New field", f, [{ label: "Save", cls: "primary", act: async () => {
        const v = f.values();
        const r = await run("cf.def_save", { row: Object.assign({ id: d.id, entity: ent }, v) }, "Field saved");
        const i = defs.findIndex((x) => x.id === r.id); if (i >= 0) defs[i] = r; else defs.push(r); drawList();
      } }], { narrow: true });
    };
    drawList();
    modal("Extra fields — " + (ents.find((x) => x.entity === ent) || {}).label, h("div", {}, box), [{ label: "+ New field", keep: true, act: () => { edit(); return false; } }], { onClose: () => go() });
  }
})();
