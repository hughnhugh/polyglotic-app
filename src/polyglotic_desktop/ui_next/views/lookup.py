"""W3, the lookup, as plain Python: what the card shows and what its
actions do (polyglotic-hq project 109's structure, section 6; project 113).

`Lookup` is the card's model (109's `LookupModel`): the word looked up and
its context, hover or pinned, the parts drilled into (Back returns), and
the commands - Add to deck, Known, Save to a category (or a new one),
Remove, a part, Back, Close. `card()` is what the card shows now, as
facts (`Card`); the words around them are the card's, through Qt's
translations. Today's content (`ui.lookup`), in 109's shape:
- **hover**: the headword, its reading, its status and its first sense -
  no actions;
- **pinned** (a click, or a drag across a phrase): up to `READINGS`
  readings with up to `SENSES` senses each ("+N more readings"), measure
  words, chengyu, the saved category, "heard in N captions", the actions,
  the parts ("Inside this word", each a click away - Back returns) and
  the context line: the caption's row and its translation;
- **not in the dictionary**: for Chinese, a best-guess reading and the
  words' meanings joined ("Not in the dictionary as a whole - ..."), with
  its words and characters; otherwise "Not in the dictionary";
- **an English word in a Chinese learner's caption**: "Chinese for it";
- **the learner's dictionary out** (missing or damaged on the PC;
  polyglotic-hq 199): the word, and what's wrong - the card says how to
  fix it. A basic dictionary's words are still looked up.

A pinned word in a language not being learned, with a dictionary, asks
once (`LanguagesOffer`; DECISIONS.md #65, polyglotic-hq 262): "Learn
Japanese too" adds it to Learning's list; "Not now" isn't asked again.

Every lookup shown is reported to Learning (`Vocabulary.looked_up`); a
pinned one is evidence the learner doesn't know the word (as today). A
command returns the entry it changed, so the caption windows repaint only
the captions holding it.

`place`: where the card goes - above the word, centred on it; below when
there's no room above; never over the row being read; on the work area.

Holds caption text (the context): never log it.
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from polyglotic_desktop.core.learning.languages import Tier, learned_code, tier_of
from polyglotic_desktop.core.learning.lookups import LookupContext
from polyglotic_desktop.core.learning.saved_words import Category
from polyglotic_desktop.core.learning.vocabulary import EntryText, Vocabulary
from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary, has_han, is_han
from polyglotic_desktop.core.lexicon.english import EnglishDictionary
from polyglotic_desktop.core.lexicon.entries import DictionaryEntry
from polyglotic_desktop.core.lexicon.meanings import (
    definitions,
    meaning_of,
    short_meaning,
)
from polyglotic_desktop.core.shared import EntryFacts, WordInLine, WordStatus
from polyglotic_desktop.ports.dictionary import DictionaryProblem
from polyglotic_desktop.ui_next.views.placement import Rect, Size

READINGS = 3
"""Readings (dictionary entries) a pinned card shows; the rest are counted."""
SENSES = 3
"""Senses shown per reading."""
PARTS = 8
"""Parts, or Chinese words for an English one, a pinned card lists."""
HOVER_CHINESE_FOR = 3
GAP = 6
"""Pixels between the card and the row it's about."""
MARGIN = 8
"""Pixels the card keeps from the work area's edges."""


_STRESS = ("\u0301", "\u0300")  # Russian's stress marks: combining accents


def said(entry: DictionaryEntry) -> str:
    """An entry's headword and how it's said, for the line naming the entry
    an inflected form belongs to: "saber  /saˈbeɾ/", "食べる  たべる". A
    reading that is the headword with its stress marked is said once:
    "рука́", not "рука  рука́"."""
    marked = unicodedata.normalize("NFD", entry.reading)
    for mark in _STRESS:
        marked = marked.replace(mark, "")
    plain = unicodedata.normalize("NFC", marked)
    if entry.reading and all(p == entry.headword for p in plain.split(", ")):
        return entry.reading
    return f"{entry.headword}  {entry.reading}".strip()


class Learner(Protocol):
    """What the lookup and the caption windows' marks need of the learning
    tools (`ui.learning.LearningTools`, handed over by `main`): the
    learner's vocabulary, the dictionary and the word split."""

    @property
    def vocabulary(self) -> Vocabulary: ...

    @property
    def dictionary(self) -> ChineseDictionary | EnglishDictionary: ...

    @property
    def ready(self) -> bool:
        """Whether the word split can answer without reading the dictionary
        first (`ChineseDictionary.ready`): until then, marks that need it
        wait for `dictionary_ready` rather than the interface thread."""
        ...

    def words_in(self, line: str) -> list[WordInLine]: ...

    def learns(self, language: str | None) -> bool:
        """Whether a row in `language` is in the language being learned -
        the only rows Learning marks."""
        ...

    def word_at(
        self, line: str, index: int, language: str | None = None
    ) -> tuple[int, int] | None: ...

    def lookup(self, word: str, language: str | None = None) -> list[DictionaryEntry]:
        """The entries for `word` from a row in `language` (None: the
        learner's dictionary)."""
        ...

    def is_basic(self, language: str | None) -> bool:
        """Whether a row in `language` is looked up in a basic dictionary
        (decision 0035): a lookup only, kept out of the learner's data."""
        ...

    def form_reading(self, word: str, language: str | None = None) -> str:
        """How `word` itself is said, where a basic dictionary marks it
        apart from its entry (Russian: "руку" is "ру́ку"), else ""."""
        ...

    def facts(self, entry: DictionaryEntry) -> EntryFacts: ...

    @property
    def dictionary_problem(self) -> DictionaryProblem | None:
        """Why the learner's dictionary is out (None: it answers)."""
        ...


class LanguagesOffer(Protocol):
    """What the card asks of the languages being learned (`main`'s, kept in
    the settings): which language a pinned word's row offers to learn too,
    and the two answers."""

    def asks_about(self, caption_language: str | None) -> str | None:
        """The language to ask about for a row in `caption_language` (a
        learned language's code), or None."""
        ...

    def learn_too(self, code: str) -> None: ...

    def not_now(self, code: str) -> None: ...


class Shows(StrEnum):
    """What kind of card it is."""

    ENTRY = "entry"
    NOT_FOUND = "not_found"
    CHINESE_FOR = "chinese_for"
    """An English word in a Chinese learner's caption: Chinese words for it."""
    DICTIONARY_OUT = "dictionary_out"
    """The learner's dictionary is out: what's wrong (`Card.problem`)."""
    NO_DICTIONARY = "no_dictionary"
    """A word the learner's dictionary hasn't got, in a row whose language
    has no dictionary on this PC yet (Thai; Japanese without its pack):
    said so, not "not in the dictionary" (polyglotic-hq 248's 3.3, 262).
    Also one in a row whose full dictionary isn't the one in use (Chinese
    while English's runs - the first run asks no language, 293): it's
    used once that language is learned, from the next start."""


class PartsTitle(StrEnum):
    INSIDE = "inside"  # "Inside this word"
    WORDS_AND_CHARACTERS = "words_and_characters"  # not in the dictionary
    CHINESE_FOR = "chinese_for"  # "Chinese for it"


@dataclass(frozen=True)
class Reading:
    """One dictionary entry's reading (pinyin, or IPA as "/.../" after the
    entry's word when it isn't the word looked up), senses and measure
    words."""

    reading: str
    senses: tuple[str, ...]
    measure_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class Part:
    """A word inside the one looked up (or a Chinese word for an English
    one): a click looks it up. `reading` and `meaning` are "" when the
    dictionary hasn't got it."""

    word: str
    reading: str
    meaning: str


@dataclass(frozen=True)
class Card:
    """What the card shows (`Lookup.card`)."""

    word: str
    shows: Shows
    pinned: bool
    traditional: bool = False
    """The word is a traditional form (its headword font)."""
    other: str = ""
    """The word's other form: traditional or simplified."""
    base: str = ""
    """An inflected English word's entry ("ran" counts for "run")."""
    chengyu: bool = False
    status: WordStatus | None = None
    saved_in: Category | None = None
    readings: tuple[Reading, ...] = ()
    more_readings: int = 0
    guess: str = ""
    """Not in the dictionary (Chinese): a best-guess reading."""
    meaning: str = ""
    """Not in the dictionary (Chinese): its words' meanings joined."""
    heard: int = 0
    parts_title: PartsTitle | None = None
    parts: tuple[Part, ...] = ()
    categories: tuple[Category, ...] = ()
    back_to: str = ""
    """The word Back returns to; "" for none."""
    context: LookupContext | None = None
    found_at: tuple[int, int] | None = None
    """Where the word is in the context's sentence."""
    basic: bool = False
    """From a basic dictionary (decision 0035): marked so, and nothing to
    do with it but read - it isn't the learner's language."""
    language: str | None = None
    """A basic dictionary's language (for its script's font); None for
    the learner's own dictionary."""
    problem: DictionaryProblem | None = None
    """Why the learner's dictionary is out (`Shows.DICTIONARY_OUT`)."""
    offer: str = ""
    """A language this word's row is in that isn't being learned: "Learn
    it too?" (its code; "" for none)."""
    added: str = ""
    """The language just added from this card (its code): said once."""

    @property
    def actions(self) -> bool:
        """The actions show: pinned, on an entry of the learner's dictionary."""
        return self.pinned and self.shows is Shows.ENTRY and not self.basic

    @property
    def known(self) -> bool:
        return self.status is WordStatus.KNOWN

    @property
    def in_deck(self) -> bool:
        return self.status is WordStatus.LEARNING


@dataclass(frozen=True)
class WordAt:
    """A word (or a phrase dragged across) in a caption window, to look up:
    the text, its context - the caption's row and its translation - where
    it is in the row (`at`), and where it is on the screen (`rect`), in
    which row (`row`), on which work area (`area`). `key`: the caption's
    line key, the row and `at` - the same word again is the same key."""

    word: str
    context: LookupContext
    at: tuple[int, int]
    rect: Rect
    row: Rect
    area: Rect
    key: tuple[int, int, int, int]
    language: str | None = None
    """The row's language, if known - it picks a basic dictionary."""


@dataclass
class _Shown:
    word: str
    context: LookupContext
    at: tuple[int, int] | None
    history: list[str] = field(default_factory=list)
    language: str | None = None
    added: str = ""


class Lookup:
    """The lookup card's model: what's looked up, and its commands."""

    def __init__(self, learner: Learner, offer: LanguagesOffer | None = None) -> None:
        """`offer`: the languages being learned, for "Learn it too?" (none:
        never asked)."""
        self.learner = learner
        self.offer = offer
        self.pinned = False
        self._shown: _Shown | None = None

    @property
    def word(self) -> str:
        return self._shown.word if self._shown else ""

    @property
    def showing(self) -> bool:
        return self._shown is not None

    @property
    def is_chinese(self) -> bool:
        """For a Chinese learner (CC-CEDICT), not an English one (ECDICT)."""
        return isinstance(self.learner.dictionary, ChineseDictionary)

    # -- what's looked up ---------------------------------------------------------------

    def show(
        self,
        word: str,
        context: LookupContext,
        pinned: bool,
        at: tuple[int, int] | None = None,
        language: str | None = None,
    ) -> None:
        """`word`, from a caption row (`context`; at `at` in its sentence;
        in `language` if known), shown on hover or pinned."""
        self._shown = _Shown(word, context, at, language=language)
        self.pinned = pinned
        self._report()

    @property
    def basic(self) -> bool:
        """The word shown is looked up in a basic dictionary."""
        return self._shown is not None and self.learner.is_basic(self._shown.language)

    def close(self) -> None:
        self._shown = None
        self.pinned = False

    def part(self, index: int) -> None:
        """Looks up the card's `index`th part (or Chinese word) - Back
        returns. The context stays the line it was found in."""
        parts = self.card().parts
        if self._shown is None or not 0 <= index < len(parts):
            return
        self._shown.history.append(self._shown.word)
        self._shown.word = parts[index].word
        self._report()

    def back(self) -> bool:
        """Back to the word before the part shown; False if there's none."""
        if self._shown is None or not self._shown.history:
            return False
        self._shown.word = self._shown.history.pop()
        return True

    def _report(self) -> None:
        entry = self.entry()
        if entry is not None:
            self.learner.vocabulary.looked_up(self.learner.facts(entry), self.pinned)

    def entry(self) -> DictionaryEntry | None:
        """The entry shown: the word's everyday reading. None from a basic
        dictionary: its words aren't the learner's language, so nothing is
        reported or kept (the learner's languages are 157's step 5)."""
        if self._shown is None or self.basic:
            return None
        entries = self.learner.lookup(self._shown.word)
        return entries[0] if entries else None

    # -- the commands --------------------------------------------------------------------

    def learn_too(self) -> None:
        """ "Learn X too": the language this card asks about is learned too
        (Learning's list), and the card says so."""
        code = self.card().offer
        if code and self.offer is not None and self._shown is not None:
            self.offer.learn_too(code)
            self._shown.added = code

    def not_now(self) -> None:
        """ "Not now": not asked about this language again."""
        code = self.card().offer
        if code and self.offer is not None:
            self.offer.not_now(code)

    def add_to_deck(self) -> DictionaryEntry | None:
        """Into the deck, keeping the line it was in and that line's
        translation (for the Anki file) - or, in it already, out of it
        (back to new). The entry changed, or None."""
        entry = self.entry()
        if entry is None or self._shown is None:
            return None
        vocabulary = self.learner.vocabulary
        if self._status(entry) is WordStatus.LEARNING:
            vocabulary.set_status(entry.entry_id, WordStatus.NEW)
        else:
            vocabulary.learn(entry.entry_id, self._text(entry), self._shown.context)
        return entry

    def known(self) -> DictionaryEntry | None:
        """Known - or, known already, back to new."""
        entry = self.entry()
        if entry is None:
            return None
        known = self._status(entry) is WordStatus.KNOWN
        self.learner.vocabulary.set_status(
            entry.entry_id, WordStatus.NEW if known else WordStatus.KNOWN
        )
        return entry

    def save_to(self, category_id: str) -> DictionaryEntry | None:
        """Saved into a category, or moved there if saved already."""
        entry = self.entry()
        vocabulary = self.learner.vocabulary
        if (
            entry is None
            or self._shown is None
            or vocabulary.category(category_id) is None
        ):
            return None
        text = self._text(entry)
        vocabulary.save(
            entry.entry_id,
            text.headword,
            text.traditional,
            text.reading,
            text.meaning,
            category_id,
            self._shown.context,
        )
        return entry

    def new_category(self, name: str) -> DictionaryEntry | None:
        """A new category, named `name` (numbered if that's taken) in the
        next colour, with the word saved in it - one click, nothing typed:
        the card never takes the keyboard. Renamed on the Words page."""
        if self.entry() is None:
            return None
        vocabulary = self.learner.vocabulary
        taken = {c.name for c in vocabulary.categories}
        named, n = name, 2
        while named in taken:
            named, n = f"{name} {n}", n + 1
        return self.save_to(vocabulary.add_category(named).id)

    def remove(self) -> DictionaryEntry | None:
        """Out of the saved words."""
        entry = self.entry()
        if entry is None:
            return None
        self.learner.vocabulary.unsave(entry.entry_id)
        return entry

    def _status(self, entry: DictionaryEntry) -> WordStatus:
        return self.learner.vocabulary.status(self.learner.facts(entry)).status

    def _text(self, entry: DictionaryEntry) -> EntryText:
        """What the deck and saved words keep of it."""
        dictionary = self.learner.dictionary
        word = self.word
        meaning = (
            meaning_of(dictionary, word)
            if isinstance(dictionary, ChineseDictionary)
            else short_meaning(self.learner.lookup(word))
        )
        return EntryText(entry.headword, entry.traditional, entry.reading, meaning)

    # -- what it shows -------------------------------------------------------------------

    def card(self) -> Card:
        """What the card shows now. The learner's dictionary out, it says
        so - not "not in the dictionary", which it can't know. Asked after
        the card's own lookups: one of them may be what finds the file
        damaged (polyglotic-hq 199)."""
        shown = self._shown
        if shown is None:
            return Card("", Shows.NOT_FOUND, False)
        found = self._found(shown)
        if self._no_dictionary(found, shown.language):
            found = Card(
                shown.word,
                Shows.NO_DICTIONARY,
                self.pinned,
                back_to=found.back_to,
                language=learned_code(shown.language or ""),
            )
        problem = self.learner.dictionary_problem
        if problem is not None and not found.basic:
            found = Card(shown.word, Shows.DICTIONARY_OUT, self.pinned, problem=problem)
        offer = self.offer
        asked = offer.asks_about(shown.language) if offer and self.pinned else None
        if asked or shown.added:
            return replace(found, offer=asked or "", added=shown.added)
        return found

    def _no_dictionary(self, found: Card, language: str | None) -> bool:
        """Nothing found for a word in a row whose language has no
        dictionary here: neither a full one (the learner's, or the other one
        - "Chinese for it" on an English row) nor its basic pack. Or not
        found in a row whose full dictionary isn't the one in use (293)."""
        nothing = found.shows is Shows.NOT_FOUND or (
            found.shows is Shows.CHINESE_FOR and not found.parts
        )
        if not nothing or found.basic or language is None:
            return False
        code = learned_code(language)
        if tier_of(code) is not Tier.FULL:
            return True
        running = (
            "zh" if isinstance(self.learner.dictionary, ChineseDictionary) else "en"
        )
        return found.shows is Shows.NOT_FOUND and code != running

    def _found(self, shown: _Shown) -> Card:
        word, pinned = shown.word, self.pinned
        back_to = shown.history[-1] if shown.history and pinned else ""
        if self.basic:
            return self._basic(word, back_to)
        dictionary = self.learner.dictionary
        if isinstance(dictionary, ChineseDictionary) and not has_han(word):
            return self._chinese_for(dictionary, word, back_to)
        entries = self.learner.lookup(word)
        context = shown.context if pinned and not shown.history else None
        found_at = shown.at if context is not None else None
        if not entries:
            return self._not_found(word, back_to, context, found_at)
        vocabulary = self.learner.vocabulary
        first = entries[0]
        saved = vocabulary.saved_word(first.entry_id)
        limit = READINGS if pinned else 1
        readings = tuple(self._reading(e, word, pinned) for e in entries[:limit])
        title, parts = (None, ()) if not pinned else self._parts(word, found=True)
        return Card(
            word,
            Shows.ENTRY,
            pinned,
            traditional=any(
                e.traditional == word and e.headword != word for e in entries
            ),
            other=self._other(word, entries) if has_han(word) else "",
            base=self._other(word, entries) if not has_han(word) else "",
            chengyu=any(e.idiom for e in entries),
            status=self._status(first),
            saved_in=vocabulary.category(saved.category_id) if saved else None,
            readings=readings,
            more_readings=max(0, len(entries) - limit) if pinned else 0,
            heard=vocabulary.exposures(first.entry_id).heard if pinned else 0,
            parts_title=title,
            parts=parts,
            categories=tuple(vocabulary.categories) if pinned else (),
            back_to=back_to,
            context=context,
            found_at=found_at,
        )

    def _basic(self, word: str, back_to: str) -> Card:
        """A word from a basic dictionary: its readings and senses, marked
        basic; no status, deck or categories."""
        assert self._shown is not None
        entries = self.learner.lookup(word, self._shown.language)
        language = self._shown.language
        if not entries:
            return Card(
                word,
                Shows.NOT_FOUND,
                self.pinned,
                back_to=back_to,
                basic=True,
                language=language,
            )
        limit = READINGS if self.pinned else 1
        first = entries[0]
        # an inflected form: "supe -> saber /saˈber/", the reading the lemma's
        base = said(first) if first.headword != word else ""
        readings = []
        for n, entry in enumerate(entries[:limit]):
            # the reading as the pack has it: kana, IPA with its slashes, or
            # the word with its stress marked
            reading = entry.reading
            if entry.headword != word:
                # the form's own, where the pack marks it ("руку": "ру́ку")
                own = self.learner.form_reading(word, language)
                reading = own if n == 0 else said(entry)
            senses = definitions(entry)[0]
            readings.append(
                Reading(reading, tuple(senses[: SENSES if self.pinned else 1]))
            )
        return Card(
            word,
            Shows.ENTRY,
            self.pinned,
            base=base,
            readings=tuple(readings),
            more_readings=max(0, len(entries) - limit) if self.pinned else 0,
            back_to=back_to,
            basic=True,
            language=language,
        )

    def _reading(self, entry: DictionaryEntry, word: str, pinned: bool) -> Reading:
        senses, measure_words = definitions(entry)
        if self.is_chinese:
            reading = entry.reading
        else:  # IPA; and the entry's word, if it isn't the word looked up
            reading = f"/{entry.reading}/" if entry.reading else ""
            if entry.headword != word:
                reading = f"{entry.headword}  {reading}".strip()
        return Reading(
            reading,
            tuple(senses[: SENSES if pinned else 1]),
            tuple(measure_words) if pinned else (),
        )

    @staticmethod
    def _other(word: str, entries: Sequence[DictionaryEntry]) -> str:
        return next(
            (
                f
                for e in entries
                for f in (e.headword, e.traditional)
                if f and f != word
            ),
            "",
        )

    def _not_found(
        self,
        word: str,
        back_to: str,
        context: LookupContext | None,
        found_at: tuple[int, int] | None,
    ) -> Card:
        dictionary = self.learner.dictionary
        if not isinstance(dictionary, ChineseDictionary):
            return Card(word, Shows.NOT_FOUND, self.pinned, back_to=back_to)
        title, parts = (None, ()) if not self.pinned else self._parts(word, found=False)
        return Card(
            word,
            Shows.NOT_FOUND,
            self.pinned,
            guess=dictionary.pinyin_of(word),
            meaning=meaning_of(dictionary, word),
            parts_title=title,
            parts=parts,
            back_to=back_to,
            context=context,
            found_at=found_at,
        )

    def _parts(
        self, word: str, found: bool
    ) -> tuple[PartsTitle | None, tuple[Part, ...]]:
        """The shorter words and the characters inside a Chinese word."""
        dictionary = self.learner.dictionary
        if not isinstance(dictionary, ChineseDictionary) or len(word) < 2:
            return None, ()
        words = dictionary.parts(word) + list(
            dict.fromkeys(c for c in word if is_han(c))
        )
        if not words:
            return None, ()
        title = PartsTitle.INSIDE if found else PartsTitle.WORDS_AND_CHARACTERS
        return title, tuple(self._part(w) for w in words[:PARTS])

    def _part(self, word: str) -> Part:
        entries = self.learner.lookup(word)
        if not entries:
            return Part(word, "", "")
        readings = " / ".join(dict.fromkeys(e.reading for e in entries[:3]))
        return Part(word, readings, "; ".join(definitions(entries[0])[0][:2]))

    def _chinese_for(
        self, dictionary: ChineseDictionary, word: str, back_to: str
    ) -> Card:
        limit = PARTS if self.pinned else HOVER_CHINESE_FOR
        found = list(
            dict.fromkeys(e.headword for e in dictionary.reverse_lookup(word, limit))
        )
        return Card(
            word,
            Shows.CHINESE_FOR,
            self.pinned,
            parts_title=PartsTitle.CHINESE_FOR,
            parts=tuple(self._part(w) for w in found),
            back_to=back_to,
        )


def place(word: Rect, row: Rect, size: Size, area: Rect) -> tuple[Rect, bool]:
    """Where a card of `size` goes for `word` (on screen), in `row` - the
    row being read - on the work area `area`; and whether it's above.

    Above the row, centred on the word; below the row when there's no room
    above; kept on the work area. If it fits on neither side whole, the
    side with more room, held on the area (it may then cover the row)."""
    x = word.x + word.width // 2 - size.width // 2
    x = min(max(x, area.x + MARGIN), area.right - MARGIN - size.width)
    above = row.y - GAP - size.height
    if above >= area.y + MARGIN:
        return Rect(x, above, size.width, size.height), True
    below = row.bottom + GAP
    if below + size.height <= area.bottom - MARGIN:
        return Rect(x, below, size.width, size.height), False
    if row.y - area.y >= area.bottom - row.bottom:
        return Rect(x, area.y + MARGIN, size.width, size.height), True
    y = max(area.y + MARGIN, area.bottom - MARGIN - size.height)
    return Rect(x, y, size.width, size.height), False
