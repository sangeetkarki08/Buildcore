/* BuildCore 2.13 — licence keys: activation on each computer, key making on the admin computer only. */
(function () {
"use strict";

let LIC = null;
const tok = () => { try { return (typeof S !== "undefined" && S && S.token) || ""; } catch (e) { return ""; } };
async function licCall(fn, args) {
  const r = await fetch("/api", { method: "POST", headers: { "Content-Type": "application/json", "X-Token": tok() },
    body: JSON.stringify({ fn, args: args || {} }) });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "Something went wrong");
  return j.data;
}
const el = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => { if (k === "style") e.style.cssText = v; else if (k.startsWith("on")) e[k] = v; else e.setAttribute(k, v); });
  kids.flat().forEach((k) => { if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k))); });
  return e;
};
function copyText(t, btn) {
  const done = () => { if (btn) { const o = btn.textContent; btn.textContent = "Copied ✓"; setTimeout(() => { btn.textContent = o; }, 1500); } };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, () => { fallback(); });
  else fallback();
  function fallback() { const ta = el("textarea", {}, t); document.body.append(ta); ta.select(); try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ } ta.remove(); }
}
function readFile(input) {
  return new Promise((ok, bad) => {
    const f = input.files && input.files[0];
    if (!f) return bad(new Error("Choose the file first."));
    const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = () => bad(new Error("Could not read the file.")); r.readAsText(f);
  });
}
function saveFile(name, text) {
  const a = el("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name });
  document.body.append(a); a.click(); a.remove();
}

/* ── the activation screen, shown instead of BuildCore until a key is entered ── */
function showActivation(s) {
  if (document.getElementById("bco-lic")) return;
  const msg = el("div", { style: "min-height:20px;margin:8px 0;color:#b42318;font-weight:600" });
  const keyBox = el("textarea", { rows: "4", placeholder: "BCK1-…", style: "width:100%;font-family:monospace;font-size:13px;padding:8px;box-sizing:border-box" });
  const keyFile = el("input", { type: "file", accept: ".lic,.txt" });
  const copyBtn = el("button", { class: "btn", onclick: () => copyText(s.request_code, copyBtn) }, "Copy");
  const activate = async (text) => {
    msg.textContent = "";
    try { await licCall("license.activate", { key: text }); msg.style.color = "#067647"; msg.textContent = "Activated. Opening BuildCore …"; setTimeout(() => location.reload(), 800); }
    catch (e) { msg.style.color = "#b42318"; msg.textContent = e.message; }
  };
  const mFile = el("input", { type: "file", accept: ".bckey,.txt" });
  const pw1 = el("input", { type: "password", placeholder: "New master password (8+ characters)", style: "width:100%;margin:4px 0;padding:6px" });
  const pw2 = el("input", { type: "password", placeholder: "Same password again", style: "width:100%;margin:4px 0;padding:6px" });
  const mMsg = el("div", { style: "color:#b42318;margin-top:6px" });
  const box = el("div", { id: "bco-lic", style: "position:fixed;inset:0;z-index:99999;background:#f2f4f7;overflow:auto;font-family:inherit" },
    el("div", { style: "max-width:720px;margin:40px auto;background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:28px" },
      el("h1", { style: "margin:0 0 6px" }, "Activate BuildCore"),
      el("p", { style: "color:#475467;margin:0 0 18px" }, s.reason || "BuildCore needs a licence key for this computer."),
      el("h3", {}, "1 · Send this request code to your BuildCore administrator"),
      el("div", { style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap" },
        el("code", { style: "font-size:22px;letter-spacing:1px;background:#f2f4f7;padding:10px 14px;border-radius:8px;user-select:all" }, s.request_code), copyBtn),
      el("p", { style: "color:#667085;font-size:13px" }, "Computer: " + (s.computer || "") + ". The code belongs to this computer only — send it by e-mail, Viber or phone."),
      el("h3", { style: "margin-top:22px" }, "2 · Enter the licence key you receive"),
      keyBox,
      el("div", { style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px" },
        el("button", { class: "btn primary", onclick: () => activate(keyBox.value) }, "Activate"),
        el("span", { style: "color:#667085" }, "or load the key file:"), keyFile,
        el("button", { class: "btn", onclick: async () => { try { activate(await readFile(keyFile)); } catch (e) { msg.textContent = e.message; } } }, "Load")),
      msg,
      el("details", { style: "margin-top:26px;border-top:1px solid #eaecf0;padding-top:14px" },
        el("summary", { style: "cursor:pointer;color:#344054" }, "This is the admin computer — I have the master key file"),
        el("p", { style: "color:#667085;font-size:13px" }, "Only the admin computer holds the master key; it makes the keys for all other computers. "
          + "Load the master key file once and lock it with a password you will type each time you make a key."),
        mFile, pw1, pw2,
        el("button", { class: "btn primary", onclick: async () => {
          mMsg.textContent = "";
          if (pw1.value !== pw2.value) { mMsg.textContent = "The two passwords are different."; return; }
          try { await licCall("license.master_load", { text: await readFile(mFile), password: pw1.value }); location.reload(); }
          catch (e) { mMsg.textContent = e.message; }
        } }, "Make this the admin computer"), mMsg)));
  document.body.append(box);
}

function banner(s) {
  const old = document.getElementById("bco-lic-bar"); if (old) old.remove();
  if (!s || !s.active) return;
  let t = "";
  if (s.grace) t = "No licence key on this computer yet — BuildCore works for " + s.days_left + " more day(s). Enter the key in Administration › Licence keys.";
  else if (s.days_left != null && s.days_left <= 30) t = "The BuildCore licence ends on " + s.expires + " (" + s.days_left + " day(s) left). Ask your administrator for a new key.";
  if (!t) return;
  document.body.append(el("div", { id: "bco-lic-bar", style: "position:fixed;left:50%;transform:translateX(-50%);bottom:10px;z-index:9000;background:#fffaeb;border:1px solid #fec84b;color:#93370d;padding:8px 14px;border-radius:8px;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.1);cursor:pointer",
    onclick: () => { location.hash = "#/admin/licence"; } }, t));
}

/* check before BuildCore opens */
const _boot = window.bcoBoot;
window.bcoBoot = function () {
  const go_ = () => (_boot ? _boot() : (typeof start === "function" ? start() : null));
  licCall("license.status").then((s) => {
    LIC = s;
    if (!s.active) return showActivation(s);
    go_();
    setTimeout(() => banner(s), 3000);
  }, () => go_());
};

/* a licence that runs out while BuildCore is open: show the activation screen */
const _fetch = window.fetch.bind(window);
window.fetch = async function (url, opts) {
  const r = await _fetch(url, opts);
  try {
    if (String(url).endsWith("/api") && r.status === 200) {
      r.clone().json().then((j) => {
        if (j && !j.ok && /^Licence required/.test(j.error || "")) licCall("license.status").then((s) => { if (!s.active) showActivation(s); });
      }, () => {});
    }
  } catch (e) { /* never break a request */ }
  return r;
};

/* ── Administration › Licence keys ── */
PAGES["admin/licence"] = async (root) => {
  const s = await run("license.status", {});
  LIC = s;
  const kvRows = [["Status", s.active ? (s.grace ? "Working without a key — " + s.days_left + " day(s) left" : "Active") : "Not active"],
    ["Licensed to", s.licensee || "—"], ["Valid until", s.grace ? "—" : (s.expires || "no end date")],
    ["Users allowed", s.max_users ? s.max_users + " active users (" + (s.users_active || 0) + " now)" : "no limit"],
    ["This computer", s.computer], ["Request code", s.request_code]];
  const keyBox = h("textarea", { rows: 3, placeholder: "Paste a new key (BCK1-…) to renew or change the licence", style: "font-family:monospace" });
  root.append(pageHead("Licence keys", "Every computer that runs BuildCore needs a key made for its request code. Browsers using this computer's BuildCore over the network need no key."),
    h("div", { class: "panel" }, h("h2", {}, "This computer"), kv(kvRows),
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: (e) => copyText(s.request_code, e.target) }, "Copy request code")),
      h("h3", {}, "Enter a new key"), keyBox,
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => { await run("license.activate", { key: keyBox.value }, "Licence key saved"); go(); } }, "Save the key"))));
  if (s.admin_pc) {
    const f = form([{ k: "request_code", label: "Request code of the computer", req: true, ph: "XXXXX-XXXXX-XXXXX-XXXXX" },
      { k: "licensee", label: "Licensed to (company / site)", req: true }, { k: "computer", label: "Computer / person (for your list)" },
      { k: "expires", label: "Valid until (blank = no end)", type: "date" }, { k: "max_users", label: "Active users allowed (0 = no limit)", type: "number" },
      { k: "note", label: "Note" }, { k: "password", label: "Master password", type: "password", req: true }], { max_users: 0 });
    const out = h("div");
    const list = h("div");
    const loadList = async () => {
      const rows = await run("license.issued", {});
      list.innerHTML = "";
      list.append(table([{ label: "Made", v: (r) => (r.ts || "").slice(0, 16).replace("T", " ") }, { k: "licensee", label: "Licensed to" }, { k: "computer", label: "Computer" },
        { k: "request_code", label: "Request code" }, { label: "Valid until", v: (r) => r.expires || "no end" }, { label: "Users", v: (r) => Number(r.max_users) || "no limit" },
        { k: "note", label: "Note" }, { k: "made_by", label: "By" },
        { label: "", v: (r) => h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); copyText(r.key, e.target); } }, "Copy key") }],
      rows, { name: "licence_keys", title: "Licence keys made", empty: "No keys made yet." }));
    };
    root.append(h("div", { class: "panel" }, h("h2", {}, "Make a licence key (admin computer)"),
      h("p", { class: "hint" }, "Ask the other computer for the request code on its activation screen (or its Administration › Licence keys page). Each key opens only that computer."),
      f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        const v = f.values();
        const r = await run("license.make", v, "Key made");
        f.set && f.set("password", "");
        out.innerHTML = "";
        const ta = h("textarea", { rows: 4, readonly: true, style: "font-family:monospace" }); ta.value = r.key;
        out.append(h("div", { class: "panel" }, h("h3", {}, "Key for " + r.record.licensee), ta,
          h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: (e) => copyText(r.key, e.target) }, "Copy key"),
            h("button", { class: "btn", onclick: () => saveFile(r.filename, r.key + "\r\n") }, "Save as .lic file")),
          h("p", { class: "hint" }, "Send it to that computer by e-mail, Viber or pen drive. It goes in on the activation screen, or in Administration › Licence keys there.")));
        loadList();
      } }, "Make the key")), out),
    h("div", { class: "panel" }, h("h2", {}, "Keys made on this computer"), list),
    h("div", { class: "panel" }, h("h2", {}, "Master key"),
      h("p", { class: "hint" }, "This computer holds the master key, locked with your master password. Keep the original master key file on a pen drive in a safe place: "
        + "without it no new keys can be made if this computer is lost. Anyone with that file and a BuildCore can make keys."),
      h("button", { class: "btn warn", onclick: () => {
        const pf = form([{ k: "password", label: "Master password", type: "password", req: true }], {});
        modal("Remove the master key from this computer", h("div", {}, h("p", {}, "This computer will no longer make keys (it will need its own licence key). You can load the master key file again later."), pf),
          [{ label: "Remove", cls: "warn", act: async () => { await run("license.master_forget", pf.values(), "Master key removed from this computer"); go(); } }], { narrow: true });
      } }, "Remove the master key from this computer")));
    await loadList();
  } else if (typeof can === "function" && can("admin", "edit")) {
    const mf = h("input", { type: "file", accept: ".bckey,.txt" });
    const pf = form([{ k: "p1", label: "New master password (8+ characters)", type: "password" }, { k: "p2", label: "Same password again", type: "password" }], {});
    root.append(h("div", { class: "panel" }, h("h2", {}, "Make this the admin computer"),
      h("p", { class: "hint" }, "Only one computer should make keys. Load the master key file here once and lock it with a password."), mf, pf,
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: async () => {
        const v = pf.values();
        if (v.p1 !== v.p2) return toast("The two passwords are different.", "err");
        let text; try { text = await readFile(mf); } catch (e) { return toast(e.message, "err"); }
        await run("license.master_load", { text, password: v.p1 }, "This is now the admin computer"); go();
      } }, "Load the master key"))));
  }
};

})();
