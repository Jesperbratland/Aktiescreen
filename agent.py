"""Vargen 🐺 – AI-agent (Claude) som svarar på frågor om aktier och din portfölj.

Agenten har verktyg för att hämta aktuell data, så att svaren bygger på riktiga siffror:
  hamta_portfolj   – dina innehav, konton och pengar för köp
  hamta_aktie      – kurs, nyckeltal, avkastning och tekniska signaler för en ticker
  sok_ticker       – hitta ticker utifrån bolagsnamn
Kräver en API-nyckel från Anthropic (console.anthropic.com) i Streamlit Secrets: ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import math

import pandas as pd

import analysis
import db
import market
import portfolio

MODEL = "claude-sonnet-5-5"
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """Du är Vargen 🐺 – en påhittad, självsäker och karismatisk aktiemäklare med glimten i ögat.
Du pratar svenska med energi och lite skryt ("lyssna nu, det här är guld"), korta meningar och tydliga poänger.
Du är INTE någon verklig person och citerar inga filmer.

Bakom attityden är du extremt kunnig och ärlig:
- Basera alltid analyser på riktiga siffror: använd verktygen för att hämta portföljen och aktiedata innan du
  uttalar dig om en specifik aktie eller om användarens innehav. Hitta aldrig på kurser eller nyckeltal.
- Förklara värdering (P/E, P/B, EV/EBITDA, direktavkastning), kvalitet (ROE, marginaler, skuld), trend
  (MA50/MA200, RSI, momentum) och risk (volatilitet, drawdown, koncentration) på ett begripligt sätt.
- Ta hänsyn till kontotyp: ISK/KF (schablonskatt 1,065 % 2026 över 300 000 kr) vs AF (30 % på vinst).
- Var tydlig med risker och motargument. Lova aldrig avkastning. Uppmana aldrig till belåning, blankning,
  att lägga allt i en aktie eller att agera på rykten. Ingen pump-and-dump-mentalitet – du gillar
  långsiktighet, spridning och låga avgifter, även om du säger det med swagger.
- Det är användaren som fattar besluten. Avsluta analyser med en kort påminnelse om att detta inte är
  personlig finansiell rådgivning, men gör det kort och i din stil.
- Håll svaren lagom korta (helst under 250 ord) om inte användaren ber om djupare analys. Använd gärna
  punktlistor och fetstil för nyckelsiffror.
"""

TOOLS = [
    {
        "name": "hamta_portfolj",
        "description": "Hämtar användarens nuvarande portfölj: innehav per konto med antal, GAV, värde, "
                       "orealiserat resultat och vikt, samt kontotyper och pengar tillgängliga för köp.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "hamta_aktie",
        "description": "Hämtar aktuell data för en aktie: kurs, nyckeltal (P/E, P/B, ROE, marginaler, "
                       "direktavkastning, skuld), avkastning över perioder, risk och tekniska signaler. "
                       "Tickern ska vara i Yahoo-format, t.ex. VOLV-B.ST, AAPL, NOVO-B.CO.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}},
                         "required": ["ticker"]},
    },
    {
        "name": "sok_ticker",
        "description": "Söker efter ticker utifrån bolagsnamn, t.ex. 'Volvo' eller 'Nvidia'.",
        "input_schema": {"type": "object", "properties": {"namn": {"type": "string"}}, "required": ["namn"]},
    },
]


def _clean(v):
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    return v


def tool_portfolio() -> dict:
    tx = db.load_transactions()
    accounts = db.load_accounts()
    cash = db.get_cash()
    out = {"konton": [{"namn": r.name, "typ": r.type, "maklare": r.broker,
                       "tillgangligt_for_kop_sek": round(cash.get(r.name, 0.0), 2)}
                      for r in accounts.itertuples()], "innehav": []}
    if tx.empty:
        return out
    pos = portfolio.compute_positions(tx, by_account=True)
    pos = pos[pos["qty"] > 0]
    if pos.empty:
        return out
    quotes = market.get_live_quotes(tuple(sorted(pos["ticker"].unique())))
    fx = market.get_fx_now(tuple(sorted(set(pos["currency"]) | {"SEK"})))
    pos = pos.assign(
        kurs=pos["ticker"].map(quotes["last"]),
        varde_sek=lambda d: d["qty"] * d["kurs"] * d["currency"].map(fx).fillna(1.0),
    )
    total = pos["varde_sek"].sum()
    for r in pos.itertuples():
        out["innehav"].append({
            "konto": r.account, "ticker": r.ticker, "antal": _clean(float(r.qty)),
            "gav": _clean(float(r.cost_local / r.qty)), "valuta": r.currency, "kurs": _clean(float(r.kurs)),
            "varde_sek": _clean(float(r.varde_sek)), "anskaffning_sek": _clean(float(r.cost_sek)),
            "orealiserat_pct": _clean(float(r.varde_sek / r.cost_sek - 1)) if r.cost_sek else None,
            "vikt_pct": _clean(float(r.varde_sek / total * 100)) if total else None,
        })
    out["totalt_aktier_sek"] = _clean(float(total))
    return out


def tool_stock(ticker: str) -> dict:
    ticker = ticker.strip().upper()
    hist = market.get_history(ticker, "5y")
    if hist.empty:
        return {"fel": f"Hittade ingen data för {ticker}. Prova sok_ticker."}
    info = market.get_info(ticker)
    close = hist["Close"]
    live = market.get_live_quotes((ticker,))
    keys = ["longName", "sector", "industry", "currency", "marketCap", "trailingPE", "forwardPE", "priceToBook",
            "enterpriseToEbitda", "returnOnEquity", "profitMargins", "grossMargins", "revenueGrowth",
            "earningsGrowth", "debtToEquity", "dividendRate", "payoutRatio", "targetMeanPrice",
            "recommendationKey", "numberOfAnalystOpinions"]
    return {
        "ticker": ticker,
        "kurs": _clean(float(live.loc[ticker, "last"])) if ticker in live.index else _clean(float(close.iloc[-1])),
        "kurskalla": live.loc[ticker, "source"] if ticker in live.index else "Yahoo",
        "nyckeltal": {k: _clean(info.get(k)) for k in keys if info.get(k) is not None},
        "avkastning": {k: _clean(v) for k, v in analysis.period_returns(close).items()},
        "risk_1ar": {k: _clean(v) for k, v in analysis.perf_stats(close.tail(252)).items()},
        "rsi14": _clean(float(analysis.rsi(close).iloc[-1])),
        "ma50": _clean(float(analysis.sma(close, 50).iloc[-1])),
        "ma200": _clean(float(analysis.sma(close, 200).iloc[-1])),
        "signaler": [f"{s['signal']}: {s['detail']}" for s in analysis.technical_signals(hist)],
        "bolagsbeskrivning": (info.get("longBusinessSummary") or "")[:600],
    }


def tool_search(namn: str) -> dict:
    res = market.search_ticker(namn)
    if res.empty:
        return {"traffar": []}
    return {"traffar": res.head(8).to_dict("records")}


def run_tool(name: str, args: dict) -> str:
    try:
        if name == "hamta_portfolj":
            out = tool_portfolio()
        elif name == "hamta_aktie":
            out = tool_stock(args.get("ticker", ""))
        elif name == "sok_ticker":
            out = tool_search(args.get("namn", ""))
        else:
            out = {"fel": f"Okänt verktyg {name}"}
    except Exception as e:  # verktygsfel ska inte krascha chatten
        out = {"fel": str(e)}
    return json.dumps(out, ensure_ascii=False, default=str)


def chat(api_key: str, history: list[dict], on_tool=None, model: str = MODEL) -> str:
    """Skickar konversationen till Claude, kör verktyg vid behov och returnerar svaret som text.

    history: [{"role": "user"/"assistant", "content": "text"}, ...]
    on_tool: valfri callback(namn, argument) för att visa vad agenten gör.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(model=model, max_tokens=1500, system=SYSTEM_PROMPT,
                                      tools=TOOLS, messages=messages)
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                if on_tool:
                    on_tool(b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": run_tool(b.name, b.input)})
        messages.append({"role": "user", "content": results})
    return "Jag har grävt i siffrorna länge nu – ställ frågan lite smalare så tar vi det steg för steg. 🐺"
