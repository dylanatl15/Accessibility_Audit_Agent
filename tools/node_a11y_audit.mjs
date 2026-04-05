import { chromium } from "playwright";
import axe from "axe-core";

async function fetchText(url) {
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return await res.text();
}

function extractSitemapLocs(xml) {
  const locs = [];
  const re = /<loc>\s*([^<\s]+)\s*<\/loc>/gi;
  let m;
  while ((m = re.exec(xml))) {
    locs.push(String(m[1]));
  }
  return locs;
}

async function getSitemapUrls(startUrl, sitemapUrl, cap) {
  const start = new URL(startUrl);
  const candidates = [sitemapUrl || new URL("/sitemap.xml", start).toString()];
  const out = [];
  const seen = new Set();

  for (const sm of candidates) {
    if (out.length >= cap) break;
    let xml;
    try {
      xml = await fetchText(sm);
    } catch {
      continue;
    }

    const locs = extractSitemapLocs(xml);
    for (const loc of locs) {
      if (out.length >= cap) break;
      if (seen.has(loc)) continue;
      seen.add(loc);
      try {
        const u = new URL(loc);
        if (u.protocol !== "http:" && u.protocol !== "https:") continue;
        u.hash = "";
        if (u.host !== start.host) continue;
        out.push(u.toString());
      } catch {
        continue;
      }
    }
  }

  return out;
}

const axeSource = axe.source;

function normalizeUrl(url) {
  const u = (url || "").trim();
  if (!u) return u;
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(u)) return `https://${u}`;
  return u;
}

function canonicalizeUrl(url, stripTrackingParams = true) {
  try {
    const u = new URL(url);
    u.hash = "";
    if (stripTrackingParams) {
      const removeKeys = [];
      for (const [k] of u.searchParams.entries()) {
        const key = String(k || "").toLowerCase();
        if (
          key.startsWith("utm_") ||
          key === "gclid" ||
          key === "fbclid" ||
          key === "mc_cid" ||
          key === "mc_eid"
        ) {
          removeKeys.push(k);
        }
      }
      for (const k of removeKeys) u.searchParams.delete(k);
    }
    if (u.pathname !== "/" && u.pathname.endsWith("/")) u.pathname = u.pathname.slice(0, -1);
    return u.toString();
  } catch {
    return url;
  }
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

function baseDomain(host) {
  const parts = String(host || "").split(".").filter(Boolean);
  if (parts.length < 2) return String(host || "");
  return parts.slice(-2).join(".");
}

function sameDomainOrSubdomain(baseUrl, url) {
  try {
    const pb = new URL(baseUrl);
    const pu = new URL(url);
    const b = baseDomain(pb.hostname.toLowerCase());
    const h = pu.hostname.toLowerCase();
    return h === b || h.endsWith(`.${b}`);
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

function looksLikeLoginUrl(url) {
  const u = String(url || "").toLowerCase();
  if (u.includes("/c/portal/login")) return true;
  if (u.includes("login.microsoftonline.com")) return true;
  if (u.includes("login.live.com")) return true;
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
const includeSubdomains = getBool("include_subdomains", false);
const includePatterns = getJsonList("include_url_patterns");
const excludePatterns = getJsonList("exclude_url_patterns");
const headless = getBool("headless", true);
const waitMs = getInt("wait_ms", 500);
const useSitemap = getBool("use_sitemap", false);
const sitemapUrlOverride = getArg("sitemap_url");
const autoUseSitemapOnStall = getBool("auto_use_sitemap_on_stall", true);
const minTimeBetweenPagesMs = getInt("min_time_between_pages_ms", 0);
const stripTrackingParams = getBool("strip_tracking_params", true);

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

function looksLikeMfa(pageUrl, pageText) {
  const u = String(pageUrl || "").toLowerCase();
  const t = String(pageText || "").toLowerCase();
  if (u.includes("login.microsoftonline.com") || u.includes("login.live.com")) {
    if (t.includes("approve sign in request") || t.includes("enter code") || t.includes("verification code") || t.includes("microsoft authenticator")) {
      return true;
    }
  }
  if (t.includes("two-step verification") || t.includes("multi-factor") || t.includes("mfa")) return true;
  return false;
}

const visited = new Set();
let queue = [startUrl];
const pages = [];

let crawlBaseUrl = startUrl;

let lastNavMs = 0;

async function throttle() {
  if (!minTimeBetweenPagesMs) return;
  const now = Date.now();
  const delta = now - lastNavMs;
  if (delta < minTimeBetweenPagesMs) {
    await new Promise((r) => setTimeout(r, minTimeBetweenPagesMs - delta));
  }
  lastNavMs = Date.now();
}

function popNext() {
  while (queue.length) {
    const url = queue.shift();
    if (!url) continue;
    const c = canonicalizeUrl(url, stripTrackingParams);
    if (visited.has(c)) continue;
    if (looksLikeLoginUrl(c)) {
      visited.add(c);
      continue;
    }
    if (shouldSkip(c, includePatterns, excludePatterns)) {
      visited.add(c);
      continue;
    }
    if (sameDomainOnly) {
      if (includeSubdomains) {
        if (!sameDomainOrSubdomain(crawlBaseUrl, c)) {
          visited.add(c);
          continue;
        }
      } else if (!sameSite(crawlBaseUrl, c)) {
        visited.add(c);
        continue;
      }
    }
    return c;
  }
  return null;
}

let browser;
try {
  if (useSitemap) {
    const sitemapUrls = await getSitemapUrls(startUrl, sitemapUrlOverride, Math.max(25, maxPages * 5));
    if (sitemapUrls && sitemapUrls.length) {
      const seeded = [startUrl, ...sitemapUrls].map((u) => canonicalizeUrl(u, stripTrackingParams));
      queue = Array.from(new Set(seeded));
    }
  }

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

    const postLoginText = await page.textContent("body").catch(() => "");
    const mfa = looksLikeMfa(page.url(), postLoginText);
    if (mfa) {
      pages.push({
        url: loginUrl,
        title: await page.title().catch(() => ""),
        violations_count: 0,
        violations: [],
        note: "Login requires 2FA; continuing with public crawl only.",
        login_status: "2fa_required",
      });
      await page.goto(startUrl, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(waitMs);
    }
  }

  while (pages.length < maxPages) {
    const url = popNext();
    if (!url) break;

    visited.add(url);

    try {
      await throttle();
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(waitMs);

      const finalUrl = canonicalizeUrl(page.url(), stripTrackingParams);

      if (pages.length === 0) {
        crawlBaseUrl = finalUrl;
      }
      if (sameDomainOnly) {
        const inScope = includeSubdomains ? sameDomainOrSubdomain(crawlBaseUrl, finalUrl) : sameSite(crawlBaseUrl, finalUrl);
        if (!inScope) {
          pages.push({
            url,
            final_url: finalUrl,
            title: await page.title().catch(() => ""),
            violations_count: 0,
            violations: [],
            note: "Redirected off-site (likely login); continuing public crawl.",
          });
          visited.add(finalUrl);
          await page.goto(startUrl, { waitUntil: "domcontentloaded" });
          await page.waitForTimeout(waitMs);
          continue;
        }
      }
      visited.add(finalUrl);

      await page.addScriptTag({ content: axeSource });
      const axeResults = await page.evaluate(async () => {
        const r = await globalThis.axe.run();
        return r;
      });

      const violations = (axeResults && axeResults.violations) || [];
      pages.push({
        url,
        final_url: finalUrl,
        title: await page.title(),
        violations_count: Array.isArray(violations) ? violations.length : 0,
        violations,
      });

      const hrefs = await page.$$eval("a[href]", (els) => els.map((e) => e.getAttribute("href")));
      let extracted = extractLinks(finalUrl, hrefs);
      if (!extracted.length && autoUseSitemapOnStall && !useSitemap && pages.length === 1) {
        const sitemapUrls = await getSitemapUrls(crawlBaseUrl, sitemapUrlOverride, Math.max(25, maxPages * 5));
        for (const u of sitemapUrls) {
          const c = canonicalizeUrl(u, stripTrackingParams);
          if (!visited.has(c) && !queue.includes(c)) queue.push(c);
        }
        extracted = extractLinks(finalUrl, hrefs);
      }

      for (const link of extracted) {
        const c = canonicalizeUrl(link, stripTrackingParams);
        if (looksLikeLoginUrl(c)) continue;
        if (sameDomainOnly && includeSubdomains && !sameDomainOrSubdomain(crawlBaseUrl, c)) continue;
        if (!visited.has(c) && !queue.includes(c)) queue.push(c);
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
