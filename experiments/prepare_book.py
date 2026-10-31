import re
import sys
import html
from pathlib import Path

# e-derslik kitabindan lazim olan seyfelerin metnini cixarir
BOOK_DIR = Path("data/riyaziyyat-5-az-1/units")
OUT_DIR = Path("data/pages")


def page_text(path):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(TAPŞIRIQ|NÜMUNƏ)\s*-->", r"\1", text)
    text = text.replace("TAPŞIRIQ ", "").replace("Riyaziyyat 5 (1-ci hissə)", "")
    return text.strip()


def export(start, end, name):
    parts = []
    for n in range(start, end + 1):
        p = BOOK_DIR / "unit-1" / f"page{n}.xhtml"
        if not p.exists():
            continue
        parts.append(f"=== Səhifə {n} ===\n{page_text(p)}")
    out = OUT_DIR / f"{name}.txt"
    out.write_text("\n\n".join(parts), encoding="utf-8")
    print(f"{out}: {len(parts)} seyfe, {sum(len(x) for x in parts)} simvol")


if __name__ == "__main__":
    # 1.8 bolenler/bolunenler, 2.1-2.5 kesrler
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    export(start, end, f"5_sinif_s{start:03d}-{end:03d}")
