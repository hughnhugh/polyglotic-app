"""The update feed, checked against our own signature before Velopack sees it (decision 0019).

Unsigned, anyone who can write the update storage or the domain's DNS can
serve testers other code (polyglotic-hq project 032, section 2). Signed:
the release workflow signs `releases.<channel>.json` - as the storage
serves it, after Velopack's upload has merged it (decision 0020) - with an
Ed25519 key only it holds, and publishes `releases.<channel>.json.sig`
beside it. What is signed is the channel's name and the feed's exact bytes
(`signed_message`), so one channel's feed can't be served as another's. The
app, with the public keys built in (`main.FEED_KEYS`):
1. fetches the feed and its signature, and refuses the feed unless one of
   the keys signed exactly those bytes for the channel it asked for;
2. downloads the package Velopack would install - the newest full one -
   and refuses it unless its size and SHA-256 are the signed feed's;
3. writes the signed feed beside it in a folder of its own, and Velopack
   reads that folder instead of the network (deltas off: only the full
   package is there).

Someone holding the storage or DNS can then stop updates, never change
them. Two keys may be built in at once, so a new key can be brought in by
a release before the old one is retired. Ed25519 is libsodium's, through
PyNaCl.
"""

import base64
import binascii
import hashlib
import json
import logging
import re
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from polyglotic_desktop.core.shared.client import HEADERS

log = logging.getLogger(__name__)

TIMEOUT_SEC = 60
SIGNATURE_BYTES = 64
FEED_BYTES_MAX = 4_000_000  # a feed is a few KB; anything this big is wrong
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
"""A package's file name in the feed: a bare name, never a path."""


class FeedNotTrusted(Exception):
    """The feed, its signature or a package isn't what we signed. Says
    which check failed, never the contents."""


def public_keys(encoded: Sequence[str]) -> list[VerifyKey]:
    """Ed25519 public keys from their base64 (32 bytes each)."""
    return [VerifyKey(base64.b64decode(key, validate=True)) for key in encoded]


SIGNED_PREFIX = b"Polyglotic update feed 1\n"
"""What every signed message starts with: what it is, and the format's
number - a signature over anything else can't pass for a feed's."""


def signed_message(channel: str, feed: bytes) -> bytes:
    """What the release workflow signs and the app checks for `channel`'s
    feed: the prefix, the channel's name on a line of its own, then the
    feed's exact bytes (decision 0020). A channel's name is a plain name
    (no line breaks), so the message reads back one way only."""
    if not PLAIN_NAME.fullmatch(channel):
        raise ValueError("not a channel name")
    return SIGNED_PREFIX + channel.encode("ascii") + b"\n" + feed


def verify(message: bytes, signature: bytes, keys: Sequence[VerifyKey]) -> None:
    """Nothing if one of `keys` signed exactly `message`; FeedNotTrusted
    otherwise. `signature` is the `.sig` file: base64 of 64 bytes."""
    try:
        raw = base64.b64decode(signature.strip(), validate=True)
    except binascii.Error:
        raise FeedNotTrusted("the signature isn't base64") from None
    if len(raw) != SIGNATURE_BYTES:
        raise FeedNotTrusted("the signature isn't 64 bytes")
    for key in keys:
        try:
            key.verify(message, raw)
            return
        except BadSignatureError:
            continue
    raise FeedNotTrusted("no key we trust signed this feed")


def _version(text: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return None


def _newer(candidate: str, current: str) -> bool:
    """Whether `candidate` is a version Velopack would install over
    `current` without a change of channel: a higher one. The same or a
    lower one (an old feed served again, say) isn't fetched - it would
    never be applied. Versions that can't be read are compared as text."""
    newest, installed = _version(candidate), _version(current)
    if newest is None or installed is None:
        return candidate != current
    return newest > installed


def newest_full_package(feed: bytes) -> dict[str, object]:
    """The asset Velopack would install from this feed: the newest full
    package (FeedNotTrusted if there's none, or its fields are wrong)."""
    try:
        assets = json.loads(feed)["Assets"]
    except (ValueError, KeyError, TypeError):
        raise FeedNotTrusted("the feed can't be read") from None
    full = [
        a
        for a in assets
        if isinstance(a, dict)
        and str(a.get("Type", "")).lower() == "full"
        and _version(str(a.get("Version", ""))) is not None
    ]
    if not full:
        raise FeedNotTrusted("the feed has no full package")
    newest = max(full, key=lambda a: _version(str(a["Version"])) or ())
    name, size, sha256 = (
        newest.get("FileName"),
        newest.get("Size"),
        newest.get("SHA256"),
    )
    if not isinstance(name, str) or not PLAIN_NAME.fullmatch(name) or ".." in name:
        raise FeedNotTrusted("a package's file name isn't a plain name")
    if not isinstance(size, int) or not isinstance(sha256, str):
        raise FeedNotTrusted("a package's size or SHA-256 is missing")
    return newest


def _request(url: str) -> urllib.request.Request:
    """A GET that says who asks (core/shared/client.py: Python's default
    name is refused at Cloudflare's edge)."""
    return urllib.request.Request(url, headers=HEADERS)


def fetch(url: str) -> bytes:
    """A small file (the feed, its signature) over HTTPS - the feed's
    address is checked before this is used."""
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_SEC) as response:
        body: bytes = response.read(FEED_BYTES_MAX + 1)
        return body


def fetch_to(url: str, path: Path, limit: int) -> None:
    """A package, streamed to `path` (tens of MB: never held in memory) - at
    most `limit` bytes of it. The caller passes one more than the signed
    feed's size: a package served longer than that is cut there, so whoever
    holds the storage can't fill the disk, and the size check refuses it."""
    with (
        urllib.request.urlopen(_request(url), timeout=TIMEOUT_SEC) as response,
        path.open("wb") as out,
    ):
        left = limit
        while left > 0 and (block := response.read(min(1 << 20, left))):
            out.write(block)
            left -= len(block)


class VerifiedFeed:
    """The signed feed at `base` (an `https://` address), checked into a
    folder of its own per channel, for Velopack to read."""

    def __init__(
        self,
        base: str,
        keys: Sequence[VerifyKey],
        folder: Path,
        get: Callable[[str], bytes] = fetch,
        get_to: Callable[[str, Path, int], None] = fetch_to,
    ) -> None:
        if not keys:
            raise ValueError("a signed feed needs at least one public key")
        self._base = base if base.endswith("/") else base + "/"
        self._keys = keys
        self._folder = folder
        self._get = get
        self._get_to = get_to

    def refresh(self, channel: str, current_version: str, switching: bool) -> Path:
        """Fetches and checks `channel`'s feed and its newest full package -
        unless that's this version or an older one and the channel isn't
        changing (nothing Velopack would install: then any package checked
        before, installed by now, is removed) - and returns the folder
        Velopack should read. Raises
        FeedNotTrusted, leaving the folder's last checked feed (or none),
        if any check fails."""
        name = f"releases.{channel}.json"
        feed = self._get(self._base + name)
        if len(feed) > FEED_BYTES_MAX:
            raise FeedNotTrusted("the feed is too big")
        signature = self._get(self._base + name + ".sig")
        verify(signed_message(channel, feed), signature, self._keys)
        newest = newest_full_package(feed)
        folder = self.folder_for(channel)
        folder.mkdir(parents=True, exist_ok=True)
        package = folder / str(newest["FileName"])
        wanted = switching or _newer(str(newest["Version"]), current_version)
        if wanted and not self._has(package, newest):
            self._download(package, newest)
        elif not wanted:
            self._remove_packages(folder)
        (folder / name).write_bytes(feed)  # last: only a checked feed is ever there
        log.info("update feed checked: newest %s", newest["Version"])
        return folder

    def folder_for(self, channel: str) -> Path:
        """Where `channel`'s checked feed and package are kept."""
        if not PLAIN_NAME.fullmatch(channel):
            raise ValueError("not a channel name")
        return self._folder / channel

    @staticmethod
    def _has(package: Path, asset: dict[str, object]) -> bool:
        return package.is_file() and _sha256(package) == str(asset["SHA256"]).lower()

    @staticmethod
    def _remove_packages(folder: Path) -> None:
        """Nothing here is wanted: a package checked for an update that has
        since been installed is tens of MB kept for nothing until the next
        release (polyglotic-hq project 042, Low 7). One Windows won't let go
        of yet stays until the next check."""
        for old in [*folder.glob("*.nupkg"), *folder.glob("*.part")]:
            try:
                old.unlink(missing_ok=True)
            except OSError as e:
                log.info("checked package kept for now (%s)", type(e).__name__)
            else:
                log.info("checked package removed: nothing to install")

    def _download(self, package: Path, asset: dict[str, object]) -> None:
        part = package.with_name(package.name + ".part")
        size = int(str(asset["Size"]))
        # one byte more than the feed says: a longer package is cut and refused
        self._get_to(self._base + package.name, part, size + 1)
        if part.stat().st_size != size:
            part.unlink()
            raise FeedNotTrusted("a package isn't the size the feed says")
        if _sha256(part) != str(asset["SHA256"]).lower():
            part.unlink()
            raise FeedNotTrusted("a package isn't the one the feed says")
        part.replace(package)
        for old in package.parent.glob("*.nupkg"):
            if old != package:
                old.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()
