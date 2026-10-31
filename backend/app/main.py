import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .db import Base, engine, get_db
from .extract import ExtractionError, extract_graph
from .models import Chapter, Concept, ConceptEdge, QuestionTemplate
from .questions import build_checked_templates, build_instance
from .schemas import (ChapterOut, ConceptOut, EdgeOut, GraphOut, OptionOut, QuestionOut,
                      QuestionStats, StatusIn)

MAX_SIZE = 15 * 1024 * 1024  # 15 MB
logger = logging.getLogger("temel")


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

    source_text = ""
    if (file.filename or "").lower().endswith(".txt"):
        source_text = data.decode("utf-8", errors="ignore")
    chapter = Chapter(title=title, grade=grade, source_file=file.filename or "", source_text=source_text)
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


# ---------------- sual banki ----------------

def question_out(q: QuestionTemplate, with_sample=True) -> QuestionOut:
    sample = None
    if with_sample:
        try:
            sample = build_instance(q.as_dict(), seed=q.id)
        except Exception:  # noqa: BLE001
            # bir pis sablon butun siyahini cokdurmesin
            logger.exception("numune yaradilmadi, sablon id=%s", q.id)
    return QuestionOut(
        id=q.id,
        concept=q.concept.name,
        difficulty=q.difficulty,
        status=q.status,
        template_text=q.text,
        source_quote=q.source_quote,
        problems=(q.check_report or {}).get("problems", []),
        notes=(q.check_report or {}).get("notes", []),
        sample_text=sample["text"] if sample else None,
        sample_options=[OptionOut(**o) for o in sample["options"]] if sample else [],
    )


@app.post("/chapters/{chapter_id}/questions/generate", response_model=QuestionStats)
def generate_questions(chapter_id: int, db: Session = Depends(get_db)):
    graph = load_graph(db, chapter_id)
    ch = db.get(Chapter, chapter_id)

    # her movzunun evvelceden bilinmeli movzulari
    prereqs = {c.name: [] for c in graph.concepts}
    for e in graph.edges:
        prereqs[e.to_concept].append(e.from_concept)
    by_name = {c.name: c for c in graph.concepts}

    def work(concept):
        return concept, build_checked_templates(concept.name, concept.description,
                                                prereqs[concept.name], ch.source_text)

    # gemini cagirislarini paralel edirik, yoxsa 12 movzu bir nece deqiqe cekir
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(work, c) for c in graph.concepts]
        for f in futures:
            try:
                results.append(f.result())
            except ExtractionError as e:
                errors.append(str(e))

    if not results:
        raise HTTPException(502, "AI heç bir sual yarada bilmədi: " + "; ".join(errors[:3]))

    # tesdiqlenmis suallara toxunmuruq, qalanlarini yenisi ile evez edirik
    db.execute(delete(QuestionTemplate).where(
        QuestionTemplate.chapter_id == chapter_id,
        QuestionTemplate.status != "approved",
    ))

    for concept, items in results:
        for data, report, meta in items:
            db.add(QuestionTemplate(
                chapter_id=chapter_id,
                concept_id=by_name[concept.name].id,
                difficulty=meta["difficulty"],
                source_quote=meta["source_quote"],
                status="auto_ok" if report["ok"] else "needs_review",
                check_report=report,
                **data,
            ))
    db.commit()
    return question_stats(chapter_id, db)


@app.get("/chapters/{chapter_id}/questions", response_model=list[QuestionOut])
def list_questions(chapter_id: int, status: str | None = None, db: Session = Depends(get_db)):
    query = (select(QuestionTemplate)
             .where(QuestionTemplate.chapter_id == chapter_id)
             .options(selectinload(QuestionTemplate.concept))
             .order_by(QuestionTemplate.concept_id, QuestionTemplate.difficulty))
    if status:
        query = query.where(QuestionTemplate.status == status)
    return [question_out(q) for q in db.scalars(query).all()]


@app.get("/chapters/{chapter_id}/questions/stats", response_model=QuestionStats)
def question_stats(chapter_id: int, db: Session = Depends(get_db)):
    statuses = db.scalars(select(QuestionTemplate.status).where(QuestionTemplate.chapter_id == chapter_id)).all()
    return QuestionStats(
        total=len(statuses),
        auto_ok=statuses.count("auto_ok"),
        needs_review=statuses.count("needs_review"),
        approved=statuses.count("approved"),
        rejected=statuses.count("rejected"),
    )


@app.patch("/questions/{question_id}", response_model=QuestionOut)
def set_question_status(question_id: int, body: StatusIn, db: Session = Depends(get_db)):
    if body.status not in ("approved", "rejected", "needs_review"):
        raise HTTPException(400, "Status səhvdir")
    q = db.get(QuestionTemplate, question_id)
    if q is None:
        raise HTTPException(404, "Sual tapılmadı")
    if body.status == "approved" and not (q.check_report or {}).get("ok"):
        # kod yoxlamasindan kecmeyen sablon sagirde getmemelidir
        raise HTTPException(409, "Bu şablon avtomatik yoxlamadan keçməyib, əvvəlcə düzəldilməlidir")
    q.status = body.status
    db.commit()
    db.refresh(q)
    return question_out(q)


@app.post("/chapters/{chapter_id}/questions/approve-auto", response_model=QuestionStats)
def approve_auto(chapter_id: int, db: Session = Depends(get_db)):
    for q in db.scalars(select(QuestionTemplate).where(
            QuestionTemplate.chapter_id == chapter_id, QuestionTemplate.status == "auto_ok")).all():
        q.status = "approved"
    db.commit()
    return question_stats(chapter_id, db)
