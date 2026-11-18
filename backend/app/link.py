"""Sinifler arasi elaqe: yeni bolmenin movzularini evvelki siniflerin movzulari ile baglayir.
Mes: "Kvadrat tenlik (8)" <- "Vuruqlara ayirma (7)" <- "Tam ededler (6)".
"""
import logging

from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .extract import MODEL, get_client, grade_label
from .models import Chapter, Concept, ConceptEdge


MAX_LINKS_PER_CONCEPT = 2
MIN_SCORE = 4
log = logging.getLogger("uvicorn.error")


class Link(BaseModel):
    concept_id: int = Field(description="Yeni bölmənin mövzusunun id-si (siyahıdan)")
    prerequisite_id: int = Field(description="Əvvəlki mövzunun id-si (siyahıdan)")
    reason: str = Field(description="1 qısa cümlə: niyə bu bilik lazımdır")


class Prereq(BaseModel):
    prerequisite_id: int = Field(description="Əvvəlki mövzunun id-si (siyahıdan)")
    score: int = Field(description="1-5: 5 = bunsuz tapşırıq həll olunmur, 1 = demək olar əlaqəsi yoxdur")
    reason: str = Field(description="1 qısa cümlə, konkret nümunə ilə")


class TargetLinks(BaseModel):
    concept_id: int = Field(description="Yeni bölmənin mövzusunun id-si")
    prereqs: list[Prereq]


class Links(BaseModel):
    items: list[TargetLinks]


PROMPT = """Sən riyaziyyat kurikulumu mütəxəssisisən.
Şagird {grade} sinifdə «{title}» bölməsini öyrənir. Bu bölmənin mövzuları:
{targets}

Əvvəlki siniflərdə (və ya eyni sinfin əvvəlki bölmələrində) öyrənilmiş mövzular:
{candidates}

Tapşırıq: yeni bölmənin HƏR mövzusu üçün əvvəlki siyahıdan ən vacib 1-3 mövzunu seç və hər birinə bal ver:
  5 = bu bilik olmadan yeni mövzunun tipik tapşırığı həll oluna bilməz
  4 = tapşırıqların çoxunda bu bilik birbaşa istifadə olunur
  3 = faydalıdır, amma vacib deyil
  1-2 = zəif əlaqə
Qaydalar:
- Siyahıdakı bütün siniflərə bax, yalnız birinə yox. Ən yaxın və birbaşa istifadə olunan bilik ən yüksək balı alır.
- Tipik tapşırığı ağlında həll et və hansı əvvəlki bilikdən istifadə etdiyinə bax.
  Nümunə: "Diskriminant" -> "Tam ədədlərin vurulması" 5 bal (b² − 4ac mənfi ədədlərlə hesablanır).
- AD OXŞARLIĞINA görə bal vermə: "Kəsrlərin toplanması" -> "Tam ədədlərin toplanması" 1 baldır (−3 + 5 kəsrsiz hesablanır).
- Tərif və tanıma mövzuları ("Birhədli", "Dərəcə", "Sərbəst hədd" kimi) hesablama mövzularından 4-5 bal almır.
- concept_id yeni bölmənin siyahısından, prerequisite_id əvvəlki mövzuların siyahısından olsun."""


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
        targets="\n".join(f"[id={c.id}] {c.name}: {c.description}" for c in targets),
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

    by_id = {c.id: c for c in targets}
    valid_ids = {c.id for c, _ in cands}
    names = {c.id: c.name for c, _ in cands} | {c.id: c.name for c in targets}
    log.info("LINK teklif: %s", [(names.get(p.prerequisite_id), names.get(i.concept_id), p.score)
                                 for i in resp.parsed.items for p in i.prereqs])

    # AI siyahida olmayan ad ve ya id yaza biler - yoxlayiriq
    proposed = {}
    for item in resp.parsed.items:
        target = by_id.get(item.concept_id)
        # yuksek bal birinci gelsin
        for pr in sorted(item.prereqs, key=lambda x: -x.score):
            if target is None or pr.prerequisite_id not in valid_ids:
                log.info("LINK atildi (id sehvdir): %s -> %s", pr.prerequisite_id, item.concept_id)
                continue
            if pr.score < MIN_SCORE:
                log.info("LINK atildi (bal %s): %s -> %s", pr.score, names.get(pr.prerequisite_id), target.name)
                continue
            proposed.setdefault(target.id, {})[pr.prerequisite_id] = pr.reason

    # dolayi elaqeni atiriq, amma yalniz yaxin yollara baxiriq (uzaq yollar duz elaqeni de silirdi)
    home_ids = {c.id for c in targets}
    all_edges = db.scalars(select(ConceptEdge)).all()

    # 1) bu bolmenin daxili elaqeleri + AI teklifleri
    children = {}
    for e in all_edges:
        if e.from_concept_id in home_ids and e.to_concept_id in home_ids:
            children.setdefault(e.from_concept_id, set()).add(e.to_concept_id)
    for target_id, sources in proposed.items():
        for src_id in sources:
            children.setdefault(src_id, set()).add(target_id)

    def reaches(start, goal):
        stack, seen = [start], set()
        while stack:
            cur = stack.pop()
            if cur == goal:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(children.get(cur, ()))
        return False

    # 2) evvelki movzularin oz aralarindaki yollar (A -> B, ikisi de eyni hedefe teklif olunubsa A artiqdir)
    parents = {}
    for e in all_edges:
        parents.setdefault(e.to_concept_id, set()).add(e.from_concept_id)

    def ancestors(cid):
        out, stack = set(), [cid]
        while stack:
            for p in parents.get(stack.pop(), ()):
                if p not in out:
                    out.add(p)
                    stack.append(p)
        return out

    created = []
    for target_id, sources in proposed.items():
        target = db.get(Concept, target_id)
        kept = 0
        for src_id, reason in sources.items():
            # A -> X (bu bolmeden) -> hedef yolu varsa
            if any(reaches(c, target_id) for c in children.get(src_id, ()) if c != target_id):
                log.info("LINK atildi (dolayi yol): %s -> %s", names.get(src_id), target.name)
                continue
            # A basqa teklif olunan B-nin evvelki movzusudursa
            if any(src_id in ancestors(other) for other in sources if other != src_id):
                log.info("LINK atildi (basqa teklifin evvelidir): %s -> %s", names.get(src_id), target.name)
                continue
            if kept >= MAX_LINKS_PER_CONCEPT:
                break
            kept += 1
            link = Link(concept_id=target.id, prerequisite_id=src_id, reason=reason)
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
