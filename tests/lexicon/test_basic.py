"""A basic dictionary's lookups (decision 0035), through fakes of the
dictionary file and the word split: the order a caption's word is looked
up in, and the words in a line."""

from collections.abc import Sequence

from tests.lexicon.sample import FakeDictionaryFile

from polyglotic_desktop.core.lexicon.basic import BasicDictionary
from polyglotic_desktop.ports.dictionary import EntryRecord
from polyglotic_desktop.ports.word_split import SplitWord


def record(entry_id: str, headword: str, meaning: str, rank: int = 1) -> EntryRecord:
    return EntryRecord(entry_id, headword, "", "", (meaning,), rank)


SPANISH = FakeDictionaryFile(
    [
        record("wiktes:casa", "casa", "house", 300),
        record("wiktes:casar", "casar", "to marry", 2000),
        record("wiktes:saber", "saber", "to know", 160),
        record("wiktes:venir", "venir", "to come", 270),
        record("wiktes:vengar", "vengar", "to avenge", 9000),
        record("wiktes:Darwin", "Darwin", "a surname", 8000),
    ],
    {
        "casa": ["wiktes:casa"],
        "casar": ["wiktes:casar"],
        "saber": ["wiktes:saber"],
        "venir": ["wiktes:venir"],
        "vengar": ["wiktes:vengar"],
        "Darwin": ["wiktes:Darwin"],
    },
    lemmas={"supe": "saber", "vengo": "venir"},
)


class FakeSplit:
    """Words by spaces; `table` gives each word's analysis."""

    def __init__(self, table: dict[str, SplitWord] | None = None) -> None:
        self.table = table or {}

    def words(self, text: str) -> Sequence[SplitWord]:
        out, at = [], 0
        for word in text.split():
            start = text.index(word, at)
            at = start + len(word)
            seen = self.table.get(word, SplitWord(0, 0))
            out.append(SplitWord(start, at, seen.lemmas, seen.guesses, seen.content))
        return out


def heads(dictionary: BasicDictionary, word: str) -> list[str]:
    return [e.headword for e in dictionary.lookup(word)]


def test_the_packs_own_forms_come_before_the_analysers_guess() -> None:
    split = FakeSplit({"vengo": SplitWord(0, 0, guesses=("vengar",))})
    spanish = BasicDictionary(SPANISH, split, "es")
    assert heads(spanish, "vengo") == ["venir"]  # Wiktionary's, not simplemma's
    assert heads(spanish, "supe") == ["saber"]
    assert heads(spanish, "Casa") == ["casa"]  # lower case too
    assert spanish.lookup("nada") == []


def test_a_guess_is_tried_when_the_pack_knows_nothing_better() -> None:
    split = FakeSplit({"casándose": SplitWord(0, 0, guesses=("casar",))})
    assert heads(BasicDictionary(SPANISH, split, "es"), "casándose") == ["casar"]


def test_an_analysers_lemma_in_context_comes_before_the_word_itself() -> None:
    japanese = FakeDictionaryFile(
        [
            record("jmdict:suru", "する", "to do", 27),
            record("jmdict:shi", "し", "four"),
        ],
        {"する": ["jmdict:suru"], "し": ["jmdict:shi"]},
    )
    split = FakeSplit({"し": SplitWord(0, 0, lemmas=("する",), content=True)})
    assert heads(BasicDictionary(japanese, split, "ja"), "し") == ["する", "し"]


def test_words_in_a_line_count_for_their_entries() -> None:
    split = FakeSplit({"vengo": SplitWord(0, 0, guesses=("vengar",))})
    spanish = BasicDictionary(SPANISH, split, "es")
    words = spanish.words_in("vengo a casa de Darwin", "es-frequency")
    assert [(w.start, w.end, w.entry.entry_id) for w in words] == [
        (0, 5, "wiktes:venir"),
        (8, 12, "wiktes:casa"),
        (16, 22, "wiktes:Darwin"),
    ]
    assert words[2].entry.is_name  # a capitalised headword, as in English
    assert spanish.word_at("vengo a casa", 9) == (8, 12)
    assert spanish.word_at("vengo a casa", 5) is None
    assert spanish.entry(words[0].entry.entry_id) == spanish.lookup("venir")[0]


def test_a_phrase_is_looked_up_as_written() -> None:
    spanish = BasicDictionary(SPANISH, FakeSplit(), "es")
    assert spanish.lookup("a casa") == []


def test_a_forms_own_reading_is_found_as_written_or_in_lower_case() -> None:
    russian = BasicDictionary(
        FakeDictionaryFile(
            [record("wiktru:ruka", "рука", "hand")],
            {"рука": ["wiktru:ruka"]},
            lemmas={"руку": "рука"},
            form_readings={"руку": "ру́ку"},
        ),
        FakeSplit(),
        "ru",
    )
    assert russian.form_reading("руку") == russian.form_reading("Руку") == "ру́ку"
    assert russian.form_reading("рука") == ""
