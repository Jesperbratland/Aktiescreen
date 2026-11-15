"""🏅 Portföljbetyg – djupgående utvärdering av portföljen."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import db
import market
import portfolio
import utvardering as ev
from ui import fmt_num, fmt_pct, fmt_sek


def score_color(score: float) -> str:
    if score != score:
        return charts.NEUTRAL
    return charts.POS if score >= 75 else charts.ACCENT if score >= 55 else charts.NEG


def load_evaluation() -> dict:
    tx = db.load_transactions()
    cash = sum(db.get_cash().values())
    if tx.empty:
        return ev.evaluate(tx, pd.DataFrame(), cash)
    pos = portfolio.compute_positions(tx)
    open_pos = pos[pos["qty"] > 0]
    if open_pos.empty:
        return ev.evaluate(tx, pd.DataFrame(), cash)
    quotes = market.get_live_quotes(tuple(sorted(open_pos["ticker"])))
    fx = market.get_fx_now(tuple(sorted(set(open_pos["currency"]) | {"SEK"})))
    hold = portfolio.enrich_positions(pos, quotes, fx)
    return ev.evaluate(tx, hold, cash, db.load_accounts())


def _gauge(score: float, grade: str) -> go.Figure:
    color = score_color(score)
    fig = go.Figure(go.Pie(values=[max(score, 0), 100 - max(score, 0)], hole=0.82, sort=False,
                           direction="clockwise", rotation=0, textinfo="none", hoverinfo="skip",
                           marker=dict(colors=[color, "rgba(244,239,230,0.08)"], line=dict(width=0))))
    fig.add_annotation(text=f"<b>{score:.0f}</b>", x=0.5, y=0.56, xref="paper", yref="paper", showarrow=False,
                       font=dict(size=46, color=charts.INK))
    fig.add_annotation(text=f"av 100 · betyg <b>{grade}</b>", x=0.5, y=0.34, xref="paper", yref="paper",
                       showarrow=False, font=dict(size=14, color=charts.INK_2))
    fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
    return fig


def render():
    st.title("🏅 Portföljbetyg")
    st.caption("En genomgång av din portfölj på åtta områden, med konkreta förslag. Poängen bygger på vanliga "
               "tumregler för långsiktigt sparande – inte på någon garanti om framtiden.")
    with st.spinner("Utvärderar portföljen …"):
        res = load_evaluation()
    if res["total"] != res["total"]:
        st.info(res["verdict"] or "För lite data för att utvärdera portföljen.")
        return
    history = ev.save_history(res["total"])

    # ---------- Toppen: mätare + sammanfattning ----------
    with st.container(border=True):
        a, b = st.columns([1, 1.6])
        with a:
            charts.show(_gauge(res["total"], res["grade"]), height=240)
        with b:
            st.markdown(f"### {res['verdict']}")
            if res.get("cap_note"):
                st.caption("⚠️ " + res["cap_note"])
            if len(history) > 1:
                prev = history.iloc[-2]
                d = res["total"] - prev
                st.caption(f"{'▲' if d >= 0 else '▼'} {abs(d):.0f} poäng sedan {history.index[-2]}")
            if res.get("strengths"):
                st.markdown("**👍 Styrkor**")
                for name, text in res["strengths"]:
                    st.markdown(f"- {ev.ICONS[name]} {text}")
            if res.get("improvements"):
                st.markdown("**🛠️ Viktigast att förbättra**")
                for name, text in res["improvements"][:3]:
                    st.markdown(f"- {ev.ICONS[name]} {text}")

    # ---------- Delbetyg ----------
    st.subheader("Delbetyg")
    cats = [c for c in res["categories"] if c["score"] == c["score"]]
    cats_sorted = sorted(cats, key=lambda c: c["score"])
    fig = go.Figure(go.Bar(
        x=[c["score"] for c in cats_sorted], y=[f"{ev.ICONS[c['name']]} {c['name']}" for c in cats_sorted],
        orientation="h", width=0.55, marker_color=[score_color(c["score"]) for c in cats_sorted],
        text=[f"{c['score']:.0f}" for c in cats_sorted], textposition="outside",
        textfont=dict(color=charts.INK_2), cliponaxis=False,
        customdata=[f"{c['weight'] * 100:.0f} %" for c in cats_sorted],
        hovertemplate="<b>%{y}</b><br>%{x:.0f} av 100 · väger %{customdata}<extra></extra>"))
    fig.update_layout(hovermode="closest", margin=dict(t=10, b=10, l=10, r=40),
                      xaxis=dict(range=[0, 105], showgrid=True, tickvals=[0, 25, 50, 75, 100]),
                      yaxis=dict(showgrid=False))
    charts.show(fig, height=40 * len(cats) + 60)

    # ---------- Detaljer per område ----------
    st.subheader("Område för område")
    cols = st.columns(2)
    for i, c in enumerate(res["categories"]):
        with cols[i % 2].container(border=True):
            sc = "–" if c["score"] != c["score"] else f"{c['score']:.0f}"
            st.markdown(f"#### {ev.ICONS[c['name']]} {c['name']} · <span style='color:{score_color(c['score'])}'>"
                        f"{sc}</span>", unsafe_allow_html=True)
            st.caption(ev.EXPLAIN[c["name"]] + f" Väger {c['weight'] * 100:.0f} % av betyget.")
            for f in c["facts"]:
                st.markdown(f"- {f}")
            for t in c["tips"]:
                st.markdown(f"💡 {t}")
            if not c["tips"] and c["score"] == c["score"]:
                st.markdown("✅ Inget att anmärka på.")

    # ---------- Risk på djupet ----------
    rd = res.get("risk") or {}
    if rd:
        st.subheader("🎢 Risk på djupet")
        k = st.columns(4)
        k[0].metric("Svängningar per år", fmt_pct(rd["vol"], 1, sign=False),
                    help="Hur mycket värdet brukar variera på ett år. Börsen i stort: ca 15–20 %.")
        k[1].metric("Största fall (1 år)", fmt_pct(rd["mdd"], 1))
        k[2].metric("Beta", fmt_num(rd.get("beta"), 2),
                    help="1 = rör sig som OMXS30. 1,3 = rör sig 30 % mer än börsen, upp som ner.")
        k[3].metric("Senaste året", fmt_pct(rd["ret_1y"], 1),
                    f"OMXS30 {fmt_pct(rd.get('bench_1y'), 1)}", delta_color="off")

        value = float(res["hold"]["value_sek"].sum())
        beta = rd.get("beta") or 1.0
        st.markdown("**Om börsen föll …** (uppskattat med portföljens beta)")
        s = st.columns(3)
        for col, drop in zip(s, (0.10, 0.20, 0.30)):
            col.metric(f"Börsen −{drop * 100:.0f} %", fmt_sek(-value * drop * beta),
                       fmt_pct(-drop * beta, 0), delta_color="off")

        left, right = st.columns(2)
        if "risk_contrib" in rd:
            with left:
                st.markdown("**Vem står för risken?**")
                rc = rd["risk_contrib"].clip(lower=0).sort_values()
                wts = rd["weights"].reindex(rc.index)
                f2 = go.Figure()
                f2.add_trace(go.Bar(y=rc.index, x=wts * 100, orientation="h", name="Andel av pengarna",
                                    marker_color=charts.NEUTRAL, width=0.35,
                                    hovertemplate="%{x:.1f} % av pengarna<extra></extra>"))
                f2.add_trace(go.Bar(y=rc.index, x=rc * 100, orientation="h", name="Andel av risken",
                                    marker_color=charts.ACCENT, width=0.35,
                                    hovertemplate="%{x:.1f} % av risken<extra></extra>"))
                f2.update_layout(barmode="group", hovermode="y unified", xaxis=dict(ticksuffix=" %"),
                                 yaxis=dict(showgrid=False), margin=dict(t=30, b=10, l=10, r=10))
                charts.show(f2, height=max(240, 46 * len(rc) + 60))
                st.caption("Står ett bolag för mer risk än pengar svänger det mer än resten.")
        corr = rd.get("corr")
        if corr is not None and len(corr) >= 2:
            with right:
                st.markdown("**Hur lika rör sig dina aktier?**")
                f3 = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1,
                                          colorscale=[[0, "#3987e5"], [0.5, "#1B2B26"], [1, "#d95926"]],
                                          xgap=2, ygap=2, colorbar=dict(thickness=10, outlinewidth=0),
                                          hovertemplate="%{y} & %{x}: %{z:.2f}<extra></extra>"))
                f3.update_layout(hovermode="closest", xaxis=dict(showgrid=False, tickangle=-45),
                                 yaxis=dict(showgrid=False, autorange="reversed"), margin=dict(t=30, b=10, l=10, r=10))
                charts.show(f3, height=max(260, 34 * len(corr) + 100))
                st.caption("Orange = rör sig ofta åt samma håll (sämre spridning). Blått = rör sig olika.")

    # ---------- Utdelning ----------
    div = res.get("dividend") or {}
    if div.get("annual"):
        st.subheader("💸 Förväntad utdelning")
        d = st.columns(3)
        d[0].metric("Per år", fmt_sek(div["annual"]))
        d[1].metric("Per månad i snitt", fmt_sek(div["annual"] / 12))
        d[2].metric("Direktavkastning", fmt_pct(div["yield"], 1, sign=False))
        st.caption("Baserat på bolagens senaste årliga utdelning och dina antal aktier idag.")

    # ---------- Historik ----------
    if len(history) > 1:
        st.subheader("📅 Betyget över tid")
        f4 = go.Figure(go.Scatter(x=pd.to_datetime(history.index), y=history.values, mode="lines+markers",
                                  line=dict(color=charts.ACCENT), hovertemplate="%{y:.0f} poäng<extra></extra>"))
        f4.update_layout(yaxis=dict(range=[0, 100]), hovermode="closest")
        charts.show(f4, height=240)
    st.caption("Betyget sparas en gång per dag när du öppnar sidan eller Översikten. Inte finansiell rådgivning.")


def overview_card(tx, hold, cash) -> None:
    """Litet betygskort till Översikten."""
    try:
        res = ev.evaluate(tx, hold, cash, db.load_accounts())
    except Exception:
        return
    if res["total"] != res["total"]:
        return
    ev.save_history(res["total"])
    color = score_color(res["total"])
    tip = res["improvements"][0][1] if res.get("improvements") else "Inget akut att förbättra – snyggt jobbat!"
    with st.container(border=True):
        a, b, c = st.columns([1.1, 3.4, 1.2])
        a.markdown(f"<div style='font-size:.8rem;color:{charts.INK_2}'>🏅 Portföljbetyg</div>"
                   f"<div style='font-size:2rem;font-weight:700;line-height:1.1;color:{color}'>{res['total']:.0f}"
                   f"<span style='font-size:1rem;color:{charts.INK_2}'> /100 · {res['grade']}</span></div>",
                   unsafe_allow_html=True)
        b.markdown(f"<div style='font-size:.8rem;color:{charts.INK_2}'>Tips</div>{tip}", unsafe_allow_html=True)
        c.write("")
        if c.button("Se utvärdering →", use_container_width=True, key="eval_card"):
            st.switch_page(st.session_state["_pages"]["utvardering"])
