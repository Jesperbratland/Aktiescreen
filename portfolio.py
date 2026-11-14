"""Portföljberäkningar: innehav, GAV, realiserat resultat, historik och TWR.

Genomsnittsmetoden (GAV) används – samma princip som Skatteverket.
Alla belopp räknas om till SEK med valutakursen vid respektive affär.
Courtage/källskatt (fee) anges alltid i SEK.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POSITION_COLS = ["ticker", "currency", "qty", "cost_sek", "cost_local", "realized_sek",
                 "dividends_sek", "fees_sek", "first_date"]


def _fx(r) -> float:
    return float(r.fx_rate) if r.fx_rate and r.fx_rate > 0 else 1.0


def validate(tx: pd.DataFrame) -> list[str]:
    """Returnerar en lista med fel (tom lista = OK)."""
    errors: list[str] = []
    if tx.empty:
        return errors
    from db import TYPES
    for i, r in tx.reset_index(drop=True).iterrows():
        row = i + 1
        if not str(r["ticker"]).strip():
            errors.append(f"Rad {row}: ticker saknas")
        if r["type"] not in TYPES:
            errors.append(f"Rad {row}: okänd typ '{r['type']}'")
        if pd.isna(pd.to_datetime(r["date"], errors="coerce")):
            errors.append(f"Rad {row}: ogiltigt datum '{r['date']}'")
        if r["type"] == "JUSTERING":
            if not (pd.notna(r["quantity"]) and r["quantity"] != 0):
                errors.append(f"Rad {row}: antal får inte vara 0 för justering")
        elif not (pd.notna(r["quantity"]) and r["quantity"] > 0):
            errors.append(f"Rad {row}: antal måste vara > 0")
        if not (pd.notna(r["price"]) and r["price"] >= 0):
            errors.append(f"Rad {row}: kurs måste vara ≥ 0")
    if errors:
        return errors
    holdings: dict[tuple, float] = {}
    srt = _with_account(tx).assign(_d=pd.to_datetime(tx["date"])).sort_values(["_d"], kind="stable")
    for r in srt.itertuples(index=False):
        key = (r.account, r.ticker)
        h = holdings.get(key, 0.0)
        if r.type == "KÖP":
            holdings[key] = h + r.quantity
        elif r.type == "SÄLJ":
            if r.quantity > h + 1e-9:
                errors.append(f"{r.date} {r.ticker} ({r.account}): säljer {r.quantity:g} men innehar bara {h:g}")
            holdings[key] = max(h - r.quantity, 0.0)
        elif r.type == "JUSTERING":
            holdings[key] = max(h + r.quantity, 0.0)
    return errors


def is_oversell_error(msg: str) -> bool:
    return "men innehar bara" in msg


def _with_account(tx: pd.DataFrame) -> pd.DataFrame:
    if "account" not in tx:
        return tx.assign(account="Mitt ISK")
    return tx.assign(account=tx["account"].fillna("Mitt ISK"))


def _book(tx: pd.DataFrame):
    """Går igenom transaktionerna per (konto, ticker) med genomsnittsmetoden.

    Returnerar (positioner per konto/ticker, lista med realiserade försäljningar).
    """
    tx = _with_account(tx)
    if "id" not in tx:
        tx = tx.assign(id=range(len(tx)))
    tx = tx.assign(dt_=pd.to_datetime(tx["date"])).sort_values(["dt_", "id"], kind="stable")
    book: dict[tuple, dict] = {}
    events: list[dict] = []
    for r in tx.itertuples(index=False):
        b = book.setdefault((r.account, r.ticker), {
            "account": r.account, "ticker": r.ticker, "currency": r.currency, "qty": 0.0, "cost_sek": 0.0,
            "cost_local": 0.0, "realized_sek": 0.0, "dividends_sek": 0.0, "fees_sek": 0.0,
            "first_date": r.date,
        })
        fx = _fx(r)
        fee = float(r.fee or 0.0)
        b["fees_sek"] += fee
        if r.type == "KÖP":
            b["cost_sek"] += r.quantity * r.price * fx + fee
            b["cost_local"] += r.quantity * r.price + fee / fx
            b["qty"] += r.quantity
        elif r.type == "SÄLJ":
            q = min(r.quantity, b["qty"])
            share = q / b["qty"] if b["qty"] > 0 else 0.0
            basis_sek = b["cost_sek"] * share
            proceeds = r.quantity * r.price * fx - fee
            b["realized_sek"] += proceeds - basis_sek
            events.append({"date": r.dt_, "account": r.account, "ticker": r.ticker, "quantity": r.quantity,
                           "proceeds_sek": proceeds, "basis_sek": basis_sek, "gain_sek": proceeds - basis_sek})
            b["cost_sek"] -= basis_sek
            b["cost_local"] -= b["cost_local"] * share
            b["qty"] -= q
            if b["qty"] < 1e-9:
                b["qty"] = b["cost_sek"] = b["cost_local"] = 0.0
        elif r.type == "UTDELNING":
            b["dividends_sek"] += r.quantity * r.price * fx - fee
        elif r.type == "JUSTERING":
            # Split/sammanläggning: antalet ändras men anskaffningsvärdet är detsamma.
            # Flytt in: aktier läggs till (med kurs som anskaffningspris om angiven).
            # Flytt ut: anskaffningsvärdet följer med proportionellt, ingen vinst/förlust.
            is_split = "split" in str(r.note).lower()
            if r.quantity > 0:
                if not is_split:
                    b["cost_sek"] += r.quantity * r.price * fx + fee
                    b["cost_local"] += r.quantity * r.price + fee / fx
                b["qty"] += r.quantity
            else:
                q = min(-r.quantity, b["qty"])
                if not is_split and b["qty"] > 0:
                    share = q / b["qty"]
                    b["cost_sek"] -= b["cost_sek"] * share
                    b["cost_local"] -= b["cost_local"] * share
                b["qty"] -= q
                if b["qty"] < 1e-9:
                    b["qty"] = b["cost_sek"] = b["cost_local"] = 0.0
    return list(book.values()), events


def compute_positions(tx: pd.DataFrame, by_account: bool = False) -> pd.DataFrame:
    """En rad per ticker (även stängda innehav). by_account=True ger en rad per konto och ticker."""
    cols = (["account"] if by_account else []) + POSITION_COLS
    if tx.empty:
        return pd.DataFrame(columns=cols)
    rows, _ = _book(tx)
    df = pd.DataFrame(rows)
    if by_account:
        return df[cols]
    agg = df.groupby("ticker", as_index=False, sort=False).agg(
        currency=("currency", "first"), qty=("qty", "sum"), cost_sek=("cost_sek", "sum"),
        cost_local=("cost_local", "sum"), realized_sek=("realized_sek", "sum"),
        dividends_sek=("dividends_sek", "sum"), fees_sek=("fees_sek", "sum"), first_date=("first_date", "min"))
    return agg[POSITION_COLS]


def realized_events(tx: pd.DataFrame) -> pd.DataFrame:
    """En rad per försäljning med vinst/förlust enligt genomsnittsmetoden (underlag för K4)."""
    cols = ["date", "account", "ticker", "quantity", "proceeds_sek", "basis_sek", "gain_sek"]
    if tx.empty:
        return pd.DataFrame(columns=cols)
    _, events = _book(tx)
    return pd.DataFrame(events, columns=cols)


def enrich_positions(pos: pd.DataFrame, quotes: pd.DataFrame, fx_now: dict[str, float]) -> pd.DataFrame:
    """Lägger till marknadsvärde, orealiserat resultat, vikt m.m. för öppna innehav."""
    df = pos[pos["qty"] > 0].copy()
    if df.empty:
        return df
    df["price"] = df["ticker"].map(quotes["last"])
    df["prev"] = df["ticker"].map(quotes["prev"])
    df["fx"] = df["currency"].map(fx_now).fillna(1.0)
    df["gav_local"] = df["cost_local"] / df["qty"]
    df["gav_sek"] = df["cost_sek"] / df["qty"]
    df["value_sek"] = df["qty"] * df["price"] * df["fx"]
    df["unrealized_sek"] = df["value_sek"] - df["cost_sek"]
    df["unrealized_pct"] = df["unrealized_sek"] / df["cost_sek"]
    df["day_change_sek"] = df["qty"] * (df["price"] - df["prev"]) * df["fx"]
    df["day_change_pct"] = df["price"] / df["prev"] - 1
    total = df["value_sek"].sum()
    df["weight"] = df["value_sek"] / total if total else np.nan
    return df.sort_values("value_sek", ascending=False)


def _to_business_days(s: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """Flyttar händelser på helgdagar till nästa vardag i idx."""
    if s.empty:
        return pd.Series(0.0, index=idx)
    pos = np.clip(idx.searchsorted(s.index), 0, len(idx) - 1)
    return pd.Series(s.values, index=idx[pos]).groupby(level=0).sum().reindex(idx, fill_value=0.0)


def portfolio_history(tx: pd.DataFrame, closes: pd.DataFrame, fx_hist: pd.DataFrame) -> pd.DataFrame:
    """Daglig serie med marknadsvärde, nettoinvesterat och tidsviktad avkastning (TWR).

    closes: stängningskurser (kolumn per ticker), fx_hist: SEK per valuta (kolumn per valuta).
    """
    if tx.empty or closes.empty:
        return pd.DataFrame()
    tx = tx.copy()
    tx["date"] = pd.to_datetime(tx["date"])
    tx["fx"] = tx["fx_rate"].where(tx["fx_rate"] > 0, 1.0)
    # Effektiv antalsförändring per rad – sälj/flytt ut kan aldrig ta antalet under noll
    tx = _with_account(tx).sort_values("date", kind="stable")
    held: dict[tuple, float] = {}
    eff = []
    for r in tx.itertuples(index=False):
        key = (r.account, r.ticker)
        h = held.get(key, 0.0)
        if r.type == "KÖP":
            d = r.quantity
        elif r.type == "SÄLJ":
            d = -min(r.quantity, h)
        elif r.type == "JUSTERING":
            d = r.quantity if r.quantity > 0 else -min(-r.quantity, h)
        else:
            d = 0.0
        held[key] = h + d
        eff.append(d)
    tx["signed_qty"] = eff

    idx = pd.bdate_range(tx["date"].min(), pd.Timestamp.today().normalize())
    if len(idx) < 2:
        return pd.DataFrame()

    flows = (tx.pivot_table(index="date", columns="ticker", values="signed_qty", aggfunc="sum")
             .fillna(0.0).cumsum())
    full = flows.index.union(idx)
    holdings = flows.reindex(full).ffill().fillna(0.0).reindex(idx)

    tickers = [t for t in holdings.columns if t in closes.columns]
    prices = closes[tickers].reindex(closes.index.union(idx)).ffill().reindex(idx)

    cur_map = tx.groupby("ticker")["currency"].first()
    fx = pd.DataFrame(index=idx)
    for t in tickers:
        c = cur_map.get(t, "SEK")
        if c == "SEK" or c not in fx_hist.columns:
            fx[t] = 1.0
        else:
            fx[t] = fx_hist[c].reindex(fx_hist.index.union(idx)).ffill().bfill().reindex(idx)

    value = (holdings[tickers] * prices * fx).sum(axis=1, min_count=1).fillna(0.0)

    # Kassaflöden in i portföljen (köp +, sälj −) och utdelningar ut
    buy = tx["type"] == "KÖP"
    sell = tx["type"] == "SÄLJ"
    div = tx["type"] == "UTDELNING"
    tx["cash_in"] = 0.0
    tx.loc[buy, "cash_in"] = tx.loc[buy, "quantity"] * tx.loc[buy, "price"] * tx.loc[buy, "fx"] + tx.loc[buy, "fee"]
    tx.loc[sell, "cash_in"] = -(tx.loc[sell, "quantity"] * tx.loc[sell, "price"] * tx.loc[sell, "fx"] - tx.loc[sell, "fee"])
    tx["dividend"] = 0.0
    tx.loc[div, "dividend"] = tx.loc[div, "quantity"] * tx.loc[div, "price"] * tx.loc[div, "fx"] - tx.loc[div, "fee"]

    cf = _to_business_days(tx.groupby("date")["cash_in"].sum(), idx)
    dv = _to_business_days(tx.groupby("date")["dividend"].sum(), idx)

    prev = value.shift(1)
    r = ((value + dv - cf) / prev - 1).where(prev > 0, 0.0)
    r = r.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    return pd.DataFrame({
        "value": value,
        "invested": cf.cumsum(),
        "dividends": dv.cumsum(),
        "cashflow": cf,
        "daily_return": r,
        "twr_index": (1 + r).cumprod() * 100,
    })


def realized_by_ticker(pos: pd.DataFrame) -> pd.DataFrame:
    df = pos[["ticker", "realized_sek", "dividends_sek", "fees_sek"]].copy()
    df = df[(df["realized_sek"].abs() > 0) | (df["dividends_sek"].abs() > 0)]
    return df.sort_values("realized_sek", ascending=False)
