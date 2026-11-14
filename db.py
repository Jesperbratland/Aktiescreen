"""SQLite-lagring av konton och transaktioner."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "data" / "portfolio.db"

TYPES = ["KÖP", "SÄLJ", "UTDELNING", "JUSTERING"]  # JUSTERING = split/flytt, ändrar antal utan pengar
CURRENCIES = ["SEK", "USD", "EUR", "NOK", "DKK", "GBP", "CAD", "CHF"]
COLUMNS = ["id", "date", "account", "ticker", "type", "quantity", "price", "fee", "currency", "fx_rate", "note"]

ACCOUNT_TYPES = {
    "ISK": "ISK – Investeringssparkonto",
    "KF": "KF – Kapitalförsäkring",
    "AF": "AF – Aktie- och fondkonto (depå)",
}
ACCOUNT_COLUMNS = ["name", "type", "broker", "courtage_class", "custom_pct", "custom_min", "cash"]
DEFAULT_ACCOUNT = "Mitt ISK"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT    NOT NULL,              -- YYYY-MM-DD
    account   TEXT    NOT NULL DEFAULT 'Mitt ISK',
    ticker    TEXT    NOT NULL,              -- Yahoo-ticker, t.ex. VOLV-B.ST
    type      TEXT    NOT NULL,              -- KÖP / SÄLJ / UTDELNING
    quantity  REAL    NOT NULL,              -- antal aktier
    price     REAL    NOT NULL,              -- kurs (eller utdelning/aktie) i aktiens valuta
    fee       REAL    NOT NULL DEFAULT 0,    -- courtage / valutaväxling / källskatt i SEK
    currency  TEXT    NOT NULL DEFAULT 'SEK',
    fx_rate   REAL    NOT NULL DEFAULT 1,    -- SEK per 1 enhet valuta vid affären
    note      TEXT
);
CREATE TABLE IF NOT EXISTS accounts (
    name            TEXT PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'ISK',      -- ISK / KF / AF
    broker          TEXT NOT NULL DEFAULT 'Avanza',   -- Avanza / Nordnet / Annan
    courtage_class  TEXT NOT NULL DEFAULT 'Mini',
    custom_pct      REAL NOT NULL DEFAULT 0,          -- egen courtagesats i %, för 'Annan'
    custom_min      REAL NOT NULL DEFAULT 0,          -- eget minimicourtage i kr
    cash            REAL NOT NULL DEFAULT 0           -- pengar tillgängliga för köp (SEK)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS cash_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date     TEXT NOT NULL,
    account  TEXT NOT NULL,
    kind     TEXT NOT NULL,     -- INSÄTTNING / UTTAG / SALDO / KÖP / SÄLJ / UTDELNING
    amount   REAL NOT NULL,     -- + in på kontot, − ut från kontot
    balance  REAL NOT NULL,     -- saldo efter händelsen
    note     TEXT
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # Migrering: äldre databaser saknar kolumnen account
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    if "account" not in cols:
        conn.execute(f"ALTER TABLE transactions ADD COLUMN account TEXT NOT NULL DEFAULT '{DEFAULT_ACCOUNT}'")
    acols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)")]
    if "cash" not in acols:
        conn.execute("ALTER TABLE accounts ADD COLUMN cash REAL NOT NULL DEFAULT 0")
    if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
        conn.execute("INSERT INTO accounts (name, type, broker, courtage_class) VALUES (?, 'ISK', 'Avanza', 'Mini')",
                     (DEFAULT_ACCOUNT,))
    conn.commit()
    return conn


# ---------- Konton ----------
def load_accounts() -> pd.DataFrame:
    with _conn() as conn:
        return pd.read_sql_query(f"SELECT {', '.join(ACCOUNT_COLUMNS)} FROM accounts ORDER BY rowid", conn)


def account_names() -> list[str]:
    return load_accounts()["name"].tolist()


def save_accounts(df: pd.DataFrame) -> None:
    df = df.copy()
    if "cash" not in df:
        df["cash"] = 0.0
    df = df[ACCOUNT_COLUMNS]
    df["custom_pct"] = df["custom_pct"].fillna(0.0)
    df["custom_min"] = df["custom_min"].fillna(0.0)
    df["cash"] = df["cash"].fillna(0.0)
    with _conn() as conn:
        conn.execute("DELETE FROM accounts")
        conn.executemany(f"INSERT INTO accounts ({', '.join(ACCOUNT_COLUMNS)}) VALUES (?,?,?,?,?,?,?)",
                         list(df.itertuples(index=False, name=None)))


def rename_account(old: str, new: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE accounts SET name = ? WHERE name = ?", (new, old))
        conn.execute("UPDATE transactions SET account = ? WHERE account = ?", (new, old))
        conn.execute("UPDATE cash_log SET account = ? WHERE account = ?", (new, old))


# ---------- Pengar tillgängliga för köp ----------
def get_cash() -> dict[str, float]:
    with _conn() as conn:
        return {n: float(c) for n, c in conn.execute("SELECT name, cash FROM accounts")}


def change_cash(account: str, amount: float, kind: str, note: str = "", date: str | None = None) -> float:
    """Ändrar saldot med amount (+ in, − ut). kind='SALDO' sätter saldot till amount. Returnerar nytt saldo."""
    import datetime as _dt
    date = date or _dt.date.today().isoformat()
    with _conn() as conn:
        row = conn.execute("SELECT cash FROM accounts WHERE name = ?", (account,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO accounts (name) VALUES (?)", (account,))
            row = (0.0,)
        old = float(row[0])
        new = float(amount) if kind == "SALDO" else old + float(amount)
        conn.execute("UPDATE accounts SET cash = ? WHERE name = ?", (round(new, 2), account))
        conn.execute("INSERT INTO cash_log (date, account, kind, amount, balance, note) VALUES (?,?,?,?,?,?)",
                     (date, account, kind, round(new - old, 2), round(new, 2), note))
    return new


def load_cash_log() -> pd.DataFrame:
    with _conn() as conn:
        return pd.read_sql_query("SELECT date, account, kind, amount, balance, note FROM cash_log "
                                 "ORDER BY date DESC, id DESC", conn)


# ---------- Transaktioner ----------
def load_transactions() -> pd.DataFrame:
    with _conn() as conn:
        df = pd.read_sql_query(f"SELECT {', '.join(COLUMNS)} FROM transactions ORDER BY date, id", conn)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df["note"] = df["note"].fillna("")
    return df


def add_transaction(date: str, ticker: str, type_: str, quantity: float, price: float,
                    fee: float, currency: str, fx_rate: float, note: str = "",
                    account: str = DEFAULT_ACCOUNT) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO transactions (date, account, ticker, type, quantity, price, fee, currency, fx_rate, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (date, account, ticker.strip().upper(), type_, float(quantity), float(price), float(fee),
             currency, float(fx_rate), note),
        )


def replace_all(df: pd.DataFrame) -> None:
    """Ersätter alla transaktioner (används av redigeringsvyn och importer)."""
    df = df.copy()
    if "account" not in df:
        df["account"] = DEFAULT_ACCOUNT
    df["account"] = df["account"].fillna(DEFAULT_ACCOUNT).replace("", DEFAULT_ACCOUNT)
    rows = df[[c for c in COLUMNS if c != "id"]].itertuples(index=False, name=None)
    with _conn() as conn:
        conn.execute("DELETE FROM transactions")
        conn.executemany(
            "INSERT INTO transactions (date, account, ticker, type, quantity, price, fee, currency, fx_rate, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            list(rows),
        )
        # Se till att alla konton som används finns
        existing = {r[0] for r in conn.execute("SELECT name FROM accounts")}
        for acc in sorted(set(df["account"]) - existing):
            conn.execute("INSERT INTO accounts (name) VALUES (?)", (acc,))


def delete_demo() -> int:
    """Tar bort exempeltransaktionerna. Returnerar antal borttagna."""
    with _conn() as conn:
        return conn.execute("DELETE FROM transactions WHERE note LIKE 'Demo%'").rowcount


def delete_holding(account: str, ticker: str) -> None:
    """Tar bort alla transaktioner för en aktie på ett konto."""
    with _conn() as conn:
        conn.execute("DELETE FROM transactions WHERE account = ? AND ticker = ?", (account, ticker))


def get_setting(key: str, default: str | None = None) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str | None) -> None:
    with _conn() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


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
        ("2024-04-05", "VOLV-B.ST", "UTDELNING", 100, 18.0, 0, "SEK", 1.0, "Demo – utdelning"),
        ("2024-05-02", "INVE-B.ST", "UTDELNING", 50, 4.8, 0, "SEK", 1.0, "Demo – utdelning"),
        ("2024-06-14", "VOLV-B.ST", "SÄLJ", 40, 280.0, 49, "SEK", 1.0, "Demo – vinsthemtagning"),
        ("2024-09-03", "EVO.ST", "KÖP", 15, 1050.0, 49, "SEK", 1.0, "Demo"),
        ("2025-02-20", "AAPL", "KÖP", 10, 245.0, 49, "USD", 10.70, "Demo"),
    ], columns=["date", "ticker", "type", "quantity", "price", "fee", "currency", "fx_rate", "note"])
    demo["account"] = DEFAULT_ACCOUNT
    replace_all(demo)
