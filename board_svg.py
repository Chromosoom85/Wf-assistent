"""
board_svg.py
------------
Zet een Board om naar een visuele SVG-weergave (bonusvakjes + letters),
zodat de gebruiker het bord kan ZIEN in plaats van 15 regels punten te
moeten interpreteren. Puur weergave -- de daadwerkelijke invoer blijft
via het tekstveld lopen (SVG kan in Streamlit niet direct klikbaar
teruggekoppeld worden zonder een custom component te bouwen).

LET OP: voor handmatig ingevoerde borden kennen we de ECHTE bonuslayout
niet (die is willekeurig per potje, zie board_ocr.py's bevindingen) --
deze preview toont daarom altijd de STANDAARD-layout uit board_skeleton.py.
Dat is een bewuste beperking: zonder de OCR (die nu niet werkt) hebben we
geen andere bron voor de echte bonusposities bij handmatige invoer.
"""

from __future__ import annotations

from board_skeleton import Board, Bonus, BOARD_SIZE

CELL = 32  # pixels per vakje
PADDING = 4

BONUS_COLORS = {
    Bonus.TW: "#c0353d",
    Bonus.DW: "#d98c1e",
    Bonus.TL: "#3f77a8",
    Bonus.DL: "#5f9153",
    Bonus.START: "#5f9153",
    Bonus.NONE: "#2a2e33",
}
BONUS_LABELS = {
    Bonus.TW: "3W", Bonus.DW: "2W", Bonus.TL: "3L", Bonus.DL: "2L",
    Bonus.START: "★", Bonus.NONE: "",
}
LETTER_TILE_COLOR = "#f2eeea"
LETTER_TEXT_COLOR = "#1a1a1a"
BORDER_COLOR = "#17191c"


def board_to_svg(
    board: Board,
    highlight_uncertain: set[tuple[int, int]] | None = None,
    highlight_new: set[tuple[int, int]] | None = None,
) -> str:
    """Genereert een SVG-string van het bord.
    `highlight_uncertain`: rode rand (bv. onzekere OCR-vakjes).
    `highlight_new`: gouden rand (bv. 'hier moet je een tegel neerleggen'
    voor een voorgestelde zet)."""
    highlight_uncertain = highlight_uncertain or set()
    highlight_new = highlight_new or set()
    size = BOARD_SIZE * CELL + 2 * PADDING
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="100%" style="max-width:520px" font-family="Arial, sans-serif">',
        f'<rect width="{size}" height="{size}" fill="{BORDER_COLOR}"/>',
    ]

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            x = PADDING + c * CELL
            y = PADDING + r * CELL
            cell = board.grid[r][c]
            has_letter = cell.letter is not None

            fill = LETTER_TILE_COLOR if has_letter else BONUS_COLORS[cell.bonus]
            parts.append(
                f'<rect x="{x+1}" y="{y+1}" width="{CELL-2}" height="{CELL-2}" '
                f'rx="3" fill="{fill}"/>'
            )

            if has_letter:
                parts.append(
                    f'<text x="{x+CELL/2}" y="{y+CELL/2+7}" font-size="18" '
                    f'font-weight="bold" text-anchor="middle" '
                    f'fill="{LETTER_TEXT_COLOR}">{cell.letter}</text>'
                )
            else:
                label = BONUS_LABELS[cell.bonus]
                if label:
                    parts.append(
                        f'<text x="{x+CELL/2}" y="{y+CELL/2+4}" font-size="10" '
                        f'text-anchor="middle" fill="#ffffffcc">{label}</text>'
                    )

            if (r, c) in highlight_uncertain:
                parts.append(
                    f'<rect x="{x+1}" y="{y+1}" width="{CELL-2}" height="{CELL-2}" '
                    f'rx="3" fill="none" stroke="#e03131" stroke-width="3"/>'
                )
            if (r, c) in highlight_new:
                parts.append(
                    f'<rect x="{x+1}" y="{y+1}" width="{CELL-2}" height="{CELL-2}" '
                    f'rx="3" fill="none" stroke="#f2b705" stroke-width="3"/>'
                )

    parts.append("</svg>")
    return "".join(parts)


def move_to_svg(board: Board, move) -> str:
    """Toont het bord MET een specifieke voorgestelde zet erop gelegd,
    met de nieuw te plaatsen tegels (die je zelf nog moet neerleggen)
    gemarkeerd met een gouden rand. Cellen die al een letter hadden
    (bestaande bordletters die toevallig deel uitmaken van het woord)
    krijgen geen markering."""
    length = len(move.word)
    if move.horizontal:
        cells = [(move.row, move.col + i) for i in range(length)]
    else:
        cells = [(move.row + i, move.col) for i in range(length)]

    new_cells = {(r, c) for (r, c) in cells if board.grid[r][c].letter is None}

    preview_board = board.clone()
    preview_board.place_word(move.word, move.row, move.col, move.horizontal)
    return board_to_svg(preview_board, highlight_new=new_cells)


def apply_move_and_consume_rack(board: Board, rack: str, move) -> tuple[str, str]:
    """
    Past `move` toe op een kopie van `board` en geeft het nieuwe bord
    (als tekst, klaar om in het invoerveld te plakken) en het bijgewerkte
    rack terug (de gebruikte letters eraf, blanco's als '?').

    Alleen letters die NIEUW op het bord komen (d.w.z. het vakje was
    daarvoor leeg) worden van het rack afgehaald -- letters die al op het
    bord lagen en hergebruikt worden door dit woord tellen niet mee.
    """
    from board_ocr import board_to_text  # lokale import om circulaire import te vermijden

    length = len(move.word)
    if move.horizontal:
        cells = [(move.row, move.col + i) for i in range(length)]
    else:
        cells = [(move.row + i, move.col) for i in range(length)]

    remaining_rack = list(rack.upper())
    for (r, c), letter in zip(cells, move.word):
        if board.grid[r][c].letter is None:  # nieuw, dus van het rack
            if letter in remaining_rack:
                remaining_rack.remove(letter)
            elif "?" in remaining_rack:
                remaining_rack.remove("?")
            # anders: mismatch (zou niet moeten gebeuren bij een geldige zet) -> negeren

    new_board = board.clone()
    new_board.place_word(move.word, move.row, move.col, move.horizontal)
    return board_to_text(new_board), "".join(remaining_rack)


def safety_gradient_color(exposure: float, low: float = 0.0, high: float = 25.0) -> str:
    """
    Groen (veilig) -> geel -> rood (risicovol) op basis van de kansgewogen
    exposure_score (verwachte punten die de tegenstander op blootgestelde
    bonusvakjes kan scoren). 0 punten = volledig groen, `high` of meer =
    volledig rood. De exacte grens (25) is met de hand gekozen als
    "een TW met een gemiddelde letter erop" -- geen wetenschappelijke
    ijking, maar een redelijk gevoel voor wat 'veel' risico is.
    """
    t = max(0.0, min(1.0, (exposure - low) / (high - low))) if high > low else 0.0
    # Vlakke-UI-kleuren: groen #2ecc71 -> geel #f1c40f -> rood #e74c3c
    stops = [(0.0, (46, 204, 113)), (0.5, (241, 196, 15)), (1.0, (231, 76, 60))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t0 <= t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            r = round(c0[0] + frac * (c1[0] - c0[0]))
            g = round(c0[1] + frac * (c1[1] - c0[1]))
            b = round(c0[2] + frac * (c1[2] - c0[2]))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#e74c3c"


def safety_badge_html(exposure: float) -> str:
    """Klein gekleurd label ('veilig'/'gemiddeld'/'risicovol') voor in een
    zetkaart, als visuele aanvulling op de numerieke Safety Index."""
    color = safety_gradient_color(exposure)
    label = "veilig" if exposure < 5 else "risicovol" if exposure > 18 else "gemiddeld"
    return (
        f'<span style="background:{color};color:white;padding:2px 10px;'
        f'border-radius:12px;font-size:0.8em;font-weight:600;'
        f'display:inline-block;">{label}</span>'
    )


if __name__ == "__main__":
    b = Board()
    b.place_word("HUIS", row=7, col=6, horizontal=True)
    svg = board_to_svg(b, highlight_uncertain={(7, 6)})
    with open("/tmp/board_preview.svg", "w") as f:
        f.write(svg)
    print("SVG geschreven naar /tmp/board_preview.svg, lengte:", len(svg))
