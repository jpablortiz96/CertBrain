"""CertBrain — Knowledge Graph visualization component.

Creates interactive Plotly network graphs from KnowledgeGraph data.
Nodes are colored by mastery level (red/yellow/green), sized by exam
weight, and the layout uses NetworkX spring positioning.
"""

from __future__ import annotations

from typing import Any

import math
import networkx as nx
import plotly.graph_objects as go


def _mastery_to_color(mastery: float) -> str:
    """Map mastery (0-1) to a hex color on the red-yellow-green gradient."""
    if mastery < 0.3:
        # Red → Orange  (0 to 0.3)
        t = mastery / 0.3
        r, g = 220, int(60 + 120 * t)
        return f"rgb({r},{g},60)"
    elif mastery < 0.7:
        # Orange → Yellow  (0.3 to 0.7)
        t = (mastery - 0.3) / 0.4
        r, g = int(220 - 20 * t), int(180 + 40 * t)
        return f"rgb({r},{g},60)"
    else:
        # Yellow-green → Bright green  (0.7 to 1.0)
        t = (mastery - 0.7) / 0.3
        r, g = int(200 - 170 * t), int(220 + 15 * t)
        return f"rgb({r},{g},80)"


def _mastery_category(mastery: float) -> str:
    if mastery < 0.3:
        return "Not Yet Learned"
    if mastery < 0.7:
        return "In Progress (ZPD)"
    return "Mastered"


def create_knowledge_graph_figure(
    kg_data: dict[str, Any],
    title: str = "Knowledge Map",
    bg_color: str = "#0a0a0f",
    height: int = 600,
) -> go.Figure:
    """Build an interactive Plotly network graph from serialised KG data.

    Parameters
    ----------
    kg_data:
        Dict produced by ``KnowledgeGraph.to_dict()`` with keys
        ``"nodes"`` and ``"edges"``.
    title:
        Figure title.
    bg_color:
        Background colour (hex).
    height:
        Figure height in pixels.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    nodes: list[dict[str, Any]] = kg_data.get("nodes", [])
    edges: list[dict[str, Any]] = kg_data.get("edges", [])

    if not nodes:
        fig = go.Figure()
        fig.add_annotation(
            text="No knowledge graph data yet",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color="#888", size=16),
        )
        fig.update_layout(
            paper_bgcolor=bg_color, plot_bgcolor=bg_color, height=height,
        )
        return fig

    # Build NetworkX graph for layout
    G = nx.DiGraph()
    node_map: dict[str, dict[str, Any]] = {}
    for n in nodes:
        nid = n["id"]
        G.add_node(nid)
        node_map[nid] = n

    for e in edges:
        G.add_edge(e["source"], e["target"])

    # Spring layout
    seed = 42
    try:
        pos = nx.spring_layout(G, k=2.5, iterations=80, seed=seed)
    except Exception:
        pos = {nid: (math.cos(2 * math.pi * i / len(nodes)),
                     math.sin(2 * math.pi * i / len(nodes)))
               for i, nid in enumerate(node_map)}

    # ---- Edge traces (one per edge for arrow-like lines) ----
    edge_traces: list[go.Scatter] = []
    for e in edges:
        src, tgt = e["source"], e["target"]
        if src not in pos or tgt not in pos:
            continue
        x0, y0 = pos[src]
        x1, y1 = pos[tgt]
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=1.5, color="rgba(0,245,212,0.25)"),
            hoverinfo="none",
            showlegend=False,
        ))

    # ---- Arrow annotations ----
    annotations: list[dict[str, Any]] = []
    for e in edges:
        src, tgt = e["source"], e["target"]
        if src not in pos or tgt not in pos:
            continue
        x0, y0 = pos[src]
        x1, y1 = pos[tgt]
        annotations.append(dict(
            ax=x0, ay=y0, axref="x", ayref="y",
            x=x1, y=y1, xref="x", yref="y",
            showarrow=True,
            arrowhead=3, arrowsize=1.2, arrowwidth=1.5,
            arrowcolor="rgba(0,245,212,0.4)",
        ))

    # ---- Node traces by category ----
    categories = {
        "Not Yet Learned":  [],
        "In Progress (ZPD)": [],
        "Mastered":          [],
    }

    node_x: dict[str, list[float]] = {c: [] for c in categories}
    node_y: dict[str, list[float]] = {c: [] for c in categories}
    node_text: dict[str, list[str]] = {c: [] for c in categories}
    node_hover: dict[str, list[str]] = {c: [] for c in categories}
    node_sizes: dict[str, list[float]] = {c: [] for c in categories}
    node_colors: dict[str, list[str]] = {c: [] for c in categories}

    for nid, data in node_map.items():
        if nid not in pos:
            continue
        mastery = float(data.get("mastery", 0.0))
        cat = _mastery_category(mastery)
        x, y = pos[nid]
        weight = float(data.get("weight_percent", 5.0))
        size = max(14, min(40, 14 + weight * 0.8))

        deps = [e["target"] for e in edges if e["source"] == nid]
        prereqs = [e["source"] for e in edges if e["target"] == nid]

        hover = (
            f"<b>{data.get('name', nid)}</b><br>"
            f"Mastery: {mastery:.0%}<br>"
            f"Category: {cat}<br>"
            f"Exam weight: {weight:.1f}%<br>"
            f"Prerequisites: {', '.join(prereqs) or 'none'}<br>"
            f"Unlocks: {', '.join(deps) or 'none'}"
        )

        node_x[cat].append(x)
        node_y[cat].append(y)
        node_text[cat].append(data.get("name", nid)[:18])
        node_hover[cat].append(hover)
        node_sizes[cat].append(size)
        node_colors[cat].append(_mastery_to_color(mastery))

    cat_colors_fixed = {
        "Not Yet Learned":   "#e03c3c",
        "In Progress (ZPD)": "#f0c040",
        "Mastered":          "#00e676",
    }

    node_traces: list[go.Scatter] = []
    for cat in categories:
        if not node_x[cat]:
            continue
        node_traces.append(go.Scatter(
            x=node_x[cat], y=node_y[cat],
            mode="markers+text",
            name=cat,
            marker=dict(
                size=node_sizes[cat],
                color=node_colors[cat],
                line=dict(width=2, color="rgba(255,255,255,0.15)"),
                symbol="circle",
            ),
            text=node_text[cat],
            textposition="top center",
            textfont=dict(size=9, color="rgba(255,255,255,0.85)"),
            hovertext=node_hover[cat],
            hovertemplate="%{hovertext}<extra></extra>",
        ))

    all_traces = edge_traces + node_traces

    fig = go.Figure(
        data=all_traces,
        layout=go.Layout(
            title=dict(
                text=title,
                font=dict(color="#00f5d4", size=18, family="Space Grotesk"),
            ),
            showlegend=True,
            legend=dict(
                x=0.01, y=0.99,
                bgcolor="rgba(10,10,20,0.7)",
                bordercolor="rgba(0,245,212,0.3)",
                borderwidth=1,
                font=dict(color="#ccc", size=11),
            ),
            hovermode="closest",
            annotations=annotations,
            margin=dict(b=20, l=5, r=5, t=50),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            paper_bgcolor=bg_color,
            plot_bgcolor=bg_color,
            height=height,
        ),
    )
    return fig


def create_radar_chart(
    objectives: list[str],
    scores: list[float],
    title: str = "Objective Scores",
) -> go.Figure:
    """Radar / spider chart for per-objective mastery scores."""
    if not objectives:
        return go.Figure()

    # Close the radar polygon
    objs = objectives + [objectives[0]]
    vals = scores + [scores[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=vals,
        theta=objs,
        fill="toself",
        fillcolor="rgba(0,245,212,0.15)",
        line=dict(color="#00f5d4", width=2),
        name="Your Score",
    ))
    fig.add_trace(go.Scatterpolar(
        r=[0.8] * len(objs),
        theta=objs,
        fill="toself",
        fillcolor="rgba(255,255,255,0.04)",
        line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"),
        name="Pass threshold (80%)",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="#111120",
            radialaxis=dict(
                visible=True, range=[0, 1],
                tickfont=dict(color="#888", size=9),
                gridcolor="rgba(255,255,255,0.08)",
                linecolor="rgba(255,255,255,0.1)",
            ),
            angularaxis=dict(
                tickfont=dict(color="#ccc", size=10),
                linecolor="rgba(255,255,255,0.1)",
            ),
        ),
        paper_bgcolor="#0a0a0f",
        plot_bgcolor="#0a0a0f",
        font=dict(color="#eee"),
        title=dict(text=title, font=dict(color="#00f5d4", size=15)),
        legend=dict(
            bgcolor="rgba(10,10,20,0.8)",
            font=dict(color="#ccc"),
        ),
        margin=dict(t=60, b=20, l=20, r=20),
        height=380,
    )
    return fig


def create_score_comparison_bar(
    objectives: list[str],
    before: list[float],
    after: list[float],
) -> go.Figure:
    """Grouped bar chart: diagnostic score vs assessment score per objective."""
    fig = go.Figure(data=[
        go.Bar(
            name="Diagnostic (before)",
            x=objectives, y=before,
            marker_color="rgba(100,120,200,0.7)",
            marker_line=dict(width=0),
        ),
        go.Bar(
            name="Assessment (after)",
            x=objectives, y=after,
            marker_color="rgba(0,245,212,0.85)",
            marker_line=dict(width=0),
        ),
    ])
    fig.add_hline(
        y=0.8, line_dash="dot", line_color="rgba(255,200,0,0.6)",
        annotation_text="Pass 80%",
        annotation_font_color="#f0c040",
    )
    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0a0a0f",
        plot_bgcolor="#111120",
        font=dict(color="#eee"),
        legend=dict(bgcolor="rgba(0,0,0,0.4)", font=dict(color="#ccc")),
        xaxis=dict(
            tickangle=-30, tickfont=dict(size=10),
            gridcolor="rgba(255,255,255,0.05)",
        ),
        yaxis=dict(
            range=[0, 1.05], title="Score",
            gridcolor="rgba(255,255,255,0.07)",
        ),
        margin=dict(t=20, b=80, l=40, r=20),
        height=320,
    )
    return fig
