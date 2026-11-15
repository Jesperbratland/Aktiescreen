"""🧭 Analysguide – räknar och förklarar en aktieanalys steg för steg.

Steg: 1 Bolaget · 2 Kvalitet · 3 Värdering (+ rimligt värde) · 4 Nyheter · 5 Trend & köpsignaler · 6 Risk & storlek · 7 Beslut
Analysen anpassas efter bransch (PROFILES) och väger in nyhetsflöde och insynshandel.
Varje kontroll får status good/ok/bad (🟢🟡🔴) och en förklaring på vanlig svenska.
Gränserna är vanliga tumregler, inte sanningar – förklaringarna säger vad siffran betyder.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import analysis
import market

SECTOR_SV = {
    "Technology": "Teknik", "Communication Services": "Telekom & media", "Consumer Cyclical": "Sällanköpsvaror",
    "Consumer Defensive": "Dagligvaror", "Healthcare": "Hälsovård", "Financial Services": "Finans",
    "Industrials": "Industri", "Basic Materials": "Råvaror", "Energy": "Energi", "Utilities": "Kraftförsörjning",
    "Real Estate": "Fastigheter",
}
REQUIRED_RETURN = 0.08  # avkastningskrav i utdelningsmodellen
COST_OF_EQUITY = 0.10   # avkastningskrav för banker/försäkring (motiverat P/B = ROE / krav)
POINTS = {"good": 100, "ok": 60, "bad": 20}

# ---------------------------------------------------------------- branschprofiler
# Varje bransch bedöms med sina egna gränser. (bra, okej) – sämre än okej blir rött. None = mäts inte.
# methods: vilka modeller för rimligt värde som passar branschen.
_BASE = dict(pe=17, roe=(0.15, 0.08), margin=(0.15, 0.05), growth=(0.08, 0.0), debt=(60, 150), ev=(10, 16),
             pb=None, methods=("pe", "graham", "ddm", "target"), cyclical=False,
             weights={"Kvalitet": 0.30, "Värdering": 0.30, "Trend": 0.20, "Risk": 0.20})


def _p(name, focus, **kw):
    d = dict(_BASE, name=name, focus=focus)
    d.update(kw)
    return d


PROFILES = {
    "bank": _p("Bank", "För banker är **ROE**, **P/B**, kreditförluster och kapitalbuffert viktigast. Lån är själva "
               "affärsmodellen, så skuldsättning och vinstmarginal säger lite. Bankaktier är ofta lågt värderade "
               "och delar ut mycket.",
               pe=10, roe=(0.12, 0.09), margin=None, debt=None, ev=None, pb=(1.1, 1.6), growth=(0.05, -0.02),
               methods=("pe", "pb_roe", "ddm", "target"),
               weights={"Kvalitet": 0.30, "Värdering": 0.35, "Trend": 0.15, "Risk": 0.20}),
    "insurance": _p("Försäkring", "Försäkringsbolag bedöms på **ROE**, **P/B** och hur stabil utdelningen är. "
                    "Skulder (försäkringsåtaganden) ingår i affären och jämförs inte som i vanliga bolag.",
                    pe=13, roe=(0.15, 0.10), margin=None, debt=None, ev=None, pb=(1.5, 2.5), growth=(0.05, -0.02),
                    methods=("pe", "pb_roe", "ddm", "target"),
                    weights={"Kvalitet": 0.30, "Värdering": 0.35, "Trend": 0.15, "Risk": 0.20}),
    "investment": _p("Investmentbolag", "Investmentbolag äger andra bolag. Det viktiga är **substansvärdet** (vad "
                     "innehaven är värda) och om aktien handlas med **rabatt eller premie** mot det. Vinsten svänger "
                     "med börsen och P/E säger därför lite. Eget kapital per aktie används som ungefärligt "
                     "substansvärde.",
                     pe=None, roe=None, margin=None, debt=(30, 60), ev=None, pb=(0.95, 1.15), growth=None,
                     methods=("book", "target"),
                     weights={"Kvalitet": 0.20, "Värdering": 0.40, "Trend": 0.20, "Risk": 0.20}),
    "finance": _p("Finans", "För finansbolag (t.ex. nätmäklare och betalbolag) är **ROE**, tillväxt och marginal "
                  "viktigast. Skuldsättning jämförs inte som i vanliga bolag.",
                  pe=15, debt=None, ev=None, pb=None, methods=("pe", "ddm", "target")),
    "real_estate": _p("Fastigheter", "Fastighetsbolag bedöms på **substansvärde (P/B)**, **belåning** och "
                      "**räntekänslighet**. Vinsten innehåller värdeförändringar på fastigheterna och svänger "
                      "mycket, så P/E säger lite. Stigande räntor slår hårt mot branschen.",
                      pe=None, roe=None, margin=None, debt=(110, 180), ev=(18, 25), pb=(0.9, 1.3), growth=(0.04, 0.0),
                      methods=("book", "ddm", "target"),
                      weights={"Kvalitet": 0.25, "Värdering": 0.35, "Trend": 0.15, "Risk": 0.25}),
    "software": _p("Mjukvara & spel", "Mjukvarubolag bedöms främst på **tillväxt** och **marginal** – höga P/E är "
                   "normalt om tillväxten håller i sig. PEG (P/E delat med tillväxt) blir viktigare än P/E. "
                   "Grahams formel och utdelningsmodellen passar inte.",
                   pe=30, margin=(0.20, 0.08), growth=(0.15, 0.05), ev=(18, 28), methods=("pe", "target"),
                   weights={"Kvalitet": 0.35, "Värdering": 0.25, "Trend": 0.20, "Risk": 0.20}),
    "semis": _p("Halvledare", "Halvledare är **cykliska** – efterfrågan går i vågor. Lågt P/E kan betyda att "
                "vinsten är på topp precis innan den vänder ner. Titta på tillväxt, marginal och var i cykeln "
                "bolaget är.",
                pe=22, margin=(0.20, 0.08), growth=(0.12, 0.0), ev=(14, 22), methods=("pe", "target"), cyclical=True),
    "tech": _p("Teknik", "Teknikbolag bedöms främst på **tillväxt**, **marginal** och konkurrenskraft. Värderingen "
               "är ofta högre än börssnittet om tillväxten är god.",
               pe=24, margin=(0.15, 0.06), growth=(0.10, 0.0), ev=(14, 22), methods=("pe", "target")),
    "telecom": _p("Telekom", "Telekombolag är stabila med låg tillväxt och höga investeringar. Fokus är "
                  "**kassaflöde**, **utdelning** och att skulderna är hanterbara – högre skuld än snittet är normalt.",
                  pe=16, growth=(0.03, -0.02), debt=(100, 180), ev=(7, 10), methods=("pe", "ddm", "target"),
                  weights={"Kvalitet": 0.30, "Värdering": 0.35, "Trend": 0.15, "Risk": 0.20}),
    "media": _p("Media & internet", "Media- och internetbolag bedöms på **tillväxt**, **marginal** och hur stark "
                "plattformen eller varumärket är.",
                pe=22, growth=(0.10, 0.0), ev=(14, 20), methods=("pe", "target")),
    "biotech": _p("Bioteknik", "Bioteknikbolag går ofta med förlust i många år. Det viktiga är **hur länge kassan "
                  "räcker**, vilka studier som pågår och risken för **nyemission**. Vanliga nyckeltal som P/E "
                  "fungerar inte – värdet avgörs av forskningsresultat, så risken är mycket hög.",
                  pe=None, roe=None, margin=None, growth=(0.15, 0.0), ev=None, methods=("target",),
                  weights={"Kvalitet": 0.30, "Värdering": 0.15, "Trend": 0.25, "Risk": 0.30}),
    "healthcare": _p("Hälsovård", "Hälsovårdsbolag är ofta stabila med jämn efterfrågan. Fokus är **marginal**, "
                     "**tillväxt** och patent eller produkter som skyddar mot konkurrens.",
                     pe=22, margin=(0.15, 0.06), growth=(0.07, 0.0), ev=(14, 20)),
    "industrials": _p("Industri", "Verkstads- och industribolag är **cykliska** – de följer konjunkturen. Titta på "
                      "**orderingång**, marginaler och skulder. Lågt P/E på toppen av en konjunktur kan vara en fälla.",
                      pe=19, margin=(0.12, 0.06), growth=(0.06, -0.02), ev=(12, 17), cyclical=True),
    "materials": _p("Råvaror", "Råvarubolag (stål, skog, gruvor, kemi) är **mycket cykliska** – vinsten följer "
                    "råvarupriset. Lågt P/E betyder ofta att priserna är höga just nu, inte att aktien är billig. "
                    "Låga skulder är extra viktigt.",
                    pe=13, margin=(0.15, 0.07), growth=(0.05, -0.05), debt=(40, 90), ev=(7, 11), cyclical=True,
                    weights={"Kvalitet": 0.30, "Värdering": 0.25, "Trend": 0.25, "Risk": 0.20}),
    "energy": _p("Energi", "Energibolag följer olje- och gaspriset och är **mycket cykliska**. Fokus är "
                 "**kassaflöde**, låga skulder och utdelningar. Lågt P/E är normalt i branschen.",
                 pe=11, margin=(0.12, 0.05), growth=(0.05, -0.05), debt=(50, 100), ev=(5, 8), cyclical=True,
                 weights={"Kvalitet": 0.30, "Värdering": 0.25, "Trend": 0.25, "Risk": 0.20}),
    "utilities": _p("Kraftförsörjning", "Kraftbolag är stabila med låg tillväxt och höga skulder (dyra "
                    "anläggningar). De köps ofta för **utdelningen** och är **räntekänsliga**.",
                    pe=16, roe=(0.10, 0.07), margin=(0.12, 0.05), growth=(0.04, -0.02), debt=(120, 200), ev=(9, 13),
                    weights={"Kvalitet": 0.30, "Värdering": 0.35, "Trend": 0.15, "Risk": 0.20}),
    "staples": _p("Dagligvaror", "Dagligvarubolag säljer sådant folk köper i alla tider. De växer långsamt men "
                  "stabilt, så **jämn vinst**, **marginal** och **utdelning** är viktigast.",
                  pe=20, margin=(0.10, 0.04), growth=(0.05, 0.0), ev=(13, 17),
                  weights={"Kvalitet": 0.30, "Värdering": 0.35, "Trend": 0.15, "Risk": 0.20}),
    "consumer": _p("Sällanköpsvaror", "Sällanköpsvaror (kläder, bilar, resor m.m.) är **konjunkturkänsliga** – "
                   "när hushållen har mindre pengar minskar köpen. Fokus är **tillväxt**, **marginal** och "
                   "lagernivåer.",
                   pe=18, margin=(0.10, 0.04), growth=(0.07, 0.0), ev=(11, 16), cyclical=True),
    "default": _p("Övrigt", "Analysen använder allmänna tumregler eftersom branschen är okänd."),
}


def profile(info: dict) -> dict:
    """Välj branschprofil utifrån Yahoos sektor och bransch."""
    sec, ind = info.get("sector") or "", (info.get("industry") or "").lower()
    eps = _f(info.get("trailingEps"))
    key = "default"
    if "bank" in ind:
        key = "bank"
    elif "insurance" in ind:
        key = "insurance"
    elif "asset management" in ind:
        key = "investment"
    elif sec == "Financial Services":
        key = "finance"
    elif sec == "Real Estate":
        key = "real_estate"
    elif "biotech" in ind or (sec == "Healthcare" and _ok(eps) and eps <= 0 and "drug" in ind):
        key = "biotech"
    elif sec == "Healthcare":
        key = "healthcare"
    elif "semiconductor" in ind:
        key = "semis"
    elif "software" in ind or "gaming" in ind:
        key = "software"
    elif sec == "Technology":
        key = "tech"
    elif "telecom" in ind:
        key = "telecom"
    elif sec == "Communication Services":
        key = "media"
    else:
        key = {"Utilities": "utilities", "Consumer Defensive": "staples", "Consumer Cyclical": "consumer",
               "Industrials": "industrials", "Basic Materials": "materials", "Energy": "energy"}.get(sec, "default")
    return dict(PROFILES[key], key=key)


# Bakåtkompatibelt: typiskt P/E per Yahoo-sektor
SECTOR_PE = {s: PROFILES[k]["pe"] for s, k in (
    ("Technology", "tech"), ("Communication Services", "media"), ("Consumer Cyclical", "consumer"),
    ("Consumer Defensive", "staples"), ("Healthcare", "healthcare"), ("Financial Services", "finance"),
    ("Industrials", "industrials"), ("Basic Materials", "materials"), ("Energy", "energy"),
    ("Utilities", "utilities"))} | {"Real Estate": 17}


def _f(v) -> float:
    try:
        v = float(v)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _ok(v) -> bool:
    return v == v


def _pct(x, d=0, sign=False) -> str:
    if not _ok(x):
        return "–"
    s = f"{x * 100:+.{d}f}" if sign else f"{x * 100:.{d}f}"
    return s.replace(".", ",") + " %"


def _n(x, d=1) -> str:
    return "–" if not _ok(x) else f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def _item(label, value, status, why, term=None):
    return {"label": label, "value": value, "status": status, "why": why, "term": term or label}


def _score(items) -> float:
    pts = [POINTS[i["status"]] for i in items if i["status"] in POINTS]
    return float(np.mean(pts)) if pts else float("nan")


def _grade(x, lim, higher_better=True) -> str:
    good, ok = lim
    if higher_better:
        return "good" if x >= good else "ok" if x >= ok else "bad"
    return "good" if x <= good else "ok" if x <= ok else "bad"


def _fx_factor(info: dict) -> float:
    """Om bolaget redovisar i en annan valuta än aktien handlas i (t.ex. ABB: USD vs SEK)."""
    fin, cur = (info.get("financialCurrency") or "").upper(), (info.get("currency") or "").upper()
    if not fin or not cur or fin == cur:
        return 1.0
    rates = market.get_fx_now(tuple(sorted({fin, cur, "SEK"})))
    if fin in rates and cur in rates and rates[cur]:
        return rates[fin] / rates[cur]
    return 1.0


# ---------------------------------------------------------------- steg 1
def company(info: dict) -> dict:
    sector = info.get("sector") or "Okänd"
    mcap = _f(info.get("marketCap"))
    fx = market.get_fx_now(tuple(sorted({(info.get("currency") or "SEK").upper(), "SEK"})))
    mcap_sek = mcap * fx.get((info.get("currency") or "SEK").upper(), 1.0) if _ok(mcap) else float("nan")
    size = ("Storbolag (Large Cap)" if mcap_sek >= 1e11 else "Medelstort (Mid Cap)" if mcap_sek >= 1e10
            else "Mindre bolag (Small Cap)" if _ok(mcap_sek) else "Okänd storlek")
    summary = info.get("longBusinessSummary") or ""
    return {
        "name": info.get("longName") or info.get("shortName") or "",
        "sector": SECTOR_SV.get(sector, sector), "sector_en": sector, "industry": info.get("industry") or "",
        "country": info.get("country") or "", "size": size, "mcap_sek": mcap_sek,
        "employees": info.get("fullTimeEmployees"), "summary": summary,
        "website": info.get("website") or "",
    }


# ---------------------------------------------------------------- steg 2
def quality(info: dict, prof: dict | None = None) -> dict:
    prof = prof or profile(info)
    bn = prof["name"].lower()
    roe, margin = _f(info.get("returnOnEquity")), _f(info.get("profitMargins"))
    rev_g, earn_g = _f(info.get("revenueGrowth")), _f(info.get("earningsGrowth"))
    de, fcf = _f(info.get("debtToEquity")), _f(info.get("freeCashflow"))
    cash = _f(info.get("totalCash"))
    items = []
    if _ok(roe) and prof["roe"]:
        st_ = _grade(roe, prof["roe"])
        items.append(_item("ROE", _pct(roe), st_,
                           f"Bolaget tjänar {_pct(roe)} per år på ägarnas pengar. För {bn} räknas över "
                           f"{_pct(prof['roe'][0])} som bra. "
                           + ("Det här är en stark nivå." if st_ == "good" else
                              "Det är okej men inte imponerande." if st_ == "ok" else
                              "Det är lågt – affären skapar lite värde för ägarna.")))
    if _ok(margin) and prof["margin"]:
        st_ = _grade(margin, prof["margin"])
        items.append(_item("Vinstmarginal", _pct(margin), st_,
                           f"Av varje försäljningskrona blir {_n(margin * 100, 0)} öre vinst. I {bn} räknas över "
                           f"{_pct(prof['margin'][0])} som bra. "
                           + ("Hög marginal ger buffert i sämre tider." if st_ == "good" else
                              "Normal nivå för branschen." if st_ == "ok" else
                              "Låg marginal gör vinsten känslig för kostnadsökningar.")))
    if _ok(rev_g) and prof["growth"]:
        st_ = _grade(rev_g, prof["growth"])
        items.append(_item("Omsättningstillväxt", _pct(rev_g, sign=True), st_,
                           "Försäljningen växer " + ("snabbt" if st_ == "good" else "lite" if st_ == "ok"
                                                     else "inte – den minskar jämfört med året innan")
                           + f" (bra för {bn} är över {_pct(prof['growth'][0])})."))
    # Fastighetsbolags vinst innehåller värdeförändringar – vinsttillväxt säger lite där
    if _ok(earn_g) and prof["growth"] and prof["key"] not in ("biotech", "real_estate"):
        st_ = "good" if earn_g >= max(prof["growth"][0], 0.08) else "ok" if earn_g >= 0 else "bad"
        why = ("Vinsten " + ("ökar starkt." if st_ == "good" else "ökar något." if st_ == "ok"
                             else "har minskat – ta reda på varför (engångseffekt eller trend?)."))
        if prof["cyclical"] and st_ == "bad":
            why += " I en cyklisk bransch kan det vara konjunkturen – fråga dig om botten är nådd."
        items.append(_item("Vinsttillväxt", _pct(earn_g, sign=True), st_, why))
    if _ok(de) and prof["debt"]:
        st_ = _grade(de, prof["debt"], higher_better=False)
        items.append(_item("Skuld/EK (%)", f"{_n(de, 0)} %", st_,
                           "Skulderna är " + ("låga" if st_ == "good" else "på en normal nivå" if st_ == "ok"
                                             else "höga")
                           + f" för {bn} (bra är under {prof['debt'][0]} %). "
                           + ("Bolaget klarar sig bra även om räntorna stiger." if st_ == "good" else
                              "" if st_ == "ok" else "Sårbart om vinsten faller eller räntorna stiger.")))
    # För banker och försäkringsbolag är kassaflödet en del av utlåning/placeringar och säger lite
    if _ok(fcf) and prof["key"] not in ("bank", "insurance"):
        if fcf > 0:
            items.append(_item("Fritt kassaflöde", "Positivt", "good",
                               "Bolaget genererar mer pengar än det investerar – pengar som kan gå till utdelning, "
                               "återköp eller tillväxt.", term="Fritt kassaflöde"))
        elif _ok(cash) and cash > 0:
            years = cash / -fcf
            st_ = "good" if years >= 3 else "ok" if years >= 1.5 else "bad"
            items.append(_item("Kassan räcker", f"ca {_n(years, 1)} år", st_,
                               f"Bolaget förbrukar pengar. Med nuvarande takt räcker kassan i ungefär {_n(years, 1)} år. "
                               + ("Det ger gott om tid." if st_ == "good" else
                                  "Det kan behövas nya pengar inom ett par år." if st_ == "ok" else
                                  "Stor risk för nyemission snart – det späder ut befintliga ägare."),
                               term="Kassan räcker"))
        else:
            items.append(_item("Fritt kassaflöde", "Negativt", "bad",
                               "Bolaget förbrukar pengar – behöver låna eller nyemittera om det fortsätter.",
                               term="Fritt kassaflöde"))
    return {"items": items, "score": _score(items)}


# ---------------------------------------------------------------- steg 3
def valuation(info: dict, price: float, prof: dict | None = None) -> dict:
    prof = prof or profile(info)
    bn = prof["name"].lower()
    fxf = _fx_factor(info)
    pe, fpe = _f(info.get("trailingPE")), _f(info.get("forwardPE"))
    peg = _f(info.get("trailingPegRatio") or info.get("pegRatio"))
    ev_ebitda, pb = _f(info.get("enterpriseToEbitda")), _f(info.get("priceToBook"))
    target = _f(info.get("targetMeanPrice"))
    typ = prof["pe"]
    items = []
    if _ok(pe) and typ:
        if pe <= 0:
            items.append(_item("P/E", "Negativt", "bad", "Bolaget går med förlust – P/E säger inget. Värderingen "
                                                         "bygger helt på förhoppningar om framtida vinst."))
        else:
            ratio = pe / typ
            st_ = "good" if ratio <= 0.8 else "ok" if ratio <= 1.25 else "bad"
            why = (f"Du betalar {_n(pe, 0)} kr per krona i årsvinst. Typiskt för {bn} är runt {typ}. "
                   + ("Det är billigare än branschen." if st_ == "good" else
                      "Det ligger i nivå med branschen." if st_ == "ok" else
                      "Det är dyrare än branschen – marknaden väntar sig stark tillväxt."))
            if prof["cyclical"] and st_ == "good" and not (_ok(fpe) and 0 < fpe < pe):
                st_ = "ok"
                why += (" Men branschen är cyklisk: lågt P/E kan betyda att vinsten är på topp och väntas falla, "
                        "så det räknas inte som ett klart köpsignal.")
            items.append(_item("P/E", _n(pe), st_, why))
    if _ok(fpe) and _ok(pe) and pe > 0 and fpe > 0 and typ:
        st_ = "good" if fpe < pe * 0.9 else "ok" if fpe <= pe * 1.05 else "bad"
        items.append(_item("P/E (framåt)", _n(fpe), st_,
                           "Analytikerna väntar sig att vinsten "
                           + ("ökar – då blir aktien billigare räknat på nästa års vinst." if st_ == "good" else
                              "är ungefär oförändrad." if st_ == "ok" else "minskar nästa år.")))
    if _ok(peg) and peg > 0 and prof["key"] not in ("bank", "insurance", "investment", "real_estate", "biotech"):
        # Tillväxtbranscher accepterar något högre PEG
        lim = (1.3, 2.3) if prof["key"] in ("software", "tech", "semis", "media") else (1.0, 2.0)
        st_ = _grade(peg, lim, higher_better=False)
        items.append(_item("PEG", _n(peg, 2), st_,
                           "Tar hänsyn till tillväxten: " + ("billigt i förhållande till hur snabbt vinsten växer."
                                                            if st_ == "good" else "rimligt pris för tillväxten."
                                                            if st_ == "ok" else "dyrt även med tillväxten inräknad.")))
    if _ok(ev_ebitda) and ev_ebitda > 0 and prof["ev"]:
        st_ = _grade(ev_ebitda, prof["ev"], higher_better=False)
        items.append(_item("EV/EBITDA", _n(ev_ebitda), st_,
                           "Värdering inklusive skulder: " + ("lågt" if st_ == "good" else "normalt"
                                                              if st_ == "ok" else "högt")
                           + f" för {bn} (normalt upp till ca {prof['ev'][1]})."))
    if _ok(pb) and pb > 0 and prof["pb"]:
        st_ = _grade(pb, prof["pb"], higher_better=False)
        if prof["key"] in ("investment", "real_estate"):
            prem = pb - 1
            why = (f"Aktien handlas {'med en rabatt' if prem < 0 else 'med en premie'} på ca {_pct(abs(prem))} "
                   "mot eget kapital (ungefär substansvärdet). "
                   + ("Rabatt betyder att du köper tillgångarna billigare än de är värda." if prem < 0 else
                      "Premie betyder att du betalar mer än tillgångarna är värda – marknaden tror på förvaltningen."))
        else:
            why = (f"För {bn} är P/B viktigt: " + ("nära eller under bokfört värde." if st_ == "good"
                                                  else "en bit över bokfört värde." if st_ == "ok"
                                                  else "klart över bokfört värde."))
        items.append(_item("P/B", _n(pb, 2), st_, why))
    if _ok(target) and price:
        up = target / price - 1
        st_ = "good" if up >= 0.15 else "ok" if up >= 0 else "bad"
        n_an = info.get("numberOfAnalystOpinions")
        items.append(_item("Analytikers riktkurs", f"{_n(target, 1)} ({_pct(up, 0, sign=True)})", st_,
                           f"{n_an or 'Några'} analytiker tror i snitt på {_pct(up, 0, sign=True)} på ett år. "
                           "Riktkurser slår ofta fel – se det som stämningsläget."))

    # Rimligt värde – de metoder som passar branschen
    allowed = set(prof["methods"])
    eps = _f(info.get("forwardEps")) if _ok(_f(info.get("forwardEps"))) else _f(info.get("trailingEps"))
    eps_t, book = _f(info.get("trailingEps")) * fxf, _f(info.get("bookValue")) * fxf
    eps = eps * fxf if _ok(eps) else eps
    roe = _f(info.get("returnOnEquity"))
    methods = []
    if "pe" in allowed and typ and _ok(eps) and eps > 0:
        methods.append(("Vinst × branschens P/E", eps * typ,
                        f"Förväntad vinst per aktie ({_n(eps, 2)}) × typiskt P/E för {bn} ({typ})."))
    pb_now = price / book if _ok(book) and book > 0 and price else float("nan")
    payout = _f(info.get("payoutRatio"))
    # Grahams tal passar bara bolag med lågt P/B (Graham: P/E × P/B ≤ 22,5) – annars blir värdet orimligt lågt
    if ("graham" in allowed and _ok(eps_t) and _ok(book) and eps_t > 0 and book > 0
            and (not _ok(pb_now) or pb_now <= 3)):
        methods.append(("Grahams tal", math.sqrt(22.5 * eps_t * book),
                        "Benjamin Grahams klassiska formel: √(22,5 × vinst per aktie × eget kapital per aktie). "
                        "Försiktig – passar stabila bolag."))
    if "pb_roe" in allowed and _ok(book) and book > 0 and _ok(roe) and roe > 0:
        fair_pb = min(max(roe / COST_OF_EQUITY, 0.5), 3.0)
        methods.append(("Motiverat P/B", book * fair_pb,
                        f"Vanlig bankmodell: en bank som tjänar {_pct(roe)} på eget kapital, när ägarna kräver "
                        f"{_pct(COST_OF_EQUITY)}, är värd ca {_n(fair_pb, 2)} × eget kapital per aktie ({_n(book, 2)})."))
    if "book" in allowed and _ok(book) and book > 0:
        methods.append(("Substansvärde (eget kapital)", book,
                        f"Eget kapital per aktie ({_n(book, 2)}) – ungefär vad tillgångarna är värda minus skulderna. "
                        "Bolagens egna substansvärden kan skilja sig något."))
    div = _f(info.get("dividendRate"))
    # Utdelningsmodellen passar bolag som delar ut en stor del av vinsten
    if "ddm" in allowed and _ok(div) and div > 0 and (not _ok(payout) or payout >= 0.35):
        g = _f(info.get("earningsGrowth"))
        g = min(max(g if _ok(g) else 0.03, 0.0), 0.05)
        methods.append(("Utdelningsmodell", div * (1 + g) / (REQUIRED_RETURN - g),
                        f"Värdet av alla framtida utdelningar ({_n(div, 2)}/år, växer {_pct(g)}/år) med 8 % "
                        "avkastningskrav."))
    if "target" in allowed and _ok(target):
        methods.append(("Analytikernas riktkurs", target, "Snittet av analytikernas bedömningar."))
    # Rensa metoder som avviker kraftigt från de övriga (t.ex. Grahams tal för ett snabbväxande bolag)
    methods = [(n, v, how) for n, v, how in methods if _ok(v) and v > 0]
    used, dropped = list(methods), []
    if len(methods) >= 3:
        med = float(np.median([v for _, v, _ in methods]))
        used = [m for m in methods if med / 2.2 <= m[1] <= med * 2.2]
        dropped = [m for m in methods if m not in used]
    vals = [v for _, v, _ in used]
    fair = {"methods": used, "dropped": dropped,
            "skipped_note": "" if len(allowed) >= 3 else
            f"För {bn} passar bara vissa värderingsmodeller, därför är uppskattningen extra osäker."}
    if vals:
        mid = float(np.median(vals))
        spread = max(vals) / min(vals) if min(vals) > 0 else float("inf")
        fair["uncertain"] = len(vals) < 2 or spread > 2.0 or prof["key"] == "biotech"
        fair.update(low=float(min(vals)), mid=mid, high=float(max(vals)),
                    margin=mid / price - 1 if price else float("nan"))
        m = fair["margin"]
        fair["verdict"] = ("🟢 Ser billig ut" if m >= 0.20 else "🟡 Rimligt värderad" if m >= -0.10
                           else "🔴 Ser dyr ut")
        fair["why"] = (f"Mittenvärdet av {len(vals)} metoder är {_n(mid, 1)} mot dagens kurs {_n(price, 1)} – "
                       + (f"en säkerhetsmarginal på {_pct(m)}." if m >= 0 else f"aktien kostar {_pct(-m)} mer.")
                       + (" Uppskattningen är osäker (få metoder eller stor spridning)." if fair["uncertain"] else ""))
        st_ = "good" if m >= 0.20 else "ok" if m >= -0.10 else "bad"
        if fair["uncertain"] and st_ == "good":
            st_ = "ok"  # en osäker uppskattning räcker inte för grönt
        items.append(_item("Rimligt värde", f"{_n(mid, 1)} ({_pct(m, 0, sign=True)})", st_, fair["why"],
                           term="Rimligt värde"))
    return {"items": items, "score": _score(items), "fair": fair, "sector_pe": typ}


# ---------------------------------------------------------------- nyheter
# Nyckelord i rubriker (svenska + engelska). Poäng: + positivt, − negativt. RED = allvarliga varningsflaggor.
_RED = {
    "vinstvarning": "vinstvarning", "profit warning": "vinstvarning",
    "nyemission": "nyemission", "riktad emission": "nyemission", "företrädesemission": "nyemission",
    "rights issue": "nyemission", "share issue": "nyemission", "konkurs": "konkurs/rekonstruktion",
    "bankrupt": "konkurs/rekonstruktion", "rekonstruktion": "konkurs/rekonstruktion",
    "chapter 11": "konkurs/rekonstruktion", "bedrägeri": "misstänkt brott/utredning", "fraud": "misstänkt brott/utredning",
    "penningtvätt": "misstänkt brott/utredning", "money laundering": "misstänkt brott/utredning",
    "åtal": "misstänkt brott/utredning", "indicted": "misstänkt brott/utredning", "razzia": "misstänkt brott/utredning",
    "utreds": "misstänkt brott/utredning", "investigation": "misstänkt brott/utredning", "probe": "misstänkt brott/utredning",
    "sänker prognos": "sänkt prognos", "sänker sin prognos": "sänkt prognos", "sänkt prognos": "sänkt prognos",
    "cuts guidance": "sänkt prognos", "lowers guidance": "sänkt prognos", "cuts outlook": "sänkt prognos",
    "lowers outlook": "sänkt prognos", "cuts forecast": "sänkt prognos",
    "slopar utdelning": "sänkt/slopad utdelning", "ställer in utdelning": "sänkt/slopad utdelning",
    "sänker utdelning": "sänkt/slopad utdelning", "suspends dividend": "sänkt/slopad utdelning",
    "cuts dividend": "sänkt/slopad utdelning", "blankare": "blankningsattack", "short seller": "blankningsattack",
    "avnotering": "avnotering", "delisting": "avnotering",
}
_NEG = ["vd avgår", "vd lämnar", "ceo resign", "ceo steps down", "varsel", "varslar", "layoff", "job cuts",
        "missar", "misses", "sämre än väntat", "lägre än väntat", "svagare än väntat", "below expectations",
        "weaker than expected", "rasar", "rasade", "störtdyker", "plunge", "tumble", "sinks", "faller", "föll",
        "falls", "slump", "sänker riktkurs", "sänks", "downgrade", "nedgrader", "säljråd", "förlust", "tappar",
        "stämning", "stäms", "lawsuit", "sued", "böter", "nedskrivning", "impairment", "write-down", "återkall",
        "recall", "oro", "concern", "warning"]
_POS = ["höjer riktkurs", "upgrade", "uppgrader", "köpråd", "slår förväntning", "över förväntan",
        "bättre än väntat", "starkare än väntat", "beats", "tops estimates", "rekord", "record", "stiger", "aktien steg",
        "rusar", "rusade", "surges", "jumps", "soars", "rallies", "vinstlyft", "ökar vinsten", "får order",
        "erhåller order", "tar order", "stororder", "wins order", "kontrakt", "contract", "tecknar avtal", "godkänn", "approval", "approved", "partnership"]
_POS2 = ["höjer prognos", "höjer sin prognos", "raises guidance", "raises outlook", "återköp", "buyback",
         "repurchase", "höjer utdelning", "raises dividend", "extrautdelning", "special dividend", "bud på",
         "budpremie", "takeover", "rekordorder", "miljardorder", "jätteorder"]


def _has(text: str, kw: str) -> bool:
    import re
    return re.search(r"(?<![a-zåäö])" + re.escape(kw), text) is not None


def headline_tone(title: str) -> tuple[int, list[str]]:
    """Poäng för en rubrik (−3…+3) och eventuella varningsflaggor."""
    t = (title or "").lower()
    flags = sorted({lab for kw, lab in _RED.items() if _has(t, kw)})
    s = -3 * len(flags)
    s -= sum(1 for kw in _NEG if _has(t, kw))
    s += sum(1 for kw in _POS if _has(t, kw)) + 2 * sum(1 for kw in _POS2 if _has(t, kw))
    return int(max(-3, min(3, s))), flags


def news_check(ticker: str, name: str = "") -> dict:
    """Läser de senaste nyheterna och insynshandeln och väger ihop tonen. Gratis – bara nyckelord, ingen AI."""
    import handelser
    try:
        raw = handelser.news(ticker, limit=15)
    except Exception:
        raw = []
    try:
        core = handelser.core_name(ticker).lower()
    except Exception:
        core = (name or ticker).lower()
    first = core.split()[0] if core else ""
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for it in raw:
        ts = it.get("ts")
        age = (now - ts).days if ts is not None and not pd.isna(ts) else 60
        tone, flags = headline_tone(it["title"])
        low = it["title"].lower()
        about = bool(core) and (core in low or (len(first) >= 4 and first in low))
        rows.append(dict(it, age=age, tone=tone, flags=flags, about=about))
    # Rubriker som nämner bolaget väger tyngst; finns inga sådana används alla
    relevant = [r for r in rows if r["about"]] or rows
    pos = neg = 0.0
    for r in relevant:
        w = 1.0 if r["age"] <= 14 else 0.6 if r["age"] <= 45 else 0.3
        if r["tone"] > 0:
            pos += w * r["tone"]
        elif r["tone"] < 0:
            neg += w * -r["tone"]
    red = [r for r in relevant if r["flags"] and r["age"] <= 30]
    items = []
    if relevant:
        bal = (pos - neg) / max(pos + neg, 1.0)
        score = 60 + 35 * bal
        st_ = "good" if bal >= 0.3 else "bad" if bal <= -0.3 else "ok"
        if red:
            score, st_ = min(score, 25), "bad"
        n_pos = sum(1 for r in relevant if r["tone"] > 0)
        n_neg = sum(1 for r in relevant if r["tone"] < 0)
        items.append(_item("Nyhetsläget", f"{n_pos} positiva · {n_neg} negativa", st_,
                           ("Nyhetsflödet är mest positivt." if st_ == "good" and not red else
                            "Nyhetsflödet är blandat eller neutralt." if st_ == "ok" else
                            "Nyhetsflödet är övervägande negativt – ta reda på vad som hänt.")
                           + f" Bygger på {len(relevant)} rubriker, de senaste veckorna väger tyngst.",
                           term="Nyhetsläget"))
        for r in red[:3]:
            items.append(_item("⚠️ " + ", ".join(r["flags"]).capitalize(), handelser.ago(r["ts"]) if r["ts"] is not None
                               else "nyligen", "bad",
                               f"”{r['title']}” – en sådan nyhet kan ändra hela caset. Läs den innan du köper."))
    else:
        score = float("nan")
    ins = {}
    try:
        ins = handelser.insider_summary(handelser.insider(ticker, days=180))
    except Exception:
        pass
    if ins and (ins.get("buys") or ins.get("sells")):
        st_ = "good" if ins["tone"] == "pos" else "bad" if ins["tone"] == "neg" else "ok"
        items.append(_item("Insynshandel (6 mån)", f"{ins['buys']} köp · {ins['sells']} sälj", st_,
                           ("Personer i ledningen köper egna aktier – de tror på bolaget." if st_ == "good" else
                            "Ledningen har sålt mer än köpt. Det kan ha privata skäl, men är värt att notera."
                            if st_ == "bad" else "Blandad insynshandel – ingen tydlig signal."),
                           term="Insynshandel"))
        if _ok(score):
            score = score + (8 if st_ == "good" else -8 if st_ == "bad" else 0)
        else:
            score = POINTS[st_]
    score = float(min(max(score, 0), 100)) if _ok(score) else score
    return {"items": items, "score": score, "headlines": relevant[:10], "red": red, "insider": ins}


# ---------------------------------------------------------------- steg 4
def trend(hist: pd.DataFrame, bench: pd.Series | None) -> dict:
    close = hist["Close"].dropna()
    items = []
    if len(close) < 60:
        return {"items": items, "score": float("nan"), "signal": "För lite historik"}
    last = float(close.iloc[-1])
    ma50, ma200 = analysis.sma(close, 50).iloc[-1], analysis.sma(close, 200).iloc[-1]
    rsi = float(analysis.rsi(close).iloc[-1])
    hi = float(close.tail(252).max())
    if _ok(ma200):
        above = last > ma200
        items.append(_item("MA200", f"{_pct(last / ma200 - 1, 0, sign=True)} från MA200", "good" if above else "bad",
                           "Kursen ligger " + ("över sitt årssnitt – långsiktig upptrend." if above else
                                               "under sitt årssnitt – långsiktig nedtrend. Många väntar med att köpa "
                                               "tills kursen tar sig över MA200.")))
        if _ok(ma50):
            items.append(_item("MA50", "Över MA200" if ma50 > ma200 else "Under MA200",
                               "good" if ma50 > ma200 else "bad",
                               "Kvartalssnittet ligger " + ("över årssnittet – trenden är positiv (\"golden cross\")."
                                                            if ma50 > ma200 else
                                                            "under årssnittet – trenden är negativ (\"death cross\").")))
    st_ = "good" if rsi < 30 else "ok" if rsi <= 70 else "bad"
    items.append(_item("RSI", _n(rsi, 0), st_,
                       "Översåld – aktien har fallit snabbt och kan studsa." if st_ == "good" else
                       "Normalläge – inga extrema rörelser." if st_ == "ok" else
                       "Överköpt – aktien har stigit snabbt, risk för en rekyl nedåt."))
    dist = last / hi - 1
    st_ = "good" if dist >= -0.10 else "ok" if dist >= -0.30 else "bad"
    items.append(_item("Från 52v-högsta", _pct(dist, 0), st_,
                       "Nära årshögsta – stark aktie." if st_ == "good" else
                       "En bit under årshögsta." if st_ == "ok" else
                       "Långt under årshögsta – något har gått fel eller så är det ett köpläge. Ta reda på varför."))
    line, sig, _ = analysis.macd(close)
    up = line.iloc[-1] > sig.iloc[-1]
    items.append(_item("MACD", "Över signallinjen" if up else "Under signallinjen", "good" if up else "bad",
                       "Kortsiktigt momentum är " + ("positivt." if up else "negativt.")))
    if bench is not None and len(bench.dropna()) > 200 and len(close) > 252:
        r_s = last / float(close.iloc[-253]) - 1
        b = bench.dropna()
        r_b = float(b.iloc[-1]) / float(b.iloc[-253]) - 1 if len(b) > 252 else float("nan")
        if _ok(r_b):
            st_ = "good" if r_s > r_b + 0.02 else "ok" if r_s > r_b - 0.05 else "bad"
            items.append(_item("1 år", f"{_pct(r_s, 0, sign=True)} vs index {_pct(r_b, 0, sign=True)}", st_,
                               "Aktien har " + ("slagit" if st_ == "good" else "följt" if st_ == "ok" else "gått sämre än")
                               + " börsen det senaste året."))
    return {"items": items, "score": _score(items)}


# ---------------------------------------------------------------- steg 5
def risk(hist: pd.DataFrame, bench: pd.Series | None, mcap_sek: float) -> dict:
    close = hist["Close"].dropna().tail(252)
    items = []
    if len(close) < 60:
        return {"items": items, "score": float("nan"), "max_weight": 0.05}
    r = close.pct_change().dropna()
    vol = float(r.std() * math.sqrt(252))
    mdd = float((close / close.cummax() - 1).min())
    st_ = "good" if vol <= 0.22 else "ok" if vol <= 0.35 else "bad"
    items.append(_item("Volatilitet (år)", _pct(vol), st_,
                       "Aktien svänger " + ("lugnt." if st_ == "good" else "normalt för en enskild aktie."
                                            if st_ == "ok" else "kraftigt – var beredd på stora rörelser.")))
    st_ = "good" if mdd >= -0.20 else "ok" if mdd >= -0.40 else "bad"
    items.append(_item("Max drawdown", _pct(mdd), st_,
                       f"Som mest har aktien fallit {_pct(-mdd)} det senaste året. Fråga dig: klarar du det utan att sälja?"))
    if bench is not None and len(bench.dropna()) > 60:
        both = pd.concat([r, bench.pct_change()], axis=1).dropna()
        if len(both) > 60 and both.iloc[:, 1].var() > 0:
            beta = float(both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var())
            st_ = "good" if beta <= 1.0 else "ok" if beta <= 1.4 else "bad"
            items.append(_item("Beta", _n(beta, 2), st_,
                               f"När börsen rör sig 10 % rör sig aktien i snitt {_n(beta * 10, 0)} %."))
    if _ok(mcap_sek):
        st_ = "good" if mcap_sek >= 1e11 else "ok" if mcap_sek >= 1e10 else "bad"
        items.append(_item("Börsvärde", f"{_n(mcap_sek / 1e9, 0)} mdr kr", st_,
                           "Stort, etablerat bolag – oftast stabilare." if st_ == "good" else
                           "Medelstort bolag." if st_ == "ok" else
                           "Litet bolag – större chans men också större risk och ibland låg handel."))
    sc = _score(items)
    max_w = 0.10 if sc >= 75 else 0.07 if sc >= 50 else 0.04
    return {"items": items, "score": sc, "max_weight": max_w, "vol": vol}


# ---------------------------------------------------------------- steg 6
WEIGHTS = {"Kvalitet": 0.30, "Värdering": 0.30, "Trend": 0.20, "Risk": 0.20}
NEWS_WEIGHT = 0.10


def decision(q: dict, v: dict, t: dict, r: dict, n: dict | None = None, prof: dict | None = None) -> dict:
    w = dict((prof or {}).get("weights") or WEIGHTS)
    parts = {"Kvalitet": q["score"], "Värdering": v["score"], "Trend": t["score"], "Risk": r["score"]}
    if n is not None:
        parts["Nyheter"] = n["score"]
        w = {k: x * (1 - NEWS_WEIGHT) for k, x in w.items()} | {"Nyheter": NEWS_WEIGHT}
    valid = {k: s for k, s in parts.items() if _ok(s)}
    total = (sum(s * w[k] for k, s in valid.items()) / sum(w[k] for k in valid)) if valid else float("nan")
    if not _ok(total):
        verdict, color = "För lite data för ett beslut", "neu"
    elif total >= 75:
        verdict, color = "🟢 Starkt köpläge", "pos"
    elif total >= 60:
        verdict, color = "🟢 Intressant – värt att titta närmare på", "pos"
    elif total >= 45:
        verdict, color = "🟡 Avvakta – bevaka och vänta på bättre läge", "neu"
    else:
        verdict, color = "🔴 Undvik just nu", "neg"
    fair = v.get("fair", {})
    margin = fair.get("margin", float("nan"))
    capped = []
    if _ok(total) and _ok(margin) and margin < -0.10 and not fair.get("uncertain") and total >= 60:
        total, verdict, color = 59.0, "🟡 Avvakta – bra bolag men priset är högt", "neu"
        capped.append(f"Poängen är begränsad eftersom aktien kostar {_pct(-margin)} mer än det uppskattade "
                      "rimliga värdet.")
    if n is not None and n.get("red") and _ok(total) and total >= 50:
        flags = sorted({f for r_ in n["red"] for f in r_["flags"]})
        if total >= 60:
            total, color = 59.0, "neu"
        verdict = "🟡 Avvakta – läs de senaste nyheterna först"
        capped.append(f"Färska nyheter om {', '.join(flags)} kan ändra hela bilden. Siffrorna i analysen bygger "
                      "ofta på data från före nyheten.")
    capped = " ".join(capped) or None
    vs, ts = v["score"], t["score"]
    if _ok(vs) and _ok(ts):
        if vs >= 60 and ts >= 60:
            timing = "Attraktiv värdering **och** på väg upp – ett klassiskt köpläge."
        elif vs >= 60:
            timing = ("Värderingen ser bra ut men trenden är svag. Många väntar tills kursen vänder upp (t.ex. över MA50) "
                      "eller köper i omgångar för att inte fånga en fallande kniv.")
        elif ts >= 60:
            timing = ("Stark trend men värderingen är hög. Risk för rekyl – köp hellre i omgångar än allt på en gång, "
                      "eller bevaka med en lägre köpkurs.")
        else:
            timing = "Både hög värdering och svag trend – det finns oftast bättre lägen."
    else:
        timing = ""
    if n is not None and n.get("red"):
        timing = ("Siffrorna nedan bygger på senaste rapporten, men det har kommit en viktig nyhet efter den. "
                  "Läs nyheten i steg 4 innan du bestämmer dig – den kan ändra både vinst och värdering.")
    groups = [("Kvalitet", q), ("Värdering", v), ("Trend", t), ("Risk", r)] + ([("Nyheter", n)] if n else [])
    all_items = [(k, i) for k, d in groups for i in d["items"]]
    pros = [f"{i['label']}: {i['why']}" for _, i in all_items if i["status"] == "good"][:5]
    cons = [f"{i['label']}: {i['why']}" for _, i in all_items if i["status"] == "bad"]
    cons = (sorted(cons, key=lambda c: not c.startswith("⚠️")))[:5]
    return {"total": total, "parts": parts, "verdict": verdict, "color": color, "timing": timing,
            "pros": pros, "cons": cons, "capped": capped}


def next_step(res: dict) -> dict:
    """Ett förslag som hänger ihop med beslutet: köp nu, köp vid rekyl eller bevaka till ett rimligt pris."""
    d, price = res["decision"], res["price"]
    fair = res["valuation"]["fair"]
    mid = fair.get("mid", float("nan"))
    ma50 = res.get("ma50", float("nan"))
    tot = d["total"]
    if not _ok(tot):
        return {"action": "watch", "price": round(price * 0.95, 2),
                "why": "För lite data – bevaka aktien och läs på mer innan du bestämmer dig."}
    if res.get("news", {}).get("red"):
        target = ma50 if _ok(ma50) and ma50 < price else price * 0.95
        return {"action": "watch", "price": round(target, 2),
                "why": ("Det finns färska, viktiga nyheter om bolaget (se steg 4). Läs dem först och gör om "
                        f"analysen när siffrorna har uppdaterats. Under tiden kan du bevaka med larm vid {_n(target, 2)}.")}
    if tot >= 60:
        dip = ma50 if _ok(ma50) and price * 0.85 <= ma50 < price else price * 0.95
        return {"action": "buy", "price": round(dip, 2),
                "why": ("Analysen talar för ett köp till dagens pris. Vill du hellre köpa lite billigare kan du "
                        f"bevaka och få larm vid {_n(dip, 2)}"
                        + (" – kursens 50-dagarssnitt, där aktien ofta brukar studsa." if _ok(ma50) and dip == ma50
                           else " (5 % under dagens kurs).")
                        + " Ett vanligt sätt är att köpa hälften nu och resten vid en rekyl.")}
    if _ok(mid) and mid < price:
        target = mid * 0.95
        return {"action": "watch", "price": round(target, 2),
                "why": (f"Aktien ser dyr ut just nu. Ett rimligt värde är ca {_n(mid, 1)}; med 5 % marginal blir "
                        f"köpkursen {_n(target, 2)} ({_pct(target / price - 1, 0, sign=True)} från idag).")}
    target = ma50 if _ok(ma50) and ma50 < price else price * 0.95
    return {"action": "watch", "price": round(target, 2),
            "why": ("Priset är okej men trenden eller kvaliteten övertygar inte än. Bevaka och få larm vid "
                    f"{_n(target, 2)} ({_pct(target / price - 1, 0, sign=True)}) – eller vänta tills trenden vänder upp.")}


def analyze(ticker: str, hist: pd.DataFrame, info: dict, with_news: bool = True) -> dict:
    bench_t = "^OMX" if ticker.upper().endswith(".ST") else "^GSPC"
    b = market.get_closes((bench_t,), period="2y")
    bench = b.iloc[:, 0] if not b.empty else None
    price = float(hist["Close"].dropna().iloc[-1])
    prof = profile(info)
    c = company(info)
    q, v = quality(info, prof), valuation(info, price, prof)
    t = trend(hist, bench)
    r = risk(hist, bench, c["mcap_sek"])
    n = news_check(ticker, c["name"]) if with_news else None
    ma50 = analysis.sma(hist["Close"].dropna(), 50).iloc[-1] if len(hist) >= 50 else float("nan")
    return {"company": c, "profile": prof, "quality": q, "valuation": v, "trend": t, "risk": r, "news": n or {},
            "decision": decision(q, v, t, r, n, prof), "price": price, "ma50": float(ma50),
            "bench_name": "OMXS30" if bench_t == "^OMX" else "S&P 500"}
