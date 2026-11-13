"""Words by language (polyglotic-hq 250, the user's F23): a section per
language learned. With one, simply open - the page as it was; with several,
each opens and closes under a heading with its count, and stays as the
learner left it, between runs. Made-up learning, kept in memory; offscreen."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from tests.lexicon.sample import chinese_sample, english_sample
from tests.ui.fakes import MemorySettingsStore, tools_for

from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary
from polyglotic_desktop.core.lexicon.english import EnglishDictionary
from polyglotic_desktop.ui.learning import LearningTools
from polyglotic_desktop.ui_next.views.words import LanguageGroup, language_groups
from polyglotic_desktop.ui_next.words_page import (
    OPEN_KEY,
    OpenLanguages,
    WordsPage,
    heading,
)


@pytest.fixture(autouse=True)
def windows_deleted(qapp: QApplication) -> Iterator[None]:
    before = set(QApplication.topLevelWidgets())
    yield
    for widget in QApplication.topLevelWidgets():
        if widget not in before:
            widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def settle() -> None:
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


# -- the sections, as plain Python ------------------------------------------------------


def test_one_language_is_simply_open() -> None:
    assert language_groups(["zh"], {"zh": False}) == [LanguageGroup("zh", True, False)]


def test_several_open_and_close_the_first_open_to_start_with() -> None:
    assert language_groups(["zh", "en"], {}) == [
        LanguageGroup("zh", True, True),
        LanguageGroup("en", False, True),
    ]


def test_several_stay_as_the_learner_left_them() -> None:
    assert language_groups(["zh", "en"], {"zh": False, "en": True}) == [
        LanguageGroup("zh", False, True),
        LanguageGroup("en", True, True),
    ]


# -- the page --------------------------------------------------------------------------


def chinese() -> LearningTools:
    tools = tools_for(ChineseDictionary(chinese_sample()), "hsk-2025")
    tools.vocabulary.caption_finished("c1", tools.words_in("我的电脑"), False)
    return tools


def english() -> LearningTools:
    tools = tools_for(EnglishDictionary(english_sample()), "en-frequency")
    tools.vocabulary.caption_finished("c1", tools.words_in("she runs"), False)
    return tools


def shown(learners: list[LearningTools], opened: OpenLanguages) -> WordsPage:
    page = WordsPage(learners, None, opened=opened)
    page.resize(900, 700)
    page.show()
    settle()
    return page


def test_with_one_language_the_page_has_no_heading_and_is_open(
    qapp: QApplication,
) -> None:
    page = shown([chinese()], OpenLanguages())
    (section,) = page.sections
    assert not section.heading.isVisible()
    assert section.words.isVisible() and page.first.words.isVisible()


def test_each_language_has_a_heading_with_its_count_and_opens_and_closes(
    qapp: QApplication,
) -> None:
    zh, en = chinese(), english()
    page = shown([zh, en], OpenLanguages())
    first, second = page.sections
    assert first.heading.isVisible() and second.heading.isVisible()
    assert first.words.isVisible() and not second.words.isVisible()
    met = page.first.heard.words_met
    assert met > 0 and first.heading.text() == f"▾  {heading('zh', met)}"
    assert heading("zh", 1) == "Chinese · 1 word met"
    assert heading("en", 2) == "English · 2 words met"
    second.heading.click()  # opened: its words show, counted
    settle()
    assert second.words.isVisible()
    assert second.heading.text().startswith("▾  English · ")
    assert (
        page.languages[1].hearing.isVisible()
        or page.languages[1].hearing_empty.isVisible()
    )
    first.heading.click()  # closed
    settle()
    assert not first.words.isVisible() and first.heading.text().startswith("▸  ")


def test_the_open_state_is_kept_for_next_time(qapp: QApplication) -> None:
    store = MemorySettingsStore({"learning": "zh"})
    page = shown([chinese(), english()], OpenLanguages(store))
    page.sections[0].heading.click()  # Chinese closed
    page.sections[1].heading.click()  # English opened
    assert store.values[OPEN_KEY] == {"zh": False, "en": True}
    assert store.values["learning"] == "zh"  # the other settings kept
    page.close()
    again = shown([chinese(), english()], OpenLanguages(store))
    assert not again.sections[0].words.isVisible()
    assert again.sections[1].words.isVisible()


def test_a_closed_language_refreshes_when_opened(qapp: QApplication) -> None:
    """Words heard while it's closed show when it's opened (it isn't
    refreshed while hidden)."""
    zh, en = chinese(), english()
    page = shown([zh, en], OpenLanguages())
    english_words = page.languages[1]
    en.changed.connect(english_words.learning_changed)
    page.sections[1].heading.click()  # opened: counted
    settle()
    before = english_words.heard.words_met
    page.sections[1].heading.click()  # closed again
    settle()
    en.vocabulary.caption_finished("c2", en.words_in("they keep running"), False)
    settle()
    assert english_words.heard.words_met == before  # not while it's closed
    page.sections[1].heading.click()
    settle()
    assert english_words.heard.words_met == len(en.vocabulary.met_words()) > before
    assert (
        page.sections[1]
        .heading.text()
        .endswith(f"{english_words.heard.words_met} words met")
    )
