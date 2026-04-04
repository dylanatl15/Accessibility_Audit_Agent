import io
import zipfile
from pathlib import Path

from PIL import Image


def main() -> int:
    base = Path(
        r"C:\\Users\\dylan\\OneDrive - The University of Texas-Rio Grande Valley\\Classes\\Spring 26\\DB"
    )
    if not base.exists():
        print(f"DB folder not found: {base}")
        return 1

    pptx_files = sorted([p for p in base.rglob("*.pptx") if p.is_file()])
    print(f"pptx files: {len(pptx_files)}")

    checked = 0
    failures: list[tuple[str, str, str, str, int]] = []

    for pptx in pptx_files:
        with zipfile.ZipFile(pptx, "r") as z:
            media = [n for n in z.namelist() if n.startswith("ppt/media/")]
            for n in media:
                ext = Path(n).suffix.lower()
                if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                data = z.read(n)
                checked += 1
                try:
                    im = Image.open(io.BytesIO(data))
                    im.verify()
                except Exception as e:
                    failures.append((str(pptx), n, ext, str(e), len(data)))

    print(f"checked raster images: {checked}")
    print(f"decode failures: {len(failures)}")
    for pptx, n, ext, err, size in failures:
        print(f"{pptx} | {n} | {ext} | {size} bytes | {err}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
