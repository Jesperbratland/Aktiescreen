"""🎯 Mål och delmål på Översikten – diskret och lite kul.

Automatiska milstolpar (värde, utdelningar, avkastning, spridning, tid) + ett eget sparmål.
Lägg gärna till fler i listorna nedan: (gräns, namn).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import db
from ui import fmt_num, fmt_sek

VALUE_GOALS = [
    (10_000, "Första tian"), (25_000, "Kvartsvägs till hundra"), (50_000, "Halvvägs till hundra"),
    (100_000, "Sexsiffrigt"), (250_000, "Kvarts miljon"), (500_000, "Halvmiljonären"),
    (1_000_000, "Miljonär 🎉"), (2_500_000, "Två och en halv"), (5_000_000, "Fem miljoner"),
    (10_000_000, "Tiomiljonersklubben"),
]
DIVIDEND_GOALS = [  # utdelningar senaste 12 månaderna
    (1_200, "En streamingtjänst om året"), (5_000, "En weekendresa"), (12_000, "En tusenlapp i månaden"),
    (36_500, "En hundralapp om dagen"), (120_000, "En tia i månaden"), (300_000, "Lön utan att jobba"),
]
RETURN_GOALS = [(0.10, "+10 %"), (0.25, "+25 %"), (0.50, "+50 %"), (1.00, "Dubblat pengarna")]
SPREAD_GOALS = [(5, "Fem bolag"), (10, "Tio bolag – bra spridning"), (15, "Femton bolag")]
YEAR_GOALS = [(1, "Ett år som investerare"), (3, "Tre år i marknaden"), (5, "Fem år – långsiktig på riktigt"),
              (10, "Ett decennium")]


def _next(goals, value):
    """(föregående nivå, nästa mål) – nästa är None om alla är klara."""
    prev = 0
    for limit, name in goals:
        if value < limit:
            return prev, (limit, name)
        prev = limit
    return prev, None


def _bar(col, title: str, value: float, goals, fmt) -> None:
    prev, nxt = _next(goals, value)
    if nxt is None:
        col.caption(f"{title} · alla mål klara 🏆")
        col.progress(1.0)
        return
    limit, name = nxt
    pct = max(0.0, min(1.0, (value - prev) / (limit - prev))) if limit > prev else 0.0
    col.caption(f"{title} · nästa: **{name}**")
    col.progress(pct, text=f"{fmt(value)} / {fmt(limit)}")


def render(tx: pd.DataFrame, total_value: float, cost: float, total_result: float, n_holdings: int,
           currencies: set[str]) -> None:
    today = pd.Timestamp.today().normalize()
    divs = tx[tx["type"] == "UTDELNING"]
    divs = divs[pd.to_datetime(divs["date"]) >= today - pd.Timedelta(days=365)]
    div12 = float((divs["quantity"] * divs["price"] * divs["fx_rate"] - divs["fee"]).sum())
    invested = cost if cost > 0 else 0.0
    ret = total_result / invested if invested else 0.0
    years = (today - pd.to_datetime(tx["date"]).min()).days / 365.25 if not tx.empty else 0.0

    c = st.columns(3)
    _bar(c[0], "🎯 Portföljvärde", total_value, VALUE_GOALS, fmt_sek)
    _bar(c[1], "💸 Utdelning 12 mån", div12, DIVIDEND_GOALS, fmt_sek)
    own = _own_goal_bar(c[2], total_value)
    if not own:
        _bar(c[2], "📈 Avkastning", ret, RETURN_GOALS, lambda x: f"{x * 100:.0f} %")

    # Alla mål & utmärkelser
    badges = []
    for title, goals, val in (("Värde", VALUE_GOALS, total_value), ("Utdelning", DIVIDEND_GOALS, div12),
                              ("Avkastning", RETURN_GOALS, ret), ("Spridning", SPREAD_GOALS, n_holdings),
                              ("Tid", YEAR_GOALS, years)):
        for limit, name in goals:
            badges.append((title, name, val >= limit))
    badges.append(("Spridning", "Världsmedborgare – aktier i flera valutor", len(currencies) >= 2))
    done = sum(1 for *_, ok in badges if ok)

    with st.expander(f"🏅 Mål & utmärkelser · {done} av {len(badges)} klara"):
        cols = st.columns(5)
        for i, cat in enumerate(["Värde", "Utdelning", "Avkastning", "Spridning", "Tid"]):
            with cols[i]:
                st.markdown(f"**{cat}**")
                for t, name, ok in badges:
                    if t == cat:
                        st.markdown(f"{'✅' if ok else '⬜'} <span class='small-muted'>{name}</span>"
                                    if not ok else f"✅ {name}", unsafe_allow_html=True)
        st.divider()
        _own_goal_editor(total_value)


def _own_goal() -> tuple[float, dt.date | None, str]:
    try:
        amount = float(db.get_setting("goal_amount", "0") or 0)
    except ValueError:
        amount = 0.0
    d = db.get_setting("goal_date")
    name = db.get_setting("goal_name", "Mitt mål") or "Mitt mål"
    return amount, (dt.date.fromisoformat(d) if d else None), name


def _own_goal_bar(col, total_value: float) -> bool:
    amount, date, name = _own_goal()
    if amount <= 0:
        return False
    pct = max(0.0, min(1.0, total_value / amount))
    text = f"{fmt_sek(total_value)} / {fmt_sek(amount)}"
    if date and total_value < amount:
        months = max((date.year - dt.date.today().year) * 12 + date.month - dt.date.today().month, 1)
        text += f" · ≈{fmt_num((amount - total_value) / months, 0)} kr/mån"
    col.caption(f"⭐ {name}" + (f" · till {date:%Y-%m-%d}" if date else "") + (" · klart! 🎉" if pct >= 1 else ""))
    col.progress(pct, text=text)
    return True


def _own_goal_editor(total_value: float) -> None:
    amount, date, name = _own_goal()
    st.markdown("**⭐ Eget sparmål** – visas på Översikten")
    a, b, c, d = st.columns([2, 1.3, 1.3, 1])
    new_name = a.text_input("Namn", value=name, key="goal_name", placeholder="t.ex. Sommarstugan")
    new_amount = b.number_input("Belopp (kr)", 0.0, value=float(amount), step=10_000.0, key="goal_amount")
    if date and date < dt.date.today():
        date = None
    new_date = c.date_input("Senast (valfritt)", value=date, min_value=dt.date.today(), format="YYYY-MM-DD",
                            key="goal_date")
    d.write("")
    if d.button("Spara", key="goal_save", use_container_width=True):
        db.set_setting("goal_name", new_name.strip() or "Mitt mål")
        db.set_setting("goal_amount", new_amount)
        db.set_setting("goal_date", new_date.isoformat() if new_date else None)
        st.rerun()
    st.caption("Belopp 0 tar bort målet. Kr/mån är vad du behöver spara utan att räkna med avkastning.")
