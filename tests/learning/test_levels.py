"""The level as a curve, and statuses estimated from it (project 019's
recommendation, agreed for the MVP 2026-11-04)."""

from tests.learning.fakes import facts

from polyglotic_desktop.core.learning.levels import KNOWN_AT, LevelCurve
from polyglotic_desktop.core.learning.statuses import (
    StatusRecord,
    StatusSource,
    estimated_status,
    status_of,
)
from polyglotic_desktop.core.shared import Level, WordStatus


def test_a_picked_level_counts_words_at_or_below_it_as_known() -> None:
    curve = LevelCurve.picked(Level("hsk-2025", 4))
    assert curve == LevelCurve("hsk-2025", 4.5)
    assert curve.picked_level == 4
    assert [curve.estimates_known(level) for level in range(1, 8)] == [
        True, True, True, True, False, False, False,
    ]  # fmt: skip
    assert not curve.estimates_known(None)  # not on the HSK lists


def test_the_chance_of_knowing_a_word_falls_along_the_curve() -> None:
    curve = LevelCurve("en-frequency", 3.5)
    chances = [curve.chance_known(level) for level in range(1, 8)]
    assert chances == sorted(chances, reverse=True)
    assert abs(curve.chance_known(3.5) - 0.5) < 1e-9
    assert curve.chance_known(3) > KNOWN_AT > curve.chance_known(4)


def test_just_starting_knows_nothing_yet() -> None:
    curve = LevelCurve.picked(Level("hsk-2025", 0))
    assert curve.picked_level == 0
    assert not curve.estimates_known(1)


def test_common_words_reach_about_one_band_above_the_level() -> None:
    curve = LevelCurve.picked(Level("hsk-2025", 2))
    assert [curve.within_reach(level) for level in (1, 2, 3, 4, None)] == [
        True, True, True, False, False,
    ]  # fmt: skip


def test_default_statuses_are_computed_from_the_curve() -> None:
    curve = LevelCurve.picked(Level("hsk-2025", 3))
    assert estimated_status(facts("easy", level=2), curve) is WordStatus.KNOWN
    assert estimated_status(facts("hard", level=5), curve) is WordStatus.NEW
    assert estimated_status(facts("off-list", level=None), curve) is WordStatus.NEW
    assert estimated_status(facts("Beijing", is_name=True), curve) is WordStatus.IGNORED
    # before the learner picks a level, everything is new
    assert estimated_status(facts("easy", level=1), None) is WordStatus.NEW


def test_an_explicit_status_wins_over_the_estimate() -> None:
    curve = LevelCurve.picked(Level("hsk-2025", 6))
    easy = facts("easy", level=1)
    explicit = StatusRecord(WordStatus.LEARNING, StatusSource.LEARNER)
    assert status_of(easy, explicit, curve) is explicit
    estimated = status_of(easy, None, curve)
    assert estimated == StatusRecord(WordStatus.KNOWN, StatusSource.ESTIMATED)
    assert not estimated.is_learners_own and explicit.is_learners_own
