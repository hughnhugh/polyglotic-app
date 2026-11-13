"""English: words in a line, lookups, and inflected forms to their entry.

Word statuses and exposures are counted per entry, so "running", "ran"
and "runs" in a caption all count for "run" (`entry_for_word`), using
ECDICT's inflection data. A form with meanings of its own ("left": 左边的)
is still looked up too: `lookup` shows its lemma's entry first, then its
own.
"""

import re
from collections.abc import Mapping, Sequence

from polyglotic_desktop.core.lexicon.entries import DictionaryEntry, words_in_runs
from polyglotic_desktop.core.shared import EntryFacts, EntryId, WordInLine
from polyglotic_desktop.ports.dictionary import DictionaryFile, EntryRecord

# A word in a spaced language: letters, it's, well-known. Chinese
# characters aren't its letters: in 用iPhone打 the word is iPhone (133).
_LETTER = r"[^\W\d_\u3007\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]"
_WORD = re.compile(rf"{_LETTER}+(?:['’-]{_LETTER}+)*")


def entry_from_record(record: EntryRecord) -> DictionaryEntry:
    """An ECDICT entry. A capitalised headword (other than "I") is a proper
    noun - a name, place, language or day - not shown as unfamiliar."""
    return DictionaryEntry(
        entry_id=EntryId(record.entry_id),
        headword=record.headword,
        traditional=record.traditional,
        reading=record.reading,
        meanings=record.meanings,
        frequency_rank=record.frequency_rank,
        levels=record.levels,
        is_name=record.headword[:1].isupper() and len(record.headword) > 1,
    )


def words(text: str) -> list[tuple[int, int]]:
    """(start, end) of each word in `text`: runs of letters, with
    apostrophes and hyphens inside ("it's", "well-known")."""
    return [m.span() for m in _WORD.finditer(text)]


def word_at(text: str, index: int) -> tuple[int, int] | None:
    """(start, end) of the word at `index` - None on a space, digit or
    punctuation."""
    for start, end in words(text):
        if start <= index < end:
            return start, end
    return None


class EnglishDictionary:
    """ECDICT for English learners: lookups, and the entry a word in a
    caption counts for. Nothing is loaded up front."""

    def __init__(self, file: DictionaryFile) -> None:
        self._file = file

    @property
    def ready(self) -> bool:
        """Always: nothing is loaded up front (`ChineseDictionary.ready`)."""
        return True

    def lookup(self, word: str) -> list[DictionaryEntry]:
        """The entries for `word` as written, trying lower case too
        ("Running" at the start of a sentence): its lemma's entry first if
        it's an inflected form ("running" -> run), then its own."""
        word = word.replace("’", "'")
        found: dict[str, DictionaryEntry] = {}
        for form in dict.fromkeys((word, word.lower())):
            lemma = self._file.lemma(form)
            for record in [
                *(self._file.records(lemma) if lemma else ()),
                *self._file.records(form),
            ]:
                found.setdefault(record.entry_id, entry_from_record(record))
            if found:
                break
        return list(found.values())

    def entry_for_word(self, word: str) -> DictionaryEntry | None:
        """The entry `word` counts for in statuses and exposures: its
        lemma's if it's an inflected form, else its own; None if the
        dictionary doesn't have it."""
        entries = self.lookup(word)
        return entries[0] if entries else None

    def words_in(self, text: str, scheme_id: str) -> list[WordInLine]:
        """The words in `text` the dictionary has, each with the entry it
        counts for and the facts Learning needs for a learner in
        `scheme_id` - for highlights and exposures."""
        found = []
        for start, end in words(text):
            entry = self.entry_for_word(text[start:end])
            if entry is not None:
                found.append(WordInLine(start, end, entry.facts(scheme_id)))
        return found

    def entry(self, entry_id: EntryId) -> DictionaryEntry | None:
        """The entry with this ID - or the one it was merged into."""
        record = self._file.record(entry_id)
        return entry_from_record(record) if record else None

    def facts(self, entry_id: EntryId, scheme_id: str) -> EntryFacts | None:
        """`entry(entry_id).facts(scheme_id)`: what Learning asks for every
        word met (as `ChineseDictionary.facts`)."""
        entry = self.entry(entry_id)
        return entry.facts(scheme_id) if entry else None

    def words_in_ranks(self, runs: Sequence[tuple[int, int]]) -> list[int]:
        """How many words (written forms) each run of frequency ranks
        (first, last) has - the sizes of Words' bands."""
        last = max((last for _, last in runs), default=0)
        return words_in_runs(self._file.words_ranked(last), runs)

    def words_at_levels(self, scheme_id: str) -> Mapping[int, int]:
        """How many headwords the level scheme puts at each level."""
        return self._file.words_at_levels(scheme_id)

    def merged_ids(self) -> list[EntryId]:
        """The entry IDs merged into other entries (decision 0007): what
        `Vocabulary.follow_merged_entries` checks at start."""
        return [EntryId(old) for old in self._file.merged_ids()]
