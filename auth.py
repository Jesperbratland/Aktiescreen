"""Inloggning med engångskod via e-post – bara ägaren (AUTH_EMAIL) kan få koden.

Inställningar i Streamlit Secrets:
  AUTH_EMAIL      = "din@epost.se"          # dit koden skickas (enda som kan logga in)
  SMTP_USER       = "avsandare@gmail.com"   # kontot som skickar mejlet
  SMTP_PASSWORD   = "xxxx xxxx xxxx xxxx"   # Gmail: app-lösenord (kräver tvåstegsverifiering)
  SMTP_SERVER     = "smtp.gmail.com"        # valfritt, standard Gmail
  SMTP_PORT       = 587                     # valfritt
  AUTH_CODE_LENGTH = 4                      # valfritt, 4–8 siffror (6 är säkrare)

Skydd mot gissning (gemensamt för alla besökare, inte bara per flik):
  - koden gäller i 10 minuter och max 3 försök, sedan måste en ny skickas
  - max 5 koder per timme och minst 60 sekunder mellan utskick
  - efter 8 felaktiga försök inom 24 timmar låses inloggningen i 24 timmar och ägaren får ett varningsmejl
Saknas AUTH_EMAIL är inloggningen avstängd (appen är öppen) och en varning visas.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets as pysecrets
import smtplib
import threading
import time
from email.message import EmailMessage

import streamlit as st

CODE_TTL = 10 * 60
TRIES_PER_CODE = 3
SEND_COOLDOWN = 60
MAX_SENDS_PER_HOUR = 5
FAIL_WINDOW = 24 * 3600
MAX_FAILS = 8
LOCK_SECONDS = 24 * 3600
SESSION_HOURS = 12


def _secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def enabled() -> bool:
    return bool(_secret("AUTH_EMAIL"))


@st.cache_resource
def _state() -> dict:
    """Delas av alla sessioner på servern, så att man inte kan nollställa försöken genom att ladda om."""
    return {"lock": threading.Lock(), "key": pysecrets.token_bytes(32), "code_hash": None, "expires": 0.0,
            "tries": 0, "sends": [], "fails": [], "locked_until": 0.0}


def _hash(code: str) -> str:
    return hmac.new(_state()["key"], code.encode(), hashlib.sha256).hexdigest()


def _mask(email: str) -> str:
    user, _, domain = email.partition("@")
    return f"{user[:1]}{'•' * max(len(user) - 1, 2)}@{domain}"


def _send_mail(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _secret("SMTP_USER")
    msg["To"] = _secret("AUTH_EMAIL")
    msg.set_content(body)
    with smtplib.SMTP(_secret("SMTP_SERVER", "smtp.gmail.com"), int(_secret("SMTP_PORT", 587)), timeout=20) as s:
        s.starttls()
        s.login(_secret("SMTP_USER"), _secret("SMTP_PASSWORD"))
        s.send_message(msg)


def _code_length() -> int:
    try:
        return min(max(int(_secret("AUTH_CODE_LENGTH", 4)), 4), 8)
    except (TypeError, ValueError):
        return 4


def send_code() -> tuple[bool, str]:
    s = _state()
    now = time.time()
    with s["lock"]:
        if now < s["locked_until"]:
            return False, "Inloggningen är tillfälligt låst efter för många felaktiga försök."
        s["sends"] = [t for t in s["sends"] if now - t < 3600]
        if s["sends"] and now - s["sends"][-1] < SEND_COOLDOWN:
            return False, f"Vänta {int(SEND_COOLDOWN - (now - s['sends'][-1]))} sekunder innan du skickar en ny kod."
        if len(s["sends"]) >= MAX_SENDS_PER_HOUR:
            return False, "För många koder har skickats senaste timmen. Försök igen senare."
        n = _code_length()
        code = f"{pysecrets.randbelow(10 ** n):0{n}d}"
        s.update(code_hash=_hash(code), expires=now + CODE_TTL, tries=0)
        s["sends"].append(now)
    try:
        _send_mail(f"Din kod till Aktiescreen: {code}",
                   f"Din verifikationskod är: {code}\n\nKoden gäller i 10 minuter.\n\n"
                   "Har du inte försökt logga in? Då försöker någon annan – koden fungerar bara för dig, "
                   "så du behöver inte göra något.")
    except Exception as e:
        with s["lock"]:
            s["code_hash"] = None
        return False, f"Kunde inte skicka mejlet. Kontrollera SMTP-inställningarna. ({type(e).__name__})"
    return True, f"En kod är skickad till {_mask(_secret('AUTH_EMAIL'))}."


def check_code(entered: str) -> tuple[bool, str]:
    s = _state()
    now = time.time()
    entered = "".join(ch for ch in str(entered) if ch.isdigit())
    notify = False
    with s["lock"]:
        if now < s["locked_until"]:
            return False, "Inloggningen är tillfälligt låst efter för många felaktiga försök."
        if not s["code_hash"] or now > s["expires"]:
            return False, "Koden har gått ut eller saknas. Skicka en ny kod."
        if hmac.compare_digest(_hash(entered), s["code_hash"]):
            s.update(code_hash=None, tries=0, fails=[])
            return True, "Inloggad!"
        s["tries"] += 1
        s["fails"] = [t for t in s["fails"] if now - t < FAIL_WINDOW] + [now]
        if len(s["fails"]) >= MAX_FAILS:
            s.update(locked_until=now + LOCK_SECONDS, code_hash=None)
            notify = True
            msg = "För många felaktiga försök – inloggningen är låst i 24 timmar."
        elif s["tries"] >= TRIES_PER_CODE:
            s["code_hash"] = None
            msg = "Fel kod för många gånger. Skicka en ny kod."
        else:
            msg = f"Fel kod. {TRIES_PER_CODE - s['tries']} försök kvar för den här koden."
    if notify:
        try:
            _send_mail("⚠️ Aktiescreen: inloggningen är låst",
                       "Någon har skrivit fel kod för många gånger. Inloggningen är låst i 24 timmar.\n"
                       "Var det inte du kan någon ha din länk – koden skickas dock bara till dig.\n"
                       "Vill du låsa upp direkt: starta om appen under Manage app → Reboot på share.streamlit.io.")
        except Exception:
            pass
    return False, msg


def require_login() -> None:
    """Anropas överst i app.py. Stoppar sidan tills rätt kod har angetts."""
    if not enabled():
        return
    ok_at = st.session_state.get("auth_ok_at")
    if ok_at and time.time() - ok_at < SESSION_HOURS * 3600:
        return
    st.session_state.pop("auth_ok_at", None)

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
        st.markdown("## 🔒 Aktiescreen")
        st.caption(f"Logga in med en kod som skickas till {_mask(_secret('AUTH_EMAIL'))}.")
        if msg := st.session_state.pop("auth_msg", None):
            (st.success if msg[0] else st.error)(msg[1])
        if st.button("📧 Skicka kod till min e-post", type="primary", use_container_width=True):
            st.session_state["auth_msg"] = send_code()
            st.session_state["auth_sent"] = True
            st.rerun()
        if st.session_state.get("auth_sent"):
            n = _code_length()
            with st.form("auth_form", clear_on_submit=True):
                code = st.text_input(f"Kod ({n} siffror)", max_chars=n, placeholder="•" * n)
                if st.form_submit_button("Logga in", use_container_width=True):
                    ok, msg = check_code(code)
                    if ok:
                        st.session_state["auth_ok_at"] = time.time()
                        st.session_state.pop("auth_sent", None)
                    else:
                        st.session_state["auth_msg"] = (False, msg)
                    st.rerun()
            st.caption("Ingen kod? Kolla skräpposten, eller vänta en minut och skicka igen.")
    st.stop()


def logout_button() -> None:
    if enabled() and st.session_state.get("auth_ok_at"):
        if st.button("🔓 Logga ut", use_container_width=True):
            st.session_state.pop("auth_ok_at", None)
            st.rerun()
    elif not enabled():
        st.caption("⚠️ Inloggning är inte aktiverad – vem som helst med länken kan se appen.")
