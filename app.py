"""Aktiescreen – portföljdashboard, aktieanalys och screener.

Starta med:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Aktiescreen", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")

from ui import inject_css  # noqa: E402
import sida_analys as stock_analysis  # noqa: E402
import sida_oversikt as overview  # noqa: E402
import sida_screener as screener_page  # noqa: E402
import sida_tips as tips  # noqa: E402
import sida_transaktioner as transactions  # noqa: E402

inject_css()

pages = {
    "oversikt": st.Page(overview.render, title="Översikt", icon="📊", url_path="oversikt", default=True),
    "transaktioner": st.Page(transactions.render, title="Transaktioner", icon="🧾", url_path="transaktioner"),
    "analys": st.Page(stock_analysis.render, title="Aktieanalys", icon="🔬", url_path="analys"),
    "screener": st.Page(screener_page.render, title="Screener", icon="🧭", url_path="screener"),
    "tips": st.Page(tips.render, title="Tips & insikter", icon="💡", url_path="tips"),
}
st.session_state["_pages"] = pages

nav = st.navigation({
    "Portfölj": [pages["oversikt"], pages["transaktioner"]],
    "Analys": [pages["analys"], pages["screener"], pages["tips"]],
})

with st.sidebar:
    st.markdown("### 📈 Aktiescreen")
    if st.button("🔄 Uppdatera kurser", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Kurser via Yahoo Finance (kan vara ~15 min fördröjda). Data lagras lokalt i data/portfolio.db.")

nav.run()
