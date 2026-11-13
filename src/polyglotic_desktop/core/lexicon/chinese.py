"""Chinese: word split, everyday readings, parts and reverse lookup.

From the proof of concept's `dictionary.py` (CC-CEDICT, the word split
that keeps whole phrases and chengyu together, everyday readings, English
to Chinese), reading entries through the `DictionaryFile` port instead of
holding the whole dictionary in memory.

Some rules run when the dictionary file is built rather than in the app,
so that loading is instant: `everyday_first` (the order of a word's
entries) and `index_words` (the reverse lookup's index). They live here so
the rule has one home; `tools/dictionaries` calls them.
"""

import itertools
import math
import re
import threading
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from polyglotic_desktop.core.lexicon.entries import (
    DictionaryEntry,
    entry_facts,
    words_in_runs,
)
from polyglotic_desktop.core.lexicon.pinyin import mark_pinyin
from polyglotic_desktop.core.shared import EntryFacts, EntryId, WordInLine
from polyglotic_desktop.ports.dictionary import DictionaryFile, EntryRecord

MAX_WORD = 20  # characters - CC-CEDICT's longest entries are whole proverbs
# Reverse lookup ranks at most this many entries per English word form, the
# commonest: "to" is in about 35,000 meanings, and ranking them all takes 2s.
REVERSE_CANDIDATES = 2000

# Function words read differently alone than in the words that contain
# them - their everyday reading first (see everyday_first).
FUNCTION_READINGS = {
    "还": "hái", "還": "hái", "都": "dōu", "了": "le", "着": "zhe", "著": "zhe",
    "得": "de", "的": "de", "吧": "ba", "呢": "ne", "啊": "a", "吗": "ma",
    "嗎": "ma", "嘛": "ma", "呀": "ya", "么": "me", "麼": "me", "哪": "nǎ",
}  # fmt: skip


def is_han(char: str) -> bool:
    return (
        "㐀" <= char <= "鿿"
        or "豈" <= char <= "﫿"
        or "\U00020000" <= char <= "\U0002ffff"
        or char == "〇"
    )


def has_han(text: str) -> bool:
    return any(is_han(c) for c in text)


def entry_from_record(record: EntryRecord) -> DictionaryEntry:
    """A CC-CEDICT entry with its pinyin tone-marked. Capitalised pinyin
    marks a proper noun - a name or place - in CC-CEDICT."""
    return DictionaryEntry(
        entry_id=EntryId(record.entry_id),
        headword=record.headword,
        traditional=record.traditional,
        reading=mark_pinyin(record.reading),
        meanings=record.meanings,
        frequency_rank=record.frequency_rank,
        levels=record.levels,
        is_name=_is_name(record),
    )


def facts_from_record(record: EntryRecord, scheme_id: str) -> EntryFacts:
    """`entry_from_record(record).facts(scheme_id)`, without marking the
    pinyin - most of making an entry (polyglotic-hq project 212)."""
    return entry_facts(
        EntryId(record.entry_id),
        record.frequency_rank,
        record.levels,
        _is_name(record),
        scheme_id,
    )


def _is_name(record: EntryRecord) -> bool:
    return record.reading[:1].isupper()


# -- rules applied when the file is built ---------------------------------------


def count_reading_uses(entries: Iterable[DictionaryEntry]) -> Counter[tuple[str, str]]:
    """How many words use each reading of each character: (char, syllable)
    -> words. CC-CEDICT has no frequencies, but this is a good stand-in for
    a character's everyday reading (足: zú in 329 words, jù in none)."""
    uses: Counter[tuple[str, str]] = Counter()
    for e in entries:
        syllables = e.reading.lower().split()
        if len(e.headword) > 1 and len(syllables) == len(e.headword):
            for form in {e.headword, e.traditional}:
                uses.update(zip(form, syllables, strict=True))
    return uses


def everyday_first(
    word: str, entries: Iterable[DictionaryEntry], uses: Counter[tuple[str, str]]
) -> list[DictionaryEntry]:
    """`word`'s entries in the order a lookup shows them: real meanings
    before "variant of", common words before names, then the reading
    likeliest in speech - a function word's own reading (还 hái, though
    huán is in more words), then the reading most words use."""
    return sorted(
        entries,
        key=lambda e: (
            e.variant_only,
            e.is_name,
            e.reading != FUNCTION_READINGS.get(word, e.reading),
            -uses[word, e.reading.lower()],
        ),
    )


_INDEX_WORD = re.compile(r"[a-z]+")


def index_words(entry: DictionaryEntry) -> set[str]:
    """The English words reverse lookup finds `entry` by - none for a
    "variant of" entry, and not from measure words ("CL:")."""
    if entry.variant_only:
        return set()
    words: set[str] = set()
    for meaning in entry.meanings:
        if not meaning.startswith("CL:"):
            words.update(_INDEX_WORD.findall(meaning.lower()))
    return words


# -- reverse lookup helpers -----------------------------------------------------

_STOP = {
    "a", "an", "the", "to", "of", "it", "its", "is", "am", "are", "was", "were",
    "be", "been", "will", "would", "have", "has", "and", "or", "in", "on", "at",
    "for", "with", "this", "that", "i", "you", "me", "my", "your", "s", "so",
    "just", "like", "do",
}  # fmt: skip
# A reading's first meaning starting so: rarely the one being said
_OBSCURE = (
    "(archaic)", "(literary)", "(old)", "(dialect)", "(Cantonese)",
    "old variant", "surname", "used in",
)  # fmt: skip
_CONTRACTIONS = {"re": " are", "m": " am", "ll": " will", "ve": " have", "d": " would"}


def _plain(text: str) -> str:
    """A meaning (or English query) compared plainly: lower case, no
    "(coll.)"-style notes, no articles, no leading "to"."""
    text = re.sub(r"\([^)]*\)", " ", text.lower())
    text = " ".join(
        w for w in re.findall(r"[a-z']+", text) if w not in ("a", "an", "the")
    )
    return re.sub(r"^to ", "", text)


def _stems(word: str) -> list[str]:
    """The word and what it may be in a meaning: games -> game, overdoing
    -> overdo, lagging -> lag."""
    forms = [word]
    for suffix, back in (
        ("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"),
    ):  # fmt: skip
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)] + back
            forms.append(stem)
            if len(stem) > 3 and stem[-1] == stem[-2]:  # lagging -> lagg -> lag
                forms.append(stem[:-1])
    return forms


def _commonness(rank: int | None) -> float:
    """Higher for commoner words: about log2 of a count, from the rank."""
    return 0.0 if rank is None else max(0.0, 21 - math.log2(rank))


class ChineseDictionary:
    """CC-CEDICT for Chinese learners: lookups in either script, the word
    split, parts, pinyin for a phrase, and English to Chinese.

    Opening one reads nothing. The word split needs every headword and
    frequency rank (about 0.2 s for CC-CEDICT, polyglotic-hq project 110):
    `prepare` reads them - call it off the interface thread at start, and
    ask `ready` before splitting on it (polyglotic-hq project 136);
    otherwise the first split, `is_word` or `parts` does. Lookups are
    queries."""

    def __init__(self, file: DictionaryFile) -> None:
        self._file = file
        self._split: dict[str, float] | None = None
        """Every written form in the dictionary, with its commonness (0.0
        for the many without a frequency rank): one mapping, so each form is
        held once (polyglotic-hq project 136: about 25 MB for CC-CEDICT)."""
        self._preparing = threading.Lock()

    @property
    def ready(self) -> bool:
        """Whether the word split's data is read: `split`, `words_in` and
        `parts` answer without reading it first."""
        return self._split is not None

    def prepare(self) -> None:
        """Reads what the word split needs, once. Safe to call from another
        thread while this one is used: the data is set in one step, and a
        second caller waits for the first instead of reading it again."""
        if self._split is not None:
            return
        with self._preparing:
            if self._split is None:
                commonness = {
                    form: _commonness(rank)
                    for form, rank in self._file.frequency_ranks().items()
                }
                for form in self._file.headwords():
                    commonness.setdefault(form, 0.0)
                self._split = commonness

    def _split_data(self) -> dict[str, float]:
        """The headwords and their commonness, read now if not yet."""
        self.prepare()
        assert self._split is not None
        return self._split

    def lookup(self, word: str) -> list[DictionaryEntry]:
        """Every entry for `word` (in either script), everyday reading first."""
        return [entry_from_record(r) for r in self._file.records(word)]

    def entry(self, entry_id: EntryId) -> DictionaryEntry | None:
        """The entry with this ID - or the one it was merged into."""
        record = self._file.record(entry_id)
        return entry_from_record(record) if record else None

    def facts(self, entry_id: EntryId, scheme_id: str) -> EntryFacts | None:
        """`entry(entry_id).facts(scheme_id)`, read without making the entry:
        what Learning asks for every word met (polyglotic-hq project 212)."""
        record = self._file.record(entry_id)
        return facts_from_record(record, scheme_id) if record else None

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

    def is_word(self, text: str) -> bool:
        return text in self._split_data()

    def split(self, text: str) -> list[tuple[int, int]]:
        """The word split: [(start, end)] covering `text`, each run of Chinese
        characters cut into dictionary words - as few as possible, so whole
        phrases and chengyu stay together; among equally few, the most
        evenly sized (研究/生命/起源, not 研究生/命/起源), then the commoner
        words (是/非常, not 是非/常; 这个/人, not 这/个人 - by the entries'
        frequency ranks), then the longest first. Everything else (Latin,
        digits, punctuation) is one span per run, not looked up.

        Project 039 (2026-11-05) measured the split on 60 FLEURS sentences:
        every wrong cut that made a non-word (很|多情|况, 中看|到, 会面|临刑|事)
        was a tie on the first two rules, and the frequency rule fixes
        them all. The server splits the same way for word links, with the
        same ranks, so a link's underline matches the hover highlight."""
        spans: list[tuple[int, int]] = []
        i, n = 0, len(text)
        while i < n:
            j = i
            if is_han(text[i]):
                while j < n and is_han(text[j]):
                    j += 1
                spans += [(i + a, i + b) for a, b in self._split_run(text[i:j])]
            else:
                while j < n and not is_han(text[j]):
                    j += 1
                spans.append((i, j))
            i = j
        return spans

    def _split_run(self, run: str) -> list[tuple[int, int]]:
        words = self._split_data()  # a form -> its commonness
        n = len(run)
        # best[i]: (words, sum of squared lengths, -commonness, previous cut)
        # for run[:i]; commonness is the words' summed _commonness
        best: list[tuple[int, int, float, int] | None] = [(0, 0, 0.0, -1)] + [None] * n
        for end in range(1, n + 1):
            for start in range(max(0, end - MAX_WORD), end):
                before = best[start]
                word = run[start:end]
                if before is None or (end - start > 1 and word not in words):
                    continue
                candidate = (
                    before[0] + 1,
                    before[1] + (end - start) ** 2,
                    before[2] - words.get(word, 0.0),
                    start,
                )
                current = best[end]
                # <=: on a tie the later start wins - the longer earlier word
                if current is None or candidate[:3] <= current[:3]:
                    best[end] = candidate
        cuts = []
        end = n
        while end > 0:
            step = best[end]
            assert step is not None  # every single character is a step
            cuts.append((step[3], end))
            end = step[3]
        return cuts[::-1]

    def words_in(self, text: str, scheme_id: str) -> list[WordInLine]:
        """The dictionary words in `text`, by the word split, each with the
        facts Learning needs for a learner in `scheme_id` - for highlights
        and exposures. A word counts for its everyday reading's entry (还
        for hái). Characters the dictionary hasn't got are left out."""
        found = []
        for start, end in self.split(text):
            word = text[start:end]
            if not has_han(word):
                continue
            entries = self.lookup(word)
            if entries:
                found.append(WordInLine(start, end, entries[0].facts(scheme_id)))
        return found

    def word_at(self, text: str, index: int) -> tuple[int, int] | None:
        """(start, end) of the dictionary word the character at `index`
        belongs to - None for anything but a Chinese character."""
        if not (0 <= index < len(text)) or not is_han(text[index]):
            return None
        for start, end in self.split(text):
            if start <= index < end:
                return start, end
        return None

    def parts(self, word: str) -> list[str]:
        """The shorter dictionary words inside `word` (游戏 in 打游戏),
        longest first - each once, in order of where they start."""
        words = self._split_data()
        found: list[str] = []
        for length in range(len(word) - 1, 1, -1):
            for start in range(len(word) - length + 1):
                part = word[start : start + length]
                if part in words and part not in found:
                    found.append(part)
        return found

    def pinyin_of(self, text: str) -> str:
        """Best-guess pinyin for any Chinese text: each word's everyday
        reading - for a phrase the dictionary doesn't have as a whole."""
        out = []
        for start, end in self.split(text):
            part = text[start:end]
            if not has_han(part):
                continue
            entries = self.lookup(part)
            out.append(entries[0].reading if entries else "?" * len(part))
        return " ".join(out)

    def reverse_lookup(self, query: str, limit: int = 8) -> list[DictionaryEntry]:
        """Chinese words for an English word or phrase, from CC-CEDICT's
        meanings: a meaning that's exactly the phrase first ("game" - 游戏),
        then ones starting or ending with it, then containing it, then with
        all its words; everyday words before names; then the commonest
        (累 before 骀 for "tired"), favouring a word's main meaning over a
        side one; then the phrase as given before a stemmed form of it."""
        text = query.lower().replace("’", "'")
        text = re.sub(r"n't\b", " not", text)
        text = re.sub(
            r"'(re|m|s|ll|ve|d)\b", lambda m: _CONTRACTIONS.get(m.group(1), ""), text
        )
        words = re.findall(r"[a-z]+", text)
        content = [w for w in words if w not in _STOP] or words
        if not content:
            return []
        found: dict[str, DictionaryEntry] | None = None
        for word in content:
            entries = {
                r.entry_id: entry_from_record(r)
                for form in _stems(word)
                for r in self._file.records_by_meaning(form, REVERSE_CANDIDATES)
            }
            found = (
                entries
                if found is None
                else {k: e for k, e in found.items() if k in entries}
            )
        phrases = self._phrases(words, content)
        ranked = []
        for e in (found or {}).values():
            best = self._best_match(e, phrases, content)
            if best is not None:
                # How common, less a little for each meaning before the
                # match: 支持 (to support, its 2nd) still before 赡 (to
                # support, its 1st). The rank is the word's, so not an
                # obscure reading's - not 那 nuó's (archaic: beautiful).
                obscure = e.meanings[0].startswith(_OBSCURE) if e.meanings else False
                common = (
                    _commonness(None if obscure else e.frequency_rank) - 1.5 * best[2]
                )
                key = (best[0], e.is_name, -common, best[1], len(e.headword))
                ranked.append((key, e))
        ranked.sort(key=lambda r: r[0])
        return [e for _, e in ranked[:limit]]

    @staticmethod
    def _phrases(words: Sequence[str], content: Sequence[str]) -> dict[str, bool]:
        """The phrase, and without what it starts with before its first real
        word ("I don't know" -> "not know"), each also with its words
        stemmed: phrase -> whether it was stemmed."""
        first = words.index(content[0])
        phrases: dict[str, bool] = {}
        for start in (0, first):
            tail = words[start:]
            options = [_stems(w) if w in content else [w] for w in tail][:6]
            for variant in itertools.islice(itertools.product(*options), 64):
                phrase = _plain(" ".join(variant))
                stemmed = any(
                    form != word for form, word in zip(variant, tail, strict=False)
                )
                if phrase and (phrase not in phrases or not stemmed):
                    phrases[phrase] = stemmed
        return phrases

    @staticmethod
    def _best_match(
        entry: DictionaryEntry, phrases: dict[str, bool], content: Sequence[str]
    ) -> tuple[int, bool, int] | None:
        """(how well, stemmed, which meaning) of the best match, or None."""
        best: tuple[int, bool, int] | None = None
        # each sense on its own - a meaning is often several: "safe; secure"
        for position, meaning in enumerate(entry.meanings):
            for sense in meaning.split(";"):
                plain = _plain(sense)
                if not plain:
                    continue
                for phrase, stemmed in phrases.items():
                    if plain == phrase:
                        score = 0
                    elif plain.startswith(phrase + " ") or plain.endswith(" " + phrase):
                        score = 1
                    elif f" {phrase} " in f" {plain} ":
                        score = 2
                    elif all(
                        any(f" {form} " in f" {plain} " for form in _stems(w))
                        for w in content
                    ):
                        score = 3
                    else:
                        continue
                    key = (score, stemmed, position)
                    best = key if best is None or key < best else best
        return best
