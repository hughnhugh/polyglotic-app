"""The Learning page (polyglotic-hq 262; 248's IA.md section 3; the user's
F19, F29, F30): a card per language - its tier, its level, what it can do
now - Learn another language, Word introductions with the three choices
and what each does. Offscreen."""

from collections.abc import Iterator

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from polyglotic_desktop.core.learning.highlights import WordIntroductions
from polyglotic_desktop.core.learning.languages import LearningLanguages, Tier
from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.ui_next.learning_page import (
    LearningPage,
    introductions_line,
    learnable,
)
from polyglotic_desktop.ui_next.views.learning import LanguageCard, cards, offered

HSK4 = LevelCurve("hsk-2025", 4.5)
MADE: list[LearningPage] = []
"""The pages a test made, deleted at its end (`deleted`)."""


@pytest.fixture(autouse=True)
def deleted() -> Iterator[None]:
    """Each page deleted when its test ends, not at the interpreter's exit,
    where one left over crashes the run after every test passed (261's
    finding; here too: the run exited 127)."""
    yield
    while MADE:
        made = MADE.pop()
        if shiboken6.isValid(made):
            made.close()
            shiboken6.delete(made)


def made() -> LearningPage:
    page = LearningPage()
    MADE.append(page)
    return page


def levels(code: str) -> LevelCurve | None:
    return {"zh": HSK4}.get(code)


def test_the_language_in_use_can_change_its_level_now() -> None:
    (chinese,) = cards(LearningLanguages("zh"), "zh", levels)
    assert chinese.main and chinese.running and chinese.can_change_level
    assert not chinese.can_switch and not chinese.starts_next
    assert chinese.level is not None and chinese.level.level == "4"


def test_another_full_dictionary_can_be_used_instead_from_the_next_start() -> None:
    chinese, english = cards(LearningLanguages("zh", ("en",)), "zh", levels)
    assert english.can_switch and not english.can_change_level
    assert english.level is not None and not english.level.picked  # none kept
    # switched: until the next start, both cards say so
    english, chinese = cards(LearningLanguages("en", ("zh",)), "zh", levels)
    assert (english.code, english.starts_next) == ("en", True)
    assert chinese.stops_next and chinese.can_switch  # "Keep using Chinese"
    assert chinese.can_change_level  # its data still runs until then


def test_basic_and_no_dictionary_cards_say_what_they_can_do() -> None:
    languages = LearningLanguages("zh", ("ja", "th"))
    _, japanese, thai = cards(languages, "zh", levels, ("ja",))
    assert (japanese.tier, japanese.pack_here, japanese.level) == (
        Tier.BASIC,
        True,
        None,
    )
    assert (thai.tier, thai.level, thai.can_switch) == (Tier.NONE, None, False)


def test_learn_another_offers_those_not_learned_in_the_order_given() -> None:
    """No tier first (polyglotic-hq 293: Chinese and English on top made the
    app look as if it were only for them) - each names its tier instead."""
    codes = ["fr", "en", "zh", "yue", "th", "ja", "es", "fr"]
    assert offered(LearningLanguages("zh"), codes) == [
        "fr",
        "en",
        "yue",
        "th",
        "ja",
        "es",
    ]


def test_every_caption_language_can_be_learned_once(qapp: QApplication) -> None:
    found = learnable()
    assert "zh" in found and "zh-hant" not in found and "yue" in found
    assert len(found) == len(set(found)) == 23
    assert found[:3] == ["ar", "yue", "zh"]  # by name: Arabic, Cantonese, Chinese


@pytest.fixture
def page(qapp: QApplication) -> LearningPage:
    page = made()
    languages = LearningLanguages("zh", ("ja",))
    page.show_learning(
        languages,
        cards(languages, "zh", levels),
        WordIntroductions.A_FEW,
        "zh",
    )
    return page


def test_the_cards_say_the_tier_and_the_level(page: LearningPage) -> None:
    assert [c.code for c in page.cards] == ["zh", "ja"]
    chinese, japanese = page.cards
    assert chinese.change_level is not None and chinese.stop is None
    assert japanese.change_level is None and japanese.stop is not None
    assert page.choices.findData("zh") == page.choices.findData("ja") == -1
    assert page.choices.itemData(0) == "ar"  # by name, none pinned (293)
    assert page.choices.itemText(page.choices.findData("en")) == (
        "English - Full dictionary"  # each says its tier instead
    )


def test_learning_another_and_stopping_one_ask_for_the_list(
    page: LearningPage,
) -> None:
    wanted: list[LearningLanguages] = []
    page.languages_wanted.connect(wanted.append)
    page.choices.setCurrentIndex(page.choices.findData("th"))
    assert "no lookups" in page.chosen_gives.text()  # said before it's added
    page.add.click()
    japanese = page.card("ja")
    assert japanese is not None and japanese.stop is not None
    japanese.stop.click()
    assert wanted == [LearningLanguages("zh", ("ja", "th")), LearningLanguages("zh")]


def test_a_double_click_on_learn_it_adds_one_language(page: LearningPage) -> None:
    """Learn it's list moves on to the next language once one is added, so
    a double-click's second click added that one too - English, then
    Japanese (269). The page is told the new list at once, as `main` does."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    def apply(languages: LearningLanguages) -> None:
        page.show_learning(
            languages, cards(languages, "zh", levels), WordIntroductions.A_FEW, "zh"
        )

    wanted: list[LearningLanguages] = []
    page.languages_wanted.connect(wanted.append)
    page.languages_wanted.connect(apply)
    page.choices.setCurrentIndex(page.choices.findData("en"))
    page.add.click()
    page.add.click()  # the second click of a double-click, the mouse not moved
    assert wanted == [LearningLanguages("zh", ("ja", "en"))]
    # once added, none is chosen (293): Learn it waits for the next choice
    assert page.choices.currentIndex() == -1 and not page.add.isEnabled()
    page.choices.setCurrentIndex(page.choices.findData("fr"))
    QTest.keyClick(page.add, Qt.Key.Key_Space)  # a keyboard has no double-click
    assert len(wanted) == 2


def test_word_introductions_are_chosen_and_explained(page: LearningPage) -> None:
    chosen: list[object] = []
    page.introductions_chosen.connect(chosen.append)
    assert page.introductions.value() is WordIntroductions.A_FEW
    page.introductions.choose(WordIntroductions.OFF)
    assert chosen == [WordIntroductions.OFF]
    off = introductions_line(WordIntroductions.OFF)
    assert page.introductions_said.text() == off
    assert page.sample.choice is WordIntroductions.OFF


def test_with_nothing_learned_it_says_so(qapp: QApplication) -> None:
    page = made()
    page.show_learning(LearningLanguages(), (), WordIntroductions.A_FEW)
    assert page.cards == [] and not page.none_yet.isHidden()
    assert page.choices.itemData(0) == "ar"  # by name: Arabic (293)
    assert page.choices.currentIndex() == -1  # none suggested: "Choose a language"
    assert not page.add.isEnabled()


def test_a_card_has_its_parent_before_it_shows(qapp: QApplication) -> None:
    page = made()
    card = LanguageCard("zh", Tier.FULL, main=True, running=True)
    page.show_learning(LearningLanguages("zh"), (card,), WordIntroductions.EVERY)
    assert all(c.parent() is not None for c in page.cards)


def test_the_same_again_rebuilds_nothing(page: LearningPage) -> None:
    """`main` shows the page again on any change of setting: the cards stay
    as they are unless something they show changed."""
    before = list(page.cards)
    languages = LearningLanguages("zh", ("ja",))
    shown = cards(languages, "zh", levels)
    page.show_learning(languages, shown, WordIntroductions.A_FEW, "zh")
    assert page.cards == before
    page.show_learning(languages, shown, WordIntroductions.EVERY, "zh")
    assert page.introductions.value() is WordIntroductions.EVERY
