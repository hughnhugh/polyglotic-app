"""The updater on Velopack (decision 0017): the feed's address checked, the
options passed for a change of channel, and - for real - nothing to update
when run from source."""

from pathlib import Path
from typing import Any, ClassVar

import pytest

from polyglotic_desktop.adapters import velopack_updates
from polyglotic_desktop.adapters.velopack_updates import (
    VelopackUpdater,
    feed_source,
    run_installer_hooks,
)
from polyglotic_desktop.ports.updates import DownloadFailed, FeedUnreachable, Update

FEED = "https://updates.example.org/"


def test_the_feed_is_https_or_a_folder_on_this_pc(tmp_path: Path) -> None:
    assert feed_source("https://updates.example.org") == FEED
    assert feed_source(FEED) == FEED
    assert feed_source(str(tmp_path)) == str(tmp_path.resolve())


@pytest.mark.parametrize(
    "address",
    [
        "http://updates.example.org/",  # anyone on the network could swap it
        "ftp://updates.example.org/",
        "https://",
        "C:/no/such/folder/anywhere",
    ],
)
def test_any_other_feed_is_refused(address: str) -> None:
    with pytest.raises(ValueError):
        feed_source(address)


def test_from_source_nothing_is_installed_and_the_hooks_return() -> None:
    """The real Velopack, from pytest's Python: no install to find."""
    run_installer_hooks()  # returns: not started by the installer
    assert VelopackUpdater(FEED).installed() is False


class FakeAsset:
    def __init__(self, version: str, notes: str = "") -> None:
        self.Version = version
        self.NotesMarkdown = notes


class FakeInfo:
    def __init__(self, version: str, downgrade: bool, notes: str = "") -> None:
        self.TargetFullRelease = FakeAsset(version, notes)
        self.IsDowngrade = downgrade


class FakeManager:
    made: ClassVar[list["FakeManager"]] = []
    feed: ClassVar[dict[str | None, FakeInfo]] = {}
    fails: ClassVar[str] = ""
    """"check" or "download": that call raises, as Velopack's do."""

    def __init__(self, source: str, options: Any) -> None:
        self.source, self.options = source, options
        self.calls: list[str] = []
        FakeManager.made.append(self)

    def check_for_updates(self) -> FakeInfo | None:
        if self.fails == "check":
            raise OSError("the feed's address didn't answer")
        return self.feed.get(self.options.ExplicitChannel)

    def download_updates(self, info: FakeInfo) -> None:
        if self.fails == "download":
            raise RuntimeError("the package's SHA-256 didn't match")
        self.calls.append(f"download {info.TargetFullRelease.Version}")

    def wait_exit_then_apply_updates(
        self, info: FakeInfo, silent: bool, restart: bool
    ) -> None:
        version = info.TargetFullRelease.Version
        self.calls.append(f"at exit {version} silent={silent} restart={restart}")

    def apply_updates_and_restart(self, info: FakeInfo) -> None:
        self.calls.append(f"restart {info.TargetFullRelease.Version}")


@pytest.fixture
def fake_velopack(monkeypatch: pytest.MonkeyPatch) -> type[FakeManager]:
    FakeManager.made = []
    FakeManager.feed = {}
    FakeManager.fails = ""
    monkeypatch.setattr(velopack_updates.velopack, "UpdateManager", FakeManager)
    return FakeManager


def test_a_newer_release_is_found_downloaded_and_restarted_into(
    fake_velopack: type[FakeManager],
) -> None:
    fake_velopack.feed = {None: FakeInfo("0.2.0", False)}
    updater = VelopackUpdater("https://updates.example.org")

    assert updater.installed() is True
    update = updater.find(None, False)
    assert update == Update("0.2.0")
    updater.download(update)
    updater.restart_into(update)

    (manager,) = fake_velopack.made
    assert manager.source == FEED
    assert manager.options.ExplicitChannel is None
    assert manager.options.AllowVersionDowngrade is False
    assert manager.calls == ["download 0.2.0", "restart 0.2.0"]


def test_a_change_of_channel_allows_a_downgrade_applied_at_exit(
    fake_velopack: type[FakeManager],
) -> None:
    fake_velopack.feed = {"win-x64-beta": FakeInfo("0.1.0", True)}
    updater = VelopackUpdater(FEED)

    assert updater.find(None, False) is None
    update = updater.find("win-x64-beta", True)
    assert update == Update("0.1.0", downgrade=True)
    updater.download(update)
    updater.apply_at_exit(update)

    usual, switching = fake_velopack.made
    assert usual.options.ExplicitChannel is None
    assert usual.options.AllowVersionDowngrade is False
    assert switching.options.ExplicitChannel == "win-x64-beta"
    assert switching.options.AllowVersionDowngrade is True
    assert switching.calls == [
        "download 0.1.0",
        "at exit 0.1.0 silent=True restart=False",
    ]


def test_restart_now_applies_as_the_app_quits_then_starts_it(
    fake_velopack: type[FakeManager],
) -> None:
    """The learner's Restart now (polyglotic-hq 299): applied once the app
    has quit - its own quit, so everything is saved - and started again."""
    fake_velopack.feed = {None: FakeInfo("0.2.0", False, "### New\n\n- A thing.")}
    updater = VelopackUpdater(FEED)
    update = updater.find(None, False)
    assert update is not None and update.notes == "### New\n\n- A thing."
    updater.download(update)
    updater.apply_at_exit(update, restart=True)
    (manager,) = fake_velopack.made
    assert manager.calls == ["download 0.2.0", "at exit 0.2.0 silent=True restart=True"]


def test_a_feed_that_cant_be_read_and_a_failed_download_say_which(
    fake_velopack: type[FakeManager],
) -> None:
    """The port's errors, so Settings can say which went wrong (299)."""
    fake_velopack.feed = {None: FakeInfo("0.2.0", False)}
    updater = VelopackUpdater(FEED)
    fake_velopack.fails = "check"
    with pytest.raises(FeedUnreachable) as raised:
        updater.find(None, False)
    assert isinstance(raised.value.__cause__, OSError)
    fake_velopack.fails = "download"
    update = updater.find(None, False)
    assert update is not None
    with pytest.raises(DownloadFailed):
        updater.download(update)


def test_with_a_signed_feed_velopack_reads_only_the_checked_folder(
    fake_velopack: type[FakeManager], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 0019: the feed is checked first (refresh), then Velopack is
    pointed at the checked folder, full packages only."""
    from nacl.signing import SigningKey
    from tests.test_signed_feed import public

    from polyglotic_desktop.adapters.signed_feed import FeedNotTrusted, VerifiedFeed

    refreshed: list[tuple[str, str, bool]] = []

    def refresh(
        self: VerifiedFeed, channel: str, version: str, switching: bool
    ) -> Path:
        refreshed.append((channel, version, switching))
        return self.folder_for(channel)

    monkeypatch.setattr(VerifiedFeed, "refresh", refresh)
    fake_velopack.feed = {"win-x64-beta": FakeInfo("0.1.0", True)}
    key = public(SigningKey.generate())
    updater = VelopackUpdater(FEED, (key,), "win-x64-alpha", "0.2.0", tmp_path)

    assert updater.find(None, False) is None
    assert updater.find("win-x64-beta", True) == Update("0.1.0", downgrade=True)

    assert refreshed == [
        ("win-x64-alpha", "0.2.0", False),
        ("win-x64-beta", "0.2.0", True),
    ]
    usual, switching = fake_velopack.made
    assert usual.source == str(tmp_path / "win-x64-alpha")
    assert switching.source == str(tmp_path / "win-x64-beta")
    assert usual.options.MaximumDeltasBeforeFallback == -1

    def refuse(self: VerifiedFeed, channel: str, version: str, switching: bool) -> Path:
        raise FeedNotTrusted("no key we trust signed this feed")

    monkeypatch.setattr(VerifiedFeed, "refresh", refuse)
    with pytest.raises(FeedUnreachable) as raised:  # a feed not trusted isn't read
        updater.find(None, False)
    assert isinstance(raised.value.__cause__, FeedNotTrusted)


def test_a_signed_feed_must_be_https(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        VelopackUpdater(str(tmp_path), ("AAAA",), "win-x64-alpha", "0.1.0", tmp_path)
