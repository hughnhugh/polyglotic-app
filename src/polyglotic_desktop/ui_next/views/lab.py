"""The Lab: experimental caption settings for the user and the testers to
tune by feel (polyglotic-hq 284; the user's live testing, 270's
FEEDBACK.md: "Configurability of settings and modes are particularly
good especially for my own testing and alpha / beta testers ... If there
are things that are obviously bad, we can remove them later").

One value, `CaptionLab`, kept in the look every caption window shares
(`CaptionLook.lab`) and saved as one setting, `caption_lab` - so "Reset
the lab" is one step, and taking a control out later is one field. Every
control applies at once to the running caption windows and the preview.
Its defaults are the app as it is without the lab.

Each slider's ends were found by trying them (284's report says how):
- **New for** (`new_for`): how long a caption stays at full ink after it
  arrives, beside the newest - which always is (`newness`). 0 s is
  today's step (DECISIONS.md #104). Up to `NEW_FOR_RANGE`'s end: past it,
  every caption a default window shows at a typical pace is still "new"
  and the step says nothing.
- **Then** (`new_fade`): it steps back at once, or fades back over
  `FADE_BACK_SEC`.
- **Gap between new captions** (`arrival_gap`): captions arriving
  together are let into a window at least this far apart, in order,
  nothing dropped (`views.pacing`); 0 s is today's.
- **Text still being spoken** (`unfinished`): as now, like finished
  text, dimmer, italic, or in the theme's accent - a provisional line and
  a live caption alike.
- **Underline thickness** (`link_px`): a word link's underline as a
  slider, in place of Word links' three steps while it's set.
- **Spacing** (`row_gap`, `caption_gap`): between a clause and its
  translation, and between captions.
- **The loading sign** (`loading`): the bar, three dots, or an ellipsis
  after the text still being spoken.
- **Older captions** (`older`): how much ink a caption that isn't new
  keeps - what was said; its translation steps back less, in the same
  proportion as today's (`older_translation`). 100 % is no step at all;
  `OLDER_RANGE`'s floor keeps an older line at 3:1 on Classic's panel over
  a light video.

Plain Python, no Qt. Holds no caption text.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from enum import StrEnum

from polyglotic_desktop.ui_next.views.arrivals import (
    OLDER_ALPHA,
    OLDER_TRANSLATION_ALPHA,
)

NEW_FOR_RANGE = (0.0, 8.0)
"""Seconds a caption stays new: 0 is today's (only the newest is). Past
the top, every caption in view is still "new" at a typical pace and the
step says nothing: a default window (960 x 300 at 100 %) shows 3 of the
recorded conversation's captions (measured offscreen, 284: 114 px each),
so at a typical 2.5 s between captions (`arrivals.TYPICAL_GAP_SEC`) the
oldest in view arrived 5 s before the newest; 8 s leaves an older caption
in view in a window twice that height (5 captions, 10 s)."""
NEW_FOR_STEP = 0.5
FADE_BACK_SEC = 1.5
"""A gradual step back takes this long, after the caption's new time: slow
enough to see as a fade, quicker than the next caption at a typical pace."""
OLDER_RANGE = (0.45, 1.0)
"""An older caption's ink, what was said: 100 % is no step back (253's C);
45 % is the least that keeps it at 3:1 - WCAG's floor for large text - on
Classic's panel (72 %) over a light video (#f3f5f7). Below it, older
captions stop being readable on a bright scene (284, computed per preset;
today's 72 % keeps 4.5:1)."""
OLDER_STEP = 0.05
ARRIVAL_GAP_RANGE = (0.0, 1.5)
"""Seconds at least between new captions in a window (`views.pacing`): 0
lets them in as they come (today's). Tried on made-up streams (polyglotic-hq
284's report: 400 captions a gaussian 2.5 s or 1.3 s apart,
three landing together every twelfth, the longest wait 3 s): at 1.5 s a
typical pace keeps the gap for 99 in 100 captions (the wait lets the
rest in) and adds 2.9 s at the 95th percentile; at 2 s the wait lets in 11
in 100 and the gap stops being kept. A fast speaker's captions (1.3 s
apart, 253's recorded conversation) keep it up to 1.0 s (2 in 100 let
in by the wait), 38 in 100 at 1.3 s."""
ARRIVAL_GAP_STEP = 0.1
_TRANSLATION_SHARE = (1.0 - OLDER_TRANSLATION_ALPHA) / (1.0 - OLDER_ALPHA)
"""How much of what was said's step back the translation takes: the yellow
starts darker, so it steps back less (today's 0.72 / 0.82)."""


LINK_PX_RANGE = (1.0, 6.0)
"""A word link's underline, pixels at 21 px text (scaled with it): the
Lab's slider in place of Word links' Thin / Medium / Thick (1.4, 2.2,
3.4 - the user: "Thickness options should be more different"). Tried at
each end in a caption window (284's report has the pictures): at 0.6 px
and 70 % text size the line is drawn at well under half its colour and
the links' colours can't be told apart; at 1 px they can. At 6 px a line
is as heavy as the strokes of the words above it; at 8 it's heavier and
draws the eye off the words."""
LINK_PX_STEP = 0.2
ROW_GAP_RANGE = (0.0, 12.0)
"""Pixels between a clause and its translation, at text size 1.0 (today's
2). 0: the rows' own line spacing alone, which keeps them clear. Tried in
a caption window: at 12 a translation sat nearer the next clause (8 px
below it) than its own original, so the gap between clauses grows with
this one, staying `CLAUSE_MORE` more (`clause_gap`); past 12 a caption of
three clauses no longer fits a default window."""
CLAUSE_MORE = 6.0
CAPTION_GAP_RANGE = (4.0, 40.0)
"""Pixels between one caption and the next, at text size 1.0 (today's
10). Tried in a caption window: at 4 the label above a caption ("Discord
· Mandarin") still parts it from the one before; with no label it reads
as one caption. Past 40 a default window (300 px) shows two of the
recorded conversation's captions, not three."""
SPACING_STEP = 1.0


class Unfinished(StrEnum):
    """How text still being spoken - a provisional line (Steady, Quick
    preview) or a live caption (Live updates) - looks beside finished
    text (the user's live testing, 270's FEEDBACK.md line 20: "Mid
    transcription lines should be visually distinguishable to established
    lines")."""

    AS_NOW = "as_now"
    """Today's: a provisional line dim and italic, a live one a little dim."""
    SAME = "same"
    """Like finished text."""
    DIMMER = "dimmer"
    """Both dim, upright."""
    ITALIC = "italic"
    """Both italic, at full ink."""
    COLOUR = "colour"
    """Both in the theme's accent, readable on the panel."""


class Loading(StrEnum):
    """The sign that speech was heard and its caption is on its way (the
    listening mark; the user's live testing, 270's FEEDBACK.md line 27:
    "The loading bar doesn't look that clean, either the three dots,
    and/or ellipsis on current previewed text")."""

    BAR = "bar"
    """Today's: a bar whose lit part sweeps across it (267)."""
    DOTS = "dots"
    """Three dots, lighting up in turn."""
    ELLIPSIS = "ellipsis"
    """An ellipsis growing after the text still being spoken - or, with
    none yet, where the bar would be."""


class NewFade(StrEnum):
    """How a caption that's no longer new goes to an older caption's ink."""

    INSTANT = "instant"
    GRADUAL = "gradual"


@dataclass(frozen=True, slots=True)
class CaptionLab:
    """The lab's values; the defaults are the app without the lab."""

    new_for: float = 0.0
    new_fade: NewFade = NewFade.INSTANT
    older: float = OLDER_ALPHA
    arrival_gap: float = 0.0
    unfinished: Unfinished = Unfinished.AS_NOW
    link_px: float | None = None
    """None: Word links' Thin / Medium / Thick decides."""
    row_gap: float = 2.0
    caption_gap: float = 10.0
    loading: Loading = Loading.BAR

    def to_stored(self) -> dict[str, object]:
        """Only what differs from the default: an untouched lab stores `{}`,
        so a later default reaches everyone who didn't move it."""
        default = CaptionLab()
        stored: dict[str, object] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value != getattr(default, f.name):
                stored[f.name] = value.value if isinstance(value, StrEnum) else value
        return stored

    @classmethod
    def from_stored(cls, stored: object) -> "CaptionLab":
        """The lab as saved: anything missing, of the wrong type or out of
        range takes its default (an old or hand-edited file never stops
        the app)."""
        if not isinstance(stored, Mapping):
            return cls()
        found: dict[str, object] = {}
        new_for = _number(stored.get("new_for"), NEW_FOR_RANGE)
        if new_for is not None:
            found["new_for"] = new_for
        if stored.get("new_fade") in {f.value for f in NewFade}:
            found["new_fade"] = NewFade(str(stored["new_fade"]))
        older = _number(stored.get("older"), OLDER_RANGE)
        if older is not None:
            found["older"] = older
        if stored.get("unfinished") in {u.value for u in Unfinished}:
            found["unfinished"] = Unfinished(str(stored["unfinished"]))
        if stored.get("loading") in {k.value for k in Loading}:
            found["loading"] = Loading(str(stored["loading"]))
        for name, within in (
            ("link_px", LINK_PX_RANGE),
            ("row_gap", ROW_GAP_RANGE),
            ("caption_gap", CAPTION_GAP_RANGE),
        ):
            value = _number(stored.get(name), within)
            if value is not None:
                found[name] = value
        gap = _number(stored.get("arrival_gap"), ARRIVAL_GAP_RANGE)
        if gap is not None:
            found["arrival_gap"] = gap
        return replace(cls(), **found)  # type: ignore[arg-type]


def _number(value: object, within: tuple[float, float]) -> float | None:
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and within[0] <= value <= within[1]
    ):
        return round(float(value), 2)
    return None


def older_translation(older: float) -> float:
    """An older caption's translation's ink, for what was said's `older`:
    the same share of the step as today's (0.72 -> 0.82)."""
    return round(1.0 - (1.0 - older) * _TRANSLATION_SHARE, 3)


def newness(age: float | None, lab: CaptionLab) -> float:
    """How new a caption is, 1.0 to 0.0 - 1.0 drawn at full ink, 0.0 at an
    older caption's - `age` seconds after it arrived (None: it was there
    when the window opened, or it isn't known). New for `new_for` seconds;
    then at once, or over FADE_BACK_SEC."""
    if age is None or age < 0.0:
        return 0.0
    if age < lab.new_for:
        return 1.0
    if lab.new_fade is NewFade.GRADUAL and lab.new_for > 0.0:
        gone = (age - lab.new_for) / FADE_BACK_SEC
        return max(0.0, 1.0 - gone)
    return 0.0


def clause_gap(row_gap: float) -> float:
    """The gap between clauses for a gap of `row_gap` between a clause and
    its translation: today's 8, or more, so a translation stays nearer its
    own original than the next clause."""
    return max(8.0, row_gap + CLAUSE_MORE)


def ink_between(older: float, new: float) -> float:
    """An ink part way from an older caption's (`new` 0.0) to full (1.0)."""
    return older + (1.0 - older) * new


def changes_at(age: float, lab: CaptionLab) -> float | None:
    """How long after `age` a caption's newness next changes on its own -
    when it steps back, or starts or ends its fade - or None if it won't
    (it's old, or its fade is under way: drawn every frame)."""
    if age < lab.new_for:
        return lab.new_for - age
    return None
