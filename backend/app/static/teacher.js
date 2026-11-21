// radarda butun movzular ya yalniz vaciblar
let showAllConcepts = false;

// Temel - muellim paneli
const TOKEN_KEY = "temel_teacher_token";
const $ = (id) => document.getElementById(id);
// sinif sekilcesi: 5-ci, 6-ci, 9-cu
const gradeLabel = (g) => `${g}-${({ 1: "ci", 2: "ci", 3: "cü", 4: "cü", 5: "ci", 6: "cı", 7: "ci", 8: "ci", 9: "cu", 10: "cu", 11: "ci" })[g] || "ci"}`;
let token = null;
let currentSession = null;
let pollTimer = null;

function esc(t) {
  return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(method, path, body) {
  const headers = { "ngrok-skip-browser-warning": "1" };  // ngrok xeberdarliq sehifesi ucun
  if (body) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* */ }
  if (resp.status === 401 && path !== "/teacher/login") { logout(); throw new Error("Giriş vaxtı bitib"); }
  if (!resp.ok) throw new Error(data && typeof data.detail === "string" ? data.detail : "Xəta baş verdi");
  return data;
}

function view(name) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  if (name !== "session") stopPolling();
}

// ---------- giris ----------

$("login-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const err = $("login-error");
  err.hidden = true;
  try {
    const res = await api("POST", "/teacher/login", { username: $("username").value, password: $("password").value });
    token = res.token;
    try { localStorage.setItem(TOKEN_KEY, token); } catch (e) { /* */ }
    $("password").value = "";
    await openHome();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
};

function logout() {
  if (token) fetch("/teacher/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  token = null;
  try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* */ }
  $("who").hidden = true;
  view("login");
}
$("logout-btn").onclick = logout;

// ---------- sessiyalar ----------

async function openHome() {
  const me = await api("GET", "/teacher/me");
  $("who-name").textContent = me.name;
  $("who").hidden = false;

  const chapters = await api("GET", "/public/chapters");
  $("chapter-select").innerHTML = chapters.length
    ? chapters.map((c) => `<option value="${c.id}">${esc(c.title)} · ${gradeLabel(c.grade)} sinif</option>`).join("")
    : `<option value="">Hazır mövzu yoxdur</option>`;

  const sessions = await api("GET", "/teacher/sessions");
  $("session-list").innerHTML = sessions.length ? sessions.map((s) => `
    <div class="card session-row">
      <div class="meta"><b>${esc(s.class_name)} · ${esc(s.chapter_title)}</b>
        <span>Kod ${esc(s.join_code)} · ${s.joined} qoşuldu · ${s.done} bitirdi · ${new Date(s.created_at).toLocaleString("az")}</span></div>
      <div class="row gap"><span class="badge ${s.active ? "on" : "off"}">${s.active ? "Aktiv" : "Bağlı"}</span>
        <button class="btn ghost small" data-open="${s.id}">Radara bax →</button></div>
    </div>`).join("") : `<div class="empty">Hələ sessiya yoxdur. Yuxarıdan birini aç.</div>`;
  document.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openSession(Number(b.dataset.open))));
  view("home");
  loadOverview().catch(() => {});
}

// ---------- umumi baxis ----------

async function loadOverview() {
  const o = await api("GET", "/teacher/overview");
  $("overview").hidden = !o.sessions;
  if (!o.sessions) return;
  $("ov-sessions").textContent = o.sessions;
  $("ov-students").textContent = o.students;
  $("ov-done").textContent = o.done;
  $("ov-nogap").textContent = o.no_gap;

  const max = Math.max(1, ...o.top_roots.map((r) => r.count));
  $("ov-roots").innerHTML = o.top_roots.length ? o.top_roots.map((r) => `
    <div class="bar-row"><div class="label"><b>${esc(r.concept)}</b><span>${r.count} şagird · ${r.classes.map(esc).join(", ")}</span></div>
      <div class="track"><i class="root" style="width:${(r.count / max) * 100}%"></i></div></div>`).join("")
    : `<div class="empty">Hələ kök səbəb tapılmayıb.</div>`;

  $("ov-classes").innerHTML = o.classes.map((c) => `
    <tr><td><b>${esc(c.class_name)}</b><small>${c.chapters.map(esc).join(", ")}</small></td>
      <td>${c.done}/${c.students}</td>
      <td>${c.accuracy === null ? "—" : c.accuracy + "%"}</td>
      <td>${c.top_root ? `<span class="chip">${esc(c.top_root)}</span>` : `<span class="chip ok">Boşluq yoxdur</span>`}</td></tr>`).join("");
}

// Excel ucun CSV: token header-de getdiyi ucun adi link isletmirik
$("export-btn").onclick = async () => {
  const btn = $("export-btn");
  btn.disabled = true;
  try {
    const resp = await fetch("/teacher/export.csv", {
      headers: { Authorization: `Bearer ${token}`, "ngrok-skip-browser-warning": "1" },
    });
    if (!resp.ok) throw new Error("Yükləmək alınmadı");
    const url = URL.createObjectURL(await resp.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `temel_neticeler_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
};

$("new-session").onsubmit = async (ev) => {
  ev.preventDefault();
  const err = $("new-error");
  err.hidden = true;
  const chapterId = Number($("chapter-select").value);
  const className = $("class-name").value.trim();
  if (!className || !chapterId) {
    err.textContent = "Sinfi yaz və mövzu seç.";
    err.hidden = false;
    return;
  }
  try {
    const s = await api("POST", "/teacher/sessions", { chapter_id: chapterId, class_name: className });
    $("class-name").value = "";
    openSession(s.id);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  }
};

// ---------- canli radar ----------

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function openSession(id) {
  currentSession = id;
  view("session");
  await refreshRadar(true);
  stopPolling();
  pollTimer = setInterval(() => refreshRadar(false), 3000);
}

function joinUrl(code) {
  return `${location.origin}/app/?code=${code}`;
}

function renderJoin(s) {
  $("join-code").textContent = s.join_code;
  const url = joinUrl(s.join_code);
  $("join-url").textContent = url.replace(/^https?:\/\//, "");
  $("local-warn").hidden = !["localhost", "127.0.0.1"].includes(location.hostname);
  $("qr").innerHTML = `<img src="/qr.svg?text=${encodeURIComponent(url)}" width="180" height="180" alt="Qoşulma QR kodu">`;
}

async function refreshRadar(first) {
  if (!currentSession) return;
  let r;
  try {
    r = await api("GET", `/teacher/sessions/${currentSession}/radar`);
  } catch (e) {
    $("live-dot").className = "live off";
    $("live-dot").textContent = "● Bağlantı yoxdur";
    return;
  }
  const s = r.session;
  if (first) renderJoin(s);
  $("session-title").textContent = `${s.class_name} · ${s.chapter_title}`;
  $("live-dot").className = s.active ? "live" : "live off";
  $("live-dot").textContent = s.active ? "● Canlı" : "Sessiya bağlıdır";
  $("close-btn").hidden = !s.active;
  if (!s.active) stopPolling();

  const inProgress = r.students.filter((x) => x.status !== "done").length;
  $("st-joined").textContent = s.joined;
  $("st-done").textContent = s.done;
  $("st-progress").textContent = inProgress;
  $("st-nogap").textContent = r.no_gap;
  $("advice").textContent = r.advice;

  // kok sebebi en cox olan movzular yuxarida
  const total = Math.max(1, s.done);
  // kok ve zeif olanlar yuxarida, yoxlanmayanlar en asagida
  const score = (c) => c.root * 1000 + c.weak * 100 + c.known * 10 + (c.implied || 0) - c.unknown;
  const sorted = [...r.concepts].sort((a, b) => score(b) - score(a));
  // evvelki siniflerin movzularini yalniz bosluq olanda gosteririk, siyahi uzanmasin
  const isForeign = (c) => /\(\d+-c[iıu] sinif\)$/.test(c.concept);
  const problem = (c) => c.root || c.weak;
  const rows = showAllConcepts ? sorted : sorted.filter((c) => !isForeign(c) || problem(c));
  const hidden = sorted.length - rows.length;
  $("bars-more").hidden = !s.done || (!hidden && !showAllConcepts);
  $("bars-more").textContent = showAllConcepts
    ? "Yalnız vacibləri göstər"
    : `+ əvvəlki siniflərdən ${hidden} mövzu, boşluq tapılmayıb · Hamısını göstər`;
  $("bars").innerHTML = rows.map((c) => {
    const w = (n) => `${(n / total) * 100}%`;
    const parts = [];
    if (c.root) parts.push(`${c.root} kök`);
    if (c.weak) parts.push(`${c.weak} zəif`);
    if (c.known) parts.push(`${c.known} bilir`);
    if (c.implied) parts.push(`${c.implied} yəqin bilir`);
    return `<div class="bar-row"><div class="label"><b>${esc(c.concept)}</b><span>${parts.join(" · ") || "—"}</span></div>
      <div class="track" role="img" aria-label="${esc(c.concept)}: ${parts.join(", ")}">
        <i class="root" style="width:${w(c.root)}"></i><i class="weak" style="width:${w(c.weak)}"></i>
        <i class="known" style="width:${w(c.known)}"></i><i class="implied" style="width:${w(c.implied || 0)}"></i>
        <i class="unknown" style="width:${w(c.unknown)}"></i></div></div>`;
  }).join("") || `<div class="empty">Şagirdlər bitirdikcə radar dolacaq.</div>`;
  if (!s.done) $("bars").innerHTML = `<div class="empty">Hələ heç kim testi bitirməyib. Radar ilk nəticə ilə dolacaq.</div>`;

  $("mistakes").innerHTML = r.mistakes.length ? r.mistakes.map((m) => `
    <div class="mistake"><b>${m.count}</b><div><p>${esc(m.misconception)}</p><span>${esc(m.concept)}</span></div></div>`).join("")
    : `<div class="empty">Səhvlər burada toplanacaq.</div>`;

  $("students").innerHTML = r.students.length ? r.students.map((st) => {
    const state = st.status === "done"
      ? (st.roots.length ? st.roots.map((x) => `<span class="chip">${esc(x)}</span>`).join("") : `<span class="chip ok">Boşluq yoxdur</span>`)
      : `<span class="s">Test davam edir · ${st.answered} sual</span>`;
    const score = st.status === "done" ? `<span class="s">${st.correct}/${st.answered} düz</span>` : "";
    return `<button class="student" data-st="${st.attempt_id}"><span class="n">${esc(st.nickname)}</span>${score}<div>${state}</div></button>`;
  }).join("") : `<div class="empty">Şagirdlər koda qoşulanda burada görünəcək.</div>`;
  document.querySelectorAll("[data-st]").forEach((b) => (b.onclick = () => openStudent(Number(b.dataset.st))));
}

$("bars-more").onclick = () => {
  showAllConcepts = !showAllConcepts;
  refreshRadar(false);
};

async function openStudent(attemptId) {
  const d = await api("GET", `/teacher/sessions/${currentSession}/students/${attemptId}`);
  $("d-name").textContent = d.nickname;
  const diag = d.diagnosis;
  const head = diag
    ? (diag.roots.length ? `<p><b>Kök səbəb:</b> ${diag.roots.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}</p>`
                         : `<p><span class="chip ok">Ciddi boşluq tapılmadı</span></p>`)
    : `<p class="muted">Test hələ davam edir.</p>`;
  const answers = d.answers.map((a, i) => `
    <div class="ans ${a.correct ? "ok" : "no"}"><small>${i + 1}. ${esc(a.concept)}</small>
      ${esc(a.question)} → <b>${esc(a.chosen)}</b> ${a.correct ? "✓" : `✗ (düz: ${esc(a.correct_value)})`}
      ${!a.correct && a.misconception ? `<br><small>${esc(a.misconception)}</small>` : ""}</div>`).join("");
  $("d-body").innerHTML = head + answers;
  $("detail").showModal();
}
$("d-close").onclick = () => $("detail").close();

$("back-btn").onclick = () => { currentSession = null; openHome(); };
$("close-btn").onclick = async () => {
  await api("POST", `/teacher/sessions/${currentSession}/close`);
  refreshRadar(false);
};

// ---------- basla ----------

(async function init() {
  try { token = localStorage.getItem(TOKEN_KEY); } catch (e) { token = null; }
  if (!token) return view("login");
  try { await openHome(); } catch (e) { logout(); }
})();
