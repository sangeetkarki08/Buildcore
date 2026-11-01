/* BuildCore web edition - the browser side of the few web differences. Loaded before every screen.
 *
 *  - files larger than a web request can carry go straight to the private file store with a one-time link
 *  - restore sends the desktop data file the same way, then the server imports it
 *  - the first administrator needs the setup key from the Vercel settings
 *  - Backup & restore gets a step to bring the desktop's attachments (data\files folder) across
 */
(function () {
  "use strict";
  const BIG = 4 * 1024 * 1024;
  const realFetch = window.fetch.bind(window);

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
})();
