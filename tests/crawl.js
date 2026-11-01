// Visit every screen (company workspace, then a project workspace) and record server/database errors.
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://127.0.0.1:8760";
const USER = process.env.U || "admin", PASS = process.env.P || "admin12345";
const PROJECT = +(process.env.PROJECT || 3);
const BAD = /SQL|Operational|Unexpected error|Server error|syntax|does not exist|operator|invalid input|could not|psycopg|Traceback|must appear|ambiguous|datatype|function .*\(|argument of/i;
(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome" });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const tok = await (await fetch(BASE + "/api", { method: "POST", body: JSON.stringify({ fn: "auth.login", args: { username: USER, password: PASS } }) })).json();
  if (!tok.ok) { console.log("login failed", tok); process.exit(1); }
  const problems = [];
  let current = "";
  page.on("pageerror", (e) => problems.push({ page: current, kind: "js", msg: String(e.message).slice(0, 300) }));
  page.on("response", async (r) => {
    if (!r.url().includes("/api")) return;
    let j = null, req = null;
    try { req = r.request().postData(); } catch (e) {}
    try { j = await r.json(); } catch (e) { if (r.status() >= 500) problems.push({ page: current, kind: "http" + r.status(), msg: r.url() }); return; }
    if (j && j.ok === false && BAD.test(j.error || "")) problems.push({ page: current, kind: "api", fn: (req || "").slice(0, 120), msg: (j.error || "").slice(0, 400) });
  });
  await page.goto(BASE + "/");
  await page.evaluate((t) => { localStorage.setItem("bco_token", t); for (const v of ["2.24.0","2.25.0","2.26.0","2.27.0","2.28.0","2.29.0","2.30.0","2.31.0","2.32.0","2.33.0","2.34.0","2.35.0"]) localStorage.setItem("bco_seen_" + v, "1"); }, tok.data.token);
  let visited = 0, shown = 0;
  for (const ws of [{ workspace: "company" }, { workspace: "project", project_id: PROJECT }]) {
    await page.goto(BASE + "/");
    await page.waitForTimeout(1500);
    await page.evaluate(async (w) => { await api("ws.enter", w); }, ws);
    await page.goto(BASE + "/#/dashboard");
    await page.waitForTimeout(2500);
    // the workspace chooser (2.20+) opens first after sign-in: pick the workspace on it, as a person would
    if (await page.locator("text=Where will you work?").count()) {
      if (ws.workspace === "company") await page.locator("button.wscard").first().click();
      else await page.locator(".wsproj button").filter({ hasText: process.env.PROJECT_CODE || "ROAD" }).first().click();
      await page.waitForTimeout(2500);
    }
    const keys = await page.evaluate(() => Object.keys(PAGES));
    for (const k of keys) {
      current = ws.workspace + ":" + k;
      try {
        await page.evaluate((k) => { location.hash = "#/" + k; }, k);
        await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(250);
        const txt = await page.evaluate(() => { const p = document.querySelector("#page"); return p ? p.innerText.slice(0, 2000) : "\u0000"; });
        if (txt === "\u0000") problems.push({ page: current, kind: "noscreen", msg: "no #page on this screen" });
        else if (txt.trim()) shown++;
        const m = txt.match(/This page could not load\.\s*\n?(.*)/);
        if (m && BAD.test(m[1] || "")) problems.push({ page: current, kind: "page", msg: (m[1] || "").slice(0, 300) });
        visited++;
      } catch (e) { problems.push({ page: current, kind: "nav", msg: String(e).slice(0, 200) }); }
    }
  }
  console.log(JSON.stringify({ visited, shown, problems }, null, 1));
  await browser.close();
})();
