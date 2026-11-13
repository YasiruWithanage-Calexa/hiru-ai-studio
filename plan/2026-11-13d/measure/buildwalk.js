// The build page while a (simulated) build runs: open it, start fakebuild.py, stay until it is done, then 15 s more.
//   node buildwalk.js <label> [seconds]     # writes browser.<label>.jsonl; analyze.py <label> reads it
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const { chromium } = require(path.join(__dirname, "../../2026-11-13b/measure/node_modules/playwright-core"));

const ids = JSON.parse(fs.readFileSync(path.join(__dirname, "create.json"), "utf8"));
const LABEL = process.argv[2] || "build";
const SECONDS = Number(process.argv[3] || 90);
const API = "http://localhost:8001";
const out = fs.createWriteStream(path.join(__dirname, `browser.${LABEL}.jsonl`));
let step = "start";
const log = (o) => out.write(JSON.stringify({ at: Date.now() / 1000, step, ...o }) + "\n");
const mark = (name) => { step = name; log({ ev: "step" }); console.log(new Date().toISOString(), name); };

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  page.on("request", (q) => { if (q.url().startsWith(API)) log({ ev: "req", method: q.method(), url: q.url().replace(API, "") }); });
  page.on("console", (m) => { if (m.type() === "error") log({ ev: "console", text: m.text().slice(0, 300) }); });
  mark("login");
  await page.goto("http://localhost:3030/login", { waitUntil: "networkidle" });
  await page.waitForTimeout(3000);
  await page.locator('input[type="email"]').first().fill(ids.email);
  await page.locator('input[type="password"]').first().fill(ids.password);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(3000);

  // The simulated build starts first, so the page opens on a running build (as after "Start build").
  mark("build-start");
  const python = path.join(__dirname, "../../../.venv/Scripts/python.exe");
  const fake = spawn(python, [path.join(__dirname, "fakebuild.py"), String(SECONDS), "3"], { stdio: ["ignore", "pipe", "inherit"] });
  const done = new Promise((resolve) => fake.on("exit", resolve));
  await new Promise((resolve) => fake.stdout.once("data", resolve));
  mark("build-running");
  await page.goto(`http://localhost:3030/productions/${ids.P}/build`, { waitUntil: "domcontentloaded" });
  await done;
  mark("build-settled");
  await page.waitForTimeout(15000);
  const text = await page.locator("body").innerText().catch(() => "");
  log({ ev: "final", text: /Build finished/.test(text) ? "shows Build finished" : "does NOT show Build finished" });
  console.log(/Build finished/.test(text) ? "page shows Build finished" : "page does NOT show Build finished");
  mark("end");
  await browser.close();
  out.end();
})();
