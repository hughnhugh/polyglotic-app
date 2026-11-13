"""What the app tells the server about itself: its version, update channel and Windows.

Sent when redeeming an invite code and in every `hello` (protocol.md).
Never the user's name, the PC's name, or anything about the captioned app.

The version and channel are the release's: the release build writes them
into the app as `release.json` - the version from the git tag (`v0.1.0`
-> `0.1.0`), the channel it was packed for (decision 0015). Run from
source, there's no such file: the app is `0.0.0` on `win-x64-alpha`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import TYPE_CHECKING, get_args

if TYPE_CHECKING:
    # imported at runtime only to read a release stamp: `protocol` brings
    # pydantic (about 0.1 s), which the window needn't wait for (136)
    from polyglotic_desktop.connection.protocol import Channel, Os

log = logging.getLogger(__name__)

RELEASE_FILE = "release.json"
FROM_SOURCE_VERSION = "0.0.0"
FIRST_CHANNEL: Channel = "win-x64-alpha"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
"""protocol.md's versions: `MAJOR.MINOR.PATCH`, no leading zeros."""


@dataclass(frozen=True, slots=True)
class Release:
    """The release this copy of the app is: its version and channel."""

    version: str
    channel: Channel


def read_release(text: str) -> Release:
    """`release.json`'s contents, or ValueError: not a version protocol.md
    accepts, or not a channel it knows."""
    from polyglotic_desktop.connection import protocol

    channels: dict[str, Channel] = {c: c for c in get_args(protocol.Channel)}
    data = json.loads(text)
    fields = data if isinstance(data, dict) else {}
    version = fields.get("version")
    channel = channels.get(str(fields.get("channel")))
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("release.json: the version isn't MAJOR.MINOR.PATCH")
    if channel is None:
        raise ValueError("release.json: not a known channel")
    return Release(version, channel)


def this_release(stamped: Traversable | None = None) -> Release:
    """The release the build stamped into the app; `0.0.0` on the first
    channel when run from source. A stamp that can't be read is logged and
    taken as `0.0.0`, which the server answers with `update_required` - so
    a broken build still updates itself."""
    file = stamped or files("polyglotic_desktop") / RELEASE_FILE
    if not file.is_file():
        return Release(FROM_SOURCE_VERSION, FIRST_CHANNEL)
    try:
        return read_release(file.read_text(encoding="utf-8"))
    except ValueError as e:  # json.JSONDecodeError is a ValueError
        log.error("the release stamp can't be read: %s", e)
        return Release(FROM_SOURCE_VERSION, FIRST_CHANNEL)


@dataclass(frozen=True, slots=True)
class AppInfo:
    app_version: str
    os: Os
    channel: Channel = FIRST_CHANNEL
    os_version: str = ""
    """The OS's version number ("10.0.26200"): feedback carries it; `hello`
    and sign-in don't."""

    @property
    def platform(self) -> str:
        """The app's platform, `os`'s first part (`windows`): all its
        session's summary says about the PC (polyglotic-server's tracking
        plan, 051)."""
        return self.os.split("-", 1)[0]

    @classmethod
    def this_app(cls, os: Os, os_version: str) -> AppInfo:
        """This copy of the app on this OS: its name and version number come
        from the OS's adapters (`main.os_adapters`, decision 0038)."""
        release = this_release()
        return cls(release.version, os, release.channel, os_version)
