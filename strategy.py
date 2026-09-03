"""
strategy.py
-----------
De "masterbrein"-laag bovenop move_generator.py. Vijf onderdelen:

1. find_words_from_letters()   -- alle woorden die met een lettergreep
                                   (rack) te maken zijn, los van het bord.
2. rack_bingo_potential()      -- (3) bingo-gerichte racksturing: kun je nu
                                   al 7 tegels wegleggen, en zo niet, welke
                                   6 vasthouden geeft de beste kans op een
                                   bingo bij de volgende trekking?
3. probabilistic_exposure()    -- (4) dynamische letterrisico's: weegt
                                   blootgestelde bonusvakjes met de
                                   daadwerkelijke resterende letterkansen
                                   uit de TileTracker, i.p.v. vaste gewichten.
4. simulate_opponent_response()
   exact_opponent_response()   -- (1) 2-ply lookahead (kansgewogen zolang de
                                   pot niet leeg is) en (2) exacte eindspel-
                                   berekening (zodra het tegenstander-rack
                                   met zekerheid bekend is), incl. de
                                   Wordfeud-regel voor de "uitspeel"-bonus.
5. explain_move()              -- (5) coach-modus: korte uitleg in gewone taal.
"""

from __future__ import annotations

import random
from collections import Counter

from board_skeleton import Board, Bonus, BOARD_SIZE, CandidateMove
from tile_tracker import DUTCH_TILE_POINTS, TileTracker
from trie import Trie, TrieNode
from move_generator import (
    _letters_grid,
    compute_cross_checks,
    generate_moves,
    _Placement,
)

DIFFICULT_LETTERS = {"Q", "X", "Y", "*"}


# ----------------------------------------------------------------------
# 1. Woorden uit een los rack (geen bord nodig) -- ook los een nuttige
#    functie: "wat kan ik allemaal maken met deze letters?"
# ----------------------------------------------------------------------
def find_words_from_letters(
    rack: str | Counter, trie: Trie, min_length: int = 2, max_length: int = 15
) -> list[str]:
    """
    Vind ALLE woorden die met (een deel van) het rack te vormen zijn,
    onafhankelijk van enig bord. Gebruikt dezelfde Trie-DFS-aanpak als de
    move-generator, maar zonder de bord-/cross-check-beperkingen: puur
    "welke combinaties van deze letters vormen een geldig woord".
    """
    if isinstance(rack, str):
        counter = Counter()
        for ch in rack.upper():
            counter["*" if ch == "?" else ch] += 1
    else:
        counter = Counter(rack)

    found: set[str] = set()

    def dfs(node: TrieNode, path: list[str], remaining: Counter) -> None:
        if node.is_word and min_length <= len(path) <= max_length:
            found.add("".join(path))
        if len(path) >= max_length:
            return
        for letter, child in node.children.items():
            if remaining[letter] > 0:
                remaining[letter] -= 1
                path.append(letter)
                dfs(child, path, remaining)
                path.pop()
                remaining[letter] += 1
            elif remaining["*"] > 0:
                remaining["*"] -= 1
                path.append(letter)
                dfs(child, path, remaining)
                path.pop()
                remaining["*"] += 1

    dfs(trie.root, [], counter)
    return sorted(found, key=lambda w: (-len(w), w))


# ----------------------------------------------------------------------
# 2. Bingo-potentieel: (a) kun je nu al alle 7 tegels in één woord kwijt?
#    (b) zo niet, welke letter zou je moeten LOZEN om de kans op een
#    bingo bij je volgende trekking te maximaliseren?
# ----------------------------------------------------------------------
def rack_bingo_potential(
    rack: str, trie: Trie, tracker: TileTracker, board: Board | None = None
) -> dict:
    """
    Geeft een dict terug:
        {
            "current_bingos": [...],   # 7-letter woorden die NU al kunnen
            "best_discard": "K",       # letter die je het beste kunt lozen...
            "best_discard_ev": 0.23,   # ...met deze kans (0-1) op een bingo
                                       # bij een willekeurige volgende trekking
            "per_discard": {"K": 0.23, "A": 0.05, ...},
            "board_aware": True/False,  # of dit écht op het bord is gecheckt
        }

    Als `board` wordt meegegeven, wordt niet alleen gecheckt of het
    7-letterwoord in het woordenboek bestaat, maar ook of het daadwerkelijk
    ergens op DIT bord neergelegd kan worden (via de echte move-generator:
    anchors, cross-checks, kruiswoorden -- alles). Zonder bord (of bij een
    leeg bord waar toch al iets ligt maar je 'm niet meegeeft) valt de
    functie terug op de pure woordenboek-check, wat sneller is maar
    optimistischer: een woord dat wél bestaat maar nergens past, zou dan
    ten onrechte als 'haalbaar' worden meegeteld.
    """
    counter = Counter()
    for ch in rack.upper():
        counter["*" if ch == "?" else ch] += 1
    rack_letters = list(counter.elements())
    board_aware = board is not None

    def _bingo_words_for_rack(rack_str: str) -> list[str]:
        if board_aware:
            moves = generate_moves(board, rack_str, trie)
            return sorted({m.word for m in moves if m.is_bingo})
        return find_words_from_letters(rack_str, trie, min_length=7, max_length=7)

    current_bingos = _bingo_words_for_rack(rack)

    letter_probs = tracker.estimate_opponent_probabilities()
    if not letter_probs:
        return {
            "current_bingos": current_bingos,
            "best_discard": None,
            "best_discard_ev": 0.0,
            "per_discard": {},
            "board_aware": board_aware,
        }

    per_discard: dict[str, float] = {}
    if len(rack_letters) == 7:
        for i in range(7):
            remaining_six = Counter(rack_letters)
            discarded_letter = rack_letters[i]
            remaining_six[discarded_letter] -= 1

            ev = 0.0
            for draw_letter, p in letter_probs.items():
                seven = Counter(remaining_six)
                seven[draw_letter] += 1
                seven_str = "".join(seven.elements()).replace("*", "?")
                if _bingo_words_for_rack(seven_str):
                    ev += p
            per_discard[discarded_letter] = round(ev, 4)

        best_discard = max(per_discard, key=per_discard.get) if per_discard else None
        best_discard_ev = per_discard.get(best_discard, 0.0) if best_discard else 0.0
        if best_discard_ev == 0.0:
            # Geen enkele optie levert iets op (bv. bord blokkeert alles) --
            # dan is 'de beste' van zes gelijke nullen misleidend advies.
            best_discard, best_discard_ev = None, 0.0
    else:
        best_discard, best_discard_ev = None, 0.0

    return {
        "current_bingos": current_bingos,
        "best_discard": best_discard,
        "best_discard_ev": best_discard_ev,
        "per_discard": per_discard,
        "board_aware": board_aware,
    }


def apply_move_to_board(board: Board, move: CandidateMove) -> Board:
    """Kopieer het bord en leg de zet erop (voor lookahead-analyse)."""
    new_board = board.clone()
    new_board.place_word(move.word, move.row, move.col, move.horizontal)
    return new_board


# ----------------------------------------------------------------------
# 4. Dynamische letterrisico's: i.p.v. vaste gewichten per bonustype,
#    weeg elk blootgesteld bonusvakje met de daadwerkelijke resterende
#    letterkansen (uit de TileTracker) en de puntwaarde van die letters.
#    Een TW naast een vakje waar alleen zeldzame letters nog passen is
#    veel minder gevaarlijk dan een TW waar de helft van het alfabet
#    (incl. veelvoorkomende hoge-puntletters) nog past.
# ----------------------------------------------------------------------
def probabilistic_exposure(
    board: Board, move: CandidateMove, trie: Trie, tracker: TileTracker
) -> float:
    board_after = apply_move_to_board(board, move)
    letters = _letters_grid(board_after)
    cross_checks_h = compute_cross_checks(letters, trie)  # voor horizontale kruiswoorden
    # Voor verticale kruiswoorden hebben we de cross-check op de getransponeerde
    # grid nodig (zelfde principe, 90 graden gedraaid).
    transposed = [list(row) for row in zip(*letters)]
    cross_checks_v_t = compute_cross_checks(transposed, trie)

    letter_probs = tracker.estimate_opponent_probabilities()
    if not letter_probs:
        return 0.0

    # Verzamel de cellen die door deze zet NIEUW zijn ingevuld.
    length = len(move.word)
    if move.horizontal:
        new_cells = [(move.row, move.col + i) for i in range(length)]
    else:
        new_cells = [(move.row + i, move.col) for i in range(length)]

    risk = 0.0
    seen_targets: set[tuple[int, int]] = set()
    for (r, c) in new_cells:
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE):
                continue
            if letters[nr][nc] is not None:
                continue
            if (nr, nc) in seen_targets:
                continue
            bonus = board.grid[nr][nc].bonus
            if bonus not in (Bonus.TW, Bonus.DW, Bonus.TL, Bonus.DL):
                continue
            seen_targets.add((nr, nc))

            word_mult = 3 if bonus == Bonus.TW else 2 if bonus == Bonus.DW else 1
            letter_mult = 3 if bonus == Bonus.TL else 2 if bonus == Bonus.DL else 1

            allowed_h = cross_checks_h[nr][nc]
            allowed_v = cross_checks_v_t[nc][nr]  # let op: getransponeerde coördinaten
            # Als er geen enkele beperking is (None), mag in principe elke
            # letter -- neem dan gewoon de volledige kansverdeling.
            candidates = letter_probs.keys()
            if allowed_h is not None:
                candidates = [l for l in candidates if l in allowed_h]
            if allowed_v is not None:
                candidates = [l for l in candidates if l in allowed_v]

            expected_letter_value = sum(
                letter_probs.get(l, 0.0) * DUTCH_TILE_POINTS.get(l, 0) * letter_mult
                for l in candidates
            )
            risk += expected_letter_value * word_mult

    return round(risk, 2)


# ----------------------------------------------------------------------
# 1. Twee-ply lookahead: zolang de pot nog niet leeg is, weten we het
#    tegenstander-rack niet exact. We simuleren daarom met willekeurige
#    steekproeven uit de kansverdeling van de TileTracker: trek N keer
#    een plausibel 7-letter rack, laat de generator daar het beste woord
#    voor vinden, en middel de scores. Dat is een genuine tweede
#    zoekdiepte, alleen kansgewogen i.p.v. exact (want exact kan nog niet).
# ----------------------------------------------------------------------
def simulate_opponent_response(
    board_after_move: Board,
    trie: Trie,
    tracker: TileTracker,
    n_samples: int = 10,
    rng: random.Random | None = None,
) -> float:
    rng = rng or random
    pool: list[str] = []
    for letter, count in tracker.remaining.items():
        already_ours = tracker.own_rack.get(letter, 0)
        pool.extend([letter] * max(0, count - already_ours))

    if len(pool) < 7:
        return 0.0  # te weinig onbekende tegels om een zinnig rack te trekken

    total = 0.0
    for _ in range(n_samples):
        sample_rack = "".join(rng.sample(pool, 7)).replace("*", "?")
        opponent_moves = generate_moves(board_after_move, sample_rack, trie)
        total += opponent_moves[0].raw_score if opponent_moves else 0.0

    return round(total / n_samples, 2)


# ----------------------------------------------------------------------
# 2. Exacte eindspelberekening: zodra tracker.deduce_opponent_rack() een
#    zekere uitkomst geeft (de pot is leeg), kennen we het tegenstander-
#    rack EXACT. Dan hoeven we niet te simuleren -- we kunnen precies
#    berekenen wat hun beste zet zou zijn. Plus: de Wordfeud-regel dat je
#    bij het legen van je eigen rack (en een lege pot) de puntwaarde van
#    ALLE tegels die de tegenstander nog vasthoudt, als bonus krijgt.
# ----------------------------------------------------------------------
def exact_endgame_response(
    board_after_move: Board,
    opponent_rack: Counter,
    trie: Trie,
) -> float:
    rack_str = "".join(opponent_rack.elements()).replace("*", "?")
    if not rack_str:
        return 0.0
    opponent_moves = generate_moves(board_after_move, rack_str, trie)
    return float(opponent_moves[0].raw_score) if opponent_moves else 0.0


def endgame_out_bonus(
    our_rack_after_move: Counter, opponent_rack: Counter, bag_is_empty: bool
) -> int:
    """
    Wordfeud-regel: als jij als eerste je rack leeg speelt terwijl de pot
    leeg is, eindigt het spel meteen en krijg jij de puntwaarde van alle
    tegels die de tegenstander nog vasthoudt (en zij die van hunzelf
    NIET afgetrokken -- in deze functie berekenen we alleen JOUW bonus).
    """
    if not bag_is_empty or sum(our_rack_after_move.values()) > 0:
        return 0
    return sum(
        DUTCH_TILE_POINTS.get(letter, 0) * count
        for letter, count in opponent_rack.items()
    )


# ----------------------------------------------------------------------
# 5. Coach-modus: korte uitleg in gewone taal, gebaseerd op de velden die
#    hierboven al berekend zijn.
# ----------------------------------------------------------------------
def explain_move(move: CandidateMove) -> str:
    parts = [f"{move.raw_score} punten"]

    if move.cross_words:
        parts.append("vormt ook " + ", ".join(move.cross_words))

    if move.is_bingo:
        parts.append("gebruikt je hele rack (+40 bonus!)")

    if move.rack_balance_bonus > 0:
        parts.append("loost lastige letter(s) en/of houdt een gezonde balans over")

    if move.exposure_score > 8:
        parts.append(
            f"⚠️ legt wel gemiddeld ~{move.exposure_score:.0f} punten aan "
            f"bonusvakjes open voor de tegenstander"
        )
    elif move.exposure_score > 0:
        parts.append(f"legt een klein beetje risico open (~{move.exposure_score:.0f})")
    else:
        parts.append("laat geen bonusvakjes onbeschermd achter")

    if move.expected_opponent_response > 0:
        parts.append(
            f"verwachte tegenzet ~{move.expected_opponent_response:.0f} punten"
        )

    if move.endgame_bonus > 0:
        parts.append(f"eindspelbonus +{move.endgame_bonus} (tegenstander speelt niet meer uit)")

    return "; ".join(parts) + "."


# ----------------------------------------------------------------------
# Orkestratie: combineert alle bovenstaande onderdelen tot één ranking.
# ----------------------------------------------------------------------
def analyze_moves(
    board: Board,
    rack: str,
    trie: Trie,
    tracker: TileTracker,
    top_k: int = 8,
    n_samples: int = 10,
    risk_weight: float = 1.0,
    rng: random.Random | None = None,
) -> list[CandidateMove]:
    """
    Het volledige 'masterbrein': genereert alle zetten, en verrijkt de
    top_k (op basis van de eenvoudige Safety Index) met kansgewogen
    exposure, een lookahead naar de tegenstander (exact als de pot leeg
    is en het rack bekend, anders kansgewogen gesimuleerd), eventuele
    eindspelbonus, en een coach-uitleg per zet. De analyse van deze extra
    lagen is rekenintensief (elke kandidaat kost een aparte
    move-generation-run), vandaar de beperking tot top_k kandidaten.
    """
    base_candidates = generate_moves(board, rack, trie, risk_weight=risk_weight)
    if not base_candidates:
        return []

    rack_counter = Counter()
    for ch in rack.upper():
        rack_counter["*" if ch == "?" else ch] += 1

    opponent_rack = tracker.deduce_opponent_rack()  # None tenzij de pot leeg is
    bag_is_empty = tracker.is_bag_empty()

    analyzed: list[CandidateMove] = []
    for move in base_candidates[:top_k]:
        move.exposure_score = probabilistic_exposure(board, move, trie, tracker)
        # move.is_bingo is al precies gezet door move_generator.py (op basis
        # van het exacte aantal nieuw geplaatste tegels), niets aan te doen hier.

        board_after = apply_move_to_board(board, move)
        rack_after = Counter(rack_counter)
        _consume_rack_for_move(rack_after, move)

        if opponent_rack is not None:
            move.expected_opponent_response = exact_endgame_response(
                board_after, opponent_rack, trie
            )
            move.endgame_bonus = endgame_out_bonus(rack_after, opponent_rack, bag_is_empty)
        else:
            move.expected_opponent_response = simulate_opponent_response(
                board_after, trie, tracker, n_samples=n_samples, rng=rng
            )

        move.explanation = explain_move(move)
        analyzed.append(move)

    analyzed.sort(key=lambda m: m.advanced_value(risk_weight), reverse=True)
    return analyzed


def _consume_rack_for_move(rack_counter: Counter, move: CandidateMove) -> None:
    """
    Beste-poging-schatting van welke rackletters deze zet verbruikt heeft
    (we kennen hier alleen het uiteindelijke woord, niet de exacte
    plaatsingen -- voor een exacte eindspel-berekening is dit voldoende
    nauwkeurig omdat we toch alleen kijken of het rack HELEMAAL leeg is).
    """
    for ch in move.word:
        if rack_counter.get(ch, 0) > 0:
            rack_counter[ch] -= 1
        elif rack_counter.get("*", 0) > 0:
            rack_counter["*"] -= 1
        # Anders: letter kwam al van het bord, niet van het rack -> negeren.


if __name__ == "__main__":
    demo_words = [
        "HUIS", "HUIZEN", "KAT", "KATER", "KATERS", "AUTO", "HOND", "TAFEL",
        "TAFELS", "STOEL", "STOELEN", "RAT", "RATEL", "TAK", "TAKEL",
    ]
    trie = Trie(demo_words)
    tracker = TileTracker()

    print("Woorden uit 'KATEROP':", find_words_from_letters("KATEROP", trie))
    print()
    print("Woorden uit 'STOELEN':", find_words_from_letters("STOELEN", trie))
    print()
    result = rack_bingo_potential("STOELEK", trie, tracker)
    print("Bingo-potentieel van STOELEK:")
    print("  Nu al bingo mogelijk:", result["current_bingos"])
    print("  Beste letter om te lozen:", result["best_discard"],
          f"(kans op bingo volgende trekking: {result['best_discard_ev']:.1%})")
