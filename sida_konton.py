"""Mitt innehav: lägg till aktier enkelt, se och ta bort innehav, ställ in konton (ISK/KF/AF, mäklare, courtage)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import aktielista
import avanza_import as avi
import db
import fees
import market
import portfolio
from ui import fmt_num, fmt_pct, fmt_sek


def render():
    st.title("➕ Mitt innehav")
    if msg := st.session_state.pop("flash_konton", None):
        st.success(msg)

    tab0, tab1, tab2, tab3 = st.tabs(["📥 Importera från Avanza", "➕ Lägg till aktie", "📋 Mina aktier",
                                      "🏦 Mina konton"])
    with tab0:
        _avanza_import()
    with tab1:
        _quick_add()
        with st.expander("📑 Har du många aktier? Lägg till flera på en gång i en tabell"):
            _holdings()
    with tab2:
        _my_stocks()
    with tab3:
        _accounts()


# ---------------------------------------------------------------- Snabbt tillägg
def _quick_add():
    accounts = db.load_accounts()
    names = accounts["name"].tolist()
    tx = db.load_transactions()
    is_demo = not tx.empty and tx["note"].str.startswith("Demo").any()
    if is_demo:
        st.info("🎁 Just nu visas exempelaktier. De tas bort automatiskt när du lägger till din första egna aktie.")

    k = st.session_state.get("qa_n", 0)  # räknare som nollställer fälten efter varje tillägg
    with st.container(border=True):
        st.markdown("#### 1. Vilken aktie?")
        choice = st.selectbox(
            "Aktie", aktielista.options(), index=None, key=f"qa_pick_{k}", accept_new_options=True,
            placeholder="Skriv bolagets namn, t.ex. Volvo, Investor, Apple …", label_visibility="collapsed",
        )
        ticker = name = None
        if choice:
            ticker = aktielista.ticker_from_label(choice)
            if ticker:
                name = aktielista.POPULAR[ticker]
            else:
                with st.spinner("Söker …"):
                    res = market.search_ticker(choice)
                if not res.empty:
                    res = res[res["Typ"].isin(["EQUITY", "ETF"]) & res["Ticker"].notna()].reset_index(drop=True)
                if res.empty:
                    st.warning("Hittade ingen aktie med det namnet. Prova att stava annorlunda eller skriv bara "
                               "en del av namnet.")
                    return
                labels = [f"{r.Namn} · {r.Ticker} ({r.Börs})" for r in res.itertuples()]
                i = st.radio("Vilken av dessa menar du?", range(len(labels)), format_func=lambda i: labels[i],
                             key=f"qa_res_{k}")
                ticker, name = res.loc[i, "Ticker"], res.loc[i, "Namn"]
        if not ticker:
            st.caption("💡 Listan innehåller vanliga svenska, nordiska och amerikanska aktier. Finns inte din "
                       "aktie med – skriv namnet och tryck Enter, så söker appen upp den.")
            return

        info_cur = None if ticker in aktielista.POPULAR else market.get_info(ticker).get("currency")
        cur = aktielista.currency_for(ticker, info_cur)
        quotes = market.get_live_quotes((ticker,))
        price = quotes.loc[ticker, "last"] if ticker in quotes.index else float("nan")
        if pd.isna(price):
            st.warning(f"Hittar ingen aktuell kurs för {ticker} just nu. Du kan lägga till den ändå.")
        else:
            st.markdown(f"✅ **{name}** · {ticker} · senaste kurs **{fmt_num(price, 2)} {cur}**")

        st.markdown("#### 2. Hur många har du och vad betalade du?")
        c = st.columns(3)
        last_acc = st.session_state.get("qa_last_acc")
        account = c[0].selectbox("Konto", names, index=names.index(last_acc) if last_acc in names else 0,
                                 key=f"qa_acc_{k}")
        qty = c[1].number_input("Antal aktier", min_value=0.0, step=1.0, format="%g", key=f"qa_qty_{k}")
        gav = c[2].number_input(f"GAV per aktie ({cur})", min_value=0.0, step=0.01, format="%.2f", key=f"qa_gav_{k}",
                                help="Det du har betalat i snitt per aktie. Står som GAV under Innehav i "
                                     "Avanza- eller Nordnet-appen.")
        dont_know = st.checkbox("Jag vet inte mitt GAV – använd dagens kurs", key=f"qa_dk_{k}")
        with st.expander("Mer (valfritt)"):
            date = st.date_input("Ungefär när köpte du?", dt.date.today(), max_value=dt.date.today(),
                                 format="YYYY-MM-DD", key=f"qa_date_{k}",
                                 help="Används för historikgrafen på Översikt.")
            cost_sek = 0.0
            if cur != "SEK":
                cost_sek = st.number_input("Anskaffningsvärde totalt i SEK", min_value=0.0, step=100.0,
                                           key=f"qa_cost_{k}",
                                           help="Visar appen vad du betalat i kronor? Fyll i det så blir valutakursen exakt.")

        use_gav = price if dont_know and pd.notna(price) else gav
        if qty > 0 and pd.notna(price):
            fx_now = market.get_fx_now((cur,)).get(cur, 1.0) if cur != "SEK" else 1.0
            val = qty * price * fx_now
            txt = f"Värde idag ≈ **{fmt_sek(val)}**"
            if use_gav > 0:
                diff = price / use_gav - 1
                txt += f" · {'upp' if diff >= 0 else 'ner'} {fmt_pct(abs(diff), 1, sign=False)} sedan köp"
            st.markdown(txt)

        if st.button("➕ Lägg till i mitt innehav", type="primary", disabled=qty <= 0, key=f"qa_btn_{k}"):
            if use_gav <= 0:
                st.error("Fyll i GAV, eller kryssa i att du inte vet det.")
                return
            date_s = date.isoformat()
            if cur == "SEK":
                fx = 1.0
            elif cost_sek > 0:
                fx = cost_sek / (qty * use_gav)
            else:
                fx = market.get_fx_on(cur, date_s) or market.get_fx_now((cur,)).get(cur) or 1.0
            removed = db.delete_demo() if is_demo else 0
            already = not tx.empty and ((tx["account"] == account) & (tx["ticker"] == ticker)).any()
            db.add_transaction(date_s, ticker, "KÖP", qty, use_gav, 0.0, cur, fx, "Ingående innehav", account)
            msg = f"✅ {name}: {qty:g} st tillagd på {account}."
            if already:
                msg += " Du hade redan aktien där – antalet har lagts ihop och GAV räknats om."
            if removed:
                msg += " Exempelaktierna är borttagna."
            st.session_state["flash_konton"] = msg
            st.session_state["qa_last_acc"] = account
            st.session_state["qa_n"] = k + 1
            st.rerun()


# ---------------------------------------------------------------- Mina aktier
def _my_stocks():
    tx = db.load_transactions()
    if tx.empty:
        st.info("Inga aktier inlagda än. Lägg till under **➕ Lägg till aktie**.")
        return
    pos = portfolio.compute_positions(tx, by_account=True)
    pos = pos[pos["qty"] > 0]
    if pos.empty:
        st.info("Inga öppna innehav.")
        return
    quotes = market.get_live_quotes(tuple(sorted(pos["ticker"].unique())))
    fxn = market.get_fx_now(tuple(sorted(set(pos["currency"]) | {"SEK"})))
    pending = st.session_state.get("qa_delete")

    for acc, g in pos.groupby("account", sort=False):
        st.markdown(f"#### 🏦 {acc}")
        head = st.columns([3, 1.2, 1.4, 1.6, 1.4, 0.6])
        for col, t in zip(head, ["Aktie", "Antal", "GAV", "Värde idag", "Utveckling", ""]):
            col.caption(t)
        for r in g.itertuples():
            price = quotes["last"].get(r.ticker, float("nan"))
            fx = fxn.get(r.currency, 1.0)
            value = r.qty * price * fx
            gav = r.cost_local / r.qty
            chg = value / r.cost_sek - 1 if r.cost_sek else float("nan")
            c = st.columns([3, 1.2, 1.4, 1.6, 1.4, 0.6])
            c[0].markdown(f"**{aktielista.POPULAR.get(r.ticker, r.ticker)}**  \n"
                          f"<span class='small-muted'>{r.ticker}</span>", unsafe_allow_html=True)
            c[1].write(f"{r.qty:g}")
            c[2].write(f"{fmt_num(gav, 2)} {r.currency}")
            c[3].write(fmt_sek(value))
            color = "#22C55E" if chg >= 0 else "#EF4444"
            c[4].markdown(f"<span style='color:{color}'>{fmt_pct(chg)}</span>" if pd.notna(chg) else "–",
                          unsafe_allow_html=True)
            if c[5].button("🗑️", key=f"del_{acc}_{r.ticker}", help="Ta bort aktien från kontot"):
                st.session_state["qa_delete"] = (acc, r.ticker)
                st.rerun()
            if pending == (acc, r.ticker):
                w = st.columns([4, 1, 1])
                w[0].warning(f"Ta bort **{r.ticker}** från {acc}? Alla dess köp, sälj och utdelningar raderas.")
                if w[1].button("Ja, ta bort", key=f"yes_{acc}_{r.ticker}", type="primary"):
                    db.delete_holding(acc, r.ticker)
                    st.session_state.pop("qa_delete", None)
                    st.session_state["flash_konton"] = f"{r.ticker} är borttagen från {acc}."
                    st.rerun()
                if w[2].button("Avbryt", key=f"no_{acc}_{r.ticker}"):
                    st.session_state.pop("qa_delete", None)
                    st.rerun()
    st.caption("Vill du ändra antal eller GAV? Ta bort aktien och lägg till den igen – eller redigera under **Transaktioner**.")


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
    is_demo = not tx.empty and tx["note"].str.startswith("Demo").any()

    st.markdown("En rad per aktie och konto. Tickern måste vara i Yahoo-format, t.ex. VOLV-B.ST.")

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
            quotes = market.get_live_quotes(tuple(sorted(rows["ticker"].unique())))
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



# ---------------------------------------------------------------- Avanza-import
def _resolve_ticker(name: str, isin: str) -> str:
    """Hitta Yahoo-ticker för ett värdepapper från Avanza-exporten."""
    t = avi.ticker_from_name(name)
    if t:
        return t
    want = avi.isin_suffix(isin)
    for query in (isin, name):
        if not query:
            continue
        res = market.search_ticker(query)
        if res.empty:
            continue
        res = res[res["Typ"].isin(["EQUITY", "ETF"]) & res["Ticker"].notna()]
        if res.empty:
            continue
        if want:
            hit = res[res["Ticker"].str.upper().str.endswith(want)]
            if not hit.empty:
                return hit.iloc[0]["Ticker"]
        elif isin and isin.startswith("US"):
            hit = res[~res["Ticker"].str.contains(r"\.", regex=True)]
            if not hit.empty:
                return hit.iloc[0]["Ticker"]
        return res.iloc[0]["Ticker"]
    return ""


def _avanza_import():
    st.markdown("Det enklaste sättet att få in **allt** – med exakt samma GAV, courtage och valutakurser som Avanza.")
    with st.expander("📋 Så här exporterar du från Avanza", expanded=True):
        st.markdown(
            """
1. Logga in på **avanza.se** i en dator (inte appen).
2. Gå till **Min ekonomi → Transaktioner**.
3. Välj tidsperiod **från början** (så långt bak det går), så att alla köp kommer med.
4. Klicka på **Exportera** och spara filen (den heter ungefär *transaktioner_….csv*).
5. Ladda upp den här nedanför.

Filen innehåller bara dina affärer – inget lösenord eller personnummer.
Hittar du inte knappen? Skicka en skärmdump i chatten med Claude, så får du hjälp.
            """
        )
    up = st.file_uploader("Avanzas transaktionsfil (.csv)", type=["csv", "txt"], key="av_file")
    if up is None:
        return
    try:
        raw = avi.read_file(up.getvalue())
    except Exception as e:
        st.error(f"Kunde inte läsa filen: {e}")
        return
    if raw.empty:
        st.error("Filen är tom.")
        return

    detected = avi.detect_columns(raw)
    required = ["date", "type", "name", "quantity", "price"]
    labels = {"date": "Datum", "account": "Konto", "type": "Typ av transaktion", "name": "Värdepapper",
              "quantity": "Antal", "price": "Kurs", "amount": "Belopp (SEK)", "courtage": "Courtage",
              "fx": "Valutakurs", "currency": "Valuta", "isin": "ISIN"}
    all_ok = all(detected[k] for k in required)
    with st.expander("🧩 Kolumner i filen" + ("" if all_ok else " – behöver hjälp!"), expanded=not all_ok):
        if not all_ok:
            st.warning("Alla kolumner kändes inte igen. Välj vilken kolumn i filen som motsvarar vad.")
        opts = ["–"] + list(raw.columns)
        cols = {}
        grid = st.columns(4)
        for i, (k, lab) in enumerate(labels.items()):
            cur = detected.get(k)
            sel = grid[i % 4].selectbox(lab + (" *" if k in required else ""), opts,
                                        index=opts.index(cur) if cur in opts else 0, key=f"av_col_{k}")
            cols[k] = None if sel == "–" else sel
        st.dataframe(raw.head(5), hide_index=True, use_container_width=True)
    try:
        tx, stats = avi.parse(raw, cols)
    except ValueError as e:
        st.error(str(e))
        return
    if tx.empty:
        st.error("Hittade inga köp, sälj eller utdelningar i filen.")
        return

    st.success(f"Hittade **{stats['used']}** köp/sälj/utdelningar i {stats['rows']} rader"
               + (f", och {stats['withholding_rows']} rader källskatt som kopplas till utdelningarna." if stats['withholding_rows'] else "."))
    if stats["ignored"]:
        st.caption("Hoppar över (påverkar inte innehaven): " +
                   ", ".join(f"{k or 'tom'} ({v})" for k, v in stats["ignored"].items()))

    # --- Värdepapper -> ticker
    st.markdown("#### 1. Kontrollera aktierna")
    inst = (tx.groupby(["name", "isin"], dropna=False).size().reset_index(name="rader"))
    cache = st.session_state.setdefault("av_tickers", {})
    with st.spinner("Letar upp aktierna …"):
        for r in inst.itertuples():
            key = f"{r.name}|{r.isin}"
            if key not in cache:
                cache[key] = _resolve_ticker(r.name, r.isin)
    inst["ticker"] = [cache[f"{r.name}|{r.isin}"] for r in inst.itertuples()]
    inst["status"] = inst["ticker"].map(lambda t: "✅" if t else "❓ Fyll i ticker eller lämna tomt för att hoppa över")
    ed = st.data_editor(
        inst[["status", "name", "isin", "ticker", "rader"]], hide_index=True, use_container_width=True,
        disabled=["status", "name", "isin", "rader"], key="av_inst",
        column_config={"status": "", "name": "Värdepapper (Avanza)", "isin": "ISIN",
                       "ticker": st.column_config.TextColumn("Ticker", help="Yahoo-ticker, t.ex. VOLV-B.ST. Tomt = hoppa över."),
                       "rader": st.column_config.NumberColumn("Rader")})
    st.caption("Fonder finns oftast inte hos Yahoo Finance – lämna dem tomma så hoppas de över.")
    tmap = {(r.name, r.isin): str(r.ticker or "").strip().upper() for r in ed.itertuples()}

    # --- Konton
    st.markdown("#### 2. Kontrollera kontona")
    acc = pd.DataFrame({"avanza": sorted(tx["account"].unique())})
    existing = db.load_accounts().set_index("name")
    acc["name"] = acc["avanza"]
    acc["type"] = [existing["type"].get(a, avi.guess_account_type(a)) for a in acc["avanza"]]
    acc_ed = st.data_editor(acc, hide_index=True, use_container_width=True, disabled=["avanza"], key="av_acc",
                            column_config={
                                "avanza": "Konto i filen",
                                "name": st.column_config.TextColumn("Namn i appen", required=True),
                                "type": st.column_config.SelectboxColumn("Kontotyp", options=list(db.ACCOUNT_TYPES),
                                                                         required=True)})
    amap = dict(zip(acc_ed["avanza"], acc_ed["name"].astype(str).str.strip()))
    atype = dict(zip(acc_ed["name"].astype(str).str.strip(), acc_ed["type"]))
    if len(acc) == 1 and acc["avanza"].iloc[0] == "Avanza":
        st.caption("Filen saknar kontokolumn – allt hamnar på ett konto. Byt namn och kontotyp ovan om du vill.")

    # --- Bygg transaktioner
    tx["ticker"] = [tmap.get((r.name, r.isin), "") for r in tx.itertuples()]
    use = tx[tx["ticker"] != ""].copy()
    skipped = len(tx) - len(use)
    rows, no_fx = [], []
    for r in use.itertuples():
        cur = aktielista.currency_for(r.ticker, r.currency if r.currency in db.CURRENCIES else None)
        fx = avi.fx_for_row(r, cur)
        if fx is None:
            fx = market.get_fx_on(cur, r.date) or 1.0
            no_fx.append(r.ticker)
        rows.append({"date": r.date, "account": amap.get(r.account, r.account), "ticker": r.ticker,
                     "type": r.kind, "quantity": r.quantity, "price": r.price if pd.notna(r.price) else 0.0,
                     "fee": float(r.fee), "currency": cur, "fx_rate": float(fx), "note": "Avanza-import"})
    new = pd.DataFrame(rows)
    if new.empty:
        st.warning("Inga rader att importera – fyll i ticker för minst en aktie.")
        return

    # --- Förhandsgranskning
    st.markdown("#### 3. Så här blir ditt innehav")
    preview = portfolio.compute_positions(new.assign(id=range(len(new))), by_account=True)
    preview = preview[preview["qty"] > 1e-9]
    st.dataframe(preview.assign(gav=preview["cost_local"] / preview["qty"])[
        ["account", "ticker", "qty", "gav", "currency", "cost_sek"]], hide_index=True, use_container_width=True,
        column_config={"account": "Konto", "ticker": "Ticker",
                       "qty": st.column_config.NumberColumn("Antal", format="%.4g"),
                       "gav": st.column_config.NumberColumn("GAV", format="%.2f"), "currency": "Valuta",
                       "cost_sek": st.column_config.NumberColumn("Anskaffning (SEK)", format="%.0f")})
    st.caption("💡 Jämför antal och GAV med Avanza-appen. Skiljer något? Kontrollera att exporten gick från start.")
    if skipped:
        st.caption(f"{skipped} rader hoppas över (värdepapper utan ticker).")

    tx_now = db.load_transactions()
    only_demo = tx_now.empty or tx_now["note"].str.startswith("Demo").all()
    mode = st.radio("Vad ska hända med det som redan finns i appen?",
                    ["Ersätt allt med Avanza-filen", "Lägg till (behåll det jag redan lagt in)"],
                    index=0, key="av_mode", horizontal=True)
    if not only_demo and mode.startswith("Ersätt"):
        st.warning("Allt du tidigare lagt in i appen ersätts av innehållet i filen.")

    combined = new if mode.startswith("Ersätt") else pd.concat(
        [tx_now[~tx_now["note"].str.startswith("Demo")].drop(columns="id"), new], ignore_index=True)
    combined = combined.reset_index(drop=True)
    combined.insert(0, "id", range(1, len(combined) + 1))
    errors = portfolio.validate(combined)
    if errors:
        st.error("Filen verkar sakna några köp (säljer fler aktier än som köpts). Exportera från ett tidigare datum "
                 "– helst från när du öppnade kontot.\n\n- " + "\n- ".join(errors[:10]))
        return

    if st.button(f"📥 Importera {len(new)} transaktioner", type="primary"):
        # Konton: lägg till nya, uppdatera kontotyp på befintliga
        accs = db.load_accounts()
        for name, typ in atype.items():
            if name in accs["name"].values:
                accs.loc[accs["name"] == name, "type"] = typ
            else:
                accs = pd.concat([accs, pd.DataFrame([{"name": name, "type": typ, "broker": "Avanza",
                                                       "courtage_class": "Mini", "custom_pct": 0.0,
                                                       "custom_min": 0.0}])], ignore_index=True)
        db.save_accounts(accs)
        db.replace_all(combined)
        st.session_state.pop("av_tickers", None)
        st.session_state["flash_konton"] = (f"✅ Importerade {len(new)} transaktioner från Avanza. "
                                            "Kolla Översikt – kurserna följer nu Avanza.")
        st.rerun()
