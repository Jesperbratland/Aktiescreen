"""Marknadsdata via yfinance (Yahoo Finance), med caching."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st
import yfinance as yf

BENCHMARKS = {
    "OMXS30": "^OMX",
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "MSCI World (ETF URTH)": "URTH",
}


def _clean_index(obj: pd.DataFrame | pd.Series):
    idx = pd.to_datetime(obj.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    obj = obj.copy()
    obj.index = idx.normalize()
    return obj[~obj.index.duplicated(keep="last")].sort_index()


@st.cache_data(ttl=900, show_spinner=False)
def get_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """OHLCV-historik för en ticker."""
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = _clean_index(df)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


@st.cache_data(ttl=900, show_spinner=False)
def get_closes(tickers: tuple[str, ...], start: str | None = None,
               period: str | None = None) -> pd.DataFrame:
    """Stängningskurser för flera tickers. Kolumner = tickers."""
    if not tickers:
        return pd.DataFrame()
    kwargs = dict(auto_adjust=False, progress=False, threads=True)
    if start:
        kwargs["start"] = start
    else:
        kwargs["period"] = period or "1y"
    try:
        raw = yf.download(list(tickers), **kwargs)
    except Exception:
        return pd.DataFrame()
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(tickers[0])
    return _clean_index(closes).dropna(how="all")


def fx_ticker(currency: str) -> str:
    return f"{currency.upper()}SEK=X"


@st.cache_data(ttl=900, show_spinner=False)
def get_fx_history(currencies: tuple[str, ...], start: str) -> pd.DataFrame:
    """SEK per 1 enhet valuta, en kolumn per valuta (SEK = 1)."""
    foreign = [c for c in currencies if c != "SEK"]
    out = pd.DataFrame()
    if foreign:
        closes = get_closes(tuple(fx_ticker(c) for c in foreign), start=start)
        if not closes.empty:
            closes.columns = [str(c).replace("SEK=X", "") for c in closes.columns]
            out = closes
    if "SEK" in currencies:
        out["SEK"] = 1.0
    return out


@st.cache_data(ttl=300, show_spinner=False)
def get_fx_now(currencies: tuple[str, ...]) -> dict[str, float]:
    rates = {"SEK": 1.0}
    foreign = [c for c in currencies if c != "SEK"]
    if foreign:
        closes = get_closes(tuple(fx_ticker(c) for c in foreign), period="10d")
        for c in foreign:
            col = fx_ticker(c)
            if col in closes and closes[col].notna().any():
                rates[c] = float(closes[col].dropna().iloc[-1])
    return rates


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_fx_on(currency: str, date: str) -> float | None:
    """Valutakurs (SEK per enhet) på ett visst datum – senaste kända värde."""
    if currency == "SEK":
        return 1.0
    d = pd.Timestamp(date)
    closes = get_closes((fx_ticker(currency),),
                        start=(d - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))
    if closes.empty:
        return None
    s = closes.iloc[:, 0].dropna()
    s = s[s.index <= d]
    return float(s.iloc[-1]) if not s.empty else None


@st.cache_data(ttl=300, show_spinner=False)
def get_quotes(tickers: tuple[str, ...]) -> pd.DataFrame:
    """Senaste kurs, föregående stängning och dagsförändring."""
    closes = get_closes(tickers, period="10d")
    rows = []
    for t in tickers:
        last = prev = math.nan
        if t in closes:
            s = closes[t].dropna()
            if len(s) >= 1:
                last = float(s.iloc[-1])
            if len(s) >= 2:
                prev = float(s.iloc[-2])
        rows.append({"ticker": t, "last": last, "prev": prev})
    df = pd.DataFrame(rows).set_index("ticker")
    df["change_pct"] = df["last"] / df["prev"] - 1
    return df


PRICE_SOURCES = ["Avanza (realtid, nordiska aktier)", "Yahoo Finance (ca 15 min fördröjning)"]


def use_avanza() -> bool:
    return st.session_state.get("price_source", PRICE_SOURCES[0]) == PRICE_SOURCES[0]


def get_live_quotes(tickers: tuple[str, ...]) -> pd.DataFrame:
    """Som get_quotes, men med Avanzas kurser där det går (om valt i sidomenyn).

    Kolumnen 'source' visar varifrån kursen kommer. Faller alltid tillbaka på Yahoo.
    """
    df = get_quotes(tickers).copy()
    df["source"] = "Yahoo"
    if not tickers or not use_avanza():
        return df
    import avanza  # importeras här så att appen fungerar även om modulen strular
    try:
        av = avanza.quotes(tickers)
    except Exception:
        av = {}
    for t, q in av.items():
        y = df.loc[t, "last"] if t in df.index else math.nan
        # Rimlighetskontroll: fel instrument ger orimlig kurs
        if not math.isnan(y) and y > 0 and abs(q["last"] / y - 1) > 0.25:
            continue
        df.loc[t, "last"] = q["last"]
        if q.get("prev"):
            df.loc[t, "prev"] = q["prev"]
        df.loc[t, "source"] = "Avanza"
    df["change_pct"] = df["last"] / df["prev"] - 1
    st.session_state["avanza_hits"] = (int((df["source"] == "Avanza").sum()),
                                       sum(1 for t in tickers if avanza.supported(t)))
    return df


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_info(ticker: str) -> dict:
    """Bolagsinformation och nyckeltal (kan vara ofullständigt för vissa bolag)."""
    try:
        return dict(yf.Ticker(ticker).info or {})
    except Exception:
        return {}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def search_ticker(query: str) -> pd.DataFrame:
    """Sök efter Yahoo-ticker på bolagsnamn, t.ex. 'Volvo'."""
    if not query or len(query) < 2:
        return pd.DataFrame()
    try:
        res = yf.Search(query, max_results=10).quotes
    except Exception:
        return pd.DataFrame()
    rows = [{
        "Ticker": q.get("symbol"),
        "Namn": q.get("longname") or q.get("shortname"),
        "Börs": q.get("exchDisp") or q.get("exchange"),
        "Typ": q.get("quoteType"),
    } for q in res]
    return pd.DataFrame(rows)
