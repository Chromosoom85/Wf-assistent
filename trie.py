"""
trie.py
-------
Eenvoudige Trie (prefixboom) voor het woordenboek. Dit is de datastructuur
die de zetgenerator gebruikt om tijdens het opbouwen van een woord, letter
voor letter, meteen te weten: "is dit nog een geldig voorvoegsel?" en
"is dit een compleet, geldig woord?" -- zonder ooit het hele woordenboek
te hoeven doorzoeken.

Waarom geen volledige GADDAG?
Een GADDAG maakt het mogelijk om vanuit een willekeurige letter zowel
links als rechts uit te breiden in één structuur. Dat is efficiënter,
maar aanzienlijk complexer om te bouwen en te debuggen. Met een rack van
maximaal 7 letters en een bord van 15x15 is de eenvoudigere aanpak
(Appel & Jacobson, 1988: aparte links-uitbreiding gevolgd door een
rechts-uitbreiding per anchor) ruim snel genoeg, en veel makkelijker te
begrijpen en te onderhouden. Dit bestand implementeert een gewone Trie;
move_generator.py implementeert de links/rechts-uitbreidingslogica erbovenop.
"""

from __future__ import annotations


class TrieNode:
    __slots__ = ("children", "is_word")

    def __init__(self) -> None:
        self.children: dict[str, "TrieNode"] = {}
        self.is_word: bool = False


class Trie:
    def __init__(self, words: list[str] | None = None) -> None:
        self.root = TrieNode()
        if words:
            for w in words:
                self.insert(w)

    def insert(self, word: str) -> None:
        node = self.root
        for ch in word.upper():
            node = node.children.setdefault(ch, TrieNode())
        node.is_word = True

    def has_word(self, word: str) -> bool:
        node = self._walk(word)
        return node is not None and node.is_word

    def has_prefix(self, prefix: str) -> bool:
        return self._walk(prefix) is not None

    def _walk(self, s: str) -> TrieNode | None:
        node = self.root
        for ch in s.upper():
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    @classmethod
    def from_lexicon(cls, lexicon) -> "Trie":
        """
        Bouw een Trie uit een LexiconManager: basiswoordenboek + whitelist,
        MINUS de blacklist (die mag nooit als geldig woord getoond worden).
        """
        words = set(lexicon._base_dictionary) | set(lexicon.whitelist)
        words -= set(lexicon.blacklist)
        return cls(words)


if __name__ == "__main__":
    t = Trie(["HUIS", "HUIZEN", "HOND"])
    print(t.has_word("HUIS"))       # True
    print(t.has_prefix("HUI"))      # True
    print(t.has_word("HUI"))        # False (prefix, geen woord)
    print(t.has_prefix("XYZ"))      # False
