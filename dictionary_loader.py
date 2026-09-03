"""
dictionary_loader.py
---------------------
Haalt de officiële Nederlandse OpenTaal-woordenlijst op en zet hem om
naar een vorm die daadwerkelijk op een Wordfeud-bord gelegd kan worden.

Waarom OpenTaal specifiek? Wordfeud heeft dit zelf bevestigd op hun
devblog: hun Nederlandse woordenboek is gebaseerd op de OpenTaal-
woordenlijst 2.10, aangevuld en gefilterd volgens de regels van de
Nederlandse Scrabble-bond. Het is dus niet "een" willekeurige lijst,
maar de daadwerkelijke bron. Belangrijk voor dit project: de lijst
bevat, naast ~200.000 basiswoorden, ook ~170.000 "flexies" (vervoegingen
en verbuigingen zoals 'werke', 'stoeltjes', 'grotere') -- precies de
vervoegingen die je zei dat Wordfeud accepteert. Afkortingen komen er
nauwelijks in voor, dus die hoeven we niet apart uit te filteren.

BELANGRIJK -- bordtranscriptie:
Een Wordfeud-tegel kent alleen de 26 gewone letters (geen accenten,
koppeltekens of apostrofs). Een woord met een accent of trema wordt op
het bord dus getranscribeerd naar gewone letters. Wordfeud zelf geeft
als voorbeelden (devblog):
    geëerd   -> geeerd   (trema/accent weg, letter blijft gewoon staan)
    zee-egel -> zeeegel  (koppelteken weg, gewoon aan elkaar geplakt)
    taxi's   -> taxis    (apostrof weg)
We passen dezelfde transformatie toe op de hele woordenlijst, zodat de
Trie alleen woorden bevat in de vorm die je ook echt op het bord kunt
leggen.
"""

from __future__ import annotations

import unicodedata

OPENTAAL_WORDLIST_URL = (
    "https://raw.githubusercontent.com/OpenTaal/opentaal-wordlist/master/wordlist.txt"
)

# Extra tekens die simpelweg verwijderd worden (geen tegel voor bestaat).
_STRIP_CHARS = "'-. /+&@€"


def normalize_for_board(word: str) -> str | None:
    """
    Zet een woordenboek-woord om naar de vorm zoals die op het Wordfeud-
    bord gelegd zou worden: accenten/trema's weg (NFKD-decompositie +
    combining marks strippen), koppeltekens/apostrofs/spaties weg,
    resultaat in hoofdletters.

    Geeft None terug als er na normalisatie nog niet-alfabetische tekens
    overblijven (bv. cijfers, €-tekens) -- zulke "woorden" horen niet in
    de speel-Trie thuis.
    """
    # NFKD splitst bv. 'ë' in 'e' + combinerend trema-teken; we houden
    # alleen de basisletter over door combining marks (categorie 'Mn') weg te gooien.
    decomposed = unicodedata.normalize("NFKD", word)
    base_letters = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")

    cleaned = "".join(ch for ch in base_letters if ch not in _STRIP_CHARS)
    cleaned = cleaned.upper()

    if not cleaned or not cleaned.isalpha():
        return None
    return cleaned


def is_likely_proper_noun(original_word: str) -> bool:
    """
    OpenTaal's wordlist.txt bevat naast gewone woorden ook eigennamen
    (Jansen, Facebookgroep, Schin op Geul...) uit basiswoorden-ongekeurd.txt.
    Nederlandse eigennamen beginnen met een hoofdletter; gewone
    zelfstandige naamwoorden in de lijst staan in kleine letters. Dit is
    een heuristiek, geen garantie -- maar filtert het overgrote deel van
    de eigennamen eruit.
    """
    return original_word[:1].isupper()


def download_opentaal_wordlist(
    url: str = OPENTAAL_WORDLIST_URL,
    min_length: int = 2,
    max_length: int = 15,
    timeout: int = 60,
) -> set[str]:
    """
    Download en verwerk de volledige OpenTaal-woordenlijst tot een set
    board-klare, hoofdletter-woorden.

    LET OP: dit vereist internettoegang. In de Claude-sandbox waarin dit
    bestand geschreven is, is die toegang uitgeschakeld -- deze functie
    is dus getest op logica maar NIET live tegen de echte URL. Op
    Streamlit Community Cloud (of je eigen laptop) werkt dit gewoon,
    want die omgevingen hebben wel internettoegang.
    """
    import requests  # lokale import: alleen nodig als deze functie ook echt wordt aangeroepen

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"

    words: set[str] = set()
    for line in response.text.splitlines():
        original = line.strip()
        if not original or is_likely_proper_noun(original):
            continue
        normalized = normalize_for_board(original)
        if normalized is None:
            continue
        if not (min_length <= len(normalized) <= max_length):
            continue
        words.add(normalized)

    return words


if __name__ == "__main__":
    # Zelftest van de normalisatie-logica (geen netwerk nodig)
    tests = {
        "geëerd": "GEEERD",
        "zee-egel": "ZEEEGEL",
        "taxi's": "TAXIS",
        "café": "CAFE",
        "hond": "HOND",
        "CO₂-emissie": None,  # bevat een subscript-cijfer -> geen geldig bordwoord
    }
    for word, expected in tests.items():
        result = normalize_for_board(word)
        status = "OK" if result == expected else "FOUT"
        print(f"[{status}] normalize_for_board({word!r}) = {result!r} (verwacht: {expected!r})")

    print()
    print("is_likely_proper_noun('Jansen'):", is_likely_proper_noun("Jansen"))   # True
    print("is_likely_proper_noun('tafel'): ", is_likely_proper_noun("tafel"))    # False
