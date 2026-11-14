"""Screener: filtrera och ranka aktier på nyckeltal och teknik."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

import db, screener
from ui import DISCLAIMER


def render():
    st.title("🧭 Aktiescreener")

    c1, c2 = st.columns([2, 3])
    universe = c1.selectbox("Urval", [*screener.UNIVERSES, "Egen lista", "Mina innehav"])
    if universe == "Egen lista":
        raw = c2.text_area("Tickers (komma- eller radseparerade)", "VOLV-B.ST, ERIC-B.ST, AAPL, NOVO-B.CO", height=80)
        tickers = [t for t in raw.replace("\n", ",").split(",") if t.strip()]
    elif universe == "Mina innehav":
        tx = db.load_transactions()
        tickers = sorted(tx["ticker"].unique()) if not tx.empty else []
        c2.caption(", ".join(tickers) or "Inga innehav.")
    else:
        tickers = screener.UNIVERSES[universe]
        c2.caption(f"{len(tickers)} bolag: " + ", ".join(tickers))

    with_fund = st.toggle("Hämta fundamentala nyckeltal (P/E, ROE, utdelning …) – tar längre tid", value=True)
    if st.button("▶ Kör screener", type="primary", disabled=not tickers):
        bar = st.progress(0.0, "Hämtar kurser…")
        res = screener.run_screener(tickers, with_fund,
                                    progress=lambda p, t: bar.progress(p, f"Hämtar nyckeltal: {t}"))
        bar.empty()
        st.session_state["screener_raw"] = res
        st.session_state["screener_universe"] = universe

    res = st.session_state.get("screener_raw")
    if res is None:
        st.info("Välj urval och klicka **Kör screener**.")
        return
    if res.empty:
        st.warning("Ingen data hittades för urvalet.")
        return
    st.caption(f"Resultat för: **{st.session_state.get('screener_universe')}**")

    has_fund = "P/E" in res.columns
    with st.expander("⚖️ Viktning av poäng", expanded=False):
        w = st.columns(4)
        wv = w[0].slider("Värde", 0.0, 2.0, 1.0, 0.1, disabled=not has_fund)
        wq = w[1].slider("Kvalitet", 0.0, 2.0, 1.0, 0.1, disabled=not has_fund)
        wm = w[2].slider("Momentum", 0.0, 2.0, 1.0, 0.1)
        wd = w[3].slider("Utdelning", 0.0, 2.0, 0.5, 0.1, disabled=not has_fund)
        st.caption("Poängen är percentilrank inom urvalet (0–100). Värde = låg P/E, P/B, EV/EBITDA. "
                   "Kvalitet = hög ROE och marginal, låg skuldsättning. Momentum = 3 och 12 mån avkastning + över MA200.")
    df = screener.add_scores(res, wv, wq, wm, wd)

    with st.expander("🔍 Filter", expanded=True):
        f = st.columns(4)
        rsi_rng = f[0].slider("RSI", 0, 100, (0, 100))
        mom_min = f[1].slider("12 m avkastning minst (%)", -100, 200, -100)
        only_trend = f[2].checkbox("Endast över MA200")
        min_score = f[3].slider("Minsta poäng", 0, 100, 0)
        if has_fund:
            g = st.columns(4)
            pe_max = g[0].slider("P/E högst", 0, 100, 100)
            dy_min = g[1].slider("Direktavkastning minst (%)", 0.0, 10.0, 0.0, 0.25)
            roe_min = g[2].slider("ROE minst (%)", -50, 60, -50)
            sectors = g[3].multiselect("Sektor", sorted(df["Sektor"].dropna().unique()))

    m = df["RSI"].between(*rsi_rng) & (df["12 m"].fillna(-9) * 100 >= mom_min) & (df["Poäng"].fillna(0) >= min_score)
    if only_trend:
        m &= df["Över MA200"].eq(True)
    if has_fund:
        if pe_max < 100:
            m &= df["P/E"].between(0, pe_max)
        if dy_min > 0:
            m &= df["Direktavk."].fillna(0) * 100 >= dy_min
        if roe_min > -50:
            m &= df["ROE"].fillna(-9) * 100 >= roe_min
        if sectors:
            m &= df["Sektor"].isin(sectors)
    out = df[m]
    st.markdown(f"**{len(out)}** av {len(df)} bolag matchar")

    show = out.copy()
    for col in ("1 m", "3 m", "12 m", "Volatilitet", "Från 52v-högsta", "Direktavk.", "ROE", "Vinstmarginal", "Vinsttillväxt"):
        if col in show:
            show[col] = show[col] * 100
    if "Börsvärde" in show:
        show["Börsvärde"] = show["Börsvärde"] / 1e9
    pct = lambda name: st.column_config.NumberColumn(name, format="%.1f %%")  # noqa: E731
    st.dataframe(
        show.reset_index(), hide_index=True, use_container_width=True, height=520,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", pinned=True),
            "Poäng": st.column_config.ProgressColumn("Poäng", min_value=0, max_value=100, format="%d"),
            "Börsvärde": st.column_config.NumberColumn("Börsvärde (mdr)", format="%.1f"),
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "Fwd P/E": st.column_config.NumberColumn(format="%.1f"),
            "P/B": st.column_config.NumberColumn(format="%.1f"),
            "EV/EBITDA": st.column_config.NumberColumn(format="%.1f"),
            "Skuld/EK": st.column_config.NumberColumn(format="%.0f"),
            "Kurs": st.column_config.NumberColumn(format="%.2f"),
            "RSI": st.column_config.NumberColumn(format="%.0f"),
            **{c: pct(c) for c in ("1 m", "3 m", "12 m", "Volatilitet", "Från 52v-högsta",
                                   "Direktavk.", "ROE", "Vinstmarginal", "Vinsttillväxt")},
        },
    )

    a, b = st.columns([1, 3])
    pick = a.selectbox("Analysera närmare", out.index.tolist() or ["–"])
    if a.button("Öppna i Aktieanalys", disabled=out.empty):
        st.session_state["analyze_ticker"] = pick
        st.switch_page(st.session_state["_pages"]["analys"])

    if has_fund and not out.empty:
        plot = out.reset_index().dropna(subset=["P/E", "12 m"])
        plot = plot[(plot["P/E"] > 0) & (plot["P/E"] < 100)]
        if not plot.empty:
            fig = px.scatter(plot, x="P/E", y=plot["12 m"] * 100, color="Poäng", hover_name="ticker",
                             hover_data={"Namn": True}, color_continuous_scale="Blues",
                             labels={"y": "12 m avkastning (%)"})
            fig.update_traces(marker=dict(size=12, line=dict(width=1, color="white")))
            fig.update_layout(height=420, margin=dict(t=30, b=10), title="Värdering vs momentum")
            b.plotly_chart(fig, use_container_width=True)

    st.download_button("⬇️ Exportera resultat (CSV)", out.to_csv().encode("utf-8"), "screener.csv", "text/csv")
    st.caption(DISCLAIMER)
