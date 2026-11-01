/* Working together: live activity, who is where, remote access and site packs. */
"use strict";

const KIND_WORDS = { work: "Site work", store: "Store", procure: "Procurement", accounts: "Accounts",
  commercial: "Billing", quality: "Quality", equipment: "Equipment", sync: "Link" };

function sinceWords(ts) {
  if (!ts) return "—";
  const s = Math.max(0, (Date.now() - new Date(ts.replace(" ", "T")).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " hr ago";
  return Math.round(s / 86400) + " days ago";
}
const clock = (ts) => (ts || "").slice(11, 16);

/* The strip of people working right now - used on the live page and the control room. */
function onlineStrip(list) {
  if (!list || !list.length) return h("p", { class: "muted" }, "Nobody else is signed in at the moment.");
  return h("div", { class: "whobar" }, list.map((p) => h("span", { class: "who-chip", title:
    (p.device || "") + " · last seen " + sinceWords(p.last_seen) },
    h("i", { class: "dot on" }), h("b", {}, p.name || p.username),
    h("span", {}, (p.location ? p.location + " · " : "") + p.role.replace(/_/g, " ")))));
}

function feedList(rows) {
  if (!rows.length) return h("p", { class: "muted" }, "Nothing has happened yet today.");
  const list = h("div", { class: "feed" });
  let day = null;
  rows.forEach((r) => {
    const d = (r.ts || "").slice(0, 10);
    if (d !== day) { day = d; list.append(h("div", { class: "feed-day" }, d === today() ? "Today" : d)); }
    list.append(h("a", { class: "feed-row", href: r.link || "#/p/today", onclick: () => { if (r.project_id) setProject(r.project_id, true); } },
      h("i", { class: "k k-" + (r.kind || "work") }, KIND_WORDS[r.kind] || r.kind),
      h("div", { class: "grow" },
        h("b", {}, (r.user_name || "Someone") + " " + r.title),
        h("span", { class: "muted" }, [r.detail, r.project_id ? nm.pcode(r.project_id) : null, r.location].filter(Boolean).join(" · "))),
      r.amount ? h("span", { class: "amt" }, fmtMoney(r.amount)) : null,
      h("span", { class: "tm" }, clock(r.ts))));
  });
  return list;
}

/* ── live activity: what the owner watches from anywhere ── */
PAGES["p/live"] = async (root, params) => {
  const mine = params.scope !== "all";
  const d = await run("team.feed", { project_id: mine && S.project ? S.project : null, limit: 80 });
  const t = await api("team.tick", { since_id: d.last_id, project_id: S.project || null }).catch(() => ({ online: [] }));
  LIVE.seen = d.last_id;
  root.append(pageHead("Live activity",
    (mine && S.project ? nm.project(S.project) : "All projects") + " · updates by itself every " + (LIVE.every / 1000) + " seconds",
    h("button", { class: "btn", onclick: () => { location.hash = "#/p/live?scope=" + (mine ? "all" : "project"); } },
      mine ? "Show all projects" : "Show this project only"),
    h("button", { class: "btn", onclick: () => go() }, "Refresh now")));
  root.append(h("div", { class: "panel" }, h("h2", {}, "Working right now (" + (t.online || []).length + ")"),
    onlineStrip(t.online)));
  root.append(h("div", { class: "panel" }, h("h2", {}, "As it happens"), feedList(d.rows)));
};
PAGES["p/live"].live = true;

/* ── team & devices ── */
PAGES["admin/team"] = async (root) => {
  const p = await run("team.presence", {});
  const ses = can("admin", "view") ? await run("team.sessions", {}) : [];
  root.append(pageHead("Team", (p.site_name || "This computer") + " · " + p.online + " signed in now",
    can("admin", "edit") ? h("button", { class: "btn primary", onclick: () => { location.hash = "#/admin/users"; } }, "Add or edit people") : null));
  root.append(h("div", { class: "panel" }, h("h2", {}, "Working right now"),
    onlineStrip(p.people.filter((x) => x.online))));
  root.append(h("div", { class: "panel" }, h("h2", {}, "Everyone"),
    table([{ k: "name", label: "Name" }, { k: "username", label: "Username" },
      { label: "Role", v: (r) => r.role.replace(/_/g, " ") }, { k: "location", label: "Works from" },
      { k: "phone", label: "Phone" },
      { label: "Now", v: (r) => r.online ? h("span", { class: "stamp st-approved" }, "online") : "" },
      { label: "Last seen", v: (r) => sinceWords(r.last_seen) },
      { label: "Active", v: (r) => r.active ? "yes" : "no" }], p.people, { search: false })));
  if (ses.length) {
    root.append(h("div", { class: "panel" }, h("h2", {}, "Signed-in computers"),
      h("p", { class: "hint" }, "End a sign-in if a laptop or phone was lost, or somebody left the company."),
      table([{ k: "name", label: "Person" }, { k: "device", label: "Computer" }, { k: "ip", label: "Address" },
        { label: "Signed in", v: (r) => (r.created || "").slice(0, 16).replace("T", " ") },
        { label: "Last used", v: (r) => sinceWords(r.last_seen || r.created) },
        { label: "", v: (r) => can("admin", "edit") ? h("button", { class: "btn small", onclick: async (e) => {
          e.stopPropagation();
          if (await ask("End this sign-in?", (r.name || r.username) + " will have to sign in again on " + (r.device || "that computer") + ".", { ok: "End sign-in", danger: true })) {
            await run("team.signout", { token: r.token }, "Sign-in ended"); go();
          }
        } }, "End") : null }], ses, { search: false })));
  }
};

/* ── remote access: the setup instructions, written for a site manager ── */
PAGES["admin/remote"] = async (root) => {
  const i = await run("server.info", {});
  const f = form([
    { k: "site_name", label: "Name of this computer / office", hint: "Shown to everyone who connects, e.g. Head office, Kathmandu" },
    { k: "site_code", label: "Short code for site packs", hint: "Only needed if this copy works without internet, e.g. MKHEP" },
    { k: "session_days", label: "Sign-in lasts (days)", type: "number" },
    { k: "allow_public", label: "Allow computers outside the office network or VPN (not recommended)", type: "check" },
  ], { site_name: i.site_name, site_code: i.site_code, session_days: i.session_days || 30, allow_public: i.allow_public ? 1 : 0 });
  const addr = i.addresses || [];
  root.append(pageHead("Remote access", "How the site, the office and the owner work on the same project"));

  root.append(h("div", { class: "panel" }, h("h2", {}, "This computer"),
    kv([["BuildCore version", i.version], ["Name", i.site_name || "(not named)"],
      ["Reachable by others", i.mode === "network" ? "yes" : "no — only this computer"],
      ["Address for others", addr.length ? addr.join("   ") : "—"],
      ["Connection", i.tls ? "https (encrypted)" : "http (use a VPN outside the office)"],
      ["People", i.users + " users, " + i.online + " signed in now"],
      ["Data folder", i.data_dir]]),
    h("p", { class: "hint" }, i.mode === "network"
      ? "Others connect with the address above. Keep BuildCore open on this computer while they work."
      : "Switch sharing on in the BuildCore menu: Network → Share this computer with the office network.")));

  const step = (n, title, lines) => h("div", { class: "step" }, h("b", {}, n + ". " + title),
    h("ul", {}, lines.map((l) => h("li", {}, l))));
  root.append(h("div", { class: "panel" }, h("h2", {}, "Choose how your team is spread out"),
    h("div", { class: "cols3" },
      h("div", { class: "way" }, h("h3", {}, "A · One office, several desks"),
        h("p", { class: "muted" }, "Accounts, store and management in the same building."),
        step(1, "On the main computer", ["Open BuildCore → Network → Share this computer with the office network.",
          "Note the address it shows, e.g. " + (addr[0] || "http://192.168.1.10:8750") + ".",
          "Leave BuildCore open during office hours."]),
        step(2, "On every other computer", ["Install BuildCore, then Network → Connect to BuildCore on another computer.",
          "Type the address from step 1.", "Or simply open that address in Chrome or Edge."]),
        step(3, "Give each person their own sign-in", ["Administration → Users → New user.",
          "One username per person, with the role that matches their job."])),
      h("div", { class: "way" }, h("h3", {}, "B · Two cities, both with internet"),
        h("p", { class: "muted" }, "Accounts in Kathmandu, engineers at site, owner anywhere. This is the one you want."),
        step(1, "Pick one computer to hold the data", ["Usually the accounts computer in Kathmandu.",
          "It must stay switched on and connected while people work."]),
        step(2, "Join the computers with a private network (VPN)", [
          "Install Tailscale (free for small teams) on the office computer and on every site and owner computer.",
          "Sign in to Tailscale with the same account on all of them.",
          "Tailscale gives each computer a fixed private address like 100.x.x.x."]),
        step(3, "Share and connect", ["On the office computer: Network → Share this computer with the office network.",
          "On the other computers: Network → Connect to BuildCore on another computer, and type http://100.x.x.x:8750.",
          "The owner can also just open that address in a browser on a laptop or phone."]),
        step(4, "Nothing else to do", ["Everyone is now on the same database.",
          "A DPR approved at site is in the Kathmandu trial balance in the same second.",
          "This page and Live activity show who is working and what they have just done."])),
      h("div", { class: "way" }, h("h3", {}, "C · Site has no internet at all"),
        h("p", { class: "muted" }, "Tunnel face, remote hydropower site, no mobile signal."),
        step(1, "Install BuildCore at site as its own copy", ["Give it a short code in the box below, e.g. MKHEP.",
          "Create the same project code as head office."]),
        step(2, "Site works normally, offline", ["DPR, material issues and equipment logsheets are entered at site every day."]),
        step(3, "Send a site pack when someone travels or a signal appears", [
          "Administration → Site packs → Make a pack for the dates concerned.",
          "Carry the file on a pen drive or phone, or e-mail it."]),
        step(4, "Head office loads the pack", ["Administration → Site packs → Load a pack.",
          "Reports arrive as 'submitted' and issues as drafts; Kathmandu checks, approves and posts them.",
          "Loading the same pack twice changes nothing — nothing is ever doubled."])))));

  root.append(h("div", { class: "panel" }, h("h2", {}, "Safety"),
    h("ul", { class: "plain" },
      h("li", {}, "BuildCore refuses connections from the open internet unless you switch the box below on. "
        + "Use a VPN such as Tailscale instead — it is safer and needs no router settings."),
      h("li", {}, "Never open port 8750 on your router to the internet."),
      h("li", {}, "Each person must have their own username. Sharing one login loses the record of who did what."),
      h("li", {}, "Five wrong passwords lock a username for a few minutes."),
      h("li", {}, "The computer holding the data is the one to back up: Administration → Backup & restore.")),
    f, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const v = f.values();
      await run("server.access", { site_name: v.site_name, site_code: (v.site_code || "").toUpperCase(),
        session_days: v.session_days, allow_public: v.allow_public ? "1" : "0" }, "Saved");
      go();
    } }, "Save"))));
};

/* ── site packs ── */
PAGES["admin/sync"] = async (root) => {
  const i = await run("server.info", {});
  const packs = await run("team.packs", {});
  root.append(pageHead("Site packs", "Carry a day's work between two BuildCore computers that cannot reach each other"));
  if (!i.site_code) {
    root.append(h("div", { class: "panel warn" }, h("b", {}, "Name this copy first."),
      h("p", {}, "Give this computer a short code (Administration → Remote access) so packs can never be mixed up. "
        + "Head office is usually HO; a site is usually the project code."),
      h("button", { class: "btn primary", onclick: () => { location.hash = "#/admin/remote"; } }, "Go to Remote access")));
  }

  const ef = form([
    { k: "project_id", label: "Project", type: "select", options: S.L.projects.map((p) => [p.id, p.code + " — " + p.name]), noBlank: true },
    { k: "from", label: "From date", type: "date" }, { k: "to", label: "To date", type: "date" },
    { k: "note", label: "Note for head office" },
  ], { project_id: S.project || (S.L.projects[0] || {}).id, from: today(), to: today() });
  root.append(h("div", { class: "panel" }, h("h2", {}, "1 · Make a pack (at site)"),
    h("p", { class: "hint" }, "Includes daily progress reports, material issues and equipment logsheets entered on THIS computer."),
    ef, h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      const v = ef.values();
      const d = await run("team.pack_export", v);
      const blob = new Blob([JSON.stringify(d.pack)], { type: "application/json" });
      const a = h("a", { href: URL.createObjectURL(blob), download: d.filename });
      document.body.append(a); a.click(); a.remove();
      toast("Pack saved: " + Object.entries(d.counts).map(([k, n]) => n + " " + k).join(", "), "ok");
      go();
    } }, "Make the pack file"))));

  const file = h("input", { type: "file", accept: ".bcpack,.json" });
  const out = h("div");
  root.append(h("div", { class: "panel" }, h("h2", {}, "2 · Load a pack (at head office)"),
    h("p", { class: "hint" }, "The same pack can be loaded twice without doubling anything. "
      + "Daily progress reports arrive as “submitted” and material issues as drafts: check them here, "
      + "then approve and post so that cost and stock move in the head-office accounts."),
    h("div", { class: "bar" }, file, h("button", { class: "btn", onclick: async () => {
      if (!file.files[0]) return toast("Choose the pack file first.", "err");
      const text = await file.files[0].text();
      let prev;
      try { prev = await run("team.pack_preview", { pack: text }); } catch (e) { return; }
      out.innerHTML = "";
      out.append(kv([["From", (prev.site_name || prev.site_code) + " · made " + (prev.made || "").replace("T", " ")],
        ["Made by", prev.made_by], ["Project", prev.project_code + " " + (prev.project_name || "")],
        ["Dates", prev.from + " to " + prev.to],
        ["In the pack", Object.entries(prev.counts || {}).map(([k, n]) => n + " " + k).join(", ") || "nothing"],
        ["New here", Object.entries(prev.new || {}).map(([k, n]) => n + " " + k).join(", ")]]));
      if (!prev.project_known) {
        out.append(h("p", { class: "red" }, "Project " + prev.project_code + " does not exist on this computer. "
          + "Create it with exactly that code first."));
        return;
      }
      out.append(h("button", { class: "btn primary", onclick: async () => {
        const r = await run("team.pack_import", { pack: text, filename: file.files[0].name },
          (d) => "Loaded " + d.added.dpr + " DPR, " + d.added.issues + " issues, " + d.added.logsheets + " logsheets");
        if (r.problems.length) {
          modal("Loaded, with notes", h("div", {}, h("p", {}, "Everything that could be matched was loaded. These need attention:"),
            h("ul", {}, r.problems.map((x) => h("li", {}, x)))), [], {});
        }
        go();
      } }, "Load these records"));
    } }, "Check the file")), out));

  root.append(h("div", { class: "panel" }, h("h2", {}, "History"),
    table([{ label: "When", v: (r) => (r.ts || "").slice(0, 16).replace("T", " ") },
      { label: "Direction", v: (r) => r.direction === "out" ? "made here" : "loaded here" },
      { k: "site_code", label: "Site" }, { label: "Project", v: (r) => nm.pcode(r.project_id) },
      { k: "filename", label: "File" },
      { label: "Records", v: (r) => JSON.stringify(r.counts).replace(/[{}"]/g, "").replace(/,/g, ", ") },
      { k: "note", label: "Note" }], packs, { search: false, empty: "No packs yet." })));
};

/* ── the poller that makes the app feel live ── */
const LIVE = { every: 15000, seen: 0, timer: null, online: 0, failures: 0 };

function liveBadge() {
  return h("span", { class: "livewrap", id: "livewrap", title: "People working now" },
    h("i", { class: "dot" }), h("b", { id: "livecount" }, "—"),
    h("a", { href: "#/p/live" }, "live"));
}

async function liveTick() {
  if (!S.user || document.hidden) return;
  let t;
  try { t = await api("team.tick", { since_id: LIVE.seen, project_id: S.project || null }); } catch (e) { LIVE.failures++; return; }
  LIVE.failures = 0;
  const wrap = $("#livewrap");
  if (wrap) {
    $("#livecount").textContent = (t.online || []).length;
    wrap.querySelector(".dot").className = "dot on";
    wrap.title = (t.online || []).map((p) => (p.name || p.username) + (p.location ? " (" + p.location + ")" : "")).join("\n") || "Only you";
  }
  if (t.new && LIVE.seen) {
    const page = PAGES[parseHash().path];
    if (page && page.live) { LIVE.seen = t.last_id; return go(); }
    if (t.latest) toast((t.latest.user_name || "Someone") + " " + t.latest.title, "ok");
  }
  LIVE.seen = t.last_id;
}

function startLive() {
  if (LIVE.timer) clearInterval(LIVE.timer);
  LIVE.timer = setInterval(liveTick, LIVE.every);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) liveTick(); });
  liveTick();
}
