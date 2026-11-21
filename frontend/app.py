import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
ADMIN_KEY = os.getenv("ADMIN_PASSWORD", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8010").rstrip("/")

st.set_page_config(page_title="Təməl · Admin", page_icon="🎯", layout="wide")

LOGO = """<svg viewBox="0 0 40 40" width="{s}" height="{s}"><rect width="40" height="40" rx="11" fill="#3D4BE0"/>
<circle cx="20" cy="20" r="12" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="2"/>
<circle cx="20" cy="20" r="6.5" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="2"/>
<path d="M20 20L28.5 11.5" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
<circle cx="20" cy="20" r="2.4" fill="#fff"/><circle cx="25" cy="26" r="2" fill="#fff"/></svg>"""

# temel-in reng ve sriftleri: sagird/muellim tetbiqi ile eyni gorunsun
# tema: istifadeci menyudan (⋮ → Settings) ag ve ya qaranliq secir
try:
    IS_DARK = st.context.theme.type == "dark"
except Exception:  # noqa: BLE001
    IS_DARK = False

# iki tema ucun de rengler; hansi aktivdirse, brauzerdeki skript <html data-theme> qoyur
THEME_VARS = """:root {
  --bg: #F4F5FA; --surface: #FFFFFF; --surface-2: #F4F5FA; --line: #E2E4EE;
  --text: #15172B; --muted: #555A70; --accent: #3D4BE0; --accent-soft: #E8EAFD; --accent-ink: #2A35B8;
  --good-soft: #DDF3E9; --good: #0F5C3E; --gray-soft: #F4F5FA; --gray: #555A70;
}
:root[data-theme="dark"] {
  --bg: #11121A; --surface: #1A1C27; --surface-2: #222536; --line: #2C2F42;
  --text: #E9EAF2; --muted: #9A9EB5; --accent: #6E7BFF; --accent-soft: rgba(110,123,255,.16); --accent-ink: #B4BBFF;
  --good-soft: rgba(63,165,122,.18); --good: #7FD3AE; --gray-soft: #262938; --gray: #B5B8CC;
}"""

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
/*VARS*/
html, body, [class*="css"], .stMarkdown, .stButton button, input, textarea, select { font-family: 'Inter', sans-serif !important; }
h1, h2, h3, h4, h5, h6 { font-family: 'Inter', sans-serif !important; letter-spacing: -0.4px; color: var(--text); }
h1, h2, h3 { font-weight: 800 !important; }
h4, h5 { font-weight: 700 !important; }
.block-container { padding-top: 2rem; max-width: 1200px; }
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--line); }
[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 14px 18px; }
[data-testid="stMetricValue"] { font-weight: 800; }
[data-testid="stMetricLabel"] p { color: var(--muted); }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px !important; background: var(--surface); border-color: var(--line) !important; }
[data-testid="stExpander"] { background: var(--surface); border-radius: 16px; border-color: var(--line) !important; }
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button { border-radius: 12px; font-weight: 600; min-height: 42px; }
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.brand b { font-size: 20px; font-weight: 800; display: block; line-height: 1.1; color: var(--text); }
.brand span { font-size: 13px; color: var(--muted); }
.page-sub { color: var(--muted); margin-top: -8px; margin-bottom: 18px; }
.chip { display: inline-block; font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-ink); margin-right: 6px; }
.chip.green { background: var(--good-soft); color: var(--good); }
.chip.gray { background: var(--gray-soft); color: var(--gray); }
.ch-title { font-size: 16px; font-weight: 700; margin: 6px 0 4px; color: var(--text); }
.login-card { text-align: center; margin: 8vh auto 18px; }
.login-card h1 { margin: 12px 0 4px; font-size: 30px; }
.login-card p { color: var(--muted); }
/* yan menyu: radio duymeleri pill kimi, secilen mavi fonla */
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span:not([data-testid="stIconMaterial"]),
[data-testid="stSidebar"] a, [data-testid="stSidebar"] button { font-family: 'Inter', sans-serif !important; }
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has([role="radiogroup"]),
[data-testid="stSidebar"] [data-testid="stRadio"] { width: 100% !important; }
[data-testid="stSidebar"] [role="radiogroup"] { align-items: stretch !important; width: 100%; gap: 4px; }
[data-testid="stSidebar"] [role="radiogroup"] > div { width: 100%; }
[data-testid="stSidebar"] [role="radiogroup"] label { width: 100%; padding: 11px 14px; border-radius: 12px; margin: 0;
  cursor: pointer; transition: background .15s; box-sizing: border-box; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: var(--surface-2); }
/* radio yuvarlagini gizledirik (kohne ve yeni streamlit versiyasi) */
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child,
[data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child:not([data-testid="stMarkdownContainer"]) { display: none; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background: var(--accent-soft); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p { color: var(--accent-ink); font-weight: 700; }
[data-testid="stSidebar"] [role="radiogroup"] label p { font-size: 15px; font-weight: 500; color: var(--text); }
.side-label { font-size: 11px; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); margin: 18px 4px 8px; }
[data-testid="stSidebar"] [data-testid="stLinkButton"] a { justify-content: flex-start; border-radius: 12px; border: 1px solid var(--line);
  background: var(--bg); color: var(--text); font-weight: 600; min-height: 42px; }
[data-testid="stSidebar"] [data-testid="stLinkButton"] a:hover { border-color: var(--accent); color: var(--accent-ink); }
.pwd-box { background: var(--good-soft); border: 1px solid rgba(127,211,174,.35); border-radius: 14px; padding: 12px 16px; margin-bottom: 8px; color: var(--good); }
</style>
""".replace("/*VARS*/", THEME_VARS), unsafe_allow_html=True)

# streamlit tema deyisende sehifeni yeniden yuklemir: fon rengine baxib data-theme qoyuruq
st.html("""<script>
(function () {
  function sync() {
    const app = document.querySelector('[data-testid="stApp"]');
    if (!app) return;
    const m = getComputedStyle(app).backgroundColor.match(/\\d+/g);
    if (!m) return;
    const light = (m[0] * 299 + m[1] * 587 + m[2] * 114) / 1000 > 128;
    document.documentElement.dataset.theme = light ? "light" : "dark";
  }
  sync();
  if (!window.__temelTheme) window.__temelTheme = setInterval(sync, 400);
})();
</script>""", unsafe_allow_javascript=True)


def page_header(title, sub=""):
    st.markdown(f"## {title}")
    if sub:
        st.markdown(f"<p class='page-sub'>{sub}</p>", unsafe_allow_html=True)


# ---------- giris: panel internetde aciq olacaq ----------
if not st.session_state.get("admin_ok"):
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown(f"<div class='login-card'>{LOGO.format(s=64)}<h1>Təməl · Admin</h1>"
                    "<p>Dərsliklər, suallar, nəticələr və müəllimlər</p></div>", unsafe_allow_html=True)
        with st.form("login"):
            pwd = st.text_input("Admin şifrəsi", type="password")
            if st.form_submit_button("Daxil ol", type="primary", use_container_width=True):
                if ADMIN_KEY and pwd == ADMIN_KEY:
                    st.session_state["admin_ok"] = True
                    st.rerun()
                else:
                    st.error("Şifrə səhvdir")
    st.stop()

# butun sorgulara admin acarini elave edirik
http = requests.Session()
http.headers["X-Admin-Key"] = ADMIN_KEY

# istifadeci adinda az herflerini latina ceviririk: sebine, "səbinə" yox
AZ_LATIN = str.maketrans("əıöüçşğ", "eioucsg")


def to_username(text):
    return text.strip().lower().replace("i̇", "i").translate(AZ_LATIN).replace(" ", "_")


def api_get(path):
    resp = http.get(f"{API_URL}{path}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def error_text(resp):
    # fastapi xetasi {"detail": "..."} formasinda gelir
    try:
        detail = resp.json().get("detail")
        return detail if isinstance(detail, str) else str(detail)
    except ValueError:
        return resp.text[:300]


def api_send(method, path, **kwargs):
    resp = http.request(method, f"{API_URL}{path}", timeout=kwargs.pop("timeout", 30), **kwargs)
    if not resp.ok:
        st.error(error_text(resp))
        return None
    return resp.json()


def grade_label(g):
    return f"{g}-" + {1: "ci", 2: "ci", 3: "cü", 4: "cü", 5: "ci", 6: "cı", 7: "ci", 8: "ci", 9: "cu",
                      10: "cu", 11: "ci"}.get(g, "ci")


# ---------- yan menyu ----------
with st.sidebar:
    st.markdown(f"<div class='brand'>{LOGO.format(s=40)}<div><b>Təməl</b><span>Admin paneli</span></div></div>",
                unsafe_allow_html=True)
    st.markdown("<div class='side-label'>Menyu</div>", unsafe_allow_html=True)
    page = st.radio("Menyu", ["📚 Dərsliklər və suallar", "📊 Nəticələr", "👩‍🏫 Müəllimlər"],
                    label_visibility="collapsed")
    st.markdown("<div class='side-label'>Tətbiqlər</div>", unsafe_allow_html=True)
    st.link_button("🎒 Şagird tətbiqi ↗", f"{PUBLIC_URL}/app/", use_container_width=True)
    st.link_button("🧑‍🏫 Müəllim paneli ↗", f"{PUBLIC_URL}/app/teacher.html", use_container_width=True)
    st.markdown("<div class='side-label'>Görünüş</div>", unsafe_allow_html=True)
    st.caption("🌓 Ağ / qaranlıq tema: sağ yuxarıdakı **⋮** → Light / Dark / System")
    if st.button("↩ Çıxış", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# api isleyir mi
try:
    api_get("/health")
except requests.RequestException:
    st.error("Backend-ə qoşulmaq olmadı. `docker compose up` işləyirmi?")
    st.stop()


# =====================================================================
# MUELLIMLER
# =====================================================================
if page == "👩‍🏫 Müəllimlər":
    page_header("Müəllimlər", "Müəllim hesabı yarat. Şifrə yalnız bir dəfə göstərilir — unudulsa, yenilə.")

    # yeni yaradilan ve ya yenilenen sifre: rerun-dan sonra da gorunsun
    shown = st.session_state.get("shown_password")
    if shown:
        st.markdown(f"<div class='pwd-box'><b>{shown['title']}</b> Bu məlumatı köçür və müəllimə ver. "
                    "Bir daha göstərilməyəcək.</div>", unsafe_allow_html=True)
        st.code(f"Ad: {shown['name']}\nİstifadəçi adı: {shown['username']}\nŞifrə: {shown['password']}\n"
                f"Giriş: {PUBLIC_URL}/app/teacher.html", language=None)
        if st.button("Köçürdüm, gizlət"):
            st.session_state.pop("shown_password")
            st.rerun()

    left, right = st.columns([1, 1.6], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### ➕ Yeni müəllim")
            with st.form("new_teacher", clear_on_submit=True, border=False):
                t_name = st.text_input("Ad", placeholder="Səbinə müəllim")
                t_user = st.text_input("İstifadəçi adı", placeholder="sebine",
                                       help="Azərbaycan hərfləri avtomatik latına çevrilir: Səbinə → sebine")
                t_ok = st.form_submit_button("Hesab yarat", type="primary", use_container_width=True)
            if t_ok:
                res = api_send("POST", "/admin/teachers", json={"name": t_name, "username": to_username(t_user)})
                if res:
                    st.session_state["shown_password"] = {**res, "title": "✓ Hesab yaradıldı."}
                    st.rerun()

    with right:
        teachers = api_get("/admin/teachers")
        st.markdown(f"#### Hesablar · {len(teachers)}")
        if not teachers:
            st.info("Hələ müəllim yoxdur.")
        for t in teachers:
            with st.container(border=True):
                a, b = st.columns([3, 1.3])
                a.markdown(f"**{t['name']}**  \n<span class='chip gray'>{t['username']}</span>"
                           f"<span class='chip'>{t.get('sessions', 0)} sessiya</span>", unsafe_allow_html=True)
                if b.button("🔑 Şifrəni yenilə", key=f"reset{t['id']}", use_container_width=True):
                    res = api_send("POST", f"/admin/teachers/{t['id']}/reset-password")
                    if res:
                        st.session_state["shown_password"] = {**res, "title": "✓ Yeni şifrə yaradıldı."}
                        st.rerun()
    st.stop()


# =====================================================================
# NETICELER: butun testler (kodlu ve kodsuz)
# =====================================================================
if page == "📊 Nəticələr":
    page_header("Nəticələr", "Bütün testlər: müəllim sessiyasından (kodlu) və öz-özünə məşq edənlər (kodsuz).")
    rows = api_get("/admin/attempts")
    if not rows:
        st.info("Hələ test yoxdur.")
        st.stop()

    done = [r for r in rows if r["status"] == "bitirdi"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cəmi test", len(rows))
    c2.metric("Bitirib", len(done))
    c3.metric("Kodsuz", sum(1 for r in rows if r["class_name"] == "— kodsuz —"))
    fast = sum(1 for r in done if r["minutes"] is not None and r["minutes"] < 1)
    c4.metric("1 dəqiqədən tez", fast, help="Çox tez bitənlər çox güman təsadüfi basılıb")

    st.markdown("#### Bütün testlər")
    table = [{
        "id": r["id"], "Şagird": r["nickname"], "Sinif": r["class_name"],
        "Mövzu": f"{r['chapter']} ({grade_label(r['grade'])})" if r["grade"] else r["chapter"],
        "Status": r["status"],
        "Düz": f"{r['correct']}/{r['answered']}" if r["answered"] else "",
        "Kök səbəb": ", ".join(r["roots"]), "Dəqiqə": r["minutes"], "Başladı": r["started_at"],
    } for r in rows]
    st.dataframe(table, use_container_width=True, hide_index=True)

    # bir testin detali: hansi suala ne cavab verib
    options = {f"#{r['id']} · {r['nickname']} · {r['chapter']}": r["id"] for r in rows if r["answered"]}
    if options:
        st.markdown("#### Testin detalı")
        pick = st.selectbox("Test seç", list(options), label_visibility="collapsed")
        det = api_get(f"/admin/attempts/{options[pick]}")
        with st.container(border=True):
            if det["roots"]:
                st.markdown("**Kök səbəb:** " + " ".join(f"<span class='chip'>{r}</span>" for r in det["roots"]),
                            unsafe_allow_html=True)
            if det["explanation"]:
                st.caption(f"İzah: {det['explanation']}")
            for i, x in enumerate(det["answers"], 1):
                mark = "✅" if x["correct"] else "❌"
                st.markdown(f"**{i}. {x['concept']}** {mark}  \n{x['question']}  \n"
                            f"Cavab: **{x['chosen']}**" + ("" if x["correct"] else f" · düz: **{x['correct_value']}**"))
                if not x["correct"] and x["misconception"]:
                    st.caption(f"↳ {x['misconception']}")
    st.stop()


# =====================================================================
# DERSLIKLER VE SUALLAR
# =====================================================================
page_header("Dərsliklər və suallar", "Dərslik bölməsini yüklə → AI mövzuları çıxarır → suallar yaradılır → sən təsdiqləyirsən.")

chapters = api_get("/chapters")
approved = {c["id"]: c["questions"] for c in api_get("/public/chapters")}

# qisa xulase
if chapters:
    grades = sorted({c["grade"] for c in chapters})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Bölmə", len(chapters))
    m2.metric("Mövzu", sum(c["concept_count"] for c in chapters))
    m3.metric("Təsdiqlənmiş sual", sum(approved.values()))
    m4.metric("Siniflər", f"{grades[0]}–{grades[-1]}" if len(grades) > 1 else str(grades[0]))
    st.markdown("#### Bölmələr")

# bolmeler: kartlar
if chapters:
    cols = st.columns(3)
    for i, ch in enumerate(sorted(chapters, key=lambda c: (c["grade"], c["id"]))):
        with cols[i % 3].container(border=True):
            st.markdown(f"<span class='chip'>{grade_label(ch['grade'])} sinif</span>"
                        f"<div class='ch-title'>{ch['title']}</div>"
                        f"<span class='chip gray'>{ch['concept_count']} mövzu</span>"
                        f"<span class='chip green'>{approved.get(ch['id'], 0)} sual</span>", unsafe_allow_html=True)


G = ({"fill": "#2A2E52", "border": "#6E7BFF", "font": "#E9EAF2", "edge": "#6B6F86", "cross_fill": "#1A1C27", "cross_font": "#B5B8CC"}
     if IS_DARK else
     {"fill": "#E8EAFD", "border": "#3D4BE0", "font": "#15172B", "edge": "#9EA2B5", "cross_fill": "#F4F5FA", "cross_font": "#555A70"})


def graph_dot(graph):
    # bu bolmenin movzulari goy, evvelki sinifler boz ve qirik xetle
    lines = [
        "digraph G {", "rankdir=TB;",
        f'node [shape=box, style="rounded,filled", fillcolor="{G["fill"]}", color="{G["border"]}", fontcolor="{G["font"]}", fontname="Helvetica"];',
        f'edge [color="{G["edge"]}"];', 'bgcolor="transparent";',
    ]
    for c in graph["concepts"]:
        lines.append(f'"{c["name"].replace(chr(34), chr(39))}";')
    for e in graph["edges"]:
        a = e["from_concept"].replace('"', "'")
        b = e["to_concept"].replace('"', "'")
        if e.get("cross"):
            node = f"{a} ({grade_label(e['from_grade'])} sinif)"
            lines.append(f'"{node}" [fillcolor="{G["cross_fill"]}", color="{G["edge"]}", fontcolor="{G["cross_font"]}", style="rounded,filled,dashed"];')
            lines.append(f'"{node}" -> "{b}" [style=dashed];')
        else:
            lines.append(f'"{a}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines)


with st.expander("➕ Yeni bölmə yüklə", expanded=not chapters):
    st.caption("PDF yüklə. AI mətni oxuyur, mövzuları və aralarındakı asılılıqları çıxarır (2–4 dəqiqə).")
    with st.form("upload", clear_on_submit=False):
        col1, col2, col3 = st.columns([3, 1, 1])
        title = col1.text_input("Bölmənin adı", placeholder="məs. Bölənlər və adi kəsrlər")
        # default yoxdur ki unudub 5-ci sinif qalmasin
        grade = col2.selectbox("Sinif", [5, 6, 7, 8, 9], index=None, placeholder="Seç")
        first_page = col3.number_input("Kitabda ilk səhifə", min_value=1, max_value=500, value=1,
                                       help="PDF-in ilk səhifəsi kitabda neçənci səhifədir (mənbə üçün)")
        file = st.file_uploader("Fayl (.txt, PDF və ya şəkil)", type=["txt", "pdf", "jpg", "jpeg", "png", "webp", "heic"])
        submitted = st.form_submit_button("Yüklə və analiz et", type="primary")

    if submitted:
        if not title or not file or grade is None:
            st.warning("Bölmənin adını yaz, sinfi seç və fayl seç.")
        else:
            with st.status("Gemini dərsliyi oxuyur... (PDF-də 2-4 dəqiqə çəkə bilər)", expanded=True) as status:
                try:
                    resp = http.post(f"{API_URL}/chapters",
                                     data={"title": title, "grade": grade, "first_page": int(first_page)},
                                     files={"file": (file.name, file.getvalue())},
                                     timeout=600)  # PDF oxumaq 2-4 deqiqe ceke biler
                except requests.Timeout:
                    status.update(label="Vaxt bitdi", state="error")
                    st.error("AI çox gec cavab verdi. Bir az sonra yenidən cəhd et.")
                    st.stop()
                except requests.RequestException as e:
                    status.update(label="Xəta", state="error")
                    st.error(f"Backend-ə qoşulmaq olmadı: {e}")
                    st.stop()
                if resp.ok:
                    g = resp.json()
                    status.update(label="Hazırdır", state="complete")
                    st.session_state["selected_id"] = g["chapter"]["id"]
                    st.success(f"{len(g['concepts'])} mövzu və {len(g['edges'])} asılılıq tapıldı.")
                else:
                    status.update(label="Alınmadı", state="error")
                    st.error(error_text(resp))

if not chapters:
    st.stop()

st.markdown("### Bölməyə bax")
labels = {ch["id"]: f"{ch['title']} · {grade_label(ch['grade'])} sinif · {ch['concept_count']} mövzu" for ch in chapters}
ids = list(labels)
default_id = st.session_state.get("selected_id", ids[0])
selected = st.selectbox("Bölmə seç", ids, index=ids.index(default_id) if default_id in ids else 0,
                        format_func=lambda i: labels[i], label_visibility="collapsed")

graph = api_get(f"/chapters/{selected}/graph")

STATUS_LABEL = {"auto_ok": "Yoxlamadan keçdi", "needs_review": "Baxılmalıdır",
                "approved": "Təsdiqlənib", "rejected": "Rədd edilib"}

tab_map, tab_bank = st.tabs(["🗺️ Mövzu xəritəsi", "📝 Sual bankı"])

with tab_map:
    left, right = st.columns([3, 2])
    with left:
        if graph["edges"]:
            st.graphviz_chart(graph_dot(graph), use_container_width=True)
        else:
            st.info("Asılılıq tapılmadı.")
    with right:
        st.dataframe([{"Mövzu": c["name"], "İzah": c["description"]} for c in graph["concepts"]],
                     hide_index=True, use_container_width=True)

    st.markdown("#### Əvvəlki siniflərlə əlaqə")
    st.caption("AI bu bölmənin mövzularını əvvəlki siniflərin mövzuları ilə əlaqələndirir (bal ≥ 4). Səhv əlaqəni sil.")
    if st.button("Əvvəlki siniflərlə əlaqələndir", type="primary"):
        with st.spinner("AI əlaqələri axtarır..."):
            res = api_send("POST", f"/chapters/{selected}/link", timeout=180)
        if res is not None:
            st.success(f"{len(res['created'])} yeni əlaqə yaradıldı")
            st.rerun()
    cross = [e for e in graph["edges"] if e.get("cross")]
    if not cross:
        st.info("Hələ siniflərarası əlaqə yoxdur.")
    for e in cross:
        with st.container(border=True):
            c1, c2 = st.columns([6, 1])
            c1.markdown(f"<span class='chip gray'>{grade_label(e['from_grade'])} sinif</span> **{e['from_concept']}** → "
                        f"**{e['to_concept']}**", unsafe_allow_html=True)
            if c2.button("Sil", key=f"del{e['id']}", use_container_width=True):
                api_send("DELETE", f"/edges/{e['id']}")
                st.rerun()

with tab_bank:
    stats = api_get(f"/chapters/{selected}/questions/stats")
    if stats["total"] == 0:
        st.info("Bu bölmə üçün hələ sual yoxdur. AI hər mövzu üçün sual şablonları yaradacaq.")
    cols = st.columns(4)
    cols[0].metric("Cəmi şablon", stats["total"])
    cols[1].metric("Yoxlamadan keçdi", stats["auto_ok"])
    cols[2].metric("Baxılmalıdır", stats["needs_review"])
    cols[3].metric("Təsdiqlənib", stats["approved"])

    b1, b2 = st.columns(2)
    gen_label = "Sual şablonları yarat" if stats["total"] == 0 else "Yenidən yarat (təsdiqlənmişlər qalır)"
    if b1.button(gen_label, type="primary", use_container_width=True):
        with st.status("AI sual şablonları yazır, kod onları yoxlayır...", expanded=False) as status:
            res = api_send("POST", f"/chapters/{selected}/questions/generate", timeout=300)
            if res:
                status.update(label=f"{res['total']} şablon hazırdır", state="complete")
                st.rerun()
            else:
                status.update(label="Alınmadı", state="error")
    if b2.button(f"Yoxlamadan keçənlərin hamısını təsdiqlə ({stats['auto_ok']})",
                 disabled=stats["auto_ok"] == 0, use_container_width=True):
        api_send("POST", f"/chapters/{selected}/questions/approve-auto")
        st.rerun()

    if stats["total"]:
        st.divider()
        view = st.radio("Göstər", ["Baxılmalıdır", "Hamısı", "Təsdiqlənib"], horizontal=True)
        status_filter = {"Baxılmalıdır": "needs_review", "Təsdiqlənib": "approved", "Hamısı": None}[view]
        params = {"status": status_filter} if status_filter else {}
        resp = http.get(f"{API_URL}/chapters/{selected}/questions", params=params, timeout=30)
        if not resp.ok:
            st.error(f"Suallar yüklənmədi ({resp.status_code}): {error_text(resp)}")
            st.stop()
        questions = resp.json()
        if not questions:
            st.success("Bu siyahıda sual yoxdur.")

        for q in questions:
            with st.container(border=True):
                top = st.columns([3, 1])
                top[0].markdown(f"<span class='chip'>{q['concept']}</span><span class='chip gray'>çətinlik {q['difficulty']}</span>",
                                unsafe_allow_html=True)
                top[1].markdown(f"`{STATUS_LABEL.get(q['status'], q['status'])}`")

                if q["sample_text"]:
                    st.markdown(f"##### {q['sample_text']}")
                    for o in q["sample_options"]:
                        if o["correct"]:
                            st.markdown(f"✅ **{o['value']}** — düz cavab")
                        else:
                            st.markdown(f"❌ **{o['value']}** — {o['misconception']} → *{o['points_to']}*")
                else:
                    st.warning("Bu şablondan sual yaratmaq olmadı.")

                st.caption(f"Şablon: {q['template_text']}")
                if q["source_quote"]:
                    st.caption(f"Mənbə: “{q['source_quote']}”")
                for note in q.get("notes", []):
                    st.info(note)
                for prob in q["problems"]:
                    st.error(prob)

                a, r, _ = st.columns([1, 1, 3])
                if a.button("Təsdiqlə", key=f"ok{q['id']}", disabled=bool(q["problems"]) or q["status"] == "approved"):
                    api_send("PATCH", f"/questions/{q['id']}", json={"status": "approved"})
                    st.rerun()
                if r.button("Rədd et", key=f"no{q['id']}", disabled=q["status"] == "rejected"):
                    api_send("PATCH", f"/questions/{q['id']}", json={"status": "rejected"})
                    st.rerun()
