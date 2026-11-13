// F1, the HMR hypothesis: with /productions on screen, re-save N interface files (same bytes, new mtime), the way a
// formatter does, and count the server renders (/v1/productions reads) that follow.   node f1b.js [files] [gapMs]
const path = require("path");
const fs = require("fs");
const { chromium } = require(path.join(__dirname, "../../2026-11-13b/measure/node_modules/playwright-core"));
const ids = JSON.parse(fs.readFileSync(path.join(__dirname, "create.json"), "utf8"));
const N = Number(process.argv[2] || 20), GAP = Number(process.argv[3] || 150);
const TRACE = path.join(__dirname, "trace.jsonl");
const SRC = path.join(__dirname, "../../../../hiru-ai-studio-interface/src");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const renders = (from, to) => fs.readFileSync(TRACE, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
  .filter((t) => t.at >= from && t.at <= to && t.path === "/v1/productions" && t.method === "GET").length;
(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await (await browser.newContext()).newPage();
  let fromBrowser = 0;
  page.on("request", (r) => { if (r.url().startsWith("http://localhost:8001")) fromBrowser += 1; });
  await page.goto("http://localhost:3030/login", { waitUntil: "networkidle" });
  await page.waitForTimeout(3000);
  await page.locator('input[type="email"]').first().fill(ids.email);
  await page.locator('input[type="password"]').first().fill(ids.password);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 }).catch(() => {});
  await page.goto("http://localhost:3030/productions", { waitUntil: "networkidle" });
  await sleep(4000);
  let t0 = Date.now() / 1000;
  await sleep(8000);
  console.log("quiet 8 s:", renders(t0, Date.now() / 1000), "renders");
  const files = [];
  if (process.env.SERVER_FILES) files.push(...process.env.SERVER_FILES.split(",").map((f) => path.join(SRC, f)));
  else for (const dir of ["features/productions/components", "features/drama/components", "components/ui"])
    for (const f of fs.readdirSync(path.join(SRC, dir))) if (f.endsWith(".tsx") && !f.includes(".test.")) files.push(path.join(SRC, dir, f));
  t0 = Date.now() / 1000;
  fromBrowser = 0;
  const orig = files.slice(0, N).map((f) => [f, fs.readFileSync(f)]);
  try { for (const [f, b] of orig) { fs.writeFileSync(f, Buffer.concat([b, Buffer.from([10])])); await sleep(GAP); } }
  finally { await sleep(3000); for (const [f, b] of orig) fs.writeFileSync(f, b); }
  await sleep(10000);
  console.log(`${N} files re-saved ${GAP} ms apart:`, renders(t0, Date.now() / 1000), "renders,", fromBrowser, "browser requests");
  await browser.close();
})();
