/* BuildCore 2.49 "Safe and correct" (screens).
   1. Lists and words that showed wrongly: a list of options given to the page in one piece showed as one blank or
      "[object …]" item (GRN "Against PO", Transfers "To store", Document library chips), a missing value showed as
      the word "null", and an empty sum showed "NaN". Fixed once, for every screen.
   2. Administration › Setup & switches, Usage report, Backup copies (second copy and attached files). */
"use strict";
(function () {
  if (window.__bco249dom) return; window.__bco249dom = true;
  const flat = (args) => {
    const out = [];
    const add = (x) => {
      if (x == null || x === false) return;
      if (Array.isArray(x) || (typeof NodeList !== "undefined" && x instanceof NodeList) || (typeof HTMLCollection !== "undefined" && x instanceof HTMLCollection)) { Array.from(x).forEach(add); return; }
      if (typeof x === "number" && Number.isNaN(x)) { out.push("—"); return; }
      out.push(x);
    };
    args.forEach(add); return out;
  };
  for (const P of [Element.prototype, DocumentFragment.prototype, Document.prototype]) {
    for (const name of ["append", "prepend", "replaceChildren"]) {
      const orig = P[name];
      if (!orig || orig.__bco249) continue;
      const f = function (...args) { return orig.apply(this, flat(args)); };
      f.__bco249 = true; P[name] = f;
    }
  }
  for (const name of ["before", "after", "replaceWith"]) {
    const orig = Element.prototype[name];
    if (!orig || orig.__bco249) continue;
    const f = function (...args) { return orig.apply(this, flat(args)); };
    f.__bco249 = true; Element.prototype[name] = f;
  }
  /* an empty or impossible sum is shown as a dash, never "NaN" */
  const tls = Number.prototype.toLocaleString;
  Number.prototype.toLocaleString = function (...a) { const v = this.valueOf(); return Number.isNaN(v) ? "—" : tls.apply(this, a); };
  const tfx = Number.prototype.toFixed;
  Number.prototype.toFixed = function (...a) { const v = this.valueOf(); return Number.isNaN(v) ? "—" : tfx.apply(this, a); };
})();

(function () {
  if (window.__bco249) return; window.__bco249 = true;
  const yes = (b) => h("span", { class: "sf-pill " + (b ? "ok" : "no") }, b ? "Done" : "To do");
  const onoff = (b) => h("span", { class: "sf-pill " + (b ? "ok" : "off") }, b ? "On" : "Off");
  const css = ".sf-pill{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12px;font-weight:600}.sf-pill.ok{background:#e3f4e8;color:#1d6b35}.sf-pill.no{background:#fdecea;color:#a3271b}" +
    ".sf-pill.off{background:#eef0f3;color:#5b6472}.sf-steps li{margin:8px 0;list-style:none;display:grid;grid-template-columns:70px 1fr auto;gap:10px;align-items:start}.sf-steps{padding:0}" +
    ".sf-steps .w{color:var(--muted,#6b7280);font-size:13px;display:block}.sf-banner{background:#fff6e0;border:1px solid #f0d48a;color:#6b4e00;padding:8px 12px;border-radius:8px;margin:0 0 12px;font-size:13px}" +
    "[data-theme=dark] .sf-banner{background:#3a3220;color:#f3dfa6;border-color:#6b5a2a}";
  document.head.append(h("style", {}, css));

  /* ── Administration › Setup & switches ── */
  PAGES["admin/setup"] = async (root, params) => {
    const d = await run("sf.setup", {});
    root.append(pageHead("Setup & switches", "Everything that must be in place for BuildCore's figures to be right, and every feature switch, on one page. Work down the list. Each switch is still turned on from its own screen (the link), with the same rights as before; every change is recorded in the Audit log."));
    const steps = h("ul", { class: "sf-steps" });
    d.steps.forEach((x) => steps.append(h("li", {}, yes(x.done), h("div", {}, h("b", {}, x.title), h("span", { class: "w" }, x.detail)),
      x.action === "periods" ? h("button", { class: "btn small", onclick: () => periodsFix() }, "Correct the dates") : h("a", { href: x.href }, x.link + " ›"))));
    root.append(h("div", { class: "panel" }, h("h2", {}, "1. Set-up steps"), steps));
    const sw = table([{ label: "#", v: (r) => r.order }, { label: "Feature", v: (r) => h("div", {}, h("b", {}, r.label), h("div", { class: "hint" }, r.what)) },
      { label: "State", v: (r) => onoff(r.on) }, { label: "Right needed", v: (r) => r.right },
      { label: "", v: (r) => r.key === "tn_on" ? (d.can_switch_tn ? h("button", { class: "btn small" + (r.on ? "" : " primary"), onclick: () => tnDialog(r.on) }, r.on ? "Turn off" : "Preview and turn on") : "") : h("a", { href: r.href }, "Open ›") }],
    d.switches, { name: "sf_switches", search: false });
    root.append(h("div", { class: "panel" }, h("h2", {}, "2. Switches, in the order to turn them on"),
      h("p", { class: "hint" }, "Newer features that change figures or rules start off on a company that already had data, so nothing changes until accounts has looked."), sw));
    if (params.fix === "periods") periodsFix();
  };

  async function tnDialog(isOn) {
    if (isOn) {
      if (!(await ask("Trust the numbers", "Turn off? CPI and tender margin go back to the old way (all items' revenue against costed items' cost)."))) return;
      await run("sf.switch", { key: "tn_on", on: 0 }, "Turned off"); return go();
    }
    const d = await run("sf.tn_preview", {});
    const pct = (x) => x == null ? "—" : x + "%";
    const body = h("div", {}, h("p", {}, "Each project before and after. Only CPI, tender margin and margin fade change; no posting, budget or cost changes."),
      table([{ k: "project", label: "Project" }, { label: "CPI before", v: (r) => r.before ? r.before.cpi ?? "—" : "" }, { label: "CPI after", v: (r) => r.after ? r.after.cpi ?? "—" : r.error },
        { label: "Tender margin before", v: (r) => r.before ? pct(r.before.tender_margin) : "" }, { label: "after", v: (r) => r.after ? pct(r.after.tender_margin) : "" },
        { label: "Forecast margin", v: (r) => r.after ? pct(r.after.forecast_margin) : "" }, { label: "Margin fade after", v: (r) => r.after ? (r.after.margin_fade == null ? "—" : r.after.margin_fade + " pts") : "" },
        { label: "Basis", v: (r) => r.basis || "" }], d.projects, { search: false }));
    modal("Trust the numbers: preview", body, [{ label: "Turn on", cls: "primary", act: async () => { await run("sf.switch", { key: "tn_on", on: 1 }, "Turned on"); go(); } }]);
  }

  async function periodsFix() {
    const d = await run("sf.periods_check", {});
    if (!d.changes.length) return toast("All periods already follow the Nepali calendar.", "ok");
    const body = h("div", {}, h("p", {}, "The accounting periods were made as the 17th to the 16th of English months. The real Nepali months are a day or two different, so a voucher on the last day of a month could fall in the next period. These periods change; their names, status and vouchers stay the same."),
      table([{ k: "code", label: "Period" }, { k: "status", label: "Status" }, { label: "Now", v: (r) => r.start + " – " + r.end }, { label: "Nepali month", v: (r) => r.true_start + " – " + r.true_end }], d.changes, { search: false }),
      d.problems.length ? h("p", { class: "red" }, d.problems.length + " voucher(s) would move between a closed and an open month (e.g. " + d.problems[0].voucher + " of " + d.problems[0].date + "). Open those months first.") : null);
    modal("Correct the period dates", body, d.problems.length ? [] : [{ label: "Correct " + d.changes.length + " period(s)", cls: "primary", act: async () => { await run("sf.periods_fix", {}, (x) => x.fixed + " period(s) corrected"); go(); } }]);
  }

  /* ── Administration › Usage report ── */
  PAGES["admin/usage"] = async (root) => {
    const d = await run("sf.usage", {});
    root.append(pageHead("Usage report", d.note + " Use it to choose which screens to hide (nothing is deleted)."));
    root.append(h("p", {}, h("b", {}, d.unused + " of " + d.rows.length), " registers have no records on this company."));
    root.append(table([{ k: "group", label: "Area" }, { label: "Screen", v: (r) => h("a", { href: "#/" + r.path }, r.screen) }, { k: "records", label: "Records", fmt: "qty" },
      { label: "Last entry", v: (r) => r.last || "—" }, { label: "Last 90 days", v: (r) => r.recent == null ? "—" : r.recent },
      { label: "", v: (r) => r.records ? "" : h("span", { class: "sf-pill off" }, "never used") }], d.rows, { name: "sf_usage" }));
    if (d.feed.length) root.append(h("h2", {}, "Actions recorded in the activity feed"), table([{ k: "kind", label: "Kind" }, { k: "n", label: "Actions", fmt: "qty" }, { k: "last", label: "Last" }], d.feed, { search: false }));
  };

  /* ── Backup & restore: attached files and the second copy (added under the existing screen) ── */
  function backupPanel() {
    const box = h("div", { class: "panel" }, h("h2", {}, "Attached files and a second copy"));
    const load = async () => {
      const d = await api("sf.backup_status", {});
      box.replaceChildren(h("h2", {}, "Attached files and a second copy"),
        h("p", { class: "hint" }, "Every backup now also copies the attached scans, photos and drawings (" + d.files_dir + ") into " + d.backup_dir + "\\files. A second copy can go to another drive or computer: the latest backup and all files, checked every hour while BuildCore runs."),
        d.ok ? h("p", {}, h("span", { class: "sf-pill ok" }, "All good")) : h("ul", {}, d.warnings.map((w) => h("li", { class: "red" }, w))),
        kv([["Latest backup", (d.db_backup || "none") + (d.db_backup_at ? "  (" + d.db_backup_at.replace("T", " ") + ")" : "")],
          ["Attached files", d.files_in_data + " in use, " + d.files_in_backup + " in the backup" + (d.files_backup_at ? " (copied " + d.files_backup_at.replace("T", " ") + ")" : "")],
          ["Second copy", d.copy_dir ? d.copy_dir + (d.copy_at ? " — last " + d.copy_at.replace("T", " ") : " — not made yet") : "not set"],
          d.test ? ["Last restore test", (d.test.ok ? "Good" : "PROBLEM") + " — " + d.test.backup + ", " + d.test.vouchers + " vouchers, " + d.test.files_missing_in_backup + " file(s) missing (" + d.test.at.replace("T", " ") + ")"] : null,
          d.copy_error ? ["Last problem", d.copy_error] : null]));
      const inp = h("input", { value: d.copy_dir || "", placeholder: "e.g. E:\\  or  \\\\OFFICE-PC\\Backup", style: "min-width:340px" });
      box.append(h("div", { class: "actions" }, h("label", {}, "Second copy to: ", inp),
        h("button", { class: "btn", onclick: async () => { await run("sf.backup_set", { copy_dir: inp.value }, "Saved"); load(); } }, "Save place"),
        h("button", { class: "btn primary", onclick: async () => { const r = await run("sf.backup_run", {}, "Backup made"); load(); if (r.ran.second_copy && !r.ran.second_copy.ok) toast(r.ran.second_copy.reason, "err"); } }, "Back up everything now"),
        h("button", { class: "btn", onclick: async () => { const r = await run("sf.backup_test", {}); toast(r.ok ? "Backup " + r.backup + " is good" : "Backup has a problem: see the panel", r.ok ? "ok" : "err"); load(); } }, "Test the latest backup"),
        h("button", { class: "btn", onclick: async () => { const r = await run("sf.files_restore", {}); toast(r.brought_back + " file(s) brought back" + (r.still_missing ? ", " + r.still_missing + " still missing" : ""), r.still_missing ? "err" : "ok"); load(); } }, "Bring missing files back")));
    };
    load().catch((e) => box.append(h("p", { class: "red" }, e.message)));
    return box;
  }

  /* ── a note on project screens while the project position is off ── */
  let FLAGS = null;
  const flags = async () => { if (!FLAGS) { try { FLAGS = await api("sf.flags", {}); } catch (e) { FLAGS = {}; } } return FLAGS; };
  const BANNER_ON = new Set(["p/evm", "p/control", "cl/cvr", "mg/project", "dashboard", "command", "ws/project", "cl/cvrall", "cl/league"]);
  let warned = false;

  window.addEventListener("load", () => {
    const ob = PAGES["admin/backup"];
    if (ob && !ob.__sf) { const nb = async (root, p) => { await ob(root, p); const t = root.querySelector("h2"); const pnl = backupPanel(); if (t && t.parentElement && t.parentElement.classList.contains("panel")) t.parentElement.before(pnl); else root.append(pnl); }; nb.__sf = true; PAGES["admin/backup"] = nb; }
    window.addEventListener("hashchange", async () => {
      if (!S || !S.token) return;
      const path = (location.hash.replace(/^#\/?/, "") || "").split("?")[0];
      const f = await flags();
      if (BANNER_ON.has(path) && f.pfp_on === false) {
        setTimeout(() => {
          const root = document.querySelector("#page"); if (!root || root.querySelector(".sf-banner")) return;
          const bar = root.querySelector(".bar");
          const b = h("div", { class: "sf-banner" }, "Figures can differ between screens until accounts confirms the one project position (CVR and forecast › Project position). ", h("a", { href: "#/admin/setup" }, "Setup & switches ›"));
          if (bar) bar.after(b); else root.prepend(b);
        }, 1200);
      }
      if (!warned && f.backup_ok === false && (path === "dashboard" || path === "command" || path === "" || path === "ws/company")) {
        warned = true; toast("Backup: " + (f.backup_warnings || [])[0] + " See Administration › Backup & restore.", "err");
      }
    });
  });
})();
