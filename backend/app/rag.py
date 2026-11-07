"""Dersliyi sehifelere bolub embedding edir ve movzuya uygun sehifeni tapir."""
import re

from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from .extract import get_client
from .models import EMBED_DIM, Chapter, Chunk

EMBED_MODEL = "gemini-embedding-001"
PAGE_RE = re.compile(r"=== Səhifə (\d+) ===")


def split_pages(text: str):
    # prepare_book.py "=== Səhifə N ===" yazir, onlara gore bolurux
    parts = PAGE_RE.split(text)
    if len(parts) > 1:
        pages = []
        for i in range(1, len(parts), 2):
            body = parts[i + 1].strip()
            if body:
                pages.append((int(parts[i]), body))
        return pages
    # isare yoxdursa 1500 simvolluq parcalar
    return [(None, text[i:i + 1500]) for i in range(0, len(text), 1500) if text[i:i + 1500].strip()]


def embed(texts, task):
    resp = get_client().models.embed_content(
        model=EMBED_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM, task_type=task),
    )
    return [e.values for e in resp.embeddings]


def ensure_index(db: Session, chapter: Chapter) -> int:
    """Bolmenin sehifeleri hele index olunmayibsa, edir. Index olunan sehife sayini qaytarir."""
    existing = db.scalar(select(Chunk.id).where(Chunk.chapter_id == chapter.id).limit(1))
    if existing or not chapter.source_text:
        return 0
    pages = split_pages(chapter.source_text)
    vectors = []
    for i in range(0, len(pages), 50):  # bir sorguda 50-den cox gondermirik
        vectors += embed([p[1] for p in pages[i:i + 50]], "RETRIEVAL_DOCUMENT")
    for (page, body), vec in zip(pages, vectors):
        db.add(Chunk(chapter_id=chapter.id, page=page, text=body, embedding=vec))
    db.commit()
    return len(pages)


def search(db: Session, chapter_id: int, query: str, k: int = 2):
    qvec = embed([query], "RETRIEVAL_QUERY")[0]
    rows = db.execute(
        select(Chunk.page, Chunk.text, Chunk.embedding.cosine_distance(qvec).label("dist"))
        .where(Chunk.chapter_id == chapter_id)
        .order_by("dist")
        .limit(k)
    ).all()
    return [{"page": r.page, "text": r.text, "distance": float(r.dist)} for r in rows]
