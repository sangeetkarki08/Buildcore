// Browser check used during development: setup key, restore of a desktop data file, attachments folder, file links.
// Needs Playwright, tools/dev_server.py and tools/dev_storage.py running, and a desktop backup at the paths below.
const { chromium } = require("playwright");
const BASE = "http://127.0.0.1:8760";
(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const dialogs = [];
  page.on("dialog", async (d) => { dialogs.push(d.type() + ": " + d.message()); if (d.type() === "prompt") await d.accept(process.env.SETUP_KEY || ""); else await d.accept(); });
  page.on("pageerror", (e) => console.log("JS ERROR", e.message));
  await page.goto(BASE + "/"); await page.waitForTimeout(1500);
  await page.fill("input[name=company_name]", "Web Test Co"); await page.fill("input[name=name]", "Web Admin");
  await page.fill("input[name=password]", "webadmin1"); await page.fill("input[name=password2]", "webadmin1");
  await page.locator("form.card button[type=submit], form.card .btn.primary").last().click(); await page.waitForTimeout(3000);
  console.log("err line:", await page.locator(".err").first().innerText().catch(() => ""));
  console.log("after setup, hash:", await page.evaluate(() => location.hash), "token:", !!(await page.evaluate(() => localStorage.getItem("bco_token"))));
  await page.evaluate(() => { for (const v of ["2.24.0","2.25.0","2.26.0","2.27.0","2.28.0","2.29.0"]) localStorage.setItem("bco_seen_" + v, "1"); location.hash = "#/admin/backup"; });
  await page.waitForTimeout(2500);
  console.log("subtitle:", await page.locator("#page p").first().innerText().catch(() => "?"));
  console.log("attachments panel:", await page.locator("text=Attachments from BuildCore desktop").count());
  for (let i = 0; i < 4 && await page.locator(".overlay").count(); i++) {
    console.log("overlay:", (await page.locator(".overlay").first().innerText()).slice(0, 160).replace(/\n/g, " | "));
    await page.keyboard.press("Escape"); await page.waitForTimeout(400);
    if (await page.locator(".overlay").count()) await page.locator(".overlay button").last().click().catch(() => {});
    await page.waitForTimeout(400);
  }
  await page.locator('input[type=file][accept=".db"]').setInputFiles("/tmp/claude-0/rt/desk.db");
  await page.click("text=Restore from file"); await page.waitForTimeout(500);
  await page.locator(".overlay button.warn").last().click();
  await page.waitForTimeout(15000);
  console.log("dialogs:", JSON.stringify(dialogs));
  // sign in as the desktop admin
  const tok = await page.evaluate(async () => (await (await fetch("/api", { method: "POST", body: JSON.stringify({ fn: "auth.login", args: { username: "admin", password: "admin12345" } }) })).json()));
  console.log("desktop login:", tok.ok);
  await page.evaluate((t) => { localStorage.setItem("bco_token", t); location.hash = "#/admin/backup"; location.reload(); }, tok.data.token);
  await page.waitForTimeout(3000);
  if (!(await page.locator("input[webkitdirectory]").count())) {
    console.log("screen:", (await page.locator("body").innerText()).slice(0, 400).replace(/\n/g, " | "));
    console.log("ws.enter:", await page.evaluate(async () => { try { return JSON.stringify(await api("ws.enter", { workspace: "company" })).slice(0, 200); } catch (e) { return "ERR " + e.message; } }));
    await page.goto(BASE + "/#/dashboard"); await page.reload(); await page.waitForTimeout(2500);
    for (let i = 0; i < 4 && await page.locator(".overlay").count(); i++) { await page.keyboard.press("Escape"); await page.waitForTimeout(400); }
    await page.evaluate(() => { location.hash = "#/admin/backup"; }); await page.waitForTimeout(2500);
  }
  console.log("now:", await page.evaluate(() => location.hash), (await page.locator("body").innerText()).slice(0, 300).replace(/\n/g, " | "));
  const dir = page.locator("input[webkitdirectory]");
  await dir.setInputFiles("/tmp/claude-0/rt/files");
  for (let i = 0; i < 6 && await page.locator(".overlay").count(); i++) { await page.keyboard.press("Escape"); await page.waitForTimeout(300); if (await page.locator(".overlay").count()) await page.locator(".overlay button").last().click().catch(() => {}); await page.waitForTimeout(300); }
  await page.click("text=Send the attachments"); await page.waitForTimeout(4000);
  console.log("attach result:", await page.locator("text=/Done: sent/").innerText());
  const r = await page.evaluate(async () => { const x = await fetch("/files/1?token=" + localStorage.getItem("bco_token")); const b = await x.arrayBuffer(); return [x.status, b.byteLength, x.url.slice(0, 60)]; });
  console.log("file 1:", JSON.stringify(r));
  await browser.close();
})();
