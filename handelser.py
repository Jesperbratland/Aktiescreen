"""📅 Händelser: rapport- och utdelningskalender, utdelningsprognos, nyheter och insynshandel.

Källor (alla gratis, inga nycklar):
  - Yahoo Finance via yfinance: kalender (rapportdatum, X-dag), utdelningshistorik, nyheter, insider (USA)
  - Google News RSS: svenska nyheter om bolaget
  - Finansinspektionens insynsregister (marknadssok.fi.se): insynshandel i svenska bolag, CSV-export
Allt är inlindat i try/except – svarar en källa inte blir resultatet bara tomt.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

import aktielista
import market

UA = {"User-Agent": "Mozilla/5.0 (Aktiescreen; personlig portfölj)"}
MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
FI_SEARCH = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search"

# Namn som Finansinspektionen använder när bolagsnamnet i listan inte räcker
FI_NAMES = {
    "HM-B.ST": "Hennes", "SEB-A.ST": "Skandinaviska Enskilda", "SOBI.ST": "Swedish Orphan",
    "AZN.ST": "AstraZeneca", "INDU-C.ST": "Industrivärden", "LATO-B.ST": "Latour",
    "LUND-B.ST": "Lundbergföretagen", "AZA.ST": "Avanza", "SAVE.ST": "Nordnet", "ALIV-SDB.ST": "Autoliv",
    "SBB-B.ST": "Samhällsbyggnadsbolaget", "SCA-B.ST": "Svenska Cellulosa", "SHB-A.ST": "Handelsbanken",
    "NDA-SE.ST": "Nordea", "BEIJ-B.ST": "Beijer Ref", "LIFCO-B.ST": "Lifco", "ADDT-B.ST": "Addtech",
}


# ---------------------------------------------------------------- hjälp
def _date(v) -> dt.date | None:
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            if not math.isfinite(v):
                return None
            return dt.datetime.fromtimestamp(v, dt.timezone.utc).date()
        ts = pd.Timestamp(v)
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def fmt_date(d: dt.date | None) -> str:
    return "–" if d is None else f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def days_text(d: dt.date | None) -> str:
    if d is None:
        return ""
    n = (d - dt.date.today()).days
    if n == 0:
        return "idag"
    if n == 1:
        return "i morgon"
    if n > 1:
        return f"om {n} dagar"
    if n == -1:
        return "i går"
    return f"för {-n} dagar sedan"


def ago(ts: pd.Timestamp | None) -> str:
    if ts is None or pd.isna(ts):
        return ""
    now = pd.Timestamp.now(tz="UTC")
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    m = (now - ts).total_seconds() / 60
    if m < 60:
        return f"{max(int(m), 1)} min sedan"
    if m < 60 * 24:
        return f"{int(m // 60)} tim sedan"
    d = int(m // (60 * 24))
    return "i går" if d == 1 else f"{d} dagar sedan"


def company_name(ticker: str) -> str:
    if ticker in aktielista.POPULAR:
        return aktielista.POPULAR[ticker]
    info = market.get_info(ticker)
    return info.get("shortName") or info.get("longName") or ticker


def core_name(ticker: str) -> str:
    """Bolagets kärnnamn för sökningar: 'Volvo B' -> 'Volvo', 'Atlas Copco A' -> 'Atlas Copco'."""
    if ticker in FI_NAMES:
        return FI_NAMES[ticker]
    name = company_name(ticker)
    name = re.sub(r"\s+(A|B|C|D|SDB|SE|ser\.? ?[A-D])$", "", name.strip(), flags=re.I)
    name = re.sub(r"\b(AB|ASA|A/S|Oyj|Inc\.?|Corp\.?|Corporation|plc|Ltd|\(publ\)|Group|Holding)\b", "", name,
                  flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" ,.-") or ticker


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------------------------------------------------------------- kalender
@st.cache_data(ttl=12 * 3600, show_spinner=False)
def calendar(ticker: str) -> dict:
    """{'earnings': [date, ...], 'ex_div': date|None, 'div_pay': date|None}"""
    out = {"earnings": [], "ex_div": None, "div_pay": None}
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception:
        cal = None
    if isinstance(cal, pd.DataFrame):
        cal = {str(k): (v.iloc[0] if len(v) else None) for k, v in cal.T.items()} if not cal.empty else {}
    if isinstance(cal, dict):
        e = cal.get("Earnings Date")
        e = e if isinstance(e, (list, tuple)) else [e]
        out["earnings"] = sorted({d for d in (_date(x) for x in e) if d})
        out["ex_div"] = _date(cal.get("Ex-Dividend Date"))
        out["div_pay"] = _date(cal.get("Dividend Date"))
    if not out["earnings"]:
        info = market.get_info(ticker)
        for key in ("earningsTimestamp", "earningsTimestampStart"):
            d = _date(info.get(key))
            if d:
                out["earnings"] = [d]
                break
    return out


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def dividend_history(ticker: str) -> pd.Series:
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    try:
        s = yf.Ticker(ticker).dividends
    except Exception:
        return empty
    if s is None or s.empty:
        return empty
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return pd.Series(s.values, index=idx.normalize()).sort_index()


def dividend_forecast(holdings: list[tuple[str, float, str]]) -> pd.DataFrame:
    """Prognos för kommande 12 månader: varje utdelning senaste året upprepas ett år senare.

    holdings: [(ticker, antal, valuta)]. Bekräftade X-dagar från kalendern ersätter prognosdatumet.
    """
    today = pd.Timestamp.today().normalize()
    fx = market.get_fx_now(tuple(sorted({c for _, _, c in holdings} | {"SEK"})))
    rows = []
    for ticker, qty, cur in holdings:
        hist = dividend_history(ticker)
        last = hist[hist.index > today - pd.Timedelta(days=365)]
        cal = calendar(ticker)
        confirmed = pd.Timestamp(cal["ex_div"]) if cal.get("ex_div") else None
        for d, amount in last.items():
            when = d + pd.DateOffset(years=1)
            status = "Prognos"
            if confirmed is not None and confirmed >= today and abs((confirmed - when).days) <= 60:
                when, status = confirmed, "Bekräftad X-dag"
            if when < today:
                continue
            rows.append({"date": when.date(), "ticker": ticker, "name": company_name(ticker), "per_share": float(amount),
                         "currency": cur, "qty": qty, "kr": float(amount) * qty * fx.get(cur, 1.0), "status": status})
        # Bekräftad X-dag utan motsvarighet i historiken (t.ex. ny utdelare)
        if confirmed is not None and confirmed >= today and not any(r["ticker"] == ticker and r["status"] != "Prognos"
                                                                   for r in rows):
            rate = market.get_info(ticker).get("lastDividendValue")
            if rate:
                rows.append({"date": confirmed.date(), "ticker": ticker, "name": company_name(ticker),
                             "per_share": float(rate), "currency": cur, "qty": qty,
                             "kr": float(rate) * qty * fx.get(cur, 1.0), "status": "Bekräftad X-dag"})
    df = pd.DataFrame(rows)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


def upcoming_events(tickers: list[str], days: int = 90) -> pd.DataFrame:
    """Rapporter och X-dagar de närmaste dagarna."""
    today = dt.date.today()
    end = today + dt.timedelta(days=days)
    rows = []
    for t in tickers:
        cal = calendar(t)
        name = company_name(t)
        for d in cal["earnings"][:1]:
            if today <= d <= end:
                rows.append({"date": d, "ticker": t, "name": name, "kind": "📊 Rapport"})
        if cal["ex_div"] and today <= cal["ex_div"] <= end:
            rows.append({"date": cal["ex_div"], "ticker": t, "name": name, "kind": "✂️ X-dag (sista dag med utdelning: dagen före)"})
        if cal["div_pay"] and today <= cal["div_pay"] <= end:
            rows.append({"date": cal["div_pay"], "ticker": t, "name": name, "kind": "💸 Utbetalning"})
    df = pd.DataFrame(rows)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


# ---------------------------------------------------------------- nyheter
def _yahoo_news(ticker: str) -> list[dict]:
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:
        return []
    out = []
    for it in items:
        c = it.get("content") if isinstance(it.get("content"), dict) else it
        title = c.get("title")
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or c.get("link"))
        when = c.get("pubDate") or c.get("displayTime") or it.get("providerPublishTime")
        try:
            ts = pd.Timestamp(when, unit="s", tz="UTC") if isinstance(when, (int, float)) else pd.Timestamp(when)
        except Exception:
            ts = None
        src = (c.get("provider") or {}).get("displayName") or c.get("publisher") or "Yahoo Finance"
        if title and url:
            out.append({"title": title, "url": url, "source": src, "ts": ts})
    return out


def _google_news(query: str) -> list[dict]:
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{query} when:30d")
           + "&hl=sv&gl=SE&ceid=SE:sv")
    try:
        r = requests.get(url, headers=UA, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        src = (item.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        try:
            ts = pd.Timestamp(item.findtext("pubDate"))
        except Exception:
            ts = None
        link = item.findtext("link")
        if title and link:
            out.append({"title": title, "url": link, "source": src or "Google Nyheter", "ts": ts})
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def news(ticker: str, limit: int = 10) -> list[dict]:
    """De senaste nyheterna om bolaget (svenska + engelska), nyast först."""
    items = _yahoo_news(ticker)
    if ticker.upper().endswith((".ST", ".CO", ".OL", ".HE")) or len(items) < 3:
        items += _google_news(f'"{core_name(ticker)}" aktie' if ticker.upper().endswith(".ST") else core_name(ticker))
    seen, out = set(), []
    for it in items:
        key = _norm(it["title"])[:70]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: x["ts"] if x["ts"] is not None and not pd.isna(x["ts"])
             else pd.Timestamp("1970-01-01", tz="UTC"), reverse=True)
    for it in out:
        if it["ts"] is not None and not pd.isna(it["ts"]) and it["ts"].tzinfo is None:
            it["ts"] = it["ts"].tz_localize("UTC")
    return out[:limit]


# ---------------------------------------------------------------- insynshandel
FI_COLS = {  # vår kolumn -> början på FI:s rubrik (gemener)
    "published": "publiceringsdatum", "issuer": "emittent", "person": "person i ledande",
    "role": "befattning", "related": "närstående", "kind": "karaktär", "instrument": "instrumentnamn",
    "date": "transaktionsdatum", "volume": "volym", "price": "pris", "currency": "valuta", "status": "status",
}


def fi_search_url(ticker: str) -> str:
    return FI_SEARCH + "?" + urllib.parse.urlencode({"SearchFunctionType": "Insyn", "Utgivare": core_name(ticker)})


def _parse_number(v) -> float:
    s = str(v).strip().replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_fi_csv(content: bytes) -> pd.DataFrame:
    """Tolkar FI:s CSV-export (kolumnerna känns igen på namn)."""
    text = None
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = content.decode("utf-16")
    else:
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    if not text or ";" not in text.split("\n", 1)[0] and "," not in text.split("\n", 1)[0]:
        return pd.DataFrame()
    sep = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
    raw = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    headers = {c.strip().lower(): c for c in raw.columns}
    out = pd.DataFrame(index=raw.index)
    for key, prefix in FI_COLS.items():
        col = next((orig for low, orig in headers.items() if low.startswith(prefix)), None)
        if key == "volume":
            col = next((orig for low, orig in headers.items() if low == "volym"), col)
        out[key] = raw[col] if col else ""
    if out["issuer"].eq("").all():
        return pd.DataFrame()
    out["date"] = pd.to_datetime(out["date"].str[:10], errors="coerce")
    out["published"] = pd.to_datetime(out["published"].str[:10], errors="coerce")
    out["volume"] = out["volume"].map(_parse_number)
    out["price"] = out["price"].map(_parse_number)
    out["value"] = out["volume"] * out["price"]
    kind = out["kind"].str.lower()
    out["side"] = "Övrigt"
    out.loc[kind.str.contains("förvärv|teckning|köp|acquisition|subscription", regex=True), "side"] = "Köp"
    out.loc[kind.str.contains("avyttring|försäljning|sälj|disposal|sale", regex=True), "side"] = "Sälj"
    if out["status"].str.len().gt(0).any():
        out = out[~out["status"].str.lower().str.contains("makulerad|historisk|revoked", regex=True)]
    return out


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _fi_export(issuer: str, since: str) -> pd.DataFrame:
    params = {"SearchFunctionType": "Insyn", "Utgivare": issuer, "PersonILedandeStällningNamn": "",
              "Transaktionsdatum.From": since, "Transaktionsdatum.To": "", "Publiceringsdatum.From": "",
              "Publiceringsdatum.To": "", "button": "export"}
    try:
        r = requests.get(FI_SEARCH, params=params, headers=UA, timeout=15)
        r.raise_for_status()
        return parse_fi_csv(r.content)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _yahoo_insider(ticker: str) -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).insider_transactions
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "date": pd.to_datetime(df.get("Start Date"), errors="coerce"),
        "person": df.get("Insider", ""), "role": df.get("Position", ""),
        "kind": df.get("Transaction", df.get("Text", "")).fillna(""),
        "volume": pd.to_numeric(df.get("Shares"), errors="coerce"),
        "value": pd.to_numeric(df.get("Value"), errors="coerce"), "currency": "USD",
    })
    text = (df.get("Text", pd.Series("", index=df.index)).fillna("") + " " + out["kind"]).str.lower()
    out["side"] = "Övrigt"
    out.loc[text.str.contains("purchase|buy", regex=True), "side"] = "Köp"
    out.loc[text.str.contains("sale|sell", regex=True), "side"] = "Sälj"
    out["price"] = out["value"] / out["volume"]
    return out


def insider(ticker: str, days: int = 180) -> pd.DataFrame:
    """Insynshandel senaste dagarna. Svenska bolag från FI, övriga från Yahoo."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    if ticker.upper().endswith(".ST"):
        core = core_name(ticker)
        df = _fi_export(core, since)
        if not df.empty:
            key = _issuer_key(core)
            names = df["issuer"].map(_issuer_key)
            exact = names == key
            # Exakt namn först ("AB Volvo"), annars namn som innehåller kärnnamnet ("Svenska Handelsbanken")
            df = df[exact] if exact.any() else df[names.str.contains(rf"\b{re.escape(key)}\b", regex=True)]
    else:
        df = _yahoo_insider(ticker)
    if df.empty:
        return df
    df = df[df["date"] >= pd.Timestamp(since)]
    return df.sort_values("date", ascending=False).reset_index(drop=True)


def _issuer_key(name: str) -> str:
    words = [w for w in _norm(name).split() if w not in {"ab", "publ", "aktiebolag", "aktiebolaget", "group", "holding",
                                                          "ltd", "plc", "oyj", "asa", "as", "inc", "corp", "the"}]
    return " ".join(words)


def insider_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"buys": 0, "sells": 0, "net": 0.0, "signal": "Ingen insynshandel", "tone": "neu"}
    b, s = df[df["side"] == "Köp"], df[df["side"] == "Sälj"]
    net = float(b["value"].sum(skipna=True) - s["value"].sum(skipna=True))
    if len(b) and not len(s):
        sig, tone = "🟢 Insiders köper", "pos"
    elif len(s) and not len(b):
        sig, tone = "🔴 Insiders säljer", "neg"
    elif net > 0:
        sig, tone = "🟢 Mer köp än sälj", "pos"
    elif net < 0:
        sig, tone = "🟠 Mer sälj än köp", "neg"
    else:
        sig, tone = "⚪ Blandat", "neu"
    return {"buys": len(b), "sells": len(s), "net": net, "signal": sig, "tone": tone}
