"""Lagring av konton, transaktioner, bevakningar och inställningar.

Två lägen, väljs automatiskt:
  - DATABASE_URL i Streamlit Secrets (t.ex. gratis Postgres hos Neon) → permanent lagring i molnet.
  - Annars en lokal SQLite-fil (data/portfolio.db). På Streamlit Cloud töms den vid omstart.
Första gången molndatabasen används flyttas eventuell lokal data över automatiskt.
SQL skrivs med ?-platshållare och översätts till Postgres (%s) vid behov.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
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
WATCH_COLUMNS = ["ticker", "name", "added_date", "added_price", "buy_below", "sell_above", "note"]
DEFAULT_ACCOUNT = "Mitt ISK"

_TABLES = """
CREATE TABLE IF NOT EXISTS transactions (
    id        {serial},
    date      TEXT    NOT NULL,              -- YYYY-MM-DD
    account   TEXT    NOT NULL DEFAULT 'Mitt ISK',
    ticker    TEXT    NOT NULL,              -- Yahoo-ticker, t.ex. VOLV-B.ST
    type      TEXT    NOT NULL,              -- KÖP / SÄLJ / UTDELNING / JUSTERING
    quantity  {real}  NOT NULL,              -- antal aktier
    price     {real}  NOT NULL,              -- kurs (eller utdelning/aktie) i aktiens valuta
    fee       {real}  NOT NULL DEFAULT 0,    -- courtage / valutaväxling / källskatt i SEK
    currency  TEXT    NOT NULL DEFAULT 'SEK',
    fx_rate   {real}  NOT NULL DEFAULT 1,    -- SEK per 1 enhet valuta vid affären
    note      TEXT
);
CREATE TABLE IF NOT EXISTS accounts (
    name            TEXT PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'ISK',      -- ISK / KF / AF
    broker          TEXT NOT NULL DEFAULT 'Avanza',   -- Avanza / Nordnet / Annan
    courtage_class  TEXT NOT NULL DEFAULT 'Mini',
    custom_pct      {real} NOT NULL DEFAULT 0,        -- egen courtagesats i %, för 'Annan'
    custom_min      {real} NOT NULL DEFAULT 0,        -- eget minimicourtage i kr
    cash            {real} NOT NULL DEFAULT 0{ordcol} -- pengar för köp (SEK)
);
CREATE TABLE IF NOT EXISTS watchlist (
    ticker       TEXT PRIMARY KEY,
    name         TEXT,
    added_date   TEXT,
    added_price  {real},
    buy_below    {real},          -- larm: kursen har fallit till/under
    sell_above   {real},          -- larm: kursen har stigit till/över
    note         TEXT{ordcol}
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS cash_log (
    id       {serial},
    date     TEXT NOT NULL,
    account  TEXT NOT NULL,
    kind     TEXT NOT NULL,     -- INSÄTTNING / UTTAG / SALDO / KÖP / SÄLJ / UTDELNING
    amount   {real} NOT NULL,   -- + in på kontot, − ut från kontot
    balance  {real} NOT NULL,   -- saldo efter händelsen
    note     TEXT
);
"""
SQLITE_SCHEMA = _TABLES.format(serial="INTEGER PRIMARY KEY AUTOINCREMENT", real="REAL", ordcol="")
# Postgres saknar rowid – kolumnen ord håller ordningen som rader lades in i
PG_SCHEMA = _TABLES.format(serial="SERIAL PRIMARY KEY", real="DOUBLE PRECISION", ordcol=",\n    ord SERIAL")


# ---------------------------------------------------------------- anslutning
def database_url() -> str | None:
    try:
        import streamlit as st
        url = st.secrets.get("DATABASE_URL")
    except Exception:
        url = None
    return url or os.environ.get("DATABASE_URL") or None


def is_cloud() -> bool:
    return bool(database_url())


def _py(v):
    """numpy/pandas-värden -> vanliga Python-värden som databasen förstår."""
    if v is None:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _params(p) -> tuple:
    return tuple(_py(v) for v in p)


_pg_lock = threading.RLock()
_pg_state: dict = {"conn": None, "ready": False}


def _pg_connect():
    import psycopg2
    url = database_url()
    conn = psycopg2.connect(url, connect_timeout=20, keepalives=1, keepalives_idle=30)
    conn.autocommit = False
    return conn


def _pg_conn():
    """Återanvänder en anslutning; återansluter om databasen har somnat (Neon sover efter 5 min)."""
    import time
    conn = _pg_state["conn"]
    now = time.time()
    if conn is not None and not conn.closed and now - _pg_state.get("used", 0) < 60:
        _pg_state["used"] = now  # nyss använd – hoppa över kontrollen (snabbare)
        return conn
    _pg_state["used"] = now
    if conn is not None and not conn.closed:
        try:
            with conn.cursor() as c:
                c.execute("SELECT 1")
            conn.rollback()
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    conn = _pg_connect()
    _pg_state["conn"] = conn
    if not _pg_state["ready"]:
        with conn.cursor() as c:
            c.execute(PG_SCHEMA)
            _ensure_default_account(_Cur(c, True))
            _migrate_from_sqlite(_Cur(c, True))
        conn.commit()
        _pg_state["ready"] = True
    return conn


class _Cur:
    """Liten adapter så att resten av koden kan skriva samma SQL för SQLite och Postgres."""

    def __init__(self, cur, pg: bool):
        self.cur, self.pg = cur, pg

    def _sql(self, sql: str) -> str:
        if not self.pg:
            return sql
        # psycopg2: % måste skrivas %% (t.ex. LIKE 'Demo%'), platshållare är %s
        return sql.replace("%", "%%").replace("?", "%s").replace("ORDER BY rowid", "ORDER BY ord")

    def execute(self, sql: str, params=()) -> int:
        self.cur.execute(self._sql(sql), _params(params))
        return self.cur.rowcount

    def executemany(self, sql: str, rows) -> None:
        rows = [_params(r) for r in rows]
        if rows:
            self.cur.executemany(self._sql(sql), rows)

    def rows(self, sql: str, params=()) -> list[tuple]:
        self.cur.execute(self._sql(sql), _params(params))
        return self.cur.fetchall()

    def one(self, sql: str, params=()):
        self.cur.execute(self._sql(sql), _params(params))
        return self.cur.fetchone()

    def df(self, sql: str, params=()) -> pd.DataFrame:
        self.cur.execute(self._sql(sql), _params(params))
        cols = [d[0] for d in self.cur.description]
        return pd.DataFrame(self.cur.fetchall(), columns=cols)


def _ensure_default_account(c: _Cur) -> None:
    if c.one("SELECT COUNT(*) FROM accounts")[0] == 0:
        c.execute("INSERT INTO accounts (name, type, broker, courtage_class) VALUES (?, 'ISK', 'Avanza', 'Mini')",
                  (DEFAULT_ACCOUNT,))


def _sqlite_migrations(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    if "account" not in cols:
        conn.execute(f"ALTER TABLE transactions ADD COLUMN account TEXT NOT NULL DEFAULT '{DEFAULT_ACCOUNT}'")
    acols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)")]
    if "cash" not in acols:
        conn.execute("ALTER TABLE accounts ADD COLUMN cash REAL NOT NULL DEFAULT 0")


def _migrate_from_sqlite(c: _Cur) -> None:
    """Flyttar lokal data till molndatabasen första gången (om molnet är tomt)."""
    if not DB_PATH.exists() or c.one("SELECT COUNT(*) FROM transactions")[0] > 0:
        return
    try:
        src = sqlite3.connect(DB_PATH)
        _sqlite_migrations(src)
        n = src.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        if n == 0:
            return
        tables = {
            "accounts": ACCOUNT_COLUMNS,
            "transactions": [col for col in COLUMNS if col != "id"],
            "watchlist": WATCH_COLUMNS,
            "settings": ["key", "value"],
            "cash_log": ["date", "account", "kind", "amount", "balance", "note"],
        }
        c.execute("DELETE FROM accounts")
        for table, cols in tables.items():
            try:
                rows = src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            c.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)
        _ensure_default_account(c)
    except Exception:
        pass


@contextmanager
def _db():
    """Öppnar en transaktion. Allt i blocket sparas tillsammans – eller inte alls vid fel."""
    if is_cloud():
        with _pg_lock:
            conn = _pg_conn()
            cur = conn.cursor()
            try:
                yield _Cur(cur, True)
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                _pg_state["used"] = 0  # kontrollera anslutningen nästa gång
                raise
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.executescript(SQLITE_SCHEMA)
            _sqlite_migrations(conn)
            cur = _Cur(conn.cursor(), False)
            _ensure_default_account(cur)
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def storage_status() -> tuple[bool, str]:
    """(permanent?, text) för sidomenyn."""
    if not is_cloud():
        return False, "⚠️ Data sparas tillfälligt – försvinner vid omstart. Koppla in databas (se Inställningar)."
    try:
        with _db() as c:
            c.one("SELECT 1")
        return True, "💾 Data sparas permanent i molnet."
    except Exception as e:
        return False, f"⚠️ Kunde inte nå databasen ({type(e).__name__}). Kontrollera DATABASE_URL."


# ---------------------------------------------------------------- Konton
def load_accounts() -> pd.DataFrame:
    with _db() as c:
        return c.df(f"SELECT {', '.join(ACCOUNT_COLUMNS)} FROM accounts ORDER BY rowid")


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
    with _db() as c:
        c.execute("DELETE FROM accounts")
        c.executemany(f"INSERT INTO accounts ({', '.join(ACCOUNT_COLUMNS)}) VALUES (?,?,?,?,?,?,?)",
                      list(df.itertuples(index=False, name=None)))


def rename_account(old: str, new: str) -> None:
    with _db() as c:
        c.execute("UPDATE accounts SET name = ? WHERE name = ?", (new, old))
        c.execute("UPDATE transactions SET account = ? WHERE account = ?", (new, old))
        c.execute("UPDATE cash_log SET account = ? WHERE account = ?", (new, old))


# ---------------------------------------------------------------- Pengar för köp
def get_cash() -> dict[str, float]:
    with _db() as c:
        return {n: float(v) for n, v in c.rows("SELECT name, cash FROM accounts")}


def change_cash(account: str, amount: float, kind: str, note: str = "", date: str | None = None) -> float:
    """Ändrar saldot med amount (+ in, − ut). kind='SALDO' sätter saldot till amount. Returnerar nytt saldo."""
    import datetime as _dt
    date = date or _dt.date.today().isoformat()
    with _db() as c:
        row = c.one("SELECT cash FROM accounts WHERE name = ?", (account,))
        if row is None:
            c.execute("INSERT INTO accounts (name) VALUES (?)", (account,))
            row = (0.0,)
        old = float(row[0])
        new = float(amount) if kind == "SALDO" else old + float(amount)
        c.execute("UPDATE accounts SET cash = ? WHERE name = ?", (round(new, 2), account))
        c.execute("INSERT INTO cash_log (date, account, kind, amount, balance, note) VALUES (?,?,?,?,?,?)",
                  (date, account, kind, round(new - old, 2), round(new, 2), note))
    return new


def load_cash_log() -> pd.DataFrame:
    with _db() as c:
        return c.df("SELECT date, account, kind, amount, balance, note FROM cash_log ORDER BY date DESC, id DESC")


# ---------------------------------------------------------------- Transaktioner
def load_transactions() -> pd.DataFrame:
    with _db() as c:
        df = c.df(f"SELECT {', '.join(COLUMNS)} FROM transactions ORDER BY date, id")
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df["note"] = df["note"].fillna("")
    for col in ("quantity", "price", "fee", "fx_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def add_transaction(date: str, ticker: str, type_: str, quantity: float, price: float,
                    fee: float, currency: str, fx_rate: float, note: str = "",
                    account: str = DEFAULT_ACCOUNT) -> None:
    with _db() as c:
        c.execute(
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
    for col, default in (("note", ""), ("fee", 0.0), ("fx_rate", 1.0), ("currency", "SEK")):
        if col not in df:
            df[col] = default
        df[col] = df[col].fillna(default)
    rows = list(df[[col for col in COLUMNS if col != "id"]].itertuples(index=False, name=None))
    with _db() as c:
        c.execute("DELETE FROM transactions")
        c.executemany(
            "INSERT INTO transactions (date, account, ticker, type, quantity, price, fee, currency, fx_rate, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        existing = {r[0] for r in c.rows("SELECT name FROM accounts")}
        for acc in sorted(set(df["account"]) - existing):
            c.execute("INSERT INTO accounts (name) VALUES (?)", (acc,))


def delete_demo() -> int:
    """Tar bort exempeltransaktionerna. Returnerar antal borttagna."""
    with _db() as c:
        return c.execute("DELETE FROM transactions WHERE note LIKE 'Demo%'")


def delete_holding(account: str, ticker: str) -> None:
    """Tar bort alla transaktioner för en aktie på ett konto."""
    with _db() as c:
        c.execute("DELETE FROM transactions WHERE account = ? AND ticker = ?", (account, ticker))


def delete_all() -> None:
    with _db() as c:
        c.execute("DELETE FROM transactions")


# ---------------------------------------------------------------- Bevakningslista
def load_watchlist() -> pd.DataFrame:
    with _db() as c:
        df = c.df(f"SELECT {', '.join(WATCH_COLUMNS)} FROM watchlist ORDER BY rowid")
    df["note"] = df["note"].fillna("")
    for col in ("added_price", "buy_below", "sell_above"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def add_watch(ticker: str, name: str, price: float | None) -> bool:
    """Lägger till en aktie. Returnerar False om den redan fanns."""
    import datetime as _dt
    with _db() as c:
        if c.one("SELECT 1 FROM watchlist WHERE ticker = ?", (ticker,)):
            return False
        c.execute("INSERT INTO watchlist (ticker, name, added_date, added_price, note) VALUES (?,?,?,?,'')",
                  (ticker, name, _dt.date.today().isoformat(), price))
    return True


def save_watchlist(df: pd.DataFrame) -> None:
    with _db() as c:
        c.execute("DELETE FROM watchlist")
        c.executemany(f"INSERT INTO watchlist ({', '.join(WATCH_COLUMNS)}) VALUES (?,?,?,?,?,?,?)",
                      list(df[WATCH_COLUMNS].itertuples(index=False, name=None)))


def remove_watch(ticker: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))


# ---------------------------------------------------------------- Inställningar
def get_setting(key: str, default: str | None = None) -> str | None:
    with _db() as c:
        row = c.one("SELECT value FROM settings WHERE key = ?", (key,))
    return row[0] if row else default


def set_setting(key: str, value: str | None) -> None:
    with _db() as c:
        if value is None:
            c.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                      "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, str(value)))


# ---------------------------------------------------------------- Säkerhetskopia
BACKUP_TABLES = {
    "accounts": ACCOUNT_COLUMNS,
    "transactions": [col for col in COLUMNS if col != "id"],
    "watchlist": WATCH_COLUMNS,
    "settings": ["key", "value"],
    "cash_log": ["date", "account", "kind", "amount", "balance", "note"],
}


def export_all() -> dict[str, list[dict]]:
    out = {}
    with _db() as c:
        for table, cols in BACKUP_TABLES.items():
            out[table] = c.df(f"SELECT {', '.join(cols)} FROM {table}").to_dict("records")
    return out


def import_all(data: dict[str, list[dict]]) -> None:
    """Ersätter allt med innehållet i en säkerhetskopia."""
    with _db() as c:
        for table, cols in BACKUP_TABLES.items():
            if table not in data:
                continue
            c.execute(f"DELETE FROM {table}")
            c.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          [tuple(r.get(col) for col in cols) for r in data[table]])
        _ensure_default_account(c)


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
