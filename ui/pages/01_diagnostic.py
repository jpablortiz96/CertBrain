"""CertBrain — Diagnostic Pre-Test page.

Presents AI-generated adaptive multiple-choice questions one at a time.
Questions are generated in real-time using the DiagnosticAgent LLM call.
Difficulty adapts using CAT rules: correct → move up, wrong → move down.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import math
import streamlit as st

from ui.components.progress_bar import (
    phase_progress_sidebar, difficulty_badge, bloom_badge, metric_card
)
from ui.components.brain_viz import create_radar_chart

st.set_page_config(page_title="CertBrain · Diagnostic", page_icon="🔬", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif!important;}
.stApp{background:#0a0a0f;}
section.main>div{background:#0a0a0f;}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0d0d18 0%,#0a0a0f 100%);border-right:1px solid rgba(0,245,212,.12);}
.stButton>button{background:linear-gradient(135deg,#00f5d4 0%,#00b4d8 100%)!important;color:#0a0a0f!important;border:none!important;border-radius:10px!important;font-weight:700!important;padding:10px 28px!important;}
.stRadio div[role="radiogroup"]{background:rgba(255,255,255,.03);border-radius:10px;padding:10px;}
.stRadio label{color:#c8c8d8!important;}
.stProgress>div>div{background:linear-gradient(90deg,#00f5d4,#00b4d8)!important;border-radius:4px!important;}
[data-testid="stMetricValue"]{color:#00f5d4!important;font-weight:700!important;}
hr{border-color:rgba(255,255,255,.08)!important;}
</style>
""", unsafe_allow_html=True)

TOTAL_QUESTIONS = 10

# CAT difficulty labels and display config
_DIFF_EMOJI = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
_DIFF_LABEL = {"easy": "EASY", "medium": "MEDIUM", "hard": "HARD"}


def _next_difficulty(current: str, was_correct: bool) -> str:
    """CAT adaptation: correct → move up one level, wrong → move down."""
    levels = ["easy", "medium", "hard"]
    idx = levels.index(current)
    return levels[min(idx + 1, 2) if was_correct else max(idx - 1, 0)]


def _theta_to_mastery(theta: float) -> float:
    return round(1.0 / (1.0 + math.exp(-theta)), 2)


# ── Session state ─────────────────────────────────────────────────────────────
def _init():
    defaults = {
        "diag_idx": 0,
        "diag_answers": [],
        "diag_done": False,
        "diag_selected": None,
        "diag_submitted": False,
        "diag_theta": {},
        "diag_questions": [],           # generated on demand, cached here
        "diag_objectives": None,        # loaded once from backend
        "diag_difficulty": "medium",    # CAT: current difficulty (starts MEDIUM)
        "diag_difficulty_history": [],  # CAT: progression per answered question
        "student_name": "Student",
        "selected_cert_name": "Azure Fundamentals",
        "exam_uid": "exam.az-900",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


def _get_objectives() -> list[dict]:
    """Load objectives once and cache in session state."""
    if st.session_state["diag_objectives"] is None:
        from ui.backend import fetch_objectives
        with st.spinner("Loading exam objectives..."):
            objs = fetch_objectives(st.session_state["exam_uid"])
        st.session_state["diag_objectives"] = objs
    return st.session_state["diag_objectives"]


def _get_or_generate_question(idx: int) -> dict | None:
    """Return cached question at idx, or generate a new one."""
    questions = st.session_state["diag_questions"]
    if idx < len(questions):
        return questions[idx]

    objectives = _get_objectives()
    if not objectives:
        return None

    obj = objectives[idx % len(objectives)]
    # CAT: use the globally tracked difficulty (not theta-derived)
    difficulty = st.session_state.get("diag_difficulty", "medium")

    from ui.backend import generate_question
    with st.spinner(f"Generating question {idx + 1}..."):
        raw = generate_question(
            objective=obj,
            difficulty=difficulty,
            cert_name=st.session_state["selected_cert_name"],
        )

    # Normalize to a consistent internal format
    options_raw = raw.get("options", [])
    options = []
    for opt in options_raw:
        if isinstance(opt, dict):
            options.append((opt.get("key", "?"), opt.get("text", ""), opt.get("is_correct", False)))
        elif isinstance(opt, (list, tuple)) and len(opt) >= 3:
            options.append(tuple(opt))

    # Ensure one correct option
    if options and sum(1 for _, _, c in options if c) != 1:
        options = [(k, t, False) for k, t, _ in options]
        if options:
            options[0] = (options[0][0], options[0][1], True)

    q = {
        "id": f"q{idx+1}",
        "objective_id": obj["id"],
        "objective": obj["name"],
        "stem": raw.get("stem", f"Question about {obj['name']}"),
        "difficulty": difficulty,
        "bloom": raw.get("bloom_level", "understand"),
        "options": options,
        "explanation": raw.get("explanation", ""),
    }
    st.session_state["diag_questions"].append(q)
    return q


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2 style='color:#00f5d4;'>🧬 CertBrain</h2>", unsafe_allow_html=True)
    st.divider()
    phase_progress_sidebar("diagnostic")
    st.divider()
    idx = st.session_state["diag_idx"]
    st.metric("Question", f"{min(idx+1, TOTAL_QUESTIONS)} / {TOTAL_QUESTIONS}")
    answered = len(st.session_state["diag_answers"])
    correct = sum(1 for a in st.session_state["diag_answers"] if a.get("correct"))
    if answered:
        st.metric("Correct so far", f"{correct}/{answered}", f"{correct/answered:.0%}")

# ── Header ────────────────────────────────────────────────────────────────────
cert_name = st.session_state.get("selected_cert_name", "Azure Fundamentals")
student   = st.session_state.get("student_name", "Student")
st.markdown(
    f"<h1 style='color:#e8e8f0;font-size:28px;margin-bottom:4px;'>"
    f"🔬 Diagnostic Assessment</h1>"
    f"<p style='color:#666;font-size:14px;margin-top:0;'>"
    f"{cert_name} · AI-Adaptive Computerized Test · {student}</p>",
    unsafe_allow_html=True,
)

idx  = st.session_state["diag_idx"]
done = st.session_state.get("diag_done", False)

# ── Results view ──────────────────────────────────────────────────────────────
if done:
    answers   = st.session_state["diag_answers"]
    questions = st.session_state["diag_questions"]
    n_correct = sum(1 for a in answers if a.get("correct"))
    score     = n_correct / len(answers) if answers else 0

    st.markdown("<br>", unsafe_allow_html=True)
    score_color = "#00e676" if score >= 0.8 else "#f0c040" if score >= 0.5 else "#e03c3c"
    st.markdown(
        f"""<div style="text-align:center;padding:30px;
            background:rgba(255,255,255,.03);border:1px solid rgba(0,245,212,.15);
            border-radius:16px;margin-bottom:24px;">
            <div style="font-size:56px;font-weight:700;color:{score_color};">{score:.0%}</div>
            <div style="color:#888;font-size:16px;margin-top:4px;">Diagnostic Score</div>
            <div style="color:#555;font-size:12px;margin-top:8px;">
                {n_correct} correct out of {len(answers)} questions
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Per-objective breakdown using theta
    objectives = _get_objectives()
    obj_names = [o["name"] for o in objectives]
    theta = st.session_state["diag_theta"]
    obj_masteries = [_theta_to_mastery(theta.get(o["id"], 0.0)) for o in objectives]

    col_l, col_r = st.columns([1.2, 1])
    with col_l:
        st.plotly_chart(
            create_radar_chart(obj_names, obj_masteries, "Mastery by Exam Area"),
            use_container_width=True,
        )
    with col_r:
        st.markdown("**Mastery by Objective**")
        for name, mv in zip(obj_names, obj_masteries):
            color = "#00e676" if mv >= 0.7 else "#f0c040" if mv >= 0.4 else "#e03c3c"
            st.markdown(
                f"<div style='margin:6px 0;'>"
                f"<span style='color:#ccc;font-size:12px;'>{name}</span>"
                f"<div style='background:#1a1a2e;border-radius:4px;height:8px;margin-top:3px;'>"
                f"<div style='background:{color};width:{mv*100:.0f}%;height:8px;border-radius:4px;'></div>"
                f"</div>"
                f"<span style='color:{color};font-size:11px;font-weight:600;'>{mv:.0%}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        gaps = [n for n, m in zip(obj_names, obj_masteries) if m < 0.5]
        if gaps:
            st.markdown(
                f"<div style='background:rgba(224,60,60,.1);border:1px solid rgba(224,60,60,.3);"
                f"border-radius:8px;padding:10px 14px;font-size:12px;color:#e06060;'>"
                f"⚠️ <b>Gaps identified:</b> {', '.join(gaps)}</div>",
                unsafe_allow_html=True,
            )

    # CAT difficulty progression
    diff_history = st.session_state.get("diag_difficulty_history", [])
    if diff_history:
        _diff_colors_hex = {"easy": "#00e676", "medium": "#f0c040", "hard": "#e03c3c"}

        def _diff_span(d: str) -> str:
            c = _diff_colors_hex.get(d, "#888")
            e = _DIFF_EMOJI.get(d, "🟡")
            l = _DIFF_LABEL.get(d, "?")
            return f"<span style='color:{c};font-weight:600;'>{e}{l}</span>"

        progression_html = " &rarr; ".join(_diff_span(d) for d in diff_history)
        st.markdown(
            f"<div style='background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);"
            f"border-radius:10px;padding:12px 16px;font-size:12px;'>"
            f"<span style='color:#666;'>Difficulty progression: </span>{progression_html}"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Continue to Knowledge Map →", use_container_width=True):
        st.session_state["diagnostic_done"] = True
        # Store objective mastery for downstream pages
        st.session_state["diag_obj_scores"] = {
            o["id"]: _theta_to_mastery(theta.get(o["id"], 0.0))
            for o in objectives
        }
        st.session_state["final_score"] = score
        st.switch_page("pages/02_knowledge_map.py")

# ── Question view ─────────────────────────────────────────────────────────────
elif idx < TOTAL_QUESTIONS:
    q = _get_or_generate_question(idx)
    if q is None:
        st.error("Could not load exam objectives. Check your Azure connection.")
        st.stop()

    progress = idx / TOTAL_QUESTIONS
    st.progress(progress, text=f"Question {idx+1} of {TOTAL_QUESTIONS}")
    st.markdown("<br>", unsafe_allow_html=True)

    col_q, col_meta = st.columns([3, 1])
    with col_meta:
        # CAT difficulty indicator (🟢 EASY / 🟡 MEDIUM / 🔴 HARD)
        diff_key = q["difficulty"]
        diff_colors = {"easy": "#00e676", "medium": "#f0c040", "hard": "#e03c3c"}
        diff_color  = diff_colors.get(diff_key, "#888")
        st.markdown(
            f"<div style='font-size:11px;color:#888;margin-bottom:2px;'>Difficulty</div>"
            f"<div style='font-size:22px;font-weight:700;color:{diff_color};'>"
            f"{_DIFF_EMOJI.get(diff_key,'🟡')} {_DIFF_LABEL.get(diff_key,'MEDIUM')}"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(bloom_badge(q["bloom"]), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        theta_val = st.session_state["diag_theta"].get(q["objective_id"], 0.0)
        mastery_est = _theta_to_mastery(theta_val)
        st.markdown(
            f"<div style='font-size:11px;color:#888;'>Skill estimate</div>"
            f"<div style='font-size:20px;font-weight:700;color:#00f5d4;'>{mastery_est:.0%}</div>",
            unsafe_allow_html=True,
        )
        st.progress(mastery_est)
        st.caption(q["objective"])

    with col_q:
        st.markdown(
            f"""<div style="
                background:rgba(255,255,255,.03);
                border:1px solid rgba(0,245,212,.12);
                border-radius:14px;padding:24px 28px;
                font-size:17px;color:#e8e8f0;line-height:1.6;
                min-height:100px;
            ">{q['stem']}</div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    submitted = st.session_state.get("diag_submitted", False)

    if not submitted:
        option_labels = [f"{key}. {text}" for key, text, _ in q["options"]]
        selected = st.radio(
            "Choose your answer:",
            options=option_labels,
            key=f"radio_{idx}",
            index=None,
        )
        st.session_state["diag_selected"] = selected

        col_btn, _ = st.columns([1, 3])
        with col_btn:
            if st.button("Submit Answer", disabled=selected is None):
                st.session_state["diag_submitted"] = True
                st.rerun()
    else:
        selected    = st.session_state.get("diag_selected", "")
        selected_key = selected[0] if selected else ""
        correct_key  = next((k for k, _, is_c in q["options"] if is_c), "A")
        is_correct   = selected_key == correct_key

        for key, text, is_c in q["options"]:
            if is_c:
                icon, style = "✅", "background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.3);color:#00e676;"
            elif key == selected_key and not is_c:
                icon, style = "❌", "background:rgba(224,60,60,.1);border:1px solid rgba(224,60,60,.3);color:#e03c3c;"
            else:
                icon, style = "  ", "background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);color:#666;"
            st.markdown(
                f"<div style='{style}border-radius:8px;padding:10px 16px;margin:4px 0;font-size:14px;'>"
                f"{icon} <b>{key}.</b> {text}</div>",
                unsafe_allow_html=True,
            )

        if is_correct:
            st.success("✅ Correct!")
        else:
            st.error(f"❌ Incorrect. The correct answer is **{correct_key}**.")

        if q.get("explanation"):
            with st.expander("📖 Explanation", expanded=True):
                st.markdown(
                    f"<div style='color:#bbb;font-size:13px;line-height:1.7;'>"
                    f"{q['explanation']}</div>",
                    unsafe_allow_html=True,
                )

        # Record answer, update theta and CAT difficulty exactly once per question.
        # Guard prevents double-execution when Streamlit re-runs on button clicks.
        if len(st.session_state["diag_answers"]) == idx:
            # IRT theta update (used for mastery estimation in results)
            theta = st.session_state["diag_theta"]
            oid   = q["objective_id"]
            delta_map = {("easy", True): 0.15, ("medium", True): 0.30, ("hard", True): 0.50,
                         ("easy", False): -0.40, ("medium", False): -0.25, ("hard", False): -0.10}
            theta[oid] = max(-2.0, min(2.0, theta.get(oid, 0.0) + delta_map.get((q["difficulty"], is_correct), 0)))
            st.session_state["diag_theta"] = theta

            # CAT: record this question's difficulty and advance to next
            current_diff = st.session_state.get("diag_difficulty", "medium")
            st.session_state["diag_difficulty_history"].append(current_diff)
            st.session_state["diag_difficulty"] = _next_difficulty(current_diff, is_correct)

            st.session_state["diag_answers"].append({
                "question_id": q["id"],
                "objective_id": q["objective_id"],
                "correct": is_correct,
                "selected": selected_key,
                "difficulty": current_diff,
            })

        col_next, _ = st.columns([1, 3])
        with col_next:
            label = "Next Question →" if idx + 1 < TOTAL_QUESTIONS else "View Results →"
            if st.button(label, use_container_width=True):
                st.session_state["diag_idx"] += 1
                st.session_state["diag_submitted"] = False
                st.session_state["diag_selected"]  = None
                if st.session_state["diag_idx"] >= TOTAL_QUESTIONS:
                    st.session_state["diag_done"] = True
                st.rerun()

else:
    st.session_state["diag_done"] = True
    st.rerun()
