// The pages of the creation walk's production, nothing running (plan/2026-11-13d phase 4 and 7):
// productions list, documents (where "Create and upload" lands), overview, an episode, a scene's director page, a
// shot's workspace, then the next shot by a click.     node pages.js <label> [dwellMs]
const path = require("path");
const fs = require("fs");
const { chromium } = require(path.join(__dirname, "../../2026-11-13b/measure/node_modules/playwright-core"));

const ids = JSON.parse(fs.readFileSync(path.join(__dirname, "create.json"), "utf8"));
const LABEL = process.argv[2] || "pages";
const DWELL = Number(process.argv[3] || 7000);
const API = "http://localhost:8001";
const WEB = "http://localhost:3030";
const out = fs.createWriteStream(path.join(__dirname, `browser.${LABEL}.jsonl`));
let step = "start";
const log = (o) => out.write(JSON.stringify({ at: Date.now() / 1000, step, ...o }) + "\n");
const mark = (name) => { step = name; log({ ev: "step" }); console.log(new Date().toISOString(), name); };

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  page.on("request", (q) => { if (q.url().startsWith(API)) log({ ev: "req", method: q.method(), url: q.url().replace(API, "") }); });
  page.on("response", (r) => { if (r.url().startsWith(API) && r.status() >= 400) log({ ev: "console", text: `${r.status()} ${r.url().replace(API, "")}` }); });
  mark("login");
  await page.goto(WEB + "/login", { waitUntil: "networkidle" });
  await page.waitForTimeout(3000);
  await page.locator('input[type="email"]').first().fill(ids.email);
  await page.locator('input[type="password"]').first().fill(ids.password);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(3000);
  const P = `/productions/${ids.P}`;
  const visit = async (name, url) => { mark(name); await page.goto(WEB + url, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {}); await page.waitForTimeout(DWELL); };
  const click = async (name, selector) => {
    const link = page.locator(selector).first();
    if (!(await link.count())) { log({ ev: "no-link", text: selector }); return false; }
    mark(name);
    await link.click().catch(() => {});
    await page.waitForTimeout(DWELL);
    return true;
  };
  await visit("productions", "/productions");
  await visit("documents", `${P}/documents`);
  await visit("overview", P);
  await click("episode", `a[href*="${P}/episodes/"]`);
  if (await click("scene-director", 'a[href*="/scenes/"]')) {
    const hrefs = await page.locator('a[href*="/shots/"]').evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    const shots = [...new Set(hrefs.map((h) => h.split("/shots/")))].filter((p) => p.length === 2)
      .map(([head, tail]) => ({ head, id: tail.split("/")[0] }));
    const ids = [...new Set(shots.map((s) => s.id))];
    if (ids.length) {
      await visit("shot-workspace", `${shots[0].head}/shots/${ids[0]}/workspace`);
      if (ids[1]) await click("shot-next", `a[href*="/shots/${ids[1]}"]`);
    } else log({ ev: "no-link", text: "shot" });
  }
  mark("end");
  await browser.close();
  out.end();
})();
