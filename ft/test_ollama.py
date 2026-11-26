"""Ollama-daki temel-guard modelini yoxlayir (API ile eyni yol: OpenAI-uygun endpoint)."""
import json
import time
import urllib.request

URL = "http://localhost:11434/v1/chat/completions"
SYSTEM = json.loads(open("data/eval/ft/test.jsonl", encoding="utf-8").readline())["messages"][0]["content"]

for q in ["ƏKOB-u necə tapım?", "Başa düşmədim, daha sadə izah et", "Messi yoxsa Ronaldo?", "Salam necəsən?"]:
    body = {"model": "temel-guard", "temperature": 0, "max_tokens": 3, "messages": [
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Mövzu: ƏKOB\nSual: {q}"}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        out = json.loads(urllib.request.urlopen(req, timeout=60).read())
        print(f"{out['choices'][0]['message']['content']!r:8} {1000 * (time.time() - t0):5.0f} ms  {q}")
    except urllib.error.HTTPError as e:
        print("XETA:", e.code, e.read().decode()[:300])
        break
