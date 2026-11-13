"""When the app updates itself (decision 0017).

The rules (polyglotic-hq ENGINEERING.md, "Releases"; project 032's
checklist for D5, item 9):
- **Look early and quietly:** at start, before the rest of the app is
  built, and every few hours while it runs; download in the background.
- **Apply at the next start, never mid-capture:** the installer applies a
  newer downloaded version when the app next starts. Nothing restarts the
  app by itself while it runs, except -
- **`update_required` goes straight to the updater:** the server has
  refused this version, so no captions can come until it's updated:
  download if needed and restart into it now. What it found
  (`UpdateNow`) tells the learner what to do while there's nothing to
  restart into (polyglotic-hq 137).
- **Follow the channel the server names** (`welcome.channel`) when it's one
  this app knows; **a lower version only when changing channel**
  (`AllowVersionDowngrade` nowhere else). The installer doesn't apply a
  lower version by itself at start, so a downgrade applies as the app
  exits.
- **A downloaded update is offered, never forced** (polyglotic-hq 299;
  the user, 2026-11-13: "Updates should happen automatically and pop up
  to install it"): "Version X is ready", with what's new in two lines
  (`whats_new`), Restart now and Later - where the learner looks, never
  over what they're doing (`RestartOffer`). Restart now applies it as the
  app quits and starts the new version (`restart_when_quitting`); Later
  stops the asking until the next start, which installs it anyway. What a
  look found (`Found`) is what Settings says.
- **The Microsoft Store's copy updates through the Store** (decision
  0056): the app looks for nothing and downloads nothing - the Store
  installs each new package - and "update required" tells the learner to
  get it from the Store.

No I/O here: `Updates` asks the `Updater` port, on whatever thread `main`
gives it - one at a time.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from polyglotic_desktop.ports.updates import (
    DownloadFailed,
    FeedUnreachable,
    Update,
    Updater,
)

CHANNELS = ("win-x64-alpha", "win-x64-beta", "win-x64-stable")
"""The update channels (protocol.md): names fixed once testers install."""

CHECK_EVERY_HOURS = 6


class UpdateNow(StrEnum):
    """What `update_now` found - what the learner is told while the server
    refuses this version."""

    RESTARTING = "restarting"
    """Downloaded: the app restarts into it now."""
    DOWNLOADED = "downloaded"
    """Downloaded, but not restarted into: it installs at the next start."""
    NONE_YET = "none_yet"
    """Nothing newer on the feed yet, or the feed couldn't be reached."""
    NOT_INSTALLED = "not_installed"
    """Not installed by the installer: this copy can't update itself."""
    FROM_STORE = "from_store"
    """The Microsoft Store's copy: the Store updates it, and the learner can
    ask it to now."""


class Found(StrEnum):
    """What a look for an update found - what Settings says of it."""

    UP_TO_DATE = "up_to_date"
    """Nothing newer on the feed."""
    READY = "ready"
    """Downloaded: it installs at the next start, or now with a restart."""
    NO_FEED = "no_feed"
    """The feed couldn't be read (no internet, the address down) or
    trusted: it's looked at again later."""
    NOT_DOWNLOADED = "not_downloaded"
    """Found, but the download failed: tried again at the next look."""
    NOT_INSTALLED = "not_installed"
    """Not installed by the installer: this copy can't update itself."""


@dataclass(frozen=True, slots=True)
class UpdateCheck:
    """Where to look: `channel` None for the one this copy came from; a
    lower version allowed only when changing channel."""

    channel: str | None = None
    allow_downgrade: bool = False


def check_for(installed_channel: str, server_channel: str | None) -> UpdateCheck:
    """The installed channel, unless the server names another channel this
    app knows - then that one, and its newest release even if lower. A
    channel this app doesn't know is ignored (protocol.md's versioning rule
    1)."""
    if server_channel in CHANNELS and server_channel != installed_channel:
        return UpdateCheck(server_channel, allow_downgrade=True)
    return UpdateCheck()


class Updates:
    """This copy's updates: what to look for, what's downloaded, when it
    applies."""

    def __init__(self, updater: Updater | None, installed_channel: str) -> None:
        """`updater` None: the Microsoft Store's copy, which the Store
        updates - nothing here looks, downloads or applies."""
        self._updater = updater
        self._installed_channel = installed_channel
        self._server_channel: str | None = None
        self.downloaded: Update | None = None
        self._restart = False

    @property
    def wanted(self) -> UpdateCheck:
        return check_for(self._installed_channel, self._server_channel)

    def follow(self, server_channel: str | None) -> bool:
        """The channel the server's `welcome` named. True if that changes
        where to look (check again then)."""
        before = self.wanted
        self._server_channel = server_channel
        return self._updater is not None and self.wanted != before

    def check(self) -> Update | None:
        """Looks for an update and downloads it, to apply at the next
        start. Returns what's downloaded (None: nothing to update to, or
        not installed by the installer)."""
        if self._updater is None or not self._updater.installed():
            return None
        wanted = self.wanted
        update = self._updater.find(wanted.channel, wanted.allow_downgrade)
        if update is None:
            return None
        if update != self.downloaded:
            self._updater.download(update)
            self.downloaded = update
        return update

    def look(self) -> Found:
        """`check`, saying what it found: a feed that can't be read and a
        download that fails are outcomes here, not errors - the app looks
        again later. Anything else the updater raises is raised."""
        if self._updater is None or not self._updater.installed():
            return Found.NOT_INSTALLED
        try:
            update = self.check()
        except FeedUnreachable:
            return Found.NO_FEED
        except DownloadFailed:
            return Found.NOT_DOWNLOADED
        return Found.UP_TO_DATE if update is None else Found.READY

    def restart_when_quitting(self) -> Update | None:
        """The learner chose Restart now: what's downloaded applies as the
        app quits, and the new version starts. Returns it (None: nothing to
        restart into - the app then just quits)."""
        self._restart = self.downloaded is not None
        return self.downloaded

    def update_now(self) -> UpdateNow:
        """The server needs a newer app (`update_required`): download what
        the feed has and restart into it. Says what it found when there's
        nothing to restart into - not installed, or no newer release on the
        feed yet. A failure to download or restart raises; `downloaded`
        then says whether the next start installs one."""
        if self._updater is None:
            return UpdateNow.FROM_STORE
        if not self._updater.installed():
            return UpdateNow.NOT_INSTALLED
        update = self.check()
        if update is None:
            return UpdateNow.NONE_YET
        self._updater.restart_into(update)
        return UpdateNow.RESTARTING

    def at_exit(self) -> None:
        """The app is quitting. After Restart now, what's downloaded applies
        and the new version starts; otherwise a downloaded downgrade (a
        change of channel) applies now, since the next start won't apply
        it, and a newer version is left for the next start."""
        if self._updater is None or self.downloaded is None:
            return
        if self._restart:
            self._updater.apply_at_exit(self.downloaded, restart=True)
        elif self.downloaded.downgrade:
            self._updater.apply_at_exit(self.downloaded)


class RestartOffer:
    """Whether the learner is asked to restart into a downloaded update
    (polyglotic-hq 299): asked once one is ready; after Later, not again
    until the next start - whatever the looks every few hours find, a newer
    version included. It never restarts the app itself: only the learner's
    Restart now does, so captions and dictation are never cut off."""

    def __init__(self) -> None:
        self.ready: Update | None = None
        """The update downloaded, ready to restart into."""
        self._later = False

    def found(self, update: Update | None) -> bool:
        """A look's update (None: nothing downloaded). True if what's
        asked changed."""
        before = self.asking
        self.ready = update
        return self.asking != before

    def later(self) -> None:
        """Later: not asked again until the next start."""
        self._later = True

    @property
    def asking(self) -> Update | None:
        """The update the learner is asked to restart into, if any."""
        return None if self._later else self.ready


WHATS_NEW_LINES = 2
WHATS_NEW_CHARS = 110
"""What's new in the offer: the notes' first lines, each one sentence cut
to about this long."""

_ITEM = re.compile(r"^\s*[-*] (?P<text>.*)$")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKS = re.compile(r"\*\*|__|`")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")


def whats_new(
    notes: str, lines: int = WHATS_NEW_LINES, chars: int = WHATS_NEW_CHARS
) -> tuple[str, ...]:
    """What's new, from a release's notes (RELEASE-NOTES.md's section, as
    Markdown): the first `lines` items - New before Better and Fixed, as
    the file has them - each in plain text: its first sentence, cut at a
    word to at most `chars`, with an ellipsis. () when there are none."""
    items: list[list[str]] = []
    for line in notes.splitlines():
        found = _ITEM.match(line)
        if found:
            items.append([found["text"].strip()])
        elif items and line[:1] in (" ", "\t") and line.strip():
            items[-1].append(line.strip())  # the item goes on
    said = []
    for item in items[:lines]:
        text = _MARKS.sub("", _LINK.sub(r"\1", " ".join(item)))
        text = _SENTENCE_END.split(text, maxsplit=1)[0].strip()
        if len(text) > chars:
            text = text[: chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
        said.append(text)
    return tuple(said)
