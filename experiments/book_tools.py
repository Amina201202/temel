"""Butun dersliklerin metnini vahid formata salir: data/books_text/<kitab>.json = [{page, text}]
Isletmek: python experiments/book_tools.py
"""
import html
import json
import re
import subprocess
import unicodedata
from pathlib import Path

DATA = Path("data")
OUT = DATA / "books_text"


def clean(text):
    text = unicodedata.normalize("NFKC", text)          # ﬁ -> fi
    text = text.replace("ә", "ə").replace("Ә", "Ə")      # kiril ә -> latin ə
    text = text.replace("­", "")                     # gizli defis
    text = re.sub(r"(TAPŞIRIQ|NÜMUNƏ)\s*-->", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def from_xhtml(folder):
    pages = []
    for p in folder.rglob("page*.xhtml"):
        n = int(re.search(r"page(\d+)", p.name).group(1))
        raw = p.read_text(encoding="utf-8", errors="ignore")
        pages.append({"page": n, "text": clean(html.unescape(re.sub(r"<[^>]+>", " ", raw)))})
    return sorted(pages, key=lambda x: x["page"])


def from_pdf(path):
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    total = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    pages = []
    for n in range(1, total + 1):
        t = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(path), "-"],
                           capture_output=True, text=True).stdout
        pages.append({"page": n, "text": clean(t)})
    return pages


BOOKS = {
    "5-1": ("xhtml", DATA / "riyaziyyat-5-az-1"),
    "5-2": ("xhtml", DATA / "books" / "riyaziyyat-5-az-2"),
    "6-1": ("xhtml", DATA / "books" / "Riyaziyyat-6-az-1-ci-hisse"),
    "6-2": ("xhtml", DATA / "books" / "Riyaziyyat-6-az-2-ci-hisse"),
    "7-1": ("pdf", DATA / "7ci sinif riy 1-ci hisse.pdf"),
    "7-2": ("pdf", DATA / "7ci sinif riy 2-ci hisse.pdf"),
    "8": ("pdf", DATA / "8ci sinif riy.pdf"),
    "9": ("pdf", DATA / "9cu sinif riy.pdf"),
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (kind, path) in BOOKS.items():
        pages = from_xhtml(path) if kind == "xhtml" else from_pdf(path)
        (OUT / f"{name}.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(pages)} sehife, {sum(len(p['text']) for p in pages)} simvol")
