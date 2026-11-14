"""Konton & innehav: ställ in konton (ISK/KF/AF, mäklare, courtageklass) och mata in nuvarande innehav."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import db
import fees
import market
import portfolio


def render():
    st.title("🏦 Konton & innehav")
    if msg := st.session_state.pop("flash_konton", None):
        st.success(msg)
    st.markdown("Här ställer du in **dina konton** och lägger in **det du äger idag**. "
                "Kontotypen styr hur skatten räknas, och mäklare + courtageklass styr courtaget.")

    tab1, tab2 = st.tabs(["1️⃣ Mina konton", "2️⃣ Lägg in mina innehav"])
    with tab1:
        _accounts()
    with tab2:
        _holdings()


# ---------------------------------------------------------------- Konton
def _accounts():
    acc = db.load_accounts()
    tx = db.load_transactions()
    used = set(tx["account"]) if not tx.empty else set()

    st.markdown("Lägg till en rad per konto du har. Exempel: *ISK Avanza*, *KF Nordnet*, *Depå SEB*.")
    edited = st.data_editor(
        acc, num_rows="dynamic", hide_index=True, use_container_width=True, key="acc_editor",
        column_config={
            "name": st.column_config.TextColumn("Kontonamn", required=True, help="Valfritt namn, t.ex. 'ISK Avanza'"),
            "type": st.column_config.SelectboxColumn("Kontotyp", options=list(db.ACCOUNT_TYPES), required=True,
                                                     default="ISK", help="ISK, KF eller AF (vanlig depå)"),
            "broker": st.column_config.SelectboxColumn("Mäklare", options=fees.BROKERS, required=True, default="Avanza"),
            "courtage_class": st.column_config.SelectboxColumn("Courtageklass", options=fees.all_classes(),
                                                               required=True, default="Mini"),
            "custom_pct": st.column_config.NumberColumn("Egen sats %", min_value=0.0, format="%.3f",
                                                        help="Bara för mäklare 'Annan', t.ex. 0,09 för SEB/Nordea"),
            "custom_min": st.column_config.NumberColumn("Eget minimum kr", min_value=0.0, format="%.0f",
                                                        help="Bara för mäklare 'Annan'"),
        },
    )
    if st.button("💾 Spara konton", type="primary"):
        df = edited.dropna(subset=["name"]).copy()
        df["name"] = df["name"].astype(str).str.strip()
        df = df[df["name"] != ""]
        errors = []
        if df.empty:
            errors.append("Du behöver minst ett konto.")
        if df["name"].duplicated().any():
            errors.append("Två konton har samma namn.")
        missing = used - set(df["name"])
        if missing:
            errors.append(f"Kontot {', '.join(sorted(missing))} har transaktioner och kan inte tas bort här. "
                          "Byt namn med verktyget nedan i stället.")
        for r in df.itertuples():
            if r.broker == "Avanza" and r.courtage_class not in fees.COURTAGE["Avanza"]:
                errors.append(f"{r.name}: Avanza har klasserna {', '.join(fees.COURTAGE['Avanza'])}.")
            if r.broker == "Nordnet" and r.courtage_class not in fees.COURTAGE["Nordnet"]:
                errors.append(f"{r.name}: Nordnet har klasserna {', '.join(fees.COURTAGE['Nordnet'])}.")
        if errors:
            st.error("\n\n".join(errors))
        else:
            db.save_accounts(df)
            st.session_state["flash_konton"] = "Konton sparade."
            st.rerun()

    with st.expander("✏️ Byt namn på ett konto"):
        c1, c2, c3 = st.columns([2, 2, 1])
        old = c1.selectbox("Konto", acc["name"].tolist(), key="ren_old")
        new = c2.text_input("Nytt namn", key="ren_new").strip()
        c3.write("")
        if c3.button("Byt namn", disabled=not new or new in acc["name"].tolist()):
            db.rename_account(old, new)
            st.session_state["flash_konton"] = f"'{old}' heter nu '{new}'."
            st.rerun()

    with st.expander("ℹ️ Vilken kontotyp och courtageklass har jag?"):
        st.markdown(
            """
**Kontotyp** – står i din app hos banken/mäklaren:
- **ISK** (Investeringssparkonto): ingen skatt på vinster, i stället en årlig schablonskatt på värdet.
  2026 är de första 300 000 kr (ISK + KF tillsammans) skattefria, sedan 1,065 %.
- **KF** (Kapitalförsäkring): skattas som ISK, men skatten dras av försäkringsbolaget.
- **AF** (Aktie- och fondkonto / depå): 30 % skatt på vinster och utdelningar när de sker. Deklareras på K4.

**Courtageklass** – hittar du under *Profil/Inställningar → Courtageklass* i Avanza- eller Nordnet-appen.

| Klass (Avanza / Nordnet) | Courtage |
|---|---|
| Start / Kom igång | 0 kr (svenska aktier, sparande under 50 000 kr) |
| Mini | 0,25 %, minst 1 kr |
| Small / Liten | 0,15 %, minst 39 kr |
| Medium / Mellan | 0,069 %, minst 69 kr |
| Fast pris / Fast | 99 kr |

Vid köp i utländsk valuta tillkommer **0,25 % valutaväxling**. Använder du en annan bank,
välj mäklare *Annan* och fyll i egen sats (t.ex. 0,09 % och minst 1 kr för SEB/Nordea).
            """
        )


# ---------------------------------------------------------------- Innehav
def _holdings():
    accounts = db.load_accounts()
    names = accounts["name"].tolist()
    tx = db.load_transactions()
    is_demo = not tx.empty and (tx["note"] == "Demo").any()

    st.markdown(
        "Skriv in **det du äger idag** – en rad per aktie och konto. Du hittar uppgifterna under "
        "**Innehav** i din Avanza- eller Nordnet-app."
    )
    if is_demo:
        st.info("🎁 Appen innehåller just nu **exempelaktier**. Välj *Ersätt allt* nedan så tas de bort.")

    with st.expander("🔎 Hitta rätt ticker"):
        q = st.text_input("Sök på bolagsnamn", placeholder="t.ex. Volvo, Investor, Apple", key="hold_search")
        if q:
            res = market.search_ticker(q)
            if res.empty:
                st.caption("Inga träffar.")
            else:
                st.dataframe(res, hide_index=True, use_container_width=True)
        st.caption("Svenska aktier slutar på .ST (VOLV-B.ST), danska .CO, norska .OL, finska .HE. USA utan ändelse (AAPL).")

    template = pd.DataFrame({
        "account": pd.Series([names[0]] * 3, dtype="object"),
        "ticker": pd.Series(["", "", ""], dtype="object"),
        "quantity": pd.Series([None] * 3, dtype="float"),
        "gav": pd.Series([None] * 3, dtype="float"),
        "currency": pd.Series(["SEK"] * 3, dtype="object"),
        "cost_sek": pd.Series([None] * 3, dtype="float"),
        "date": pd.Series([dt.date.today()] * 3, dtype="object"),
    })
    edited = st.data_editor(
        template, num_rows="dynamic", hide_index=True, use_container_width=True, key="hold_editor",
        column_config={
            "account": st.column_config.SelectboxColumn("Konto", options=names, required=True, default=names[0]),
            "ticker": st.column_config.TextColumn("Ticker", help="t.ex. VOLV-B.ST"),
            "quantity": st.column_config.NumberColumn("Antal", min_value=0.0, format="%.4f"),
            "gav": st.column_config.NumberColumn("GAV per aktie", min_value=0.0, format="%.4f",
                                                 help="Genomsnittligt anskaffningsvärde per aktie, i aktiens valuta"),
            "currency": st.column_config.SelectboxColumn("Valuta", options=db.CURRENCIES, default="SEK"),
            "cost_sek": st.column_config.NumberColumn("Anskaffn. totalt SEK (valfritt)", min_value=0.0, format="%.0f",
                                                      help="För utländska aktier: fyll i om appen visar anskaffningsvärdet i "
                                                           "kronor – då blir valutakursen exakt."),
            "date": st.column_config.DateColumn("Köpdatum (ungefär)", format="YYYY-MM-DD",
                                                help="Används för historikgrafen. Vet du inte, låt dagens datum stå."),
        },
    )
    st.caption("💡 Lägg till fler rader med **+** längst ner i tabellen. Courtage räknas som redan inkluderat i GAV.")

    mode = st.radio("Vad ska hända med det som redan finns?",
                    ["Ersätt allt (tar bort exempelaktier och tidigare transaktioner)", "Lägg till"],
                    index=0 if (is_demo or tx.empty) else 1)
    if st.button("✅ Spara mina innehav", type="primary"):
        rows = edited.copy()
        rows["ticker"] = rows["ticker"].fillna("").astype(str).str.strip().str.upper()
        rows = rows[(rows["ticker"] != "") & (rows["quantity"].fillna(0) > 0)]
        if rows.empty:
            st.error("Fyll i minst en rad med ticker och antal.")
            return
        if rows["gav"].isna().any():
            st.error("GAV saknas på någon rad.")
            return
        new_tx, notes = [], []
        with st.spinner("Kontrollerar tickers och valutakurser…"):
            quotes = market.get_quotes(tuple(sorted(rows["ticker"].unique())))
            for r in rows.itertuples():
                found = r.ticker in quotes.index and pd.notna(quotes.loc[r.ticker, "last"])
                if not found:
                    notes.append(f"⚠️ Hittade ingen kurs för **{r.ticker}** – kontrollera tickern.")
                date = pd.Timestamp(r.date if pd.notna(r.date) else dt.date.today()).strftime("%Y-%m-%d")
                cur = r.currency or "SEK"
                if cur == "SEK":
                    fx = 1.0
                elif pd.notna(r.cost_sek) and r.cost_sek > 0 and r.gav > 0:
                    fx = r.cost_sek / (r.quantity * r.gav)
                else:
                    fx = market.get_fx_on(cur, date) or market.get_fx_now((cur,)).get(cur) or 1.0
                new_tx.append({"date": date, "account": r.account, "ticker": r.ticker, "type": "KÖP",
                               "quantity": float(r.quantity), "price": float(r.gav), "fee": 0.0,
                               "currency": cur, "fx_rate": float(fx), "note": "Ingående innehav"})
        new = pd.DataFrame(new_tx)
        combined = new if mode.startswith("Ersätt") else pd.concat([tx.drop(columns="id"), new], ignore_index=True)
        combined.insert(0, "id", range(1, len(combined) + 1))
        errors = portfolio.validate(combined)
        if errors:
            st.error("\n".join(errors))
            return
        db.replace_all(combined)
        st.session_state["flash_konton"] = f"Sparade {len(new)} innehav. " + " ".join(notes)
        st.rerun()

    # Nuvarande innehav per konto
    if not tx.empty:
        st.divider()
        st.subheader("Det här finns inlagt nu")
        pos = portfolio.compute_positions(tx, by_account=True)
        pos = pos[pos["qty"] > 0]
        if pos.empty:
            st.caption("Inga öppna innehav.")
        else:
            show = pos[["account", "ticker", "qty", "currency", "cost_sek"]].assign(
                gav=pos["cost_local"] / pos["qty"])
            st.dataframe(show, hide_index=True, use_container_width=True, column_config={
                "account": "Konto", "ticker": "Ticker",
                "qty": st.column_config.NumberColumn("Antal", format="%.4g"),
                "currency": "Valuta",
                "cost_sek": st.column_config.NumberColumn("Anskaffning (SEK)", format="%.0f"),
                "gav": st.column_config.NumberColumn("GAV", format="%.2f"),
            })
            st.caption("Vill du ändra eller ta bort något? Gå till **Transaktioner** – där kan du redigera allt.")
