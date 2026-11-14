"""Lösenordsskydd för hela appen – lösenordet frågas varje gång hemsidan öppnas.

Inställning i Streamlit Secrets:
  APP_PASSWORD = "ditt-lösenord"
Saknas APP_PASSWORD är appen öppen och en varning visas i sidomenyn.

Skydd mot gissning (gemensamt för alla besökare, går inte att nollställa genom att ladda om):
  - 5 fel inom 15 minuter  -> paus i 15 minuter
  - 20 fel inom 24 timmar  -> låst i 24 timmar (lås upp: Reboot app på share.streamlit.io)
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time

import streamlit as st

SHORT_WINDOW, SHORT_MAX = 15 * 60, 5
LONG_WINDOW, LONG_MAX = 24 * 3600, 20


def _password() -> str | None:
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None


def enabled() -> bool:
    return bool(_password())


@st.cache_resource
def _state() -> dict:
    return {"lock": threading.Lock(), "fails": []}


def _locked(now: float, fails: list[float]) -> str | None:
    recent = [t for t in fails if now - t < SHORT_WINDOW]
    day = [t for t in fails if now - t < LONG_WINDOW]
    if len(day) >= LONG_MAX:
        return "För många felaktiga försök – inloggningen är låst i 24 timmar."
    if len(recent) >= SHORT_MAX:
        wait = int((SHORT_WINDOW - (now - recent[0])) / 60) + 1
        return f"För många felaktiga försök. Vänta {wait} minuter och försök igen."
    return None


def check_password(entered: str) -> tuple[bool, str]:
    s = _state()
    now = time.time()
    with s["lock"]:
        s["fails"] = [t for t in s["fails"] if now - t < LONG_WINDOW]
        if msg := _locked(now, s["fails"]):
            return False, msg
        a = hashlib.sha256(entered.encode()).digest()
        b = hashlib.sha256(_password().encode()).digest()
        if hmac.compare_digest(a, b):
            return True, ""
        s["fails"].append(now)
        return False, _locked(now, s["fails"]) or "Fel lösenord."


def require_login() -> None:
    """Anropas överst i app.py. Stoppar sidan tills rätt lösenord har angetts."""
    if not enabled() or st.session_state.get("auth_ok"):
        return
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.markdown("## 🔒 Aktiescreen")
        st.caption("Skriv ditt lösenord för att öppna appen.")
        if msg := st.session_state.pop("auth_msg", None):
            st.error(msg)
        with st.form("login", clear_on_submit=True):
            pw = st.text_input("Lösenord", type="password")
            if st.form_submit_button("Logga in", type="primary", use_container_width=True):
                ok, msg = check_password(pw)
                if ok:
                    st.session_state["auth_ok"] = True
                else:
                    st.session_state["auth_msg"] = msg
                st.rerun()
    st.stop()


def logout_button() -> None:
    if not enabled():
        st.caption("⚠️ Inget lösenord är satt – vem som helst med länken kan se appen.")
    elif st.button("🔒 Logga ut", use_container_width=True):
        st.session_state.pop("auth_ok", None)
        st.rerun()
