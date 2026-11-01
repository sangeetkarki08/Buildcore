/* BuildCore 2.31 — report generator.
   The 2.29 report builder grows into a report generator for every module. Same place (Overview › Command centre ›
   Report builder) and one new menu item at the end of Overview: Report generator. The other menus are unchanged.
   Choose the data, the date and period (English or Nepali), the columns in your order with your own headings,
   calculated columns, filters, up to three groups with totals or a summary, then print, PDF, Excel or CSV, and save it.
   The engine decides what each person may see; nothing here posts. */
(function () {
  "use strict";
  if (window.__bcoRgen) return;
  window.__bcoRgen = true;

  document.head.append(h("style", {}, ".rg{display:grid;grid-template-columns:270px minmax(0,1fr);gap:14px}.rg>div{min-width:0}@media(max-width:980px){.rg{grid-template-columns:1fr}}" +
    ".rg-list input{width:100%;margin:0 0 6px}.rg-list h4{margin:10px 0 4px;font-size:12px;color:#667;text-transform:uppercase;letter-spacing:.3px}" +
    ".rg-list button{display:block;width:100%;text-align:left;border:1px solid #e3e8ee;background:#fff;border-radius:6px;padding:6px 8px;margin:0 0 4px;cursor:pointer;color:inherit}" +
    ".rg-list button.on{border-color:#1f6fb2;background:#eef5fb}.rg-list small{color:#667;display:block}" +
    ".rg-bar{display:flex;gap:8px;align-items:end;flex-wrap:wrap;margin:0 0 8px}.rg-bar label{display:flex;flex-direction:column;font-size:12px;color:#556;gap:2px}" +
    ".rg-bar label.ck{flex-direction:row;align-items:center;gap:5px;font-size:13px;color:inherit}" +
    ".rg details{border:1px solid #e3e8ee;border-radius:8px;padding:6px 10px;margin:0 0 8px;background:#fff}.rg summary{cursor:pointer;font-weight:600;padding:2px 0}" +
    ".rg summary small{font-weight:400;color:#667;margin-left:6px}" +
    ".rg-cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.rg-cols{grid-template-columns:1fr}}" +
    ".rg-av{max-height:300px;overflow:auto;font-size:13px;border:1px solid #eef1f4;border-radius:6px;padding:4px 8px}.rg-av label{display:block}" +
    ".rg-av h5{margin:6px 0 2px;font-size:11px;color:#778;text-transform:uppercase}" +
    ".rg-ch{max-height:300px;overflow:auto;border:1px solid #eef1f4;border-radius:6px;padding:4px}.rg-ch div{display:flex;gap:4px;align-items:center;margin:0 0 3px}" +
    ".rg-ch input{flex:1;min-width:80px}.rg-ch button{padding:1px 7px}.rg-ch .o{color:#889;font-size:11px;min-width:18px;text-align:right}" +
    ".rg-rep td.n,.rg-rep th.n{text-align:right}.rg-rep tr.g td{font-weight:600;background:#f3f6f9}.rg-rep tr.st td{font-weight:600;border-top:1px solid #ccd}" +
    ".rg-rep tr.tt td{font-weight:700;border-top:2px solid #99a}.rg-hint{color:#667;font-size:12px}" +
    "body.dark .rg details,body.dark .rg-list button{background:transparent}"));

  const NUM = (c) => c && ["number", "money"].includes(c.type);
  const OPS = { eq: "is", ne: "is not", contains: "contains", not_contains: "does not contain", starts: "starts with", gt: ">", gte: "≥", lt: "<", lte: "≤",
    between: "between", in: "is one of (a, b)", empty: "is empty", notempty: "is not empty" };
  const STYLES = { ad: "English dates", bs: "Nepali dates", both: "English and Nepali" };
  const dl = (x, mime) => {
    if (!x || !x.b64) return;
    const a = document.createElement("a");
    a.href = "data:" + mime + ";base64," + x.b64;
    a.download = x.filename; document.body.append(a); a.click(); a.remove();
  };
  const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const mode = () => (typeof window.bcoDateMode === "function" ? window.bcoDateMode() : "ad");
  const fmtCell = (c, v) => (v == null || v === "" ? "" : c.type === "money" ? fmtMoney(v) : c.type === "number" ? (typeof v === "number" ? fmtN(v, 4) : v) : String(v));
  const firstCell = (res, ln, c, i) => {
    const v = (ln.values || {})[c.k];
    if (i === 0 && (!res.summary_only || v == null || v === "" || ln.type === "total")) return ln.label + (ln.count != null ? " (" + ln.count + ")" : "");
    return fmtCell(c, v);
  };

  async function generator(params, opts) {
    const box = h("div", { class: "rg" });
    const meta = await api("fcc.report_meta", {});
    if (!meta.datasets.length) return h("p", { class: "empty" }, "Your role cannot see any data for reports.");
    const left = h("div", { class: "rg-list" });
    const right = h("div");
    box.append(left, right);
    const DSL = (k) => meta.datasets.find((x) => x.key === k);
    const areaName = Object.fromEntries(meta.areas || []);
    let cur = null, search = "";

    function drawList() {
      left.innerHTML = "";
      const s = h("input", { type: "search", placeholder: "Find a report", value: search, oninput: (e) => { search = e.target.value; drawItems(); } });
      const items = h("div");
      left.append(h("button", { onclick: () => edit(null) }, h("b", {}, "+ New report"), h("small", {}, "Choose the data, period, columns and grouping")), s, items);
      const drawItems = () => {
        items.innerHTML = "";
        const t = search.trim().toLowerCase();
        const pick = (r) => !t || (r.name + " " + ((DSL(r.dataset) || {}).label || "")).toLowerCase().includes(t);
        [["Mine", (r) => !r.builtin && !r.shared], ["Shared", (r) => !r.builtin && r.shared], ["Ready-made", (r) => r.builtin]].forEach(([title, f]) => {
          const list = meta.reports.filter((r) => f(r) && pick(r));
          if (!list.length) return;
          items.append(h("h4", {}, title));
          list.forEach((r) => items.append(h("button", { class: cur && cur.id === r.id ? "on" : "", onclick: () => edit(r) }, r.name,
            h("small", {}, ((DSL(r.dataset) || {}).label || r.dataset) + (title === "Shared" ? " · " + (r.owner || "—") : "")))));
        });
      };
      drawItems();
    }

    function edit(r) {
      cur = r;
      drawList();
      right.innerHTML = "";
      const blank = { dataset: (params && params.data && DSL(params.data) ? params.data : meta.datasets[0].key), period: "this_bs_month", columns: [] };
      const def = JSON.parse(JSON.stringify((r && r.definition) || blank));
      ["filters", "group_by", "sort", "calc", "project_ids"].forEach((k) => { def[k] = def[k] || []; });
      def.summaries = def.summaries || {}; def.labels = def.labels || {};
      if (!def.date_style) def.date_style = mode() === "ad" ? "ad" : mode();
      let extra = [];                       /* fields a run adds (DPR template fields) */
      const name = h("input", { value: (r && !r.builtin && r.name) || "", placeholder: r && r.builtin ? r.name + " (copy)" : "Report name", style: "min-width:220px" });
      const form1 = h("div");
      const out = h("div", { class: "no-bs" });
      const DS = () => DSL(def.dataset) || meta.datasets[0];
      const calcCols = () => def.calc.map((x, i) => ({ k: x.k || "calc_" + (i + 1), label: x.label || "Calculated " + (i + 1), type: ["pct", "days"].includes(x.op) ? "number" : "money", calc: true }));
      const allCols = () => [...DS().columns, ...extra, ...DS().time_cols, ...calcCols()];
      const colOf = (k) => allCols().find((c) => c.k === k);
      const opt = (sel, list, blankText) => [blankText != null ? h("option", { value: "" }, blankText) : null, ...list.map((c) => h("option", { value: c.k, selected: c.k === sel }, c.label))];

      function drawForm() {
        form1.innerHTML = "";
        const ds = DS();
        if (!def.columns.length) {     /* a first choice: the leading fields and the first amounts */
          const t = ds.columns.filter((c) => !NUM(c)).slice(0, 6), n = ds.columns.filter(NUM).slice(0, 3);
          def.columns = ds.columns.filter((c) => t.includes(c) || n.includes(c)).map((c) => c.k);
        }
        /* what */
        const groups = {};
        meta.datasets.forEach((x) => { (groups[x.area] = groups[x.area] || []).push(x); });
        const dsSel = h("select", { onchange: (e) => { Object.assign(def, { dataset: e.target.value, columns: [], filters: [], group_by: [], sort: [], summaries: {}, labels: {}, calc: [], date_field: null }); extra = []; drawForm(); } },
          (meta.areas || []).filter(([k]) => groups[k]).map(([k, l]) => h("optgroup", { label: l }, groups[k].map((x) => h("option", { value: x.key, selected: x.key === def.dataset }, x.label)))));
        form1.append(h("div", { class: "rg-bar" }, h("label", {}, "Report name", name), h("label", {}, "Data", dsSel),
          h("span", { class: "rg-hint" }, areaName[ds.area] || "")));
        /* time */
        if (ds.period) {
          const tbar = h("div", { class: "rg-bar" });
          const per = h("select", { onchange: (e) => { def.period = e.target.value; drawTime(); } }, meta.periods.map(([k, l]) => h("option", { value: k, selected: k === (def.period || "custom") }, l)));
          const dateSel = ds.dates.length ? h("select", { onchange: (e) => { def.date_field = e.target.value || null; } },
            ds.dates.map((d) => h("option", { value: d.k, selected: d.k === (def.date_field || ds.default_date) }, d.label)), ds.default_date ? null : h("option", { value: "", selected: !def.date_field }, "(no date limit)")) : null;
          const style = h("select", { onchange: (e) => { def.date_style = e.target.value; } }, (meta.date_styles || ["ad"]).map((k) => h("option", { value: k, selected: k === def.date_style }, STYLES[k] || k)));
          const extraBox = h("span", { style: "display:contents" });
          const drawTime = () => {
            extraBox.innerHTML = "";
            if (def.period === "custom") {
              extraBox.append(h("label", {}, "From", h("input", { type: "date", value: def.from || "", onchange: (e) => { def.from = e.target.value; } })),
                h("label", {}, "To", h("input", { type: "date", value: def.to || "", onchange: (e) => { def.to = e.target.value; } })));
            } else if (def.period === "bs_month" && meta.bs) {
              const [y0, m0] = String(def.bs_month || (meta.bs.y + "-" + meta.bs.m)).split("-").map(Number);
              const ys = h("select", {}, meta.bs.years.map((y) => h("option", { value: y, selected: y === y0 }, y)));
              const ms = h("select", {}, meta.bs.names.map((n, i) => h("option", { value: i + 1, selected: i + 1 === m0 }, n)));
              const set = () => { def.bs_month = ys.value + "-" + String(ms.value).padStart(2, "0"); };
              ys.onchange = set; ms.onchange = set; set();
              extraBox.append(h("label", {}, "Nepali month", ms), h("label", {}, "Year", ys));
            } else if (def.period === "fy" && meta.bs) {
              const fy0 = Number(String(def.fy || meta.bs.fy).split("/")[0]);
              const fs = h("select", { onchange: (e) => { def.fy = Number(e.target.value); } }, meta.bs.years.slice(0, -1).map((y) => h("option", { value: y, selected: y === fy0 }, y + "/" + String((y + 1) % 100).padStart(2, "0"))));
              def.fy = fy0;
              extraBox.append(h("label", {}, "Fiscal year", fs));
            }
          };
          drawTime();
          tbar.append(dateSel ? h("label", {}, "Date to use", dateSel) : "", h("label", {}, "Period", per), extraBox, h("label", {}, "Show dates as", style));
          form1.append(tbar);
        }
        /* projects */
        if (ds.company) form1.append(h("p", { class: "rg-hint" }, "Company-wide figures; no project choice."));
        else if (meta.projects.length > 1) {
          const proj = h("select", { multiple: true, size: Math.min(4, meta.projects.length), onchange: (e) => { def.project_ids = [...e.target.selectedOptions].map((o) => Number(o.value)); } },
            meta.projects.map((p) => h("option", { value: p.id, selected: def.project_ids.includes(p.id) }, p.code + " " + p.name)));
          const ws = meta.workspace_project && meta.projects.find((p) => p.id === meta.workspace_project);
          form1.append(h("div", { class: "rg-bar" }, h("label", {}, "Projects (Ctrl+click for several; none = " + (ws ? "the open project " + ws.code : "all you may see") + ")", proj)));
        }
        /* columns */
        const chosen = h("div", { class: "rg-ch" });
        const avail = h("div", { class: "rg-av" });
        const csearch = h("input", { type: "search", placeholder: "Find a column", oninput: () => drawAvail() });
        const drawChosen = () => {
          chosen.innerHTML = "";
          def.columns = def.columns.filter((k) => colOf(k));
          if (!def.columns.length) chosen.append(h("p", { class: "rg-hint" }, "Tick columns on the left."));
          def.columns.forEach((k, i) => {
            const c = colOf(k);
            const mv = (d) => { const j = i + d; if (j < 0 || j >= def.columns.length) return; [def.columns[i], def.columns[j]] = [def.columns[j], def.columns[i]]; drawChosen(); };
            chosen.append(h("div", {}, h("span", { class: "o" }, i + 1),
              h("input", { value: def.labels[k] || "", placeholder: c.label, title: "Heading in the report (blank = " + c.label + ")", onchange: (e) => { if (e.target.value.trim()) def.labels[k] = e.target.value.trim(); else delete def.labels[k]; } }),
              h("button", { class: "btn small", title: "Move up", onclick: () => mv(-1) }, "↑"), h("button", { class: "btn small", title: "Move down", onclick: () => mv(1) }, "↓"),
              h("button", { class: "btn small", title: "Take out", onclick: () => { def.columns.splice(i, 1); drawChosen(); drawAvail(); drawTotals(); } }, "✕")));
          });
        };
        const drawAvail = () => {
          avail.innerHTML = "";
          const t = csearch.value.trim().toLowerCase();
          const sect = (title, list) => {
            list = list.filter((c) => !t || c.label.toLowerCase().includes(t));
            if (!list.length) return;
            avail.append(h("h5", {}, title));
            list.forEach((c) => avail.append(h("label", {}, h("input", { type: "checkbox", checked: def.columns.includes(c.k), onchange: (e) => {
              if (e.target.checked) { if (!def.columns.includes(c.k)) def.columns.push(c.k); } else def.columns = def.columns.filter((x) => x !== c.k);
              drawChosen(); drawTotals(); } }), " ", c.label)));
          };
          sect("Fields", ds.columns);
          sect("Fields from DPR templates", extra);
          sect("Calculated", calcCols());
          sect("From the dates (week, month, Nepali month, fiscal year)", ds.time_cols);
        };
        drawAvail(); drawChosen();
        form1.append(h("details", { open: true }, h("summary", {}, "Columns", h("small", {}, "tick to add; the right side sets the order and the headings")),
          h("div", { class: "rg-cols" }, h("div", {}, csearch, avail), h("div", {}, h("div", { class: "rg-hint" }, "In the report, in this order"), chosen))));
        /* calculated columns */
        const cl = h("div");
        const numDate = () => [...ds.columns, ...extra, ...calcCols()].filter((c) => NUM(c) || c.type === "date");
        const drawCalc = () => {
          cl.innerHTML = "";
          def.calc.forEach((x, i) => {
            x.k = x.k || "calc_" + (i + 1);
            const bnum = h("input", { type: "number", step: "any", value: x.num ?? "", placeholder: "or a number", style: "width:110px", onchange: (e) => { x.num = e.target.value; } });
            cl.append(h("div", { class: "rg-bar" },
              h("label", {}, "Heading", h("input", { value: x.label || "", placeholder: "Calculated " + (i + 1), onchange: (e) => { x.label = e.target.value; drawAvail(); drawChosen(); } })),
              h("label", {}, "Column", h("select", { onchange: (e) => { x.a = e.target.value; } }, opt(x.a, numDate(), "—"))),
              h("label", {}, "Do", h("select", { onchange: (e) => { x.op = e.target.value; } }, Object.entries(meta.calc_ops || {}).map(([k, l]) => h("option", { value: k, selected: k === x.op }, l)))),
              h("label", {}, "With column", h("select", { onchange: (e) => { x.b = e.target.value || null; } }, opt(x.b, numDate(), "(a number)"))),
              h("label", {}, "Number", bnum),
              h("button", { class: "btn small", onclick: () => { def.columns = def.columns.filter((k) => k !== x.k); def.calc.splice(i, 1); def.calc.forEach((y, j) => { y.k = "calc_" + (j + 1); }); drawCalc(); drawAvail(); drawChosen(); } }, "Remove")));
          });
          cl.append(h("button", { class: "btn small", onclick: () => { const k = "calc_" + (def.calc.length + 1); def.calc.push({ k, label: "", a: (numDate()[0] || {}).k, op: "mul", b: null, num: "" }); def.columns.push(k); drawCalc(); drawAvail(); drawChosen(); } }, "+ Calculated column"));
          cl.append(h("p", { class: "rg-hint" }, "Examples: Qty × Rate; Amount as % of Contract; days from Date to Due date."));
        };
        drawCalc();
        form1.append(h("details", { open: def.calc.length > 0 }, h("summary", {}, "Calculated columns"), cl));
        /* filters */
        const fl = h("div");
        const cache = {};
        const drawF = () => {
          fl.innerHTML = "";
          def.filters.forEach((x, i) => {
            const listId = "rgv" + Math.random().toString(36).slice(2, 8);
            const dlist = h("datalist", { id: listId });
            const c = colOf(x.field) || {};
            const vtype = c.type === "date" ? "date" : NUM(c) ? "number" : "text";
            const load = async () => {
              if (vtype !== "text" || !x.field) return;
              if (!cache[x.field]) { try { cache[x.field] = (await api("rg.values", { definition: payload().definition, field: x.field })).values; } catch (e) { cache[x.field] = []; } }
              dlist.innerHTML = ""; cache[x.field].forEach((v) => dlist.append(h("option", { value: v })));
            };
            const v1 = h("input", { type: vtype, step: "any", list: listId, value: x.value || "", onfocus: load, onchange: (e) => { x.value = e.target.value; } });
            const v2 = x.op === "between" ? h("input", { type: vtype, step: "any", value: x.value2 || "", onchange: (e) => { x.value2 = e.target.value; } }) : null;
            fl.append(h("div", { class: "rg-bar" }, h("select", { onchange: (e) => { x.field = e.target.value; drawF(); } }, opt(x.field, allCols())),
              h("select", { onchange: (e) => { x.op = e.target.value; drawF(); } }, (meta.ops || Object.keys(OPS)).map((o) => h("option", { value: o, selected: o === x.op }, OPS[o] || o))),
              ["empty", "notempty"].includes(x.op) ? "" : v1, v2 ? h("span", {}, "and") : "", v2 || "", dlist,
              h("button", { class: "btn small", onclick: () => { def.filters.splice(i, 1); drawF(); } }, "Remove")));
          });
          fl.append(h("button", { class: "btn small", onclick: () => { def.filters.push({ field: ds.columns[0].k, op: "eq", value: "" }); drawF(); } }, "+ Filter"));
          if (def.filters.length > 1) fl.append(h("p", { class: "rg-hint" }, "A row must pass every filter."));
        };
        drawF();
        form1.append(h("details", { open: def.filters.length > 0 }, h("summary", {}, "Filters", def.filters.length ? h("small", {}, def.filters.length + " set") : ""), fl));
        /* groups, sort, totals */
        const gsel = (i) => h("select", { onchange: (e) => { def.group_by[i] = e.target.value; def.group_by = def.group_by.filter(Boolean); } }, opt(def.group_by[i], allCols(), i ? "—" : "No grouping"));
        const ssel = (i) => {
          const s = def.sort[i] || {};
          const d = h("select", { onchange: (e) => { if (def.sort[i]) def.sort[i].dir = e.target.value; } }, h("option", { value: "asc" }, "A → Z, small → large"), h("option", { value: "desc", selected: s.dir === "desc" }, "Z → A, large → small"));
          const f = h("select", { onchange: (e) => { if (e.target.value) def.sort[i] = { field: e.target.value, dir: d.value }; else def.sort.splice(i, 1); def.sort = def.sort.filter(Boolean); } }, opt(s.field, allCols(), i ? "—" : "As the data comes"));
          return [h("label", {}, i ? "then by" : "Sort by", f), h("label", {}, "Order", d)];
        };
        const totals = h("div", { class: "rg-bar" });
        const drawTotals = () => {
          totals.innerHTML = "";
          const sel = def.columns.map(colOf).filter(Boolean);
          const nums = sel.filter(NUM);
          const txt = sel.filter((c) => !NUM(c)).slice(0, 1);
          Object.keys(def.summaries).forEach((k) => { if (!def.columns.includes(k)) delete def.summaries[k]; });
          if (!nums.length && !txt.length) totals.append(h("span", { class: "rg-hint" }, "Choose columns first."));
          [...nums, ...txt].forEach((c) => totals.append(h("label", {}, def.labels[c.k] || c.label, h("select", { onchange: (e) => { if (e.target.value) def.summaries[c.k] = e.target.value; else delete def.summaries[c.k]; } },
            [["", "—"], ["sum", "Sum"], ["avg", "Average"], ["min", "Smallest"], ["max", "Largest"], ["count", "Count"]].filter(([k]) => NUM(c) || ["", "count"].includes(k))
              .map(([k, l]) => h("option", { value: k, selected: def.summaries[c.k] === k }, l))))));
        };
        drawTotals();
        const top = h("input", { type: "number", min: 0, value: def.top || "", placeholder: "all", style: "width:80px", onchange: (e) => { def.top = Number(e.target.value) || null; } });
        form1.append(h("details", { open: def.group_by.length > 0 || Object.keys(def.summaries).length > 0 || def.sort.length > 0 }, h("summary", {}, "Group, sort and totals"),
          h("div", { class: "rg-bar" }, h("label", {}, "Group by", gsel(0)), h("label", {}, "then by", gsel(1)), h("label", {}, "then by", gsel(2)),
            h("label", { class: "ck" }, h("input", { type: "checkbox", checked: !!def.summary_only, onchange: (e) => { def.summary_only = e.target.checked; } }), "Only one line per group (summary)")),
          h("div", { class: "rg-bar" }, ...ssel(0), ...ssel(1), h("label", {}, "Only the first … rows", top)),
          h("div", { class: "rg-hint" }, "Totals (shown under each group and at the end):"), totals));
        /* page */
        const orient = h("select", { onchange: (e) => { def.orientation = e.target.value; } }, h("option", { value: "portrait" }, "Portrait"), h("option", { value: "landscape", selected: def.orientation === "landscape" }, "Landscape"));
        form1.append(h("details", {}, h("summary", {}, "Page for printing"), h("div", { class: "rg-bar" }, h("label", {}, "Page", orient),
          h("label", {}, "Header", h("input", { value: def.header || "", onchange: (e) => { def.header = e.target.value; } })),
          h("label", {}, "Footer", h("input", { value: def.footer || "", onchange: (e) => { def.footer = e.target.value; } })),
          def.dataset === "dpr" ? h("label", { class: "ck" }, h("input", { type: "checkbox", checked: !!def.attachments, onchange: (e) => { def.attachments = e.target.checked; } }), "List photos and attachments") : "")));
      }
      drawForm();
      const payload = () => ({ definition: Object.assign({}, def, { title: name.value || (r && r.name) || "" }) });
      let res = null;
      const runIt = async () => {
        res = await run("fcc.report_run", payload());
        const known = new Set([...DS().columns, ...DS().time_cols, ...calcCols()].map((c) => c.k));
        const add = res.all_columns.filter((c) => !known.has(c.k) && !c.calc && !c.time);
        if (add.length && add.some((c) => !extra.find((x) => x.k === c.k))) { extra = add; drawForm(); }
        drawResult();
      };
      function drawResult() {
        out.innerHTML = "";
        if (!res) return;
        out.append(h("h3", {}, res.title), h("p", { class: "rg-hint" }, [res.dataset_label, res.period_label ? (res.date_label ? res.date_label + ": " : "") + res.period_label : null, res.projects,
          res.rows + " row(s)" + (res.truncated ? " (the first " + res.limit + " are shown; Excel and CSV have all)" : "")].filter(Boolean).join(" · ")));
        out.append(resultTable(res));
      }
      const saveIt = async (asNew) => {
        const nm = name.value.trim() || (r && !r.builtin ? r.name : "");
        if (!nm) { toast("Give the report a name.", "err"); name.focus(); return; }
        let shared = r && !r.builtin ? r.shared : 0;
        if (meta.rights.share) shared = (await ask("Share", "Share this report with everyone who may see its data?", { ok: "Share with everyone", cancel: "Keep it for me" })) ? 1 : 0;
        const x = await run("fcc.report_save", { id: !asNew && r && !r.builtin ? r.id : null, name: nm, shared, definition: payload().definition }, "Report saved");
        meta.reports = (await api("fcc.report_meta", {})).reports;
        edit(meta.reports.find((y) => y.id === x.id));
      };
      right.append(form1, h("div", { class: "rg-bar" }, h("button", { class: "btn primary", onclick: runIt }, "Run"),
        meta.rights.export ? h("button", { class: "btn", onclick: async () => dl(await run("fcc.report_xlsx", payload()), XLSX) }, "Excel") : "",
        meta.rights.export ? h("button", { class: "btn", onclick: async () => dl(await run("rg.csv", payload()), "text/csv") }, "CSV") : "",
        h("button", { class: "btn", onclick: async () => { if (!res) await runIt(); printReport(res); } }, "Print / PDF"),
        meta.rights.create && r && !r.builtin && r.can_edit ? h("button", { class: "btn", onclick: () => saveIt(false) }, "Save") : "",
        meta.rights.create ? h("button", { class: "btn", onclick: () => saveIt(true) }, r ? "Save as new" : "Save") : "",
        r && !r.builtin && r.can_edit ? h("button", { class: "btn warn", onclick: async () => { if (!(await ask("Remove", "Remove the report '" + r.name + "'?", { ok: "Remove" }))) return; await run("fcc.report_delete", { id: r.id }, "Removed"); meta.reports = meta.reports.filter((y) => y.id !== r.id); edit(null); } }, "Remove") : ""), out);
      if (r) runIt().catch(() => {});
    }
    drawList();
    const want = params && params.report ? meta.reports.find((x) => String(x.id) === String(params.report)) : null;
    edit(want || (opts && opts.page ? null : meta.reports[0]) || null);
    return box;
  }

  function resultTable(res) {
    const cols = res.columns;
    const tb = h("tbody");
    res.lines.forEach((ln) => {
      if (ln.type === "group") tb.append(h("tr", { class: "g" }, h("td", { colspan: cols.length, style: "padding-left:" + (8 + 14 * ln.level) + "px" }, ln.label)));
      else if (ln.type === "row") tb.append(h("tr", {}, cols.map((c) => h("td", { class: NUM(c) ? "n" : "" }, fmtCell(c, ln.values[c.k])))));
      else tb.append(h("tr", { class: ln.type === "total" ? "tt" : res.summary_only && ln.level === res.group_by.length - 1 ? "" : "st" }, cols.map((c, i) => h("td", { class: NUM(c) ? "n" : "", style: i === 0 && res.summary_only && ln.type !== "total" ? "padding-left:" + (8 + 14 * ln.level) + "px" : null }, firstCell(res, ln, c, i)))));
    });
    if (!res.rows) tb.append(h("tr", {}, h("td", { colspan: cols.length || 1, class: "empty" }, res.period_label ? "Nothing in this period with these filters. Try a longer period (e.g. This fiscal year or All dates)." : "Nothing matches these filters.")));
    return h("div", { class: "tablewrap rg-rep" }, h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: NUM(c) ? "n" : "" }, c.label)))), tb));
  }

  function printReport(res) {
    if (!res) return;
    const w = window.open("", "_blank");
    if (!w) { toast("Allow pop-ups to print.", "err"); return; }
    const esc = escHtml;
    const cols = res.columns;
    const body = res.lines.map((ln) => ln.type === "group" ? `<tr><td colspan="${cols.length}" style="font-weight:600;background:#eef2f6;padding-left:${6 + 12 * ln.level}px">${esc(ln.label)}</td></tr>`
      : ln.type === "row" ? `<tr>${cols.map((c) => `<td class="${NUM(c) ? "n" : ""}">${esc(fmtCell(c, ln.values[c.k]))}</td>`).join("")}</tr>`
        : `<tr style="font-weight:${ln.type === "total" ? 700 : res.summary_only && ln.level === res.group_by.length - 1 ? 400 : 600}">${cols.map((c, i) => `<td class="${NUM(c) ? "n" : ""}">${esc(firstCell(res, ln, c, i))}</td>`).join("")}</tr>`).join("");
    w.document.write(`<html><head><title>${esc(res.title)}</title><style>${PRINT_CSS}@page{size:A4 ${res.orientation === "landscape" ? "landscape" : "portrait"};margin:12mm}
      td.n,th.n{text-align:right}.hdr{margin:0 0 6px}.ftr{margin-top:10px;font-size:11px;color:#555;display:flex;justify-content:space-between}</style></head><body>
      ${headingHtml(res.title, [])}${res.header ? `<div class="hdr">${esc(res.header)}</div>` : ""}
      <div class="meta"><div><b>Data:</b> ${esc(res.dataset_label)}</div><div><b>Projects:</b> ${esc(res.projects)}</div>${res.period_label ? `<div><b>${esc(res.date_label || "Period")}:</b> ${esc(res.period_label)}</div>` : ""}<div><b>Rows:</b> ${res.rows}</div></div>
      <table><thead><tr>${cols.map((c) => `<th class="${NUM(c) ? "n" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>
      <div class="ftr"><span>${esc(res.footer || "")}</span><span>Generated ${esc((res.generated || "").replace("T", " ").slice(0, 16))} by ${esc(res.by || "")}</span></div>
      <script>window.onload=()=>window.print()<\/script></body></html>`);
    w.document.close();
  }

  window.bcoReports = (p) => generator(p, {});
  PAGES["rg"] = async (root, params) => {
    root.append(pageHead("Report generator", "Make the report you need from any part of BuildCore: choose the data, the period (English or Nepali), the columns and their order, filters, groups and totals. Print, PDF, Excel or CSV, and save it to run again."));
    root.append(await generator(params || {}, { page: true }));
  };

  /* What's new */
  const VER = "2.31.0";
  const seenGet = () => { try { return localStorage.getItem("bco_seen_" + VER); } catch (e) { return "1"; } };
  function whatsNew() {
    if (seenGet()) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("p", {}, "Overview › Report generator (new, at the end of Overview; the report builder in the Command centre is the same tool). Nothing else in the menu has moved."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, "Reports from every module: DPR days, labour, machines and delays; stock, GRNs, issues and requests; orders, bills, payments and vouchers; logsheets and equipment; BOQ, measurements, variations, subcontracts, events; issues, RFIs, inspections, safety and tasks."),
        h("li", {}, "Any period: English dates or presets, a Nepali month, the Nepali fiscal year or quarter, on the date you choose."),
        h("li", {}, "Your columns in your order with your own headings, calculated columns, filters with a pick-list, up to three groups with totals, or a summary only."),
        h("li", {}, "Group by week, month, Nepali month or fiscal year. Dates printed in English, Nepali or both."),
        h("li", {}, "Print, PDF, Excel or CSV; save a report for yourself or share it.")),
      h("p", { class: "hint" }, "Reports only read your data. Nothing is posted and no balance changes.")),
    [{ label: "Open the report generator", cls: "primary", act: () => { location.hash = "#/rg"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 9500); } }, 900);
})();
