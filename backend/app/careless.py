"""Klassik ML: testi tesadufi basib kecen sagirdi tapir (random-click detector).

Niye lazimdir: real pilotda bir sagird 12 suali 36 saniyede bitirdi. Onun "kok sebebleri"
yanlisdir, muellim radarinda diger sagirdlerle bir sayilmamalidir.

Problem: real etiketli data azdir (10-a yaxin test). Ona gore modeli SINTETIK sagirdlerle
oyredirik (simulyator), real testlerde ise yoxlayiriq.

    docker compose exec api python -m app.careless
"""
import json
import math
import random
from pathlib import Path
from statistics import mean, median, pstdev

MODEL_PATH = Path(__file__).parent / "ml" / "careless.joblib"
REPORT_PATH = Path("/app/eval/careless_report.json")
FEATURES = ["n", "total_sec", "median_sec", "min_sec", "cv", "frac_fast", "accuracy", "acc_easy", "slope"]
FAST = 5  # 5 saniyeden tez cavab - sual oxunmayib


def features(times, correct, difficulty):
    """Bir testin xususiyyetleri: vaxt (en vacib), duzgunluk, asan suallarda duzgunluk."""
    n = len(times)
    m = mean(times)
    easy = [c for c, d in zip(correct, difficulty) if d <= 1]
    half = n // 2
    # testin ikinci yarisinda suretlenme: evvel duz-emelli, sonra "bezib" basir
    slope = (mean(times[half:]) - mean(times[:half])) / m if half else 0.0
    return {
        "n": n,
        "total_sec": sum(times),
        "median_sec": median(times),
        "min_sec": min(times),
        "cv": pstdev(times) / m if m else 0.0,
        "frac_fast": sum(t < FAST for t in times) / n,
        "accuracy": sum(correct) / n,
        "acc_easy": sum(easy) / len(easy) if easy else sum(correct) / n,
        "slope": slope,
    }


# ---------- simulyator ----------

def simulate_student(rng, kind):
    """kind: genuine (fikirlesib cavab verir), fast (cox tez, amma bilir - "dahi"),
    random (tesadufi basir), rusher (yarida bezir)."""
    n = rng.randint(5, 12)
    difficulty = [rng.choice([1, 1, 2, 2, 3]) for _ in range(n)]
    ability = rng.uniform(0.15, 0.95)  # zeif sagird de "genuine" ola biler - esas cetinlik budur
    speed = math.exp(rng.gauss(0, 0.35))  # her sagirdin oz sureti
    if kind == "fast":
        # movzunu yaxsi bilen usaq 3-6 saniyede duz cavab verir - onu tesadufi saymamaliyiq
        ability, speed = rng.uniform(0.8, 0.98), rng.uniform(0.2, 0.4)
    times, correct = [], []
    switch = rng.randint(2, n - 2) if kind == "rusher" else n
    for i, d in enumerate(difficulty):
        careless = kind == "random" or i >= switch
        if careless:
            t = math.exp(rng.gauss(math.log(3.0), 0.5)) * speed
            ok = rng.random() < 0.25  # 4 variantdan biri
        else:
            t = math.exp(rng.gauss(math.log({1: 10, 2: 17, 3: 26}[d]), 0.6)) * speed
            p = max(0.05, min(0.97, ability + (0.2 if d == 1 else 0) - (0.15 if d == 3 else 0)))
            if rng.random() < 0.1:  # bilmeyende bezen texmin edir (tez, amma tesadufi deyil)
                t *= 0.5
            ok = rng.random() < p
        times.append(max(1.0, t))
        correct.append(int(ok))
    label = int(kind in ("random", "rusher"))
    return features(times, correct, difficulty), label


def make_dataset(size, seed):
    rng = random.Random(seed)
    kinds = ["genuine"] * 5 + ["fast"] + ["random"] * 2 + ["rusher"] * 2  # 60% normal, 40% tesadufi
    rows = [simulate_student(rng, rng.choice(kinds)) for _ in range(size)]
    X = [[f[k] for k in FEATURES] for f, _ in rows]
    y = [lab for _, lab in rows]
    return X, y


# ---------- real testler (DB) ----------

def attempt_features(db, attempt):
    from sqlalchemy import select
    from .models import AttemptAnswer, QuestionTemplate
    answers = db.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)
                         .order_by(AttemptAnswer.id)).all()
    if len(answers) < 5:
        return None
    diff = {t.id: t.difficulty for t in db.scalars(select(QuestionTemplate).where(
        QuestionTemplate.id.in_([a.template_id for a in answers if a.template_id]))).all()}
    times, prev = [], attempt.started_at
    for a in answers:
        times.append(max(1.0, (a.answered_at - prev).total_seconds()))
        prev = a.answered_at
    return features(times, [int(a.correct) for a in answers], [diff.get(a.template_id, 2) for a in answers])


_model = None


def careless_score(db, attempt):
    """0..1 - tesadufi basilma ehtimali. Model yoxdursa None (sistem islemeye davam edir)."""
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            return None
        import joblib
        _model = joblib.load(MODEL_PATH)
    f = attempt_features(db, attempt)
    if f is None:
        return None
    return round(float(_model.predict_proba([[f[k] for k in FEATURES]])[0][1]), 2)


# ---------- oyretme + qiymetlendirme ----------

def train():
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X_train, y_train = make_dataset(4000, seed=1)
    X_test, y_test = make_dataset(1000, seed=2)  # ayri seed - model bunu gormeyib

    def rule(X):  # baseline: admin panelindeki "1 deqiqeden tez" qaydasi
        return [int(row[FEATURES.index("total_sec")] < 60) for row in X]

    models = {
        "Qayda (<1 dəq)": None,
        "Logistic Regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "Random Forest": RandomForestClassifier(n_estimators=200, max_depth=6, random_state=0),
    }
    report = {"train_size": len(X_train), "test_size": len(X_test), "features": FEATURES, "models": {}}
    print(f"Sintetik data: train {len(X_train)}, test {len(X_test)} (40% tesadufi)\n")
    print(f"{'Model':<22}{'Precision':>10}{'Recall':>8}{'F1':>7}   Confusion [[TN FP][FN TP]]")
    for name, model in models.items():
        if model is None:
            pred = rule(X_test)
        else:
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
        r = {"precision": round(precision_score(y_test, pred), 3), "recall": round(recall_score(y_test, pred), 3),
             "f1": round(f1_score(y_test, pred), 3), "confusion": confusion_matrix(y_test, pred).tolist()}
        report["models"][name] = r
        print(f"{name:<22}{r['precision']:>10}{r['recall']:>8}{r['f1']:>7}   {r['confusion']}")

    rf = models["Random Forest"]
    imp = sorted(zip(FEATURES, rf.feature_importances_), key=lambda x: -x[1])
    report["importance"] = {k: round(float(v), 3) for k, v in imp}
    print("\nEn vacib xususiyyetler:", ", ".join(f"{k} {v:.2f}" for k, v in imp[:5]))

    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(rf, MODEL_PATH)
    print(f"\nModel saxlandi: {MODEL_PATH}")

    # real testlerde yoxlama
    from sqlalchemy import select
    from .db import SessionLocal
    from .models import Attempt
    db = SessionLocal()
    real = []
    try:
        for a in db.scalars(select(Attempt).where(Attempt.status == "done").order_by(Attempt.id)).all():
            f = attempt_features(db, a)
            if f is None:
                continue
            p = float(rf.predict_proba([[f[k] for k in FEATURES]])[0][1])
            # kohne testlere de ehtimali yaziriq ki, radarda gorunsun
            a.diagnosis = {**a.diagnosis, "careless": round(p, 2)}
            # hesabata real lebeqleri yazmiriq (repo public-dir), yalniz terminalda gorunur
            real.append({"id": a.id, "nickname": f"sagird #{a.id}", "_shown": a.nickname, "n": f["n"], "total_sec": round(f["total_sec"]),
                         "median_sec": round(f["median_sec"], 1), "accuracy": round(f["accuracy"], 2),
                         "prob": round(p, 2)})
        db.commit()
    finally:
        db.close()
    report["real"] = real
    print(f"\nReal testler ({len(real)}):")
    print(f"{'id':>4}  {'ləqəb':<20}{'sual':>5}{'saniyə':>8}{'median':>8}{'düz%':>6}{'ehtimal':>9}")
    for r in real:
        flag = "  ⚠️ təsadüfi?" if r["prob"] >= 0.5 else ""
        print(f"{r['id']:>4}  {r.pop('_shown')[:19]:<20}{r['n']:>5}{r['total_sec']:>8}{r['median_sec']:>8}"
              f"{round(100 * r['accuracy']):>6}{r['prob']:>9}{flag}")

    if REPORT_PATH.parent.exists():
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nHesabat: data/eval/{REPORT_PATH.name}")


if __name__ == "__main__":
    train()
