// F1 (plan/2026-11-13d phase 0 step 2): does the productions page render itself in a loop when the API comes back?
//   node f1.js        # writes f1.jsonl: per window, the API's /v1/productions + /v1/me + /v1/usage count (server
//                     # renders: the browser makes no request for them) and what the browser asked
// Needs the interface on :3030 and start-dev.ps1 (API only). It stops and starts the API itself.
const path = require("path");
const fs = require("fs");
const { execSync } = require("child_process");
const { chromium } = require(path.join(__dirname, "../../2026-11-13b/measure/node_modules/playwright-core"));

const ids = JSON.parse(fs.readFileSync(path.join(__dirname, "create.json"), "utf8"));
const WEB = "http://localhost:3030";
const TRACE = path.join(__dirname, "trace.jsonl");
const START = `powershell -File "${path.join(__dirname, "start-dev.ps1")}"`;
const STOP = `powershell -Command "Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"`;
const out = fs.createWriteStream(path.join(__dirname, "f1.jsonl"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const traceLines = () => (fs.existsSync(TRACE) ? fs.readFileSync(TRACE, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);
const count = (from, to) => {
  const rows = traceLines().filter((t) => t.at >= from && t.at <= to && t.method === "GET");
  const c = {};
  for (const t of rows) {
    const k = t.path.replace(/[0-9a-f-]{36}/g, "{id}");
    c[k] = (c[k] || 0) + 1;
  }
  return c;
};
const waitApi = async () => {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch("http://localhost:8001/healthz")).ok) return; } catch {}
    await sleep(500);
  }
};

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await (await browser.newContext()).newPage();
  let browserReqs = 0;
  page.on("request", (r) => { if (r.url().startsWith("http://localhost:8001")) browserReqs += 1; });
  await page.goto(WEB + "/login", { waitUntil: "networkidle" });
  await page.waitForTimeout(3000);
  await page.locator('input[type="email"]').first().fill(ids.email);
  await page.locator('input[type="password"]').first().fill(ids.password);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(3000);

  const run = async (name, before, dwellMs) => {
    browserReqs = 0;
    await before();
    const t0 = Date.now() / 1000;
    await sleep(dwellMs);
    const t1 = Date.now() / 1000;
    const row = { name, secs: Math.round(t1 - t0), api: count(t0, t1), browser: browserReqs };
    out.write(JSON.stringify(row) + "\n");
    console.log(JSON.stringify(row));
  };

  // A: API up from the start.
  await run("api-up", async () => { await page.goto(WEB + "/productions", { waitUntil: "domcontentloaded" }); }, 12000);
  // B: the page opened while the API is down, then the API comes back while it stays on screen.
  execSync(STOP);
  await sleep(1500);
  await page.goto(WEB + "/productions", { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(5000);
  out.write(JSON.stringify({ name: "api-down-page", text: (await page.locator("body").innerText().catch(() => "")).slice(0, 200) }) + "\n");
  await run("api-back", async () => { execSync(START); await waitApi(); }, 15000);
  // C: after an HMR edit of a file the page uses (touch only: same content).
  const f = path.join(__dirname, "../../../../hiru-ai-studio-interface/src/features/productions/components/productions-browser.tsx");
  await run("after-hmr", async () => { const now = new Date(); fs.utimesSync(f, now, now); fs.writeFileSync(f, fs.readFileSync(f)); }, 12000);
  await browser.close();
  out.end();
})();
