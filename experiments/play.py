"""Testi terminalda yoxlamaq ucun (sagird ekranlari hazir olana qeder).
Isletmek: python experiments/play.py
"""
import json
import urllib.error
import urllib.request

API = "http://localhost:8010"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Xeta {e.code}: {e.read().decode()}")
    except urllib.error.URLError:
        raise SystemExit("API-ye qosulmaq olmadi (localhost:8010). docker compose up isleyir? "
                         "Yoxla: docker compose logs api --tail 30")


chapters = call("GET", "/public/chapters")  # /chapters artiq admin ucundur
chapter_id = chapters[0]["id"]
print(f"Bolme: {chapters[0]['title']}\n")

step = call("POST", "/attempts", {"nickname": "terminal_test", "chapter_id": chapter_id})
while not step["done"]:
    q = step["question"]
    print(f"[{q['number']}/{q['max']}] ({q['concept']})")
    print("  ", q["text"])
    for i, opt in enumerate(q["options"], 1):
        print(f"     {i}) {opt}")
    choice = input("   Cavab nomresi: ").strip()
    while not choice.isdigit() or not 1 <= int(choice) <= len(q["options"]):
        choice = input("   1-den " + str(len(q["options"])) + "-e qeder nomre yaz: ").strip()
    step = call("POST", f"/attempts/{step['attempt_id']}/answer",
                {"token": step["token"], "value": q["options"][int(choice) - 1]})
    fb = step["feedback"]
    if fb["correct"]:
        print("   ✓ Duzdur\n")
    else:
        print(f"   ✗ Duz cavab: {fb['correct_value']}. {fb['misconception'] or ''}\n")

d = step["diagnosis"]
print("=" * 50)
print(f"Netice: {d['correct']}/{d['answered']} duz, inam: {d['confidence']}")
print("KOK SEBEB:", ", ".join(d["roots"]) or "ciddi bosluq tapilmadi")
for weak, because in d["weak_because"].items():
    print(f"  {weak} zeifdir, cunki: {', '.join(because)}")
print("\nXerite:")
icons = {"known": "🟢", "weak": "🟡", "root": "🔴", "unknown": "⚪"}
for concept, st in d["concept_map"].items():
    print(f"  {icons[st]} {concept}")
