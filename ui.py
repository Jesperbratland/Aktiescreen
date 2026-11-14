"""Formatering och gemensam styling."""
from __future__ import annotations

import math

import streamlit as st

POS = "#22C55E"
NEG = "#EF4444"
NEU = "#94A3B8"
ACCENT = "#3B82F6"


def _isnan(x) -> bool:
    try:
        return x is None or (isinstance(x, float) and math.isnan(x))
    except Exception:
        return False


def fmt_num(x, decimals: int = 0) -> str:
    """Svensk talformatering: 1 234 567,89"""
    if _isnan(x):
        return "–"
    s = f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",")


def fmt_sek(x, decimals: int = 0) -> str:
    return "–" if _isnan(x) else f"{fmt_num(x, decimals)} kr"


def fmt_pct(x, decimals: int = 1, sign: bool = True) -> str:
    """x anges som andel (0.05 = 5 %)."""
    if _isnan(x):
        return "–"
    s = f"{x * 100:+.{decimals}f}" if sign else f"{x * 100:.{decimals}f}"
    return s.replace(".", ",") + " %"


def fmt_big(x) -> str:
    """Stora belopp: 1,2 mdr / 345 mn"""
    if _isnan(x):
        return "–"
    for div, suf in ((1e12, "bn"), (1e9, "mdr"), (1e6, "mn")):
        if abs(x) >= div:
            return f"{fmt_num(x / div, 1)} {suf}"
    return fmt_num(x, 0)


CSS = """
.block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px;}
[data-testid="stMetric"] {
    background: #131C2E; border: 1px solid #1F2A40; border-radius: 12px;
    padding: 14px 16px;
}
[data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #94A3B8;}
[data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 650;}
.signal {border-radius: 10px; padding: 10px 14px; margin-bottom: 8px;
         border-left: 4px solid; background: #131C2E;}
.signal.pos {border-color: #22C55E;}
.signal.neg {border-color: #EF4444;}
.signal.neu {border-color: #94A3B8;}
.signal b {display: block; margin-bottom: 2px;}
.small-muted {color: #94A3B8; font-size: 0.85rem;}
"""


def inject_css() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def signal_card(title: str, detail: str, tone: str = "neu") -> None:
    st.markdown(
        f'<div class="signal {tone}"><b>{title}</b><span class="small-muted">{detail}</span></div>',
        unsafe_allow_html=True,
    )


DISCLAIMER = (
    "⚠️ Signaler och tips är automatiska, regelbaserade beräkningar på historisk data – "
    "inte finansiell rådgivning. Gör alltid din egen analys."
)
