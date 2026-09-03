"""
board_skeleton.py
------------------
Conceptueel skelet van het 15x15 Wordfeud-bord + de aanpak voor het
efficiënt vinden van (parallelle) woorden, inclusief de "Safety Index"
voor defensieve zetten.

Dit bestand is bewust nog GEEN volledig werkende move-generator (dat is
stap 2). Het doel hier is de datastructuren en het algoritme-ontwerp
vast te leggen, zodat de echte GADDAG/cross-check implementatie er
straks 1-op-1 op aansluit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

BOARD_SIZE = 15


class Bonus(Enum):
    NONE = "  "
    DL = "DL"   # dubbele letterwaarde
    TL = "TL"   # driedubbele letterwaarde
    DW = "DW"   # dubbele woordwaarde
    TW = "TW"   # driedubbele woordwaarde
    START = "★"


def default_bonus_grid() -> list[list[Bonus]]:
    """
    Officiële symmetrische Wordfeud-standaardbord-layout, rij voor rij
    (0-indexed). Het bord is punt-symmetrisch rond het midden (7,7), dus
    we bouwen de onderste helft door de bovenste helft te spiegelen.
    """
    code_grid = [
        ["tw", "..", "..", "dl", "..", "..", "..", "tw", "..", "..", "..", "dl", "..", "..", "tw"],
        ["..", "dw", "..", "..", "..", "tl", "..", "..", "..", "tl", "..", "..", "..", "dw", ".."],
        ["..", "..", "dw", "..", "..", "..", "dl", "..", "dl", "..", "..", "..", "dw", "..", ".."],
        ["dl", "..", "..", "dw", "..", "..", "..", "dl", "..", "..", "..", "dw", "..", "..", "dl"],
        ["..", "..", "..", "..", "dw", "..", "..", "..", "..", "..", "dw", "..", "..", "..", ".."],
        ["..", "tl", "..", "..", "..", "tl", "..", "..", "..", "tl", "..", "..", "..", "tl", ".."],
        ["..", "..", "dl", "..", "dl", "..", "..", "..", "..", "..", "dl", "..", "dl", "..", ".."],
        ["tw", "..", "..", "dl", "..", "..", "..", "st", "..", "..", "..", "dl", "..", "..", "tw"],
    ]
    # Onderste helft = spiegeling van de bovenste 7 rijen (rij 8..14 spiegelt rij 6..0)
    full_codes = code_grid + code_grid[-2::-1]

    code_to_bonus = {
        "..": Bonus.NONE, "dl": Bonus.DL, "tl": Bonus.TL,
        "dw": Bonus.DW, "tw": Bonus.TW, "st": Bonus.START,
    }
    return [[code_to_bonus[code] for code in row] for row in full_codes]


@dataclass
class Cell:
    letter: str | None = None       # None = leeg
    is_blank: bool = False          # True als hier een joker ligt
    bonus: Bonus = Bonus.NONE


@dataclass
class Board:
    grid: list[list[Cell]] = field(
        default_factory=lambda: [
            [Cell(bonus=default_bonus_grid()[r][c]) for c in range(BOARD_SIZE)]
            for r in range(BOARD_SIZE)
        ]
    )

    def is_empty(self) -> bool:
        return all(cell.letter is None for row in self.grid for cell in row)

    def clone(self) -> "Board":
        """Diepe kopie -- nodig voor lookahead-analyse (2-ply/eindspel) die
        een zet 'uitprobeert' zonder het echte bord aan te passen."""
        new_board = Board()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                new_board.grid[r][c].letter = self.grid[r][c].letter
                new_board.grid[r][c].is_blank = self.grid[r][c].is_blank
                # bonus blijft hetzelfde object/waarde, hoeft niet gekopieerd
        return new_board

    def place_word(self, word: str, row: int, col: int, horizontal: bool) -> None:
        for i, ch in enumerate(word):
            r = row if horizontal else row + i
            c = col + i if horizontal else col
            self.grid[r][c].letter = ch.upper()


# ----------------------------------------------------------------------
# ONTWERP: hoe vinden we ALLE geldige zetten (incl. korte parallelwoorden)
# efficiënt, zonder brute-force over alle 15x15xrichting mogelijkheden?
# ----------------------------------------------------------------------
"""
AANPAK: cross-check sets + anchor squares (vergelijkbaar met de klassieke
Appel & Jacobson Scrabble-aanpak, aangepast voor Wordfeud).

1. ANCHOR SQUARES
   Een 'anchor' is elk leeg vakje dat grenst aan een reeds gelegde letter
   (of, bij een leeg bord, het startvakje). We hoeven alleen zetten te
   overwegen die minstens één anchor-vakje raken -- dat scheelt enorm
   in de zoekruimte t.o.v. "probeer elk woord op elke positie".

2. CROSS-CHECK SETS (dit is de sleutel tot parallelle woorden!)
   Voor elk leeg vakje (r, c) berekenen we vooraf: "welke letters mogen
   hier komen te liggen, gegeven de letters die al VERTICAAL (of
   HORIZONTAAL, afhankelijk van de hoofdrichting van de zet) grenzen?"

   Concreet: als we een horizontaal woord aan het leggen zijn en vakje
   (r, c) heeft al een letter erboven en/of eronder staan, dan vormt het
   plaatsen van letter X op (r, c) automatisch ook een nieuw verticaal
   woord (bv. boven-letter + X + onder-letter). Dat verticale woord moet
   ZELF ook geldig zijn.

   We precomputen daarom per leeg vakje de set toegestane letters:

       cross_check[r][c] = { X in alfabet :
           verticaal_woord_met_X_op_deze_plek is geldig in lexicon }

   Dit is exact het mechanisme waarmee we automatisch korte woorden als
   'EX', 'QI', 'PF' vinden: als een vakje naast een bestaande letter ligt
   en het 2-letterwoord dat ontstaat staat in het lexicon (of de
   whitelist!), dan laat de cross-check die letter toe -- de generator
   hoeft daar niet apart naar te zoeken, het rolt vanzelf uit dezelfde
   pass.

3. WOORD-GENERATIE MET EEN TRIE / DAWG
   Het basiswoordenboek laden we niet als platte set, maar als Trie
   (of nog beter: een DAWG/GADDAG) zodat we tijdens het plaatsen van
   letters op de rack per stap kunnen zien "is dit nog een geldig
   prefix?" en vroegtijdig kunnen afkappen (branch-and-bound), i.p.v.
   achteraf elk mogelijk woord te toetsen. Dat is wat het algoritme
   snel genoeg maakt om dit real-time op een smartphone-foto te draaien.

4. SCORING PER KANDIDAAT-ZET
   Voor elke gevonden geldige plaatsing:
     a. Bereken het hoofdwoord-score (letterwaarden × DL/TL,
        woordtotaal × DW/TW van de NIEUW gebruikte vakjes).
     b. Bereken ELK nieuw gevormd kruis-woord (via dezelfde
        cross-check-informatie) en tel die score erbij op.
     c. Tel de bonus van 40 punten als alle 7 rackletters gebruikt zijn
        ("bingo"/uitleggen).
     -> raw_score = hoofdwoord + som(kruiswoorden) + eventuele bingo-bonus.

5. SAFETY INDEX (defensieve laag, bovenop raw_score)
   Voor elke kandidaat-zet simuleren we: "welke NIEUWE anchor-vakjes met
   welke bonus (TW/TL) komen hierdoor vrij te liggen voor de
   tegenstander, en met welke cross-check letters?" Dit geeft een
   'exposure_score': hoe makkelijk kan de tegenstander een hoge
   bonus scoren op de opengelegde vakjes.

       safety_index = raw_score - RISK_WEIGHT * exposure_score

   RISK_WEIGHT is instelbaar (agressief vs. voorzichtig spelen).
   Zetten worden uiteindelijk gesorteerd op safety_index, niet op
   raw_score alleen -- zo voorkomen we dat de AI een hoge score
   voorstelt die per ongeluk een TW naast een makkelijke aanlegletter
   voor de tegenstander openlegt.

6. TILE-DUMP HEURISTIEK
   Als aanvulling op de score: zetten die moeilijke letters (Q, X, Y,
   of een 3e/4e klinker op een rack met te veel klinkers) verbruiken,
   krijgen een kleine score-bonus t.o.v. een qua score gelijk alternatief
   -- dit implementeren we als een aparte 'rack_balance_bonus' term die
   meeweegt in de uiteindelijke ranking, vergelijkbaar met de Safety Index.
"""


@dataclass
class CandidateMove:
    word: str
    row: int
    col: int
    horizontal: bool
    raw_score: int
    cross_words: list[str] = field(default_factory=list)
    exposure_score: float = 0        # hoe kwetsbaar de zet de tegenstander maakt
    rack_balance_bonus: int = 0      # bonus voor het lozen van lastige letters

    # -- Onderstaande velden worden pas gevuld door de "masterbrein"-analyse
    # in strategy.py (analyze_moves). Bij een gewone generate_moves()-aanroep
    # blijven ze op hun standaardwaarde staan. --
    is_bingo: bool = False                    # gebruikt alle 7 rackletters (40-bonus)
    expected_opponent_response: float = 0.0   # verwachte score van tegenstander erna
    endgame_bonus: int = 0                    # eindspel "uitspelen"-bonus, indien van toepassing
    explanation: str = ""                     # coach-modus: uitleg in gewone taal

    def safety_index(self, risk_weight: float = 1.0) -> float:
        return self.raw_score + self.rack_balance_bonus - risk_weight * self.exposure_score

    def advanced_value(self, risk_weight: float = 1.0) -> float:
        """
        De 'masterbrein'-ranking: score + racksaldo - directe blootstelling
        - verwachte tegenzet + eventuele eindspelbonus. Dit is wat
        analyze_moves() gebruikt om te sorteren zodra de diepere analyse
        is uitgevoerd.
        """
        return (
            self.raw_score
            + self.rack_balance_bonus
            - risk_weight * self.exposure_score
            - self.expected_opponent_response
            + self.endgame_bonus
        )


def rank_moves(
    moves: list[CandidateMove], risk_weight: float = 1.0
) -> list[CandidateMove]:
    """Sorteer kandidaat-zetten op Safety Index (hoog naar laag)."""
    return sorted(moves, key=lambda m: m.safety_index(risk_weight), reverse=True)


if __name__ == "__main__":
    board = Board()
    print("Bord is leeg:", board.is_empty())
    board.place_word("HUIS", row=7, col=6, horizontal=True)
    print("Middelste rij na 'HUIS':",
          "".join(cell.letter or "." for cell in board.grid[7]))

    # Demonstratie van ranking-logica met wat fictieve kandidaten
    demo_moves = [
        CandidateMove("HUIZEN", 7, 5, True, raw_score=32, exposure_score=18),
        CandidateMove("PF", 8, 6, False, raw_score=9, exposure_score=1,
                      rack_balance_bonus=3),  # loost de P
    ]
    for m in rank_moves(demo_moves):
        print(f"{m.word:8s} raw={m.raw_score:3d} "
              f"exposure={m.exposure_score:3d} "
              f"safety_index={m.safety_index():.1f}")
