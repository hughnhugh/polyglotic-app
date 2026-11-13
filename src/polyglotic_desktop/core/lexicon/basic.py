"""Basic dictionaries: lookups in a caption language beyond Chinese and
English, from a dictionary pack (decision 0035; polyglotic-hq project
157's "basic" tier - open data, no human check of the meanings).

A pack is a dictionary file like CC-CEDICT's, plus a word split for its
language (`ports.word_split`): Sudachi for Japanese, letters and
simplemma for Spanish. A word in a caption is looked up as, in order:
1. the dictionary forms the word split found for it in its line
   (Japanese: "食べ" in 食べました is 食べる);
2. the pack's own inflection table, then the word's own entries - as
   written, then in lower case (Spanish: "supe" is saber; "casa" is
   house);
3. the word split's out-of-context guesses (simplemma), if nothing else
   was found.

Entries keep their pack's IDs (`jmdict:`, `wiktes:`), so statuses and
lookups reach the server as they do for Chinese and English.
"""

from collections.abc import Sequence

from polyglotic_desktop.core.lexicon.english import entry_from_record
from polyglotic_desktop.core.lexicon.entries import DictionaryEntry
from polyglotic_desktop.core.shared import EntryId, WordInLine
from polyglotic_desktop.ports.dictionary import DictionaryFile, EntryRecord
from polyglotic_desktop.ports.word_split import SplitWord, WordSplit


class BasicDictionary:
    """One language's pack: lookups, the word split, and the entry a word
    in a caption counts for. `language` is the caption language it serves
    ("ja", "es")."""

    def __init__(self, file: DictionaryFile, split: WordSplit, language: str) -> None:
        self._file = file
        self._split = split
        self.language = language

    @property
    def ready(self) -> bool:
        """Always: nothing is read up front (`ChineseDictionary.ready`)."""
        return True

    def words(self, text: str) -> list[tuple[int, int]]:
        """(start, end) of each word in `text`, by the word split."""
        return [(w.start, w.end) for w in self._split.words(text)]

    def word_at(self, text: str, index: int) -> tuple[int, int] | None:
        """(start, end) of the word at `index`, or None between words."""
        for word in self._split.words(text):
            if word.start <= index < word.end:
                return word.start, word.end
        return None

    def lookup(self, word: str) -> list[DictionaryEntry]:
        """The entries for `word` (a word or phrase as the learner picked
        it), best first. A single word is split first, for the dictionary
        form its analyser finds."""
        split = self._split.words(word)
        if len(split) == 1 and (split[0].start, split[0].end) == (0, len(word)):
            return self.lookup_split(word, split[0])
        return self.lookup_split(word, SplitWord(0, len(word)))

    def lookup_split(self, word: str, split: SplitWord) -> list[DictionaryEntry]:
        """The entries for `word` as the word split saw it in its line
        (see the module's order), best first."""
        word = word.replace("’", "'")
        found: dict[str, DictionaryEntry] = {}

        def add(records: Sequence[EntryRecord]) -> None:
            for record in records:
                found.setdefault(record.entry_id, entry_from_record(record))

        for lemma in split.lemmas:
            add(self._file.records(lemma))
        for form in dict.fromkeys((word, word.lower())):
            inflected_from = self._file.lemma(form)
            if inflected_from:
                add(self._file.records(inflected_from))
            add(self._file.records(form))
            if found:
                break
        if not found:
            for guess in split.guesses:
                add(self._file.records(guess))
        return list(found.values())

    def form_reading(self, word: str) -> str:
        """How `word` itself is said, as written or in lower case, where the
        pack marks it ("руку": "ру́ку"; Russian's stress moves as a word
        inflects) - "" if it doesn't."""
        word = word.replace("’", "'")
        for form in dict.fromkeys((word, word.lower())):
            reading = self._file.form_reading(form)
            if reading:
                return reading
        return ""

    def words_in(self, text: str, scheme_id: str) -> list[WordInLine]:
        """The words in `text` the pack has, each with the entry it counts
        for and the facts Learning needs - as `EnglishDictionary.words_in`."""
        out = []
        for split in self._split.words(text):
            entries = self.lookup_split(text[split.start : split.end], split)
            if entries:
                out.append(
                    WordInLine(split.start, split.end, entries[0].facts(scheme_id))
                )
        return out

    def entry(self, entry_id: EntryId) -> DictionaryEntry | None:
        """The entry with this ID - or the one it was merged into."""
        record = self._file.record(entry_id)
        return entry_from_record(record) if record else None
