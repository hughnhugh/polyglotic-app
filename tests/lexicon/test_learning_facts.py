"""What Lexicon tells Learning: the words in a line with their entries'
facts (level in the learner's scheme, rank, name), and meanings as a
lookup shows them."""

import pytest
from tests.lexicon.sample import chinese_sample, english_sample

from polyglotic_desktop.core.lexicon import chinese
from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary
from polyglotic_desktop.core.lexicon.english import EnglishDictionary
from polyglotic_desktop.core.lexicon.entries import DictionaryEntry
from polyglotic_desktop.core.lexicon.meanings import (
    definitions,
    meaning_of,
    short_meaning,
)
from polyglotic_desktop.core.shared import EntryId


def test_chinese_words_in_a_line_count_for_their_everyday_reading() -> None:
    zh = ChineseDictionary(chinese_sample(frequency_ranks={"还": 100}))
    line = "我还打游戏 OK 北京"
    found = zh.words_in(line, "hsk-2025")
    assert [line[w.start : w.end] for w in found] == [
        "还",
        "打游戏",
        "北京",
    ]  # 我 isn't in the sample
    hai = found[0].entry
    assert hai.entry_id == zh.lookup("还")[0].entry_id
    assert zh.lookup("还")[0].reading == "hái"
    assert hai.frequency_rank == 100 and hai.level is None
    assert found[2].entry.is_name


def test_english_words_count_for_their_lemma_with_their_band() -> None:
    en = EnglishDictionary(english_sample())
    line = "They ran to brunch, ubiquitously"
    found = en.words_in(line, "en-frequency")
    assert [line[w.start : w.end] for w in found] == ["They", "ran", "to", "brunch"]
    ran = found[1].entry
    assert ran.entry_id == "ecdict:run" and ran.level == 1  # rank 202: top 1,000
    assert found[3].entry.level == 7  # rank 15,000: the top 20,000
    assert found[0].entry.level == 1  # "They" found as "they"


def test_an_entrys_level_depends_on_the_scheme() -> None:
    entry = DictionaryEntry(
        EntryId("cedict:x"), "爱好", "愛好", "ài hào", ("hobby",), 2400,
        (("hsk-2025", 2), ("hsk-2021", 1)),
    )  # fmt: skip
    assert entry.facts("hsk-2025").level == 2
    assert entry.facts("hsk-2021").level == 1
    assert entry.facts("en-frequency").level == 3  # by rank
    assert entry.facts("no-such-scheme").level is None


SCHEMES_TRIED = ("hsk-2025", "hsk-2021", "en-frequency", "no-such-scheme")


def test_an_entrys_facts_read_alone_are_its_entrys_in_every_scheme() -> None:
    """`facts` - what Learning asks for every word met - is the entry's
    facts, names and merged entries included (polyglotic-hq 212)."""
    sample = chinese_sample(frequency_ranks={"电脑": 2400, "北京": 300})
    sample.merged["cedict:old"] = sample.forms["电脑"][0]
    zh = ChineseDictionary(sample)
    en = EnglishDictionary(english_sample())
    for dictionary, ids in (
        (zh, [*chinese_sample().by_id, "cedict:old"]),
        (en, list(english_sample().by_id)),
    ):
        for entry_id in ids:
            entry = dictionary.entry(EntryId(entry_id))
            assert entry is not None
            for scheme in SCHEMES_TRIED:
                assert dictionary.facts(EntryId(entry_id), scheme) == entry.facts(
                    scheme
                )
        assert dictionary.facts(EntryId("cedict:nothing"), "hsk-2025") is None
    assert zh.facts(EntryId(sample.forms["北京"][0]), "hsk-2025").is_name  # type: ignore[union-attr]


def test_a_chinese_entrys_facts_are_read_without_marking_its_pinyin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marking the pinyin was most of the cost: Words' first show read
    every word met's facts that way - 80 ms at 10,000 words met
    (polyglotic-hq 212)."""
    zh = ChineseDictionary(chinese_sample())
    computer = zh.lookup("电脑")[0]

    def marked(reading: str) -> str:
        raise AssertionError("pinyin marked for facts")

    monkeypatch.setattr(chinese, "mark_pinyin", marked)
    assert zh.facts(computer.entry_id, "hsk-2025") == computer.facts("hsk-2025")


def test_measure_words_are_pulled_out_of_the_definitions() -> None:
    zh = ChineseDictionary(chinese_sample())
    computer = zh.lookup("电脑")
    assert definitions(computer[0]) == (["computer"], ["台 tái"])
    assert short_meaning(computer) == "computer"
    # the first entry's first few meanings
    assert short_meaning(zh.lookup("画")) == "to draw; to paint; picture; painting"
    assert short_meaning(zh.lookup("画"), limit=1) == "to draw; to paint"
    assert short_meaning([]) == ""


def test_a_phrase_not_in_the_dictionary_gets_its_words_meanings() -> None:
    zh = ChineseDictionary(chinese_sample())
    assert meaning_of(zh, "电脑") == "computer"
    assert meaning_of(zh, "电脑游戏") == "computer + game"
    assert meaning_of(zh, "OK") == ""


def test_the_level_picker_knows_about_how_many_words_each_level_is() -> None:
    from polyglotic_desktop.core.lexicon.entries import (
        ENGLISH_FREQUENCY,
        HSK_2021,
        HSK_2025,
    )

    assert [HSK_2025.words_at(n) for n in (0, 1, 4, 7, 8)] == [
        0,
        300,
        2000,
        11000,
        None,
    ]
    assert ENGLISH_FREQUENCY.words_at(3) == 3000  # the band's cutoff
    assert HSK_2021.words_at(1) is None  # not given
