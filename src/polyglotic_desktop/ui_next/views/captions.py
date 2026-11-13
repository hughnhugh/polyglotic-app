"""One app's captions as its caption window or transcript shows them: what
was said and its translation into one language - or no translation
("captions only").

Each app captioned (a source) gets a caption window and a transcript of
its own, each with the original and one translation (polyglotic-hq
DECISIONS.md #53); the user's own speech (the mic, "You") can show in it
too, so a view takes one or more sources (the user, 2026-11-07).
`CaptionLines` keeps those sources' captions in a caption history of its
own - so a transcript holds its 1,000 lines, not the session's last 300
across every app - and turns each into a `Line`: the rows core's display
rules give it (`core.listening.display`), in the language chosen. With
no language chosen a clause is its original row alone - no translation
row, not an empty one. A line is rebuilt only when its caption changes,
or the language or display options do; the text size changes no rows.

Above each caption a small line can say where it came from and the
language spoken ("Discord  Mandarin", "You"): `Labels`, in the source's
colour - the user's own always, the others' with "show the source" on.

`revision` goes up on anything that changes what shows; the widget
drawing the view repaints then. Where it's scrolled to is `scroll`.

Holds caption text: never log it. Not thread-safe - one thread (the
interface's).
"""

import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from polyglotic_desktop.core.listening.captions import (
    CaptionUpdate,
    Clause,
    Language,
)
from polyglotic_desktop.core.listening.delays import CaptionDelay, delay
from polyglotic_desktop.core.listening.display import (
    CaptionRow,
    DisplayOptions,
    caption_rows,
)
from polyglotic_desktop.core.listening.history import Caption, CaptionHistory
from polyglotic_desktop.core.listening.sources import SourceId, SourceLabel
from polyglotic_desktop.core.listening.timing import CaptionId
from polyglotic_desktop.ui_next.views.scroll import Scroll

DELAYS_KEPT = 512
"""Captions whose delay a view remembers (live ones never finished go too)."""

CAPTION_WINDOW_LINES = 150

"""Lines a caption window keeps to scroll back through (as today's overlay)."""

TRANSCRIPT_LINES = 1_000
"""Lines a transcript lists - laid out, searched and scrolled through; the
surfaces' budgets hold at this many."""

SESSION_LINES = 50_000
"""Lines a transcript keeps for Copy all and Save: the whole session (a
film, a long call) - about two days of constant speech - kept as text
beyond the `TRANSCRIPT_LINES` it lists (polyglotic-hq 137). The cap only
keeps an app left captioning for days from growing without end."""

TEXT_SIZES = (0.7, 2.0)
"""The smallest and largest text size, as a scale of the base size (as
today's setting)."""


_NO_TRANSLATION = Language("")
"""A target no clause is translated into: core's rules then show each
clause's original alone (captions only)."""

_NO_ID = CaptionId("")
_YOU = SourceLabel("You", "#7c9cff")
"""The user's own mic's label unless named: blue, as "You" always was."""


@dataclass(frozen=True, slots=True)
class Line:
    """A caption as a surface shows it. `key` stays the same through the
    caption's updates and joins (the caption history's), so a surface
    keeps what it laid out until `rows` change. `by_you`: from the user's
    own mic ("You"). `provisional`: Quick preview's line - drawn dim and
    italic until its finished caption. `label`: the small line above it
    (`Labels`), in `label_color` ("#rrggbb"); empty for none. `heard`: the
    languages spoken in it; `checked`: the best model's version, which the
    learner said is right ("Looks wrong?") - a transcript says both."""

    key: int
    source: SourceId
    by_you: bool
    rows: tuple[CaptionRow, ...]
    live: bool
    provisional: bool
    started_at: datetime
    caption_id: CaptionId = _NO_ID
    label: str = ""
    label_color: str = ""
    heard: tuple[Language, ...] = ()
    checked: bool = False


@dataclass(frozen=True)
class Labels:
    """What the small line above each caption says: its source's name, in
    its colour (`sources`; on this PC only) - always for the user's own
    ("You", `you`), for the others with `show_source` - and the language
    spoken, with `show_language` (`spoken` names it: "Mandarin",
    "Mandarin + English"); and, with `delay`, how long the caption took to
    show (`delay` says it: polyglotic-hq 271, off unless the learner asks)."""

    sources: Mapping[SourceId, SourceLabel] = field(default_factory=dict)
    show_source: bool = False
    show_language: bool = False
    you: SourceLabel = _YOU
    spoken: Callable[[Sequence[Language]], str] | None = None
    delay: Callable[[CaptionDelay], str] | None = None

    def of(self, caption: Caption, took: CaptionDelay | None = None) -> tuple[str, str]:
        """The label's text and colour for `caption`; `took`: its delay, if
        known."""
        parts = []
        color = ""
        source = self.sources.get(caption.source_id)
        if source is None and caption.by_you:
            source = self.you
        if source is not None and (self.show_source or caption.by_you):
            parts.append(source.name)
            color = source.color
        heard = caption.languages_heard or (
            (caption.language,) if caption.language else ()
        )
        if self.show_language and heard and self.spoken is not None:
            parts.append(self.spoken(heard))
        if self.delay is not None and took is not None:
            parts.append(self.delay(took))
        return "  ".join(parts), color


class CaptionLines:
    """Some sources' captions - an app's, and the user's own if shown - as
    lines in one translation language, or none."""

    def __init__(
        self,
        sources: Collection[SourceId],
        target: Language | None,
        *,
        keep: int,
        keep_earlier: int = 0,
        second: Language | None = None,
        options: DisplayOptions | None = None,
        yours: Collection[SourceId] = (),
        text_size: float = 1.0,
        labels: Labels | None = None,
        finished_only: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """`sources`: whose captions show. `target`: the one translation
        shown, None for captions only. `keep`: lines kept, oldest dropped
        first (`CAPTION_WINDOW_LINES`, `TRANSCRIPT_LINES`); `keep_earlier`:
        finished captions dropped from those kept as text in `earlier`
        (`SESSION_LINES`, a transcript's). `second`: the
        language shown for a clause already in `target`. `yours`: the
        sources that are the user's own mic. `finished_only`: no line for a
        caption still being spoken (a transcript's). `clock`: when captions
        arrive - by default now (the lab's made-up times are the same every
        run)."""
        self.sources = frozenset(sources)
        self.keep = keep
        """Lines kept: no surface shows more of this view's than these."""
        self._finished_only = finished_only
        self.scroll = Scroll()
        self.revision = 0
        self._history = (
            CaptionHistory(yours, clock, max_captions=keep, keep_earlier=keep_earlier)
            if clock is not None
            else CaptionHistory(yours, max_captions=keep, keep_earlier=keep_earlier)
        )
        self._target = target
        self._second = second
        self._options = options or DisplayOptions()
        self._labels = labels or Labels()
        self._text_size = _clamped(text_size)
        self._lines: tuple[Line, ...] = ()
        self._built: dict[int, tuple[Caption, Line]] = {}
        self._delays: dict[CaptionId, CaptionDelay] = {}
        """How long each caption's latest update took to show - its own
        speech's only (`CaptionUpdate.times`); the newest `DELAYS_KEPT`."""
        self._history_version = self._history.version

    # -- what shows -----------------------------------------------------------------

    @property
    def lines(self) -> tuple[Line, ...]:
        """The lines, oldest first (in key order)."""
        return self._lines

    def caption(self, key: int) -> Caption | None:
        """The caption a line shows, by the line's key: its clauses in every
        language, for a lookup's context line."""
        found = self._built.get(key)
        return found[0] if found else None

    @property
    def target(self) -> Language | None:
        """The one translation shown; None: captions only."""
        return self._target

    @property
    def text_size(self) -> float:
        return self._text_size

    @property
    def started_at(self) -> datetime:
        """When these lines began to be kept: the listening session's start,
        as far as they're concerned (an SRT's cues are timed from it)."""
        return self._history.started_at

    @property
    def earlier(self) -> Sequence[Caption]:
        """The finished captions kept from before the lines, oldest first
        (with `keep_earlier`): in Copy all and Save, not in the list."""
        return self._history.earlier

    def captions_of(self, lines: Sequence[Line]) -> list[Caption]:
        """The captions `lines` show, in their order (for copying and saving
        them: every language they hold)."""
        return [self._built[line.key][0] for line in lines if line.key in self._built]

    # -- from the session ----------------------------------------------------------

    def apply(self, update: CaptionUpdate) -> bool:
        """A caption update; True if what shows changed. Other sources'
        updates are ignored."""
        if update.source_id not in self.sources:
            return False
        took = delay(update, time.perf_counter())
        if took is not None:  # before the line is built: its label says it
            self._delays[update.caption_id] = took
            while len(self._delays) > DELAYS_KEPT:
                del self._delays[next(iter(self._delays))]
        self._history.apply(update)
        return self._history_changed()

    def use_checked(
        self,
        caption_id: CaptionId,
        clauses: tuple[Clause, ...],
        language: Language | None,
        languages_heard: tuple[Language, ...],
    ) -> bool:
        """The best model's version of a finished caption, which the
        learner said is right ("Looks wrong?"), in its place."""
        self._history.use_checked(caption_id, clauses, language, languages_heard)
        return self._history_changed()

    # -- the learner's choices -----------------------------------------------------

    def set_language(
        self, target: Language | None, second: Language | None = None
    ) -> None:
        """The one translation shown (None: captions only), and the second
        language."""
        if (target, second) == (self._target, self._second):
            return
        self._target, self._second = target, second
        self._rebuild(everything=True)

    def set_options(self, options: DisplayOptions) -> None:
        if options == self._options:
            return
        self._options = options
        self._rebuild(everything=True)

    def set_labels(self, labels: Labels) -> None:
        """What the line above each caption says."""
        if labels == self._labels:
            return
        self._labels = labels
        self._rebuild(everything=True)

    def show_sources(self, sources: Collection[SourceId]) -> None:
        """Whose captions show from now on (the user's own mic shown or
        not). Lines already kept stay."""
        self.sources = frozenset(sources)

    def set_text_size(self, size: float) -> None:
        """The text size, as a scale of the base size, kept in TEXT_SIZES.
        No line changes; the widget lays out what shows again."""
        size = _clamped(size)
        if size != self._text_size:
            self._text_size = size
            self.revision += 1

    # -- keeping the lines in step ---------------------------------------------------

    def _history_changed(self) -> bool:
        if self._history.version == self._history_version:
            return False
        return self._rebuild(everything=False)

    def _rebuild(self, everything: bool) -> bool:
        """The lines from the history's captions: a caption's line is
        reused while the caption is the same version (and, unless
        `everything`, the language and options are unchanged). False if no
        line changed (a live update, where only finished captions show)."""
        built: dict[int, tuple[Caption, Line]] = {}
        lines = []
        for caption in self._history.captions:
            if self._finished_only and caption.live:
                continue
            found = None if everything else self._built.get(caption.key)
            if found is not None and found[0] is caption:
                line = found[1]
            else:
                line = self._line(caption)
            built[caption.key] = (caption, line)
            lines.append(line)
        self._history_version = self._history.version
        kept = tuple(lines)
        if not everything and _same(kept, self._lines):
            return False
        self._built = built
        self._lines = kept
        self.revision += 1
        return True

    def _line(self, caption: Caption) -> Line:
        if self._target is None:  # captions only: each clause's original
            options = replace(self._options, show_original=True)
            rows = caption_rows(caption, _NO_TRANSLATION, None, options)
        else:
            rows = caption_rows(caption, self._target, self._second, self._options)
        label, color = self._labels.of(caption, self._delays.get(caption.caption_id))
        return Line(
            key=caption.key,
            source=caption.source_id,
            by_you=caption.by_you,
            rows=tuple(rows),
            live=caption.live,
            provisional=caption.live and self._options.preview,
            started_at=caption.started_at,
            caption_id=caption.caption_id,
            label=label,
            label_color=color,
            heard=caption.languages_heard
            or ((caption.language,) if caption.language else ()),
            checked=caption.checked,
        )


def _same(a: tuple[Line, ...], b: tuple[Line, ...]) -> bool:
    """The same lines, each the very same object (none rebuilt)."""
    return len(a) == len(b) and all(x is y for x, y in zip(a, b, strict=True))


def _clamped(size: float) -> float:
    low, high = TEXT_SIZES
    return round(min(high, max(low, size)), 2)
