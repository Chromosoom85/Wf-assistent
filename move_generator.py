"""
move_generator.py
------------------
De echte implementatie van het ontwerp uit board_skeleton.py: vindt ALLE
geldige zetten op het bord voor een gegeven rack, inclusief automatisch
gevonden parallelle (kruis)woorden, en rangschikt ze op Safety Index.

Algoritme (Appel & Jacobson, 1988 -- de klassieke Scrabble-aanpak):

  1. Vind alle ANCHOR-vakjes: lege vakjes die grenzen aan een bestaande
     letter (of, op een leeg bord, het startvakje).
  2. Bereken per leeg vakje de CROSS-CHECK set: welke letters mogen hier
     komen te liggen, gegeven het kruisende woord dat daardoor ontstaat?
     Dit is het mechanisme waarmee korte parallelwoorden (EX, EL, PF...)
     automatisch meegenomen worden, zonder er apart naar te hoeven zoeken.
  3. Voor elke rij EN elke kolom (het bord wordt getransponeerd om
     verticale zetten met dezelfde code als horizontale te behandelen):
     voor elke anchor, probeer met de Trie alle combinaties van
     rackletters + al liggende letters die een geldig woord vormen en
     door de anchor heen lopen.
  4. Score elke gevonden plaatsing: hoofdwoord + alle nieuw gevormde
     kruiswoorden + eventuele bingo-bonus (40 punten bij gebruik van
     alle 7 rackletters).
  5. Bereken de Safety Index: score minus een risico-term voor TW/TL-
     vakjes die door deze zet vrijkomen voor de tegenstander, plus een
     kleine bonus voor het lozen van lastige letters.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from board_skeleton import Board, Bonus, BOARD_SIZE, CandidateMove
from tile_tracker import DUTCH_TILE_POINTS
from trie import Trie

DIFFICULT_LETTERS = {"Q", "X", "Y", "*"}
VOWELS = set("AEIOU")


# ----------------------------------------------------------------------
# Hulpstructuur: een "laag" bordoverzicht (letter per vakje, of None)
# zodat we horizontaal en verticaal met exact dezelfde functies kunnen
# werken door simpelweg de rijen/kolommen te verwisselen (transponeren).
# ----------------------------------------------------------------------
def _letters_grid(board: Board) -> list[list[str | None]]:
    return [[cell.letter for cell in row] for row in board.grid]


def _transpose(grid: list[list]) -> list[list]:
    return [list(row) for row in zip(*grid)]


def find_anchors(letters: list[list[str | None]]) -> set[tuple[int, int]]:
    """Lege vakjes die grenzen aan een bestaande letter, of het startvakje
    als het bord nog helemaal leeg is."""
    anchors: set[tuple[int, int]] = set()
    empty_board = all(cell is None for row in letters for cell in row)
    if empty_board:
        return {(BOARD_SIZE // 2, BOARD_SIZE // 2)}

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if letters[r][c] is not None:
                continue
            neighbors = [
                (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1),
            ]
            for nr, nc in neighbors:
                if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                    if letters[nr][nc] is not None:
                        anchors.add((r, c))
                        break
    return anchors


def compute_cross_checks(
    letters: list[list[str | None]], trie: Trie
) -> list[list[set[str] | None]]:
    """
    Voor elk leeg vakje (r, c): welke letters mogen hier liggen, gegeven
    de letters die er verticaal boven/onder aan grenzen (bij het scannen
    van HORIZONTALE zetten -- vandaar dat je deze functie ook los
    aanroept op de getransponeerde grid om de check voor VERTICALE
    zetten te krijgen).

    None betekent: geen beperking (geen verticale buren, elke letter mag).
    Een lege set betekent: GEEN letter is hier toegestaan (dus dit vakje
    is voor horizontale zetten feitelijk geblokkeerd).
    """
    checks: list[list[set[str] | None]] = [
        [None] * BOARD_SIZE for _ in range(BOARD_SIZE)
    ]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if letters[r][c] is not None:
                continue

            # Verzamel het stukje boven en onder dit vakje.
            above = []
            rr = r - 1
            while rr >= 0 and letters[rr][c] is not None:
                above.append(letters[rr][c])
                rr -= 1
            above.reverse()

            below = []
            rr = r + 1
            while rr < BOARD_SIZE and letters[rr][c] is not None:
                below.append(letters[rr][c])
                rr += 1

            if not above and not below:
                continue  # geen verticale buren -> geen beperking (blijft None)

            allowed = set()
            for letter in alphabet:
                word = "".join(above) + letter + "".join(below)
                if trie.has_word(word):
                    allowed.add(letter)
            checks[r][c] = allowed

    return checks


# ----------------------------------------------------------------------
# Kernrecursie: vanaf een anchor naar rechts uitbreiden, met de rack en
# de cross-check-beperkingen. `left_part` is wat al links van de anchor
# is opgebouwd (leeg, of via het bord liggende letters, of via rack
# letters bij het naar links "vooruitplaatsen").
# ----------------------------------------------------------------------
@dataclass
class _Placement:
    row: int
    col: int
    letter: str
    from_rack: bool  # False = letter lag al op het bord


def _extend_right(
    letters: list[list[str | None]],
    cross_checks: list[list[set[str] | None]],
    trie: Trie,
    node,
    row: int,
    col: int,
    rack: Counter,
    placements: list[_Placement],
    results: list[list[_Placement]],
    anchor_col: int,
    anchor_filled: bool = False,
) -> None:
    """
    anchor_col / anchor_filled: een zet moet het anchor-vakje daadwerkelijk
    bedekken om geldig te zijn (anders "raakt" het nieuwe woord het bord
    niet). anchor_filled wordt True zodra we bij col == anchor_col een
    letter plaatsen (het anchor-vakje is per definitie leeg, dus dat kan
    alleen vanuit de rack). Records worden alleen geaccepteerd als
    anchor_filled uiteindelijk True is.
    """
    if col >= BOARD_SIZE:
        if node.is_word and placements and anchor_filled:
            results.append(list(placements))
        return

    existing = letters[row][col]
    if existing is not None:
        nxt = node.children.get(existing)
        if nxt is not None:
            _extend_right(letters, cross_checks, trie, nxt, row, col + 1,
                          rack, placements, results, anchor_col,
                          anchor_filled or col == anchor_col)
        return

    # Vakje is leeg -> we mogen hier stoppen (als het al een geldig woord is
    # EN het anchor-vakje daadwerkelijk bedekt is)
    if node.is_word and placements and anchor_filled:
        results.append(list(placements))

    allowed_cross = cross_checks[row][col]  # None = geen beperking

    for letter, child_node in node.children.items():
        if allowed_cross is not None and letter not in allowed_cross:
            continue
        if rack[letter] > 0:
            rack[letter] -= 1
            placements.append(_Placement(row, col, letter, from_rack=True))
            _extend_right(letters, cross_checks, trie, child_node, row, col + 1,
                          rack, placements, results, anchor_col,
                          anchor_filled or col == anchor_col)
            placements.pop()
            rack[letter] += 1
        elif rack["*"] > 0:
            rack["*"] -= 1
            placements.append(_Placement(row, col, letter, from_rack=True))
            _extend_right(letters, cross_checks, trie, child_node, row, col + 1,
                          rack, placements, results, anchor_col,
                          anchor_filled or col == anchor_col)
            placements.pop()
            rack["*"] += 1


def _generate_for_row(
    letters: list[list[str | None]],
    cross_checks: list[list[set[str] | None]],
    trie: Trie,
    rack: Counter,
    anchors: set[tuple[int, int]],
    row: int,
) -> list[list[_Placement]]:
    """Genereer alle plaatsingen voor anchors in deze rij (horizontale zetten)."""
    all_results: list[list[_Placement]] = []

    row_anchors = sorted(c for (r, c) in anchors if r == row)
    for anchor_col in row_anchors:
        # Bepaal hoeveel ruimte er links van de anchor is om een prefix
        # op te bouwen (tot bordrand of tot een bestaande letter).
        limit = 0
        cc = anchor_col - 1
        while cc >= 0 and letters[row][cc] is None and (row, cc) not in anchors:
            limit += 1
            cc -= 1
        # (we nemen ook mee: als er direct links al een bestaande letter
        # ligt, dan begint het woord daar -- dat vangen we af door vanaf
        # de eerste lege of randpositie links te starten in _left_part.)

        start_col = anchor_col
        rr = anchor_col - 1
        prefix_from_board = []
        while rr >= 0 and letters[row][rr] is not None:
            prefix_from_board.append(letters[row][rr])
            rr -= 1
        prefix_from_board.reverse()
        start_col = rr + 1

        if prefix_from_board:
            # Er ligt al een vast voorvoegsel op het bord: volg de trie
            # daarlangs en start de rechts-uitbreiding meteen na de anchor.
            node = trie.root
            valid = True
            for ch in prefix_from_board:
                node = node.children.get(ch)
                if node is None:
                    valid = False
                    break
            if valid:
                results: list[list[_Placement]] = []
                _extend_right(letters, cross_checks, trie, node, row, anchor_col,
                              rack, [], results, anchor_col)
                all_results.extend(results)
        else:
            # Geen vast voorvoegsel op het bord: probeer elke voorvoegsel-
            # lengte L van 0..limit apart. Voor een gekozen lengte L worden
            # de letters van links naar rechts geplaatst (kolom anchor_col-L
            # t/m anchor_col-1), zodat de Trie-traversal in de juiste
            # volgorde gebeurt (een Trie kan alleen voorwaarts gelezen
            # worden). Zodra het voorvoegsel van lengte L compleet is,
            # start de rechts-uitbreiding op de anchorkolom zelf.
            def _build_left(node, col: int, remaining_len: int,
                             placements: list[_Placement]) -> None:
                if remaining_len == 0:
                    results: list[list[_Placement]] = []
                    _extend_right(letters, cross_checks, trie, node, row,
                                  anchor_col, rack, list(placements), results,
                                  anchor_col)
                    all_results.extend(results)
                    return

                allowed_cross = cross_checks[row][col]  # None = geen beperking
                for letter, child in node.children.items():
                    if allowed_cross is not None and letter not in allowed_cross:
                        continue
                    if rack[letter] > 0:
                        rack[letter] -= 1
                        placements.append(_Placement(row, col, letter, True))
                        _build_left(child, col + 1, remaining_len - 1, placements)
                        placements.pop()
                        rack[letter] += 1
                    elif rack["*"] > 0:
                        rack["*"] -= 1
                        placements.append(_Placement(row, col, letter, True))
                        _build_left(child, col + 1, remaining_len - 1, placements)
                        placements.pop()
                        rack["*"] += 1

            for length in range(0, limit + 1):
                _build_left(trie.root, anchor_col - length, length, [])

    return all_results


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------
def _word_score(
    board: Board,
    placements: list[_Placement],
    letters_before: list[list[str | None]],
    horizontal: bool,
) -> tuple[int, list[str], str, int, int]:
    """Bereken de score van het hoofdwoord + alle nieuw gevormde kruiswoorden.
    Geeft ook het VOLLEDIGE hoofdwoord terug (incl. reeds op het bord
    liggende letters), niet alleen de nieuw geplaatste letters."""
    if not placements:
        return 0, [], "", 0, 0

    points = DUTCH_TILE_POINTS

    # -- Hoofdwoord --
    if horizontal:
        r = placements[0].row
        cols = [p.col for p in placements]
        c0, c1 = min(cols), max(cols)
        while c0 > 0 and letters_before[r][c0 - 1] is not None:
            c0 -= 1
        while c1 < BOARD_SIZE - 1 and letters_before[r][c1 + 1] is not None:
            c1 += 1
        word_cells = [(r, c) for c in range(c0, c1 + 1)]
    else:
        c = placements[0].col
        rows = [p.row for p in placements]
        r0, r1 = min(rows), max(rows)
        while r0 > 0 and letters_before[r0 - 1][c] is not None:
            r0 -= 1
        while r1 < BOARD_SIZE - 1 and letters_before[r1 + 1][c] is not None:
            r1 += 1
        word_cells = [(r, c) for r in range(r0, r1 + 1)]


    new_positions = {(p.row, p.col): p.letter for p in placements}

    def score_line(cells: list[tuple[int, int]]) -> int:
        total = 0
        word_multiplier = 1
        for (r, c) in cells:
            letter = new_positions.get((r, c)) or letters_before[r][c]
            letter_score = points.get(letter, 0)
            if (r, c) in new_positions:
                bonus = board.grid[r][c].bonus
                if bonus == Bonus.DL:
                    letter_score *= 2
                elif bonus == Bonus.TL:
                    letter_score *= 3
                elif bonus == Bonus.DW:
                    word_multiplier *= 2
                elif bonus == Bonus.TW:
                    word_multiplier *= 3
            total += letter_score
        return total * word_multiplier

    main_word = "".join(
        (new_positions.get((r, c)) or letters_before[r][c]) for (r, c) in word_cells
    )
    total_score = score_line(word_cells)
    cross_words = []

    # -- Kruiswoorden: voor elke NIEUW geplaatste letter, kijk of er een
    # kruisend woord ontstaat (loodrecht op de hoofdrichting). --
    for p in placements:
        if horizontal:
            r0 = p.row
            while r0 > 0 and (
                letters_before[r0 - 1][p.col] is not None or (r0 - 1, p.col) in new_positions
            ):
                r0 -= 1
            r1 = p.row
            while r1 < BOARD_SIZE - 1 and (
                letters_before[r1 + 1][p.col] is not None or (r1 + 1, p.col) in new_positions
            ):
                r1 += 1
            if r1 > r0:
                cells = [(r, p.col) for r in range(r0, r1 + 1)]
                cross_words.append("".join(
                    new_positions.get((r, c)) or letters_before[r][c] for (r, c) in cells
                ))
                total_score += score_line(cells)
        else:
            c0 = p.col
            while c0 > 0 and (
                letters_before[p.row][c0 - 1] is not None or (p.row, c0 - 1) in new_positions
            ):
                c0 -= 1
            c1 = p.col
            while c1 < BOARD_SIZE - 1 and (
                letters_before[p.row][c1 + 1] is not None or (p.row, c1 + 1) in new_positions
            ):
                c1 += 1
            if c1 > c0:
                cells = [(p.row, c) for c in range(c0, c1 + 1)]
                cross_words.append("".join(
                    new_positions.get((r, c)) or letters_before[r][c] for (r, c) in cells
                ))
                total_score += score_line(cells)

    if len(placements) == 7:
        total_score += 40  # bingo-bonus

    start_row, start_col = word_cells[0]
    return total_score, cross_words, main_word, start_row, start_col


def _exposure_score(board: Board, placements: list[_Placement]) -> int:
    """
    Simpele defensieve heuristiek: tel de TW/TL-vakjes die NA deze zet
    direct naast een geplaatste letter liggen en nog leeg zijn -- dat zijn
    de vakjes die de tegenstander bij zijn volgende zet zou kunnen bereiken.
    TW weegt zwaarder mee dan TL, want een woordbonus is doorgaans gevaarlijker.
    """
    exposure = 0
    occupied = {(p.row, p.col) for p in placements}
    for p in placements:
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = p.row + dr, p.col + dc
            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and (nr, nc) not in occupied:
                bonus = board.grid[nr][nc].bonus
                if bonus == Bonus.TW:
                    exposure += 15
                elif bonus == Bonus.TL:
                    exposure += 6
                elif bonus == Bonus.DW:
                    exposure += 5
                elif bonus == Bonus.DL:
                    exposure += 2
    return exposure


def _rack_balance_bonus(placements: list[_Placement], rack_before: Counter) -> int:
    """Kleine bonus voor het lozen van lastige letters (Q, X, Y, blanco) en
    voor het herstellen van een scheve klinker/medeklinker-verhouding."""
    bonus = 0
    for p in placements:
        if p.from_rack and p.letter in DIFFICULT_LETTERS:
            bonus += 5

    remaining_after = Counter(rack_before)
    for p in placements:
        if p.from_rack:
            remaining_after[p.letter] -= 1
    vowels_left = sum(n for l, n in remaining_after.items() if l in VOWELS)
    consonants_left = sum(n for l, n in remaining_after.items() if l not in VOWELS and l != "*")
    if vowels_left + consonants_left > 0:
        ratio = vowels_left / (vowels_left + consonants_left)
        if 0.3 <= ratio <= 0.55:
            bonus += 3  # gezonde balans overgehouden
    return bonus


# ----------------------------------------------------------------------
# Publieke API
# ----------------------------------------------------------------------
def generate_moves(
    board: Board, rack_letters: str, trie: Trie, risk_weight: float = 1.0
) -> list[CandidateMove]:
    """
    Vind alle geldige zetten voor `rack_letters` (bv. "HUISJE?") op `board`,
    en geef ze terug gesorteerd op Safety Index (hoog naar laag).
    """
    rack = Counter()
    for ch in rack_letters.upper():
        rack["*" if ch == "?" else ch] += 1

    all_candidates: list[CandidateMove] = []

    for horizontal, letters, cross_source in (
        (True, _letters_grid(board), board),
        (False, _transpose(_letters_grid(board)), board),
    ):
        anchors = find_anchors(letters)
        cross_checks = compute_cross_checks(letters, trie)

        for row in range(BOARD_SIZE):
            placements_list = _generate_for_row(
                letters, cross_checks, trie, rack.copy(), anchors, row
            )
            for placements in placements_list:
                if not horizontal:
                    # Terugtransponeren naar echte (rij, kolom)
                    placements = [
                        _Placement(p.col, p.row, p.letter, p.from_rack)
                        for p in placements
                    ]

                raw_score, cross_words, full_word, start_row, start_col = _word_score(
                    board, placements, _letters_grid(board), horizontal
                )
                if raw_score <= 0:
                    continue

                candidate = CandidateMove(
                    word=full_word,
                    row=start_row,
                    col=start_col,
                    horizontal=horizontal,
                    raw_score=raw_score,
                    cross_words=cross_words,
                    exposure_score=_exposure_score(board, placements),
                    rack_balance_bonus=_rack_balance_bonus(placements, rack),
                    is_bingo=(len(placements) == 7),
                )
                all_candidates.append(candidate)

    # Dedupliceren (dezelfde zet kan soms via meerdere anchors gevonden worden)
    seen = set()
    unique_candidates = []
    for m in all_candidates:
        key = (m.word, m.row, m.col, m.horizontal)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(m)

    return sorted(
        unique_candidates, key=lambda m: m.safety_index(risk_weight), reverse=True
    )


if __name__ == "__main__":
    demo_words = [
        "HUIS", "HUIZEN", "KAT", "KATER", "AUTO", "HOND", "TAFEL",
        "EX", "EL", "PF", "OP", "TE", "EEN", "AAN",
    ]
    trie = Trie(demo_words)
    board = Board()
    board.place_word("HUIS", row=7, col=6, horizontal=True)

    moves = generate_moves(board, "KATEROP", trie)
    print(f"{len(moves)} kandidaat-zetten gevonden:\n")
    for m in moves[:10]:
        print(
            f"  {m.word:10s} @ ({m.row:2d},{m.col:2d}) "
            f"{'→' if m.horizontal else '↓'}  "
            f"score={m.raw_score:3d}  kruiswoorden={m.cross_words}  "
            f"exposure={m.exposure_score:3d}  safety={m.safety_index():.1f}"
        )
