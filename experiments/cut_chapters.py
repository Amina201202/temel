"""Dersliklerden lazim olan bolmeleri kesir: data/chapters/
PDF-ler PDF kimi qalir (Gemini ozu oxuyacaq), xhtml kitablar .txt olur.
"""
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

DATA = Path("data")
OUT = DATA / "chapters"

CHAPTERS = [
    # (fayl adi, menbe, ilk sehife, son sehife)
    ("6_tam_ededler_s073-104", "6-1", 73, 104),
    ("7_birhedli_coxhedli_s059-082", "7ci sinif riy 1-ci hisse.pdf", 59, 82),
    ("7_muxteser_vurma_s083-105", "7ci sinif riy 1-ci hisse.pdf", 83, 105),
    ("8_kvadrat_kok_s008-035", "8ci sinif riy.pdf", 8, 35),
    ("8_kvadrat_tenlik_s048-072", "8ci sinif riy.pdf", 48, 72),
    ("9_kvadrat_funksiya_s053-078", "9cu sinif riy.pdf", 53, 78),
    # 9-cu sinif 1-ci ve 2-ci bolme (kitabda sehife = pdf sehife - 2)
    ("9_n_ci_derece_kok_s008-029", "9cu sinif riy.pdf", 8, 29),
    ("9_cevre_s030-052", "9cu sinif riy.pdf", 30, 52),
]

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, src, first, last in CHAPTERS:
        if src.endswith(".pdf"):
            reader = PdfReader(DATA / src)
            writer = PdfWriter()
            for i in range(first - 1, last):
                writer.add_page(reader.pages[i])
            path = OUT / f"{name}.pdf"
            with open(path, "wb") as f:
                writer.write(f)
        else:
            pages = json.load(open(DATA / "books_text" / f"{src}.json", encoding="utf-8"))
            text = "\n\n".join(f"=== Səhifə {p['page']} ===\n{p['text']}" for p in pages if first <= p["page"] <= last)
            path = OUT / f"{name}.txt"
            path.write_text(text, encoding="utf-8")
        print(f"{path.name}: {path.stat().st_size // 1024} KB")
