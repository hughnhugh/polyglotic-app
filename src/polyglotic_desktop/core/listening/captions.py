"""Caption updates: what the server says about a caption, as plain values.

A caption is one stretch of speech as shown - its clauses, each with the
original, its translations and word links - updated in place until it is
finished (glossary). The server sends a caption update each time it
changes: a live update while the speech goes on, the finished caption at
the pause, or a withdrawal. `connection` builds these from protocol.md's
`caption_update` messages; the caption display (D1) and caption history
build on them. They carry caption text: never log them.

Joined captions: a finished update can `replace` other captions (normally
the live caption that had started after a short pause); those are then
gone, and this caption takes in their speech. A caption id can be finished
more than once, only through a join; the latest finished wins.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NewType

from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.core.listening.timing import CaptionId, WithdrawalReason

Language = NewType("Language", str)
"""A language code, lower case: `en`, `zh`, `yue`, `zh-hant` (protocol.md)."""


class CaptionKind(StrEnum):
    """What a caption update says: the caption so far, the whole caption at
    the pause, or that it was taken back."""

    LIVE = "live"
    FINISHED = "finished"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class WordLink:
    """Words in a clause and its translation that say the same thing.

    `original` and `translation` are character spans, `[start, end)` in
    code points (Python string indices), within the clause's original and
    its translation. A key link joins content words; a minor one, pronouns
    and the like. `confidence` is from 0 to 1."""

    original: tuple[int, int]
    translation: tuple[int, int]
    key: bool
    confidence: float


@dataclass(frozen=True, slots=True)
class Clause:
    """A sentence, or a long-enough piece ending at a comma: the unit of
    translation and an overlay row. `translations` and `links` are by
    target language; a target can be missing (a translation still on its
    way, or the clause already in that language)."""

    original: str
    translations: Mapping[Language, str] = field(default_factory=dict)
    links: Mapping[Language, tuple[WordLink, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpeechTimes:
    """When the speech a caption update answers was said and sent, and when
    the answer came - seconds on the app's monotonic clock (polyglotic-hq
    271: each caption's delay, `core.listening.delays`)."""

    speech_start: float
    speech_end: float
    sent: float
    received: float


@dataclass(frozen=True, slots=True)
class CaptionUpdate:
    """A caption update from the server.

    Live and finished updates carry the caption's clauses as they now
    stand, its language and every language heard in it (a mixed-language
    caption). A withdrawn update carries only its reason - None if the
    server gave one this app doesn't know. `replaces` lists the captions
    this one takes the place of (a joined caption). `processing_ms` is the
    server's time for this update. `times`: its speech's times, added by
    the session when it sent that speech itself (None otherwise)."""

    caption_id: CaptionId
    source_id: SourceId
    kind: CaptionKind
    clauses: tuple[Clause, ...] = ()
    language: Language | None = None
    languages_heard: tuple[Language, ...] = ()
    replaces: tuple[CaptionId, ...] = ()
    reason: WithdrawalReason | None = None
    processing_ms: int | None = None
    times: SpeechTimes | None = None
