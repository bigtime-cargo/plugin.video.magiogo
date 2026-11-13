# -*- coding: utf-8 -*-
"""Filtrovanie kanálov Magio GO: kanály, ktoré už sú v doplnku O2 TV
(duplicity), a regionálne/lokálne stanice. Bez importov Kodi (testovateľné)."""
import re

from kanaly_skupiny import normalize, tema

# Kanály Magio GO, ktoré má používateľ aj na O2 TV (porovnané 13. 11. 2026
# s playlistom O2 TV). Mená sú tak, ako ich vracia Magio GO; porovnáva sa
# normalizovaný názov bez "HD".
O2_KANALY = [
    "Jednotka HD", "Dvojka HD", "Markíza HD", "JOJ HD", "Plus HD",
    "JOJ KRIMI HD", "Doma HD", "DAJTO HD", "Jojko HD", "ČT1 HD", "ČT2 HD",
    "Prima SK HD", "JOJ 24 HD", "TA3 HD", "24 HD", "CNN Prima News HD",
    "ČT24 HD", "Prima COOL SK HD", "Prima KRIMI SK HD", "Markíza KRIMI HD",
    "Markíza Klasik HD", "Prima LOVE SK HD", "ŠPORT HD", "Lux TV HD",
    "Kanal 1 HD", "Kino Barrandov HD", "Šláger Originál HD",
]

# Regionálne a lokálne televízie Magio GO majú čísla 500-599.
REGIONAL_FROM, REGIONAL_TO = 500, 599


def _key(name):
    return " ".join(re.sub(r"\b(hd|uhd|4k|sd|fhd)\b", " ", normalize(name)).split())


_O2 = {_key(n) for n in O2_KANALY}


def je_na_o2(name):
    return _key(name) in _O2


def je_regionalny(chan):
    n = chan.get("number")
    try:
        if n is not None and REGIONAL_FROM <= int(n) <= REGIONAL_TO:
            return True
    except (TypeError, ValueError):
        pass
    return tema(chan.get("name", "")) == "Regionálne"


def filter_channels(chans, hide_o2=True, hide_regional=True):
    out = []
    for c in chans:
        if hide_o2 and je_na_o2(c.get("name", "")):
            continue
        if hide_regional and je_regionalny(c):
            continue
        out.append(c)
    return out
