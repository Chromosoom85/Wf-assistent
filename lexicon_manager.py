"""
lexicon_manager.py
-------------------
Beheert de "getrainde" woordenlijst bovenop het standaard Nederlandse
woordenboek (bijv. OpenTaal / Van Dale):

- WHITELIST: woorden die Wordfeud accepteert maar die niet (of niet
  betrouwbaar) in het standaardwoordenboek staan (bv. PF, HM, ZN, FY).
- BLACKLIST: woorden die de engine ooit voorstelde, maar die Wordfeud
  in de praktijk AFKEURDE. Deze mogen nooit meer als suggestie
  terugkomen, ook al staan ze wel in het standaardwoordenboek.

Opslag: platte tekstbestanden (1 woord per regel), zodat je ze ook met
de hand kunt inspecteren/editen. Er wordt bewust GEEN database gebruikt
in Fase 1 -- dat houdt het simpel en makkelijk te synchroniseren als je
dit bestand later gewoon meestuurt naar de Android-client.
"""

from __future__ import annotations

import os
import threading
from typing import Iterable


class LexiconManager:
    """
    Houdt een basis-woordenboek (grote set, alleen-lezen in dit voorbeeld)
    plus een whitelist en blacklist bij die persistent zijn op schijf.

    Gebruik:
        lex = LexiconManager(base_dictionary=mijn_woordenset)
        lex.is_valid("PF")          -> True/False
        lex.add_to_whitelist("PF")  -> voegt toe + slaat op
        lex.reject_word("EXPORNO")  -> zet op blacklist + slaat op
    """

    def __init__(
        self,
        base_dictionary: Iterable[str] | None = None,
        whitelist_path: str = "wf_whitelist.txt",
        blacklist_path: str = "wf_blacklist.txt",
    ) -> None:
        # Thread-lock: de Android-overlay kan in de toekomst gelijktijdige
        # verzoeken sturen (bv. review-actie tijdens een nieuwe scan).
        self._lock = threading.RLock()

        self.whitelist_path = whitelist_path
        self.blacklist_path = blacklist_path

        # Basiswoordenboek: normaliseren naar hoofdletters, zodat alle
        # vergelijkingen in de engine hoofdletterongevoelig zijn.
        self._base_dictionary: set[str] = {
            w.strip().upper() for w in (base_dictionary or []) if w.strip()
        }

        self._whitelist: set[str] = self._load(self.whitelist_path)
        self._blacklist: set[str] = self._load(self.blacklist_path)

    # ------------------------------------------------------------------
    # Persistentie
    # ------------------------------------------------------------------
    @staticmethod
    def _load(path: str) -> set[str]:
        if not os.path.exists(path):
            return set()
        with open(path, "r", encoding="utf-8") as f:
            return {line.strip().upper() for line in f if line.strip()}

    def _save(self, path: str, words: set[str]) -> None:
        # Sorteren maakt het bestand leesbaar/diff-baar (handig voor git).
        with open(path, "w", encoding="utf-8") as f:
            for word in sorted(words):
                f.write(word + "\n")

    # ------------------------------------------------------------------
    # Whitelist
    # ------------------------------------------------------------------
    def add_to_whitelist(self, word: str) -> None:
        word = word.strip().upper()
        if not word:
            return
        with self._lock:
            # Een woord kan niet tegelijk goed- en afgekeurd zijn.
            self._blacklist.discard(word)
            self._whitelist.add(word)
            self._save(self.whitelist_path, self._whitelist)
            self._save(self.blacklist_path, self._blacklist)

    def remove_from_whitelist(self, word: str) -> None:
        word = word.strip().upper()
        with self._lock:
            if word in self._whitelist:
                self._whitelist.discard(word)
                self._save(self.whitelist_path, self._whitelist)

    # ------------------------------------------------------------------
    # Blacklist ("afgekeurd door Wordfeud")
    # ------------------------------------------------------------------
    def reject_word(self, word: str) -> None:
        """Markeer een woord als afgekeurd -- wordt nooit meer gesuggereerd."""
        word = word.strip().upper()
        if not word:
            return
        with self._lock:
            self._whitelist.discard(word)
            self._blacklist.add(word)
            self._save(self.whitelist_path, self._whitelist)
            self._save(self.blacklist_path, self._blacklist)

    def unreject_word(self, word: str) -> None:
        word = word.strip().upper()
        with self._lock:
            if word in self._blacklist:
                self._blacklist.discard(word)
                self._save(self.blacklist_path, self._blacklist)

    # ------------------------------------------------------------------
    # De vraag die de engine bij ELK kandidaat-woord stelt
    # ------------------------------------------------------------------
    def is_valid(self, word: str) -> bool:
        """
        Regel-volgorde is belangrijk:
        1. Staat het op de blacklist?  -> altijd ongeldig, punt uit.
        2. Staat het op de whitelist?  -> altijd geldig (overrulet woordenboek).
        3. Staat het in het standaardwoordenboek? -> geldig.
        4. Anders: ongeldig.
        """
        word = word.strip().upper()
        if word in self._blacklist:
            return False
        if word in self._whitelist:
            return True
        return word in self._base_dictionary

    def set_base_dictionary(self, words: Iterable[str]) -> None:
        """Handig om na het laden van de echte OpenTaal-lijst te vullen."""
        with self._lock:
            self._base_dictionary = {w.strip().upper() for w in words if w.strip()}

    # ------------------------------------------------------------------
    # Introspectie (handig voor een debug-UI / instellingenscherm)
    # ------------------------------------------------------------------
    @property
    def whitelist(self) -> frozenset[str]:
        return frozenset(self._whitelist)

    @property
    def blacklist(self) -> frozenset[str]:
        return frozenset(self._blacklist)

    def stats(self) -> dict[str, int]:
        return {
            "base_dictionary": len(self._base_dictionary),
            "whitelist": len(self._whitelist),
            "blacklist": len(self._blacklist),
        }


if __name__ == "__main__":
    # Kleine zelftest / demo
    demo_dict = {"HUIS", "AUTO", "KAT", "HOND"}
    lex = LexiconManager(
        base_dictionary=demo_dict,
        whitelist_path="demo_whitelist.txt",
        blacklist_path="demo_blacklist.txt",
    )

    print("PF geldig voor training?", lex.is_valid("PF"))  # False
    lex.add_to_whitelist("PF")
    print("PF geldig na whitelist? ", lex.is_valid("PF"))  # True

    print("HUIS geldig?           ", lex.is_valid("HUIS"))  # True
    lex.reject_word("HUIS")
    print("HUIS geldig na reject? ", lex.is_valid("HUIS"))  # False

    print("Stats:", lex.stats())

    # opruimen van demo-bestanden
    os.remove("demo_whitelist.txt")
    os.remove("demo_blacklist.txt")
