from __future__ import annotations

import os
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from omniagents import function_tool


@dataclass(frozen=True)
class _ImageOccurrence:
    doc_type: str
    document_path: str
    occurrence_id: str
    container: str
    slide_or_page: Optional[int]
    media_path_in_archive: str
    extracted_path: str
    original_extracted_path: Optional[str]
    vision_path: Optional[str]
    conversion_error: Optional[str]
    current_alt: Optional[str]


def _tmp_root() -> Path:
    root = Path(__file__).resolve().parents[1] / ".tmp_a11y"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_tmp_root_contents() -> Dict[str, Any]:
    root = _tmp_root()
    deleted: List[str] = []
    errors: List[str] = []

    def onerror(func, path, exc_info):
        try:
            os.chmod(path, 0o666)
            func(path)
        except Exception as e:
            errors.append(f"{path}: {e}")

    for p in root.iterdir():
        try:
            if p.is_dir():
                shutil.rmtree(p, onerror=onerror)
            else:
                p.unlink()
            deleted.append(str(p))
        except Exception as e:
            errors.append(f"{p}: {e}")
    return {"ok": len(errors) == 0, "deleted": deleted, "errors": errors, "temp_root": str(root)}


def _new_session_dir() -> Path:
    d = _tmp_root() / str(uuid.uuid4())
    d.mkdir(parents=True, exist_ok=False)
    return d


def _read_zip_bytes(zip_path: Path, inner_path: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            return z.read(inner_path)
    except Exception:
        return None


def _read_zip_xml(zip_path: Path, inner_path: str):
    xml = _read_zip_bytes(zip_path, inner_path)
    if not xml:
        return None
    try:
        from lxml import etree  # type: ignore

        return etree.fromstring(xml)
    except Exception:
        return None


def _rels_map(zip_path: Path, rels_path: str) -> Dict[str, str]:
    root = _read_zip_xml(zip_path, rels_path)
    if root is None:
        return {}

    rels: Dict[str, str] = {}
    for rel in root.xpath(".//*[local-name()='Relationship']"):
        rid = rel.get("Id")
        target = rel.get("Target")
        if rid and target:
            rels[str(rid)] = str(target)
    return rels


def _resolve_zip_target(base_inner_path: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")

    base = PurePosixPath(base_inner_path).parent
    joined = base.joinpath(PurePosixPath(target))
    parts: List[str] = []
    for part in joined.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in name)
    return cleaned[:200] or "image"


def _try_convert_to_png(input_path: Path) -> Tuple[Optional[Path], Optional[str]]:
    ext = input_path.suffix.lower()
    if ext not in {".emf", ".wmf"}:
        return None, None

    out = input_path.with_suffix(".png")
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "$in=$args[0]; $out=$args[1]; "
            "Add-Type -AssemblyName System.Drawing; "
            "$mf=New-Object System.Drawing.Imaging.Metafile($in); "
            "$w=[Math]::Max(1,$mf.Width); $h=[Math]::Max(1,$mf.Height); "
            "$bmp=New-Object System.Drawing.Bitmap($w,$h); "
            "$g=[System.Drawing.Graphics]::FromImage($bmp); "
            "$g.Clear([System.Drawing.Color]::White); "
            "$g.DrawImage($mf,0,0,$w,$h); "
            "$bmp.Save($out,[System.Drawing.Imaging.ImageFormat]::Png); "
            "$g.Dispose(); $bmp.Dispose(); $mf.Dispose();"
        ),
        str(input_path),
        str(out),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip()
            return None, err or f"Conversion failed (exit {res.returncode})."
    except Exception as e:
        return None, str(e)

    if out.exists() and out.is_file() and out.stat().st_size > 0:
        return out, None
    return None, "Conversion produced no output."


def _is_vision_supported(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _extract_docx_images(docx_path: Path, session_dir: Path) -> List[_ImageOccurrence]:
    occurrences: List[_ImageOccurrence] = []

    doc_xml = _read_zip_xml(docx_path, "word/document.xml")
    if doc_xml is None:
        return occurrences

    rels = _rels_map(docx_path, "word/_rels/document.xml.rels")

    doc_pr_nodes = doc_xml.xpath(".//*[local-name()='drawing']//*[local-name()='docPr']")

    for idx, doc_pr in enumerate(doc_pr_nodes, start=1):
        drawing = doc_pr.getparent()
        while drawing is not None and getattr(drawing, "tag", "") is not None and "drawing" not in str(drawing.tag):
            drawing = drawing.getparent()

        rid = None
        if drawing is not None:
            blips = drawing.xpath(".//*[local-name()='blip']")
            for b in blips:
                for attr_name in ("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", "r:embed"):
                    if attr_name in b.attrib:
                        rid = b.attrib.get(attr_name)
                        break
                if rid:
                    break

        target = rels.get(str(rid)) if rid else None
        if not target:
            continue

        inner_media = _resolve_zip_target("word/document.xml", target)

        media_bytes = _read_zip_bytes(docx_path, inner_media)
        if not media_bytes:
            continue

        ext = Path(inner_media).suffix or ".img"
        out_name = _safe_filename(f"docx_{idx}{ext}")
        extracted_path = session_dir / out_name
        extracted_path.write_bytes(media_bytes)

        converted_path, conversion_error = _try_convert_to_png(extracted_path)
        original_extracted_path = str(extracted_path) if converted_path else None
        vision_path: Optional[str]
        if converted_path:
            vision_path = str(converted_path)
        elif _is_vision_supported(extracted_path):
            vision_path = str(extracted_path)
        else:
            vision_path = None

        extracted_path_str = str(extracted_path)
        if vision_path is None:
            original_extracted_path = original_extracted_path or extracted_path_str
            try:
                extracted_path.unlink(missing_ok=True)
            except Exception:
                pass
            extracted_path_str = ""

        current_alt = doc_pr.get("descr") or doc_pr.get("title")

        occurrences.append(
            _ImageOccurrence(
                doc_type="docx",
                document_path=str(docx_path),
                occurrence_id=f"docx:{idx}",
                container="word/document.xml",
                slide_or_page=None,
                media_path_in_archive=inner_media,
                extracted_path=extracted_path_str,
                original_extracted_path=original_extracted_path,
                vision_path=vision_path,
                conversion_error=conversion_error,
                current_alt=current_alt,
            )
        )

    return occurrences


def _extract_pptx_images(pptx_path: Path, session_dir: Path) -> List[_ImageOccurrence]:
    occurrences: List[_ImageOccurrence] = []

    try:
        with zipfile.ZipFile(pptx_path, "r") as z:
            slide_names = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            slide_names.sort()

        for slide_idx, slide_name in enumerate(slide_names, start=1):
            root = _read_zip_xml(pptx_path, slide_name)
            if root is None:
                continue

            rels_path = f"ppt/slides/_rels/{Path(slide_name).name}.rels"
            rels = _rels_map(pptx_path, rels_path)

            pics = root.xpath(".//*[local-name()='pic']")
            for pic_i, pic in enumerate(pics, start=1):
                c_nv_pr = pic.xpath(".//*[local-name()='cNvPr']")
                if not c_nv_pr:
                    continue
                c = c_nv_pr[0]
                current_alt = c.get("descr") or c.get("title")

                rid = None
                blips = pic.xpath(".//*[local-name()='blip']")
                for b in blips:
                    for attr_name in ("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", "r:embed"):
                        if attr_name in b.attrib:
                            rid = b.attrib.get(attr_name)
                            break
                    if rid:
                        break

                target = rels.get(str(rid)) if rid else None
                if not target:
                    continue

                inner_media = _resolve_zip_target(slide_name, target)

                media_bytes = _read_zip_bytes(pptx_path, inner_media)
                if not media_bytes:
                    continue

                ext = Path(inner_media).suffix or ".img"
                out_name = _safe_filename(f"pptx_s{slide_idx}_{pic_i}{ext}")
                extracted_path = session_dir / out_name
                extracted_path.write_bytes(media_bytes)

                converted_path, conversion_error = _try_convert_to_png(extracted_path)
                original_extracted_path = str(extracted_path) if converted_path else None
                vision_path: Optional[str]
                if converted_path:
                    vision_path = str(converted_path)
                elif _is_vision_supported(extracted_path):
                    vision_path = str(extracted_path)
                else:
                    vision_path = None

                extracted_path_str = str(extracted_path)
                if vision_path is None:
                    original_extracted_path = original_extracted_path or extracted_path_str
                    try:
                        extracted_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    extracted_path_str = ""

                occurrences.append(
                    _ImageOccurrence(
                        doc_type="pptx",
                        document_path=str(pptx_path),
                        occurrence_id=f"pptx:{slide_idx}:{pic_i}",
                        container=slide_name,
                        slide_or_page=slide_idx,
                        media_path_in_archive=inner_media,
                        extracted_path=extracted_path_str,
                        original_extracted_path=original_extracted_path,
                        vision_path=vision_path,
                        conversion_error=conversion_error,
                        current_alt=current_alt,
                    )
                )

    except Exception:
        return occurrences

    return occurrences


@function_tool
def extract_document_images(path: str) -> Dict[str, Any]:
    """Extract embedded images from a DOCX or PPTX to a temporary folder.

    Args:
        path: Path to a .docx or .pptx file.

    Returns:
        Dict including session_id, temp_dir, and a list of image occurrences with file paths.
    """

    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}

    session_dir = _new_session_dir()

    ext = p.suffix.lower()
    if ext == ".docx":
        occ = _extract_docx_images(p, session_dir)
    elif ext == ".pptx":
        occ = _extract_pptx_images(p, session_dir)
    else:
        cleanup_temp_artifacts._original_func(str(session_dir))
        return {"ok": False, "error": "Supported types: .docx, .pptx"}

    return {
        "ok": True,
        "path": str(p),
        "session_id": session_dir.name,
        "temp_dir": str(session_dir),
        "images": [
            {
                "doc_type": o.doc_type,
                "occurrence_id": o.occurrence_id,
                "container": o.container,
                "slide_or_page": o.slide_or_page,
                "media_path_in_archive": o.media_path_in_archive,
                "extracted_path": o.extracted_path,
                "original_extracted_path": o.original_extracted_path,
                "vision_path": o.vision_path,
                "read_image_path": o.vision_path,
                "conversion_error": o.conversion_error,
                "current_alt": o.current_alt,
            }
            for o in occ
        ],
    }


def _apply_docx_alt_text(docx_path: Path, mapping: Dict[str, str], output_path: Path) -> Tuple[int, List[str]]:
    doc_xml_bytes = _read_zip_bytes(docx_path, "word/document.xml")
    if not doc_xml_bytes:
        shutil.copyfile(docx_path, output_path)
        return 0, ["Could not read document.xml; copied file unchanged."]

    try:
        from lxml import etree  # type: ignore

        root = etree.fromstring(doc_xml_bytes)
        doc_pr_nodes = root.xpath(".//*[local-name()='drawing']//*[local-name()='docPr']")

        changed = 0
        for idx, doc_pr in enumerate(doc_pr_nodes, start=1):
            key = f"docx:{idx}"
            alt = mapping.get(key)
            if not alt:
                continue
            doc_pr.set("descr", alt)
            changed += 1

        updated = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None)

        with zipfile.ZipFile(docx_path, "r") as zin:
            with zipfile.ZipFile(output_path, "w") as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename == "word/document.xml":
                        data = updated
                    zout.writestr(info, data)

        return changed, ["Applied alt text to DOCX images via docPr descr."]

    except Exception:
        shutil.copyfile(docx_path, output_path)
        return 0, ["Failed to update document.xml; copied file unchanged."]


def _apply_pptx_alt_text(pptx_path: Path, mapping: Dict[str, str], output_path: Path) -> Tuple[int, List[str]]:
    rewrites: Dict[str, bytes] = {}
    changed = 0

    try:
        with zipfile.ZipFile(pptx_path, "r") as z:
            slide_names = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            slide_names.sort()

            from lxml import etree  # type: ignore

            for slide_idx, slide_name in enumerate(slide_names, start=1):
                xml = z.read(slide_name)
                root = etree.fromstring(xml)
                pics = root.xpath(".//*[local-name()='pic']")
                slide_changed = 0

                for pic_i, pic in enumerate(pics, start=1):
                    key = f"pptx:{slide_idx}:{pic_i}"
                    alt = mapping.get(key)
                    if not alt:
                        continue
                    c_nv_pr = pic.xpath(".//*[local-name()='cNvPr']")
                    if not c_nv_pr:
                        continue
                    c_nv_pr[0].set("descr", alt)
                    slide_changed += 1

                if slide_changed:
                    changed += slide_changed
                    rewrites[slide_name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None)

        with zipfile.ZipFile(pptx_path, "r") as zin:
            with zipfile.ZipFile(output_path, "w") as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename in rewrites:
                        data = rewrites[info.filename]
                    zout.writestr(info, data)

        return changed, ["Applied alt text to PPTX images via cNvPr descr."]

    except Exception:
        shutil.copyfile(pptx_path, output_path)
        return 0, ["Failed to update PPTX slides; copied file unchanged."]


@function_tool
def apply_document_alt_text(
    path: str,
    alt_text_entries: List[List[str]],
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply provided alt text strings to a DOCX or PPTX and write an updated file.

    Args:
        path: Path to the input .docx or .pptx.
        alt_text_entries: List of [occurrence_id, alt_text] pairs.
        output_path: Optional explicit output path; defaults to *_accessible next to original.

    Returns:
        Dict with how many entries were applied.
    """

    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}

    out = Path(output_path).expanduser() if output_path else p.with_name(f"{p.stem}_accessible{p.suffix}")
    if out.resolve() == p.resolve():
        return {"ok": False, "error": "Refusing to overwrite the original file. Provide a different output_path."}

    mapping: Dict[str, str] = {}
    for entry in alt_text_entries:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        oid = str(entry[0] or "").strip()
        alt = str(entry[1] or "").strip()
        if oid and alt:
            mapping[oid] = alt

    ext = p.suffix.lower()
    if ext == ".docx":
        applied, notes = _apply_docx_alt_text(p, mapping, out)
    elif ext == ".pptx":
        applied, notes = _apply_pptx_alt_text(p, mapping, out)
    else:
        return {"ok": False, "error": "Supported types: .docx, .pptx"}

    return {
        "ok": True,
        "input_path": str(p),
        "output_path": str(out),
        "applied": applied,
        "notes": notes,
        "message": f"Wrote updated file to: {out}",
    }


@function_tool
def cleanup_temp_artifacts(temp_dir: str) -> Dict[str, Any]:
    """Delete a temporary extraction folder created by extract_document_images.

    Args:
        temp_dir: The temp_dir path returned by extract_document_images.

    Returns:
        Dict indicating deletion status.
    """

    p = Path(temp_dir).expanduser()
    try:
        root = _tmp_root().resolve()
        pr = p.resolve()
        if root not in pr.parents and pr != root:
            return {"ok": False, "error": "Refusing to delete non-temp directory."}
    except Exception:
        return {"ok": False, "error": "Invalid temp_dir."}

    if not p.exists():
        return {"ok": True, "deleted": False, "temp_dir": str(p), "message": "Temp dir already absent."}

    try:
        shutil.rmtree(p)
        return {"ok": True, "deleted": True, "temp_dir": str(p), "message": "Temp dir deleted."}
    except Exception as e:
        return {"ok": False, "error": f"Failed to delete temp_dir: {e}", "temp_dir": str(p)}


@function_tool
def cleanup_all_temp_artifacts() -> Dict[str, Any]:
    """Delete all temporary extraction folders under .tmp_a11y."""

    return _cleanup_tmp_root_contents()
