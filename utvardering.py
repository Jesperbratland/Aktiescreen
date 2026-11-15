"""🏅 Portföljbetyg – utvärderar portföljen och ger poäng 0–100.

Åtta delbetyg (vikt):
  Spridning 20 %, Branscher & länder 15 %, Kvalitet 15 %, Värdering 10 %,
  Risk 15 %, Avkastning 10 %, Avgifter & skatt 10 %, Kontanter 5 %.
Varje delbetyg bygger på några mätbara nyckeltal som räknas om till 0–100 med enkla gränser
(se _lin). Saknas data för ett delbetyg räknas det inte med, och vikterna fördelas om.
Risk och avkastning räknas på DAGENS innehav det senaste året ("om du hade ägt den här
portföljen i ett år"), så betyget fungerar även om du nyss lagt in dina aktier.
"""
from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd

import db
import market

WEIGHTS = {
    "Spridning": 0.20, "Branscher & länder": 0.15, "Kvalitet": 0.15, "Värdering": 0.10,
    "Risk": 0.15, "Avkastning": 0.10, "Avgifter & skatt": 0.10, "Kontanter": 0.05,
}
ICONS = {"Spridning": "🧺", "Branscher & länder": "🌍", "Kvalitet": "💎", "Värdering": "🏷️",
         "Risk": "🎢", "Avkastning": "📈", "Avgifter & skatt": "💸", "Kontanter": "💰"}
EXPLAIN = {
    "Spridning": "Hur väl pengarna är fördelade på flera bolag, så att ett enskilt bolag inte kan sänka allt.",
    "Branscher & länder": "Om portföljen är beroende av en enda bransch eller ett enda land.",
    "Kvalitet": "Hur lönsamma och stabila bolagen är (ROE, vinstmarginal, skuldsättning).",
    "Värdering": "Om du betalar mycket eller lite för bolagens vinster (P/E-tal).",
    "Risk": "Hur mycket portföljen svänger och hur djupt den har fallit det senaste året.",
    "Avkastning": "Hur dagens portfölj har gått det senaste året jämfört med Stockholmsbörsen.",
    "Avgifter & skatt": "Courtage, valutaväxling och om pengarna ligger på rätt typ av konto.",
    "Kontanter": "Om du har lagom med pengar redo för köp – varken för lite eller för mycket.",
}


def _lin(x, bad, good) -> float:
    """Linjär poäng: x=bad → 0, x=good → 100 (fungerar åt båda hållen), klipps till 0–100."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or bad == good:
        return float("nan")
    return float(np.clip((x - bad) / (good - bad) * 100, 0, 100))


def _mean(vals) -> float:
    v = [x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return float(np.mean(v)) if v else float("nan")


def _wavg(values: pd.Series, weights: pd.Series) -> float:
    m = values.notna()
    if not m.any() or weights[m].sum() == 0:
        return float("nan")
    return float((values[m] * weights[m]).sum() / weights[m].sum())


def _pct(x, d=0) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{d}f} %".replace(".", ",")


def grade(score: float) -> tuple[str, str]:
    if score != score:
        return "–", "För lite data för ett betyg."
    for limit, g, text in ((90, "A+", "Toppklass – en välbyggd och genomtänkt portfölj."),
                           (80, "A", "Mycket bra – bara små saker att finslipa."),
                           (70, "B", "Bra portfölj med några tydliga förbättringsmöjligheter."),
                           (60, "C", "Okej, men det finns flera saker som skulle göra den stabilare."),
                           (50, "D", "Ganska sårbar – titta på förbättringsförslagen nedan."),
                           (0, "E", "Hög risk eller obalanserad – börja med de viktigaste förslagen.")):
        if score >= limit:
            return g, text
    return "E", ""


def _risk_data(hold: pd.DataFrame) -> dict:
    """Daglig avkastning för dagens portfölj (fasta vikter) och för OMXS30 senaste året."""
    tickers = tuple(sorted(hold["ticker"]))
    closes = market.get_closes(tickers + ("^OMX",), period="1y")
    if closes.empty:
        return {}
    rets = closes.ffill().pct_change().dropna(how="all").iloc[1:]
    stock = rets[[t for t in tickers if t in rets.columns]].fillna(0.0)
    if stock.empty or len(stock) < 40:
        return {}
    w = hold.set_index("ticker")["weight"].reindex(stock.columns).fillna(0.0)
    w = w / w.sum() if w.sum() else w
    port = (stock * w).sum(axis=1)
    bench = rets["^OMX"].fillna(0.0) if "^OMX" in rets else pd.Series(dtype=float)
    out = {"port": port, "stock": stock, "weights": w, "bench": bench}
    out["vol"] = float(port.std() * math.sqrt(252))
    idx = (1 + port).cumprod()
    out["mdd"] = float((idx / idx.cummax() - 1).min())
    out["ret_1y"] = float(idx.iloc[-1] - 1)
    if not bench.empty and bench.var() > 0:
        both = pd.concat([port, bench], axis=1).dropna()
        out["beta"] = float(both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var())
        out["bench_1y"] = float((1 + bench).prod() - 1)
    # Riskbidrag per innehav: w_i * cov(r_i, r_p) / var(r_p)
    var_p = port.var()
    if var_p > 0:
        out["risk_contrib"] = (w * stock.apply(lambda s: s.cov(port)) / var_p).sort_values(ascending=False)
    out["corr"] = stock.corr()
    return out


def evaluate(tx: pd.DataFrame, hold: pd.DataFrame, cash: float, accounts: pd.DataFrame | None = None) -> dict:
    """Utvärderar portföljen. hold = enrich_positions(...) (öppna innehav med value_sek, weight)."""
    res = {"categories": [], "total": float("nan"), "grade": "–", "verdict": "", "risk": {}}
    if hold is None or hold.empty or hold["value_sek"].sum() <= 0:
        res["verdict"] = "Lägg in dina aktier så kan portföljen utvärderas."
        return res
    hold = hold[hold["value_sek"].notna() & (hold["value_sek"] > 0)].copy()
    value = float(hold["value_sek"].sum())
    hold["weight"] = hold["value_sek"] / value
    info = {t: market.get_info(t) for t in hold["ticker"]}

    def num(t, key):
        v = info[t].get(key)
        try:
            v = float(v)
            return v if math.isfinite(v) else float("nan")
        except (TypeError, ValueError):
            return float("nan")

    cats = []

    # 1. Spridning
    n = len(hold)
    top = hold.sort_values("weight", ascending=False).iloc[0]
    eff_n = 1 / float((hold["weight"] ** 2).sum())
    s = _mean([_lin(n, 3, 12), _lin(float(top["weight"]), 0.40, 0.12), _lin(eff_n, 3, 10)])
    tips = []
    if top["weight"] > 0.20:
        tips.append(f"**{top['ticker']}** utgör {_pct(top['weight'])} av portföljen. Sikta på max 10–20 % per bolag "
                    "– använd nästa insättning till andra bolag.")
    if n < 8:
        tips.append(f"Med {n} bolag blir enskilda bolag avgörande. Bygg upp till 8–15 bolag, eller komplettera "
                    "med en billig global indexfond.")
    cats.append({"name": "Spridning", "score": s, "tips": tips, "facts": [
        f"{n} innehav", f"Största innehav: {top['ticker']} ({_pct(top['weight'])})",
        f"Effektivt antal bolag: {eff_n:.1f}".replace(".", ","),
    ], "good": "Pengarna är väl fördelade på flera bolag." if s >= 75 else None})

    # 2. Branscher & länder
    hold["sector"] = hold["ticker"].map(lambda t: info[t].get("sector") or "Okänd")
    hold["country"] = hold["ticker"].map(lambda t: info[t].get("country") or "Okänt")
    sec = hold.groupby("sector")["weight"].sum().sort_values(ascending=False)
    known = sec.drop("Okänd", errors="ignore")
    sek = float(hold.loc[hold["currency"] == "SEK", "weight"].sum())
    home = 100.0 if 0.25 <= sek <= 0.75 else (_lin(sek, 1.0, 0.75) if sek > 0.75 else _lin(sek, 0.0, 0.25))
    parts = [home]
    if not known.empty:
        parts += [_lin(float(known.iloc[0]), 0.65, 0.25), _lin(len(known), 1, 6)]
    s = _mean(parts)
    tips = []
    if not known.empty and known.iloc[0] > 0.40:
        tips.append(f"**{known.index[0]}** väger {_pct(known.iloc[0])}. En nedgång i den branschen slår hårt – "
                    "lägg till bolag i andra branscher.")
    if sek > 0.85:
        tips.append(f"{_pct(sek)} ligger i svenska aktier. Sverige är en liten del av världen – överväg en "
                    "global fond eller några utländska kvalitetsbolag.")
    elif sek < 0.15:
        tips.append("Nästan allt ligger i utländsk valuta, så kronans kurs påverkar din avkastning mycket.")
    cats.append({"name": "Branscher & länder", "score": s, "tips": tips, "facts": [
        f"{len(known)} branscher" + (f", störst {known.index[0]} ({_pct(known.iloc[0])})" if not known.empty else ""),
        f"Svenska aktier: {_pct(sek)}",
        f"Länder: {', '.join(hold.groupby('country')['weight'].sum().sort_values(ascending=False).index[:4])}",
    ], "good": "Bra balans mellan branscher och länder." if s >= 75 else None, "sectors": sec})

    # 3. Kvalitet
    roe = _wavg(hold["ticker"].map(lambda t: num(t, "returnOnEquity")), hold["weight"])
    margin = _wavg(hold["ticker"].map(lambda t: num(t, "profitMargins")), hold["weight"])
    de = _wavg(hold["ticker"].map(lambda t: num(t, "debtToEquity")), hold["weight"])
    s = _mean([_lin(roe, 0.0, 0.20), _lin(margin, 0.0, 0.15), _lin(de, 200, 50)])
    weak = [t for t in hold["ticker"] if num(t, "returnOnEquity") == num(t, "returnOnEquity")
            and num(t, "returnOnEquity") < 0.05]
    tips = []
    if weak:
        tips.append(f"Låg lönsamhet (ROE under 5 %) i: {', '.join(weak[:5])}. Kontrollera att investeringscaset håller.")
    cats.append({"name": "Kvalitet", "score": s, "tips": tips, "facts": [
        f"Viktad ROE: {_pct(roe)}", f"Viktad vinstmarginal: {_pct(margin)}",
        f"Skuld/eget kapital: {'–' if de != de else f'{de:.0f} %'}",
    ], "good": "Lönsamma bolag med sunda balansräkningar." if s >= 75 else None})

    # 4. Värdering
    pe = hold["ticker"].map(lambda t: num(t, "trailingPE"))
    pos = pe > 0
    ey = float((hold.loc[pos, "weight"] / pe[pos]).sum() / hold.loc[pos, "weight"].sum()) if pos.any() else float("nan")
    port_pe = 1 / ey if ey and ey == ey else float("nan")
    loss_w = float(hold.loc[pe.notna() & (pe <= 0), "weight"].sum())
    s = _mean([_lin(port_pe, 35, 14), _lin(loss_w, 0.4, 0.0) if pe.notna().any() else float("nan")])
    tips = []
    if port_pe == port_pe and port_pe > 28:
        expensive = [t for t, p in zip(hold["ticker"], pe) if p == p and p > 40]
        tips.append(f"Portföljens P/E är ca {port_pe:.0f} – höga förväntningar är redan inprisade"
                    + (f" (dyrast: {', '.join(expensive[:4])})." if expensive else "."))
    cats.append({"name": "Värdering", "score": s, "tips": tips, "facts": [
        f"Portföljens P/E: {'–' if port_pe != port_pe else f'{port_pe:.1f}'.replace('.', ',')}",
        f"Andel bolag med förlust: {_pct(loss_w)}",
    ], "good": "Rimligt värderat i förhållande till vinsterna." if s >= 75 else None})

    # 5 + 6. Risk och avkastning (dagens portfölj, senaste året)
    rd = _risk_data(hold)
    res["risk"] = rd
    if rd:
        beta = rd.get("beta", float("nan"))
        s = _mean([_lin(rd["vol"], 0.32, 0.13), _lin(rd["mdd"], -0.40, -0.10), _lin(beta, 1.5, 0.8)])
        tips = []
        if rd["vol"] > 0.25:
            tips.append(f"Portföljen svänger mycket ({_pct(rd['vol'])} per år). Fler bolag i olika branscher "
                        "eller en del stabila utdelningsbolag dämpar svängningarna.")
        if "risk_contrib" in rd and rd["risk_contrib"].iloc[0] > 0.35:
            t = rd["risk_contrib"].index[0]
            tips.append(f"**{t}** står för {_pct(rd['risk_contrib'].iloc[0])} av portföljens risk.")
        cats.append({"name": "Risk", "score": s, "tips": tips, "facts": [
            f"Svängningar: {_pct(rd['vol'])} per år", f"Största fall senaste året: {_pct(rd['mdd'])}",
            f"Beta mot OMXS30: {'–' if beta != beta else f'{beta:.2f}'.replace('.', ',')}",
        ], "good": "Lagom risk – portföljen svänger inte mer än marknaden." if s >= 75 else None})

        diff = rd["ret_1y"] - rd.get("bench_1y", float("nan"))
        s = _mean([_lin(diff, -0.15, 0.05), _lin(rd["ret_1y"], -0.10, 0.12)])
        tips = []
        if diff == diff and diff < -0.05:
            tips.append(f"Dagens portfölj har gått {_pct(-diff)} sämre än OMXS30 det senaste året. Fundera på om en "
                        "indexfond borde utgöra en del av sparandet.")
        cats.append({"name": "Avkastning", "score": s, "tips": tips, "facts": [
            f"Dagens innehav senaste året: {_pct(rd['ret_1y'], 1)}",
            f"OMXS30 samma period: {_pct(rd.get('bench_1y'), 1)}",
            f"Skillnad: {'–' if diff != diff else ('+' if diff >= 0 else '') + _pct(diff, 1)}",
        ], "good": "Dagens innehav har slagit Stockholmsbörsen senaste året." if diff == diff and diff > 0 else None})

    # 7. Avgifter & skatt
    year_ago = (pd.Timestamp.today() - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    trades = tx[(tx["type"].isin(["KÖP", "SÄLJ"])) & (tx["date"] >= year_ago)
                & (tx["note"] != "Ingående innehav") & ~tx["note"].str.startswith("Demo")]
    fees = float(trades["fee"].sum())
    fee_pct = fees / (value + cash) if value + cash else float("nan")
    parts, tips = [_lin(fee_pct, 0.01, 0.001)], []
    if accounts is not None and not accounts.empty:
        acc_type = dict(zip(accounts["name"], accounts["type"]))
        pos_acc = tx.assign(t=tx["account"].map(acc_type))
        af_tickers = set(pos_acc.loc[pos_acc["t"] == "AF", "ticker"])
        af_share = float(hold.loc[hold["ticker"].isin(af_tickers), "weight"].sum())
        if af_share > 0.5 and value < 300_000:
            parts.append(40.0)
            tips.append(f"{_pct(af_share)} ligger på AF-konto. Med under 300 000 kr totalt är ISK skattefritt 2026 "
                        "– långsiktigt sparande passar oftast bättre där.")
        else:
            parts.append(100.0)
    if fee_pct == fee_pct and fee_pct > 0.005:
        tips.append(f"Avgifterna senaste året motsvarar {_pct(fee_pct, 2)} av portföljen. Kolla din courtageklass "
                    "under Skatt & avgifter och undvik många små affärer.")
    s = _mean(parts)
    cats.append({"name": "Avgifter & skatt", "score": s, "tips": tips, "facts": [
        f"Avgifter senaste året: {fees:,.0f} kr".replace(",", " "), f"I procent av portföljen: {_pct(fee_pct, 2)}",
    ], "good": "Låga avgifter och smart kontoval." if s >= 75 else None})

    # 8. Kontanter
    c_share = cash / (value + cash) if value + cash else 0.0
    if 0.02 <= c_share <= 0.15:
        s = 100.0
    elif c_share < 0.02:
        s = 70.0
    else:
        s = _lin(c_share, 0.50, 0.15)
    tips = []
    if c_share > 0.2:
        tips.append(f"{_pct(c_share)} ligger som kontanter. Pengar som ligger still tappar mot inflationen – "
                    "investera gärna i omgångar, t.ex. en gång i månaden.")
    elif c_share < 0.01:
        tips.append("Du har nästan inga pengar redo för köp. En liten buffert gör att du kan köpa när börsen faller.")
    cats.append({"name": "Kontanter", "score": s, "tips": tips,
                 "facts": [f"Pengar för köp: {_pct(c_share)} av totalen"],
                 "good": "Lagom med pengar redo för köp." if s >= 90 else None})

    # Totalt
    valid = [c for c in cats if c["score"] == c["score"]]
    wsum = sum(WEIGHTS[c["name"]] for c in valid)
    total = sum(c["score"] * WEIGHTS[c["name"]] for c in valid) / wsum if wsum else float("nan")
    for c in cats:
        c["weight"] = WEIGHTS[c["name"]]
    # Tak: ett enskilt bolag som dominerar gör portföljen sårbar oavsett övriga poäng
    res["cap_note"] = None
    if total == total and top["weight"] > 0.35:
        cap = 59.0 if top["weight"] > 0.5 else 69.0
        if total > cap:
            total = cap
            res["cap_note"] = (f"Betyget är begränsat till {cap:.0f} eftersom {top['ticker']} utgör "
                               f"{_pct(top['weight'])} av portföljen.")
    res.update(categories=cats, total=total)
    res["grade"], res["verdict"] = grade(total)
    # Viktigaste förbättringar: tips från kategorier med lägst poäng × vikt
    ranked = sorted(valid, key=lambda c: (100 - c["score"]) * c["weight"], reverse=True)
    res["improvements"] = [(c["name"], t) for c in ranked for t in c["tips"]][:5]
    res["strengths"] = [(c["name"], c["good"]) for c in sorted(valid, key=lambda c: -c["score"]) if c.get("good")][:4]
    res["dividend"] = _dividends(hold, info)
    res["hold"] = hold
    return res


def _dividends(hold: pd.DataFrame, info: dict) -> dict:
    fx = market.get_fx_now(tuple(sorted(set(hold["currency"]) | {"SEK"})))
    total = 0.0
    rows = []
    for r in hold.itertuples():
        rate = info[r.ticker].get("dividendRate")
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(rate) or rate <= 0:
            continue
        amount = rate * r.qty * fx.get(r.currency, 1.0)
        total += amount
        rows.append({"ticker": r.ticker, "kr": amount})
    value = float(hold["value_sek"].sum())
    return {"annual": total, "yield": total / value if value else float("nan"),
            "rows": pd.DataFrame(rows).sort_values("kr", ascending=False) if rows else pd.DataFrame()}


def save_history(total: float) -> pd.Series:
    """Sparar dagens betyg (en gång per dag) och returnerar historiken."""
    try:
        hist = json.loads(db.get_setting("score_history", "{}") or "{}")
    except (ValueError, TypeError):
        hist = {}
    today = dt.date.today().isoformat()
    if total == total:
        hist[today] = round(total, 1)
        hist = dict(sorted(hist.items())[-365:])
        db.set_setting("score_history", json.dumps(hist))
    return pd.Series(hist, dtype=float)
