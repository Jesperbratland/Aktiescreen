"""Import av Avanzas transaktionsexport (CSV).

Avanza: Logga in → Min ekonomi → Transaktioner → välj period (t.ex. från start) → Exportera.
Filen är semikolonseparerad med decimalkomma. Kolumnerna har ändrats genom åren, så de
känns igen på namn i stället för position. Typiska rubriker:
  Datum; Konto; Typ av transaktion; Värdepapper/beskrivning; Antal; Kurs; Belopp;
  Courtage; Valuta / Instrumentvaluta; Valutakurs; ISIN; Resultat
"""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

import aktielista

# Vår kolumn -> möjliga rubriker hos Avanza (gemener)
COLUMN_ALIASES = {
    "date": ["datum", "affärsdag", "affärsdatum", "transaktionsdag"],
    "account": ["konto", "kontonamn", "kontonummer"],
    "type": ["typ av transaktion", "transaktionstyp", "typ"],
    "name": ["värdepapper/beskrivning", "värdepapper", "beskrivning", "instrument", "namn"],
    "quantity": ["antal"],
    "price": ["kurs", "pris"],
    "amount": ["belopp", "belopp (sek)", "belopp sek"],
    "courtage": ["courtage", "courtage (sek)", "avgift"],
    "fx": ["valutakurs"],
    "currency": ["instrumentvaluta", "valuta", "transaktionsvaluta"],
    "isin": ["isin"],
}

ISIN_SUFFIX = {"SE": ".ST", "DK": ".CO", "NO": ".OL", "FI": ".HE"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower().replace("﻿", ""))


def parse_number(v) -> float:
    """'1 234,56' / '-1234.5' / '−12,3' -> float. Tomt -> NaN."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return float("nan")
    s = str(v).strip().replace("−", "-").replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "--"):
        return float("nan")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def read_file(data: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if text.count(";") >= text.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    headers = {_norm(c): c for c in df.columns}
    found: dict[str, str | None] = {}
    for key, aliases in COLUMN_ALIASES.items():
        found[key] = next((headers[a] for a in aliases if a in headers), None)
        if found[key] is None and key in ("courtage", "amount"):
            found[key] = next((orig for n, orig in headers.items() if n.startswith(aliases[0])), None)
    return found


def classify(type_text: str) -> str | None:
    t = _norm(type_text)
    if "källskatt" in t:
        return "KÄLLSKATT"
    if "utdelning" in t:
        return "UTDELNING"
    if t.startswith("sälj") or t == "sälj":
        return "SÄLJ"
    if t.startswith("köp") or t == "köp":
        return "KÖP"
    return None


def guess_account_type(name: str) -> str:
    n = _norm(name)
    if "kapitalförs" in n or re.search(r"\bkf\b", n):
        return "KF"
    if "isk" in n or "investeringssparkonto" in n:
        return "ISK"
    if "depå" in n or "aktie- och fond" in n or re.search(r"\baf\b", n):
        return "AF"
    if "pension" in n or "tjp" in n or "ips" in n:
        return "KF"  # beskattas med avkastningsskatt, närmast KF
    return "ISK"


def _simplify(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(ab|asa|a/s|oyj|inc|corp|corporation|plc|ltd|publ|class|ser|serie)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def ticker_from_name(name: str) -> str | None:
    """Matchar Avanzas namn (t.ex. 'Volvo B') mot listan med populära aktier."""
    target = _simplify(name)
    for t, n in aktielista.POPULAR.items():
        if _simplify(n) == target:
            return t
    return None


def parse(df: pd.DataFrame, cols: dict[str, str | None]) -> tuple[pd.DataFrame, dict]:
    """Gör om Avanzas rader till våra transaktioner (utan ticker än).

    Returnerar (transaktioner, statistik). Källskatt läggs som avgift på motsvarande utdelning.
    """
    need = ["date", "type", "name", "quantity", "price"]
    missing = [k for k in need if not cols.get(k)]
    if missing:
        raise ValueError("Hittade inte kolumnerna: " + ", ".join(missing))

    def col(key, default=""):
        c = cols.get(key)
        return df[c] if c else pd.Series([default] * len(df), index=df.index)

    out = pd.DataFrame({
        "date": pd.to_datetime(col("date"), errors="coerce").dt.strftime("%Y-%m-%d"),
        "account": col("account", "Avanza").replace("", "Avanza"),
        "kind": col("type").map(classify),
        "type_text": col("type"),
        "name": col("name").str.strip(),
        "isin": col("isin").str.strip().str.upper(),
        "quantity": col("quantity").map(parse_number).abs(),
        "price": col("price").map(parse_number).abs(),
        "amount": col("amount").map(parse_number).abs(),
        "courtage": col("courtage").map(parse_number).abs().fillna(0.0),
        "fx_col": col("fx").map(parse_number),
        "currency": col("currency").str.strip().str.upper(),
    })
    stats = {"rows": len(out)}
    ignored = out[out["kind"].isna()]["type_text"].value_counts()
    stats["ignored"] = ignored.to_dict()

    # Källskatt -> avgift på utdelningen samma dag för samma värdepapper
    wht = out[out["kind"] == "KÄLLSKATT"]
    tx = out[out["kind"].isin(["KÖP", "SÄLJ", "UTDELNING"])].copy()
    tx = tx[tx["date"].notna() & (tx["quantity"] > 0)]
    tx["fee"] = 0.0
    tx.loc[tx["kind"].isin(["KÖP", "SÄLJ"]), "fee"] = tx["courtage"]
    for r in wht.itertuples():
        m = (tx["kind"] == "UTDELNING") & (tx["date"] == r.date) & \
            ((tx["isin"] == r.isin) if r.isin else (tx["name"] == r.name))
        if m.any() and pd.notna(r.amount):
            tx.loc[tx.index[m][0], "fee"] += r.amount
    stats["withholding_rows"] = len(wht)
    stats["used"] = len(tx)
    return tx.reset_index(drop=True), stats


def fx_for_row(r, currency: str) -> float | None:
    """Valutakursen som faktiskt användes, räknad ur beloppet i SEK."""
    if currency == "SEK":
        return 1.0
    gross = r.quantity * r.price
    if gross > 0 and pd.notna(r.amount) and r.amount > 0:
        if r.kind == "KÖP":
            fx = (r.amount - r.courtage) / gross
        elif r.kind == "SÄLJ":
            fx = (r.amount + r.courtage) / gross
        else:
            fx = r.amount / gross
        if fx > 0:
            return fx
    if pd.notna(r.fx_col) and r.fx_col > 0:
        return float(r.fx_col)
    return None


def isin_suffix(isin: str) -> str | None:
    return ISIN_SUFFIX.get(str(isin)[:2].upper()) if isin else None
