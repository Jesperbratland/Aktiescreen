"""Tekniska indikatorer, nyckeltal och regelbaserade signaler."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ---------- Indikatorer ----------
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(s, fast) - ema(s, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(s, n)
    sd = s.rolling(n, min_periods=n).std()
    return mid + k * sd, mid, mid - k * sd


# ---------- Nyckeltal ----------
def perf_stats(close: pd.Series, rf: float = 0.02) -> dict:
    close = close.dropna()
    if len(close) < 3:
        return {}
    r = close.pct_change().dropna()
    years = (close.index[-1] - close.index[0]).days / 365.25
    cagr = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1 if years > 0.25 else math.nan
    vol = r.std() * math.sqrt(TRADING_DAYS)
    sharpe = (r.mean() * TRADING_DAYS - rf) / vol if vol > 0 else math.nan
    downside = r[r < 0].std() * math.sqrt(TRADING_DAYS)
    sortino = (r.mean() * TRADING_DAYS - rf) / downside if downside > 0 else math.nan
    dd = close / close.cummax() - 1
    return {
        "Total avkastning": close.iloc[-1] / close.iloc[0] - 1,
        "CAGR": cagr,
        "Volatilitet (år)": vol,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Max drawdown": dd.min(),
        "Nuvarande drawdown": dd.iloc[-1],
    }


def drawdown(close: pd.Series) -> pd.Series:
    return close / close.cummax() - 1


def period_returns(close: pd.Series) -> dict:
    close = close.dropna()
    if close.empty:
        return {}
    last_date, last = close.index[-1], close.iloc[-1]
    offsets = {
        "1 v": pd.DateOffset(weeks=1), "1 m": pd.DateOffset(months=1),
        "3 m": pd.DateOffset(months=3), "6 m": pd.DateOffset(months=6),
        "1 år": pd.DateOffset(years=1), "3 år": pd.DateOffset(years=3),
        "5 år": pd.DateOffset(years=5),
    }
    out = {}
    for label, off in offsets.items():
        past = close[close.index <= last_date - off]
        out[label] = last / past.iloc[-1] - 1 if not past.empty else math.nan
    ytd = close[close.index < pd.Timestamp(year=last_date.year, month=1, day=1)]
    out["i år"] = last / ytd.iloc[-1] - 1 if not ytd.empty else math.nan
    return out


def beta(asset: pd.Series, bench: pd.Series) -> float:
    df = pd.concat([asset.pct_change(), bench.pct_change()], axis=1).dropna()
    if len(df) < 30 or df.iloc[:, 1].var() == 0:
        return math.nan
    return df.iloc[:, 0].cov(df.iloc[:, 1]) / df.iloc[:, 1].var()


# ---------- Signaler ----------
def _crossed_above(a: pd.Series, b: pd.Series, lookback: int) -> bool:
    """Har a korsat upp över b inom de senaste `lookback` dagarna (och ligger kvar över)?"""
    diff = (a - b).dropna().tail(lookback + 1)
    if len(diff) < 2:
        return False
    crosses = (diff > 0) & (diff.shift(1) <= 0)
    return bool(crosses.any() and diff.iloc[-1] > 0)


def _crossed_below(a: pd.Series, b: pd.Series, lookback: int) -> bool:
    return _crossed_above(b, a, lookback)


def technical_signals(df: pd.DataFrame) -> list[dict]:
    """Regelbaserade signaler. tone: pos / neg / neu."""
    close = df["Close"].dropna()
    if len(close) < 60:
        return [{"signal": "För lite historik", "detail": "Minst 60 handelsdagar behövs.", "tone": "neu"}]
    sig: list[dict] = []
    last = close.iloc[-1]
    s50, s200 = sma(close, 50), sma(close, 200)
    r = rsi(close).iloc[-1]

    if not math.isnan(s200.iloc[-1]):
        if last > s200.iloc[-1]:
            sig.append({"signal": "Långsiktig upptrend",
                        "detail": f"Kursen ligger {(last / s200.iloc[-1] - 1) * 100:.1f} % över MA200.", "tone": "pos"})
        else:
            sig.append({"signal": "Långsiktig nedtrend",
                        "detail": f"Kursen ligger {(1 - last / s200.iloc[-1]) * 100:.1f} % under MA200.", "tone": "neg"})
        if _crossed_above(s50, s200, 15):
            sig.append({"signal": "Golden cross", "detail": "MA50 har nyligen korsat över MA200.", "tone": "pos"})
        if _crossed_below(s50, s200, 15):
            sig.append({"signal": "Death cross", "detail": "MA50 har nyligen korsat under MA200.", "tone": "neg"})

    if not math.isnan(r):
        if r < 30:
            sig.append({"signal": f"Översåld (RSI {r:.0f})",
                        "detail": "RSI under 30 – kan indikera överdriven nedgång.", "tone": "pos"})
        elif r > 70:
            sig.append({"signal": f"Överköpt (RSI {r:.0f})",
                        "detail": "RSI över 70 – risk för rekyl.", "tone": "neg"})
        else:
            sig.append({"signal": f"Neutral RSI ({r:.0f})", "detail": "RSI mellan 30 och 70.", "tone": "neu"})

    line, signal_line, _ = macd(close)
    if _crossed_above(line, signal_line, 5):
        sig.append({"signal": "MACD köpsignal", "detail": "MACD har korsat över signallinjen senaste veckan.", "tone": "pos"})
    elif _crossed_below(line, signal_line, 5):
        sig.append({"signal": "MACD säljsignal", "detail": "MACD har korsat under signallinjen senaste veckan.", "tone": "neg"})

    year = close.tail(TRADING_DAYS)
    hi, lo = year.max(), year.min()
    if last >= hi * 0.97:
        sig.append({"signal": "Nära 52-veckorshögsta", "detail": "Stark relativ styrka/momentum.", "tone": "pos"})
    elif last <= lo * 1.03:
        sig.append({"signal": "Nära 52-veckorslägsta", "detail": "Svag trend – undersök orsaken.", "tone": "neg"})

    upper, _, lower = bollinger(close)
    if not math.isnan(lower.iloc[-1]) and last < lower.iloc[-1]:
        sig.append({"signal": "Under nedre Bollingerband", "detail": "Ovanligt stor kortsiktig nedgång.", "tone": "neu"})
    elif not math.isnan(upper.iloc[-1]) and last > upper.iloc[-1]:
        sig.append({"signal": "Över övre Bollingerband", "detail": "Ovanligt stor kortsiktig uppgång.", "tone": "neu"})
    return sig


def signal_score(signals: list[dict]) -> int:
    """Enkel netto-poäng: +1 per positiv, −1 per negativ signal."""
    return sum(1 if s["tone"] == "pos" else -1 if s["tone"] == "neg" else 0 for s in signals)
