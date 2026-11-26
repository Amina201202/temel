"""Fine-tuning ucun dataset: Gemini (boyuk "muellim") kicik modeli oyredir - distillation.

1) DB-deki her movzu ucun Gemini sagird sualleri yazir (movzuya aid + aid olmayan)
2) Her suali guard-in OZ promptu ile Gemini etiketleyir (on / off) - bu bizim "duz cavab"
3) Movzulara gore bolurik: train / valid / test (test movzularini model hec gormur)

    docker compose exec api python -m app.ft_data
Netice: data/eval/ft/{train,valid,test}.jsonl  (mlx-lm chat formati)
"""
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.genai import types
from pydantic import BaseModel
from sqlalchemy import select

from .db import SessionLocal
from .extract import MODEL, get_client
from .guard import EMAIL, FT_SYSTEM, INJECTION_RE, PHONE, TOPIC_PROMPT, TopicCheck
from .models import Chapter, Concept

OUT = Path("/app/eval/ft")
SYSTEM = FT_SYSTEM  # guard.py-de, lokal model de eyni promptu gorur


def user_text(concept, question):
    return f"Mövzu: {concept}\nSual: {question}"


class Item(BaseModel):
    text: str
    kind: str


class Items(BaseModel):
    items: list[Item]


GEN_PROMPT = """{grade}-ci sinif şagirdi «{concept}» riyaziyyat mövzusunu öyrənir və AI köməkçiyə yazır.
Şagirdin yaza biləcəyi 12 fərqli qısa mesaj yaz (Azərbaycan dilində, uşaq dili ilə, bəzən səhv yazı, bəzən ingilis/rus sözü):
- 6 mesaj bu mövzu haqqında (anlamadığı yer, "niyə", nümunə istəmək, səhvini soruşmaq, qaydanı soruşmaq) -> kind="on"
- 6 mesaj aid deyil: salam/necəsən, başqa fənn (tarix, ingilis dili...), futbol/oyun/kino, şəxsi söhbət,
  "ev tapşırığımı həll et" (hazır cavab istəmək), uzaq riyaziyyat mövzusu -> kind="off"
Hər mesaj 3-20 söz. Bir-birini təkrarlamasın."""


def generate(concept, grade):
    try:
        resp = get_client().models.generate_content(
            model=MODEL, contents=GEN_PROMPT.format(concept=concept, grade=grade),
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Items,
                                               temperature=1.0, thinking_config=types.ThinkingConfig(thinking_budget=0)))
    except Exception as e:  # noqa: BLE001
        # bir movzu alinmasa butun skript dayanmasin
        print(f"  ! {concept}: {e}")
        return []
    return [(concept, it.text.strip(), it.kind) for it in (resp.parsed.items if resp.parsed else [])]


def label(concept, question):
    # guard.py-deki EYNI prompt - kicik model Gemini-nin qerarini oyrenir
    try:
        resp = get_client().models.generate_content(
            model=MODEL, contents=TOPIC_PROMPT.format(concept=concept, question=question.replace(">>>", "")),
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=TopicCheck,
                                               temperature=0, thinking_config=types.ThinkingConfig(thinking_budget=0)))
    except Exception as e:  # noqa: BLE001
        print(f"  ! etiket: {e}")
        return None
    return "on" if resp.parsed and resp.parsed.on_topic else "off"


def to_row(concept, question, lab):
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user_text(concept, question)},
                         {"role": "assistant", "content": lab}]}


def main():
    db = SessionLocal()
    try:
        grades = {c.id: c.grade for c in db.scalars(select(Chapter)).all()}
        concepts = sorted({(c.name, grades.get(c.chapter_id, 5)) for c in db.scalars(select(Concept)).all()})
    finally:
        db.close()
    print(f"{len(concepts)} mövzu üçün suallar yaradılır...")
    get_client()  # client-i thread-lerden evvel yaradiriq

    with ThreadPoolExecutor(max_workers=8) as pool:
        generated = [x for part in pool.map(lambda c: generate(*c), concepts) for x in part]
    # injection / sexsi melumat regex ile tutulur, onlari kicik modele oyretmeye ehtiyac yoxdur
    generated = [g for g in generated if not (INJECTION_RE.search(g[1]) or PHONE.search(g[1]) or EMAIL.search(g[1]))]
    print(f"{len(generated)} sual yaradıldı, Gemini etiketləyir...")

    with ThreadPoolExecutor(max_workers=8) as pool:
        labels = list(pool.map(lambda g: label(g[0], g[1]), generated))

    # movzulara gore bolurik ki, test movzulari train-de olmasin (data leakage yox)
    names = sorted({c for c, _ in concepts})
    random.Random(42).shuffle(names)
    n = len(names)
    split = {c: "test" if i < n // 10 else "valid" if i < n // 5 else "train" for i, c in enumerate(names)}

    OUT.mkdir(parents=True, exist_ok=True)
    files = {k: open(OUT / f"{k}.jsonl", "w", encoding="utf-8") for k in ("train", "valid", "test")}
    stats = {k: {"on": 0, "off": 0} for k in files}
    agree = 0
    for (concept, q, kind), lab in zip(generated, labels):
        if lab is None:
            continue
        part = split[concept]
        files[part].write(json.dumps(to_row(concept, q, lab), ensure_ascii=False) + "\n")
        stats[part][lab] += 1
        agree += kind == lab
    for f in files.values():
        f.close()
    print(json.dumps(stats, indent=2))
    print(f"Generasiya niyyəti ilə Gemini etiketinin uyğunluğu: {agree}/{len(generated)}")
    print(f"Fayllar: data/eval/ft/")


if __name__ == "__main__":
    main()
