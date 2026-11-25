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


def is_careless(a):
    return bool(a.diagnosis) and (a.diagnosis.get("careless") or 0) >= 0.5


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
    sessions = dict(db.execute(select(ClassSession.teacher_id, func.count()).group_by(ClassSession.teacher_id)).all())
    return [{"id": t.id, "name": t.name, "username": t.username, "sessions": sessions.get(t.id, 0),
             "created_at": t.created_at.strftime("%Y-%m-%d") if t.created_at else ""} for t in rows]


@router.post("/admin/teachers/{teacher_id}/reset-password", dependencies=[Depends(require_admin)])
def reset_password(teacher_id: int, db: Session = Depends(get_db)):
    """Muellim sifreni unudanda: yeni sifre yaradilir ve bir defe gosterilir."""
    t = db.get(Teacher, teacher_id)
    if t is None:
        raise HTTPException(404, "Müəllim tapılmadı")
    password = generate_password()
    t.password_hash = hash_password(password)
    db.commit()
    clear_fails(t.username)  # sehv cehdlere gore bloklanibsa, aciriq
    return {"id": t.id, "name": t.name, "username": t.username, "password": password}


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
    done_all = [a for a in attempts if a.status == "done" and a.diagnosis]
    # ML tesadufi basilmis sayirsa, statistikaya qatmiriq (sehv "kok sebeb" yaratmasin)
    done = [a for a in done_all if not is_careless(a)]
    skipped = len(done_all) - len(done)
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
    def status_of(a, c):
        st = a.diagnosis["concept_map"].get(c, "unknown")
        # yoxlanmayib, cetin suala duz cavabdan netice cixarilib
        if st == "known" and c in (a.diagnosis.get("implied") or []):
            return "implied"
        return st

    for c in concepts:
        counts = Counter(status_of(a, c) for a in done)
        concept_stats.append({"concept": c, "root": counts["root"], "weak": counts["weak"],
                              "known": counts["known"], "implied": counts["implied"],
                              "unknown": counts["unknown"]})

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
    if skipped:
        advice += f" ({skipped} test təsadüfi basıldığı üçün statistikaya daxil edilmədi.)"
    else:
        advice = "Şagirdlər testi bitirdikcə tövsiyə burada görünəcək."

    return {
        "session": session_summary(db, cs),
        "students": [{
            "attempt_id": a.id, "nickname": a.nickname, "status": a.status,
            "answered": answered.get(a.id, 0),
            "correct": a.diagnosis["correct"] if a.diagnosis else None,
            "roots": a.diagnosis["roots"] if a.diagnosis else [],
            "careless": is_careless(a),
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


# ---------- umumi baxis: muellimin butun sessiyalari birlikde ----------

def teacher_attempts(db: Session, teacher: Teacher):
    """Muellimin butun sessiyalari ve onlardaki testler."""
    sessions = db.scalars(select(ClassSession).where(ClassSession.teacher_id == teacher.id)
                          .order_by(ClassSession.created_at)).all()
    by_id = {s.id: s for s in sessions}
    attempts = db.scalars(select(Attempt).where(Attempt.session_id.in_(list(by_id) or [-1]))
                          .order_by(Attempt.started_at)).all() if by_id else []
    return sessions, by_id, attempts


@router.get("/teacher/overview")
def overview(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    sessions, by_id, attempts = teacher_attempts(db, teacher)
    done = [a for a in attempts if a.status == "done" and a.diagnosis]
    titles = {c.id: c.title for c in db.scalars(select(Chapter)).all()}

    # en cox rast gelinen kok sebebler: hansi siniflerde
    root_count, root_classes = Counter(), {}
    for a in done:
        for r in a.diagnosis.get("roots", []):
            root_count[r] += 1
            root_classes.setdefault(r, set()).add(by_id[a.session_id].class_name)
    top_roots = [{"concept": r, "count": n, "classes": sorted(root_classes[r])}
                 for r, n in root_count.most_common(8)]

    # sinifler uzre muqayise
    classes = {}
    for s in sessions:
        c = classes.setdefault(s.class_name, {"class_name": s.class_name, "sessions": 0, "students": 0,
                                              "done": 0, "answered": 0, "correct": 0, "no_gap": 0,
                                              "roots": Counter(), "chapters": set()})
        c["sessions"] += 1
        c["chapters"].add(titles.get(s.chapter_id, ""))
    for a in attempts:
        c = classes[by_id[a.session_id].class_name]
        c["students"] += 1
        if a in done:
            d = a.diagnosis
            c["done"] += 1
            c["answered"] += d.get("answered", 0)
            c["correct"] += d.get("correct", 0)
            c["roots"].update(d.get("roots", []))
            if not d.get("roots"):
                c["no_gap"] += 1
    class_rows = []
    for c in classes.values():
        top = c["roots"].most_common(1)
        class_rows.append({
            "class_name": c["class_name"], "sessions": c["sessions"], "students": c["students"],
            "done": c["done"], "no_gap": c["no_gap"],
            "accuracy": round(100 * c["correct"] / c["answered"]) if c["answered"] else None,
            "top_root": top[0][0] if top else None, "top_root_count": top[0][1] if top else 0,
            "chapters": sorted(x for x in c["chapters"] if x),
        })
    class_rows.sort(key=lambda r: -r["students"])

    return {
        "sessions": len(sessions), "students": len(attempts), "done": len(done),
        "no_gap": sum(1 for a in done if not a.diagnosis.get("roots")),
        "top_roots": top_roots, "classes": class_rows,
    }


@router.get("/teacher/export.csv")
def export_csv(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Butun neticeler Excel-de acilan CSV kimi."""
    import csv
    import io
    from fastapi.responses import Response

    sessions, by_id, attempts = teacher_attempts(db, teacher)
    titles = {c.id: c.title for c in db.scalars(select(Chapter)).all()}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")  # az/ru Excel noqteli vergulu gozleyir
    w.writerow(["Sinif", "Mövzu", "Kod", "Şagird", "Status", "Sual", "Düz", "Faiz",
                "Kök səbəb", "Başladı", "Müddət (dəq)"])
    for a in attempts:
        s = by_id[a.session_id]
        d = a.diagnosis or {}
        answered, correct = d.get("answered"), d.get("correct")
        minutes = round((a.finished_at - a.started_at).total_seconds() / 60, 1) if a.finished_at else ""
        w.writerow([s.class_name, titles.get(s.chapter_id, ""), s.join_code, a.nickname,
                    "bitirdi" if a.status == "done" else "yarımçıq",
                    answered or "", correct if correct is not None else "",
                    f"{round(100 * correct / answered)}%" if answered else "",
                    ", ".join(d.get("roots", [])), a.started_at.strftime("%Y-%m-%d %H:%M"), minutes])
    # BOM: Excel az herflerini duz gostersin
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="temel_neticeler.csv"'})


# ---------- admin: butun testler (kodlu ve kodsuz) ----------

@router.get("/admin/attempts", dependencies=[Depends(require_admin)])
def admin_attempts(db: Session = Depends(get_db)):
    titles = {c.id: (c.title, c.grade) for c in db.scalars(select(Chapter)).all()}
    classes = {s.id: s.class_name for s in db.scalars(select(ClassSession)).all()}
    rows = []
    for a in db.scalars(select(Attempt).order_by(Attempt.id.desc())).all():
        d = a.diagnosis or {}
        title, grade = titles.get(a.chapter_id, ("", None))
        rows.append({
            "id": a.id, "nickname": a.nickname, "chapter": title, "grade": grade,
            "class_name": classes.get(a.session_id) or "— kodsuz —",
            "status": "bitirdi" if a.status == "done" else "yarımçıq",
            "answered": d.get("answered"), "correct": d.get("correct"),
            "roots": d.get("roots", []),
            "careless": d.get("careless"),
            "minutes": round((a.finished_at - a.started_at).total_seconds() / 60, 1) if a.finished_at else None,
            "started_at": a.started_at.strftime("%Y-%m-%d %H:%M"),
        })
    return rows


@router.get("/admin/attempts/{attempt_id}", dependencies=[Depends(require_admin)])
def admin_attempt_detail(attempt_id: int, db: Session = Depends(get_db)):
    a = db.get(Attempt, attempt_id)
    if a is None:
        raise HTTPException(404, "Tapılmadı")
    answers = db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == a.id)
                         .order_by(AttemptAnswer.id)).all()
    d = a.diagnosis or {}
    return {
        "nickname": a.nickname, "roots": d.get("roots", []), "weak_because": d.get("weak_because", {}),
        "explanation": (d.get("explanation") or {}).get("headline"),
        "answers": [{"concept": x.concept, "question": x.question_text, "chosen": x.chosen,
                     "correct_value": x.correct_value, "correct": x.correct,
                     "misconception": x.misconception} for x in answers],
    }
