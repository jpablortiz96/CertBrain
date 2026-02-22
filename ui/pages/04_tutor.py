"""CertBrain — Socratic Tutor session page.

Chat-style interface where the AI tutor guides the student using the
Socratic method, never giving direct answers.  Bloom's level escalates
as mastery improves.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import streamlit as st
from ui.components.progress_bar import (
    phase_progress_sidebar, bloom_badge, metric_card
)

st.set_page_config(page_title="CertBrain · Tutor", page_icon="🤖", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif!important;}
.stApp{background:#0a0a0f;}
section.main>div{background:#0a0a0f;}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0d0d18 0%,#0a0a0f 100%);border-right:1px solid rgba(0,245,212,.12);}
.stButton>button{background:linear-gradient(135deg,#00f5d4 0%,#00b4d8 100%)!important;color:#0a0a0f!important;border:none!important;border-radius:10px!important;font-weight:700!important;padding:10px 28px!important;}
[data-testid="stMetricValue"]{color:#00f5d4!important;font-weight:700!important;}
.stChatMessage{background:rgba(255,255,255,.03)!important;border:1px solid rgba(255,255,255,.07)!important;border-radius:12px!important;}
hr{border-color:rgba(255,255,255,.08)!important;}
</style>
""", unsafe_allow_html=True)

MAX_TUTOR_TURNS = 8  # max student turns before session completes

# ── Topic helpers ─────────────────────────────────────────────────────────────

_AZ900_TOPICS = [
    "Cloud Concepts",
    "Azure Architecture & Services",
    "Azure Management & Governance",
    "Security & Identity",
]


def _get_topics() -> list[str]:
    objectives = st.session_state.get("diag_objectives") or []
    if objectives:
        return [o["name"] for o in objectives]
    return _AZ900_TOPICS


def _get_initial_mastery(topic: str) -> float:
    objectives = st.session_state.get("diag_objectives") or []
    obj_scores = st.session_state.get("diag_obj_scores") or {}
    obj = next((o for o in objectives if o["name"] == topic), None)
    if obj:
        return obj_scores.get(obj["id"], 0.0)
    return 0.0


def _get_initial_bloom(topic: str) -> str:
    from agents.socratic_tutor import bloom_for_mastery
    m = _get_initial_mastery(topic)
    bloom, _ = bloom_for_mastery(m)
    return bloom.value


def _init():
    topics = _get_topics()
    defaults = {
        "tutor_topic": topics[0] if topics else _AZ900_TOPICS[0],
        "tutor_messages": [],
        "tutor_mastery": 0.0,
        "tutor_bloom": "remember",
        "tutor_session_started": False,
        "tutor_session_done": False,
        "tutor_initial_mastery": 0.0,
        "student_name": "Student",
        "tutor_unlocked": 0,
        "tutor_turn_count": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

TOPICS = _get_topics()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2 style='color:#00f5d4;'>🧬 CertBrain</h2>", unsafe_allow_html=True)
    st.divider()
    phase_progress_sidebar("studying")
    st.divider()

    st.markdown("<b style='color:#ccc;font-size:13px;'>Select Topic</b>", unsafe_allow_html=True)
    chosen = st.selectbox("Topic", TOPICS, label_visibility="collapsed")
    if chosen != st.session_state["tutor_topic"]:
        st.session_state["tutor_topic"] = chosen
        st.session_state["tutor_messages"] = []
        st.session_state["tutor_session_started"] = False
        st.session_state["tutor_session_done"] = False
        st.session_state["tutor_turn_count"] = 0
        initial_m = _get_initial_mastery(chosen)
        st.session_state["tutor_mastery"] = initial_m
        st.session_state["tutor_initial_mastery"] = initial_m
        st.session_state["tutor_bloom"] = _get_initial_bloom(chosen)

    st.divider()
    topic = st.session_state["tutor_topic"]
    init_m = st.session_state.get("tutor_initial_mastery", 0.0)
    curr_m = st.session_state["tutor_mastery"]

    st.markdown(f"**Topic:** {topic}")
    col_a, col_b = st.columns(2)
    col_a.metric("Initial", f"{init_m:.0%}")
    col_b.metric("Current", f"{curr_m:.0%}", delta=f"+{max(0, curr_m-init_m):.0%}")
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**Bloom Level**")
    st.markdown(bloom_badge(st.session_state["tutor_bloom"]), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.metric("Concepts Unlocked", st.session_state.get("tutor_unlocked", 0))

# ── Header ────────────────────────────────────────────────────────────────────
topic = st.session_state["tutor_topic"]
st.markdown(
    f"<h1 style='color:#e8e8f0;font-size:28px;margin-bottom:4px;'>🤖 Socratic Tutor</h1>"
    f"<p style='color:#666;font-size:14px;margin-top:0;'>"
    f"Never gives direct answers · Guides you to discover · Topic: <b style='color:#00f5d4;'>{topic}</b></p>",
    unsafe_allow_html=True,
)

col_meta1, col_meta2, _ = st.columns([1, 1, 3])
col_meta1.markdown(
    f"Current Bloom level: {bloom_badge(st.session_state['tutor_bloom'])}",
    unsafe_allow_html=True,
)
col_meta2.markdown(
    f"Mastery: <b style='color:#00f5d4;'>{st.session_state['tutor_mastery']:.0%}</b>",
    unsafe_allow_html=True,
)

st.markdown("<br>", unsafe_allow_html=True)

# ── Session done view ─────────────────────────────────────────────────────────
if st.session_state.get("tutor_session_done"):
    init_m = st.session_state.get("tutor_initial_mastery", 0.0)
    curr_m = st.session_state["tutor_mastery"]
    delta  = curr_m - init_m

    st.markdown(
        f"""<div style="background:rgba(0,245,212,.07);border:1px solid rgba(0,245,212,.25);
            border-radius:14px;padding:24px;text-align:center;margin-bottom:20px;">
            <div style="font-size:36px;margin-bottom:8px;">🎉</div>
            <div style="font-size:22px;font-weight:700;color:#00f5d4;">Session Complete!</div>
            <div style="color:#888;margin-top:8px;font-size:14px;">
                Mastery improved from <b style="color:#e8e8f0;">{init_m:.0%}</b>
                to <b style="color:#00e676;">{curr_m:.0%}</b>
                (+{delta:.0%})
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Show transcript
    st.markdown("**Session Transcript**")
    for msg in st.session_state["tutor_messages"]:
        role = msg["role"]
        with st.chat_message("assistant" if role == "tutor" else "user"):
            st.markdown(msg["content"])
            if role == "tutor" and "bloom" in msg:
                st.markdown(bloom_badge(msg["bloom"]), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📚 Study Next Topic", use_container_width=True):
            next_idx = (TOPICS.index(topic) + 1) % len(TOPICS)
            next_topic = TOPICS[next_idx]
            initial_m = _get_initial_mastery(next_topic)
            st.session_state["tutor_topic"] = next_topic
            st.session_state["tutor_messages"] = []
            st.session_state["tutor_session_done"] = False
            st.session_state["tutor_session_started"] = False
            st.session_state["tutor_turn_count"] = 0
            st.session_state["tutor_mastery"] = initial_m
            st.session_state["tutor_initial_mastery"] = initial_m
            st.session_state["tutor_bloom"] = _get_initial_bloom(next_topic)
            st.rerun()
    with col_b:
        if st.button("📝 Proceed to Final Assessment →", use_container_width=True):
            st.switch_page("pages/05_assessment.py")

# ── Chat interface ────────────────────────────────────────────────────────────
else:
    if not st.session_state["tutor_session_started"]:
        initial_m = _get_initial_mastery(topic)
        st.session_state["tutor_mastery"] = initial_m
        st.session_state["tutor_initial_mastery"] = initial_m
        st.session_state["tutor_bloom"] = _get_initial_bloom(topic)

    # Display existing messages
    for msg in st.session_state["tutor_messages"]:
        role = msg["role"]
        with st.chat_message("assistant" if role == "tutor" else "user"):
            st.markdown(msg["content"])
            if role == "tutor" and "bloom" in msg:
                st.markdown(bloom_badge(msg["bloom"]), unsafe_allow_html=True)

    # Start button if fresh
    if not st.session_state["tutor_session_started"]:
        st.markdown(
            f"""<div style="background:rgba(255,255,255,.03);border:1px solid rgba(0,245,212,.15);
                border-radius:12px;padding:20px;text-align:center;color:#888;font-size:14px;">
                🤖 Your Socratic tutor is ready to guide you through
                <b style="color:#00f5d4;">{topic}</b>.<br>
                <span style="font-size:12px;">Remember: the tutor will ask questions, not give answers.</span>
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("▶️ Start Tutoring Session", use_container_width=True):
            from ui.backend import get_tutor_response
            with st.spinner("Starting session..."):
                ai_resp = get_tutor_response(
                    topic=st.session_state["tutor_topic"],
                    mastery=st.session_state["tutor_mastery"],
                    transcript=[],
                )
            bloom = ai_resp.get("bloom_level", "remember")
            st.session_state["tutor_messages"].append({
                "role": "tutor",
                "content": ai_resp.get("tutor_message", f"Let's explore {st.session_state['tutor_topic']}. What do you already know?"),
                "bloom": bloom,
            })
            st.session_state["tutor_bloom"] = bloom
            st.session_state["tutor_turn_count"] = 0
            st.session_state["tutor_session_started"] = True
            st.rerun()
    else:
        # Real AI chat
        turn_count = st.session_state.get("tutor_turn_count", 0)
        all_done   = turn_count >= MAX_TUTOR_TURNS

        if not all_done:
            user_input = st.chat_input("Your answer...")
            if user_input:
                st.session_state["tutor_messages"].append({
                    "role": "student",
                    "content": user_input,
                })

                # Call real AI tutor
                from ui.backend import get_tutor_response
                with st.spinner("Tutor thinking..."):
                    ai_resp = get_tutor_response(
                        topic=st.session_state["tutor_topic"],
                        mastery=st.session_state["tutor_mastery"],
                        transcript=st.session_state["tutor_messages"],
                    )

                delta  = float(ai_resp.get("mastery_delta", 0.0))
                bloom  = ai_resp.get("bloom_level", "remember")
                msg    = ai_resp.get("tutor_message", "Let me ask you another question...")

                st.session_state["tutor_mastery"] = min(
                    1.0,
                    st.session_state["tutor_mastery"] + delta,
                )
                st.session_state["tutor_bloom"] = bloom
                st.session_state["tutor_messages"].append({
                    "role": "tutor",
                    "content": msg,
                    "bloom": bloom,
                })
                st.session_state["tutor_turn_count"] = turn_count + 1
                if delta > 0:
                    st.session_state["tutor_unlocked"] = (
                        st.session_state.get("tutor_unlocked", 0) + 1
                    )
                st.rerun()
        else:
            st.info(f"You've completed {MAX_TUTOR_TURNS} exchanges for this topic! Click below to finish.")
            if st.button("✅ Complete Session", use_container_width=True):
                st.session_state["tutor_session_done"] = True
                st.rerun()
