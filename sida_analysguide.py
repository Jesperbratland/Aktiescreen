"""🧭 Analysguide i Aktieanalys – visar analysguide.py steg för steg med förklaringar och åtgärder."""
from __future__ import annotations

import html
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analysguide as ag
import analysis
import begrepp
import charts
import db
import market
import portfolio
from ui import fmt_num, fmt_sek

DOT = {"good": "🟢", "ok": "🟡", "bad": "🔴"}


def _color(score: float) -> str:
    if score != score:
        return charts.NEUTRAL
    return charts.POS if score >= 70 else charts.ACCENT if score >= 50 else charts.NEG


def _rows(items: list[dict]) -> None:
    if not items:
        st.caption("Det finns inte tillräckligt med data för det här steget.")
        return
    body = []
    for i in items:
        tip = begrepp.explain(i["term"])
        icon = f" <span class='term-i'>ⓘ<span class='term-tip'>{html.escape(tip)}</span></span>" if tip else ""
        body.append(f"<tr><td style='width:1.6rem'>{DOT.get(i['status'], '')}</td>"
                    f"<td style='white-space:nowrap'><b>{html.escape(i['label'])}</b>{icon}</td>"
                    f"<td style='white-space:nowrap;text-align:right'>{html.escape(str(i['value']))}</td>"
                    f"<td class='small-muted'>{html.escape(i['why'])}</td></tr>")
    st.markdown(f"<table class='terms'>{''.join(body)}</table>", unsafe_allow_html=True)


def _step_header(title: str, score: float | None, intro: str) -> None:
    sc = "" if score is None or score != score else (
        f" · <span style='color:{_color(score)}'>{score:.0f}/100</span>")
    st.markdown(f"#### {title}{sc}", unsafe_allow_html=True)
    st.caption(intro)


def _portfolio_context(ticker: str, sector: str) -> dict:
    tx = db.load_transactions()
    cash = sum(db.get_cash().values())
    out = {"total": cash, "cash": cash, "own_value": 0.0, "sector_value": 0.0, "n": 0}
    if tx.empty:
        return out
    pos = portfolio.compute_positions(tx)
    pos = pos[pos["qty"] > 0]
    if pos.empty:
        return out
    q = market.get_live_quotes(tuple(sorted(pos["ticker"])))
    fx = market.get_fx_now(tuple(sorted(set(pos["currency"]) | {"SEK"})))
    hold = portfolio.enrich_positions(portfolio.compute_positions(tx), q, fx)
    hold = hold[hold["value_sek"].notna()]
    out["total"] = float(hold["value_sek"].sum()) + cash
    out["n"] = len(hold)
    out["own_value"] = float(hold.loc[hold["ticker"] == ticker, "value_sek"].sum())
    out["sector_value"] = float(sum(v for t, v in zip(hold["ticker"], hold["value_sek"])
                                    if (market.get_info(t).get("sector") or "") == sector))
    return out


def render_guide(ticker: str, hist: pd.DataFrame, info: dict, cur: str) -> None:
    with st.spinner("Analyserar …"):
        res = ag.analyze(ticker, hist, info)
    d, c, prof = res["decision"], res["company"], res["profile"]

    # ---------- Sammanfattning ----------
    with st.container(border=True):
        a, b = st.columns([1, 2.4])
        tot = d["total"]
        a.markdown(f"<div style='font-size:.8rem;color:{charts.INK_2}'>Köpläge-poäng</div>"
                   f"<div style='font-size:3rem;font-weight:700;line-height:1;color:{_color(tot)}'>"
                   f"{'–' if tot != tot else f'{tot:.0f}'}<span style='font-size:1rem;color:{charts.INK_2}'>/100</span></div>",
                   unsafe_allow_html=True)
        with b:
            st.markdown(f"### {d['verdict']}")
            if d["timing"]:
                st.markdown(d["timing"])
            if d.get("capped"):
                st.caption("⚠️ " + d["capped"])
            st.caption(f"🏭 Anpassad för branschen **{prof['name'].lower()}**"
                       + (" (cyklisk)" if prof["cyclical"] else "") + " · nyheter och insynshandel är invägda.")
            pills = "".join(
                f"<div class='pill {'pos' if s == s and s >= 70 else 'neg' if s == s and s < 50 else ''}'>"
                f"<span>{k}</span><b>{'–' if s != s else f'{s:.0f}'}</b></div>" for k, s in d["parts"].items())
            st.markdown(f"<div class='hero-pills'>{pills}</div>", unsafe_allow_html=True)
    st.caption("Gå igenom flikarna i tur och ordning – precis som en analytiker gör. Varje rad visar 🟢 bra, "
               "🟡 okej eller 🔴 varning och förklarar varför. Håll över ⓘ för att se vad begreppet betyder.")

    t1, t2, t3, tn, t4, t5, t6 = st.tabs(["1 · Bolaget", "2 · Kvalitet", "3 · Värdering", "4 · Nyheter",
                                          "5 · Trend & köpsignal", "6 · Risk & storlek", "7 · Beslut"])

    # 1. Bolaget
    with t1:
        _step_header("1 · Förstå bolaget", None,
                     "Köp aldrig något du inte förstår. Börja med vad bolaget gör och hur det tjänar pengar.")
        k = st.columns(4)
        k[0].metric("Bransch", c["sector"] or "–", c["industry"] or None, delta_color="off")
        k[1].metric("Land", c["country"] or "–")
        k[2].metric("Storlek", c["size"].split(" (")[0], help=begrepp.TERMS["Börsvärde"])
        k[3].metric("Anställda", fmt_num(c["employees"], 0) if c["employees"] else "–")
        with st.container(border=True):
            st.markdown(f"**🏭 Så bedöms {prof['name'].lower()}**")
            st.markdown(prof["focus"])
            st.caption("Gränserna för 🟢🟡🔴, typiskt P/E och vilka värderingsmodeller som används är anpassade "
                       "efter branschen." + (" Branschen är cyklisk – lågt P/E räknas inte automatiskt som billigt."
                                             if prof["cyclical"] else ""))
        if c["summary"]:
            st.markdown(c["summary"][:700] + ("…" if len(c["summary"]) > 700 else ""))
            if len(c["summary"]) > 700:
                with st.expander("Läs hela beskrivningen"):
                    st.write(c["summary"])
        if c["website"]:
            st.markdown(f"🌐 [Bolagets webbplats]({c['website']}) – under *Investerare* hittar du rapporter och "
                        "årsredovisning.")
        st.markdown("**Frågor att kunna svara på innan du köper:**\n"
                    "- Hur tjänar bolaget pengar, och vilka är kunderna?\n"
                    "- Vad gör det svårt för konkurrenter att ta över (varumärke, patent, storlek, nätverk)?\n"
                    "- Växer marknaden bolaget verkar i?\n"
                    "- Vad är det största som kan gå fel?")

    # 2. Kvalitet
    with t2:
        _step_header("2 · Är det ett bra bolag?", res["quality"]["score"],
                     "Kvalitetsbolag tjänar mycket på sitt kapital, har bra marginaler, växer och har lagom med skulder. "
                     f"De klarar sig ofta bättre i sämre tider. Gränserna är satta för {prof['name'].lower()}.")
        _rows(res["quality"]["items"])

    # 3. Värdering
    with t3:
        v = res["valuation"]
        _step_header("3 · Är aktien dyr eller billig?", v["score"],
                     "Även ett fantastiskt bolag kan vara en dålig affär om du betalar för mycket. Här jämförs priset "
                     "med vinsten, tillväxten och branschen.")
        _rows(v["items"])
        fair = v["fair"]
        st.markdown("##### 💡 Vad är ett rimligt pris?")
        if "mid" not in fair:
            st.caption("Det finns för lite data (vinst, eget kapital eller utdelning) för att räkna fram ett rimligt värde."
                       + (" " + fair["skipped_note"] if fair.get("skipped_note") else ""))
        else:
            price = res["price"]
            k = st.columns(3)
            k[0].metric("Dagens kurs", f"{fmt_num(price, 2)} {cur}")
            k[1].metric("Rimligt värde (mitten)", f"{fmt_num(fair['mid'], 2)} {cur}",
                        f"{fair['margin'] * 100:+.0f} %".replace(".", ","), delta_color="normal")
            k[2].metric("Spann", f"{fmt_num(fair['low'], 0)}–{fmt_num(fair['high'], 0)} {cur}")
            st.markdown(f"**{fair['verdict']}** – {fair['why']}")
            if fair.get("skipped_note"):
                st.caption(fair["skipped_note"])
            fig = go.Figure()
            for i, (name, val, _) in enumerate(fair["methods"]):
                if val == val and val > 0:
                    fig.add_trace(go.Scatter(x=[val], y=[name], mode="markers", showlegend=False,
                                             marker=dict(size=14, color=charts.CATEGORICAL[i],
                                                         line=dict(width=2, color=charts.SURFACE)),
                                             hovertemplate=f"{name}: %{{x:,.2f}} {cur}<extra></extra>"))
            fig.add_vline(x=price, line_color=charts.INK, line_width=1.5,
                          annotation_text=f"Kurs {fmt_num(price, 1)}", annotation_position="top")
            fig.add_vrect(x0=fair["low"], x1=fair["high"], fillcolor=charts.hex_to_rgba(charts.ACCENT, 0.08), line_width=0)
            fig.update_layout(hovermode="closest", yaxis=dict(showgrid=False), xaxis=dict(title=cur),
                              margin=dict(t=30, b=10, l=10, r=10))
            charts.show(fig, height=60 * len(fair["methods"]) + 90)
            with st.expander("Hur räknas det?"):
                for name, val, how in fair["methods"]:
                    st.markdown(f"**{name}: {fmt_num(val, 2)} {cur}**  \n{how}")
                for name, val, how in fair.get("dropped", []):
                    st.markdown(f"~~{name}: {fmt_num(val, 2)} {cur}~~ – räknas inte med eftersom den avviker "
                                f"kraftigt från de andra metoderna. {how}")
                st.caption("Alla modeller är förenklingar. Använd spannet som en fingervisning – inte ett exakt pris.")

    # 4. Nyheter
    with tn:
        n = res["news"]
        _step_header("4 · Vad händer i bolaget just nu?", n.get("score"),
                     "Siffrorna ovan bygger på senaste rapporten. Nyheter som vinstvarningar, nyemissioner, stora "
                     "order eller höjd prognos kan ändra bilden snabbt – därför vägs de in.")
        for r_ in n.get("red", [])[:3]:
            st.warning(f"**{', '.join(r_['flags']).capitalize()}:** [{r_['title']}]({r_['url']}) "
                       f"· {r_['source']}")
        _rows(n.get("items", []))
        heads = n.get("headlines", [])
        if heads:
            st.markdown("##### 📰 Senaste rubrikerna")
            from handelser import ago
            for h_ in heads:
                dot = "🟢" if h_["tone"] > 0 else "🔴" if h_["tone"] < 0 else "⚪"
                when = ago(h_["ts"]) if h_.get("ts") is not None else ""
                st.markdown(f"{dot} [{h_['title']}]({h_['url']})  \n"
                            f"<span class='small-muted'>{html.escape(h_['source'])} · {when}</span>",
                            unsafe_allow_html=True)
            st.caption("🟢 positiv · 🔴 negativ · ⚪ neutral rubrik. Tonen bedöms automatiskt med nyckelord, så den "
                       "kan bli fel – läs alltid själva nyheten innan du agerar.")
        else:
            st.caption("Hittade inga nyheter om bolaget de senaste veckorna.")

    # 5. Trend
    with t4:
        t = res["trend"]
        _step_header("5 · Är det rätt läge att köpa?", t["score"],
                     "Trend och momentum säger inget om bolaget, men mycket om timing. Att köpa i en upptrend minskar "
                     "risken att köpa något som fortsätter falla.")
        _rows(t["items"])
        if d["timing"]:
            st.info(d["timing"])
        close = hist["Close"].dropna()
        one = close[close.index >= close.index[-1] - pd.DateOffset(years=1)]
        if len(one) > 20:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=one.index, y=one, name="Kurs", line=dict(color=charts.ACCENT)))
            fig.add_trace(go.Scatter(x=one.index, y=analysis.sma(close, 50).loc[one.index], name="MA50",
                                     line=dict(color=charts.CATEGORICAL[1], width=1.5)))
            fig.add_trace(go.Scatter(x=one.index, y=analysis.sma(close, 200).loc[one.index], name="MA200",
                                     line=dict(color=charts.CATEGORICAL[0], width=1.5)))
            charts.show(fig, height=300)
        good = sum(1 for i in t["items"] if i["status"] == "good")
        st.markdown(f"**Köpsignaler: {good} av {len(t['items'])} positiva.**")

    # 5. Risk & storlek
    with t5:
        r = res["risk"]
        _step_header("6 · Hur riskabel är den – och hur mycket ska jag köpa?", r["score"],
                     "Ju mer en aktie svänger, desto mindre del av portföljen bör den vara. Då klarar du ett ras utan "
                     "att hela sparandet tar stryk.")
        _rows(r["items"])
        ctx = _portfolio_context(ticker, info.get("sector") or "")
        if ctx["total"] > 0:
            fx = market.get_fx_now(tuple(sorted({cur.upper() or "SEK", "SEK"}))).get(cur.upper() or "SEK", 1.0)
            unit = res["price"] * fx
            target = r["max_weight"] * (ctx["total"] + 0)
            room = max(target - ctx["own_value"], 0.0)
            shares = int(room // unit) if unit else 0
            st.markdown("##### 🧮 Förslag på storlek")
            k = st.columns(3)
            k[0].metric("Max andel av portföljen", f"{r['max_weight'] * 100:.0f} %",
                        help="10 % för lugna aktier, 7 % för normala, 4 % för riskabla.")
            k[1].metric("Köp för upp till", fmt_sek(room),
                        f"äger redan {fmt_sek(ctx['own_value'])}" if ctx["own_value"] else None, delta_color="off")
            k[2].metric("Ungefär antal aktier", f"{shares} st")
            if room > ctx["cash"] > 0:
                st.caption(f"Du har {fmt_sek(ctx['cash'])} tillgängligt för köp – det räcker till ungefär "
                           f"{int(ctx['cash'] // unit) if unit else 0} aktier.")
            if ctx["sector_value"] and ctx["total"]:
                after = (ctx["sector_value"] + room) / (ctx["total"])
                st.caption(f"Branschen {res['company']['sector'].lower()} utgör {fmt_num(ctx['sector_value'] / ctx['total'] * 100, 0)} % "
                           f"av portföljen idag – efter köpet ca {fmt_num(after * 100, 0)} %."
                           + (" ⚠️ Det är mycket i en bransch." if after > 0.4 else ""))
            import sida_analys
            sida_analys._buy_calc(ticker, res["price"], cur)
        else:
            st.caption("Lägg in dina innehav och pengar för köp så föreslår guiden hur mycket du kan köpa.")

    # 6. Beslut
    with t6:
        _step_header("7 · Beslut", d["total"], "Väg ihop allt. Ingen aktie är perfekt – frågan är om fördelarna "
                                               "väger tyngre än nackdelarna, och om priset är rätt.")
        st.markdown(f"### {d['verdict']}")
        a, b = st.columns(2)
        with a:
            st.markdown("**👍 Talar för**")
            for p in d["pros"] or ["–"]:
                st.markdown(f"- {p}")
        with b:
            st.markdown("**👎 Talar emot**")
            for p in d["cons"] or ["–"]:
                st.markdown(f"- {p}")
        st.markdown("**✅ Din checklista innan köp**")
        checks = ["Jag förstår hur bolaget tjänar pengar", "Jag har läst eller skummat den senaste rapporten",
                  "Jag kan förklara varför jag köper (mitt investeringscase)",
                  "Jag vet när jag säljer – om caset inte håller eller ett mål nås",
                  "Köpet passar min spridning och är inte för stort"]
        done = sum(st.checkbox(cl, key=f"chk_{ticker}_{i}") for i, cl in enumerate(checks))
        if done == len(checks):
            st.success("Bra jobbat – du har gjort en ordentlig analys. Beslutet är ditt.")
        st.markdown("**Nästa steg**")
        ns = ag.next_step(res)
        st.info(ns["why"])
        x, y, z = st.columns(3)
        if ns["action"] == "buy":
            if x.button("🛒 Registrera köp", type="primary", use_container_width=True, key=f"g_buy_{ticker}"):
                st.switch_page(st.session_state["_pages"]["transaktioner"])
            watch_label = f"👀 Bevaka – larm vid {fmt_num(ns['price'], 2)}"
            watch_col = y
        else:
            watch_label = f"👀 Bevaka – köpkurs {fmt_num(ns['price'], 2)}"
            watch_col = x
        if watch_col.button(watch_label, use_container_width=True, key=f"g_watch_{ticker}",
                            type="secondary" if ns["action"] == "buy" else "primary"):
            db.add_watch(ticker, c["name"] or ticker, res["price"])
            wl = db.load_watchlist()
            wl.loc[wl["ticker"] == ticker, "buy_below"] = ns["price"]
            wl.loc[wl["ticker"] == ticker, "note"] = (f"Analys {pd.Timestamp.today():%Y-%m-%d}: {d['verdict']} "
                                                      f"({d['total']:.0f}/100)")
            db.save_watchlist(wl)
            st.toast("Tillagd i bevakningslistan med köplarm", icon="👀")
        if z.button("🐺 Fråga Vargen om aktien", use_container_width=True, key=f"g_varg_{ticker}"):
            heads = "; ".join(h_["title"] for h_ in res["news"].get("headlines", [])[:5])
            st.session_state["vargen_pending"] = (
                f"Vad tycker du om {c['name'] or ticker} ({ticker})? Bransch: {prof['name']}. "
                f"Min analysguide säger {d['verdict']} ({d['total']:.0f}/100)."
                + (f" Senaste rubrikerna: {heads}. Väg in nyheterna och vad som är viktigt i branschen." if heads else ""))
            st.switch_page(st.session_state["_pages"]["vargen"])
        st.caption("Guiden bygger på vanliga tumregler och data från Yahoo Finance, som kan vara ofullständig. "
                   "Det är inte finansiell rådgivning – gör alltid din egen bedömning.")
