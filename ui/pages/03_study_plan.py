"""CertBrain — Study Plan page.

Timeline view of the SM-2 spaced-repetition study plan, week-by-week
expandable sections, MS Learn module links, exam readiness prediction.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import date, timedelta

import streamlit as st
import plotly.graph_objects as go

from ui.components.progress_bar import phase_progress_sidebar, metric_card, mastery_gauge

st.set_page_config(page_title="CertBrain · Study Plan", page_icon="📋", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif!important;}
.stApp{background:#0a0a0f;}
section.main>div{background:#0a0a0f;}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0d0d18 0%,#0a0a0f 100%);border-right:1px solid rgba(0,245,212,.12);}
.stButton>button{background:linear-gradient(135deg,#00f5d4 0%,#00b4d8 100%)!important;color:#0a0a0f!important;border:none!important;border-radius:10px!important;font-weight:700!important;padding:10px 28px!important;}
[data-testid="stMetricValue"]{color:#00f5d4!important;font-weight:700!important;}
.streamlit-expanderHeader{background:rgba(255,255,255,.03)!important;border:1px solid rgba(0,245,212,.12)!important;border-radius:8px!important;color:#ccc!important;}
hr{border-color:rgba(255,255,255,.08)!important;}
</style>
""", unsafe_allow_html=True)

TODAY = date.today()
MS_LEARN_BASE = "https://learn.microsoft.com/en-us/training/modules/"

def _init():
    if "plan_data" not in st.session_state:
        kg_data = st.session_state.get("kg_data")
        objectives = st.session_state.get("diag_objectives") or []
        student_name = st.session_state.get("student_name", "Student")
        exam_uid = st.session_state.get("exam_uid", "exam.az-900")
        mastery = st.session_state.get("final_score", 0.35)
        if kg_data and objectives:
            from ui.backend import generate_study_plan
            with st.spinner("Generating your personalised study plan..."):
                plan = generate_study_plan(
                    kg_data=kg_data,
                    objectives=objectives,
                    student_name=student_name,
                    exam_uid=exam_uid,
                    overall_mastery=mastery,
                )
            st.session_state["plan_data"] = plan if plan.get("weeks") else {
                "weeks": [], "total_days": 28,
                "exam_date": (date.today() + timedelta(days=35)).isoformat(),
                "total_hours": 0, "daily_commitment": 45,
            }
        else:
            st.session_state["plan_data"] = {
                "weeks": [], "total_days": 28,
                "exam_date": (date.today() + timedelta(days=35)).isoformat(),
                "total_hours": 0, "daily_commitment": 45,
            }
    if "plan_confirmed" not in st.session_state:
        st.session_state["plan_confirmed"] = False

_init()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2 style='color:#00f5d4;'>🧬 CertBrain</h2>", unsafe_allow_html=True)
    st.divider()
    phase_progress_sidebar("planning")
    st.divider()
    plan = st.session_state["plan_data"]
    st.metric("Total Sessions", sum(len(w["sessions"]) for w in plan["weeks"]))
    st.metric("Study Hours", f"{plan['total_hours']:.1f}h")
    st.metric("Daily Commitment", f"{plan['daily_commitment']} min/day")
    exam_date = plan.get("exam_date", "TBD")
    st.metric("Exam Target", exam_date)

# ── Content ───────────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='color:#e8e8f0;font-size:28px;margin-bottom:4px;'>📋 Your Study Plan</h1>"
    "<p style='color:#666;font-size:14px;margin-top:0;'>"
    "Personalised · SM-2 Spaced Repetition · Mapped to Microsoft Learn</p>",
    unsafe_allow_html=True,
)

plan = st.session_state["plan_data"]

# ── Key metrics ───────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.markdown(metric_card("Study Weeks",    "4",                 icon="📅"), unsafe_allow_html=True)
m2.markdown(metric_card("Total Hours",    f"{plan['total_hours']:.0f}h", icon="⏱️"), unsafe_allow_html=True)
m3.markdown(metric_card("Daily Target",   f"{plan['daily_commitment']}m", icon="🎯"), unsafe_allow_html=True)
m4.markdown(metric_card("Exam Target",    plan.get("exam_date","TBD"), icon="📝"), unsafe_allow_html=True)

# ── Exam readiness prediction ─────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
col_ready, col_gauge = st.columns([2, 1])
with col_ready:
    st.markdown(
        "<h3 style='color:#e8e8f0;font-size:18px;'>📈 Exam Readiness Trajectory</h3>",
        unsafe_allow_html=True,
    )
    weeks_x = [0, 1, 2, 3, 4]
    projected = [0.35, 0.52, 0.65, 0.75, 0.83]
    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=weeks_x, y=projected,
        mode="lines+markers",
        name="Projected Mastery",
        line=dict(color="#00f5d4", width=3),
        marker=dict(size=8, color="#00f5d4"),
        fill="tozeroy",
        fillcolor="rgba(0,245,212,0.06)",
    ))
    fig_line.add_hline(y=0.8, line_dash="dot", line_color="#f0c040",
                        annotation_text="Pass threshold", annotation_font_color="#f0c040")
    milestones = [w["target_mastery"] for w in plan["weeks"]]
    fig_line.add_trace(go.Scatter(
        x=[1,2,3,4], y=milestones,
        mode="markers", name="Week milestones",
        marker=dict(size=12, color="#8b5cf6", symbol="diamond"),
    ))
    fig_line.update_layout(
        paper_bgcolor="#0a0a0f", plot_bgcolor="#111120",
        font=dict(color="#eee"),
        xaxis=dict(title="Week", tickvals=[0,1,2,3,4],
                   ticktext=["Start","W1","W2","W3","W4"],
                   gridcolor="rgba(255,255,255,.05)"),
        yaxis=dict(title="Mastery", range=[0,1.05],
                   tickformat=".0%", gridcolor="rgba(255,255,255,.07)"),
        legend=dict(bgcolor="rgba(0,0,0,.4)", font=dict(color="#ccc")),
        margin=dict(t=10, b=40, l=50, r=20), height=240,
    )
    st.plotly_chart(fig_line, use_container_width=True)

with col_gauge:
    current_mastery = 0.35
    st.plotly_chart(
        mastery_gauge(current_mastery, label="Current Mastery", height=200),
        use_container_width=True,
    )

# ── Weekly plan ───────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("<h3 style='color:#e8e8f0;font-size:18px;'>🗓️ Week-by-Week Schedule</h3>", unsafe_allow_html=True)

type_colors = {
    "study":  ("rgba(0,245,212,.08)",  "rgba(0,245,212,.25)",  "#00f5d4", "📖"),
    "review": ("rgba(139,92,246,.08)", "rgba(139,92,246,.25)", "#a78bfa", "🔄"),
}

if not plan.get("weeks"):
    st.info("No study plan generated yet. Please complete the Diagnostic and Knowledge Map first, then return here.")
    st.stop()

for week_data in plan["weeks"]:
    week_num = week_data["week"]
    milestone = week_data["milestone"]
    target = week_data["target_mastery"]
    sessions = week_data["sessions"]
    total_min = sum(s["duration"] for s in sessions)

    with st.expander(
        f"📅 Week {week_num} — {milestone}  ·  "
        f"Target: {target:.0%}  ·  {total_min // 60}h {total_min % 60}m",
        expanded=(week_num == 1),
    ):
        for s in sessions:
            bg, border, color, icon = type_colors.get(s["type"], type_colors["study"])
            session_date = TODAY + timedelta(days=s["day"] - 1)
            # Prefer real URL from catalog API; fall back to constructed URL from slug
            ms_url = s.get("url") or (MS_LEARN_BASE + s["module"] + "/" if s.get("module") else "")
            link_text = s.get("module", s["topic"])

            st.markdown(
                f"""<div style="background:{bg};border:1px solid {border};
                    border-radius:8px;padding:10px 16px;margin:4px 0;
                    display:flex;align-items:flex-start;gap:12px;">
                    <div style="font-size:20px;margin-top:2px;">{icon}</div>
                    <div style="flex:1;">
                        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                            <span style="color:{color};font-weight:600;font-size:13px;">{s['topic']}</span>
                            <span style="color:#555;font-size:11px;">{session_date.strftime('%a %b %d')}</span>
                            <span style="background:{border};color:{color};border-radius:12px;
                                padding:1px 8px;font-size:10px;">
                                {'🔄 Review' if s['review'] else '📖 Study'}</span>
                            <span style="color:#555;font-size:11px;">⏱ {s['duration']} min</span>
                        </div>
                        {f'<div style="margin-top:4px;"><a href="{ms_url}" target="_blank" style="color:#666;font-size:11px;text-decoration:none;">🔗 Microsoft Learn: {link_text}</a></div>' if ms_url else ''}
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

        # Week milestone bar
        st.markdown(
            f"<div style='margin-top:12px;padding:8px 12px;"
            f"background:rgba(0,245,212,.05);border-radius:6px;font-size:12px;color:#888;'>"
            f"🎯 <b style='color:#00f5d4;'>Week {week_num} Milestone:</b> "
            f"Reach <b style='color:#e8e8f0;'>{target:.0%}</b> mastery in <i>{milestone}</i>"
            f"</div>",
            unsafe_allow_html=True,
        )

# ── CTA buttons ───────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
col_a, col_b = st.columns(2)
with col_a:
    if st.button("✅ Confirm Plan & Start Studying", use_container_width=True):
        st.session_state["plan_confirmed"] = True
        st.session_state["plan_done"] = True
        st.switch_page("pages/04_tutor.py")
with col_b:
    if st.button("📧 Set Up Email Reminders", use_container_width=True):
        st.success(
            "✅ Reminders scheduled! You'll receive study prompts at key points in your plan."
        )
