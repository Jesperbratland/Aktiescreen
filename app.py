"""Aktiescreen – portföljdashboard, aktieanalys och screener.

Starta med:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Aktiescreen", page_icon="🎄", layout="wide",
                   initial_sidebar_state="expanded")

import auth  # noqa: E402
import charts  # noqa: E402,F401  (registrerar diagramstilen)
import market  # noqa: E402
from ui import JULTEMA, christmas_greeting, inject_christmas, inject_css  # noqa: E402
import sida_analys as stock_analysis  # noqa: E402
import sida_bevakning as bevakning  # noqa: E402
import sida_konton as konton  # noqa: E402
import sida_malkalkyl as malkalkyl  # noqa: E402
import sida_skatt as skatt  # noqa: E402
import sida_vargen as vargen  # noqa: E402
import sida_oversikt as overview  # noqa: E402
import sida_screener as screener_page  # noqa: E402
import sida_tips as tips  # noqa: E402
import sida_transaktioner as transactions  # noqa: E402

inject_css()
inject_christmas(snow=st.session_state.get("snow", True))
auth.require_login()  # stoppar här tills rätt lösenord har angetts

pages = {
    "oversikt": st.Page(overview.render, title="Översikt", icon="📊", url_path="oversikt", default=True),
    "konton": st.Page(konton.render, title="Mitt innehav", icon="➕", url_path="konton"),
    "transaktioner": st.Page(transactions.render, title="Transaktioner", icon="🧾", url_path="transaktioner"),
    "skatt": st.Page(skatt.render, title="Skatt & avgifter", icon="🧮", url_path="skatt"),
    "mal": st.Page(malkalkyl.render, title="Mål & sparkalkyl", icon="🎯", url_path="mal"),
    "bevakning": st.Page(bevakning.render, title="Bevakningslista", icon="👀", url_path="bevakning"),
    "analys": st.Page(stock_analysis.render, title="Aktieanalys", icon="🔬", url_path="analys"),
    "screener": st.Page(screener_page.render, title="Screener", icon="🧭", url_path="screener"),
    "tips": st.Page(tips.render, title="Tips & insikter", icon="💡", url_path="tips"),
    "vargen": st.Page(vargen.render, title="Fråga Vargen", icon="🐺", url_path="vargen"),
}
st.session_state["_pages"] = pages

nav = st.navigation({
    "AI-expert": [pages["vargen"]],
    "Portfölj": [pages["oversikt"], pages["konton"], pages["transaktioner"], pages["skatt"]],
    "Analys": [pages["bevakning"], pages["analys"], pages["screener"], pages["tips"]],
    "Mål": [pages["mal"]],
})

with st.sidebar:
    st.markdown("### 🎄 Aktiescreen" if JULTEMA else "### 📈 Aktiescreen")
    christmas_greeting()
    if st.button("🔄 Uppdatera kurser", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.selectbox("Kurskälla", market.PRICE_SOURCES, key="price_source",
                 help="Avanza ger samma kurser som i Avanza-appen (realtid) för nordiska aktier. "
                      "Svarar inte Avanza används Yahoo automatiskt.")
    if hits := st.session_state.get("avanza_hits"):
        ok, total = hits
        if total and market.use_avanza():
            st.caption(f"{'✅' if ok == total else '⚠️'} Avanza-kurs för {ok} av {total} nordiska aktier"
                       + ("" if ok == total else " – övriga från Yahoo"))
    if JULTEMA:
        st.toggle("❄️ Snöfall", value=True, key="snow")
    st.caption("Historik och nyckeltal från Yahoo Finance. Data lagras i data/portfolio.db.")
    auth.logout_button()

nav.run()
