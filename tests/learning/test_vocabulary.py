"""The learner's vocabulary end to end, through a store in memory: the
level picker sets the curve; a sample caption shows the right unfamiliar
words; a lookup, a save and a click change them; exposures and "words you
keep hearing" count correctly; learning events carry entry IDs and times
only."""

import csv
import io
from datetime import date

from tests.learning.fakes import Clock, MemoryLearningStore, facts, words_of

from polyglotic_desktop.core.learning.highlights import WordIntroductions
from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.core.learning.lookups import LookupContext
from polyglotic_desktop.core.learning.statuses import StatusSource
from polyglotic_desktop.core.learning.vocabulary import (
    Changed,
    Vocabulary,
    VocabularyChanged,
)
from polyglotic_desktop.core.shared import (
    EntryFacts,
    EntryId,
    LearningEvent,
    Level,
    WordLookedUp,
    WordSaved,
    WordStatus,
    WordStatusChanged,
    WordUnsaved,
)

# A made-up dictionary: word -> facts on an HSK-like scale.
ENTRIES = {
    "我": facts("我", level=1, rank=5),
    "今天": facts("今天", level=1, rank=60),
    "去": facts("去", level=1, rank=40),
    "超市": facts("超市", level=2, rank=3000),
    "买": facts("买", level=1, rank=300),
    "水果": facts("水果", level=2, rank=2500),
    "和": facts("和", level=1, rank=10),
    "酸奶": facts("酸奶", level=3, rank=9000),
    "还有": facts("还有", level=2, rank=150),
    "榴莲": facts("榴莲", level=None, rank=30000),
    "张伟": facts("张伟", level=None, rank=None, is_name=True),
    "折扣": facts("折扣", level=4, rank=7000),
}
BY_ID = {f.entry_id: f for f in ENTRIES.values()}


def lookup(entry_id: EntryId, scheme: str) -> EntryFacts | None:
    return BY_ID.get(entry_id)


def eid(word: str) -> EntryId:
    return ENTRIES[word].entry_id


class Setup:
    def __init__(self, store: MemoryLearningStore | None = None) -> None:
        self.store = store or MemoryLearningStore()
        self.clock = Clock()
        self.vocab = Vocabulary(self.store, lookup, "hsk-2025", self.clock)
        self.events: list[LearningEvent | VocabularyChanged] = []
        self.vocab.subscribe(self.events.append)

    def sent(self) -> list[LearningEvent]:
        """The events for the server, since last asked."""
        found = [e for e in self.events if not isinstance(e, VocabularyChanged)]
        self.events.clear()
        return found

    def unfamiliar(self, *lines: str) -> list[list[str]]:
        result = self.vocab.highlights(
            [(line, words_of(line, ENTRIES)) for line in lines]
        )
        return [
            [line[w.start : w.end] for w in h.unfamiliar]
            for line, h in zip(lines, result, strict=True)
        ]


LINE = "我 今天 去 超市 买 水果 和 酸奶 还有 榴莲 张伟"


def test_first_run_starts_with_no_level_and_the_default_categories() -> None:
    s = Setup()
    assert s.vocab.curve is None and s.vocab.scheme == "hsk-2025"
    assert [c.name for c in s.vocab.categories] == ["Saved", "Tricky"]
    assert len(s.store.categories) == 2  # kept, so they can be renamed


def test_the_level_picker_sets_the_curve_and_it_is_kept() -> None:
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 2))
    assert s.vocab.curve == LevelCurve("hsk-2025", 2.5)
    assert VocabularyChanged(Changed.LEVEL) in s.events
    again = Vocabulary(s.store, lookup, "hsk-2025")
    assert again.curve == LevelCurve("hsk-2025", 2.5)


def test_until_a_level_is_set_words_are_estimated_at_a_middle_one() -> None:
    """The first run doesn't ask the level (polyglotic-hq 293): a learner
    who hasn't set one is estimated at HSK 3, so a caption doesn't mark
    every word as new - and still has no level of their own."""
    s = Setup()
    assert s.vocab.curve is None
    status = s.vocab.status_of_entry
    assert status(eid("超市")).status is WordStatus.KNOWN  # HSK 2
    assert status(eid("酸奶")).status is WordStatus.KNOWN  # HSK 3
    assert status(eid("折扣")).status is WordStatus.NEW  # HSK 4
    assert s.unfamiliar(LINE) == [[]]  # nothing in reach past HSK 3 here
    s.vocab.set_level(Level("hsk-2025", 0))  # "Just starting", set
    assert status(eid("超市")).status is WordStatus.NEW


def test_a_sample_caption_shows_the_right_unfamiliar_words() -> None:
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 1))
    # 11 words: room for 1. New within reach (level 2): 超市, 水果, 还有 -
    # 还有 is the commonest. 酸奶 (3) and 榴莲 (off the list) are too rare;
    # 张伟 is a name.
    assert s.unfamiliar(LINE) == [["还有"]]
    s.vocab.set_level(Level("hsk-2025", 2))
    assert s.unfamiliar(LINE) == [["酸奶"]]  # the only one in reach now
    s.vocab.set_level(Level("hsk-2025", 6))
    assert s.unfamiliar(LINE) == [[]]
    everything = s.vocab.highlights(
        [(LINE, words_of(LINE, ENTRIES))], WordIntroductions.EVERY
    )
    assert [LINE[w.start : w.end] for w in everything[0].unfamiliar] == ["榴莲"]


def test_a_lookup_save_and_click_change_the_highlights() -> None:
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 2))
    s.sent()
    super_market = ENTRIES["超市"]
    # a pinned lookup of a word only estimated known turns it back to new
    s.vocab.looked_up(super_market, pinned=True)
    status = s.vocab.status(super_market)
    assert (status.status, status.source) == (WordStatus.NEW, StatusSource.ESTIMATED)
    assert s.sent() == [WordLookedUp(eid("超市"), s.clock.now)]  # estimate not sent
    assert "超市" in s.unfamiliar(LINE)[0]

    # saved: drawn in its category's colour wherever it's heard
    s.clock.advance(seconds=5)
    s.vocab.save(
        eid("超市"), "超市", "超市", "chāo shì", "supermarket", "saved",
        LookupContext("我今天去超市", "I went to the supermarket today"),
    )  # fmt: skip
    assert s.sent() == [WordSaved(eid("超市"), s.clock.now)]
    spans = s.vocab.highlights([(LINE, words_of(LINE, ENTRIES))])[0].saved
    assert [(LINE[x.start : x.end], x.entry_id) for x in spans] == [
        ("超市", eid("超市"))
    ]

    # one click marks it known: no longer unfamiliar, and the server hears
    s.clock.advance(seconds=5)
    s.vocab.set_status(eid("超市"), WordStatus.KNOWN)
    assert "超市" not in s.unfamiliar(LINE)[0]
    assert s.sent() == [WordStatusChanged(eid("超市"), WordStatus.KNOWN, s.clock.now)]

    # or adds it to the deck
    s.vocab.set_status(eid("酸奶"), WordStatus.LEARNING)
    deck = s.vocab.highlights([(LINE, words_of(LINE, ENTRIES))])[0].in_deck
    assert [LINE[w.start : w.end] for w in deck] == ["酸奶"]


def test_word_introductions_off_points_out_no_new_word_but_keeps_the_learners_own() -> (
    None
):
    """Off (polyglotic-hq 262; F19, F30): no new word is pointed out - not
    even the one "a few per caption" picks - while saved words and words in
    the deck still show: they're the learner's own."""
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 1))
    s.vocab.save(
        eid("超市"), "超市", "超市", "chāo shì", "supermarket", "saved",
        LookupContext("我今天去超市", "I went to the supermarket today"),
    )  # fmt: skip
    s.vocab.set_status(eid("酸奶"), WordStatus.LEARNING)
    line = [(LINE, words_of(LINE, ENTRIES))]
    assert s.vocab.highlights(line, WordIntroductions.A_FEW)[0].unfamiliar
    off = s.vocab.highlights(line, WordIntroductions.OFF)[0]
    assert off.unfamiliar == []
    assert [LINE[x.start : x.end] for x in off.saved] == ["超市"]
    assert [LINE[w.start : w.end] for w in off.in_deck] == ["酸奶"]


def test_the_learners_own_choices_never_change_by_themselves() -> None:
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 1))
    s.vocab.set_status(eid("我"), WordStatus.KNOWN)
    s.vocab.looked_up(ENTRIES["我"], pinned=True)
    assert s.vocab.status(ENTRIES["我"]).status is WordStatus.KNOWN
    s.vocab.set_level(Level("hsk-2025", 0))
    assert s.vocab.status(ENTRIES["我"]).status is WordStatus.KNOWN
    # a hover isn't evidence enough
    s.vocab.looked_up(ENTRIES["今天"], pinned=False)
    assert s.vocab.status(ENTRIES["今天"]).status is WordStatus.NEW  # level 0 now
    s.vocab.set_level(Level("hsk-2025", 1))
    assert s.vocab.status(ENTRIES["今天"]).status is WordStatus.KNOWN


def test_exposures_and_words_you_keep_hearing_count_correctly() -> None:
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 1))
    s.vocab.caption_finished(
        "c1", words_of("超市 超市 酸奶 张伟", ENTRIES), by_you=False
    )
    s.vocab.caption_finished("c2", words_of("超市 水果", ENTRIES), by_you=False)
    s.vocab.caption_finished("c3", words_of("超市 我", ENTRIES), by_you=False)
    s.vocab.caption_finished("c4", words_of("水果 酸奶 折扣", ENTRIES), by_you=True)
    # a join finishes c3 again: 我 stays counted once, 酸奶 is added
    s.vocab.caption_finished("c3", words_of("超市 我 酸奶", ENTRIES), by_you=False)

    assert s.vocab.exposures(eid("超市")).heard == 3
    assert s.vocab.exposures(eid("酸奶")).heard == 2
    assert s.vocab.exposures(eid("水果")).heard == 1
    assert s.vocab.exposures(eid("水果")).heard_by_you == 1
    assert s.vocab.exposures(eid("张伟")).heard == 0  # names aren't counted
    # unfamiliar words, most heard first; known words and the mic don't count
    assert [e for e, _ in s.vocab.keep_hearing()] == [eid("超市"), eid("酸奶")]

    s.vocab.set_status(eid("超市"), WordStatus.LEARNING)
    assert [e for e, _ in s.vocab.keep_hearing()] == [eid("酸奶")]
    s.vocab.caption_finished("c5", words_of("超市", ENTRIES), by_you=False)
    assert s.vocab.exposures(eid("超市")).heard_in_deck == 1
    assert s.vocab.exposures(eid("超市")).heard == 4

    s.vocab.caption_withdrawn("c5")  # e.g. mic bleed
    assert s.vocab.exposures(eid("超市")).heard == 3
    # kept: the store has the counts, and daily counts without the mic
    again = Vocabulary(s.store, lookup, "hsk-2025")
    assert again.exposures(eid("超市")).heard == 3
    daily = s.store.daily_exposures(date(2026, 11, 4))
    assert daily[eid("超市")] == 3 and eid("折扣") not in daily
    # exposures are never published for the server; the deck change is
    assert [type(e) for e in s.sent()] == [WordStatusChanged]


def test_the_vocabulary_list_shows_every_word_met_with_its_status() -> None:
    s = Setup()
    s.vocab.set_level(Level("hsk-2025", 1))
    s.vocab.caption_finished("c1", words_of("我 超市 超市", ENTRIES), by_you=False)
    s.vocab.caption_finished("c2", words_of("超市", ENTRIES), by_you=False)
    s.vocab.set_status(eid("折扣"), WordStatus.IGNORED)
    rows = s.vocab.vocabulary_list()
    assert [(r.entry_id, r.status.status) for r in rows] == [
        (eid("超市"), WordStatus.NEW),
        (eid("我"), WordStatus.KNOWN),
        (eid("折扣"), WordStatus.IGNORED),
    ]
    assert [r.entry_id for r in s.vocab.vocabulary_list(WordStatus.KNOWN)] == [
        eid("我")
    ]
    # corrected by hand
    s.vocab.set_status(eid("我"), WordStatus.LEARNING)
    assert [r.entry_id for r in s.vocab.vocabulary_list(WordStatus.LEARNING)] == [
        eid("我")
    ]


def test_categories_are_added_renamed_and_deleted_with_their_words() -> None:
    s = Setup()
    food = s.vocab.add_category("Food")
    assert food.color not in {c.color for c in s.vocab.categories if c != food}
    s.vocab.change_category(food.id, name="Food words", color="#123456")
    assert s.vocab.category(food.id) is not None
    assert s.vocab.category(food.id).name == "Food words"  # type: ignore[union-attr]
    ctx = LookupContext("吃榴莲")
    s.vocab.save(eid("榴莲"), "榴莲", "榴槤", "liú lián", "durian", food.id, ctx)
    s.vocab.save(eid("榴莲"), "榴莲", "榴槤", "liú lián", "durian", "tricky", ctx)
    assert s.vocab.saved_word(eid("榴莲")).category_id == "tricky"  # type: ignore[union-attr]
    s.vocab.save(eid("酸奶"), "酸奶", "酸奶", "suān nǎi", "yogurt", food.id, ctx)
    s.sent()
    s.vocab.remove_category(food.id)
    assert s.sent() == [WordUnsaved(eid("酸奶"), s.clock.now)]
    assert [w.entry_id for w in s.vocab.saved_words] == [eid("榴莲")]
    s.vocab.unsave(eid("榴莲"))
    s.vocab.remove_category("tricky")
    s.vocab.remove_category("saved")  # the last one stays
    assert [c.id for c in s.vocab.categories] == ["saved"]
    again = Vocabulary(s.store, lookup, "hsk-2025")
    assert [c.id for c in again.categories] == ["saved"] and not again.saved_words


def test_saved_words_export_as_a_csv_anki_imports() -> None:
    s = Setup()
    s.vocab.save(
        eid("榴莲"), "榴莲", "榴槤", "liú lián", "durian", "saved",
        LookupContext("他说：“榴莲, 很臭”", 'He said: "durian, smelly"'),
    )  # fmt: skip
    s.clock.advance(minutes=1)
    s.vocab.save(
        eid("酸奶"), "酸奶", "酸奶", "suān nǎi", "yogurt", "tricky", LookupContext("")
    )
    file = s.vocab.export_anki()
    assert file.entry_ids == (eid("榴莲"), eid("酸奶"))
    lines = file.text.splitlines()
    assert lines[:2] == ["#separator:Comma", "#html:true"]
    assert "#guid column:8" in lines and "#tags column:3" in lines
    rows = list(csv.reader(io.StringIO("\n".join(ln for ln in lines if ln[0] != "#"))))
    assert [r[-1] for r in rows] == [
        f"polyglotic:{eid('榴莲')}",
        f"polyglotic:{eid('酸奶')}",
    ]
    assert rows[0][0:3:2] == ["榴莲 (榴槤)", "polyglotic polyglotic::Saved"]
    assert rows[0][3:7] == [
        "liú lián", "durian", "他说：“<b>榴莲</b>, 很臭”",
        'He said: "durian, smelly"',
    ]  # fmt: skip
    assert rows[1][0:3:2] == ["酸奶", "polyglotic polyglotic::Tricky"]
    assert rows[1][5:7] == ["", ""]  # saved with no sentence


def test_the_whole_learning_state_is_what_was_published_last_per_word() -> None:
    """After the server's store is restored, the app sends this again
    (polyglotic-hq project 166): each status the learner set and each saved
    word, at its time - what was published for them, the latest of each -
    and none of the statuses Learning only estimated."""
    s = Setup()
    ctx = LookupContext("我今天去超市", "I went to the supermarket today")
    s.vocab.set_status(eid("超市"), WordStatus.LEARNING)
    s.clock.advance(seconds=5)
    s.vocab.set_status(eid("超市"), WordStatus.KNOWN)
    s.vocab.save(eid("榴莲"), "榴莲", "榴槤", "liú lián", "durian", "saved", ctx)
    s.vocab.save(eid("酸奶"), "酸奶", "酸奶", "suān nǎi", "yoghurt", "saved", ctx)
    s.vocab.unsave(eid("酸奶"))
    s.vocab.set_status(eid("水果"), WordStatus.KNOWN, StatusSource.ESTIMATED)
    published = s.sent()
    latest = {(type(e), e.entry_id): e for e in published}
    expected = [
        e for e in latest.values() if isinstance(e, (WordStatusChanged, WordSaved))
    ]
    expected = [e for e in expected if e.entry_id != eid("酸奶")]  # unsaved since
    assert sorted(s.vocab.learning_state(), key=repr) == sorted(expected, key=repr)
    assert len(expected) == 2
