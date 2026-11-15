"""Små hjälpdelar som gör appen enklare att använda: snabbsök, felmeddelanden, kom igång, ordlista."""
from __future__ import annotations

import streamlit as st

import aktielista
import db
import market


def _go(page_key: str) -> None:
    st.switch_page(st.session_state["_pages"][page_key])


# ---------------------------------------------------------------- Snabbsök
def global_search() -> None:
    """Sökruta i sidomenyn: skriv ett bolag och hamna direkt i Aktieanalys."""
    n = st.session_state.get("gs_n", 0)
    choice = st.selectbox("🔍 Sök aktie", aktielista.options(), index=None, key=f"gs_{n}",
                          accept_new_options=True, placeholder="Sök aktie …", label_visibility="collapsed")
    if not choice:
        return
    ticker = aktielista.ticker_from_label(choice)
    if not ticker:
        text = choice.strip()
        if "." in text and " " not in text:
            ticker = text.upper()
        else:
            res = market.search_ticker(text)
            if not res.empty:
                res = res[res["Typ"].isin(["EQUITY", "ETF"]) & res["Ticker"].notna()]
            if res.empty:
                st.warning("Hittade ingen aktie med det namnet.")
                return
            ticker = res.iloc[0]["Ticker"]
    st.session_state["analyze_ticker"] = ticker
    st.session_state["gs_n"] = n + 1
    _go("analys")


# ---------------------------------------------------------------- Felmeddelanden
def friendly_error(e: Exception) -> None:
    st.error("😕 **Något gick fel på den här sidan.** Dina uppgifter är inte påverkade.")
    st.markdown("Prova att klicka **Försök igen**. Hjälper det inte – ta en skärmdump av rutan "
                "*Teknisk information* och skicka till Claude, så rättas det.")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("🔄 Försök igen", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    if c2.button("📊 Till Översikt", use_container_width=True):
        _go("oversikt")
    with st.expander("Teknisk information"):
        st.exception(e)


# ---------------------------------------------------------------- Kom igång
def onboarding(tx) -> None:
    """Checklista för att komma igång. Försvinner när allt är klart eller när den döljs."""
    if db.get_setting("onboarding_hidden") == "1":
        return
    own = not tx.empty and not tx["note"].str.startswith("Demo").all()
    cash = any(v != 0 for v in db.get_cash().values()) or not db.load_cash_log().empty
    try:
        goal = float(db.get_setting("goal_amount", "0") or 0) > 0
    except ValueError:
        goal = False
    steps = [
        (own, "Lägg in dina aktier", "konton", "➕ Mitt innehav"),
        (cash, "Ange pengar för köp", "konton", "💰 Mitt innehav → Pengar för köp"),
        (goal, "Sätt ett sparmål", "mal", "🎯 Mål & sparkalkyl"),
        (db.is_cloud(), "Spara permanent (gratis databas)", "installningar", "⚙️ Inställningar"),
    ]
    done = sum(ok for ok, *_ in steps)
    if done == len(steps):
        return
    with st.expander(f"🚀 Kom igång · {done} av {len(steps)} klara", expanded=done < 2):
        st.progress(done / len(steps))
        for i, (ok, label, page, where) in enumerate(steps):
            a, b = st.columns([4, 1.4])
            a.markdown(f"{'✅' if ok else '⬜'} **{label}**" + ("" if ok else f"  \n<span class='small-muted'>{where}</span>"),
                       unsafe_allow_html=True)
            if not ok and b.button("Gör det", key=f"ob_{i}", use_container_width=True):
                _go(page)
        if st.button("Dölj listan", key="ob_hide"):
            db.set_setting("onboarding_hidden", "1")
            st.rerun()


# ---------------------------------------------------------------- Snabbknappar
def quick_actions() -> None:
    c = st.columns(4)
    for col, (label, page) in zip(c, [("➕ Lägg till aktie", "konton"), ("👀 Bevaka aktie", "bevakning"),
                                      ("🎯 Mina mål", "mal"), ("🐺 Fråga Vargen", "vargen")]):
        if col.button(label, use_container_width=True, key=f"qa_{page}_{label}"):
            _go(page)


# ---------------------------------------------------------------- Ordlista
GLOSSARY = {
    "GAV": "Genomsnittligt anskaffningsvärde – vad du har betalat i snitt per aktie, inklusive courtage.",
    "Orealiserat": "Vinst/förlust på aktier du fortfarande äger. Ändras med kursen.",
    "Realiserat": "Vinst/förlust på aktier du har sålt. Inlåst – på AF-konto är det detta du skattar för.",
    "Tidsviktad avkastning (TWR)": "Hur bra dina pengar har växt, oberoende av när du satt in eller tagit ut. "
                                   "Går att jämföra rättvist med ett index.",
    "Courtage": "Avgiften du betalar till banken för varje köp eller sälj.",
    "ISK / KF": "Konton där du inte skattar på vinster utan betalar en liten årlig skatt på värdet "
                "(1,065 % på det som överstiger 300 000 kr 2026).",
    "AF (depå)": "Vanligt aktiekonto: 30 % skatt på vinster och utdelningar. Förluster kan dras av.",
    "P/E-tal": "Aktiekursen delat med vinsten per aktie. Lågt = billigt i förhållande till vinsten.",
    "Direktavkastning": "Årlig utdelning delat med aktiekursen. 4 % betyder 4 kr per 100 kr investerat.",
    "ROE": "Avkastning på eget kapital – hur lönsamt bolaget är. Över 15 % räknas som bra.",
    "MA200": "Genomsnittlig kurs de senaste 200 handelsdagarna. Kursen över MA200 = upptrend.",
    "RSI": "Mäter hur snabbt kursen rört sig. Under 30 = översåld (fallit mycket), över 70 = överköpt.",
    "Volatilitet": "Hur mycket kursen svänger. Högre = större risk, både upp och ner.",
}


def glossary() -> None:
    with st.expander("📖 Ordlista – vad betyder orden?"):
        cols = st.columns(2)
        for i, (term, text) in enumerate(GLOSSARY.items()):
            cols[i % 2].markdown(f"**{term}**  \n<span class='small-muted'>{text}</span>", unsafe_allow_html=True)
