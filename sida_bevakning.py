"""👀 Bevakningslista: aktier du spanar på, med kurslarm, minigraf och signaler."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

import aktielista
import analysis
import db
import market
from ui import fmt_num, fmt_pct


def alerts(wl: pd.DataFrame | None = None) -> list[dict]:
    """Bevakningar som nått köp- eller säljlarmet. Används även av Översikten."""
    wl = db.load_watchlist() if wl is None else wl
    if wl.empty or (wl["buy_below"].isna().all() and wl["sell_above"].isna().all()):
        return []
    q = market.get_live_quotes(tuple(wl["ticker"]))
    out = []
    for r in wl.itertuples():
        price = q["last"].get(r.ticker, math.nan)
        if math.isnan(price):
            continue
        if pd.notna(r.buy_below) and price <= r.buy_below:
            out.append({"ticker": r.ticker, "name": r.name, "kind": "köp", "price": price, "level": r.buy_below})
        if pd.notna(r.sell_above) and price >= r.sell_above:
            out.append({"ticker": r.ticker, "name": r.name, "kind": "sälj", "price": price, "level": r.sell_above})
    return out


def _add_picker():
    k = st.session_state.get("wl_n", 0)
    c1, c2 = st.columns([4, 1])
    choice = c1.selectbox("Lägg till aktie", aktielista.options(), index=None, key=f"wl_pick_{k}",
                          accept_new_options=True, label_visibility="collapsed",
                          placeholder="➕ Lägg till: skriv bolagsnamn, t.ex. Saab, Nvidia …")
    ticker = name = None
    if choice:
        ticker = aktielista.ticker_from_label(choice)
        if ticker:
            name = aktielista.POPULAR[ticker]
        else:
            res = market.search_ticker(choice)
            if not res.empty:
                res = res[res["Typ"].isin(["EQUITY", "ETF"]) & res["Ticker"].notna()].reset_index(drop=True)
            if res.empty:
                st.warning("Hittade ingen aktie med det namnet.")
                return
            labels = [f"{r.Namn} · {r.Ticker} ({r.Börs})" for r in res.itertuples()]
            i = st.radio("Vilken menar du?", range(len(labels)), format_func=lambda i: labels[i], key=f"wl_res_{k}",
                         horizontal=False)
            ticker, name = res.loc[i, "Ticker"], res.loc[i, "Namn"]
    c2.write("")
    if c2.button("Bevaka", type="primary", disabled=not ticker, use_container_width=True, key=f"wl_add_{k}"):
        q = market.get_live_quotes((ticker,))
        price = q["last"].get(ticker, math.nan)
        if db.add_watch(ticker, name, None if math.isnan(price) else float(price)):
            st.session_state["wl_flash"] = f"👀 {name} bevakas nu."
        else:
            st.session_state["wl_flash"] = f"{name} finns redan i listan."
        st.session_state["wl_n"] = k + 1
        st.rerun()


def render():
    st.title("👀 Bevakningslista")
    st.caption("Aktier du spanar på. Sätt en köpkurs eller säljkurs så säger appen till när den nås.")
    if msg := st.session_state.pop("wl_flash", None):
        st.success(msg)

    _add_picker()
    wl = db.load_watchlist()
    if wl.empty:
        st.info("Listan är tom. Lägg till en aktie ovanför – t.ex. ett bolag du funderar på att köpa.")
        return

    tickers = tuple(wl["ticker"])
    with st.spinner("Hämtar kurser …"):
        q = market.get_live_quotes(tickers)
        closes = market.get_closes(tickers, period="1y")

    # Larm
    for a in alerts(wl):
        if a["kind"] == "köp":
            st.success(f"🔔 **{a['name']}** har fallit till {fmt_num(a['price'], 2)} – under din köpkurs "
                       f"{fmt_num(a['level'], 2)}.")
        else:
            st.warning(f"🔔 **{a['name']}** har stigit till {fmt_num(a['price'], 2)} – över din säljkurs "
                       f"{fmt_num(a['level'], 2)}.")

    rows = []
    for r in wl.itertuples():
        s = closes[r.ticker].dropna() if r.ticker in closes else pd.Series(dtype=float)
        price = q["last"].get(r.ticker, math.nan)
        prev = q["prev"].get(r.ticker, math.nan)
        rsi = float(analysis.rsi(s).iloc[-1]) if len(s) > 20 else math.nan
        hi = float(s.max()) if not s.empty else math.nan
        ma200 = float(analysis.sma(s, 200).iloc[-1]) if len(s) >= 200 else math.nan
        to_buy = (price / r.buy_below - 1) if pd.notna(r.buy_below) and r.buy_below and price else math.nan
        rows.append({
            "ticker": r.ticker,
            "Namn": r.name or aktielista.POPULAR.get(r.ticker, r.ticker),
            "Kurs": price,
            "Idag %": (price / prev - 1) * 100 if prev else math.nan,
            "Sedan tillagd %": (price / r.added_price - 1) * 100 if r.added_price else math.nan,
            "3 mån": s.tail(63).tolist(),
            "Från 52v-högsta %": (price / hi - 1) * 100 if hi else math.nan,
            "RSI": rsi,
            "Trend": ("⬆️ Upp" if price > ma200 else "⬇️ Ned") if not math.isnan(ma200) else "–",
            "Köp under": r.buy_below,
            "Avstånd till köp %": to_buy * 100 if not math.isnan(to_buy) else math.nan,
            "Sälj över": r.sell_above,
            "Anteckning": r.note,
        })
    table = pd.DataFrame(rows)
    for col in ("Köp under", "Sälj över"):
        table[col] = pd.to_numeric(table[col], errors="coerce").astype(float)

    edited = st.data_editor(
        table, hide_index=True, use_container_width=True, key="wl_editor",
        disabled=[c for c in table.columns if c not in ("Köp under", "Sälj över", "Anteckning")],
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", pinned=True),
            "Namn": st.column_config.TextColumn(pinned=True),
            "Kurs": st.column_config.NumberColumn(format="%.2f"),
            "Idag %": st.column_config.NumberColumn(format="%+.2f %%"),
            "Sedan tillagd %": st.column_config.NumberColumn(format="%+.1f %%"),
            "3 mån": st.column_config.LineChartColumn("Senaste 3 mån", width="small"),
            "Från 52v-högsta %": st.column_config.NumberColumn(format="%.1f %%"),
            "RSI": st.column_config.NumberColumn(format="%.0f", help="Under 30 = översåld, över 70 = överköpt"),
            "Köp under": st.column_config.NumberColumn("🔔 Köp under", format="%.2f", min_value=0.0,
                                                       help="Larm när kursen faller hit"),
            "Avstånd till köp %": st.column_config.NumberColumn(format="%+.1f %%",
                                                                help="Hur långt över din köpkurs aktien ligger. 0 eller minus = köpkursen är nådd"),
            "Sälj över": st.column_config.NumberColumn("🔔 Sälj över", format="%.2f", min_value=0.0,
                                                       help="Larm när kursen stiger hit"),
            "Anteckning": st.column_config.TextColumn("📝 Anteckning", help="Varför bevakar du den?"),
        },
    )
    st.caption("✏️ Klicka i kolumnerna *Köp under*, *Sälj över* och *Anteckning* för att ändra – spara sedan.")

    c = st.columns([1, 1.4, 1.4, 2])
    if c[0].button("💾 Spara", type="primary", use_container_width=True):
        upd = wl.set_index("ticker")
        e = edited.set_index("ticker")
        upd["buy_below"] = e["Köp under"]
        upd["sell_above"] = e["Sälj över"]
        upd["note"] = e["Anteckning"].fillna("")
        db.save_watchlist(upd.reset_index())
        st.session_state["wl_flash"] = "Bevakningslistan är sparad."
        st.rerun()
    pick = c[1].selectbox("Aktie", list(wl["ticker"]), label_visibility="collapsed",
                          format_func=lambda t: f"{wl.set_index('ticker').loc[t, 'name'] or t}")
    if c[2].button("🔬 Analysera", use_container_width=True):
        st.session_state["analyze_ticker"] = pick
        st.switch_page(st.session_state["_pages"]["analys"])
    if c[3].button("🗑️ Ta bort från listan", use_container_width=True):
        db.remove_watch(pick)
        st.session_state["wl_flash"] = f"{pick} är borttagen."
        st.rerun()
