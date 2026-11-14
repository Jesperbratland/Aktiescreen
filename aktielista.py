"""Populära aktier med namn, så att man kan välja utan att kunna tickern.

Saknas en aktie kan man ändå skriva namnet – då söks den upp hos Yahoo Finance.
Lägg gärna till fler: "TICKER": "Namn".
"""

POPULAR: dict[str, str] = {
    # Sverige – stora bolag
    "ABB.ST": "ABB", "ADDT-B.ST": "Addtech B", "ALFA.ST": "Alfa Laval", "ALIV-SDB.ST": "Autoliv SDB",
    "ASSA-B.ST": "Assa Abloy B", "ATCO-A.ST": "Atlas Copco A", "ATCO-B.ST": "Atlas Copco B",
    "AZN.ST": "AstraZeneca", "BOL.ST": "Boliden", "EPI-A.ST": "Epiroc A", "EQT.ST": "EQT",
    "ERIC-B.ST": "Ericsson B", "ESSITY-B.ST": "Essity B", "EVO.ST": "Evolution", "GETI-B.ST": "Getinge B",
    "HEXA-B.ST": "Hexagon B", "HM-B.ST": "H&M B", "INDU-C.ST": "Industrivärden C", "INVE-A.ST": "Investor A",
    "INVE-B.ST": "Investor B", "KINV-B.ST": "Kinnevik B", "LIFCO-B.ST": "Lifco B", "LUND-B.ST": "L E Lundbergföretagen B",
    "NDA-SE.ST": "Nordea", "NIBE-B.ST": "Nibe B", "SAAB-B.ST": "Saab B", "SAND.ST": "Sandvik", "SCA-B.ST": "SCA B",
    "SEB-A.ST": "SEB A", "SHB-A.ST": "Handelsbanken A", "SKA-B.ST": "Skanska B", "SKF-B.ST": "SKF B",
    "SSAB-B.ST": "SSAB B", "SWED-A.ST": "Swedbank A", "TEL2-B.ST": "Tele2 B", "TELIA.ST": "Telia",
    "VOLV-A.ST": "Volvo A", "VOLV-B.ST": "Volvo B",
    # Sverige – medelstora och populära
    "AAK.ST": "AAK", "AXFO.ST": "Axfood", "AZA.ST": "Avanza Bank", "BEIJ-B.ST": "Beijer Ref B",
    "BILL.ST": "Billerud", "BURE.ST": "Bure Equity", "CAMX.ST": "Camurus", "CAST.ST": "Castellum",
    "EKTA-B.ST": "Elekta B", "ELUX-B.ST": "Electrolux B", "EMBRAC-B.ST": "Embracer B", "FABG.ST": "Fabege",
    "FNOX.ST": "Fortnox", "HOLM-B.ST": "Holmen B", "HUSQ-B.ST": "Husqvarna B", "INDT.ST": "Indutrade",
    "LAGR-B.ST": "Lagercrantz B", "LATO-B.ST": "Investment AB Latour B", "MYCR.ST": "Mycronic",
    "SAGA-B.ST": "Sagax B", "SAVE.ST": "Nordnet", "SBB-B.ST": "Samhällsbyggnadsbolaget B",
    "SECU-B.ST": "Securitas B", "SINCH.ST": "Sinch", "SOBI.ST": "Sobi", "SWEC-B.ST": "Sweco B",
    "THULE.ST": "Thule", "TREL-B.ST": "Trelleborg B", "VITR.ST": "Vitrolife", "WALL-B.ST": "Wallenstam B",
    "WIHL.ST": "Wihlborgs",
    # Norden
    "NOVO-B.CO": "Novo Nordisk B", "DSV.CO": "DSV", "MAERSK-B.CO": "A.P. Møller-Mærsk B", "ORSTED.CO": "Ørsted",
    "VWS.CO": "Vestas", "CARL-B.CO": "Carlsberg B", "EQNR.OL": "Equinor", "DNB.OL": "DNB", "MOWI.OL": "Mowi",
    "TEL.OL": "Telenor", "NOKIA.HE": "Nokia", "NESTE.HE": "Neste", "SAMPO.HE": "Sampo", "KNEBV.HE": "Kone",
    # USA
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "GOOGL": "Alphabet (Google) A",
    "META": "Meta (Facebook)", "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway B", "JPM": "JPMorgan Chase",
    "V": "Visa", "MA": "Mastercard", "UNH": "UnitedHealth", "XOM": "Exxon Mobil", "JNJ": "Johnson & Johnson",
    "PG": "Procter & Gamble", "HD": "Home Depot", "COST": "Costco", "AVGO": "Broadcom", "LLY": "Eli Lilly",
    "KO": "Coca-Cola", "PEP": "PepsiCo", "NFLX": "Netflix", "ADBE": "Adobe", "CRM": "Salesforce", "AMD": "AMD",
    "SPOT": "Spotify", "PLTR": "Palantir", "INTC": "Intel", "DIS": "Disney", "NKE": "Nike", "MCD": "McDonald's",
    "O": "Realty Income",
}

# Valuta utifrån börsändelse
SUFFIX_CURRENCY = {
    ".ST": "SEK", ".CO": "DKK", ".OL": "NOK", ".HE": "EUR", ".DE": "EUR", ".PA": "EUR", ".AS": "EUR",
    ".MI": "EUR", ".MC": "EUR", ".BR": "EUR", ".L": "GBP", ".TO": "CAD", ".SW": "CHF",
}


def currency_for(ticker: str, info_currency: str | None = None) -> str:
    for suf, cur in SUFFIX_CURRENCY.items():
        if ticker.upper().endswith(suf):
            return cur
    if info_currency and info_currency.upper() in {"SEK", "USD", "EUR", "NOK", "DKK", "GBP", "CAD", "CHF"}:
        return info_currency.upper()
    return "USD" if "." not in ticker else "SEK"


def label(ticker: str) -> str:
    return f"{POPULAR[ticker]}  ·  {ticker}" if ticker in POPULAR else ticker


def options() -> list[str]:
    return sorted((label(t) for t in POPULAR), key=str.lower)


def ticker_from_label(text: str) -> str | None:
    """Returnerar tickern om texten är ett val ur listan, annars None."""
    if "  ·  " in text:
        return text.split("  ·  ")[-1].strip()
    return None
