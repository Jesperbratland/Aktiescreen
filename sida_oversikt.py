"""Översikt: KPI:er, fördelning, innehav och historik."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import aktielista, charts, db, mal, market, portfolio, ui_helpers
from ui import ACCENT, NEG, POS, fmt_pct, fmt_sek


def _load_portfolio(tx):
    pos = portfolio.compute_positions(tx)
    open_pos = pos[pos["qty"] > 0]
    tickers = tuple(sorted(open_pos["ticker"]))
    currencies = tuple(sorted(set(open_pos["currency"]) | {"SEK"}))
    quotes = market.get_live_quotes(tickers) if tickers else pd.DataFrame(columns=["last", "prev", "change_pct"])
    fx_now = market.get_fx_now(currencies)
    hold = portfolio.enrich_positions(pos, quotes, fx_now)
    return tx, pos, hold


DAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober",
          "november", "december"]


def _compute_history(tx: pd.DataFrame) -> pd.DataFrame:
    if tx.empty:
        return pd.DataFrame()
    start = pd.to_datetime(tx["date"]).min().strftime("%Y-%m-%d")
    closes = market.get_closes(tuple(sorted(tx["ticker"].unique())), start=start)
    fx_hist = market.get_fx_history(tuple(sorted(tx["currency"].unique())), start)
    return portfolio.portfolio_history(tx, closes, fx_hist)


def _greeting() -> str:
    import datetime as dt
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("Europe/Stockholm"))
    h = now.hour
    hello = ("God natt" if h < 5 else "God morgon" if h < 10 else "Hej" if h < 17
             else "God kväll" if h < 23 else "God natt")
    return f"{hello} 👋 · {DAYS[now.weekday()]} {now.day} {MONTHS[now.month - 1]}"


def _pill(label: str, kr: float, pct: float | None) -> str:
    tone = "pos" if kr > 0.5 else "neg" if kr < -0.5 else ""
    kr_txt = ("+" if kr > 0.5 else "") + fmt_sek(kr)
    if pct is not None and pct == pct:
        arrow = "▲" if pct > 0 else "▼" if pct < 0 else "●"
        pct_txt = f"{arrow} {fmt_pct(abs(pct), 1, sign=False)}"
    else:
        pct_txt = "–"
    return f'<div class="pill {tone}"><span>{label}</span><b>{kr_txt}</b><small>{pct_txt}</small></div>'


def _hero(value: float, cash: float, day: float, prev_value: float, total: float, hist: pd.DataFrame):
    today = pd.Timestamp.today().normalize()
    ytd_kr = ytd_pct = week_kr = week_pct = None
    if not hist.empty:
        wk = today - pd.Timedelta(days=7)
        wb = hist[hist.index <= wk]
        if not wb.empty:
            after = hist[hist.index > wk]
            week_kr = value - float(wb["value"].iloc[-1]) - float(after["cashflow"].sum()) + \
                float(hist["dividends"].iloc[-1] - wb["dividends"].iloc[-1])
            week_pct = float(hist["twr_index"].iloc[-1]) / float(wb["twr_index"].iloc[-1]) - 1
        soy = pd.Timestamp(year=today.year, month=1, day=1)
        before = hist[hist.index < soy]
        base_val = float(before["value"].iloc[-1]) if not before.empty else 0.0
        base_twr = float(before["twr_index"].iloc[-1]) if not before.empty else 100.0
        in_year = hist[hist.index >= soy]
        ytd_kr = value - base_val - float(in_year["cashflow"].sum()) + \
            float(in_year["dividends"].iloc[-1] - (before["dividends"].iloc[-1] if not before.empty else 0.0)) \
            if not in_year.empty else 0.0
        ytd_pct = float(hist["twr_index"].iloc[-1]) / base_twr - 1

    with st.container(border=True):
        left, right = st.columns([1.45, 1])
        with left:
            st.markdown(
                f'<div class="hero-top">{_greeting()}</div>'
                f'<div class="hero-label">Totalt värde</div>'
                f'<div class="hero-value">{fmt_sek(value + cash)}</div>'
                f'<div class="hero-sub">Aktier {fmt_sek(value)} · 💰 Tillgängligt för köp {fmt_sek(cash)}</div>'
                f'<div class="hero-pills">'
                f'{_pill("☀️ Idag", day, day / prev_value if prev_value else None)}'
                f'{_pill("📅 Senaste veckan", week_kr if week_kr is not None else 0.0, week_pct)}'
                f'{_pill("🗓️ I år", ytd_kr if ytd_kr is not None else 0.0, ytd_pct)}'
                f'</div>', unsafe_allow_html=True)
        with right:
            if not hist.empty:
                h = hist[hist.index >= today - pd.DateOffset(years=1)]["value"]
                up = h.iloc[-1] >= h.iloc[0] if len(h) > 1 else True
                color = POS if up else NEG
                fig = go.Figure(go.Scatter(x=h.index, y=h, mode="lines", line=dict(color=color, width=2),
                                           fill="tozeroy", fillcolor=charts.hex_to_rgba(color, 0.10),
                                           hovertemplate="%{x|%d %b %Y}<br><b>%{y:,.0f} kr</b><extra></extra>"))
                fig.add_trace(go.Scatter(x=[h.index[-1]], y=[h.iloc[-1]], mode="markers", hoverinfo="skip",
                                         marker=dict(color=color, size=9, line=dict(width=2, color=charts.SURFACE))))
                lo, hi = float(h.min()), float(h.max())
                pad = (hi - lo) * 0.12 or hi * 0.05
                fig.update_layout(margin=dict(t=28, b=0, l=0, r=6), showlegend=False, hovermode="x",
                                  xaxis=dict(visible=False), yaxis=dict(visible=False, range=[lo - pad, hi + pad]),
                                  title=dict(text="Aktier senaste året", font=dict(size=12, color=charts.INK_2)))
                charts.show(fig, height=200)
    st.write("")


def _next_events(hold: pd.DataFrame) -> None:
    """Diskret rad med de närmaste rapporterna/utdelningarna."""
    if hold.empty:
        return
    try:
        import handelser as h
        ev = h.upcoming_events(list(hold["ticker"]), days=45)
    except Exception:
        return
    if ev.empty:
        return
    items = [f"**{r.name}** {r.kind.split(' (')[0].lower()} {r.date.day} {h.MONTHS[r.date.month - 1]}"
             for r in ev.head(3).itertuples()]
    a, b = st.columns([6, 1])
    a.caption("📅 På gång: " + " · ".join(items))
    if b.button("Kalender", key="ov_cal", use_container_width=True):
        st.switch_page(st.session_state["_pages"]["handelser"])


def render():
    tx = db.load_transactions()
    if tx.empty:
        st.title("📊 Portföljöversikt")
        ui_helpers.onboarding(tx)
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
    cash_map = db.get_cash()
    accs = sorted(set(tx["account"]) | {a for a, c in cash_map.items() if c})
    choice = None
    if len(accs) > 1:
        choice = st.segmented_control("Konto", ["Alla konton", *accs], default="Alla konton")
        if choice and choice != "Alla konton":
            tx = tx[tx["account"] == choice]
    cash = cash_map.get(choice, 0.0) if choice and choice != "Alla konton" else sum(cash_map.values())

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

    with st.spinner("Räknar på historiken…"):
        hist = _compute_history(tx)
    ui_helpers.onboarding(tx)
    _hero(value, cash, day, prev_value, total, hist)
    ui_helpers.quick_actions()
    _next_events(hold)
    if not hold.empty:
        import sida_utvardering
        with st.spinner("Sätter betyg på portföljen …"):
            sida_utvardering.overview_card(tx, hold, cash)
    try:
        import sida_bevakning
        hits = sida_bevakning.alerts()
    except Exception:
        hits = []
    if hits:
        names = ", ".join(f"{a['name']} ({a['kind']})" for a in hits[:4])
        a1, a2 = st.columns([5, 1])
        a1.caption(f"🔔 {len(hits)} bevakning{'ar' if len(hits) > 1 else ''} har nått din kurs: {names}")
        if a2.button("Visa", key="wl_goto"):
            st.switch_page(st.session_state["_pages"]["bevakning"])
    mal.render(tx, value + cash, cost, total, len(hold), set(hold["currency"]) if not hold.empty else set())
    if cash < 0:
        st.warning("Saldot för köp är negativt – kontrollera under **Mitt innehav → Pengar för köp**.")

    if hold.empty:
        st.warning("Inga öppna innehav just nu.")
    else:
        src = market.get_live_quotes(tuple(sorted(hold["ticker"])))["source"]
        n_av = int((src == "Avanza").sum())
        if market.use_avanza() and n_av:
            st.caption(f"🟢 Kurser från Avanza för {n_av} av {len(src)} innehav, övriga från Yahoo Finance.")
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
            if cash > 0:
                cash_group = "SEK" if by == "Valuta" else "💰 Kontanter"
                alloc = pd.concat([alloc, pd.DataFrame([{"group": cash_group, "value_sek": cash}])])
                alloc = alloc.groupby("group", as_index=False)["value_sek"].sum()
            alloc = alloc.sort_values("value_sek", ascending=False)
            if len(alloc) > 8:  # max 8 färger – resten samlas i "Övrigt"
                rest = alloc.iloc[7:]["value_sek"].sum()
                alloc = pd.concat([alloc.iloc[:7], pd.DataFrame([{"group": "Övrigt", "value_sek": rest}])])
            total_alloc = alloc["value_sek"].sum()
            fig = go.Figure(go.Pie(
                labels=alloc["group"], values=alloc["value_sek"], hole=0.72,
                marker=dict(colors=charts.CATEGORICAL[:len(alloc)], line=dict(color=charts.SURFACE, width=3)),
                textinfo="none", direction="clockwise", rotation=90,
                hovertemplate="<b>%{label}</b><br>%{value:,.0f} kr · %{percent}<extra></extra>",
            ))
            fig.add_annotation(text=f"<span style='font-size:12px;color:{charts.INK_2}'>Totalt</span><br>"
                                    f"<b>{fmt_sek(total_alloc)}</b>", showarrow=False, font=dict(size=17),
                               x=0.5, y=0.5, xref="paper", yref="paper")
            fig.update_layout(showlegend=True, margin=dict(t=10, b=10, l=10, r=10),
                              legend=dict(orientation="v", y=0.5, yanchor="middle", x=1.02, xanchor="left"))
            charts.show(fig, height=320)

        with right:
            st.subheader("Resultat per innehav")
            bar = hold.sort_values("unrealized_sek")
            colors = [charts.POS if v >= 0 else charts.NEG for v in bar["unrealized_sek"]]
            fig = go.Figure(go.Bar(
                x=bar["unrealized_sek"], y=bar["ticker"], orientation="h", marker_color=colors,
                width=0.55, customdata=bar["unrealized_pct"] * 100,
                text=[f"{v * 100:+.0f} %".replace(".", ",") for v in bar["unrealized_pct"]],
                textposition="outside", textfont=dict(color=charts.INK_2, size=11), cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>%{x:,.0f} kr · %{customdata:+.1f} %<extra></extra>",
            ))
            fig.update_layout(hovermode="closest", margin=dict(t=10, b=10, l=10, r=40),
                              xaxis=dict(title="Orealiserat (kr)", showgrid=True, zeroline=True,
                                         zerolinecolor="rgba(244,239,230,0.25)", zerolinewidth=1),
                              yaxis=dict(showgrid=False))
            charts.show(fig, height=max(240, 34 * len(bar) + 60))

        st.subheader("Innehav")
        table = hold.assign(
            name=hold["ticker"].map(lambda t: aktielista.POPULAR.get(t, t)),
            unrealized_pct=hold["unrealized_pct"] * 100,
            day_change_pct=hold["day_change_pct"] * 100,
            weight=hold["weight"] * 100,
            value_sek=hold["value_sek"].round(0), cost_sek=hold["cost_sek"].round(0),
            unrealized_sek=hold["unrealized_sek"].round(0), dividends_sek=hold["dividends_sek"].round(0),
        )[["name", "ticker", "qty", "gav_local", "price", "currency", "day_change_pct", "value_sek",
           "cost_sek", "unrealized_sek", "unrealized_pct", "dividends_sek", "weight"]]
        st.dataframe(
            table, hide_index=True, use_container_width=True,
            column_config={
                "name": st.column_config.TextColumn("Aktie", pinned=True),
                "ticker": "Ticker",
                "qty": st.column_config.NumberColumn("Antal", format="%g"),
                "gav_local": st.column_config.NumberColumn("GAV", format="%.2f", help="Genomsnittligt anskaffningsvärde i aktiens valuta"),
                "price": st.column_config.NumberColumn("Kurs", format="%.2f"),
                "currency": "Valuta",
                "day_change_pct": st.column_config.NumberColumn("Idag", format="%.2f %%"),
                "value_sek": st.column_config.NumberColumn("Värde (SEK)", format="localized"),
                "cost_sek": st.column_config.NumberColumn("Anskaffning (SEK)", format="localized"),
                "unrealized_sek": st.column_config.NumberColumn("Orealiserat (SEK)", format="localized"),
                "unrealized_pct": st.column_config.NumberColumn("Orealiserat %", format="%.1f %%"),
                "dividends_sek": st.column_config.NumberColumn("Utdelning (SEK)", format="localized"),
                "weight": st.column_config.ProgressColumn("Vikt", format="%.1f %%", min_value=0, max_value=100),
            },
        )

    _history_section(tx, hist)
    ui_helpers.glossary()


def _history_section(tx: pd.DataFrame, hist: pd.DataFrame):
    st.subheader("Utveckling över tid")
    c1, c2 = st.columns([1, 1])
    bench_name = c1.selectbox("Jämförelseindex", list(market.BENCHMARKS), index=0)
    period = c2.segmented_control("Period", ["3 m", "6 m", "1 år", "3 år", "Allt"], default="Allt")
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
        fig.add_trace(go.Scatter(x=hist.index, y=hist["invested"], name="Insatta pengar",
                                 line=dict(color=charts.NEUTRAL, width=1.5, shape="hv"),
                                 hovertemplate="%{y:,.0f} kr"))
        fig.add_trace(go.Scatter(x=hist.index, y=hist["value"], name="Marknadsvärde",
                                 line=dict(color=charts.ACCENT, width=2), fill="tozeroy",
                                 fillcolor=charts.hex_to_rgba(charts.ACCENT, 0.10), hovertemplate="%{y:,.0f} kr"))
        fig.update_layout(yaxis=dict(ticksuffix=" kr", tickformat=",.0f"))
        charts.show(fig, height=380)
    with tab2:
        twr = hist["twr_index"] / hist["twr_index"].iloc[0] * 100
        bench = market.get_closes((market.BENCHMARKS[bench_name],), start=hist.index[0].strftime("%Y-%m-%d"))
        fig = go.Figure()
        if not bench.empty:
            b = bench.iloc[:, 0].dropna()
            b = b / b.iloc[0] * 100
            fig.add_trace(go.Scatter(x=b.index, y=b, name=bench_name, line=dict(color=charts.CATEGORICAL[0]),
                                     hovertemplate="%{y:.1f}"))
            delta = twr.iloc[-1] / 100 - b.iloc[-1] / 100
            st.caption(f"Portfölj: {fmt_pct(twr.iloc[-1] / 100 - 1)} · {bench_name}: "
                       f"{fmt_pct(b.iloc[-1] / 100 - 1)} · Skillnad: {fmt_pct(delta)}")
        fig.add_trace(go.Scatter(x=twr.index, y=twr, name="Min portfölj", line=dict(color=charts.ACCENT),
                                 hovertemplate="%{y:.1f}"))
        fig.add_hline(y=100, line_color="rgba(244,239,230,0.2)", line_width=1)
        fig.update_layout(yaxis_title="Index (start = 100)")
        charts.show(fig, height=380)
        st.caption("TWR = tidsviktad avkastning, opåverkad av när du sätter in/tar ut pengar. Utdelningar räknas in.")
