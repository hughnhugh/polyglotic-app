"""Caption display rules: what an overlay shows for a caption, and where
captions go - the rules, out of Qt, so they can be tested.

From the proof of concept's `ui/overlay.py` (`caption_lines`,
`_first_rewritten`, `_following_top`) and its design notes
(`docs/line-by-line-captions.md`, `docs/word-links.md`):

- **Clause rows.** A caption shows a clause at a time: what was said
  (white - left out if the overlay hides originals and there's a
  translation), then its translation (yellow) into the overlay's target
  language - or, for a clause already in it, into the overlay's **second
  language**. A live caption's last row trails off.
- **Word links** are drawn only on settled clauses, never on a live
  caption's last (its words are still changing); one link - one colour -
  per counterpart, so a word said twice for the same thing shares it;
  "key words" leaves out minor links; if a cap is set, the surest stay,
  key links first; numbered in reading order.
- **Crossfade from the first rewritten row:** rows above it are unchanged
  and stay as they are.
- **One-way layout:** following the live end, no placed caption moves
  down. A caption shrinking leaves space at the bottom; growth uses it
  first; a live caption that has to push leaves headroom to grow into.
- **Quick preview's line** (polyglotic-hq project 064; 049's wireframes,
  3.2): with the preview on, a live caption is provisional - what was
  said, with its translation under it once the server sends one
  (polyglotic-hq 268, DECISIONS.md #101), but no word links (the overlay
  also draws it dim and italic, with no marks) - until its finished
  caption replaces it.
- **The listening mark** (every caption timing: polyglotic-hq 260):
  shown from the moment a source's speech is under way until its
  finished caption arrives - a live update, Quick preview's line among
  them, doesn't end it (`ListeningMark`).

The overlay draws what these return; nothing here knows Qt.
"""

import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from polyglotic_desktop.core.listening.captions import Language, WordLink
from polyglotic_desktop.core.listening.history import Caption
from polyglotic_desktop.core.listening.sources import SourceId

LIVE_TRAIL = " …"
"""How a live caption's last row ends: the speech is still going on."""


class RowKind(StrEnum):
    ORIGINAL = "original"  # white: what was said, in its own language
    TRANSLATION = "translation"  # yellow: always a translation


class WordLinks(StrEnum):
    """How word links are shown (a setting)."""

    OFF = "off"
    HOVER = "hover"  # only for the word pointed at
    COLOURS = "colours"  # linked words underlined in the same colour
    ARROWS = "arrows"  # and joined by curves between the rows


class LinkDetail(StrEnum):
    """Which word links are shown (a setting)."""

    KEY = "key"  # key links only: content words
    MOST = "most"  # minor links too: pronouns, 是, 这个 and the like


class LinkLine(StrEnum):
    """How thick a word link's underline is (a setting; the user's
    rehearsal feedback F14, polyglotic-hq 249)."""

    THIN = "thin"
    MEDIUM = "medium"
    THICK = "thick"


class LinkGap(StrEnum):
    """How far below the text - below its descenders - a word link's
    underline is (a setting, F14)."""

    CLOSE = "close"
    MEDIUM = "medium"
    FAR = "far"


@dataclass(frozen=True, slots=True)
class DisplayOptions:
    """The settings that change what an overlay's rows say."""

    show_original: bool = True
    word_links: WordLinks = WordLinks.OFF
    link_detail: LinkDetail = LinkDetail.MOST
    max_links: int | None = None  # per clause; None: every link (for now)
    preview: bool = False  # live captions are Quick preview's provisional line


@dataclass(frozen=True, slots=True)
class LinkedWords:
    """Words of a row - `text[start:end]` - linked to words of the other
    row of its clause. `link` numbers the link within the clause, in
    reading order; the overlay colours it by number."""

    start: int
    end: int
    link: int


@dataclass(frozen=True, slots=True)
class CaptionRow:
    """One row an overlay shows for a caption. `clause` is the clause it
    shows; `starts_clause` is true for the first row of the clause's pair.
    `language` is the row's language (for its font), None if unknown."""

    text: str
    kind: RowKind
    language: Language | None
    clause: int
    starts_clause: bool
    links: tuple[LinkedWords, ...] = ()


def caption_rows(
    caption: Caption,
    target: Language,
    second: Language | None,
    options: DisplayOptions,
) -> list[CaptionRow]:
    """The rows `target`'s overlay shows for `caption`: a clause at a time,
    so a clause whose words didn't change keeps its rows."""
    provisional = caption.live and options.preview  # Quick preview's line
    linking = (
        options.word_links is not WordLinks.OFF
        and options.show_original
        and not provisional
    )
    rows: list[CaptionRow] = []
    last = len(caption.clauses) - 1
    for n, clause in enumerate(caption.clauses):
        language = target
        translation = clause.translations.get(target) or None
        if translation is None and second is not None and second != target:
            translation = clause.translations.get(second) or None
            language = second
        settled = not (caption.live and n == last)
        original_links: tuple[LinkedWords, ...] = ()
        translation_links: tuple[LinkedWords, ...] = ()
        if linking and translation is not None and settled:
            original_links, translation_links = numbered_links(
                clause.links.get(language, ()),
                options.link_detail,
                options.max_links,
                len(clause.original),
                len(translation),
            )
        starts = True
        if translation is None or options.show_original:
            rows.append(
                CaptionRow(
                    clause.original,
                    RowKind.ORIGINAL,
                    caption.language,
                    n,
                    starts,
                    original_links,
                )
            )
            starts = False
        if translation is not None:
            rows.append(
                CaptionRow(
                    translation,
                    RowKind.TRANSLATION,
                    language,
                    n,
                    starts,
                    translation_links,
                )
            )
    if caption.live and rows:
        end = rows[-1]
        rows[-1] = CaptionRow(
            end.text + LIVE_TRAIL,
            end.kind,
            end.language,
            end.clause,
            end.starts_clause,
            end.links,
        )
    return rows


def numbered_links(
    links: Sequence[WordLink],
    detail: LinkDetail,
    cap: int | None = None,
    original_length: int | None = None,
    translation_length: int | None = None,
) -> tuple[tuple[LinkedWords, ...], tuple[LinkedWords, ...]]:
    """A clause's word links as (words in the original, words in the
    translation), each numbered by link. One link per counterpart in the
    translation: original words that say the same thing share it (a word
    said twice). "Key words" leaves out minor links. With `cap`, the
    surest stay - key links first. Numbered in reading order of the
    original. Spans outside the texts' lengths, if given, are dropped."""
    groups: dict[tuple[int, int], tuple[list[tuple[int, int]], bool, float]] = {}
    for link in links:
        if detail is LinkDetail.KEY and not link.key:
            continue
        if not (
            _fits(link.original, original_length)
            and _fits(link.translation, translation_length)
        ):
            continue
        spans, key, confidence = groups.get(link.translation, ([], False, 0.0))
        spans.append(link.original)
        groups[link.translation] = (
            spans,
            key or link.key,
            max(confidence, link.confidence),
        )
    kept = sorted(groups.items(), key=lambda g: (not g[1][1], -g[1][2]))
    if cap is not None:
        kept = kept[:cap]
    kept.sort(key=lambda g: min(g[1][0]))
    original = sorted(
        (
            LinkedWords(a, b, number)
            for number, (_, (spans, _, _)) in enumerate(kept)
            for a, b in spans
        ),
        key=lambda w: (w.start, w.end),
    )
    translation = sorted(
        (LinkedWords(c, d, number) for number, ((c, d), _) in enumerate(kept)),
        key=lambda w: (w.start, w.end),
    )
    return tuple(original), tuple(translation)


def _fits(span: tuple[int, int], length: int | None) -> bool:
    start, end = span
    return 0 <= start < end and (length is None or end <= length)


def clause_versions(caption: Caption, clause: int) -> dict[str, str]:
    """A clause in every language it's shown in - what was said first,
    then its translations - by language code: the lookup context's
    versions for a word in one of its rows."""
    shown = caption.clauses[clause]
    versions = {str(caption.language or ""): shown.original}
    versions.update({str(k): v for k, v in shown.translations.items() if v})
    return versions


def first_rewritten(old: Sequence[str], new: Sequence[str]) -> int | None:
    """The index of the first row of `new` that rewrites its row in `old`
    rather than only growing it (a live caption's last row) - `len(new)`
    if only rows at the end went - or None if nothing was rewritten. The
    overlay crossfades from there down; the rows above stay as they are."""
    for i, (a, b) in enumerate(zip(old, new, strict=False)):
        grew = i == len(old) - 1 and b.startswith(a.removesuffix(LIVE_TRAIL))
        if a != b and not grew:
            return i
    return len(new) if len(new) < len(old) else None


@dataclass(frozen=True, slots=True)
class Placed:
    """A caption in an overlay's stack: its height, and where its top was
    placed last (None if it's arriving)."""

    height: float
    top: float | None


def stack_height(items: Sequence[Placed], gap: float) -> float:
    return sum(i.height for i in items) + gap * max(0, len(items) - 1)


def following_top(
    items: Sequence[Placed],
    canvas_height: float,
    gap: float,
    last_is_live: bool,
    headroom: float,
    reanchor: bool,
) -> float:
    """Where the top of the stack goes while following the live end: as
    low as it can be while it fits on the canvas and no caption already
    placed moves down (the one-way layout). So a caption shrinking - the
    finished pass merging rows, a caption withdrawn - doesn't pull the
    ones above down: those below move up, and space is left at the
    bottom. A caption growing pushes the ones above up - or first grows
    into that space. A live caption at the bottom that has to push
    leaves `headroom` spare to grow into, so the stack steps up now and
    then rather than with every update. `reanchor`: settle at the bottom
    afresh (after a resize, a restyle or scrolling back)."""
    bottom = canvas_height - stack_height(items, gap)
    if reanchor or not items:
        return bottom
    placed = math.inf  # the lowest top that moves no placed caption down
    offset = 0.0
    for item in items:
        if item.top is not None:
            placed = min(placed, item.top - offset)
        offset += item.height + gap
    if placed <= bottom:
        return placed
    if last_is_live:
        return bottom - headroom
    return bottom


MARK_WAIT_SEC = 3.0
"""Once speech stops, the listening mark waits at most this long for its
caption (the server takes a second or so; none comes for speech too short
to send, mic bleed, or speech lost)."""


@dataclass(slots=True)
class _Heard:
    seen: float  # when its speech was last seen under way
    stopped: float | None = None  # when it was first seen stopped
    answered: float = -math.inf  # when a caption from it last arrived


class ListeningMark:
    """When the overlays show the listening mark - the quiet sign that
    speech is being heard, so the wait for a finished caption (in Steady
    a median ~3.6s from the first word) reads as "coming", not "broken"
    (polyglotic-hq project 049's wireframes, 3.2). It never shows text.
    In every caption timing, for the mic's speech as for an app's (260,
    the user's F33: "a loading bar whilst there is speech being recorded
    / processed either through my own mic or others").

    Shown from the moment a source's speech is under way until a finished
    caption from that source arrives after the speech stopped, or
    MARK_WAIT_SEC if none does. `heard` is fed which sources are under
    way, every so often; `captioned` each finished or withdrawn caption -
    never a live update: Quick preview's line and Live updates' rewrites
    come while the speech is still being finished. Times are on one
    clock, in seconds; nothing here reads one."""

    def __init__(self) -> None:
        self._heard: dict[SourceId, _Heard] = {}

    def heard(self, under_way: Collection[SourceId], at: float) -> None:
        """The sources whose speech is under way at `at`."""
        for source_id in under_way:
            found = self._heard.get(source_id)
            if found is None:
                self._heard[source_id] = _Heard(at)
            else:
                found.seen, found.stopped = at, None
        for source_id, found in list(self._heard.items()):
            if source_id in under_way or found.stopped is not None:
                continue
            if found.answered > found.seen:
                # its caption came before the speech was seen to stop
                del self._heard[source_id]
            else:
                found.stopped = at

    def captioned(self, source_id: SourceId, at: float) -> None:
        """A finished caption (or a withdrawal) from `source_id` arrived."""
        found = self._heard.get(source_id)
        if found is None:
            return
        if found.stopped is not None:
            del self._heard[source_id]
        else:
            found.answered = at

    def speaking(self) -> bool:
        """Whether any source's speech is under way - heard, and not seen to
        stop since: a caption arriving now has another on its way (the
        caption window's arrival slides quicker; polyglotic-hq 267)."""
        return any(found.stopped is None for found in self._heard.values())

    def showing(self, at: float) -> bool:
        for source_id, found in list(self._heard.items()):
            if found.stopped is not None and at - found.stopped > MARK_WAIT_SEC:
                del self._heard[source_id]
        return bool(self._heard)
