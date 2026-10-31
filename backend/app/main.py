from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db import Base, engine, get_db
from .extract import ExtractionError, extract_graph
from .models import Chapter, Concept, ConceptEdge
from .schemas import ChapterOut, ConceptOut, EdgeOut, GraphOut

MAX_SIZE = 15 * 1024 * 1024  # 15 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    # cedveller yoxdursa yaradir (sonra alembic-e kececeyik)
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Təməl API", lifespan=lifespan)


def chapter_out(ch: Chapter) -> ChapterOut:
    return ChapterOut(
        id=ch.id,
        title=ch.title,
        grade=ch.grade,
        source_file=ch.source_file,
        status=ch.status,
        created_at=ch.created_at,
        concept_count=len(ch.concepts),
        edge_count=len(ch.edges),
    )


def load_graph(db: Session, chapter_id: int) -> GraphOut:
    ch = db.scalar(
        select(Chapter)
        .where(Chapter.id == chapter_id)
        .options(
            selectinload(Chapter.concepts),
            selectinload(Chapter.edges).selectinload(ConceptEdge.from_concept),
            selectinload(Chapter.edges).selectinload(ConceptEdge.to_concept),
        )
    )
    if ch is None:
        raise HTTPException(404, "Bölmə tapılmadı")
    return GraphOut(
        chapter=chapter_out(ch),
        concepts=[ConceptOut(id=c.id, name=c.name, description=c.description) for c in ch.concepts],
        edges=[
            EdgeOut(id=e.id, from_concept=e.from_concept.name, to_concept=e.to_concept.name, approved=e.approved)
            for e in ch.edges
        ],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chapters", response_model=GraphOut)
def create_chapter(
    title: str = Form(..., min_length=2, max_length=200),
    grade: int = Form(..., ge=1, le=11),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    data = file.file.read()
    if not data:
        raise HTTPException(400, "Fayl boşdur")
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "Fayl 15 MB-dan böyükdür")

    try:
        graph = extract_graph(file.filename or "file.txt", data)
    except ExtractionError as e:
        raise HTTPException(502, f"AI mövzuları çıxara bilmədi: {e}") from e

    if not graph.concepts:
        raise HTTPException(422, "Bu fayldan heç bir mövzu tapılmadı")

    chapter = Chapter(title=title, grade=grade, source_file=file.filename or "")
    db.add(chapter)
    db.flush()

    by_name = {}
    for c in graph.concepts:
        if c.name in by_name:
            continue  # tekrar ad gelse atiriq
        obj = Concept(chapter_id=chapter.id, name=c.name, description=c.description)
        db.add(obj)
        by_name[c.name] = obj
    db.flush()

    seen = set()
    for e in graph.edges:
        key = (e.prerequisite, e.concept)
        if key in seen:
            continue
        seen.add(key)
        db.add(ConceptEdge(
            chapter_id=chapter.id,
            from_concept_id=by_name[e.prerequisite].id,
            to_concept_id=by_name[e.concept].id,
        ))
    db.commit()

    return load_graph(db, chapter.id)


@app.get("/chapters", response_model=list[ChapterOut])
def list_chapters(db: Session = Depends(get_db)):
    chapters = db.scalars(
        select(Chapter)
        .options(selectinload(Chapter.concepts), selectinload(Chapter.edges))
        .order_by(Chapter.created_at.desc())
    ).all()
    return [chapter_out(ch) for ch in chapters]


@app.get("/chapters/{chapter_id}/graph", response_model=GraphOut)
def get_graph(chapter_id: int, db: Session = Depends(get_db)):
    return load_graph(db, chapter_id)
