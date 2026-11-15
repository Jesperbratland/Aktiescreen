"""📅 Kalender & nyheter: kommande rapporter och utdelningar, utdelningsprognos, nyheter och insynshandel."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import db
import handelser as h
import portfolio
from ui import fmt_num, fmt_sek


def _holdings() -> list[tuple[str, float, str]]:
    tx = db.load_transactions()
    if tx.empty:
        return []
    pos = portfolio.compute_positions(tx)
    pos = pos[pos["qty"] > 0]
    return [(r.ticker, float(r.qty), r.currency) for r in pos.itertuples()]


def _scope_tickers(scope: str, holds) -> list[str]:
    own = [t for t, _, _ in holds]
    watch = db.load_watchlist()["ticker"].tolist()
    if scope == "Mina innehav":
        return own
    if scope == "Bevakningslistan":
        return watch
    return list(dict.fromkeys(own + watch))


def news_list(items: list[dict], show_company: str | None = None) -> None:
    if not items:
        st.caption("Inga nyheter hittades den senaste månaden.")
        return
    for it in items:
        prefix = f"**{show_company}** · " if show_company else ""
        st.markdown(f"{prefix}[{it['title']}]({it['url']})  \n"
                    f"<span class='small-muted'>{it['source']} · {h.ago(it['ts'])}</span>", unsafe_allow_html=True)


def insider_view(ticker: str, compact: bool = False) -> None:
    df = h.insider(ticker)
    s = h.insider_summary(df)
    if df.empty:
        st.caption("Ingen insynshandel hittades det senaste halvåret.")
    else:
        k = st.columns(3)
        k[0].metric("Signal", s["signal"])
        k[1].metric("Köp / sälj", f"{s['buys']} / {s['sells']}")
        cur = df["currency"].dropna().iloc[0] if df["currency"].notna().any() else ""
        k[2].metric("Netto köpt", f"{fmt_num(s['net'], 0)} {cur}".strip())
        show = df.head(8 if compact else 30)
        st.dataframe(pd.DataFrame({
            "Datum": show["date"].dt.strftime("%Y-%m-%d"), "Person": show["person"], "Roll": show["role"],
            "Typ": show["side"], "Antal": show["volume"], "Kurs": show["price"], "Belopp": show["value"],
        }), hide_index=True, use_container_width=True, column_config={
            "Antal": st.column_config.NumberColumn(format="localized"),
            "Kurs": st.column_config.NumberColumn(format="%.2f"),
            "Belopp": st.column_config.NumberColumn(format="localized")})
    if ticker.upper().endswith(".ST"):
        st.markdown(f"[🔎 Öppna Finansinspektionens insynsregister för {h.core_name(ticker)}]({h.fi_search_url(ticker)})")


def render():
    st.title("📅 Kalender & nyheter")
    st.caption("Kommande rapporter och utdelningar, vad du kan räkna med i utdelning, de senaste nyheterna och "
               "vad bolagens ledning köper och säljer.")
    holds = _holdings()
    scope = st.segmented_control("Visa för", ["Mina innehav", "Bevakningslistan", "Båda"], default="Mina innehav",
                                 key="ev_scope") or "Mina innehav"
    tickers = _scope_tickers(scope, holds)
    if not tickers:
        st.info("Inga aktier här ännu. Lägg in innehav under **➕ Mitt innehav** eller bevaka aktier under **👀 Bevakningslista**.")
        return

    t1, t2, t3, t4 = st.tabs(["📅 Kommande", "💸 Utdelningar", "📰 Nyheter", "🕵️ Insynshandel"])

    with t1:
        with st.spinner("Hämtar kalender …"):
            ev = h.upcoming_events(tickers, days=120)
            fc = h.dividend_forecast([x for x in holds if x[0] in tickers]) if holds else pd.DataFrame()
        if not fc.empty:
            proj = fc[fc["status"] == "Prognos"]
            proj = proj[proj["date"] <= dt.date.today() + dt.timedelta(days=120)]
            extra = pd.DataFrame({"date": proj["date"], "ticker": proj["ticker"], "name": proj["name"],
                                  "kind": "💸 Väntad utdelning (prognos, " + proj["kr"].map(lambda v: fmt_sek(v)) + ")"})
            ev = pd.concat([ev, extra], ignore_index=True).sort_values("date") if not ev.empty else extra
        if ev is None or ev.empty:
            st.info("Inga kända rapporter eller utdelningar de närmaste fyra månaderna.")
        else:
            for month, g in ev.groupby(pd.to_datetime(ev["date"]).dt.to_period("M"), sort=True):
                st.markdown(f"##### {h.MONTHS[month.month - 1].capitalize()} {month.year}")
                for r in g.itertuples():
                    a, b = st.columns([1, 4])
                    a.markdown(f"**{r.date.day} {h.MONTHS[r.date.month - 1]}**  \n"
                               f"<span class='small-muted'>{h.days_text(r.date)}</span>", unsafe_allow_html=True)
                    b.markdown(f"**{r.name}** · {r.kind}")
        st.caption("Datum från Yahoo Finance. Rapportdatum kan ändras – bolagens egna finansiella kalendrar gäller.")

    with t2:
        if not holds:
            st.info("Utdelningsprognosen bygger på dina innehav – lägg in dem först.")
        else:
            with st.spinner("Räknar på utdelningar …"):
                fc = h.dividend_forecast([x for x in holds if x[0] in tickers] or holds)
            tx = db.load_transactions()
            got = tx[(tx["type"] == "UTDELNING") & (pd.to_datetime(tx["date"]) >= pd.Timestamp.today() - pd.Timedelta(days=365))]
            received = float((got["quantity"] * got["price"] * got["fx_rate"] - got["fee"]).sum())
            total = float(fc["kr"].sum()) if not fc.empty else 0.0
            k = st.columns(4)
            k[0].metric("Väntat kommande 12 mån", fmt_sek(total))
            k[1].metric("Per månad i snitt", fmt_sek(total / 12))
            nxt = fc.iloc[0] if not fc.empty else None
            k[2].metric("Nästa utdelning", fmt_sek(nxt["kr"]) if nxt is not None else "–",
                        f"{nxt['name']} · {h.days_text(nxt['date'])}" if nxt is not None else None, delta_color="off")
            k[3].metric("Fått senaste 12 mån", fmt_sek(received), help="Registrerade utdelningar under Transaktioner.")
            if fc.empty:
                st.caption("Inga utdelningar hittades för dina innehav det senaste året.")
            else:
                start = pd.Timestamp.today().normalize().replace(day=1)
                months = pd.period_range(start, periods=12, freq="M")
                per = fc.assign(m=pd.to_datetime(fc["date"]).dt.to_period("M")).groupby("m")["kr"].sum()
                vals = [float(per.get(m, 0.0)) for m in months]
                fig = go.Figure(go.Bar(x=[f"{h.MONTHS[m.month - 1]} {str(m.year)[2:]}" for m in months], y=vals,
                                       marker_color=charts.ACCENT, width=0.6,
                                       text=[fmt_sek(v) if v else "" for v in vals], textposition="outside",
                                       textfont=dict(color=charts.INK_2, size=11), cliponaxis=False,
                                       hovertemplate="%{x}: %{y:,.0f} kr<extra></extra>"))
                fig.update_layout(hovermode="closest", yaxis=dict(ticksuffix=" kr", tickformat=",.0f"),
                                  xaxis=dict(showgrid=False), margin=dict(t=30, b=10, l=10, r=10))
                charts.show(fig, height=300)
                st.dataframe(pd.DataFrame({
                    "Datum (X-dag)": fc["date"].map(h.fmt_date), "Bolag": fc["name"],
                    "Per aktie": fc["per_share"].round(2).astype(str) + " " + fc["currency"],
                    "Antal": fc["qty"], "Belopp (kr)": fc["kr"].round(0), "Status": fc["status"],
                }), hide_index=True, use_container_width=True, column_config={
                    "Antal": st.column_config.NumberColumn(format="%g"),
                    "Belopp (kr)": st.column_config.NumberColumn(format="localized")})
                st.caption("Prognosen upprepar varje utdelning från det senaste året ett år framåt, med dina antal "
                           "aktier idag och dagens valutakurs. Pengarna kommer oftast några dagar efter X-dagen.")

    with t3:
        names = {t: h.company_name(t) for t in tickers}
        pick = st.selectbox("Bolag", ["Alla"] + tickers, format_func=lambda t: "Alla bolag" if t == "Alla" else names[t],
                            key="news_pick")
        with st.spinner("Hämtar nyheter …"):
            if pick == "Alla":
                items = []
                for t in tickers[:20]:
                    for it in h.news(t, limit=4):
                        items.append({**it, "company": names[t]})
                items.sort(key=lambda x: x["ts"] if x["ts"] is not None and not pd.isna(x["ts"])
                           else pd.Timestamp("1970-01-01", tz="UTC"), reverse=True)
                for it in items[:30]:
                    st.markdown(f"**{it['company']}** · [{it['title']}]({it['url']})  \n"
                                f"<span class='small-muted'>{it['source']} · {h.ago(it['ts'])}</span>",
                                unsafe_allow_html=True)
                if not items:
                    st.caption("Inga nyheter hittades.")
            else:
                news_list(h.news(pick, limit=15))
        st.caption("Rubriker från Yahoo Finance och Google Nyheter. Klicka för att läsa hos källan.")

    with t4:
        st.caption("Personer i ledande ställning (vd, styrelse m.fl.) måste rapportera sina affärer i bolaget. "
                   "Många ser insiderköp som en positiv signal – de känner bolaget bäst.")
        with st.spinner("Hämtar insynshandel …"):
            rows = []
            for t in tickers[:25]:
                df = h.insider(t)
                s = h.insider_summary(df)
                rows.append({"ticker": t, "Bolag": h.company_name(t), "Signal": s["signal"], "Köp": s["buys"],
                             "Sälj": s["sells"], "Senaste": df["date"].max().strftime("%Y-%m-%d") if not df.empty else "–"})
        summary = pd.DataFrame(rows)
        st.dataframe(summary.drop(columns="ticker"), hide_index=True, use_container_width=True)
        pick = st.selectbox("Detaljer för", tickers, format_func=lambda t: h.company_name(t), key="ins_pick")
        insider_view(pick)
        st.caption("Svenska bolag: Finansinspektionens insynsregister, senaste halvåret. Utländska: Yahoo Finance.")
