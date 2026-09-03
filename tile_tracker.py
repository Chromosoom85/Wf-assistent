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

    # Wat WIJ zelf zeker weten dat op ons eigen rack ligt (blijft NIET in
    # 'remaining' zitten aftrekken via mark_seen, maar wordt apart bijgehouden
    # zodat we het onderscheid met "in de pot" kunnen maken voor de eindspel-som).
    own_rack: Counter = field(default_factory=Counter)
    on_board: Counter = field(default_factory=Counter)

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

    # ------------------------------------------------------------------
    def remaining_in_bag(self) -> int:
        """
        Totaal aantal stenen dat nog ONVERDEELD is over pot + tegenstander-rack.
        Dit is: alles wat nog 'remaining' is, MINUS wat wij zelf op ons eigen
        rack hebben (want dat weten we al zeker, dat zit niet meer in de pot).
        """
        return sum(self.remaining.values()) - sum(self.own_rack.values())

    def is_bag_empty(self) -> bool:
        return self.remaining_in_bag() <= 0

    def deduce_opponent_rack(self) -> Counter | None:
        """
        Zodra de pot leeg is (remaining_in_bag() == 0), staat het exacte
        multiset van de tegenstander vast: het is precies 'remaining' zelf,
        want remaining bevat op dat punt alleen nog de letters die NERGENS
        zichtbaar zijn (niet op bord, niet op ons rack) -- en die kunnen dan
        alleen nog bij de tegenstander liggen.

        Retourneert None als de pot nog niet leeg is (dan is deductie nog
        niet 100% zeker, hooguit een kansinschatting -- zie estimate_opponent_probabilities).
        """
        if not self.is_bag_empty():
            return None
        # Alles wat nog 'remaining' is (en dus niet ons eigen rack is)
        # moet bij de tegenstander liggen.
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
        pot_only = Counter(self.remaining)
        # own_rack is al zeker, dus die tellen niet mee als "onbekend"
        for letter, n in self.own_rack.items():
            pot_only[letter] -= n
        return {
            letter: count / total_unknown
            for letter, count in pot_only.items()
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
