// Temel - sagird tetbiqi. Framework yoxdur, sade JS.
const API = "";  // eyni serverdir
const STORE_KEY = "temel_attempt";

const $ = (id) => document.getElementById(id);
// sinif sekilcesi: 5-ci, 6-ci, 9-cu
const gradeLabel = (g) => `${g}-${({ 1: "ci", 2: "ci", 3: "cü", 4: "cü", 5: "ci", 6: "cı", 7: "ci", 8: "ci", 9: "cu", 10: "cu", 11: "ci" })[g] || "ci"}`;
let selectedChapter = null;
let attempt = null;       // {attempt_id, token}
let pendingStep = null;   // cavabdan sonra gelen novbeti addim
let lastDiagnosis = null;

// ---------- komekci funksiyalar ----------

function show(screen) {
  document.querySelectorAll(".screen").forEach((s) => (s.hidden = s.id !== screen));
  window.scrollTo(0, 0);
}

function esc(text) {
  // AI-in yazdigi metni html kimi yox, metn kimi gosteririk (XSS olmasin)
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function frac(n, d) {
  return `<span class="frac"><span>${n}</span><span>${d}</span></span>`;
}

function mathHtml(text) {
  // "2 1/3" -> qarisiq eded, "3/4" -> ust-uste kesr
  return esc(text)
    .replace(/(\d+)\s+(\d+)\/(\d+)/g, (m, w, n, d) => `<span class="mixed">${w}${frac(n, d)}</span>`)
    .replace(/(\d+)\/(\d+)/g, (m, n, d) => frac(n, d));
}

async function api(method, path, body) {
  const resp = await fetch(API + path, {
    method,
    // ngrok-un pulsuz planinda xeberdarliq sehifesi API sorgularina mane olmasin
    headers: body ? { "Content-Type": "application/json", "ngrok-skip-browser-warning": "1" } : { "ngrok-skip-browser-warning": "1" },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* bos cavab */ }
  if (!resp.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : "Xəta baş verdi, yenidən cəhd et.";
    throw new Error(detail);
  }
  return data;
}

function saveAttempt() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(attempt)); } catch (e) { /* private rejim */ }
}
function loadAttempt() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)); } catch (e) { return null; }
}
function clearAttempt() {
  try { localStorage.removeItem(STORE_KEY); } catch (e) { /* */ }
}

// ---------- 1. giris ----------

async function loadChapters() {
  const box = $("chapter-list");
  try {
    const chapters = await api("GET", "/public/chapters");
    if (!chapters.length) {
      box.innerHTML = `<p class="muted">Hələ hazır test yoxdur. Müəllimdən kod istə.</p>`;
      return;
    }
    box.innerHTML = "";
    chapters.forEach((ch, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice";
      btn.innerHTML = `<span><span class="title">${esc(ch.title)}</span>
        <span class="sub">${gradeLabel(ch.grade)} sinif</span></span><span class="radio"></span>`;
      btn.onclick = () => {
        selectedChapter = ch.id;
        box.querySelectorAll(".choice").forEach((b) => b.classList.toggle("selected", b === btn));
      };
      box.appendChild(btn);
      if (i === 0) btn.click();
    });
  } catch (e) {
    box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

$("start-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const nickname = $("nickname").value.trim();
  const code = $("join-code").value.trim();
  const err = $("start-error");
  err.hidden = true;

  if (nickname.length < 2) {
    err.textContent = "Ləqəb ən azı 2 simvol olsun.";
    err.hidden = false;
    return;
  }
  if (!code && !selectedChapter) {
    err.textContent = "Sinif kodunu yaz və ya mövzu seç.";
    err.hidden = false;
    return;
  }

  const btn = $("start-btn");
  btn.disabled = true;
  btn.textContent = "Hazırlanır...";
  try {
    const body = code ? { nickname, join_code: code } : { nickname, chapter_id: selectedChapter };
    const step = await api("POST", "/attempts", body);
    attempt = { attempt_id: step.attempt_id, token: step.token };
    saveAttempt();
    renderStep(step);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Testə başla →";
  }
};

// ---------- 2. test ----------

function renderStep(step) {
  if (step.done) {
    lastDiagnosis = step.diagnosis;
    renderMap(step.diagnosis);
    show("screen-map");
    loadExplanation(step.diagnosis);
    return;
  }
  renderQuestion(step.question);
  show("screen-test");
}

function renderQuestion(q) {
  $("q-counter").textContent = `Sual ${q.number}`;
  $("q-progress").style.width = `${Math.min(100, (q.number - 1) / q.max * 100)}%`;
  $("q-concept").textContent = q.concept;
  $("q-text").innerHTML = mathHtml(q.text);
  $("q-feedback").hidden = true;
  $("next-btn").hidden = true;
  $("wait-btn").hidden = false;

  const box = $("q-options");
  box.innerHTML = "";
  q.options.forEach((value, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "option";
    btn.dataset.value = value;
    btn.setAttribute("aria-label", `Variant ${"ABCD"[i] || i + 1}: ${value}`);
    btn.innerHTML = `<span class="letter">${"ABCD"[i] || i + 1}</span><span>${mathHtml(value)}</span>`;
    btn.onclick = () => answer(value, btn);
    box.appendChild(btn);
  });
}

async function answer(value, btn) {
  const all = document.querySelectorAll(".option");
  all.forEach((b) => (b.disabled = true));
  btn.classList.add("picked");
  try {
    const step = await api("POST", `/attempts/${attempt.attempt_id}/answer`, { token: attempt.token, value });
    showFeedback(step.feedback, value);
    pendingStep = step;
  } catch (e) {
    all.forEach((b) => (b.disabled = false));
    btn.classList.remove("picked");
    const fb = $("q-feedback");
    fb.className = "feedback no";
    fb.innerHTML = `<b>Göndərilmədi</b><span>${esc(e.message)}</span>`;
    fb.hidden = false;
  }
}

function showFeedback(fb, chosen) {
  document.querySelectorAll(".option").forEach((b) => {
    b.classList.remove("picked");
    if (b.dataset.value === fb.correct_value) b.classList.add("right");
    else if (b.dataset.value === chosen) b.classList.add("wrong");
  });
  const box = $("q-feedback");
  if (fb.correct) {
    box.className = "feedback ok";
    box.innerHTML = `<b>✓ Düzdür</b>`;
  } else {
    box.className = "feedback no";
    box.innerHTML = `<b>! Bu səhv bir şey deyir</b><span>${esc(fb.misconception || "Düz cavab: " + fb.correct_value)}</span>`;
  }
  box.hidden = false;
  $("wait-btn").hidden = true;
  $("next-btn").hidden = false;
}

$("next-btn").onclick = () => pendingStep && renderStep(pendingStep);

$("quit-btn").onclick = () => {
  if (window.confirm("Testdən çıxırsan? Sonra yenidən başlamalı olacaqsan.")) {
    clearAttempt();
    show("screen-start");
  }
};

// ---------- 3. bilik xeritesi ----------

const STATUS_TEXT = { root: "× Kök səbəb", weak: "! Zəif", known: "✓ Bilirsən", implied: "≈ Yəqin bilirsən", unknown: "Yoxlanmadı" };
const FOREIGN = /\(\d+-c[iıu] sinif\)$/;

function renderMap(d) {
  $("map-summary").textContent = `${d.answered} sualdan ${d.correct}-i düz`;

  const roots = $("map-roots");
  if (d.roots.length) {
    roots.innerHTML = d.roots.map((r) => {
      // bu kokden asili olan zeif movzular
      const deps = Object.entries(d.weak_because).filter(([, b]) => b.includes(r)).map(([w]) => w);
      const why = deps.length
        ? `${deps.map(esc).join(", ")} mövzusunda səhv edirsən, çünki əsas problem <b>${esc(r)}</b> mövzusundadır.`
        : `Bu mövzunun özündə boşluq var. Əvvəlki mövzuları isə bilirsən.`;
      return `<div class="root-card"><span class="label">Kök səbəb</span>
        <span class="name">${esc(r)}</span><p>${why}</p></div>`;
    }).join("");
  } else {
    roots.innerHTML = `<div class="good-card"><span class="name">Ciddi boşluq tapılmadı</span>
      <p>Bu bölmənin mövzularını yaxşı bilirsən.</p></div>`;
  }

  // movzulari sirala: kok, zeif, bilir, yoxlanmadi
  const order = { root: 0, weak: 1, known: 2, implied: 3, unknown: 4 };
  const implied = new Set(d.implied || []);
  let hidden = 0;
  const items = Object.entries(d.concept_map)
    .map(([name, st]) => [name, st === "known" && implied.has(name) ? "implied" : st])
    // evvelki siniflerin yoxlanmamis movzularini gizledirik, siyahi uzanmasin
    .filter(([name, st]) => {
      if (FOREIGN.test(name) && (st === "implied" || st === "unknown")) { hidden += 1; return false; }
      return true;
    })
    .sort((a, b) => order[a[1]] - order[b[1]]);
  const more = hidden
    ? `<p class="muted map-more">+ əvvəlki siniflərdən ${hidden} mövzu: düz cavablarına görə yəqin ki onları bilirsən.</p>` : "";
  $("map-list").innerHTML = items.map(([name, st]) => {
    const because = d.weak_because[name];
    const sub = st === "weak" && because ? `<div class="c-sub">çünki: ${because.map(esc).join(", ")}</div>` : "";
    return `<div class="concept ${st}"><div><div class="c-name">${esc(name)}</div>${sub}</div>
      <span class="pill ${st}">${STATUS_TEXT[st]}</span></div>`;
  }).join("") + more;
}

// ---------- sesli izah ----------
let listenAudio = null;

async function toggleListen() {
  const btn = $("listen-btn");
  const err = $("listen-err");
  err.hidden = true;
  if (listenAudio && !listenAudio.paused) { listenAudio.pause(); btn.textContent = "▶ Davam et"; return; }
  if (listenAudio) { listenAudio.play(); btn.textContent = "⏸ Dayandır"; return; }
  btn.disabled = true;
  btn.textContent = "⏳ Səs hazırlanır...";
  try {
    const resp = await fetch(`/attempts/${attempt.attempt_id}/explanation/audio`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "1" },
      body: JSON.stringify({ token: attempt.token }),
    });
    if (!resp.ok) {
      const j = await resp.json().catch(() => ({}));
      throw new Error(j.detail || "Səsli izah hazırlana bilmədi");
    }
    listenAudio = new Audio(URL.createObjectURL(await resp.blob()));
    listenAudio.onended = () => { btn.textContent = "🔊 Yenidən dinlə"; };
    await listenAudio.play();
    btn.textContent = "⏸ Dayandır";
  } catch (e) {
    listenAudio = null;
    btn.textContent = "🔊 Yenidən cəhd et";
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

async function loadExplanation(d) {
  const box = $("explain");
  // evvelki testin sesini dayandiririq
  if (listenAudio) { listenAudio.pause(); listenAudio = null; }
  // evvelki testden qalan sual formasini ve cavablari temizleyirik
  $("ask-form").hidden = true;
  $("ask-answers").innerHTML = "";
  $("ask-topic").textContent = "";
  if (!d.roots.length || !attempt) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = `<span class="ai">AI sənin üçün izah yazır...</span>
    <div class="skeleton" style="width:80%"></div><div class="skeleton"></div><div class="skeleton" style="width:60%"></div>`;
  try {
    const res = await api("POST", `/attempts/${attempt.attempt_id}/explanation`, { token: attempt.token });
    const e = res.explanation;
    if (!e) { box.hidden = true; return; }
    box.innerHTML = `<span class="ai">Sənə özəl izah</span>
      <h3>${esc(e.headline)}</h3>
      <button id="listen-btn" class="listen" type="button">🔊 İzahı dinlə</button>
      <span id="listen-err" class="listen-err" hidden></span>
      <p>${mathHtml(e.why)}</p>
      <div class="box"><b>Qayda</b>${mathHtml(e.rule)}</div>
      <div class="box"><b>Nümunə</b>${mathHtml(e.example)}</div>
      <div class="tip">💡 ${mathHtml(e.tip)}</div>
      ${e.source_page ? `<span class="src">Mənbə: Riyaziyyat ${e.source_grade || 5}, səh. ${e.source_page}</span>` : ""}`;
    $("listen-btn").onclick = toggleListen;
    $("ask-topic").textContent = `(yalnız «${d.roots[0]}» haqqında)`;
    $("ask-form").hidden = false;
  } catch (err) {
    box.innerHTML = `<span class="ai">İzah</span><p class="muted">${esc(err.message)}</p>
      <button class="retry" type="button">Yenidən cəhd et</button>`;
    box.querySelector(".retry").onclick = () => loadExplanation(d);
  }
}

$("ask-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const input = $("ask-input");
  const q = input.value.trim();
  if (!q || !attempt) return;
  const box = $("ask-answers");
  const qEl = document.createElement("div");
  qEl.className = "qa q";
  qEl.textContent = q;
  const aEl = document.createElement("div");
  aEl.className = "qa a";
  aEl.innerHTML = `<div class="skeleton" style="width:70%"></div>`;
  box.prepend(aEl);
  box.prepend(qEl);
  input.value = "";
  try {
    const r = await api("POST", `/attempts/${attempt.attempt_id}/ask`, { token: attempt.token, question: q });
    aEl.innerHTML = mathHtml(r.answer) +
      `<small>${r.source_page ? `Mənbə: səh. ${r.source_page} · ` : ""}${r.left} sual qaldı</small>`;
  } catch (e) {
    aEl.className = "qa blocked";
    aEl.textContent = e.message;
  }
};

$("plan-btn").onclick = () => { renderPlan(lastDiagnosis); show("screen-plan"); };
$("back-map-btn").onclick = () => show("screen-map");

// ---------- 4. plan ----------

function buildPlan(d) {
  if (!d.roots.length) {
    return {
      goal: "Biliyini möhkəmləndir və növbəti mövzuya keç",
      days: [
        { title: "Gün 1 · Çətin tapşırıqlar", tasks: ["Bölmənin sonundakı çətin məsələlərdən 5-ni həll et"] },
        { title: "Gün 2 · Növbəti mövzu", tasks: ["Dərslikdə növbəti bölməyə başla"] },
        { title: "Gün 3 · Yoxlama", tasks: ["Testi yenidən keç"] },
      ],
    };
  }
  const root = d.roots[0];
  const deps = Object.entries(d.weak_because).filter(([, b]) => b.includes(root)).map(([w]) => w);
  const next = deps[0];
  return {
    goal: `Hədəf: ${root} boşluğunu bağlamaq${next ? `, sonra ${next} mövzusuna qayıtmaq` : ""}`,
    days: [
      { title: `Gün 1 · ${root}`, tasks: [`Dərslikdə ${root} izahını yenidən oxu`, `${root}: 5 asan məşq həll et`] },
      { title: `Gün 2 · ${next || root}`, tasks: next
          ? [`${next}: dərslikdəki nümunələrə bax`, `${next}: 5 məşq həll et`]
          : [`${root}: 5 çətin məşq həll et`, "Səhv etdiyin məşqləri yenidən yoxla"] },
      { title: "Gün 3 · Yoxlama", tasks: ["Testi yenidən keç", "Xəritənin yaşıllaşdığına bax"] },
    ],
  };
}

function renderPlan(d) {
  const plan = buildPlan(d);
  const key = `temel_plan_${attempt ? attempt.attempt_id : 0}`;
  let done = {};
  try { done = JSON.parse(localStorage.getItem(key)) || {}; } catch (e) { done = {}; }

  $("plan-goal").textContent = plan.goal;
  const total = plan.days.reduce((n, day) => n + day.tasks.length, 0);
  const box = $("plan-days");
  box.innerHTML = "";
  let count = 0;

  plan.days.forEach((day, di) => {
    const el = document.createElement("div");
    el.className = "day" + (di === 0 ? " today" : "");
    el.innerHTML = `<div class="day-head"><span>${esc(day.title)}</span>${di === 0 ? '<span class="tag">Bu gün</span>' : ""}</div>`;
    day.tasks.forEach((task, ti) => {
      const id = `t${di}_${ti}`;
      if (done[id]) count++;
      const label = document.createElement("label");
      label.className = "task" + (done[id] ? " done" : "");
      label.innerHTML = `<input type="checkbox" ${done[id] ? "checked" : ""}><span>${esc(task)}</span>`;
      label.querySelector("input").onchange = (ev) => {
        done[id] = ev.target.checked;
        try { localStorage.setItem(key, JSON.stringify(done)); } catch (e) { /* */ }
        renderPlan(d);
      };
      el.appendChild(label);
    });
    box.appendChild(el);
  });
  $("plan-done").textContent = `${count} / ${total} tamamlandı`;
}

$("restart-btn").onclick = () => { clearAttempt(); attempt = null; show("screen-start"); };

// ---------- basla: yarimciq test varsa davam et ----------

(async function init() {
  loadChapters();
  // QR-dan gelende kod linkde olur: /app/?code=4821
  const code = new URLSearchParams(location.search).get("code");
  if (code) {
    $("join-code").value = code;
    $("chapter-field").hidden = true;
  }
  const saved = loadAttempt();
  if (saved) {
    try {
      const step = await api("GET", `/attempts/${saved.attempt_id}?token=${encodeURIComponent(saved.token)}`);
      attempt = saved;
      renderStep(step);
      return;
    } catch (e) {
      clearAttempt();
    }
  }
  show("screen-start");
})();


// ---------- PWA: tetbiq kimi qurasdirma ----------
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

let installEvent = null;
const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;

// android/chrome: brauzer icaze verende duymeni gosteririk
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installEvent = e;
  $("install-btn").hidden = false;
});

$("install-btn").onclick = async () => {
  if (!installEvent) return;
  installEvent.prompt();
  await installEvent.userChoice;
  installEvent = null;
  $("install-btn").hidden = true;
};

window.addEventListener("appinstalled", () => { $("install-btn").hidden = true; });

// iphone-da bu hadise yoxdur, ona gore qisa izah gosteririk
if (/iphone|ipad|ipod/i.test(navigator.userAgent) && !standalone) {
  $("ios-hint").hidden = false;
}
