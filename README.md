# Wordfeud AI Assistant (Fase 1 — PWA-backend)

Een strategische Nederlandse Wordfeud-assistent. Deze repo bevat de
Fase 1 "brain" (Streamlit-webapp): woordenboek, zetgenerator en een
masterbrein-analyselaag. Fase 2 (een native Android-overlay-app die
deze backend aanspreekt) volgt later.

## Bestanden

| Bestand | Verantwoordelijkheid |
|---|---|
| `app.py` | Streamlit-UI: bord/rack invoeren, zetten tonen, woordenboek trainen, stenen-tracker |
| `board_skeleton.py` | 15×15 bord, officiële bonusvakjes-layout, `CandidateMove`-datastructuur |
| `trie.py` | Prefixboom voor snelle woord-lookups |
| `move_generator.py` | De echte zetgenerator: anchor + cross-check-algoritme (vindt ook automatisch parallelle kruiswoorden) |
| `strategy.py` | Het "masterbrein": kansgewogen risico, 2-ply-lookahead, exact eindspel, bingo-sturing, coach-uitleg |
| `lexicon_manager.py` | Whitelist/blacklist-beheer (persistent op schijf) |
| `tile_tracker.py` | Houdt de 104 Nederlandse Wordfeud-stenen bij, incl. eindspel-deductie van het tegenstanderrack |
| `dictionary_loader.py` | Downloadt de officiële OpenTaal-woordenlijst (>400.000 woorden) en zet 'm om naar bordklare vorm |
| `board_ocr.py` | Leest een screenshot van een lopend potje uit (bord + rack) via kleurclassificatie + OCR |
| `board_svg.py` | Visuele SVG-weergave van het bord en van voorgestelde zetten (welke tegels waar neerleggen) |
| `requirements.txt` | Python-dependencies voor Streamlit Cloud |
| `packages.txt` | Systeem-dependency (`tesseract-ocr`) die Streamlit Cloud via apt-get installeert -- nodig voor de screenshot-functie |

## Lokaal draaien

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Live hosten (Streamlit Community Cloud)

1. Push deze repo naar GitHub (public).
2. Ga naar [share.streamlit.io](https://share.streamlit.io), log in met GitHub.
3. **New app** → kies deze repo → main file: `app.py` → **Deploy**.
4. Open de resulterende link op je telefoon → "Toevoegen aan startscherm".

## Bekende beperkingen

- **Meerdere potjes tegelijk**: kies/maak een potje bovenaan het scherm.
  Elk potje bewaart zijn eigen bord, rack én score in de URL. Bij heel
  veel gelijktijdige potjes kan de link lang worden.
- **Standscore-bewuste analyse**: vul je eigen score en die van je
  tegenstander in -- het masterbrein speelt voorzichtiger als je voorstaat
  en agressiever als je achterstaat (zie `compute_risk_weight` in
  `strategy.py`). Bij elke zoekactie zie je zowel de veiligste zet
  (bij jouw stand) als de hoogst scorende, met een 🟢🟡🔴-kleurcode per
  zet gebaseerd op het risico.
- De Stenen-tracker is nog gedeeld over alle potjes, niet per potje apart.
- Het demo-woordenboek is klein (~25 woorden) totdat je op "📥 Laad
  volledige woordenlijst" klikt — de app waarschuwt hier nu prominent
  voor op het "Zetten zoeken"-tabblad zelf.
- Whitelist/blacklist worden lokaal op schijf opgeslagen
  (`wf_whitelist.txt` / `wf_blacklist.txt`). Op Streamlit Community
  Cloud gaat dat verloren bij een herstart/redeploy — gebruik de
  downloadknoppen om een back-up te bewaren.
- De 2-ply-lookahead is kansgewogen gesimuleerd (Monte Carlo), niet
  exact — dat kan pas zodra het tegenstanderrack met zekerheid bekend
  is (eindspel, wanneer de stenenpot leeg is).
- Screenshot-upload in de APP zelf werkt op sommige toestellen niet
  betrouwbaar (nog niet opgelost — lijkt browser-/netwerkgerelateerd,
  niet iets in de Python-code). De onderliggende OCR-module
  (`board_ocr.py`) werkt wél aantoonbaar goed op losse screenshots;
  het is specifiek de upload-widget die op sommige apparaten vastloopt.
- De standaardbordlayout in `board_skeleton.py` is empirisch bevestigd
  via een echt screenshot (180°- én diagonaal-symmetrisch). Willekeurige
  ("random") Wordfeud-borden wijken hier wél van af — daarvoor is OCR
  nodig om de echte layout van dát specifieke potje te kennen.
