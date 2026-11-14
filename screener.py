"""Screener: tekniska + fundamentala nyckeltal och en sammanvägd poäng."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import analysis, market

# Urval – justera fritt. Yahoo-tickers (.ST = Stockholm, .CO = Köpenhamn, .OL = Oslo, .HE = Helsingfors)
UNIVERSES: dict[str, list[str]] = {
    "Sverige – storbolag (urval)": [
        "ABB.ST", "ADDT-B.ST", "ALFA.ST", "ASSA-B.ST", "ATCO-A.ST", "AZN.ST", "BOL.ST",
        "EPI-A.ST", "EQT.ST", "ERIC-B.ST", "ESSITY-B.ST", "EVO.ST", "GETI-B.ST", "HEXA-B.ST",
        "HM-B.ST", "INDU-C.ST", "INVE-B.ST", "LIFCO-B.ST", "NDA-SE.ST", "NIBE-B.ST", "SAAB-B.ST",
        "SAND.ST", "SCA-B.ST", "SEB-A.ST", "SHB-A.ST", "SKF-B.ST", "SWED-A.ST", "TEL2-B.ST",
        "TELIA.ST", "VOLV-B.ST",
    ],
    "Sverige – medelstora (urval)": [
        "AAK.ST", "AXFO.ST", "BEIJ-B.ST", "BILL.ST", "CAST.ST", "ELUX-B.ST", "FABG.ST",
        "HUSQ-B.ST", "INDT.ST", "INTRUM.ST", "LAGR-B.ST", "LATO-B.ST", "MYCR.ST", "NOLA-B.ST",
        "SAGA-B.ST", "SECU-B.ST", "SINCH.ST", "SWEC-B.ST", "THULE.ST", "TREL-B.ST", "VITR.ST",
        "WALL-B.ST", "WIHL.ST",
    ],
    "Norden – storbolag (urval)": [
        "NOVO-B.CO", "DSV.CO", "MAERSK-B.CO", "ORSTED.CO", "VWS.CO", "CARL-B.CO",
        "EQNR.OL", "DNB.OL", "MOWI.OL", "TEL.OL", "NOKIA.HE", "NESTE.HE", "SAMPO.HE", "KNEBV.HE",
    ],
    "USA – megacap (urval)": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "JPM", "V",
        "UNH", "XOM", "JNJ", "PG", "MA", "HD", "COST", "AVGO", "LLY", "KO", "PEP", "NFLX",
        "ADBE", "CRM", "AMD",
    ],
}


def technical_snapshot(closes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t in closes.columns:
        s = closes[t].dropna()
        if len(s) < 60:
            continue
        last = s.iloc[-1]
        s200 = analysis.sma(s, 200).iloc[-1]
        s50 = analysis.sma(s, 50).iloc[-1]
        year = s.tail(analysis.TRADING_DAYS)

        def ret(n):
            return last / s.iloc[-n - 1] - 1 if len(s) > n else math.nan

        rows.append({
            "ticker": t,
            "Kurs": last,
            "RSI": analysis.rsi(s).iloc[-1],
            "Över MA50": bool(last > s50) if not math.isnan(s50) else None,
            "Över MA200": bool(last > s200) if not math.isnan(s200) else None,
            "1 m": ret(21),
            "3 m": ret(63),
            "12 m": ret(252) if len(s) > 252 else last / s.iloc[0] - 1,
            "Volatilitet": s.pct_change().tail(252).std() * math.sqrt(252),
            "Från 52v-högsta": last / year.max() - 1,
        })
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()


def _num(info: dict, key: str) -> float:
    v = info.get(key)
    try:
        v = float(v)
        return v if math.isfinite(v) else math.nan
    except (TypeError, ValueError):
        return math.nan


def fundamentals(tickers: list[str], progress=None) -> pd.DataFrame:
    rows = []
    for i, t in enumerate(tickers):
        info = market.get_info(t)
        price = _num(info, "currentPrice")
        if math.isnan(price):
            price = _num(info, "regularMarketPrice")
        div_rate = _num(info, "dividendRate")
        if not math.isnan(div_rate) and not math.isnan(price) and price > 0:
            dy = div_rate / price
        else:
            dy = _num(info, "trailingAnnualDividendYield")
        rows.append({
            "ticker": t,
            "Namn": info.get("shortName") or info.get("longName") or t,
            "Sektor": info.get("sector") or "–",
            "Valuta": info.get("currency") or "",
            "Börsvärde": _num(info, "marketCap"),
            "P/E": _num(info, "trailingPE"),
            "Fwd P/E": _num(info, "forwardPE"),
            "P/B": _num(info, "priceToBook"),
            "EV/EBITDA": _num(info, "enterpriseToEbitda"),
            "Direktavk.": dy,
            "ROE": _num(info, "returnOnEquity"),
            "Vinstmarginal": _num(info, "profitMargins"),
            "Skuld/EK": _num(info, "debtToEquity"),
            "Vinsttillväxt": _num(info, "earningsGrowth"),
        })
        if progress:
            progress((i + 1) / len(tickers), t)
    return pd.DataFrame(rows).set_index("ticker")


def _rank(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
    return s.rank(pct=True, ascending=higher_is_better)


def add_scores(df: pd.DataFrame, w_value=1.0, w_quality=1.0, w_momentum=1.0, w_dividend=0.5) -> pd.DataFrame:
    """Percentilrankar inom urvalet → delpoäng 0–100 och en viktad totalpoäng."""
    df = df.copy()
    comps = {}
    if "P/E" in df:
        pe = df["P/E"].where(df["P/E"] > 0)
        pb = df["P/B"].where(df["P/B"] > 0)
        ev = df["EV/EBITDA"].where(df["EV/EBITDA"] > 0)
        comps["Värde"] = (pd.concat([_rank(pe, False), _rank(pb, False), _rank(ev, False)], axis=1).mean(axis=1), w_value)
        comps["Kvalitet"] = (pd.concat([_rank(df["ROE"]), _rank(df["Vinstmarginal"]),
                                        _rank(df["Skuld/EK"], False)], axis=1).mean(axis=1), w_quality)
        comps["Utdelning"] = (_rank(df["Direktavk."]), w_dividend)
    if "12 m" in df:
        trend = df["Över MA200"].map({True: 1.0, False: 0.0})
        comps["Momentum"] = (pd.concat([_rank(df["12 m"]), _rank(df["3 m"]), trend], axis=1).mean(axis=1), w_momentum)

    num = pd.Series(0.0, index=df.index)
    den = pd.Series(0.0, index=df.index)
    for name, (score, w) in comps.items():
        df[name] = (score * 100).round(0)
        mask = score.notna()
        num[mask] += score[mask] * w
        den[mask] += w
    df["Poäng"] = (num / den.replace(0, np.nan) * 100).round(0)
    return df.sort_values("Poäng", ascending=False)


def run_screener(tickers: list[str], with_fundamentals: bool = True, progress=None) -> pd.DataFrame:
    tickers = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))
    closes = market.get_closes(tuple(tickers), period="2y")
    tech = technical_snapshot(closes)
    if tech.empty:
        return tech
    if with_fundamentals:
        fund = fundamentals(list(tech.index), progress=progress)
        df = fund.join(tech, how="right")
    else:
        df = tech
        df.insert(0, "Namn", df.index)
    return df
