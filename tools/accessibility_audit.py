from __future__ import annotations

import json
import re
import subprocess
import sys
from shutil import which
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from omniagents import function_tool


@dataclass(frozen=True)
class _LoginConfig:
    login_url: str
    username: str
    password: str
    username_selector: Optional[str]
    password_selector: Optional[str]
    submit_selector: Optional[str]
    post_login_url_prefix: Optional[str]


def _same_site(a: str, b: str) -> bool:
    pa = urlparse(a)
    pb = urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    parsed = urlparse(u)
    if not parsed.scheme:
        return "https://" + u
    return u


def _should_skip(url: str, include: Optional[List[str]], exclude: Optional[List[str]]) -> bool:
    if exclude:
        for pattern in exclude:
            if re.search(pattern, url):
                return True
    if include:
        for pattern in include:
            if re.search(pattern, url):
                return False
        return True
    return False


def _extract_links(base_url: str, hrefs: List[str]) -> List[str]:
    out: List[str] = []
    for href in hrefs:
        if not href:
            continue
        if href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        cleaned = parsed._replace(fragment="").geturl()
        out.append(cleaned)
    return out


def _summarize_violations(violations: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for v in violations:
        rule_id = str(v.get("id", ""))
        if not rule_id:
            continue
        entry = by_id.setdefault(
            rule_id,
            {
                "id": rule_id,
                "impact": v.get("impact"),
                "help": v.get("help"),
                "helpUrl": v.get("helpUrl"),
                "count": 0,
            },
        )
        nodes = v.get("nodes") or []
        entry["count"] += len(nodes) if isinstance(nodes, list) else 1
        if entry.get("impact") is None and v.get("impact") is not None:
            entry["impact"] = v.get("impact")
    sorted_rules = sorted(by_id.values(), key=lambda x: (-int(x.get("count", 0)), str(x.get("id", ""))))
    return {"total_rules": len(sorted_rules), "rules": sorted_rules}


def _run_node_audit(
    *,
    start_url: str,
    max_pages: int,
    same_domain_only: bool,
    include_url_patterns: Optional[List[str]],
    exclude_url_patterns: Optional[List[str]],
    login_cfg: Optional[_LoginConfig],
    headless: bool,
    wait_ms: int,
) -> Dict[str, Any]:
    script_path = str((__import__("pathlib").Path(__file__).parent / "node_a11y_audit.mjs").resolve())

    node = which("node") or "node"

    cmd: List[str] = [
        node,
        script_path,
        "--start_url",
        start_url,
        "--max_pages",
        str(max_pages),
        "--same_domain_only",
        "true" if same_domain_only else "false",
        "--headless",
        "true" if headless else "false",
        "--wait_ms",
        str(wait_ms),
    ]

    if include_url_patterns is not None:
        cmd.extend(["--include_url_patterns", json.dumps(include_url_patterns)])
    if exclude_url_patterns is not None:
        cmd.extend(["--exclude_url_patterns", json.dumps(exclude_url_patterns)])

    if login_cfg is not None:
        cmd.extend(["--login_url", login_cfg.login_url])
        cmd.extend(["--username", login_cfg.username])
        cmd.extend(["--password", login_cfg.password])
        if login_cfg.username_selector:
            cmd.extend(["--username_selector", login_cfg.username_selector])
        if login_cfg.password_selector:
            cmd.extend(["--password_selector", login_cfg.password_selector])
        if login_cfg.submit_selector:
            cmd.extend(["--submit_selector", login_cfg.submit_selector])
        if login_cfg.post_login_url_prefix:
            cmd.extend(["--post_login_url_prefix", login_cfg.post_login_url_prefix])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60, 10 + max_pages * 6),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "Missing dependency: node is required for this environment."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Audit timed out. Reduce max_pages or increase wait_ms."}

    out = (result.stdout or "").strip()
    if not out:
        err = (result.stderr or "").strip()
        if "ERR_MODULE_NOT_FOUND" in err or "Cannot find package" in err:
            return {
                "ok": False,
                "error": "Missing Node dependencies. Run `npm install` in the project root.",
            }
        return {"ok": False, "error": f"Node audit produced no output. {err[:500]}"}

    try:
        parsed = json.loads(out)
    except Exception:
        return {"ok": False, "error": f"Node audit output was not valid JSON: {out[:500]}"}

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        err = str(parsed.get("error") if isinstance(parsed, dict) else "Node audit failed")
        hint = parsed.get("hint") if isinstance(parsed, dict) else None
        res: Dict[str, Any] = {"ok": False, "error": err}
        if hint:
            res["hint"] = hint
        return res

    pages = parsed.get("pages")
    if not isinstance(pages, list):
        return {"ok": False, "error": "Node audit returned invalid pages payload."}

    all_violations: List[Dict[str, Any]] = []
    for item in pages:
        if isinstance(item, dict) and isinstance(item.get("violations"), list):
            all_violations.extend(item["violations"])

    return {
        "ok": True,
        "engine": "node-playwright + axe-core",
        "pages": pages,
        "top_issues": _summarize_violations(all_violations),
    }


@function_tool
def run_accessibility_audit(
    start_url: str,
    max_pages: int = 25,
    same_domain_only: bool = True,
    include_url_patterns: Optional[List[str]] = None,
    exclude_url_patterns: Optional[List[str]] = None,
    login_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    username_selector: Optional[str] = None,
    password_selector: Optional[str] = None,
    submit_selector: Optional[str] = None,
    post_login_url_prefix: Optional[str] = None,
    headless: bool = True,
    wait_ms: int = 500,
) -> Dict[str, Any]:
    """Crawl a website and run an automated accessibility audit.

    This tool performs an automated scan aligned to WCAG 2.x A/AA style rules via axe.
    It can optionally log into a site first using the provided credentials.

    Args:
        start_url: The first page to scan. If missing scheme, https:// is assumed.
        max_pages: Max number of pages to scan during crawl.
        same_domain_only: If true, only crawl links on the same scheme+host as start_url.
        include_url_patterns: Optional regex patterns; if provided, only URLs matching at least one pattern are scanned.
        exclude_url_patterns: Optional regex patterns; URLs matching any pattern are skipped.
        login_url: Optional URL to perform login before scanning. Defaults to start_url if provided credentials.
        username: Optional username/email for login.
        password: Optional password for login.
        username_selector: Optional CSS selector for the username/email input.
        password_selector: Optional CSS selector for the password input.
        submit_selector: Optional CSS selector for the submit button.
        post_login_url_prefix: Optional URL prefix expected after login (used as a best-effort login success check).
        headless: Run browser headless.
        wait_ms: Wait time after navigation and login actions.

    Returns:
        Dict summary with pages scanned, per-page results, and a top-issues summary.
    """

    start_url_n = _normalize_url(start_url)
    if not start_url_n:
        return {"ok": False, "error": "start_url is required"}

    login_cfg: Optional[_LoginConfig] = None
    if (username is not None) or (password is not None) or (login_url is not None):
        if not username or not password:
            return {
                "ok": False,
                "error": "For login, provide username and password (and optionally selectors).",
            }
        login_cfg = _LoginConfig(
            login_url=_normalize_url(login_url or start_url_n),
            username=username,
            password=password,
            username_selector=username_selector,
            password_selector=password_selector,
            submit_selector=submit_selector,
            post_login_url_prefix=_normalize_url(post_login_url_prefix) if post_login_url_prefix else None,
        )

    if sys.version_info >= (3, 13):
        node_res = _run_node_audit(
            start_url=start_url_n,
            max_pages=max_pages,
            same_domain_only=same_domain_only,
            include_url_patterns=include_url_patterns,
            exclude_url_patterns=exclude_url_patterns,
            login_cfg=login_cfg,
            headless=headless,
            wait_ms=wait_ms,
        )
        if not node_res.get("ok"):
            return {
                "ok": False,
                "error": node_res.get("error", "Accessibility audit failed."),
                "hint": "This environment uses Python 3.13; the agent uses a Node-based audit runner. Ensure Node.js is installed.",
            }

        pages = node_res["pages"]
        summary = node_res["top_issues"]
        return {
            "ok": True,
            "engine": node_res.get("engine"),
            "standard_target": "WCAG 2.2 AA (automated checks; manual review required)",
            "also_relevant": ["Section 508 (US)", "EN 301 549 (EU)"],
            "start_url": start_url_n,
            "max_pages": max_pages,
            "pages_scanned": len(pages),
            "pages": pages,
            "top_issues": summary,
        }

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return {
            "ok": False,
            "error": "Missing dependency: playwright. Add it to requirements and run `python -m playwright install`.",
        }

    axe_mode = "axe-playwright-python"
    Axe: Any = None
    try:
        from axe_playwright_python.sync_playwright import Axe as _Axe  # type: ignore

        Axe = _Axe
    except Exception:
        axe_mode = "missing"

    if axe_mode == "missing":
        return {
            "ok": False,
            "error": "Missing dependency: axe-playwright-python. Install it to run automated accessibility rules.",
        }

    scanned: List[Dict[str, Any]] = []
    visited: Set[str] = set()
    queue: List[str] = [start_url_n]

    def pop_next() -> Optional[str]:
        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            if _should_skip(url, include_url_patterns, exclude_url_patterns):
                visited.add(url)
                continue
            if same_domain_only and not _same_site(start_url_n, url):
                visited.add(url)
                continue
            return url
        return None

    try:
        playwright_cm = sync_playwright()
        p = playwright_cm.__enter__()
    except Exception as e:
        return {
            "ok": False,
            "error": f"Playwright failed to start: {e}",
            "hint": "Try Python 3.10–3.12 and re-run `python -m playwright install`.",
        }

    try:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        if login_cfg is not None:
            page.goto(login_cfg.login_url, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)

            user_sel = login_cfg.username_selector or "input[type='email'], input[name*='email' i], input[type='text'], input[name*='user' i], input[name*='login' i]"
            pass_sel = login_cfg.password_selector or "input[type='password']"

            page.locator(user_sel).first.fill(login_cfg.username)
            page.locator(pass_sel).first.fill(login_cfg.password)

            if login_cfg.submit_selector:
                page.locator(login_cfg.submit_selector).first.click()
            else:
                page.keyboard.press("Enter")

            page.wait_for_timeout(wait_ms)

            if login_cfg.post_login_url_prefix and not page.url.startswith(login_cfg.post_login_url_prefix):
                pass

        while len(scanned) < max_pages:
            url = pop_next()
            if url is None:
                break

            visited.add(url)

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(wait_ms)

                axe = Axe.from_page(page)
                results = axe.run()

                violations = results.get("violations") or []
                page_entry: Dict[str, Any] = {
                    "url": url,
                    "title": page.title(),
                    "violations_count": len(violations) if isinstance(violations, list) else 0,
                    "violations": violations,
                }
                scanned.append(page_entry)

                hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
                if isinstance(hrefs, list):
                    for link in _extract_links(url, [str(x) for x in hrefs]):
                        if link not in visited and link not in queue:
                            queue.append(link)

            except Exception as e:
                scanned.append({"url": url, "error": str(e)})

        browser.close()
    finally:
        try:
            playwright_cm.__exit__(None, None, None)
        except Exception:
            pass

    all_violations: List[Dict[str, Any]] = []
    for item in scanned:
        v = item.get("violations")
        if isinstance(v, list):
            all_violations.extend(v)

    summary = _summarize_violations(all_violations)

    return {
        "ok": True,
        "standard_target": "WCAG 2.2 AA (automated checks; manual review required)",
        "also_relevant": ["Section 508 (US)", "EN 301 549 (EU)"],
        "start_url": start_url_n,
        "max_pages": max_pages,
        "pages_scanned": len(scanned),
        "pages": scanned,
        "top_issues": summary,
        "export": {
            "note": "If you want, I can add a tool to write a JSON/HTML report file to disk.",
            "json": json.dumps({"pages": scanned, "top_issues": summary}, ensure_ascii=False)[:20000],
        },
    }
