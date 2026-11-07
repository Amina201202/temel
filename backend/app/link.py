"""Sinifler arasi elaqe: yeni bolmenin movzularini evvelki siniflerin movzulari ile baglayir.
Mes: "Kvadrat tenlik (8)" <- "Vuruqlara ayirma (7)" <- "Tam ededler (6)".
"""
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .extract import MODEL, get_client, grade_label
from .models import Chapter, Concept, ConceptEdge


class Link(BaseModel):
    concept: str = Field(description="Yeni bölmənin mövzusu (siyahıdan, adı dəqiq)")
    prerequisite_id: int = Field(description="Əvvəlki sinif mövzusunun id-si (siyahıdan)")
    reason: str = Field(description="1 qısa cümlə: niyə bu bilik lazımdır")


class Links(BaseModel):
    links: list[Link]


PROMPT = """Sən riyaziyyat kurikulumu mütəxəssisisən.
Şagird {grade} sinifdə «{title}» bölməsini öyrənir. Bu bölmənin mövzuları:
{targets}

Əvvəlki siniflərdə (və ya eyni sinfin əvvəlki bölmələrində) öyrənilmiş mövzular:
{candidates}

Tapşırıq: yeni bölmənin hər mövzusu üçün onu başa düşmək üçün MÜTLƏQ bilinməli olan əvvəlki mövzuları seç.
- Yalnız BİRBAŞA və vacib asılılıqları yaz (bir mövzuya ən çox 2 əlaqə).
- "Faydalı olar" kifayət deyil: əvvəlki mövzunu bilmədən yeni mövzu ilə bağlı tapşırıq həll oluna bilmirsə, əlaqə yaz.
- Heç bir əlaqə yoxdursa, həmin mövzunu yazma.
- prerequisite_id yalnız siyahıdakı id-lərdən olsun."""


def candidate_concepts(db: Session, chapter: Chapter):
    # asagi sinifler + eyni sinfin evvel yuklenmis bolmeleri (dovr olmasin deye)
    rows = db.execute(
        select(Concept, Chapter)
        .join(Chapter, Chapter.id == Concept.chapter_id)
        .where(or_(Chapter.grade < chapter.grade,
                   (Chapter.grade == chapter.grade) & (Chapter.id < chapter.id)))
        .order_by(Chapter.grade, Chapter.id, Concept.id)
    ).all()
    return rows


def suggest_links(db: Session, chapter: Chapter):
    targets = db.scalars(select(Concept).where(Concept.chapter_id == chapter.id).order_by(Concept.id)).all()
    cands = candidate_concepts(db, chapter)
    if not targets or not cands:
        return []
    prompt = PROMPT.format(
        grade=grade_label(chapter.grade), title=chapter.title,
        targets="\n".join(f"- {c.name}: {c.description}" for c in targets),
        candidates="\n".join(f"[id={c.id}] {c.name} ({grade_label(ch.grade)} sinif, «{ch.title}»): {c.description}"
                             for c, ch in cands),
    )
    resp = get_client().models.generate_content(
        model=MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_schema=Links, temperature=0.1),
    )
    if resp.parsed is None:
        return []

    by_name = {c.name: c for c in targets}
    valid_ids = {c.id for c, _ in cands}
    created = []
    for link in resp.parsed.links:
        target = by_name.get(link.concept)
        # AI siyahida olmayan ad ve ya id yaza biler - yoxlayiriq
        if target is None or link.prerequisite_id not in valid_ids:
            continue
        exists = db.scalar(select(ConceptEdge).where(ConceptEdge.from_concept_id == link.prerequisite_id,
                                                     ConceptEdge.to_concept_id == target.id))
        if exists:
            continue
        edge = ConceptEdge(chapter_id=chapter.id, from_concept_id=link.prerequisite_id, to_concept_id=target.id)
        db.add(edge)
        created.append((edge, link.reason))
    db.commit()
    return created


def collect_graph(db: Session, chapter: Chapter):
    """Bolmenin movzulari + onlara elaqeli butun evvelki sinif movzulari (dolayi da)."""
    home = db.scalars(select(Concept).where(Concept.chapter_id == chapter.id).order_by(Concept.id)).all()
    concepts = {c.id: c for c in home}
    edges = {}
    frontier = set(concepts)
    while frontier:
        rows = db.scalars(select(ConceptEdge).where(ConceptEdge.to_concept_id.in_(frontier))).all()
        frontier = set()
        for e in rows:
            edges[e.id] = e
            if e.from_concept_id not in concepts:
                concepts[e.from_concept_id] = db.get(Concept, e.from_concept_id)
                frontier.add(e.from_concept_id)

    grades = {ch.id: ch.grade for ch in db.scalars(select(Chapter).where(
        Chapter.id.in_({c.chapter_id for c in concepts.values()}))).all()}

    # basqa bolmenin movzusuna sinfi elave edirik: "Vuruqlara ayirma (7-ci sinif)"
    display = {}
    for cid, c in concepts.items():
        name = c.name if c.chapter_id == chapter.id else f"{c.name} ({grade_label(grades[c.chapter_id])} sinif)"
        while name in display.values():
            name += "*"
        display[cid] = name
    return concepts, edges, display, grades
