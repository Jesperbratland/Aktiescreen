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
    "Vad tycker du om Investor B?",
    "Jag har pengar att investera – vad ska jag titta på?",
]


def _secret(name: str) -> str | None:
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def render():
    st.title("🐺 Vargen")
    st.caption("Din aktieexpert – en påhittad mäklarkaraktär. Han ser dina innehav och hämtar aktuella kurser "
               "och nyckeltal. Inte finansiell rådgivning – du fattar besluten.")

    groq_key = _secret("GROQ_API_KEY") or st.session_state.get("groq_key")
    claude_key = _secret("ANTHROPIC_API_KEY")
    if groq_key:
        provider, api_key = "groq", groq_key
        st.success("🟢 **AI-läge** – gratis via Groq. Prata fritt med Vargen.", icon="🐺")
    elif claude_key:
        provider, api_key = "claude", claude_key
        st.success("🟢 **AI-läge** – Claude.", icon="🐺")
    else:
        provider, api_key = "offline", None
        st.info("🟡 **Grundläge** – helt gratis, ingen AI. Vargen går igenom din portfölj och analyserar aktier "
                "med appens egna siffror. Vill du kunna prata fritt? Se *Koppla in gratis AI* längst ner.")

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
                answer = agent.chat(provider, api_key, msgs[-20:], on_tool=on_tool)
                status.update(label="Klart", state="complete")
            except Exception as e:
                status.update(label="Något gick fel", state="error")
                answer = _error_text(e)
            st.markdown(answer)
        msgs.append({"role": "assistant", "content": answer})

    if msgs and st.button("🧹 Ny konversation"):
        st.session_state["vargen_msgs"] = []
        st.rerun()
    if provider == "offline":
        _setup_guide()


def _error_text(e: Exception) -> str:
    text = str(e)
    low = text.lower()
    if "rate_limit" in low or "429" in low:
        return "⏳ Gratiskvoten är slut för stunden. Vänta en minut (eller till i morgon om dagskvoten är slut)."
    if "401" in low or "invalid api key" in low or "authentication" in low:
        return "⚠️ API-nyckeln fungerar inte. Kontrollera GROQ_API_KEY i Streamlit Secrets."
    if "model" in low and ("not found" in low or "does not exist" in low or "decommissioned" in low):
        return f"⚠️ AI-modellen finns inte längre ({agent.GROQ_MODEL}). Be Claude byta modell i agent.py."
    return f"⚠️ Något gick fel: `{text[:300]}`"


def _setup_guide():
    with st.expander("🔑 Koppla in gratis AI (ca 3 minuter, inget betalkort)"):
        st.markdown(
            """
Vargen kan drivas av en gratis AI-tjänst som heter **Groq**. Den är gratis upp till ungefär
1 000 frågor per dag – mer än nog för dig.

1. Gå till **https://console.groq.com** och logga in med ditt Google-konto.
2. Klicka på **API Keys** → **Create API Key**, ge den ett namn (t.ex. *aktiescreen*) och kopiera nyckeln
   (börjar med `gsk_`). Den visas bara en gång!
3. Gå till **https://share.streamlit.io**, klicka på **⋮** vid din app → **Settings** → **Secrets**.
4. Klistra in följande och klicka **Save**:
```toml
GROQ_API_KEY = "gsk_din-nyckel-här"
```
            """
        )
        key = st.text_input("…eller testa direkt (sparas bara tills du stänger sidan)", type="password",
                            placeholder="gsk_…")
        if key.startswith("gsk_"):
            st.session_state["groq_key"] = key
            st.rerun()
