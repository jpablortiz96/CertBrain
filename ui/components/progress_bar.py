"""CertBrain — Custom progress & status UI components.

Reusable Streamlit components: phase stepper, mastery gauge, Bloom badge.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------
_PHASES = [
    ("diagnostic",            "🔬", "Diagnostic"),
    ("building_graph",        "🧠", "Knowledge Map"),
    ("planning",              "📋", "Study Plan"),
    ("confirming_plan",       "✅", "Confirm Plan"),
    ("studying",              "📚", "Study Sessions"),
    ("ready_for_assessment",  "🎯", "Ready"),
    ("assessing",             "📝", "Assessment"),
    ("passed",                "🏆", "Passed!"),
    ("needs_review",          "🔄", "Review"),
]

_BLOOM_COLORS = {
    "remember":   ("#e03c3c", "REMEMBER"),
    "understand": ("#e06a2a", "UNDERSTAND"),
    "apply":      ("#d4aa00", "APPLY"),
    "analyze":    ("#4caf50", "ANALYZE"),
    "evaluate":   ("#2196f3", "EVALUATE"),
    "create":     ("#9c27b0", "CREATE"),
}

_DIFF_COLORS = {
    "easy":   ("#4caf50", "🟢"),
    "medium": ("#f0c040", "🟡"),
    "hard":   ("#e03c3c", "🔴"),
}


# ---------------------------------------------------------------------------
# Phase progress stepper
# ---------------------------------------------------------------------------
def phase_progress_sidebar(current_phase: str) -> None:
    """Render the pipeline progress steps in the Streamlit sidebar.

    Uses native Streamlit components only — no raw HTML divs.
    """
    st.sidebar.markdown("**Pipeline Progress**")
    for phase_key, icon, label in _PHASES:
        is_current = phase_key == current_phase
        is_done = _is_before(phase_key, current_phase)
        if is_done:
            st.sidebar.success(f"{icon} {label} ✓")
        elif is_current:
            st.sidebar.info(f"{icon} **{label}** ◀ current")
        else:
            st.sidebar.caption(f"{icon} {label}")


def _is_before(phase_key: str, current: str) -> bool:
    """Return True if *phase_key* comes before *current* in the pipeline."""
    keys = [p[0] for p in _PHASES]
    try:
        return keys.index(phase_key) < keys.index(current)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Mastery gauge
# ---------------------------------------------------------------------------
def mastery_gauge(
    score: float,
    label: str = "Overall Mastery",
    height: int = 220,
) -> go.Figure:
    """Circular gauge chart coloured by mastery level."""
    pct = round(score * 100, 1)
    if pct < 40:
        bar_color = "#e03c3c"
    elif pct < 70:
        bar_color = "#f0c040"
    elif pct < 80:
        bar_color = "#8bc34a"
    else:
        bar_color = "#00e676"

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=pct,
        delta={"reference": 80, "suffix": "%", "font": {"size": 12}},
        number={"suffix": "%", "font": {"size": 28, "color": bar_color}},
        title={"text": label, "font": {"size": 13, "color": "#aaa"}},
        gauge={
            "axis": {
                "range": [0, 100],
                "tickwidth": 1,
                "tickcolor": "#444",
                "tickfont": {"size": 9, "color": "#666"},
            },
            "bar": {"color": bar_color, "thickness": 0.25},
            "bgcolor": "#111120",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 40],  "color": "rgba(224,60,60,0.12)"},
                {"range": [40, 70], "color": "rgba(240,192,64,0.12)"},
                {"range": [70, 80], "color": "rgba(139,195,74,0.12)"},
                {"range": [80, 100],"color": "rgba(0,230,118,0.12)"},
            ],
            "threshold": {
                "line": {"color": "#f0c040", "width": 3},
                "thickness": 0.75,
                "value": 80,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor="#0a0a0f",
        font=dict(color="#eee"),
        height=height,
        margin=dict(t=30, b=10, l=20, r=20),
    )
    return fig


# ---------------------------------------------------------------------------
# Bloom badge
# ---------------------------------------------------------------------------
def bloom_badge(level: str) -> str:
    """Return an HTML string for a coloured Bloom's taxonomy badge."""
    color, label = _BLOOM_COLORS.get(level.lower(), ("#888", level.upper()))
    return (
        f'<span style="'
        f"background:{color}22;border:1px solid {color}88;"
        f"color:{color};border-radius:20px;padding:3px 12px;"
        f"font-size:11px;font-weight:700;font-family:Space Grotesk,sans-serif;"
        f'">{label}</span>'
    )


def difficulty_badge(level: str) -> str:
    """Return an HTML string for a difficulty indicator badge."""
    color, dot = _DIFF_COLORS.get(level.lower(), ("#888", "⚪"))
    return (
        f'<span style="'
        f"background:{color}22;border:1px solid {color}66;"
        f"color:{color};border-radius:20px;padding:3px 10px;"
        f"font-size:11px;font-weight:600;"
        f'">{dot} {level.upper()}</span>'
    )


# ---------------------------------------------------------------------------
# Metric card
# ---------------------------------------------------------------------------
def metric_card(label: str, value: str, delta: str = "", icon: str = "") -> str:
    """Return HTML for a styled metric card."""
    delta_html = (
        f'<div style="font-size:11px;color:#00e676;margin-top:2px;">{delta}</div>'
        if delta else ""
    )
    return (
        f'<div style="'
        f"background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);"
        f"border-radius:10px;padding:14px 16px;text-align:center;"
        f'">'
        f'<div style="font-size:22px;margin-bottom:4px;">{icon}</div>'
        f'<div style="font-size:24px;font-weight:700;color:#00f5d4;">{value}</div>'
        f'<div style="font-size:11px;color:#888;margin-top:2px;">{label}</div>'
        f'{delta_html}'
        f"</div>"
    )
