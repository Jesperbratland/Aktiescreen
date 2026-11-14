"""Vargen 🐺 – AI-agent som svarar på frågor om aktier och din portfölj.

Tre lägen, väljs automatiskt utifrån vilka nycklar som finns i Streamlit Secrets:
  GROQ_API_KEY       – gratis AI via Groq (inget betalkort), modell GROQ_MODEL
  ANTHROPIC_API_KEY  – Claude (betalt)
  ingen nyckel       – grundläge: regelbaserade svar på appens egen data, helt gratis

Agenten har verktyg för att hämta aktuell data, så att svaren bygger på riktiga siffror:
  hamta_portfolj   – dina innehav, konton och pengar för köp
  hamta_aktie      – kurs, nyckeltal, avkastning och tekniska signaler för en ticker
  sok_ticker       – hitta ticker utifrån bolagsnamn
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
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
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


def chat_claude(api_key: str, history: list[dict], on_tool=None, model: str = MODEL) -> str:
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



# ---------------------------------------------------------------- Groq (gratis)
def chat_groq(api_key: str, history: list[dict], on_tool=None, model: str = GROQ_MODEL) -> str:
    """Samma agent via Groqs gratisnivå (OpenAI-kompatibelt API med verktyg)."""
    import requests

    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["input_schema"]}} for t in TOOLS]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + \
        [{"role": m["role"], "content": m["content"]} for m in history]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for _ in range(MAX_TOOL_ROUNDS):
        r = requests.post(GROQ_URL, headers=headers, timeout=60, json={
            "model": model, "messages": messages, "tools": tools, "tool_choice": "auto",
            "max_completion_tokens": 1500, "temperature": 0.6,
        })
        if r.status_code == 429:
            raise RuntimeError("rate_limit: Gratiskvoten är slut för stunden – vänta en minut och försök igen.")
        if r.status_code >= 400:
            raise RuntimeError(f"Groq svarade {r.status_code}: {r.text[:300]}")
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip()
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if on_tool:
                on_tool(name, args)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": run_tool(name, args)})
    return "Jag har grävt i siffrorna länge nu – ställ frågan lite smalare så tar vi det steg för steg. 🐺"


# ---------------------------------------------------------------- Grundläge (utan AI, helt gratis)
def _pct(x) -> str:
    return "–" if x is None else f"{x * 100:+.1f} %".replace(".", ",")


def _kr(x) -> str:
    return "–" if x is None else f"{x:,.0f} kr".replace(",", " ")


def _find_tickers(text: str) -> list[str]:
    import re

    import aktielista
    low = text.lower()
    found = []
    for t, n in sorted(aktielista.POPULAR.items(), key=lambda kv: -len(kv[1])):
        base = n.lower().split(" (")[0]
        if re.search(rf"\b{re.escape(base)}\b", low) or re.search(rf"\b{re.escape(t.lower())}\b", low):
            if t not in found:
                found.append(t)
    # Bara bolagsnamn utan aktieslag, t.ex. "volvo" -> första träffen
    if not found:
        # Föredra B-aktien (oftast mest omsatt) när bara bolagsnamnet anges
        for t, n in sorted(aktielista.POPULAR.items(), key=lambda kv: (not kv[1].endswith(" B"), kv[0])):
            first = n.lower().split()[0]
            if len(first) > 3 and re.search(rf"\b{re.escape(first)}\b", low):
                found.append(t)
                break
    for m in re.findall(r"\b[A-Z0-9]{1,6}(?:-[A-Z])?\.(?:ST|CO|OL|HE)\b", text.upper()):
        if m not in found:
            found.append(m)
    return found[:3]


def _review_stock(t: str) -> str:
    d = tool_stock(t)
    if "fel" in d:
        return f"🐺 {d['fel']}"
    k = d["nyckeltal"]
    name = k.get("longName", t)
    cur = k.get("currency", "")
    kurs = f"{d['kurs']:,.2f}".replace(",", " ").replace(".", ",") if d["kurs"] else "–"
    lines = [f"### 🐺 {name} ({t})", f"Kurs: **{kurs} {cur}** (källa: {d['kurskalla']})"]
    pe, roe, mrg = k.get("trailingPE"), k.get("returnOnEquity"), k.get("profitMargins")
    dy = (k.get("dividendRate") or 0) / d["kurs"] if d["kurs"] else None
    good, bad = [], []
    if pe:
        label = " – billigt" if 0 < pe < 15 else " – dyrt" if pe > 30 else " – negativ vinst" if pe <= 0 else " – rimligt"
        (bad if pe > 30 or pe <= 0 else good).append(f"P/E {pe:.1f}".replace(".", ",") + label)
    if roe is not None:
        (good if roe > 0.15 else bad if roe < 0.05 else good).append(f"ROE {_pct(roe)}")
    if mrg is not None:
        (good if mrg > 0.10 else bad).append(f"vinstmarginal {_pct(mrg)}")
    if dy:
        good.append(f"direktavkastning {_pct(dy).lstrip('+')}")
    r1 = d["avkastning"].get("1 år")
    if r1 is not None:
        (good if r1 > 0 else bad).append(f"{_pct(r1)} senaste året")
    if d["ma200"] and d["kurs"]:
        (good if d["kurs"] > d["ma200"] else bad).append("över MA200 (upptrend)" if d["kurs"] > d["ma200"] else "under MA200 (nedtrend)")
    rsi = d["rsi14"]
    if rsi is not None and (rsi < 30 or rsi > 70):
        (good if rsi < 30 else bad).append(f"RSI {rsi:.0f} – {'översåld' if rsi < 30 else 'överköpt'}")
    if good:
        lines.append("**Det här gillar jag:** " + ", ".join(good) + ".")
    if bad:
        lines.append("**Det här ska du ha koll på:** " + ", ".join(bad) + ".")
    score = len(good) - len(bad)
    verdict = ("Lyssna nu – siffrorna ser riktigt starka ut. Men köp aldrig mer än du tål att se halveras."
               if score >= 3 else
               "Blandad bild. Inte skräp, inte fynd – dyk djupare under **Aktieanalys** innan du gör något."
               if score >= 0 else
               "Här skulle jag vara försiktig. Fler varningsflaggor än guldklimpar just nu.")
    lines.append(f"\n**Vargens dom:** {verdict}")
    vol = d["risk_1ar"].get("Volatilitet (år)")
    if vol:
        lines.append(f"Risk: svänger ungefär {_pct(vol).strip('+')} per år, största fall senaste året "
                     f"{_pct(d['risk_1ar'].get('Max drawdown'))}.")
    return "\n\n".join(lines)


def _review_portfolio() -> str:
    p = tool_portfolio()
    h = p["innehav"]
    cash = sum(k["tillgangligt_for_kop_sek"] for k in p["konton"])
    if not h:
        return ("🐺 Du har inga aktier inlagda än, kompis. Gå till **➕ Mitt innehav** – sen snackar vi."
                + (f" Du har {_kr(cash)} att köpa för, krutet finns!" if cash else ""))
    total = p.get("totalt_aktier_sek") or 0
    hs = sorted(h, key=lambda x: -(x["varde_sek"] or 0))
    top = hs[0]
    win = max(h, key=lambda x: x["orealiserat_pct"] or -9)
    lose = min(h, key=lambda x: x["orealiserat_pct"] or 9)
    lines = ["### 🐺 Vargens genomgång av din portfölj",
             f"Aktier för **{_kr(total)}** i {len(h)} innehav" + (f", plus **{_kr(cash)}** redo att investeras." if cash else ".")]
    lines.append(f"- 🏆 Bäst: **{win['ticker']}** {_pct(win['orealiserat_pct'])}")
    lines.append(f"- 🩸 Sämst: **{lose['ticker']}** {_pct(lose['orealiserat_pct'])}")
    lines.append(f"- ⚖️ Störst: **{top['ticker']}** väger {top['vikt_pct']:.0f} %".replace(".", ","))
    tips = []
    if top["vikt_pct"] and top["vikt_pct"] > 25:
        tips.append(f"{top['ticker']} är över en fjärdedel av allt. Ett dåligt kvartal där och hela portföljen blöder.")
    if len(h) < 5:
        tips.append("Under fem bolag är för tunt. Bygg ut till minst 8–10, eller komplettera med en billig indexfond.")
    if lose["orealiserat_pct"] is not None and lose["orealiserat_pct"] < -0.3:
        tips.append(f"{lose['ticker']} är ner över 30 %. Fråga dig: skulle du köpa den idag? Om nej – varför äger du den?")
    if cash and total and cash / (cash + total) > 0.2:
        tips.append("Över 20 % i kontanter. Pengar som ligger still växer inte – men köp inte bara för att köpa.")
    types = {k["typ"] for k in p["konton"]}
    if "AF" in types and "ISK" not in types:
        tips.append("Bara AF-konto? Med 300 000 kr skattefritt på ISK 2026 kan det löna sig att spara där.")
    if tips:
        lines.append("\n**Mina råd:**\n" + "\n".join(f"- {t}" for t in tips))
    else:
        lines.append("\nSnyggt balanserat. Fortsätt så – låga avgifter, spridning och tålamod vinner.")
    lines.append("\n_Inte personlig rådgivning – du fattar besluten._")
    return "\n".join(lines)


def offline_answer(question: str) -> str:
    """Regelbaserat svar utan AI – kostar ingenting och kräver ingen nyckel."""
    q = question.lower()
    tickers = _find_tickers(question)
    if tickers:
        return "\n\n---\n\n".join(_review_stock(t) for t in tickers)
    if any(w in q for w in ["portfölj", "innehav", "mina aktier", "min aktie", "risk", "hur går", "hur ser"]):
        return _review_portfolio()
    if any(w in q for w in ["köpa", "pengar", "idé", "tips", "investera", "vad ska jag"]):
        cash = sum(db.get_cash().values())
        return ("### 🐺 Pengar som bränner i fickan?\n\n"
                + (f"Du har **{_kr(cash)}** att köpa för. " if cash else "")
                + "Mitt recept: 1) kolla **💡 Tips & insikter → Aktieidéer** – där screenar jag fram kvalitet till "
                  "rimligt pris, momentumledare och utdelningscase. 2) Fråga mig om en specifik aktie, t.ex. "
                  "*\"Vad tycker du om Investor B?\"* 3) Sprid köpen över tid – ingen vet vart börsen går nästa vecka.\n\n"
                  "_Inte personlig rådgivning._")
    return ("🐺 Lyssna nu. I grundläget kan jag:\n"
            "- **Gå igenom din portfölj** – skriv *\"Hur ser min portfölj ut?\"*\n"
            "- **Analysera en aktie** – skriv t.ex. *\"Vad tycker du om Volvo B?\"* eller en ticker som *SAAB-B.ST*\n"
            "- **Ge köpidéer** – skriv *\"Jag har pengar att investera\"*\n\n"
            "Vill du kunna prata fritt med mig? Koppla in en gratis AI-nyckel – instruktionen finns här under.")


def chat(provider: str, api_key: str | None, history: list[dict], on_tool=None) -> str:
    if provider == "groq":
        return chat_groq(api_key, history, on_tool)
    if provider == "claude":
        return chat_claude(api_key, history, on_tool)
    return offline_answer(history[-1]["content"])
