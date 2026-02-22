"""CertBrain — Knowledge Graph visualization page.

Interactive, coloured network graph built from the KnowledgeGraph model.
Nodes glow red/yellow/green by mastery.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import streamlit as st
from ui.components.progress_bar import phase_progress_sidebar, metric_card
from ui.components.brain_viz import create_knowledge_graph_figure

st.set_page_config(page_title="CertBrain · Knowledge Map", page_icon="🧠", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif!important;}
.stApp{background:#0a0a0f;}
section.main>div{background:#0a0a0f;}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0d0d18 0%,#0a0a0f 100%);border-right:1px solid rgba(0,245,212,.12);}
.stButton>button{background:linear-gradient(135deg,#00f5d4 0%,#00b4d8 100%)!important;color:#0a0a0f!important;border:none!important;border-radius:10px!important;font-weight:700!important;padding:10px 28px!important;}
[data-testid="stMetricValue"]{color:#00f5d4!important;font-weight:700!important;}
hr{border-color:rgba(255,255,255,.08)!important;}
</style>
""", unsafe_allow_html=True)

def _init():
    if "kg_data" not in st.session_state or not st.session_state["kg_data"]:
        objectives = st.session_state.get("diag_objectives") or []
        mastery_map = st.session_state.get("diag_obj_scores") or {}
        if objectives and mastery_map:
            from ui.backend import build_knowledge_graph
            with st.spinner("Building your knowledge graph..."):
                st.session_state["kg_data"] = build_knowledge_graph(objectives, mastery_map)
        else:
            # Build minimal KG from objectives alone (no mastery data yet)
            if objectives:
                from ui.backend import build_knowledge_graph
                with st.spinner("Building knowledge graph..."):
                    st.session_state["kg_data"] = build_knowledge_graph(objectives, {})
            else:
                st.session_state["kg_data"] = {"nodes": [], "edges": []}

_init()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2 style='color:#00f5d4;'>🧬 CertBrain</h2>", unsafe_allow_html=True)
    st.divider()
    phase_progress_sidebar("building_graph")
    st.divider()

    kg = st.session_state["kg_data"]
    nodes = kg.get("nodes", [])
    mastered    = [n for n in nodes if n.get("mastery", 0) >= 0.7]
    in_progress = [n for n in nodes if 0.3 <= n.get("mastery", 0) < 0.7]
    gaps        = [n for n in nodes if n.get("mastery", 0) < 0.3]
    avg_mastery = sum(n.get("mastery", 0) for n in nodes) / max(len(nodes), 1)

    st.metric("Total Concepts", len(nodes))
    st.metric("Average Mastery", f"{avg_mastery:.0%}")
    st.metric("In ZPD", len(in_progress), help="Zone of Proximal Development (0.3–0.7)")
    st.metric("Mastered", len(mastered))
    st.metric("Critical Gaps", len(gaps))

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='color:#e8e8f0;font-size:28px;margin-bottom:4px;'>🧠 Knowledge Map</h1>"
    f"<p style='color:#666;font-size:14px;margin-top:0;'>"
    f"{len(nodes)} concepts · {len(mastered)} mastered · "
    f"{len(in_progress)} in progress · {len(gaps)} gaps · "
    "Hover nodes for details</p>",
    unsafe_allow_html=True,
)

# ── Legend ────────────────────────────────────────────────────────────────────
st.markdown(
    """<div style="display:flex;gap:20px;margin-bottom:16px;flex-wrap:wrap;">
    <span style="font-size:12px;color:#888;">Node colour:</span>
    <span style="background:rgba(224,60,60,.15);border:1px solid #e03c3c55;
        color:#e03c3c;border-radius:20px;padding:2px 12px;font-size:11px;">
        🔴 Not Yet Learned &lt;30%</span>
    <span style="background:rgba(240,192,64,.12);border:1px solid #f0c04055;
        color:#f0c040;border-radius:20px;padding:2px 12px;font-size:11px;">
        🟡 In Progress 30–70%</span>
    <span style="background:rgba(0,230,118,.12);border:1px solid #00e67655;
        color:#00e676;border-radius:20px;padding:2px 12px;font-size:11px;">
        🟢 Mastered &gt;70%</span>
    <span style="color:#555;font-size:11px;">· Node size = exam weight</span>
    </div>""",
    unsafe_allow_html=True,
)

# ── Main graph + side panel ───────────────────────────────────────────────────
col_graph, col_panel = st.columns([3, 1])

with col_graph:
    kg_data = st.session_state["kg_data"]
    fig = create_knowledge_graph_figure(
        kg_data,
        title="",
        height=600,
    )
    st.plotly_chart(fig, use_container_width=True)

with col_panel:
    st.markdown(
        "<div style='height:20px;'></div>",
        unsafe_allow_html=True,
    )

    # Learning frontier (ZPD)
    frontier = sorted(in_progress, key=lambda n: n.get("mastery", 0))
    if frontier:
        st.markdown(
            "<div style='font-size:13px;font-weight:600;color:#f0c040;margin-bottom:6px;'>"
            "🎯 Learning Frontier (ZPD)</div>",
            unsafe_allow_html=True,
        )
        for n in frontier[:6]:
            m = n.get("mastery", 0)
            st.markdown(
                f"<div style='background:rgba(240,192,64,.07);border:1px solid rgba(240,192,64,.2);"
                f"border-radius:6px;padding:6px 10px;margin:3px 0;font-size:11px;'>"
                f"<b style='color:#f0c040;'>{n.get('name','')}</b><br>"
                f"<span style='color:#888;'>Mastery: {m:.0%}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # Critical gaps
    if gaps:
        st.markdown(
            "<div style='font-size:13px;font-weight:600;color:#e03c3c;margin-bottom:6px;'>"
            "⚠️ Critical Gaps</div>",
            unsafe_allow_html=True,
        )
        for n in gaps[:5]:
            m = n.get("mastery", 0)
            st.markdown(
                f"<div style='background:rgba(224,60,60,.07);border:1px solid rgba(224,60,60,.2);"
                f"border-radius:6px;padding:6px 10px;margin:3px 0;font-size:11px;'>"
                f"<b style='color:#e03c3c;'>{n.get('name','')}</b><br>"
                f"<span style='color:#888;'>Mastery: {m:.0%}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # Strengths
    if mastered:
        st.markdown(
            "<div style='font-size:13px;font-weight:600;color:#00e676;margin-bottom:6px;'>"
            "✅ Strengths</div>",
            unsafe_allow_html=True,
        )
        for n in mastered[:5]:
            m = n.get("mastery", 0)
            st.markdown(
                f"<div style='background:rgba(0,230,118,.07);border:1px solid rgba(0,230,118,.2);"
                f"border-radius:6px;padding:6px 10px;margin:3px 0;font-size:11px;'>"
                f"<b style='color:#00e676;'>{n.get('name','')}</b><br>"
                f"<span style='color:#888;'>Mastery: {m:.0%}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

# ── Progress summary ──────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
m1, m2, m3, m4 = st.columns(4)
m1.markdown(metric_card("Total Concepts", str(len(nodes)), icon="🧠"), unsafe_allow_html=True)
m2.markdown(metric_card("Avg Mastery", f"{avg_mastery:.0%}", icon="📊"), unsafe_allow_html=True)
m3.markdown(metric_card("ZPD Topics", str(len(in_progress)), icon="🎯"), unsafe_allow_html=True)
m4.markdown(metric_card("Critical Gaps", str(len(gaps)), icon="⚠️"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
if st.button("📋 Generate Personalised Study Plan →", use_container_width=True):
    st.session_state["graph_done"] = True
    st.switch_page("pages/03_study_plan.py")
