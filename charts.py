"""Gemensam, modern stil för alla Plotly-diagram i appen.

Principer (dataviz-metoden):
- Lugn bakgrund: transparent, hårfina heldragna stödlinjer, inga axellinjer.
- Data är det enda som får synas: 2 px linjer, 10 % ton under ytor, tunna staplar med rundade hörn.
- Kategorifärger i fast ordning (validerade för färgblindhet mot appens mörka bakgrund).
- Text i textfärger – aldrig i seriefärgen.
Använd: charts.show(fig) i stället för st.plotly_chart(fig).
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

SURFACE = "#0C1A17"
INK = "#F4EFE6"
INK_2 = "#A8B5AE"
INK_3 = "#6F7F78"
GRID = "rgba(244,239,230,0.07)"

ACCENT = "#E8B44C"     # portföljen / huvudserien
POS = "#4ADE80"        # upp / vinst
NEG = "#F87171"        # ned / förlust
NEUTRAL = "#8A9A93"    # insatta pengar, referenslinjer

# Kategoriska färger i fast ordning (validerade: CVD ΔE ≥ 8,4 mellan grannar på mörk yta)
CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]
SEQUENTIAL_BLUE = ["#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef"]

FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"


def _axis(**overrides) -> dict:
    base = dict(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, showline=False,
                ticks="", tickfont=dict(color=INK_3, size=11), title=dict(font=dict(color=INK_2, size=12)),
                showspikes=True, spikemode="across", spikethickness=1, spikedash="solid",
                spikecolor="rgba(244,239,230,0.25)", spikesnap="cursor")
    base.update(overrides)
    return base


_template = go.layout.Template(
    layout=dict(
        font=dict(family=FONT, color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=CATEGORICAL,
        margin=dict(t=36, r=12, b=8, l=8),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="rgba(20,39,33,0.96)", bordercolor="rgba(244,239,230,0.12)",
                        font=dict(family=FONT, color=INK, size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color=INK_2, size=12), itemclick="toggleothers"),
        xaxis=_axis(showgrid=False), yaxis=_axis(),
        barcornerradius=4, bargap=0.35,
        separators=", ",
        title=dict(font=dict(size=14, color=INK_2), x=0, xanchor="left"),
    ),
    data=dict(
        scatter=[go.Scatter(line=dict(width=2, shape="linear"), marker=dict(size=8, line=dict(width=2, color=SURFACE)))],
        bar=[go.Bar(marker=dict(line=dict(width=0)))],
        pie=[go.Pie(marker=dict(line=dict(color=SURFACE, width=2)), sort=False)],
    ),
)
pio.templates["aktie"] = _template
pio.templates.default = "plotly_dark+aktie"


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def show(fig: go.Figure, where=None, height: int | None = None, **kwargs) -> None:
    """Visar diagrammet med appens stil (Streamlits egen tema stängs av så att vår mall gäller)."""
    if height:
        fig.update_layout(height=height)
    (where or st).plotly_chart(fig, use_container_width=True, theme=None,
                               config={"displayModeBar": False}, **kwargs)
