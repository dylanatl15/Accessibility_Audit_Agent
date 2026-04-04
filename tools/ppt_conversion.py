from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from omniagents import function_tool


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_converted.pptx")


@function_tool
def convert_ppt_to_pptx(input_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Convert a legacy .ppt file to .pptx.

    This tool uses Microsoft PowerPoint via Windows COM automation.

    Args:
        input_path: Path to a .ppt file.
        output_path: Optional output .pptx path. Defaults to *_converted.pptx alongside the input.

    Returns:
        Dict with conversion status and the output path.
    """

    src = Path(input_path).expanduser()
    if not src.exists() or not src.is_file():
        return {"ok": False, "error": f"Not a file: {input_path}"}
    if src.suffix.lower() != ".ppt":
        return {"ok": False, "error": "input_path must end with .ppt"}

    dst = Path(output_path).expanduser() if output_path else _default_output_path(src)
    if dst.suffix.lower() != ".pptx":
        return {"ok": False, "error": "output_path must end with .pptx"}
    if dst.exists():
        return {"ok": False, "error": f"Refusing to overwrite existing file: {dst}"}

    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception:
        return {
            "ok": False,
            "error": "Missing dependency: pywin32 (and PowerPoint installed) is required to convert .ppt files.",
            "hint": "Install pywin32 and ensure Microsoft PowerPoint is installed. Alternatively install LibreOffice and add soffice to PATH.",
        }

    pythoncom.CoInitialize()
    app = None
    presentation = None
    try:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = 1
        presentation = app.Presentations.Open(str(src), WithWindow=True)

        ppSaveAsOpenXMLPresentation = 24
        presentation.SaveAs(str(dst), ppSaveAsOpenXMLPresentation)

        return {"ok": True, "input_path": str(src), "output_path": str(dst)}
    except Exception as e:
        return {"ok": False, "error": f"Conversion failed: {e}"}
    finally:
        try:
            if presentation is not None:
                presentation.Close()
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
