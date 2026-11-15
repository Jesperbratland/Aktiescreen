"""Tips & insikter: portföljhälsa, signaler på innehav och idéer från screenern."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import analysis, db, market, portfolio, screener
from ui import DISCLAIMER, fmt_num, fmt_pct, signal_card


def render():
    st.title("💡 Tips & insikter")
    st.caption(DISCLAIMER)

    tx = db.load_transactions()
    tab1, tab2, tab3 = st.tabs(["🩺 Portföljhälsa", "📡 Signaler på innehav", "🎯 Aktieidéer"])
    with tab1:
        _health(tx)
    with tab2:
        _holding_signals(tx)
    with tab3:
        _ideas(tx)


def _holdings(tx):
    pos = portfolio.compute_positions(tx)
    open_pos = pos[pos["qty"] > 0]
    if open_pos.empty:
        return pd.DataFrame()
    quotes = market.get_live_quotes(tuple(sorted(open_pos["ticker"])))
    fx = market.get_fx_now(tuple(sorted(set(open_pos["currency"]) | {"SEK"})))
    return portfolio.enrich_positions(pos, quotes, fx)


def _health(tx):
    if tx.empty:
        st.info("Lägg till transaktioner för att få en hälsokontroll av portföljen.")
        return
    hold = _holdings(tx)
    if hold.empty:
        st.info("Inga öppna innehav.")
        return
    hold["sector"] = hold["ticker"].map(lambda t: market.get_info(t).get("sector") or "Okänd")
    n = len(hold)
    top = hold.iloc[0]
    top3 = hold["weight"].head(3).sum()
    sector_w = hold.groupby("sector")["weight"].sum().sort_values(ascending=False)
    cur_w = hold.groupby("currency")["weight"].sum().sort_values(ascending=False)

    c = st.columns(4)
    c[0].metric("Antal innehav", n)
    c[1].metric("Största innehav", f"{top['ticker']}", fmt_pct(top["weight"], 1, sign=False), delta_color="off")
    c[2].metric("Topp 3 andel", fmt_pct(top3, 0, sign=False))
    c[3].metric("Största sektor", sector_w.index[0], fmt_pct(sector_w.iloc[0], 0, sign=False), delta_color="off")

    st.subheader("Observationer")
    tips = []
    if n < 5:
        tips.append(("Låg diversifiering", f"Du har {n} innehav. Med färre än ~8–10 bolag blir enskilda bolagsrisker stora.", "neg"))
    elif n > 30:
        tips.append(("Många innehav", f"{n} innehav kan bli svårt att följa – överväg om en indexfond gör samma jobb billigare.", "neu"))
    else:
        tips.append(("Rimlig spridning", f"{n} innehav ger en hanterbar portfölj.", "pos"))
    if top["weight"] > 0.20:
        tips.append(("Koncentrationsrisk", f"{top['ticker']} utgör {fmt_pct(top['weight'], 0, sign=False)} av portföljen. "
                     "Många sätter ett tak på 10–20 % per bolag.", "neg"))
    if sector_w.iloc[0] > 0.40:
        tips.append(("Sektorkoncentration", f"{sector_w.index[0]} väger {fmt_pct(sector_w.iloc[0], 0, sign=False)}. "
                     "Portföljen blir känslig för den branschens cykel.", "neg"))
    if cur_w.get("SEK", 0) > 0.9 and n >= 3:
        tips.append(("Hemmamarknadsbias", "Över 90 % i svenska aktier. Sverige är ~1 % av världens börsvärde.", "neu"))
    elif cur_w.get("SEK", 0) < 0.3:
        tips.append(("Hög valutaexponering", f"Bara {fmt_pct(cur_w.get('SEK', 0), 0, sign=False)} i SEK – kronans kurs påverkar din avkastning mycket.", "neu"))
    losers = hold[hold["unrealized_pct"] < -0.25]
    for r in losers.itertuples():
        tips.append((f"{r.ticker}: {fmt_pct(r.unrealized_pct, 0)}", "Stor förlust. Gäller ditt ursprungliga investeringscase fortfarande?", "neg"))
    winners = hold[(hold["unrealized_pct"] > 0.5) & (hold["weight"] > 0.12)]
    for r in winners.itertuples():
        tips.append((f"{r.ticker}: {fmt_pct(r.unrealized_pct, 0)}", f"Stor vinnare som nu väger {fmt_pct(r.weight, 0, sign=False)} – överväg ombalansering.", "pos"))
    for t in tips:
        signal_card(*t)

    st.subheader("Sektorfördelning")
    import plotly.graph_objects as go

    import charts
    sw = (sector_w * 100).sort_values()
    fig = go.Figure(go.Bar(x=sw.values, y=sw.index, orientation="h", width=0.55,
                           marker_color=charts.CATEGORICAL[0],
                           text=[f"{v:.0f} %" for v in sw.values], textposition="outside",
                           textfont=dict(color=charts.INK_2, size=11), cliponaxis=False,
                           hovertemplate="<b>%{y}</b><br>%{x:.1f} %<extra></extra>"))
    fig.update_layout(hovermode="closest", margin=dict(t=10, b=10, l=10, r=40),
                      xaxis=dict(ticksuffix=" %", showgrid=True), yaxis=dict(showgrid=False))
    charts.show(fig, height=max(200, 34 * len(sw) + 50))


def _holding_signals(tx):
    if tx.empty:
        st.info("Inga innehav ännu.")
        return
    hold = _holdings(tx)
    if hold.empty:
        st.info("Inga öppna innehav.")
        return
    rows = []
    with st.spinner("Analyserar innehav…"):
        for r in hold.itertuples():
            h = market.get_history(r.ticker, "2y")
            if h.empty:
                continue
            sigs = analysis.technical_signals(h)
            rows.append({
                "Ticker": r.ticker,
                "Netto": analysis.signal_score(sigs),
                "RSI": analysis.rsi(h["Close"]).iloc[-1],
                "Positiva": ", ".join(s["signal"] for s in sigs if s["tone"] == "pos") or "–",
                "Negativa": ", ".join(s["signal"] for s in sigs if s["tone"] == "neg") or "–",
                "Orealiserat %": r.unrealized_pct * 100,
                "Vikt %": r.weight * 100,
            })
    if not rows:
        st.warning("Kunde inte hämta data.")
        return
    df = pd.DataFrame(rows).sort_values("Netto", ascending=False)
    st.dataframe(df, hide_index=True, use_container_width=True, column_config={
        "Netto": st.column_config.NumberColumn("Netto", format="%+d", help="Positiva minus negativa signaler"),
        "RSI": st.column_config.NumberColumn(format="%.0f"),
        "Orealiserat %": st.column_config.NumberColumn(format="%.1f %%"),
        "Vikt %": st.column_config.NumberColumn(format="%.1f %%"),
    })
    weak = df[df["Netto"] <= -2]
    strong = df[df["Netto"] >= 2]
    if not weak.empty:
        st.markdown("**Bevaka extra:** " + ", ".join(weak["Ticker"]) + " – flera negativa tekniska signaler.")
    if not strong.empty:
        st.markdown("**Starkt tekniskt läge:** " + ", ".join(strong["Ticker"]) + ".")


IDEA_RULES = {
    "Kvalitet till rimligt pris": (
        "Hög ROE och marginal, P/E under 22.",
        lambda d: d[(d["ROE"] > 0.15) & (d["Vinstmarginal"] > 0.10) & d["P/E"].between(0, 22)]
        .sort_values("Poäng", ascending=False)),
    "Momentumledare": (
        "Bäst 12-månadersavkastning, över MA200 och inte överköpta (RSI < 75).",
        lambda d: d[d["Över MA200"].eq(True) & (d["RSI"] < 75)].sort_values("12 m", ascending=False)),
    "Översålda kvalitetsbolag": (
        "RSI under 40 men lönsamma (ROE > 12 %) – möjliga rekylköp.",
        lambda d: d[(d["RSI"] < 40) & (d["ROE"] > 0.12)].sort_values("RSI")),
    "Utdelningscase": (
        "Direktavkastning över 3,5 % och P/E under 20.",
        lambda d: d[(d["Direktavk."] > 0.035) & d["P/E"].between(0, 20)].sort_values("Direktavk.", ascending=False)),
}


def _ideas(tx):
    held = set(tx["ticker"]) if not tx.empty else set()
    c1, c2 = st.columns([2, 1])
    universe = c1.selectbox("Sök idéer i", list(screener.UNIVERSES), key="idea_universe")
    c2.write("")
    if c2.button("Generera idéer", type="primary"):
        bar = st.progress(0.0, "Hämtar data…")
        res = screener.run_screener(screener.UNIVERSES[universe], True,
                                    progress=lambda p, t: bar.progress(p, f"Analyserar {t}"))
        bar.empty()
        st.session_state["ideas_raw"] = (universe, res)

    stored = st.session_state.get("ideas_raw")
    if not stored:
        st.info("Klicka **Generera idéer** för att screena urvalet efter fyra strategier.")
        return
    universe, res = stored
    if res.empty or "P/E" not in res:
        st.warning("Ingen data.")
        return
    df = screener.add_scores(res)
    st.caption(f"Urval: {universe} · ⭐ = du äger redan aktien")
    cols = st.columns(2)
    for i, (title, (desc, rule)) in enumerate(IDEA_RULES.items()):
        with cols[i % 2]:
            st.markdown(f"#### {title}")
            st.caption(desc)
            hits = rule(df).head(5)
            if hits.empty:
                st.markdown("_Inga träffar just nu._")
                continue
            for t, r in hits.iterrows():
                star = " ⭐" if t in held else ""
                st.markdown(
                    f"**{t}**{star} · {r['Namn']}  \n"
                    f"<span class='small-muted'>P/E {fmt_num(r['P/E'], 1)} · ROE {fmt_pct(r['ROE'], 0, sign=False)} · "
                    f"Direktavk. {fmt_pct(r['Direktavk.'], 1, sign=False)} · 12 m {fmt_pct(r['12 m'], 0)} · "
                    f"RSI {fmt_num(r['RSI'], 0)} · Poäng {fmt_num(r['Poäng'], 0)}</span>",
                    unsafe_allow_html=True,
                )
