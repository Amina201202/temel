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
  // daxil olubsa lebeq hesabdan gelir
  const nickname = me ? me.nickname : $("nickname").value.trim();
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
    if (me) body.student_token = me.token;
    fromHistory = false;
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
    $("map-topbar").hidden = !fromHistory;
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

const STATUS_TEXT = { closed: "✅ Bağlandı", root: "× Kök səbəb", weak: "! Zəif", known: "✓ Bilirsən", implied: "≈ Yəqin bilirsən", unknown: "Yoxlanmadı" };
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
      if ((d.closed || []).includes(r)) {
        return `<div class="good-card closed-card"><span class="label">✅ Bağlandı</span>
          <span class="name">${esc(r)}</span><p>Bu boşluğu məşqlə bağladın. Afərin! 🎉</p></div>`;
      }
      return `<div class="root-card"><span class="label">Kök səbəb</span>
        <span class="name">${esc(r)}</span><p>${why}</p>
        <button class="btn practice" type="button" data-practice="${esc(r)}">💪 Bu boşluğu bağla · 5 sual</button></div>`;
    }).join("");
  } else {
    roots.innerHTML = `<div class="good-card"><span class="name">Ciddi boşluq tapılmadı</span>
      <p>Bu bölmənin mövzularını yaxşı bilirsən.</p></div>`;
  }

  roots.querySelectorAll("[data-practice]").forEach((b) => (b.onclick = () => startPractice(b.dataset.practice)));

  // movzulari sirala: kok, zeif, bilir, yoxlanmadi
  const order = { root: 0, closed: 1, weak: 2, known: 3, implied: 4, unknown: 5 };
  const implied = new Set(d.implied || []);
  let hidden = 0;
  const items = Object.entries(d.concept_map)
    .map(([name, st]) => [name, (d.closed || []).includes(name) ? "closed" : st === "known" && implied.has(name) ? "implied" : st])
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

$("plan-btn").onclick = () => { renderPlan(lastDiagnosis); show("screen-plan"); prepareTelegram(); };

// Telegram linkini evvelceden aliriq ki, duyme adi link olsun (popup bloklanmasin)
async function prepareTelegram() {
  const btn = $("tg-btn");
  btn.hidden = true;
  $("tg-hint").hidden = true;
  if (!attempt) return;
  try {
    const res = await api("POST", `/attempts/${attempt.attempt_id}/telegram`, { token: attempt.token });
    btn.href = res.url;
    btn.hidden = false;
    btn.onclick = () => { $("tg-hint").hidden = false; };
  } catch (e) {
    // bot qosulmayibsa duymeni umumiyyetle gostermirik
  }
}
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
      { title: "Gün 3 · Yoxlama", tasks: ["Testi yenidən keç", `${root} indi “Bilirsən” çıxırmı, bax`] },
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

// ---------- 4b. boslugu bagla: mesq ----------
let prPending = null;

async function startPractice(concept) {
  try {
    const res = await api("POST", `/attempts/${attempt.attempt_id}/practice/start`, { token: attempt.token, concept });
    $("pr-result").hidden = true;
    $("pr-body").hidden = false;
    renderPractice(res.question);
    show("screen-practice");
  } catch (e) {
    alert(e.message);
  }
}

function renderPractice(q) {
  $("pr-counter").textContent = `${q.number} / ${q.total}`;
  $("pr-progress").style.width = `${(q.number - 1) / q.total * 100}%`;
  $("pr-concept").textContent = q.concept;
  $("pr-text").innerHTML = mathHtml(q.text);
  $("pr-feedback").hidden = true;
  $("pr-next").hidden = true;
  const box = $("pr-options");
  box.innerHTML = "";
  q.options.forEach((value, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "option";
    btn.dataset.value = value;
    btn.innerHTML = `<span class="letter">${"ABCD"[i] || i + 1}</span><span>${mathHtml(value)}</span>`;
    btn.onclick = () => practiceAnswer(value, btn);
    box.appendChild(btn);
  });
}

async function practiceAnswer(value, btn) {
  const all = document.querySelectorAll("#pr-options .option");
  all.forEach((b) => (b.disabled = true));
  btn.classList.add("picked");
  try {
    const r = await api("POST", `/attempts/${attempt.attempt_id}/practice/answer`, { token: attempt.token, value });
    all.forEach((b) => {
      b.classList.remove("picked");
      if (b.dataset.value === r.correct_value) b.classList.add("right");
      else if (b.dataset.value === value) b.classList.add("wrong");
    });
    const fb = $("pr-feedback");
    if (r.correct) { fb.className = "feedback ok"; fb.innerHTML = `<b>✓ Düzdür!</b>`; }
    else {
      fb.className = "feedback no";
      fb.innerHTML = `<b>! Düz cavab: ${mathHtml(r.correct_value)}</b><span>${esc(r.misconception || "")}</span>`;
    }
    fb.hidden = false;
    prPending = r;
    $("pr-next").textContent = r.next ? "Növbəti sual →" : "Nəticəyə bax →";
    $("pr-next").hidden = false;
  } catch (e) {
    all.forEach((b) => (b.disabled = false));
    alert(e.message);
  }
}

$("pr-next").onclick = () => {
  const r = prPending;
  if (r.next) { renderPractice(r.next); return; }
  // netice
  const res = r.result;
  $("pr-progress").style.width = "100%";
  $("pr-body").hidden = true;
  $("pr-next").hidden = true;
  const box = $("pr-result");
  if (res.passed) {
    lastDiagnosis.closed = res.closed;
    box.innerHTML = `<div class="pr-emoji">🏆</div><h2>Boşluq bağlandı!</h2>
      <p><b>${esc(res.concept)}</b> · ${res.right}/${res.total} düz</p>
      <button class="btn primary" type="button" id="pr-back">Xəritəmə bax →</button>`;
    confetti();
  } else {
    box.innerHTML = `<div class="pr-emoji">💪</div><h2>Az qaldı!</h2>
      <p>${res.right}/${res.total} düz. Bağlamaq üçün ${res.total >= 5 ? 4 : res.total - 1} lazımdır.<br>İzahı bir də oxu və yenidən cəhd et.</p>
      <button class="btn primary" type="button" id="pr-again">Yenidən cəhd et</button>
      <button class="btn secondary" type="button" id="pr-back">Xəritəyə qayıt</button>`;
    $("pr-again").onclick = () => startPractice(res.concept);
  }
  box.hidden = false;
  $("pr-back").onclick = () => { renderMap(lastDiagnosis); show("screen-map"); };
};

$("pr-quit").onclick = () => { renderMap(lastDiagnosis); show("screen-map"); };

// kicik konfeti - kitabxanasiz
function confetti() {
  const colors = ["#3D4BE0", "#FFC857", "#3FA57A", "#E8505B", "#8B5CF6"];
  for (let i = 0; i < 70; i++) {
    const p = document.createElement("i");
    p.className = "confetti";
    p.style.left = `${Math.random() * 100}vw`;
    p.style.background = colors[i % colors.length];
    p.style.animationDelay = `${Math.random() * 0.6}s`;
    p.style.animationDuration = `${1.6 + Math.random() * 1.4}s`;
    p.style.transform = `rotate(${Math.random() * 360}deg)`;
    document.body.appendChild(p);
    setTimeout(() => p.remove(), 3600);
  }
}

// ---------- 5. sagird girisi + menim sehifem ----------
let fromHistory = false;
const SUFFIX = { 5: "ci", 6: "cı", 7: "ci", 8: "ci", 9: "cu" };
const ME_KEY = "radix_student";
let me = null;  // {token, nickname}
try { me = JSON.parse(localStorage.getItem(ME_KEY)); } catch (e) { me = null; }

function initials(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

// start ekranindaki hesab zolagi
function renderAccount(stats) {
  $("acct-guest").hidden = !!me;
  $("acct-user").hidden = !me;
  $("nickname-field").hidden = !!me;
  if (!me) return;
  $("acct-avatar").textContent = initials(me.nickname);
  $("acct-hello").textContent = `Salam, ${me.nickname} 👋`;
  $("acct-sub").textContent = stats ? `${stats.tests} test · Mənim səhifəm` : "Mənim səhifəm";
}

function logout(silent) {
  if (me && !silent) api("POST", "/students/logout").catch(() => {});
  me = null;
  try { localStorage.removeItem(ME_KEY); } catch (e) { /* */ }
  renderAccount();
}

async function meApi(method, path) {
  // sagird tokeni ile sorgu (api() token gondermir)
  const resp = await fetch(API + path, {
    method, headers: { Authorization: `Bearer ${me.token}`, "ngrok-skip-browser-warning": "1" },
  });
  if (resp.status === 401) { logout(true); show("screen-login"); throw new Error("Yenidən daxil ol"); }
  if (!resp.ok) throw new Error("Xəta baş verdi");
  return resp.json();
}

$("acct-guest").onclick = () => {
  $("l-nickname").value = $("nickname").value.trim();
  $("l-pin").value = "";
  $("login-error").hidden = true;
  show("screen-login");
};
$("acct-user").onclick = () => openMe();
$("login-back").onclick = () => show("screen-start");
$("me-back").onclick = () => show("screen-start");
$("me-new").onclick = () => show("screen-start");
$("back-history-btn").onclick = () => openMe();
$("logout-btn").onclick = () => { logout(); show("screen-start"); };

$("login-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const err = $("login-error");
  err.hidden = true;
  const nickname = $("l-nickname").value.trim();
  const pin = $("l-pin").value.trim();
  if (nickname.length < 2 || !/^\d{4}$/.test(pin)) {
    err.textContent = "Ləqəbi və 4 rəqəmli PIN-i yaz.";
    err.hidden = false;
    return;
  }
  const btn = $("login-submit");
  btn.disabled = true;
  try {
    me = await api("POST", "/students/login", { nickname, pin });
    try { localStorage.setItem(ME_KEY, JSON.stringify(me)); } catch (e) { /* */ }
    renderAccount();
    await openMe();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
};

async function openMe() {
  if (!me) { show("screen-login"); return; }
  const res = await meApi("GET", "/students/me");
  renderAccount(res.stats);
  $("me-avatar").textContent = initials(res.nickname);
  $("me-name").textContent = res.nickname;
  $("ms-tests").textContent = res.stats.tests;
  $("ms-closed").textContent = res.stats.closed;
  $("ms-last").textContent = res.stats.last_root || "—";
  renderMeList(res.attempts);
  show("screen-me");
}

function renderMeList(list) {
  const box = $("me-list");
  if (!list.length) {
    box.innerHTML = `<div class="me-empty">Hələ test yoxdur.<br>İlk testini keç, nəticə burada görünəcək.</div>`;
    return;
  }
  box.innerHTML = list.map((a, i) => {
    let kind = "gap", body;
    if (a.status !== "done") { kind = "wip"; body = `<span class="muted">Yarımçıq qalıb, davam et</span>`; }
    else if (a.roots.length) {
      body = a.roots.map((r) => (a.closed || []).includes(r)
        ? `<span class="hchip ok">✅ ${esc(r)}</span>` : `<span class="hchip">${esc(r)}</span>`).join("");
      if (a.roots.every((r) => (a.closed || []).includes(r))) kind = "ok";
    } else { kind = "ok"; body = `<span class="hchip ok">Boşluq tapılmadı 🎉</span>`; }
    let prog = "";
    if (a.progress && a.progress.closed.length) prog = `<p class="hprog ok">✅ Bağlandı: ${a.progress.closed.map(esc).join(", ")}</p>`;
    else if (a.progress && a.progress.still.length) prog = `<p class="hprog">⏳ Hələ də boşluq: ${a.progress.still.map(esc).join(", ")}</p>`;
    const score = a.status === "done" ? `<span class="hscore">${a.correct}/${a.answered}</span>` : "";
    const warn = a.careless ? ` · ⚠️ çox tez basılıb` : "";
    const grade = a.grade ? ` · ${a.grade}-${SUFFIX[a.grade] || "ci"} sinif` : "";
    // baglanmamis bosluq varsa - birbasa mesqe kecid
    const open = a.status === "done" ? a.roots.filter((r) => !(a.closed || []).includes(r)) : [];
    const fix = open.length ? `<span class="hfix" data-fix="${i}">💪 ${esc(open[0])} boşluğunu bağla →</span>` : "";
    return `<div class="hitem ${kind}" data-i="${i}" role="button" tabindex="0">
      <div class="hrow"><span class="hmeta">${esc(a.date)}${warn}</span>${score}</div>
      <b class="htitle">${esc(a.chapter)}<span class="muted">${grade}</span></b>
      <div>${body}</div>${prog}${fix}</div>`;
  }).join("");
  box.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => openHistory(list[Number(b.dataset.i)])));
  box.querySelectorAll("[data-fix]").forEach((b) => (b.onclick = async (ev) => {
    ev.stopPropagation();
    const a = list[Number(b.dataset.fix)];
    await openHistory(a);
    startPractice(a.roots.find((r) => !(a.closed || []).includes(r)));
  }));
}

async function openHistory(a) {
  attempt = { attempt_id: a.attempt_id, token: a.token };
  saveAttempt();
  fromHistory = true;
  renderStep(await api("GET", `/attempts/${a.attempt_id}?token=${encodeURIComponent(a.token)}`));
}

renderAccount();
if (me) meApi("GET", "/students/me").then((r) => renderAccount(r.stats)).catch(() => {});

$("restart-btn").onclick = () => { clearAttempt(); attempt = null; show("screen-start"); };

// ---------- basla: yarimciq test varsa davam et ----------

// ---------- kod yazilanda sinfi gosteririk ----------
let codeTimer = null;

async function checkCode() {
  const code = $("join-code").value.trim();
  const info = $("code-info");
  if (code.length < 4) {
    info.hidden = true;
    $("chapter-field").hidden = false;
    return;
  }
  try {
    const s = await api("GET", `/public/sessions/${encodeURIComponent(code)}`);
    info.className = "code-info ok";
    info.textContent = `✓ ${s.class_name} sinfi · ${s.chapter_title}${s.grade ? ` (${gradeLabel(s.grade)} sinif)` : ""}`;
    $("chapter-field").hidden = true;  // movzunu muellim secib
  } catch (e) {
    info.className = "code-info bad";
    info.textContent = "✗ Bu kodla aktiv sessiya tapılmadı. Kodu müəllimdən yoxla.";
    $("chapter-field").hidden = false;
  }
  info.hidden = false;
}

$("join-code").addEventListener("input", () => {
  clearTimeout(codeTimer);
  codeTimer = setTimeout(checkCode, 350);  // her herfde sorgu getmesin
});

(async function init() {
  loadChapters();
  // QR-dan gelende kod linkde olur: /app/?code=4821
  const code = new URLSearchParams(location.search).get("code");
  if (code) {
    $("join-code").value = code;
    $("chapter-field").hidden = true;
    checkCode();
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
