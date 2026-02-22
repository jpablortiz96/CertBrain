"""CertBrain — Final Assessment page.

Exam-like interface with timer, progress bar, and a dramatic result reveal.
Pass >= 80% triggers balloons + celebration. Fail shows analysis + retry path.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import time
from datetime import date, timedelta

import streamlit as st
import plotly.graph_objects as go

from ui.components.progress_bar import phase_progress_sidebar, difficulty_badge
from ui.components.brain_viz import create_score_comparison_bar

st.set_page_config(page_title="CertBrain · Assessment", page_icon="📝", layout="wide")

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

TOTAL_ASSESSMENT_QUESTIONS = 10
EXAM_DURATION_SECONDS = 1800

def _init():
    defaults = {
        "assess_idx": 0,
        "assess_answers": [],
        "assess_done": False,
        "assess_selected": None,
        "assess_submitted": False,
        "assess_start_time": None,
        "assess_questions": [],    # AI-generated, cached
        "student_name": "Student",
        "selected_cert_name": "Azure Fundamentals",
        "exam_uid": "exam.az-900",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2 style='color:#00f5d4;'>🧬 CertBrain</h2>", unsafe_allow_html=True)
    st.divider()
    phase_progress_sidebar("assessing")
    st.divider()
    idx = st.session_state["assess_idx"]
    total = TOTAL_ASSESSMENT_QUESTIONS
    st.metric("Question", f"{min(idx+1, total)} / {total}")
    answered = len(st.session_state["assess_answers"])
    correct  = sum(1 for a in st.session_state["assess_answers"] if a.get("correct"))
    if answered:
        st.metric("Running Score", f"{correct/answered:.0%}")

    # Timer
    if st.session_state.get("assess_start_time") and not st.session_state["assess_done"]:
        elapsed = time.time() - st.session_state["assess_start_time"]
        remaining = max(0, EXAM_DURATION_SECONDS - int(elapsed))
        mins, secs = divmod(remaining, 60)
        color = "#e03c3c" if remaining < 300 else "#f0c040" if remaining < 600 else "#00f5d4"
        st.markdown(
            f"<div style='text-align:center;font-size:28px;font-weight:700;"
            f"color:{color};font-family:monospace;'>{mins:02d}:{secs:02d}</div>"
            f"<div style='text-align:center;color:#555;font-size:11px;'>Time remaining</div>",
            unsafe_allow_html=True,
        )

# ── Header ────────────────────────────────────────────────────────────────────
cert = st.session_state.get("selected_cert_name", "Azure Fundamentals")
st.markdown(
    f"<h1 style='color:#e8e8f0;font-size:28px;margin-bottom:4px;'>📝 Final Assessment</h1>"
    f"<p style='color:#666;font-size:14px;margin-top:0;'>"
    f"{cert} · AI Exam Simulation · {TOTAL_ASSESSMENT_QUESTIONS} questions</p>",
    unsafe_allow_html=True,
)

idx  = st.session_state["assess_idx"]
done = st.session_state["assess_done"]


def _get_or_generate_assessment_question(idx: int) -> dict | None:
    """Return cached assessment question or generate a new one."""
    questions = st.session_state["assess_questions"]
    if idx < len(questions):
        return questions[idx]

    objectives = st.session_state.get("diag_objectives") or []
    if not objectives:
        from ui.backend import fetch_objectives
        objectives = fetch_objectives(st.session_state.get("exam_uid", "exam.az-900"))
        st.session_state["diag_objectives"] = objectives

    if not objectives:
        return None

    obj = objectives[idx % len(objectives)]
    difficulty = ["medium", "hard", "medium", "hard", "medium",
                  "hard", "medium", "hard", "medium", "hard"][idx % 10]

    from ui.backend import generate_assessment_question
    with st.spinner(f"Generating question {idx + 1}..."):
        raw = generate_assessment_question(
            objective=obj,
            difficulty=difficulty,
            cert_name=st.session_state.get("selected_cert_name", "Azure Fundamentals"),
        )

    options_raw = raw.get("options", [])
    options = []
    for opt in options_raw:
        if isinstance(opt, dict):
            options.append((opt.get("key", "?"), opt.get("text", ""), opt.get("is_correct", False)))
        elif isinstance(opt, (list, tuple)) and len(opt) >= 3:
            options.append(tuple(opt))

    if options and sum(1 for _, _, c in options if c) != 1:
        options = [(k, t, False) for k, t, _ in options]
        if options:
            options[0] = (options[0][0], options[0][1], True)

    q = {
        "id": f"a{idx+1}",
        "objective_id": obj["id"],
        "objective": obj["name"],
        "stem": raw.get("stem", f"Question about {obj['name']}"),
        "difficulty": difficulty,
        "options": options,
        "explanation": raw.get("explanation", ""),
    }
    st.session_state["assess_questions"].append(q)
    return q

# ── Results view ──────────────────────────────────────────────────────────────
if done:
    answers   = st.session_state["assess_answers"]
    n_correct = sum(1 for a in answers if a.get("correct"))
    score     = n_correct / len(answers) if answers else 0
    passed    = score >= 0.80

    if passed:
        st.balloons()

    # Score display
    score_color = "#00e676" if passed else "#e03c3c"
    st.markdown(
        f"""<div style="text-align:center;padding:36px;
            background:{'rgba(0,230,118,.07)' if passed else 'rgba(224,60,60,.07)'};
            border:2px solid {'rgba(0,230,118,.3)' if passed else 'rgba(224,60,60,.3)'};
            border-radius:20px;margin-bottom:28px;">
            <div style="font-size:72px;font-weight:800;color:{score_color};">{score:.0%}</div>
            <div style="font-size:24px;margin-top:8px;color:#e8e8f0;font-weight:600;">
                {'🏆 Congratulations! You PASSED!' if passed else '📚 Keep Going — You Got This!'}
            </div>
            <div style="color:#888;font-size:14px;margin-top:8px;">
                {n_correct} correct out of {len(answers)} questions ·
                {'Ready for the real exam!' if passed else f'{0.80-score:.0%} more to reach the pass threshold'}
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    if passed:
        exam_date = (date.today() + timedelta(days=14)).strftime("%B %d, %Y")
        st.markdown(
            f"""<div style="background:rgba(0,245,212,.07);border:1px solid rgba(0,245,212,.25);
                border-radius:14px;padding:20px;margin-bottom:20px;">
                <div style="color:#00f5d4;font-weight:600;font-size:16px;">📅 Recommended Exam Date</div>
                <div style="color:#e8e8f0;font-size:20px;font-weight:700;margin-top:8px;">{exam_date}</div>
                <div style="margin-top:12px;">
                    <a href="https://learn.microsoft.com/en-us/certifications/exams/az-900/"
                       target="_blank"
                       style="color:#00b4d8;font-size:13px;">
                        🔗 Register for AZ-900 on Microsoft Learn →
                    </a>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        # Show weak areas
        obj_results: dict[str, dict] = {}
        for a in answers:
            oid = a.get("objective_id", "")
            obj_name = a.get("objective", oid)
            if obj_name not in obj_results:
                obj_results[obj_name] = {"correct": 0, "total": 0}
            obj_results[obj_name]["total"] += 1
            if a.get("correct"):
                obj_results[obj_name]["correct"] += 1

        weak = [(name, d["correct"]/d["total"])
                for name, d in obj_results.items()
                if d["total"] > 0 and d["correct"]/d["total"] < 0.6]
        weak.sort(key=lambda x: x[1])
        if weak:
            st.markdown("**Areas to focus on:**")
            for name, s in weak:
                st.markdown(
                    f"<div style='background:rgba(224,60,60,.08);border:1px solid rgba(224,60,60,.2);"
                    f"border-radius:8px;padding:10px 14px;margin:4px 0;font-size:13px;'>"
                    f"⚠️ <b style='color:#e03c3c;'>{name}</b> — Score: {s:.0%}</div>",
                    unsafe_allow_html=True,
                )

    # Before / After comparison
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**📊 Before vs After Comparison**")
    before_scores_map = st.session_state.get("diag_obj_scores", {})
    after_results: dict[str, list] = {}
    for a in answers:
        obj_name = a.get("objective", "")
        if obj_name not in after_results:
            after_results[obj_name] = []
        after_results[obj_name].append(1.0 if a.get("correct") else 0.0)
    after_scores = {name: sum(vals)/len(vals) for name, vals in after_results.items() if vals}

    # Build obj names from the answers themselves
    common_objs = list(dict.fromkeys(a.get("objective", "") for a in answers if a.get("objective")))
    before_vals = [before_scores_map.get(n, 0.5) for n in common_objs]
    after_vals  = [after_scores.get(n, score) for n in common_objs]

    if common_objs:
        st.plotly_chart(
            create_score_comparison_bar(common_objs, before_vals, after_vals),
            use_container_width=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    if not passed:
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("📚 Create Revised Study Plan", use_container_width=True):
                # Reset for another loop
                for k in ["assess_idx", "assess_answers", "assess_done",
                          "assess_submitted", "assess_start_time"]:
                    st.session_state[k] = 0 if k == "assess_idx" else \
                                          [] if k == "assess_answers" else \
                                          False if isinstance(st.session_state[k], bool) else None
                st.switch_page("pages/03_study_plan.py")
        with col_b:
            if st.button("🔁 Retake Assessment", use_container_width=True):
                for k in ["assess_idx", "assess_answers", "assess_done",
                          "assess_submitted", "assess_start_time"]:
                    st.session_state[k] = 0 if k == "assess_idx" else \
                                          [] if k == "assess_answers" else \
                                          False if isinstance(st.session_state[k], bool) else None
                st.rerun()

# ── Question view ─────────────────────────────────────────────────────────────
elif idx < TOTAL_ASSESSMENT_QUESTIONS:
    # Start timer on first question
    if st.session_state["assess_start_time"] is None:
        st.session_state["assess_start_time"] = time.time()

    q = _get_or_generate_assessment_question(idx)
    if q is None:
        st.error("Could not generate question. Check your Azure connection.")
        st.stop()

    # Solemn progress header
    progress = idx / TOTAL_ASSESSMENT_QUESTIONS
    remaining_q = TOTAL_ASSESSMENT_QUESTIONS - idx
    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:center;"
        f"margin-bottom:8px;'>"
        f"<span style='color:#888;font-size:12px;'>Question {idx+1} of {TOTAL_ASSESSMENT_QUESTIONS}</span>"
        f"<span style='color:#555;font-size:12px;'>{remaining_q} remaining</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.progress(progress)
    st.markdown("<br>", unsafe_allow_html=True)

    col_q, col_meta = st.columns([3, 1])
    with col_meta:
        st.markdown(difficulty_badge(q["difficulty"]), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:11px;color:#555;'>Objective</div>"
            f"<div style='font-size:12px;color:#888;font-weight:500;'>{q['objective']}</div>",
            unsafe_allow_html=True,
        )

    with col_q:
        st.markdown(
            f"""<div style="
                background:rgba(255,255,255,.025);
                border:1px solid rgba(255,255,255,.08);
                border-left:3px solid #00f5d4;
                border-radius:12px;padding:24px 28px;
                font-size:17px;color:#e8e8f0;line-height:1.65;
            ">{q['stem']}</div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    submitted = st.session_state.get("assess_submitted", False)

    if not submitted:
        option_labels = [f"{key}. {text}" for key, text, _ in q["options"]]
        selected = st.radio("Select your answer:", option_labels, key=f"assess_radio_{idx}", index=None)
        st.session_state["assess_selected"] = selected

        col_btn, _ = st.columns([1, 3])
        with col_btn:
            if st.button("Submit Answer", disabled=selected is None):
                st.session_state["assess_submitted"] = True
                st.rerun()
    else:
        selected   = st.session_state.get("assess_selected", "")
        sel_key    = selected[0] if selected else ""
        correct_key = next(k for k, _, is_c in q["options"] if is_c)
        is_correct  = sel_key == correct_key

        for key, text, is_c in q["options"]:
            if is_c:
                icon, style = "✅", "background:rgba(0,230,118,.1);border:1px solid rgba(0,230,118,.3);color:#00e676;"
            elif key == sel_key and not is_c:
                icon, style = "❌", "background:rgba(224,60,60,.08);border:1px solid rgba(224,60,60,.3);color:#e03c3c;"
            else:
                icon, style = "  ", "background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.05);color:#555;"
            st.markdown(
                f"<div style='{style}border-radius:8px;padding:10px 16px;margin:4px 0;font-size:14px;'>"
                f"{icon} <b>{key}.</b> {text}</div>",
                unsafe_allow_html=True,
            )

        if is_correct:
            st.success("✅ Correct!")
        else:
            st.error(f"❌ Incorrect. The correct answer was **{correct_key}**.")

        with st.expander("📖 Show Explanation"):
            st.markdown(
                f"<div style='color:#bbb;font-size:13px;line-height:1.7;'>{q['explanation']}</div>",
                unsafe_allow_html=True,
            )

        st.session_state["assess_answers"].append({
            "question_id": q["id"],
            "objective_id": q["objective_id"],
            "objective": q["objective"],
            "correct": is_correct,
        })

        col_next, _ = st.columns([1, 3])
        with col_next:
            label = "Next Question →" if idx + 1 < TOTAL_ASSESSMENT_QUESTIONS else "View Results →"
            if st.button(label, use_container_width=True):
                st.session_state["assess_idx"] += 1
                st.session_state["assess_submitted"] = False
                st.session_state["assess_selected"]  = None
                if st.session_state["assess_idx"] >= TOTAL_ASSESSMENT_QUESTIONS:
                    st.session_state["assess_done"] = True
                st.rerun()

else:
    st.session_state["assess_done"] = True
    st.rerun()
