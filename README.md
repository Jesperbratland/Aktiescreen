# 📈 Aktiescreen

En portföljdashboard och aktiescreener byggd i Streamlit. Mata in dina köp, sälj och utdelningar, följ portföljen mot index, analysera enskilda aktier och screena efter idéer.

## Kom igång

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Appen öppnas på http://localhost:8501. Klicka **Ladda exempelportfölj** på Översikt för att testa direkt.

## Sidor

| Sida | Innehåll |
|---|---|
| **🐺 Fråga Vargen** | Aktieexpert (påhittad mäklarkaraktär) som ser din portfölj. **Grundläge** helt gratis utan nyckel (regelbaserade analyser). **AI-läge** gratis via Groq: lägg `GROQ_API_KEY` i Streamlit Secrets . |
| **Översikt** | Marknadsvärde, dagens förändring, orealiserat/realiserat resultat, utdelningar. Fördelning per innehav/valuta/sektor. Värde vs insatt kapital. Tidsviktad avkastning (TWR) mot OMXS30, S&P 500 m.fl. |
| **Portföljbetyg** | Betyg 0–100 (A+–E) från åtta delbetyg: spridning, branscher & länder, kvalitet, värdering, risk, avkastning, avgifter & skatt och kontanter. Styrkor, konkreta förbättringar, risk på djupet (beta, stresstest, riskbidrag, korrelation), förväntad utdelning och betyget över tid. Litet betygskort på Översikten. |
| **Mitt innehav** | **Importera alla affärer från Avanza** (CSV-export) med exakt GAV, courtage och valutakurser. Lägg till aktier genom att skriva bolagsnamnet – ticker och valuta hittas automatiskt. Lista över dina aktier per konto med ta bort-knapp. **Pengar för köp** per konto (sätt in, ta ut, ange saldo) som uppdateras automatiskt vid köp, sälj och utdelning. Konton (ISK, KF, AF), mäklare och courtageklass. |
| **Skatt & avgifter** | Uppskattad ISK/KF-schablonskatt (kvartalsvärden, 300 000 kr fribelopp 2026), skatt på vinster/utdelningar på AF med K4-underlag, courtage och valutaväxling, tips om courtageklass samt jämförelse ISK vs AF. |
| **Transaktioner** | Formulär för köp/sälj/utdelning (valutakurs hämtas automatiskt), redigerbar tabell, CSV-import/export, tickersök på bolagsnamn, realiserat resultat per aktie. |
| **Bevakningslista** | Aktier du spanar på med minigraf, RSI, trend, avstånd från 52-veckorshögsta och anteckningar. Kurslarm för köp under/sälj över visas på sidan och på Översikten. |
| **Kalender & nyheter** | Kommande rapporter, X-dagar och utbetalningar; utdelningsprognos 12 månader (per månad och bolag); nyheter från Yahoo Finance och Google Nyheter; insynshandel från Finansinspektionens insynsregister (svenska bolag) och Yahoo (utländska). Visas också per aktie i Aktieanalys och som "På gång" på Översikten. |
| **Aktieanalys** | **🧭 Analysguide** i sex steg (bolaget, kvalitet, värdering med rimligt värde, trend & köpsignal, risk & positionsstorlek, beslut) med 🟢🟡🔴 och förklaringar, köpläge-poäng, checklista och knappar för att bevaka med köpkurs. Dessutom candlestick med MA20/50/200, Bollinger, RSI, MACD, volym. Dina köp/sälj och ditt GAV i grafen. Avkastning per period, Sharpe, Sortino, max drawdown, beta, nyckeltal, analytikerkonsensus, jämförelse mot andra aktier. |
| **Screener** | Färdiga urval (Sverige large/mid cap, Norden, USA) eller egen lista. Filter på P/E, direktavkastning, ROE, RSI, momentum, MA200, sektor. Viktbar poäng för Värde / Kvalitet / Momentum / Utdelning. |
| **Mål & sparkalkyl** | Hur mycket behöver du spara per månad för att nå ett belopp? Diagram med troligt, dåligt och bra utfall (Monte Carlo) samt bara insatta pengar, och chansen att nå målet. |
| **Tips & insikter** | Portföljhälsa (koncentration, sektor, valuta, stora förlorare/vinnare), tekniska signaler på dina innehav och aktieidéer enligt fyra strategier. |

## Lagring

Utan inställning sparas allt i `data/portfolio.db` (töms vid omstart på Streamlit Cloud). Lägg `DATABASE_URL` (gratis Postgres hos Neon) i Streamlit Secrets för permanent lagring – befintlig data flyttas över automatiskt. Under **⚙️ Inställningar** finns guide och säkerhetskopia (JSON).

## Inloggning

Sätt `APP_PASSWORD` i Streamlit Secrets så måste lösenordet skrivas in varje gång hemsidan öppnas. 5 fel inom 15 minuter ger en paus, 20 fel inom ett dygn låser i 24 timmar (Reboot app låser upp). Se `auth.py`.

## Kurser

Välj kurskälla i sidomenyn. *Avanza* hämtar realtidskurser för nordiska aktier från Avanzas öppna, inofficiella webbtjänst (ingen inloggning). Svarar den inte används Yahoo Finance automatiskt. Historik och nyckeltal kommer alltid från Yahoo.

## Så räknas det

- **GAV** – genomsnittsmetoden, samma som Skatteverket använder. Courtage ingår i anskaffningsvärdet.
- **Valuta** – varje affär räknas om till SEK med valutakursen den dagen. Courtage och källskatt anges i SEK.
- **Utdelning** – ange antal aktier och utdelning per aktie i aktiens valuta, och källskatten som avgift.
- **TWR** – tidsviktad avkastning, opåverkad av insättningar och uttag, så att den går att jämföra rättvist med ett index.

## Tickers

Yahoo Finance-format: `VOLV-B.ST` (Stockholm), `NOVO-B.CO` (Köpenhamn), `EQNR.OL` (Oslo), `NOKIA.HE` (Helsingfors), `AAPL` (USA). Använd sökrutan under Transaktioner om du är osäker.

## CSV-format

```csv
date,account,ticker,type,quantity,price,fee,currency,fx_rate,note
2024-03-01,ISK Avanza,VOLV-B.ST,KÖP,100,265.5,69,SEK,1,
2024-05-10,ISK Avanza,AAPL,KÖP,10,183.0,49,USD,10.62,
2024-04-12,ISK Avanza,VOLV-B.ST,UTDELNING,100,18,0,SEK,1,
```

`type` är `KÖP`, `SÄLJ` eller `UTDELNING`. Det går också med `BUY`, `SELL` och `DIVIDEND`.

## Begränsningar

- Yahoo Finance är gratis men inofficiellt. Kurser kan vara fördröjda och nyckeltal saknas ibland, särskilt för mindre svenska bolag.
- Data sparas lokalt i `data/portfolio.db` (SQLite). Gör backup via CSV-export.
- Signaler och tips är regelbaserade och ska inte ses som finansiell rådgivning.

## Driftsätta som hemsida

1. Lägg koden på GitHub (filen `data/portfolio.db` är exkluderad via `.gitignore`).
2. Gå till [share.streamlit.io](https://share.streamlit.io), koppla ditt repo och välj `app.py`.
3. Obs: Streamlit Community Cloud har ingen beständig disk. Databasen nollställs vid omstart, så använd CSV-export/import eller byt till en extern databas (t.ex. Supabase/Postgres). Ett förslag på hur finns i `CLAUDE.md`.
