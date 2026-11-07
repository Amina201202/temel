import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Təməl · Admin", layout="wide")

ADMIN_KEY = os.getenv("ADMIN_PASSWORD", "")

with st.sidebar:
    st.title("Təməl")
    st.caption("Sənin bilik radarın")
    st.divider()
    st.markdown("**Admin paneli**")
    st.markdown("[Şagird tətbiqi](http://localhost:8010/app/) · [Müəllim paneli](http://localhost:8010/app/teacher.html)")
    st.divider()
    st.markdown("**Müəllim hesabları**")
    with st.form("new_teacher", clear_on_submit=True):
        t_name = st.text_input("Ad", placeholder="Səbinə müəllim")
        t_user = st.text_input("İstifadəçi adı", placeholder="sebine (kiçik hərf, rəqəm)")
        t_ok = st.form_submit_button("Hesab yarat")
    if t_ok:
        r = requests.post(f"{API_URL}/admin/teachers", headers={"X-Admin-Key": ADMIN_KEY},
                          json={"name": t_name, "username": t_user.strip().lower()}, timeout=15)
        if r.ok:
            t = r.json()
            st.success("Hesab yaradıldı. Şifrəni indi köçür, bir daha göstərilməyəcək:")
            st.code(f"İstifadəçi: {t['username']}\nŞifrə: {t['password']}")
        else:
            st.error(r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text)
    try:
        teachers = requests.get(f"{API_URL}/admin/teachers", headers={"X-Admin-Key": ADMIN_KEY}, timeout=10)
        if teachers.ok:
            for t in teachers.json():
                st.caption(f"• {t['name']} ({t['username']})")
    except requests.RequestException:
        pass


def api_get(path):
    resp = requests.get(f"{API_URL}{path}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def error_text(resp):
    # fastapi xetasi {"detail": "..."} formasinda gelir
    try:
        detail = resp.json().get("detail")
        return detail if isinstance(detail, str) else str(detail)
    except ValueError:
        return resp.text[:300]


def graph_dot(graph):
    # graphviz ile sade qraf, ox: evvel bilinmeli -> sonraki movzu
    lines = [
        "digraph G {",
        "rankdir=TB;",
        'node [shape=box, style="rounded,filled", fillcolor="#E8EAFD", color="#3D4BE0", fontname="Helvetica"];',
        'edge [color="#9EA2B5"];',
    ]
    for c in graph["concepts"]:
        name = c["name"].replace('"', "'")
        lines.append(f'"{name}";')
    for e in graph["edges"]:
        a = e["from_concept"].replace('"', "'")
        b = e["to_concept"].replace('"', "'")
        lines.append(f'"{a}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines)


# api isleyir mi
try:
    api_get("/health")
except requests.RequestException:
    st.error("Backend-ə qoşulmaq olmadı. `docker compose up` işləyirmi?")
    st.stop()

st.header("Bölmə yüklə")
st.caption("Dərslik bölməsini yüklə. AI mövzuları və aralarındakı asılılıqları çıxaracaq.")

with st.form("upload", clear_on_submit=False):
    col1, col2 = st.columns([3, 1])
    title = col1.text_input("Bölmənin adı", placeholder="məs. Bölənlər və adi kəsrlər")
    grade = col2.selectbox("Sinif", [5, 6, 7, 8, 9], index=0)
    file = st.file_uploader(
        "Fayl (.txt, PDF və ya şəkil)",
        type=["txt", "pdf", "jpg", "jpeg", "png", "webp", "heic"],
    )
    submitted = st.form_submit_button("Yüklə və analiz et", type="primary")

if submitted:
    if not title or not file:
        st.warning("Bölmənin adını yaz və fayl seç.")
    else:
        with st.status("Gemini dərsliyi oxuyur...", expanded=True) as status:
            st.write("Fayl göndərilir")
            try:
                resp = requests.post(
                    f"{API_URL}/chapters",
                    data={"title": title, "grade": grade},
                    files={"file": (file.name, file.getvalue())},
                    timeout=180,
                )
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

st.divider()
st.header("Bölmələr")

chapters = api_get("/chapters")
if not chapters:
    st.info("Hələ heç bir bölmə yoxdur. Yuxarıdan dərslik yüklə.")
    st.stop()

labels = {ch["id"]: f"{ch['title']} · {ch['grade']}-ci sinif · {ch['concept_count']} mövzu" for ch in chapters}
ids = list(labels)
default_id = st.session_state.get("selected_id", ids[0])
selected = st.selectbox(
    "Bölmə seç",
    ids,
    index=ids.index(default_id) if default_id in ids else 0,
    format_func=lambda i: labels[i],
)

graph = api_get(f"/chapters/{selected}/graph")

STATUS_LABEL = {
    "auto_ok": "Yoxlamadan keçdi",
    "needs_review": "Baxılmalıdır",
    "approved": "Təsdiqlənib",
    "rejected": "Rədd edilib",
}


def api_send(method, path, **kwargs):
    resp = requests.request(method, f"{API_URL}{path}", timeout=kwargs.pop("timeout", 30), **kwargs)
    if not resp.ok:
        st.error(error_text(resp))
        return None
    return resp.json()


tab_map, tab_bank = st.tabs(["Mövzu xəritəsi", "Sual bankı"])

with tab_map:
    st.caption("Status: qaralama — admin təsdiqləyənə qədər şagirdlərə görünmür.")
    left, right = st.columns([3, 2])
    with left:
        if graph["edges"]:
            st.graphviz_chart(graph_dot(graph), use_container_width=True)
        else:
            st.info("Asılılıq tapılmadı.")
    with right:
        st.dataframe(
            [{"Mövzu": c["name"], "İzah": c["description"]} for c in graph["concepts"]],
            hide_index=True,
            use_container_width=True,
        )

with tab_bank:
    stats = api_get(f"/chapters/{selected}/questions/stats")

    if stats["total"] == 0:
        st.info("Bu bölmə üçün hələ sual yoxdur. AI hər mövzu üçün 2 sual şablonu yaradacaq.")
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
        resp = requests.get(f"{API_URL}/chapters/{selected}/questions", params=params, timeout=30)
        if not resp.ok:
            st.error(f"Suallar yüklənmədi ({resp.status_code}): {error_text(resp)}")
            st.stop()
        questions = resp.json()

        if not questions:
            st.success("Bu siyahıda sual yoxdur.")

        for q in questions:
            with st.container(border=True):
                top = st.columns([3, 1])
                top[0].markdown(f"**{q['concept']}** · çətinlik {q['difficulty']}")
                top[1].markdown(f"`{STATUS_LABEL.get(q['status'], q['status'])}`")

                if q["sample_text"]:
                    st.markdown(f"#### {q['sample_text']}")
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
