from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import uuid
from shutil import which
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

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


def _looks_like_mfa(url: str, body_text: str) -> bool:
    u = (url or "").lower()
    t = (body_text or "").lower()
    if "login.microsoftonline.com" in u or "login.live.com" in u:
        if "approve sign in request" in t or "enter code" in t or "verification code" in t or "microsoft authenticator" in t:
            return True
    if "two-step verification" in t or "multi-factor" in t or "mfa" in t:
        return True
    return False


def _same_site(a: str, b: str) -> bool:
    pa = urlparse(a)
    pb = urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def _base_domain(host: str) -> str:
    parts = [p for p in (host or "").split(".") if p]
    if len(parts) < 2:
        return host
    return ".".join(parts[-2:])


def _same_domain_or_subdomain(base_url: str, url: str) -> bool:
    pb = urlparse(base_url)
    pu = urlparse(url)
    if not pb.netloc or not pu.netloc:
        return False
    b = _base_domain(pb.netloc.lower())
    h = pu.netloc.lower()
    return h == b or h.endswith("." + b)


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    parsed = urlparse(u)
    if not parsed.scheme:
        return "https://" + u
    return u


def _canonical_url(url: str, *, strip_tracking_params: bool = True) -> str:
    try:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(url)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        if strip_tracking_params:
            filtered: List[Tuple[str, str]] = []
            for k, v in query_pairs:
                key = (k or "").lower()
                if key.startswith("utm_") or key in {"gclid", "fbclid", "mc_cid", "mc_eid"}:
                    continue
                filtered.append((k, v))
            query_pairs = filtered

        query = urlencode(query_pairs, doseq=True)
        path = parts.path
        if path.endswith("/") and path != "/":
            path = path[:-1]
        return urlunsplit((parts.scheme, parts.netloc, path, query, ""))
    except Exception:
        return url


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


def _looks_like_login_url(url: str) -> bool:
    u = (url or "").lower()
    if "/c/portal/login" in u:
        return True
    if "login.microsoftonline.com" in u or "login.live.com" in u:
        return True
    return False


def _sitemap_seed_urls(start_url: str, sitemap_url: Optional[str], cap: int) -> List[str]:
    seed: List[str] = []
    start = urlparse(start_url)
    if not start.scheme or not start.netloc:
        return seed

    def fetch_xml(url: str) -> Optional[str]:
        try:
            with urlopen(url, timeout=10) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception:
            return None

    def is_index(xml_text: str) -> bool:
        return bool(re.search(r"<\s*sitemapindex[\s>]", xml_text or "", flags=re.IGNORECASE))

    b = _base_domain(start.netloc.lower())

    queue: List[str] = [sitemap_url or f"{start.scheme}://{start.netloc}/sitemap.xml"]
    seen_sitemaps: Set[str] = set()

    while queue and len(seed) < cap:
        sm = queue.pop(0)
        if sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)

        xml = fetch_xml(sm)
        if not xml:
            continue

        sitemap_index = is_index(xml)
        for m in re.finditer(r"<loc>\s*([^<\s]+)\s*</loc>", xml, flags=re.IGNORECASE):
            if len(seed) >= cap:
                break
            loc = str(m.group(1)).strip()
            try:
                u = urlparse(loc)
            except Exception:
                continue
            if u.scheme not in {"http", "https"}:
                continue
            cleaned = u._replace(fragment="").geturl()
            if sitemap_index:
                if cleaned not in seen_sitemaps:
                    queue.append(cleaned)
                continue
            h = u.netloc.lower()
            if not (h == b or h.endswith("." + b)):
                continue
            if cleaned not in seed:
                seed.append(cleaned)

    return seed


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


def _standard_target() -> str:
    return "WCAG 2.1 AA (automated checks; manual review required)"


def _default_report_path(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "reports"
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / f"{prefix}_{ts}.json"


def _write_json_report(path: Path, payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, None
    except Exception as e:
        return False, str(e)


def _safe_filename_from_url(url: str, fallback_ext: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)[:180]
    if not name or "." not in name:
        name = f"download{fallback_ext}"
    return name


def _download_limited(url: str, dest: Path, max_bytes: int) -> Tuple[bool, Optional[str]]:
    try:
        with urlopen(url, timeout=20) as resp:
            total = 0
            with dest.open("wb") as f:
                while True:
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        return False, f"File exceeds max size ({max_bytes} bytes)"
                    f.write(chunk)
        return True, None
    except Exception as e:
        return False, str(e)


def _sanitize_pdf(src: Path, dest: Path) -> Tuple[bool, Optional[str]]:
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except Exception as e:
        return False, f"Missing dependency: pypdf ({e})"

    try:
        reader = PdfReader(str(src))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.add_metadata({})
        with dest.open("wb") as f:
            writer.write(f)
        return True, None
    except Exception as e:
        return False, str(e)


def _sanitize_office_zip(src: Path, dest: Path) -> Tuple[bool, Optional[str]]:
    try:
        import zipfile

        with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                name = info.filename
                lower = name.lower()
                if lower.endswith("vbaProject.bin".lower()):
                    continue
                if lower.startswith("word/embeddings/") or lower.startswith("ppt/embeddings/"):
                    continue
                if lower.startswith("word/media/") or lower.startswith("ppt/media/") or lower.startswith("xl/media/"):
                    pass
                data = zin.read(info.filename)
                if lower.endswith(".rels"):
                    try:
                        text = data.decode("utf-8", errors="ignore")
                        text = re.sub(r"TargetMode=\"External\"", "", text, flags=re.IGNORECASE)
                        data = text.encode("utf-8")
                    except Exception:
                        pass
                zout.writestr(info, data)

        return True, None
    except Exception as e:
        return False, str(e)


def _sanitize_downloaded_file(src: Path, dest: Path) -> Tuple[bool, Optional[str]]:
    ext = src.suffix.lower()
    if ext == ".pdf":
        return _sanitize_pdf(src, dest)
    if ext in {".docx", ".pptx"}:
        return _sanitize_office_zip(src, dest)
    return False, f"Unsupported file type for sanitization: {ext}"


def _scanned_urls(pages: Any) -> List[str]:
    urls: List[str] = []
    if not isinstance(pages, list):
        return urls
    for p in pages:
        if not isinstance(p, dict):
            continue
        u = p.get("final_url") if isinstance(p.get("final_url"), str) else p.get("url")
        if isinstance(u, str) and u and u not in urls:
            urls.append(u)
    return urls


def _load_json_report(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, "Report JSON is not an object."
        return data, None
    except Exception as e:
        return None, str(e)


def _violation_counts(report: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    def add_violations(violations: Any):
        if not isinstance(violations, list):
            return
        for v in violations:
            if not isinstance(v, dict):
                continue
            rid = str(v.get("id") or "").strip()
            if not rid:
                continue
            nodes = v.get("nodes")
            n = len(nodes) if isinstance(nodes, list) else 1
            counts[rid] = counts.get(rid, 0) + max(1, n)

    pages = report.get("pages")
    if isinstance(pages, list):
        for p in pages:
            if isinstance(p, dict):
                add_violations(p.get("violations"))

    sites = report.get("sites")
    if isinstance(sites, list):
        for s in sites:
            if isinstance(s, dict):
                inner_pages = s.get("pages")
                if isinstance(inner_pages, list):
                    for p in inner_pages:
                        if isinstance(p, dict):
                            add_violations(p.get("violations"))

    return counts


def _page_urls(report: Dict[str, Any]) -> Set[str]:
    urls: Set[str] = set()
    pages = report.get("pages")
    if isinstance(pages, list):
        for p in pages:
            if isinstance(p, dict) and isinstance(p.get("url"), str):
                urls.add(p["url"])
    sites = report.get("sites")
    if isinstance(sites, list):
        for s in sites:
            if isinstance(s, dict) and isinstance(s.get("pages"), list):
                for p in s["pages"]:
                    if isinstance(p, dict) and isinstance(p.get("url"), str):
                        urls.add(p["url"])
    return urls


@function_tool
def diff_accessibility_reports(old_report_path: str, new_report_path: str) -> Dict[str, Any]:
    """Diff two JSON reports produced by this agent."""

    old_p = Path(old_report_path).expanduser()
    new_p = Path(new_report_path).expanduser()
    if not old_p.exists() or not old_p.is_file():
        return {"ok": False, "error": f"Not a file: {old_report_path}"}
    if not new_p.exists() or not new_p.is_file():
        return {"ok": False, "error": f"Not a file: {new_report_path}"}

    old, err = _load_json_report(old_p)
    if old is None:
        return {"ok": False, "error": f"Failed to read old report: {err}"}
    new, err = _load_json_report(new_p)
    if new is None:
        return {"ok": False, "error": f"Failed to read new report: {err}"}

    old_counts = _violation_counts(old)
    new_counts = _violation_counts(new)
    all_rules = sorted(set(old_counts) | set(new_counts))
    delta: List[Dict[str, Any]] = []
    for rid in all_rules:
        before = int(old_counts.get(rid, 0))
        after = int(new_counts.get(rid, 0))
        if before == after:
            continue
        delta.append({"id": rid, "before": before, "after": after, "delta": after - before})

    added_pages = sorted(_page_urls(new) - _page_urls(old))
    removed_pages = sorted(_page_urls(old) - _page_urls(new))

    delta_sorted = sorted(delta, key=lambda x: (-abs(int(x.get("delta", 0))), str(x.get("id", ""))))

    return {
        "ok": True,
        "old_report_path": str(old_p),
        "new_report_path": str(new_p),
        "pages_added": added_pages,
        "pages_removed": removed_pages,
        "rule_deltas": delta_sorted,
    }


def _run_node_audit(
    *,
    start_url: str,
    max_pages: int,
    same_domain_only: bool,
    include_subdomains: bool,
    seed_urls: Optional[List[str]],
    include_url_patterns: Optional[List[str]],
    exclude_url_patterns: Optional[List[str]],
    login_cfg: Optional[_LoginConfig],
    headless: bool,
    wait_ms: int,
    use_sitemap: bool,
    sitemap_url: Optional[str],
    auto_use_sitemap_on_stall: bool,
    min_time_between_pages_ms: int,
    strip_tracking_params: bool,
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
        "--include_subdomains",
        "true" if include_subdomains else "false",
        "--headless",
        "true" if headless else "false",
        "--wait_ms",
        str(wait_ms),
        "--use_sitemap",
        "true" if use_sitemap else "false",
        "--auto_use_sitemap_on_stall",
        "true" if auto_use_sitemap_on_stall else "false",
        "--min_time_between_pages_ms",
        str(int(min_time_between_pages_ms)),
        "--strip_tracking_params",
        "true" if strip_tracking_params else "false",
    ]

    if sitemap_url:
        cmd.extend(["--sitemap_url", sitemap_url])

    if seed_urls is not None:
        cmd.extend(["--seed_urls", json.dumps(seed_urls)])

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

    documents = parsed.get("documents")
    if documents is not None and not isinstance(documents, list):
        documents = None

    all_violations: List[Dict[str, Any]] = []
    for item in pages:
        if isinstance(item, dict) and isinstance(item.get("violations"), list):
            all_violations.extend(item["violations"])

    return {
        "ok": True,
        "engine": "node-playwright + axe-core",
        "pages": pages,
        "documents": [str(x) for x in documents] if documents is not None else [],
        "top_issues": _summarize_violations(all_violations),
    }


@function_tool
def run_accessibility_audit(
    start_url: str,
    max_pages: int = 25,
    same_domain_only: bool = True,
    include_subdomains: bool = False,
    seed_urls: Optional[List[str]] = None,
    scan_linked_documents: bool = False,
    max_documents: int = 20,
    max_document_bytes: int = 20_000_000,
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
    output_path: Optional[str] = None,
    use_sitemap: bool = False,
    sitemap_url: Optional[str] = None,
    auto_use_sitemap_on_stall: bool = True,
    min_time_between_pages_ms: int = 0,
    strip_tracking_params: bool = True,
) -> Dict[str, Any]:
    """Crawl and scan a website with axe-core."""

    if scan_linked_documents:
        if max_documents < 0:
            return {"ok": False, "error": "max_documents must be >= 0"}
        if max_document_bytes < 1024:
            return {"ok": False, "error": "max_document_bytes must be >= 1024"}

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
            include_subdomains=include_subdomains,
            seed_urls=seed_urls,
            include_url_patterns=include_url_patterns,
            exclude_url_patterns=exclude_url_patterns,
            login_cfg=login_cfg,
            headless=headless,
            wait_ms=wait_ms,
            use_sitemap=use_sitemap,
            sitemap_url=sitemap_url,
            auto_use_sitemap_on_stall=auto_use_sitemap_on_stall,
            min_time_between_pages_ms=min_time_between_pages_ms,
            strip_tracking_params=strip_tracking_params,
        )
        if not node_res.get("ok"):
            return {
                "ok": False,
                "error": node_res.get("error", "Accessibility audit failed."),
                "hint": "This environment uses Python 3.13; the agent uses a Node-based audit runner. Ensure Node.js is installed.",
            }

        pages = node_res["pages"]
        summary = node_res["top_issues"]
        doc_urls = node_res.get("documents") if isinstance(node_res, dict) else None
        doc_urls_list = [u for u in doc_urls if isinstance(u, str)] if isinstance(doc_urls, list) else []

        doc_scan: Optional[Dict[str, Any]] = None
        tmp_dir: Optional[Path] = None
        if scan_linked_documents and doc_urls_list:
            tmp_dir = Path(tempfile.gettempdir()) / f"a11y_docs_{uuid.uuid4().hex}"
            tmp_dir.mkdir(parents=True, exist_ok=True)

            downloaded: List[Dict[str, Any]] = []
            try:
                limited = doc_urls_list[: max(0, int(max_documents))]
                for u in limited:
                    ext = Path(urlparse(u).path).suffix.lower()
                    if ext not in {".pdf", ".docx", ".pptx"}:
                        continue

                    raw_name = _safe_filename_from_url(u, ext)
                    raw_path = tmp_dir / ("raw_" + raw_name)
                    clean_path = tmp_dir / ("clean_" + raw_name)

                    ok, err = _download_limited(u, raw_path, max_bytes=int(max_document_bytes))
                    if not ok:
                        downloaded.append({"url": u, "ok": False, "stage": "download", "error": err})
                        continue

                    ok, err = _sanitize_downloaded_file(raw_path, clean_path)
                    if not ok:
                        downloaded.append({"url": u, "ok": False, "stage": "sanitize", "error": err})
                        continue

                    downloaded.append({"url": u, "ok": True, "sanitized_path": str(clean_path)})

                from tools.document_accessibility import scan_documents_accessibility

                scan_res = scan_documents_accessibility._original_func(
                    root_dir=str(tmp_dir),
                    recursive=False,
                    max_files=max(0, int(max_documents)),
                    extensions=[".pdf", ".docx", ".pptx"],
                )
                doc_scan = {
                    "ok": bool(scan_res.get("ok")) if isinstance(scan_res, dict) else False,
                    "downloaded": downloaded,
                    "scan": scan_res,
                }
            finally:
                try:
                    import shutil

                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

        res: Dict[str, Any] = {
            "ok": True,
            "engine": node_res.get("engine"),
            "standard_target": _standard_target(),
            "also_relevant": ["Section 508 (US)", "EN 301 549 (EU)"],
            "start_url": start_url_n,
            "max_pages": max_pages,
            "pages_scanned": len(pages),
            "pages": pages,
            "top_issues": summary,
            "scanned_urls": _scanned_urls(pages),
            "linked_documents": doc_scan,
        }

        report_path = Path(output_path).expanduser() if output_path else _default_report_path("web_a11y")
        ok, err = _write_json_report(report_path, res)
        res["report_path"] = str(report_path)
        if not ok:
            res["report_write_error"] = err
        return res

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
    queue: List[str] = []
    start_c = _canonical_url(start_url_n, strip_tracking_params=strip_tracking_params)
    queue.append(start_c)

    if seed_urls:
        for s in seed_urls:
            if not isinstance(s, str):
                continue
            sn = _normalize_url(s)
            if not sn:
                continue
            c = _canonical_url(sn, strip_tracking_params=strip_tracking_params)
            if c not in queue:
                queue.append(c)

    crawl_base_url = start_url_n

    if use_sitemap:
        seeds = _sitemap_seed_urls(start_url_n, sitemap_url, cap=max(25, max_pages * 5))
        for s in seeds:
            c = _canonical_url(s, strip_tracking_params=strip_tracking_params)
            if c not in queue:
                queue.append(c)

    def pop_next() -> Optional[str]:
        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            if _looks_like_login_url(url):
                visited.add(url)
                continue
            if _should_skip(url, include_url_patterns, exclude_url_patterns):
                visited.add(url)
                continue
            if same_domain_only:
                if include_subdomains:
                    if not _same_domain_or_subdomain(crawl_base_url, url):
                        visited.add(url)
                        continue
                elif not _same_site(crawl_base_url, url):
                    visited.add(url)
                    continue
                visited.add(url)
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

            try:
                body_text = page.text_content("body") or ""
            except Exception:
                body_text = ""

            if _looks_like_mfa(page.url, body_text):
                scanned.append(
                    {
                        "url": login_cfg.login_url,
                        "title": page.title(),
                        "violations_count": 0,
                        "violations": [],
                        "note": "Login requires 2FA; continuing with public crawl only.",
                        "login_status": "2fa_required",
                    }
                )
                page.goto(start_url_n, wait_until="domcontentloaded")
                page.wait_for_timeout(wait_ms)

            if login_cfg.post_login_url_prefix and not page.url.startswith(login_cfg.post_login_url_prefix):
                pass

        last_nav = 0.0

        while len(scanned) < max_pages:
            url = pop_next()
            if url is None:
                break

            visited.add(url)

            try:
                if min_time_between_pages_ms:
                    import time

                    now = time.time() * 1000
                    delta = now - last_nav
                    if delta < min_time_between_pages_ms:
                        time.sleep((min_time_between_pages_ms - delta) / 1000)
                    last_nav = time.time() * 1000

                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(wait_ms)

                final_url = _canonical_url(page.url, strip_tracking_params=strip_tracking_params)
                if not scanned:
                    crawl_base_url = final_url

                if same_domain_only:
                    in_scope = _same_domain_or_subdomain(crawl_base_url, final_url) if include_subdomains else _same_site(crawl_base_url, final_url)
                    if not in_scope:
                        scanned.append(
                            {
                                "url": url,
                                "final_url": final_url,
                                "title": page.title(),
                                "violations_count": 0,
                                "violations": [],
                                "note": "Redirected off-site (likely login); continuing public crawl.",
                            }
                        )
                        visited.add(final_url)
                        page.goto(start_url_n, wait_until="domcontentloaded")
                        page.wait_for_timeout(wait_ms)
                        continue
                visited.add(final_url)

                axe = Axe.from_page(page)
                results = axe.run()

                violations = results.get("violations") or []
                page_entry: Dict[str, Any] = {
                    "url": url,
                    "final_url": final_url,
                    "title": page.title(),
                    "violations_count": len(violations) if isinstance(violations, list) else 0,
                    "violations": violations,
                }
                scanned.append(page_entry)

                hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
                if isinstance(hrefs, list):
                    extracted = _extract_links(final_url, [str(x) for x in hrefs])
                    if not extracted and auto_use_sitemap_on_stall and not use_sitemap and not scanned:
                        seeds = _sitemap_seed_urls(crawl_base_url, sitemap_url, cap=max(25, max_pages * 5))
                        for s in seeds:
                            c = _canonical_url(s, strip_tracking_params=strip_tracking_params)
                            if c not in queue and c not in visited:
                                queue.append(c)
                        extracted = _extract_links(final_url, [str(x) for x in hrefs])

                    for link in extracted:
                        c = _canonical_url(link, strip_tracking_params=strip_tracking_params)
                        if _looks_like_login_url(c):
                            continue
                        if same_domain_only:
                            if include_subdomains:
                                if not _same_domain_or_subdomain(crawl_base_url, c):
                                    continue
                            elif not _same_site(crawl_base_url, c):
                                continue
                        if c not in visited and c not in queue:
                            queue.append(c)

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
        "standard_target": _standard_target(),
        "also_relevant": ["Section 508 (US)", "EN 301 549 (EU)"],
        "start_url": start_url_n,
        "max_pages": max_pages,
        "pages_scanned": len(scanned),
        "pages": scanned,
        "scanned_urls": _scanned_urls(scanned),
        "top_issues": summary,
        "export": {
            "note": "If you want, I can add a tool to write a JSON/HTML report file to disk.",
            "json": json.dumps({"pages": scanned, "top_issues": summary}, ensure_ascii=False)[:20000],
        },
    }


@function_tool
def run_multisite_accessibility_audit(
    start_urls: List[str],
    max_pages_per_site: int = 25,
    max_total_pages: Optional[int] = None,
    include_subdomains: bool = False,
    seed_urls: Optional[List[str]] = None,
    include_url_patterns: Optional[List[str]] = None,
    exclude_url_patterns: Optional[List[str]] = None,
    headless: bool = True,
    wait_ms: int = 500,
    output_path: Optional[str] = None,
    use_sitemap: bool = False,
    sitemap_url: Optional[str] = None,
    min_time_between_pages_ms: int = 0,
    strip_tracking_params: bool = True,
) -> Dict[str, Any]:
    """Scan multiple sites and write a combined JSON report."""

    cleaned = [
        _normalize_url(u)
        for u in start_urls
        if isinstance(u, str) and _normalize_url(u)
    ]
    if not cleaned:
        return {"ok": False, "error": "start_urls must include at least one valid URL"}

    per_site: List[Dict[str, Any]] = []
    all_violations: List[Dict[str, Any]] = []
    all_urls: List[str] = []

    remaining = max_total_pages if (isinstance(max_total_pages, int) and max_total_pages > 0) else None

    for u in cleaned:
        if remaining is not None and remaining <= 0:
            break

        max_pages = max_pages_per_site
        if remaining is not None:
            max_pages = min(max_pages, remaining)

        r = run_accessibility_audit._original_func(
            start_url=u,
            max_pages=max_pages,
            same_domain_only=True,
            include_subdomains=include_subdomains,
            seed_urls=seed_urls,
            include_url_patterns=include_url_patterns,
            exclude_url_patterns=exclude_url_patterns,
            login_url=None,
            username=None,
            password=None,
            username_selector=None,
            password_selector=None,
            submit_selector=None,
            post_login_url_prefix=None,
            headless=headless,
            wait_ms=wait_ms,
            output_path=None,
            use_sitemap=use_sitemap,
            sitemap_url=sitemap_url,
            min_time_between_pages_ms=min_time_between_pages_ms,
            strip_tracking_params=strip_tracking_params,
        )
        per_site.append(r)
        scanned_urls = r.get("scanned_urls") if isinstance(r, dict) else None
        if isinstance(scanned_urls, list):
            for su in scanned_urls:
                if isinstance(su, str) and su and su not in all_urls:
                    all_urls.append(su)
        pages = r.get("pages")
        if isinstance(pages, list):
            for item in pages:
                if isinstance(item, dict) and isinstance(item.get("violations"), list):
                    all_violations.extend(item["violations"])

        pages_scanned = r.get("pages_scanned") if isinstance(r, dict) else None
        if remaining is not None and isinstance(pages_scanned, int):
            remaining -= pages_scanned

    combined: Dict[str, Any] = {
        "ok": True,
        "standard_target": _standard_target(),
        "also_relevant": ["Section 508 (US)", "EN 301 549 (EU)"],
        "sites": per_site,
        "top_issues": _summarize_violations(all_violations),
        "scanned_urls": all_urls,
        "max_pages_per_site": max_pages_per_site,
        "max_total_pages": max_total_pages,
        "pages_scanned_total": sum(int(s.get("pages_scanned", 0)) for s in per_site if isinstance(s, dict)),
    }

    report_path = Path(output_path).expanduser() if output_path else _default_report_path("multisite_web_a11y")
    ok, err = _write_json_report(report_path, combined)
    combined["report_path"] = str(report_path)
    if not ok:
        combined["report_write_error"] = err

    return combined
