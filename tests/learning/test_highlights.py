"""Unfamiliar words under the "common words only" cap (project 019,
section 6): new words up to about the next band, about 5% of a caption's
words and 2 per line, the most heard and commonest first, never names."""

from tests.learning.fakes import facts

from polyglotic_desktop.core.learning.highlights import (
    WordIntroductions,
    caption_cap,
    unfamiliar_words,
)
from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.core.learning.statuses import estimated_status
from polyglotic_desktop.core.shared import EntryFacts, EntryId, Level, WordInLine

CURVE = LevelCurve.picked(Level("hsk-2025", 2))


def line_of(*entries: EntryFacts) -> list[WordInLine]:
    return [WordInLine(i * 2, i * 2 + 2, e) for i, e in enumerate(entries)]


def shown(
    lines: list[list[WordInLine]],
    heard: dict[str, int] | None = None,
    common_only: bool = True,
) -> list[list[str]]:
    counts = heard or {}
    result = unfamiliar_words(
        lines,
        lambda f: estimated_status(f, CURVE),
        CURVE,
        lambda entry_id: counts.get(entry_id.removeprefix("test:"), 0),
        common_only,
    )
    return [[w.entry.entry_id.removeprefix("test:") for w in line] for line in result]


def known(n: int) -> list[EntryFacts]:
    return [facts(f"known{i}", level=1) for i in range(n)]


def test_the_cap_is_about_five_percent_and_at_least_one() -> None:
    assert [caption_cap(n) for n in (1, 10, 29, 30, 50, 100)] == [1, 1, 1, 2, 3, 5]


def test_only_new_words_within_reach_are_shown_and_never_names() -> None:
    line = line_of(
        *known(30),
        facts("next-band", level=3),
        facts("too-rare", level=5),
        facts("off-list", level=None),
        facts("Zhang", level=3, is_name=True),
    )
    assert shown([line]) == [["next-band"]]
    # without the cap: every new word, but still no names
    assert shown([line], common_only=False) == [["next-band", "too-rare", "off-list"]]


def test_the_most_heard_then_the_commonest_words_win_the_places() -> None:
    line = line_of(
        *known(20),
        facts("rarer", level=3, rank=4000),
        facts("commoner", level=3, rank=900),
        facts("heard-often", level=3, rank=8000),
    )
    assert shown([line]) == [["commoner"]]  # 23 words: room for 1
    assert shown([line], heard={"heard-often": 7}) == [["heard-often"]]


def test_at_most_two_per_line_and_each_word_once() -> None:
    a, b, c = (facts(n, level=3, rank=r) for n, r in (("a", 1), ("b", 2), ("c", 3)))
    first = line_of(*known(40), a, b, c)
    second = line_of(*known(40), a, c)
    assert shown([first, second]) == [["a", "b"], ["c"]]


def test_a_word_set_new_by_the_learner_shows_even_if_easy() -> None:
    easy = facts("easy-but-new", level=1)
    result = unfamiliar_words(
        [line_of(*known(5), easy)],
        lambda f: estimated_status(f, None if f == easy else CURVE),
        CURVE,
        lambda entry_id: 0,
        True,
    )
    assert [w.entry.entry_id for w in result[0]] == [EntryId("test:easy-but-new")]


def test_word_introductions_are_kept_as_off_and_common_words_only() -> None:
    """Learning's three choices (polyglotic-hq 262) and the two settings
    that keep them: off wins, and keeps the cap for coming back."""
    of = WordIntroductions.of
    assert of(False, True) is WordIntroductions.A_FEW
    assert of(False, False) is WordIntroductions.EVERY
    assert of(True, True) is of(True, False) is WordIntroductions.OFF
    for choice in WordIntroductions:
        assert of(choice.off, choice.common_only) is choice
    assert WordIntroductions.OFF.common_only  # back on: a few
