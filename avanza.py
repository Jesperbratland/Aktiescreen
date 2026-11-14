"""Kurser från Avanzas öppna (inofficiella) webbtjänst – ingen inloggning, inga personuppgifter.

Tjänsten är inte officiell och kan ändras eller stängas utan förvarning. Därför:
- allt är inlindat i try/except och returnerar None vid minsta problem,
- appen faller automatiskt tillbaka på Yahoo Finance,
- en Avanza-kurs som skiljer sig mer än 25 % från Yahoo kastas (troligen fel instrument).
Används för nordiska aktier (.ST, .CO, .OL, .HE).
"""
from __future__ import annotations

import math

import requests
import streamlit as st

BASE = "https://www.avanza.se"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Aktiescreen; personlig portfölj)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
TIMEOUT = 6
SUPPORTED = {".ST": "SE", ".CO": "DK", ".OL": "NO", ".HE": "FI"}


def supported(ticker: str) -> bool:
    return any(ticker.upper().endswith(s) for s in SUPPORTED)


def _symbol(ticker: str) -> str:
    """VOLV-B.ST -> 'VOLV B'"""
    base = ticker.upper().rsplit(".", 1)[0]
    return base.replace("-", " ")


def _num(v) -> float | None:
    try:
        f = float(v["value"] if isinstance(v, dict) else v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError, KeyError):
        return None


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def find_orderbook_id(ticker: str) -> str | None:
    """Slår upp Avanzas interna id för en aktie via deras sökning."""
    if not supported(ticker):
        return None
    sym = _symbol(ticker)
    country = next(c for s, c in SUPPORTED.items() if ticker.upper().endswith(s))
    try:
        r = requests.post(f"{BASE}/_api/search/filtered-search", headers=HEADERS, timeout=TIMEOUT, json={
            "query": sym, "searchFilter": {"types": ["STOCK"]},
            "pagination": {"from": 0, "size": 20},
        })
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception:
        return None
    best = None
    for h in hits:
        hsym = str(h.get("tickerSymbol") or h.get("ticker") or h.get("symbol") or "").upper().replace("-", " ")
        oid = h.get("orderBookId") or h.get("orderbookId") or h.get("id")
        if not oid or hsym != sym:
            continue
        flag = str(h.get("flagCode") or h.get("countryCode") or "").upper()
        if flag == country:
            return str(oid)
        best = best or str(oid)
    return best


@st.cache_data(ttl=60, show_spinner=False)
def get_quote(orderbook_id: str) -> dict | None:
    """Senaste kurs och föregående stängning. None om något går fel."""
    try:
        r = requests.get(f"{BASE}/_api/market-guide/stock/{orderbook_id}", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
    except Exception:
        return None
    q = d.get("quote") or d
    last = _num(q.get("last")) or _num(q.get("latest")) or _num(q.get("lastPrice"))
    if last is None:
        return None
    prev = _num(q.get("previousClosingPrice")) or _num(d.get("previousClosingPrice"))
    if prev is None:
        chg = _num(q.get("change"))
        chgp = _num(q.get("changePercent"))
        if chg is not None:
            prev = last - chg
        elif chgp is not None and chgp > -100:
            prev = last / (1 + chgp / 100)
    return {"last": last, "prev": prev}


def quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """{ticker: {'last', 'prev'}} för de tickers där Avanza svarade."""
    out = {}
    for t in tickers:
        if not supported(t):
            continue
        oid = find_orderbook_id(t)
        if not oid:
            continue
        q = get_quote(oid)
        if q:
            out[t] = q
    return out
