"""Skatteberäkningar för svenska privatpersoner (förenklade uppskattningar).

ISK/KF – schablonskatt:
  kapitalunderlag = (värde 1 jan + 1 apr + 1 jul + 1 okt + insättningar under året) / 4
  skatt = (kapitalunderlag − fribelopp) × (statslåneränta 30 nov året innan + 1 %) × 30 %
  Fribeloppet gäller per person, gemensamt för alla ISK och KF.
  2025: statslåneränta 1,96 %, fribelopp 150 000 kr → 0,888 %
  2026: statslåneränta 2,55 %, fribelopp 300 000 kr → 1,065 %
  2027: statslåneräntan fastställs 30 november 2026 – uppdatera RULES när den är känd.

AF (aktie- och fondkonto/depå):
  30 % skatt på realiserade vinster (genomsnittsmetoden) och utdelningar.
  Förluster på marknadsnoterade aktier kvittas fullt mot vinster på aktier;
  ett kvarvarande underskott ger skattereduktion på 70 % × 30 % = 21 %.
"""
from __future__ import annotations

import pandas as pd

TAX_RATE = 0.30
LOSS_DEDUCTION = 0.70

# år: (statslåneränta i %, fribelopp i kr)
RULES: dict[int, tuple[float, float]] = {
    2024: (2.62, 0.0),
    2025: (1.96, 150_000.0),
    2026: (2.55, 300_000.0),
}


def rules_for(year: int) -> tuple[float, float, bool]:
    """Returnerar (statslåneränta, fribelopp, är_känd)."""
    if year in RULES:
        return (*RULES[year], True)
    latest = RULES[max(RULES)]
    return (*latest, False)


def isk_rate(slr_pct: float) -> float:
    """Effektiv skattesats som andel, t.ex. 0.01065."""
    return max(slr_pct + 1.0, 1.25) / 100 * TAX_RATE


def quarter_starts(year: int) -> list[pd.Timestamp]:
    return [pd.Timestamp(year=year, month=m, day=1) for m in (1, 4, 7, 10)]


def quarter_values(history: pd.DataFrame, year: int) -> list[tuple[pd.Timestamp, float, bool]]:
    """Portföljvärde vid varje kvartalsstart. Framtida kvartal uppskattas med senaste värdet.

    Returnerar lista med (datum, värde, är_prognos).
    """
    out = []
    today = pd.Timestamp.today().normalize()
    for q in quarter_starts(year):
        if history.empty:
            out.append((q, 0.0, q > today))
            continue
        if q > today:
            out.append((q, float(history["value"].iloc[-1]), True))
            continue
        before = history[history.index <= q]
        # Värdet vid kvartalets början = senaste stängning före/på dagen
        val = float(before["value"].iloc[-1]) if not before.empty else 0.0
        out.append((q, val, False))
    return out


def isk_tax(quarter_sum: float, deposits: float, year: int, slr_pct: float | None = None,
            free_amount: float | None = None) -> dict:
    slr, fri, known = rules_for(year)
    if slr_pct is not None:
        slr = slr_pct
    if free_amount is not None:
        fri = free_amount
    base = (quarter_sum + deposits) / 4
    taxable = max(base - fri, 0.0)
    rate = isk_rate(slr)
    return {
        "kapitalunderlag": base,
        "fribelopp": fri,
        "skattepliktigt": taxable,
        "schablonränta": (slr + 1.0) / 100,
        "skattesats": rate,
        "skatt": taxable * rate,
        "regler_kända": known,
    }


def af_tax(gains: float, losses: float, dividends: float) -> dict:
    """gains ≥ 0, losses ≤ 0 (realiserade under året), dividends brutto i SEK."""
    net = gains + losses
    if net >= 0:
        capital_tax = net * TAX_RATE
        reduction = 0.0
    else:
        capital_tax = 0.0
        reduction = -net * LOSS_DEDUCTION * TAX_RATE
    div_tax = max(dividends, 0.0) * TAX_RATE
    return {
        "vinster": gains, "förluster": losses, "netto": net,
        "skatt_vinst": capital_tax, "skattereduktion": reduction,
        "utdelningar": dividends, "skatt_utdelning": div_tax,
        "total": capital_tax + div_tax - reduction,
    }
