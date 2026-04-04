import zipfile
from pathlib import Path


def main() -> int:
    base = Path(
        r"C:\\Users\\dylan\\OneDrive - The University of Texas-Rio Grande Valley\\Classes\\Spring 26\\DB"
    )
    pptx_files = sorted([p for p in base.rglob("*.pptx") if p.is_file()])
    print(f"pptx files: {len(pptx_files)}")
    for pptx in pptx_files:
        with zipfile.ZipFile(pptx, "r") as z:
            media = [n for n in z.namelist() if n.startswith("ppt/media/")]
            exts = sorted({Path(n).suffix.lower() for n in media})
        print(f"{pptx}: {exts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
