import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Təməl · Admin", layout="wide")

with st.sidebar:
    st.title("Təməl")
    st.caption("Sənin bilik radarın")
    st.divider()
    st.markdown("**Admin paneli**")


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

st.caption("Status: qaralama — admin təsdiqləyənə qədər şagirdlərə görünmür.")

left, right = st.columns([3, 2])
with left:
    st.subheader("Mövzu xəritəsi")
    if graph["edges"]:
        st.graphviz_chart(graph_dot(graph), use_container_width=True)
    else:
        st.info("Asılılıq tapılmadı.")
with right:
    st.subheader("Mövzular")
    st.dataframe(
        [{"Mövzu": c["name"], "İzah": c["description"]} for c in graph["concepts"]],
        hide_index=True,
        use_container_width=True,
    )
