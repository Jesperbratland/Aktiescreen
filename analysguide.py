"""🧭 Analysguide – räknar och förklarar en aktieanalys steg för steg.

Steg: 1 Bolaget · 2 Kvalitet · 3 Värdering (+ rimligt värde) · 4 Trend & köpsignaler · 5 Risk & storlek · 6 Beslut
Varje kontroll får status good/ok/bad (🟢🟡🔴) och en förklaring på vanlig svenska.
Gränserna är vanliga tumregler, inte sanningar – förklaringarna säger vad siffran betyder.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import analysis
import market

# Ungefärligt typiskt P/E per bransch (Yahoo-namn) – används som jämförelse, inte som facit
SECTOR_PE = {
    "Technology": 25, "Communication Services": 20, "Consumer Cyclical": 19, "Consumer Defensive": 20,
    "Healthcare": 22, "Financial Services": 12, "Industrials": 20, "Basic Materials": 13, "Energy": 11,
    "Utilities": 16, "Real Estate": 17,
}
SECTOR_SV = {
    "Technology": "Teknik", "Communication Services": "Telekom & media", "Consumer Cyclical": "Sällanköpsvaror",
    "Consumer Defensive": "Dagligvaror", "Healthcare": "Hälsovård", "Financial Services": "Finans",
    "Industrials": "Industri", "Basic Materials": "Råvaror", "Energy": "Energi", "Utilities": "Kraftförsörjning",
    "Real Estate": "Fastigheter",
}
REQUIRED_RETURN = 0.08  # avkastningskrav i utdelningsmodellen
POINTS = {"good": 100, "ok": 60, "bad": 20}


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
def quality(info: dict) -> dict:
    roe, margin = _f(info.get("returnOnEquity")), _f(info.get("profitMargins"))
    rev_g, earn_g = _f(info.get("revenueGrowth")), _f(info.get("earningsGrowth"))
    de, fcf = _f(info.get("debtToEquity")), _f(info.get("freeCashflow"))
    financial = (info.get("sector") or "") in ("Financial Services", "Real Estate")
    items = []
    if _ok(roe):
        st_ = "good" if roe >= 0.15 else "ok" if roe >= 0.08 else "bad"
        items.append(_item("ROE", _pct(roe), st_,
                           f"Bolaget tjänar {_pct(roe)} per år på ägarnas pengar. "
                           + ("Det är högt – tecken på en stark affär." if st_ == "good" else
                              "Det är okej men inte imponerande." if st_ == "ok" else
                              "Det är lågt – affären skapar lite värde för ägarna.")))
    if _ok(margin):
        st_ = "good" if margin >= 0.15 else "ok" if margin >= 0.05 else "bad"
        items.append(_item("Vinstmarginal", _pct(margin), st_,
                           f"Av varje försäljningskrona blir {_n(margin * 100, 0)} öre vinst. "
                           + ("Hög marginal ger buffert i sämre tider." if st_ == "good" else
                              "Normal nivå för många branscher." if st_ == "ok" else
                              "Låg marginal gör vinsten känslig för kostnadsökningar.")))
    if _ok(rev_g):
        st_ = "good" if rev_g >= 0.08 else "ok" if rev_g >= 0 else "bad"
        items.append(_item("Omsättningstillväxt", _pct(rev_g, sign=True), st_,
                           "Försäljningen växer " + ("snabbt." if st_ == "good" else "lite." if st_ == "ok"
                                                     else "inte – den minskar jämfört med året innan.")))
    if _ok(earn_g):
        st_ = "good" if earn_g >= 0.10 else "ok" if earn_g >= 0 else "bad"
        items.append(_item("Vinsttillväxt", _pct(earn_g, sign=True), st_,
                           "Vinsten " + ("ökar starkt." if st_ == "good" else "ökar något." if st_ == "ok"
                                         else "har minskat – ta reda på varför (engångseffekt eller trend?).")))
    if _ok(de) and not financial:
        st_ = "good" if de <= 60 else "ok" if de <= 150 else "bad"
        items.append(_item("Skuld/EK (%)", f"{_n(de, 0)} %", st_,
                           "Skulderna är " + ("låga – bolaget klarar sig bra även om räntorna stiger." if st_ == "good"
                                             else "på en normal nivå." if st_ == "ok"
                                             else "höga – sårbart om vinsten faller eller räntorna stiger.")))
    if _ok(fcf):
        items.append(_item("Fritt kassaflöde", "Positivt" if fcf > 0 else "Negativt", "good" if fcf > 0 else "bad",
                           "Bolaget " + ("genererar mer pengar än det investerar – pengar som kan gå till utdelning, "
                                         "återköp eller tillväxt." if fcf > 0 else
                                         "förbrukar pengar – behöver låna eller nyemittera om det fortsätter."),
                           term="Fritt kassaflöde"))
    if financial:
        items.append(_item("Bank/fastighet", "Notera", "ok",
                           "För banker och fastighetsbolag säger skuldsättning och marginaler mindre – titta "
                           "hellre på P/B och ROE.", term="P/B"))
    return {"items": items, "score": _score([i for i in items if i["label"] != "Bank/fastighet"])}


# ---------------------------------------------------------------- steg 3
def valuation(info: dict, price: float) -> dict:
    fxf = _fx_factor(info)
    pe, fpe = _f(info.get("trailingPE")), _f(info.get("forwardPE"))
    peg = _f(info.get("trailingPegRatio") or info.get("pegRatio"))
    ev_ebitda, pb = _f(info.get("enterpriseToEbitda")), _f(info.get("priceToBook"))
    target = _f(info.get("targetMeanPrice"))
    sector = info.get("sector") or ""
    typ = SECTOR_PE.get(sector, 17)
    items = []
    if _ok(pe):
        if pe <= 0:
            items.append(_item("P/E", "Negativt", "bad", "Bolaget går med förlust – P/E säger inget. Värderingen "
                                                         "bygger helt på förhoppningar om framtida vinst."))
        else:
            ratio = pe / typ
            st_ = "good" if ratio <= 0.8 else "ok" if ratio <= 1.25 else "bad"
            items.append(_item("P/E", _n(pe), st_,
                               f"Du betalar {_n(pe, 0)} kr per krona i årsvinst. Typiskt för "
                               f"{SECTOR_SV.get(sector, 'branschen').lower()} är runt {typ}. "
                               + ("Det är billigare än branschen." if st_ == "good" else
                                  "Det ligger i nivå med branschen." if st_ == "ok" else
                                  "Det är dyrare än branschen – marknaden väntar sig stark tillväxt.")))
    if _ok(fpe) and _ok(pe) and pe > 0 and fpe > 0:
        st_ = "good" if fpe < pe * 0.9 else "ok" if fpe <= pe * 1.05 else "bad"
        items.append(_item("P/E (framåt)", _n(fpe), st_,
                           "Analytikerna väntar sig att vinsten "
                           + ("ökar – då blir aktien billigare räknat på nästa års vinst." if st_ == "good" else
                              "är ungefär oförändrad." if st_ == "ok" else "minskar nästa år.")))
    if _ok(peg) and peg > 0:
        st_ = "good" if peg <= 1 else "ok" if peg <= 2 else "bad"
        items.append(_item("PEG", _n(peg, 2), st_,
                           "Tar hänsyn till tillväxten: " + ("billigt i förhållande till hur snabbt vinsten växer."
                                                            if st_ == "good" else "rimligt pris för tillväxten."
                                                            if st_ == "ok" else "dyrt även med tillväxten inräknad.")))
    if _ok(ev_ebitda) and ev_ebitda > 0 and sector not in ("Financial Services",):
        st_ = "good" if ev_ebitda <= 10 else "ok" if ev_ebitda <= 16 else "bad"
        items.append(_item("EV/EBITDA", _n(ev_ebitda), st_,
                           "Värdering inklusive skulder: " + ("lågt." if st_ == "good" else "normalt."
                                                              if st_ == "ok" else "högt.")))
    if _ok(pb) and sector in ("Financial Services", "Real Estate"):
        st_ = "good" if pb <= 1.2 else "ok" if pb <= 2 else "bad"
        items.append(_item("P/B", _n(pb, 2), st_,
                           "För banker/fastigheter är P/B viktigt: " + ("nära eller under bokfört värde." if st_ == "good"
                                                                       else "en bit över bokfört värde." if st_ == "ok"
                                                                       else "klart över bokfört värde.")))
    if _ok(target) and price:
        up = target / price - 1
        st_ = "good" if up >= 0.15 else "ok" if up >= 0 else "bad"
        n_an = info.get("numberOfAnalystOpinions")
        items.append(_item("Analytikers riktkurs", f"{_n(target, 1)} ({_pct(up, 0, sign=True)})", st_,
                           f"{n_an or 'Några'} analytiker tror i snitt på {_pct(up, 0, sign=True)} på ett år. "
                           "Riktkurser slår ofta fel – se det som stämningsläget."))

    # Rimligt värde – flera enkla metoder
    eps = _f(info.get("forwardEps")) if _ok(_f(info.get("forwardEps"))) else _f(info.get("trailingEps"))
    eps_t, book = _f(info.get("trailingEps")) * fxf, _f(info.get("bookValue")) * fxf
    eps = eps * fxf if _ok(eps) else eps
    methods = []
    if _ok(eps) and eps > 0:
        methods.append(("Vinst × branschens P/E", eps * typ,
                        f"Förväntad vinst per aktie ({_n(eps, 2)}) × typiskt P/E för branschen ({typ})."))
    if _ok(eps_t) and _ok(book) and eps_t > 0 and book > 0:
        methods.append(("Grahams tal", math.sqrt(22.5 * eps_t * book),
                        "Benjamin Grahams klassiska formel: √(22,5 × vinst per aktie × eget kapital per aktie). "
                        "Försiktig – passar stabila bolag."))
    div = _f(info.get("dividendRate"))
    if _ok(div) and div > 0:
        g = _f(info.get("earningsGrowth"))
        g = min(max(g if _ok(g) else 0.03, 0.0), 0.05)
        methods.append(("Utdelningsmodell", div * (1 + g) / (REQUIRED_RETURN - g),
                        f"Värdet av alla framtida utdelningar ({_n(div, 2)}/år, växer {_pct(g)}/år) med 8 % "
                        "avkastningskrav."))
    if _ok(target):
        methods.append(("Analytikernas riktkurs", target, "Snittet av analytikernas bedömningar."))
    vals = [v for _, v, _ in methods if _ok(v) and v > 0]
    fair = {"methods": methods}
    if vals:
        mid = float(np.median(vals))
        fair.update(low=float(min(vals)), mid=mid, high=float(max(vals)),
                    margin=mid / price - 1 if price else float("nan"))
        m = fair["margin"]
        fair["verdict"] = ("🟢 Ser billig ut" if m >= 0.20 else "🟡 Rimligt värderad" if m >= -0.10
                           else "🔴 Ser dyr ut")
        fair["why"] = (f"Mittenvärdet av {len(vals)} metoder är {_n(mid, 1)} mot dagens kurs {_n(price, 1)} – "
                       + (f"en säkerhetsmarginal på {_pct(m)}." if m >= 0 else f"aktien kostar {_pct(-m)} mer."))
        st_ = "good" if m >= 0.20 else "ok" if m >= -0.10 else "bad"
        items.append(_item("Rimligt värde", f"{_n(mid, 1)} ({_pct(m, 0, sign=True)})", st_, fair["why"],
                           term="Rimligt värde"))
    return {"items": items, "score": _score(items), "fair": fair, "sector_pe": typ}


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


def decision(q: dict, v: dict, t: dict, r: dict) -> dict:
    parts = {"Kvalitet": q["score"], "Värdering": v["score"], "Trend": t["score"], "Risk": r["score"]}
    valid = {k: s for k, s in parts.items() if _ok(s)}
    total = (sum(s * WEIGHTS[k] for k, s in valid.items()) / sum(WEIGHTS[k] for k in valid)) if valid else float("nan")
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
    all_items = [(k, i) for k, d in (("Kvalitet", q), ("Värdering", v), ("Trend", t), ("Risk", r)) for i in d["items"]]
    pros = [f"{i['label']}: {i['why']}" for _, i in all_items if i["status"] == "good"][:5]
    cons = [f"{i['label']}: {i['why']}" for _, i in all_items if i["status"] == "bad"][:5]
    return {"total": total, "parts": parts, "verdict": verdict, "color": color, "timing": timing,
            "pros": pros, "cons": cons}


def analyze(ticker: str, hist: pd.DataFrame, info: dict) -> dict:
    bench_t = "^OMX" if ticker.upper().endswith(".ST") else "^GSPC"
    b = market.get_closes((bench_t,), period="2y")
    bench = b.iloc[:, 0] if not b.empty else None
    price = float(hist["Close"].dropna().iloc[-1])
    c = company(info)
    q, v = quality(info), valuation(info, price)
    t = trend(hist, bench)
    r = risk(hist, bench, c["mcap_sek"])
    return {"company": c, "quality": q, "valuation": v, "trend": t, "risk": r,
            "decision": decision(q, v, t, r), "price": price, "bench_name": "OMXS30" if bench_t == "^OMX" else "S&P 500"}
