// The creation walk (plan/2026-11-13d phase 0): a fresh production from upload to a built structure, then one scene
// and one shot, recording every request the browser makes to the API (the API's trace records what each one cost).
//   python ../../2026-11-13b/measure/seed.py create-prod     # writes create.json (a new traffic-create-* production)
//   node create.js [label]                                    # writes browser.<label>.jsonl
// The production is made by seed.py because creating one is an admin's act and the traffic bot is a director; the
// walk starts at the upload, the way the "Create and upload" form ends.
const path = require("path");
const fs = require("fs");
const { chromium } = require(path.join(__dirname, "../../2026-11-13b/measure/node_modules/playwright-core"));

const ids = JSON.parse(fs.readFileSync(path.join(__dirname, "create.json"), "utf8"));
const WEB = "http://localhost:3030";
const API = "http://localhost:8001";
const LABEL = process.argv[2] || "run";
const SCRIPT = path.join(__dirname, "../../../tests/fixtures/corpus/harbour-lights-ep01-script.fountain");
const out = fs.createWriteStream(path.join(__dirname, `browser.${LABEL}.jsonl`));
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
    if (u.startsWith(API)) log({ ev: "res", status: res.status(), url: u.replace(API, "") });
  });
  page.on("console", (m) => { if (m.type() === "error") log({ ev: "console", text: m.text().slice(0, 300) }); });
  page.on("pageerror", (e) => log({ ev: "pageerror", text: String(e).slice(0, 300) }));

  const mark = (name) => { step = name; log({ ev: "step" }); console.log(new Date().toISOString(), name); };
  const visit = async (name, url, dwell) => {
    mark(name);
    try { await page.goto(WEB + url, { waitUntil: "domcontentloaded", timeout: 60000 }); } catch (e) { log({ ev: "nav-error", text: String(e).slice(0, 200) }); }
    await page.waitForTimeout(dwell);
  };
  const waitText = async (re, ms) => {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      const text = await page.locator("body").innerText().catch(() => "");
      if (re.test(text)) return true;
      await page.waitForTimeout(500);
    }
    log({ ev: "timeout", text: String(re) });
    return false;
  };

  mark("login");
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto(WEB + "/login", { waitUntil: "networkidle", timeout: 90000 });
    await page.waitForTimeout(3000);
    await page.locator('input[type="email"], input[name="email"]').first().fill(ids.email);
    await page.locator('input[type="password"]').first().fill(ids.password);
    await page.click('button[type="submit"]');
    if (await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }).then(() => true).catch(() => false)) break;
  }
  await page.waitForTimeout(4000);

  const P = `/productions/${ids.P}`;
  await visit("productions-list", "/productions", 8000);
  await visit("landing", P, 6000);

  // Upload on the documents page (where "Create and upload" lands), then open the build dialog at once: it watches
  // the document while it is read.
  await visit("documents", `${P}/documents`, 3000);
  mark("upload-and-read");
  await page.locator('input[type="file"]').first().setInputFiles(SCRIPT);
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: "Build structure" }).click();
  const start = page.getByRole("button", { name: "Start build" });
  const until = Date.now() + 180000;
  while (Date.now() < until && !(await start.isEnabled().catch(() => false))) await page.waitForTimeout(500);
  await page.waitForTimeout(1000);

  mark("build");
  await start.click();
  await page.waitForURL((u) => u.pathname.endsWith("/build"), { timeout: 30000 }).catch(() => log({ ev: "nav-error", text: "no /build" }));
  await waitText(/Build finished|Build failed|Waiting for your answers|Build stopped/, 600000);
  mark("build-settled");
  await page.waitForTimeout(10000);

  // One scene and one shot of what the build made.
  await visit("overview-after", P, 5000);
  const episode = page.locator(`a[href*="${P}/episodes/"]`).first();
  if (await episode.count()) {
    mark("episode");
    await episode.click().catch(() => {});
    await page.waitForTimeout(5000);
    const scene = page.locator('a[href*="/scenes/"]').first();
    if (await scene.count()) {
      mark("scene-director");
      await scene.click().catch(() => {});
      await page.waitForTimeout(8000);
      const shot = page.locator('a[href*="/shots/"]').first();
      if (await shot.count()) {
        mark("shot");
        await shot.click().catch(() => {});
        await page.waitForTimeout(8000);
      } else log({ ev: "no-link", text: "shot" });
    } else log({ ev: "no-link", text: "scene" });
  } else log({ ev: "no-link", text: "episode" });

  mark("idle");
  await page.waitForTimeout(30000);
  mark("end");
  await browser.close();
  out.end();
})();
