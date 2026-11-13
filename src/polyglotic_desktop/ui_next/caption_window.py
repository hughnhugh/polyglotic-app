"""W1, the caption window: one app's captions over that app (polyglotic-hq
project 109's structure, section 2; the interaction specs 10.1-10.4).

A frameless, always-on-top, translucent window that never takes the
focus: a click on it leaves the app underneath active (a full-screen game
can minimise when it loses focus) - `Qt.WindowDoesNotAcceptFocus`, which
on Windows is `WS_EX_NOACTIVATE` on its native window (checked on a real
window, 2026-11-07), and shown without activating. Its parts:
- **the canvas** (`Canvas`): the captions, newest at the bottom, painted
  from the caption layout engine; the panel behind them; the listening
  mark; "Looks wrong?" on a hovered finished caption; the empty text;
- **the hover strip**: 28 px over the top of the canvas, shown 80 ms after
  the mouse comes over an unlocked window and gone 300 ms after it leaves.
  It is drawn over the captions - nothing moves (108's bug 4) - and covers
  whole rows: a label or row it would cut isn't drawn (113). On it, the
  same at every width (the user, 2026-11-07, in place of 109's chips): the
  source's dot and label (and "Original only" when the window shows no
  translation, and the mic mark while it shows my speech) - the part that
  shortens when the window is narrow - then word links on / off (every
  window's; the user's rehearsal feedback F9, 249), lock (all windows),
  settings and close (stop captioning the app);
- **the settings popover** (`settings_popover`) beside the settings
  button: Translate into (or Original only), Show my speech here, the
  timing, Text size (A- / A+), All caption settings...,
  Open transcript, Join
  windows, Stop captioning - no Position: it's moved by hand (the user's
  rehearsal feedback F8, 249). Every control is one named action (`controls`) the
  strip or the popover draws;
- **the notice line** over the top band (under the header if both show);
  **Back to live · N new** over the bottom band while scrolled back;
- **the lookup** (`lookup_card`, one card every window shares): the word
  under the mouse - by the word split - is drawn softly behind, with its
  word links (links "On hover"); resting on it shows its lookup; a press
  on it looks it up (pinned), and a drag from it across its row selects
  a phrase - a press on a word never moves the window (109's 10.3).

Every edge and corner resizes, anchored to the opposite one (centred
presets symmetric); a drag anywhere else moves it, snapping to the
presets; both are clamped to the work area, and every step lays out again
in the same frame (`views.placement`). Text size changes live and the
window keeps its size; Ctrl+wheel steps it too.

A window is a stack of captions the size the learner set (the Strip, a
window whose height followed the newest caption, went in polyglotic-hq
272: "The strip toggle feels bad, probably remove that").

**Nothing moves under the mouse** (109's rule): while the mouse moves over
an unlocked window, new caption updates wait (`receive`), and come in at
once when it leaves - so a click a moment late still lands on the word
that was under it (polyglotic-hq 145). A mouse left still on it for
`HOLD_SEC` lets them in too: a parked mouse doesn't stop the captions.

After `fade_after` seconds of quiet it fades out, and comes back with the
next caption - or when the mouse rests on it (109's "fades to 0 except in
hover"). A faded window is invisible to the mouse too: Windows passes the
mouse through to what's underneath, so it hears nothing (polyglotic-hq
141). While it's faded and unlocked it looks where the mouse is instead,
every `POINT_POLL_MS`; resting on it for `POINT_REST` looks brings it back
(a mouse passing over doesn't). Locked, it stays click-through and faded.

In a joined window (`joined_window`, 109's 2a) the same window is a
column: a child widget of the joined window, with its own captions,
scroll-back, label, language, text size, my speech and strip (without
lock, which is the window's), while the place, the drags,
the notice line and the fade are the joined window's (`host`).

The window says what the learner did through its signals; `CaptionWindows`
saves its choices and passes on what concerns the session. Holds caption
text: never log it.
"""

import logging
import math
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
    QTextLayout,
    QTextLine,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from polyglotic_desktop.core.learning.lookups import LookupContext, lookup_context
from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Language,
)
from polyglotic_desktop.core.listening.display import (
    DisplayOptions,
    WordLinks,
    clause_versions,
)
from polyglotic_desktop.core.listening.sources import SourceId, SourceLabel
from polyglotic_desktop.core.listening.timing import MAX_WAIT_FOR_TEXT_SEC, CaptionMode
from polyglotic_desktop.core.shared import EntryId
from polyglotic_desktop.perf import spans
from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.caption_delay import delay_text
from polyglotic_desktop.ui_next.caption_layout import (
    LINK_GAP_PX,
    LINK_PX,
    CaptionLayout,
    CaptionStyle,
    Ink,
    LaidLine,
    LaidRow,
    char_under,
    span_rects,
)
from polyglotic_desktop.ui_next.caption_marks import LINK_COLORS, CaptionMarks
from polyglotic_desktop.ui_next.caption_surface import PAD, CaptionSurface
from polyglotic_desktop.ui_next.glyphs import Glyph, icon, paint, text_width
from polyglotic_desktop.ui_next.languages import spoken_names
from polyglotic_desktop.ui_next.lookup_card import LookupCard
from polyglotic_desktop.ui_next.settings_popover import (
    COLUMN_ROWS,
    ROWS,
    KeyState,
    SettingsPopover,
)
from polyglotic_desktop.ui_next.views import placement
from polyglotic_desktop.ui_next.views.app_choices import AppChoice
from polyglotic_desktop.ui_next.views.arrivals import (
    ENTRY_GAP_PX,
    Motion,
    effective,
    older_alphas,
    pace_of,
    slide_seconds,
)
from polyglotic_desktop.ui_next.views.caption_window import (
    CaptionLook,
    Notice,
    Notices,
    WindowChoices,
    intro_seconds,
    shows,
    stepped,
)
from polyglotic_desktop.ui_next.views.captions import (
    CAPTION_WINDOW_LINES,
    CaptionLines,
    Labels,
    Line,
)
from polyglotic_desktop.ui_next.views.lab import (
    Loading,
    Unfinished,
    changes_at,
    clause_gap,
    ink_between,
    newness,
)
from polyglotic_desktop.ui_next.views.lab import (
    older_translation as older_translation_ink,
)
from polyglotic_desktop.ui_next.views.lookup import Learner, WordAt
from polyglotic_desktop.ui_next.views.pacing import Pacing
from polyglotic_desktop.ui_next.views.placement import Edge, Preset, Rect, Size
from polyglotic_desktop.ui_next.views.presets import contrast, readable_on

if TYPE_CHECKING:
    from polyglotic_desktop.ui_next.joined_window import JoinedWindow

log = logging.getLogger(__name__)

WINDOW_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    # a click on it never takes the focus from the app underneath
    | Qt.WindowType.WindowDoesNotAcceptFocus
)
"""A caption window's (and a joined window's) window flags."""
BAND_HEIGHT = 28
"""The hover band over the top of the canvas, in pixels at 100 % text size:
it grows with Windows' text size (`band_height`), as does all the window's
chrome - its captions keep the window's own text size (A- / A+)."""


def band_height() -> int:
    """The hover band's height at the text size now."""
    return style.px(BAND_HEIGHT)


def least_size(least: Size) -> Size:
    """A window's minimum (`MIN_PANEL`) at the text size now:
    wide enough for its hover band."""
    return Size(style.px(least.width), least.height)


STRIP = ("links", "lock", "report", "settings", "stop")
"""The hover strip's buttons after the source's label, left to right - the
same at every width (the user, 2026-11-07); the rest is in the settings
popover. Word links in place of A- / A+, which moved to the popover (the
user's rehearsal feedback F9, 2026-11-08). "Report a problem" only for
alpha testers (`set_reporting`, polyglotic-hq 275)."""
BAND_IN_MS = 80
BAND_OUT_MS = 300
STILL_OVER_MS = 250
"""While the mouse is over a window, how often it checks the mouse is
still there: Windows can lose the leave (after locking and unlocking it,
polyglotic-hq 272). The idle timers' floor (`perf.budgets.IDLE_TIMER`)."""
BAND_ALPHA = 0.6
"""The band's panel: the canvas shows through it at 40 %."""
MIN_PANEL = Size(320, 120)
"""At 100 % text size: the width holds the hover band, so it grows with
the text size (`least_size`); the height holds captions, at their own."""
FADE_SEC = 0.375
FRAME_MS = 16
POINT_POLL_MS = 100
"""How often a faded window looks whether the mouse is on it."""
HOLD_SEC = 4.0
"""New captions wait while the mouse moves over a window; left still this
long, the mouse lets them in (a parked mouse mustn't stop the captions).
Longer than reaching for a word and clicking it."""
POINT_REST = 2
"""Looks in a row the mouse is on a faded window before it comes back
(100-200 ms): resting on it, not passing over."""
MARK_LENGTH = 56.0
MARK_THICK = 4.0
"""The listening mark, a loading bar (the user's word for it, F33): this
long and thick at 100 % text size, growing with it to 160 % - easy to see
at a glance, and thin enough to stay quiet in the padding under the text
(polyglotic-hq 267; it was three 4 px dots, 25 px across)."""
MARK_PERIOD = 1.4
"""Seconds for the bar's lit part to sweep across it once."""
MARK_LIT = 0.36
"""The share of the bar lit as it sweeps."""
MARK_TRACK_ALPHA = 0.22
MARK_LIT_ALPHA = 0.8
"""The bar's track, faint, and its lit part, in the window's original
colour."""
MARK_STILL_ALPHA = 0.7
"""The bar with Windows' animations off (reduced motion): three still
dashes along it, an ellipsis, at this ink - no sweep (260)."""
LOCKED_SEC = 4.0
"""How long a window says how to unlock it, on locking; then only its
corner says the hotkey, faintly (F10, 249)."""
LOCKED_ALPHA = 0.55
"""The locked corner's words: faint, to be seen when looked for."""
FEW_ROWS = 3
"""At this many text rows or fewer, A+ says how to get more."""
GLYPH_PX, MIC_PX = 12, 11
"""The band's icons' and the label's mic's sizes at 100 % text size
(`glyphs`: drawn, the sizes Windows' icon font had there)."""
TEXT = "#e9ecf2"
TEXT_DIM = "#a0a8b6"
ACCENT = "#7c9cff"
ACCENT_TEXT = "#0d1220"
AROUND = (-PAD, -6.0, PAD, 8.0)
"""How far around a line's rows what's drawn with it reaches: a hovered
word's highlight, a dotted mark under its last row."""
HOVERED = QColor(255, 255, 255, 46)
"""Behind the word under the mouse (today's), on a dark panel - on a light
one (Paper's) the same in black (`shade`): white there was invisible."""
SELECTED = QColor(124, 156, 255, 90)
"""Behind a phrase being dragged across."""


def _tr(text: str) -> str:
    return QApplication.translate("CaptionWindow", text)


def timing_name(mode: CaptionMode) -> str:
    return {
        CaptionMode.STEADY: _tr("Steady"),
        CaptionMode.PREVIEW: _tr("Quick preview"),
        CaptionMode.LIVE: _tr("Live updates"),
    }[mode]


def timing_tip(mode: CaptionMode) -> str:
    """What a caption timing does, in plain words, on hover - wherever it's
    chosen (the user's rehearsal feedback F22, 249), with what project 145
    measured on the real models (as the Timing panel's sentence)."""
    return {
        CaptionMode.STEADY: _tr(
            "Each sentence appears once, finished, about half a second after it "
            "ends. Nothing changes while you read."
        ),
        CaptionMode.PREVIEW: _tr(
            "A dim first guess after about 2 seconds, then the finished caption "
            "and its translation when the sentence ends."
        ),
        CaptionMode.LIVE: _tr(
            "Words appear as they're said and rewrite themselves until the "
            "sentence ends - the quickest, but the words move."
        ),
    }[mode]


def high_contrast() -> bool:
    """Whether the learner asked Windows for high contrast (Qt's contrast
    preference): then no caption steps back (F21)."""
    hints = QGuiApplication.styleHints()  # held: its accessibility() is its child
    preference = hints.accessibility().contrastPreference()
    return preference is Qt.ContrastPreference.HighContrast


def reduced_motion() -> bool:
    """Whether the learner turned Windows' animation effects off (Qt's
    motion preference, from `SPI_GETCLIENTAREAANIMATION` on Windows): then
    the listening mark stands still (polyglotic-hq 260)."""
    hints = QGuiApplication.styleHints()  # held: its accessibility() is its child
    preference = hints.accessibility().motionPreference()
    return preference is Qt.MotionPreference.ReducedMotion


LOADING_PERIOD = 1.2
"""Seconds for the Lab's dots to light up in turn, or its ellipsis to
pulse, once (284)."""
DOT_PX = 3.0
"""A dot's radius at 100 % text size (the bar is 4 px thick)."""


def paint_loading(
    painter: QPainter,
    loading: Loading,
    at: QPointF,
    scale: float,
    color: QColor,
    now: float | None,
    newest_live: bool = False,
) -> QRect:
    """The listening mark - speech heard, its caption on its way - as the
    Lab says (`Loading`; 270's FEEDBACK.md line 27): the bar (today's), three
    dots lighting up in turn, or an ellipsis. With the ellipsis, a newest
    caption still being spoken says it by its own trailing "…" (the
    display's `LIVE_TRAIL`), so nothing more is drawn; with none, an
    ellipsis stands where the bar would. `at`: the bar's top left; `now`:
    the clock, None to stand still (Windows' animations off, a preview).
    Where it was drawn, for repainting it alone."""
    left, top = at.x(), at.y()
    thick = MARK_THICK * scale
    if loading is Loading.BAR:
        return paint_bar(painter, left, top, scale, color, now)
    phase = 0.0 if now is None else now / LOADING_PERIOD
    if loading is Loading.DOTS:
        return paint_dots(painter, left, top + thick / 2, scale, color, phase)
    if newest_live:
        return QRect()
    return paint_ellipsis(painter, left, top + thick, scale, color, phase)


def paint_bar(
    painter: QPainter, left: float, top: float, scale: float, color: QColor,
    now: float | None,
) -> QRect:  # fmt: skip
    """The loading bar, its lit part sweeping slowly across a faint track
    (`mark_lit`) - or, standing still (`now` None: Windows' animations
    off), three still dashes along it (260). Never text."""
    length, thick = MARK_LENGTH * scale, MARK_THICK * scale
    color = QColor(color)
    painter.setPen(Qt.PenStyle.NoPen)

    def part(start: float, end: float, alpha: float) -> None:
        color.setAlphaF(alpha)
        painter.setBrush(color)
        x, width = left + start * length, (end - start) * length
        painter.drawRoundedRect(QRectF(x, top, width, thick), thick / 2, thick / 2)

    if now is None:
        dash = 0.25  # three dashes and two gaps of half a dash
        for i in range(3):
            part(i * dash * 1.5, i * dash * 1.5 + dash, MARK_STILL_ALPHA)
    else:
        part(0.0, 1.0, MARK_TRACK_ALPHA)
        start, end = mark_lit(now / MARK_PERIOD)
        if end > start:
            part(start, end, MARK_LIT_ALPHA)
    return QRectF(left - 2, top - 2, length + 4, thick + 4).toAlignedRect()


def dot_inks(phase: float) -> tuple[float, float, float]:
    """The three dots' ink at `phase` (0..1, one cycle): each lights up in
    turn, then fades back to the track's."""
    inks = []
    for i in range(3):
        t = (phase - i / 3.0) % 1.0
        lit = max(0.0, 1.0 - 2.0 * t)
        inks.append(MARK_TRACK_ALPHA + (MARK_LIT_ALPHA - MARK_TRACK_ALPHA) * lit)
    return inks[0], inks[1], inks[2]


def paint_dots(
    painter: QPainter, left: float, middle: float, scale: float, color: QColor,
    phase: float,
) -> QRect:  # fmt: skip
    """The Lab's three dots, from `left`, centred on `middle`; still at
    phase 0 (Windows' animations off: the first lit)."""
    radius = DOT_PX * scale
    painter.setPen(Qt.PenStyle.NoPen)
    for i, ink in enumerate(dot_inks(phase)):
        dot = QColor(color)
        dot.setAlphaF(ink)
        painter.setBrush(dot)
        centre = QPointF(left + radius + i * radius * 3.2, middle)
        painter.drawEllipse(centre, radius, radius)
    width = radius * 2 + 2 * radius * 3.2
    return QRectF(
        left - 2, middle - radius - 2, width + 4, 2 * radius + 4
    ).toAlignedRect()


def paint_ellipsis(
    painter: QPainter, left: float, bottom: float, scale: float, color: QColor,
    phase: float,
) -> QRect:  # fmt: skip
    """The Lab's ellipsis where the bar would be, its ink pulsing gently;
    still at phase 0."""
    font = QFont(painter.font())
    font.setPixelSize(max(8, round(18 * scale)))
    font.setWeight(QFont.Weight.Bold)
    ink = QColor(color)
    pulse = 0.5 + 0.5 * math.cos(2 * math.pi * phase)
    ink.setAlphaF(MARK_TRACK_ALPHA + (MARK_LIT_ALPHA - MARK_TRACK_ALPHA) * pulse)
    painter.setPen(ink)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance("…")
    baseline = bottom
    painter.drawText(QPointF(left, baseline), "…")
    return QRectF(
        left - 2, baseline - metrics.ascent() - 2, width + 4, metrics.height() + 4
    ).toAlignedRect()


def mark_lit(phase: float) -> tuple[float, float]:
    """The listening mark's lit part at `phase` (0..1, one sweep), as where
    it starts and ends along the bar (0..1): it comes in at the left, eases
    across and goes out at the right."""
    t = phase % 1.0
    eased = t * t * (3.0 - 2.0 * t)  # smoothstep: slow at the ends
    start = -MARK_LIT + (1.0 + MARK_LIT) * eased
    return max(0.0, start), min(1.0, start + MARK_LIT)


LABEL_CONTRAST = 7.0
"""A label's colour against the look's panel at least: WCAG's 7:1 for small
type, so it still clears 4.5:1 drawn a little faint over a panel that
isn't quite solid (Paper's: 94 %) - 261."""


def caption_style(look: CaptionLook) -> CaptionStyle:
    """The caption layout's style for `look`: its font, and a word link's
    underline - with room under each row while links are underlined (F14) -
    and the Lab's (284): which text still being spoken is italic, the
    underline's thickness if it's set there, and the spacing."""
    lab = look.lab
    unfinished = lab.unfinished
    return CaptionStyle(
        family=look.font,
        link_px=LINK_PX[look.link_line] if lab.link_px is None else lab.link_px,
        row_gap=lab.row_gap,
        clause_gap=clause_gap(lab.row_gap),
        caption_gap=lab.caption_gap,
        link_gap=LINK_GAP_PX[look.link_gap],
        link_room=look.show_original
        and look.word_links in (WordLinks.COLOURS, WordLinks.ARROWS),
        arrows=look.show_original and look.word_links is WordLinks.ARROWS,
        italic_provisional=unfinished in (Unfinished.AS_NOW, Unfinished.ITALIC),
        italic_live=unfinished is Unfinished.ITALIC,
    )


UNFINISHED_ALPHAS = {
    Unfinished.AS_NOW: (Ink.provisional_alpha, Ink.live_alpha),
    Unfinished.SAME: (1.0, 1.0),
    Unfinished.DIMMER: (Ink.provisional_alpha, Ink.provisional_alpha),
    Unfinished.ITALIC: (1.0, 1.0),
    Unfinished.COLOUR: (1.0, 1.0),
}
"""How faint text still being spoken is drawn - a provisional line, a live
caption - for each of the Lab's choices (284)."""


def unfinished_ink(ink: Ink, look: CaptionLook) -> Ink:
    """`ink` with text still being spoken drawn as the Lab says: fainter,
    or in the theme's accent, readable on the look's panel (284)."""
    unfinished = look.lab.unfinished
    provisional, live = UNFINISHED_ALPHAS[unfinished]
    colour = None
    if unfinished is Unfinished.COLOUR:
        colour = QColor(readable_on(ACCENT, look.background))
    return replace(
        ink, provisional_alpha=provisional, live_alpha=live, unfinished=colour
    )


def word_hint() -> str:
    """Said once, on the first finished caption a window shows, until the
    learner's first lookup (polyglotic-hq 160: people didn't find that the
    words are clickable; 176)."""
    return _tr("Click any word to look it up")


def notice_text(notice: Notice, retry_in: int | None) -> str:
    """The notice line's wording (087 section 5.5) - the same words on
    every caption window, the joined window, a transcript and Home's
    banner. A busy time: the server slows live updates (`pace`), so
    "slowed" where 087 drew "paused", and "busy time" for any hour.
    Stopped says what to do, in Home's words (polyglotic-hq 235); so do
    Not signed in (Home has Sign in) and Update needed (Home says which
    step, as the update goes - polyglotic-hq 237)."""
    if notice is Notice.RECONNECTING and retry_in:
        return _tr("Reconnecting - trying again in {n} s").format(n=retry_in)
    if notice is Notice.SERVER_BUSY and retry_in:
        return _tr("The server is busy - trying again in {n} s").format(n=retry_in)
    if notice in _COUNTED and retry_in:
        return _COUNTED[notice]().format(n=retry_in)
    return {
        Notice.PAUSED: _tr("Paused"),
        Notice.RECONNECTING: _tr("Reconnecting"),
        Notice.SERVER_BUSY: _tr("The server is busy"),
        Notice.NOT_SIGNED_IN: _tr("Not signed in - sign in on Home"),
        Notice.UPDATE_NEEDED: _tr("Update needed - captions paused; see Home"),
        Notice.STOPPED: _tr("Stopped - quit from the tray and start again"),
        Notice.PLUS_ENDED: _tr("Plus has ended - captions stopped; see Home"),
        Notice.MINUTES_USED: _tr("Today's free minutes are used - more at midnight"),
        Notice.FAILING: _tr("Captions failing on the server - still trying"),
        Notice.UNSTABLE: _tr("Connection unstable - captions may come late"),
        Notice.BUSY: _tr("Busy time - live updates slowed; captions continue"),
        Notice.OFFLINE: _tr("No internet? Can't reach Polyglotic's server"),
        Notice.CANT_REACH: _tr("Can't reach Polyglotic's server"),
        Notice.SERVER_DOWN: _tr("Polyglotic's server is down"),
        Notice.SERVER_RESTARTING: _tr("Polyglotic's server is restarting"),
        Notice.SERVER_PROBLEM: _tr("Polyglotic's server has a problem"),
        Notice.BLOCKED: _tr("Connection blocked by this network - see Home"),
        Notice.NOT_SECURE: _tr("Can't connect securely - see Home"),
        Notice.CLOCK: _tr("Check this PC's date and time - see Home"),
        Notice.TOO_MANY_SESSIONS: _tr("Open on too many of your PCs - see Home"),
        Notice.TOO_MANY_TRIES: _tr("Too many sign-in tries"),
    }[notice]


_COUNTED: dict[Notice, Callable[[], str]] = {
    Notice.OFFLINE: lambda: _tr(
        "No internet? Can't reach Polyglotic's server - trying again in {n} s"
    ),
    Notice.CANT_REACH: lambda: _tr(
        "Can't reach Polyglotic's server - trying again in {n} s"
    ),
    Notice.SERVER_DOWN: lambda: _tr(
        "Polyglotic's server is down - trying again in {n} s"
    ),
    Notice.SERVER_RESTARTING: lambda: _tr(
        "Polyglotic's server is restarting - trying again in {n} s"
    ),
    Notice.SERVER_PROBLEM: lambda: _tr(
        "Polyglotic's server has a problem - trying again in {n} s"
    ),
    Notice.TOO_MANY_TRIES: lambda: _tr(
        "Too many sign-in tries - trying again in {n} s"
    ),
}
"""Why the server can't be reached, counting down to the next try
(polyglotic-hq 251)."""


def locked_text(keys: str) -> str:
    """What a window says when it's locked: how to unlock it - with the
    hotkey as it is now, or where else to, if another app has the hotkey
    (the user's rehearsal feedback F10, 249)."""
    if keys:
        return _tr("Locked - {keys} to unlock").format(keys=keys)
    return _tr("Locked - unlock on Home or from the tray")


def preset_name(preset: Preset) -> str:
    return {
        Preset.BOTTOM_LEFT: _tr("Bottom left"),
        Preset.BOTTOM_CENTRE: _tr("Bottom centre"),
        Preset.TOP_CENTRE: _tr("Top centre"),
        Preset.CUSTOM: _tr("Where I put it"),
    }[preset]


def restore_minimised(window: QWidget) -> Callable[[], None]:
    """What brings back a caption or joined window Windows minimised: out of
    the minimised state, and shown, still without activating it."""

    def restore() -> None:
        if window.isMinimized() and window.isVisible():
            # hidden and shown again, as Ctrl+Alt+H twice: shown without
            # activating it - Qt's restore (setWindowState) activated it, on
            # a real window (272), which a full-screen game can lose to
            window.hide()
            window.setWindowState(
                window.windowState() & ~Qt.WindowState.WindowMinimized
            )
            window.show()

    return restore


def to_qrect(rect: Rect) -> QRect:
    return QRect(rect.x, rect.y, rect.width, rect.height)


def to_rect(rect: QRect) -> Rect:
    return Rect(rect.x(), rect.y(), rect.width(), rect.height())


def work_areas() -> list[Rect]:
    """Each screen's work area (the taskbar excluded), the primary first."""
    primary = QGuiApplication.primaryScreen()
    screens = QGuiApplication.screens()
    ordered = [primary, *(s for s in screens if s is not primary)] if primary else []
    return [to_rect(s.availableGeometry()) for s in ordered]


_CURSORS = {
    Edge.LEFT: Qt.CursorShape.SizeHorCursor,
    Edge.RIGHT: Qt.CursorShape.SizeHorCursor,
    Edge.TOP: Qt.CursorShape.SizeVerCursor,
    Edge.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Edge.LEFT | Edge.TOP: Qt.CursorShape.SizeFDiagCursor,
    Edge.RIGHT | Edge.BOTTOM: Qt.CursorShape.SizeFDiagCursor,
    Edge.RIGHT | Edge.TOP: Qt.CursorShape.SizeBDiagCursor,
    Edge.LEFT | Edge.BOTTOM: Qt.CursorShape.SizeBDiagCursor,
}


@dataclass(frozen=True)
class Marked:
    """Characters `[start, end)` of row `row` of the line `key`."""

    key: int
    row: int
    start: int
    end: int


@dataclass
class _Selecting:
    """A press on a word: a click looks it up; a drag across the row
    selects a phrase from it. `anchor`: the character pressed on."""

    word: Marked
    anchor: int


def _wordlike(char: str) -> bool:
    """Not a space or punctuation - what a dragged-out phrase is trimmed to."""
    return (
        not char.isspace()
        and not unicodedata.category(char).startswith("P")
        and char != "…"
    )


@dataclass
class _Drag:
    """A press being dragged: resizing `edges` (none: moving) from `start`
    (the window's place then) at the mouse's `origin`."""

    edges: Edge
    origin: QPointF
    start: Rect
    snapped: Preset = Preset.CUSTOM
    moved: bool = False


class Canvas(CaptionSurface):
    """The window's captions and what's painted with them. Takes no mouse
    of its own: the window has it (resizing, moving, hovering)."""

    def __init__(self, window: "CaptionWindow", view: CaptionLines) -> None:
        super().__init__(view, parent=window)
        self.owner = window
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.placed: list[tuple[Line, LaidLine, QRectF]] = []
        """The lines the last paint drew, laid out, and where."""
        self.hovered: Marked | None = None
        """The word under the mouse: drawn behind, with its word links."""
        self.selection: Marked | None = None
        """A phrase being dragged across."""
        self.clear_top = float(PAD)
        """Where the last paint's captions started (below the band, if shown)."""
        self.flagged: Line | None = None
        """The finished caption under the mouse: "Looks wrong?" on it."""
        self.flag_rect: QRectF | None = None
        self.mark_rect: QRect | None = None
        self._dirty = QRectF()
        """What the paint under way was asked to draw: lines outside it are
        placed, not painted (a hovered word repaints its line alone)."""
        self.at_rest: dict[tuple[int, int], float] = {}
        """Where the last paint's rows sit at rest, before any slide - each
        row's top on the screen, by its line's key and row index: what the
        next arrival measures against (`rest_rows`). Noted only while the
        window slides."""

    # -- measuring at a width --------------------------------------------------------

    def laid_at(self, line: Line, width: int) -> LaidLine:
        return self.engine.laid(line, width, self.view.text_size)

    def rows_that_fit(self) -> float:
        """About how many rows of text the window shows at its text size."""
        row = self.engine.style.text_px * self.view.text_size * 1.35
        return self._view_height() / row

    # -- painting ---------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        with spans.span("caption_window.paint"):
            self._dirty = QRectF(event.rect())
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_panel(painter)
            if self.owner.band_shown:
                self._paint_band(painter)
            painter.end()
            self._drawn_revision = self.view.revision

    def _panel(self, painter: QPainter, top: float, bottom: float) -> None:
        look = self.owner.look
        whole = self.owner.band_shown or self.owner.hovered
        opacity = max(look.opacity, 0.55) if whole else look.opacity
        color = QColor(look.background)
        color.setAlphaF(opacity)
        painter.setBrush(color)
        if whole:
            painter.setPen(QPen(shade(self.owner.bar, 46), 1))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        left, right = self._sides()
        painter.drawRoundedRect(
            QRectF(
                0.5 - left, top + 0.5, self.width() - 1 + left + right, bottom - top - 1
            ),
            12,
            12,
        )
        if left:  # a joined window's column: a 1 px divider from the one before
            painter.setPen(QPen(shade(self.owner.bar, 38), 1))
            painter.drawLine(QPointF(0.5, top + 1), QPointF(0.5, bottom - 1))

    def _sides(self) -> tuple[float, float]:
        """How far the panel runs on past the left and right edges: a joined
        window's column runs on under its neighbours, so only the window's
        outer corners are round."""
        inner_left, inner_right = self.owner.inner_sides()
        return (16.0 if inner_left else 0.0), (16.0 if inner_right else 0.0)

    def _paint_panel(self, painter: QPainter) -> None:
        view = self.view
        width = self._width()
        placed = view.scroll.placed(
            view.lines, self._height, self._view_height(), self._gap()
        )
        offset, entry = self._motion()
        listening = self.owner.mark_showing
        # the whole panel, the size the learner set: one that hugged the text
        # grew as live text came, and in a joined window a quiet column had
        # none - one column bobbing beside the others (the user's "window
        # resizes / flickers", polyglotic-hq 272). A window with nothing to
        # show is faded out, panel and all (`views.caption_window.shows`).
        self._panel(painter, 0, self.height())
        shown = self._moved(
            [(item.line, self._laid(item.line), PAD + item.top) for item in placed],
            offset,
            entry,
        )
        # whole rows at the top too, as under the band: the oldest row in
        # view isn't drawn cut through its glyphs (151's W3; 176)
        top = (
            self._clear_of_band(shown)
            if self.owner.band_shown
            else self._clear_of(shown, float(PAD))
        )
        self.clear_top = top
        painter.save()
        painter.setClipRect(
            QRectF(0, top, self.width(), max(0.0, PAD + self._view_height() - top))
        )
        self.placed = []
        whole = self._dirty.contains(QRectF(self.rect()))  # a part: its lines
        # B (F21, 253): the newest caption full, those before it a step back -
        # the preview line, newer still, full too; scrolled back, all full.
        # The Lab: how far back, and captions new for a while full too (284)
        lab = self.owner.look.lab
        older, older_translation = older_alphas(
            high_contrast(),
            view.scroll.following,
            (lab.older, older_translation_ink(lab.older)),
        )
        newest = next(
            (line.key for line in reversed(view.lines) if not line.provisional), None
        )
        now = self.owner.clock()
        for line, laid, y in shown:
            if not any(
                y + row.top + row.layout.boundingRect().height() > top + 0.01
                for row in laid.rows
            ):
                continue  # every row above the top: none drawn (W3)
            at = QPointF(PAD, y)
            alpha = translation = 1.0
            if newest is not None and line.key < newest:
                new = newness(self.owner.age_of(line.key, now), lab)
                alpha = ink_between(older, new)
                translation = ink_between(older_translation, new) / alpha
            ink = self.ink
            if alpha < 1.0 or translation != 1.0:
                ink = replace(self.ink, alpha=alpha, translation_alpha=translation)
            rect = QRectF(at.x(), at.y(), width, laid.height)
            asked = whole or self._dirty.intersects(rect.adjusted(*AROUND))
            if asked:  # else outside what this paint redraws: placed, not painted
                self._paint_marked(painter, line, laid, at)
                self.engine.paint(painter, line, laid, at, ink, self.marks)
            self.placed.append((line, laid, rect))
        painter.restore()
        self.shown = len(placed)
        if not view.lines:
            self._paint_empty(painter)
        self.mark_rect = self._paint_mark(painter) if listening else None
        self.flag_rect = self._paint_flag(painter)
        self._paint_locked(painter)

    # -- arriving: step and slide (views.arrivals; polyglotic-hq 253, 267) ------------

    def _motion(self) -> tuple[float, dict[int, float]]:
        """How far below its place the text in view is drawn now, and each
        new line's entry beyond that (its key -> px) - none unless the
        window slides (`CaptionWindow.sliding`)."""
        owner = self.owner
        if not owner.sliding:
            return 0.0, {}
        now = owner.clock()
        motion = owner.motion
        gap = ENTRY_GAP_PX * self.view.text_size
        entries = {key: gap * motion.entry(key, now) for key in motion.entries}
        return motion.offset(now), {k: px for k, px in entries.items() if px > 0.0}

    def _moved(
        self,
        shown: list[tuple[Line, LaidLine, float]],
        offset: float,
        entry: dict[int, float],
    ) -> list[tuple[Line, LaidLine, float]]:
        """`shown` (each line's top at rest) where it's drawn now - its rest
        places noted first (`at_rest`) when the window slides."""
        if not self.owner.sliding:
            return shown
        self.at_rest = self._rows_of(shown)
        if not offset and not entry:
            return shown
        return [
            (ln, laid, y + offset + entry.get(ln.key, 0.0)) for ln, laid, y in shown
        ]

    def _rows_of(
        self, shown: list[tuple[Line, LaidLine, float]]
    ) -> dict[tuple[int, int], float]:
        """Each row's top on the screen, by its line's key and row index."""
        top = float(self.mapToGlobal(QPoint(0, 0)).y())
        return {
            (line.key, row.index): top + y + row.top
            for line, laid, y in shown
            for row in laid.rows
        }

    def rest_rows(self) -> dict[tuple[int, int], float]:
        """Where each row in view sits at rest now - every row's top on the
        screen - for an arrival to measure how far the text rose since the
        last paint (`at_rest`)."""
        view = self.view
        placed = view.scroll.placed(
            view.lines, self._height, self._view_height(), self._gap()
        )
        return self._rows_of(
            [(item.line, self._laid(item.line), PAD + item.top) for item in placed]
        )

    def _paint_marked(
        self, painter: QPainter, line: Line, laid: LaidLine, at: QPointF
    ) -> None:
        """Behind the hovered word and a phrase being selected: a soft
        highlight; and the hovered word's word links - it and its
        counterpart in the link's colour (links "On hover", and on hover
        with Colours or Arrows)."""
        hovered_tint = shade(self.owner.bar, HOVERED.alpha())
        for marked, color in ((self.hovered, hovered_tint), (self.selection, SELECTED)):
            if marked is not None and marked.key == line.key:
                self._fill(painter, laid, at, marked, color)
        hovered = self.hovered
        if (
            hovered is None
            or hovered.key != line.key
            or self.owner.look.word_links is WordLinks.OFF
        ):
            return
        for partner, link in linked_with(line, hovered):
            tint = QColor(LINK_COLORS[link % len(LINK_COLORS)])
            tint.setAlphaF(0.4)
            self._fill(painter, laid, at, partner, tint)

    @staticmethod
    def _fill(
        painter: QPainter, laid: LaidLine, at: QPointF, marked: Marked, color: QColor
    ) -> None:
        row = next((r for r in laid.rows if r.index == marked.row), None)
        if row is None:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for rect in span_rects(row.layout, marked.start, marked.end):
            box = rect.translated(at.x(), at.y() + row.top).adjusted(-3, 0, 3, 0)
            painter.drawRoundedRect(box, 5, 5)

    # -- words under the mouse -----------------------------------------------------------

    def line_area(self, key: int) -> QRect | None:
        """Where line `key` was last drawn, with what's drawn just around its
        rows (a hovered word's highlight, dots under a row): what a change
        to that line alone repaints. None if it wasn't drawn."""
        for line, _, rect in self.placed:
            if line.key == key:
                return rect.adjusted(*AROUND).toAlignedRect()
        return None

    def hit(self, pos: QPointF) -> tuple[Line, LaidRow, QPointF, int] | None:
        """The character under `pos`: its line, row, the row's top left
        (in the canvas) and its index in the row's text - or None."""
        if pos.y() < self.clear_top:
            return None  # under the band: not drawn
        for line, laid, rect in self.placed:
            if not rect.top() <= pos.y() < rect.bottom():
                continue
            rows = ((row, QPointF(rect.x(), rect.y() + row.top)) for row in laid.rows)
            found = char_under(rows, pos)
            return (line, *found) if found is not None else None
        return None

    def shown_row(self, key: int, index: int) -> tuple[Line, LaidRow, QPointF] | None:
        """Row `index` of the line `key`, if it's drawn: and its top left."""
        for line, laid, rect in self.placed:
            if line.key == key:
                for row in laid.rows:
                    if row.index == index:
                        return line, row, QPointF(rect.x(), rect.y() + row.top)
        return None

    def char_at(self, row: LaidRow, origin: QPointF, pos: QPointF) -> int:
        """The character of `row` nearest `pos` - a drag needn't stay on it."""
        layout = row.layout
        lines = [layout.lineAt(i) for i in range(layout.lineCount())]
        if not lines:
            return 0
        text_line = next(
            (li for li in lines if pos.y() < origin.y() + li.y() + li.height()),
            lines[-1],
        )
        index = text_line.xToCursor(
            pos.x() - origin.x(), QTextLine.CursorPosition.CursorOnCharacter
        )
        return min(max(index, 0), max(0, len(row.row.text) - 1))

    def line_rect(self, row: LaidRow, origin: QPointF, start: int, end: int) -> QRectF:
        """The text lines of `row` that characters `[start, end)` are on,
        across the canvas: the row being read."""
        rects = span_rects(row.layout, start, end)
        top = min((r.top() for r in rects), default=0.0)
        bottom = max((r.bottom() for r in rects), default=0.0)
        return QRectF(0, origin.y() + top, self.width(), bottom - top)

    @staticmethod
    def _clear_of_band(shown: list[tuple[Line, LaidLine, float]]) -> float:
        """Where captions start while the hover band shows: below every
        label and row it would cut, so it covers whole rows - none peeks
        out half under it. `shown`: each line drawn, laid out, and its top."""
        return Canvas._clear_of(shown, band_height() + 1.0)

    @staticmethod
    def _clear_of(shown: list[tuple[Line, LaidLine, float]], edge: float) -> float:
        """Where captions start below `edge` - the band's foot, or the
        panel's top: below every label and row that starts above it, so
        only whole rows show. `shown`: each line drawn, laid out, and its
        top."""
        top = edge
        for n, (_, laid, y) in enumerate(shown):
            if y >= edge:
                break
            newest = n == len(shown) - 1
            if laid.label is not None and laid.rows:
                top = max(top, y + laid.rows[0].top)  # the label, and its gap
            for row in laid.rows:
                if y + row.top >= edge:
                    break
                if newest:
                    # the newest caption by its wrapped lines: a row taller
                    # than the window is never whole, and skipping it whole
                    # left a long sentence's window blank (polyglotic-hq 278)
                    top = max(
                        top, Canvas._clear_of_lines(row.layout, y + row.top, edge)
                    )
                else:
                    top = max(top, y + row.top + row.layout.boundingRect().height())
        return top

    @staticmethod
    def _clear_of_lines(layout: QTextLayout, at: float, edge: float) -> float:
        """Below every wrapped line of a row at `at` that starts above `edge`."""
        top = edge
        for n in range(layout.lineCount()):
            line = layout.lineAt(n)
            if at + line.y() >= edge:
                break
            top = max(top, at + line.y() + line.height())
        return top

    def _paint_band(self, painter: QPainter) -> None:
        """The hover band's panel, over the top of the captions - those it
        covers aren't drawn (`_clear_of_band`); the panel shows through."""
        color = QColor(self.owner.look.background)
        color.setAlphaF(BAND_ALPHA)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        left, right = self._sides()
        painter.drawRoundedRect(
            QRectF(1 - left, 1, self.width() - 2 + left + right, band_height()), 11, 11
        )

    def _paint_empty(self, painter: QPainter) -> None:
        """With nothing to read yet: "Waiting for audio…" ("Listening…" once
        speech is heard) and whose captions will appear - from the moment its
        app is chosen until its first captions (polyglotic-hq 272), in the
        window's own colour."""
        look = self.owner.look
        waiting = QColor(readable_on(look.original, look.background, LABEL_CONTRAST))
        whose = QColor(waiting)
        whose.setAlphaF(0.75)
        font = QFont(self.font())
        font.setPixelSize(style.px(15))
        font.setWeight(QFont.Weight.DemiBold)
        small = QFont(self.font())
        small.setPixelSize(style.px(13))
        width = self.width() - 2 * PAD
        middle = self.height() / 2
        tall = QFontMetrics(font).height()
        painter.setPen(waiting)
        painter.setFont(font)
        painter.drawText(
            QRectF(PAD, middle - tall, width, tall),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            _tr("Listening…") if self.owner.mark_showing else _tr("Waiting for audio…"),
        )
        painter.setPen(whose)
        painter.setFont(small)
        painter.drawText(
            QRectF(PAD, middle + 2, width, tall),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            _tr("{app}'s captions appear here").format(app=self.owner.label.name),
        )

    def _paint_mark(self, painter: QPainter) -> QRect:
        """The listening mark under the newest caption, as the Lab says
        (`paint_loading`, 284). In the window's original colour."""
        scale = min(self.view.text_size, 1.6)
        thick = MARK_THICK * scale
        still = reduced_motion()
        lines = self.view.lines
        return paint_loading(
            painter,
            self.owner.look.lab.loading,
            QPointF(PAD + 3, self.height() - PAD / 2 - thick / 2 - 1),
            scale,
            QColor(self.owner.look.original),
            None if still else time.monotonic(),
            newest_live=bool(lines) and lines[-1].live,
        )

    def _paint_locked(self, painter: QPainter) -> None:
        """Locked: a lock and the hotkey that unlocks, faint, in the bottom
        right corner, in the padding under the captions (F10, 249) - the
        joined window's last column only."""
        owner = self.owner
        host = owner.host
        if not owner.locked or (host is not None and host.columns[-1:] != [owner]):
            return
        font = QFont(self.font())
        font.setPixelSize(style.px(12))
        keys = owner.unlock_keys
        width = QFontMetrics(font).horizontalAdvance(keys) if keys else 0
        side = style.px(GLYPH_PX)
        gap = 4 if keys else 0
        right = self.width() - PAD
        middle = self.height() - PAD / 2
        color = QColor(owner.bar.text)
        color.setAlphaF(LOCKED_ALPHA)
        paint(
            painter,
            Glyph.LOCK,
            QRectF(right - width - gap - side, middle - side / 2, side, side),
            color,
        )
        if keys:
            painter.setPen(color)
            painter.setFont(font)
            painter.drawText(
                QRectF(right - width, middle - side, width, 2 * side),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                keys,
            )

    def _paint_flag(self, painter: QPainter) -> QRectF | None:
        """ "Looks wrong?" at a hovered finished caption's top right."""
        line = self.flagged
        found = next(
            (r for ln, _, r in self.placed if line is not None and ln is line), None
        )
        if line is None or found is None:
            return None
        font = QFont(self.font())
        font.setPixelSize(style.px(12))
        text = _tr("Looks wrong?")
        width = QFontMetrics(font).horizontalAdvance(text) + 16
        rect = QRectF(found.right() - width, max(found.top(), PAD), width, style.px(20))
        ink = self.owner.bar
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade(ink, 40))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(ink.text))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        return rect


def linked_with(line: Line, marked: Marked) -> list[tuple[Marked, int]]:
    """The word links touching `marked`: each linked word, on its row and
    the other row of its clause, with its link's number."""
    if marked.row >= len(line.rows):
        return []
    row = line.rows[marked.row]
    numbers = {
        w.link for w in row.links if w.start < marked.end and marked.start < w.end
    }
    if not numbers:
        return []
    return [
        (Marked(marked.key, index, w.start, w.end), w.link)
        for index, other in enumerate(line.rows)
        if other.clause == row.clause
        for w in other.links
        if w.link in numbers
    ]


class SourceTag(QWidget):
    """The source's colour dot and label - the window's title - then, dim,
    why the window shows no translation ("Original only"), and the mic
    mark while the window shows my speech. The label shortens first."""

    NOTE_MIN = 40
    """The label is shortened to no less than this before the note goes."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.label = SourceLabel("", ACCENT)
        self.mic = False
        self.note = ""
        self.ink = bar_ink(CaptionLook().background)
        """Its words' colours, on its window's panel."""
        self._font = style.ui_font()
        self._font.setWeight(QFont.Weight.DemiBold)
        self._note_font = style.ui_font()
        self.restyle()

    def restyle(self) -> None:
        """Its fonts at the text size now."""
        self._font.setPixelSize(style.px(12))
        self._note_font.setPixelSize(style.px(12))  # never under 12 px (the UI lab)
        self.updateGeometry()

    def show_label(self, label: SourceLabel, mic: bool, note: str = "") -> None:
        self.label, self.mic, self.note = label, mic, note
        self.setToolTip(f"{label.name} - {note}" if note else label.name)
        self.updateGeometry()
        self.update()

    def _note_width(self) -> int:
        if not self.note:
            return 0
        return 10 + QFontMetrics(self._note_font).horizontalAdvance(self.note)

    def sizeHint(self) -> QSize:
        width = 14 + QFontMetrics(self._font).horizontalAdvance(self.label.name[:24])
        mic = style.px(18) if self.mic else 0
        return QSize(width + self._note_width() + mic + 4, style.px(22))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.label.color))
        painter.drawEllipse(QRectF(2, self.height() / 2 - 4, 8, 8))
        mic = style.px(18) if self.mic else 0
        room = self.width() - 14 - mic
        note = self._note_width()
        metrics = QFontMetrics(self._font)
        if note and room - note < min(
            self.NOTE_MIN, metrics.horizontalAdvance(self.label.name)
        ):
            note = 0  # too narrow for both: the label alone
        painter.setPen(QColor(self.ink.text))
        painter.setFont(self._font)
        name = metrics.elidedText(
            self.label.name, Qt.TextElideMode.ElideRight, room - note
        )
        painter.drawText(
            QRectF(14, 0, room - note, self.height()),
            Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        if note:
            painter.setPen(QColor(self.ink.dim))
            painter.setFont(self._note_font)
            painter.drawText(
                QRectF(
                    14 + metrics.horizontalAdvance(name) + 10, 0, note, self.height()
                ),
                Qt.AlignmentFlag.AlignVCenter,
                self.note,
            )
        if self.mic:
            side = style.px(MIC_PX)
            area = QRectF(self.width() - mic, 0, mic - 2, self.height())
            box = QRectF(0, 0, side, side)
            box.moveCenter(area.center())
            paint(painter, Glyph.MIC, box, QColor(self.ink.accent))
        painter.end()


def notice_style() -> str:
    """The notice line's look, at the text size now."""
    return (
        f"background: rgba(25,29,36,0.92); color: {TEXT}; border: 1px solid #262b34;"
        f" border-radius: 9px; padding: 2px 12px; font-size: {style.px(12)}px;"
    )


def fit_glyph(button: QToolButton, side: int) -> None:
    """`button`'s icon `side` pixels square, the button as wide as Windows'
    icon font made it (its words' size, `px(12)`), so the band keeps its
    layout."""
    button.setIconSize(QSize(side, side))
    button.setMinimumWidth(0)
    margins = button.sizeHint().width() - side
    button.setMinimumWidth(margins + text_width(style.px(12)))


BAR_CONTRAST = 4.5
"""The top bar's words and icons against the panel's colour at least: WCAG's
4.5:1 for text, so its icons clear 1.4.11's 3:1 with room for the game
showing through a panel that isn't quite solid (polyglotic-hq 272: white
icons on Paper's cream were 1.05:1, "impossible to see")."""


@dataclass(frozen=True, slots=True)
class BarInk:
    """The colours of a window's own chrome on its panel - the top bar's
    words and icons, the hover behind its buttons, the locked corner and
    "Looks wrong?" - following the panel's colour (`bar_ink`)."""

    text: str
    dim: str
    disabled: str
    accent: str
    shade: str
    """"r,g,b" of what lightens or darkens a button under the mouse:
    white on a dark panel, black on a light one."""


def bar_ink(background: str) -> BarInk:
    """The chrome's colours on a panel of `background` ("#rrggbb"): the
    usual light ones on a dark panel, darkened until readable on a light
    one."""
    light = contrast("#000000", background) > contrast("#ffffff", background)
    return BarInk(
        text=readable_on(TEXT, background, BAR_CONTRAST),
        dim=readable_on(TEXT_DIM, background, BAR_CONTRAST),
        disabled=readable_on(TEXT_DIM, background, 3.0),
        accent=readable_on(ACCENT, background, 3.0),
        shade="0,0,0" if light else "255,255,255",
    )


def shade(ink: BarInk, alpha: int) -> QColor:
    """What lightens or darkens on the panel at `alpha` (0-255): white on a
    dark panel, black on a light one (`BarInk.shade`) - a hovered word, the
    hovered window's edge, a joined window's dividers."""
    red, green, blue = (int(c) for c in ink.shade.split(","))
    return QColor(red, green, blue, alpha)


def band_style(ink: BarInk | None = None) -> str:
    """The hover band's buttons' look, at the text size now, in `ink` (the
    default panel's if None)."""
    ink = ink or bar_ink(CaptionLook().background)
    shade = ink.shade
    return f"""
QToolButton {{ background: transparent; color: {ink.text}; border: 1px solid transparent;
  border-radius: 5px; padding: 0 6px; font-size: {style.px(12)}px;
  min-height: {style.px(20)}px; }}
QToolButton:hover {{ background: rgba({shade},0.16); }}
QToolButton:checked {{ background: rgba({shade},0.24); }}
QToolButton:checked:disabled {{ background: rgba({shade},0.08); }}
QToolButton[chip="true"] {{ border: 1px solid rgba({shade},0.35); }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
"""


def pill_style() -> str:
    """Back to live's look, at the text size now."""
    return (
        f"QPushButton {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: none;"
        f" border-radius: 9px; padding: 3px 14px; font-size: {style.px(12)}px;"
        " font-weight: 600; }"
    )


class CaptionWindow(QWidget):
    """One app's caption window. `choices` are what it remembers; `look`,
    the timing, second languages, labels, paused, the notice and the
    listening mark are the session's, set by `CaptionWindows`."""

    changed = Signal()
    """Its choices changed (place, text size, mode, language, my speech)."""
    language_changed = Signal()
    mic_changed = Signal()
    lock_wanted = Signal()
    hide_wanted = Signal()
    stop_wanted = Signal()
    report_wanted = Signal()
    """An alpha tester's "Report a problem" (polyglotic-hq 275)."""
    """Close: stop captioning this app (= untick it)."""
    transcript_wanted = Signal()
    all_settings_wanted = Signal()
    """All caption settings...: Settings > Captions in the main window."""
    links_wanted = Signal(bool)
    """The strip's word links button: on or off, for every window (F9)."""
    timing_wanted = Signal(str)
    looks_wrong = Signal(str)
    """A finished caption's id: check it with the best model (101)."""
    join_wanted = Signal()
    """Join windows: every caption window into one, a column each (109's 2a)."""
    app_wanted = Signal(str)
    """An app's name, from its settings: caption it here instead (F12, 249)."""
    second_wanted = Signal(str, str)
    """Its settings' "Lines already in ...": a translation language and the
    language its lines already in it are shown in ("": left as they are) -
    by translation language, so for every window with it (263)."""

    def __init__(
        self,
        key: str,
        source: SourceId,
        choices: WindowChoices,
        label: SourceLabel,
        look: CaptionLook | None = None,
        index: int = 0,
        mic: SourceId | None = None,
        areas: Callable[[], list[Rect]] = work_areas,
        keys: KeyState | None = None,
        learner: Learner | None = None,
        card: LookupCard | None = None,
    ) -> None:
        """`keys`: whether Esc or a mouse button is held anywhere (from
        `platform`, by way of `main`), for closing the settings popover;
        `learner`: the learning tools (highlights, the words under the
        mouse); `card`: the lookup card every window shares."""
        super().__init__(None, WINDOW_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName(f"caption_window.{index}")
        self.setFont(style.ui_font())  # its own words, painted or not
        self.setMouseTracking(True)
        self.key, self.source, self.index = key, source, index
        self.choices = choices
        self.label = label
        self.look = look or CaptionLook()
        self.mic = mic
        self.timing = CaptionMode.STEADY
        self.second_languages: Mapping[Language, Language] = {}
        self.spoken_fallback = False
        """Its spoken language can't be used as it is: the server takes one
        for every window (one from before 2026-11-09), and another window
        names a different one - so its app is heard as Detect (263)."""
        self.labels = Labels()
        self.windows = 1  # caption windows there are (for Join windows)
        self.host: JoinedWindow | None = None
        """The joined window it's a column of, or None: a window of its own."""
        self.locked = False
        self.reporting = False
        """Whether the strip offers "Report a problem" (an alpha tester's, 275)."""
        self.unlock_keys = "Ctrl+Alt+L"
        """The hotkey that unlocks, as it is now ("" if another app has it):
        said on locking (`set_locked`), and faintly while locked."""
        self.app_choices: Callable[[], list[AppChoice]] = list
        """The apps this window can caption instead (`views.app_choices`):
        none for a window that isn't one app's (everything, the mic)."""
        self.hovered = False  # the mouse over it, unlocked
        self.band_shown = False
        self.always_shown = False  # never fades, nothing slides (the lab)
        self.clock: Callable[[], float] = lambda: time.monotonic()
        """The arrivals' clock (the lab steps it, to photograph frames)."""
        self.motion = Motion()
        """Arrivals sliding into place (step and slide)."""
        self._slid = False
        """Something slid at the last frame: the next paints it at rest."""
        self._known: set[int] | None = None
        """The captions' keys it has shown (None: none yet - the first
        captions a window opens with don't arrive, they're there)."""
        self._last_caption_at: float | None = None
        """When the last new caption arrived (`clock`): the speech's pace."""
        self._arrived: dict[int, float | None] | None = None
        """When each caption in view arrived as text (`clock`), by its key -
        a preview line from when it became its finished caption; None for
        the ones it opened with. How new each is (the Lab's New for)."""
        self._newness_drawn: tuple[tuple[int, float], ...] = ()
        self.listening = False  # speech heard, its caption not here yet
        self.speaking = False
        """Speech under way now (the session's listening mark): an arrival
        while it is slides quicker - the next caption is on its way."""
        self.notices = Notices()
        self._areas = areas
        self.keys = keys
        self.learner = learner
        self.card = card
        self._selecting: _Selecting | None = None
        self.popover: SettingsPopover | None = None
        self._drag: _Drag | None = None
        self._seen = -1  # the newest line's key when last following
        self._alpha = 1.0
        self._last_activity = 0.0
        self._intro_until: float | None = None
        """When its first seconds end (`introduce`); None once over."""
        self._last_tick = time.monotonic()
        self.pointer: Callable[[], QPoint] = QCursor.pos
        """Where the mouse is on the screen (a test's own)."""
        self.pointed = False
        """The mouse rests on it while it's faded, or shown for that."""
        self.waiting: list[CaptionUpdate] = []
        """Caption updates for it that arrived while the mouse moved over it
        (`receive`), in order."""
        self.pacing = Pacing()
        """Captions arriving together, let in the Lab's gap apart (284)."""
        self.longest_wait = MAX_WAIT_FOR_TEXT_SEC
        """The longest wait for text (decision 0068; `CaptionWindows`'): no
        caption waits longer than this for the gap."""
        self._pace_timer = QTimer(self, singleShot=True)
        self._pace_timer.timeout.connect(self._let_paced)
        self._holding = False
        self._hold_timer = QTimer(self, singleShot=True)
        self._hold_timer.setInterval(round(HOLD_SEC * 1000))
        self._hold_timer.timeout.connect(self.let_in)
        self._pointed_looks = 0
        self.setWindowTitle(_tr("{app} captions").format(app=label.name))

        view = CaptionLines(
            self._sources(),
            choices.target,
            keep=CAPTION_WINDOW_LINES,
            second=self._second(),
            options=self._options(),
            yours=(mic,) if mic else (),
            text_size=choices.text_size,
        )
        self.canvas = Canvas(self, view)
        self.canvas.engine = CaptionLayout(
            caption_style(self.look), lines_kept=view.keep
        )
        self.canvas.ink = self._ink()
        self.marks = CaptionMarks(learner)
        self.marks.set_look(self.look.word_links, self.look.introductions)
        self.canvas.marks = self.marks
        self._build_controls()
        self._build_band()
        self.pill = QPushButton(self)
        self.pill.setObjectName("caption_window.back_to_live")
        self.pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill.setStyleSheet(pill_style())
        self.pill.clicked.connect(self.go_live)
        self.pill.setToolTip(_tr("Back to the newest captions"))
        self.pill.hide()
        self.notice = QLabel(self)
        self.notice.setObjectName("caption_window.notice")
        self.notice.setStyleSheet(notice_style())
        self.notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.notice.hide()

        self._band_in = QTimer(self, singleShot=True, interval=BAND_IN_MS)
        self._band_in.timeout.connect(lambda: self._show_band(True))
        self._band_out = QTimer(self, singleShot=True, interval=BAND_OUT_MS)
        self._band_out.timeout.connect(self._band_left)
        self._still_over = QTimer(self, interval=STILL_OVER_MS)
        self._still_over.timeout.connect(self._check_still_over)
        # the fade, the notice and the listening mark: a frame timer while any
        # of them moves, stopped when nothing does; woken when one is due
        self._tick_timer = QTimer(self, interval=FRAME_MS)
        self._tick_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick_timer.timeout.connect(self._tick)
        self._wake_timer = QTimer(self, singleShot=True)
        self._wake_timer.timeout.connect(self._wake)
        self._point_timer = QTimer(self, interval=POINT_POLL_MS)
        self._point_timer.timeout.connect(self._look_for_pointer)

        self.setGeometry(to_qrect(self._start_place()))
        self._show_labels()
        self._refresh()
        self.introduce()

    # -- what it shows ------------------------------------------------------------------

    @property
    def view(self) -> CaptionLines:
        return self.canvas.view

    @property
    def alpha(self) -> float:
        """How faded it is: 1.0 shown, 0.0 faded out (a joined window shows
        while any column does)."""
        return self._alpha

    def introduce(self) -> None:
        """Shows itself for the fade-after time from now, then fades as an
        idle window does (polyglotic-hq DECISIONS.md #56): when Reset
        position (or joining, or separating) puts it somewhere new, so the
        learner sees that it's there and where. With nothing to read yet it
        shows anyway, waiting for audio (`views.caption_window.shows`)."""
        now = time.monotonic()
        self._intro_until = now + intro_seconds(self.look.fade_after)
        self._last_activity = now
        self.canvas.update()
        self._wake()

    @property
    def mark_showing(self) -> bool:
        """The listening mark: speech heard and its finished caption not
        here yet (in every timing: polyglotic-hq 260), while following
        live."""
        return self.listening and self.view.scroll.following

    def _sources(self) -> tuple[SourceId, ...]:
        if self.choices.show_mic and self.mic is not None:
            return (self.source, self.mic)
        return (self.source,)

    def _second(self) -> Language | None:
        target = self.choices.target
        return self.second_languages.get(target) if target else None

    def _options(self) -> DisplayOptions:
        look = self.look
        return DisplayOptions(
            look.show_original, look.word_links, look.link_detail, preview=look.preview
        )

    def _ink(self) -> Ink:
        look = self.look
        label = readable_on(Ink().label.name(), look.background, LABEL_CONTRAST)
        ink = Ink(QColor(look.original), QColor(look.translation), QColor(label))
        return unfinished_ink(ink, look)

    def _show_labels(self) -> None:
        # each app's colour, readable on the panel: they're picked for dark
        # panels, and Paper's is cream (261)
        panel = self.look.background

        def readable(label: SourceLabel) -> SourceLabel:
            return replace(label, color=readable_on(label.color, panel, LABEL_CONTRAST))

        labels = self.labels
        self.view.set_labels(
            replace(
                labels,
                sources={key: readable(each) for key, each in labels.sources.items()},
                you=readable(labels.you),
                show_source=self.look.show_source,
                show_language=self.look.show_language,
                spoken=lambda heard: spoken_names(str(lang) for lang in heard),
                delay=delay_text if self.look.show_delay else None,
            )
        )

    def receive(self, update: CaptionUpdate) -> bool:
        """A caption update: shown now, or - while the mouse moves over it -
        kept waiting until it leaves or rests (`let_in`), so nothing moves
        under it. True if it changed what shows now."""
        if self._holding:
            if update.source_id in self.view.sources:
                self.waiting.append(update)
            return False
        if self.look.lab.arrival_gap > 0.0 or len(self.pacing):
            if update.source_id not in self.view.sources:
                return False
            self.pacing.add(update, self.clock())
            return self._let_paced()
        if not self.view.apply(update):
            return False
        self.apply_changed(new_caption=True)
        return True

    def _is_new(self, update: CaptionUpdate) -> bool:
        """Whether `update` brings a caption the window doesn't show yet."""
        if update.kind is CaptionKind.WITHDRAWN:
            return False
        shown = {line.caption_id for line in self.view.lines}
        return update.caption_id not in shown and not shown.intersection(
            update.replaces
        )

    def _let_paced(self) -> bool:
        """The updates waiting for the Lab's gap that may come now, shown in
        order; the next woken when it may (`views.pacing`). Not while the
        mouse holds the captions: they go on when it leaves. True if what
        shows changed."""
        self._pace_timer.stop()
        if self._holding:
            return False
        gap, longest, now = self.look.lab.arrival_gap, self.longest_wait, self.clock()
        changed = False
        while (update := self.pacing.next(now, gap, longest, self._is_new)) is not None:
            changed = self.view.apply(update) or changed
        if changed:
            self.apply_changed(new_caption=True)
        wait = self.pacing.wait_for(now, gap, longest)
        if wait is not None:
            self._pace_timer.start(max(1, math.ceil(wait * 1000)))
        return changed

    def _hold(self) -> None:
        """The mouse moves over it: new captions wait, for `HOLD_SEC` more -
        and a caption still sliding into place is there at once, whole: a
        slide stopped where it was left its last rows below the window's
        edge while the mouse stayed (polyglotic-hq 291)."""
        if self.locked:
            return
        self._holding = True
        self._hold_timer.start()
        if self.motion.moving(self.clock()):
            self.motion.stop()
            self.canvas.update()

    def let_in(self) -> None:
        """The captions that waited, shown - the mouse left, or rested."""
        self._holding = False
        self._hold_timer.stop()
        self._wake()
        waiting, self.waiting = self.waiting, []
        if self.look.lab.arrival_gap > 0.0 or len(self.pacing):
            for update in waiting:  # still the gap apart (284)
                self.pacing.add(update, self.clock())
            self._let_paced()
            return
        changed = False
        for update in waiting:
            changed = self.view.apply(update) or changed
        if changed:
            self.apply_changed(new_caption=True)

    def apply_changed(self, new_caption: bool) -> None:
        """The view's captions changed (`CaptionWindows` applied an update)."""
        if new_caption:
            self._last_activity = time.monotonic()
        self._refresh()
        self._note_arrivals()
        self._wake()

    @property
    def sliding(self) -> bool:
        """Whether arrivals slide here now: step and slide, with Windows'
        animation effects on, following the newest, and not the lab's
        photographs. Otherwise they step (`views.arrivals`)."""
        return (
            effective(self.look.arrival, reduced_motion()).slides
            and self.view.scroll.following
            and not self.always_shown
        )

    def age_of(self, key: int, now: float) -> float | None:
        """How long ago (`clock`) caption `key` arrived as text - None for
        one the window opened with, or not shown."""
        arrived = (self._arrived or {}).get(key)
        return None if arrived is None else now - arrived

    def _note_text(self) -> None:
        """When each caption in view arrived as text: a preview line when
        its finished caption came (284's New for)."""
        keys = [line.key for line in self.view.lines if not line.provisional]
        known, now = self._arrived, self.clock()
        if known is None:
            self._arrived = dict.fromkeys(keys)
            return
        self._arrived = {key: known.get(key, now) for key in keys}

    def _newness(self, now: float) -> tuple[bool, float | None]:
        """Whether a caption is fading back now (a frame each tick), and in
        how many seconds one next steps back or starts to - the Lab's New
        for; a repaint when what's new changed since the last."""
        lab = self.look.lab
        if lab.new_for <= 0.0 or self._arrived is None:
            return False, None
        state, fading, due = [], False, None
        for key, arrived in self._arrived.items():
            if arrived is None:
                continue
            age = now - arrived
            new = newness(age, lab)
            if new > 0.0:
                state.append((key, round(new, 3)))
            fading = fading or 0.0 < new < 1.0
            soon = changes_at(age, lab)
            if soon is not None:
                due = soon if due is None else min(due, soon)
        drawn = tuple(state)
        if drawn != self._newness_drawn:
            self._newness_drawn = drawn
            self.canvas.update()
        return fading, due

    def _note_arrivals(self) -> None:
        """The captions new since the last change, and how far the text in
        view rose for them since the last paint: sliding, it slides there
        instead of jumping, and the new lines enter from below, at the
        speech's pace - how long since the last caption, and whether speech
        is still under way. Stepping, they're simply there (F21)."""
        self._note_text()
        keys = {line.key for line in self.view.lines}
        known, self._known = self._known, keys
        if known is None:
            return  # the captions it opens with are there
        new = keys - known
        now = self.clock()
        since = None if self._last_caption_at is None else now - self._last_caption_at
        if new:
            self._last_caption_at = now
        if not self.sliding:
            self.motion.stop()
            self.canvas.at_rest = {}  # what shows next isn't measured from this
            return
        # how far the established text rose: its oldest row in view before
        # and now (the newest line may have changed as well as moved)
        rest, before = self.canvas.rest_rows(), self.canvas.at_rest
        kept = rest.keys() & before.keys()
        risen = before[min(kept)] - rest[min(kept)] if kept else 0.0
        self.canvas.at_rest = rest  # where the next change measures from
        seconds = slide_seconds(pace_of(since, self.speaking))
        most = self.canvas.height()  # more at once can't be followed: at rest
        self.motion.start(now, max(0.0, risen), new, seconds, most_px=most)

    @property
    def arriving(self) -> bool:
        """A caption still sliding into place: the frame timer keeps going."""
        if not self.sliding:
            self.motion.stop()
        return self.motion.moving(self.clock())

    @property
    def bar(self) -> BarInk:
        """Its chrome's colours, on its panel's (`bar_ink`)."""
        return bar_ink(self.look.background)

    def restyle(self) -> None:
        """Its chrome at the text size now - Windows' changed while it was
        open - and in its panel's colours; its captions keep the window's
        own size."""
        self.band.setStyleSheet(band_style(self.bar))
        self.tag.ink = self.bar
        self.notice.setStyleSheet(notice_style())
        self.pill.setStyleSheet(pill_style())
        self._draw_glyphs()
        self.tag.restyle()
        self._fit_band()
        self._place_overlays()  # its notice and Back to live, measured again
        self.canvas.update()

    def set_look(self, look: CaptionLook) -> None:
        if look == self.look:
            return
        recolour = look.background != self.look.background
        self.look = look
        style = caption_style(look)
        if style != self.canvas.engine.style:  # laid out again: a font, link room
            self.canvas.engine = CaptionLayout(style, lines_kept=self.view.keep)
        self.canvas.ink = self._ink()
        self.marks.set_look(look.word_links, look.introductions)
        if recolour:  # its chrome in the panel's colours
            self.restyle()
        self._show_links()
        self.view.set_options(self._options())
        self._show_labels()
        self._refresh()
        self._wake()
        if len(self.pacing):  # a gap changed or gone: those waiting, by it
            self._let_paced()

    def set_labels(self, labels: Mapping[SourceId, SourceLabel], you: str) -> None:
        """Each source's name and colour; `you`: what the mic is called."""
        own = labels.get(self.source)
        if own is not None and own != self.label:
            self.label = own
            self.setWindowTitle(_tr("{app} captions").format(app=own.name))
        mic = labels.get(self.mic) if self.mic else None
        self.labels = Labels(
            dict(labels), you=mic or SourceLabel(you, self.labels.you.color)
        )
        self._show_labels()
        self._sync_controls()  # the title, the tag, "Stop captioning ..."
        self._refresh()

    def set_timing(self, mode: CaptionMode) -> None:
        self.timing = mode
        self.controls[mode.value].setChecked(True)
        if self.settings_open:
            assert self.popover is not None
            self.popover.refresh()

    def entry_changed(self, entry_id: EntryId, texts: tuple[str, ...]) -> None:
        """A Learning action changed one entry (`texts`: its forms): the
        captions holding it repaint - only those, and nothing is laid out."""
        forgotten = self.marks.forget(entry_id, texts)
        for line, _, rect in self.canvas.placed:
            if line.key in forgotten:
                self.canvas.update(rect.toAlignedRect().adjusted(-4, -4, 4, 6))

    def learning_changed(self, what: str) -> None:
        """Learning changed (a word saved, known, added to the deck): the
        marks showing are drawn again - nothing is laid out."""
        if self.marks.learning_changed(what):
            self.canvas.update()

    def set_second_languages(self, seconds: Mapping[Language, Language]) -> None:
        self.second_languages = dict(seconds)
        self.view.set_language(self.choices.target, self._second())
        self._refresh()
        if self.settings_open:
            assert self.popover is not None
            self.popover.refresh()  # its "Lines already in ..." row

    def set_spoken_fallback(self, fallback: bool) -> None:
        """Whether its app is heard as Detect, not as its spoken language
        (`spoken_fallback`)."""
        if fallback != self.spoken_fallback:
            self.spoken_fallback = fallback
            if self.settings_open:
                assert self.popover is not None
                self.popover.refresh()

    def set_listening(self, listening: bool) -> None:
        if listening != self.listening:
            self.listening = listening
            # speech heard, or its mark gone: not quiet - a still mark
            # (reduced motion) doesn't keep the frame timer counting
            self._last_activity = time.monotonic()
            self.canvas.update()
            self._wake()

    def set_paused(self, paused: bool) -> None:
        self.notices.paused = paused
        self._wake()

    def set_minutes_used(self, used: bool) -> None:
        """Today's free minutes used: said on its notice line until there
        are more (after Paused; before the connection's state)."""
        self.notices.minutes_used = used
        self._wake()

    def set_failing(self, failing: bool) -> None:
        """Captions failing on the server: said on its notice line until a
        caption arrives again (after today's free minutes used)."""
        self.notices.failing = failing
        self._wake()

    def set_unstable(self, unstable: bool) -> None:
        """The connection keeps dropping: said on its notice line while it
        listens, until the connection has held again."""
        self.notices.unstable = unstable
        self._wake()

    def set_connection(self, notice: Notice | None, retry_in: float | None) -> None:
        self.notices.state = notice
        now = time.monotonic()
        self.notices.retry_at = now + retry_in if retry_in is not None else None
        self._wake()

    def set_hint(self, text: str | None) -> None:
        """A hint on its notice line while nothing else is said there
        (`Notices.hint`); None: gone."""
        if text == self.notices.hint:
            return
        self.notices.hint = text
        self._show_notice(time.monotonic())
        self._wake()

    def show_notice(self, text: str, seconds: float | None = None) -> None:
        """A brief notice (a server notice; a preset's name on snapping)."""
        now = time.monotonic()
        if seconds is None:
            self.notices.brief(text, now)
        else:
            self.notices.brief(text, now, seconds)
        self._show_notice(now)
        self._wake()

    # -- the learner's choices ---------------------------------------------------------

    def set_text_size(self, size: float) -> None:
        """Live; the window keeps its size."""
        with spans.span("caption_window.text_size"):
            self.view.set_text_size(size)
            if self.view.text_size == self.choices.text_size:
                return
            self.choices = replace(self.choices, text_size=self.view.text_size)
            self._refresh()
            self.canvas.repaint()
            self._tip_text_size()
            if self.popover is not None and self.popover.isVisible():
                self.popover.refresh()  # its text size row says the size
            self.changed.emit()

    def step_text(self, steps: int) -> None:
        self.set_text_size(stepped(self.view.text_size, steps))

    def set_language(self, code: str) -> None:
        """This window's translation language; ORIGINAL_ONLY for none."""
        if code == self.choices.translate_into:
            return
        with spans.span("caption_window.language"):
            self.choices = replace(self.choices, translate_into=code)
            self.view.set_language(self.choices.target, self._second())
            self._refresh()
            self.canvas.repaint()
        self._sync_controls()
        self.changed.emit()
        self.language_changed.emit()

    def set_spoken_language(self, code: str | None) -> None:
        """The language its app's speech is in (one of SPOKEN_LANGUAGES);
        None: Detect."""
        if (code or None) == self.choices.spoken_language:
            return
        self.choices = replace(self.choices, spoken_language=code or None)
        self._sync_controls()
        self.changed.emit()
        self.language_changed.emit()

    def set_second(self, second: str) -> None:
        """Its lines already in its translation language: shown in `second`
        ("": left as they are) - asked of the app, which keeps it by
        language (`second_wanted`)."""
        target = self.choices.target
        if target is not None and second != (self._second() or ""):
            self.second_wanted.emit(str(target), second)

    def set_show_mic(self, on: bool) -> None:
        if on == self.choices.show_mic:
            return
        self.choices = replace(self.choices, show_mic=on)
        self.view.show_sources(self._sources())
        self._sync_controls()
        self.changed.emit()
        self.mic_changed.emit()

    def set_preset(self, preset: Preset) -> None:
        """At a preset's place; the size kept."""
        area = self._area()
        size = Size(self.width(), self.height())
        rect = placement.slot(preset, area, size)
        self.choices = replace(self.choices, preset=preset, geometry=rect)
        self._set_place(rect)
        self.changed.emit()

    def reset_position(self) -> None:
        """Its default slot and size, at Bottom centre."""
        area = self._primary()
        rect = placement.slot(
            Preset.BOTTOM_CENTRE, area, placement.default_size(area), self.index
        )
        self.choices = replace(self.choices, preset=Preset.BOTTOM_CENTRE, geometry=None)
        self._set_place(rect)
        self.introduce()  # shown where it now is (DECISIONS.md #56)
        self.changed.emit()

    def set_locked(self, locked: bool) -> None:
        """Locked: clicks pass through; no band, no hover, no resizing."""
        if locked == self.locked:
            return
        self.locked = locked
        if self.isWindow():  # a column passes clicks through with its window
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, locked)
            if visible:
                self.show()  # changing window flags hides it
        if locked:
            self.hovered = False
            self.let_in()
            self._stop_looking_for_pointer()
            self.canvas.flagged = None
            self._let_go_of_word()
            self._show_band(False)
            self.go_live()
            self.show_notice(locked_text(self.unlock_keys), LOCKED_SEC)
        self.canvas.update()
        self._wake()

    def set_unlock_keys(self, keys: str) -> None:
        """The hotkey that unlocks now ("" if another app has it)."""
        if keys != self.unlock_keys:
            self.unlock_keys = keys
            self.canvas.update()

    def go_live(self) -> None:
        self.view.scroll.follow()
        self._refresh()

    # -- in a joined window -------------------------------------------------------------

    def set_host(self, host: "JoinedWindow | None") -> None:
        """A column of `host` - a child widget, with no window of its own -
        or a window of its own again, at its own place, in its own mode. Not
        shown: the caller shows it. Its captions, scroll-back and layouts
        are the same either way."""
        if host is self.host:
            return
        self.close_settings()
        self._let_go_of_word()
        if self.popover is not None:  # its rows differ: made again when next opened
            self.popover.deleteLater()
            self.popover = None
        self._show_band(False)
        self.hovered = False
        self.let_in()
        self.host = host
        if host is not None:
            self.setParent(host)
        else:
            flags = WINDOW_FLAGS
            if self.locked:
                flags |= Qt.WindowType.WindowTransparentForInput
            self.setParent(None, flags)
            self.setWindowOpacity(self._alpha)
            self.setGeometry(to_qrect(self._start_place()))
        self.host_changed()
        self.introduce()  # joined, or back at its own place: shown there

    def host_changed(self) -> None:
        """Its joined window's columns or mode changed: its strip fitted
        again, and drawn; its notices where they now show."""
        self._fit_band()
        self._refresh()
        self._wake()

    def inner_sides(self) -> tuple[bool, bool]:
        """Whether another column of its joined window is beyond its left
        edge, and beyond its right."""
        host = self.host
        if host is None or self not in host.columns:
            return False, False
        index = host.columns.index(self)
        return index > 0, index < len(host.columns) - 1

    def show_band(self, shown: bool) -> None:
        """Its strip shown or gone: a joined window shows its columns' together."""
        self._show_band(shown)

    def set_hovered(self, hovered: bool) -> None:
        """The mouse over its joined window: the whole panel is drawn."""
        hovered = hovered and not self.locked
        if hovered:
            self._hold()
        else:
            self.let_in()
        if hovered != self.hovered:
            self.hovered = hovered
            self.canvas.update()
            self._wake()

    # -- the controls -------------------------------------------------------------------

    def _action(
        self,
        name: str,
        text: str,
        tip: str = "",
        slot: Callable[[], object] | None = None,
        glyph: Glyph | None = None,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setObjectName(f"caption_window.{name}")
        if glyph is not None:
            self.glyphs[name] = glyph  # the strip's button; the popover shows the text
        action.setToolTip(tip or text)
        action.setCheckable(checkable)
        if slot is not None:
            action.triggered.connect(slot)
        self.controls[name] = action
        return action

    def _choices(self, choices: tuple[tuple[str, str, str], ...]) -> list[QAction]:
        """Checkable actions, one of them checked at a time."""
        group = QActionGroup(self)
        found = []
        for name, text, tip in choices:
            action = self._action(name, text, tip, checkable=True)
            group.addAction(action)
            found.append(action)
        return found

    def _build_controls(self) -> None:
        """Every control of the window, once each, as a named action
        (`controls`): the hover strip draws those named in STRIP, the
        settings popover the rest (`settings_popover.ROWS`)."""
        self.controls: dict[str, QAction] = {}
        self.glyphs: dict[str, Glyph] = {}
        """The controls whose strip button is an icon, not words."""
        self._action(
            "links",
            _tr("Word links"),
            _tr("Word links on or off: words that mean the same share a colour"),
            glyph=Glyph.LINKS,
            checkable=True,
        ).triggered.connect(lambda on: self.links_wanted.emit(bool(on)))
        self._action(
            "smaller",
            "A-",
            _tr("Smaller text (Ctrl+wheel)"),
            lambda: self.step_text(-1),
        )
        self._action(
            "bigger", "A+", _tr("Bigger text (Ctrl+wheel)"), lambda: self.step_text(1)
        )
        self._action(
            "lock",
            _tr("Lock all windows"),
            _tr("Lock - clicks pass through to what's underneath, Ctrl+Alt+L"),
            self.lock_wanted.emit,
            glyph=Glyph.LOCK,
        )
        self._action(
            "settings",
            _tr("Settings"),
            _tr("This window's settings: its translation, timing and more"),
            self.toggle_settings,
            glyph=Glyph.SETTINGS,
        )
        self._action("stop", "", slot=self.stop_wanted.emit, glyph=Glyph.CLOSE)
        self._action(
            "report",
            _tr("Report a problem"),
            _tr(
                "Report a problem - with what was shown and heard, which you check first"
            ),
            self.report_wanted.emit,
            glyph=Glyph.REPORT,
        )
        self._action(
            "show_mic",
            _tr("Show my speech here"),
            _tr("Your microphone is sent to the server only while this is on"),
            checkable=True,
        ).triggered.connect(lambda on: self.set_show_mic(bool(on)))
        for action, timing in zip(
            self._choices(
                tuple((m.value, timing_name(m), timing_tip(m)) for m in CaptionMode)
            ),
            CaptionMode,
            strict=True,
        ):
            action.triggered.connect(
                lambda _=False, t=timing: self.timing_wanted.emit(t.value)
            )
        self._action(
            "all_settings",
            _tr("All caption settings…"),
            _tr(
                "Colours, font, word links, timing and the rest - for every "
                "window, in Settings"
            ),
            self.all_settings_wanted.emit,
        )
        self._action(
            "transcript",
            _tr("Open transcript"),
            _tr("Everything said in this app, to read back, search and save"),
            self.transcript_wanted.emit,
        )
        self._action(
            "join",
            _tr("Join windows"),
            _tr("Every caption window side by side in one window"),
            self.join_wanted.emit,
        )

    def _build_band(self) -> None:
        band = self.band = QWidget(self)
        band.setObjectName("caption_window.band")
        band.setMouseTracking(True)  # the band's gaps pass the mouse to the window
        band.setStyleSheet(band_style(self.bar))
        row = QHBoxLayout(band)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.tag = SourceTag(band)
        self.tag.ink = self.bar
        self.tag.setMouseTracking(True)
        # the label takes what's left, and is what shortens when it's narrow
        self.tag.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row.addWidget(self.tag, 1)
        self.buttons: dict[str, QToolButton] = {}
        for name in STRIP:
            action = self.controls[name]
            button = QToolButton(band)
            button.setObjectName(f"caption_window.band.{name}")
            button.setDefaultAction(action)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMouseTracking(True)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.buttons[name] = button
            row.addWidget(button)
        self._draw_glyphs()
        band.hide()
        self.set_timing(self.timing)
        self._sync_controls()

    def _draw_glyphs(self) -> None:
        """The strip's icon buttons' icons, at the text size now and in its
        panel's colours, each as wide as its glyph was (`glyphs.text_width`)."""
        side = style.px(GLYPH_PX)
        ink = self.bar
        for name, glyph in self.glyphs.items():
            self.controls[name].setIcon(
                icon(glyph, ink.text, side, disabled=ink.disabled)
            )
            if name in self.buttons:
                fit_glyph(self.buttons[name], side)

    def _sync_controls(self) -> None:
        """The controls show the window's choices."""
        self.controls["show_mic"].setChecked(self.choices.show_mic)
        self._show_links()
        stop = _tr("Stop captioning {app}").format(app=self.label.name)
        self.controls["stop"].setText(stop)
        self.controls["stop"].setToolTip(stop)
        self._name_buttons()
        self._fit_band()
        if self.popover is not None and self.popover.isVisible():
            self.popover.refresh()

    def _show_links(self) -> None:
        """The strip's word links button: on or off. With what was said
        hidden it can change nothing - a link joins a word of what was said
        to its translation - so it's off to clicks and says why, in Look's
        words (249's F9; polyglotic-hq 258)."""
        links = self.controls["links"]
        links.setChecked(self.look.word_links is not WordLinks.OFF)
        links.setEnabled(self.look.show_original)
        links.setToolTip(
            _tr("Word links on or off: words that mean the same share a colour")
            if self.look.show_original
            else _tr(
                "Word links need what was said: turn on “Show the original above "
                "the translation” in Settings"
            )
        )

    def _name_buttons(self) -> None:
        """What a screen reader says for each of the strip's buttons: its
        action's words, never nothing for an icon."""
        for name, button in self.buttons.items():
            button.setAccessibleName(self.controls[name].text())

    def set_reporting(self, on: bool) -> None:
        """Show "Report a problem" on the strip: an alpha tester's (275)."""
        if on != self.reporting:
            self.reporting = on
            self._fit_band()

    def _fit_band(self) -> None:
        note = _tr("Original only") if self.choices.target is None else ""
        self.tag.show_label(self.label, self.choices.show_mic, note)
        # a column: lock is the joined window's, at the right of the last
        self.buttons["lock"].setVisible(self.host is None)
        self.buttons["report"].setVisible(self.reporting)
        room = self.host.controls_width(self) if self.host is not None else 0
        # inside the corner zones, so every edge still resizes
        self.band.setGeometry(
            placement.CORNER_ZONE,
            placement.EDGE_ZONE - 1,
            max(0, self.width() - 2 * placement.CORNER_ZONE - room),
            band_height() - placement.EDGE_ZONE,
        )

    # -- the settings popover ----------------------------------------------------------

    @property
    def settings_open(self) -> bool:
        return self.popover is not None and self.popover.isVisible()

    def toggle_settings(self) -> None:
        """The settings popover, beside the settings button - or closed."""
        if self.settings_open:
            self.close_settings()
            return
        if self.locked or not self.isVisible():
            return
        with spans.span("caption_window.settings"):
            if self.popover is None:
                rows = COLUMN_ROWS if self.host is not None else ROWS
                self.popover = SettingsPopover(self, self.keys, rows)
            button = self.buttons["settings"]
            anchor = QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
            self.popover.open_beside(anchor)

    def _on_label(self, event: QMouseEvent) -> bool:
        """A click on the strip's label (the app's name)."""
        if not self.band_shown:
            return False
        at = self.tag.mapFrom(self, event.position().toPoint())
        return self.tag.rect().contains(at)

    def pick_app(self) -> None:
        """Its settings, with the apps it can caption open (F12, 249): what
        a click on the strip's label opens - a window of one app's only."""
        if not self.app_choices():
            return
        if not self.settings_open:
            self.toggle_settings()
        popover = self.popover
        if popover is not None and popover.isVisible() and popover.apps.isHidden():
            popover._toggle_apps()

    def close_settings(self) -> None:
        if self.popover is not None:
            self.popover.close()

    def area_at(self, rect: QRect) -> Rect:
        """The work area holding `rect` (global), or this window's."""
        return placement.area_for(to_rect(rect), self._areas()) or self._area()

    def _show_band(self, shown: bool) -> None:
        shown = shown and not self.locked
        if shown == self.band_shown:
            return
        self.band_shown = shown
        self.band.setVisible(shown)
        if shown:
            self.band.raise_()
            self._tip_text_size()
        else:
            self.close_settings()
        self._place_overlays()
        self.canvas.update()
        self._wake()

    def _band_left(self) -> None:
        if self.settings_open:  # the strip stays while its popover is open
            self._band_out.start()
            return
        self.hovered = False
        self._show_band(False)

    def _tip_text_size(self) -> None:
        few = self.canvas.rows_that_fit() <= FEW_ROWS
        self.controls["bigger"].setToolTip(
            _tr("Drag the top edge for more lines")
            if few
            else _tr("Bigger text (Ctrl+wheel)")
        )

    def showEvent(self, event: QShowEvent) -> None:
        self._wake()  # faded when it was hidden: it looks for the mouse again

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() is QEvent.Type.WindowStateChange and self.isMinimized():
            # Windows minimised it ("show desktop", another app): it has no
            # taskbar button to come back from, so it's back at once
            # (polyglotic-hq 272: "the caption window will minimize")
            log.info("caption window %d minimised by Windows: restored", self.index)
            QTimer.singleShot(0, self, restore_minimised(self))

    def hideEvent(self, event: QHideEvent) -> None:
        self.let_in()
        self._stop_looking_for_pointer()
        self.close_settings()  # hidden (Ctrl+Alt+H) or closed: so is its popover
        self._let_go_of_word()
        if self.card is not None:
            self.card.closed_with(self)  # and a card pinned from it

    # -- where it is --------------------------------------------------------------------

    def _primary(self) -> Rect:
        areas = self._areas()
        return areas[0] if areas else Rect(0, 0, 1920, 1040)

    def _area(self, rect: Rect | None = None) -> Rect:
        found = placement.area_for(rect or self._place(), self._areas())
        return found or self._primary()

    def _place(self) -> Rect:
        return to_rect(self.geometry())

    def _start_place(self) -> Rect:
        area = self._primary()
        choices = self.choices
        preset = (
            choices.preset
            if choices.preset is not Preset.CUSTOM
            else Preset.BOTTOM_CENTRE
        )
        default = placement.slot(preset, area, placement.default_size(area), self.index)
        return placement.at_start(
            choices.geometry, choices.preset, self._areas(), default
        )

    def _set_place(self, rect: Rect) -> None:
        if self.host is not None:  # a column: the joined window has the place
            return
        if rect != self._place():
            self.setGeometry(to_qrect(rect))

    def _minimum(self) -> Size:
        return least_size(MIN_PANEL)

    # -- keeping it in step -------------------------------------------------------------

    def _refresh(self) -> None:
        """After the view changed: Back to live, a repaint."""
        lines = self.view.lines
        if self.view.scroll.following or not lines:
            self._seen = lines[-1].key if lines else -1
            self.pill.hide()
        else:
            new = sum(1 for line in lines if line.key > self._seen)
            self.pill.setText(
                _tr("Back to live · {n} new").format(n=new)
                if new
                else _tr("Back to live")
            )
            self.pill.show()
        self._place_overlays()
        self.canvas.changed()
        self.canvas.update()

    def _place_overlays(self) -> None:
        if self.pill.isVisible():
            self.pill.adjustSize()
            self.pill.move(
                (self.width() - self.pill.width()) // 2,
                self.height() - self.pill.height() - 6,
            )
            self.pill.raise_()
        if self.host is not None:
            self.host.place_notice()
        elif self.notice.isVisible():
            self.notice.adjustSize()
            top = band_height() + 4 if self.band_shown else 6
            self.notice.move((self.width() - self.notice.width()) // 2, top)
            self.notice.raise_()

    def _notice_line(self) -> QLabel | None:
        """Where its notices show: its own line - or, in a joined window,
        the window's one line, which its first column speaks for (every
        window hears the same notices)."""
        host = self.host
        if host is None:
            return self.notice
        return host.notice if host.columns and host.columns[0] is self else None

    def _show_notice(self, now: float) -> None:
        notice, text = self.notices.showing(now)
        if notice is not None:
            text = notice_text(notice, self.notices.retry_in(now))
        line = self._notice_line()
        if line is not self.notice:
            self.notice.hide()
        if line is None:
            return
        if text is None:
            line.hide()
            return
        if text != line.text():
            line.setText(text)
        line.show()
        self._place_overlays()

    def _wake(self) -> None:
        if not self._tick_timer.isActive():
            self._wake_timer.stop()
            self._last_tick = time.monotonic()
            self._tick_timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        moving = False
        if self.mark_showing:
            self._last_activity = now  # speech heard: not quiet
            if not reduced_motion():
                moving = True  # the bar sweeps; still, it needs no frames
                if self.canvas.mark_rect is not None:
                    self.canvas.update(self.canvas.mark_rect)
        arriving = self.arriving
        if arriving or self._slid:  # a new caption sliding in: a frame each tick -
            # and one more once it's at rest: the last frame painted may be a
            # slow paint's before the end, with the newest rows still below
            # the clip (the user's "translation cut off at the bottom", 272)
            moving = moving or arriving
            self.canvas.update()
        self._slid = arriving
        fading, new_due = self._newness(self.clock())  # the Lab's New for
        moving = moving or fading
        self._show_notice(now)
        fade_after = self.look.fade_after
        line = self._notice_line()
        awake = (
            self.always_shown
            or (line is not None and line.isVisible())
            or self.band_shown
            or self.hovered
            or self.pointed
            or not self.view.scroll.following
            or self.mark_showing
            or self.notices.paused
        )
        quiet = now - self._last_activity
        intro = self._intro_until
        introducing = intro is not None and now < intro
        target = (
            1.0
            if shows(
                awake=awake,
                introducing=introducing,
                empty=not self.view.lines,
                quiet=quiet,
                fade_after=fade_after,
            )
            else 0.0
        )
        if self._alpha != target:
            step = dt / FADE_SEC
            if abs(target - self._alpha) <= max(step, 0.001):
                self._alpha = target
            else:
                self._alpha += step if target > self._alpha else -step
            if self.host is not None:
                self.host.follow_alpha()  # it fades when every column would
            else:
                self.setWindowOpacity(self._alpha)
            if self._alpha == 0.0 and fade_after is None:  # gone, fading off
                log.info(
                    "caption window %d faded out with fading off: %s",
                    self.index,
                    "nothing to read" if not self.view.lines else "unexpected",
                )
            moving = moving or self._alpha != target
        if intro is not None and not introducing and self._alpha == 0.0:
            self._intro_until = None  # its first seconds are over
            self.canvas.update()
        if moving:
            return
        self._tick_timer.stop()  # still: woken when the next thing is due
        faded = self._alpha < 1.0 and not self.locked and self.isVisible()
        if faded and not self._point_timer.isActive():  # it looks for the mouse
            self._pointed_looks = 0
            self._point_timer.start()
        due = []
        upcoming = self.notices.next_change(now)
        if upcoming is not None:
            due.append(upcoming)
        if fade_after and self._alpha > 0.0 and not awake:
            due.append(self._last_activity + fade_after)
        if intro is not None and introducing and not awake:
            due.append(intro)
        if new_due is not None:  # a caption steps back, or starts to
            due.append(now + new_due + 0.001)
        later = [at - now for at in due if at > now]
        if later:
            self._wake_timer.start(max(1, math.ceil(min(later) * 1000)))

    def _look_for_pointer(self) -> None:
        """Faded - or shown because the mouse rests on it - whether the
        mouse is on it now: Windows passes the mouse through a faded window,
        so it hears nothing of it. Resting `POINT_REST` looks brings it
        back; leaving lets it fade again."""
        if self.locked or not self.isVisible():
            self._stop_looking_for_pointer()
            return
        on = self.window().geometry().contains(self.pointer())
        self._pointed_looks = self._pointed_looks + 1 if on else 0
        pointed = self._pointed_looks >= POINT_REST
        if pointed != self.pointed:
            self.pointed = pointed
            self._wake()
        if not pointed and self._alpha >= 1.0:
            self._point_timer.stop()  # shown for something else: Qt hears the mouse

    def _stop_looking_for_pointer(self) -> None:
        self._point_timer.stop()
        self._pointed_looks = 0
        self.pointed = False

    # -- events -------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.canvas.setGeometry(self.rect())
        self._fit_band()
        self._place_overlays()

    def enterEvent(self, event: QEnterEvent) -> None:
        self.came_over()

    def came_over(self) -> None:
        """The mouse came over it: its band shows after BAND_IN_MS, new
        captions wait. Also from a mouse move while not hovered - Windows
        can lose the mouse's arrival: after locking and unlocking it, Qt
        heard no enter again until the app restarted (polyglotic-hq 272) -
        and while hovered it checks the mouse is still there
        (`_check_still_over`): the leave can be lost the same way."""
        if self.locked or self.host is not None:  # a column: the window's band
            return
        self.hovered = True
        self._hold()
        self._band_out.stop()
        if not self.band_shown:
            self._band_in.start()
        self._still_over.start()
        self.canvas.update()
        self._wake()

    def _check_still_over(self) -> None:
        """While hovered: the mouse left without Qt saying so - as if it had."""
        if not self.hovered or self.locked or not self.isVisible():
            self._still_over.stop()
        elif not self.geometry().contains(self.pointer()):
            self._still_over.stop()
            self.leaveEvent(None)

    def leaveEvent(self, event: object) -> None:
        self._still_over.stop()
        if self.host is None:  # a column: its joined window lets them in
            self.let_in()
        self._band_in.stop()
        if self._drag is None and self.host is None:
            self._band_out.start()
        if self.canvas.flagged is not None:
            self.canvas.flagged = None
            self.canvas.update()
        if self._selecting is None:
            self._unhover()

    def _edges(self, pos: QPointF) -> Edge:
        if self.host is not None:  # a column: the joined window's edges
            return self.host.edges_at(pos + QPointF(self.x(), self.y()))
        return placement.edges_at(pos.x(), pos.y(), self.width(), self.height())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.locked:
            return
        pos = event.position()
        flag = self.canvas.flag_rect
        if flag is not None and flag.contains(pos) and self.canvas.flagged is not None:
            self.looks_wrong.emit(str(self.canvas.flagged.caption_id))
            return
        divider = self._divider(pos)
        if divider is not None and self.host is not None:  # a column's width
            self.host.press_divider(divider, event.globalPosition())
            return
        edges = self._edges(pos)
        word = self._marked_at(pos) if not edges else None
        if word is not None:  # a click looks it up, a drag selects a phrase
            index = self.canvas.hit(pos)
            self._selecting = _Selecting(word, index[3] if index else word.start)
            self._unhover()
            return
        if self.host is not None:  # a column: the joined window moves or resizes
            self.host.press(edges, event.globalPosition())
            return
        self._drag = _Drag(edges, event.globalPosition(), self._place())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.hovered and self._drag is None:  # its arrival lost (272)
            if self.host is None:
                self.came_over()
            elif not self.host.dragging:
                self.host.came_over()
        if self.hovered or self.host is not None:
            self._hold()
        if self._selecting is not None:
            self._select_to(event.position())
            return
        if self.host is not None and self.host.dragging:
            self.host.drag_to(event.globalPosition())
            return
        drag = self._drag
        if drag is None:
            self._hover(event.position())
            return
        delta = event.globalPosition() - drag.origin
        dx, dy = round(delta.x()), round(delta.y())
        if not drag.moved and abs(dx) + abs(dy) < 3:
            return
        drag.moved = True
        with spans.span("caption_window.drag_step"):
            if drag.edges:
                self.resize_by(drag, dx, dy)
            else:
                self.move_by(drag, dx, dy)

    def resize_by(self, drag: _Drag, dx: int, dy: int) -> None:
        """A resize step: the dragged edges moved, re-laid out in this frame."""
        area = self._area(drag.start)
        rect = placement.resized(
            drag.start, drag.edges, dx, dy, self.choices.preset, self._minimum(), area
        )
        self._set_place(rect)
        self.canvas.repaint()

    def move_by(self, drag: _Drag, dx: int, dy: int) -> None:
        """A move step: kept on the screen; near a preset, snapped to it."""
        raw = Rect(
            drag.start.x + dx, drag.start.y + dy, drag.start.width, drag.start.height
        )
        area = self._area(raw)
        rect, preset = placement.snapped(
            placement.moved(drag.start, dx, dy, area), area
        )
        if preset is not Preset.CUSTOM and preset is not drag.snapped:
            self.show_notice(preset_name(preset), seconds=1.0)
        drag.snapped = preset
        self._set_place(rect)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._selecting is not None:
            self._pin_selected()
            return
        if self.host is not None:
            self.host.release()
            return
        drag, self._drag = self._drag, None
        if drag is None or not drag.moved:
            if drag is not None and not drag.edges and self._on_label(event):
                self.pick_app()  # the strip's label: which app (F12)
            return
        place = self._place()
        if drag.edges:
            self.choices = replace(self.choices, geometry=place)  # the preset kept
        else:
            self.choices = replace(self.choices, preset=drag.snapped, geometry=place)
        self._refresh()
        self.changed.emit()

    def _divider(self, pos: QPointF) -> int | None:
        """A column: the joined window's divider at `pos`, if any (284)."""
        if self.host is None:
            return None
        return self.host.divider_at(pos + QPointF(self.x(), self.y()))

    def _hover(self, pos: QPointF) -> None:
        if self.locked:
            return
        if self._divider(pos) is not None:  # the divider beside: drag it
            self.setCursor(Qt.CursorShape.SplitHCursor)
            self._unhover()
            return
        edges = self._edges(pos)
        flagged = None
        if not edges:
            for line, _, rect in self.canvas.placed:
                if rect.top() <= pos.y() < rect.bottom() and not line.live:
                    flagged = line
                    break
        if flagged is not self.canvas.flagged:
            before = self.canvas.flagged
            self.canvas.flagged = flagged
            if self.canvas.flag_rect is not None:
                self.canvas.update(
                    self.canvas.flag_rect.toAlignedRect().adjusted(-2, -2, 2, 2)
                )
            self._repaint_lines(before, flagged)
        flag = self.canvas.flag_rect
        on_flag = flag is not None and flag.contains(pos)
        word = self._marked_at(pos) if not edges and not on_flag else None
        if word is None:
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if on_flag
                else _CURSORS.get(edges, Qt.CursorShape.SizeAllCursor)
            )
            self._unhover()
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if word != self.canvas.hovered:
            was = self.canvas.hovered
            self.canvas.hovered = word
            self._repaint_lines(was, word)
        card = self.card
        if card is None:
            return
        key = (word.key, word.row, word.start, word.end)
        if card.showing(key):  # the same word: nothing new to look up
            card.hover_kept()
            return
        if card.pinned:
            return
        found = self.word_at(word)
        if found is not None:
            card.hover(found)

    # -- the lookup ---------------------------------------------------------------------

    def _marked_at(self, pos: QPointF) -> Marked | None:
        """The word under `pos`, by the word split - None for none."""
        learner = self.learner
        hit = self.canvas.hit(pos)
        if learner is None or hit is None:
            return None
        line, row, _, index = hit
        text = row.row.text
        if not 0 <= index < len(text):
            return None
        span = learner.word_at(text, index, row.row.language)
        if span is None or span[0] >= span[1]:
            return None
        return Marked(line.key, row.index, *span)

    def word_at(self, marked: Marked) -> WordAt | None:
        """What the lookup needs for `marked`: the text, its context (the
        caption's row and its translation) and where it is on the screen -
        None if its line isn't drawn any more."""
        shown = self.canvas.shown_row(marked.key, marked.row)
        if shown is None:
            return None
        line, row, origin = shown
        text = row.row.text
        caption = self.view.caption(line.key)
        context = (
            lookup_context(text, clause_versions(caption, row.row.clause))
            if caption is not None and row.row.clause < len(caption.clauses)
            else LookupContext(text)
        )
        rects = span_rects(row.layout, marked.start, marked.end)
        if not rects:
            return None
        box = rects[0]
        for rect in rects[1:]:
            box = box.united(rect)
        word = self._on_screen(box.translated(origin))
        reading = self._on_screen(
            self.canvas.line_rect(row, origin, marked.start, marked.end)
        )
        return WordAt(
            text[marked.start : marked.end],
            context,
            (marked.start, marked.end),
            word,
            reading,
            self.area_at(QRect(word.x, word.y, word.width, word.height)),
            (marked.key, marked.row, marked.start, marked.end),
            row.row.language,
        )

    def _on_screen(self, rect: QRectF) -> Rect:
        top_left = self.canvas.mapToGlobal(rect.topLeft().toPoint())
        return Rect(
            top_left.x(), top_left.y(), round(rect.width()), round(rect.height())
        )

    def _repaint_lines(self, *changed: Marked | Line | None) -> None:
        """The lines a hover change touched, repainted - those alone, not
        the window: a mouse move across words with thick arrows painted
        the whole window each time, up to 487 ms on the user's PC
        (polyglotic-hq 272)."""
        for each in changed:
            if each is None:
                continue
            area = self.canvas.line_area(each.key)
            if area is None:  # not drawn where it was: all of it, to be sure
                self.canvas.update()
                return
            self.canvas.update(area)

    def _unhover(self) -> None:
        if self.canvas.hovered is not None:
            before = self.canvas.hovered
            self.canvas.hovered = None
            self._repaint_lines(before)
        if self.card is not None:
            self.card.unhover()

    def _let_go_of_word(self) -> None:
        """No word marked, nothing being selected (locked, hidden, closed)."""
        self._selecting = None
        self.canvas.selection = None
        self._unhover()

    def _select_to(self, pos: QPointF) -> None:
        """A drag from a word: the phrase from it to `pos`, within its row -
        snapped to whole words. Still on the first word: still a click."""
        selecting = self._selecting
        assert selecting is not None
        word = selecting.word
        shown = self.canvas.shown_row(word.key, word.row)
        if shown is None or self.learner is None:
            return
        _, row, origin = shown
        text = row.row.text
        current = self.canvas.char_at(row, origin, pos)
        low, high = sorted((selecting.anchor, current))
        start, end = self._snapped(text, low, high + 1, row.row.language)
        if self.canvas.selection is None and (start, end) == (word.start, word.end):
            return
        selection = Marked(word.key, word.row, start, end)
        if selection != self.canvas.selection:
            self.canvas.selection = selection
            self.setCursor(Qt.CursorShape.IBeamCursor)
            self.canvas.update()

    def _snapped(
        self, text: str, start: int, end: int, language: str | None = None
    ) -> tuple[int, int]:
        """`[start, end)` widened to whole words at both ends."""
        assert self.learner is not None
        first = self.learner.word_at(text, start, language)
        last = self.learner.word_at(text, end - 1, language)
        return (first[0] if first else start), (last[1] if last else end)

    def _pin_selected(self) -> None:
        """The phrase dragged across - trimmed of spaces and punctuation at
        its ends - or, after a plain click, the word: pinned."""
        selecting, self._selecting = self._selecting, None
        selection, self.canvas.selection = self.canvas.selection, None
        assert selecting is not None
        marked = selecting.word
        if selection is not None:
            shown = self.canvas.shown_row(selection.key, selection.row)
            text = shown[1].row.text if shown else ""
            start, end = selection.start, selection.end
            while start < end and not _wordlike(text[start]):
                start += 1
            while end > start and not _wordlike(text[end - 1]):
                end -= 1
            if start < end:  # else: only punctuation - the word pressed on
                marked = Marked(selection.key, selection.row, start, end)
            self.canvas.update()
        found = self.word_at(marked)
        if found is not None and self.card is not None:
            self.card.pin(found, self)

    def wheelEvent(self, event: QWheelEvent) -> None:
        notches = event.angleDelta().y() / 120
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if notches:
                self.step_text(1 if notches > 0 else -1)
        elif not self.locked:
            with spans.span("caption_window.scroll_step"):
                self.canvas.scroll_by(notches * 48)
                self._refresh()
        event.accept()
