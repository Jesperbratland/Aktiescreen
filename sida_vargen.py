"""Vargen 🐺 – chatta med en AI-aktieexpert som ser din portfölj."""
from __future__ import annotations

import streamlit as st

import agent

AVATAR = "🐺"
TOOL_LABELS = {"hamta_portfolj": "📂 Kollar din portfölj", "hamta_aktie": "📈 Hämtar data för",
               "sok_ticker": "🔎 Söker efter"}
STARTERS = [
    "Hur ser min portfölj ut – vad är bra och vad är riskabelt?",
    "Vilken av mina aktier är mest övervärderad just nu?",
    "Analysera Investor B åt mig",
    "Jag har pengar att köpa för – vad skulle du titta på?",
]


def _secret(name: str) -> str | None:
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def render():
    st.title("🐺 Vargen")
    st.caption("Din AI-aktieexpert – en påhittad mäklarkaraktär som drivs av Claude. Han ser dina innehav och "
               "hämtar aktuella kurser och nyckeltal. Inte finansiell rådgivning – du fattar besluten.")

    # Lösenordsskydd (rekommenderas eftersom hemsidan är publik och varje fråga kostar API-pengar)
    pw = _secret("APP_PASSWORD")
    if pw and not st.session_state.get("vargen_ok"):
        entered = st.text_input("Lösenord", type="password")
        if entered and entered == pw:
            st.session_state["vargen_ok"] = True
            st.rerun()
        elif entered:
            st.error("Fel lösenord.")
        return

    api_key = _secret("ANTHROPIC_API_KEY") or st.session_state.get("anthropic_key")
    if not api_key:
        _setup_guide()
        return

    msgs = st.session_state.setdefault("vargen_msgs", [])
    if not msgs:
        with st.chat_message("assistant", avatar=AVATAR):
            st.markdown("**Lyssna nu.** Jag är Vargen, och jag har koll på marknaden. Fråga mig om dina aktier, "
                        "ett bolag du spanar på eller vad du ska göra med dina pengar – så går vi igenom siffrorna. 🐺")
        cols = st.columns(2)
        for i, q in enumerate(STARTERS):
            if cols[i % 2].button(q, key=f"starter_{i}", use_container_width=True):
                st.session_state["vargen_pending"] = q
                st.rerun()

    for m in msgs:
        with st.chat_message(m["role"], avatar=AVATAR if m["role"] == "assistant" else "🙂"):
            st.markdown(m["content"])

    prompt = st.chat_input("Fråga Vargen om aktier …") or st.session_state.pop("vargen_pending", None)
    if prompt:
        msgs.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🙂"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar=AVATAR):
            status = st.status("Vargen tänker …", expanded=False)

            def on_tool(name, args):
                arg = args.get("ticker") or args.get("namn") or ""
                status.write(f"{TOOL_LABELS.get(name, name)} {arg}".strip())

            try:
                answer = agent.chat(api_key, msgs[-20:], on_tool=on_tool)
                status.update(label="Klart", state="complete")
            except Exception as e:
                status.update(label="Något gick fel", state="error")
                answer = _error_text(e)
            st.markdown(answer)
        msgs.append({"role": "assistant", "content": answer})

    if msgs and st.button("🧹 Ny konversation"):
        st.session_state["vargen_msgs"] = []
        st.rerun()


def _error_text(e: Exception) -> str:
    text = str(e)
    if "authentication" in text.lower() or "401" in text:
        return "⚠️ API-nyckeln fungerar inte. Kontrollera ANTHROPIC_API_KEY i Streamlit Secrets."
    if "credit" in text.lower() or "billing" in text.lower():
        return "⚠️ Ditt Anthropic-konto saknar krediter. Fyll på under Billing på console.anthropic.com."
    if "not_found" in text.lower() or "model" in text.lower():
        return f"⚠️ Modellen hittades inte ({agent.MODEL}). Be Claude byta modell i agent.py.\n\n`{text[:300]}`"
    return f"⚠️ Något gick fel: `{text[:300]}`"


def _setup_guide():
    st.info("🔑 Vargen behöver en **API-nyckel från Anthropic** för att kunna prata. Det kostar några ören per fråga.")
    st.markdown(
        """
**Så här kopplar du in honom (ca 5 minuter):**

1. Gå till **https://console.anthropic.com** och skapa ett konto.
2. Under **Billing** – lägg in betalkort och fyll på t.ex. 5 dollar.
3. Under **API Keys** – klicka **Create Key** och kopiera nyckeln (börjar med `sk-ant-`).
4. Gå till **https://share.streamlit.io**, klicka på **⋮** vid din app → **Settings** → **Secrets**.
5. Klistra in följande (med din nyckel och ett eget lösenord) och klicka **Save**:
```toml
ANTHROPIC_API_KEY = "sk-ant-din-nyckel-här"
APP_PASSWORD = "välj-ett-lösenord"
```
Lösenordet gör att bara du kan prata med Vargen – annars kan vem som helst med länken använda din nyckel.
        """
    )
    with st.expander("Testa direkt utan att spara nyckeln"):
        key = st.text_input("API-nyckel (sparas bara tills du stänger sidan)", type="password")
        if key.startswith("sk-ant-"):
            st.session_state["anthropic_key"] = key
            st.rerun()
