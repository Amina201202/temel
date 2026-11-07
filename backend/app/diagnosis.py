"""Adaptiv diaqnostik test - LangGraph ile.

Fikir: sagird en "ust" movzudan baslayir. Duz cavab versə, hemin movzunun
butun evvelki movzulari da bilinir sayilir. Sehv versə, sehv variantin
gosterdiyi (points_to) evvelki movzuya enirik. Asagida duz, yuxarida sehv
olan yer - kok sebebdir.

"Hara enmek" qerarini AI vermir, qrafa gore sade qayda verir.
"""
import random
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .questions import build_instance

MAX_QUESTIONS = 12
MIN_QUESTIONS = 5


class DiagState(TypedDict, total=False):
    concepts: list[str]
    prereqs: dict[str, list[str]]
    templates: dict[str, list[dict]]
    meta: dict
    seed: int
    status: dict[str, str]  # known | implied | weak | weak_implied | untested
    stack: list[str]
    retried: list[str]
    confirmed: list[str]
    used_templates: list[int]
    asked: list[dict]
    current: dict | None
    answer: str | None
    done: bool
    diagnosis: dict | None


def ancestors(concept, prereqs):
    # bir movzudan evvel bilinmeli olan butun movzular (dolayi da)
    seen, stack = set(), list(prereqs.get(concept, []))
    while stack:
        c = stack.pop()
        if c not in seen:
            seen.add(c)
            stack.extend(prereqs.get(c, []))
    return seen


def plan(state: DiagState):
    prereqs = state["prereqs"]
    used_as_prereq = {p for ps in prereqs.values() for p in ps}
    # en ust movzular - hec kimin evvelki movzusu olmayanlar
    tops = [c for c in state["concepts"] if c not in used_as_prereq and state["templates"].get(c)]
    # en derin olanlardan basla: bir duz cavab cox movzunu yoxlamis olur
    tops.sort(key=lambda c: len(ancestors(c, prereqs)), reverse=True)
    return {"status": {}, "stack": tops, "retried": [], "confirmed": [], "used_templates": [], "asked": [],
            "current": None, "answer": None, "done": False, "diagnosis": None}


def pick(state: DiagState):
    status = dict(state["status"])
    stack = list(state["stack"])
    used = list(state["used_templates"])
    rng = random.Random(state["seed"] + len(state["asked"]))
    asked_concepts = {a["concept"] for a in state["asked"]}

    if len(state["asked"]) >= MAX_QUESTIONS:
        return {"done": True, "current": None, "stack": stack, "status": status}

    retried = list(state["retried"])
    while True:
        if not stack:
            # bitirmeden evvel: yalniz 1 sehv cavaba esaslanan kok namizedini yeniden yoxlayiriq
            # (tesadufi sehv saxta kok yaratmasin)
            prereqs = state["prereqs"]
            cands = [c for c in state["concepts"]
                     if status.get(c) == "weak" and c not in retried and state["templates"].get(c)
                     and all(status.get(p) in ("known", "implied") for p in prereqs.get(c, []))]
            if cands:
                c = cands[0]
                retried.append(c)
                status.pop(c)
                stack.append(c)
                continue
            # cox tez bitdise, "bilir sayilan" movzulardan birini yoxlayiriq
            if len(state["asked"]) >= MIN_QUESTIONS:
                break
            spot = [c for c in state["concepts"]
                    if status.get(c) == "implied" and c not in asked_concepts and state["templates"].get(c)]
            if not spot:
                break
            spot.sort(key=lambda c: len(ancestors(c, state["prereqs"])), reverse=True)
            status.pop(spot[0])
            stack.append(spot[0])

        c = stack.pop(0)
        if status.get(c) in ("known", "implied", "weak", "weak_implied", "untested"):
            continue
        all_tpls = state["templates"].get(c, [])
        fresh = [t for t in all_tpls if t["id"] not in used] or all_tpls
        if not fresh:
            status[c] = "untested"
            continue
        # cetin sual evvelki movzulari da yoxlayir, asan sual yox (mes: eyni mexrecli toplama EKOB isteMIR)
        tpl = sorted(fresh, key=lambda t: t["difficulty"], reverse=True)[0]
        inst = build_instance(tpl["data"], seed=rng.randint(0, 10**9))
        if inst is None:
            status[c] = "untested"
            continue
        used.append(tpl["id"])
        current = {"concept": c, "template_id": tpl["id"], "difficulty": tpl["difficulty"],
                   "text": inst["text"], "options": inst["options"]}
        return {"current": current, "stack": stack, "status": status, "used_templates": used,
                "retried": retried, "done": False}

    return {"done": True, "current": None, "stack": stack, "status": status, "retried": retried}


def ask(state: DiagState):
    # burada qraf dayanir ve sagirdin cavabini gozleyir
    # diqqet: sagirde duz cavab ve misconception GETMIR
    q = state["current"]
    public = {
        "number": len(state["asked"]) + 1,
        "max": MAX_QUESTIONS,
        "concept": q["concept"],
        "text": q["text"],
        "options": [o["value"] for o in q["options"]],
    }
    answer = interrupt(public)
    return {"answer": str(answer)}


def grade(state: DiagState):
    q = state["current"]
    c = q["concept"]
    chosen = next((o for o in q["options"] if o["value"] == state["answer"]), None)
    correct = bool(chosen and chosen["correct"])

    status = dict(state["status"])
    stack = list(state["stack"])
    retried = list(state["retried"])
    confirmed = list(state["confirmed"])
    record = {
        "concept": c,
        "template_id": q["template_id"],
        "difficulty": q.get("difficulty", 1),
        "text": q["text"],
        "chosen": state["answer"],
        "correct": correct,
        "correct_value": next(o["value"] for o in q["options"] if o["correct"]),
        "misconception": chosen.get("misconception") if chosen else None,
        "points_to": chosen.get("points_to") if chosen else None,
    }

    open_below = [a for a in ancestors(c, state["prereqs"]) if status.get(a) is None]
    if correct and open_below and c not in confirmed and c not in retried:
        # bir duz cavab cox movzunu "bilir" edir, tesadufi tapmis ola biler - tesdiqleyek
        confirmed.append(c)
        stack.insert(0, c)
    elif correct:
        status[c] = "known"
        # tekrar yoxlamada duz cavab verdise, onun ucun "zeif" sayilan movzulari yeniden acmaq lazimdir
        for d in state["concepts"]:
            if status.get(d) == "weak_implied":
                still = any(status.get(a) in ("weak", "weak_implied") for a in ancestors(d, state["prereqs"]))
                if not still:
                    status.pop(d)
                    stack.append(d)
        history = state["asked"] + [record]
        hard_ok = any(a["concept"] == c and a["correct"] and a["difficulty"] >= 2 for a in history)
        if hard_ok:
            for a in ancestors(c, state["prereqs"]):
                if status.get(a) not in ("known", "weak"):
                    status[a] = "implied"
        else:
            # yalniz asan sual duz idi - evvelki movzulari ayrica yoxlamaq lazimdir
            for p in state["prereqs"].get(c, []):
                if status.get(p) is None and p not in stack:
                    stack.append(p)
    else:
        prs = state["prereqs"].get(c, [])
        pt = record["points_to"]
        # bu sehv movcud zeiflikle elaqelidirmi? (qrafda yuxarida ve ya asagida sehv var)
        wrong_before = {a["concept"] for a in state["asked"] if not a["correct"]}
        wrong_before |= {x for x, st in status.items() if st in ("weak", "weak_implied")}
        family = ancestors(c, state["prereqs"]) | {d for d in state["concepts"] if c in ancestors(d, state["prereqs"])}
        related = bool(family & wrong_before)
        is_leaf = not prs  # en asagi movzu: sehv olsa birbasa kok elan olunur
        if pt not in prs and c not in retried and (not related or is_leaf):
            # elaqesiz sehv tesadufi ola biler; en asagi movzuda ise sehvin qiymeti boyukdur
            # - her iki halda bir defe de yoxlayiriq
            retried.append(c)
            stack.insert(0, c)
        else:
            status[c] = "weak"
            # bu movzunu bilmirse, ona soykenen movzulari da bilmir - sual vermeye ehtiyac yoxdur
            for d in state["concepts"]:
                if status.get(d) is None and c in ancestors(d, state["prereqs"]):
                    status[d] = "weak_implied"
            stack = [x for x in stack if status.get(x) != "weak_implied"]
            # evvelce sehvin gosterdiyi movzuya, sonra qalanlarina enirik
            order = ([pt] if pt in prs else []) + [p for p in prs if p != pt]
            down = [p for p in order if status.get(p) is None]
            stack = down + [s for s in stack if s not in down]

    return {"status": status, "stack": stack, "retried": retried, "confirmed": confirmed,
            "asked": state["asked"] + [record], "current": None, "answer": None}


def diagnose(state: DiagState):
    status, prereqs = state["status"], state["prereqs"]
    weak_like = ("weak", "weak_implied")
    weak = [c for c in state["concepts"] if status.get(c) in weak_like]
    # kok sebeb: sualla tesdiqlenmis zeiflikdir ve evvelki movzularinda zeiflik yoxdur
    roots = [c for c in weak if status.get(c) == "weak"
             and not any(status.get(p) in weak_like for p in prereqs.get(c, []))]
    because = {c: [p for p in prereqs.get(c, []) if status.get(p) in weak_like] for c in weak if c not in roots}
    # kokun altinda yoxlanmamis movzu qalibsa, bunu demeliyik
    unchecked_below = {r: [p for p in prereqs.get(r, []) if status.get(p) in (None, "untested")] for r in roots}

    asked = state["asked"]
    wrong = [a for a in asked if not a["correct"]]
    if len(asked) < 4:
        confidence = "low"
    elif (roots and len(wrong) >= 2) or (not wrong and len(asked) >= MIN_QUESTIONS):
        confidence = "high"
    else:
        confidence = "medium"

    concept_map = {}
    for c in state["concepts"]:
        s = status.get(c)
        if c in roots:
            concept_map[c] = "root"
        elif s in weak_like:
            concept_map[c] = "weak"
        elif s in ("known", "implied"):
            concept_map[c] = "known"
        else:
            concept_map[c] = "unknown"

    diagnosis = {
        "roots": roots,
        "weak_because": because,
        "unchecked_below": {k: v for k, v in unchecked_below.items() if v},
        "concept_map": concept_map,
        "answered": len(asked),
        "correct": len(asked) - len(wrong),
        "misconceptions": [a["misconception"] for a in wrong if a["misconception"]],
        "confidence": confidence,
        # kok basqa sinifdendirse, izah ucun hansi kitabdan oldugunu bilmek lazimdir
        "meta": {c: state.get("meta", {}).get(c) for c in roots + [w for w in weak]},
    }
    return {"diagnosis": diagnosis, "done": True}


def route_after_pick(state: DiagState):
    return "diagnose" if state["done"] else "ask"


def build_graph(checkpointer):
    g = StateGraph(DiagState)
    g.add_node("plan", plan)
    g.add_node("pick", pick)
    g.add_node("ask", ask)
    g.add_node("grade", grade)
    g.add_node("diagnose", diagnose)
    g.add_edge(START, "plan")
    g.add_edge("plan", "pick")
    g.add_conditional_edges("pick", route_after_pick, ["ask", "diagnose"])
    g.add_edge("ask", "grade")
    g.add_edge("grade", "pick")
    g.add_edge("diagnose", END)
    return g.compile(checkpointer=checkpointer)
