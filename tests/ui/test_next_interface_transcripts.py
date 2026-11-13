"""The transcript windows under the developer switch (`main.wire_transcripts`):
Open transcript and the tray open them, captions reach them, and their
commands are today's."""

from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication
from tests.ui.fakes import FakeAppList, MemorySettingsStore
from tests.ui_next.made_up import finished_updates

from polyglotic_desktop.core.listening.sources import MIC, SourceId
from polyglotic_desktop.core.listening.timing import CaptionMode
from polyglotic_desktop.main import (
    Panels,
    follow_transcripts,
    wire_caption_windows,
    wire_transcripts,
)
from polyglotic_desktop.ui.app import ConnectionState, DesktopApp
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.panels import LanguagesPanel, LookPanel, TimingPanel
from polyglotic_desktop.ui_next.transcripts import Transcripts
from polyglotic_desktop.ui_next.views.placement import Rect

APP_1 = SourceId("app-1")
KEY = "Web Browser"


@pytest.fixture
def switched(qapp: QApplication) -> Iterator[tuple[DesktopApp, Transcripts]]:
    store = MemorySettingsStore({"apps": [KEY], "targets": ["en"]})
    desktop = DesktopApp(store, None, FakeAppList())
    areas = [Rect(0, 0, 1920, 1040)]
    windows = CaptionWindows(store, MIC, lambda: areas)
    transcripts = Transcripts(windows, store, areas=lambda: areas)
    wire_caption_windows(windows, desktop, lambda: None)
    wire_transcripts(transcripts, desktop)
    windows.set_captioned([(KEY, APP_1)])
    yield desktop, transcripts
    transcripts.close()
    windows.close()
    desktop.close()


def test_open_transcript_opens_its_window(
    switched: tuple[DesktopApp, Transcripts],
) -> None:
    _, transcripts = switched
    transcripts.windows.windows[KEY].controls["transcript"].trigger()
    assert transcripts.shown[KEY].isVisible()


def test_the_tray_has_a_transcript_per_app_captioned(
    switched: tuple[DesktopApp, Transcripts],
) -> None:
    desktop, transcripts = switched
    menu = desktop.tray_menu
    entries = [a.menu() for a in menu.actions() if a.menu() is not None]
    # dictation's language is the tray's other menu (polyglotic-hq 283)
    assert entries == [desktop.dictation_language_menu, transcripts.menu]
    names = [a.text() for a in transcripts.menu.actions()]
    assert names == [KEY]
    transcripts.menu.actions()[0].trigger()
    assert transcripts.shown[KEY].isVisible()
    order = [a.text() for a in menu.actions()]
    assert order.index("Transcript") < order.index("Report a problem…")


def test_the_tray_and_a_transcript_take_the_apps_name_once_its_source_is_found(
    switched: tuple[DesktopApp, Transcripts],
) -> None:
    """At every start the windows open before capture finds the apps: the
    caption windows took the app's name then (141), but the tray's
    Transcript menu kept the file name ("vlc.exe") until a setting changed
    (polyglotic-hq 184)."""
    desktop, transcripts = switched
    transcripts.show(KEY)
    desktop.set_app_sources({APP_1: (KEY, "Browser")})
    assert [a.text() for a in transcripts.menu.actions()] == ["Browser"]
    shown = transcripts.shown[KEY]
    assert shown.label.name == "Browser"
    assert shown.windowTitle() == "Browser - Transcript"


def test_captions_reach_its_transcript_with_the_window_closed(
    switched: tuple[DesktopApp, Transcripts],
) -> None:
    desktop, transcripts = switched
    for update in finished_updates(3, source=APP_1):
        desktop.feed.apply(update)
    assert len(transcripts.transcripts[KEY].lines) == 3


def test_its_commands_are_today_s(
    switched: tuple[DesktopApp, Transcripts],
) -> None:
    desktop, transcripts = switched
    transcripts.show(KEY)
    shown = transcripts.shown[KEY]
    shown.timing_wanted.emit(CaptionMode.LIVE.value)
    assert desktop.settings.value.caption_mode is CaptionMode.LIVE
    transcripts.windows.set_timing(CaptionMode.LIVE)  # as main's settings_changed does
    follow_transcripts(transcripts)
    assert shown.buttons["timing"].text() == "Live updates ▾"
    update = finished_updates(1, source=APP_1)[0]
    desktop.feed.apply(update)
    shown.looks_wrong.emit(str(update.caption_id))  # today's comparison card
    card = desktop.looks_wrong.card
    assert card is not None and card.isVisible()
    card.close()
    desktop.pause.setChecked(True)
    assert shown.notice.text() == "Paused"
    desktop.pause.setChecked(False)
    desktop.set_connection(ConnectionState.WAITING, 5.0)
    assert shown.notice.text() == "Reconnecting"


def test_its_rail_shows_the_session_s_panels(
    switched: tuple[DesktopApp, Transcripts],
) -> None:
    desktop, transcripts = switched
    transcripts.panels = Panels(desktop.settings, transcripts.windows)
    transcripts.show(KEY)
    shown = transcripts.shown[KEY]
    shown.animate = False
    shown.toggle_rail()
    languages, timing, look = shown.rail.panels
    assert isinstance(languages, LanguagesPanel)
    assert isinstance(timing, TimingPanel) and isinstance(look, LookPanel)
    languages.spoken.choose("zh")  # a change in the rail: today's setting
    assert desktop.settings.value.spoken_language == "zh"
    follow_transcripts(transcripts)  # the window theme, today's
    assert shown.theme == transcripts.theme
