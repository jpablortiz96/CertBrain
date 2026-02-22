"""CertBrain — Main Streamlit app (landing page).

Entry point for the multi-page dashboard.  Handles:
- Global CSS / theme injection
- Certification + student setup
- Session state bootstrap
- Sidebar navigation with progress indicator
"""

from __future__ import annotations

import sys
import os

# Make project root importable when running as `streamlit run ui/app.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from ui.components.progress_bar import phase_progress_sidebar, metric_card

# ---------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CertBrain",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Space Grotesk', sans-serif !important;
}

/* Background */
.stApp { background-color: #0a0a0f; }

/* Main content area */
section.main > div { background-color: #0a0a0f; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d0d18 0%, #0a0a0f 100%);
    border-right: 1px solid rgba(0,245,212,0.12);
}

/* Headings */
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; }

/* Text */
p, label, .stMarkdown { color: #c8c8d8; }

/* Inputs */
.stTextInput input, .stSelectbox select {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(0,245,212,0.2) !important;
    border-radius: 8px !important;
    color: #e8e8f0 !important;
    font-family: 'Space Grotesk', sans-serif !important;
}
.stTextInput input:focus {
    border-color: #00f5d4 !important;
    box-shadow: 0 0 0 2px rgba(0,245,212,0.12) !important;
}

/* Primary buttons */
.stButton > button[kind="primary"], .stButton > button {
    background: linear-gradient(135deg, #00f5d4 0%, #00b4d8 100%) !important;
    color: #0a0a0f !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    font-family: 'Space Grotesk', sans-serif !important;
    padding: 10px 28px !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.3px !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 24px rgba(0,245,212,0.3) !important;
}

/* Radio buttons */
.stRadio label { color: #c8c8d8 !important; }
.stRadio div[role="radiogroup"] {
    background: rgba(255,255,255,0.03);
    border-radius: 10px;
    padding: 10px;
}

/* Progress bars */
.stProgress > div > div {
    background: linear-gradient(90deg, #00f5d4, #00b4d8) !important;
    border-radius: 4px !important;
}

/* Metrics */
[data-testid="stMetricValue"] { color: #00f5d4 !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"] { color: #888 !important; font-size: 12px !important; }

/* Expanders */
.streamlit-expanderHeader {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(0,245,212,0.12) !important;
    border-radius: 8px !important;
    color: #ccc !important;
}

/* Success / Error / Info */
.stAlert { border-radius: 8px !important; }
div[data-testid="stNotification"] { background: rgba(0,245,212,0.1) !important; }

/* Dividers */
hr { border-color: rgba(255,255,255,0.08) !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0a0a0f; }
::-webkit-scrollbar-thumb { background: rgba(0,245,212,0.2); border-radius: 3px; }
</style>
"""

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------
CERTIFICATIONS = [
    ("AZ-900", "Azure Fundamentals",            "exam.az-900"),
    ("AZ-104", "Azure Administrator",           "exam.az-104"),
    ("AZ-204", "Azure Developer Associate",     "exam.az-204"),
    ("AI-900", "Azure AI Fundamentals",         "exam.ai-900"),
    ("AI-102", "Azure AI Engineer Associate",   "exam.ai-102"),
    ("DP-900", "Azure Data Fundamentals",       "exam.dp-900"),
    ("DP-203", "Azure Data Engineer Associate", "exam.dp-203"),
    ("SC-900", "Security Fundamentals",         "exam.sc-900"),
    ("MS-900", "Microsoft 365 Fundamentals",    "exam.ms-900"),
    ("PL-900", "Power Platform Fundamentals",   "exam.pl-900"),
]

CERT_LABELS = [f"{code} — {name}" for code, name, _ in CERTIFICATIONS]

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
def _init_state() -> None:
    defaults = {
        "cert_index": 0,
        "student_name": "",
        "student_email": "",
        "session_started": False,
        "certbrain_state": None,
        "diagnostic_done": False,
        "graph_done": False,
        "plan_done": False,
        "plan_confirmed": False,
        "questions": [],
        "answers": [],
        "current_q_idx": 0,
        "kg_data": None,
        "study_sessions": [],
        "timeline": {},
        "tutor_messages": [],
        "assessment_answers": [],
        "assessment_done": False,
        "final_score": 0.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        "<h2 style='color:#00f5d4;font-size:20px;margin:0;'>🧬 CertBrain</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#666;font-size:11px;margin-top:0;'>"
        "Neuro-Adaptive Cert Coach</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    current_phase = "diagnostic"
    if st.session_state.get("certbrain_state"):
        try:
            current_phase = st.session_state["certbrain_state"].current_phase.value
        except Exception:
            pass
    elif st.session_state.get("plan_confirmed"):
        current_phase = "studying"
    elif st.session_state.get("plan_done"):
        current_phase = "confirming_plan"
    elif st.session_state.get("graph_done"):
        current_phase = "planning"
    elif st.session_state.get("diagnostic_done"):
        current_phase = "building_graph"

    phase_progress_sidebar(current_phase)
    st.divider()

    # Sidebar metrics
    if st.session_state.get("diagnostic_done"):
        score = st.session_state.get("final_score", 0.0)
        n_q = len(st.session_state.get("answers", []))
        n_topics = len(st.session_state.get("study_sessions", []))
        st.sidebar.metric("Questions Answered", n_q)
        st.sidebar.metric("Mastery Score", f"{score:.0%}")
        st.sidebar.metric("Study Sessions", n_topics)

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "<p style='font-size:10px;color:#444;text-align:center;'>"
        "Microsoft Agents League Hackathon 2025</p>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Landing page content
# ---------------------------------------------------------------------------
# Hero
st.markdown(
    """
    <div style="text-align:center;padding:40px 20px 20px;">
        <div style="font-size:72px;margin-bottom:8px;filter:drop-shadow(0 0 24px #00f5d4);">🧬</div>
        <h1 style="
            font-size:52px;font-weight:700;margin:0;
            background:linear-gradient(135deg,#00f5d4 0%,#00b4d8 50%,#8b5cf6 100%);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;
            background-clip:text;font-family:'Space Grotesk',sans-serif;
        ">CertBrain</h1>
        <p style="
            color:#8a8aaa;font-size:18px;margin-top:8px;
            font-family:'Space Grotesk',sans-serif;letter-spacing:0.5px;
        ">Neuro-Adaptive Microsoft Certification Coach</p>
        <p style="color:#555;font-size:13px;max-width:520px;margin:12px auto 0;">
            Powered by AI agents · Spaced repetition · Bloom's taxonomy ·
            Socratic tutoring · Knowledge graphs
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("<br>", unsafe_allow_html=True)

# Feature cards
col1, col2, col3, col4 = st.columns(4)
features = [
    ("🎯", "Adaptive Diagnostic", "CAT algorithm adjusts difficulty in real-time to find your exact knowledge level"),
    ("🧠", "Knowledge Graph", "Visual map of your strengths and gaps, powered by NetworkX and GPT-4o"),
    ("📚", "SM-2 Study Plan", "Spaced repetition scheduling mapped to real Microsoft Learn modules"),
    ("🤖", "Socratic Tutor", "Never gives direct answers — guides you to discover concepts yourself"),
]
for col, (icon, title, desc) in zip([col1, col2, col3, col4], features):
    col.markdown(
        f"""<div style="
            background:rgba(255,255,255,0.03);
            border:1px solid rgba(0,245,212,0.12);
            border-radius:14px;padding:20px 16px;text-align:center;
            min-height:160px;
            transition:border-color 0.2s;
        ">
        <div style="font-size:30px;margin-bottom:10px;">{icon}</div>
        <div style="font-weight:600;color:#e8e8f0;font-size:14px;margin-bottom:6px;">{title}</div>
        <div style="color:#666;font-size:12px;line-height:1.5;">{desc}</div>
        </div>""",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)
st.divider()

# Setup form
st.markdown(
    "<h2 style='color:#e8e8f0;font-size:24px;'>Get Started</h2>",
    unsafe_allow_html=True,
)

col_form, col_spacer = st.columns([2, 1])
with col_form:
    cert_choice = st.selectbox(
        "Select your target certification",
        options=CERT_LABELS,
        index=st.session_state["cert_index"],
        key="cert_select",
    )
    st.session_state["cert_index"] = CERT_LABELS.index(cert_choice)

    name = st.text_input(
        "Your name",
        value=st.session_state["student_name"],
        placeholder="e.g. Alex Rivera",
        key="name_input",
    )
    st.session_state["student_name"] = name

    email = st.text_input(
        "Email for study reminders (optional)",
        value=st.session_state["student_email"],
        placeholder="you@example.com",
        key="email_input",
    )
    st.session_state["student_email"] = email

    selected_code, selected_name, selected_uid = CERTIFICATIONS[st.session_state["cert_index"]]

    st.markdown(
        f"""<div style="
            background:rgba(0,245,212,0.06);
            border:1px solid rgba(0,245,212,0.18);
            border-radius:10px;padding:12px 16px;margin:10px 0;font-size:13px;
        ">
        <b style="color:#00f5d4;">{selected_code}</b>
        <span style="color:#888;"> — {selected_name}</span><br>
        <span style="color:#555;font-size:11px;">Exam UID: {selected_uid}</span>
        </div>""",
        unsafe_allow_html=True,
    )

    btn_disabled = not name.strip()
    if st.button("🚀 Start Diagnostic", disabled=btn_disabled, use_container_width=True):
        st.session_state["session_started"] = True
        st.session_state["student_name"] = name.strip()
        st.session_state["student_email"] = email.strip()
        st.session_state["selected_cert_code"] = selected_code
        st.session_state["selected_cert_name"] = selected_name
        st.session_state["selected_exam_uid"] = selected_uid
        # Reset flow state for fresh start
        for key in ["diagnostic_done", "graph_done", "plan_done", "plan_confirmed",
                    "questions", "answers", "current_q_idx", "kg_data",
                    "study_sessions", "assessment_done", "final_score"]:
            st.session_state[key] = False if isinstance(st.session_state[key], bool) else \
                                    [] if isinstance(st.session_state[key], list) else \
                                    0 if isinstance(st.session_state[key], (int, float)) else \
                                    st.session_state[key]
        st.switch_page("pages/01_diagnostic.py")

    if btn_disabled:
        st.caption("Please enter your name to continue.")

with col_spacer:
    st.markdown(
        """<div style="
            background:rgba(139,92,246,0.08);
            border:1px solid rgba(139,92,246,0.2);
            border-radius:14px;padding:20px;margin-top:28px;
        ">
        <div style="color:#a78bfa;font-weight:600;font-size:14px;margin-bottom:12px;">
            🔬 What happens next?
        </div>
        <ol style="color:#888;font-size:12px;line-height:2;padding-left:18px;margin:0;">
            <li>20-question adaptive diagnostic</li>
            <li>AI builds your knowledge graph</li>
            <li>Personalised study plan generated</li>
            <li>Socratic tutoring sessions</li>
            <li>Final assessment &amp; exam readiness</li>
        </ol>
        </div>""",
        unsafe_allow_html=True,
    )

# Footer
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown(
    """<div style="text-align:center;color:#333;font-size:11px;">
    Built for <b style="color:#555;">Microsoft Agents League Hackathon 2025</b> ·
    Azure AI Foundry · GPT-4o · NetworkX · Streamlit
    </div>""",
    unsafe_allow_html=True,
)
