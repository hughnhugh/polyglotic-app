"""Settings is one page with three sections at its top - Captions ·
Learning · App - and Captions holds every caption window's settings, each
with its line under its name; "Look..." is gone, and a caption window's
"All caption settings..." opens Settings > Captions (polyglotic-hq 248's
sections 2.1-2.4, the user's F11 and F18; 261)."""

from collections.abc import Iterator

import pytest
import shiboken6
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from tests.ui_next.test_caption_window import window_of

from polyglotic_desktop.core.listening.timing import CaptionMode
from polyglotic_desktop.ui_next.controls import Card, Segmented
from polyglotic_desktop.ui_next.main_window import MainWindow
from polyglotic_desktop.ui_next.settings_page import SECTIONS, SettingsPage
from polyglotic_desktop.ui_next.settings_popover import ROWS, WINDOW_ROWS
from polyglotic_desktop.ui_next.views.caption_window import CaptionLook
from polyglotic_desktop.ui_next.views.panels import (
    LanguagesView,
    LookView,
    SessionLanguages,
    Timing,
    TimingView,
)

MADE: list[SettingsPage] = []
"""The pages a test made, deleted after it (`deleted`)."""


@pytest.fixture(autouse=True)
def deleted() -> Iterator[None]:
    """Each page deleted at the end of its test, its panels with it - not
    left to the interpreter's exit, where a page's panels, still bound to
    their views, crashed Linux's run now and then (exit code 134,
    "malloc_consolidate()": #416's first CI run)."""
    yield
    while MADE:
        page = MADE.pop()
        if shiboken6.isValid(page):
            page.close()
            shiboken6.delete(page)


def page_with(
    look: LookView | None = None,
    timing: TimingView | None = None,
    speech: LanguagesView | None = None,
) -> SettingsPage:
    actions = {"L": QAction("Lock all caption windows")}, QAction("Tell us")
    page = SettingsPage(
        [("margin", "Margin")],
        *actions,
        look=look or LookView(CaptionLook()),
        timing=timing or TimingView(Timing()),
        speech=speech or LanguagesView(SessionLanguages()),
    )
    page.keep = actions  # type: ignore[attr-defined]  # alive as long as it
    page.resize(900, 700)
    MADE.append(page)
    return page


def test_three_sections_at_the_top_captions_first(qapp: QApplication) -> None:
    page = page_with()
    page.show()
    qapp.processEvents()
    assert SECTIONS == ("captions", "learning", "app")
    assert [b.text() for b in page.sections.buttons] == ["Captions", "Learning", "App"]
    assert page.sections.value() == "captions"
    shown = [key for key, box in page.section.items() if box.isVisible()]
    assert shown == ["captions"]
    page.sections.choose("app")
    assert [key for key, box in page.section.items() if box.isVisible()] == ["app"]
    assert page.theme.isVisible() and not page.look.isVisible()
    page.show_section("captions")
    assert page.sections.value() == "captions" and page.look.isVisible()
    page.close()


def test_captions_holds_every_caption_setting_in_248s_order(
    qapp: QApplication,
) -> None:
    page = page_with()
    groups: list[Card] = [page.look, page.word_links, page.timing, page.behaviour]
    groups += [page.speech, page.reset]
    titles = [g.title.text() if g.title else "" for g in groups]
    assert titles == ["Look", "Word links", "Timing", "Behaviour", "Speech", "Reset"]
    column = page.section["captions"].layout()
    assert column is not None
    items = [column.itemAt(i) for i in range(column.count())]
    in_order = [item.widget() for item in items if item is not None]
    assert [w for w in in_order if w in groups] == groups


def test_a_change_in_settings_is_the_views_and_every_panel_shows_it(
    qapp: QApplication,
) -> None:
    look = LookView(CaptionLook())
    page, other = page_with(look=look), page_with(look=look)
    page.look.original.click()  # Show the original above the translation
    assert look.value.show_original is False
    assert not other.look.original.isChecked()
    page.word_links.link_detail.choose(page.word_links.link_detail._values[0])
    assert other.word_links.link_detail.value() == look.value.link_detail


def test_translate_live_captions_is_timings_and_only_with_live_updates(
    qapp: QApplication,
) -> None:
    timing = TimingView(Timing(CaptionMode.STEADY))
    speech = LanguagesView(SessionLanguages(translate_live=True))
    page = page_with(timing=timing, speech=speech)
    page.show()
    qapp.processEvents()
    row = page.timing.translate_row
    switch = page.timing.translate_live
    assert row is not None and switch is not None
    assert not row.isVisible()
    timing.set_mode(CaptionMode.LIVE)
    assert row.isVisible() and switch.isChecked()
    switch.click()
    assert speech.value.translate_live is False
    page.close()


def test_the_learning_section_points_to_the_learning_page_and_holds_nothing_of_it(
    qapp: QApplication,
) -> None:
    """What's learned, the level and word introductions are the Learning
    page's (248's section 3.6; polyglotic-hq 262): Settings only points
    there - from its Learning section and from Word links."""
    page = page_with()
    wanted: list[bool] = []
    page.learning_wanted.connect(lambda: wanted.append(True))
    page.open_learning.click()
    link = page.word_links.findChild(QLabel, "look.to_learning")
    assert link is not None and "Learning" in link.text()
    link.linkActivated.emit("learning")
    assert wanted == [True, True]
    learning = page.section["learning"]
    assert not learning.findChildren(Segmented)  # no choices: a way there only
    # nor anywhere else in Settings: both live on Learning now (262)
    assert page.findChild(QWidget, "languages.learning") is None
    assert page.findChild(QWidget, "look.common_words_only") is None


def test_every_caption_setting_has_its_line_and_its_tooltip(qapp: QApplication) -> None:
    """F18: a line under every setting that isn't obvious, and the same on
    hover - 248's section 2.4's copy."""
    page = page_with()
    look = page.look
    assert look.background.toolTip().startswith("0 % is no box at all")
    assert look.colours["translation"].toolTip().startswith("The colour of the trans")
    assert page.behaviour.fade.toolTip().startswith("Captions disappear after")
    assert page.word_links.word_links.toolTip().startswith("Which words of what was")


def test_the_hubs_minimum_is_960_by_680(qapp: QApplication) -> None:
    """248's section 2.1: a bigger Settings (F11) - a section fits without
    scrolling at the common sizes."""
    window = MainWindow(QAction("Quit"))
    assert (window.minimumWidth(), window.minimumHeight()) == (960, 680)
    window.keep_in_tray = False
    window.close()


def test_all_caption_settings_ends_every_windows_popover(qapp: QApplication) -> None:
    """ "Look..." is gone (F11); "All caption settings..." takes its place,
    last, in a window's popover and a joined window's own."""
    assert "look" not in ROWS and ROWS[-1] == "all_settings"
    assert "look" not in WINDOW_ROWS and WINDOW_ROWS[-1] == "all_settings"
    window = window_of(qapp)
    asked: list[bool] = []
    window.all_settings_wanted.connect(lambda: asked.append(True))
    window.hovered = True
    window._show_band(True)
    window.buttons["settings"].click()
    popover = window.popover
    assert popover is not None
    row = popover.rows["all_settings"]
    assert isinstance(row, QPushButton) and row.text() == "All caption settings…"
    row.click()
    assert asked == [True]
    assert "look" not in window.controls
    window.close()


def test_the_popovers_timing_is_one_line_a_shortcut(qapp: QApplication) -> None:
    """248's Q8 A: Timing lives in Settings > Captions; a caption window's
    popover keeps it on one line - the timing now (Steady by default) on a
    chip, its three choices under it only while open."""
    from polyglotic_desktop.core.listening.timing import default_caption_mode

    window = window_of(qapp)
    window.hovered = True
    window._show_band(True)
    window.buttons["settings"].click()
    popover = window.popover
    assert popover is not None
    chip = popover.timing
    assert default_caption_mode() is CaptionMode.STEADY
    window.set_timing(CaptionMode.STEADY)
    assert chip.text().startswith("Steady") and popover.timings.isHidden()
    assert "Settings" in chip.toolTip()
    one_line = popover.rows["timing"].sizeHint().height()
    chip.click()
    assert not popover.timings.isHidden()
    assert popover.rows["timing"].sizeHint().height() > one_line
    live = popover.findChild(QPushButton, "settings_popover.caption_window.live")
    assert live is not None
    live.click()
    assert window.controls["live"].isChecked()
    assert popover.timings.isHidden() and chip.text().startswith("Live updates")
    window.close()


def test_the_apps_language_is_under_the_title_in_every_section(
    qapp: QApplication,
) -> None:
    """The user's live testing (polyglotic-hq 270): "App language should
    also be more obvious rather than hid in 2 layers" - so it's under the
    page's title whichever section shows, each language by its own name,
    the same setting as App's Language (284)."""
    actions = {"L": QAction("Lock all caption windows")}, QAction("Tell us")
    page = SettingsPage(
        [("margin", "Margin")],
        *actions,
        [("en", "English"), ("zh_CN", "简体中文")],
        look=LookView(CaptionLook()),
        timing=TimingView(Timing()),
        speech=LanguagesView(SessionLanguages()),
    )
    page.keep = actions  # type: ignore[attr-defined]
    MADE.append(page)
    page.resize(900, 700)
    page.show()
    qapp.processEvents()
    picker = page.language_picker
    chosen: list[str] = []
    page.interface_language_chosen.connect(chosen.append)
    for section in ("captions", "learning", "app"):
        page.show_section(section)
        assert picker.isVisible()
    assert [picker.itemText(i) for i in range(picker.count())][1:] == [
        "English",
        "简体中文",
    ]
    assert not page.language_later.isVisible()
    picker.setCurrentIndex(2)
    assert chosen == ["zh_CN"]
    assert page.interface_language.currentData() == "zh_CN"  # App's shows it too
    assert page.language_later.isVisible()  # from the next start
    page.interface_language.setCurrentIndex(page.interface_language.findData("en"))
    assert picker.currentData() == "en" and chosen[-1] == "en"
    page.show_interface_language("")
    assert picker.currentIndex() == 0
    assert page.interface_language.currentIndex() == 0
    assert chosen[-1] == "en"  # showing the setting isn't choosing it


def test_a_machine_drafted_language_says_so_and_asks(qapp: QApplication) -> None:
    """polyglotic-hq 294 (decision 0087): the app's text in a language no
    native speaker has checked says it's a machine draft, under the title
    in every section, with "Tell us what reads wrong" - the feedback form."""
    actions = {"L": QAction("Lock all caption windows")}, QAction("Tell us")
    page = SettingsPage(
        [("margin", "Margin")],
        *actions,
        [("de", "Deutsch"), ("en", "English")],
        look=LookView(CaptionLook()),
        timing=TimingView(Timing()),
        speech=LanguagesView(SessionLanguages()),
    )
    page.keep = actions  # type: ignore[attr-defined]
    MADE.append(page)
    page.resize(900, 700)
    page.show()
    qapp.processEvents()
    assert not page.language_draft.isVisible()  # English: not a draft
    page.show_draft(True)
    asked: list[bool] = []
    page.translation_feedback_wanted.connect(lambda: asked.append(True))
    for section in ("captions", "learning", "app"):
        page.show_section(section)
        assert page.language_draft.isVisible() and page.language_wrong.isVisible()
    assert page.language_draft.text() == "Machine draft"
    # on a line of its own under the picker: beside it, a long language's
    # words ran past the page at the Largest text size (294's walk)
    picker = page.language_picker.mapTo(page, page.language_picker.rect().bottomLeft())
    note = page.language_wrong.mapTo(page, page.language_wrong.rect().topLeft())
    assert note.y() >= picker.y()
    page.language_wrong.click()
    assert asked == [True]
