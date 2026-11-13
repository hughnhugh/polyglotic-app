"""The new interface's small standard controls: a card, a setting's row, a
row of choices, a switch, a colour choice, a status dot and a button that
opens one of our web pages in the browser.

Like today's `ui.widgets` (which this package can't import - decision
0031), with the same object names, so a window's stylesheet
(`style.stylesheet`) dresses them; nothing has a fixed width, so a card
fits a 320 px popover and a 720 px column alike (109's 10.5). The switch
and the dot paint themselves in the theme's colours at paint time.
"""

import math
import time
from collections.abc import Sequence

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.ui_next import style


def page_button(text: str, url: str, name: str) -> QPushButton:
    """A button that opens `url` - a page of our website, such as the privacy
    notice - in the learner's browser; never shown inside the app, so the
    app and the site can't say different things (polyglotic-hq 185). Today's
    dialogs have the same, `ui.widgets.page_button`."""
    button = QPushButton(text)
    button.setObjectName(name)
    button.setProperty("url", url)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(QApplication.translate("Pages", "Opens in your browser"))
    button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return button


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    """A label; `role` is its object name for the stylesheet (`Dim`,
    `Faint`, `CardTitle`, ...)."""
    found = QLabel(text)
    if role:
        found.setObjectName(role)
    found.setWordWrap(wrap)
    return found


class Card(QFrame):
    """A titled card: a column of rows."""

    def __init__(
        self, title: str = "", subtitle: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(14, 14, 14, 14)
        self.column.setSpacing(10)
        self.title = label(title, "CardTitle") if title else None
        if self.title is not None:
            self.column.addWidget(self.title)
        if subtitle:
            self.column.addWidget(label(subtitle, "Dim", wrap=True))

    def add(self, item: QWidget | QHBoxLayout | QVBoxLayout) -> None:
        if isinstance(item, QWidget):
            self.column.addWidget(item)
        else:
            self.column.addLayout(item)


class Row(QWidget):
    """One setting: its title and what it does, with its control under them
    (`beside`: at their right), so the row fits any width. Its words start
    at INSET, as a `SwitchRow`'s do. `tip`: what it does when the title
    says enough to use it - on hover and to a screen reader, not under it
    (151's P2, 176: one sentence at most under a control)."""

    def __init__(
        self,
        title: str,
        detail: str,
        control: QWidget,
        beside: bool = False,
        tip: str = "",
    ) -> None:
        super().__init__()
        self.control = control
        if tip:
            tipped(self, control, tip)
        words = QVBoxLayout()
        words.setContentsMargins(1, 0, 0, 0)  # with the control's border: INSET
        words.setSpacing(2)
        self.title = label(title, "RowTitle", wrap=True)
        words.addWidget(self.title)
        self.detail = label(detail, "Faint", wrap=True)
        if not detail:  # hidden, never shown: shown before it has a parent, a
            self.detail.hide()  # label is a window of its own for a moment
        words.addWidget(self.detail)
        if beside:
            line = QHBoxLayout(self)
            line.setContentsMargins(INSET - 1, 0, 0, 0)
            line.setSpacing(12)
            line.addLayout(words, 1)
            line.addWidget(control, 0, Qt.AlignmentFlag.AlignTop)
        else:
            column = QVBoxLayout(self)
            column.setContentsMargins(INSET - 1, 0, 0, 0)
            column.setSpacing(6)
            column.addLayout(words)
            column.addWidget(control)


class Segmented(QFrame):
    """A row of choices, one at a time - a handful that should all stay in
    view rather than in a dropdown. Each choice is a Tab stop: the one-at-a-
    time rule is kept here, not by an exclusive button group (which Qt
    makes a single Tab stop, reached only at its checked choice)."""

    changed = Signal(object)

    def __init__(
        self, options: Sequence[tuple[object, str]], value: object = None
    ) -> None:
        super().__init__()
        self.setProperty("segmented", True)  # its name is free for tests
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._values = [v for v, _ in options]
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.buttons: list[QPushButton] = []
        for index, (_, text) in enumerate(options):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self._clicked(i))
            self.buttons.append(button)
            row.addWidget(button)
        self.set_value(value)

    def _clicked(self, index: int) -> None:
        self.set_value(self._values[index])  # a click on the chosen one keeps it
        self.changed.emit(self._values[index])

    def set_value(self, value: object) -> None:
        if value not in self._values:
            return
        chosen = self._values.index(value)
        for index, button in enumerate(self.buttons):
            button.setChecked(index == chosen)

    def value(self) -> object:
        for index, button in enumerate(self.buttons):
            if button.isChecked():
                return self._values[index]
        return None

    def choose(self, value: object) -> None:
        """Picks `value` as a click would."""
        self.buttons[self._values.index(value)].click()


INSET = 9
"""Where every row's words start inside its card or popover: a button's
border and padding - so titles, notes, buttons and ticked choices line up."""
TICK = 16
"""The column a ticked choice's tick sits in, before its words (at 100 %
text size: it grows with the tick, `style.px`)."""
SWITCH = (28, 16)
"""The on / off switch's size: on, it's filled with the accent."""


def _ink(given: tuple[str, ...] | None, tokens: tuple[str, ...]) -> list[QColor]:
    """The colours given, or the theme's now."""
    if given is not None:
        return [QColor(c) for c in given]
    theme = style.current()
    return [QColor(theme[t]) for t in tokens]


class TickButton(QPushButton):
    """A row button: a checked, checkable one with the property `tick` has
    a tick in the column before its words (`TICK`), so ticked and unticked
    rows line up. `ink`: (accent, dim) - the theme's if not given."""

    def __init__(
        self, parent: QWidget | None = None, ink: tuple[str, str] | None = None
    ) -> None:
        super().__init__(parent)
        self.ink = ink

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not (self.property("tick") and self.isCheckable() and self.isChecked()):
            return
        accent, dim = _ink(self.ink, ("ACCENT", "TEXT_DIM"))
        painter = QPainter(self)
        painter.setPen(accent if self.isEnabled() else dim)
        painter.drawText(
            QRectF(INSET, 0, style.px(TICK), self.height()),
            Qt.AlignmentFlag.AlignVCenter,
            "✓",
        )
        painter.end()


class SwitchButton(QPushButton):
    """A row button with an on / off switch at its right: on, filled with
    the accent and the knob at the right. The whole row is the switch.
    `ink`: (accent, dim, the knob on the accent) - the theme's if not given."""

    def __init__(
        self, parent: QWidget | None = None, ink: tuple[str, str, str] | None = None
    ) -> None:
        super().__init__(parent)
        self.ink = ink
        self.setCheckable(True)
        self.setProperty("switch", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_quietly(self, on: bool) -> None:
        """Shows `on` without saying it changed (it was changed elsewhere)."""
        blocked = self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(blocked)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        accent, dim, knob_on = _ink(self.ink, ("ACCENT", "TEXT_DIM", "SURFACE"))
        if not self.isEnabled():
            accent.setAlphaF(0.4)
        width, height = SWITCH
        track = QRectF(
            self.width() - width - INSET, (self.height() - height) / 2, width, height
        )
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(accent if on else dim)
        painter.setBrush(accent if on else QColor(0, 0, 0, 0))
        painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        knob = height - 6
        x = track.right() - 3 - knob if on else track.left() + 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_on if on else dim)
        painter.drawEllipse(QRectF(x, track.top() + 3, knob, knob))
        painter.end()


def tipped(row: QWidget, control: QWidget, tip: str) -> None:
    """`tip` on `row` and its control - or, when the control holds others
    (a slider and its value), each of them that takes the focus: on hover,
    and to a screen reader."""
    row.setToolTip(tip)
    held = [
        w
        for w in control.findChildren(QWidget)
        if w.focusPolicy() is not Qt.FocusPolicy.NoFocus
    ]
    for each in [control, *held]:
        if not each.toolTip():
            each.setToolTip(tip)
        if not each.accessibleDescription():
            each.setAccessibleDescription(tip)


class SwitchRow(QWidget):
    """A setting that is on or off: its title on a row-wide switch
    (`SwitchButton`), and what it does under it - or, with `tip`, on hover
    (as `Row`'s)."""

    def __init__(self, title: str, detail: str, name: str, tip: str = "") -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)
        self.switch = SwitchButton(self)
        self.switch.setObjectName(name)
        self.switch.setText(title)
        if tip:
            tipped(self, self.switch, tip)
        column.addWidget(self.switch)
        self.detail = label(detail, "Faint", wrap=True)
        self.detail.setContentsMargins(INSET, 0, SWITCH[0] + INSET, 0)
        if not detail:  # hidden, never shown: shown before it has a parent, a
            self.detail.hide()  # label is a window of its own for a moment
        column.addWidget(self.detail)


def swatch(colour: str, size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(128, 128, 128, 160))
    painter.setBrush(QColor(colour))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class ColourChoice(QToolButton):
    """A colour, chosen from a few that read well: its swatch, and a menu of
    the others."""

    chosen = Signal(str)

    def __init__(self, choices: Sequence[str], colour: str, name: str) -> None:
        super().__init__()
        self.setObjectName(name)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.colour = ""
        menu = QMenu(self)
        for each in choices:
            action = menu.addAction(swatch(each), "")
            action.setObjectName(f"{name}.{each}")
            action.triggered.connect(lambda _=False, c=each: self.chosen.emit(c))
        self.setMenu(menu)
        self.show_colour(colour)

    def show_colour(self, colour: str) -> None:
        if colour != self.colour:
            self.colour = colour
            self.setIcon(swatch(colour))


PULSE_SEC = 1.2
"""One breath of a pulsing dot: from full to faint and back."""
PULSE_MS = 50
"""How often a pulsing dot repaints (20 a second: a 14 px dot, cheap)."""


def pulse_opacity(seconds: float) -> float:
    """A pulsing dot's opacity `seconds` into its pulse: 1.0 down to 0.35
    and back, smoothly, once every PULSE_SEC."""
    return 0.675 + 0.325 * math.cos(2 * math.pi * seconds / PULSE_SEC)


class StatusDot(QWidget):
    """A small dot in one of the theme's colours (`SUCCESS`, `WARNING`, ...)
    - or a colour of its own. Pulsing (`set_pulsing`), it breathes: the
    app is doing something (connecting)."""

    def __init__(self, token: str = "TEXT_FAINT", size: int = 10) -> None:
        super().__init__()
        self.token = token
        self.setFixedSize(size, size)
        self.opacity = 1.0
        self._pulse_started = 0.0
        self._pulse = QTimer(self, interval=PULSE_MS)
        self._pulse.timeout.connect(self._breathe)

    def set_pulsing(self, on: bool) -> None:
        if on == self._pulse.isActive():
            return
        if on:
            self._pulse_started = time.monotonic()
            self._pulse.start()
        else:
            self._pulse.stop()
            self.opacity = 1.0
            self.update()

    @property
    def pulsing(self) -> bool:
        return self._pulse.isActive()

    def _breathe(self) -> None:
        self.opacity = pulse_opacity(time.monotonic() - self._pulse_started)
        self.update()

    def set_token(self, token: str) -> None:
        if token != self.token:
            self.token = token
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        token = self.token
        colour = token if token.startswith("#") else style.current()[token]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colour))
        painter.setOpacity(self.opacity)  # alpha only: nothing moves
        painter.drawEllipse(self.rect())
        painter.end()
