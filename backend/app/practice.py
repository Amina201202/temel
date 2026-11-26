"""Boslugu bagla: kok sebeb movzusundan 5 mesq suali.

Diaqnoz "bilmirsen" deyir, bu ise "gel indi oyrenek" deyir. Suallar eyni yoxlanmis
sablonlardan gelir (admin tesdiqleyib), her cavabdan sonra sehvin ne demek oldugu gorunur.
4/5 duz olsa movzu "baglandi" sayilir ve diagnosis["closed"]-a yazilir.
"""
import json
import random
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import store
from .db import get_db
from .models import Attempt, QuestionTemplate
from .questions import build_instance

router = APIRouter()
TOTAL = 5
PASS = 4
TTL = 2 * 3600


class StartIn(BaseModel):
    token: str
    concept: str | None = None


class PracticeAnswerIn(BaseModel):
    token: str
    value: str


def own_attempt(db, attempt_id, token):
    a = db.get(Attempt, attempt_id)
    if a is None or not secrets.compare_digest(a.token, token):
        raise HTTPException(404, "Test tapılmadı")
    if a.status != "done" or not a.diagnosis:
        raise HTTPException(409, "Əvvəlcə testi bitir")
    return a


def public(q, number, concept):
    return {"number": number, "total": TOTAL, "concept": concept, "text": q["text"], "options": q["options"]}


@router.post("/attempts/{attempt_id}/practice/start")
def practice_start(attempt_id: int, body: StartIn, db: Session = Depends(get_db)):
    a = own_attempt(db, attempt_id, body.token)
    d = a.diagnosis
    closed = d.get("closed") or []
    roots = [r for r in d.get("roots", []) if r not in closed]
    concept = body.concept if body.concept in roots else (roots[0] if roots else None)
    if concept is None:
        raise HTTPException(409, "Bağlanacaq boşluq qalmayıb 🎉")
    info = (d.get("meta") or {}).get(concept)
    if not info:
        raise HTTPException(409, "Bu mövzu üçün sual tapılmadı")
    tpls = db.scalars(select(QuestionTemplate).where(QuestionTemplate.concept_id == info["concept_id"],
                                                     QuestionTemplate.status == "approved")).all()
    if not tpls:
        raise HTTPException(409, "Bu mövzu üçün hələ məşq sualı yoxdur")

    # sablonlari novbe ile isledirik, reqemler her defe ferqli
    rng = random.Random()
    tpls = sorted(tpls, key=lambda t: (t.difficulty, rng.random()))  # asandan cetine
    questions = []
    for i in range(TOTAL * 3):
        if len(questions) == TOTAL:
            break
        inst = build_instance(tpls[i % len(tpls)].as_dict(), seed=rng.randint(0, 10**9))
        if inst is None or any(q["text"] == inst["text"] for q in questions):
            continue
        right = next(o["value"] for o in inst["options"] if o["correct"])
        questions.append({"text": inst["text"], "options": [o["value"] for o in inst["options"]], "right": right,
                          "why": {o["value"]: o["misconception"] for o in inst["options"] if not o["correct"]}})
    if len(questions) < 3:
        raise HTTPException(409, "Bu mövzu üçün kifayət qədər sual yaradılmadı")

    state = {"concept": concept, "qs": questions, "i": 0, "right": 0}
    store().setex(f"practice:{a.id}", TTL, json.dumps(state, ensure_ascii=False))
    return {"question": public(questions[0], 1, concept) | {"total": len(questions)}}


@router.post("/attempts/{attempt_id}/practice/answer")
def practice_answer(attempt_id: int, body: PracticeAnswerIn, db: Session = Depends(get_db)):
    a = own_attempt(db, attempt_id, body.token)
    raw = store().get(f"practice:{a.id}")
    if not raw:
        raise HTTPException(409, "Məşq vaxtı bitib, yenidən başla")
    st = json.loads(raw)
    q = st["qs"][st["i"]]
    if body.value not in q["options"]:
        raise HTTPException(400, "Bu cavab variantlarda yoxdur")
    correct = body.value == q["right"]
    st["right"] += int(correct)
    st["i"] += 1
    total = len(st["qs"])
    out = {"correct": correct, "correct_value": q["right"], "misconception": None if correct else q["why"].get(body.value)}

    if st["i"] < total:
        store().setex(f"practice:{a.id}", TTL, json.dumps(st, ensure_ascii=False))
        out["next"] = public(st["qs"][st["i"]], st["i"] + 1, st["concept"]) | {"total": total}
        return out

    # mesq bitdi
    store().delete(f"practice:{a.id}")
    need = PASS if total >= TOTAL else total - 1
    passed = st["right"] >= need
    if passed:
        d = dict(a.diagnosis)
        d["closed"] = sorted(set(d.get("closed") or []) | {st["concept"]})
        a.diagnosis = d  # JSON sutunu yeniden menimsedirik ki saxlansin
        db.commit()
    out["result"] = {"concept": st["concept"], "right": st["right"], "total": total, "passed": passed,
                     "closed": a.diagnosis.get("closed", [])}
    return out
