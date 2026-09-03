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
| `requirements.txt` | Python-dependencies voor Streamlit Cloud |

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

- Het demo-woordenboek is klein (~25 woorden) totdat je op "📥 Laad
  volledige woordenlijst" klikt in het tabblad *Woordenboek trainen*.
- Whitelist/blacklist worden lokaal op schijf opgeslagen
  (`wf_whitelist.txt` / `wf_blacklist.txt`). Op Streamlit Community
  Cloud gaat dat verloren bij een herstart/redeploy — gebruik de
  downloadknoppen om een back-up te bewaren.
- De 2-ply-lookahead is kansgewogen gesimuleerd (Monte Carlo), niet
  exact — dat kan pas zodra het tegenstanderrack met zekerheid bekend
  is (eindspel, wanneer de stenenpot leeg is).
