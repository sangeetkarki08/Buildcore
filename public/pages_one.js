/* BuildCore 2.38 — Books agree.
   One new tab; the menu, module names and groups are unchanged:
     Fixed assets › Depreciation run ......... Check: one depreciation per machine
   Months depreciated by both Equipment and Fixed assets are listed; accounts proposes which posting to keep and another
   accounts approver approves (one correcting journal). Machines synced before 2.38 can bring their history across. */
(function () {
  "use strict";
  if (window.__bcoOne) return;
  window.__bcoOne = true;

  const addTabs = (route, title, sub, first, list) => {
    window.BCO_TABS = window.BCO_TABS || {};
    if (PAGES[route] && typeof window.bcoTabbed === "function") window.bcoTabbed(route, title, sub, { firstLabel: first, tabs: list });
    else (window.BCO_TABS[route] = window.BCO_TABS[route] || []).push(...list);
  };
  const KEEP = { equipment: "Equipment › Depreciation", fixed_assets: "Fixed assets › Depreciation run" };

  async function checkTab() {
    const box = h("div");
    const load = async () => {
      const d = await api("one.dep_check", {});
      box.innerHTML = "";
      box.append(h("h3", {}, "Months depreciated twice"));
      if (!d.doubles.length) box.append(h("p", { class: "hint" }, "No machine is depreciated twice in any month. From 2.38 each machine and month can be depreciated only once, from either screen."));
      else {
        box.append(h("p", { class: "hint" }, "These machines were depreciated by both Equipment › Depreciation and Fixed assets › Depreciation run for the same month (before 2.38). " +
          "Choose the posting to keep. Another accounts approver approves; BuildCore then posts one correcting journal for the other amount (Dr accumulated depreciation, Cr depreciation). The original vouchers stay as they are."));
        box.append(table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "month", label: "Month" },
          { k: "equipment_amount", label: "Equipment posting", fmt: "money" }, { k: "equipment_voucher", label: "Voucher" },
          { k: "fixed_assets_amount", label: "Fixed assets posting", fmt: "money" }, { k: "fixed_assets_voucher", label: "Voucher" },
          { label: "Proposal", v: (r) => (r.proposal ? "Keep " + KEEP[r.proposal.keep] + " · take back " + fmtMoney(r.proposal.amount) : "Suggested: keep " + KEEP[r.suggest_keep] + " (posted first)") }],
        d.doubles, { name: "dep_twice", search: false }));
        d.doubles.forEach((r) => {
          const btn = (label, fn, cls) => h("button", { class: "btn small " + (cls || ""), onclick: async () => { await fn(); await load(); } }, label);
          const acts = [];
          if (d.can_propose && !r.proposal) {
            acts.push(btn("Keep Equipment posting", () => run("one.dep_fix_propose", { equipment_id: r.equipment_id, month: r.month, keep: "equipment" }, "Proposed")));
            acts.push(btn("Keep Fixed assets posting", () => run("one.dep_fix_propose", { equipment_id: r.equipment_id, month: r.month, keep: "fixed_assets" }, "Proposed")));
          }
          if (r.proposal && d.can_approve) {
            acts.push(btn("Approve and post the correction", () => run("one.dep_fix_decide", { id: r.proposal.id }, (x) => "Correction posted: " + fmtMoney(x.amount)), "primary"));
            acts.push(btn("Reject", () => run("one.dep_fix_decide", { id: r.proposal.id, action: "reject" }, "Rejected")));
          }
          if (acts.length) box.append(h("div", { class: "actions", style: "margin:4px 0" }, h("b", { style: "margin-right:8px" }, r.code + " " + r.month + ":"), acts));
        });
      }
      box.append(h("h3", {}, "Equipment register and fixed asset register"));
      box.append(h("p", { class: "hint" }, "Both registers should carry the same depreciation history for every machine. Machines brought into Fixed assets before 2.38 started at zero; " +
        "bringing the history across copies the months and totals between the registers and takes the method, life and residual from the equipment register when Fixed assets has not depreciated the machine itself. No voucher is posted."));
      box.append(table([{ k: "code", label: "Machine" }, { k: "name", label: "Name" }, { k: "equipment_accumulated", label: "Equipment register", fmt: "money" },
        { k: "fa_accumulated", label: "Fixed asset register", fmt: "money" }, { k: "after", label: "Both after", fmt: "money" },
        { label: "Months to copy", v: (r) => [].concat(r.months_to_fixed_assets, r.months_to_equipment).join(", ") },
        { label: "Status", v: (r) => (r.double_months.length ? "Correct the months above first" : r.needed ? "Needs history" : "Agrees") }],
      d.history, { name: "dep_history", search: false, empty: "No machine in the fixed asset register yet (Capital register › bring machines in)." }));
      if (d.needs_history.length && d.can_propose)
        box.append(h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
          const ok = await ask("Bring history across", "Copy the depreciation history between the two registers for " + d.needs_history.length + " machine(s)? No voucher is posted.");
          if (!ok) return;
          await run("one.dep_history_apply", {}, (x) => "Done: " + (x.done.join(", ") || "none") + (x.skipped.length ? " · skipped " + x.skipped.length : ""));
          await load();
        } }, "Bring history across")));
    };
    await load();
    return box;
  }

  addTabs("fa/dep", "Depreciation run", "One depreciation per machine and month, kept the same in the equipment register and the fixed asset register.", "Depreciation run",
    [["Check: one depreciation", checkTab]]);

  /* What's new */
  const VER = "2.38.0";
  const openCheck = () => {
    const t = (PAGES["fa/dep"] && PAGES["fa/dep"].__bco && PAGES["fa/dep"].__bco.tabs) || [];
    const i = t.findIndex((x) => x[0] === "Check: one depreciation");
    location.hash = "#/fa/dep?tab=" + (i < 0 ? 1 : i + 1);
  };
  function whatsNew() {
    try { if (localStorage.getItem("bco_seen_" + VER)) return; } catch (e) { return; }
    if (document.querySelector(".overlay")) { setTimeout(whatsNew, 4000); return; }
    try { localStorage.setItem("bco_seen_" + VER, "1"); } catch (e) { /* ignore */ }
    if (!can("accounts", "view")) return;
    modal("What's new in BuildCore " + VER, h("div", { style: "max-width:620px" },
      h("ul", { style: "line-height:1.6;padding-left:18px" },
        h("li", {}, h("b", {}, "One depreciation per machine and month. "), "Equipment › Depreciation and Fixed assets › Depreciation run now keep one history: whichever posts first, the other skips that machine and month, and both registers show the same figures."),
        h("li", {}, h("b", {}, "Check: one depreciation "), "(Fixed assets › Depreciation run). Lists any month depreciated by both screens before 2.38. Accounts chooses which posting to keep and another approver approves one correcting journal. Machines brought into Fixed assets earlier can bring their depreciation history across."),
        h("li", {}, h("b", {}, "One charge per machine hour. "), "Equipment allocation no longer charges hours already charged by the DPR or by an internal hire bill. Hire bills count approved logsheet hours only."),
        h("li", {}, h("b", {}, "Data checks. "), "Financial data checks and Integrity now compare stock, asset cost and depreciation with the ledger, and name any entry still waiting in the accounts posting queue.")),
      h("p", { class: "hint" }, "Nothing already posted is changed. Corrections are posted only after approval.")),
    [{ label: "Open the check", cls: "primary", act: openCheck }], { narrow: true });
  }
  const seen = setInterval(() => { if (typeof S !== "undefined" && S.user && document.querySelector(".top") && !document.querySelector(".overlay")) { clearInterval(seen); setTimeout(whatsNew, 12000); } }, 900);
})();
