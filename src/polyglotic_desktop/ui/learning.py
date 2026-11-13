"""What the learning views share: the learner's vocabulary and dictionary,
and a Qt signal when either changes.

`LearningTools` is handed to every learning view (the lookup popup, the
vocabulary page, the developer view). It holds no rules of its own: it
asks Lexicon for the words in a line and Learning (`Vocabulary`) for
everything about the learner, and turns `Vocabulary`'s change events into
the `changed` signal views redraw on.
"""

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot

from polyglotic_desktop.core.learning.bands import FREQUENCY_BANDS
from polyglotic_desktop.core.learning.exposures import in_learned_language
from polyglotic_desktop.core.learning.vocabulary import (
    EntryText,
    FactsRead,
    Vocabulary,
    VocabularyChanged,
)
from polyglotic_desktop.core.lexicon.basic import BasicDictionary
from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary, has_han
from polyglotic_desktop.core.lexicon.english import EnglishDictionary
from polyglotic_desktop.core.lexicon.english import word_at as english_word_at
from polyglotic_desktop.core.lexicon.entries import DictionaryEntry
from polyglotic_desktop.core.lexicon.meanings import short_meaning
from polyglotic_desktop.core.shared import (
    EntryFacts,
    EntryId,
    LearningEvent,
    WordInLine,
)
from polyglotic_desktop.ports.anki_deck import AnkiDeckWriter
from polyglotic_desktop.ports.dictionary import DictionaryProblem
from polyglotic_desktop.ports.learning import SetAsideLearningData


@dataclass(frozen=True)
class _ReadAhead:
    """What `prepare`'s thread read for Words: facts, and the bands' sizes
    (the scheme, by frequency, by level)."""

    facts: FactsRead
    band_sizes: tuple[str, list[int], Mapping[int, int]]


class LearningTools(QObject):
    changed = Signal(str)  # a core.learning.vocabulary.Changed value
    dictionary_out = Signal()
    """The learner's dictionary went out after the start: a query failed on
    a damaged file (polyglotic-hq 199) - `dictionary_problem` says why.
    Emitted on the thread whose query failed - connect queued."""
    learning_damaged = Signal(object)
    """The learning data was found damaged after the start - a save or a
    read failed (polyglotic-hq 206): nothing more is saved on this PC this
    session. Its `SetAsideLearningData`, or None if it couldn't be set
    aside. Emitted on the store's thread - connect queued."""
    learning_deleted = Signal()
    """The learner's learning data on this PC was deleted, with the files
    set aside from it (polyglotic-hq 207): `learning_set_aside` no longer
    names one that's gone (213). Emitted on the store's thread - connect
    queued."""
    dictionary_ready = Signal()
    """The word split's data is read (`prepare`): captions' words can be
    counted and marked. Sent too when the read failed - the split then reads
    it when first asked, rather than captions waiting for good
    (polyglotic-hq 142). Emitted on the reading thread - connect queued."""
    read_ahead_done = Signal()
    """`prepare`'s read of what Words reads is back (`read_ahead`) - or
    failed, and Words reads what it needs itself. Emitted on this thread."""
    _read = Signal(object)  # a _ReadAhead or None, from `prepare`'s thread
    _described = Signal(object)  # {EntryId: EntryText}, from `prepare`'s thread

    def __init__(
        self,
        vocabulary: Vocabulary,
        dictionary: ChineseDictionary | EnglishDictionary,
        parent: QObject | None = None,
        deck_writer: AnkiDeckWriter | None = None,
        basic: Mapping[str, BasicDictionary] | None = None,
        dictionary_problem: Callable[[], DictionaryProblem | None] | None = None,
        learning_data_new: bool = False,
        learning_set_aside: SetAsideLearningData | None = None,
    ) -> None:
        """`dictionary_problem`: why the learner's dictionary file is out, if
        it is (`main` hands over the file's; polyglotic-hq 199).
        `learning_data_new`: the learning data was started at this start -
        new, or its file set aside (polyglotic-hq 206); `learning_set_aside`:
        that file, if it was."""
        super().__init__(parent)
        self.learning_data_new = learning_data_new
        """The learning data on this PC was started at this start: what the
        server keeps syncs back from the start (polyglotic-hq 206)."""
        self.learning_set_aside = learning_set_aside
        """The learning data file that couldn't be read at this start, or
        was found damaged since, kept where this says - Home and Help tell
        the learner (polyglotic-hq 206)."""
        self.learning_unsaved = False
        """Found damaged since the start: nothing is saved on this PC until
        the next start (`learning_damaged`)."""
        self.learning_damaged.connect(self._learning_damaged)
        self.learning_deleted.connect(self._learning_deleted)
        self.vocabulary = vocabulary
        self.dictionary = dictionary
        self._problem = dictionary_problem or (lambda: None)
        self.deck_writer = deck_writer  # None: no deck file export
        self._band_sizes: tuple[str, list[int], Mapping[int, int]] | None = None
        self.read_ahead = False
        """What Words reads for every word met has been read ahead
        (`prepare`) and handed over."""
        self.reading_ahead = False
        """That read is under way: Words, opened meanwhile, says it's reading
        rather than reading it all itself alongside (polyglotic-hq 220: 425
        ms at 10,000 words met on CC-CEDICT), until `read_ahead_done`."""
        self._read.connect(self._ahead)  # queued: emitted on `prepare`'s thread
        self._texts: dict[EntryId, EntryText] = {}
        self.texts_read_ahead = False
        """Every word met's text (`describe`) has been read ahead (`prepare`)
        and handed over: Words' first search reads nothing from the
        dictionary (polyglotic-hq 220)."""
        self._described.connect(self._know_texts)  # queued, as `_read`
        self.basic = dict(basic or {})
        """Basic dictionaries by caption language, for lookups only - empty
        unless the developer switch opens them (decision 0035)."""
        vocabulary.subscribe(self._on_event)

    @Slot(object)
    def _learning_damaged(self, aside: SetAsideLearningData | None) -> None:
        self.learning_unsaved = True
        if aside is not None:
            self.learning_set_aside = aside

    @Slot()
    def _learning_deleted(self) -> None:
        """Forgotten once it's gone: one that couldn't be deleted (in use),
        or a folder set aside (kept: what's in it may not be the app's), is
        still named. `learning_unsaved` stays: the store is still out until
        a restart."""
        aside = self.learning_set_aside
        if aside is not None and not aside.path.exists():
            self.learning_set_aside = None

    def _on_event(self, event: LearningEvent | VocabularyChanged) -> None:
        if isinstance(event, VocabularyChanged):
            self.changed.emit(event.what.value)

    @property
    def dictionary_problem(self) -> DictionaryProblem | None:
        """Why the learner's dictionary is out - None while it answers.
        While it's out, it answers nothing: captions run without word marks
        or counting, and a lookup says what's wrong and how to fix it."""
        return self._problem()

    @property
    def ready(self) -> bool:
        """Whether the word split answers without reading the dictionary
        first (`ChineseDictionary.ready`; an English dictionary always)."""
        return self.dictionary.ready

    def prepare(self) -> None:
        """Reads ahead, on a thread of its own: what the word split needs
        (about 0.2 s for CC-CEDICT), then `dictionary_ready`; then what
        Words reads for every word met - each one's facts and the bands'
        sizes - handed back to this thread (`read_ahead`), then each one's
        text, which Words' search reads (`texts_read_ahead`: about 150 ms more
        at 10,000 words met on CC-CEDICT, polyglotic-hq 220). Until the split's
        data is read a caption shows at once, its words counted and marked
        when it's read - never waiting on the interface thread
        (polyglotic-hq project 136: the first Chinese caption froze the
        interface for up to 0.9 s); Words opened first says it's reading
        (`reading_ahead`) until it's back."""
        if self.basic:
            threading.Thread(
                target=self._warm_basic, name="basic dictionaries", daemon=True
            ).start()
        dictionary = self.dictionary
        splits = isinstance(dictionary, ChineseDictionary) and not dictionary.ready
        facts = self.vocabulary.facts_to_read()
        scheme = self.vocabulary.scheme
        met = [e for e in self.vocabulary.met_entries() if e not in self._texts]

        def read() -> None:
            ahead = None
            try:
                if splits and isinstance(dictionary, ChineseDictionary):
                    try:
                        dictionary.prepare()
                    finally:  # failed too: see `dictionary_ready`
                        self.dictionary_ready.emit()
                sizes = (
                    scheme,
                    dictionary.words_in_ranks(FREQUENCY_BANDS),
                    dictionary.words_at_levels(scheme),
                )
                ahead = _ReadAhead(facts(), sizes)
            finally:  # failed too: Words isn't left waiting
                self._read.emit(ahead)
            texts = {}
            for entry_id in met:
                text = _text(dictionary, entry_id)
                if text is not None:
                    texts[entry_id] = text
            self._described.emit(texts)

        self.reading_ahead = True
        threading.Thread(target=read, name="dictionary", daemon=True).start()

    @Slot(object)
    def _ahead(self, ahead: _ReadAhead | None) -> None:
        if ahead is not None:
            self.vocabulary.know_facts(ahead.facts)
            if self._band_sizes is None:
                self._band_sizes = ahead.band_sizes
            self.read_ahead = True
        self.reading_ahead = False
        self.read_ahead_done.emit()

    @Slot(object)
    def _know_texts(self, texts: Mapping[EntryId, EntryText]) -> None:
        """Texts read ahead. A word the read didn't find is asked for again
        when wanted - the dictionary may have been out."""
        for entry_id, text in texts.items():
            self._texts.setdefault(entry_id, text)
        self.texts_read_ahead = True

    def _warm_basic(self) -> None:
        """Each basic dictionary's word split reads its data on first use -
        simplemma's Spanish about 0.5 s - so a first word here, off the
        interface thread, keeps the first hover from waiting on it."""
        for basic in self.basic.values():
            basic.words("a")

    @property
    def is_chinese(self) -> bool:
        """For a Chinese learner (CC-CEDICT), not an English one (ECDICT)."""
        return isinstance(self.dictionary, ChineseDictionary)

    @property
    def language(self) -> str:
        """The language being learned: `zh` or `en`."""
        return "zh" if self.is_chinese else "en"

    def learns(self, caption_language: str | None) -> bool:
        """Whether a caption in `caption_language` counts as heard - its
        exposures, coverage and listening time: only one in the language
        being learned (`exposures.in_learned_language`)."""
        return in_learned_language(caption_language, self.language)

    def band_sizes(self) -> tuple[list[int], Mapping[int, int]]:
        """How many words each of Words' frequency bands has
        (`FREQUENCY_BANDS`), and each level of the learner's scheme - read
        from the dictionary once per scheme (about 40 ms for CC-CEDICT)."""
        scheme = self.vocabulary.scheme
        if self._band_sizes is None or self._band_sizes[0] != scheme:
            self._band_sizes = (
                scheme,
                self.dictionary.words_in_ranks(FREQUENCY_BANDS),
                self.dictionary.words_at_levels(scheme),
            )
        return self._band_sizes[1], self._band_sizes[2]

    def words_in(self, line: str) -> list[WordInLine]:
        return self.dictionary.words_in(line, self.vocabulary.scheme)

    def is_basic(self, language: str | None) -> bool:
        """Whether a row in `language` is looked up in a basic dictionary."""
        return language is not None and language in self.basic

    def word_at(
        self, line: str, index: int, language: str | None = None
    ) -> tuple[int, int] | None:
        """The word a lookup shows at `line[index]` of a row in `language`
        (None: not known): by a basic dictionary's word split if there's
        one for it; else a Chinese word by the word split, or a word of
        any spaced language."""
        if language is not None and language in self.basic:
            return self.basic[language].word_at(line, index)
        if isinstance(self.dictionary, ChineseDictionary) and has_han(
            line[index : index + 1]
        ):
            return self.dictionary.word_at(line, index)
        return english_word_at(line, index)

    def lookup(self, word: str, language: str | None = None) -> list[DictionaryEntry]:
        """The entries for `word` from a row in `language`: in its basic
        dictionary if there's one, else the learner's."""
        if language is not None and language in self.basic:
            return self.basic[language].lookup(word)
        return self.dictionary.lookup(word)

    def form_reading(self, word: str, language: str | None = None) -> str:
        """How `word` itself is said, where a basic dictionary's pack marks
        it (Russian's stress on an inflected form) - "" otherwise."""
        if language is not None and language in self.basic:
            return self.basic[language].form_reading(word)
        return ""

    def entry(self, entry_id: EntryId) -> DictionaryEntry | None:
        return self.dictionary.entry(entry_id)

    def describe(self, entry_id: EntryId) -> EntryText | None:
        """An entry's text from the dictionary - Words' rows and its search,
        and words in the Anki file that were put in the deck without a
        lookup here: read ahead for every word met (`prepare`), else read
        now."""
        text = self._texts.get(entry_id)
        return text if text is not None else _text(self.dictionary, entry_id)

    def facts(self, entry: DictionaryEntry) -> EntryFacts:
        return entry.facts(self.vocabulary.scheme)


def _text(
    dictionary: ChineseDictionary | EnglishDictionary, entry_id: EntryId
) -> EntryText | None:
    """An entry's text (`LearningTools.describe`), read from the dictionary."""
    entry = dictionary.entry(entry_id)
    if entry is None:
        return None
    return EntryText(
        entry.headword, entry.traditional, entry.reading, short_meaning([entry])
    )
