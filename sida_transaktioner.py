"""Transaktioner: lägg till, redigera, importera och exportera."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import db, market, portfolio
from ui import fmt_sek


def render():
    st.title("🧾 Transaktioner")
    if msg := st.session_state.pop("flash", None):
        st.success(msg)

    with st.expander("🔎 Hitta rätt ticker", expanded=False):
        q = st.text_input("Sök på bolagsnamn", placeholder="t.ex. Volvo, Investor, Apple")
        if q:
            res = market.search_ticker(q)
            if res.empty:
                st.caption("Inga träffar.")
            else:
                st.dataframe(res, hide_index=True, use_container_width=True)
        st.caption("Svenska aktier slutar på **.ST** (VOLV-B.ST), danska **.CO**, norska **.OL**, finska **.HE**. "
                   "Amerikanska saknar suffix (AAPL).")

    _add_form()
    st.divider()
    _editor()
    st.divider()
    _import_export()


def _add_form():
    st.subheader("Ny transaktion")
    with st.form("add_tx", clear_on_submit=True):
        c = st.columns(4)
        date = c[0].date_input("Datum", value=dt.date.today(), max_value=dt.date.today(), format="YYYY-MM-DD")
        ticker = c[1].text_input("Ticker", placeholder="VOLV-B.ST").strip().upper()
        type_ = c[2].selectbox("Typ", db.TYPES)
        currency = c[3].selectbox("Valuta", db.CURRENCIES)
        c = st.columns(4)
        qty = c[0].number_input("Antal", min_value=0.0, step=1.0, format="%.4f")
        price = c[1].number_input("Kurs / utdelning per aktie", min_value=0.0, step=0.01, format="%.4f")
        fee = c[2].number_input("Courtage / källskatt (SEK)", min_value=0.0, step=1.0)
        fx = c[3].number_input("Valutakurs (SEK)", min_value=0.0, step=0.0001, format="%.4f",
                               help="Lämna 0 för att hämta automatiskt för datumet. Ignoreras för SEK.")
        note = st.text_input("Anteckning", placeholder="Valfritt – t.ex. investeringscase")
        submitted = st.form_submit_button("Spara transaktion", type="primary")

    if not submitted:
        return
    if not ticker or qty <= 0:
        st.error("Ange ticker och antal.")
        return
    if currency == "SEK":
        fx = 1.0
    elif fx <= 0:
        fx = market.get_fx_on(currency, date.isoformat())
        if fx is None:
            st.error(f"Kunde inte hämta {currency}/SEK för {date}. Ange valutakursen manuellt.")
            return
    new = pd.DataFrame([{"id": 10**9, "date": date.isoformat(), "ticker": ticker, "type": type_,
                         "quantity": qty, "price": price, "fee": fee, "currency": currency,
                         "fx_rate": fx, "note": note}])
    combined = pd.concat([db.load_transactions(), new], ignore_index=True)
    errors = portfolio.validate(combined)
    if errors:
        st.error("\n".join(errors))
        return
    db.add_transaction(date.isoformat(), ticker, type_, qty, price, fee, currency, fx, note)
    amount = qty * price * fx
    st.session_state["flash"] = f"Sparat: {type_} {qty:g} {ticker} à {price:g} {currency} ≈ {fmt_sek(amount)}"
    st.rerun()


def _editor():
    st.subheader("Alla transaktioner")
    tx = db.load_transactions()
    if tx.empty:
        st.caption("Inga transaktioner ännu.")
        return

    f1, f2 = st.columns([2, 1])
    tickers = f1.multiselect("Filtrera ticker", sorted(tx["ticker"].unique()))
    types = f2.multiselect("Filtrera typ", db.TYPES)
    if tickers or types:
        view = tx[(tx["ticker"].isin(tickers) if tickers else True) & (tx["type"].isin(types) if types else True)]
        st.dataframe(view.drop(columns="id"), hide_index=True, use_container_width=True)
        st.caption("Ta bort filtren för att redigera.")
        return

    editable = tx.copy()
    editable["date"] = pd.to_datetime(editable["date"]).dt.date
    edited = st.data_editor(
        editable.drop(columns="id"), num_rows="dynamic", hide_index=True, use_container_width=True,
        key="tx_editor",
        column_config={
            "date": st.column_config.DateColumn("Datum", format="YYYY-MM-DD", required=True),
            "ticker": st.column_config.TextColumn("Ticker", required=True),
            "type": st.column_config.SelectboxColumn("Typ", options=db.TYPES, required=True),
            "quantity": st.column_config.NumberColumn("Antal", min_value=0, format="%.4f", required=True),
            "price": st.column_config.NumberColumn("Kurs", min_value=0, format="%.4f", required=True),
            "fee": st.column_config.NumberColumn("Avgift (SEK)", min_value=0, format="%.2f", default=0.0),
            "currency": st.column_config.SelectboxColumn("Valuta", options=db.CURRENCIES, default="SEK"),
            "fx_rate": st.column_config.NumberColumn("Valutakurs", min_value=0, format="%.4f", default=1.0),
            "note": st.column_config.TextColumn("Anteckning"),
        },
    )
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("💾 Spara ändringar", type="primary"):
        df = edited.dropna(subset=["date", "ticker", "type"]).copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["ticker"] = df["ticker"].str.strip().str.upper()
        df["fee"] = df["fee"].fillna(0.0)
        df["currency"] = df["currency"].fillna("SEK")
        df["fx_rate"] = df["fx_rate"].fillna(1.0)
        df.loc[df["currency"] == "SEK", "fx_rate"] = 1.0
        df["note"] = df["note"].fillna("")
        df.insert(0, "id", range(1, len(df) + 1))
        errors = portfolio.validate(df)
        if errors:
            st.error("Sparades inte:\n\n- " + "\n- ".join(errors))
        else:
            db.replace_all(df)
            st.session_state["flash"] = "Ändringar sparade."
            st.rerun()
    if c2.button("🗑️ Radera allt"):
        st.session_state["confirm_delete"] = True
    if st.session_state.get("confirm_delete"):
        st.warning("Är du säker? Detta raderar alla transaktioner.")
        a, b, _ = st.columns([1, 1, 4])
        if a.button("Ja, radera"):
            db.delete_all()
            st.session_state["confirm_delete"] = False
            st.rerun()
        if b.button("Avbryt"):
            st.session_state["confirm_delete"] = False
            st.rerun()

    pos = portfolio.compute_positions(tx)
    real = portfolio.realized_by_ticker(pos)
    if not real.empty:
        st.subheader("Realiserat resultat & utdelningar")
        st.dataframe(real, hide_index=True, use_container_width=True, column_config={
            "ticker": "Ticker",
            "realized_sek": st.column_config.NumberColumn("Realiserat (SEK)", format="%.0f"),
            "dividends_sek": st.column_config.NumberColumn("Utdelningar (SEK)", format="%.0f"),
            "fees_sek": st.column_config.NumberColumn("Avgifter (SEK)", format="%.0f"),
        })


def _import_export():
    st.subheader("Import / export")
    c1, c2 = st.columns(2)
    tx = db.load_transactions()
    with c1:
        st.download_button("⬇️ Exportera CSV", tx.drop(columns="id").to_csv(index=False).encode("utf-8"),
                           file_name=f"transaktioner_{dt.date.today()}.csv", mime="text/csv",
                           disabled=tx.empty)
        st.caption("Kolumner: date, ticker, type, quantity, price, fee, currency, fx_rate, note")
    with c2:
        up = st.file_uploader("Importera CSV", type="csv")
        mode = st.radio("Läge", ["Lägg till", "Ersätt allt"], horizontal=True)
        if up is not None and st.button("Importera"):
            try:
                new = pd.read_csv(up, sep=None, engine="python")
            except Exception as e:
                st.error(f"Kunde inte läsa filen: {e}")
                return
            required = {"date", "ticker", "type", "quantity", "price"}
            if not required.issubset(new.columns):
                st.error(f"CSV måste innehålla kolumnerna: {', '.join(sorted(required))}")
                return
            for col, default in (("fee", 0.0), ("currency", "SEK"), ("fx_rate", 1.0), ("note", "")):
                if col not in new:
                    new[col] = default
            new["ticker"] = new["ticker"].astype(str).str.strip().str.upper()
            new["type"] = new["type"].astype(str).str.strip().str.upper().replace({"KOP": "KÖP", "SALJ": "SÄLJ", "BUY": "KÖP", "SELL": "SÄLJ", "DIVIDEND": "UTDELNING"})
            new["date"] = pd.to_datetime(new["date"]).dt.strftime("%Y-%m-%d")
            new["note"] = new["note"].fillna("")
            combined = new if mode == "Ersätt allt" else pd.concat([tx.drop(columns="id"), new], ignore_index=True)
            combined.insert(0, "id", range(1, len(combined) + 1))
            errors = portfolio.validate(combined)
            if errors:
                st.error("Importen avbröts:\n\n- " + "\n- ".join(errors[:20]))
            else:
                db.replace_all(combined)
                st.session_state["flash"] = f"Importerade {len(new)} transaktioner."
                st.rerun()
