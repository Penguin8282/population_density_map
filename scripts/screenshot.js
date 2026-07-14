// 로컬 웹앱 스크린샷 도구 (Playwright).
// 사용: NODE_PATH=$(npm root -g) node scripts/screenshot.js <url> <out.png> [width] [height] [waitMs]
const { chromium } = require("playwright");

(async () => {
  const url = process.argv[2] || "http://localhost:8000/";
  const out = process.argv[3] || "shot.png";
  const width = parseInt(process.argv[4] || "1400", 10);
  const height = parseInt(process.argv[5] || "900", 10);
  const waitMs = parseInt(process.argv[6] || "3500", 10);

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(waitMs);
  await page.screenshot({ path: out, fullPage: false });
  await browser.close();

  if (errors.length) {
    console.log("CONSOLE ERRORS:\n" + errors.join("\n"));
  } else {
    console.log("no console errors");
  }
  console.log("saved:", out);
})().catch((e) => { console.error(e); process.exit(1); });
