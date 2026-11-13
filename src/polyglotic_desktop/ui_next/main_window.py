"""W4, the new main window: a sidebar and one page at a time (polyglotic-hq
project 109's structure, sections 7 and 10.5; wireframes 6 and 6.1).

- **The sidebar** (200 px; 184 at the window's minimum): the logo; Home,
  Words, Account; Settings and Help at its foot; the line saying captions
  and translations are made by machine; Quit.
- **The pages** sit in one column at most 720 px wide, centred - the
  extra width is margin (Words' table may use up to 960). The window's
  minimum is 960 x 680 (248's section 2.1: a Settings section fits
  without scrolling at the common sizes) - kept to a small screen, but
  never under 760 x 520, where every page still fits without a
  horizontal scrollbar. Switching pages keeps each page's scroll
  position.
- **Text size** is Windows' times the app's own (`style.text_scale`):
  the text, the sidebar, the columns and the minimum all grow with it -
  the minimum is 960 x 680 times the text size, kept to the screen
  (`fit_to`). While `main` lets it follow Windows (`follows_text_size`),
  a change Qt reports restyles the window and is announced
  (`text_size_changed`); so does the app's own, chosen in Settings
  (`set_app_text_size`) - at once, no restart.
- **The theme** is a stylesheet on this window alone, from the theme's
  tokens (`style`) - no app-wide stylesheet repolishing every widget in
  the app. Painted parts read the tokens when they paint.

`add_page` takes any widget: Home is the new interface's; until Words,
Account, Settings and Help move over (109's step 6), `main` hands today's
pages over. Closing the window keeps the app in the tray, as today, and
says so (`hidden_to_tray`: `main` has the tray say it, once).
"""

from itertools import pairwise

from PySide6.QtCore import QEvent, QObject, QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QKeyEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.perf import spans
from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.controls import label
from polyglotic_desktop.ui_next.home import COLUMN

MINIMUM = (960, 680)
"""At 100 % text size (`minimum_size`), where the screen has room: 248's,
so a Settings section fits (F11)."""
FLOOR = (760, 520)
"""The least it is kept to on a small screen (`fit_to`) - every page still
fits it without a horizontal scrollbar: a 1920 x 1080 laptop at 150 % has
1280 x 672 for it, too short for MINIMUM with the title bar (polyglotic-hq
133: its foot went under the taskbar)."""
SIZE = (1000, 740)
"""Its size at first, if the screen has room (`fit_to`)."""
FRAME = 40
"""Room for Windows' title bar and borders around it (about 31 px at 100 %)."""
SIDEBAR = 200
SIDEBAR_AT_MINIMUM = 184
NARROW = 820
"""Below this window width the sidebar is at its narrower width."""
WORDS_COLUMN = 960


def minimum_size() -> tuple[int, int]:
    """The window's minimum at the text size now: every page fits it
    without a horizontal scrollbar."""
    return style.px(MINIMUM[0]), style.px(MINIMUM[1])


def _tr(text: str) -> str:
    return QApplication.translate("MainWindow", text)


class Centred(QWidget):
    """A page that scrolls by itself (today's), kept to a centred column of
    at most `width` px plus its own margins - at the text size now, again
    after a restyle."""

    def __init__(self, page: QWidget, width: int) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        self._width = width
        self._fit(page)
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        row.addWidget(page, 1000)
        row.addStretch(1)
        self.page = page

    def _fit(self, page: QWidget) -> None:
        page.setMaximumWidth(style.px(self._width) + 72)  # its own 36 px margins

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange:  # perhaps another text size
            self._fit(self.page)


class EnterClicks(QObject):
    """Enter (or Return) on a button clicks it, as Space does: Qt's buttons
    take Enter only in a dialog, so on the sidebar it did nothing
    (polyglotic-hq 133)."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
            and not event.isAutoRepeat()
            and isinstance(watched, QAbstractButton)
            and watched.isEnabled()
        ):
            watched.click()
            return True
        return False


class MainWindow(QMainWindow):
    """The hub: Home, Words, Account; Settings and Help at the sidebar's foot."""

    hidden_to_tray = Signal()
    """Closed, not quit: it was hidden and the app runs on in the tray."""
    text_size_changed = Signal()
    """The text size changed while it ran - Windows' (`follows_text_size`)
    or the app's own (`set_app_text_size`): the window is restyled; `main`
    restyles the others."""

    def __init__(self, quit_action: QAction) -> None:
        super().__init__()
        self.keep_in_tray = False  # closing hides it (the tray sets this)
        self.follows_text_size = False  # `main`: Windows' changes followed
        self.setWindowTitle("Polyglotic")
        self.setObjectName("main_window")
        self.setMinimumSize(*minimum_size())
        self.resize(*SIZE)
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(style.px(SIDEBAR))
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(2)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.logo = QLabel()
        self.logo.setObjectName("logo")
        brand.addWidget(self.logo)
        brand.addWidget(label("Polyglotic", "Brand"))
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(18)
        self.top = QVBoxLayout()
        self.top.setSpacing(2)
        side.addLayout(self.top)
        side.addStretch(1)
        self.foot = QVBoxLayout()
        self.foot.setSpacing(2)
        side.addLayout(self.foot)
        side.addSpacing(12)
        # faint and small (the stylesheet's #machine_made): the quietest line
        # in the sidebar, under the pages' buttons, not among them
        machine_made = label(
            _tr("Captions and translations are made by machine and can be wrong."),
            "machine_made",
            wrap=True,
        )
        side.addWidget(machine_made)
        side.addSpacing(12)
        self.quit_button = QToolButton()
        self.quit_button.setDefaultAction(quit_action)
        self.quit_button.setProperty("kind", "ghost")
        self.quit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        side.addWidget(self.quit_button)
        self._enter_clicks = EnterClicks(self)
        self.quit_button.installEventFilter(self._enter_clicks)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        # not a QButtonGroup: an exclusive group of buttons is radio-like in
        # Qt - once one has had the focus, Tab stops only on the checked one
        # - and the lab's keyboard check wants every page button a Tab stop
        self.nav_buttons: dict[str, QPushButton] = {}
        self.top_buttons: list[QPushButton] = []
        self.foot_buttons: list[QPushButton] = []
        self.pages: dict[str, QWidget] = {}
        self.current = ""
        self.theme = style.current()
        self.setStyleSheet(style.stylesheet(self.theme))

    # -- pages ---------------------------------------------------------------------------

    def add_page(
        self,
        key: str,
        title: str,
        page: QWidget,
        place: str | None = "top",
        width: int | None = None,
    ) -> None:
        """`page` under `key`, with a sidebar button at the `place` ("top",
        "foot", or None: reached only through `go_to`). `width`: kept to a
        centred column this wide (a page that scrolls by itself)."""
        shown = Centred(page, width) if width else page
        self.pages[key] = shown
        self.stack.addWidget(shown)
        if place is None:
            return
        button = QPushButton(title)
        button.setObjectName("FootButton" if place == "foot" else "NavButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _=False, k=key: self.go_to(k))
        button.installEventFilter(self._enter_clicks)  # Enter, as Space
        self.nav_buttons[key] = button
        if place == "foot":
            self.foot.addWidget(button)
            self.foot_buttons.append(button)
        else:
            self.top.addWidget(button)
            self.top_buttons.append(button)
        self._chain_sidebar()

    def _chain_sidebar(self) -> None:
        """Tab walks the sidebar first - the pages' buttons top to bottom,
        then Quit - and the page after it. Qt's chain is a cycle in the
        order widgets were made, walked from the window's first child:
        it put Quit first and the buttons (made here, after their page)
        last. Only a focusable widget can anchor a move, so Quit is the
        anchor: the buttons go after it, Quit goes to the cycle's end
        (after the pages' last control), then back after the last button
        - a move Qt would skip while the last button's next was Quit."""
        buttons = self.top_buttons + self.foot_buttons
        QWidget.setTabOrder(self.quit_button, buttons[0])
        for before, after in pairwise(buttons):
            QWidget.setTabOrder(before, after)
        last = self.previousInFocusChain()
        while (
            last is not None
            and last is not self
            and last.focusPolicy() == Qt.FocusPolicy.NoFocus
        ):
            last = last.previousInFocusChain()
        if last is not None:
            QWidget.setTabOrder(last, self.quit_button)
        QWidget.setTabOrder(buttons[-1], self.quit_button)

    def go_to(self, key: str) -> None:
        """Shows page `key` (each keeps where it was scrolled to)."""
        if key not in self.pages:
            return
        for each, button in self.nav_buttons.items():  # a click toggled it
            button.setChecked(each == key)  # (a page with no button: none)
        if key == self.current:
            return
        with spans.span("main_window.page"):
            self.current = key
            self.stack.setCurrentWidget(self.pages[key])

    # -- theme ---------------------------------------------------------------------------

    def set_theme(self, theme: style.Theme, logo: QPixmap | None = None) -> None:
        """The window's theme (and its logo for it): this window restyled,
        and the painted parts repainted - nothing outside it."""
        if logo is not None:
            self.logo.setPixmap(logo)
        if theme == self.theme:
            return
        with spans.span("main_window.theme"):
            self.theme = theme
            style.use(theme)
            self.setStyleSheet(style.stylesheet(theme))
            self.update()

    # -- text size -----------------------------------------------------------------------

    def event(self, event: QEvent) -> bool:
        if self.follows_text_size and event.type() in (
            QEvent.Type.ApplicationFontChange,  # the system font changed
            QEvent.Type.ThemeChange,  # Windows' settings changed
        ):
            self.follow_text_size()
        return super().event(event)

    def follow_text_size(self) -> None:
        """Windows' text size, as Qt reads it now: if it changed, the
        window restyled at it, and `text_size_changed`."""
        scale = style.text_scale_of(QApplication.font())
        if scale == style.windows_text_scale():
            return
        with spans.span("main_window.text_size"):
            style.use_text_scale(scale)
            self.restyle()
        self.text_size_changed.emit()

    def set_app_text_size(self, size: str) -> None:
        """The app's own text size (Settings > App: a `style.APP_TEXT_SIZES`
        key): if it changed, the window restyled at it, and
        `text_size_changed` - at once, as for Windows'."""
        before = style.text_scale()
        style.use_app_text_size(size)
        if style.text_scale() == before:
            return
        with spans.span("main_window.text_size"):
            self.restyle()
        self.text_size_changed.emit()

    def restyle(self) -> None:
        """The window at the text size now: its stylesheet (its pages follow
        it: Home's column, Words' rows), its sidebar and minimum."""
        self.setStyleSheet(style.stylesheet(self.theme))
        screen = self.screen()
        if screen is not None:
            self._keep_minimum_to(screen.availableGeometry())
        self._fit_sidebar(self.width())

    # -- the window ----------------------------------------------------------------------

    def fit_to(self, area: QRect) -> None:
        """Its first size and place: `SIZE` (or its minimum, at a large text
        size), or less on a small screen - never under its minimum kept to
        the screen (`FLOOR` at least) - in the
        middle of `area` (a screen's work area, the taskbar left out). At 150 %, a 1920 x 1080 laptop has
        1280 x 672 for it, and 1,000 x 740 put its foot - Help, Quit -
        under the taskbar (polyglotic-hq 133)."""
        least = self._keep_minimum_to(area)
        room = area.width() - FRAME, area.height() - FRAME
        width = max(least[0], min(max(SIZE[0], least[0]), room[0]))
        height = max(least[1], min(max(SIZE[1], least[1]), room[1]))
        self.resize(width, height)
        self.move(
            area.x() + max(0, (area.width() - width) // 2),
            area.y() + max(0, (area.height() - height - FRAME) // 2),
        )

    def _keep_minimum_to(self, area: QRect) -> tuple[int, int]:
        """The minimum at the text size now, kept to `area` (a screen's
        work area) and never under `FLOOR`: at a large text size on a
        small screen the pages scroll down - and may scroll sideways."""
        room = area.width() - FRAME, area.height() - FRAME
        wanted = minimum_size()
        width = max(FLOOR[0], min(wanted[0], room[0]))
        height = max(FLOOR[1], min(wanted[1], room[1]))
        self.setMinimumSize(width, height)
        return width, height

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._fit_sidebar(event.size().width())
        super().resizeEvent(event)

    def _fit_sidebar(self, width: int) -> None:
        narrow = width < style.px(NARROW)
        self.sidebar.setFixedWidth(style.px(SIDEBAR_AT_MINIMUM if narrow else SIDEBAR))

    def closeEvent(self, event: QCloseEvent) -> None:
        # captions are the point, not this window: it keeps running in the tray
        if self.keep_in_tray:
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
        else:
            event.accept()


__all__ = ["COLUMN", "WORDS_COLUMN", "MainWindow", "minimum_size"]
