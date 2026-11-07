"""Muellim API: giris, sessiyalar, canli sinif radari."""
import random
from collections import Counter

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import (bearer, clear_fails, current_teacher, generate_password, hash_password, issue_token,
                   login_blocked, register_fail, require_admin, revoke_token, verify_password)
from .db import get_db
from .models import Attempt, AttemptAnswer, Chapter, ClassSession, Concept, Teacher

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


class TeacherIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9_.]+$")


class SessionIn(BaseModel):
    chapter_id: int
    class_name: str = Field(min_length=1, max_length=40)


# ---------- admin: muellim hesabi yaratmaq ----------

@router.post("/admin/teachers", dependencies=[Depends(require_admin)])
def create_teacher(body: TeacherIn, db: Session = Depends(get_db)):
    if db.scalar(select(Teacher).where(Teacher.username == body.username)):
        raise HTTPException(409, "Bu istifadəçi adı artıq var")
    password = generate_password()
    teacher = Teacher(name=body.name, username=body.username, password_hash=hash_password(password))
    db.add(teacher)
    db.commit()
    # sifre yalniz bir defe gosterilir, db-de yalniz hash saxlanir
    return {"id": teacher.id, "name": teacher.name, "username": teacher.username, "password": password}


@router.get("/admin/teachers", dependencies=[Depends(require_admin)])
def list_teachers(db: Session = Depends(get_db)):
    rows = db.scalars(select(Teacher).order_by(Teacher.id)).all()
    return [{"id": t.id, "name": t.name, "username": t.username} for t in rows]


# ---------- giris ----------

@router.post("/teacher/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    if login_blocked(username):
        raise HTTPException(429, "Çox səhv cəhd oldu. 15 dəqiqə sonra yenidən yoxla.")
    teacher = db.scalar(select(Teacher).where(Teacher.username == username))
    if teacher is None or not verify_password(body.password, teacher.password_hash):
        register_fail(username)
        raise HTTPException(401, "İstifadəçi adı və ya şifrə səhvdir")
    clear_fails(username)
    return {"token": issue_token(teacher.id), "name": teacher.name}


@router.post("/teacher/logout")
def logout(authorization: str | None = Header(None)):
    revoke_token(bearer(authorization))
    return {"ok": True}


@router.get("/teacher/me")
def me(teacher: Teacher = Depends(current_teacher)):
    return {"id": teacher.id, "name": teacher.name, "username": teacher.username}


# ---------- sessiyalar ----------

def own_session(db: Session, session_id: int, teacher: Teacher) -> ClassSession:
    cs = db.get(ClassSession, session_id)
    # basqa muellimin sessiyasini gormek olmaz
    if cs is None or cs.teacher_id != teacher.id:
        raise HTTPException(404, "Sessiya tapılmadı")
    return cs


def new_join_code(db: Session) -> str:
    for _ in range(50):
        code = f"{random.randint(1000, 9999)}"
        busy = db.scalar(select(ClassSession).where(ClassSession.join_code == code, ClassSession.active.is_(True)))
        if not busy:
            return code
    raise HTTPException(503, "Boş kod tapılmadı, bir az sonra yoxla")


@router.post("/teacher/sessions")
def create_session(body: SessionIn, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    chapter = db.get(Chapter, body.chapter_id)
    if chapter is None:
        raise HTTPException(404, "Bölmə tapılmadı")
    cs = ClassSession(teacher_id=teacher.id, chapter_id=chapter.id,
                      class_name=body.class_name.strip(), join_code=new_join_code(db))
    db.add(cs)
    db.commit()
    return session_summary(db, cs)


def session_summary(db: Session, cs: ClassSession):
    chapter = db.get(Chapter, cs.chapter_id)
    counts = dict(db.execute(select(Attempt.status, func.count()).where(Attempt.session_id == cs.id)
                             .group_by(Attempt.status)).all())
    return {
        "id": cs.id, "class_name": cs.class_name, "join_code": cs.join_code, "active": cs.active,
        "chapter_id": cs.chapter_id, "chapter_title": chapter.title if chapter else "",
        "created_at": cs.created_at, "joined": sum(counts.values()), "done": counts.get("done", 0),
    }


@router.get("/teacher/sessions")
def list_sessions(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    rows = db.scalars(select(ClassSession).where(ClassSession.teacher_id == teacher.id)
                      .order_by(ClassSession.created_at.desc(), ClassSession.id.desc())).all()
    return [session_summary(db, cs) for cs in rows]


@router.post("/teacher/sessions/{session_id}/close")
def close_session(session_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cs = own_session(db, session_id, teacher)
    cs.active = False
    db.commit()
    return session_summary(db, cs)


# ---------- canli radar ----------

@router.get("/teacher/sessions/{session_id}/radar")
def radar(session_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cs = own_session(db, session_id, teacher)
    attempts = db.scalars(select(Attempt).where(Attempt.session_id == cs.id).order_by(Attempt.started_at)).all()
    done = [a for a in attempts if a.status == "done" and a.diagnosis]
    # bolmenin movzulari + diaqnozda gorunen evvelki sinif movzulari
    concepts = list(db.scalars(select(Concept.name).where(Concept.chapter_id == cs.chapter_id).order_by(Concept.id)).all())
    for a in done:
        for name in a.diagnosis["concept_map"]:
            if name not in concepts:
                concepts.append(name)

    answered = dict(db.execute(
        select(AttemptAnswer.attempt_id, func.count()).join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
        .where(Attempt.session_id == cs.id).group_by(AttemptAnswer.attempt_id)).all())

    # her movzu ucun nece sagirdde kok sebeb / zeif / bilir
    concept_stats = []
    for c in concepts:
        counts = Counter(a.diagnosis["concept_map"].get(c, "unknown") for a in done)
        concept_stats.append({"concept": c, "root": counts["root"], "weak": counts["weak"],
                              "known": counts["known"], "unknown": counts["unknown"]})

    roots = Counter(r for a in done for r in a.diagnosis["roots"]).most_common()
    no_gap = sum(1 for a in done if not a.diagnosis["roots"])

    mistakes = db.execute(
        select(AttemptAnswer.concept, AttemptAnswer.misconception, func.count().label("n"))
        .join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
        .where(Attempt.session_id == cs.id, AttemptAnswer.correct.is_(False), AttemptAnswer.misconception.isnot(None))
        .group_by(AttemptAnswer.concept, AttemptAnswer.misconception)
        .order_by(func.count().desc()).limit(5)).all()

    if roots:
        top, n = roots[0]
        advice = (f"{len(done)} şagirddən {n}-nin kök boşluğu «{top}» mövzusundadır. "
                  f"Növbəti dərsi 10 dəqiqəlik «{top}» təkrarı ilə başlamaq tövsiyə olunur.")
    elif done:
        advice = "Bitirən şagirdlərdə ortaq ciddi boşluq tapılmadı."
    else:
        advice = "Şagirdlər testi bitirdikcə tövsiyə burada görünəcək."

    return {
        "session": session_summary(db, cs),
        "students": [{
            "attempt_id": a.id, "nickname": a.nickname, "status": a.status,
            "answered": answered.get(a.id, 0),
            "correct": a.diagnosis["correct"] if a.diagnosis else None,
            "roots": a.diagnosis["roots"] if a.diagnosis else [],
        } for a in attempts],
        "concepts": concept_stats,
        "top_roots": [{"concept": c, "count": n} for c, n in roots],
        "no_gap": no_gap,
        "mistakes": [{"concept": m[0], "misconception": m[1], "count": m[2]} for m in mistakes],
        "advice": advice,
    }


@router.get("/teacher/sessions/{session_id}/students/{attempt_id}")
def student_detail(session_id: int, attempt_id: int, teacher: Teacher = Depends(current_teacher),
                   db: Session = Depends(get_db)):
    cs = own_session(db, session_id, teacher)
    a = db.get(Attempt, attempt_id)
    if a is None or a.session_id != cs.id:
        raise HTTPException(404, "Şagird tapılmadı")
    answers = db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == a.id)
                         .order_by(AttemptAnswer.id)).all()
    return {
        "nickname": a.nickname, "status": a.status, "diagnosis": a.diagnosis,
        "answers": [{"concept": x.concept, "question": x.question_text, "chosen": x.chosen,
                     "correct_value": x.correct_value, "correct": x.correct, "misconception": x.misconception}
                    for x in answers],
    }
