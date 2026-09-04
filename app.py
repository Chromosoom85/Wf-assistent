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

import streamlit as st

from lexicon_manager import LexiconManager
from tile_tracker import TileTracker, DUTCH_TILE_POINTS
from trie import Trie
from board_skeleton import Board, BOARD_SIZE
from move_generator import generate_moves
from dictionary_loader import download_opentaal_wordlist
from strategy import analyze_moves, rack_bingo_potential, find_words_from_letters
from board_ocr import read_board_from_image, read_rack_from_image, board_to_text, BoardReadError

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

if "tracker" not in st.session_state:
    st.session_state.tracker = TileTracker()

lex: LexiconManager = st.session_state.lexicon
tracker: TileTracker = st.session_state.tracker


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

tab_moves, tab_lexicon, tab_tiles, tab_about = st.tabs(
    ["🧠 Zetten zoeken", "📖 Woordenboek trainen", "🎲 Stenen-tracker", "ℹ️ Over dit scherm"]
)

# ------------------------------------------------------------------
# TAB 0: Zetten zoeken (de echte move-generator)
# ------------------------------------------------------------------
with tab_moves:
    st.subheader("📷 Bord inlezen vanaf screenshot")
    st.caption(
        "Upload een screenshot van je Wordfeud-potje (bord + rack zichtbaar) "
        "-- dit vult het bord en je rack automatisch in. Controleer het "
        "resultaat altijd even voordat je op 'Zoek beste zetten' drukt: "
        "letterherkenning is een beste-poging, geen garantie."
    )
    uploaded_screenshot = st.file_uploader(
        "Screenshot uploaden (.png of .jpg)", type=["png", "jpg", "jpeg"]
    )
    if uploaded_screenshot is not None:
        if st.button("🔍 Lees bord en rack uit deze screenshot"):
            tmp_path = f"/tmp/{uploaded_screenshot.name}"
            with open(tmp_path, "wb") as f:
                f.write(uploaded_screenshot.getbuffer())

            with st.spinner("Bord en rack aan het herkennen..."):
                try:
                    ocr_board, uncertain_board = read_board_from_image(tmp_path)
                    st.session_state["board_text_input"] = board_to_text(ocr_board)
                    n_uncertain_board = sum(sum(row) for row in uncertain_board)

                    ocr_rack, uncertain_rack = read_rack_from_image(tmp_path)
                    st.session_state["rack_text_input"] = ocr_rack
                    n_uncertain_rack = sum(uncertain_rack)

                    msg = "✅ Bord en rack ingelezen."
                    if n_uncertain_board or n_uncertain_rack:
                        msg += (
                            f" ⚠️ {n_uncertain_board} bordvakje(s) en "
                            f"{n_uncertain_rack} rackletter(s) met lage "
                            f"betrouwbaarheid -- controleer hieronder even."
                        )
                    st.success(msg)
                except BoardReadError as e:
                    st.error(f"Kon de screenshot niet verwerken: {e}")
            st.rerun()

    st.divider()
    st.subheader("Bord invoeren")
    st.caption(
        "Voer het bord in als 15 regels van 15 tekens. Gebruik een punt "
        "'.' voor een leeg vakje en de letter zelf voor een bezet vakje. "
        "Laat alles leeg voor een nieuw spel (eerste zet)."
    )

    default_board_text = "\n".join(["." * BOARD_SIZE for _ in range(BOARD_SIZE)])
    board_text = st.text_area(
        "Bordstatus (15 regels × 15 tekens)",
        value=st.session_state.get("board_text_input", default_board_text),
        height=280,
        key="board_text_input",
    )

    board_preview, board_preview_error = parse_board_text(board_text)

    rack_input = st.text_input(
        "Jouw rack (7 letters, gebruik ? voor een blanco)",
        value=st.session_state.get("rack_text_input", ""),
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
                        top_k=8, n_samples=n_samples,
                    )
                if tracker.is_bag_empty():
                    st.caption(
                        "♟️ Pot is leeg — tegenzetten hieronder zijn EXACT "
                        "berekend met het afgeleide tegenstanderrack, niet gesimuleerd."
                    )
            else:
                with st.spinner("Bezig met zoeken..."):
                    moves = generate_moves(board, rack_input, trie)

            if not moves:
                st.info(
                    "Geen geldige zetten gevonden met het huidige "
                    "(demo-)woordenboek. Breid de woordenlijst uit in het "
                    "tabblad 'Woordenboek trainen', of controleer de bordinvoer."
                )
            else:
                st.success(f"{len(moves)} geldige zet(ten) gevonden.")
                for m in moves[:20]:
                    richting = "→ horizontaal" if m.horizontal else "↓ verticaal"
                    with st.container(border=True):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            titel = f"### {m.word}"
                            if m.is_bingo:
                                titel += " 🎉 BINGO"
                            st.markdown(titel)
                            st.caption(
                                f"Positie ({m.row + 1}, {m.col + 1}) · {richting}"
                            )
                            if m.cross_words:
                                st.caption(
                                    "Kruiswoorden: " + ", ".join(m.cross_words)
                                )
                            if m.explanation:
                                st.caption("🧭 " + m.explanation)
                        with col2:
                            st.metric("Score", m.raw_score)
                            if deep_analysis:
                                st.metric(
                                    "Masterbrein-waarde",
                                    f"{m.advanced_value():.1f}",
                                )
                                if m.expected_opponent_response > 0:
                                    st.caption(
                                        f"Verw. tegenzet: {m.expected_opponent_response:.0f}"
                                    )
                                if m.endgame_bonus > 0:
                                    st.caption(f"Eindspelbonus: +{m.endgame_bonus}")
                            else:
                                st.metric("Safety Index", f"{m.safety_index():.1f}")

                        if st.button(
                            "🚫 Dit woord wordt niet geaccepteerd",
                            key=f"reject_{m.word}_{m.row}_{m.col}_{m.horizontal}",
                        ):
                            lex.reject_word(m.word)
                            st.warning(
                                f"'{m.word}' toegevoegd aan blacklist — "
                                f"wordt vanaf nu nooit meer gesuggereerd."
                            )
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
        - De volledige OpenTaal-woordenlijst moet je zelf laden via de
          knop in het tabblad "Woordenboek trainen" (gebeurt niet
          automatisch bij het opstarten, om de app snel te laten starten).
        - OCR / automatische bordherkenning vanaf een screenshot (Fase 1,
          nog te bouwen) -- voorlopig voer je het bord met de hand in.
        - De 2-ply-simulatie gebruikt willekeurige steekproeven uit de
          Stenen-tracker-kansverdeling, geen exacte minimax-boom (dat zou
          met een dictionary van 400.000+ woorden te traag worden voor
          interactief gebruik). Alleen in het exacte eindspel (pot leeg,
          tegenstander-rack bekend) is de tegenzet-berekening exact.

        ### Hoe wordt dit een installeerbare PWA?

        Streamlit-apps zijn standaard 'gewoon' webapps. Om ze
        installeerbaar te maken (icoon op je startscherm, appgevoel)
        voegen we in een volgende stap een `manifest.json` en
        service-worker toe. Dat raakt dit bestand niet aan — het is een
        kwestie van een paar regels HTML/JS die Streamlit meestuurt.
        """
    )
