/* BuildCore 2.38.0 "Books agree" - screens.
 *
 *   Administration › Settings ........... tab "Books agree": the four switches, each with its before and after figures
 *   Fixed assets › Depreciation run ...... tab "Check": machine-months depreciated twice, proposed reversals, history
 *   Equipment › Depreciation & hire ...... depreciation read-only when Fixed assets is the official route
 *
 * No menu item is added, renamed or moved.
 */
(function () {
  "use strict";
  const panel = (...k) => h("div", { class: "panel" }, ...k);
  const hint = (t) => h("p", { class: "hint" }, t);

  /* ── Administration › Settings › Books agree ── */
  async function switchesTab() {
    const d = await api("agree.switches", { detail: true });
    const box = h("div", {}, hint("Each switch corrects how a figure is posted. On a company that was updated, a switch stays off until an accounts approver confirms it here. Old postings never change; only new ones follow the switch."));
    for (const s of d.switches) {
      const im = s.impact || { rows: [] };
      const btn = can("accounts", "approve") ? h("button", { class: "btn " + (s.on ? "" : "primary"), onclick: async () => {
        if (!s.on && !(await ask("Switch on: " + s.label, "Confirm that you have checked the before and after figures shown. Only new postings change.", { ok: "Confirm and switch on" }))) return;
        await run("agree.switch_set", { key: s.key, on: !s.on }, s.on ? "Switched off" : "Switched on"); go();
      } }, s.on ? "Switch off" : "Confirm and switch on") : null;
      box.append(panel(h("h3", {}, s.label, " ", stamp(s.on ? "on" : "off")), h("p", {}, s.text),
        s.on && s.confirmed_by ? hint("Confirmed by " + s.confirmed_by + ".") : null,
        im.label ? h("h4", {}, im.label) : null,
        im.rows.length ? table([{ k: "item", label: "Item" }, { k: "before", label: "Before", fmt: "money" }, { k: "after", label: "After", fmt: "money" }, { k: "note", label: "Note" }],
          im.rows, { name: "agree_" + s.key, search: false, totals: ["before", "after"] }) : hint("Nothing in the current data is affected."),
        btn ? h("div", { class: "actions" }, btn) : null));
    }
    return box;
  }

  /* ── Fixed assets › Depreciation run › Check ── */
  async function checkTab() {
    const [d, hist] = await Promise.all([api("agree.dup_dep", {}), api("agree.history_preview", {})]);
    const box = h("div");
    box.append(panel(h("h3", {}, "Depreciated twice"),
      hint("Machines and months depreciated by both Equipment › Depreciation and Fixed assets. A proposed reversal takes back the Equipment posting; it waits in Accounts › Posting queue and changes nothing until an accounts approver posts it."),
      table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "month", label: "Month" },
        { k: "amount", label: "Equipment route", fmt: "money" }, { k: "voucher_no", label: "Voucher" },
        { k: "fa_amount", label: "Fixed assets route", fmt: "money" }, { label: "Vouchers", v: (r) => (r.fa_vouchers || []).filter(Boolean).join(", ") },
        { label: "Reversal", v: (r) => r.fix ? h("span", {}, stamp(r.fix.status), " ", r.fix.voucher_no || "in the queue") :
          (can("accounts", "edit") ? h("button", { class: "btn small primary", onclick: async (e) => { e.stopPropagation(); await run("agree.dup_propose", { dep_run_id: r.dep_run_id }, "Reversal proposed; it is in Accounts › Posting queue"); go(); } }, "Propose reversal") : "") }],
      d.rows, { name: "agree_dups", search: false, totals: ["amount", "fa_amount"], empty: "No machine and month is depreciated twice." })));
    const sel = new Set();
    box.append(panel(h("h3", {}, "Bring history across"),
      hint("Machines already in the Fixed assets register with no depreciation, although the equipment register has some. Bringing the history across copies the accumulated depreciation into the register. No voucher is posted: the ledger already holds this depreciation."),
      table([{ label: "", v: (r) => h("input", { type: "checkbox", onchange: (e) => { if (e.target.checked) sel.add(r.fa_id); else sel.delete(r.fa_id); } }) },
        { k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "accumulated", label: "Fixed assets now", fmt: "money" },
        { k: "after", label: "After (equipment register)", fmt: "money" }, { k: "dep_runs_total", label: "Equipment runs", fmt: "money" }, { k: "ledger", label: "Ledger 1502 for this machine", fmt: "money" }],
      hist, { name: "agree_history", search: false, empty: "Every machine already carries its history." }),
      hist.length && can("assets", "approve") ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        if (!sel.size) return toast("Tick the machines first.", "err");
        await run("agree.history_apply", { ids: [...sel] }, (x) => x.updated + " machine(s) updated"); go();
      } }, "Bring history across")) : null));
    return box;
  }

  /* ── Equipment › Depreciation & hire charges: read-only when Fixed assets posts depreciation ── */
  function hookEqDep() {
    const orig = PAGES["eq/dep"];
    if (!orig || orig._bco238) return;
    PAGES["eq/dep"] = async (root, params) => {
      await orig(root, params);
      let st = null;
      try { st = await api("agree.switches", {}); } catch (e) { return; }
      const sw = st.switches.find((x) => x.key === "one_dep_route");
      if (!sw || !sw.on) return;
      const fix = () => {
        const b = [...root.querySelectorAll("button")].find((x) => x.textContent.trim() === "Post depreciation");
        if (!b || b._bco238) return;
        b._bco238 = true;
        b.replaceWith(h("p", { class: "hint" }, "Depreciation is posted from Fixed assets › Depreciation run. This list shows each machine's result read-only. ",
          h("a", { href: "#/fa/dep" }, "Open the depreciation run")));
      };
      fix();
      new MutationObserver(fix).observe(root, { childList: true, subtree: true });
    };
    PAGES["eq/dep"]._bco238 = true;
  }

  (window.bcoBootHooks = window.bcoBootHooks || []).push(() => {
    hookEqDep();
    if (typeof window.bcoTabbed !== "function") return;
    if (PAGES["admin/settings"]) window.bcoTabbed("admin/settings", "Settings", "", { firstLabel: "General", tabs: [["Books agree", switchesTab]] });
    if (PAGES["fa/dep"]) window.bcoTabbed("fa/dep", "Depreciation run", "Monthly NAS 16 depreciation of plant, equipment and assets.", { firstLabel: "Run", tabs: [["Check", checkTab]] });
  });
})();
