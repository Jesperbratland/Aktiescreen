"""SQLite-lagring av transaktioner."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "data" / "portfolio.db"

TYPES = ["KÖP", "SÄLJ", "UTDELNING"]
CURRENCIES = ["SEK", "USD", "EUR", "NOK", "DKK", "GBP", "CAD", "CHF"]
COLUMNS = ["id", "date", "ticker", "type", "quantity", "price", "fee", "currency", "fx_rate", "note"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT    NOT NULL,              -- YYYY-MM-DD
    ticker    TEXT    NOT NULL,              -- Yahoo-ticker, t.ex. VOLV-B.ST
    type      TEXT    NOT NULL,              -- KÖP / SÄLJ / UTDELNING
    quantity  REAL    NOT NULL,              -- antal aktier
    price     REAL    NOT NULL,              -- kurs (eller utdelning/aktie) i aktiens valuta
    fee       REAL    NOT NULL DEFAULT 0,    -- courtage / källskatt i SEK
    currency  TEXT    NOT NULL DEFAULT 'SEK',
    fx_rate   REAL    NOT NULL DEFAULT 1,    -- SEK per 1 enhet valuta vid affären
    note      TEXT
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def load_transactions() -> pd.DataFrame:
    with _conn() as conn:
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date, id", conn)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df["note"] = df["note"].fillna("")
    return df


def add_transaction(date: str, ticker: str, type_: str, quantity: float, price: float,
                    fee: float, currency: str, fx_rate: float, note: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO transactions (date, ticker, type, quantity, price, fee, currency, fx_rate, note)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (date, ticker.strip().upper(), type_, float(quantity), float(price), float(fee),
             currency, float(fx_rate), note),
        )


def replace_all(df: pd.DataFrame) -> None:
    """Ersätter hela tabellen (används av redigeringsvyn och CSV-import)."""
    rows = df[[c for c in COLUMNS if c != "id"]].itertuples(index=False, name=None)
    with _conn() as conn:
        conn.execute("DELETE FROM transactions")
        conn.executemany(
            "INSERT INTO transactions (date, ticker, type, quantity, price, fee, currency, fx_rate, note)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            list(rows),
        )


def delete_all() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM transactions")


def load_demo() -> None:
    """Exempelportfölj så att man kan testa appen direkt."""
    demo = pd.DataFrame([
        ("2023-02-15", "VOLV-B.ST", "KÖP", 100, 215.0, 69, "SEK", 1.0, "Demo"),
        ("2023-03-10", "INVE-B.ST", "KÖP", 50, 205.0, 39, "SEK", 1.0, "Demo"),
        ("2023-05-22", "AAPL", "KÖP", 20, 174.0, 49, "USD", 10.45, "Demo"),
        ("2023-08-01", "MSFT", "KÖP", 10, 336.0, 49, "USD", 10.55, "Demo"),
        ("2023-10-12", "ATCO-A.ST", "KÖP", 80, 142.0, 39, "SEK", 1.0, "Demo"),
        ("2024-01-18", "NOVO-B.CO", "KÖP", 15, 720.0, 49, "DKK", 1.52, "Demo"),
        ("2024-04-05", "VOLV-B.ST", "UTDELNING", 100, 18.0, 0, "SEK", 1.0, "Ord + extra"),
        ("2024-05-02", "INVE-B.ST", "UTDELNING", 50, 4.8, 0, "SEK", 1.0, ""),
        ("2024-06-14", "VOLV-B.ST", "SÄLJ", 40, 280.0, 49, "SEK", 1.0, "Vinsthemtagning"),
        ("2024-09-03", "EVO.ST", "KÖP", 15, 1050.0, 49, "SEK", 1.0, "Demo"),
        ("2025-02-20", "AAPL", "KÖP", 10, 245.0, 49, "USD", 10.70, "Demo"),
    ], columns=[c for c in COLUMNS if c != "id"])
    replace_all(demo)
