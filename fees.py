"""Courtage och valutaväxling för svenska nätmäklare.

Prislistor (svenska/nordiska aktier), kontrollerade november 2026 – kan ändras,
jämför alltid med din mäklares prislista:
  Avanza:  Start 0 kr (samlat sparande < 50 000 kr), Mini 0,25 % min 1 kr,
           Small 0,15 % min 39 kr, Medium 0,069 % min 69 kr, Fast pris 99 kr
  Nordnet: Kom igång 0 kr, Mini 0,25 % min 1 kr, Liten 0,15 % min 39 kr,
           Mellan 0,069 % min 69 kr, Fast 99 kr
  Valutaväxling vid handel i utländsk valuta: 0,25 % hos båda.
Utländska aktier har egna prislistor; här används samma klass som en uppskattning.
"""
from __future__ import annotations

# (rörlig sats i %, minimicourtage kr, fast pris kr eller None)
COURTAGE: dict[str, dict[str, tuple[float, float, float | None]]] = {
    "Avanza": {
        "Start": (0.0, 0.0, None),
        "Mini": (0.25, 1.0, None),
        "Small": (0.15, 39.0, None),
        "Medium": (0.069, 69.0, None),
        "Fast pris": (0.0, 0.0, 99.0),
    },
    "Nordnet": {
        "Kom igång": (0.0, 0.0, None),
        "Mini": (0.25, 1.0, None),
        "Liten": (0.15, 39.0, None),
        "Mellan": (0.069, 69.0, None),
        "Fast": (0.0, 0.0, 99.0),
    },
    "Annan": {
        "Egen sats": (0.0, 0.0, None),
    },
}
FX_FEE_PCT = {"Avanza": 0.25, "Nordnet": 0.25, "Annan": 0.25}
BROKERS = list(COURTAGE)
FREE_CLASSES = {"Start", "Kom igång"}  # gäller bara svenska aktier


def all_classes() -> list[str]:
    seen: list[str] = []
    for classes in COURTAGE.values():
        for c in classes:
            if c not in seen:
                seen.append(c)
    return seen


def calc_fees(amount_sek: float, broker: str, courtage_class: str, foreign: bool,
              custom_pct: float = 0.0, custom_min: float = 0.0) -> dict:
    """Beräknar courtage och valutaväxlingsavgift (båda i SEK) för en affär."""
    broker = broker if broker in COURTAGE else "Annan"
    if broker == "Annan" or courtage_class == "Egen sats":
        pct, mn, fixed = custom_pct, custom_min, None
    else:
        cls = courtage_class
        if cls not in COURTAGE[broker]:
            cls = "Mini"
        if foreign and cls in FREE_CLASSES:
            cls = "Mini"  # nollcourtage gäller bara Stockholmsbörsen
        pct, mn, fixed = COURTAGE[broker][cls]
    courtage = fixed if fixed is not None else max(amount_sek * pct / 100, mn) if amount_sek > 0 else 0.0
    fx_fee = amount_sek * FX_FEE_PCT.get(broker, 0.25) / 100 if foreign else 0.0
    return {"courtage": round(courtage, 2), "fx_fee": round(fx_fee, 2), "total": round(courtage + fx_fee, 2)}
