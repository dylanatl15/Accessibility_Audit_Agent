import { chromium } from "playwright";
import axe from "axe-core";

const axeSource = axe.source;

function normalizeUrl(url) {
  const u = (url || "").trim();
  if (!u) return u;
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(u)) return `https://${u}`;
  return u;
}

function sameSite(a, b) {
  try {
    const pa = new URL(a);
    const pb = new URL(b);
    return pa.protocol === pb.protocol && pa.host === pb.host;
  } catch {
    return false;
  }
}

function shouldSkip(url, include, exclude) {
  if (exclude && exclude.length) {
    for (const p of exclude) {
      if (new RegExp(p).test(url)) return true;
    }
  }
  if (include && include.length) {
    for (const p of include) {
      if (new RegExp(p).test(url)) return false;
    }
    return true;
  }
  return false;
}

function extractLinks(baseUrl, hrefs) {
  const out = [];
  for (const href of hrefs || []) {
    if (!href) continue;
    const h = String(href);
    if (h.startsWith("mailto:") || h.startsWith("tel:") || h.startsWith("javascript:")) continue;
    try {
      const u = new URL(h, baseUrl);
      if (u.protocol !== "http:" && u.protocol !== "https:") continue;
      u.hash = "";
      out.push(u.toString());
    } catch {
      continue;
    }
  }
  return out;
}

function getArg(name, dflt = undefined) {
  const idx = process.argv.indexOf(`--${name}`);
  if (idx === -1) return dflt;
  const v = process.argv[idx + 1];
  if (v === undefined) return dflt;
  return v;
}

function getBool(name, dflt = false) {
  const v = getArg(name);
  if (v === undefined) return dflt;
  return v === "true" || v === "1";
}

function getInt(name, dflt) {
  const v = getArg(name);
  if (v === undefined) return dflt;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : dflt;
}

function getJsonList(name) {
  const v = getArg(name);
  if (!v) return null;
  try {
    const parsed = JSON.parse(v);
    return Array.isArray(parsed) ? parsed.map(String) : null;
  } catch {
    return null;
  }
}

const startUrl = normalizeUrl(getArg("start_url", ""));
if (!startUrl) {
  console.log(JSON.stringify({ ok: false, error: "start_url is required" }));
  process.exit(0);
}

const maxPages = getInt("max_pages", 25);
const sameDomainOnly = getBool("same_domain_only", true);
const includePatterns = getJsonList("include_url_patterns");
const excludePatterns = getJsonList("exclude_url_patterns");
const headless = getBool("headless", true);
const waitMs = getInt("wait_ms", 500);

const loginUrlRaw = getArg("login_url");
const username = getArg("username");
const password = getArg("password");
const usernameSelector = getArg("username_selector");
const passwordSelector = getArg("password_selector");
const submitSelector = getArg("submit_selector");
const postLoginUrlPrefix = getArg("post_login_url_prefix");

const loginEnabled = !!(loginUrlRaw || username || password);
if (loginEnabled && (!username || !password)) {
  console.log(JSON.stringify({ ok: false, error: "For login, provide username and password." }));
  process.exit(0);
}

const loginUrl = normalizeUrl(loginUrlRaw || startUrl);

const visited = new Set();
const queue = [startUrl];
const pages = [];

function popNext() {
  while (queue.length) {
    const url = queue.shift();
    if (!url) continue;
    if (visited.has(url)) continue;
    if (shouldSkip(url, includePatterns, excludePatterns)) {
      visited.add(url);
      continue;
    }
    if (sameDomainOnly && !sameSite(startUrl, url)) {
      visited.add(url);
      continue;
    }
    return url;
  }
  return null;
}

let browser;
try {
  browser = await chromium.launch({ headless });
  const context = await browser.newContext();
  const page = await context.newPage();

  if (loginEnabled) {
    await page.goto(loginUrl, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(waitMs);

    const userSel = usernameSelector || "input[type='email'], input[name*='email' i], input[type='text'], input[name*='user' i], input[name*='login' i]";
    const passSel = passwordSelector || "input[type='password']";

    await page.locator(userSel).first().fill(username);
    await page.locator(passSel).first().fill(password);

    if (submitSelector) {
      await page.locator(submitSelector).first().click();
    } else {
      await page.keyboard.press("Enter");
    }

    await page.waitForTimeout(waitMs);

    if (postLoginUrlPrefix && !page.url().startsWith(normalizeUrl(postLoginUrlPrefix))) {
      null;
    }
  }

  while (pages.length < maxPages) {
    const url = popNext();
    if (!url) break;

    visited.add(url);

    try {
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(waitMs);

      await page.addScriptTag({ content: axeSource });
      const axeResults = await page.evaluate(async () => {
        const r = await globalThis.axe.run();
        return r;
      });

      const violations = (axeResults && axeResults.violations) || [];
      pages.push({
        url,
        title: await page.title(),
        violations_count: Array.isArray(violations) ? violations.length : 0,
        violations,
      });

      const hrefs = await page.$$eval("a[href]", (els) => els.map((e) => e.getAttribute("href")));
      for (const link of extractLinks(url, hrefs)) {
        if (!visited.has(link) && !queue.includes(link)) queue.push(link);
      }
    } catch (e) {
      pages.push({ url, error: String(e) });
    }
  }

  console.log(JSON.stringify({ ok: true, pages }));
} catch (e) {
  let msg = String(e);
  msg = msg.replace(/[^\x09\x0A\x0D\x20-\x7E]/g, "");
  const hint = msg.includes("Executable doesn't exist") || msg.includes("browserType.launch") ? "Run `npx playwright install chromium`" : undefined;
  console.log(JSON.stringify({ ok: false, error: msg, hint }));
} finally {
  try {
    if (browser) await browser.close();
  } catch {
    null;
  }
}
