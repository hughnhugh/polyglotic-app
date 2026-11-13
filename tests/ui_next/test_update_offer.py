"""A downloaded update offered where the learner looks (polyglotic-hq 299),
offscreen: "Version X is ready. Restart to install it." with what's new in
two lines, Restart now and Later on Home; the tray's line; what Settings
says each look found. Later asks again only at the next start; nothing
restarts the app but the learner's Restart now."""

import shiboken6
from PySide6.QtWidgets import QApplication, QPushButton
from tests.releases.test_updates import FakeUpdater
from tests.ui.fakes import FakeAppList, MemorySettingsStore
from tests.ui.test_main_updates import settle, wait_for
from tests.ui_next.test_account_settings_help import (  # noqa: F401 - its fixture
    settings_deleted,
    settings_page,
)
from tests.ui_next.test_home import home

from polyglotic_desktop.core.releases.updates import Found, UpdateCheck, Updates
from polyglotic_desktop.main import BackgroundUpdates, UpdateShown
from polyglotic_desktop.ports.updates import Update
from polyglotic_desktop.ui.app import DesktopApp
from polyglotic_desktop.ui_next.views.home import Picker

ALPHA = "win-x64-alpha"
NOTES = (
    "### New\n\n"
    "- Hear a word: the speaker on a word's card says it aloud. More slowly\n"
    "  on the next click.\n"
    "- Text size: Settings > App > Text size.\n"
    "- A third line, not shown.\n"
)
READY = Update("0.2.0", notes=NOTES)


def button(rig: "Rig", name: str) -> QPushButton:
    found = rig.home.findChild(QPushButton, name)
    assert found is not None, name
    return found


class Rig:
    def __init__(self) -> None:
        self.home, _ = home(Picker())
        self.desktop = DesktopApp(MemorySettingsStore(), None, FakeAppList())
        self.settings, _keys = settings_page()
        self.restarts = 0
        self.shown = UpdateShown(self.home, self.desktop, self.settings, self._restart)

    def _restart(self) -> None:
        self.restarts += 1

    def found(self, found: Found, downloaded: Update | None) -> None:
        self.shown.found(found, downloaded)  # as from the updates' thread
        QApplication.processEvents()

    def close(self) -> None:
        self.desktop.close()
        self.home.close()
        shiboken6.delete(self.home)
        shiboken6.delete(self.desktop)  # the offer with it; Settings: its fixture


def test_a_downloaded_update_is_offered_on_home_in_the_tray_and_in_settings(
    qapp: QApplication,
) -> None:
    rig = Rig()
    try:
        rig.found(Found.UP_TO_DATE, None)
        assert rig.home.update_card.isHidden()
        assert not rig.desktop.install_update.isVisible()
        assert rig.settings.update_found.text() == "Polyglotic is up to date."
        assert rig.settings.restart_now.isHidden()

        rig.found(Found.READY, READY)
        assert not rig.home.update_card.isHidden()
        assert rig.home.update_title.text() == (
            "Version 0.2.0 is ready. Restart to install it."
        )
        assert [line.text() for line in rig.home.whats_new] == [
            "• Hear a word: the speaker on a word's card says it aloud.",
            "• Text size: Settings > App > Text size.",
        ]
        assert rig.desktop.install_update.isVisible()
        assert rig.desktop.install_update.text() == "Restart to install version 0.2.0"
        assert rig.settings.update_found.text() == (
            "Version 0.2.0 is ready. Restart to install it."
        )
        assert not rig.settings.restart_now.isHidden()
    finally:
        rig.close()


def test_restart_now_from_home_the_tray_or_settings_restarts(
    qapp: QApplication,
) -> None:
    rig = Rig()
    try:
        rig.found(Found.READY, READY)
        button(rig, "home.update.restart").click()
        rig.desktop.install_update.trigger()
        rig.settings.restart_now.click()
        assert rig.restarts == 3
    finally:
        rig.close()


def test_later_asks_again_only_at_the_next_start(qapp: QApplication) -> None:
    """Later hides Home's card for this run: the next looks - every few
    hours - find it, or a newer one, and Home doesn't ask again. The tray's
    line stays, quietly, for whoever wants it now."""
    rig = Rig()
    try:
        rig.found(Found.READY, READY)
        button(rig, "home.update.later").click()
        assert rig.home.update_card.isHidden()
        rig.found(Found.READY, READY)  # the next look
        rig.found(Found.READY, Update("0.3.0"))  # and a newer one
        assert rig.home.update_card.isHidden()
        assert rig.desktop.install_update.text() == "Restart to install version 0.3.0"
        assert rig.restarts == 0  # nothing restarts by itself
    finally:
        rig.close()


def test_settings_say_why_there_is_nothing_to_install(qapp: QApplication) -> None:
    """A feed out of reach and a failed download: said in Settings, and
    nothing offered on Home - the next look tries again."""
    rig = Rig()
    try:
        rig.settings.update_now.click()
        assert rig.settings.update_found.text() == "Checking for updates…"
        rig.found(Found.NO_FEED, None)
        assert rig.settings.update_found.text().startswith(
            "Couldn't reach the update server."
        )
        rig.found(Found.NOT_DOWNLOADED, None)
        assert rig.settings.update_found.text().startswith(
            "The update couldn't be downloaded."
        )
        assert rig.home.update_card.isHidden()
        assert not rig.desktop.install_update.isVisible()
        # one downloaded earlier stays ready, whatever a later look found
        rig.found(Found.NO_FEED, READY)
        assert rig.settings.update_found.text().startswith("Version 0.2.0 is ready")
    finally:
        rig.close()


def test_the_first_look_reaches_the_interface_built_after_it(
    qapp: QApplication,
) -> None:
    """The first look runs before the interface exists: its outcome is
    told to the listener as soon as there is one."""
    updater = FakeUpdater({UpdateCheck(): READY})
    updates = BackgroundUpdates(Updates(updater, ALPHA))
    updates.check()
    settle(updates)
    told: list[tuple[Found, Update | None]] = []
    updates.tell(lambda found, update: told.append((found, update)))
    assert told == [(Found.READY, READY)]
    updates.check()
    settle(updates)
    assert told[-1] == (Found.READY, READY) and len(told) == 2


def test_restart_now_applies_it_as_the_app_quits(qapp: QApplication) -> None:
    """main's Restart now: what's downloaded applies once the app has quit,
    and the new version starts - before the usual at-exit step."""
    updater = FakeUpdater({UpdateCheck(): READY})
    updates = BackgroundUpdates(Updates(updater, ALPHA))
    updates.check()
    updates.restart_when_quitting()
    updates.at_exit()
    wait_for(lambda: updater.calls[-1].startswith("apply"))
    assert updater.calls == [
        "find None False",
        "download 0.2.0",
        "apply at exit 0.2.0 and start",
    ]
