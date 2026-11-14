"""Skatt & avgifter: ISK/KF-schablonskatt, skatt på AF-konton, courtage och valutaväxling."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import db
import fees
import market
import portfolio
import tax
from ui import fmt_pct, fmt_sek


def render():
    st.title("🧮 Skatt & avgifter")
    st.caption("Uppskattningar för att planera – inte ett deklarationsunderlag. Kontrollera alltid mot "
               "Skatteverket och din bank. Kontantsaldon på kontona finns inte i appen.")

    tx = db.load_transactions()
    accounts = db.load_accounts()
    if tx.empty:
        st.info("Lägg in dina innehav under **Mitt innehav** först.")
        return
    acc_type = dict(zip(accounts["name"], accounts["type"]))
    tx = tx.assign(acc_type=tx["account"].map(acc_type).fillna("ISK"))

    years = sorted(set(pd.to_datetime(tx["date"]).dt.year) | {dt.date.today().year}, reverse=True)
    year = st.selectbox("Inkomstår", years, index=0)

    t1, t2, t3, t4 = st.tabs(["🏦 ISK & KF", "📄 AF / depå", "💸 Courtage & avgifter", "⚖️ ISK eller AF?"])
    with t1:
        _isk(tx, accounts, year)
    with t2:
        _af(tx, year)
    with t3:
        _fees(tx, accounts, year)
    with t4:
        _compare()


MONTHS = {1: "jan", 4: "apr", 7: "jul", 10: "okt"}


# ---------------------------------------------------------------- ISK / KF
def _isk(tx: pd.DataFrame, accounts: pd.DataFrame, year: int):
    isk_tx = tx[tx["acc_type"].isin(["ISK", "KF"])]
    if isk_tx.empty:
        st.info("Du har inga ISK- eller KF-konton med innehav. Ställ in kontotyp under **Mitt innehav**.")
        return

    slr, fri, known = tax.rules_for(year)
    c = st.columns(3)
    if known:
        c[0].metric("Statslåneränta (30 nov året innan)", f"{slr:.2f} %".replace(".", ","))
        c[1].metric("Skattefritt belopp", fmt_sek(fri))
        c[2].metric("Effektiv skatt på värdet", fmt_pct(tax.isk_rate(slr), 3, sign=False))
    else:
        st.warning(f"Reglerna för {year} är inte fastställda än – fyll i en uppskattning.")
        slr = c[0].number_input("Statslåneränta (%)", 0.0, 10.0, float(slr), 0.01)
        fri = c[1].number_input("Skattefritt belopp (kr)", 0.0, 1_000_000.0, float(fri), 10_000.0)
        c[2].metric("Effektiv skatt på värdet", fmt_pct(tax.isk_rate(slr), 3, sign=False))

    start = pd.to_datetime(tx["date"]).min().strftime("%Y-%m-%d")
    rows, total_q, total_dep = [], 0.0, 0.0
    with st.spinner("Räknar ut kvartalsvärden…"):
        closes = market.get_closes(tuple(sorted(isk_tx["ticker"].unique())), start=start)
        fx_hist = market.get_fx_history(tuple(sorted(isk_tx["currency"].unique())), start)
        for acc, g in isk_tx.groupby("account"):
            hist = portfolio.portfolio_history(g.drop(columns="acc_type"), closes, fx_hist)
            qv = tax.quarter_values(hist, year)
            in_year = g[pd.to_datetime(g["date"]).dt.year == year]
            buys = in_year[in_year["type"] == "KÖP"]
            sells = in_year[in_year["type"] == "SÄLJ"]
            net = (buys["quantity"] * buys["price"] * buys["fx_rate"] + buys["fee"]).sum() - \
                  (sells["quantity"] * sells["price"] * sells["fx_rate"] - sells["fee"]).sum()
            dep = max(float(net), 0.0)
            # Ingående innehav räknas inte som insättning
            init = in_year[in_year["note"] == "Ingående innehav"]
            dep = max(dep - float((init["quantity"] * init["price"] * init["fx_rate"]).sum()), 0.0)
            total_q += sum(v for _, v, _ in qv)
            total_dep += dep
            rows.append({"Konto": acc, "Typ": accounts.set_index("name")["type"].get(acc, "ISK"),
                         **{f"{d.day} {MONTHS[d.month]}" + (" *" if prog else ""): v for d, v, prog in qv},
                         "Nettoköp under året": dep})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={k: st.column_config.NumberColumn(format="%.0f") for k in rows[0] if k not in ("Konto", "Typ")})
    st.caption("\\* = kvartalet har inte startat än, uppskattat med dagens värde. "
               "Nettoköp används som uppskattning av insättningar.")

    isk_names = set(accounts.loc[accounts["type"].isin(["ISK", "KF"]), "name"])
    stored_cash = sum(v for k, v in db.get_cash().items() if k in isk_names)
    log = db.load_cash_log()
    logged_dep = 0.0
    if not log.empty:
        ly = log[(pd.to_datetime(log["date"]).dt.year == year) & log["account"].isin(isk_names)
                 & log["kind"].isin(["INSÄTTNING", "UTTAG"])]
        logged_dep = float(ly.loc[ly["kind"] == "INSÄTTNING", "amount"].sum())
    if logged_dep > 0:
        total_dep = logged_dep
    with st.expander("Justera underlaget", expanded=False):
        a, b = st.columns(2)
        cash = a.number_input("Kassa på ISK/KF (kr)", 0.0, value=float(max(stored_cash, 0.0)), step=1000.0,
                              help="Hämtas från Pengar för köp. Kontanter ingår också i kapitalunderlaget.")
        dep_override = b.number_input("Insättningar under året (kr)", 0.0, value=float(round(total_dep)),
                                      step=1000.0, help="Från dina registrerade insättningar, annars uppskattat "
                                                        "från nettoköp. Står i din app under Transaktioner.")
    res = tax.isk_tax(total_q + 4 * cash, dep_override, year, slr, fri)

    st.subheader(f"Uppskattad ISK/KF-skatt {year}")
    k = st.columns(4)
    k[0].metric("Kapitalunderlag", fmt_sek(res["kapitalunderlag"]))
    k[1].metric("Skattefritt", fmt_sek(min(res["fribelopp"], res["kapitalunderlag"])))
    k[2].metric("Skattepliktigt", fmt_sek(res["skattepliktigt"]))
    k[3].metric("Skatt att betala", fmt_sek(res["skatt"]))
    if res["skatt"] == 0:
        st.success(f"🎉 Under {fmt_sek(res['fribelopp'])} – ingen ISK/KF-skatt för {year}.")
    st.caption("Fribeloppet gäller per person för alla ISK och KF tillsammans – även konton hos andra banker. "
               "Skatten för ISK dras på deklarationen våren efter, för KF dras den av försäkringsbolaget.")


# ---------------------------------------------------------------- AF
def _af(tx: pd.DataFrame, year: int):
    af_tx = tx[tx["acc_type"] == "AF"]
    if af_tx.empty:
        st.info("Du har inga AF-konton (depå). Ställ in kontotyp under **Mitt innehav**.")
        return
    ev = portfolio.realized_events(af_tx.drop(columns="acc_type"))
    ev = ev[pd.to_datetime(ev["date"]).dt.year == year] if not ev.empty else ev
    divs = af_tx[(af_tx["type"] == "UTDELNING") & (pd.to_datetime(af_tx["date"]).dt.year == year)]
    div_gross = float((divs["quantity"] * divs["price"] * divs["fx_rate"]).sum())

    gains = float(ev.loc[ev["gain_sek"] > 0, "gain_sek"].sum()) if not ev.empty else 0.0
    losses = float(ev.loc[ev["gain_sek"] < 0, "gain_sek"].sum()) if not ev.empty else 0.0
    res = tax.af_tax(gains, losses, div_gross)

    st.subheader(f"Realiserat {year}")
    k = st.columns(4)
    k[0].metric("Vinster", fmt_sek(res["vinster"]))
    k[1].metric("Förluster", fmt_sek(res["förluster"]))
    k[2].metric("Netto", fmt_sek(res["netto"]))
    k[3].metric("Skatt på vinst" if res["netto"] >= 0 else "Skattereduktion",
                fmt_sek(res["skatt_vinst"] if res["netto"] >= 0 else res["skattereduktion"]))
    k = st.columns(4)
    k[0].metric("Utdelningar (brutto)", fmt_sek(res["utdelningar"]))
    k[1].metric("Skatt på utdelningar (30 %)", fmt_sek(res["skatt_utdelning"]))
    k[2].metric("Total skatt (uppskattad)", fmt_sek(res["total"]))
    st.caption("Svensk utdelningsskatt dras oftast automatiskt. För utländska utdelningar kan källskatt avräknas. "
               "Förluster på noterade aktier kvittas fullt mot vinster; ett kvarvarande underskott ger 21 % skattereduktion.")

    if not ev.empty:
        st.markdown("**Försäljningar (underlag för K4, sektion A)**")
        show = ev.assign(date=pd.to_datetime(ev["date"]).dt.strftime("%Y-%m-%d"))
        st.dataframe(show, hide_index=True, use_container_width=True, column_config={
            "date": "Datum", "account": "Konto", "ticker": "Värdepapper",
            "quantity": st.column_config.NumberColumn("Antal", format="%.4g"),
            "proceeds_sek": st.column_config.NumberColumn("Försäljningspris", format="%.0f"),
            "basis_sek": st.column_config.NumberColumn("Omkostnadsbelopp", format="%.0f"),
            "gain_sek": st.column_config.NumberColumn("Vinst/förlust", format="%.0f"),
        })
        st.download_button("⬇️ Ladda ner K4-underlag (CSV)", show.to_csv(index=False).encode("utf-8"),
                           f"k4_{year}.csv", "text/csv")

    # Latent skatt om allt säljs idag
    pos = portfolio.compute_positions(af_tx.drop(columns="acc_type"), by_account=True)
    pos = pos[pos["qty"] > 0]
    if not pos.empty:
        quotes = market.get_live_quotes(tuple(sorted(pos["ticker"].unique())))
        fxn = market.get_fx_now(tuple(sorted(set(pos["currency"]) | {"SEK"})))
        val = pos["qty"] * pos["ticker"].map(quotes["last"]) * pos["currency"].map(fxn).fillna(1.0)
        unreal = (val - pos["cost_sek"]).sum()
        st.subheader("Om du sålde allt på AF idag")
        st.metric("Orealiserad vinst/förlust", fmt_sek(unreal),
                  f"skatt ≈ {fmt_sek(max(unreal, 0) * tax.TAX_RATE)}", delta_color="off")


# ---------------------------------------------------------------- Avgifter
def _fees(tx: pd.DataFrame, accounts: pd.DataFrame, year: int):
    trades = tx[tx["type"].isin(["KÖP", "SÄLJ"]) & (tx["note"] != "Ingående innehav")].copy()
    trades["year"] = pd.to_datetime(trades["date"]).dt.year
    trades["belopp_sek"] = trades["quantity"] * trades["price"] * trades["fx_rate"]
    if trades.empty:
        st.info("Inga köp eller sälj registrerade ännu (ingående innehav räknas inte).")
    else:
        y = trades[trades["year"] == year]
        k = st.columns(4)
        k[0].metric(f"Avgifter {year}", fmt_sek(y["fee"].sum()))
        k[1].metric(f"Antal affärer {year}", len(y))
        k[2].metric(f"Omsatt {year}", fmt_sek(y["belopp_sek"].sum()))
        k[3].metric("Avgifter sedan start", fmt_sek(trades["fee"].sum()))
        per = y.groupby("account").agg(Affärer=("fee", "size"), Omsatt=("belopp_sek", "sum"), Avgifter=("fee", "sum"))
        per["Avgift i % av omsatt"] = per["Avgifter"] / per["Omsatt"] * 100
        st.dataframe(per.reset_index().rename(columns={"account": "Konto"}), hide_index=True,
                     use_container_width=True, column_config={
                         "Omsatt": st.column_config.NumberColumn(format="%.0f"),
                         "Avgifter": st.column_config.NumberColumn(format="%.0f"),
                         "Avgift i % av omsatt": st.column_config.NumberColumn(format="%.3f %%")})

        # Tips: billigaste klassen för din typiska affärsstorlek
        st.subheader("Har du rätt courtageklass?")
        for acc in accounts.itertuples():
            a_tr = trades[(trades["account"] == acc.name) & (trades["currency"] == "SEK")]
            if acc.broker not in ("Avanza", "Nordnet") or a_tr.empty:
                continue
            costs = {cls: sum(fees.calc_fees(b, acc.broker, cls, False)["courtage"] for b in a_tr["belopp_sek"])
                     for cls in fees.COURTAGE[acc.broker] if cls not in fees.FREE_CLASSES}
            best = min(costs, key=costs.get)
            now = costs.get(acc.courtage_class)
            median = a_tr["belopp_sek"].median()
            if now is not None and best != acc.courtage_class and now - costs[best] > 1:
                st.markdown(f"💡 **{acc.name}**: med dina affärer (median {fmt_sek(median)}) hade **{best}** kostat "
                            f"{fmt_sek(costs[best])} i stället för {fmt_sek(now)} med {acc.courtage_class}.")
            else:
                st.markdown(f"✅ **{acc.name}**: {acc.courtage_class} passar dina affärer (median {fmt_sek(median)}).")

    st.subheader("Räkna på en affär")
    c = st.columns(4)
    acc_name = c[0].selectbox("Konto", accounts["name"].tolist(), key="fee_acc")
    amount = c[1].number_input("Belopp (kr)", 0.0, value=10_000.0, step=1000.0)
    foreign = c[2].checkbox("Utländsk aktie", help="Lägger till 0,25 % valutaväxling")
    a = accounts.set_index("name").loc[acc_name]
    f = fees.calc_fees(amount, a["broker"], a["courtage_class"], foreign, a["custom_pct"], a["custom_min"])
    c[3].metric("Kostnad", fmt_sek(f["total"], 2),
                f"courtage {fmt_sek(f['courtage'], 2)} + växling {fmt_sek(f['fx_fee'], 2)}" if foreign else None,
                delta_color="off")


# ---------------------------------------------------------------- Jämförelse
def _compare():
    st.markdown("Vilken kontotyp lönar sig? Det beror på vilken avkastning du får.")
    slr, fri, _ = tax.rules_for(dt.date.today().year)
    rate = tax.isk_rate(slr)
    breakeven = rate / tax.TAX_RATE
    c = st.columns(3)
    value = c[0].number_input("Sparat belopp (kr)", 0.0, value=500_000.0, step=50_000.0)
    ret = c[1].number_input("Förväntad avkastning per år (%)", -50.0, 100.0, 7.0, 0.5) / 100
    gain = value * ret
    isk = max(value - fri, 0) * rate
    af = max(gain, 0) * tax.TAX_RATE
    c[2].metric("Brytpunkt (avkastning)", fmt_pct(breakeven, 2, sign=False),
                help="Över denna avkastning är ISK billigare än AF (bortsett från fribeloppet).")
    k = st.columns(2)
    k[0].metric("Skatt på ISK/KF", fmt_sek(isk))
    k[1].metric("Skatt på AF (om du säljer)", fmt_sek(af))
    if isk < af:
        st.success(f"ISK/KF blir billigast i det här exemplet – du sparar ungefär {fmt_sek(af - isk)} per år.")
    elif af < isk:
        st.info(f"AF blir billigast i det här exemplet – skillnad ungefär {fmt_sek(isk - af)} per år. "
                "AF kan också vara bättre för den som vill kvitta förluster.")
    st.caption(f"Med {fmt_sek(fri)} skattefritt är ISK oftast bäst för de flesta. På AF skjuts skatten upp tills du säljer.")
