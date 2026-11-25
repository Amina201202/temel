"""Telegram + n8n: sagirde 3 gunluk plan xatirlatmasi, muellime heftelik hesabat.

Yol: Telegram -> (ngrok) -> /telegram/webhook (burada) -> n8n webhook -> Telegram-a mesaj.
Mentiqi API edir (kim kimdir, hansi plan), n8n ise gozleyir (Wait) ve mesaji gonderir.
"""
import html
import json
import logging
import os
import secrets
import threading
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import current_teacher, require_admin, store
from .db import SessionLocal, get_db
from .models import Attempt, Chapter, TelegramLink, Teacher
from .teacher import is_careless, teacher_attempts

log = logging.getLogger("uvicorn.error")
router = APIRouter()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_NAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
N8N_URL = os.getenv("N8N_URL", "http://n8n:5678")
# planin gunleri arasi fasile: realda 1 gun, demoda 2 deqiqe qoymaq olar
REMIND_MINUTES = int(os.getenv("REMIND_MINUTES", "1440"))
LINK_TTL = 24 * 3600


class TokenBody(BaseModel):
    token: str


def bot_ready():
    if not (BOT_TOKEN and BOT_NAME):
        raise HTTPException(503, "Telegram botu hələ qoşulmayıb")


def deep_link(kind, ref_id):
    # Telegram /start <kod> gonderir, kodla kimin qosuldugunu bilirik (1 gun kecerli)
    code = secrets.token_urlsafe(9)
    store().setex(f"tg:{code}", LINK_TTL, f"{kind}:{ref_id}")
    return f"https://t.me/{BOT_NAME}?start={code}"


def to_n8n(path, payload):
    req = urllib.request.Request(f"{N8N_URL}/webhook/{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001
        # n8n dusubse API islemeye davam etsin
        log.warning("N8N gonderilmedi (%s): %s", path, e)


# ---------- plan (app.js-deki buildPlan ile eyni) ----------

def build_plan(d):
    if not d.get("roots"):
        return ("Biliyini möhkəmləndir və növbəti mövzuya keç", [
            ("Çətin tapşırıqlar", ["Bölmənin sonundakı çətin məsələlərdən 5-ni həll et"]),
            ("Növbəti mövzu", ["Dərslikdə növbəti bölməyə başla"]),
            ("Yoxlama", ["Testi yenidən keç"]),
        ])
    root = d["roots"][0]
    deps = [w for w, because in (d.get("weak_because") or {}).items() if root in because]
    nxt = deps[0] if deps else None
    goal = f"{root} boşluğunu bağlamaq" + (f", sonra {nxt} mövzusuna qayıtmaq" if nxt else "")
    day2 = ([f"{nxt}: dərslikdəki nümunələrə bax", f"{nxt}: 5 məşq həll et"] if nxt
            else [f"{root}: 5 çətin məşq həll et", "Səhv etdiyin məşqləri yenidən yoxla"])
    return goal, [
        (root, [f"Dərslikdə {root} izahını yenidən oxu", f"{root}: 5 asan məşq həll et"]),
        (nxt or root, day2),
        ("Yoxlama", ["Testi yenidən keç", f"{root} indi “Bilirsən” çıxırmı, bax"]),
    ]


def plan_messages(attempt):
    e = html.escape
    goal, days = build_plan(attempt.diagnosis or {})

    def day_text(i):
        title, tasks = days[i]
        return f"📅 <b>Gün {i + 1} · {e(title)}</b>\n" + "\n".join(f"• {e(t)}" for t in tasks)

    day1 = (f"👋 Salam, <b>{e(attempt.nickname)}</b>!\nMən Təməl botuyam, 3 günlük planını xatırladacağam.\n\n"
            f"🎯 Hədəf: {e(goal)}\n\n{day_text(0)}\n\nSabah Gün 2-ni göndərəcəyəm 💪")
    day2 = (f"{day_text(1)}\n\nDünənki tapşırıqları etdin? Bu gün davam edək!\n"
            "💬 Başa düşmədiyin yer varsa, bura yaz — cavab verəcəyəm.")
    day3 = f"{day_text(2)}\n\n👉 Test: {PUBLIC_URL}/app/\nBoşluq bağlandısa, bilik xəritəndə yaşıl olacaq 🌱"
    return day1, day2, day3


# ---------- linkler ----------

@router.post("/attempts/{attempt_id}/telegram")
def student_telegram(attempt_id: int, body: TokenBody, db: Session = Depends(get_db)):
    bot_ready()
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or not secrets.compare_digest(attempt.token, body.token):
        raise HTTPException(404, "Test tapılmadı")
    if attempt.status != "done":
        raise HTTPException(400, "Əvvəlcə testi bitir")
    return {"url": deep_link("student", attempt.id)}


@router.post("/teacher/telegram")
def teacher_telegram(teacher: Teacher = Depends(current_teacher)):
    bot_ready()
    return {"url": deep_link("teacher", teacher.id)}


# ---------- Telegram webhook ----------

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks,
                           x_telegram_bot_api_secret_token: str | None = Header(None),
                           db: Session = Depends(get_db)):
    # yalniz Telegram bilir bu sirri, yoxsa her kes bize saxta mesaj gondere biler
    if not SECRET or not secrets.compare_digest(x_telegram_bot_api_secret_token or "", SECRET):
        raise HTTPException(403, "icazə yoxdur")
    update = await request.json()
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id:
        return {"ok": True}

    value = None
    if text.startswith("/start "):
        code = text.split(maxsplit=1)[1]
        value = store().get(f"tg:{code}")
        if value:
            store().delete(f"tg:{code}")  # kod bir defelikdir

    if not value:
        # qosulmus sagird adi mesaj yazirsa - kok movzusu uzre sual kimi cavablayiriq
        link = db.scalar(select(TelegramLink).where(TelegramLink.chat_id == chat_id)
                         .order_by(TelegramLink.id.desc()).limit(1))
        if link and link.kind == "student" and text and not text.startswith("/"):
            background.add_task(answer_in_chat, chat_id, link.ref_id, text)
            return {"ok": True}
        hello = ("Salam! Mən <b>Təməl</b> botuyam 👋\nTesti bitirəndən sonra 3 günlük plan ekranında "
                 "<b>“Telegram-da xatırlat”</b> düyməsini bas — planını bura göndərəcəyəm.")
        if link and link.kind == "teacher":
            hello = "Salam! 👋 Həftəlik hesabat hər bazar ertəsi saat 9:00-da bura gələcək."
        background.add_task(to_n8n, "temel-message", {"chat_id": chat_id, "text": hello})
        return {"ok": True}

    kind, ref_id = value.split(":")
    ref_id = int(ref_id)
    if kind == "teacher":
        teacher = db.get(Teacher, ref_id)
        if teacher is None:
            return {"ok": True}
        # muellimin bir chat-i olur, yenisi kohnesini evez edir
        db.execute(delete(TelegramLink).where(TelegramLink.kind == "teacher", TelegramLink.ref_id == ref_id))
        db.add(TelegramLink(kind="teacher", ref_id=ref_id, chat_id=chat_id))
        db.commit()
        background.add_task(to_n8n, "temel-message", {
            "chat_id": chat_id,
            "text": f"✅ {html.escape(teacher.name)}, Telegram qoşuldu.\n"
                    "Hər bazar ertəsi saat 9:00-da siniflərinizin həftəlik hesabatı bura gələcək.",
        })
        return {"ok": True}

    attempt = db.get(Attempt, ref_id)
    if attempt is None or not attempt.diagnosis:
        return {"ok": True}
    db.add(TelegramLink(kind="student", ref_id=ref_id, chat_id=chat_id))
    db.commit()
    day1, day2, day3 = plan_messages(attempt)
    log.info("TELEGRAM plan: attempt=%s", attempt.id)
    background.add_task(to_n8n, "temel-student", {
        "chat_id": chat_id, "day1": day1, "day2": day2, "day3": day3, "wait_minutes": REMIND_MINUTES,
    })
    return {"ok": True}


def answer_in_chat(chat_id, attempt_id, text):
    """Telegram-dan gelen suala "Sualın var?" ile eyni yolla (guard + RAG) cavab."""
    from .main import answer_for_attempt  # main bu fayli import edir, ona gore burda
    e = html.escape
    db = SessionLocal()
    try:
        attempt = db.get(Attempt, attempt_id)
        if attempt is None:
            return
        if not (attempt.diagnosis or {}).get("roots"):
            reply = "Testində boşluq tapılmadı 🎉 Suallarını müəlliminə də verə bilərsən."
        else:
            root = attempt.diagnosis["roots"][0]
            try:
                ans = answer_for_attempt(db, attempt, text)
                src = f"\n\n📖 Dərslik, səh. {ans['source_page']}" if ans.get("source_page") else ""
                reply = f"🤖 <b>{e(root)}</b> haqqında:\n{e(ans['answer'])}{src}\n\n<i>{ans['left']} sual qaldı</i>"
            except HTTPException as err:
                reply = f"⚠️ {e(str(err.detail))}"
            except Exception as err:  # noqa: BLE001
                log.warning("TELEGRAM cavab xetasi: %s", err)
                reply = "⚠️ İndi cavab verə bilmədim, bir az sonra yenidən yaz."
    finally:
        db.close()
    to_n8n("temel-message", {"chat_id": chat_id, "text": reply})


# ---------- muellime heftelik hesabat (n8n her bazar ertesi cagirir) ----------

def weekly_report(db, teacher):
    e = html.escape
    since = datetime.now(timezone.utc) - timedelta(days=7)
    sessions, by_id, attempts = teacher_attempts(db, teacher)
    week = [a for a in attempts if a.started_at and a.started_at >= since]
    done = [a for a in week if a.status == "done" and a.diagnosis and not is_careless(a)]
    titles = {c.id: c.title for c in db.scalars(select(Chapter)).all()}

    lines = [f"📊 <b>Həftəlik hesabat</b> · {e(teacher.name)}",
             f"Son 7 gün: {len(week)} şagird, {len(done)} test bitirdi."]
    if not done:
        lines.append("\nBu həftə bitmiş test yoxdur. Yeni sessiya açmaq üçün müəllim panelinə keçin.")
    else:
        no_gap = sum(1 for a in done if not a.diagnosis.get("roots"))
        roots = Counter(r for a in done for r in a.diagnosis.get("roots", []))
        lines.append(f"Boşluqsuz: {no_gap} şagird.")
        lines.append("\n🔴 <b>Ən çox kök səbəblər:</b>")
        lines += [f"• {e(r)} — {n} şagird" for r, n in roots.most_common(3)]
        classes = Counter(by_id[a.session_id].class_name for a in done)
        lines.append("\n🏫 <b>Siniflər:</b> " + ", ".join(f"{e(c)} ({n})" for c, n in classes.most_common()))
        chapters = {titles.get(by_id[a.session_id].chapter_id) for a in done} - {None}
        lines.append("📚 Bölmələr: " + e(", ".join(sorted(chapters))))
        if roots:
            top = roots.most_common(1)[0][0]
            lines.append(f"\n💡 Tövsiyə: növbəti dərsin əvvəlində 10 dəqiqə <b>{e(top)}</b> təkrarı.")
    if PUBLIC_URL:
        lines.append(f"\n👉 Ətraflı: {PUBLIC_URL}/app/teacher.html")
    return "\n".join(lines)


@router.get("/internal/teacher-reports", dependencies=[Depends(require_admin)])
def teacher_reports(db: Session = Depends(get_db)):
    links = db.scalars(select(TelegramLink).where(TelegramLink.kind == "teacher")).all()
    out = []
    for link in links:
        teacher = db.get(Teacher, link.ref_id)
        if teacher:
            out.append({"chat_id": link.chat_id, "text": weekly_report(db, teacher)})
    return out


# ---------- API ise dusende webhook-u Telegram-da qeyd edirik ----------

def set_webhook():
    if not (BOT_TOKEN and SECRET and PUBLIC_URL):
        log.info("TELEGRAM: token/secret/PUBLIC_URL yoxdur, webhook qurulmadi")
        return

    def run():
        data = json.dumps({"url": f"{PUBLIC_URL}/telegram/webhook", "secret_token": SECRET,
                           "allowed_updates": ["message"]}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=15).read())
            log.info("TELEGRAM webhook: %s", res.get("description"))
        except Exception as e:  # noqa: BLE001
            log.warning("TELEGRAM webhook qurulmadi: %s", e)

    threading.Thread(target=run, daemon=True).start()
