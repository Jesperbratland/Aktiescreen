"""Förklaringar av börsbegrepp – visas när man håller musen över ⓘ eller frågetecknet."""
from __future__ import annotations

import html

import streamlit as st

TERMS: dict[str, str] = {
    # Pris och storlek
    "Senaste kurs": "Senaste priset för en aktie. Procenten visar förändringen sedan gårdagens stängning.",
    "Börsvärde": "Vad hela bolaget är värt på börsen: aktiekursen × antal aktier. mdr = miljarder.",
    "52v intervall": "Lägsta och högsta kurs de senaste 52 veckorna (ett år). Visar hur mycket aktien brukar röra sig.",
    "Direktavkastning": "Årlig utdelning delat med aktiekursen. 4 % betyder att du får ungefär 4 kr per 100 kr "
                        "investerat varje år.",
    # Värdering
    "P/E": "Pris per vinst: aktiekursen delat med vinsten per aktie senaste året. P/E 15 betyder att du betalar "
           "15 kr för varje krona bolaget tjänar. Lågt = billigt, högt = marknaden väntar sig stark tillväxt. "
           "Börsen i snitt brukar ligga runt 15–20.",
    "P/E (12m)": "Pris per vinst senaste 12 månaderna. Lågt = billigt i förhållande till vinsten.",
    "P/E (framåt)": "Som P/E, men med analytikernas förväntade vinst kommande år. Lägre än vanliga P/E betyder att "
                    "vinsten väntas öka.",
    "PEG": "P/E delat med vinsttillväxten. Under 1 räknas ofta som billigt med tanke på tillväxten, över 2 som dyrt.",
    "P/S": "Pris per försäljning: börsvärdet delat med omsättningen. Används för bolag som ännu inte går med vinst.",
    "P/B": "Pris per eget kapital (bokfört värde). Under 1 betyder att aktien kostar mindre än bolagets nettotillgångar "
           "enligt bokföringen. Vanligt för banker och fastighetsbolag.",
    "EV/EBITDA": "Bolagets totala värde inklusive skulder delat med rörelseresultat före avskrivningar. Jämför bolag "
                 "med olika skuldsättning. Under 10 brukar räknas som lågt.",
    # Lönsamhet och tillväxt
    "ROE": "Avkastning på eget kapital: hur mycket vinst bolaget gör på ägarnas pengar. Över 15 % är bra, över 20 % "
           "mycket bra.",
    "Vinstmarginal": "Hur många kronor av varje försäljningskrona som blir vinst. 10 % = 10 öre per krona.",
    "Bruttomarginal": "Andel av försäljningen kvar efter direkta kostnader för varorna. Högt tyder på starkt varumärke "
                      "eller prissättningsmakt.",
    "Omsättningstillväxt": "Hur mycket försäljningen har ökat jämfört med samma period året innan.",
    "Vinsttillväxt": "Hur mycket vinsten har ökat jämfört med samma period året innan.",
    "Skuld/EK (%)": "Skulder i förhållande till eget kapital. 50 % = skulderna är hälften så stora som eget kapital. "
                    "Högt = mer sårbart om räntorna stiger eller vinsten faller.",
    "Utdelningsandel": "Andel av vinsten som delas ut. Över 100 % betyder att bolaget delar ut mer än det tjänar, "
                       "vilket sällan håller i längden.",
    "Analytikers riktkurs": "Genomsnittet av analytikernas bedömning av vad aktien är värd om ca ett år. "
                            "Ofta fel – se det som en fingervisning.",
    "Analytikerkonsensus": "Vad analytikerna i snitt rekommenderar: strong buy, buy, hold (behåll), sell.",
    # Avkastning och risk
    "Total avkastning": "Hur mycket kursen har ändrats under hela den valda perioden.",
    "CAGR": "Genomsnittlig årlig tillväxt: hur mycket aktien har vuxit per år i snitt, med ränta-på-ränta.",
    "Volatilitet (år)": "Hur mycket kursen svänger under ett år. 20 % betyder att den normalt kan röra sig ungefär "
                        "±20 % på ett år. Högre = mer risk.",
    "Sharpe": "Avkastning i förhållande till risk. Över 1 är bra, över 2 mycket bra, under 0 = sämre än räntan.",
    "Sortino": "Som Sharpe, men räknar bara nedåtsvängningar som risk. Högre är bättre.",
    "Max drawdown": "Största fallet från en topp till en botten under perioden. Visar hur ont det kan göra.",
    "Nuvarande drawdown": "Hur långt under sin högsta kurs (under perioden) aktien ligger just nu.",
    "Beta": "Hur mycket aktien rör sig jämfört med börsen. 1 = som börsen, 1,5 = 50 % mer upp och ner, "
            "0,5 = hälften så mycket.",
    # Tekniska indikatorer
    "MA20": "Glidande medelvärde 20 dagar – genomsnittskursen senaste månaden. Visar kortsiktig trend.",
    "MA50": "Glidande medelvärde 50 dagar – ungefär ett kvartal. Visar mellanlång trend.",
    "MA200": "Glidande medelvärde 200 dagar – ungefär ett år. Kursen över MA200 räknas som upptrend.",
    "Bollinger": "Ett band runt MA20 som visar normala svängningar. Utanför bandet = ovanligt stor rörelse.",
    "RSI": "Mäter hur snabbt kursen har rört sig senaste 14 dagarna (0–100). Under 30 = översåld, över 70 = överköpt.",
    "MACD": "Skillnaden mellan två glidande medelvärden. När MACD korsar sin signallinje uppåt ses det som köpsignal.",
    "Volym": "Hur många aktier som handlats per dag. Hög volym vid en rörelse gör den mer betydelsefull.",
    # Perioder
    "1 v": "Avkastning senaste veckan.", "1 m": "Avkastning senaste månaden.",
    "3 m": "Avkastning senaste tre månaderna.", "6 m": "Avkastning senaste halvåret.",
    "1 år": "Avkastning senaste året.", "3 år": "Avkastning senaste tre åren (totalt, inte per år).",
    "5 år": "Avkastning senaste fem åren (totalt, inte per år).", "i år": "Avkastning sedan nyår.",
}


def explain(term: str) -> str | None:
    if term in TERMS:
        return TERMS[term]
    if term.startswith("Beta"):
        return TERMS["Beta"]
    return None


def table(rows: list[tuple[str, str]], label: str = "", value: str = "") -> None:
    """Tabell där varje begrepp har en ⓘ som visar förklaringen när man håller musen över den."""
    head = (f"<tr><th>{html.escape(label)}</th><th style='text-align:right'>{html.escape(value)}</th></tr>"
            if label else "")
    body = []
    for term, val in rows:
        tip = explain(term)
        icon = (f" <span class='term-i'>ⓘ<span class='term-tip'>{html.escape(tip)}</span></span>") if tip else ""
        body.append(f"<tr><td>{html.escape(term)}{icon}</td><td style='text-align:right'>{html.escape(str(val))}</td></tr>")
    st.markdown(f"<table class='terms'>{head}{''.join(body)}</table>", unsafe_allow_html=True)


CSS = """
table.terms {width: 100%; border-collapse: collapse; font-size: .92rem; background: #142721;
             border-radius: 14px; overflow: visible;}
table.terms th {color: #A8B5AE; font-weight: 500; font-size: .8rem; text-align: left; padding: .5rem .8rem;}
table.terms td {padding: .45rem .8rem; border-top: 1px solid rgba(244,239,230,.06);}
.term-i {color: #8A9A93; cursor: help; position: relative; font-size: .85em; margin-left: .2rem;}
.term-i:hover {color: #E8B44C;}
.term-tip {visibility: hidden; opacity: 0; position: absolute; z-index: 1000; left: -0.6rem; top: 1.5rem;
           width: 280px; background: rgba(20,39,33,.98); color: #F4EFE6; border: 1px solid rgba(244,239,230,.12);
           border-radius: 12px; padding: .6rem .75rem; font-size: .82rem; line-height: 1.35; font-weight: 400;
           box-shadow: 0 8px 24px rgba(0,0,0,.35); transition: opacity .12s ease; pointer-events: none;}
.term-i:hover .term-tip {visibility: visible; opacity: 1;}
"""
