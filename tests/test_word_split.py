"""The word splits behind the `WordSplit` port (polyglotic-hq project 164):
Sudachi for Japanese, letters and simplemma for Spanish."""

from polyglotic_desktop.adapters.japanese_split import JapaneseSplit
from polyglotic_desktop.adapters.spaced_split import SpacedSplit
from polyglotic_desktop.ports.word_split import SplitWord, WordSplit


def texts(split: WordSplit, line: str) -> list[str]:
    return [line[w.start : w.end] for w in split.words(line)]


def test_japanese_is_split_into_words_with_their_dictionary_forms() -> None:
    line = "私は昨日、寿司を食べました。"
    split = JapaneseSplit()
    assert texts(split, line) == [
        "私",
        "は",
        "昨日",
        "寿司",
        "を",
        "食べ",
        "まし",
        "た",
    ]
    words = {line[w.start : w.end]: w for w in split.words(line)}
    assert words["食べ"].lemmas == ("食べる",)
    assert words["まし"].lemmas == ("ます",)
    assert words["寿司"] == SplitWord(5, 7)  # its own dictionary form, content
    assert not words["は"].content and not words["まし"].content  # particle, auxiliary
    assert words["食べ"].content and words["昨日"].content


def test_japanese_normalised_forms_come_first_they_tell_namesakes_apart() -> None:
    line = "猫がいた。することがある。"
    words = {line[w.start : w.end]: w for w in JapaneseSplit().words(line)}
    assert words["い"].lemmas == ("居る", "いる")  # "to be", not 要る "to need"
    assert words["する"].lemmas == ("為る",)
    assert words["ある"].lemmas == ("有る",)


def test_japanese_spaces_and_punctuation_are_not_words() -> None:
    assert texts(JapaneseSplit(), "「はい」、 そう。") == ["はい", "そう"]
    assert JapaneseSplit().words("") == []


def test_spanish_words_with_simplemmas_lemma() -> None:
    line = "¿Hablábamos de eso? Sí, y del agua."
    split = SpacedSplit("es")
    assert texts(split, line) == ["Hablábamos", "de", "eso", "Sí", "y", "del", "agua"]
    words = split.words(line)
    assert words[0].guesses == ("hablar",) and words[0].lemmas == ()
    assert words[1].guesses == ()  # "de" is its own lemma
    assert all(w.content for w in words)


def test_a_spanish_word_beside_chinese_characters_is_a_word_of_its_own() -> None:
    assert texts(SpacedSplit("es"), "用español说") == ["español"]
