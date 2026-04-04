from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from omniagents import function_tool


DEFAULT_EXTENSIONS = [".pdf", ".docx", ".ppt", ".pptx"]
DEFAULT_MAX_FILES = 50
DEFAULT_EXCLUDE_DIR_PATTERNS = [
    r"(^|\\|/)\.git($|\\|/)",
    r"(^|\\|/)node_modules($|\\|/)",
    r"(^|\\|/)__pycache__($|\\|/)",
    r"(^|\\|/)\.venv($|\\|/)",
    r"(^|\\|/)venv($|\\|/)",
    r"(^|\\|/)AppData($|\\|/)",
    r"(^|\\|/)Windows($|\\|/)",
    r"(^|\\|/)Program Files($|\\|/)",
    r"(^|\\|/)Program Files \(x86\)($|\\|/)",
]


@dataclass(frozen=True)
class _Issue:
    file_path: str
    file_type: str
    standard: str
    severity: str
    code: str
    message: str
    location: Optional[str]
    fixable: bool
    suggested_fix: Optional[str]


def _as_issue(issue: _Issue) -> Dict[str, Any]:
    return {
        "file_path": issue.file_path,
        "file_type": issue.file_type,
        "standard": issue.standard,
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "location": issue.location,
        "fixable": issue.fixable,
        "suggested_fix": issue.suggested_fix,
    }


def _is_drive_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    return resolved.parent == resolved and resolved.drive != ""


def _matches_any(patterns: Optional[Sequence[str]], value: str) -> bool:
    if not patterns:
        return False
    for pattern in patterns:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return True
    return False


def _iter_files(
    root_dir: Path,
    *,
    recursive: bool,
    extensions: Sequence[str],
    exclude_dir_patterns: Optional[Sequence[str]],
) -> Iterable[Path]:
    exts = {e.lower() for e in extensions}
    if not recursive:
        for p in root_dir.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                yield p
        return

    for current_root, dirnames, filenames in os.walk(root_dir):
        current = Path(current_root)
        rel = str(current)
        if _matches_any(exclude_dir_patterns, rel):
            dirnames[:] = []
            continue

        kept_dirs: List[str] = []
        for d in dirnames:
            candidate = str(current / d)
            if _matches_any(exclude_dir_patterns, candidate):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for name in filenames:
            p = current / name
            if p.suffix.lower() in exts:
                yield p


def _count_pdf_text_chars(pdf_path: Path, max_pages: int = 5) -> Optional[int]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return None

    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return None

    count = 0
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        count += len(text.strip())
        if i >= max_pages - 1:
            break
    return count


def _audit_pdf(pdf_path: Path) -> List[_Issue]:
    issues: List[_Issue] = []

    text_chars = _count_pdf_text_chars(pdf_path)
    if text_chars is None:
        issues.append(
            _Issue(
                file_path=str(pdf_path),
                file_type="pdf",
                standard="PDF/UA (best-effort) + WCAG 2.2",
                severity="medium",
                code="pdf.missing_dependency",
                message="Cannot analyze PDF content (missing pypdf).",
                location=None,
                fixable=False,
                suggested_fix="Install pypdf to enable PDF checks.",
            )
        )
        return issues

    if text_chars == 0:
        issues.append(
            _Issue(
                file_path=str(pdf_path),
                file_type="pdf",
                standard="PDF/UA (best-effort)",
                severity="high",
                code="pdf.possibly_scanned",
                message="PDF appears to have little/no extractable text; it may be scanned and not screen-reader friendly.",
                location=None,
                fixable=False,
                suggested_fix="Run OCR (e.g., OCRmyPDF) and then add proper tags/reading order as needed.",
            )
        )

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        title = (reader.metadata.title if reader.metadata else None) if hasattr(reader, "metadata") else None
        if not title:
            issues.append(
                _Issue(
                    file_path=str(pdf_path),
                    file_type="pdf",
                    standard="WCAG 2.2 (2.4.2) / PDF/UA",
                    severity="low",
                    code="pdf.missing_title",
                    message="PDF metadata title is missing.",
                    location=None,
                    fixable=True,
                    suggested_fix="Set PDF metadata title to a meaningful document title.",
                )
            )
    except Exception:
        pass

    issues.append(
        _Issue(
            file_path=str(pdf_path),
            file_type="pdf",
            standard="PDF/UA (best-effort)",
            severity="medium",
            code="pdf.manual_review_required",
            message="Automated checks cannot confirm tagging, reading order, table structure, or artifacts. Manual remediation may be required.",
            location=None,
            fixable=False,
            suggested_fix="Use an accessibility checker in Acrobat Pro or a dedicated PDF/UA workflow.",
        )
    )

    return issues


def _read_zip_xml(zip_path: Path, inner_path: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            return z.read(inner_path)
    except Exception:
        return None


def _audit_docx(docx_path: Path) -> List[_Issue]:
    issues: List[_Issue] = []

    doc_xml = _read_zip_xml(docx_path, "word/document.xml")
    if not doc_xml:
        issues.append(
            _Issue(
                file_path=str(docx_path),
                file_type="docx",
                standard="WCAG 2.2",
                severity="high",
                code="docx.unreadable",
                message="Unable to read word/document.xml.",
                location=None,
                fixable=False,
                suggested_fix=None,
            )
        )
        return issues

    try:
        from lxml import etree  # type: ignore

        root = etree.fromstring(doc_xml)
        ns = root.nsmap.copy()
        ns.setdefault("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main")

        p_styles = root.xpath(".//w:pPr/w:pStyle/@w:val", namespaces=ns)
        heading_levels: List[int] = []
        for style in p_styles:
            m = re.match(r"Heading(\d+)$", str(style))
            if m:
                heading_levels.append(int(m.group(1)))

        if not heading_levels:
            issues.append(
                _Issue(
                    file_path=str(docx_path),
                    file_type="docx",
                    standard="WCAG 2.2 (1.3.1)",
                    severity="medium",
                    code="docx.no_headings",
                    message="No heading styles detected (Heading1/Heading2/etc.).",
                    location=None,
                    fixable=False,
                    suggested_fix="Use built-in heading styles to structure the document.",
                )
            )
        else:
            prev = heading_levels[0]
            for idx, level in enumerate(heading_levels[1:], start=2):
                if level - prev >= 2:
                    issues.append(
                        _Issue(
                            file_path=str(docx_path),
                            file_type="docx",
                            standard="WCAG 2.2 (1.3.1)",
                            severity="low",
                            code="docx.heading_skip",
                            message=f"Heading levels appear to skip (Heading{prev} -> Heading{level}).",
                            location=f"heading #{idx}",
                            fixable=False,
                            suggested_fix="Avoid skipping heading levels (e.g., Heading1 then Heading2).",
                        )
                    )
                    break
                prev = level

        drawing_docpr = root.xpath(".//w:drawing//*[local-name()='docPr']", namespaces=ns)
        missing_alt = 0
        for el in drawing_docpr:
            descr = el.get("descr") or el.get("{http://schemas.openxmlformats.org/drawingml/2006/main}descr")
            title = el.get("title")
            if (descr is None or str(descr).strip() == "") and (title is None or str(title).strip() == ""):
                missing_alt += 1

        if missing_alt:
            issues.append(
                _Issue(
                    file_path=str(docx_path),
                    file_type="docx",
                    standard="WCAG 2.2 (1.1.1)",
                    severity="high",
                    code="docx.image_missing_alt",
                    message=f"{missing_alt} image(s) appear to be missing alt text.",
                    location=None,
                    fixable=True,
                    suggested_fix="Add meaningful alt text to each informative image; mark decorative images as decorative.",
                )
            )

    except Exception:
        issues.append(
            _Issue(
                file_path=str(docx_path),
                file_type="docx",
                standard="WCAG 2.2",
                severity="medium",
                code="docx.parse_failed",
                message="Failed to parse document.xml for structural checks.",
                location=None,
                fixable=False,
                suggested_fix=None,
            )
        )

    return issues


def _audit_pptx(pptx_path: Path) -> List[_Issue]:
    issues: List[_Issue] = []

    try:
        with zipfile.ZipFile(pptx_path, "r") as z:
            slide_names = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            slide_names.sort()

            missing_alt_total = 0
            for slide_idx, slide_name in enumerate(slide_names, start=1):
                xml = z.read(slide_name)
                try:
                    from lxml import etree  # type: ignore

                    root = etree.fromstring(xml)
                    pic_nodes = root.xpath(".//*[local-name()='pic']")
                    for pic in pic_nodes:
                        cNvPr = pic.xpath(".//*[local-name()='cNvPr']")
                        if not cNvPr:
                            continue
                        el = cNvPr[0]
                        descr = el.get("descr")
                        title = el.get("title")
                        if (descr is None or str(descr).strip() == "") and (title is None or str(title).strip() == ""):
                            missing_alt_total += 1

                except Exception:
                    issues.append(
                        _Issue(
                            file_path=str(pptx_path),
                            file_type="pptx",
                            standard="WCAG 2.2",
                            severity="medium",
                            code="pptx.slide_parse_failed",
                            message="Failed to parse slide XML for checks.",
                            location=f"slide {slide_idx}",
                            fixable=False,
                            suggested_fix=None,
                        )
                    )

            if missing_alt_total:
                issues.append(
                    _Issue(
                        file_path=str(pptx_path),
                        file_type="pptx",
                        standard="WCAG 2.2 (1.1.1)",
                        severity="high",
                        code="pptx.image_missing_alt",
                        message=f"{missing_alt_total} image(s) appear to be missing alt text across slides.",
                        location=None,
                        fixable=True,
                        suggested_fix="Add alt text to informative images; mark decorative images as decorative.",
                    )
                )

    except Exception:
        issues.append(
            _Issue(
                file_path=str(pptx_path),
                file_type="pptx",
                standard="WCAG 2.2",
                severity="high",
                code="pptx.unreadable",
                message="Unable to read PPTX archive.",
                location=None,
                fixable=False,
                suggested_fix=None,
            )
        )

    return issues


def _audit_by_type(path: Path) -> List[_Issue]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _audit_pdf(path)
    if ext == ".docx":
        return _audit_docx(path)
    if ext == ".ppt":
        return [
            _Issue(
                file_path=str(path),
                file_type="ppt",
                standard="WCAG 2.2",
                severity="medium",
                code="ppt.legacy_needs_conversion",
                message="Legacy .ppt format requires conversion to .pptx before accessibility checks.",
                location=None,
                fixable=True,
                suggested_fix="Convert to .pptx (e.g., use convert_ppt_to_pptx) and then re-scan.",
            )
        ]
    if ext == ".pptx":
        return _audit_pptx(path)
    return []


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_accessible{input_path.suffix}")


def _copy_zip_with_rewrites(
    *,
    input_path: Path,
    output_path: Path,
    rewrites: Dict[str, bytes],
) -> None:
    with zipfile.ZipFile(input_path, "r") as zin:
        with zipfile.ZipFile(output_path, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename in rewrites:
                    data = rewrites[info.filename]
                zout.writestr(info, data)


def _apply_docx_fixes(input_path: Path, output_path: Path) -> Tuple[int, List[str]]:
    applied = 0
    notes: List[str] = []

    doc_xml = _read_zip_xml(input_path, "word/document.xml")
    if not doc_xml:
        shutil.copyfile(input_path, output_path)
        return applied, ["Could not read document.xml; copied file unchanged."]

    try:
        from lxml import etree  # type: ignore

        root = etree.fromstring(doc_xml)
        missing = 0
        for el in root.xpath(".//*[local-name()='drawing']//*[local-name()='docPr']"):
            descr = el.get("descr")
            title = el.get("title")
            if (descr is None or str(descr).strip() == "") and (title is None or str(title).strip() == ""):
                el.set("descr", "Image")
                missing += 1

        if missing:
            applied += missing
            notes.append(f"Set placeholder alt text for {missing} image(s).")

        updated = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None)
        _copy_zip_with_rewrites(input_path=input_path, output_path=output_path, rewrites={"word/document.xml": updated})
        return applied, notes

    except Exception:
        shutil.copyfile(input_path, output_path)
        return applied, ["Failed to parse/modify document.xml; copied file unchanged."]


def _apply_pptx_fixes(input_path: Path, output_path: Path) -> Tuple[int, List[str]]:
    applied = 0
    notes: List[str] = []

    rewrites: Dict[str, bytes] = {}

    try:
        with zipfile.ZipFile(input_path, "r") as z:
            slide_names = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            slide_names.sort()

            from lxml import etree  # type: ignore

            for slide_name in slide_names:
                xml = z.read(slide_name)
                root = etree.fromstring(xml)
                changed = 0

                for pic in root.xpath(".//*[local-name()='pic']"):
                    cNvPr = pic.xpath(".//*[local-name()='cNvPr']")
                    if not cNvPr:
                        continue
                    el = cNvPr[0]
                    descr = el.get("descr")
                    title = el.get("title")
                    if (descr is None or str(descr).strip() == "") and (title is None or str(title).strip() == ""):
                        el.set("descr", "Image")
                        changed += 1

                if changed:
                    applied += changed
                    rewrites[slide_name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None)

        if rewrites:
            notes.append("Set placeholder alt text for one or more images in slides.")

        _copy_zip_with_rewrites(input_path=input_path, output_path=output_path, rewrites=rewrites)
        return applied, notes

    except Exception:
        shutil.copyfile(input_path, output_path)
        return applied, ["Failed to parse/modify PPTX slides; copied file unchanged."]


def _apply_pdf_fixes(input_path: Path, output_path: Path) -> Tuple[int, List[str]]:
    applied = 0
    notes: List[str] = []

    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore

        reader = PdfReader(str(input_path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        meta = reader.metadata or {}
        title = getattr(meta, "title", None) if hasattr(meta, "title") else None
        if not title:
            writer.add_metadata({"/Title": input_path.stem})
            applied += 1
            notes.append("Set PDF metadata title.")

        with open(output_path, "wb") as f:
            writer.write(f)

        return applied, notes

    except Exception:
        shutil.copyfile(input_path, output_path)
        return applied, ["Could not modify PDF metadata; copied file unchanged."]


@function_tool
def list_documents_for_a11y_scan(
    root_dir: str,
    recursive: bool = True,
    max_files: int = DEFAULT_MAX_FILES,
    extensions: Optional[List[str]] = None,
    exclude_dir_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """List documents in a directory that are candidates for accessibility scanning.

    Args:
        root_dir: Directory to scan.
        recursive: Whether to walk subdirectories.
        max_files: Safety cap on number of matched files returned.
        extensions: File extensions to include (default: .pdf, .docx, .pptx).
        exclude_dir_patterns: Regex patterns for directories to skip.

    Returns:
        Dict with file list and safety warnings.
    """

    root = Path(root_dir).expanduser()
    exts = extensions or DEFAULT_EXTENSIONS
    excludes = exclude_dir_patterns or DEFAULT_EXCLUDE_DIR_PATTERNS

    if not root.exists() or not root.is_dir():
        return {"ok": False, "error": f"Not a directory: {root_dir}"}

    warnings: List[str] = []
    if _is_drive_root(root):
        warnings.append("Root directory appears to be a drive root; scanning may be slow. Consider narrowing the scope.")

    files: List[str] = []
    for p in _iter_files(root, recursive=recursive, extensions=exts, exclude_dir_patterns=excludes):
        files.append(str(p))
        if len(files) >= max_files:
            warnings.append(f"Reached max_files cap ({max_files}).")
            break

    return {
        "ok": True,
        "root_dir": str(root),
        "recursive": recursive,
        "extensions": exts,
        "max_files": max_files,
        "files": files,
        "warnings": warnings,
    }


@function_tool
def scan_documents_accessibility(
    root_dir: str,
    recursive: bool = True,
    max_files: int = DEFAULT_MAX_FILES,
    extensions: Optional[List[str]] = None,
    exclude_dir_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Scan documents in a directory and report accessibility issues.

    Standards:
      - Primary rating: WCAG 2.2 AA
      - PDFs: include PDF/UA best-effort flags + manual remediation notes

    Args:
        root_dir: Directory to scan.
        recursive: Whether to walk subdirectories.
        max_files: Safety cap on number of matched files.
        extensions: File extensions to include (default: .pdf, .docx, .pptx).
        exclude_dir_patterns: Regex patterns for directories to skip.

    Returns:
        Dict with issues grouped by file and a summary.
    """

    listing = list_documents_for_a11y_scan._original_func(
        root_dir=root_dir,
        recursive=recursive,
        max_files=max_files,
        extensions=extensions,
        exclude_dir_patterns=exclude_dir_patterns,
    )
    if not listing.get("ok"):
        return listing

    files = [Path(p) for p in listing.get("files", [])]

    issues: List[_Issue] = []
    per_file: Dict[str, Dict[str, Any]] = {}

    for p in files:
        file_issues = _audit_by_type(p)
        issues.extend(file_issues)
        per_file[str(p)] = {
            "file_type": p.suffix.lower().lstrip("."),
            "issues": [_as_issue(i) for i in file_issues],
        }

    counts: Dict[str, int] = {"blocker": 0, "high": 0, "medium": 0, "low": 0}
    fixable = 0
    for i in issues:
        sev = i.severity.lower()
        if sev in counts:
            counts[sev] += 1
        if i.fixable:
            fixable += 1

    return {
        "ok": True,
        "standard_target": "WCAG 2.2 AA",
        "pdf_standard": "PDF/UA (best-effort)",
        "root_dir": listing.get("root_dir"),
        "files_scanned": len(files),
        "warnings": listing.get("warnings", []),
        "summary": {
            "issues_total": len(issues),
            "by_severity": counts,
            "fixable_issues": fixable,
        },
        "files": per_file,
    }


@function_tool
def propose_document_fixes(path: str) -> Dict[str, Any]:
    """Propose accessibility fixes for a single document without modifying it.

    Args:
        path: Path to a .pdf, .docx, or .pptx file.

    Returns:
        Dict with detected issues and a proposed fix plan.
    """

    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}

    issues = _audit_by_type(p)
    fix_plan: List[Dict[str, Any]] = []

    for i in issues:
        if i.fixable:
            fix_plan.append(
                {
                    "code": i.code,
                    "severity": i.severity,
                    "message": i.message,
                    "proposed_action": i.suggested_fix,
                }
            )

    return {
        "ok": True,
        "path": str(p),
        "file_type": p.suffix.lower().lstrip("."),
        "standard_target": "WCAG 2.2 AA",
        "pdf_standard": "PDF/UA (best-effort)",
        "issues": [_as_issue(x) for x in issues],
        "fix_plan": fix_plan,
        "notes": [
            "Fixes are best-effort and may use placeholders (e.g., 'Image') where meaningful alt text must be authored by a human.",
            "For PDFs, many accessibility requirements (tagging/reading order) usually require dedicated remediation tools.",
        ],
    }


@function_tool
def apply_document_fixes(path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Apply best-effort accessibility fixes and write an updated file.

    This tool writes a new file alongside the original by default.

    Args:
        path: Path to the input .pdf, .docx, or .pptx.
        output_path: Optional explicit output path. If omitted, creates *_accessible next to original.

    Returns:
        Dict describing what was changed and where the output was written.
    """

    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}

    out = Path(output_path).expanduser() if output_path else _default_output_path(p)
    if out.resolve() == p.resolve():
        return {"ok": False, "error": "Refusing to overwrite the original file. Provide a different output_path."}

    ext = p.suffix.lower()
    if ext == ".docx":
        applied, notes = _apply_docx_fixes(p, out)
    elif ext == ".pptx":
        applied, notes = _apply_pptx_fixes(p, out)
    elif ext == ".pdf":
        applied, notes = _apply_pdf_fixes(p, out)
    elif ext == ".ppt":
        return {
            "ok": False,
            "error": "Legacy .ppt must be converted to .pptx first (use convert_ppt_to_pptx).",
        }
    else:
        return {"ok": False, "error": "Unsupported file type. Use .pdf, .docx, or .pptx."}

    return {
        "ok": True,
        "input_path": str(p),
        "output_path": str(out),
        "applied_changes_count": applied,
        "notes": notes,
        "next": "Re-scan the output file and manually review remaining issues.",
    }
