"""Sagird hesablari: lebeq + 4 reqemli PIN ile oz neticelerine baxmaq.

Tam qeydiyyat deyil: e-poct, real ad yoxdur. PIN muellim sifreleri kimi scrypt ile saxlanir,
5 sehv cehdden sonra 15 deqiqe blok (4 reqemi texmin etmek olmasin).
"""
import re
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import bearer, clear_fails, hash_password, login_blocked, register_fail, store, verify_password
from .db import get_db
from .models import Attempt, Chapter, Student

router = APIRouter()
PIN_RE = re.compile(r"^\d{4}$")
NICK_RE = re.compile(r"^[\w .-]{2,20}$")
TOKEN_TTL = 30 * 24 * 3600  # 30 gun - telefonda her defe giris etmesin


class ResultsIn(BaseModel):
    nickname: str
    pin: str


def nick_key(nickname):
    return " ".join(nickname.lower().split())


def student_for(db, nickname, pin, create):
    if not PIN_RE.match(pin or ""):
        raise HTTPException(400, "PIN 4 rəqəm olmalıdır")
    key = nick_key(nickname)
    fail_key = f"student:{key}"  # muellim login-i ile eyni limiter
    if login_blocked(fail_key):
        raise HTTPException(429, "Çox səhv cəhd oldu. 15 dəqiqə sonra yenidən yoxla.")
    student = db.scalar(select(Student).where(Student.nickname_key == key))
    if student is None:
        if not create:
            register_fail(fail_key)
            raise HTTPException(403, "Ləqəb və ya PIN səhvdir")
        student = Student(nickname=nickname.strip(), nickname_key=key, pin_hash=hash_password(pin))
        db.add(student)
        db.flush()
        return student
    if not verify_password(pin, student.pin_hash):
        register_fail(fail_key)
        if create:
            raise HTTPException(403, "Bu ləqəb artıq başqasınındır və ya PIN səhvdir. Başqa ləqəb seç.")
        raise HTTPException(403, "Ləqəb və ya PIN səhvdir")
    clear_fails(fail_key)
    return student


def results_of(db, student):
    chapters = {c.id: c for c in db.scalars(select(Chapter)).all()}
    attempts = db.scalars(select(Attempt).where(Attempt.student_id == student.id)
                          .order_by(Attempt.started_at)).all()

    rows, last_roots, closed_total = [], {}, set()  # her bolme ucun evvelki testin kok sebebleri
    for a in attempts:
        d = a.diagnosis or {}
        roots = d.get("roots", []) if a.status == "done" else []
        progress = None
        if a.status == "done" and a.chapter_id in last_roots:
            prev = last_roots[a.chapter_id]
            # evvel kok sebeb idi, indi deyil -> bagladi
            progress = {"prev": prev, "closed": [r for r in prev if r not in roots],
                        "still": [r for r in prev if r in roots]}
            closed_total.update(progress["closed"])
        if a.status == "done":
            # mesqle baglananlar da sayilir
            closed_total.update(d.get("closed") or [])
            last_roots[a.chapter_id] = roots
        ch = chapters.get(a.chapter_id)
        rows.append({
            "attempt_id": a.id, "token": a.token, "status": a.status,
            "chapter": ch.title if ch else "", "grade": ch.grade if ch else None,
            "date": a.started_at.strftime("%d.%m.%Y %H:%M"),
            "answered": d.get("answered"), "correct": d.get("correct"), "roots": roots,
            "careless": (d.get("careless") or 0) >= 0.5, "progress": progress,
            "closed": d.get("closed") or [],
        })
    done = [r for r in rows if r["status"] == "done"]
    last_root = next((r["roots"][0] for r in reversed(done) if r["roots"]), None)
    return {"nickname": student.nickname,
            "stats": {"tests": len(done), "closed": len(closed_total), "last_root": last_root},
            "attempts": list(reversed(rows))}


class LoginIn(BaseModel):
    nickname: str
    pin: str


def current_student(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Student:
    sid = store().get(f"student_token:{bearer(authorization)}")
    student = db.get(Student, int(sid)) if sid else None
    if student is None:
        raise HTTPException(401, "Yenidən daxil ol")
    return student


@router.post("/students/login")
def student_login(body: LoginIn, db: Session = Depends(get_db)):
    """Lebeq + PIN. Ilk defedirse hesab yaranir (ayrica qeydiyyat yoxdur)."""
    nickname = body.nickname.strip()
    if not NICK_RE.match(nickname) or sum(ch.isdigit() for ch in nickname) >= 7:
        raise HTTPException(400, "Ləqəb 2-20 simvol olmalıdır (hərf, rəqəm, boşluq, _ . -)")
    student = student_for(db, nickname, body.pin, create=True)
    db.commit()
    token = secrets.token_urlsafe(24)
    store().setex(f"student_token:{token}", TOKEN_TTL, student.id)
    return {"token": token, "nickname": student.nickname}


@router.post("/students/logout")
def student_logout(authorization: str | None = Header(None)):
    store().delete(f"student_token:{bearer(authorization)}")
    return {"ok": True}


@router.get("/students/me")
def student_me(student: Student = Depends(current_student), db: Session = Depends(get_db)):
    return results_of(db, student)
