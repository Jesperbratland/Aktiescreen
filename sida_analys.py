"""Aktieanalys: graf med indikatorer, nyckeltal, signaler och jämförelse."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import analysis, begrepp, charts, db, market, portfolio
from ui import DISCLAIMER, NEG, POS, fmt_big, fmt_num, fmt_pct, fmt_sek, signal_card


def render():
    st.title("🔬 Aktieanalys")

    tx = db.load_transactions()
    held = sorted(tx["ticker"].unique()) if not tx.empty else []
    default = st.session_state.get("analyze_ticker") or (held[0] if held else "VOLV-B.ST")

    c = st.columns([2, 1.3, 3])
    ticker = c[0].text_input("Ticker", value=default, help="Yahoo-ticker, t.ex. VOLV-B.ST, AAPL, NOVO-B.CO").strip().upper()
    period = c[1].selectbox("Period", ["6mo", "1y", "2y", "5y", "10y", "max"], index=2,
                            format_func=lambda p: {"6mo": "6 mån", "1y": "1 år", "2y": "2 år", "5y": "5 år",
                                                   "10y": "10 år", "max": "Max"}[p])
    indicators = c[2].multiselect("Indikatorer", ["MA20", "MA50", "MA200", "Bollinger", "RSI", "MACD", "Volym"],
                                  help="\n\n".join(f"**{t}:** {begrepp.TERMS[t]}" for t in
                                                   ["MA20", "MA50", "MA200", "Bollinger", "RSI", "MACD", "Volym"]),
                                  default=["MA50", "MA200", "RSI", "Volym"])
    if held:
        st.caption("Dina innehav: " + " · ".join(held))
    if not ticker:
        return
    st.session_state["analyze_ticker"] = ticker

    # Hämta längre historik än vald period så att MA200 finns från start
    fetch = {"6mo": "2y", "1y": "2y", "2y": "5y", "5y": "10y", "10y": "max", "max": "max"}[period]
    with st.spinner(f"Hämtar {ticker}…"):
        full = market.get_history(ticker, fetch)
        info = market.get_info(ticker)
    if full.empty:
        st.error(f"Hittade ingen data för **{ticker}**. Kontrollera tickern under Transaktioner → Hitta rätt ticker.")
        return

    close = full["Close"]
    span = {"6mo": pd.DateOffset(months=6), "1y": pd.DateOffset(years=1), "2y": pd.DateOffset(years=2),
            "5y": pd.DateOffset(years=5), "10y": pd.DateOffset(years=10)}.get(period)
    start = full.index[-1] - span if span is not None else full.index[0]
    df = full[full.index >= start]

    # ---------- Header ----------
    name = info.get("longName") or info.get("shortName") or ticker
    cur = info.get("currency", "")
    last, prev = close.iloc[-1], close.iloc[-2] if len(close) > 1 else close.iloc[-1]
    live = market.get_live_quotes((ticker,))
    if ticker in live.index and live.loc[ticker, "source"] == "Avanza":
        last = live.loc[ticker, "last"]
        prev = live.loc[ticker, "prev"] if pd.notna(live.loc[ticker, "prev"]) else prev
    st.markdown(f"### {name}  <span class='small-muted'>{ticker} · {info.get('exchange', '')} · "
                f"{info.get('sector', '')}</span>", unsafe_allow_html=True)
    k = st.columns(6)
    k[0].metric("Senaste kurs", f"{fmt_num(last, 2)} {cur}", fmt_pct(last / prev - 1, 2), help=begrepp.TERMS["Senaste kurs"])
    k[1].metric("Börsvärde", fmt_big(info.get("marketCap")), help=begrepp.TERMS["Börsvärde"])
    k[2].metric("P/E", fmt_num(info.get("trailingPE"), 1), help=begrepp.TERMS["P/E"])
    k[3].metric("P/B", fmt_num(info.get("priceToBook"), 1), help=begrepp.TERMS["P/B"])
    dr, cp = info.get("dividendRate"), info.get("currentPrice") or last
    k[4].metric("Direktavkastning", fmt_pct(dr / cp, 2, sign=False) if dr and cp else "–", help=begrepp.TERMS["Direktavkastning"])
    y = close.tail(252)
    k[5].metric("52v intervall", f"{fmt_num(y.min(), 0)}–{fmt_num(y.max(), 0)}", help=begrepp.TERMS["52v intervall"])
    _buy_calc(ticker, float(last), cur)

    # ---------- Graf ----------
    sub = [i for i in ("Volym", "RSI", "MACD") if i in indicators]
    rows = 1 + len(sub)
    heights = [0.55] + [0.45 / len(sub)] * len(sub) if sub else [1.0]
    style = st.segmented_control("Diagramtyp", ["📈 Linje", "🕯️ Candlestick"], default="📈 Linje",
                                 label_visibility="collapsed", key="chart_style") or "📈 Linje"
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=heights)
    if "Bollinger" in indicators:
        up, mid, lo = analysis.bollinger(close)
        fig.add_trace(go.Scatter(x=df.index, y=up.loc[df.index], name="Bollinger", legendgroup="bb",
                                 line=dict(color="rgba(168,181,174,0.35)", width=1), hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=lo.loc[df.index], name="Bollinger", legendgroup="bb", showlegend=False,
                                 line=dict(color="rgba(168,181,174,0.35)", width=1), hoverinfo="skip",
                                 fill="tonexty", fillcolor="rgba(168,181,174,0.06)"), row=1, col=1)
    period_up = df["Close"].iloc[-1] >= df["Close"].iloc[0]
    main_col = charts.POS if period_up else charts.NEG
    if style.startswith("🕯️"):
        fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                     name=ticker, increasing=dict(line=dict(color=charts.POS, width=1), fillcolor=charts.POS),
                                     decreasing=dict(line=dict(color=charts.NEG, width=1), fillcolor=charts.NEG)),
                      row=1, col=1)
    else:
        lo_y = float(df["Low"].min())
        # Ton under linjen ner till diagrammets botten (inte till noll, så att kursrörelsen syns)
        fig.add_trace(go.Scatter(x=df.index, y=[lo_y * 0.97] * len(df), showlegend=False, hoverinfo="skip",
                                 line=dict(width=0)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name=ticker, line=dict(color=main_col, width=2),
                                 fill="tonexty", fillcolor=charts.hex_to_rgba(main_col, 0.10),
                                 hovertemplate="%{y:,.2f}"), row=1, col=1)
        fig.update_yaxes(range=[lo_y * 0.97, float(df["High"].max()) * 1.02], row=1, col=1)
    colors = {"MA20": charts.CATEGORICAL[6], "MA50": charts.CATEGORICAL[1], "MA200": charts.CATEGORICAL[0]}
    for ma, n in (("MA20", 20), ("MA50", 50), ("MA200", 200)):
        if ma in indicators:
            fig.add_trace(go.Scatter(x=df.index, y=analysis.sma(close, n).loc[df.index], name=ma,
                                     line=dict(color=colors[ma], width=1.5), hovertemplate="%{y:,.2f}"), row=1, col=1)

    # Eget GAV som linje
    if ticker in held:
        pos = portfolio.compute_positions(tx)
        p = pos[(pos["ticker"] == ticker) & (pos["qty"] > 0)]
        if not p.empty:
            gav = float(p["cost_local"].iloc[0] / p["qty"].iloc[0])
            fig.add_hline(y=gav, line_dash="dot", line_color=charts.ACCENT, line_width=1.5, row=1, col=1,
                          annotation_text=f"Ditt GAV {fmt_num(gav, 2)}", annotation_position="top left",
                          annotation_font=dict(color=charts.INK_2, size=11))
        buys = tx[(tx["ticker"] == ticker) & (tx["type"].isin(["KÖP", "SÄLJ"]))].copy()
        buys["date"] = pd.to_datetime(buys["date"])
        buys = buys[buys["date"] >= df.index[0]]
        for typ, sym, col in (("KÖP", "triangle-up", charts.POS), ("SÄLJ", "triangle-down", charts.NEG)):
            b = buys[buys["type"] == typ]
            if not b.empty:
                fig.add_trace(go.Scatter(x=b["date"], y=b["price"], mode="markers", name=typ,
                                         marker=dict(symbol=sym, size=12, color=col, line=dict(width=2, color=charts.SURFACE)),
                                         hovertemplate=f"{typ} %{{y:,.2f}}"),
                              row=1, col=1)

    r = 2
    if "Volym" in sub:
        vcol = [charts.hex_to_rgba(charts.POS if c >= o else charts.NEG, 0.45) for o, c in zip(df["Open"], df["Close"])]
        fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vcol, name="Volym", showlegend=False,
                             hovertemplate="%{y:,.0f}"), row=r, col=1)
        fig.update_yaxes(title_text="Volym", row=r, col=1, showgrid=False)
        r += 1
    if "RSI" in sub:
        fig.add_hrect(y0=30, y1=70, fillcolor="rgba(244,239,230,0.04)", line_width=0, row=r, col=1)
        for lvl in (30, 70):
            fig.add_hline(y=lvl, line_color="rgba(244,239,230,0.15)", line_width=1, row=r, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=analysis.rsi(close).loc[df.index], name="RSI", showlegend=False,
                                 line=dict(color=charts.CATEGORICAL[6], width=1.5), hovertemplate="%{y:.0f}"), row=r, col=1)
        fig.update_yaxes(title_text="RSI", range=[0, 100], tickvals=[30, 70], row=r, col=1)
        r += 1
    if "MACD" in sub:
        line, sig, hist = analysis.macd(close)
        fig.add_trace(go.Bar(x=df.index, y=hist.loc[df.index], name="MACD hist", showlegend=False,
                             marker_color=[charts.hex_to_rgba(charts.POS if v >= 0 else charts.NEG, 0.5)
                                           for v in hist.loc[df.index]], hovertemplate="%{y:.2f}"), row=r, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=line.loc[df.index], name="MACD", showlegend=False,
                                 line=dict(color=charts.CATEGORICAL[0], width=1.5), hovertemplate="%{y:.2f}"), row=r, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=sig.loc[df.index], name="Signal", showlegend=False,
                                 line=dict(color=charts.CATEGORICAL[1], width=1.5), hovertemplate="%{y:.2f}"), row=r, col=1)
        fig.update_yaxes(title_text="MACD", row=r, col=1)

    fig.update_layout(xaxis_rangeslider_visible=False, bargap=0.15, barcornerradius=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], showgrid=False)
    charts.show(fig, height=520 + 140 * len(sub))

    # ---------- Signaler + nyckeltal ----------
    left, mid, right = st.columns([1.1, 1, 1])
    with left:
        st.subheader("Tekniska signaler")
        sigs = analysis.technical_signals(full)
        score = analysis.signal_score(sigs)
        st.caption(f"Nettopoäng: **{score:+d}** (positiva − negativa signaler)")
        for s in sigs:
            signal_card(s["signal"], s["detail"], s["tone"])
    with mid:
        st.subheader("Avkastning")
        pr = analysis.period_returns(close)
        begrepp.table([(k_, fmt_pct(v)) for k_, v in pr.items()], "Period", "Avkastning")
        st.subheader("Risk (vald period)")
        stats = analysis.perf_stats(df["Close"])
        bench = market.get_closes(("^OMX" if ticker.endswith(".ST") else "^GSPC",), period=fetch)
        b = analysis.beta(df["Close"], bench.iloc[:, 0].loc[bench.index >= df.index[0]]) if not bench.empty else None
        rows_ = [(k_, fmt_pct(v) if k_ not in ("Sharpe", "Sortino") else fmt_num(v, 2)) for k_, v in stats.items()]
        rows_.append(("Beta mot " + ("OMXS30" if ticker.endswith(".ST") else "S&P 500"), fmt_num(b, 2)))
        begrepp.table(rows_, "Mått", "Värde")
    with right:
        st.subheader("Nyckeltal")
        fund = [
            ("P/E (12m)", fmt_num(info.get("trailingPE"), 1)),
            ("P/E (framåt)", fmt_num(info.get("forwardPE"), 1)),
            ("PEG", fmt_num(info.get("trailingPegRatio") or info.get("pegRatio"), 2)),
            ("P/S", fmt_num(info.get("priceToSalesTrailing12Months"), 1)),
            ("EV/EBITDA", fmt_num(info.get("enterpriseToEbitda"), 1)),
            ("ROE", fmt_pct(info.get("returnOnEquity"), 1, sign=False) if info.get("returnOnEquity") else "–"),
            ("Vinstmarginal", fmt_pct(info.get("profitMargins"), 1, sign=False) if info.get("profitMargins") else "–"),
            ("Bruttomarginal", fmt_pct(info.get("grossMargins"), 1, sign=False) if info.get("grossMargins") else "–"),
            ("Omsättningstillväxt", fmt_pct(info.get("revenueGrowth")) if info.get("revenueGrowth") else "–"),
            ("Vinsttillväxt", fmt_pct(info.get("earningsGrowth")) if info.get("earningsGrowth") else "–"),
            ("Skuld/EK (%)", fmt_num(info.get("debtToEquity"), 0)),
            ("Utdelningsandel", fmt_pct(info.get("payoutRatio"), 0, sign=False) if info.get("payoutRatio") else "–"),
            ("Analytikers riktkurs", f"{fmt_num(info.get('targetMeanPrice'), 1)} {cur}" if info.get("targetMeanPrice") else "–"),
            ("Analytikerkonsensus", (info.get("recommendationKey") or "–").replace("_", " ")),
        ]
        begrepp.table(fund, "Nyckeltal", "Värde")

    if summary := info.get("longBusinessSummary"):
        with st.expander("Om bolaget"):
            st.write(summary)

    # ---------- Nyheter, insyn och kalender ----------
    import handelser as h
    import sida_handelser
    st.subheader("Senaste om bolaget")
    n1, n2, n3 = st.tabs(["📰 Nyheter", "🕵️ Insynshandel", "📅 Kalender"])
    with n1:
        with st.spinner("Hämtar nyheter …"):
            sida_handelser.news_list(h.news(ticker, limit=8))
    with n2:
        with st.spinner("Hämtar insynshandel …"):
            sida_handelser.insider_view(ticker, compact=True)
    with n3:
        cal = h.calendar(ticker)
        c = st.columns(3)
        nxt = next((d for d in cal["earnings"] if d >= h.dt.date.today()), None)
        c[0].metric("Nästa rapport", h.fmt_date(nxt), h.days_text(nxt) or None, delta_color="off")
        c[1].metric("X-dag", h.fmt_date(cal["ex_div"]), h.days_text(cal["ex_div"]) or None, delta_color="off")
        c[2].metric("Utbetalning", h.fmt_date(cal["div_pay"]), h.days_text(cal["div_pay"]) or None, delta_color="off")
        hist_div = h.dividend_history(ticker)
        if not hist_div.empty:
            yearly = hist_div.groupby(hist_div.index.year).sum().tail(10)
            figd = go.Figure(go.Bar(x=[str(y) for y in yearly.index], y=yearly.values, marker_color=charts.ACCENT,
                                    width=0.6, hovertemplate="%{x}: %{y:.2f} " + cur + "<extra></extra>"))
            figd.update_layout(hovermode="closest", title="Utdelning per aktie och år", xaxis=dict(showgrid=False))
            charts.show(figd, height=240)

    # ---------- Jämförelse ----------
    st.subheader("Jämför utveckling")
    others = st.multiselect("Lägg till tickers/index", options=sorted(set(held) | set(market.BENCHMARKS.values())),
                            default=["^OMX"] if ticker.endswith(".ST") else ["^GSPC"],
                            accept_new_options=True)
    comp = market.get_closes(tuple(dict.fromkeys([ticker, *others])), start=df.index[0].strftime("%Y-%m-%d"))
    if not comp.empty:
        norm = comp.ffill().apply(lambda s: s / s.dropna().iloc[0] * 100 if s.notna().any() else s)
        fig2 = go.Figure()
        others_cols = [c for c in norm.columns if c != ticker]
        for i, col in enumerate(others_cols):
            fig2.add_trace(go.Scatter(x=norm.index, y=norm[col], name=col, hovertemplate="%{y:.1f}",
                                      line=dict(color=charts.CATEGORICAL[i % len(charts.CATEGORICAL)], width=1.5)))
        if ticker in norm.columns:
            fig2.add_trace(go.Scatter(x=norm.index, y=norm[ticker], name=ticker, hovertemplate="%{y:.1f}",
                                      line=dict(color=charts.ACCENT, width=2.5)))
        fig2.add_hline(y=100, line_color="rgba(244,239,230,0.2)", line_width=1)
        fig2.update_layout(yaxis_title="Index (start = 100)")
        charts.show(fig2, height=360)

    st.caption(DISCLAIMER)



def _buy_calc(ticker: str, price: float, cur: str):
    """Hur många aktier räcker pengarna till – inklusive courtage och valutaväxling."""
    import math

    import aktielista
    import fees
    cash = db.get_cash()
    if not cash or max(cash.values()) <= 0 or not price or math.isnan(price):
        return
    cur = aktielista.currency_for(ticker, cur)
    fx = market.get_fx_now((cur,)).get(cur, 1.0) if cur != "SEK" else 1.0
    with st.expander(f"🛒 Hur många {ticker} kan jag köpa?"):
        accounts = db.load_accounts().set_index("name")
        names = [n for n in accounts.index if cash.get(n, 0) > 0]
        c = st.columns([2, 2, 3])
        acc = c[0].selectbox("Konto", names, format_func=lambda n: f"{n} ({fmt_num(cash[n], 0)} kr)",
                             key="buy_acc")
        budget = c[1].number_input("Belopp att använda (kr)", 0.0, float(cash[acc]), float(cash[acc]), 500.0,
                                   key=f"buy_budget_{acc}")
        a = accounts.loc[acc]
        unit = price * fx
        n = int(budget // unit)
        while n > 0:
            f = fees.calc_fees(n * unit, a["broker"], a["courtage_class"], cur != "SEK", a["custom_pct"], a["custom_min"])
            if n * unit + f["total"] <= budget:
                break
            n -= 1
        if n <= 0:
            c[2].warning(f"Pengarna räcker inte till en aktie ({fmt_sek(unit)} + avgifter).")
            return
        f = fees.calc_fees(n * unit, a["broker"], a["courtage_class"], cur != "SEK", a["custom_pct"], a["custom_min"])
        c[2].metric("Du kan köpa", f"{n} st", f"kostar {fmt_sek(n * unit + f['total'])} inkl. avgifter "
                    f"{fmt_sek(f['total'], 2)}", delta_color="off")
        st.caption(f"Kvar efter köp: {fmt_sek(cash[acc] - n * unit - f['total'])}. Kurs {fmt_num(price, 2)} {cur}"
                   + (f" × {fmt_num(fx, 4)} SEK/{cur}" if cur != "SEK" else "") + ".")
