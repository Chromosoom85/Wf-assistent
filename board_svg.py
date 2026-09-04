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



    b = Board()
    b.place_word("HUIS", row=7, col=6, horizontal=True)
    svg = board_to_svg(b, highlight_uncertain={(7, 6)})
    with open("/tmp/board_preview.svg", "w") as f:
        f.write(svg)
    print("SVG geschreven naar /tmp/board_preview.svg, lengte:", len(svg))
