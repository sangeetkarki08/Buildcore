/* BuildCore web edition - the browser side of the few web differences. Loaded before every screen.
 *
 *  - files larger than a web request can carry go straight to the private file store with a one-time link
 *  - restore sends the desktop data file the same way, then the server imports it
 *  - the first administrator needs the setup key from the Vercel settings
 *  - Backup & restore gets a step to bring the desktop's attachments (data\files folder) across
 *  - Forgot password on the sign-in page; the requests it sends are listed in Administration › Users
 *  - The address opens on a company sign-in (no company's name is shown), then the user sign-in of that company
 *  - The "What's new" pop-ups of each version are not shown
 *  - Two-step sign-in with an authenticator app (user menu; required or not in Administration › Users)
 */
(function () {
  "use strict";
  const BIG = 4 * 1024 * 1024;
  const realFetch = window.fetch.bind(window);

  /* "What's new in BuildCore ...": each version's pop-up is left out (a new browser would get about 15 in a row) */
  window.addEventListener("DOMContentLoaded", () => {
    const realModal = window.modal;
    if (typeof realModal !== "function") return;
    window.modal = function (title, ...rest) {
      if (/^What.s new/i.test(String(title))) return { close() { /* never opened */ }, el: document.createElement("div") };
      return realModal(title, ...rest);
    };
  });

  /* company sign-in: the ticket of the company this browser works in */
  const LSg = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const LSs = (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private window */ } };
  const coCode = () => LSg("bco_company") || "main";
  const ticketKey = (code) => "bco_ticket:" + code;
  function chooseCompany(code, ticket) {
    LSs(ticketKey(code), ticket);
    LSs("bco_company", code);
    LSs("bco_token", null);
    document.cookie = "bco_co=" + code + "; path=/; max-age=31536000; SameSite=Lax";
  }
  function leaveCompany() {
    LSs(ticketKey(coCode()), null);
    LSs("bco_company", null);
    LSs("bco_token", null);
    document.cookie = "bco_co=; path=/; max-age=0; SameSite=Lax";
  }

  function headersOf(init) {
    const out = {};
    const h = (init && init.headers) || {};
    if (typeof h.forEach === "function" && !(h instanceof Array)) h.forEach((v, k) => { out[k] = v; });
    else Object.assign(out, h);
    return out;
  }
  async function call(fn, args, headers) {
    const r = await realFetch("/api", {
      method: "POST",
      headers: Object.assign({}, headers, { "Content-Type": "application/json" }),
      body: JSON.stringify({ fn, args: args || {} }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    return j.data;
  }
  async function putSigned(url, body, type) {
    const r = await realFetch(url, { method: "PUT", headers: { "Content-Type": type || "application/octet-stream", "x-upsert": "true" }, body });
    if (!r.ok) {
      let msg = "";
      try { msg = (await r.json()).message || ""; } catch (e) { /* no detail */ }
      throw new Error("The file could not be sent (" + r.status + (msg ? ": " + msg : "") + ").");
    }
  }
  const reply = (o) => new Response(JSON.stringify(o), { status: 200, headers: { "Content-Type": "application/json" } });
  const sizeOf = (b) => (b && (b.size != null ? b.size : b.byteLength)) || 0;

  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const method = ((init && init.method) || "GET").toUpperCase();
    const ticket = LSg(ticketKey(coCode()));
    if (ticket && init && url.startsWith("/api")) init = Object.assign({}, init, { headers: Object.assign(headersOf(init), { "X-Company-Ticket": ticket }) });
    if (method !== "POST" || !init) return realFetch(input, init);
    try {
      if (url.startsWith("/api/upload") && sizeOf(init.body) > BIG) {
        const meta = Object.fromEntries(new URL(url, location.href).searchParams.entries());
        const hd = headersOf(init);
        const slot = await call("web.upload_url", { filename: meta.filename || "file" }, hd);
        await putSigned(slot.url, init.body, meta.mime);
        const done = await call("web.upload_done", { key: slot.key, meta }, hd);
        return reply({ ok: true, data: done });
      }
      if (url.startsWith("/api/restore") && sizeOf(init.body) > 0) {
        const hd = headersOf(init);
        const slot = await call("web.upload_url", { filename: "restore.db" }, hd);
        await putSigned(slot.url, init.body, "application/octet-stream");
        const r = await realFetch("/api/restore?key=" + encodeURIComponent(slot.key), { method: "POST", headers: hd });
        const j = await r.json();
        if (j.ok && j.report) {
          const rp = j.report;
          let msg = "Imported " + rp.rows.toLocaleString() + " rows from " + rp.tables + " tables.";
          if (rp.notes) msg += "\n\n" + rp.notes + " value(s) were text in a number column. Each is kept word for word in the table web_import_notes (table, row and column named), so nothing is lost.";
          msg += "\n\nIf the desktop had attachments, bring them across next: Backup & restore > Attachments from BuildCore desktop.";
          alert(msg);
        }
        return reply(j);
      }
      if (url === "/api" && typeof init.body === "string" && init.body.indexOf('"auth.login"') >= 0) {
        const req = JSON.parse(init.body);
        if (req.fn === "auth.login" && !(req.args && req.args.otp)) return await loginWithCode(input, init, req);
      }
      if (url === "/api" && typeof init.body === "string" && init.body.indexOf('"auth.setup"') >= 0) {
        const req = JSON.parse(init.body);
        if (req.fn === "auth.setup" && !(req.args && req.args.setup_key)) {
          const key = window.prompt("Setup key\n\nEnter the value of BCO_SETUP_KEY from your Vercel project (Settings > Environment Variables). It makes sure only you can create the first administrator.");
          if (key == null) return reply({ ok: false, error: "The first administrator needs the setup key." });
          req.args = Object.assign({}, req.args, { setup_key: key });
          init = Object.assign({}, init, { body: JSON.stringify(req) });
        }
      }
    } catch (e) {
      return reply({ ok: false, error: String((e && e.message) || e) });
    }
    return realFetch(input, init);
  };

  /* Backup & restore: web wording and the attachments step */
  function attachmentsPanel() {
    const box = document.createElement("div");
    box.className = "panel";
    box.innerHTML = "<h2>Attachments from BuildCore desktop</h2>" +
      "<p>After restoring your desktop data, choose the desktop's <b>data\\files</b> folder (on Windows usually " +
      "<b>%LOCALAPPDATA%\\BuildCore\\data\\files</b>). Each photo and document is sent to your private file store " +
      "under its own name, so the links in BuildCore keep working. Files BuildCore does not know are skipped.</p>";
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.setAttribute("webkitdirectory", "");
    const btn = document.createElement("button");
    btn.className = "btn primary";
    btn.textContent = "Send the attachments";
    const out = document.createElement("p");
    btn.onclick = async () => {
      const files = Array.from(input.files || []);
      if (!files.length) { out.textContent = "Choose the folder first."; return; }
      const hd = { "X-Token": localStorage.getItem("bco_token") || "" };
      let sent = 0, skipped = 0, failed = 0;
      btn.disabled = true;
      for (const f of files) {
        try {
          const slot = await call("web.attachment_slot", { name: f.name }, hd);
          if (slot.skip) { skipped++; } else { await putSigned(slot.url, f, f.type); sent++; }
        } catch (e) { failed++; }
        out.textContent = "Sent " + sent + ", skipped " + skipped + (failed ? ", failed " + failed : "") + " of " + files.length + "…";
      }
      out.textContent = "Done: sent " + sent + ", skipped " + skipped + (failed ? ", failed " + failed + " (choose the folder again to retry)" : "") + ".";
      btn.disabled = false;
    };
    const act = document.createElement("div");
    act.className = "actions";
    act.append(btn);
    box.append(input, act, out);
    return box;
  }
  const seen = new WeakSet();
  new MutationObserver(() => {
    if (!/#\/?admin\/backup/.test(location.hash)) return;
    const head = Array.from(document.querySelectorAll("h1, h2")).find((x) => /Backup & restore/.test(x.textContent));
    if (!head) return;
    const page = head.closest("#main, main, .page, #app") || document.body;
    if (seen.has(head)) return;
    seen.add(head);
    const sub = head.parentElement && head.parentElement.querySelector("p, .sub, .muted");
    if (sub && /automatically every day/.test(sub.textContent))
      sub.textContent = "Download a backup to keep a copy of the company's data on your own computer. The file opens in BuildCore desktop too. Supabase also keeps its own copy of the database.";
    const panels = page.querySelectorAll(".panel");
    const last = panels[panels.length - 1];
    if (last && last.parentNode) last.parentNode.insertBefore(attachmentsPanel(), last.nextSibling);
  }).observe(document.documentElement, { childList: true, subtree: true });

  /* Forgotten password: a new one is set with the setup key, or an administrator is asked */
  async function tryApi(fn, args) {
    try { return await api(fn, args); } catch (e) { toast(e.message, "err"); throw e; }
  }
  function forgotDialog(username) {
    const field = (label, input) => h("label", { class: "f" }, h("span", {}, label), input);
    const user = h("input", { autocomplete: "username", value: username || "" });
    const key = h("input", { type: "password", autocomplete: "off" });
    const p1 = h("input", { type: "password", autocomplete: "new-password", placeholder: "6 or more characters" });
    const p2 = h("input", { type: "password", autocomplete: "new-password", placeholder: "type it again" });
    const note = h("input", { placeholder: "optional, e.g. your phone number" });
    const m = modal("Forgot password", h("div", {},
      h("p", { class: "muted" }, "Passwords are stored scrambled, so nobody can look yours up. You set a new one instead."),
      field("Username (or your full name)", user),
      h("h4", {}, "I have the setup key"),
      h("p", { class: "hint" }, "The value of BCO_SETUP_KEY in the Vercel project (Settings › Environment Variables). Usually only the owner has it."),
      field("Setup key", key), field("New password", p1), field("New password again", p2),
      h("h4", {}, "I don't have the setup key"),
      h("p", { class: "hint" }, "Send a request. An administrator sees it in Administration › Users and sets a new password for you."),
      field("Message for the administrator", note)), [
      { label: "Ask an administrator", act: async () => {
        if (!user.value.trim()) { toast("Type your username.", "err"); throw new Error("x"); }
        await tryApi("auth.reset_request", { username: user.value.trim(), note: note.value });
        toast("Request sent. An administrator will set a new password and tell you.");
      } },
      { label: "Set new password", cls: "primary", act: async () => {
        if (!user.value.trim()) { toast("Type your username.", "err"); throw new Error("x"); }
        if (!key.value.trim()) { toast("Enter the setup key, or use Ask an administrator.", "err"); throw new Error("x"); }
        if (p1.value.length < 6) { toast("The new password needs at least 6 characters.", "err"); throw new Error("x"); }
        if (p1.value !== p2.value) { toast("The two passwords are not the same.", "err"); throw new Error("x"); }
        const r = await tryApi("auth.reset_with_key", { username: user.value.trim(), setup_key: key.value, password: p1.value });
        toast("New password set for " + r.username + ". Sign in with it now.");
        const u = document.querySelector(".auth input[name=u]");
        if (u) u.value = r.username;
      } }], { narrow: true });
    return m;
  }
  const forgotSeen = new WeakSet();
  new MutationObserver(() => {
    const form = document.querySelector(".auth form.card:not(.gate)");
    if (!form || forgotSeen.has(form)) return;
    const title = form.querySelector("h2");
    const foot = form.querySelector(".foot");
    if (!title || title.textContent !== "Sign in" || !foot) return;
    forgotSeen.add(form);
    const u = form.querySelector("input[name=u]");
    // BuildCore's own "Forgot password?" stays; the web adds the setup-key way and "another company" below it
    foot.append(h("div", { style: "margin-top:8px" }, "On the web: ",
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); forgotDialog(u && u.value.trim()); } }, "reset with the setup key"),
        " or ask an administrator."),
      h("div", { style: "margin-top:10px;padding-top:10px;border-top:1px solid var(--line, #ddd)" },
        "Not this company? ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); leaveCompany(); location.hash = ""; location.reload(); } }, "Change company")));
  }).observe(document.documentElement, { childList: true, subtree: true });

  /* A new company from the sign-in page: for an office that has no company here yet (needs the company key) */
  function signupDialog() {
    const field = (label, input) => h("label", { class: "f" }, h("span", {}, label), input);
    const inp = (o) => h("input", o || {});
    const name = inp(), pan = inp(), addr = inp(), fy = inp({ placeholder: "e.g. 2083-84" }), fys = inp({ placeholder: "YYYY-MM-DD" });      // a plain box: the date helper needs a signed-in session
    const cid = inp({ placeholder: "e.g. himal-builders", autocomplete: "off" });
    const cp1 = inp({ type: "password", autocomplete: "new-password", placeholder: "6 or more characters" });
    const who = inp(), user = inp({ autocomplete: "off" });
    const p1 = inp({ type: "password", autocomplete: "new-password", placeholder: "6 or more characters" });
    const p2 = inp({ type: "password", autocomplete: "new-password", placeholder: "type it again" });
    const key = inp({ type: "password", autocomplete: "off" });
    modal("Set up a new company", h("div", {},
      h("p", { class: "muted" }, "The new company starts empty, with its own books, stores, projects, users and fiscal years. Nothing is shared with the other companies here. You become its administrator."),
      h("h4", {}, "Company"), field("Company name", name), h("div", { class: "grid" }, field("PAN", pan), field("Address", addr)),
      h("div", { class: "grid" }, field("First fiscal year", fy), field("It starts on (AD, Shrawan 1)", fys)),
      h("h4", {}, "Company sign-in"),
      h("p", { class: "hint" }, "Your staff type these first, each time on a new device, before their own username and password."),
      h("div", { class: "grid" }, field("Company ID", cid), field("Company password", cp1)),
      h("h4", {}, "Its administrator (you)"), field("Your full name", who), field("Username (you sign in with this)", user),
      h("div", { class: "grid" }, field("Password", p1), field("Password again", p2)),
      h("h4", {}, "Company key"),
      h("p", { class: "hint" }, "Ask the person who runs this BuildCore. It stops anyone who finds this address from making companies."),
      field("Company key", key)), [
      { label: "Create the company", cls: "primary", act: async () => {
        const bad = (m) => { toast(m, "err"); throw new Error("x"); };
        if (!name.value.trim()) bad("Type the company name.");
        if (!cid.value.trim()) bad("Choose a company ID.");
        if (cp1.value.length < 6) bad("The company password needs at least 6 characters.");
        if (!who.value.trim() || !user.value.trim()) bad("Type your full name and a username.");
        if (p1.value.length < 6) bad("The password needs at least 6 characters.");
        if (p1.value !== p2.value) bad("The two passwords are not the same.");
        if (fys.value.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(fys.value.trim())) bad("Type the start date as YYYY-MM-DD, or leave it empty.");
        if (!key.value.trim()) bad("Enter the company key.");
        const r = await tryApi("co.signup", { name: name.value, pan: pan.value, address: addr.value, fy: fy.value.trim(), fy_start: fys.value.trim(),
          admin_name: who.value, username: user.value, password: p1.value, company_key: key.value, company_id: cid.value, company_password: cp1.value });
        chooseCompany(r.code, r.ticket);
        LSs("bco_last_user", r.username);
        toast(r.name + " is ready. Sign in with your new username and password.");
        setTimeout(() => { location.hash = ""; location.reload(); }, 1200);
      } }], {});
  }

  /* The first page: company sign-in. No company's name is on it; the server refuses to say any until it passes. */
  const waitCss = document.createElement("style");
  waitCss.textContent = "html.bco-wait .auth{visibility:hidden}";
  document.head.append(waitCss);
  document.documentElement.classList.add("bco-wait");
  function showGate() {
    if (document.getElementById("bco-gate")) return;
    const id = h("input", { name: "company_id", autocomplete: "organization" }), pw = h("input", { name: "company_password", type: "password", autocomplete: "current-password" });
    const err = h("div", { class: "err", hidden: true });
    const btn = h("button", { class: "btn primary", type: "submit" }, "Continue");
    const go2 = async () => {
      err.hidden = true;
      btn.disabled = true;
      try {
        const r = await call("co.gate_login", { company_id: id.value, password: pw.value }, {});
        chooseCompany(r.code, r.ticket);
        location.hash = "";
        location.reload();
      } catch (e) { err.textContent = e.message; err.hidden = false; btn.disabled = false; pw.select(); }
    };
    const gate = h("div", { class: "auth", id: "bco-gate", style: "position:fixed;inset:0;z-index:40;overflow:auto" },
      h("div", { class: "brandside" },
        h("div", {}, h("h1", {}, "BuildCore"), h("p", {}, "Construction project control, stores, equipment and accounts, in one place.")),
        h("ul", {}, ["Daily progress, BOQ and billing", "Store, procurement and machines", "Accounts by fiscal year", "Each company's data is private"].map((t) => h("li", {}, t)))),
      h("form", { class: "card gate", onsubmit: (e) => { e.preventDefault(); go2(); } }, h("h2", {}, "Company sign-in"),
        h("p", { class: "muted" }, "Enter your company first. Then you sign in with your own username."), err,
        h("label", { class: "f" }, h("span", {}, "Company ID"), id),
        h("label", { class: "f" }, h("span", {}, "Company password"), pw), btn,
        h("div", { class: "foot" }, "New here? ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); signupDialog(); } }, "Set up a new company"),
          " with its own books, projects and users.")));
    document.body.append(gate);
    id.focus();
  }
  const gateSeen = new WeakSet();
  async function gateCheck() {
    try {
      const r = await realFetch("/api", { method: "POST", headers: { "Content-Type": "application/json", "X-Company": coCode(), "X-Company-Ticket": LSg(ticketKey(coCode())) || "" },
        body: JSON.stringify({ fn: "auth.status", args: {} }) });
      const j = await r.json();
      if (!j.ok && j.error === "COMPANY_LOGIN") showGate();
    } catch (e) { /* the sign-in screen says what is wrong */ }
    document.documentElement.classList.remove("bco-wait");
  }
  new MutationObserver(() => {
    const form = document.querySelector(".auth form.card:not(.gate)");
    if (!form || gateSeen.has(form)) return;
    gateSeen.add(form);
    gateCheck();
  }).observe(document.documentElement, { childList: true, subtree: true });

  /* someone already signed in keeps working: this browser gets its company ticket without asking */
  if (LSg("bco_token") && !LSg(ticketKey(coCode()))) {
    call("co.gate_ticket", {}, { "X-Token": LSg("bco_token"), "X-Company": coCode() }).then((r) => LSs(ticketKey(r.code), r.ticket)).catch(() => { /* signs in again */ });
  }

  /* Administration › Companies: this company's sign-in */
  function gatePanel(d) {
    const id = h("input", { value: d.company_id }), p1 = h("input", { type: "password", autocomplete: "new-password", placeholder: d.has_password ? "leave blank to keep" : "6 or more characters" }), p2 = h("input", { type: "password", autocomplete: "new-password" });
    const lab = (t, el) => h("label", { class: "f" }, h("span", {}, t), el);
    return h("div", { class: "panel", style: "margin-bottom:14px" }, h("h3", {}, "Company sign-in"),
      h("p", { class: "hint" }, d.has_password ? "Your staff type these first on a new device, before their own username and password. Changing the password signs every other device out of this page until they type the new one."
        : "This company has no company password yet: the setup key opens it for now. Choose a company ID and password, then give them to your staff."),
      h("div", { class: "grid" }, lab("Company ID", id), lab("New company password", p1), lab("New password again", p2)),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
        if (p1.value !== p2.value) return toast("The two passwords are not the same.", "err");
        const r = await tryApi("co.gate_set", { company_id: id.value, password: p1.value });
        LSs(ticketKey(r.code), r.ticket);
        toast("Company sign-in saved.");
        p1.value = p2.value = "";
      } }, "Save")));
  }
  const coSeen = new WeakSet();
  new MutationObserver(async () => {
    if (!/#\/?admin\/companies/.test(location.hash)) return;
    const page = document.querySelector("#page");
    const head = page && page.querySelector("h1");
    if (!head || coSeen.has(head) || !can("admin", "edit")) return;
    coSeen.add(head);
    let d;
    try { d = await api("co.gate_ticket", {}); } catch (e) { return; }
    const bar = head.closest(".bar") || head;
    if (head.isConnected) bar.parentNode.insertBefore(gatePanel(d), bar.nextSibling);
  }).observe(document.documentElement, { childList: true, subtree: true });

  /* Administration › Users: requests from people who forgot their password */
  function requestsPanel(rows) {
    const box = h("div", { class: "panel", style: "margin-bottom:14px" }, h("h3", {}, "Password reset requests (" + rows.length + ")"),
      h("p", { class: "hint" }, "These people forgot their password. Set a new one and tell them in person or by phone."));
    for (const r of rows) {
      const line = h("div", { class: "bar", style: "gap:8px;align-items:center;padding:6px 0;border-top:1px solid var(--line, #ddd)" },
        h("div", { class: "grow" }, h("b", {}, r.username), r.name ? " (" + r.name + ")" : "", " · " + String(r.ts || "").replace("T", " ").slice(0, 16),
          r.note ? h("div", { class: "muted" }, r.note) : null, r.user_id ? null : h("div", { class: "muted" }, "This user no longer exists.")),
        r.user_id ? h("button", { class: "btn small primary", onclick: () => {
          const p1 = h("input", { type: "password", autocomplete: "new-password", placeholder: "6 or more characters" });
          modal("New password for " + r.username, h("div", {}, h("label", { class: "f" }, h("span", {}, "New password"), p1),
            h("p", { class: "hint" }, "This also unlocks the user and signs them out everywhere.")), [{ label: "Set password", cls: "primary", act: async () => {
            if (p1.value.length < 6) { toast("The new password needs at least 6 characters.", "err"); throw new Error("x"); }
            await tryApi("web.pw_request_done", { id: r.id, password: p1.value });
            toast("New password set for " + r.username + ".");
            line.remove();
          } }], { narrow: true });
        } }, "Set new password") : null,
        h("button", { class: "btn small", onclick: async () => { await tryApi("web.pw_request_done", { id: r.id }); line.remove(); } }, "Dismiss"));
      box.append(line);
    }
    return box;
  }
  const usersSeen = new WeakSet();
  new MutationObserver(async () => {
    if (!/#\/?admin\/users/.test(location.hash)) return;
    const page = document.querySelector("#page");
    const head = page && page.querySelector("h1");
    if (!head || usersSeen.has(head)) return;
    usersSeen.add(head);
    let rows = [];
    try { rows = await api("web.pw_requests", {}); } catch (e) { return; }
    if (!rows.length || !head.isConnected) return;
    const bar = head.closest(".bar") || head;
    bar.parentNode.insertBefore(requestsPanel(rows), bar.nextSibling);
  }).observe(document.documentElement, { childList: true, subtree: true });

  /* Two-step sign-in: a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator...)
     after the password. The server answers a correct password with TOTP_CODE (asks for the code) or TOTP_SETUP
     (company requires it, not set up yet: shows the QR code); the sign-in is sent again with the code. */
  function qrBox(text) {
    const qr = window.qrcode(0, "M");
    qr.addData(text); qr.make();
    const n = qr.getModuleCount(), size = 200, c = size / (n + 8);
    let d = "";
    for (let r = 0; r < n; r++) for (let k = 0; k < n; k++) if (qr.isDark(r, k)) d += `M${(k + 4) * c},${(r + 4) * c}h${c}v${c}h-${c}z`;
    const box = h("div", { style: "text-align:center;margin:8px 0" });
    box.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" style="border-radius:8px"><rect width="100%" height="100%" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
    return box;
  }
  const spaced = (s) => String(s || "").replace(/(.{4})/g, "$1 ").trim();
  function setupSteps(secret, uri) {
    return h("div", {},
      h("ol", { style: "margin:0 0 6px 18px;padding:0" },
        h("li", {}, "Install ", h("b", {}, "Google Authenticator"), " on your phone (Play Store or App Store)."),
        h("li", {}, "In the app tap ", h("b", {}, "+"), " then ", h("b", {}, "Scan a QR code"), ", and scan this:")),
      qrBox(uri),
      h("p", { class: "hint", style: "text-align:center" }, "Can't scan? Choose “Enter a setup key” and type: ",
        h("b", { style: "font-family:monospace;user-select:all" }, spaced(secret))),
      h("p", { style: "margin:6px 0 0" }, "3. Type the 6-digit code the app now shows for BuildCore:"));
  }
  function codeInput() {
    return h("input", { inputmode: "numeric", autocomplete: "one-time-code", maxlength: "7", placeholder: "123456",
      style: "font-size:24px;letter-spacing:6px;text-align:center;width:100%" });
  }
  async function loginWithCode(input, init, req) {
    const r = await realFetch(input, init);
    let j;
    try { j = await r.clone().json(); } catch (e) { return r; }
    if (j.ok || typeof j.error !== "string" || !/^TOTP_(CODE|SETUP)/.test(j.error)) return r;
    let setup = null;
    if (j.error.indexOf("TOTP_SETUP:") === 0) { try { setup = JSON.parse(j.error.slice(11)); } catch (e) { /* asked for a code below */ } }
    return new Promise((resolve) => {
      let done = false;
      const code = codeInput();
      const send = async () => {
        const v = code.value.replace(/\D/g, "");
        if (v.length !== 6) { toast("Type the 6 digits from the app.", "err"); throw new Error("x"); }
        const body = JSON.stringify(Object.assign({}, req, { args: Object.assign({}, req.args, { otp: v }) }));
        const r2 = await realFetch(input, Object.assign({}, init, { body }));
        let j2 = {};
        try { j2 = await r2.clone().json(); } catch (e) { /* passed on as it is */ }
        if (!j2.ok && j2.error === "TOTP_WRONG") {
          toast("That code is not right. Type the code the app shows now; if it keeps failing, check that the phone's time is set automatically.", "err");
          code.value = ""; code.focus();
          throw new Error("x");
        }
        done = true;
        resolve(r2);
      };
      const body = setup
        ? h("div", {}, h("p", { class: "muted", style: "margin-top:0" }, "Your company asks everyone to use an authenticator app when signing in. Set it up once on this phone:"), setupSteps(setup.secret, setup.uri), code)
        : h("div", {}, h("p", { style: "margin-top:0" }, "Open ", h("b", {}, "Google Authenticator"), " on your phone and type the 6-digit code shown for BuildCore."), code,
          h("p", { class: "hint" }, "Lost your phone? Ask an administrator to reset two-step sign-in for you (Administration › Users)."));
      const m = modal(setup ? "Set up two-step sign-in" : "Two-step sign-in", body, [{ label: "Sign in", cls: "primary", act: send }],
        { narrow: true, onClose: () => { if (!done) resolve(reply({ ok: false, error: "Sign-in needs the 6-digit code from your authenticator app." })); } });
      code.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const b = m.el.querySelector("footer .btn.primary"); if (b) b.click(); } });
      code.focus();
    });
  }
  window.bcoLoginWithCode = loginWithCode;

  /* user menu › Two-step sign-in: turn it on (scan, confirm a code) or off (password) */
  async function totpDialog() {
    let st;
    try { st = await api("web.totp_status", {}); } catch (e) { toast(e.message, "err"); return; }
    if (st.on) {
      const pw = h("input", { type: "password", autocomplete: "current-password" });
      modal("Two-step sign-in", h("div", {},
        h("p", { style: "margin-top:0" }, "✅ On since " + String(st.since || "").replace("T", " ").slice(0, 16) + ". Each sign-in asks for the code from your authenticator app."),
        st.required ? h("p", { class: "hint" }, "Your company requires it, so it stays on. Changing phones? Ask an administrator to reset it, then set it up again at your next sign-in.")
          : [h("p", { class: "hint" }, "To turn it off, type your password."), h("label", { class: "f" }, h("span", {}, "Password"), pw)]),
      st.required ? [] : [{ label: "Turn off", cls: "warn", act: async () => {
        await tryApi("web.totp_disable", { password: pw.value });
        toast("Two-step sign-in is off.");
      } }], { narrow: true });
      return;
    }
    let s;
    try { s = await api("web.totp_begin", {}); } catch (e) { toast(e.message, "err"); return; }
    const code = codeInput();
    const m = modal("Turn on two-step sign-in", h("div", {},
      h("p", { class: "muted", style: "margin-top:0" }, "After your password, BuildCore will also ask for a 6-digit code from your phone, so a stolen password alone cannot open your account."),
      setupSteps(s.secret, s.uri), code), [{ label: "Turn on", cls: "primary", act: async () => {
      await tryApi("web.totp_enable", { code: code.value });
      toast("Two-step sign-in is on. You will need the app each time you sign in.");
    } }], { narrow: true });
    code.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const b = m.el.querySelector("footer .btn.primary"); if (b) b.click(); } });
  }
  new MutationObserver(() => {
    const list = document.querySelector(".usermenu-list");
    if (!list || list.querySelector(".bco-totp")) return;
    const pw = [...list.querySelectorAll("button")].find((b) => /Change password/.test(b.textContent));
    const b = h("button", { class: "bco-totp", onclick: () => { list.hidden = true; totpDialog(); } }, "Two-step sign-in (Authenticator)");
    if (pw) pw.after(b); else list.prepend(b);
  }).observe(document.documentElement, { childList: true, subtree: true });

  /* Administration › Users: require it for everyone, see who has it, reset it for someone who changed phones */
  function totpPanel(d) {
    const box = h("div", { class: "panel", style: "margin-bottom:14px" });
    const paint = () => {
      const on = d.users.filter((x) => x.on_since).length;
      box.replaceChildren(h("h3", {}, "Two-step sign-in (Google Authenticator)"),
        h("p", { class: "hint" }, on + " of " + d.users.length + " active users have it on. " +
          (d.required ? "Required: people without it are shown the QR code right after their password and must set it up to get in."
            : "Optional: each person can turn it on from their user menu (top right).")),
        h("label", { style: "display:flex;gap:8px;align-items:center;margin:6px 0 10px" },
          h("input", { type: "checkbox", checked: d.required, onchange: async (e) => {
            const want = e.target.checked;
            if (want && !confirm("Require two-step sign-in for everyone?\n\nPeople who have not set it up will need their phone at their next sign-in. Make sure your own phone is set up first.")) { e.target.checked = false; return; }
            try { d.required = (await api("web.totp_require", { on: want })).required; toast(want ? "Two-step sign-in is now required." : "Two-step sign-in is now optional."); }
            catch (err) { e.target.checked = !want; toast(err.message, "err"); }
            paint();
          } }), h("b", {}, "Require it for everyone in this company")),
        h("details", {}, h("summary", { style: "cursor:pointer" }, "Who has it on"),
          h("div", {}, d.users.map((x) => h("div", { class: "bar", style: "gap:8px;align-items:center;padding:5px 0;border-top:1px solid var(--line, #ddd)" },
            h("div", { class: "grow" }, h("b", {}, x.name || x.username), " · " + x.username + " · " + String(x.role || "").replace(/_/g, " ")),
            x.on_since ? h("span", { class: "muted" }, "On since " + String(x.on_since).slice(0, 10)) : h("span", { class: "muted" }, "Not set up"),
            x.on_since ? h("button", { class: "btn small", onclick: async () => {
              if (!confirm("Reset two-step sign-in for " + (x.name || x.username) + "?\n\nUse this when they lost or changed their phone. They are signed out, and set it up again at their next sign-in (if required) or from their user menu.")) return;
              try { await api("web.totp_reset", { user_id: x.id }); x.on_since = null; toast("Reset for " + x.username + "."); paint(); } catch (err) { toast(err.message, "err"); }
            } }, "Reset") : null)))));
    };
    paint();
    return box;
  }
  const totpSeen = new WeakSet();
  new MutationObserver(async () => {
    if (!/#\/?admin\/users/.test(location.hash)) return;
    const page = document.querySelector("#page");
    const head = page && page.querySelector("h1");
    if (!head || totpSeen.has(head) || !can("admin", "edit")) return;
    totpSeen.add(head);
    let d;
    try { d = await api("web.totp_admin", {}); } catch (e) { return; }
    if (!head.isConnected) return;
    const bar = head.closest(".bar") || head;
    bar.parentNode.insertBefore(totpPanel(d), bar.nextSibling);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
