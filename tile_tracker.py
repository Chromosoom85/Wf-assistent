"""
tile_tracker.py
----------------
Houdt de "pot" (bag) van Nederlandse Wordfeud-stenen bij: 104 stenen
totaal, elk met een vaste puntwaarde. Elke keer dat een steen zichtbaar
wordt (op het bord ligt, OF op jouw eigen rack ligt) wordt hij uit de
pot gehaald.

Kernfunctie voor het eindspel: zodra remaining_in_bag() == 0 weten we
dat ALLE 104 stenen verdeeld zijn over (bord + jouw rack + rack van de
tegenstander). Trek je dus (bord + eigen rack) af van de totale
distributie, dan hou je exact de 7 (of minder) letters van de
tegenstander over.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


# ----------------------------------------------------------------------
# Officiële Nederlandse Wordfeud-letterverdeling (104 stenen, incl. 2 blanco's)
# Bron: puntwaarde is omgekeerd evenredig aan hoe vaak de letter voorkomt.
# ----------------------------------------------------------------------
DUTCH_TILE_DISTRIBUTION: dict[str, int] = {
    "A": 7, "B": 2, "C": 2, "D": 5, "E": 18, "F": 2, "G": 3, "H": 2,
    "I": 4, "J": 2, "K": 3, "L": 3, "M": 3, "N": 11, "O": 6, "P": 2,
    "Q": 1, "R": 5, "S": 5, "T": 5, "U": 3, "V": 2, "W": 2, "X": 1,
    "Y": 1, "Z": 2,
    "*": 2,  # blanco / joker
}

DUTCH_TILE_POINTS: dict[str, int] = {
    "A": 1, "B": 4, "C": 5, "D": 2, "E": 1, "F": 4, "G": 3, "H": 4,
    "I": 2, "J": 4, "K": 3, "L": 3, "M": 3, "N": 1, "O": 1, "P": 4,
    "Q": 10, "R": 2, "S": 2, "T": 2, "U": 2, "V": 4, "W": 5, "X": 8,
    "Y": 8, "Z": 5,
    "*": 0,  # blanco is altijd 0 punten, ongeacht welke letter hij vertegenwoordigt
}

TOTAL_TILES = sum(DUTCH_TILE_DISTRIBUTION.values())  # == 104


@dataclass
class TileTracker:
    """
    remaining: hoeveel van elke letter nog "onbekend" is (dus: nog in de
    pot óf in het rack van de tegenstander -- die twee zijn ononderscheidbaar
    totdat de pot leeg is).
    """

    remaining: Counter = field(
        default_factory=lambda: Counter(DUTCH_TILE_DISTRIBUTION)
    )
    points: dict[str, int] = field(default_factory=lambda: dict(DUTCH_TILE_POINTS))

    # Wat WIJ zelf zeker weten dat op ons eigen rack ligt. Dit is een
    # SUBSET-administratie bovenop 'remaining' (puur boekhouding/debug om
    # onderscheid te kunnen maken tussen "op mijn rack" en "op het bord"),
    # GEEN aparte aftrekpost -- mark_seen() haalt een steen sowieso al uit
    # 'remaining' zodra hij ergens zichtbaar wordt, ongeacht de locatie.
    own_rack: Counter = field(default_factory=Counter)
    on_board: Counter = field(default_factory=Counter)

    # Hoeveel tegels de tegenstander OP DIT MOMENT vasthoudt. Nodig om te
    # bepalen wanneer de pot écht leeg is: dat is namelijk NIET wanneer
    # remaining_in_bag() precies 0 is, maar wanneer alle nog onbekende
    # tegels precies passen in de hand van de tegenstander (normaal 7,
    # maar minder na een net gespeelde bingo, vlak voor ze bijtrekken).
    # Standaard 7 (de normale situatie); pas 'm aan zodra je weet dat de
    # tegenstander met minder tegels zit.
    opponent_rack_size: int = 7

    # ------------------------------------------------------------------
    def mark_seen(self, letter: str, count: int = 1, location: str = "board") -> None:
        """
        Trek 'count' exemplaren van 'letter' uit de pot, omdat ze zichtbaar
        zijn geworden (op het bord gelegd, of getrokken op je eigen rack).

        location: "board" of "rack" -- puur voor boekhouding/debug, telt
        voor de pot-berekening exact hetzelfde.
        """
        letter = letter.upper()
        if letter not in self.remaining:
            raise ValueError(f"Onbekende letter/tegel: {letter!r}")
        if self.remaining[letter] < count:
            raise ValueError(
                f"Kan niet {count}x '{letter}' aftrekken: nog maar "
                f"{self.remaining[letter]} onbekend/beschikbaar."
            )
        self.remaining[letter] -= count
        if location == "rack":
            self.own_rack[letter] += count
        else:
            self.on_board[letter] += count

    def unmark(self, letter: str, count: int = 1, location: str = "board") -> None:
        """Corrigeer een fout (bv. OCR heeft een letter verkeerd gelezen)."""
        letter = letter.upper()
        self.remaining[letter] += count
        if location == "rack":
            self.own_rack[letter] -= count
        else:
            self.on_board[letter] -= count

    def move_rack_to_board(self, letter: str, count: int = 1) -> None:
        """
        Een tegel die op je EIGEN rack lag, wordt nu op het bord gelegd
        (je speelt 'm). Dit verandert NIETS aan hoeveel stenen nog onbekend
        zijn (hij was al 'gezien') -- alleen de boekhouding van WELKE
        zichtbare plek hij inneemt verschuift van rack naar bord. Gebruik
        dit i.p.v. los unmark()+mark_seen(), zodat deze transitie altijd in
        één keer en correct gebeurt (bv. bij het toepassen van een zet).
        """
        letter = letter.upper()
        if self.own_rack[letter] < count:
            raise ValueError(
                f"Kan niet {count}x '{letter}' van rack naar bord verplaatsen: "
                f"slechts {self.own_rack[letter]} op het rack bekend."
            )
        self.own_rack[letter] -= count
        self.on_board[letter] += count
        # 'remaining' blijft ongewijzigd: de steen was al gezien (op rack),
        # en blijft gezien (nu op bord) -- nooit opnieuw "onbekend".

    # ------------------------------------------------------------------
    def remaining_in_bag(self) -> int:
        """
        Totaal aantal stenen dat nog ONVERDEELD is over pot + tegenstander-
        rack. 'remaining' registreert AL exact dit aantal: mark_seen() haalt
        een steen er sowieso uit zodra hij ergens zichtbaar wordt (rack √≥f
        bord), dus een aparte aftrek van own_rack hier zou diezelfde stenen
        een tweede keer aftrekken. (Dat gebeurde eerder ook echt: bij een
        rack van 7 stenen gaf dat toevallig geen zichtbaar probleem omdat
        beide spelers meestal evenveel stenen op hun rack hebben, maar bij
        een onvolledig rack -- bv. vlak na een bingo, of tegen het einde van
        de pot -- gaf het een structureel verkeerde uitkomst.)
        """
        return sum(self.remaining.values())

    def is_bag_empty(self) -> bool:
        """
        De POT (niet: pot+tegenstanderrack) is leeg zodra alle nog
        onbekende tegels precies passen in de hand van de tegenstander --
        dus als remaining_in_bag() <= opponent_rack_size, NIET simpelweg
        als remaining_in_bag() == 0. (Die laatste aanname klopte in eerdere
        tests toevallig steeds, puur omdat de tegenstander daar ook telkens
        7 tegels had -- bij een ander aantal geeft dat een verkeerde uitkomst.)
        """
        return self.remaining_in_bag() <= self.opponent_rack_size

    def deduce_opponent_rack(self) -> Counter | None:
        """
        Zodra de pot leeg is EN het aantal nog onbekende tegels exact
        overeenkomt met de bekende rackgrootte van de tegenstander, staat
        hun exacte multiset vast: het is precies 'remaining' zelf.

        Retourneert None als de pot nog niet leeg is (dan is deductie nog
        niet 100% zeker, hooguit een kansinschatting -- zie
        estimate_opponent_probabilities), OF als remaining_in_bag() kleiner
        is dan opponent_rack_size (inconsistente/onvolledige data -- dan is
        een betrouwbare deductie niet mogelijk).
        """
        if not self.is_bag_empty():
            return None
        if self.remaining_in_bag() != self.opponent_rack_size:
            return None
        opponent = Counter({k: v for k, v in self.remaining.items() if v > 0})
        return opponent

    def estimate_opponent_probabilities(self) -> dict[str, float]:
        """
        Zolang de pot nog niet leeg is: kans dat een willekeurige
        onbekende steen een bepaalde letter is = remaining[letter] / totaal_remaining.
        Handig voor een 'risico-inschatting' voordat het eindspel echt begint.
        """
        total_unknown = self.remaining_in_bag()
        if total_unknown <= 0:
            return {}
        # 'remaining' sluit own_rack al uit (zie remaining_in_bag) -- geen
        # aparte correctie hier nodig.
        return {
            letter: count / total_unknown
            for letter, count in self.remaining.items()
            if count > 0
        }

    def score_for(self, letter: str) -> int:
        return self.points.get(letter.upper(), 0)

    def snapshot(self) -> dict:
        """Compact overzicht, handig om als JSON terug te sturen naar de UI/APK."""
        return {
            "remaining_in_bag": self.remaining_in_bag(),
            "remaining_per_letter": dict(self.remaining),
            "own_rack": dict(self.own_rack),
            "on_board": dict(self.on_board),
        }


if __name__ == "__main__":
    tracker = TileTracker()
    print("Totaal aantal stenen (moet 104 zijn):", TOTAL_TILES)
    print("Stenen nog onverdeeld bij start:", tracker.remaining_in_bag())

    # Simuleer: wij trekken een rack
    for letter in "HUISJE":
        tracker.mark_seen(letter, location="rack")

    # Simuleer: er liggen al wat letters op het bord
    for letter in "KAT":
        tracker.mark_seen(letter, location="board")

    print("Na rack + bord, nog onverdeeld:", tracker.remaining_in_bag())
    print("Kansinschatting tegenstander (fragment):")
    probs = tracker.estimate_opponent_probabilities()
    for letter, p in sorted(probs.items(), key=lambda kv: -kv[1])[:5]:
        print(f"  {letter}: {p:.1%}")
