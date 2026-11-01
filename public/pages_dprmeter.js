/* BuildCore 2.35: DPR machine lines fill themselves.
   Opening = the machine's last closing reading (DPR before this date and shift), operator from the equipment list,
   working hours = closing − opening as you type, and when closing equals opening (or a listed machine has no closing
   reading) the user picks Idle or Breakdown and the standard day (Settings › Scheduled hours per day (equipment))
   goes into that column. Used by the smart DPR form (pages_udpr.js) and the classic form (pages_sched.js). */
(function () {
  const blank = (v) => v == null || v === "" || (typeof v === "number" && isNaN(v));
  const numv = (v) => (blank(v) ? null : Number(v));
  const r2 = (x) => Math.round(x * 100) / 100;

  function create(o) {
    o = o || {};
    const st = { machines: {}, day: 10, editor: null, cols: null, hf: null, key: "" };
    const mach = (id) => st.machines[String(id)] || null;
    const colIx = (k) => (st.cols || []).findIndex((c) => c.k === k);
    const setCell = (tr, k, v) => {
      const i = colIx(k);
      if (!tr || i < 0) return;
      const inp = tr.children[i] && tr.children[i].querySelector("input");
      if (inp) inp.value = v == null ? "" : v;
    };
    const isHours = (r) => { const m = mach(r.equipment_id); return !m || (m.meter_type || "hours") === "hours"; };
    const hoursOf = (r) => {
      const s = numv(r.meter_start), e = numv(r.meter_end);
      return s != null && e != null && e >= s ? r2(e - s) : null;
    };
    const zero = (r) => !(Number(r.hours) > 0) && !(Number(r.idle_hours) > 0) && !(Number(r.breakdown_hours) > 0);
    const same = (r) => numv(r.meter_end) != null && numv(r.meter_start) != null && numv(r.meter_end) === numv(r.meter_start);
    const name = (r) => { const m = mach(r.equipment_id); if (m) return m.code + " " + m.name; const e = (S.L.equipment || []).find((x) => String(x.id) === String(r.equipment_id)); return e ? e.code + " " + e.name : "Machine"; };

    async function load(date, shift) {
      const key = (date || "") + "|" + (shift || "day");
      if (key === st.key) return false;
      st.key = key;
      try {
        const r = await api("dpr.meter_open", { project_id: S.project, date: date || today(), shift: shift || "day", dpr_id: o.dprId ? o.dprId() || 0 : 0 });
        st.machines = r.machines || {};
        st.day = Number(r.day_hours) || 10;
      } catch (e) { st.machines = {}; }
      return true;
    }

    /* a machine was picked on a line: opening and operator follow it unless typed by hand */
    function pick(r) {
      const m = mach(r.equipment_id);
      const e = (S.L.equipment || []).find((x) => String(x.id) === String(r.equipment_id));
      if (blank(r.meter_start) || r._open_auto) {
        r.meter_start = m ? (m.opening ?? "") : (e ? e.meter : "");
        r._open_auto = 1;
      }
      const op = (m && m.operator) || (e && e.operator) || "";
      if (op && (blank(r.operator) || r._op_auto)) { r.operator = op; r._op_auto = 1; }
      if (!blank(r.meter_end) && isHours(r)) { const hh = hoursOf(r); if (hh != null) r.hours = hh; }
    }

    /* a meter was typed: hours follow; the same reading asks Idle or Breakdown */
    function meters(r, tr, k) {
      if (k === "meter_start") r._open_auto = 0;
      if (isHours(r)) {
        const hh = hoursOf(r);
        if (hh != null) { r.hours = hh; setCell(tr, "hours", hh); }
        if (numv(r.meter_end) != null && numv(r.meter_start) != null && numv(r.meter_end) < numv(r.meter_start)) toast(name(r) + ": closing reading is below the opening reading.", "err");
      }
      if (k === "meter_end" && same(r) && !(Number(r.idle_hours) > 0) && !(Number(r.breakdown_hours) > 0)) {
        choose([r], false).then((ok) => { if (ok) { ["hours", "idle_hours", "breakdown_hours", "meter_end"].forEach((x) => setCell(tr, x, r[x])); if (st.editor) st.editor.refresh(); } });
      }
    }

    /* Idle or Breakdown for each line; "leave out" only for listed machines with no closing reading */
    function choose(lines, allowOut) {
      if (lines.length === 1 && !allowOut) return chooseOne(lines[0]);
      return new Promise((resolve) => {
        let done = false;
        const pre = (r) => { const m = mach(r.equipment_id); const s = (m && m.status) || ""; return s === "breakdown" || s === "under_maintenance" ? "breakdown" : (s === "idle" || s === "standby") ? "idle" : ""; };
        const sels = lines.map((r) => {
          const opts = [["", "— choose —"], ["idle", "Idle (" + st.day + " h)"], ["breakdown", "Breakdown (" + st.day + " h)"]];
          if (allowOut && numv(r.meter_end) == null) opts.push(["out", "Not working here today: leave it out"]);
          const v0 = pre(r);
          return h("select", {}, opts.map(([v, l]) => h("option", { value: v, selected: v === v0 }, l)));
        });
        const all = (v) => sels.forEach((s) => { if ([...s.options].some((x) => x.value === v)) s.value = v; });
        const rows = lines.map((r, i) => h("tr", {}, h("td", {}, name(r)), h("td", { class: "num" }, blank(r.meter_start) ? "" : fmtQty(r.meter_start)),
          h("td", { class: "num" }, numv(r.meter_end) == null ? "no reading" : fmtQty(r.meter_end)), h("td", {}, sels[i])));
        const body = h("div", {},
          h("p", {}, "These machines show no working hours. Choose Idle or Breakdown for each; " + st.day + " hours go into that column."),
          lines.length > 1 ? h("div", { class: "bar" }, h("button", { class: "btn small", type: "button", onclick: () => all("idle") }, "All idle"),
            h("button", { class: "btn small", type: "button", onclick: () => all("breakdown") }, "All breakdown"),
            allowOut ? h("button", { class: "btn small", type: "button", onclick: () => all("out") }, "Leave out all with no reading") : null) : null,
          h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Machine"), h("th", { class: "num" }, "Opening"), h("th", { class: "num" }, "Closing"), h("th", {}, "Today"))), h("tbody", {}, rows))),
          h("p", { class: "hint" }, "The standard day is set in Settings › Scheduled hours per day (equipment)."));
        modal("Machines without working hours", body, [{ label: "OK", cls: "primary", act: () => {
          if (sels.some((s) => !s.value)) { toast("Choose Idle or Breakdown for every machine.", "err"); throw new Error("x"); }
          const out = [];
          lines.forEach((r, i) => {
            const v = sels[i].value;
            if (v === "out") { out.push(r); return; }
            setDay(r, v);
          });
          if (out.length && st.editor) st.editor.setLines(st.editor.lines().filter((x) => !out.includes(x)));
          done = true;
          resolve(true);
        } }], { onClose: () => { if (!done) resolve(false); } });
      });
    }

    function setDay(r, v) {
      r.hours = 0;
      r.idle_hours = v === "idle" ? st.day : 0;
      r.breakdown_hours = v === "breakdown" ? st.day : 0;
      if (numv(r.meter_end) == null && numv(r.meter_start) != null) r.meter_end = r.meter_start;
    }

    /* one line whose closing equals its opening: two buttons, Idle or Breakdown */
    function chooseOne(r) {
      return new Promise((resolve) => {
        let done = false;
        const pick_ = (v) => () => { setDay(r, v); done = true; resolve(true); };
        modal(name(r) + ": idle or breakdown?", h("div", {},
          h("p", {}, "The closing reading (" + fmtQty(r.meter_end) + ") is the same as the opening reading, so the machine did not work today. Was it idle or under breakdown? " + st.day + " hours go into that column."),
          h("p", { class: "hint" }, "The standard day is set in Settings › Scheduled hours per day (equipment).")),
        [{ label: "Idle (" + st.day + " h)", cls: "primary", act: pick_("idle") }, { label: "Breakdown (" + st.day + " h)", cls: "warn", act: pick_("breakdown") }],
        { narrow: true, onClose: () => { if (!done) resolve(false); } });
      });
    }

    /* before saving: every machine line has hours, idle or breakdown, or is left out */
    async function resolve() {
      if (!st.editor) return true;
      const ls = st.editor.lines();
      ls.forEach((r) => { if (r.equipment_id && isHours(r)) { const hh = hoursOf(r); if (hh != null) r.hours = hh; } });
      const pending = ls.filter((r) => r.equipment_id && zero(r) && (numv(r.meter_end) == null || same(r)));
      if (!pending.length) return true;
      const ok = await choose(pending, true);
      if (ok) st.editor.rebuild();
      return ok;
    }

    /* fill openings and operators of lines that have none (a new DPR is filled by dpr.prefill; a draft keeps what it has) */
    function fill(isNew) {
      if (!st.editor) return false;
      let changed = false;
      st.editor.lines().forEach((r) => {
        if (!r.equipment_id || !blank(r.meter_end)) return;
        const m = mach(r.equipment_id);
        if (!m) return;
        const auto = blank(r.meter_start) || r._open_auto || isNew;
        if (auto) r._open_auto = 1;
        if (auto && m.opening != null && String(r.meter_start) !== String(m.opening)) { r.meter_start = m.opening; changed = true; }
        if (blank(r.operator) && m.operator) { r.operator = m.operator; r._op_auto = 1; changed = true; }
      });
      if (changed) st.editor.rebuild();
      return changed;
    }

    function attach(editor, cols, hf, a) {
      a = a || {};
      st.editor = editor; st.cols = cols; st.hf = hf;
      if (!a.editable) return;
      const hv = () => (hf && hf.values ? hf.values() : {});
      load(hv().date || a.date, hv().shift || a.shift).then(() => fill(a.isNew));
      if (hf) hf.addEventListener("change", (e) => {
        const n = e.target && e.target.name;
        if (n && n !== "date" && n !== "shift") return;
        load(hv().date, hv().shift).then((moved) => { if (moved) fill(false); });
      });
    }

    return { load, pick, meters, resolve, attach, choose, state: st };
  }

  const HINT = "Opening = each machine's last closing reading (previous DPR); operator from the equipment list; working hours = closing − opening. Same reading as the opening: you are asked Idle or Breakdown.";
  window.bcoDprMeter = { create, HINT };
})();
