import zipfile
from pathlib import Path


def sniff(b: bytes) -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if b.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
        return "webp"
    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"):
        return "gif"
    if b.startswith(b"BM"):
        return "bmp"
    if b[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if b.lstrip().startswith(b"<svg"):
        return "svg"
    if b.startswith(b"PK\x03\x04"):
        return "zip"
    if b.startswith(b"\xd7\xcd\xc6\x9a") or b.startswith(b"\x01\x00\x00\x00"):
        return "wmf/emf?"
    return "unknown"


def main() -> int:
    base = Path(
        r"C:\\Users\\dylan\\OneDrive - The University of Texas-Rio Grande Valley\\Classes\\Spring 26\\DB"
    )
    if not base.exists():
        print(f"DB folder not found: {base}")
        return 1

    pptx_files = sorted([p for p in base.rglob("*.pptx") if p.is_file()])
    print(f"pptx files: {len(pptx_files)}")

    suspicious: list[tuple[str, str, str, str, int]] = []

    for pptx in pptx_files:
        try:
            with zipfile.ZipFile(pptx, "r") as z:
                media = [n for n in z.namelist() if n.startswith("ppt/media/")]
                for n in media:
                    b = z.read(n)
                    ext = Path(n).suffix.lower().lstrip(".")
                    kind = sniff(b[:128])

                    expected = None
                    if ext in {"jpg", "jpeg"}:
                        expected = "jpeg"
                    elif ext in {"tif", "tiff"}:
                        expected = "tiff"
                    elif ext in {"png", "webp", "gif", "bmp"}:
                        expected = ext

                    if kind == "unknown":
                        suspicious.append((str(pptx), n, ext, kind, len(b)))
                    elif expected and kind != expected:
                        suspicious.append((str(pptx), n, ext, kind, len(b)))
        except Exception as e:
            suspicious.append((str(pptx), "<zip-error>", "", f"zip-error:{e}", 0))

    print(f"suspicious media: {len(suspicious)}")
    for row in suspicious[:200]:
        pptx, n, ext, kind, size = row
        print(f"{pptx} | {n} | ext={ext} sniff={kind} size={size}")
    if len(suspicious) > 200:
        print("... truncated ...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
