"""English lookups (core.lexicon.english): words in a line, and inflected
forms counting for their entry - statuses and exposures are per entry."""

from tests.lexicon.sample import FakeDictionaryFile

from polyglotic_desktop.core.lexicon.english import EnglishDictionary, word_at, words
from polyglotic_desktop.ports.dictionary import EntryRecord


def record(word: str, meaning: str, rank: int | None = None) -> EntryRecord:
    return EntryRecord(f"ecdict:{word}", word, "", "", (meaning,), rank)


def dictionary() -> EnglishDictionary:
    records = [
        record("run", "v. 跑", 202),
        record("running", "n. 赛跑", 3252),
        record("leave", "v. 离开", 300),
        record("left", "a. 左边的", 771),
        record("English", "n. 英语", 900),
        record("I", "pron. 我", 11),
    ]
    file = FakeDictionaryFile(
        records,
        forms={r.headword: [r.entry_id] for r in records},
        lemmas={"running": "run", "ran": "run", "runs": "run", "left": "leave"},
    )
    return EnglishDictionary(file)


def test_words_in_a_line() -> None:
    line = "Doing it like this is overdoing it"
    assert word_at(line, 10) == (9, 13)
    assert word_at("I don't know", 3) == (2, 7)
    assert word_at("tiếng Việt", 2) == (0, 5)
    assert word_at("a, b", 1) is None
    assert words("well-known, it's") == [(0, 10), (12, 16)]


def test_a_word_among_chinese_characters_is_only_its_letters() -> None:
    """Code-switching (我用English说): the Latin word alone, not the Chinese
    characters it touches (polyglotic-hq 133: a click on iPhone looked up
    年的iPhone太贵了)."""
    line = "李明说2026年的iPhone太贵了！"
    assert word_at(line, line.index("P")) == (9, 15)
    assert word_at(line, line.index("贵")) is None  # the Chinese split's
    assert words("我用English说hello world，好吗") == [(2, 9), (10, 15), (16, 21)]
    assert words("〇〇七 James Bond") == [(4, 9), (10, 14)]


def test_inflected_forms_count_for_their_entry() -> None:
    d = dictionary()
    run = d.lookup("run")[0]
    assert d.entry_for_word("running") == run
    assert d.entry_for_word("ran") == run
    assert d.entry_for_word("Runs") == run  # lower case tried too
    assert d.entry_for_word("xyzzy") is None


def test_a_form_with_meanings_of_its_own_is_looked_up_after_its_lemma() -> None:
    d = dictionary()
    assert [e.headword for e in d.lookup("left")] == ["leave", "left"]
    assert [e.headword for e in d.lookup("running")] == ["run", "running"]


def test_capitalised_words_are_names_but_i_is_not() -> None:
    d = dictionary()
    assert d.lookup("English")[0].is_name
    assert not d.lookup("I")[0].is_name
    assert not d.lookup("run")[0].is_name
