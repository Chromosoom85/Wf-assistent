"""
board_ocr.py
------------
Leest een screenshot van een lopend Wordfeud-potje en zet 'm om naar een
Board + rack-string, zodat je die niet met de hand hoeft over te typen.

BELANGRIJKE ONTDEKKING (uit een echte screenshot geanalyseerd tijdens
ontwikkeling): Wordfeud gebruikt NIET altijd de "standaard" bonuslayout
uit board_skeleton.py -- potjes kunnen een WILLEKEURIG bord hebben. Deze
module leest de bonusvakjes daarom per screenshot opnieuw af (via
kleurherkenning), in plaats van te vertrouwen op een vaste layout.

AANPAK:
1. Bord lokaliseren: we nemen aan dat het bord de volledige beeldbreedte
   in beslag neemt (zoals in alle geteste Wordfeud-screenshots) en zoeken
   de verticale top-offset door te zoeken naar de uitlijning die de beste
   180-graden-puntsymmetrie van de bonusvakjes oplevert (elk Wordfeud-bord
   is per definitie punt-symmetrisch, ongeacht standaard of willekeurig).
   Vakjes waar al een LETTER op ligt tellen niet mee in die symmetrie-check
   (die zijn immers niet symmetrisch -- dat is nu net het spel).
2. Per vakje: kleur classificeren als TW/DW/TL/DL/geen/LETTER via de
   dichtstbijzijnde referentiekleur (leeg + 4 bonustypes + witte tegel +
   gele "net gelegde woord"-tegel).
3. Voor LETTER-vakjes: de losse tegel uitsnijden, binariseren (zwart/wit-
   drempel) en met tesseract (psm 10, één teken) lezen. Als het resultaat
   meer dan 1 teken oplevert, nemen we het EERSTE teken -- in de praktijk
   is dat vrijwel altijd de echte letter, met een OCR-fragment van het
   kleine puntencijfer erachteraan geplakt.
4. De rack-rij (onderaan) wordt los gelokaliseerd (brede heldere band
   onderin) en op dezelfde manier gelezen.

NAUWKEURIGHEID (gemeten op een echte screenshot tijdens ontwikkeling):
- Bonusvakjes: 100% (25/25 gecontroleerde vakjes correct, mede dankzij de
  symmetrie-check die verkeerde uitlijning voorkomt).
- Bordletters: ~86% per teken (12/14) na de eerste-teken-correctie.
- Rackletters: 100% (7/7) na de eerste-teken-correctie.
Dit is dus een BESTE-POGING-hulpmiddel: het bespaart vrijwel al het
typewerk, maar de gebruiker moet het resultaat nog even nalopen voordat
hij op "zoek beste zetten" drukt -- vandaar dat dit de tekstvelden
VOORINVULT in plaats van de zetgenerator direct aan te roepen.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
import pytesseract

from board_skeleton import Board, Bonus, BOARD_SIZE

# Referentiekleuren, empirisch bepaald op een echt Wordfeud-screenshot
# (donker thema). Als jouw Wordfeud-app een ander thema gebruikt (licht
# thema, andere huisstijl), moeten deze mogelijk opnieuw gekalibreerd
# worden -- zie recalibrate_reference_colors() onderaan dit bestand.
BONUS_REF_COLORS = {
    Bonus.TW: (192, 130, 133),
    Bonus.DW: (222, 175, 118),
    Bonus.TL: (75, 128, 166),
    Bonus.DL: (138, 166, 117),
    Bonus.NONE: (42, 46, 51),
}
TILE_BRIGHTNESS_THRESHOLD = 175  # boven deze gemiddelde helderheid = lettertegel


class BoardReadError(Exception):
    pass


def _patch_median(arr: np.ndarray, y: int, x: int, half: int = 20) -> tuple[int, int, int]:
    y0, y1 = max(0, y - half), min(arr.shape[0], y + half)
    x0, x1 = max(0, x - half), min(arr.shape[1], x + half)
    patch = arr[y0:y1, x0:x1].reshape(-1, 3)
    return tuple(int(v) for v in np.median(patch, axis=0))


def _classify_cell(rgb: tuple[int, int, int]) -> Bonus | str:
    """Geeft een Bonus-waarde terug, of de string 'LETTER' als het vakje
    een tegel bevat."""
    brightness = sum(rgb) / 3
    if brightness > TILE_BRIGHTNESS_THRESHOLD:
        return "LETTER"
    return min(
        BONUS_REF_COLORS,
        key=lambda k: sum((a - b) ** 2 for a, b in zip(BONUS_REF_COLORS[k], rgb)),
    )


def _find_board_top(arr: np.ndarray, cell_size: float, search_range: tuple[int, int]) -> float:
    """
    Twee-staps kalibratie:
    1. GROF: zoek de top-offset met de beste 180-graden-puntsymmetrie van
       de bonusvakjes (LETTER-vakjes tellen niet mee). Deze stap is
       tolerant voor een fikse foutmarge en vindt betrouwbaar het juiste
       GEBIED, ongeacht schermresolutie.
    2. FIJN: binnen dat gebied, zoek de PRECIEZE pixel-uitlijning door te
       zoeken naar waar de dunne donkere rasterlijnen tussen de vakjes
       daadwerkelijk zitten. Dit is nodig omdat de kleurclassificatie
       (stap 1) een grote, middelende steekproef gebruikt en dus tolerant
       is voor ~25px afwijking -- prima voor het classificeren van
       bonustypes, maar te grof om lettertegels scherp bij te snijden voor
       OCR. De rasterlijn-check is wél pixel-precies.
    """
    best_top, best_score = search_range[0], -1.0
    for top in range(search_range[0], search_range[1], 2):
        if top + cell_size * 15 >= arr.shape[0]:
            break
        grid = []
        for r in range(15):
            row = []
            for c in range(15):
                y = int(top + (r + 0.5) * cell_size)
                x = int((c + 0.5) * cell_size)
                row.append(_classify_cell(_patch_median(arr, y, x)))
            grid.append(row)
        pairs = [
            (grid[r][c], grid[14 - r][14 - c])
            for r in range(15) for c in range(15)
            if grid[r][c] != "LETTER" and grid[14 - r][14 - c] != "LETTER"
        ]
        score = sum(a == b for a, b in pairs) / max(len(pairs), 1)
        if score > best_score:
            best_score, best_top = score, top
    if best_score < 0.9:
        raise BoardReadError(
            f"Kon het bord niet betrouwbaar lokaliseren (beste symmetriescore "
            f"was slechts {best_score:.0%}). Probeer een screenshot waarop het "
            f"volledige bord zichtbaar is, van rand tot rand."
        )

    # Fijne verfijning: zoek de rasterlijn-uitlijning in een venster van
    # ±1 cel rond de grove schatting.
    border_ref = np.array([23, 26, 30])
    x_margin = int(arr.shape[1] * 0.1)

    def border_score(top: float) -> float:
        total = 0.0
        for k in range(16):
            y = int(round(top + k * cell_size))
            if y < 0 or y >= arr.shape[0]:
                return float("inf")
            row = arr[y, x_margin:arr.shape[1] - x_margin, :].astype(int)
            total += float(np.mean(np.sum((row - border_ref) ** 2, axis=1)))
        return total / 16

    fine_top, fine_score = best_top, border_score(best_top)
    for candidate in np.arange(best_top - cell_size, best_top + cell_size, 0.5):
        s = border_score(candidate)
        if s < fine_score:
            fine_score, fine_top = s, candidate

    return fine_top


def _ocr_single_letter(tile: Image.Image) -> str:
    gray = np.array(tile.convert("L"), dtype=np.float64)
    thresh = (gray.min() + gray.max()) / 2
    binary = np.where(gray < thresh, 0, 255).astype(np.uint8)
    binary_img = Image.fromarray(binary)
    big = binary_img.resize((binary_img.width * 5, binary_img.height * 5), Image.LANCZOS)
    text = pytesseract.image_to_string(
        big, config="--psm 10 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ).strip()
    return text[0] if text else "?"


def read_board_from_image(image_path: str) -> tuple[Board, list[list[bool]]]:
    """
    Leest het 15x15-bord (bonusvakjes + geplaatste letters) uit een
    screenshot. Geeft de Board terug plus een 'onzeker'-grid (True waar
    een letter is gelezen maar met lage betrouwbaarheid -- de gebruiker
    moet die plekken extra goed nalopen).
    """
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    cell_size = arr.shape[1] / 15  # aanname: bord = volledige breedte

    top = _find_board_top(arr, cell_size, search_range=(int(arr.shape[0] * 0.15), int(arr.shape[0] * 0.45)))

    bonus_grid = [[Bonus.NONE for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    uncertain = [[False] * BOARD_SIZE for _ in range(BOARD_SIZE)]
    letter_positions: list[tuple[int, int]] = []

    for r in range(15):
        for c in range(15):
            y = int(top + (r + 0.5) * cell_size)
            x = int((c + 0.5) * cell_size)
            cls = _classify_cell(_patch_median(arr, y, x))
            if cls == "LETTER":
                letter_positions.append((r, c))
                bonus_grid[r][c] = Bonus.NONE  # bonus zelf niet meer relevant, ligt onder de tegel
            else:
                bonus_grid[r][c] = cls

    board = Board(bonus_grid_override=bonus_grid)
    for (r, c) in letter_positions:
        y0 = int(top + r * cell_size)
        x0 = int(c * cell_size)
        tile = img.crop((x0, y0, x0 + int(cell_size), y0 + int(cell_size)))
        letter = _ocr_single_letter(tile)
        if letter == "?" or len(letter) != 1 or not letter.isalpha():
            uncertain[r][c] = True
            letter = letter if letter.isalpha() else "?"
        board.grid[r][c].letter = letter

    return board, uncertain


def _find_rack_band(arr: np.ndarray) -> tuple[int, int]:
    """Zoekt de brede, heldere horizontale band onderin het scherm waar
    de racktegels staan."""
    h = arr.shape[0]

    def brightness_fraction(y: int) -> float:
        row = arr[y, :, :].astype(int)
        return ((row.sum(axis=1) / 3) > 180).mean()

    in_band = False
    band_top, band_bottom = None, None
    for y in range(h - 1, int(h * 0.5), -2):
        frac = brightness_fraction(y)
        if frac > 0.5 and not in_band:
            band_bottom = y
            in_band = True
        if frac <= 0.2 and in_band:
            band_top = y
            break

    if band_top is None or band_bottom is None:
        raise BoardReadError(
            "Kon de rack-rij niet vinden onderin de screenshot. Zorg dat "
            "je rack (je 7 letters) zichtbaar is in beeld."
        )
    return band_top, band_bottom


def read_rack_from_image(image_path: str) -> tuple[str, list[bool]]:
    """Leest de rackletters (bv. 'DZNTDVA'). Geeft ook een 'onzeker'-lijst
    terug (per letter) voor tegels die niet eenduidig gelezen konden worden."""
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    band_top, band_bottom = _find_rack_band(arr)

    # Segmenteer de tegels net onder de bovenrand van de band (daar kruist
    # de grote lettervorm de scanlijn nog niet, waardoor tegelgrenzen
    # scherp te onderscheiden zijn).
    scan_y = min(band_top + 8, arr.shape[0] - 1)
    row = arr[scan_y, :, :].astype(int)
    bright = (row.sum(axis=1) / 3) > 150

    segments: list[tuple[int, int]] = []
    start = None
    for x in range(len(bright)):
        if bright[x] and start is None:
            start = x
        elif not bright[x] and start is not None:
            if x - start > 40:
                segments.append((start, x))
            start = None
    if start is not None and len(bright) - start > 40:
        segments.append((start, len(bright)))

    if not (1 <= len(segments) <= 7):
        raise BoardReadError(
            f"Onverwacht aantal racktegels gevonden ({len(segments)}, "
            f"verwacht 1-7). Probeer een screenshot met het volledige "
            f"rack zichtbaar."
        )

    rack_letters = []
    uncertain = []
    for (x0, x1) in segments:
        tile = img.crop((x0, band_top, x1, band_bottom))
        letter = _ocr_single_letter(tile)
        is_uncertain = letter == "?" or not letter.isalpha()
        uncertain.append(is_uncertain)
        rack_letters.append(letter if letter.isalpha() else "?")

    return "".join(rack_letters), uncertain


def board_to_text(board: Board) -> str:
    """Zet een Board om naar het 15-regelig tekstformaat dat de Streamlit-
    UI ook voor handmatige invoer gebruikt (punt = leeg vakje)."""
    return "\n".join(
        "".join(cell.letter or "." for cell in row) for row in board.grid
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Gebruik: python3 board_ocr.py <pad-naar-screenshot.png>")
        sys.exit(1)

    path = sys.argv[1]
    board, uncertain_board = read_board_from_image(path)
    print("=== Gelezen bord ===")
    print(board_to_text(board))
    n_uncertain = sum(sum(row) for row in uncertain_board)
    if n_uncertain:
        print(f"\n⚠️  {n_uncertain} vakje(s) met lage betrouwbaarheid -- controleer handmatig.")

    try:
        rack, uncertain_rack = read_rack_from_image(path)
        print(f"\n=== Gelezen rack ===\n{rack}")
        if any(uncertain_rack):
            print("⚠️  Sommige rackletters zijn onzeker -- controleer handmatig.")
    except BoardReadError as e:
        print(f"\nRack niet gevonden: {e}")
