"""🎯 Mål: hur mycket behöver jag spara för att nå en summa? Med troligt, dåligt och bra utfall.

Modell: månadsvisa simuleringar (Monte Carlo) där årsavkastningen är lognormalfördelad.
  - "Troligt" = medianutfallet (hälften av simuleringarna hamnar över, hälften under)
  - "Dåligt"  = 1 av 10 utfall blir sämre än så (10:e percentilen)
  - "Bra"     = 1 av 10 utfall blir bättre än så (90:e percentilen)
Avkastning anges som genomsnittlig årlig tillväxt (geometrisk), före inflation.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import db
import market
import portfolio
from ui import ACCENT, NEG, POS, fmt_num, fmt_pct, fmt_sek

PRESETS = {
    "Försiktig (räntor + aktier)": (4.0, 8.0),
    "Balanserad (blandad portfölj)": (6.0, 12.0),
    "Aktier – bred indexfond": (7.0, 16.0),
    "Aktier – enskilda bolag": (8.0, 22.0),
}
N_SIMS = 3000


def _current_value() -> float:
    tx = db.load_transactions()
    cash = sum(db.get_cash().values())
    if tx.empty:
        return cash
    pos = portfolio.compute_positions(tx)
    open_pos = pos[pos["qty"] > 0]
    if open_pos.empty:
        return cash
    quotes = market.get_live_quotes(tuple(sorted(open_pos["ticker"])))
    fx = market.get_fx_now(tuple(sorted(set(open_pos["currency"]) | {"SEK"})))
    hold = portfolio.enrich_positions(pos, quotes, fx)
    return float(hold["value_sek"].sum()) + cash


@st.cache_data(show_spinner=False)
def _shocks(months: int, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((N_SIMS, months))


def simulate(start: float, monthly: float, years: float, r: float, vol: float, fee: float) -> np.ndarray:
    """Returnerar matris (simuleringar × månader+1) med portföljvärden."""
    months = max(int(round(years * 12)), 1)
    mu = np.log(1 + r - fee) / 12          # median-tillväxt per månad (log)
    sigma = vol / np.sqrt(12)
    growth = np.exp(mu + sigma * _shocks(months))
    values = np.empty((N_SIMS, months + 1))
    values[:, 0] = start
    for m in range(months):
        values[:, m + 1] = (values[:, m] + monthly) * growth[:, m]
    return values


@st.cache_data(show_spinner=False)
def required_monthly(target: float, start: float, years: float, r: float, vol: float, fee: float,
                     percentile: float) -> float:
    """Minsta månadssparande så att given percentil når målet (bisektion)."""
    def end_value(pmt):
        return float(np.percentile(simulate(start, pmt, years, r, vol, fee)[:, -1], percentile))
    if end_value(0) >= target:
        return 0.0
    lo, hi = 0.0, max(target / max(years * 12, 1), 100.0)
    while end_value(hi) < target:
        hi *= 2
        if hi > 1e8:
            return float("nan")
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if end_value(mid) < target else (lo, mid)
    return hi


def render():
    st.title("🎯 Mål & sparkalkyl")
    st.caption("Räkna ut hur mycket du behöver spara för att nå ett belopp – och hur det kan gå i "
               "olika scenarier. Ingen garanti, bara sannolikheter baserade på historiska svängningar.")

    try:
        saved_amount = float(db.get_setting("goal_amount", "0") or 0)
    except ValueError:
        saved_amount = 0.0
    saved_date = db.get_setting("goal_date")
    default_years = 10
    if saved_date:
        d = dt.date.fromisoformat(saved_date)
        if d > dt.date.today():
            default_years = max(1, round((d - dt.date.today()).days / 365.25))

    with st.spinner("Hämtar ditt portföljvärde …"):
        current = _current_value()

    with st.container(border=True):
        try:
            saved_pmt = int(float(db.get_setting("monthly_saving", "2000") or 2000))
        except ValueError:
            saved_pmt = 2000
        c = st.columns(5)
        target = c[0].number_input("🎯 Mål (kr)", 0.0, 1e9, float(saved_amount or 1_000_000), 50_000.0)
        years = c[1].number_input("⏳ Antal år", 1, 60, int(default_years), 1)
        start = c[2].number_input("💼 Startkapital (kr)", 0.0, 1e9, float(round(current, -2)), 10_000.0,
                                  help="Förifyllt med ditt nuvarande portföljvärde inkl. pengar för köp.")
        pmt = c[3].number_input("💰 Jag sparar per månad (kr)", 0, 1_000_000, saved_pmt, 500,
                                help="Skriv in exakt vad du sparar, eller använd + och −. Sparas till nästa gång.")
        preset = c[4].selectbox("📊 Typ av sparande", list(PRESETS), index=2)
        if pmt != saved_pmt:
            db.set_setting("monthly_saving", pmt)
        with st.expander("⚙️ Justera antaganden"):
            a = st.columns(3)
            r = a[0].slider("Trolig avkastning per år (%)", 0.0, 15.0, PRESETS[preset][0], 0.5,
                            help="Svenska börsen har historiskt gett runt 7–9 % per år över lång tid, men det varierar mycket.") / 100
            vol = a[1].slider("Svängningar per år (%)", 0.0, 40.0, PRESETS[preset][1], 1.0,
                              help="Hur mycket värdet brukar svänga. Bred indexfond ~15 %, enskilda aktier mer.") / 100
            fee = a[2].slider("Avgifter + skatt per år (%)", 0.0, 3.0, 0.0, 0.1,
                              help="T.ex. fondavgift eller ISK-skatt (1,065 % på det som överstiger 300 000 kr 2026).") / 100

    with st.spinner("Räknar på tusentals möjliga framtider …"):
        need_likely = required_monthly(target, start, years, r, vol, fee, 50)
        need_safe = required_monthly(target, start, years, r, vol, fee, 10)

    def _round(x):
        return np.ceil(x / 100) * 100 if x == x else float("nan")

    st.markdown("##### Så mycket skulle du behöva spara för att nå målet")
    k = st.columns(3)
    k[0].metric("Troligt (hälften av utfallen)", fmt_sek(_round(need_likely)),
                delta=(f"{fmt_sek(pmt - _round(need_likely))} jämfört med ditt sparande") if need_likely == need_likely else None,
                delta_color="normal")
    k[1].metric("Säkert (9 av 10 utfall)", fmt_sek(_round(need_safe)),
                delta=(f"{fmt_sek(pmt - _round(need_safe))} jämfört med ditt sparande") if need_safe == need_safe else None,
                delta_color="normal")
    k[2].metric("Om pengarna inte växte alls", fmt_sek(_round(max(target - start, 0) / (years * 12))))
    if need_likely == need_likely and need_likely > 0:
        if pmt >= need_safe:
            st.success(f"💪 Med {fmt_sek(pmt)} i månaden når du målet i minst 9 av 10 utfall.")
        elif pmt >= need_likely:
            st.info(f"👍 Med {fmt_sek(pmt)} i månaden når du troligen målet – men inte i alla utfall.")
        else:
            st.warning(f"Med {fmt_sek(pmt)} i månaden når du troligen inte målet på {years} år. "
                       f"Höj till ca {fmt_sek(_round(need_likely))}, förläng tiden eller sänk målet.")
    elif need_likely == 0:
        st.success("🎉 Du når troligen målet utan att spara något mer – allt du sparar är bonus!")

    sims = simulate(start, pmt, years, r, vol, fee)
    months = sims.shape[1]
    dates = pd.date_range(pd.Timestamp.today().normalize(), periods=months, freq="MS")
    p10, p50, p90 = np.percentile(sims, [10, 50, 90], axis=0)
    deposits = start + pmt * np.arange(months)
    chance = float((sims[:, -1] >= target).mean())

    fig = go.Figure()
    # Spannet mellan dåligt och bra utfall som en mjuk ton
    fig.add_trace(go.Scatter(x=dates, y=p90, name="Bra utfall (1 av 10 blir bättre)",
                             line=dict(color=charts.POS, width=1.5), hovertemplate="%{y:,.0f} kr"))
    fig.add_trace(go.Scatter(x=dates, y=p10, name="Dåligt utfall (1 av 10 blir sämre)",
                             line=dict(color=charts.NEG, width=1.5), hovertemplate="%{y:,.0f} kr",
                             fill="tonexty", fillcolor=charts.hex_to_rgba(charts.ACCENT, 0.07)))
    fig.add_trace(go.Scatter(x=dates, y=deposits, name="Bara insatta pengar", hovertemplate="%{y:,.0f} kr",
                             line=dict(color=charts.NEUTRAL, width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=dates, y=p50, name="Troligt", hovertemplate="<b>%{y:,.0f} kr</b>",
                             line=dict(color=charts.ACCENT, width=3)))
    fig.add_trace(go.Scatter(x=[dates[-1]], y=[p50[-1]], mode="markers+text", showlegend=False, hoverinfo="skip",
                             text=[fmt_sek(p50[-1])], textposition="middle left", textfont=dict(color=charts.INK, size=12),
                             marker=dict(color=charts.ACCENT, size=10, line=dict(width=2, color=charts.SURFACE))))
    if target > 0:
        fig.add_hline(y=target, line_color="rgba(244,239,230,0.45)", line_width=1,
                      annotation_text=f"🎯 Mål {fmt_sek(target)}", annotation_position="top left",
                      annotation_font=dict(color=charts.INK_2, size=12))
    fig.update_layout(yaxis=dict(tickformat=",.0f", ticksuffix=" kr"), legend=dict(traceorder="normal"))
    charts.show(fig, height=460)

    end = st.columns(4)
    end[0].metric("Troligt slutvärde", fmt_sek(p50[-1]))
    end[1].metric("Dåligt utfall", fmt_sek(p10[-1]))
    end[2].metric("Bra utfall", fmt_sek(p90[-1]))
    end[3].metric("Chans att nå målet", fmt_pct(chance, 0, sign=False))

    gain = p50[-1] - deposits[-1]
    st.markdown(
        f"Med **{fmt_sek(pmt)} i månaden** sätter du in totalt **{fmt_sek(deposits[-1] - start)}** "
        f"under {years} år. Ränta-på-ränta ger troligen **{fmt_sek(max(gain, 0))}** extra"
        + (f" – det är {fmt_num(gain / max(deposits[-1], 1) * 100, 0)} % av allt du satt in." if gain > 0 else ".")
    )
    hit = np.argmax(p50 >= target) if (p50 >= target).any() else None
    if target > 0 and hit is not None and hit > 0:
        st.success(f"🎉 Troligen når du målet runt **{dates[hit]:%B %Y}**.".replace("January", "januari")
                   .replace("February", "februari").replace("March", "mars").replace("April", "april")
                   .replace("May", "maj").replace("June", "juni").replace("July", "juli")
                   .replace("August", "augusti").replace("September", "september").replace("October", "oktober")
                   .replace("November", "november").replace("December", "december"))

    a, b = st.columns([1, 3])
    if a.button("⭐ Spara som mitt mål", help="Visas som eget sparmål på Översikten"):
        db.set_setting("goal_amount", target)
        db.set_setting("goal_date", (dt.date.today() + dt.timedelta(days=int(years * 365.25))).isoformat())
        if not db.get_setting("goal_name"):
            db.set_setting("goal_name", "Mitt mål")
        st.toast("Målet är sparat – syns på Översikten.", icon="⭐")
    b.caption("Beräkningen är före inflation. Med 2 % inflation är 1 000 000 kr om 20 år värda ungefär "
              "670 000 kr i dagens pengar. Historisk avkastning är ingen garanti för framtiden.")
