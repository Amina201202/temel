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
from .link import collect_graph, suggest_links
from .guard import EMAIL, PHONE, GuardBlock, answer_question, check_input
from .auth import require_admin, store
from .extract import ExtractionError, extract_graph, transcribe_pdf
from .models import Attempt, AttemptAnswer, Chapter, ClassSession, Concept, ConceptEdge, QuestionTemplate
from .questions import build_checked_templates, build_instance
from .careless import careless_score
from .teacher import router as teacher_router
from .notify import router as notify_router, set_webhook
from .tts import explanation_text, synthesize
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
    set_webhook()
    yield
    if pool:
        pool.close()


app = FastAPI(title="Təməl API", lifespan=lifespan)


# Gemini xetasi olanda 500 yox, aydin mesaj qaytaririq
from fastapi import Request
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors


@app.exception_handler(genai_errors.APIError)
def gemini_error(request: Request, exc: genai_errors.APIError):
    logging.warning("Gemini xetasi: %s %s", exc.code, exc.message)
    billing = "billing" in (exc.message or "").lower()
    if exc.code == 402 or (exc.code == 403 and billing):
        msg = "AI xidmətinin balansında problem var (ödəniş). Bir az sonra yenidən yoxla."
        logging.error("GEMINI BALANSI: AI Studio-da odenis lazimdir - %s", exc.message)
    elif exc.code == 429:
        msg = "Gemini limitinə çatdıq. 1 dəqiqə gözlə və yenidən yoxla."
    else:
        msg = f"AI xidməti cavab vermədi ({exc.code}). Bir az sonra yenidən yoxla."
    return JSONResponse(status_code=503, content={"detail": msg})
app.include_router(teacher_router)
app.include_router(notify_router)


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
            EdgeOut(id=e.id, from_concept=e.from_concept.name, to_concept=e.to_concept.name, approved=e.approved,
                    cross=e.from_concept.chapter_id != ch.id,
                    from_grade=db.get(Chapter, e.from_concept.chapter_id).grade
                    if e.from_concept.chapter_id != ch.id else None)
            for e in ch.edges
        ],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chapters", response_model=GraphOut, dependencies=[Depends(require_admin)])
def create_chapter(
    title: str = Form(..., min_length=2, max_length=200),
    grade: int = Form(..., ge=1, le=11),
    first_page: int = Form(1, ge=1, le=500),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    data = file.file.read()
    if not data:
        raise HTTPException(400, "Fayl boşdur")
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "Fayl 15 MB-dan böyükdür")

    filename = file.filename or "file.txt"
    try:
        if filename.lower().endswith(".pdf"):
            # PDF -> metn (OCR), sonra metnden movzular: RAG ve suallar ucun metn lazimdir
            text = transcribe_pdf(data, first_page)
            filename, data = filename[:-4] + ".txt", text.encode("utf-8")
        graph = extract_graph(filename, data)
    except ExtractionError as e:
        raise HTTPException(502, f"AI mövzuları çıxara bilmədi: {e}") from e

    if not graph.concepts:
        raise HTTPException(422, "Bu fayldan heç bir mövzu tapılmadı")

    source_text = ""
    if filename.lower().endswith(".txt"):
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


@app.get("/chapters", response_model=list[ChapterOut], dependencies=[Depends(require_admin)])
def list_chapters(db: Session = Depends(get_db)):
    chapters = db.scalars(
        select(Chapter)
        .options(selectinload(Chapter.concepts), selectinload(Chapter.edges))
        .order_by(Chapter.created_at.desc())
    ).all()
    return [chapter_out(ch) for ch in chapters]


@app.get("/chapters/{chapter_id}/graph", response_model=GraphOut, dependencies=[Depends(require_admin)])
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


@app.post("/chapters/{chapter_id}/questions/generate", response_model=QuestionStats, dependencies=[Depends(require_admin)])
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
                                                prereqs[concept.name], ch.source_text, ch.grade)

    # gemini cagirislarini paralel edirik, yoxsa 12 movzu bir nece deqiqe cekir
    results, errors = [], []
    # 4 isci 12 movzuda 5 deqiqeden cox cekirdi, 8 ile 2 defe tez olur
    with ThreadPoolExecutor(max_workers=8) as pool:
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


@app.get("/chapters/{chapter_id}/questions", response_model=list[QuestionOut], dependencies=[Depends(require_admin)])
def list_questions(chapter_id: int, status: str | None = None, db: Session = Depends(get_db)):
    query = (select(QuestionTemplate)
             .where(QuestionTemplate.chapter_id == chapter_id)
             .options(selectinload(QuestionTemplate.concept))
             .order_by(QuestionTemplate.concept_id, QuestionTemplate.difficulty))
    if status:
        query = query.where(QuestionTemplate.status == status)
    return [question_out(q) for q in db.scalars(query).all()]


@app.get("/chapters/{chapter_id}/questions/stats", response_model=QuestionStats, dependencies=[Depends(require_admin)])
def question_stats(chapter_id: int, db: Session = Depends(get_db)):
    statuses = db.scalars(select(QuestionTemplate.status).where(QuestionTemplate.chapter_id == chapter_id)).all()
    return QuestionStats(
        total=len(statuses),
        auto_ok=statuses.count("auto_ok"),
        needs_review=statuses.count("needs_review"),
        approved=statuses.count("approved"),
        rejected=statuses.count("rejected"),
    )


@app.patch("/questions/{question_id}", response_model=QuestionOut, dependencies=[Depends(require_admin)])
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


@app.post("/chapters/{chapter_id}/questions/approve-auto", response_model=QuestionStats, dependencies=[Depends(require_admin)])
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
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(404, "Bölmə tapılmadı")
    # bu bolme + elaqeli evvelki sinif movzulari bir qrafda
    concepts, edges, display, grades = collect_graph(db, chapter)
    prereqs = {display[cid]: [] for cid in concepts}
    for e in edges.values():
        if e.to_concept_id in display and e.from_concept_id in display:
            prereqs[display[e.to_concept_id]].append(display[e.from_concept_id])

    templates = {}
    rows = db.scalars(select(QuestionTemplate)
                      .where(QuestionTemplate.concept_id.in_(list(concepts)), QuestionTemplate.status == "approved")).all()
    for q in rows:
        templates.setdefault(display[q.concept_id], []).append(
            {"id": q.id, "difficulty": q.difficulty, "data": q.as_dict()})
    if not any(concepts[cid].chapter_id == chapter.id for cid in concepts if display[cid] in templates):
        raise HTTPException(409, "Bu bölmədə hələ təsdiqlənmiş sual yoxdur")

    # izah ve RAG ucun: her movzu hansi bolmeden/sinifden gelir
    meta = {display[cid]: {"concept_id": cid, "chapter_id": c.chapter_id, "name": c.name,
                           "grade": grades[c.chapter_id]} for cid, c in concepts.items()}
    order = sorted(concepts, key=lambda cid: (concepts[cid].chapter_id != chapter.id, -grades[concepts[cid].chapter_id], cid))
    return {
        "concepts": [display[cid] for cid in order],
        "prereqs": prereqs,
        "templates": templates,
        "meta": meta,
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
            attempt.finished_at = datetime.now(timezone.utc)
            d = dict(values.get("diagnosis") or {})
            try:
                # ML: test tesadufi basilibmi? (careless.py)
                d["careless"] = careless_score(db, attempt)
            except Exception as e:  # noqa: BLE001
                logger.warning("careless model xetasi: %s", e)
            attempt.diagnosis = d
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


@app.post("/chapters/{chapter_id}/link", dependencies=[Depends(require_admin)])
def link_chapter(chapter_id: int, db: Session = Depends(get_db)):
    ch = db.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(404, "Bölmə tapılmadı")
    created = suggest_links(db, ch)
    return {"created": [{"id": e.id, "from": e.from_concept_id, "to": e.to_concept_id, "reason": r} for e, r in created]}


@app.delete("/edges/{edge_id}", dependencies=[Depends(require_admin)])
def delete_edge(edge_id: int, db: Session = Depends(get_db)):
    # admin AI-in sehv elaqesini silir (HITL)
    e = db.get(ConceptEdge, edge_id)
    if e is None:
        raise HTTPException(404, "Əlaqə tapılmadı")
    db.delete(e)
    db.commit()
    return {"ok": True}


@app.post("/chapters/{chapter_id}/index", dependencies=[Depends(require_admin)])
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
    info = (d.get("meta") or {}).get(root)
    chapter = db.get(Chapter, info["chapter_id"] if info else attempt.chapter_id)
    concept = db.get(Concept, info["concept_id"]) if info else db.scalar(
        select(Concept).where(Concept.chapter_id == chapter.id, Concept.name == root))
    try:
        ensure_index(db, chapter)
        pages = search(db, chapter.id, f"{concept.name if concept else root}. {concept.description if concept else ''}", k=2)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("RAG axtarisi alinmadi")
        pages = []

    wrong = db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id,
                                                   AttemptAnswer.correct.is_(False))).all()
    wrong_answers = [{"concept": w.concept, "question": w.question_text, "chosen": w.chosen,
                      "correct_value": w.correct_value, "misconception": w.misconception} for w in wrong]
    try:
        exp = generate_explanation(root, d["weak_because"], wrong_answers, pages, chapter.grade)
    except genai_errors.APIError:
        raise  # handler aydin mesaj qaytarir
    except Exception as e:  # noqa: BLE001
        logger.exception("izah alinmadi")
        raise HTTPException(502, "AI izahı hazırlaya bilmədi, bir az sonra yenidən cəhd et") from e

    exp["source_grade"] = chapter.grade  # kok basqa sinifdendirse, o kitabin sinfi
    exp["source_text"] = next((p["text"][:400] for p in pages if p["page"] == exp["source_page"]), None)
    attempt.diagnosis = {**d, "explanation": exp}  # JSON sutunu yeniden menimsedirik ki, saxlansin
    db.commit()
    return {"explanation": exp}


class AskIn(BaseModel):
    token: str
    question: str


ASK_LIMIT = 5


TTS_DIR = Path(os.getenv("TTS_CACHE_DIR", "/tmp/temel_tts"))


@app.post("/attempts/{attempt_id}/explanation/audio")
def explanation_audio(attempt_id: int, body: TokenIn, db: Session = Depends(get_db)):
    """Izahi sesle oxuyur. Her test ucun bir defe yaradilir, sonra diskden verilir."""
    attempt = get_attempt(db, attempt_id, body.token)
    exp = (attempt.diagnosis or {}).get("explanation")
    if not exp:
        raise HTTPException(409, "Əvvəlcə izah hazırlanmalıdır")
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TTS_DIR / f"{attempt.id}.wav"
    if not path.exists():
        try:
            path.write_bytes(synthesize(explanation_text(exp)))
        except genai_errors.APIError:
            raise  # yuxaridaki handler aydin mesaj qaytarir
        except Exception as e:  # noqa: BLE001
            logger.exception("ses yaradilmadi")
            raise HTTPException(502, "Səsli izah hazırlana bilmədi, bir az sonra yenidən cəhd et") from e
    return Response(path.read_bytes(), media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/attempts/{attempt_id}/ask")
def ask_question(attempt_id: int, body: AskIn, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id, body.token)
    return answer_for_attempt(db, attempt, body.question)


def answer_for_attempt(db, attempt, question_text):
    """"Sualın var?" - hem tetbiqden, hem de Telegram botundan (notify.py) cagirilir."""
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
    info = (d.get("meta") or {}).get(concept)
    src_chapter_id = info["chapter_id"] if info else attempt.chapter_id
    try:
        question = check_input(question_text, concept)
        store().setex(key, 24 * 3600, used + 1)
        # movzunun oz sehifesi + suala en uygun sehifeler (tekrarsiz)
        plain = info["name"] if info else concept
        pages = search(db, src_chapter_id, plain, k=1)
        for extra in search(db, src_chapter_id, f"{plain}. {question}", k=3):
            if extra["page"] not in {x["page"] for x in pages} and len(pages) < 3:
                pages.append(extra)
        ans = answer_question(question, concept, pages, db.get(Chapter, src_chapter_id).grade)
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


@app.get("/public/sessions/{code}")
def public_session(code: str, db: Session = Depends(get_db)):
    """Sagird kodu yazanda hansi sinfe qosuldugunu gorsun."""
    cs = db.scalar(select(ClassSession).where(ClassSession.join_code == code.strip(), ClassSession.active.is_(True)))
    if cs is None:
        raise HTTPException(404, "Bu kodla aktiv sessiya tapılmadı")
    ch = db.get(Chapter, cs.chapter_id)
    return {"class_name": cs.class_name, "chapter_title": ch.title if ch else "", "grade": ch.grade if ch else None}


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
