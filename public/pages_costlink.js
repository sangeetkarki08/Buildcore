/* BuildCore 2.24 — engineering–finance link and company health.
   Cost codes on every project (each BOQ item plus the indirect heads), the control budget, the monthly project close,
   the cost-value reconciliation (CVR) with forecast to complete, equipment as an internal business, material and
   subcontract reconciliation in rupees, company health and the project league. The screens read the one ledger and
   the site records; nothing here changes an entry or a balance. */
(function () {
  "use strict";
  const VER = "2.24.0";
  const LSg = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const LSs = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
  let META = null;
  const meta = async (fresh) => { if (!META || fresh) META = await api("cl.meta", {}); return META; };
  const money = (v) => (v == null ? "—" : fmtMoney(v));
  const m0 = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }));
  const n1 = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 1 }));
  const n2 = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const q3 = (v) => (v == null ? "—" : fmtQty(v));
  const pct = (v) => (v == null ? "—" : n1(v) + "%");
  const pidNow = () => S.project || "";
  const TYPES = { L: "Labour", M: "Material", E: "Equipment", S: "Subcontract", O: "Other" };
  const ST = { green: "good", amber: "warn", red: "bad", info: "grey" };
  const STL = { green: "Good", amber: "Watch", red: "Act now", info: "" };

  const css = document.createElement("style");
  css.textContent = [
    ".clt{display:grid;grid-template-columns:repeat(auto-fill,minmax(172px,1fr));gap:10px;margin:0 0 14px}",
    ".clt .t{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-left:4px solid #1769aa;border-radius:12px;padding:10px 14px}",
    ".clt .t.click{cursor:pointer}.clt .t b{display:block;font-size:19px;font-variant-numeric:tabular-nums}.clt .t span{color:var(--muted,#5b7183);font-size:12.5px}",
    ".clt .t small{display:block;color:var(--muted,#5b7183);font-size:11.5px;margin-top:2px}",
    ".clt .t.warn{border-left-color:#b7791f}.clt .t.bad{border-left-color:#c0392b}.clt .t.good{border-left-color:#2f7a4d}.clt .t.grey{border-left-color:#8796a3}",
    ".clnote{background:rgba(23,105,170,.07);border:1px solid rgba(23,105,170,.25);border-radius:10px;padding:9px 13px;margin:0 0 12px;font-size:13.5px}",
    ".clnote.warn{background:rgba(183,121,31,.08);border-color:rgba(183,121,31,.35)}.clnote.bad{background:rgba(192,57,43,.07);border-color:rgba(192,57,43,.35)}",
    ".clnote.good{background:rgba(47,122,77,.07);border-color:rgba(47,122,77,.35)}",
    ".clflags{margin:0 0 12px;padding-left:18px;font-size:13.5px;line-height:1.55}",
    ".clsteps{list-style:none;margin:0 0 14px;padding:0;display:grid;gap:6px}",
    ".clsteps li{display:flex;gap:10px;align-items:center;background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-radius:10px;padding:8px 12px;font-size:13.5px}",
    ".clsteps li i{width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-style:normal;font-weight:700;font-size:12px;background:#e7edf2;color:#5b7183;flex:none}",
    ".clsteps li.done i{background:#2f7a4d;color:#fff}.clsteps li .grow{flex:1}.clsteps li small{color:var(--muted,#5b7183)}",
    ".clgrid{border-collapse:collapse;font-size:12.5px}.clgrid th,.clgrid td{padding:5px 7px;border-bottom:1px solid var(--line,#eef2f5);text-align:center;white-space:nowrap}",
    ".clgrid td:first-child,.clgrid th:first-child{text-align:left}",
    ".clchip{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;color:#fff;white-space:nowrap;background:#8796a3}",
    ".clchip.locked{background:#2f7a4d}.clchip.review{background:#1769aa}.clchip.open{background:#5b7183}.clchip.reopened{background:#b7791f}",
    ".clchip.overdue{background:#c0392b}.clchip.not_started{background:#c9d2d9;color:#2c3e50}.clchip.before{background:transparent;color:#a0acb6}",
    ".clchip.green{background:#2f7a4d}.clchip.amber{background:#b7791f}.clchip.red{background:#c0392b}.clchip.info{background:#8796a3}",
    ".clchip.pass{background:#2f7a4d}.clchip.fail{background:#c0392b}.clchip.warn{background:#b7791f}",
    ".clhg{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin:0 0 16px}",
    ".clhg .t{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-top:4px solid #8796a3;border-radius:12px;padding:10px 14px;cursor:pointer}",
    ".clhg .t.good{border-top-color:#2f7a4d}.clhg .t.warn{border-top-color:#b7791f}.clhg .t.bad{border-top-color:#c0392b}",
    ".clhg .t b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.clhg .t span{font-size:13px}.clhg .t small{display:block;color:var(--muted,#5b7183);font-size:11.5px;margin-top:3px}",
    ".clhg .t svg{width:100%;height:30px;margin-top:4px}",
    ".clsub{font-size:12px;color:var(--muted,#5b7183)}.clr{color:#c0392b}.clg{color:#2f7a4d}",
    ".cltbl td.num a{color:inherit;text-decoration:underline dotted}.cltbl tr.ind td{background:rgba(135,150,163,.06)}",
    ".cltbl tr.tot td{font-weight:700;border-top:2px solid var(--line,#d6dee5)}",
    ".clqty input{width:110px;text-align:right}",
    ".clcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:0 0 14px}",
    ".clcard{background:var(--panel,#fff);border:1px solid var(--line,#d6dee5);border-radius:12px;padding:12px 16px}",
    ".clcard h4{margin:0 0 8px;font-size:13px;color:var(--muted,#5b7183);font-weight:600;text-transform:uppercase;letter-spacing:.03em}",
  ].join("\n");
  document.head.append(css);

  const tile = (v, l, cls, sub, onclick) => h("div", { class: "t " + (cls || "") + (onclick ? " click" : ""), onclick }, h("b", {}, v), h("span", {}, l), sub ? h("small", {}, sub) : null);
  const chip = (st, label) => h("span", { class: "clchip " + st }, label || String(st).replace(/_/g, " "));
  const note = (text, cls) => h("div", { class: "clnote " + (cls || "") }, text);
  const sign = (v) => h("b", { class: v < 0 ? "clr" : "clg" }, money(v));
  function spark(values) {
    const vs = values.filter((v) => v != null);
    if (vs.length < 2) return null;
    const max = Math.max(...vs), min = Math.min(...vs), W = 200, H = 30;
    const x = (i) => 2 + (W - 4) * i / (values.length - 1);
    const y = (v) => H - 3 - (H - 6) * (max === min ? 0.5 : (v - min) / (max - min));
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = `<polyline points="${values.map((v, i) => (v == null ? null : x(i) + "," + y(v))).filter(Boolean).join(" ")}" fill="none" stroke="#1769aa" stroke-width="2"/>`;
    return svg;
  }
  function needProj(root, title, sub) {
    root.append(pageHead(title, sub));
    const pid = pidNow();
    if (!pid) { root.append(projectNotice()); return null; }
    return pid;
  }
  function docTable(items) {
    return table([{ k: "ref", label: "Document" }, { k: "text", label: "What breaks the check" },
      { label: "", v: (r) => (r.link ? h("a", { href: r.link }, "Open") : "") }], items || [], { search: (items || []).length > 8, export: false, empty: "Nothing listed." });
  }
  function codePicker(codes, value) {
    return h("select", { name: "cost_code_id" }, h("option", { value: "" }, "— choose a code —"),
      codes.map((k) => h("option", { value: k.id, selected: String(k.id) === String(value) }, k.code + " · " + k.name)));
  }

  /* ───────────────────────── 1. Cost codes ───────────────────────── */
  PAGES["cl/codes"] = async (root, params) => {
    await meta();
    const pid = needProj(root, "Cost codes", "Every BOQ item and the indirect heads of this project. Each ledger line lands on one of them from the document it came from.");
    if (!pid) return;
    const holder = h("div");
    root.append(holder);
    const load = async () => {
      const [d, qd] = await Promise.all([run("cl.codes", { project_id: pid }), run("cl.queue", { project_id: pid })]);
      holder.innerHTML = "";
      const u = d.unallocated;
      holder.append(h("div", { class: "clt" },
        tile(pct(u.pct), "Unallocated share of coded cost", u.pct >= d.block ? "bad" : (u.pct > d.target ? "warn" : "good"), "Target under " + d.target + "%, close blocked at " + d.block + "%"),
        tile(money(u.amount), "Unallocated cost", u.amount > 0 ? "warn" : "good", "of " + money(u.total) + " coded"),
        tile(qd.rows.length, "Documents waiting for a code", qd.rows.length ? "warn" : "good", "Coding required from " + (d.coding_from || "—"), () => tb.querySelectorAll(".tabs button")[1].click()),
        tile(money(d.opening), "Cost before coding started", "grey", "One line, not split (back-fill in Control settings)")));
      if (d.pilot) holder.append(note("Pilot project: two monthly closes run here before every project uses the link."));
      const list = () => {
        const box = h("div");
        box.append(h("div", { class: "bar" }, h("div", { class: "grow" }),
          META.rights.create ? h("button", { class: "btn small", onclick: () => addHead() }, "Add an indirect head") : null,
          META.rights.approve ? h("button", { class: "btn small", onclick: () => projSettings(d) }, "Coding start & pilot") : null));
        box.append(table([{ k: "code", label: "Code" }, { k: "kind_label", label: "Kind" }, { k: "name", label: "Name" }, { k: "unit", label: "Unit" },
          { label: "Contract qty", v: (r) => (r.kind === "boq" ? fmtQty(r.revised_qty != null ? r.revised_qty : r.qty) : "") },
          { k: "cost", label: "Cost to date", fmt: "money" }, { label: "Active", v: (r) => (r.active ? "Yes" : "No") }],
        d.rows, { name: "cost_codes", totals: ["cost"], onRow: (r) => linesDialog(pid, r.id, r.code + " " + r.name), rowClass: (r) => (r.kind !== "boq" ? "ind" : "") }));
        return box;
      };
      const waiting = () => {
        const box = h("div");
        if (!qd.rows.length) box.append(note("Nothing is waiting for a code.", "good"));
        else box.append(table([{ k: "date", label: "Date" }, { k: "no", label: "Document" }, { k: "what", label: "Needs" },
          { label: "", v: (r) => h("button", { class: "btn small primary", onclick: (e) => { e.stopPropagation(); fixRow(r, qd); } }, r.doc === "dpr" ? "Link hours" : (r.kind === "idle" ? "Link delay" : "Give code")) }],
        qd.rows, { name: "waiting_for_code", search: true }));
        box.append(h("p", { class: "hint" }, "Requisitions, purchase requests, store issues and work orders cannot be approved, and DPRs cannot be submitted, until every line has a code. A requisition's code is copied to the purchase request and the issue."));
        return box;
      };
      const unalloc = () => {
        const box = h("div");
        const rows = qd.unallocated_lines;
        if (!rows.length) { box.append(note("No cost is sitting in Unallocated.", "good")); return box; }
        const pick = new Set();
        const sel = codePicker(qd.codes.filter((k) => k.kind !== "unallocated"));
        box.append(h("div", { class: "bar" }, sel, h("button", { class: "btn small primary", onclick: async () => {
          if (!sel.value || !pick.size) { toast("Tick lines and choose a code.", "err"); return; }
          await run("cl.recode", { line_ids: [...pick], cost_code_id: sel.value }, "Moved");
          load();
        } }, "Move ticked lines")));
        box.append(table([{ label: "", v: (r) => h("input", { type: "checkbox", onclick: (e) => { e.stopPropagation(); if (e.target.checked) pick.add(r.line_id); else pick.delete(r.line_id); } }) },
          { k: "date", label: "Date" }, { k: "account", label: "Account" }, { k: "narration", label: "Narration" }, { k: "source", label: "From" },
          { k: "status", label: "Status" }, { k: "amount", label: "Amount", fmt: "money" }], rows, { name: "unallocated_lines", totals: ["amount"] }));
        box.append(h("p", { class: "hint" }, "Moving a line changes only its cost code; the amount, account and voucher stay as posted."));
        return box;
      };
      const tb = tabs([["Code list", list], ["Waiting for a code (" + qd.rows.length + ")", waiting], ["Unallocated lines", unalloc]], params && params.tab === "queue" ? 1 : 0);
      holder.append(tb);
    };
    const addHead = () => {
      const f = form([{ k: "kind", label: "Kind", type: "select", options: [["prelim", "Preliminaries"], ["overhead", "Site overhead"], ["temp", "Temporary works"], ["defect", "Defects and rework"]], req: true },
        { k: "code", label: "Code", req: true, ph: "TW-02" }, { k: "name", label: "Name", req: true, wide: true }], { kind: "temp" });
      modal("Add an indirect head", f, [{ label: "Add", cls: "primary", act: async () => { await run("cl.code_save", { row: Object.assign({ project_id: pid }, f.values()) }, "Added"); load(); } }], { narrow: true });
    };
    const projSettings = (d) => {
      const f = form([{ k: "coding_from", label: "Coding required from", type: "date", hint: "DPRs, requisitions, issues and work orders dated on or after this day need a code" },
        { k: "pilot", label: "Pilot project", type: "check" }], { coding_from: d.coding_from, pilot: d.pilot });
      modal("Coding start and pilot", f, [{ label: "Save", cls: "primary", act: async () => { await run("cl.project_save", Object.assign({ project_id: pid }, f.values()), "Saved"); load(); } }], { narrow: true });
    };
    const fixRow = (r, qd) => {
      if (r.doc === "dpr") { dprCoding(r.doc_id, load); return; }
      const sel = codePicker(qd.codes);
      const dsel = h("select", { name: "delay_id" }, h("option", { value: "" }, "— the delay that caused it —"),
        qd.delays.map((x) => h("option", { value: x.id }, x.date + " · " + (x.category || "") + " · " + (x.resp || "") + (x.hours ? " · " + x.hours + " h" : ""))));
      const body = h("div", {}, h("p", {}, r.no + " · " + r.what),
        r.kind === "idle" ? h("label", { class: "f wide" }, h("span", {}, "Delay record"), dsel) : h("label", { class: "f wide" }, h("span", {}, "Cost code"), sel));
      modal(r.kind === "idle" ? "Link idle hours to a delay" : "Give a cost code", body, [{ label: "Save", cls: "primary", act: async () => {
        await run("cl.doc_code_set", { doc: r.doc, line_id: r.line_id, cost_code_id: sel.value || null, delay_id: dsel.value || null }, "Saved");
        load();
      } }], { narrow: true });
    };
    await load();
  };

  /* DPR: gang hours over work lines and Idle; machines' idle to the delay */
  async function dprCoding(dprId, after) {
    const d = await run("cl.dpr_coding", { dpr_id: dprId });
    const workActs = d.work.filter((w) => w.activity_id).map((w) => [w.activity_id, (w.acode || "") + " " + (w.aname || "") + (w.boq_code ? " · BOQ " + w.boq_code : "")]);
    const acts = workActs.length ? workActs : d.activities.map((a) => [a.id, a.code + " " + a.name + (a.boq_code ? " · BOQ " + a.boq_code : "")]);
    const delayOpts = d.delays.map((x) => [x.id, (x.category || "delay") + " · " + (x.resp || "") + (x.hours ? " · " + x.hours + " h" : "")]);
    const body = h("div");
    body.append(h("p", { class: "hint" }, "DPR " + (d.dpr.no || "") + " · " + d.dpr.date + ". Split each gang's hours over the day's work lines; hours lost go to Idle with the delay that caused them (employer, contractor or neutral)."));
    if (d.problems.length) body.append(note(d.problems.map((p) => p.what).join("; "), "warn"));
    const gangState = d.gangs.map((g) => ({ g, rows: (g.split.length ? g.split : [{ activity_id: workActs.length === 1 ? workActs[0][0] : "", hours: g.hours }]).map((s) => ({ ...s })) }));
    const gbox = h("div");
    const drawG = () => {
      gbox.innerHTML = "";
      gangState.forEach((st) => {
        const g = st.g;
        const card = h("div", { class: "clcard", style: "margin-bottom:10px" }, h("h4", {}, (g.trade || "Gang") + (g.party ? " · " + g.party : "") + " · " + (g.count || 0) + " × " + (g.hours || 0) + " h"));
        st.rows.forEach((s, i) => {
          const a = h("select", { onchange: (e) => { s.activity_id = e.target.value; if (s.activity_id) { s.delay_id = ""; } drawG(); } }, h("option", { value: "" }, "Idle (delay)"),
            acts.map(([v, l]) => h("option", { value: v, selected: String(v) === String(s.activity_id) }, l)));
          const dl = h("select", { disabled: !!s.activity_id, onchange: (e) => { s.delay_id = e.target.value; } }, h("option", { value: "" }, "— delay —"),
            delayOpts.map(([v, l]) => h("option", { value: v, selected: String(v) === String(s.delay_id) }, l)));
          const hr = h("input", { type: "number", step: "any", value: s.hours, style: "width:90px", onchange: (e) => { s.hours = e.target.value; } });
          card.append(h("div", { class: "bar" }, a, dl, hr, h("span", { class: "clsub" }, "hours"),
            h("button", { class: "btn small", onclick: () => { st.rows.splice(i, 1); drawG(); } }, "×")));
        });
        card.append(h("button", { class: "btn small", onclick: () => { st.rows.push({ activity_id: "", hours: 0 }); drawG(); } }, "+ split"));
        gbox.append(card);
      });
    };
    drawG();
    body.append(gbox);
    const mState = d.machines.map((m) => ({ m, delay_id: m.delay_id || "" }));
    const idleM = mState.filter((s) => (s.m.idle_hours || 0) > 0);
    if (idleM.length) {
      body.append(h("h4", {}, "Machines with idle hours"));
      idleM.forEach((s) => body.append(h("div", { class: "bar" }, h("span", { style: "min-width:160px" }, (s.m.code || "") + " · idle " + s.m.idle_hours + " h"),
        h("select", { onchange: (e) => { s.delay_id = e.target.value; } }, h("option", { value: "" }, "— the delay that caused it —"),
          delayOpts.map(([v, l]) => h("option", { value: v, selected: String(v) === String(s.delay_id) }, l))))));
    }
    modal("Cost coding of DPR " + (d.dpr.no || d.dpr.date), body, [{ label: "Save", cls: "primary", act: async () => {
      await run("cl.dpr_coding_save", { dpr_id: dprId,
        gangs: gangState.map((st) => ({ dpr_labour_id: st.g.id, split: st.rows.map((s) => ({ activity_id: s.activity_id || null, delay_id: s.delay_id || null, hours: s.hours })) })),
        machines: mState.filter((s) => s.delay_id).map((s) => ({ dpr_equipment_id: s.m.id, delay_id: s.delay_id })) }, "Saved");
      if (after) after();
    } }], {});
  }
  window.bcoDprCoding = dprCoding;

  async function linesDialog(pid, codeId, title, extra) {
    const d = await run("cl.lines", Object.assign({ project_id: pid, code_id: codeId }, extra || {}));
    modal(title, h("div", {}, h("p", { class: "hint" }, d.count + " line(s), total " + money(d.total) + (d.count > d.rows.length ? " (first " + d.rows.length + " shown)" : "")),
      table([{ k: "date", label: "Date" }, { k: "no", label: "Voucher" }, { k: "account", label: "Account" }, { label: "Type", v: (r) => TYPES[r.ctype] || r.ctype },
        { k: "narration", label: "Narration" }, { k: "source", label: "From" }, { k: "status", label: "Status" }, { k: "how", label: "Coded by" }, { k: "amount", label: "Amount", fmt: "money" }],
      d.rows, { name: "cost_lines", totals: ["amount"] })), [], {});
  }

  /* ───────────────────────── 2. Control budget ───────────────────────── */
  PAGES["cl/budget"] = async (root) => {
    await meta();
    const pid = needProj(root, "Control budget", "The bid's cost per BOQ item and cost type. Original is locked at award; Current adds approved variations and re-plans; Forecast is recalculated at each monthly close.");
    if (!pid) return;
    const holder = h("div");
    root.append(holder);
    const load = async () => {
      const d = await run("cl.budget", { project_id: pid });
      holder.innerHTML = "";
      const t = d.totals;
      const st = d.original ? "Original v" + d.original.version_no + " approved " + (d.original.approved_at || "").slice(0, 10) : (d.draft ? "Draft " + d.draft.status : "Not prepared");
      holder.append(h("div", { class: "clt" },
        tile(money(t.contract), "Contract value (BOQ)", "grey"),
        tile(money(t.original || t.draft), d.original ? "Original budget" : "Draft budget", d.original ? "good" : "warn", st),
        tile(money(t.current), "Current budget", "", d.current ? "Version " + d.current.version_no : "After approval"),
        tile(money(t.forecast), "Forecast at completion", "", d.forecast ? "From the close of " + (d.forecast.reason || "").replace("Forecast at ", "") : "From the first locked close"),
        tile(pct(d.bid_margin_pct), "Bid margin (contract − original)", d.bid_margin_pct != null && d.bid_margin_pct < 0 ? "bad" : "good")));
      const bar = h("div", { class: "bar" });
      if (!d.original && d.rights.create && (!d.draft || d.draft.status === "draft")) {
        bar.append(h("button", { class: "btn primary", onclick: async () => {
          const r = await run("cl.budget_import", { project_id: pid }, (x) => x.items + " item(s) imported");
          if (r.missing && r.missing.length) toast("No rate analysis for: " + r.missing.slice(0, 6).join(", ") + (r.missing.length > 6 ? "…" : ""), "err");
          load();
        } }, d.draft ? "Re-import from rate analysis" : "Import from rate analysis"),
        h("label", { class: "btn" }, "Import a workbook", h("input", { type: "file", accept: ".xlsx,.csv", style: "display:none", onchange: async (e) => {
          const f = e.target.files[0]; if (!f) return;
          const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(",")[1]); fr.readAsDataURL(f); });
          await run("cl.budget_import", { project_id: pid, b64, filename: f.name }, "Imported"); load();
        } })));
        if (d.draft) bar.append(h("button", { class: "btn", onclick: async () => { await run("cl.budget_submit", { project_id: pid }, "Sent to the director"); load(); } }, "Submit for approval"));
      }
      if (!d.original && d.draft && d.draft.status === "submitted" && d.rights.approve) {
        bar.append(h("button", { class: "btn primary", onclick: async () => { await run("cl.budget_approve", { project_id: pid }, "Original budget approved and locked"); load(); } }, "Approve as Original"),
          h("button", { class: "btn", onclick: async () => { const n = await ask("Return the draft", "Say what to change.", { input: "Note", required: true }); if (n) { await run("cl.budget_approve", { project_id: pid, decision: "return", note: n }, "Returned"); load(); } } }, "Return"));
      }
      bar.append(h("div", { class: "grow" }));
      if (d.original && d.rights.create) bar.append(h("button", { class: "btn", onclick: () => changeDialog(d, null) }, "Propose a change"));
      holder.append(bar);
      if (d.draft && d.draft.status === "submitted") holder.append(note("The draft is waiting for the director's approval.", "warn"));
      const byT = d.by_type || {};
      if (Object.keys(byT).length) holder.append(h("p", { class: "clsub" }, "By cost type: " + Object.keys(TYPES).filter((k) => byT[k]).map((k) => TYPES[k] + " " + m0(byT[k])).join(" · ")));
      holder.append(h("div", { class: "cltbl" }, table([{ k: "code", label: "Code" }, { k: "name", label: "Item" }, { k: "unit", label: "Unit" },
        { label: "Qty", v: (r) => fmtQty(r.line ? r.line.qty : null) }, { k: "rate", label: "Contract rate", fmt: "money" },
        { label: "Labour", v: (r) => n2(r.line && r.line.unit_labour) }, { label: "Material", v: (r) => n2(r.line && r.line.unit_material) },
        { label: "Own equip.", v: (r) => n2(r.line && r.line.unit_equip_own) }, { label: "Rented equip.", v: (r) => n2(r.line && r.line.unit_equip_rent) },
        { label: "Subcon.", v: (r) => n2(r.line && r.line.unit_subcon) }, { label: "Other", v: (r) => n2(r.line && r.line.unit_other) },
        { label: "Cost / unit", v: (r) => n2(r.unit_cost) }, { label: "Margin", v: (r) => (r.margin_pct == null ? "" : h("span", { class: r.margin_pct < 0 ? "clr" : "" }, pct(r.margin_pct))) },
        { k: "original", label: "Original", fmt: "money" }, { k: "current", label: "Current", fmt: "money" }, { k: "forecast", label: "Forecast", fmt: "money" },
        { label: "", v: (r) => (r.placeholder ? chip("amber", "placeholder") : "") }],
      d.rows, { name: "control_budget", totals: ["original", "current", "forecast"], rowClass: (r) => (r.kind !== "boq" ? "ind" : ""),
        onRow: (r) => (!d.original && d.draft && d.draft.status === "draft" && d.rights.create ? lineDialog(d, r) : (d.original && d.rights.create ? changeDialog(d, r) : null)) })));
      if (d.changes.length) {
        holder.append(h("h3", {}, "Changes to the Current budget"),
          table([{ k: "id", label: "#" }, { k: "code", label: "Code" }, { k: "kind", label: "Kind" }, { k: "reason", label: "Reason" },
            { label: "Before / unit", v: (r) => n2(r.before ? ["unit_labour", "unit_material", "unit_equip_own", "unit_equip_rent", "unit_subcon", "unit_other"].reduce((a, k) => a + (r.before[k] || 0), 0) : null) },
            { label: "After / unit", v: (r) => n2(r.after ? ["unit_labour", "unit_material", "unit_equip_own", "unit_equip_rent", "unit_subcon", "unit_other"].reduce((a, k) => a + (r.after[k] || 0), 0) : null) },
            { k: "status", label: "Status", fmt: "status" },
            { label: "", v: (r) => (["proposed", "pm_approved"].includes(r.status) ? h("span", {},
              h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); await run("cl.budget_change_decide", { id: r.id, decision: "approve" }, (x) => (x.status === "approved" ? "Approved: new Current version" : "Approved by the PM; the director approves next")); load(); } }, r.status === "proposed" ? "Approve (PM)" : "Approve (director)"),
              h("button", { class: "btn small", onclick: async (e) => { e.stopPropagation(); await run("cl.budget_change_decide", { id: r.id, decision: "reject" }, "Rejected"); load(); } }, "Reject")) : "") }],
          d.changes, { name: "budget_changes", search: false }));
      }
    };
    const unitFields = [{ k: "qty", label: "Quantity", type: "number" }, { k: "unit_labour", label: "Labour per unit", type: "number" }, { k: "unit_material", label: "Material per unit", type: "number" },
      { k: "unit_equip_own", label: "Own equipment per unit", type: "number" }, { k: "unit_equip_rent", label: "Rented equipment per unit", type: "number" },
      { k: "unit_subcon", label: "Subcontract per unit", type: "number" }, { k: "unit_other", label: "Other per unit", type: "number" },
      { k: "way_of_working", label: "Way of working", type: "select", options: [["direct", "Direct"], ["labour_sc", "Labour supply"], ["supplied_sc", "Item rate, our material"], ["b2b_sc", "Back-to-back"]] }];
    const lineDialog = (d, r) => {
      const f = form(unitFields, r.line || { qty: r.revised_qty != null ? r.revised_qty : r.contract_qty });
      modal("Draft budget · " + r.code + " " + r.name, f, [{ label: "Save", cls: "primary", act: async () => { await run("cl.budget_line_save", Object.assign({ project_id: pid, cost_code_id: r.code_id }, f.values()), "Saved"); load(); } }], {});
    };
    const changeDialog = (d, r) => {
      const fields = [{ k: "cost_code_id", label: "Cost code", type: "select", options: d.rows.map((x) => [x.code_id, x.code + " " + x.name]), req: true }].concat(unitFields,
        [{ k: "reason", label: "Reason", type: "textarea", req: true, wide: true }]);
      const f = form(fields, Object.assign({ cost_code_id: r ? r.code_id : "" }, (r && r.line) || {}));
      modal("Propose a change to the Current budget", f, [{ label: "Propose", cls: "primary", act: async () => { await run("cl.budget_change", Object.assign({ project_id: pid }, f.values()), "Proposed: the PM approves, then the director"); load(); } }], {});
    };
    await load();
  };

  /* ───────────────────────── 3. Project close ───────────────────────── */
  PAGES["cl/close"] = async (root, params) => {
    await meta();
    const pid = needProj(root, "Project close", "Once a month engineering and accounts sign the same figures at the cut-off, and BuildCore freezes them.");
    if (!pid) return;
    const holder = h("div");
    root.append(holder);
    const list = async () => {
      const d = await run("cl.closes", { project_id: pid });
      holder.innerHTML = "";
      const bar = h("div", { class: "bar" });
      if (d.can.open) {
        const sel = h("select", {}, [0, 1, 2, 3, 4, 5].map((i) => { const p = shiftP(d.default_period, -i); return h("option", { value: p }, periodLabel(p)); }));
        bar.append(h("span", {}, "Month "), sel, h("button", { class: "btn primary", onclick: async () => { const r = await run("cl.close_open", { project_id: pid, period: sel.value }); detail(r.id); } }, "Start or open the close"));
      }
      holder.append(bar);
      holder.append(table([{ k: "period_label", label: "Month" }, { k: "cutoff_date", label: "Cut-off" }, { label: "Status", v: (r) => chip(r.status) },
        { label: "Value", v: (r) => money(r.summary && r.summary.total && r.summary.total.value) }, { label: "Cost", v: (r) => money(r.summary && r.summary.total && r.summary.total.cost) },
        { label: "Margin", v: (r) => (r.summary && r.summary.total ? sign(r.summary.total.margin) : "—") }, { label: "Forecast margin", v: (r) => money(r.summary && r.summary.total && r.summary.total.forecast_margin) },
        { k: "locked_at", label: "Locked" }], d.rows, { name: "project_closes", search: false, onRow: (r) => detail(r.id), empty: "No month closed yet. Coding is required from " + (d.coding_from || "—") + "." }));
    };
    const detail = async (id) => {
      const d = await run("cl.close_get", { id });
      const k = d.close;
      holder.innerHTML = "";
      const locked = k.status === "locked";
      holder.append(h("div", { class: "bar" }, h("button", { class: "btn small", onclick: list }, "‹ All months"), h("h2", { style: "margin:0 8px" }, k.period_label), chip(k.status),
        h("span", { class: "clsub" }, "Cut-off " + k.cutoff_date + " · from " + k.from_date), h("div", { class: "grow" }),
        h("a", { class: "btn small", href: "#/cl/cvr?close_id=" + k.id }, locked ? "CVR (locked snapshot)" : "CVR (provisional)")));
      holder.append(h("ul", { class: "clsteps" }, d.steps.map((s) => h("li", { class: s.done ? "done" : "" }, h("i", {}, s.done ? "✓" : s.no), h("span", { class: "grow" }, s.name), h("small", {}, s.note)))));
      if (locked) {
        const t = (k.summary && k.summary.total) || {};
        holder.append(h("div", { class: "clt" }, tile(money(t.value), "Value earned", ""), tile(money(t.cost), "Cost to date", ""), tile(money(t.margin), "Margin to date", t.margin < 0 ? "bad" : "good", pct(t.margin_pct)),
          tile(money(t.forecast_margin), "Forecast margin", t.forecast_margin < 0 ? "bad" : "good", pct(t.forecast_margin_pct)), tile(t.cpi == null ? "—" : n2(t.cpi), "CPI", t.cpi != null && t.cpi < 0.95 ? "bad" : "good")));
        holder.append(note("Locked by " + (k.approved_by_name || "") + " on " + (k.locked_at || "").slice(0, 16) + ". A back-dated entry into this month is refused until the director reopens it; the reopening is logged.", "good"));
      }
      const pend = () => (d.pending.length ? docTable(d.pending) : note("Everything up to the cut-off is approved.", "good"));
      const qty = () => {
        const box = h("div", { class: "clqty" });
        const vals = {};
        box.append(h("p", { class: "hint" }, "Quantity done to date per BOQ item, from the measurement book. Quantity beyond the last IPC is work done not billed."));
        box.append(table([{ k: "code", label: "Item" }, { k: "description", label: "Description" }, { k: "unit", label: "Unit" }, { k: "contract_qty", label: "Contract", fmt: "qty" },
          { k: "measured", label: "Measured (verified)", fmt: "qty" }, { k: "ipc_qty", label: "In IPCs", fmt: "qty" },
          { label: "Done to date", v: (r) => (locked || !d.can.qty ? fmtQty(r.qty_done) : h("input", { type: "number", step: "any", value: r.qty_done, onchange: (e) => { vals[r.boq_item_id] = e.target.value; } })) },
          { label: "Not billed", v: (r) => fmtQty(r.not_billed) }, { label: "Value not billed", v: (r) => money(Math.max(0, r.not_billed) * (r.rate || 0)) }], d.qty, { name: "close_quantities" }));
        let scVals = {};
        if (d.sc.length) {
          box.append(h("h4", {}, "Subcontract work done to the cut-off"), table([{ k: "order_no", label: "Work order" }, { k: "party", label: "Subcontractor" }, { k: "description", label: "Line" }, { k: "boq_code", label: "Main item" },
            { k: "qty", label: "Ordered", fmt: "qty" }, { k: "billed_qty", label: "Billed", fmt: "qty" },
            { label: "Done to date", v: (r) => (locked || !d.can.qty ? fmtQty(r.qty_done) : h("input", { type: "number", step: "any", value: r.qty_done, onchange: (e) => { scVals[r.order_item_id] = e.target.value; } })) }],
          d.sc, { name: "close_subcontract", search: false }));
        }
        if (!locked && d.can.qty) {
          const save = async (confirm) => {
            const rows = d.qty.map((r) => ({ boq_item_id: r.boq_item_id, qty_done: vals[r.boq_item_id] != null ? vals[r.boq_item_id] : r.qty_done }));
            const sc_rows = d.sc.map((r) => ({ order_item_id: r.order_item_id, qty_done: scVals[r.order_item_id] != null ? scVals[r.order_item_id] : r.qty_done }));
            await run("cl.close_qty_save", { id: k.id, rows, sc_rows, confirm: confirm ? 1 : 0 }, confirm ? "Quantities confirmed" : "Saved");
            detail(k.id);
          };
          box.append(h("div", { class: "bar" }, h("button", { class: "btn", onclick: () => save(false) }, "Save"), h("button", { class: "btn primary", onclick: () => save(true) }, "Save and confirm (QS)")));
        }
        return box;
      };
      const acc = () => {
        const box = h("div");
        if (!locked && d.can.accruals) box.append(h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { await run("cl.close_accruals", { id: k.id }, "Accruals calculated"); detail(k.id); } }, "Calculate accruals")));
        box.append(table([{ k: "label", label: "Accrual" }, { k: "code", label: "Cost code" }, { k: "detail", label: "Detail" }, { k: "amount", label: "Amount", fmt: "money" }],
          d.accruals, { name: "close_accruals", totals: ["amount"], empty: k.accruals_at ? "No accruals this month." : "Not calculated yet." }));
        box.append(h("p", { class: "hint" }, d.accrual_post ? "The company posts cost accruals as reversing journals through the posting queue (finance manager, after the lock)." : "Accruals live only in this close (management accounts); the statutory books are untouched."));
        if (locked && d.accrual_post && d.can.post && !d.accruals.some((x) => x.voucher_id)) box.append(h("button", { class: "btn", onclick: async () => { await run("cl.close_post_accruals", { id: k.id }, "Sent to the posting queue"); detail(k.id); } }, "Post cost accruals as reversing journals"));
        return box;
      };
      const chk = () => {
        const box = h("div");
        if (!locked) box.append(h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { await run("cl.close_checks", { id: k.id }, (x) => (x.ok ? "All blocking checks pass" : "Some checks fail")); detail(k.id); } }, "Run the twelve checks")));
        if (!d.checks.length) { box.append(note("The checks have not run for this close yet.")); return box; }
        d.checks.forEach((c) => {
          const det = c.detail || {};
          const head = h("div", { class: "bar" }, chip(c.override_by ? "warn" : c.result, c.override_by ? "overridden" : c.result), h("b", {}, c.check_no + ". " + c.name), h("span", { class: "clsub" }, c.blocking ? "blocks the close" : "warning"), h("div", { class: "grow" }),
            c.result === "fail" && !c.override_by && d.can.lock && !locked ? h("button", { class: "btn small", onclick: async () => { const r = await ask("Override check " + c.check_no, "The reason is saved on the close record and counted on the company health dashboard.", { input: "Reason", required: true }); if (r) { await run("cl.close_override", { id: k.id, check_no: c.check_no, reason: r }, "Overridden"); detail(k.id); } } }, "Override (director)") : null);
          const card = h("div", { class: "clcard", style: "margin-bottom:8px" }, head, h("p", { style: "margin:4px 0" }, det.text || ""),
            c.override_by ? h("p", { class: "clsub" }, "Overridden by " + (c.override_name || "") + ": " + c.override_reason) : null);
          if ((det.items || []).length) card.append(h("details", {}, h("summary", {}, det.count + " document(s)"), docTable(det.items)));
          box.append(card);
        });
        return box;
      };
      const signs = () => {
        const box = h("div");
        const who = [["qs", "QS signs value", k.signed_qs_name, k.signed_qs_at, d.can.qs], ["accounts", "Project accountant signs cost", k.signed_accounts_name, k.signed_accounts_at, d.can.accounts],
          ["pm", "Project manager signs the forecast", k.signed_pm_name, k.signed_pm_at, d.can.pm]];
        box.append(table([{ k: 1, label: "Signature" }, { label: "Signed by", v: (r) => r[2] || "—" }, { label: "When", v: (r) => (r[3] || "").slice(0, 16) },
          { label: "", v: (r) => (!r[2] && r[4] && !locked ? h("button", { class: "btn small primary", onclick: async () => { await run("cl.close_sign", { id: k.id, as: r[0] }, "Signed"); detail(k.id); } }, "Sign") : "") }], who, { search: false, export: false }));
        if (!locked && d.can.lock) box.append(h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { if (await ask("Approve and lock " + k.period_label, "The checks run again, value, cost, accruals, forecast and KPIs are saved, and the month is locked for this project.", { ok: "Approve and lock" })) { await run("cl.close_lock", { id: k.id }, "Locked"); detail(k.id); } } }, "Director: approve and lock")));
        if (locked && d.can.lock) box.append(h("div", { class: "bar" }, h("button", { class: "btn warn", onclick: async () => { const r = await ask("Reopen " + k.period_label, "Signatures are cleared and the month accepts back-dated entries again. The reason is logged.", { input: "Reason", required: true, danger: true }); if (r) { await run("cl.close_reopen", { id: k.id, reason: r }, "Reopened"); detail(k.id); } } }, "Reopen the month")));
        if (d.reopen_log.length) box.append(h("h4", {}, "Reopened"), table([{ k: "at", label: "When" }, { k: "by", label: "By" }, { k: "reason", label: "Reason" }], d.reopen_log, { search: false, export: false }));
        return box;
      };
      holder.append(tabs([["1 · Site cut-off (" + d.pending.length + ")", pend], ["2–3 · Quantities", qty], ["5 · Accruals", acc], ["6 · Checks", chk], ["7–8 · Sign and lock", signs]], params && params.tab ? Number(params.tab) : 0));
    };
    if (params && params.id) await detail(params.id); else await list();
  };

  /* BS period helpers mirrored from the engine (labels only) */
  const BSM = ["Baisakh", "Jestha", "Asar", "Shrawan", "Bhadra", "Ashoj", "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra"];
  function periodLabel(p) { const [y, m] = String(p).split("-").map(Number); return (BSM[m - 1] || "") + " " + y; }
  function shiftP(p, n) { let [y, m] = String(p).split("-").map(Number); m += n; while (m < 1) { m += 12; y--; } while (m > 12) { m -= 12; y++; } return y + "-" + String(m).padStart(2, "0"); }

  /* ───────────────────────── 4. CVR and forecast ───────────────────────── */
  PAGES["cl/cvr"] = async (root, params) => {
    await meta();
    const pid = (params && params.project_id) || pidNow();
    root.append(pageHead("CVR and forecast", "What engineering earned against what accounts spent, item by item, and the forecast final profit."));
    if (!pid) { root.append(projectNotice()); return; }
    let filt = { as_of: today(), close_id: (params && params.close_id) || "" };
    const closes = await run("cl.closes", { project_id: pid });
    const holder = h("div");
    const load = async () => {
      const d = await run("cl.cvr", { project_id: pid, as_of: filt.as_of, close_id: filt.close_id || null });
      holder.innerHTML = "";
      const t = d.total;
      holder.append(d.provisional ? note("Provisional: live figures at " + d.as_of + (d.qty_source === "close" ? " with the close's quantities" : " with verified measurements") + ". A locked close freezes them.", "warn")
        : note("Locked snapshot of " + d.period_label + " (cut-off " + d.as_of + ").", "good"));
      holder.append(h("div", { class: "clt" },
        tile(money(t.value), "Value earned", "", "Billed " + money(t.billed_value), () => drill(d, null, "value")),
        tile(money(t.cost), "Cost to date", "", "Posted " + m0(t.cost_posted) + " · waiting " + m0(t.cost_waiting) + " · accrued " + m0(t.cost_accrued)),
        tile(money(t.margin), "Margin to date", t.margin < 0 ? "bad" : "good", pct(t.margin_pct)),
        tile(t.cpi == null ? "—" : n2(t.cpi), "CPI", t.cpi != null && t.cpi < (META.settings.cl_flag_cpi || 0.95) ? "bad" : "good", "Budget cost of work done ÷ cost"),
        tile(money(t.eac), "Forecast final cost (EAC)", "", "Cost to complete " + money(t.ctc)),
        tile(money(t.forecast_margin), "Forecast margin", t.forecast_margin < 0 ? "bad" : "good", pct(t.forecast_margin_pct) + (t.bid_margin_pct != null ? " · bid " + pct(t.bid_margin_pct) : "")),
        tile(money(t.unbilled_value), "Value ahead of IPCs", t.unbilled_value > (t.avg_monthly_billing || 0) ? "warn" : "good", "Average billing " + money(t.avg_monthly_billing) + " a month"),
        tile(money(t.claims_pending), "Claims pending (not in value)", "grey", "Price adjustment certified " + money(t.pa_certified))));
      if (d.flags.length) holder.append(h("div", { class: "clnote bad" }, h("b", {}, "Flags"), h("ul", { class: "clflags" }, d.flags.map((f) => h("li", {}, f.text)))));
      let split = LSg("cl_cvr_split", "0") === "1";
      const tbox = h("div", { class: "cltbl" });
      const draw = () => {
        tbox.innerHTML = "";
        const costCell = (r, k, ct) => (r[k] ? h("a", { href: "javascript:void 0", onclick: (e) => { e.stopPropagation(); drill(d, r, "cost", ct); } }, m0(r[k])) : (r[k] === 0 ? "0" : "—"));
        const cols = [{ k: "code", label: "Code" }, { k: "name", label: "Item" },
          { label: "Qty done / total", v: (r) => (r.kind === "boq" ? q3(r.qty_done) + " / " + q3(r.qty_total) : "") },
          { label: "Value", fmt: "num", v: (r) => (r.kind === "boq" && r.value ? h("a", { href: "javascript:void 0", onclick: (e) => { e.stopPropagation(); drill(d, r, "value"); } }, m0(r.value)) : m0(r.value)) }]
          .concat(split ? Object.keys(TYPES).map((ct) => ({ label: TYPES[ct], fmt: "num", v: (r) => costCell(r, "cost_" + ct.toLowerCase(), ct) })) : [])
          .concat([{ label: "Cost to date", fmt: "num", v: (r) => costCell(r, "cost") },
            { label: "Budget cost of work done", fmt: "num", v: (r) => m0(r.bcwd) },
            { label: "Margin", fmt: "num", v: (r) => (r.margin == null ? "" : h("span", { class: r.margin < 0 ? "clr" : "" }, m0(r.margin))) },
            { label: "CPI", fmt: "num", v: (r) => (r.cpi == null ? "" : h("span", { class: r.cpi < 0.95 ? "clr" : "" }, n2(r.cpi))) },
            { label: "Cost to complete", fmt: "num", v: (r) => m0(r.ctc) }, { label: "EAC", fmt: "num", v: (r) => m0(r.eac) },
            { label: "Forecast margin", fmt: "num", v: (r) => (r.forecast_margin == null ? "" : h("span", { class: r.forecast_margin < 0 ? "clr" : "" }, m0(r.forecast_margin))) },
            { label: "Wastage", fmt: "num", v: (r) => (r.wastage_value ? m0(r.wastage_value) : "") },
            { label: "After site overhead", fmt: "num", v: (r) => (r.margin_after_oh == null ? "" : m0(r.margin_after_oh)) },
            { label: "Forecast basis", v: (r) => h("span", { class: "clsub" }, r.forecast_basis || "") },
            { label: "", v: (r) => ((r.flags || []).length ? chip("red", r.flags.length + " flag") : "") }]);
        const rows = d.rows.concat([Object.assign({ code: "", name: "Project total", kind: "total" }, t)]);
        tbox.append(table(cols, rows, { name: "cvr_" + (d.project.code || ""), rowClass: (r) => (r.kind === "total" ? "tot" : (r.kind !== "boq" ? "ind" : "")),
          onRow: (r) => (r.kind === "boq" && d.provisional && META.rights.submit ? overrideDialog(r) : null) }));
      };
      holder.append(h("div", { class: "bar" }, h("label", { class: "f check" }, h("input", { type: "checkbox", checked: split, onchange: (e) => { split = e.target.checked; LSs("cl_cvr_split", split ? "1" : "0"); draw(); } }), "Cost by type (L / M / E / S / other)"),
        h("div", { class: "grow" }), h("span", { class: "clsub" }, "Own machines: " + (d.mode === "rate" ? "charged at rate per hour" : "actual running costs") + (d.budget_version ? " · budget v" + d.budget_version : " · no approved budget yet"))));
      draw();
      holder.append(tbox);
      const sb = d.standby_cost || {};
      if ((sb.employer || 0) + (sb.contractor || 0) + (sb.neutral || 0) > 0) holder.append(h("p", { class: "clsub" }, "Own machines standing idle at the standby rate (management figure): employer " + money(sb.employer) + " (claimable), contractor " + money(sb.contractor) + ", neutral " + money(sb.neutral) + "."));
      const accr = (d.accruals || []).filter((x) => Math.abs(x.amount) > 0.004);
      if (accr.length) holder.append(h("h3", {}, "Accruals in these figures"), table([{ label: "Accrual", v: (r) => (META.accrual_labels[r.kind] || r.kind) }, { k: "side", label: "Where it shows" }, { k: "detail", label: "Detail" }, { k: "amount", label: "Amount", fmt: "money" }], accr, { name: "cvr_accruals", search: false }));
    };
    const overrideDialog = (r) => {
      const f = form([{ k: "unit_cost", label: "Forecast cost per unit (empty = rule)", type: "number" }, { k: "note", label: "Why", type: "textarea", wide: true }], { unit_cost: r.forecast_basis && r.forecast_basis.startsWith("PM") ? r.forecast_unit : "" });
      modal("Forecast cost per unit · " + r.code, h("div", {}, h("p", { class: "hint" }, "Now " + n2(r.forecast_unit) + " (" + r.forecast_basis + "). Budget " + n2(r.budget_unit) + "."), f),
        [{ label: "Save", cls: "primary", act: async () => { await run("cl.forecast_override", Object.assign({ project_id: pid, cost_code_id: r.code_id }, f.values()), "Saved"); load(); } }], { narrow: true });
    };
    const drill = async (d, r, what, ctype) => {
      const x = await run("cl.drill", { project_id: pid, code_id: r ? r.code_id : null, as_of: d.as_of, what, ctype: ctype || null });
      if (what === "value") {
        modal("Value behind " + (r ? r.code : "the project"), h("div", {}, h("h4", {}, "Measurements"), table([{ k: "date", label: "Date" }, { k: "no", label: "Measurement" }, { k: "status", label: "Status" }, { k: "location", label: "Location" }, { k: "qty", label: "Qty", fmt: "qty" }], x.measurements || [], { search: false, empty: "Open an item's value to see its measurements." }),
          h("h4", {}, "IPC lines"), table([{ k: "date", label: "Date" }, { k: "no", label: "IPC" }, { k: "status", label: "Status" }, { k: "qty", label: "Qty", fmt: "qty" }, { k: "rate", label: "Rate", fmt: "money" }, { k: "amount", label: "Amount", fmt: "money" }], x.ipc || [], { search: false })), [], {});
        return;
      }
      modal("Cost behind " + r.code + (ctype ? " · " + TYPES[ctype] : ""), h("div", {}, h("p", { class: "hint" }, "Total " + money(x.total)),
        table([{ k: "date", label: "Date" }, { k: "voucher_no", label: "Voucher" }, { k: "account", label: "Account" }, { k: "narration", label: "Narration" }, { k: "status", label: "Status" },
          { label: "Document", v: (l) => (l.doc ? h("a", { href: l.doc }, l.source) : l.source || "") }, { k: "amount", label: "Amount", fmt: "money" }], x.lines, { name: "cvr_cost_lines", totals: ["amount"] }),
        x.accruals.length ? h("div", {}, h("h4", {}, "Accrued"), table([{ k: "detail", label: "Detail" }, { k: "amount", label: "Amount", fmt: "money" }], x.accruals, { search: false })) : null), [], {});
    };
    const opts = [["", "Live (provisional)"]].concat(closes.rows.map((k) => [k.id, k.period_label + " · " + k.status]));
    root.append(filterBar([{ k: "close_id", label: "Figures", type: "select", options: opts, noBlank: true }, { k: "as_of", label: "Live as at", type: "date" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  /* ───────────────────────── company screens ───────────────────────── */
  PAGES["cl/board"] = async (root) => {
    await meta();
    root.append(pageHead("Close status board", "Every project, every month: open, in review, locked, reopened or overdue (seven working days after the cut-off)."));
    const d = await run("cl.board", { months: 6 });
    const tblE = h("table", { class: "clgrid" }, h("thead", {}, h("tr", {}, h("th", {}, "Project"), d.periods.map((p) => h("th", {}, p.label.replace(" 20", " ’"))))),
      h("tbody", {}, d.rows.map((r) => h("tr", {}, h("td", {}, h("b", {}, r.code), " ", r.name, r.pilot ? " " : "", r.pilot ? chip("review", "pilot") : null),
        r.cells.map((c) => h("td", {}, c.status === "before" ? chip("before", "—") : h("a", { href: c.close_id ? "#/cl/close?id=" + c.close_id : "javascript:void 0", onclick: () => { if (!c.close_id) { setProject(r.project_id); location.hash = "#/cl/close"; } } }, chip(c.status))))))));
    root.append(h("div", { class: "tablewrap" }, tblE));
    root.append(h("p", { class: "hint" }, "— means the month is before cost coding started on that project."));
  };

  PAGES["cl/cvrall"] = async (root) => {
    await meta();
    root.append(pageHead("CVR, all projects", "Live (provisional) figures for every project, with its last locked close."));
    const d = await run("cl.cvr_all", {});
    root.append(table([{ k: "code", label: "Project" }, { k: "name", label: "Name" }, { k: "value", label: "Value earned", fmt: "money" }, { k: "cost", label: "Cost to date", fmt: "money" },
      { label: "Margin", v: (r) => (r.margin == null ? "—" : sign(r.margin)) }, { label: "CPI", v: (r) => n2(r.cpi) }, { k: "eac", label: "EAC", fmt: "money" },
      { label: "Forecast margin", v: (r) => (r.forecast_margin == null ? "—" : sign(r.forecast_margin)) }, { label: "Forecast %", v: (r) => pct(r.forecast_margin_pct) }, { label: "Bid %", v: (r) => pct(r.bid_margin_pct) },
      { label: "Unallocated", v: (r) => pct(r.unallocated_pct) }, { k: "worst_flag", label: "Worst flag" }, { k: "locked_period", label: "Last locked" }],
    d.rows, { name: "cvr_all_projects", totals: ["value", "cost", "eac"], onRow: (r) => { setProject(r.project_id); location.hash = "#/cl/cvr?project_id=" + r.project_id; } }));
  };

  PAGES["cl/accruals"] = async (root) => {
    await meta();
    root.append(pageHead("Accruals register", "Every locked close's accruals, by project and month, with the journals when the company posts them."));
    let filt = { period: "" };
    const holder = h("div");
    const load = async () => {
      const d = await run("cl.accruals", { period: filt.period || null });
      holder.innerHTML = "";
      holder.append(note(d.posting ? "Cost accruals are posted as reversing journals through the posting queue." : "Accruals are a management snapshot only; the statutory books are untouched (Control settings to change)."));
      holder.append(table([{ k: "period_label", label: "Month" }, { k: "project", label: "Project" }, { k: "label", label: "Accrual" }, { k: "cost_code", label: "Code" }, { k: "detail", label: "Detail" },
        { k: "amount", label: "Amount", fmt: "money" }, { label: "Journal", v: (r) => (r.voucher_id ? (r.voucher_no || "waiting") + (r.reversal_no ? " / " + r.reversal_no : "") : "") }], d.rows, { name: "accruals_register", totals: ["amount"], empty: "No locked close yet." }));
      if (!filt.periods) { filt.periods = d.periods; }
    };
    const d0 = await run("cl.accruals", {});
    root.append(filterBar([{ k: "period", label: "Month", type: "select", options: d0.periods.map((p) => [p.period, p.label]), blank: "All months" }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  PAGES["cl/equipment"] = async (root) => {
    await meta();
    root.append(pageHead("Equipment business", "Each owned machine as a small business: hours, utilisation, fuel against norm, what it charged against what it cost, idle cost by responsibility, EMI and break-even."));
    let filt = { period: META.period };
    const holder = h("div");
    const load = async () => {
      const d = await run("cl.eq", { period: filt.period });
      holder.innerHTML = "";
      const t = d.total;
      holder.append(h("div", { class: "clt" }, tile(n1(t.working_hrs) + " h", "Working hours", "", "Utilisation " + pct(t.utilisation_pct)), tile(money(t.charged), "Charged to projects", ""), tile(money(t.actual_cost), "Actual cost (economic)", ""),
        tile(money(t.recovery), "Over / under recovery", t.recovery < 0 ? "bad" : "good"), tile(money(t.idle_cost_employer), "Idle cost, employer (claimable)", t.idle_cost_employer > 0 ? "warn" : "grey"),
        tile(money(t.emi_due), "EMI due this month", "")));
      holder.append(table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "working_hrs", label: "Working h", fmt: "qty" }, { k: "available_hrs", label: "Available h", fmt: "qty" },
        { label: "Utilisation", v: (r) => pct(r.utilisation_pct) }, { label: "Availability", v: (r) => pct(r.availability_pct) },
        { label: "Fuel vs norm", v: (r) => (r.fuel_var_pct == null ? "—" : h("span", { class: r.fuel_var_pct > (META.settings.cl_fuel_var || 15) ? "clr" : "" }, (r.fuel_var_pct > 0 ? "+" : "") + pct(r.fuel_var_pct))) },
        { k: "charged", label: "Charged", fmt: "money" }, { k: "actual_cost", label: "Actual cost", fmt: "money" }, { label: "Recovery", v: (r) => sign(r.recovery) },
        { label: "Idle E / C / N h", v: (r) => n1(r.idle_employer) + " / " + n1(r.idle_contractor) + " / " + n1(r.idle_neutral) },
        { k: "emi_due", label: "EMI due", fmt: "money" }, { label: "Own vs hire / h", v: (r) => (r.own_vs_hire == null ? "—" : money(r.own_vs_hire)) },
        { label: "Flags", v: (r) => (r.flags.length ? h("span", { title: r.flags.map((f) => f.text).join("\n") }, chip("red", r.flags.length + " flag")) : "") }],
      d.rows, { name: "equipment_business", totals: ["working_hrs", "charged", "actual_cost", "emi_due"], onRow: (r) => eqDetail(r.equipment_id), empty: "No owned machines." }));
      const fl = d.rows.flatMap((r) => r.flags.map((f) => r.code + ": " + f.text));
      if (fl.length) holder.append(h("div", { class: "clnote warn" }, h("b", {}, "Flags"), h("ul", { class: "clflags" }, fl.map((x) => h("li", {}, x)))));
      holder.append(h("p", { class: "hint" }, "Available hours come from the working calendar (shifts, holidays) less planned maintenance. Recovery = hours charged × rate − actual cost (operating, depreciation, loan interest). Idle hours are valued at the standby rate (ownership cost only). Costing switch: " + (d.mode === "rate" ? "projects carry own machines at rate per hour." : "projects carry actual running costs.")));
    };
    const eqDetail = async (id) => {
      const d = await run("cl.eq_detail", { equipment_id: id, period: filt.period });
      const p = d.params;
      const f = form([{ k: "planned_hours_year", label: "Planned working hours a year", type: "number" }, { k: "fuel_norm", label: "Fuel norm (litres per working hour)", type: "number" },
        { k: "standby_rate", label: "Standby rate per hour", type: "number" }, { k: "market_hire_rate", label: "Market hire rate per hour", type: "number" },
        { k: "loan_id", label: "Loan", type: "select", options: d.loans.map((l) => [l.id, l.name + (l.lender ? " · " + l.lender : "")]) }],
      { planned_hours_year: p.planned_hours_year, fuel_norm: p.fuel_norm, standby_rate: p.standby_rate, market_hire_rate: p.market_hire_rate, loan_id: p.loan_id });
      const be = d.break_even || {};
      const labels = d.months.map((m) => periodLabel(m.period).replace(" 20", " ’"));
      modal(d.equipment.code + " · " + d.equipment.name, h("div", {},
        h("div", { class: "clt" }, tile(be.break_even_hours == null ? "—" : m0(be.break_even_hours) + " h", "Break-even hours a year", be.hours_year != null && be.break_even_hours != null && be.hours_year < be.break_even_hours ? "bad" : "good", "Working " + m0(be.hours_year) + " h a year"),
          tile(money(be.fixed_annual), "Fixed cost a year", "", "Depreciation + interest"), tile(money(be.running_per_hour), "Running cost per hour", "", "Market rate " + money(be.market_rate))),
        lineChart(labels, [{ name: "Charged", color: "#2f7a4d", values: d.months.map((m) => m.charged) }, { name: "Actual cost", color: "#c0392b", values: d.months.map((m) => m.actual_cost) }], { height: 180 }),
        d.flags.length ? h("ul", { class: "clflags" }, d.flags.map((x) => h("li", {}, x.text))) : null,
        table([{ label: "Month", v: (m) => periodLabel(m.period) }, { k: "working_hrs", label: "Working h", fmt: "qty" }, { label: "Util.", v: (m) => pct(m.utilisation_pct) }, { k: "fuel_litres", label: "Fuel l", fmt: "qty" },
          { label: "Fuel vs norm", v: (m) => pct(m.fuel_var_pct) }, { k: "charged", label: "Charged", fmt: "money" }, { k: "actual_cost", label: "Cost", fmt: "money" }, { k: "recovery", label: "Recovery", fmt: "money" }, { k: "emi_due", label: "EMI", fmt: "money" }],
        d.months.slice().reverse(), { search: false, name: "machine_months" }),
        h("h4", {}, "Register additions"), f),
      [{ label: "Save", cls: "primary", act: async () => { await run("cl.eq_params_save", Object.assign({ equipment_id: id }, f.values()), "Saved"); load(); } }], {});
    };
    root.append(filterBar([{ k: "period", label: "Month", type: "select", noBlank: true, options: Array.from({ length: 12 }, (_, i) => { const p = shiftP(META.period, -i); return [p, periodLabel(p)]; }) }], filt, (v) => { filt = v; load(); }));
    root.append(holder);
    await load();
  };

  async function leagueTable(box) {
    const d = await run("cl.league", {});
    box.append(table([{ label: "Project", v: (r) => h("div", { style: "min-width:180px" }, h("b", {}, r.code), h("div", { class: "clsub" }, r.name)) }, { k: "value", label: "Value earned", fmt: "money" }, { k: "cost", label: "Cost", fmt: "money" },
      { label: "Margin to date", v: (r) => sign(r.margin) }, { label: "Forecast margin", v: (r) => (r.forecast_margin == null ? "—" : h("span", {}, sign(r.forecast_margin), " ", h("span", { class: "clsub" }, pct(r.forecast_margin_pct)))) },
      { label: "CPI", v: (r) => n2(r.cpi) }, { label: "Unbilled days", v: (r) => m0(r.unbilled_days) }, { label: "Debtor days", v: (r) => m0(r.debtor_days) },
      { label: "Cash position", v: (r) => sign(r.cash) }, { label: "Worst flag", v: (r) => h("div", { style: "min-width:260px" }, r.worst_flag || "") }],
    d.rows, { name: "project_league", totals: ["value", "cost"], onRow: (r) => { setProject(r.project_id); location.hash = "#/cl/cvr?project_id=" + r.project_id; } }));
    box.append(h("p", { class: "hint" }, "Sorted worst first. Trading and company cost centres are not projects and do not appear. Cash position = receipts − payments to date on the project."));
    return box;
  }

  PAGES["cl/health"] = async (root) => {
    await meta();
    root.append(pageHead("Company health", "About twenty measures in five groups, each green, amber or red against the company's thresholds, built from the locked closes and the ledger.",
      META.rights.post ? h("button", { class: "btn", onclick: async () => { await run("cl.health_publish", {}, (x) => "Published " + x.label); location.reload(); } }, "Publish last month") : null,
      META.rights.post ? h("a", { class: "btn", href: "#/cl/settings" }, "Thresholds") : null));
    const now = async () => {
      const d = await run("cl.health", {});
      const box = h("div");
      box.append(h("p", { class: "clsub" }, "As at " + d.as_of + (d.published ? " · last published " + d.published : " · not published yet: trends start with the first published month")));
      const groups = [...new Set(d.measures.map((m) => m.group))];
      groups.forEach((g) => {
        box.append(h("h3", {}, g));
        box.append(h("div", { class: "clhg" }, d.measures.filter((m) => m.group === g).map((m) => {
          const v = m.value == null ? "—" : (m.unit === "Rs" ? money(m.value) : (m.unit === "%" ? pct(m.value) : (!m.unit && Number.isInteger(m.value) ? String(m.value) : n2(m.value) + (m.unit ? " " + m.unit : ""))));
          return h("div", { class: "t " + (ST[m.status] || ""), onclick: () => measureDialog(m) }, h("span", {}, m.label, " ", m.status !== "info" ? chip(m.status, STL[m.status]) : null), h("b", {}, v), h("small", {}, m.threshold || ""), spark((m.trend || []).map((x) => x.value)));
        })));
      });
      return box;
    };
    const measureDialog = (m) => {
      const rows = m.detail || [];
      modal(m.label, h("div", {}, h("p", {}, h("b", {}, "Formula: "), m.formula), h("p", { class: "clsub" }, "Threshold: " + (m.threshold || "—")),
        (m.trend || []).length > 1 ? lineChart(m.trend.map((x) => x.label.replace(" 20", " ’")), [{ name: m.label, color: "#1769aa", values: m.trend.map((x) => x.value) }], { height: 160 }) : null,
        rows.length ? table([{ label: "", v: (r) => r.code || "" }, { label: "Name", v: (r) => (r.link ? h("a", { href: r.link }, r.name || "") : (r.name || "")) },
          { label: "Value", v: (r) => (typeof r.value === "number" ? (m.unit === "%" ? pct(r.value) : money(r.value)) : (r.value || "")) },
          { label: "", v: (r) => [r.expiry || r.release || r.due || "", r.overdue || r.short ? " ⚠" : ""].join("") }], rows, { name: "health_" + m.key }) : null,
        m.link ? h("p", {}, h("a", { href: m.link }, "Open the screen behind this figure")) : null), [], {});
    };
    const returns = async () => {
      const box = h("div");
      const [s, ra] = await Promise.all([api("mg.segments", {}).catch(() => null), api("ret.assets", {}).catch(() => null)]);
      if (s && s.company) {
        const c = s.company;
        box.append(h("div", { class: "clt" }, tile(pct(c.roa_pct), "Return on assets (ROA)", ""), tile(pct(c.roe_pct), "Return on equity (ROE)", ""), tile(pct(c.net_margin_pct), "Net margin", "")));
      }
      if (s) box.append(h("h4", {}, "Projects"), table([{ k: "code", label: "Project" }, { k: "name", label: "Name" }, { k: "margin", label: "Margin to date", fmt: "money" }, { k: "capital_net", label: "Net capital", fmt: "money" },
        { label: "ROA", v: (r) => pct(r.roa_pct) }, { label: "ROCE", v: (r) => pct(r.roce_pct) }], s.projects || [], { name: "project_returns", search: false }));
      if (ra && (ra.rows || ra.machines)) box.append(h("h4", {}, "Machines"), table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { label: "Return", v: (r) => pct(r.roa_pct != null ? r.roa_pct : r.return_pct) }],
        ra.rows || ra.machines, { name: "machine_returns", search: false }));
      if (!s && !ra) box.append(note("Returns are in Accounts › Returns (ROA / ROE)."));
      return box;
    };
    root.append(tabs([["Company now", now], ["Project league", () => leagueTable(h("div"))], ["Returns", returns]]));
  };

  PAGES["cl/league"] = async (root) => {
    await meta();
    root.append(pageHead("Project league", "One row per project, worst first: value, cost, margin, forecast, CPI, unbilled and debtor days, cash position and its worst flag."));
    await leagueTable(root);
  };

  PAGES["cl/settings"] = async (root) => {
    await meta(true);
    root.append(pageHead("Control settings", "Cut-off day, accrual posting, the cost-to-complete rule, unallocated limits and every threshold of the CVR, equipment, close and company health."));
    const s = META.settings;
    const f = form([{ k: "cl_cutoff", label: "Cut-off", type: "select", noBlank: true, options: [["end", "Last day of each Nepali month"]].concat(Array.from({ length: 29 }, (_, i) => [String(i + 1), "Day " + (i + 1) + " of the Nepali month"])) },
      { k: "cl_accrual_post", label: "Post cost accruals as reversing journals (through the posting queue)", type: "check" },
      { k: "cl_ctc_rule", label: "Cost to complete", type: "select", noBlank: true, options: [["actual_after", "Actual unit cost once the item is X% done, budget before"], ["budget", "Always the budget unit cost"], ["pm", "PM's figure (budget where none)"]] },
      { k: "cl_ctc_pct", label: "X% done", type: "number" }, { k: "cl_spread", label: "Site overhead in item margins", type: "select", noBlank: true, options: [["both", "Own line and spread by value in a second column"], ["never", "Own line only"]] },
      { k: "cl_unalloc_target", label: "Unallocated target %", type: "number" }, { k: "cl_unalloc_block", label: "Unallocated blocks the close at %", type: "number" },
      { k: "cl_flag_cpi", label: "Flag item CPI below", type: "number" }, { k: "cl_flag_done_pct", label: "Flag negative margin on items more than % done", type: "number" },
      { k: "cl_flag_margin_drop", label: "Flag forecast margin below bid by points", type: "number" }, { k: "cl_flag_billing_months", label: "Flag value ahead of IPCs by months of billing", type: "number" },
      { k: "cl_fuel_var", label: "Fuel above norm flag %", type: "number" }, { k: "cl_util_low", label: "Utilisation low %", type: "number" }, { k: "cl_util_months", label: "for months running", type: "number" },
      { k: "cl_under_rec", label: "Under-recovery flag % of machine cost", type: "number" }, { k: "cl_sc_tol", label: "Subcontract ahead of measurement tolerance %", type: "number" },
      { k: "cl_sc_adv_billed", label: "Advance still out when work order billed %", type: "number" }, { k: "cl_chk4_tol", label: "Machine hours tolerance % (check 4)", type: "number" },
      { k: "cl_chk12_over", label: "Overrun above contract % (check 12)", type: "number" }, { k: "cl_bg_limit", label: "Bank guarantee limits (empty = from loans with a limit)", type: "number" },
      { k: "cl_od_limit", label: "Overdraft limit (empty = from loans with a limit)", type: "number" }], Object.assign({}, s, { cl_accrual_post: s.cl_accrual_post === "1" ? 1 : 0 }));
    const T = META.thresholds;
    const TL = { margin_amber: "Forecast margin amber: points below bid", margin_red: "Forecast margin red: points below bid", overhead_green: "Overhead ratio green up to %",
      overhead_red: "Overhead ratio red above %", pool_red: "Equipment pool red below % of pool cost", months_green: "Months of work green from", months_red: "Months of work red below",
      unbilled_green: "Unbilled days green up to", unbilled_red: "Unbilled days red above", debtor_green: "Debtor days green up to", debtor_red: "Debtor days red above",
      supplier_lo: "Supplier days green from", supplier_hi: "Supplier days green up to", supplier_red: "Supplier days red above", current_green: "Current ratio green from",
      current_red: "Current ratio red below", bg_green: "Guarantee limit used green up to %", bg_red: "Guarantee limit used red above %", de_green: "Debt to equity green up to",
      de_red: "Debt to equity red above", dscr_green: "Debt service cover green from", dscr_red: "Debt service cover red below", trading_plan_pct: "Trading margin plan %" };
    const tf = form(Object.keys(T).map((k) => ({ k, label: TL[k] || k.replace(/_/g, " "), type: "number" })), T);
    root.append(h("h3", {}, "Close, CVR and equipment"), f, h("h3", {}, "Company health thresholds"), tf,
      META.rights.post ? h("div", { class: "bar" }, h("button", { class: "btn primary", onclick: async () => { const v = f.values(); await run("cl.settings_save", { settings: v, thresholds: tf.values() }, "Saved"); await meta(true); } }, "Save settings")) : note("Only the finance manager changes these settings."));
    // back-fill
    const bf = h("div");
    root.append(h("h3", {}, "Back-fill of lines posted before 2.24"), bf);
    const loadBf = async () => {
      const d = await run("cl.backfill_preview", {});
      bf.innerHTML = "";
      bf.append(h("p", {}, d.lines + " posted line(s) from before 2.24 can be coded from their documents; " + d.backfilled + " already coded by the back-fill. Amounts, accounts and vouchers never change; undo removes only the codes."),
        table([{ k: "project", label: "Project" }, { k: "label", label: "Would land on" }, { k: "lines", label: "Lines", fmt: "qty" }, { k: "amount", label: "Amount", fmt: "money" }], d.rows, { name: "backfill_preview", totals: ["amount"], search: false, empty: "Nothing to back-fill." }),
        META.rights.approve ? h("div", { class: "bar" }, h("button", { class: "btn primary", disabled: !d.lines, onclick: async () => { await run("cl.backfill_apply", {}, (x) => x.coded + " line(s) coded"); loadBf(); } }, "Apply the back-fill"),
          h("button", { class: "btn", disabled: !d.backfilled, onclick: async () => { if (await ask("Undo the back-fill", "Remove the codes the back-fill gave? The ledger is not touched.", { danger: true })) { await run("cl.backfill_undo", {}, "Removed"); loadBf(); } } }, "Undo")) : null);
    };
    await loadBf();
  };

  /* ───────────────────────── panels on existing screens ───────────────────────── */
  function after(path, fn) {
    const f = PAGES[path];
    if (typeof f !== "function" || f._bco224) return;
    const w = async (root, params) => {
      const r = await f(root, params);
      try { await fn(root, params); } catch (e) { /* a panel never breaks the screen */ }
      return r;
    };
    w._bco224 = true;
    Object.keys(f).forEach((k) => { try { w[k] = f[k]; } catch (e) { /* ignore */ } });
    PAGES[path] = w;
  }
  function installPanels() {
    after("p/variations", async (root) => {
      const pid = pidNow();
      if (!pid) return;
      const d = await api("cl.idle_claims", { project_id: pid });
      const box = h("div", { class: "clcard", style: "margin-top:16px" }, h("h4", {}, "Delay cost and idle claims (2.24)"));
      box.append(h("div", { class: "clt" }, tile(money(d.amount.employer), "Employer-caused idle (claimable)", d.amount.employer > 0 ? "warn" : "grey", n1(d.hours.employer) + " h at the standby rate"),
        tile(money(d.amount.contractor), "Contractor-caused idle (borne)", "grey", n1(d.hours.contractor) + " h"), tile(money(d.amount.neutral), "Neutral (weather, force majeure)", "grey", n1(d.hours.neutral) + " h · check the EOT clause")));
      const emp = d.rows.filter((r) => r.resp === "employer");
      if (emp.length) box.append(table([{ k: "date", label: "Date" }, { k: "equipment", label: "Machine" }, { k: "hours", label: "Idle h", fmt: "qty" }, { k: "standby_rate", label: "Standby rate", fmt: "money" }, { k: "cost", label: "Claimable", fmt: "money" },
        { k: "delay", label: "Delay" }, { k: "dpr_no", label: "DPR" }, { label: "Event", v: (r) => (r.event_id ? h("a", { href: "#/p/events?id=" + r.event_id }, "Open") : "") }], emp, { name: "idle_claims", totals: ["cost"] }));
      box.append(h("p", { class: "hint" }, d.note));
      root.append(box);
    });
    after("x/sub", async (root) => {
      const pid = pidNow();
      if (!pid) return;
      const d = await api("cl.subcon", { project_id: pid });
      if (!d.rows.length) return;
      const FL = { paid_ahead: "Billed ahead of main measurement", margin_below_plan: "Back-to-back margin below plan", material_with_sub: "Material left with subcontractor", advance_outstanding: "Advance still out" };
      root.append(h("div", { class: "clcard", style: "margin-top:16px" }, h("h4", {}, "Checks against the main contract (2.24)"),
        d.unmapped ? note(d.unmapped + " work-order line(s) have no main BOQ item: map each line to the BOQ item it builds.", "warn") : null,
        table([{ k: "order_no", label: "Work order" }, { k: "party", label: "Subcontractor" }, { k: "description", label: "Line" }, { k: "boq_code", label: "Main item" }, { k: "billed_qty", label: "Billed", fmt: "qty" },
          { k: "main_measured", label: "Main measured", fmt: "qty" }, { k: "b2b_margin", label: "B2B margin", fmt: "money" }, { k: "planned_margin", label: "Planned", fmt: "money" },
          { k: "material_with_sub", label: "Material with sub", fmt: "money" }, { k: "advance_outstanding", label: "Advance out", fmt: "money" },
          { label: "Flags", v: (r) => r.flags.map((f) => chip("red", FL[f] || f)) }], d.rows, { name: "subcontract_checks" })));
    });
    after("inv/recon", async (root) => {
      const pid = pidNow();
      if (!pid) return;
      const d = await api("cl.material", { project_id: pid });
      if (!d.rows.length) return;
      root.append(h("div", { class: "clcard", style: "margin-top:16px" }, h("h4", {}, "Wastage in rupees (2.24)"),
        h("div", { class: "clt" }, tile(money(d.excess_value), "Excess wastage value", d.excess_value > 0 ? "bad" : "good", "Carried into the CVR"), tile(money(d.in_place_value), "Material in place, not yet measured", "grey", "Shown, not a loss"),
          tile(d.under_use, "Lines using less than theoretical", d.under_use ? "warn" : "good", "Short measurement or wrong coefficient?")),
        table([{ k: "boq_code", label: "Item" }, { k: "mat_name", label: "Material" }, { k: "unit", label: "Unit" }, { k: "theoretical", label: "Theoretical", fmt: "qty" }, { k: "allowed", label: "Allowed wastage", fmt: "qty" },
          { k: "issued_net", label: "Issued net", fmt: "qty" }, { k: "by_subcontractor", label: "By subcontractors", fmt: "qty" }, { k: "actual", label: "Actual", fmt: "qty" },
          { k: "in_place", label: "In place", fmt: "qty" }, { k: "excess", label: "Excess", fmt: "qty" }, { k: "excess_value", label: "Excess value", fmt: "money" },
          { label: "", v: (r) => (r.under_use ? chip("amber", "under") : "") }], d.rows, { name: "wastage_value", totals: ["excess_value"] })));
    });
    after("ws/project", async (root) => {
      const pid = pidNow();
      if (!pid) return;
      const c = await api("cl.health_card", { project_id: pid });
      if (!c) return;
      const box = h("div", { class: "clcard", style: "margin:12px 0" }, h("h4", {}, "Project health"),
        h("div", { class: "clt", style: "margin:0" }, tile(money(c.margin), "Margin to date", c.margin < 0 ? "bad" : "good", pct(c.margin_pct), () => { location.hash = "#/cl/cvr"; }),
          tile(money(c.forecast_margin), "Forecast margin", c.forecast_margin < 0 ? "bad" : "good", pct(c.forecast_margin_pct)), tile(c.cpi == null ? "—" : n2(c.cpi), "CPI", c.cpi != null && c.cpi < 0.95 ? "bad" : "good"),
          tile(m0(c.unbilled_days), "Unbilled days", c.unbilled_days > 60 ? "bad" : (c.unbilled_days > 30 ? "warn" : "good")), tile(c.last_close_label || "—", "Last close", c.last_close ? "good" : "warn", c.last_close || "No month locked yet", () => { location.hash = "#/cl/close"; }),
          tile(c.worst_flag ? "!" : "✓", c.worst_flag || "No open flag", c.worst_flag ? "bad" : "good")));
      const first = root.querySelector(".clt, .grid, table, .panel");
      if (first && first.parentNode === root) root.insertBefore(box, first); else root.append(box);
    });
    after("p/dpr", async (root) => {
      const pid = pidNow();
      if (!pid) return;
      const q = await api("cl.queue", { project_id: pid });
      const dprs = {};
      q.rows.filter((r) => r.doc === "dpr").forEach((r) => { (dprs[r.doc_id] = dprs[r.doc_id] || { r, n: 0 }).n++; });
      const list = Object.values(dprs);
      if (!list.length) return;
      root.append(h("div", { class: "clcard", style: "margin-top:16px" }, h("h4", {}, "Hours to link before submitting (2.24)"),
        table([{ label: "DPR", v: (x) => x.r.no }, { label: "Date", v: (x) => x.r.date }, { label: "Lines", v: (x) => x.n },
          { label: "", v: (x) => h("button", { class: "btn small primary", onclick: (e) => { e.stopPropagation(); dprCoding(x.r.doc_id, () => go()); } }, "Link hours") }], list, { search: false, export: false })));
    });
  }

  /* ───────────────── company-only screens stay out of the Project Workspace ───────────────── */
  const CO_ONLY = ["cl/health", "cl/league", "cl/board", "cl/cvrall", "cl/accruals", "cl/equipment", "cl/settings"];
  const projWs = () => !!(S.user && S.user.workspace && S.user.workspace.active === "project");
  CO_ONLY.forEach((p) => {
    const f = PAGES[p];
    PAGES[p] = async (root, params) => {
      if (projWs()) {
        root.append(pageHead("Company screen"), h("div", { class: "panel" }, h("b", {}, "This screen belongs to the Company Workspace."),
          h("p", { class: "muted" }, "It shows the whole company. Switch to the Company Workspace to open it.")));
        return;
      }
      return f(root, params);
    };
  });
  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    installPanels();
    if (typeof window.renderNav === "function" && !window.renderNav._bco224) {
      const orig = window.renderNav;
      const rn = function () {
        try {
          if (projWs() && typeof MENU !== "undefined") MENU.forEach((g) => { g[2] = g[2].filter((it) => !CO_ONLY.includes(it[0])); });
        } catch (e) { /* ignore */ }
        return orig.apply(this, arguments);
      };
      Object.keys(orig).forEach((k) => { try { rn[k] = orig[k]; } catch (e) { /* ignore */ } });
      rn._bco224 = true;
      window.renderNav = rn;
      try { renderNav = rn; } catch (e) { /* ignore */ } // eslint-disable-line no-global-assign
    }
  });
  // in case the boot hooks already ran (script loaded late)
  setTimeout(installPanels, 0);

  /* What's new */
  function whatsNew() {
    if (LSg("bco_seen_" + VER, "")) return;
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    LSs("bco_seen_" + VER, "1");
    const li = (b, t) => h("li", {}, h("b", {}, b), " ", t);
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("p", {}, "Engineering and accounts now meet on the same figures, item by item, every month."),
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        li("Cost codes (Commercial).", "Every BOQ item plus preliminaries, site overhead, temporary works, idle by responsibility, defects and unallocated. Each cost lands on a code from its DPR, logsheet, issue, bill or work order."),
        li("Control budget.", "Imported from the bid's rate analysis; Original locked at award, Current with variations, Forecast from each close."),
        li("Project close and CVR.", "A monthly checklist, accruals, twelve integrity checks, four signatures and a locked snapshot; value against cost per item with the forecast to complete."),
        li("Equipment business, wastage in rupees, subcontract checks.", "Each machine's month, flags and break-even; excess wastage value; subcontract quantities against the main measurement."),
        li("Company health and project league.", "Profitability, order book, cash cycle, liquidity, guarantees, debt and compliance, green to red.")),
      h("p", { class: "hint" }, "No entry, account or balance changed. Coding is required on each project from the first day of next Nepali month; earlier lines can be coded with the back-fill in Control settings.")),
    [{ label: "Open Cost codes", cls: "primary", act: () => { location.hash = "#/cl/codes"; } }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 4600); } }, 900);
})();
