/* BuildCore 2.34 — Document library.
   Every file in BuildCore in one place, found by the words inside it: files added here, files attached to records
   (letters, DPRs, IPCs, drawings…) and Document control revisions. Ported from the Document Manager tool:
   full-text search with phrases, OR and -word, categories detected from names, tags, revisions and duplicate check.
   Files stay in BuildCore's data folder; nothing is filed on disk. */
"use strict";
(function () {
  const PER = 50;
  const kb = (n) => n == null ? "" : n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  const marked = (pieces) => (pieces || []).map(([t, m]) => m ? h("mark", {}, t) : t);
  const dateText = (d) => d ? cellValue({ k: "date" }, { date: d }) : "";
  const TEXT = { ok: "Text read", pending: "Waiting to be read", empty: "No text inside (scan or picture)", unsupported: "Text not readable for this type",
                 error: "Could not read the text", missing: "File missing from the data folder" };

  if (!document.getElementById("dl-style")) {
    document.head.append(h("style", { id: "dl-style" }, `
      .dl-res { border-top: 1px solid var(--line); padding: 9px 4px; display: flex; gap: 10px; align-items: flex-start; }
      .dl-res:hover { background: var(--blue-wash); }
      .dl-res .t { font-weight: 600; cursor: pointer; }
      .dl-res .m { color: var(--muted); font-size: 12px; margin-top: 2px; }
      .dl-res .s { font-size: 13px; margin-top: 3px; color: var(--ink, inherit); }
      .dl-res mark, .dl-text mark { background: #ffe58a; color: inherit; padding: 0 1px; border-radius: 2px; }
      .dl-type { display: inline-block; min-width: 46px; text-align: center; font-size: 11px; border: 1px solid var(--line); border-radius: 4px; padding: 1px 4px; color: var(--muted); }
      .dl-text { white-space: pre-wrap; max-height: 260px; overflow: auto; font-size: 12px; background: var(--panel); border: 1px solid var(--line); padding: 8px; border-radius: 6px; }
      .dl-prog { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; margin: 6px 0; }
      .dl-prog i { display: block; height: 100%; background: var(--blue); }
    `));
  }

  /* upload one file to the data folder, then put it in the library */
  async function addOne(file, opts) {
    const qs = new URLSearchParams({ filename: file.name, mime: file.type || "", entity: "dl_doc" });
    if (opts.project_id) qs.set("project_id", opts.project_id);
    const r = await fetch("/api/upload?" + qs.toString(), { method: "POST", headers: { "X-Token": S.token }, body: file });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    return api("dl.add", Object.assign({}, opts, { file_id: j.data.id }));
  }

  /* read the text of waiting files, a few seconds at a time, showing progress */
  async function indexAll(box, onDone) {
    let first = null;
    for (let guard = 0; guard < 2000; guard++) {
      let r;
      try { r = await api("dl.index", { budget: 3 }); } catch (e) { box.innerHTML = ""; box.append(h("p", { class: "hint red" }, e.message)); return; }
      if (first === null) first = r.left + r.done;
      box.innerHTML = "";
      if (!r.left) break;
      const pct = first ? Math.round(100 * (first - r.left) / first) : 0;
      box.append(h("div", { class: "hint" }, "Reading the text inside the files… " + r.left + " left"), h("div", { class: "dl-prog" }, h("i", { style: "width:" + pct + "%" })));
      if (!r.done) break;
    }
    box.innerHTML = "";
    if (onDone) onDone();
  }

  function searchHelp() {
    modal("How to search", h("div", {},
      h("p", {}, "Type words that appear anywhere: in the title, document number, tags, file name, project, category or the text inside the file."),
      table([{ k: "a", label: "Type" }, { k: "b", label: "Finds" }], [
        { a: "weir concrete", b: "documents with both words (word starts count: concr finds concrete)" },
        { a: "\"variation order\"", b: "the exact phrase" },
        { a: "cement OR steel", b: "either word" },
        { a: "drawing -draft", b: "drawing, but not documents that mention draft" },
      ], { search: false, export: false }),
      h("p", { class: "hint" }, "Text is read from PDF, Word (.docx), Excel (.xlsx, .xls, .csv), PowerPoint (.pptx), e-mails (.eml, .msg), text and web files. Scanned PDFs and photos have no text to read; give them a good title and tags.")), [], { narrow: true });
  }

  /* add files or a whole folder */
  function addDialog(meta, done) {
    let picked = [];
    const isFolder = { v: false };
    const projByCode = {};
    meta.projects.forEach((p) => { projByCode[String(p.code).toLowerCase()] = p.id; });
    const f = form([
      { k: "project_id", label: "Project", type: "select", options: meta.projects.map((p) => [p.id, p.code + " " + p.name]), blank: "No project (company)", default: S.project || "" },
      { k: "category_id", label: "Category", type: "select", options: meta.categories.map((k) => [k.id, k.name]), blank: "Detect from the name" },
      { k: "tags", label: "Tags (comma separated)", ph: "e.g. headworks, 2026" },
      { k: "doc_date", label: "Document date", type: "date", hint: "Empty = the day the file is added" },
      { k: "by_folder", label: "A top folder named after a project code goes to that project", type: "check", default: 1, wide: true },
    ], {});
    const list = h("div", { class: "hint" }, "No files chosen yet.");
    const prog = h("div");
    const show = () => {
      list.innerHTML = "";
      if (!picked.length) { list.append("No files chosen yet."); return; }
      const size = picked.reduce((a, x) => a + x.size, 0);
      list.append(picked.length + " file(s), " + kb(size) + (isFolder.v ? " from a folder" : ""));
      const big = picked.filter((x) => x.size > 58 * 1048576);
      if (big.length) list.append(h("div", { class: "red" }, big.length + " file(s) over 58 MB will be skipped (" + big.slice(0, 3).map((x) => x.name).join(", ") + ")."));
    };
    const fin = h("input", { type: "file", multiple: true, style: "display:none", onchange: () => { picked = [...fin.files]; isFolder.v = false; show(); } });
    const din = h("input", { type: "file", multiple: true, webkitdirectory: true, style: "display:none", onchange: () => { picked = [...din.files]; isFolder.v = true; show(); } });
    const body = h("div", {}, f,
      h("div", { class: "bar" }, fin, din,
        h("button", { class: "btn", type: "button", onclick: () => fin.click() }, "Choose files…"),
        h("button", { class: "btn", type: "button", onclick: () => din.click() }, "Choose a folder…")),
      list, prog,
      h("p", { class: "hint" }, "A file whose content is already in the library is not added twice. Folder names help detect the category (a folder called Drawings puts its files in Drawings)."));
    modal("Add documents to the library", body, [{ label: "Add", cls: "primary", act: async () => {
      const v = f.values();
      const files = picked.filter((x) => x.size > 0 && x.size <= 58 * 1048576);
      if (!files.length) { toast("Choose files or a folder first.", "err"); return false; }
      let added = 0, dup = 0, failed = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const rel = file.webkitRelativePath || "";
        const parts = rel.split("/").slice(0, -1);
        let pid = v.project_id || "";
        if (Number(v.by_folder) && parts.length) {
          for (const p of parts) { const hit = projByCode[p.toLowerCase()] || projByCode[p.toLowerCase().split(/[\s_-]+/)[0]]; if (hit) { pid = hit; break; } }
        }
        prog.innerHTML = "";
        prog.append(h("div", { class: "hint" }, "Adding " + (i + 1) + " of " + files.length + ": " + file.name), h("div", { class: "dl-prog" }, h("i", { style: "width:" + Math.round(100 * i / files.length) + "%" })));
        try {
          const r = await addOne(file, { project_id: pid, category_id: v.category_id, tags: v.tags, doc_date: v.doc_date, folder_hint: parts.join(" / ") });
          if (r.status === "duplicate") dup++; else added++;
        } catch (e) { failed++; toast(file.name + ": " + e.message, "err"); }
      }
      prog.innerHTML = "";
      toast(added + " added" + (dup ? ", " + dup + " already in the library" : "") + (failed ? ", " + failed + " failed" : ""), failed ? "err" : "ok");
      done();
      return true;
    } }]);
  }

  /* one document: details, edit, new revision, earlier files */
  async function openDoc(id, meta, reload) {
    let d;
    try { d = await api("dl.get", { id }); } catch (e) { toast(e.message, "err"); return; }
    const isLib = d.source === "library";
    const edit = meta.can_edit ? form([
      { k: "title", label: "Title", req: true, wide: true },
      { k: "doc_number", label: "Document no." },
      { k: "revision", label: "Revision" },
      { k: "doc_date", label: "Date", type: "date" },
      { k: "project_id", label: "Project", type: "select", options: meta.projects.map((p) => [p.id, p.code + " " + p.name]), blank: "No project (company)", readonly: !isLib },
      { k: "category_id", label: "Category", type: "select", options: meta.categories.map((k) => [k.id, k.name]) },
      { k: "tags", label: "Tags", wide: true },
      { k: "description", label: "Description", type: "textarea", wide: true },
    ], d) : null;
    const where = d.link ? (d.link.href ? h("a", { href: d.link.href, onclick: () => m.close() }, d.link.label) : d.link.label) : (isLib ? "Library" : "");
    const revIn = h("input", { type: "file", style: "display:none", onchange: async () => {
      const file = revIn.files[0]; if (!file) return;
      const rev = await ask("New revision", "Revision of the new file (empty = read it from the file name):", { input: "e.g. C", ok: "Upload" });
      if (rev === null) return;
      try {
        const r = await fetch("/api/upload?" + new URLSearchParams({ filename: file.name, mime: file.type || "", entity: "dl_doc" }), { method: "POST", headers: { "X-Token": S.token }, body: file });
        const j = await r.json(); if (!j.ok) throw new Error(j.error);
        await run("dl.revision", { id: d.id, file_id: j.data.id, revision: rev }, "New revision saved; the earlier file is kept");
        m.close(); reload(); indexAll(meta._ibox, reload);
      } catch (e) { toast(e.message, "err"); }
    } });
    const body = h("div", {},
      h("div", { class: "bar" },
        h("a", { class: "btn primary", href: fileUrl(d.file_id), target: "_blank" }, "Open file"),
        h("a", { class: "btn", href: fileUrl(d.file_id), download: d.file_name }, "Save a copy"),
        meta.can_edit && isLib ? [revIn, h("button", { class: "btn", type: "button", onclick: () => revIn.click() }, "Upload new revision")] : null,
        meta.can_edit ? h("button", { class: "btn", type: "button", onclick: async () => { await run("dl.reindex", { ids: [d.id] }); m.close(); indexAll(meta._ibox, reload); } }, "Read text again") : null),
      kv([["File", d.file_name + " · " + d.type_label + " · " + kb(d.size)], ["Attached to", where], ["Added", (d.added_at || "").slice(0, 10)],
          ["Text", TEXT[d.text_status] + (d.text_chars ? " (" + fmtQty(d.text_chars) + " characters)" : "")],
          d.active ? null : ["Status", h("b", { class: "red" }, "Removed from the library")]]),
      edit,
      d.duplicates.length ? h("div", { class: "panel" }, h("b", {}, "Same file elsewhere"),
        h("ul", {}, d.duplicates.map((x) => h("li", {}, h("a", { href: "#", onclick: (e) => { e.preventDefault(); m.close(); openDoc(x.id, meta, reload); } }, x.title), " · " + (x.project_code || "No project") + " · " + x.source)))) : null,
      d.versions.length ? h("div", {}, h("h4", {}, "Earlier files"), table([
        { label: "Revision", k: "revision" }, { label: "File", v: (r) => h("a", { href: fileUrl(r.file_id), target: "_blank" }, r.file_name) },
        { label: "Replaced", v: (r) => (r.archived_at || "").slice(0, 10) }, { label: "By", k: "by_name" }, { label: "Size", v: (r) => kb(r.size) }], d.versions, { search: false, export: false })) : null,
      d.text_excerpt ? h("div", {}, h("h4", {}, "Text inside the file"), h("div", { class: "dl-text" }, d.text_excerpt + (d.text_more ? "\n… " + fmtQty(d.text_more) + " more characters" : ""))) : null);
    const m = drawer(d.title, body, [
      edit ? { label: "Save", cls: "primary", act: async () => { await run("dl.update", { id: d.id, row: edit.values() }, "Saved"); reload(); } } : null,
      meta.can_approve ? { label: d.active ? "Remove from library" : "Bring back", cls: d.active ? "warn" : "", act: async () => {
        if (d.active && !(await ask("Remove from the library", "The file is not deleted: it stays in its record and can be brought back from Show › Removed.", { danger: true, ok: "Remove" }))) return false;
        await run("dl.remove", { id: d.id, restore: d.active ? 0 : 1 }, d.active ? "Removed from the library" : "Back in the library"); reload();
      } } : null]);
  }

  function categoriesDialog(meta, reload) {
    const box = h("div");
    const load = async () => {
      const rows = await api("dl.categories", {});
      box.innerHTML = "";
      box.append(h("p", { class: "hint" }, "Keywords decide the category of a new file: a word in its name or folder puts it in that category. The first match in this order wins."),
        table([{ k: "sort_order", label: "Order", fmt: "num" }, { k: "name", label: "Category" }, { k: "keywords", label: "Keywords", v: (r) => (r.keywords || "").slice(0, 90) }, { k: "n", label: "Documents", fmt: "num" }],
          rows, { search: false, export: false, onRow: (r) => edit(r) }),
        h("div", { class: "bar" }, h("button", { class: "btn", onclick: () => edit({ sort_order: 100 }) }, "New category"),
          h("button", { class: "btn", onclick: async () => { const r = await run("dl.recategorise", {}); toast(r.changed + " document(s) moved out of Other", "ok"); reload(); load(); } }, "Detect again for documents in Other")));
    };
    const edit = (r) => {
      const f = form([{ k: "name", label: "Name", req: true }, { k: "sort_order", label: "Order", type: "number" }, { k: "keywords", label: "Keywords (comma separated)", type: "textarea", wide: true }], r);
      modal(r.id ? "Category " + r.name : "New category", f, [
        { label: "Save", cls: "primary", act: async () => { await run("dl.category_save", { row: Object.assign({ id: r.id }, f.values()) }, "Saved"); load(); reload(); } },
        r.id && r.name !== "Other" ? { label: "Delete", cls: "warn", act: async () => {
          if (!(await ask("Delete category", "Its documents move to Other.", { danger: true }))) return false;
          await run("dl.category_delete", { id: r.id }, "Deleted"); load(); reload();
        } } : null], { narrow: true });
    };
    load();
    modal("Document categories", box, []);
  }

  PAGES.dl = async (root, params) => {
    const meta = await api("dl.meta", {});
    const st = meta.stats;
    const v = { q: params.q || "", project_id: params.project_id || "", category_id: params.category_id || "", type: "", date_from: "", date_to: "", tag: params.tag || "",
                source: "", sort: "", old: 0, removed: 0, page: 1 };
    const ticked = new Set();
    const ibox = h("div");
    meta._ibox = ibox;
    const results = h("div");
    const chips = h("div", { class: "chips" });
    const bulkBar = h("div", { class: "bar" });

    const qbox = h("input", { type: "search", id: "dl-q", value: v.q, placeholder: "Search titles, numbers, tags and the text inside files", style: "flex:1;min-width:260px",
                              onkeydown: (e) => { if (e.key === "Enter") { v.q = qbox.value; v.page = 1; load(); } } });
    const filt = form([
      { k: "project_id", label: "Project", type: "select", options: [["none", "No project (company)"]].concat(meta.projects.map((p) => [p.id, p.code + " " + p.name])), blank: "All projects" },
      { k: "type", label: "Type", type: "select", options: meta.types, blank: "All types" },
      { k: "source", label: "Where", type: "select", options: meta.sources, blank: "Everywhere" },
      { k: "date_from", label: "Date from", type: "date" }, { k: "date_to", label: "Date to", type: "date" },
      { k: "tag", label: "Tag" },
      { k: "sort", label: "Order", type: "select", noBlank: true, options: [["", "Best match / newest"], ["newest", "Newest first"], ["oldest", "Oldest first"], ["title", "Title A–Z"], ["added", "Recently added"]] },
      { k: "old", label: "Include superseded revisions", type: "check" },
      { k: "removed", label: "Show removed", type: "check" },
    ], v);
    filt.className = "bar";
    filt.append(h("button", { class: "btn primary", onclick: () => { Object.assign(v, filt.values(), { q: qbox.value, page: 1 }); load(); } }, "Show"));

    const paintChips = () => {
      chips.innerHTML = "";
      const chip = (id, label, n) => h("span", { class: "chip" + (String(v.category_id) === String(id) ? " on" : ""), onclick: () => { v.category_id = id; v.page = 1; load(); } }, label, n != null ? h("i", {}, n) : null);
      chips.append(chip("", "All categories"), meta.categories.filter((k) => k.n).map((k) => chip(k.id, k.name, k.n)));
    };
    const paintBulk = () => {
      bulkBar.innerHTML = "";
      if (!ticked.size || !meta.can_edit) return;
      const ids = [...ticked];
      const doBulk = async (args, msg) => { const r = await run("dl.bulk", Object.assign({ ids }, args)); toast(r.done + " " + msg + (r.skipped ? ", " + r.skipped + " attached to records kept in their project" : ""), "ok"); ticked.clear(); load(); };
      const psel = h("select", { style: "width:auto" }, h("option", { value: "" }, "Move to project…"), h("option", { value: "0" }, "No project (company)"), meta.projects.map((p) => h("option", { value: p.id }, p.code + " " + p.name)));
      psel.onchange = () => { if (psel.value !== "") doBulk({ action: "project", project_id: psel.value }, "moved"); };
      const csel = h("select", { style: "width:auto" }, h("option", { value: "" }, "Set category…"), meta.categories.map((k) => h("option", { value: k.id }, k.name)));
      csel.onchange = () => { if (csel.value) doBulk({ action: "category", category_id: csel.value }, "re-categorised"); };
      bulkBar.append(h("b", {}, ticked.size + " ticked"), psel, csel,
        h("button", { class: "btn small", onclick: async () => { const t = await ask("Add tags", "Tags to add (comma separated):", { input: "e.g. claim, 2026", ok: "Add" }); if (t) doBulk({ action: "tags", tags: t }, "tagged"); } }, "Add tags"),
        h("button", { class: "btn small", onclick: async () => { await run("dl.reindex", { ids }); ticked.clear(); indexAll(ibox, load); } }, "Read text again"),
        meta.can_approve ? h("button", { class: "btn small warn", onclick: () => doBulk({ action: v.removed ? "restore" : "remove" }, v.removed ? "brought back" : "removed") }, v.removed ? "Bring back" : "Remove from library") : null,
        h("button", { class: "btn small", onclick: () => { ticked.clear(); load(); } }, "Clear"));
    };

    const load = async () => {
      paintChips();
      let r;
      try { r = await api("dl.search", Object.assign({}, v, { per_page: PER })); } catch (e) { results.innerHTML = ""; results.append(h("p", { class: "red" }, e.message)); return; }
      results.innerHTML = "";
      paintBulk();
      if (r.error) { results.append(h("p", { class: "red" }, r.error)); return; }
      const pages = Math.max(1, Math.ceil(r.total / PER));
      results.append(h("div", { class: "bar" }, h("b", {}, r.total + " document" + (r.total === 1 ? "" : "s")), v.q ? h("span", { class: "hint" }, "for: " + v.q) : null, h("div", { class: "grow" }),
        r.rows.length ? h("label", { class: "hint" }, h("input", { type: "checkbox", onchange: (e) => { r.rows.forEach((x) => e.target.checked ? ticked.add(x.id) : ticked.delete(x.id)); load(); } }), " tick all on this page") : null));
      if (!r.rows.length) {
        results.append(h("p", { class: "hint" }, st.total ? "Nothing matches. Try fewer words, the start of a word, or clear the filters." : "The library is empty. Use Add documents, or attach files to records; they appear here by themselves."));
        return;
      }
      r.rows.forEach((d) => {
        const cb = h("input", { type: "checkbox", checked: ticked.has(d.id), onchange: () => { cb.checked ? ticked.add(d.id) : ticked.delete(d.id); paintBulk(); } });
        results.append(h("div", { class: "dl-res" }, meta.can_edit ? cb : null, h("span", { class: "dl-type" }, (d.ext || "").replace(".", "").toUpperCase() || "FILE"),
          h("div", { class: "grow" },
            h("div", { class: "t", onclick: () => openDoc(d.id, meta, load) }, marked(d.title_marked),
              d.doc_number ? h("span", { class: "hint" }, "  " + d.doc_number) : null, d.revision ? h("span", { class: "tag" }, "Rev " + d.revision) : null,
              d.tag_list.map((t) => h("span", { class: "tag", style: "cursor:pointer", onclick: (e) => { e.stopPropagation(); v.tag = t; v.page = 1; filt.querySelector("[name=tag]").value = t; load(); } }, t))),
            h("div", { class: "m" }, [d.project_code || "No project", d.category_name || "No category", dateText(d.doc_date), kb(d.size), d.where ? "on a " + d.where : "",
              d.text_status !== "ok" && d.text_status !== "pending" ? TEXT[d.text_status] : ""].filter(Boolean).join(" · ")),
            d.snippet && d.snippet.length ? h("div", { class: "s" }, marked(d.snippet)) : null),
          h("a", { class: "btn small", href: fileUrl(d.file_id), target: "_blank", title: d.file_name }, "Open")));
      });
      if (pages > 1) results.append(h("div", { class: "bar" },
        h("button", { class: "btn small", disabled: v.page <= 1, onclick: () => { v.page--; load(); } }, "‹ Previous"),
        h("span", { class: "hint" }, "Page " + v.page + " of " + pages),
        h("button", { class: "btn small", disabled: v.page >= pages, onclick: () => { v.page++; load(); } }, "Next ›")));
    };

    const exportCsvBtn = h("button", { class: "btn", onclick: async () => {
      const r = await run("dl.export_csv", Object.assign({}, v, filt.values(), { q: qbox.value }));
      const a = h("a", { href: URL.createObjectURL(new Blob([r.csv], { type: "text/csv" })), download: r.filename });
      document.body.append(a); a.click(); a.remove();
    } }, "Export CSV");
    const more = h("select", { style: "width:auto" }, h("option", { value: "" }, "More…"), h("option", { value: "check" }, "Check for missing files"),
      meta.can_approve ? h("option", { value: "all" }, "Read the text of every file again") : null, h("option", { value: "help" }, "How to search"));
    more.onchange = async () => {
      const k = more.value; more.value = "";
      if (k === "check") { const r = await run("dl.check", {}); toast(r.missing ? r.missing + " file(s) missing from the data folder (shown in red)" : "All files are in the data folder", r.missing ? "err" : "ok"); load(); }
      if (k === "all" && (await ask("Read every file again", "This reads the text of all " + st.total + " documents again. It runs in the background on this screen.", { ok: "Start" }))) { await run("dl.reindex", {}); indexAll(ibox, load); }
      if (k === "help") searchHelp();
    };

    root.append(pageHead("Document library",
      st.total + " documents, " + kb(st.size) + " · files added here, attachments on records and Document control revisions, searchable by the words inside them",
      meta.can_edit ? h("button", { class: "btn primary", onclick: () => addDialog(meta, () => { load(); indexAll(ibox, load); }) }, "Add documents") : null,
      exportCsvBtn, meta.can_approve ? h("button", { class: "btn", onclick: () => categoriesDialog(meta, load) }, "Categories") : null, more),
      h("div", { class: "bar" }, qbox, h("button", { class: "btn primary", onclick: () => { v.q = qbox.value; v.page = 1; load(); } }, "Search"),
        h("a", { href: "#", class: "hint", onclick: (e) => { e.preventDefault(); searchHelp(); } }, "search tips")),
      ...[!meta.fts ? h("p", { class: "hint" }, "Fast search is not available on this computer; plain search is used.") : null,
      filt, chips, ibox, bulkBar, results].filter(Boolean));
    await load();
    if (params.doc) openDoc(Number(params.doc), meta, load);
    if (st.pending) indexAll(ibox, load);
  };
})();
