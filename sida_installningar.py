"""⚙️ Inställningar: permanent lagring (databas) och säkerhetskopia."""
from __future__ import annotations

import datetime as dt
import json

import streamlit as st

import db
import market


def render():
    st.title("⚙️ Inställningar")
    if msg := st.session_state.pop("settings_flash", None):
        st.success(msg)

    st.subheader("💾 Lagring")
    ok, text = db.storage_status()
    (st.success if ok else st.warning)(text)

    if not db.is_cloud():
        st.markdown("Just nu sparas allt i en fil på Streamlits server. Den **töms när appen startas om** – "
                    "t.ex. när den uppdateras. Koppla in en gratis databas så sparas allt för alltid.")
        with st.expander("📋 Så kopplar du in en gratis databas (ca 5 minuter)", expanded=True):
            st.markdown(
                """
**Steg 1 – Ta en säkerhetskopia först** (knappen längre ner på den här sidan). Då kan du alltid
läsa tillbaka allt om något går fel.

**Steg 2 – Skapa en gratis databas hos Neon**
1. Gå till **https://neon.com** och klicka **Sign up**. Logga in med ditt Google-konto.
2. Skapa ett projekt: namn *aktiescreen*, Postgres-version som föreslås, region **AWS US East (N. Virginia)** – samma område som Streamlits servrar, så appen blir snabbare.
3. Klicka på knappen **Connect** på projektets startsida.
4. Kopiera **anslutningssträngen** – den börjar med `postgresql://` och slutar med `sslmode=require…`.

**Steg 3 – Lägg in den i Streamlit**
1. Gå till **https://share.streamlit.io** → **⋮** vid din app → **Settings** → **Secrets**.
2. Lägg till en rad (behåll det som redan står där) och klicka **Save**:
```toml
DATABASE_URL = "postgresql://...hela-strängen-här..."
```
3. Vänta en minut och ladda om appen. Här ovanför ska det stå **💾 Data sparas permanent i molnet**.

Det du har i appen just nu flyttas över automatiskt första gången. Är något borta – läs tillbaka
säkerhetskopian nedan.
                """
            )
            st.caption("Neon är gratis upp till 0,5–1 GB – din portfölj tar några hundra kilobyte. "
                       "Databasen somnar efter 5 minuter utan användning och vaknar automatiskt när du öppnar appen "
                       "(första sidladdningen kan ta en extra sekund).")
    else:
        st.caption("Databasen hos Neon somnar efter 5 minuter utan användning och vaknar automatiskt när du "
                   "öppnar appen – första sidladdningen kan ta en extra sekund.")

    st.divider()
    st.subheader("📈 Kurser")
    cur = market.price_source()
    choice = st.radio("Kurskälla för aktuella kurser", market.PRICE_SOURCES,
                      index=market.PRICE_SOURCES.index(cur), key="ps_radio")
    if choice != cur:
        market.set_price_source(choice)
        st.cache_data.clear()
        st.rerun()
    if market.use_avanza():
        hits = st.session_state.get("avanza_hits")
        if hits and hits[1]:
            ok, total = hits
            (st.success if ok == total else st.warning)(
                f"Avanza-kurs för {ok} av {total} nordiska aktier" + ("" if ok == total else " – övriga från Yahoo."))
        st.caption("Avanza svarar inte alltid på anrop från Streamlits servrar. Då används Yahoo automatiskt.")
    else:
        st.caption("Yahoo Finance: kurser med ca 15 minuters fördröjning under börsdagen. Historik och nyckeltal "
                   "kommer alltid från Yahoo.")

    st.divider()
    st.subheader("🗂️ Säkerhetskopia")
    st.markdown("Ladda ner **allt** – konton, transaktioner, pengar för köp, bevakningar och mål – som en fil. "
                "Bra att göra då och då, och alltid innan du byter lagring.")
    data = db.export_all()
    n_tx = len(data.get("transactions", []))
    st.download_button(f"⬇️ Ladda ner säkerhetskopia ({n_tx} transaktioner)",
                       json.dumps(data, ensure_ascii=False, indent=1, default=str).encode("utf-8"),
                       file_name=f"aktiescreen_backup_{dt.date.today()}.json", mime="application/json",
                       type="primary")

    with st.expander("⬆️ Läs tillbaka en säkerhetskopia"):
        st.warning("Allt som finns i appen nu ersätts med innehållet i filen.")
        up = st.file_uploader("Säkerhetskopia (.json)", type="json", key="backup_file")
        if up is not None:
            try:
                backup = json.loads(up.getvalue().decode("utf-8"))
                if not isinstance(backup, dict) or "transactions" not in backup:
                    raise ValueError("Filen ser inte ut som en säkerhetskopia från Aktiescreen.")
            except Exception as e:
                st.error(f"Kunde inte läsa filen: {e}")
                return
            st.caption(f"Filen innehåller {len(backup.get('transactions', []))} transaktioner, "
                       f"{len(backup.get('accounts', []))} konton och {len(backup.get('watchlist', []))} bevakningar.")
            if st.button("Ersätt allt med säkerhetskopian", type="primary"):
                db.import_all(backup)
                st.session_state["settings_flash"] = "✅ Säkerhetskopian är inläst."
                st.rerun()
