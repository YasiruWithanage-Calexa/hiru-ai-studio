// Walk the studio like a person would, recording every request the browser makes to the API.
// node walk.js [dwellMs] [idleMs]
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const ids = JSON.parse(fs.readFileSync(path.join(__dirname, "ids.json"), "utf8"));
const WEB = "http://localhost:3030";
const API = "http://localhost:8001";
const DWELL = Number(process.argv[2] || 8000);
const IDLE = Number(process.argv[3] || 75000);
const out = fs.createWriteStream(path.join(__dirname, "browser.jsonl"));
let step = "start";
const log = (o) => out.write(JSON.stringify({ at: Date.now() / 1000, step, ...o }) + "\n");

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();
  page.on("request", (req) => {
    const u = req.url();
    if (u.startsWith(API) || u.includes("supabase.co"))
      log({ ev: "req", method: req.method(), url: u.replace(API, "").replace(/https:\/\/[^/]+supabase\.co/, "SB"), type: req.resourceType() });
  });
  page.on("response", (res) => {
    const u = res.url();
    if (u.startsWith(API)) log({ ev: "res", status: res.status(), url: u.replace(API, ""), fromCache: res.fromServiceWorker() });
  });
  page.on("console", (m) => { if (m.type() === "error") log({ ev: "console", text: m.text().slice(0, 300) }); });
  page.on("pageerror", (e) => log({ ev: "pageerror", text: String(e).slice(0, 300) }));

  const mark = (name) => { step = name; log({ ev: "step" }); console.log(new Date().toISOString(), name); };
  const visit = async (name, url, dwell = DWELL) => {
    mark(name);
    try { await page.goto(WEB + url, { waitUntil: "domcontentloaded", timeout: 60000 }); } catch (e) { log({ ev: "nav-error", text: String(e).slice(0, 200) }); }
    await page.waitForTimeout(dwell);
  };

  // sign in
  mark("login");
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto(WEB + "/login", { waitUntil: "networkidle", timeout: 90000 });
    await page.waitForTimeout(3000); // hydration
    await page.locator('input[type="email"], input[name="email"]').first().fill(ids.email);
    await page.locator('input[type="password"]').first().fill(ids.password);
    await page.click('button[type="submit"]');
    const ok = await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }).then(() => true).catch(() => false);
    if (ok) break;
    log({ ev: "login-retry", text: await page.locator("body").innerText().catch(() => "") });
  }
  console.log("after login:", page.url());
  await page.waitForTimeout(4000);

  const P = `/productions/${ids.P}`;
  const ep = ids.episodes[0];
  const sc = ep.scenes[0];
  const shot = sc.shots[0];
  const S = `${P}/episodes/${ep.id}/scenes/${sc.id}`;

  await visit("productions-list", "/productions");
  await visit("production-overview", P);
  await visit("episode", `${P}/episodes/${ep.id}`);
  await visit("scene-director", `${S}/director`);
  await visit("shot-workspace", `${S}/shots/${shot}/workspace`);
  await visit("shot-production", `${S}/shots/${shot}/production`);
  await visit("shot-handoff", `${S}/shots/${shot}/handoff`);
  await visit("canon", `${P}/canon`);
  await visit("canon-entity", `${P}/canon/${ids.canon[0]}`);
  await visit("documents", `${P}/documents`);
  await visit("members", `${P}/members`);
  await visit("activity", `${P}/activity`);
  await visit("questions", `${P}/questions`);

  // Client-side: step through the shots of one scene by clicking (the way a director reviews a scene).
  await visit("handoff-walk-open", `${S}/shots/${sc.shots[1]}/handoff`);
  for (let i = 2; i < sc.shots.length; i++) {
    mark(`handoff-walk-click-${i + 1}`);
    const link = page.locator(`a[href*="/shots/${sc.shots[i]}"]`).first();
    if (await link.count()) { await link.click().catch(() => {}); } else { log({ ev: "no-link", shot: sc.shots[i] }); await page.goto(WEB + `${S}/shots/${sc.shots[i]}/handoff`); }
    await page.waitForTimeout(4000);
  }
  // Client-side: other scenes of the episode from the episode page.
  await visit("episode-again", `${P}/episodes/${ep.id}`, 4000);
  for (let i = 1; i < ep.scenes.length; i++) {
    mark(`episode-click-scene-${i + 1}`);
    const link = page.locator(`a[href*="/scenes/${ep.scenes[i].id}"]`).first();
    if (await link.count()) { await link.click().catch(() => {}); await page.waitForTimeout(5000); await page.goBack().catch(() => {}); }
    else log({ ev: "no-link", scene: ep.scenes[i].id });
    await page.waitForTimeout(3000);
  }

  // Idle: nothing queued, so nothing should be fetched.
  await visit("idle-shot-handoff", `${S}/shots/${shot}/handoff`, IDLE);
  await visit("idle-scene-director", `${S}/director`, IDLE);
  await visit("idle-overview", P, IDLE);

  // Reload: what a second open costs.
  await visit("reload-shot-handoff", `${S}/shots/${shot}/handoff`);
  mark("end");
  await browser.close();
  out.end();
})();
