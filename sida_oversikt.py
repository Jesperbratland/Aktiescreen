"""Översikt: KPI:er, fördelning, innehav och historik."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import db, market, portfolio
from ui import ACCENT, NEG, POS, fmt_pct, fmt_sek


def _load_portfolio(tx):
    pos = portfolio.compute_positions(tx)
    open_pos = pos[pos["qty"] > 0]
    tickers = tuple(sorted(open_pos["ticker"]))
    currencies = tuple(sorted(set(open_pos["currency"]) | {"SEK"}))
    quotes = market.get_quotes(tickers) if tickers else pd.DataFrame(columns=["last", "prev", "change_pct"])
    fx_now = market.get_fx_now(currencies)
    hold = portfolio.enrich_positions(pos, quotes, fx_now)
    return tx, pos, hold


def render():
    st.title("📊 Portföljöversikt")
    tx = db.load_transactions()
    if tx.empty:
        st.info("Du har inga aktier inlagda ännu.")
        a, b, _ = st.columns([1, 1, 2])
        if a.button("➕ Lägg in mina aktier", type="primary", use_container_width=True):
            st.switch_page(st.session_state["_pages"]["konton"])
        if b.button("Visa exempelportfölj", use_container_width=True):
            db.load_demo()
            st.rerun()
        return

    if tx["note"].str.startswith("Demo").any():
        a, b = st.columns([4, 1])
        a.info("🎁 Du tittar på **exempelaktier**. Lägg in dina egna så försvinner de.")
        if b.button("➕ Lägg in mina aktier", type="primary", use_container_width=True):
            st.switch_page(st.session_state["_pages"]["konton"])
    accs = sorted(tx["account"].unique())
    if len(accs) > 1:
        choice = st.segmented_control("Konto", ["Alla konton", *accs], default="Alla konton")
        if choice and choice != "Alla konton":
            tx = tx[tx["account"] == choice]

    with st.spinner("Hämtar kurser…"):
        tx, pos, hold = _load_portfolio(tx)

    value = hold["value_sek"].sum() if not hold.empty else 0.0
    cost = hold["cost_sek"].sum() if not hold.empty else 0.0
    unreal = value - cost
    day = hold["day_change_sek"].sum() if not hold.empty else 0.0
    realized = pos["realized_sek"].sum()
    divs = pos["dividends_sek"].sum()
    total = unreal + realized + divs
    prev_value = value - day

    c = st.columns(6)
    c[0].metric("Marknadsvärde", fmt_sek(value))
    c[1].metric("Idag", fmt_sek(day), fmt_pct(day / prev_value if prev_value else None, 2))
    c[2].metric("Orealiserat", fmt_sek(unreal), fmt_pct(unreal / cost if cost else None))
    c[3].metric("Realiserat", fmt_sek(realized))
    c[4].metric("Utdelningar", fmt_sek(divs))
    c[5].metric("Totalt resultat", fmt_sek(total))

    if hold.empty:
        st.warning("Inga öppna innehav just nu.")
    else:
        missing = hold[hold["price"].isna()]["ticker"].tolist()
        if missing:
            st.warning(f"Kunde inte hämta kurs för: {', '.join(missing)}. Kontrollera tickern (t.ex. VOLV-B.ST).")

        left, right = st.columns([1, 1.4])
        with left:
            st.subheader("Fördelning")
            by = st.segmented_control("Gruppera på", ["Innehav", "Valuta", "Sektor"], default="Innehav",
                                      label_visibility="collapsed")
            alloc = hold[["ticker", "currency", "value_sek"]].copy()
            if by == "Sektor":
                alloc["group"] = alloc["ticker"].map(lambda t: market.get_info(t).get("sector") or "Okänd")
            elif by == "Valuta":
                alloc["group"] = alloc["currency"]
            else:
                alloc["group"] = alloc["ticker"]
            alloc = alloc.groupby("group", as_index=False)["value_sek"].sum()
            fig = px.pie(alloc, names="group", values="value_sek", hole=0.6)
            fig.update_traces(textposition="inside", textinfo="percent+label",
                              hovertemplate="%{label}<br>%{value:,.0f} kr<extra></extra>")
            fig.update_layout(showlegend=False, height=340, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

        with right:
            st.subheader("Resultat per innehav")
            bar = hold.sort_values("unrealized_sek")
            fig = go.Figure(go.Bar(
                x=bar["unrealized_sek"], y=bar["ticker"], orientation="h",
                marker_color=[POS if v >= 0 else NEG for v in bar["unrealized_sek"]],
                customdata=bar["unrealized_pct"] * 100,
                hovertemplate="%{y}: %{x:,.0f} kr (%{customdata:.1f} %)<extra></extra>",
            ))
            fig.update_layout(height=380, margin=dict(t=10, b=10, l=10, r=10), xaxis_title="Orealiserat (SEK)")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Innehav")
        table = hold.assign(
            unrealized_pct=hold["unrealized_pct"] * 100,
            day_change_pct=hold["day_change_pct"] * 100,
            weight=hold["weight"] * 100,
        )[["ticker", "qty", "gav_local", "price", "currency", "day_change_pct", "value_sek",
           "cost_sek", "unrealized_sek", "unrealized_pct", "dividends_sek", "weight"]]
        st.dataframe(
            table, hide_index=True, use_container_width=True,
            column_config={
                "ticker": "Ticker",
                "qty": st.column_config.NumberColumn("Antal", format="%.0f"),
                "gav_local": st.column_config.NumberColumn("GAV", format="%.2f", help="Genomsnittligt anskaffningsvärde i aktiens valuta"),
                "price": st.column_config.NumberColumn("Kurs", format="%.2f"),
                "currency": "Valuta",
                "day_change_pct": st.column_config.NumberColumn("Idag", format="%.2f %%"),
                "value_sek": st.column_config.NumberColumn("Värde (SEK)", format="%.0f"),
                "cost_sek": st.column_config.NumberColumn("Anskaffning (SEK)", format="%.0f"),
                "unrealized_sek": st.column_config.NumberColumn("Orealiserat (SEK)", format="%.0f"),
                "unrealized_pct": st.column_config.NumberColumn("Orealiserat %", format="%.1f %%"),
                "dividends_sek": st.column_config.NumberColumn("Utdelning (SEK)", format="%.0f"),
                "weight": st.column_config.ProgressColumn("Vikt", format="%.1f %%", min_value=0, max_value=100),
            },
        )

    _history_section(tx)


def _history_section(tx: pd.DataFrame):
    st.subheader("Utveckling över tid")
    c1, c2 = st.columns([1, 1])
    bench_name = c1.selectbox("Jämförelseindex", list(market.BENCHMARKS), index=0)
    period = c2.segmented_control("Period", ["3 m", "6 m", "1 år", "3 år", "Allt"], default="Allt")

    start = pd.to_datetime(tx["date"]).min().strftime("%Y-%m-%d")
    tickers = tuple(sorted(tx["ticker"].unique()))
    with st.spinner("Beräknar historik…"):
        closes = market.get_closes(tickers, start=start)
        fx_hist = market.get_fx_history(tuple(sorted(tx["currency"].unique())), start)
        hist = portfolio.portfolio_history(tx, closes, fx_hist)
    if hist.empty:
        st.info("Inte tillräckligt med historik ännu.")
        return

    offsets = {"3 m": pd.DateOffset(months=3), "6 m": pd.DateOffset(months=6),
               "1 år": pd.DateOffset(years=1), "3 år": pd.DateOffset(years=3)}
    if period in offsets:
        hist = hist[hist.index >= hist.index[-1] - offsets[period]]
    if hist.empty:
        return

    tab1, tab2 = st.tabs(["Värde vs insatt kapital", "Avkastning (TWR) vs index"])
    with tab1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist.index, y=hist["value"], name="Marknadsvärde",
                                 line=dict(color=ACCENT, width=2), fill="tozeroy",
                                 fillcolor="rgba(232,180,76,0.12)"))
        fig.add_trace(go.Scatter(x=hist.index, y=hist["invested"], name="Nettoinsatt",
                                 line=dict(color="#94A3B8", dash="dash")))
        fig.update_layout(height=380, hovermode="x unified", margin=dict(t=10, b=10),
                          yaxis_title="SEK", legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, use_container_width=True)
    with tab2:
        twr = hist["twr_index"] / hist["twr_index"].iloc[0] * 100
        bench = market.get_closes((market.BENCHMARKS[bench_name],), start=hist.index[0].strftime("%Y-%m-%d"))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=twr.index, y=twr, name="Min portfölj", line=dict(color=ACCENT, width=2)))
        if not bench.empty:
            b = bench.iloc[:, 0].dropna()
            b = b / b.iloc[0] * 100
            fig.add_trace(go.Scatter(x=b.index, y=b, name=bench_name, line=dict(color="#F59E0B")))
            delta = twr.iloc[-1] / 100 - b.iloc[-1] / 100
            st.caption(f"Portfölj: {fmt_pct(twr.iloc[-1] / 100 - 1)} · {bench_name}: "
                       f"{fmt_pct(b.iloc[-1] / 100 - 1)} · Skillnad: {fmt_pct(delta)}")
        fig.update_layout(height=380, hovermode="x unified", margin=dict(t=10, b=10),
                          yaxis_title="Index (start = 100)", legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("TWR = tidsviktad avkastning, opåverkad av när du sätter in/tar ut pengar. Utdelningar räknas in.")
