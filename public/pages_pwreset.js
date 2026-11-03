/* BuildCore 2.36 — forgotten passwords, offline: recovery code, reset code from an administrator,
   master key file or a reset key from the supplier; "Forgot master password?" on the admin computer. */
(function () {
"use strict";

const css = document.createElement("style");
css.textContent = [
  ".pwr-ov{position:fixed;inset:0;z-index:9000;background:rgba(13,47,69,.45);display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:5vh 12px}",
  ".pwr-card{background:var(--panel,#fff);border:1px solid var(--line,#d0d7dc);border-radius:14px;width:min(520px,96vw);padding:24px 26px 20px;box-shadow:0 18px 50px rgba(16,42,60,.25)}",
  ".pwr-card h2{margin:0 0 4px;font-size:21px}.pwr-card .muted{margin:0 0 14px;color:var(--muted,#667)}",
  ".pwr-card label.f{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}.pwr-card label.f span{font-size:13px;font-weight:600}",
  ".pwr-card input[type=text],.pwr-card input[type=password],.pwr-card textarea{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid var(--line,#c9d2d6);border-radius:8px;font:inherit;background:var(--paper,#fff);color:inherit}",
  ".pwr-card textarea{font-family:monospace;font-size:13px}",
  ".pwr-way{display:block;width:100%;text-align:left;border:1px solid var(--line,#c9d2d6);background:var(--paper,#fff);color:inherit;border-radius:10px;padding:11px 14px;margin:0 0 10px;cursor:pointer;font:inherit}",
  ".pwr-way:hover{border-color:var(--blue,#1b5e86);box-shadow:inset 0 0 0 1px var(--blue,#1b5e86)}.pwr-way b{display:block;font-size:15px}.pwr-way small{display:block;color:var(--muted,#667);margin-top:2px;line-height:1.4}",
  ".pwr-err{background:#fdecea;color:#b42318;border:1px solid #efc4bd;border-radius:8px;padding:9px 12px;margin:4px 0 12px;font-size:13px}",
  ".pwr-ok{background:#e7f6ec;color:#067647;border:1px solid #b7e1c4;border-radius:8px;padding:9px 12px;margin:4px 0 12px;font-size:13px}",
  ".pwr-code{font-family:monospace;font-size:22px;letter-spacing:1px;background:var(--blue-wash,#eef3f6);padding:10px 14px;border-radius:8px;user-select:all;display:inline-block;margin:6px 0;word-break:break-all}",
  ".pwr-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}.pwr-row .grow{flex:1}",
  ".pwr-back{border:0;background:none;color:var(--blue,#1b5e86);cursor:pointer;padding:0;font:inherit;font-size:13px}",
  ".pwr-hint{font-size:12px;color:var(--muted,#667);line-height:1.5;margin:10px 0 0}",
  ".auth .foot a.forgotlink{font-weight:600;color:var(--blue,#1b5e86)}",
].join("");
document.head.append(css);

const E = (tag, attrs, ...kids) => h(tag, attrs, ...kids);
function copy(t, btn) {
  const done = () => { if (btn) { const o = btn.textContent; btn.textContent = "Copied ✓"; setTimeout(() => { btn.textContent = o; }, 1500); } };
  const fb = () => { const ta = E("textarea", {}, t); document.body.append(ta); ta.select(); try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ } ta.remove(); };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, fb); else fb();
}
function saveText(name, text) {
  const a = E("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name });
  document.body.append(a); a.click(); a.remove();
}
function readFile(input) {
  return new Promise((ok, bad) => {
    const f = input.files && input.files[0];
    if (!f) return bad(new Error("Choose the master key file (.bckey) first."));
    const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = () => bad(new Error("Could not read the file.")); r.readAsText(f);
  });
}
const pw = (name, ph) => E("input", { type: "password", name, placeholder: ph || "", autocomplete: "new-password" });

/* ───────────────────────── sign-in screen: Forgot password? ───────────────────────── */
window.bcoForgot = function (o) {
  o = o || {};
  const old = document.querySelector(".pwr-ov"); if (old) old.remove();
  const card = E("div", { class: "pwr-card", role: "dialog", "aria-label": "Forgot password" });
  const ov = E("div", { class: "pwr-ov", onclick: (e) => { if (e.target === ov) close(); } }, card);
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { ov.remove(); document.removeEventListener("keydown", onKey); }
  document.addEventListener("keydown", onKey);
  document.body.append(ov);
  const user = E("input", { type: "text", name: "fu", autocomplete: "username", value: o.username || "" });
  const err = E("div", { class: "pwr-err", hidden: true });
  const showErr = (m) => { err.textContent = m || ""; err.hidden = !m; };
  const uname = () => user.value.trim();
  const needUser = () => { if (!uname()) { showErr("Type your username first."); user.focus(); return false; } return true; };

  const draw = (title, sub, ...body) => {
    card.innerHTML = ""; showErr("");
    card.append(...[E("h2", {}, title), sub ? E("p", { class: "muted" }, sub) : null, err, ...body].filter(Boolean));
  };
  const footer = (back) => E("div", { class: "pwr-row" }, back ? E("button", { class: "pwr-back", type: "button", onclick: back }, "‹ Back") : null,
    E("span", { class: "grow" }), E("button", { class: "btn", type: "button", onclick: close }, "Close"));

  async function done(r, note) {
    draw("Password changed", null, E("div", { class: "pwr-ok" }, "The new password is saved for " + r.username + ". Opening BuildCore …"),
      note ? E("p", { class: "pwr-hint" }, note) : null);
    setTimeout(async () => {
      close();
      if (o.signIn) {
        try { await o.signIn(r.token, r.username); } catch (e) { location.reload(); return; }
        if (note) setTimeout(() => { try { toast(note, "ok"); } catch (e) { /* ignore */ } }, 1500);
      } else { location.reload(); }
    }, 1400);
  }
  function newPwFields() {
    const p1 = pw("password", "6 or more characters"), p2 = pw("password2", "type it again");
    return { p1, p2, el: [E("label", { class: "f" }, E("span", {}, "New password"), p1), E("label", { class: "f" }, E("span", {}, "New password again"), p2)],
      check: () => { if (p1.value.length < 6) { showErr("The new password needs at least 6 characters."); p1.focus(); return false; }
        if (p1.value !== p2.value) { showErr("The two new passwords are not the same."); p2.focus(); return false; } return true; } };
  }
  const busy = async (btn, label, f) => { btn.disabled = true; const t = btn.textContent; btn.textContent = label; try { await f(); } catch (e) { showErr(e.message); } finally { btn.disabled = false; btn.textContent = t; } };

  function home() {
    draw("Forgot your password?", (o.company ? o.company + " · " : "") + "Choose how to set a new one. All of this works without internet.",
      E("label", { class: "f" }, E("span", {}, "Username"), user),
      E("button", { class: "pwr-way", type: "button", onclick: () => { if (needUser()) withCode(); } },
        E("b", {}, "I have a code"), E("small", {}, "Your own recovery code, or the one-time reset code your administrator made for you (Administration › Users › Reset code).")),
      E("button", { class: "pwr-way", type: "button", onclick: () => { if (needUser()) adminWays(); } },
        E("b", {}, "I am the administrator and no one can reset me"), E("small", {}, "Use the BuildCore master key file (.bckey), or get a reset key from your BuildCore supplier.")),
      E("p", { class: "pwr-hint" }, "No code? Ask an administrator: they can make a reset code for you, or set a new password, in Administration › Users."),
      footer());
    user.focus();
  }

  function withCode() {
    const code = E("input", { type: "text", name: "code", placeholder: "XXXXX-XXXXX-XXXXX-XXXXX", autocomplete: "off", style: "font-family:monospace;letter-spacing:1px" });
    const np = newPwFields();
    const btn = E("button", { class: "btn primary", type: "submit" }, "Set the new password");
    const f = E("form", { onsubmit: (e) => { e.preventDefault(); if (!code.value.trim()) { showErr("Type the code."); code.focus(); return; } if (!np.check()) return;
      busy(btn, "Saving…", async () => {
        const r = await api("auth.forgot_code", { username: uname(), code: code.value, password: np.p1.value, password2: np.p2.value });
        done(r, r.kind === "recovery" ? "Your recovery code is now used up. Make a new one: user menu (your initials, top right) › Password recovery code." : "");
      }); } },
      E("label", { class: "f" }, E("span", {}, "Code (20 letters and digits; dashes and small letters are fine)"), code), ...np.el, btn);
    draw("Set a new password with a code", "For " + uname() + ".", f,
      E("p", { class: "pwr-hint" }, "Wrong codes count like wrong passwords: after 5 the username is locked for a few minutes."), footer(home));
    code.focus();
  }

  function adminWays() {
    draw("Administrator locked out", "For " + uname() + ". Use one of these:",
      E("button", { class: "pwr-way", type: "button", onclick: withFile },
        E("b", {}, "I have the master key file (.bckey)"), E("small", {}, "The file given with BuildCore for making licence keys. Whoever holds it can set a new password here at once.")),
      E("button", { class: "pwr-way", type: "button", onclick: withKey },
        E("b", {}, "Ask my BuildCore supplier for a reset key"), E("small", {}, "BuildCore shows a reset request code. Send it to the supplier; type in the reset key they send back.")),
      footer(home));
  }

  function withFile() {
    const file = E("input", { type: "file", accept: ".bckey,.txt" });
    const np = newPwFields();
    const btn = E("button", { class: "btn primary", type: "submit" }, "Set the new password");
    const f = E("form", { onsubmit: (e) => { e.preventDefault(); if (!np.check()) return;
      busy(btn, "Checking…", async () => {
        const text = await readFile(file);
        done(await api("auth.forgot_bckey", { username: uname(), text, password: np.p1.value, password2: np.p2.value }));
      }); } },
      E("label", { class: "f" }, E("span", {}, "Master key file (.bckey)"), file), ...np.el, btn);
    draw("New password with the master key file", "For " + uname() + ". The file is only read, never stored by this step.", f,
      E("p", { class: "pwr-hint" }, "If you also forgot the master password for licence keys: after signing in, open Administration › Licence keys › Forgot master password."),
      footer(adminWays));
  }

  async function withKey() {
    let r;
    try { r = await api("auth.forgot_request", { username: uname() }); } catch (e) { return showErr(e.message); }
    const key = E("textarea", { rows: 3, name: "key", placeholder: "BCR1-…" });
    const np = newPwFields();
    const cb = E("button", { class: "btn", type: "button", onclick: () => copy(r.request_code, cb) }, "Copy");
    const btn = E("button", { class: "btn primary", type: "submit" }, "Set the new password");
    const f = E("form", { onsubmit: (e) => { e.preventDefault(); if (!key.value.trim()) { showErr("Paste the reset key from the supplier."); key.focus(); return; } if (!np.check()) return;
      busy(btn, "Checking…", async () => {
        done(await api("auth.forgot_key", { username: uname(), key: key.value, password: np.p1.value, password2: np.p2.value }));
      }); } },
      E("h3", { style: "margin:4px 0" }, "1 · Send this reset request code to your BuildCore supplier"),
      E("div", { class: "pwr-row", style: "margin-top:0" }, E("span", { class: "pwr-code" }, r.request_code), cb),
      E("p", { class: "pwr-hint", style: "margin-top:2px" }, "Say it is for user " + r.username + (r.company ? " of " + r.company : "") + ". The code stays the same until " + r.valid_until + " — you can close this and come back."),
      E("h3", { style: "margin:14px 0 6px" }, "2 · Paste the reset key they send back"),
      key, E("div", { style: "height:10px" }), ...np.el, btn);
    draw("Reset key from the supplier", null, f, footer(adminWays));
  }

  home();
};

/* ───────────────────────── user menu: Password recovery code ───────────────────────── */
window.bcoRecovery = async function () {
  let st = { has_code: false };
  try { st = await api("auth.recovery_status", {}); } catch (e) { /* older engine */ }
  const p = E("input", { type: "password", name: "password", autocomplete: "current-password" });
  const out = E("div");
  const body = E("div", {},
    E("p", {}, "A recovery code lets you set a new password yourself on the sign-in screen (Forgot password? › I have a code), with no administrator and no internet."),
    E("p", { class: "hint" }, st.has_code ? "You have a recovery code, made " + String(st.created || "").replace("T", " ").slice(0, 16) + ". Making a new one cancels it." : "You have no recovery code yet."),
    E("label", { class: "f" }, E("span", {}, "Your current password"), p), out);
  const m = modal("Password recovery code", body, [{ label: st.has_code ? "Make a new code" : "Make my recovery code", cls: "primary", keep: true, act: async () => {
    const r = await run("auth.recovery_make", { password: p.value });
    p.value = "";
    out.innerHTML = "";
    const txt = "BuildCore recovery code\r\nCompany: " + (r.company || "") + "\r\nUsername: " + r.username + "\r\nCode: " + r.code + "\r\n\r\nSign-in screen > Forgot password? > I have a code. Works once.\r\n";
    const cb = E("button", { class: "btn", onclick: () => copy(r.code, cb) }, "Copy");
    out.append(E("div", { class: "panel", style: "margin-top:10px" }, E("h3", {}, "Your recovery code"), E("span", { class: "pwr-code" }, r.code),
      E("div", { class: "actions" }, cb, E("button", { class: "btn", onclick: () => saveText("BuildCore_recovery_" + r.username + ".txt", txt) }, "Save as file")),
      E("p", { class: "hint" }, "Write it down or keep the file somewhere safe, away from this computer. It is shown only now. It works once; after using it, make a new one.")));
  } }], { narrow: true });
  void m;
};

/* ───────────────────────── Administration › Users: one-time reset code ───────────────────────── */
window.bcoResetCode = async function (row) {
  const ok = await ask("Reset code for " + (row.name || row.username), "Make a one-time code so " + (row.name || row.username) + " can choose a new password on the sign-in screen (Forgot password? › I have a code). Their current password keeps working until they use it.", { ok: "Make the code" });
  if (!ok) return;
  const r = await run("adm.reset_code", { id: row.id });
  const cb = E("button", { class: "btn primary", onclick: () => copy(r.code, cb) }, "Copy");
  modal("Reset code for " + r.username, E("div", {}, E("span", { class: "pwr-code" }, r.code),
    E("div", { class: "actions" }, cb),
    E("p", {}, "Give it to " + (r.name || r.username) + " by phone or in person. It works once, until " + String(r.expires || "").replace("T", " ").slice(0, 16) + " (" + r.hours + " hours)."),
    E("p", { class: "hint" }, "On the sign-in screen: Forgot password? › type the username " + r.username + " › I have a code. Making another code cancels this one.")), [], { narrow: true });
  if (typeof go === "function") go();
};

/* ───────────────────────── Administration › Licence keys: reset key, forgot master password ───────────────────────── */
let licHooked = false;
function hookLicence() {
  const cur = typeof PAGES !== "undefined" && PAGES["admin/licence"];
  if (!cur || cur._bco236 || licHooked) return;
  licHooked = true;
  const next = async (root, params) => {
    await cur(root, params);
    if (root.querySelector("[data-pwr]")) return;
    let s = null;
    try { s = await api("license.status", {}); } catch (e) { return; }
    if (!s || !s.admin_pc) return;
    const f = form([{ k: "request_code", label: "Reset request code (from their sign-in screen)", req: true, ph: "XXXXX-XXXXX-XXXXX-XXXXX" },
      { k: "for", label: "For (company / user, for your list)" }, { k: "note", label: "Note" },
      { k: "password", label: "Master password", type: "password", req: true }], {});
    const out = E("div");
    const panel = E("div", { class: "panel", "data-pwr": "1" }, E("h2", {}, "Password reset key (administrator locked out)"),
      E("p", { class: "hint" }, "When every administrator of a company has forgotten the password, their sign-in screen (Forgot password? › I am the administrator… › Ask my BuildCore supplier) shows a reset request code. "
        + "Make the key for it here. It sets a new password once, only for that request and user."),
      f, E("div", { class: "actions" }, E("button", { class: "btn primary", onclick: async () => {
        const r = await run("license.pwreset_make", f.values(), "Reset key made");
        f.set("password", "");
        out.innerHTML = "";
        const ta = E("textarea", { rows: 3, readonly: true, style: "font-family:monospace" }); ta.value = r.key;
        const cb = E("button", { class: "btn primary", onclick: () => copy(r.key, cb) }, "Copy key");
        out.append(E("div", { class: "panel" }, E("h3", {}, "Reset key"), ta, E("div", { class: "actions" }, cb,
          E("button", { class: "btn", onclick: () => saveText("BuildCore_reset_key.txt", r.key + "\r\n") }, "Save as file")),
          E("p", { class: "hint" }, "Send it back by e-mail, Viber or phone. They paste it on the same Forgot password screen and choose a new password.")));
      } }, "Make the reset key")), out);
    const mf = E("input", { type: "file", accept: ".bckey,.txt" });
    const pf = form([{ k: "password", label: "New master password (8+ characters)", type: "password" }, { k: "password2", label: "Same password again", type: "password" }], {});
    const forgot = E("div", { class: "panel" }, E("h2", {}, "Forgot master password?"),
      E("p", { class: "hint" }, "Load the original master key file (.bckey) again and choose a new master password. Licence keys already made keep working and the list of keys made stays."),
      mf, pf, E("div", { class: "actions" }, E("button", { class: "btn", onclick: async () => {
        const v = pf.values();
        if ((v.password || "").length < 8) return toast("Choose a master password of at least 8 characters.", "err");
        if (v.password !== v.password2) return toast("The two passwords are different.", "err");
        let text; try { text = await readFile(mf); } catch (e) { return toast(e.message, "err"); }
        await run("license.master_reset", { text, password: v.password, password2: v.password2 }, "New master password set");
        go();
      } }, "Set a new master password")));
    const panels = [...root.querySelectorAll(".panel")];
    const keysMade = panels.find((p) => /Keys made on this computer/.test((p.querySelector("h2") || {}).textContent || ""));
    if (keysMade) keysMade.after(panel); else root.append(panel);
    root.append(forgot);
  };
  next._bco236 = true;
  PAGES["admin/licence"] = next;
}
hookLicence();
(window.bcoBootHooks = window.bcoBootHooks || []).push(hookLicence);
})();
