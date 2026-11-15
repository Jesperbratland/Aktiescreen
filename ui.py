"""Formatering och gemensam styling."""
from __future__ import annotations

import math

import streamlit as st

POS = "#22C55E"
NEG = "#EF4444"
NEU = "#94A3B8"
ACCENT = "#E8B44C"  # guld (jultema). Original: "#3B82F6"

# 🎄 Sätt till False för att stänga av jultemat (snö, ljusslinga, julhälsning).
JULTEMA = True


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
    background: #142721; border: 1px solid #2A3F36; border-radius: 12px;
    padding: 14px 16px;
}
[data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #A8B5AE;}
[data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 650;}
.signal {border-radius: 10px; padding: 10px 14px; margin-bottom: 8px;
         border-left: 4px solid; background: #142721;}
.signal.pos {border-color: #22C55E;}
.signal.neg {border-color: #EF4444;}
.signal.neu {border-color: #94A3B8;}
.signal b {display: block; margin-bottom: 2px;}
.small-muted {color: #A8B5AE; font-size: 0.85rem;}
/* Sammanfattning överst på Översikten */
.hero-top {color: #A8B5AE; font-size: .9rem; margin-bottom: .6rem;}
.hero-label {color: #A8B5AE; font-size: .85rem; text-transform: uppercase; letter-spacing: .08em;}
.hero-value {font-size: 2.6rem; font-weight: 700; line-height: 1.15; margin: .1rem 0 .2rem;}
.hero-sub {color: #A8B5AE; font-size: .9rem; margin-bottom: 1rem;}
.hero-pills {display: flex; gap: .7rem; flex-wrap: wrap;}
.pill {background: #1B332B; border: 1px solid #2A3F36; border-radius: 12px; padding: .55rem .9rem; min-width: 150px;}
.pill span {display: block; color: #A8B5AE; font-size: .78rem;}
.pill b {display: block; font-size: 1.15rem;}
.pill small {font-size: .85rem;}
.pill.pos b, .pill.pos small {color: #22C55E;}
.pill.neg b, .pill.neg small {color: #EF4444;}
"""


def inject_css() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


# ---------- 🎄 Jultema ----------
JUL_CSS = """
/* Ljusslinga högst upp – tunn och dämpad */
.jul-slinga {position: fixed; top: 0; left: 0; right: 0; height: 6px; z-index: 999990;
    pointer-events: none;
    background: radial-gradient(circle, rgba(232,180,76,.9) 0 2px, transparent 3px) 0 0 / 28px 6px repeat-x;
    animation: jul-blink 3s ease-in-out infinite;}
@keyframes jul-blink {0%,100% {opacity: .55;} 50% {opacity: 1;}}

/* Snöfall – ligger ovanpå men går inte att klicka på */
.jul-sno {position: fixed; inset: 0; pointer-events: none; z-index: 999989; overflow: hidden;}
.jul-sno span {position: absolute; top: -5vh; color: #FFFFFF; user-select: none;
    animation-name: jul-fall; animation-timing-function: linear; animation-iteration-count: infinite;}
@keyframes jul-fall {
    0%   {transform: translate3d(0, -5vh, 0) rotate(0deg);}
    100% {transform: translate3d(var(--drift, 0px), 105vh, 0) rotate(360deg);}
}
@media (prefers-reduced-motion: reduce) {.jul-sno, .jul-slinga {display: none;}}

/* Varmare rubriker */
h1 {letter-spacing: .2px;}
[data-testid="stSidebar"] {border-right: 1px solid #2A3F36;}
.jul-halsning {background: linear-gradient(135deg, #1B332B, #142721); border: 1px solid #3A5248;
    border-radius: 12px; padding: 10px 12px; margin: 4px 0 10px; font-size: .9rem; color: #F4EFE6;}
.jul-halsning small {color: #E8B44C;}
"""


def _snowflakes(n: int = 28) -> str:
    """Bygger snöflingor med fasta (deterministiska) positioner så att de inte hoppar vid omladdning."""
    import random
    rnd = random.Random(24)
    flakes = []
    for _ in range(n):
        flakes.append(
            f'<span style="left:{rnd.uniform(0, 100):.1f}vw; font-size:{rnd.uniform(8, 16):.0f}px; '
            f'opacity:{rnd.uniform(0.12, 0.35):.2f}; animation-duration:{rnd.uniform(14, 30):.0f}s; '
            f'animation-delay:-{rnd.uniform(0, 30):.0f}s; --drift:{rnd.uniform(-40, 40):.0f}px;">❄</span>'
        )
    return "".join(flakes)


def inject_christmas(snow: bool = True) -> None:
    if not JULTEMA:
        return
    html = f"<style>{JUL_CSS}</style><div class='jul-slinga'></div>"
    if snow:
        html += f"<div class='jul-sno'>{_snowflakes()}</div>"
    st.markdown(html, unsafe_allow_html=True)


def christmas_greeting() -> None:
    """Liten julhälsning med nedräkning i sidomenyn."""
    if not JULTEMA:
        return
    import datetime as dt
    today = dt.date.today()
    eve = dt.date(today.year, 12, 24)
    if today > eve:
        eve = dt.date(today.year + 1, 12, 24)
    days = (eve - today).days
    if days == 0:
        text = "🎅 God jul! Börsen vilar – det får du också göra."
    elif today.month == 12 and today.day > 24 or (today.month == 1 and today.day <= 6):
        text = "✨ Gott nytt börsår!"
    else:
        text = f"🎁 <b>{days}</b> dagar kvar till julafton"
    st.markdown(f"<div class='jul-halsning'>{text}<br><small>God jul & gott nytt börsår</small></div>",
                unsafe_allow_html=True)


def signal_card(title: str, detail: str, tone: str = "neu") -> None:
    st.markdown(
        f'<div class="signal {tone}"><b>{title}</b><span class="small-muted">{detail}</span></div>',
        unsafe_allow_html=True,
    )


DISCLAIMER = (
    "⚠️ Signaler och tips är automatiska, regelbaserade beräkningar på historisk data – "
    "inte finansiell rådgivning. Gör alltid din egen analys."
)
