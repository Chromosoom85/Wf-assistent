"""
app.py
------
Minimale Streamlit-interface die de Fase 1-modules samenbrengt:
- LexiconManager  (whitelist/blacklist)
- TileTracker     (104-stenen pot + eindspel-deductie)
- Board / CandidateMove (conceptueel, scoring-demo)

Dit is NOG GEEN volledige move-generator (die volgt in de volgende stap).
Doel van dit scherm: alle bouwstenen zichtbaar en testbaar maken, zodat
je vanaf hier de UI kunt uitbreiden zodra de echte generator klaar is.

Starten (lokaal):
    pip install streamlit
    streamlit run app.py

Dit opent een browser-tab op http://localhost:8501 -- vanaf een
telefoon op hetzelfde wifi-netwerk kun je ook naar het IP-adres van je
laptop + poort 8501 surfen. Zie onderaan dit bestand voor hoe je hem
ook "installeerbaar" (PWA) maakt.
"""

from __future__ import annotations

import json

import streamlit as st

from lexicon_manager import LexiconManager
from tile_tracker import TileTracker, DUTCH_TILE_POINTS
from trie import Trie
from board_skeleton import Board, BOARD_SIZE, CandidateMove
from move_generator import generate_moves
from dictionary_loader import download_opentaal_wordlist
from strategy import analyze_moves, rack_bingo_potential, find_words_from_letters, compute_risk_weight
from board_ocr import read_board_from_image, read_rack_from_image, board_to_text, BoardReadError
from board_svg import board_to_svg, move_to_svg, apply_move_and_consume_rack, safety_gradient_color, safety_badge_html

st.set_page_config(page_title="Wordfeud AI Assistant", page_icon="🟩", layout="wide")


@st.cache_resource(show_spinner=False)
def _load_full_dutch_dictionary() -> set[str]:
    """
    Gecached over alle sessies heen binnen deze serverinstantie: de
    download gebeurt dus maar één keer per herstart van de app, niet bij
    elke bezoeker opnieuw. Geeft een lege set terug als er geen
    internettoegang is -- de app blijft dan gewoon werken met het kleine
    demo-woordenboek.
    """
    return download_opentaal_wordlist()


# ----------------------------------------------------------------------
# State: één instantie per browsersessie. In Fase 1 volstaat dit; zodra
# je meerdere gebruikers/apparaten tegelijk wilt bedienen (Fase 2, de
# APK praat met dezelfde server), verhuist deze state naar een
# database/JSON-store per gebruikers-ID.
# ----------------------------------------------------------------------
if "lexicon" not in st.session_state:
    # TODO: vervang demo_dict door de echte OpenTaal/Scrabble-woordenlijst.
    # Dit is bewust nog een kleine handmatige set, puur om de move-generator
    # te kunnen demonstreren zonder een extern bestand nodig te hebben.
    demo_dict = {
        "HUIS", "HUIZEN", "AUTO", "KAT", "KATER", "HOND", "TAFEL", "STOEL",
        "RAT", "RATEL", "TAK", "TAKEL", "EX", "EL", "OP", "TE", "EEN", "AAN",
        "PF", "ATE", "TARA", "KATOEN", "OER", "TERRA", "PORTO", "ROTA",
    }
    st.session_state.lexicon = LexiconManager(base_dictionary=demo_dict)

    # Black-/whitelist herstellen vanuit de URL (zie de sync helemaal
    # onderaan dit bestand) -- niet vertrouwen op de lokale schijf van de
    # server, want die wordt bij elke herstart/redeploy gewist. Zonder dit
    # zou de 🚫-afwijsknop in de praktijk nauwelijks iets uithalen.
    for _w in st.query_params.get("blacklist", "").split(","):
        if _w:
            st.session_state.lexicon.reject_word(_w)
    for _w in st.query_params.get("whitelist", "").split(","):
        if _w:
            st.session_state.lexicon.add_to_whitelist(_w)

    # Meteen de volledige woordenlijst laden bij het opstarten, zodat je dit
    # niet elke keer na een herstart van de app handmatig hoeft te doen.
    # Dit maakt de EERSTE keer laden na een (her)start een paar seconden
    # trager, maar scheelt daarna een verplichte extra stap voor iedereen.
    with st.spinner("Volledige Nederlandse woordenlijst laden (eenmalig na herstart)..."):
        try:
            _full_words = _load_full_dutch_dictionary()
            if _full_words:
                st.session_state.lexicon.set_base_dictionary(_full_words)
                st.session_state["full_dict_loaded"] = True
        except Exception:
            pass  # blijft gewoon op het demo-woordenboek staan; knop in de UI blijft als fallback

if "tracker" not in st.session_state:
    st.session_state.tracker = TileTracker()

lex: LexiconManager = st.session_state.lexicon
tracker: TileTracker = st.session_state.tracker

# Wijzigingen die knoppen willen aanbrengen aan widget-waarden (bord, rack,
# scores, het actieve potje, ...) mogen NOOIT direct via
# st.session_state[key] = ... gebeuren nadat die widget al getekend is in
# deze run -- Streamlit staat dat niet toe (StreamlitAPIException). Daarom
# zet elke knop zijn wijziging klaar in _pending_updates en roept
# st.rerun() aan; HIER, als allereerste in het HELE script (dus vóór ook
# maar één widget is aangemaakt, inclusief de potje-kiezer hieronder),
# passen we die wijzigingen alsnog toe.
_pending = st.session_state.pop("_pending_updates", None)
if _pending:
    for _key, _value in _pending.items():
        st.session_state[_key] = _value


def _flat_to_board_text(flat: str) -> str:
    """225 aaneengesloten tekens -> 15 regels van 15 tekens."""
    flat = (flat + "." * 225)[:225]
    return "\n".join(flat[i * 15:(i + 1) * 15] for i in range(15))


def _board_text_to_flat(text: str) -> str:
    """15 regels van 15 tekens -> 225 aaneengesloten tekens (voor de URL)."""
    lines = (text.splitlines() + ["." * 15] * 15)[:15]
    lines = [l.ljust(15, ".")[:15] for l in lines]
    return "".join(lines)


# ----------------------------------------------------------------------
# MEERDERE POTJES tegelijk, elk met een eigen bord/rack/score, bewaard in
# de URL (query params) als één JSON-blokje. Waarom in de URL en niet
# (alleen) in session_state: session_state leeft maar zolang de app-
# server-instantie draait -- na een herstart (nieuwe push, of de gratis
# Streamlit Cloud-instantie die in slaap valt) is dat leeg, ook al staat
# de link nog open in je browser. De URL zelf overleeft dat WEL.
#
# Beperking: dit deelt de link dus je HELE spelstand. Met heel veel
# gelijktijdige potjes kan de URL lang worden (elk potje kost ~250
# tekens) -- voor een handvol potjes ruim binnen de norm, bij tientallen
# potjes tegelijk zou dat een keer krap kunnen worden.
# ----------------------------------------------------------------------
def _load_games() -> dict:
    raw = st.query_params.get("games", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _save_games(games: dict) -> None:
    st.query_params["games"] = json.dumps(games, separators=(",", ":"))


_games = _load_games()

if "current_game_id" not in st.session_state:
    st.session_state["current_game_id"] = st.query_params.get(
        "current_game", next(iter(_games), "Potje 1")
    )

if "board_text_input" not in st.session_state:
    _cur_game = _games.get(st.session_state["current_game_id"], {})
    st.session_state["board_text_input"] = _flat_to_board_text(_cur_game.get("board", ""))
    st.session_state["rack_text_input"] = _cur_game.get("rack", "")
    st.session_state["my_score_input"] = _cur_game.get("my_score", 0)
    st.session_state["opp_score_input"] = _cur_game.get("opp_score", 0)


def parse_board_text(board_text: str) -> tuple[Board | None, str | None]:
    """Zet de 15x15 tekstinvoer om in een Board, of geeft een foutmelding
    terug. Gedeeld tussen de rack-analyse en de zoekknop, zodat beide
    exact hetzelfde bord zien."""
    rows = (board_text.splitlines() + ["." * BOARD_SIZE] * BOARD_SIZE)[:BOARD_SIZE]
    rows = [r.ljust(BOARD_SIZE, ".")[:BOARD_SIZE] for r in rows]

    board = Board()
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch != ".":
                if not ch.isalpha():
                    return None, f"Ongeldig teken '{ch}' op rij {r+1}, kolom {c+1}."
                board.grid[r][c].letter = ch.upper()
    return board, None


st.title("🟩 Wordfeud AI Assistant")
st.caption(
    "Masterbrein-engine: zetgenerator, kansgewogen risico-analyse, "
    "2-ply/eindspel-lookahead, bingo-sturing en coach-uitleg."
)

# ------------------------------------------------------------------
# Potje-kiezer: welk potje ben je aan het spelen? Bepaalt welk bord/rack/
# score de rest van het scherm laat zien. Staat boven de tabs omdat het
# alles daaronder beïnvloedt.
# ------------------------------------------------------------------
_existing_game_ids = sorted(_games.keys())
_options = _existing_game_ids + ["➕ Nieuw potje..."]
_current = st.session_state["current_game_id"]

if st.session_state.get("_game_selector") not in _options:
    st.session_state["_game_selector"] = _current if _current in _options else _options[-1]

col_game, col_my_score, col_opp_score = st.columns([3, 1, 1])
with col_game:
    _selected = st.selectbox(
        "🎮 Potje", _options, key="_game_selector",
        help="Elk potje bewaart zijn eigen bord, rack en score, ook na een herstart van de app.",
    )
with col_my_score:
    st.session_state.setdefault("my_score_input", 0)
    st.number_input(
        "Mijn score", min_value=0, step=1, key="my_score_input",
        help="Bepaalt hoe voorzichtig/agressief het masterbrein speelt.",
    )
with col_opp_score:
    st.session_state.setdefault("opp_score_input", 0)
    st.number_input("Tegenstander", min_value=0, step=1, key="opp_score_input")

if _selected == "➕ Nieuw potje...":
    _new_name = st.text_input(
        "Naam nieuw potje (bv. naam tegenstander)", key="_new_game_name_input"
    )
    if st.button("Potje aanmaken") and _new_name.strip():
        st.session_state["_pending_updates"] = {
            "current_game_id": _new_name.strip(),
            "board_text_input": "\n".join(["." * BOARD_SIZE] * BOARD_SIZE),
            "rack_text_input": "",
            "my_score_input": 0,
            "opp_score_input": 0,
        }
        st.rerun()
elif _selected != _current:
    # Gebruiker koos een ANDER, al bestaand potje -> laad diens data.
    _switch_to = _games.get(_selected, {})
    st.session_state["_pending_updates"] = {
        "current_game_id": _selected,
        "board_text_input": _flat_to_board_text(_switch_to.get("board", "")),
        "rack_text_input": _switch_to.get("rack", ""),
        "my_score_input": _switch_to.get("my_score", 0),
        "opp_score_input": _switch_to.get("opp_score", 0),
    }
    st.rerun()

st.caption(f"Actief potje: **{_current}**" + (f" ({len(_existing_game_ids)} potje(s) opgeslagen)" if _existing_game_ids else ""))
st.divider()

tab_moves, tab_lexicon, tab_tiles, tab_about = st.tabs(
    ["🧠 Zetten zoeken", "📖 Woordenboek trainen", "🎲 Stenen-tracker", "ℹ️ Over dit scherm"]
)

# ------------------------------------------------------------------
# TAB 0: Zetten zoeken (de echte move-generator)
# ------------------------------------------------------------------
with tab_moves:
    if not st.session_state.get("full_dict_loaded", False):
        st.error(
            f"⚠️ **Automatisch laden van de volledige woordenlijst is niet "
            f"gelukt** -- je zit nog op het kleine DEMO-woordenboek "
            f"({lex.stats()['base_dictionary']} woorden), vandaar matige "
            f"suggesties. Waarschijnlijk een tijdelijk netwerkprobleem: "
            f"klik hieronder om het opnieuw te proberen."
        )
        if st.button("📥 Laad nu de volledige woordenlijst", type="primary"):
            with st.spinner("Bezig met downloaden en verwerken (kan even duren)..."):
                try:
                    full_words = _load_full_dutch_dictionary()
                    if full_words:
                        lex.set_base_dictionary(full_words)
                        st.session_state["full_dict_loaded"] = True
                        st.success(f"{len(full_words):,} woorden geladen! Klaar om te zoeken.")
                        st.rerun()
                    else:
                        st.error(
                            "Downloaden leverde geen woorden op -- check je "
                            "internetverbinding en probeer opnieuw."
                        )
                except Exception as e:
                    st.error(f"Downloaden mislukt: {e}")
        st.divider()

    with st.expander("📷 Bord inlezen vanaf screenshot (experimenteel)", expanded=False):
        st.caption(
            "Werkt op sommige toestellen niet betrouwbaar. Lukt het niet? "
            "Deel je screenshot in de Claude-chat -- die leest 'm uit en "
            "geeft je kant-en-klare tekst voor het geavanceerde bordveld hieronder."
        )
        uploaded_screenshot = st.file_uploader(
            "Screenshot uploaden (.png of .jpg)", type=["png", "jpg", "jpeg"]
        )

        if uploaded_screenshot is not None:
            st.image(uploaded_screenshot, caption="Geüpload bestand", width=200)

            # Verwerk alleen automatisch als dit een NIEUW bestand is (anders
            # zou elke rerun -- ook na het aanpassen van rack/bord met de hand
            # -- de OCR opnieuw draaien en je handmatige correcties overschrijven).
            file_signature = f"{uploaded_screenshot.name}-{uploaded_screenshot.size}"
            already_processed = st.session_state.get("_last_ocr_signature") == file_signature

            if not already_processed:
                tmp_path = f"/tmp/{uploaded_screenshot.name}"
                with open(tmp_path, "wb") as f:
                    f.write(uploaded_screenshot.getbuffer())

                with st.spinner("Bord en rack aan het herkennen..."):
                    try:
                        ocr_board, uncertain_board = read_board_from_image(tmp_path)
                        n_uncertain_board = sum(sum(row) for row in uncertain_board)

                        ocr_rack, uncertain_rack = read_rack_from_image(tmp_path)
                        n_uncertain_rack = sum(uncertain_rack)

                        st.session_state["_pending_updates"] = {
                            "board_text_input": board_to_text(ocr_board),
                            "rack_text_input": ocr_rack,
                        }
                        st.session_state["_last_ocr_signature"] = file_signature
                        st.session_state["_last_ocr_message"] = (
                            "success",
                            "✅ Bord en rack ingelezen."
                            + (
                                f" ⚠️ {n_uncertain_board} bordvakje(s) en "
                                f"{n_uncertain_rack} rackletter(s) met lage "
                                f"betrouwbaarheid -- controleer hieronder even."
                                if (n_uncertain_board or n_uncertain_rack) else ""
                            ),
                        )
                    except BoardReadError as e:
                        st.session_state["_last_ocr_signature"] = file_signature
                        st.session_state["_last_ocr_message"] = (
                            "error", f"Kon de screenshot niet verwerken: {e}"
                        )
                    except Exception as e:
                        # Vang ALLES af (bv. ontbrekende tesseract-systeembinary
                        # op de server) zodat je nooit met een stille, lege
                        # pagina blijft zitten.
                        st.session_state["_last_ocr_signature"] = file_signature
                        st.session_state["_last_ocr_message"] = (
                            "error",
                            f"Onverwachte fout tijdens het inlezen: "
                            f"{type(e).__name__}: {e}. Check 'Manage app' → "
                            f"logs als dit blijft gebeuren.",
                        )
                st.rerun()

    last_msg = st.session_state.get("_last_ocr_message")
    if last_msg:
        kind, text = last_msg
        (st.success if kind == "success" else st.error)(text)

    st.divider()
    st.subheader("Bord invoeren")

    default_board_text = "\n".join(["." * BOARD_SIZE for _ in range(BOARD_SIZE)])
    st.session_state.setdefault("board_text_input", default_board_text)
    current_board_text = st.session_state["board_text_input"]
    board_preview, board_preview_error = parse_board_text(current_board_text)

    st.markdown("**✍️ Woord op het bord zetten**")

    col_row, col_col, col_dir = st.columns(3)
    with col_row:
        place_row = st.number_input(
            "Rij", min_value=1, max_value=BOARD_SIZE, value=8, key="place_row",
            help="Rijnummer 1-15, van boven naar beneden.",
        )
    with col_col:
        place_col = st.number_input(
            "Kolom", min_value=1, max_value=BOARD_SIZE, value=8, key="place_col",
            help="Kolomnummer 1-15, van links naar rechts.",
        )
    with col_dir:
        place_horizontal = st.radio(
            "Richting", ["→", "↓"], key="place_dir",
            help="→ = horizontaal (naar rechts), ↓ = verticaal (naar beneden).",
        ) == "→"

    place_word_input = st.text_input(
        "Woord (? = blanco tegel)", key="place_word_input"
    ).upper()
    place_is_own_move = st.checkbox(
        "Eigen zet (haalt gebruikte letters van je rack af)",
        value=True, key="place_is_own_move",
        help="Zet uit voor een zet van je tegenstander -- dan blijft je rack ongewijzigd.",
    )

    preview_move = None
    if place_word_input and not board_preview_error:
        r0, c0 = int(place_row) - 1, int(place_col) - 1
        length = len(place_word_input)
        fits = (
            (place_horizontal and c0 + length <= BOARD_SIZE)
            or (not place_horizontal and r0 + length <= BOARD_SIZE)
        )
        if not fits:
            st.error("Dit woord past niet meer op het bord vanaf deze positie/richting.")
        else:
            preview_move = CandidateMove(
                word=place_word_input, row=r0, col=c0,
                horizontal=place_horizontal, raw_score=0,
            )
            cells = (
                [(r0, c0 + i) for i in range(length)] if place_horizontal
                else [(r0 + i, c0) for i in range(length)]
            )
            conflicts = [
                (r, c) for (r, c), ch in zip(cells, place_word_input)
                if board_preview.grid[r][c].letter not in (None, ch)
            ]
            if conflicts:
                st.warning(
                    f"⚠️ Op {len(conflicts)} vakje(s) ligt al een ANDERE letter -- "
                    f"controleer of rij/kolom/richting kloppen."
                )

    # --- Eén enkel, altijd-zichtbaar bord: toont de live preview van het
    # woord dat je aan het intikken bent, of anders gewoon de huidige stand. ---
    st.markdown("**Bord:**")
    if board_preview_error:
        st.warning(f"Kan geen bord tonen: {board_preview_error}")
    else:
        st.caption("⚠️ Bonusvakjes tonen de STANDAARDlayout; bij een willekeurig bord kunnen kleuren afwijken. Letters kloppen wel altijd.")
        if preview_move is not None:
            st.markdown(move_to_svg(board_preview, preview_move), unsafe_allow_html=True)
            st.caption("🟡 Goud = hier komt het woord te liggen.")
        else:
            st.markdown(board_to_svg(board_preview), unsafe_allow_html=True)

    if preview_move is not None:
        if st.button("✅ Zet dit woord op het bord", type="primary"):
            if place_is_own_move:
                new_board_text, new_rack = apply_move_and_consume_rack(
                    board_preview, st.session_state.get("rack_text_input", ""),
                    preview_move,
                )
            else:
                new_board = board_preview.clone()
                new_board.place_word(place_word_input, r0, c0, place_horizontal)
                new_board_text = board_to_text(new_board)
                new_rack = st.session_state.get("rack_text_input", "")
            # Nooit direct st.session_state[...] zetten voor een widget die
            # deze run al getekend is (bv. het tekstveld hierboven) -- dat
            # geeft een StreamlitAPIException. Zet 'm klaar en herlaad.
            st.session_state["_pending_updates"] = {
                "board_text_input": new_board_text,
                "rack_text_input": new_rack,
                "place_word_input": "",
            }
            st.session_state.pop("_last_moves", None)
            st.session_state.pop("_last_search_board_text", None)
            st.success("Woord op het bord gezet!")
            st.rerun()

    with st.expander("⚙️ Geavanceerd: bord direct als tekst bewerken"):
        st.caption(
            "Voor uitzonderingen of snel plakken van OCR-tekst die je van "
            "mij kreeg. 15 regels van 15 tekens; punt '.' = leeg vakje."
        )
        board_text = st.text_area(
            "Bordstatus (15 regels × 15 tekens)",
            height=280,
            key="board_text_input",
        )

    board_text = st.session_state["board_text_input"]
    board_preview, board_preview_error = parse_board_text(board_text)

    st.session_state.setdefault("rack_text_input", "")
    rack_input = st.text_input(
        "Jouw rack (7 letters, gebruik ? voor een blanco)",
        key="rack_text_input",
    ).upper()

    if rack_input.strip():
        with st.expander("🔤 Wat kan ik met dit rack maken?"):
            trie_preview = Trie.from_lexicon(lex)
            words = find_words_from_letters(rack_input, trie_preview)
            if words:
                st.write(", ".join(words[:40]))
            else:
                st.caption("Geen woorden gevonden met het huidige woordenboek.")

            if board_preview_error:
                st.warning(
                    f"Kan het bord niet lezen ({board_preview_error}) — "
                    f"bingo-check hieronder is daarom alleen op het "
                    f"woordenboek gebaseerd, niet op plaatsing."
                )
            bingo_info = rack_bingo_potential(
                rack_input, trie_preview, tracker,
                board=board_preview if not board_preview_error else None,
            )
            placement_note = (
                " (gecontroleerd of het ook echt op dit bord past)"
                if bingo_info["board_aware"] else
                " (nog geen check of het ook op het bord past — vul het bord in voor die check)"
            )
            if bingo_info["current_bingos"]:
                st.success(
                    "🎉 Bingo mogelijk NU" + placement_note + ": "
                    + ", ".join(bingo_info["current_bingos"])
                )
            elif bingo_info["best_discard"]:
                st.info(
                    f"💡 Geen bingo nu, maar loos je een **{bingo_info['best_discard']}**, "
                    f"dan is de kans op een plaatsbare bingo bij je volgende trekking "
                    f"~{bingo_info['best_discard_ev']:.0%}" + placement_note + "."
                )
            elif bingo_info["board_aware"]:
                st.caption(
                    "Geen enkele letterwisseling levert op dit moment een "
                    "plaatsbare bingo op (het bord blokkeert het, of het "
                    "woordenboek kent geen passend 7-letterwoord)."
                )

    st.divider()
    col_toggle, col_samples = st.columns([2, 1])
    with col_toggle:
        deep_analysis = st.checkbox(
            "🧠 Masterbrein-analyse (2-ply lookahead / exact eindspel + coach-uitleg)",
            value=st.session_state.get("deep_analysis", False),
            help=(
                "Simuleert per topzet ook de te verwachten tegenzet (kansgewogen "
                "zolang de pot niet leeg is, exact zodra het tegenstander-rack "
                "bekend is) en geeft een uitleg in gewone taal. Kost meer rekentijd."
            ),
        )
    with col_samples:
        n_samples = st.slider(
            "Steekproeven (2-ply)", min_value=4, max_value=30, value=10,
            disabled=not deep_analysis,
        )

    if st.button("🔍 Zoek beste zetten", type="primary"):
        board, parse_error = parse_board_text(board_text)

        my_score = st.session_state.get("my_score_input", 0)
        opp_score = st.session_state.get("opp_score_input", 0)
        dynamic_risk_weight = compute_risk_weight(my_score, opp_score)

        if parse_error:
            st.error(parse_error)
        elif not rack_input.strip():
            st.warning("Vul eerst je rack in.")
        else:
            trie = Trie.from_lexicon(lex)
            if deep_analysis:
                with st.spinner(
                    "Bezig met diepgaande analyse (zetten genereren + "
                    "tegenzetten simuleren)..."
                ):
                    moves = analyze_moves(
                        board, rack_input, trie, tracker,
                        top_k=8, n_samples=n_samples, risk_weight=dynamic_risk_weight,
                    )
                if tracker.is_bag_empty():
                    st.caption(
                        "♟️ Pot is leeg — tegenzetten hieronder zijn EXACT "
                        "berekend met het afgeleide tegenstanderrack, niet gesimuleerd."
                    )
            else:
                with st.spinner("Bezig met zoeken..."):
                    moves = generate_moves(board, rack_input, trie, risk_weight=dynamic_risk_weight)

            if not moves:
                st.info(
                    "Geen geldige zetten gevonden met het huidige "
                    "(demo-)woordenboek. Breid de woordenlijst uit in het "
                    "tabblad 'Woordenboek trainen', of controleer de bordinvoer."
                )
            else:
                st.success(f"{len(moves)} geldige zet(ten) gevonden.")
                st.session_state["_last_moves"] = moves
                st.session_state["_last_search_board_text"] = board_text

                def _render_move_card(m, badge_extra: str = "", key_suffix: str = "list"):
                    richting = "→ horizontaal" if m.horizontal else "↓ verticaal"
                    with st.container(border=True):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            titel = f"### {m.word}"
                            if m.is_bingo:
                                titel += " 🎉 BINGO"
                            st.markdown(titel)
                            st.markdown(
                                safety_badge_html(m.exposure_score) + badge_extra,
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                f"Positie ({m.row + 1}, {m.col + 1}) · {richting}"
                            )
                            if m.cross_words:
                                st.caption("Kruiswoorden: " + ", ".join(m.cross_words))
                            if m.explanation:
                                st.caption("🧭 " + m.explanation)
                            with st.expander("📍 Toon op bord"):
                                st.markdown(
                                    move_to_svg(board_preview, m),
                                    unsafe_allow_html=True,
                                )
                                st.caption("Goud omrand = hier een tegel neerleggen.")
                        with col2:
                            st.metric("Score", m.raw_score)
                            if deep_analysis:
                                st.metric("Masterbrein-waarde", f"{m.advanced_value(dynamic_risk_weight):.1f}")
                                if m.expected_opponent_response > 0:
                                    st.caption(f"Verw. tegenzet: {m.expected_opponent_response:.0f}")
                                if m.endgame_bonus > 0:
                                    st.caption(f"Eindspelbonus: +{m.endgame_bonus}")
                            else:
                                st.metric("Safety Index", f"{m.safety_index(dynamic_risk_weight):.1f}")

                        _apply_key = f"apply_{key_suffix}_{m.word}_{m.row}_{m.col}_{m.horizontal}"
                        if st.button("✅ Zet dit woord op het bord", key=_apply_key, type="primary"):
                            _new_board_text, _new_rack = apply_move_and_consume_rack(
                                board_preview, rack_input, m
                            )
                            st.session_state["_pending_updates"] = {
                                "board_text_input": _new_board_text,
                                "rack_text_input": _new_rack,
                            }
                            st.session_state.pop("_last_moves", None)
                            st.session_state.pop("_last_search_board_text", None)
                            st.success(f"'{m.word}' op het bord gezet! Resterend rack: {_new_rack or '(leeg)'}")
                            st.rerun()

                        # key_suffix zorgt dat dezelfde zet (bv. tegelijk de
                        # 'veiligste' EN gewoon onderdeel van de volledige
                        # lijst) nooit twee widgets met dezelfde key oplevert
                        # -- dat gaf eerder een StreamlitDuplicateElementKey-crash.
                        _reject_options = [m.word] + list(m.cross_words)
                        _reject_key_base = f"{key_suffix}_{m.word}_{m.row}_{m.col}_{m.horizontal}"
                        if len(_reject_options) > 1:
                            _to_reject = st.multiselect(
                                "Woord(en) hier afwijzen",
                                _reject_options,
                                key=f"reject_select_{_reject_key_base}",
                                help=(
                                    "Vaak is niet het hoofdwoord het probleem, "
                                    "maar een los kruiswoordje (bv. een "
                                    "afkorting die Wordfeud niet accepteert) "
                                    "-- selecteer specifiek dát woord."
                                ),
                            )
                        else:
                            _to_reject = (
                                [m.word] if st.checkbox(
                                    f"🚫 '{m.word}' afwijzen",
                                    key=f"reject_check_{_reject_key_base}",
                                ) else []
                            )

                        if _to_reject and st.button(
                            "Geselecteerde woord(en) afwijzen",
                            key=f"reject_btn_{_reject_key_base}",
                        ):
                            for _w in _to_reject:
                                lex.reject_word(_w)
                            st.warning(
                                f"Afgewezen: {', '.join(_to_reject)} — "
                                f"worden vanaf nu nooit meer gesuggereerd "
                                f"(ook niet als kruiswoord bij een andere zet)."
                            )
                            st.rerun()

                # ------------------------------------------------------------
                # Aanbevolen voor jouw situatie: de zet die het beste past bij
                # de huidige stand (safest_pick, al score-bewust gesorteerd),
                # PLUS -- als die afwijkt -- de hoogst scorende zet als
                # alternatief, zodat je zelf altijd de knoop kunt doorhakken.
                # ------------------------------------------------------------
                st.markdown("### 🎯 Aanbevolen voor jouw situatie")
                score_diff = my_score - opp_score
                threshold = 20
                if score_diff > threshold:
                    st.info(
                        f"📈 Je staat **{score_diff} punten voor** — de veilige "
                        f"zet hieronder ligt voor de hand, tenzij het "
                        f"hoogstscorende alternatief het risico duidelijk waard is."
                    )
                elif score_diff < -threshold:
                    st.info(
                        f"📉 Je staat **{-score_diff} punten achter** — een "
                        f"risicovollere zet kan de moeite waard zijn om terug "
                        f"in de wedstrijd te komen."
                    )
                else:
                    st.info(
                        "⚖️ De stand is ongeveer gelijk — een goede balans "
                        "tussen score en veiligheid."
                    )

                safest_pick = moves[0]  # al gesorteerd met het standscore-bewuste risicogewicht
                highest_score_pick = max(moves, key=lambda m: m.raw_score)
                same_move = (
                    safest_pick.word == highest_score_pick.word
                    and safest_pick.row == highest_score_pick.row
                    and safest_pick.col == highest_score_pick.col
                    and safest_pick.horizontal == highest_score_pick.horizontal
                )

                _render_move_card(
                    safest_pick,
                    badge_extra=" &nbsp; ⭐ <b>aanbevolen voor deze stand</b>" if not same_move else "",
                    key_suffix="featured_safe",
                )
                if same_move:
                    st.caption(
                        "✅ Dit is toevallig ook meteen de hoogst scorende "
                        "zet — geen lastige keuze nu."
                    )
                else:
                    st.markdown("**Of ga toch voor de hoogste score:**")
                    _render_move_card(
                        highest_score_pick,
                        badge_extra=" &nbsp; 🚀 <b>hoogst scorend</b>",
                        key_suffix="featured_score",
                    )

                st.divider()
                st.markdown("### Alle gevonden zetten")
                st.caption(
                    "🟢 veilig · 🟡 gemiddeld · 🔴 risicovol -- gebaseerd op de "
                    "kansgewogen kans dat de tegenstander een bonusvakje benut "
                    "dat deze zet openlegt."
                )
                for _idx, m in enumerate(moves[:20]):
                    _render_move_card(m, key_suffix=f"list{_idx}")

    # ------------------------------------------------------------------
    # Interactieve woord-browser: kies een woord uit de laatste zoekactie,
    # blader met vorige/volgende door de mogelijke plaatsingen op het bord,
    # en pas 'm met één klik toe (bord + rack worden automatisch bijgewerkt).
    # Staat BUITEN het zoek-knop-blok zodat bladeren (dat ook een rerun
    # veroorzaakt) niet vereist dat je opnieuw op 'Zoek beste zetten' klikt.
    # ------------------------------------------------------------------
    last_moves = st.session_state.get("_last_moves")
    last_moves_board_text = st.session_state.get("_last_search_board_text")
    if last_moves and last_moves_board_text == board_text:
        st.divider()
        st.subheader("🎯 Blader per woord")
        st.caption(
            "Kies een woord, blader met ◀/▶ door de mogelijke plekken op "
            "het bord, en klik op 'Pas toe' zodra je 'm virtueel wilt "
            "neerleggen -- dat werkt automatisch je bord en rack bij."
        )

        words_seen = []
        for m in last_moves:
            if m.word not in words_seen:
                words_seen.append(m.word)

        if st.session_state.get("browse_word") not in words_seen:
            st.session_state.pop("browse_word", None)
        chosen_word = st.selectbox("Welk woord wil je bekijken?", words_seen, key="browse_word")

        placements_for_word = [m for m in last_moves if m.word == chosen_word]

        browse_key = f"browse_idx_{chosen_word}"
        st.session_state.setdefault(browse_key, 0)
        idx = st.session_state[browse_key] % len(placements_for_word)
        current_move = placements_for_word[idx]

        col_prev, col_pos, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Vorige", disabled=len(placements_for_word) <= 1):
                st.session_state[browse_key] = (idx - 1) % len(placements_for_word)
                st.rerun()
        with col_pos:
            st.markdown(
                f"<div style='text-align:center'>Plek {idx + 1} / "
                f"{len(placements_for_word)}</div>",
                unsafe_allow_html=True,
            )
        with col_next:
            if st.button("Volgende ▶", disabled=len(placements_for_word) <= 1):
                st.session_state[browse_key] = (idx + 1) % len(placements_for_word)
                st.rerun()

        richting = "→ horizontaal" if current_move.horizontal else "↓ verticaal"
        st.caption(
            f"Positie ({current_move.row + 1}, {current_move.col + 1}) · "
            f"{richting} · score {current_move.raw_score}"
        )
        st.markdown(move_to_svg(board_preview, current_move), unsafe_allow_html=True)

        if st.button("✅ Pas deze zet toe (werkt bord + rack bij)", type="primary"):
            new_board_text, new_rack = apply_move_and_consume_rack(
                board_preview, rack_input, current_move
            )
            st.session_state["_pending_updates"] = {
                "board_text_input": new_board_text,
                "rack_text_input": new_rack,
            }
            # Oude zoekresultaten horen niet meer bij het bijgewerkte bord.
            st.session_state.pop("_last_moves", None)
            st.session_state.pop("_last_search_board_text", None)
            st.success(f"Zet toegepast! Resterend rack: {new_rack or '(leeg)'}")
            st.rerun()

    st.divider()
    with st.expander("ℹ️ Hoe werkt het masterbrein?"):
        st.markdown(
            """
            **Safety Index** (altijd actief): score + racksaldo-bonus −
            risico van blootgestelde bonusvakjes (TW/DW/TL/DL).

            Met **🧠 Masterbrein-analyse** aangevinkt komt daar per topzet
            bovenop:
            - **Kansgewogen risico**: het risico wordt niet met vaste
              gewichten berekend, maar met de daadwerkelijke resterende
              letterkansen uit de Stenen-tracker — een TW naast alleen
              nog zeldzame letters is minder gevaarlijk dan een TW waar
              nog veel hoge-puntletters passen.
            - **Verwachte tegenzet**: zolang de pot nog niet leeg is,
              wordt N keer een plausibel tegenstander-rack gesimuleerd
              (kansgewogen) en hun beste antwoord gemiddeld. Zodra de pot
              wél leeg is en het tegenstander-rack dus exact bekend is
              (via de Stenen-tracker), wordt dit EXACT berekend, geen
              simulatie meer nodig.
            - **Eindspelbonus**: als deze zet je rack leegspeelt terwijl
              de pot leeg is, tel je de puntwaarde van de tegels die de
              tegenstander nog vasthoudt bij je score op (officiële
              Wordfeud-regel).
            - **Bingo-badge**: gebruikt de zet alle 7 rackletters (+40
              bonus), dan zie je 🎉 BINGO.
            - **Coach-uitleg**: een korte samenvatting in gewone taal van
              waarom een zet wel/niet aantrekkelijk is.

            De **Masterbrein-waarde** waarop dan gesorteerd wordt is:
            `score + racksaldo − risico − verwachte tegenzet + eindspelbonus`.
            """
        )

# ------------------------------------------------------------------
# TAB 1: Whitelist / Blacklist beheer
# ------------------------------------------------------------------
with tab_lexicon:
    st.subheader("📚 Volledige Nederlandse woordenlijst")
    st.caption(
        "Laadt de officiële OpenTaal-woordenlijst (>400.000 woorden, incl. "
        "~170.000 vervoegingen/verbuigingen zoals 'werke', 'stoeltjes') — "
        "dezelfde bron waar Wordfeud's eigen Nederlandse woordenboek op "
        "gebaseerd is. Woorden met accenten/koppeltekens worden automatisch "
        "omgezet naar hun bordvorm (bv. geëerd → GEEERD, taxi's → TAXIS)."
    )
    dict_loaded = st.session_state.get("full_dict_loaded", False)
    col_load, col_status = st.columns([1, 2])
    with col_load:
        if st.button("📥 Laad volledige woordenlijst" if not dict_loaded
                      else "🔄 Opnieuw laden"):
            with st.spinner("Bezig met downloaden en verwerken (kan even duren)..."):
                try:
                    full_words = _load_full_dutch_dictionary()
                    if full_words:
                        lex.set_base_dictionary(full_words)
                        st.session_state["full_dict_loaded"] = True
                        st.success(f"{len(full_words):,} woorden geladen!")
                    else:
                        st.error(
                            "Downloaden leverde geen woorden op — waarschijnlijk "
                            "geen internettoegang in deze omgeving. Dit werkt "
                            "wél zodra de app op Streamlit Cloud draait."
                        )
                except Exception as e:
                    st.error(f"Downloaden mislukt: {e}")
    with col_status:
        if dict_loaded:
            st.info(f"✅ Volledige woordenlijst actief ({lex.stats()['base_dictionary']:,} woorden)")
        else:
            st.warning("⚠️ Nog op het kleine demo-woordenboek (~25 woorden)")

    st.divider()

    st.subheader("Woord controleren")
    check_word = st.text_input("Typ een woord om te checken", key="check_word").strip()
    if check_word:
        geldig = lex.is_valid(check_word)
        if geldig:
            st.success(f"'{check_word.upper()}' is op dit moment GELDIG voor de engine.")
        else:
            st.error(f"'{check_word.upper()}' is op dit moment ONGELDIG voor de engine.")

    col_wl, col_bl = st.columns(2)

    with col_wl:
        st.markdown("**➕ Whitelist** — woorden die Wordfeud wél accepteert, "
                     "maar die (nog) niet in het standaardwoordenboek staan.")
        new_wl_word = st.text_input("Woord toevoegen aan whitelist", key="add_wl")
        if st.button("Toevoegen aan whitelist") and new_wl_word.strip():
            lex.add_to_whitelist(new_wl_word)
            st.success(f"'{new_wl_word.upper()}' toegevoegd aan whitelist.")
            st.rerun()

        st.write(f"Aantal whitelist-woorden: {len(lex.whitelist)}")
        if lex.whitelist:
            st.code(", ".join(sorted(lex.whitelist)))

    with col_bl:
        st.markdown("**🚫 Blacklist** — woorden die de engine ooit voorstelde, "
                     "maar die Wordfeud in de praktijk AFKEURDE (incl. afkortingen!).")
        new_bl_word = st.text_input("Woord afkeuren (blacklist)", key="add_bl")
        if st.button("Markeer als afgekeurd") and new_bl_word.strip():
            lex.reject_word(new_bl_word)
            st.warning(f"'{new_bl_word.upper()}' toegevoegd aan blacklist — "
                       f"wordt nooit meer gesuggereerd.")
            st.rerun()

        st.write(f"Aantal blacklist-woorden: {len(lex.blacklist)}")
        if lex.blacklist:
            st.code(", ".join(sorted(lex.blacklist)))

    st.divider()
    stats = lex.stats()
    st.metric("Woorden in basiswoordenboek", stats["base_dictionary"])



    st.divider()
    st.subheader("💾 Back-up (belangrijk bij hosting op Streamlit Cloud!)")
    st.caption(
        "Op Streamlit Community Cloud gaat alles wat lokaal is opgeslagen "
        "verloren zodra de app herstart of opnieuw wordt gedeployed. "
        "Download hier je lijsten en zet ze terug in je GitHub-repo "
        "(als wf_whitelist.txt / wf_blacklist.txt) om ze te bewaren."
    )
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "⬇️ Download whitelist",
            data="\n".join(sorted(lex.whitelist)),
            file_name="wf_whitelist.txt",
            mime="text/plain",
        )
    with col_dl2:
        st.download_button(
            "⬇️ Download blacklist",
            data="\n".join(sorted(lex.blacklist)),
            file_name="wf_blacklist.txt",
            mime="text/plain",
        )

# ------------------------------------------------------------------
# TAB 2: Tile Tracker
# ------------------------------------------------------------------
with tab_tiles:
    st.subheader("Letters markeren als 'gezien'")
    st.caption(
        "Voer hier de letters in die je op het BORD ziet liggen, en apart "
        "de letters die op JOUW rack liggen. Zodra de pot leeg is, kun je "
        "het rack van je tegenstander exact afleiden."
    )

    col_board, col_rack = st.columns(2)
    with col_board:
        board_letters = st.text_input(
            "Letters op het bord (bv. HUISKAT)", key="board_letters"
        ).upper()
        if st.button("Verwerk bordletters") and board_letters:
            errors = []
            for ch in board_letters:
                if ch.isalpha():
                    try:
                        tracker.mark_seen(ch, location="board")
                    except ValueError as e:
                        errors.append(str(e))
            if errors:
                st.error(" / ".join(errors))
            else:
                st.success(f"{len(board_letters)} bordletters verwerkt.")
            st.rerun()

    with col_rack:
        rack_letters = st.text_input(
            "Letters op jouw rack (bv. TAFELS?)", key="rack_letters"
        ).upper()
        if st.button("Verwerk rackletters") and rack_letters:
            errors = []
            for ch in rack_letters:
                letter = "*" if ch == "?" else ch
                if letter.isalpha() or letter == "*":
                    try:
                        tracker.mark_seen(letter, location="rack")
                    except ValueError as e:
                        errors.append(str(e))
            if errors:
                st.error(" / ".join(errors))
            else:
                st.success(f"{len(rack_letters)} rackletters verwerkt.")
            st.rerun()

    st.divider()

    snap = tracker.snapshot()
    st.metric("Stenen nog onverdeeld (pot + tegenstander)", snap["remaining_in_bag"])

    if tracker.is_bag_empty():
        st.success("🎯 De pot is leeg! Exacte rack van de tegenstander:")
        opp = tracker.deduce_opponent_rack()
        st.code(", ".join(f"{k}×{v}" for k, v in sorted(opp.items())) if opp else "—")
    else:
        st.info("Pot nog niet leeg — hieronder een kansinschatting per letter.")
        probs = tracker.estimate_opponent_probabilities()
        top_probs = sorted(probs.items(), key=lambda kv: -kv[1])[:8]
        if top_probs:
            st.bar_chart({letter: p for letter, p in top_probs})

    with st.expander("Volledig overzicht per letter"):
        st.json(snap["remaining_per_letter"])

    if st.button("🔄 Reset stenen-tracker"):
        st.session_state.tracker = TileTracker()
        st.rerun()

# ------------------------------------------------------------------
# TAB 3: Uitleg
# ------------------------------------------------------------------
with tab_about:
    st.markdown(
        """
        ### Wat is dit scherm wel/niet?

        **Wel:** een werkende zetgenerator (anchor + cross-check +
        Trie-algoritme) die alle geldige zetten vindt inclusief automatisch
        gevonden parallelle kruiswoorden, plus whitelist/blacklist-training,
        de stenen-tracker, én een "masterbrein"-analyselaag (strategy.py):
        kansgewogen risico, 2-ply/eindspel-lookahead, bingo-sturing en
        coach-uitleg (aan te zetten in het tabblad "Zetten zoeken").

        **Nog niet:**
        - Screenshot-OCR bestaat (`board_ocr.py`) maar de upload-knop werkt
          op sommige toestellen niet betrouwbaar (browser/netwerk-
          gerelateerd). Werkt het niet? Deel je screenshot hier in de chat
          met Claude, die leest 'm uit en geeft je kant-en-klare tekst.
        - De 2-ply-simulatie gebruikt willekeurige steekproeven uit de
          Stenen-tracker-kansverdeling, geen exacte minimax-boom (dat zou
          met een dictionary van 400.000+ woorden te traag worden voor
          interactief gebruik). Alleen in het exacte eindspel (pot leeg,
          tegenstander-rack bekend) is de tegenzet-berekening exact.
        - Meerdere potjes tegelijk (bovenaan de kiezer) + bord/rack/score
          worden per potje in de URL bewaard (zie de adresbalk na een
          wijziging) zodat een pagina-herlaad of het heropenen van de link
          je potjes herstelt. Bewaar/deel dus de VOLLEDIGE link als je 'm
          wilt hervatten -- een ingekorte of oude link mist die informatie.
          Bij heel veel gelijktijdige potjes kan de link lang worden.
        - De Stenen-tracker is nog gedeeld over alle potjes (niet per
          potje apart) -- prima voor één potje tegelijk bijhouden, maar
          nog geen aparte stenen-stand per tegenstander.

        ### Hoe wordt dit een installeerbare PWA?

        Streamlit-apps zijn standaard 'gewoon' webapps. Om ze
        installeerbaar te maken (icoon op je startscherm, appgevoel)
        voegen we in een volgende stap een `manifest.json` en
        service-worker toe. Dat raakt dit bestand niet aan — het is een
        kwestie van een paar regels HTML/JS die Streamlit meestuurt.
        """
    )

# ------------------------------------------------------------------
# Actief potje (bord + rack + score) terugschrijven naar de URL, zodat de
# huidige stand overleeft na een pagina-herlaad of het heropenen van de
# link -- ook als de app-server ondertussen herstart is. Dit staat
# helemaal aan het einde zodat het de LAATSTE waarden van deze run pakt,
# na alles wat de tabs hierboven aan session_state veranderd kunnen hebben.
# ------------------------------------------------------------------
if "board_text_input" in st.session_state:
    _games[st.session_state["current_game_id"]] = {
        "board": _board_text_to_flat(st.session_state["board_text_input"]),
        "rack": st.session_state.get("rack_text_input", ""),
        "my_score": st.session_state.get("my_score_input", 0),
        "opp_score": st.session_state.get("opp_score_input", 0),
    }
    _save_games(_games)
    st.query_params["current_game"] = st.session_state["current_game_id"]

# Black-/whitelist terugschrijven naar de URL -- zelfde reden als hierboven:
# de lokale schijf van de server overleeft geen herstart, de URL wel. Dit
# zorgt dat de 🚫-afwijsknop (en handmatig toegevoegde whitelist-woorden)
# blijvend effect hebben, ook na een redeploy.
if lex.blacklist:
    st.query_params["blacklist"] = ",".join(sorted(lex.blacklist))
if lex.whitelist:
    st.query_params["whitelist"] = ",".join(sorted(lex.whitelist))
