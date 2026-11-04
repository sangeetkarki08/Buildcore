/* BuildCore 2.47 — BOQ by location: overall summary and short codes.
   Two new tabs on Commercial › BOQ control (the menu is unchanged): "Summary by item" and "Short codes".
   Every BOQ picker in the app (DPR, requisitions, PR / PO, issues, measurements, IPC, budgets, cost codes …) shows the
   short code first, so typing HW-M25 or M25 finds the line. Off for existing companies until Commercial approve turns it on. */
(function () {
  "use strict";
  if (window.__bcoBoqLoc) return;
  window.__bcoBoqLoc = true;

  const ROUTE = "p/boq";
  const M = (v) => (v == null ? "—" : fmtMoney(v));
  const Q = (v) => (v == null || v === "" ? "" : fmtQty(v));
  const P = (v) => (v == null ? "" : v + "%");

  /* ───────── pickers and names: short code first ───────── */
  const longLabel = (b, n) => (b.sc ? b.sc + " · " : "") + b.code + " " + (b.description || "").slice(0, n) + (b.overall ? " (overall line)" : "");
  if (typeof nm !== "undefined") {
    const nm0 = nm.boq;
    nm.boq = (id) => { const x = byId(S.L.boq || [], id); return x && x.sc ? longLabel(x, 40) : nm0(id); };
  }
  if (typeof opt !== "undefined") {
    const opt0 = opt.boq;
    opt.boq = (pid) => {
      const list = (S.L.boq || []).filter((b) => String(b.project_id) === String(pid));
      if (!list.some((b) => b.sc)) return opt0(pid);
      /* location lines first (in short-code order), overall lines last */
      return list.slice().sort((a, b) => (a.overall ? 1 : 0) - (b.overall ? 1 : 0) || String(a.sc || a.code).localeCompare(String(b.sc || b.code), undefined, { numeric: true }))
        .map((b) => [b.id, longLabel(b, 50)]);
    };
  }

  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const needProj = () => h("div", { class: "panel" }, h("b", {}, "Select a project"), h("p", { class: "hint" }, "Choose a project in the bar at the top."));
  const offNote = (st, box) => h("div", { class: "panel" }, h("b", {}, "BOQ short codes and the summary by item are off for this company."),
    h("p", { class: "hint" }, "Nothing changes until it is turned on: open the Short codes tab to see the codes BuildCore would give your BOQ, then turn it on (Commercial approve)."),
    h("button", { class: "btn", onclick: () => { location.hash = "#/p/boq?tab=" + tabIndex("Short codes"); } }, "Open Short codes"));
  const tabIndex = (label) => { const t = (PAGES[ROUTE] && PAGES[ROUTE].__bco && PAGES[ROUTE].__bco.tabs) || []; const i = t.findIndex((x) => x[0] === label); return i < 0 ? 0 : i + 1; };
  const sevCls = { red: "bad", amber: "flag", info: "" };

  /* ───────── summary by item ───────── */
  function matrixCols(d, mode) {
    const locCols = d.locations.map((l) => ({ label: l.abbr, fmt: mode === "amount" ? "money" : "qty", v: (r) => (r.by_loc[l.abbr] != null ? (mode === "amount" ? (r.amt_loc || {})[l.abbr] : r.by_loc[l.abbr]) : "") }));
    return [{ k: "key", label: "Item" }, { label: "Description", v: (r) => h("span", { style: "display:inline-block;min-width:280px;max-width:420px", title: r.title || "" }, (r.title || "").slice(0, 90)) }, { k: "unit", label: "Unit" }].concat(locCols, [
      { k: "qty", label: "Total qty", fmt: "qty" }, { label: "BOQ overall", fmt: "qty", v: (r) => (r.stated_qty == null ? "" : r.stated_qty) },
      { label: "Rate", v: (r) => (r.rates_differ ? fmtMoney(r.rate_min) + " – " + fmtMoney(r.rate_max) : M(r.rate)) },
      { k: "amount", label: "Amount", fmt: "money" }, { k: "executed_qty", label: "Executed", fmt: "qty" }, { label: "Progress", v: (r) => P(r.progress_pct) },
      { k: "measured_qty", label: "Measured", fmt: "qty" }, { k: "billed_qty", label: "Billed", fmt: "qty" }, { k: "certified_qty", label: "Certified", fmt: "qty" },
      { k: "balance_qty", label: "Balance", fmt: "qty" }, { k: "ac", label: "Actual cost", fmt: "money" }, { k: "forecast_profit", label: "Forecast profit", fmt: "money" }]);
  }

  function itemDrawer(r, lines) {
    const mine = lines.filter((x) => x.item_id === r.item_id);
    drawer(r.key + " · " + (r.title || "").slice(0, 60), h("div", {},
      kv([["Unit", r.unit], ["Total quantity", Q(r.qty) + " " + r.unit], ["Overall quantity stated in the BOQ", r.stated_qty == null ? "—" : Q(r.stated_qty) + (r.stated_diff ? " (difference " + Q(r.stated_diff) + ")" : "")],
        ["Amount", M(r.amount)], ["Rate", r.rates_differ ? "differs by location; weighted average " + M(r.avg_rate) : M(r.rate)], ["Executed", Q(r.executed_qty) + " (" + P(r.progress_pct) + ")"]]),
      h("h3", {}, "Lines by location"),
      table([{ k: "short_code", label: "Short code" }, { k: "code", label: "BOQ code" }, { k: "location", label: "Location" }, { label: "Description", v: (x) => (x.description || "").slice(0, 60) },
        { k: "qty", label: "Qty", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" }, { k: "executed_qty", label: "Executed", fmt: "qty" },
        { label: "Line", v: (x) => (x.role === "overall" ? "overall (not counted)" : "") }], mine, { search: false, totals: ["qty", "amount", "executed_qty"],
        onRow: (x) => { location.hash = "#/p/boq?open=" + x.boq_item_id; } })), []);
  }

  async function summaryTab() {
    const box = h("div", { "data-bx": "summary" });
    if (!S.project) { box.append(needProj()); return box; }
    const st = await api("bx.settings", {});
    if (!st.on) { box.append(offNote(st, box)); return box; }
    let mode = "qty";
    const load = async () => {
      const [d, ln] = await Promise.all([api("bx.summary", { project_id: S.project }), api("bx.lines", { project_id: S.project })]);
      box.innerHTML = "";
      box.append(summaryStrip([["Items", d.items], ["BOQ lines", d.lines], ["Locations", d.locations.filter((l) => l.abbr !== "—").length], ["BOQ amount", M(d.totals.amount)],
        ["Earned so far", M(d.totals.earned_revenue)], ["Actual cost", M(d.totals.ac)]]));
      if (d.checks.length) {
        box.append(h("div", { class: "panel", "data-bx": "checks" }, h("b", {}, "Checks (" + d.checks.length + ")"),
          h("ul", { style: "margin:6px 0 0 18px;line-height:1.6" }, d.checks.map((c) => h("li", { class: c.severity === "red" ? "red" : "" }, c.text,
            c.boq_item_id && c.kind === "double" && st.can_edit ? h("button", { class: "btn small", style: "margin-left:8px", onclick: async () => { await run("bx.line_save", { boq_item_id: c.boq_item_id, role: "overall" }, "Marked as the overall line; counted once"); await reloadLookups(); load(); } }, "Count once (mark overall)") : null,
            c.kind === "stated" && c.item_id && st.can_edit ? h("button", { class: "btn small", style: "margin-left:8px", onclick: async () => { await run("bx.item_save", { id: c.item_id, stated_qty: "" }, "The location lines are the quantity now"); load(); } }, "Use the location total") : null)))));
      }
      box.append(h("div", { class: "bar" }, h("p", { class: "hint grow" }, "The same work in every location added up. Columns are the locations (" + d.locations.map((l) => l.abbr + " = " + l.name).join(", ") + "). Click an item to see its lines and open one."),
        h("label", {}, h("input", { type: "checkbox", checked: mode === "amount", onchange: (e) => { mode = e.target.checked ? "amount" : "qty"; load(); } }), " Location columns in rupees")));
      box.append(table(matrixCols(d, mode), d.rows, { name: "boq_summary_by_item", totals: ["qty", "amount", "ac", "forecast_profit"], export: true,
        rowClass: (r) => (r.stated_diff ? "flag" : ""), onRow: (r) => itemDrawer(r, ln.rows), empty: "This project has no BOQ lines yet." }));
      box.append(h("h3", { style: "margin-top:14px" }, "By location"), table([{ k: "abbr", label: "Code" }, { k: "name", label: "Location" }, { k: "amount", label: "BOQ amount", fmt: "money" }],
        d.locations, { search: false, totals: ["amount"], name: "boq_by_location" }));
    };
    await load();
    return box;
  }

  /* ───────── short codes: settings, lines, locations, items, import ───────── */
  function lineDialog(x, d, done) {
    const sameUnit = d.items.filter((i) => (i.unit || "").toLowerCase().replace(/\s/g, "") === (x.unit || "").toLowerCase().replace(/\s/g, "") || i.id === x.item_id);
    const f = form([{ k: "short_code", label: "Short code (typed codes are kept)" },
      { k: "item_id", label: "Summed with item", type: "select", noBlank: true, options: sameUnit.map((i) => [i.id, i.key + " · " + (i.title || "").slice(0, 50)]) },
      { k: "new_item_key", label: "…or a new item with key" },
      { k: "role", label: "This line is", type: "select", noBlank: true, options: [["line", "a BOQ line (counted in the summary)"], ["overall", "the overall figure of the item (shown, not counted)"]] }],
    { short_code: x.short_code, item_id: x.item_id, role: x.role });
    modal("Short code · " + x.code + " " + (x.description || "").slice(0, 50), h("div", {},
      h("p", { class: "hint" }, "Location " + (x.location || "none") + " · " + Q(x.qty) + " " + (x.unit || "") + ". The automatic code is location + item (" + d.format.replace("{LOC}", "HW").replace("{ITEM}", "M25") + ")."), f), [
      { label: "Save", cls: "primary", act: async () => {
        const v = f.values(); const a = { boq_item_id: x.boq_item_id };
        if (v.short_code && v.short_code !== x.short_code) a.short_code = v.short_code;
        if (v.new_item_key) a.new_item_key = v.new_item_key; else if (String(v.item_id) !== String(x.item_id)) a.item_id = v.item_id;
        if (v.role !== x.role) a.role = v.role;
        if (Object.keys(a).length === 1) return toast("Nothing changed.", "err");
        await run("bx.line_save", a, "Saved"); await reloadLookups(); done();
      } },
      x.manual || x.item_manual ? { label: "Back to automatic", act: async () => { await run("bx.line_save", { boq_item_id: x.boq_item_id, auto: 1, item_auto: 1 }, "Automatic again"); await reloadLookups(); done(); } } : null]);
  }

  function importDialog(done) {
    const cols = ["code", "description", "unit", "qty", "rate", "location", "short_code"];
    const ta = h("textarea", { style: "min-height:200px;font-family:monospace;width:100%", placeholder: cols.join("\t") });
    const headings = h("input", { type: "checkbox", checked: true });
    const skip = h("input", { type: "checkbox", checked: true });
    const out = h("div");
    const parse = () => ta.value.split(/\r?\n/).map((l) => l.split("\t")).filter((r) => r.join("").trim())
      .filter((r, i) => !(i === 0 && /^(code|item|s\.?n|description)/i.test((r[0] || "").trim()) && /desc/i.test(r.join(" "))))
      .map((r) => { const o = {}; cols.forEach((c, j) => { o[c] = (r[j] || "").trim(); }); return o; });
    const args = (apply) => ({ project_id: S.project, rows: parse(), headings: headings.checked ? 1 : 0, skip_overall: skip.checked ? 1 : 0, apply: apply ? 1 : 0 });
    modal("Import BOQ with locations", h("div", {},
      h("p", {}, "Copy rows from Excel with these columns in this order and paste below (a header row is skipped). Location and short code may be left empty."),
      h("p", { class: "hint" }, cols.join("  |  ")),
      h("p", { class: "hint" }, "A row with only a description (e.g. HEADWORKS, SETTLING BASIN, Ch 0+000 - 5+000, Block A) is a location heading for the rows under it. A location that does not exist yet is added under BOQ › Components."),
      ta,
      h("label", { style: "display:block;margin-top:6px" }, headings, " Rows with only a description are location headings"),
      h("label", { style: "display:block" }, skip, " A row with no location whose item also has location rows is the overall figure: keep it as the stated total, do not add it as a line"),
      out), [
      { label: "Preview", keep: true, act: async () => {
        const d = await run("bx.import", args(false));
        out.innerHTML = "";
        if (d.errors.length) out.append(h("div", { class: "panel" }, h("b", { class: "red" }, "Fix before importing"), h("ul", {}, d.errors.map((e) => h("li", {}, e)))));
        out.append(h("p", {}, d.adds + " lines will be added" + (d.overall ? ", " + d.overall + " overall line(s) kept as stated totals" : "") + (d.new_locations.length ? "; new locations: " + d.new_locations.join(", ") : "") + "."));
        out.append(table([{ k: "row", label: "Row" }, { label: "Action", v: (r) => (r.heading ? "heading → " + r.location : r.action === "overall" ? "overall (not a line)" : "add") }, { k: "code", label: "BOQ code" },
          { label: "Description", v: (r) => (r.description || "").slice(0, 50) }, { k: "unit", label: "Unit" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "location", label: "Location" },
          { k: "proposed_code", label: "Short code" }, { k: "note", label: "Note" }], d.rows, { search: false, name: "boq_import_preview" }));
        if (d.summary) out.append(h("h3", {}, "Summary after import"), table(matrixCols(d.summary, "qty"), d.summary.rows, { search: false, name: "boq_import_summary" }));
      } },
      { label: "Import", cls: "primary", act: async () => {
        const r = await run("bx.import", args(true), (x) => x.added + " lines imported" + (x.components_made ? ", " + x.components_made + " new locations" : ""));
        await reloadLookups(); if (done) done(r);
      } }]);
  }

  async function codesTab() {
    const box = h("div", { "data-bx": "codes" });
    const st = await api("bx.settings", {});
    const load = async () => {
      box.innerHTML = "";
      const s2 = await api("bx.settings", {});
      const f = form([{ k: "on", label: "BOQ short codes and summary by item", type: "check" },
        { k: "format", label: "Short code", type: "select", noBlank: true, options: s2.formats.map((x) => [x.value, x.value + "  (e.g. " + x.example + ")"]) }], { on: s2.on ? 1 : 0, format: s2.format });
      box.append(h("div", { class: "panel" }, h("h3", {}, "Settings"),
        h("p", { class: "hint" }, "Each BOQ line gets a short code from its location and its item: Headworks + M25 concrete = HW-M25, Settling basin + M25 = SB-M25. The same item in all locations is added up in Summary by item. Pickers everywhere show the short code first. Codes typed by hand are kept. Existing companies start with this off; nothing already entered changes."),
        f, s2.can_change ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
          const r = await run("bx.settings_save", f.values(), (x) => x.on ? "On" + (x.built && x.built.lines_new ? ": " + x.built.lines_new + " lines coded in " + x.built.projects + " projects" : "") : "Off");
          await reloadLookups(); load(); return r;
        } }, "Save")) : h("p", { class: "muted" }, "Only Commercial approvers can change these.")));
      if (!S.project) { box.append(needProj()); return; }
      if (!s2.on) {
        const pv = await api("bx.preview", { project_id: S.project });
        box.append(h("h3", {}, "What the codes would be for this project (nothing is saved)"),
          table([{ k: "code", label: "BOQ code" }, { label: "Description", v: (r) => (r.description || "").slice(0, 60) }, { k: "location", label: "Location" }, { k: "short_code", label: "Short code" }, { k: "item_key", label: "Item" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }],
            pv.rows, { name: "boq_codes_preview", empty: "No BOQ lines in this project." }),
          h("h3", {}, "Summary by item it would show"), table(matrixCols(pv.summary, "qty"), pv.summary.rows, { search: false, name: "boq_summary_preview" }));
        return;
      }
      const d = await api("bx.lines", { project_id: S.project });
      const ed = s2.can_edit;
      box.append(h("div", { class: "bar" }, h("p", { class: "hint grow" }, d.rows.length + " lines · " + d.locations.length + " locations · " + d.items.length + " items. Click a line to change its code, its item or mark it as the overall line."),
        ed ? h("button", { class: "btn primary", onclick: () => importDialog(() => load()) }, "Import BOQ with locations") : null,
        ed ? h("button", { class: "btn", onclick: () => presetDialog(load) }, "Add standard locations") : null,
        ed ? h("button", { class: "btn", onclick: async () => {
          const ok = await ask("Rebuild automatic codes", "Recalculate every automatic item key, location abbreviation and short code of this project? Codes typed by hand stay. BOQ lines whose location column names a place not yet in BOQ › Components are filed under a new component.", { ok: "Rebuild" });
          if (!ok) return; const r = await run("bx.build", { project_id: S.project, mode: "auto", files: 1 }, (x) => x.codes_changed + " codes changed" + (x.lines_filed ? ", " + x.lines_filed + " lines filed under locations" : "")); await reloadLookups(); load(); return r;
        } }, "Rebuild automatic codes") : null));
      box.append(table([{ k: "short_code", label: "Short code" }, { k: "code", label: "BOQ code" }, { label: "Description", v: (r) => (r.description || "").slice(0, 70) }, { k: "location", label: "Location" },
        { k: "item_key", label: "Item" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "unit", label: "Unit" }, { k: "amount", label: "Amount", fmt: "money" },
        { label: "", v: (r) => [r.manual ? "typed" : "", r.item_manual ? "item by hand" : "", r.role === "overall" ? "overall line" : ""].filter(Boolean).join(", ") }],
      d.rows, { name: "boq_short_codes", totals: ["amount"], rowClass: (r) => (r.role === "overall" ? "muted" : ""), onRow: ed ? (r) => lineDialog(r, d, load) : null, empty: "No BOQ lines yet: import the BOQ with locations." }));
      box.append(h("div", { class: "grid2", style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-top:12px" },
        h("div", {}, h("h3", {}, "Locations"), table([{ k: "abbr", label: "Code" }, { k: "name", label: "Location" }, { k: "lines", label: "Lines" }, { label: "", v: (r) => (r.manual ? "typed" : "") }], d.locations,
          { search: false, export: false, empty: "No locations: lines are summed without one.", onRow: ed ? async (r) => {
            const v = await ask("Location code · " + r.name, "Short code for this location (1–12 letters or digits). Every automatic short code of its lines follows.", { input: r.abbr, ok: "Save" });
            if (v === null) return; if (!v.trim()) { await run("bx.loc_save", { id: r.id, auto: 1 }, "Automatic again"); } else await run("bx.loc_save", { id: r.id, abbr: v.trim() }, "Saved"); await reloadLookups(); load();
          } : null })),
        h("div", {}, h("h3", {}, "Items"), table([{ k: "key", label: "Key" }, { label: "Description", v: (r) => (r.title || "").slice(0, 50) }, { k: "unit", label: "Unit" }, { label: "", v: (r) => (r.manual ? "typed" : "") }], d.items,
          { search: false, export: false, onRow: ed ? async (r) => {
            const v = await ask("Item key · " + (r.title || "").slice(0, 40), "Key for this item (e.g. M25, PCC-M10, RBAR). Every automatic short code of its lines follows. Leave empty to go back to the automatic key.", { input: r.key, ok: "Save" });
            if (v === null) return; if (!v.trim()) await run("bx.item_save", { id: r.id, auto: 1 }, "Automatic again"); else await run("bx.item_save", { id: r.id, key: v.trim() }, "Saved"); await reloadLookups(); load();
          } : null }))));
    };
    await load();
    return box;
  }

  async function presetDialog(done) {
    const d = await api("bx.presets", {});
    const sel = h("select", {}, d.presets.map((p) => h("option", { value: p.key }, p.label)));
    const list = h("p", { class: "hint" });
    const show = () => { const p = d.presets.find((x) => x.key === sel.value); list.textContent = p.locations.map((l) => l.abbr + " " + l.name).join(" · "); };
    sel.onchange = show; show();
    modal("Add standard locations", h("div", {}, h("p", {}, "Adds the usual locations for this kind of project under BOQ › Components, with their codes. Names that already exist are skipped. Rename or delete any of them afterwards."), sel, list), [
      { label: "Add", cls: "primary", act: async () => { await run("bx.loc_setup", { project_id: S.project, preset: sel.value }, (x) => x.created + " locations added"); if (done) done(); } }], { narrow: true });
  }

  addTabs(ROUTE, "BOQ — commercial master", "Contract, revised, executed, measured, billed and certified quantities — by line, by location and by item.", "BOQ items",
    [["Summary by item", summaryTab], ["Short codes", codesTab]]);

  /* the BOQ items list shows the short code */
  if (typeof MASTERS_UI !== "undefined" && MASTERS_UI.boq_items && !MASTERS_UI.boq_items._bx) {
    const o = MASTERS_UI.boq_items;
    o._bx = true;
    if (Array.isArray(o.cols)) o.cols.splice(1, 0, { label: "Short code", v: (r) => r.short_code || "" });
  }

  /* what's new */
  const VER = "2.47.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } };
  async function whatsNew() {
    if (LSg("bco_seen_" + VER, "")) return;
    if (!S.user || S.user.role !== "admin") return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_" + VER, "1");
    let isOn = false;
    try { isOn = (await api("bx.settings", {})).on; } catch (e) { isOn = false; }
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:560px" },
      h("p", {}, "BOQ by location: overall summary and short codes."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "Short code on every BOQ line"), " from its location and item: HW-M25 (Headworks, M25 concrete), SB-M25, HRT-SHOT-M25, CH0-5-GSB, GF-RBAR-FE500."),
        h("li", {}, h("b", {}, "Summary by item:"), " M25 at Headworks 45 + Settling basin 15 = 60 m³, with amount, executed, billed and cost added up."),
        h("li", {}, h("b", {}, "Pick by short code everywhere:"), " DPR, requisitions, PR / PO, material issues, measurements, IPC, budgets."),
        h("li", {}, h("b", {}, "Import BOQ with locations"), " (location headings or a location column); an overall line repeating the locations is not counted twice.")),
      h("p", { class: "hint" }, isOn ? "It is on for this company: Commercial › BOQ control › Short codes." :
        "It is off for your existing company until Commercial approve turns it on: Commercial › BOQ control › Short codes (shows the codes first). Nothing already entered changed.")),
    [{ label: "Open Short codes", cls: "primary", act: () => { location.hash = "#/p/boq?tab=" + tabIndex("Short codes"); } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user) { clearInterval(seen); setTimeout(whatsNew, 3500); } }, 1000);
})();
