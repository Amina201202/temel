import logging
import os
import random
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from pathlib import Path

from pydantic import BaseModel
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, selectinload

from langgraph.types import Command

from .db import Base, engine, get_db
from .diagnosis import MAX_QUESTIONS, build_graph
from .explain import generate_explanation
from .rag import ensure_index, search
from .guard import EMAIL, PHONE, GuardBlock, answer_question, check_input
from .auth import store
from .extract import ExtractionError, extract_graph
from .models import Attempt, AttemptAnswer, Chapter, ClassSession, Concept, ConceptEdge, QuestionTemplate
from .questions import build_checked_templates, build_instance
from .teacher import router as teacher_router
from .schemas import (AnswerIn, AttemptIn, AttemptStep, ChapterOut, ConceptOut, EdgeOut, Feedback, GraphOut,
                      OptionOut, PublicQuestion, QuestionOut, QuestionStats, StatusIn)

MAX_SIZE = 15 * 1024 * 1024  # 15 MB
logger = logging.getLogger("temel")


GRAPH = None


def make_checkpointer():
    # testlerde yaddasda, docker-de postgres-de saxlayiriq
    if os.getenv("CHECKPOINTER", "postgres") == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver(), None
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
    pool = ConnectionPool(url, max_size=10, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()
    return saver, pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    global GRAPH
    # pgvector extension cedvellerden evvel lazimdir
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # cedveller yoxdursa yaradir (sonra alembic-e kececeyik)
    Base.metadata.create_all(engine)
    saver, pool = make_checkpointer()
    GRAPH = build_graph(saver)
    yield
    if pool:
        pool.close()


app = FastAPI(title="Təməl API", lifespan=lifespan)
app.include_router(teacher_router)


@app.middleware("http")
async def no_stale_static(request, call_next):
    # brauzer kohne app.js-i kesden gostermesin: her defe serverden yoxlasin (304 ile ucuzdur)
    response = await call_next(request)
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache"
    return response


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

    # RAG ucun sehifeleri index edirik; alinmasa izah zamani yeniden cehd olunacaq
    try:
        ensure_index(db, chapter)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("index alinmadi, chapter=%s", chapter.id)

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


# ---------------- sagird: diaqnostik test ----------------

NICK_RE = re.compile(r"^[\w .-]{2,20}$")


def thread_config(attempt_id):
    return {"configurable": {"thread_id": f"attempt-{attempt_id}"}}


def initial_state(db: Session, chapter_id: int):
    graph = load_graph(db, chapter_id)
    prereqs = {c.name: [] for c in graph.concepts}
    for e in graph.edges:
        prereqs[e.to_concept].append(e.from_concept)

    templates = {}
    rows = db.scalars(select(QuestionTemplate)
                      .where(QuestionTemplate.chapter_id == chapter_id, QuestionTemplate.status == "approved")
                      .options(selectinload(QuestionTemplate.concept))).all()
    for q in rows:
        templates.setdefault(q.concept.name, []).append(
            {"id": q.id, "difficulty": q.difficulty, "data": q.as_dict()})
    if not templates:
        raise HTTPException(409, "Bu bölmədə hələ təsdiqlənmiş sual yoxdur")

    return {
        "concepts": [c.name for c in graph.concepts],
        "prereqs": prereqs,
        "templates": templates,
        "seed": random.randint(0, 10**9),
    }


def public_question(values):
    q = values.get("current")
    if not q:
        return None
    return PublicQuestion(number=len(values.get("asked", [])) + 1, max=MAX_QUESTIONS, concept=q["concept"],
                          text=q["text"], options=[o["value"] for o in q["options"]])


def finish_or_ask(attempt: Attempt, db: Session, feedback=None) -> AttemptStep:
    values = GRAPH.get_state(thread_config(attempt.id)).values
    if values.get("done"):
        if attempt.status != "done":
            attempt.status = "done"
            attempt.diagnosis = values.get("diagnosis")
            attempt.finished_at = datetime.now(timezone.utc)
            db.commit()
        return AttemptStep(attempt_id=attempt.id, token=attempt.token, done=True,
                           feedback=feedback, diagnosis=attempt.diagnosis)
    return AttemptStep(attempt_id=attempt.id, token=attempt.token, done=False,
                       question=public_question(values), feedback=feedback)


def get_attempt(db: Session, attempt_id: int, token: str) -> Attempt:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or not secrets.compare_digest(attempt.token, token or ""):
        raise HTTPException(404, "Test tapılmadı")
    return attempt


@app.post("/attempts", response_model=AttemptStep)
def start_attempt(body: AttemptIn, db: Session = Depends(get_db)):
    nickname = body.nickname.strip()
    if not NICK_RE.match(nickname):
        raise HTTPException(400, "Ləqəb 2-20 simvol olmalıdır (hərf, rəqəm, boşluq, _ . -)")
    if PHONE.search(nickname) or EMAIL.search(nickname) or sum(ch.isdigit() for ch in nickname) >= 7:
        raise HTTPException(400, "Ləqəbdə telefon nömrəsi kimi şəxsi məlumat yazma")

    session_id = None
    chapter_id = body.chapter_id
    if body.join_code:
        cs = db.scalar(select(ClassSession).where(ClassSession.join_code == body.join_code.strip(),
                                                  ClassSession.active.is_(True)))
        if cs is None:
            raise HTTPException(404, "Bu kodla aktiv sessiya tapılmadı")
        session_id, chapter_id = cs.id, cs.chapter_id
    if chapter_id is None:
        raise HTTPException(400, "Bölmə və ya sessiya kodu lazımdır")

    state = initial_state(db, chapter_id)
    attempt = Attempt(token=secrets.token_urlsafe(24), chapter_id=chapter_id,
                      session_id=session_id, nickname=nickname)
    db.add(attempt)
    db.commit()

    GRAPH.invoke(state, thread_config(attempt.id))
    return finish_or_ask(attempt, db)


@app.post("/attempts/{attempt_id}/answer", response_model=AttemptStep)
def answer_attempt(attempt_id: int, body: AnswerIn, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id, body.token)
    if attempt.status == "done":
        return finish_or_ask(attempt, db)

    config = thread_config(attempt.id)
    current = GRAPH.get_state(config).values.get("current")
    if not current:
        raise HTTPException(409, "Hazırda cavab gözlənilən sual yoxdur")
    if body.value not in [o["value"] for o in current["options"]]:
        raise HTTPException(400, "Bu cavab variantlarda yoxdur")

    GRAPH.invoke(Command(resume=body.value), config)

    last = GRAPH.get_state(config).values["asked"][-1]
    db.add(AttemptAnswer(
        attempt_id=attempt.id, template_id=last["template_id"], concept=last["concept"],
        question_text=last["text"], chosen=last["chosen"], correct_value=last["correct_value"],
        correct=last["correct"], misconception=last["misconception"], points_to=last["points_to"],
    ))
    db.commit()

    feedback = Feedback(correct=last["correct"], correct_value=last["correct_value"],
                        misconception=None if last["correct"] else last["misconception"])
    return finish_or_ask(attempt, db, feedback)


@app.post("/chapters/{chapter_id}/index")
def index_chapter(chapter_id: int, db: Session = Depends(get_db)):
    ch = db.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(404, "Bölmə tapılmadı")
    return {"indexed_pages": ensure_index(db, ch)}


class TokenIn(BaseModel):
    token: str


@app.post("/attempts/{attempt_id}/explanation")
def attempt_explanation(attempt_id: int, body: TokenIn, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id, body.token)
    d = attempt.diagnosis
    if attempt.status != "done" or not d:
        raise HTTPException(409, "Test hələ bitməyib")
    if not d["roots"]:
        return {"explanation": None}
    if d.get("explanation"):
        return {"explanation": d["explanation"]}  # bir defe yaradiriq, sonra cache

    root = d["roots"][0]
    chapter = db.get(Chapter, attempt.chapter_id)
    concept = db.scalar(select(Concept).where(Concept.chapter_id == chapter.id, Concept.name == root))
    try:
        ensure_index(db, chapter)
        pages = search(db, chapter.id, f"{root}. {concept.description if concept else ''}", k=2)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("RAG axtarisi alinmadi")
        pages = []

    wrong = db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id,
                                                   AttemptAnswer.correct.is_(False))).all()
    wrong_answers = [{"concept": w.concept, "question": w.question_text, "chosen": w.chosen,
                      "correct_value": w.correct_value, "misconception": w.misconception} for w in wrong]
    try:
        exp = generate_explanation(root, d["weak_because"], wrong_answers, pages)
    except Exception as e:  # noqa: BLE001
        logger.exception("izah alinmadi")
        raise HTTPException(502, "AI izahı hazırlaya bilmədi, bir az sonra yenidən cəhd et") from e

    exp["source_text"] = next((p["text"][:400] for p in pages if p["page"] == exp["source_page"]), None)
    attempt.diagnosis = {**d, "explanation": exp}  # JSON sutunu yeniden menimsedirik ki, saxlansin
    db.commit()
    return {"explanation": exp}


class AskIn(BaseModel):
    token: str
    question: str


ASK_LIMIT = 5


@app.post("/attempts/{attempt_id}/ask")
def ask_question(attempt_id: int, body: AskIn, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id, body.token)
    d = attempt.diagnosis
    if attempt.status != "done" or not d or not d["roots"]:
        raise HTTPException(409, "Sual vermək üçün əvvəlcə testi bitir")

    # bir test ucun en cox 5 sual (xerc limiti)
    key = f"ask:{attempt.id}"
    used = int(store().get(key) or 0)
    if used >= ASK_LIMIT:
        raise HTTPException(429, f"Bu test üçün {ASK_LIMIT} sual limiti doldu. Qalanını müəllimindən soruş.")

    # bloklanan cehdler de AI cagirisi edir - onlari da limitleyirik (spam olmasin)
    tries = store().incr(f"ask_try:{attempt.id}")
    if tries == 1:
        store().expire(f"ask_try:{attempt.id}", 24 * 3600)
    if tries > ASK_LIMIT * 3:
        raise HTTPException(429, "Çox cəhd oldu. Sabah yenidən yoxla.")

    concept = d["roots"][0]
    try:
        question = check_input(body.question, concept)
        store().setex(key, 24 * 3600, used + 1)
        # movzunun oz sehifesi + suala en uygun sehifeler (tekrarsiz)
        pages = search(db, attempt.chapter_id, concept, k=1)
        for extra in search(db, attempt.chapter_id, f"{concept}. {question}", k=3):
            if extra["page"] not in {x["page"] for x in pages} and len(pages) < 3:
                pages.append(extra)
        ans = answer_question(question, concept, pages)
    except GuardBlock as g:
        store().incr(f"guard:{g.rail}")  # neçə defe hansi qoruma isledi - statistikaya
        logger.info("guard block rail=%s attempt=%s", g.rail, attempt.id)
        raise HTTPException(400, g.message) from g
    store().incr("guard:passed")
    return {"answer": ans["answer"], "source_page": ans["source_page"], "left": ASK_LIMIT - used - 1}


@app.get("/attempts/{attempt_id}", response_model=AttemptStep)
def get_attempt_state(attempt_id: int, token: str, db: Session = Depends(get_db)):
    # sehife yenilenende sagird qaldigi yerden davam edir
    return finish_or_ask(get_attempt(db, attempt_id, token), db)


@app.get("/public/chapters")
def public_chapters(db: Session = Depends(get_db)):
    # sagird yalniz tesdiqlenmis suali olan bolmeleri gorur
    rows = db.execute(
        select(Chapter.id, Chapter.title, Chapter.grade, func.count(QuestionTemplate.id))
        .join(QuestionTemplate, QuestionTemplate.chapter_id == Chapter.id)
        .where(QuestionTemplate.status == "approved")
        .group_by(Chapter.id)
        .order_by(Chapter.grade, Chapter.title)
    ).all()
    return [{"id": r[0], "title": r[1], "grade": r[2], "questions": r[3]} for r in rows]


@app.get("/qr.svg", include_in_schema=False)
def qr_svg(text: str):
    # QR-i ozumuz yaradiriq: mekteb wi-fi-si CDN-i bloklasa da isleyir
    if len(text) > 300:
        raise HTTPException(400, "Mətn çox uzundur")
    import io

    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# sagird tetbiqi: html/css/js, eyni serverden (CORS lazim olmur)
app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="student")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")
