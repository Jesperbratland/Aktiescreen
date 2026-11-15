"""Aktiescreen – portföljdashboard, aktieanalys och screener.

Starta med:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Aktiescreen", page_icon="🎄", layout="wide",
                   initial_sidebar_state="expanded")

import auth  # noqa: E402
import db  # noqa: E402
import charts  # noqa: E402,F401  (registrerar diagramstilen)
import market  # noqa: E402,F401
import ui_helpers  # noqa: E402
from ui import JULTEMA, christmas_greeting, inject_christmas, inject_css  # noqa: E402
import sida_analys as stock_analysis  # noqa: E402
import sida_bevakning as bevakning  # noqa: E402
import sida_handelser as handelser_page  # noqa: E402
import sida_installningar as installningar  # noqa: E402
import sida_konton as konton  # noqa: E402
import sida_malkalkyl as malkalkyl  # noqa: E402
import sida_skatt as skatt  # noqa: E402
import sida_vargen as vargen  # noqa: E402
import sida_oversikt as overview  # noqa: E402
import sida_screener as screener_page  # noqa: E402
import sida_tips as tips  # noqa: E402
import sida_transaktioner as transactions  # noqa: E402
import sida_utvardering as utvardering  # noqa: E402

inject_css()
inject_christmas(snow=st.session_state.get("snow", True))
auth.require_login()  # stoppar här tills rätt lösenord har angetts

pages = {
    "oversikt": st.Page(overview.render, title="Översikt", icon="📊", url_path="oversikt", default=True),
    "utvardering": st.Page(utvardering.render, title="Portföljbetyg", icon="🏅", url_path="betyg"),
    "konton": st.Page(konton.render, title="Mitt innehav", icon="➕", url_path="konton"),
    "transaktioner": st.Page(transactions.render, title="Transaktioner", icon="🧾", url_path="transaktioner"),
    "skatt": st.Page(skatt.render, title="Skatt & avgifter", icon="🧮", url_path="skatt"),
    "mal": st.Page(malkalkyl.render, title="Mål & sparkalkyl", icon="🎯", url_path="mal"),
    "bevakning": st.Page(bevakning.render, title="Bevakningslista", icon="👀", url_path="bevakning"),
    "handelser": st.Page(handelser_page.render, title="Kalender & nyheter", icon="📅", url_path="kalender"),
    "analys": st.Page(stock_analysis.render, title="Aktieanalys", icon="🔬", url_path="analys"),
    "screener": st.Page(screener_page.render, title="Screener", icon="🧭", url_path="screener"),
    "tips": st.Page(tips.render, title="Tips & insikter", icon="💡", url_path="tips"),
    "vargen": st.Page(vargen.render, title="Fråga Vargen", icon="🐺", url_path="vargen"),
    "installningar": st.Page(installningar.render, title="Inställningar", icon="⚙️", url_path="installningar"),
}
st.session_state["_pages"] = pages

nav = st.navigation({
    "AI-expert": [pages["vargen"]],
    "Portfölj": [pages["oversikt"], pages["utvardering"], pages["konton"], pages["transaktioner"], pages["skatt"]],
    "Analys": [pages["bevakning"], pages["handelser"], pages["analys"], pages["screener"], pages["tips"]],
    "Mål": [pages["mal"]],
    "Övrigt": [pages["installningar"]],
})

with st.sidebar:
    st.markdown("### 🎄 Aktiescreen" if JULTEMA else "### 📈 Aktiescreen")
    christmas_greeting()
    ui_helpers.global_search()
    if st.button("🔄 Uppdatera kurser", use_container_width=True,
                 help="Kurser hämtas automatiskt var 5:e minut. Klicka för att hämta direkt."):
        st.cache_data.clear()
        st.toast("Kurserna är uppdaterade", icon="🔄")
    if JULTEMA:
        st.toggle("❄️ Snöfall", value=True, key="snow")
    if not db.is_cloud():
        st.caption("⚠️ Data sparas tillfälligt. Se **⚙️ Inställningar** för permanent lagring.")
    auth.logout_button()

try:
    nav.run()
except Exception as e:  # Streamlits egna styrsignaler (rerun/stop/switch_page) är inte Exception
    if type(e).__module__.startswith("streamlit.runtime"):
        raise
    ui_helpers.friendly_error(e)
