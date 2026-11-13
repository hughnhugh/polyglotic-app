"""The interface-thread watchdog: logs any stretch of interface-thread work
over the slot budget (50 ms; DECISIONS.md #53, "nothing on the interface
thread over 50 ms, ever") - by name and duration only.

How it sees: Qt's event dispatcher says when the interface thread wakes
(`awake`) and when it's about to wait again (`aboutToBlock`); the time
between is one stretch of work - the slots and events it handled. A
helper thread, woken by `awake`, looks at the interface thread's Python
stack once the stretch has run past the budget, and names where it is:
the innermost frame of the app's own code, as `file.py:function` - never
locals, arguments or any text (so never caption text or words). When the
stretch ends the warning is logged, e.g.

    interface thread busy 312 ms in overlay.py:_render (from app.py:_retheme)

Cheap enough to stay on in normal use: two Python calls per pass of the
event loop on the interface thread (a few microseconds), and a helper
thread that sleeps while the interface is idle and wakes at most once
per budget while it's busy. `main` starts it.
"""

import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType

from PySide6.QtCore import QAbstractEventDispatcher, QObject, QThread, Slot

from polyglotic_desktop.perf import budgets

log = logging.getLogger(__name__)

PACKAGE = "polyglotic_desktop"
"""The app's own code: frames from its files are named; others are skipped."""


class Watchdog(QObject):
    """Watches the thread it's made on - the interface thread."""

    def __init__(
        self,
        threshold_ms: float = budgets.SLOT.ms,
        report: Callable[[float, str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """`report(ms, where)` is called for each slow stretch (after the
        warning is logged)."""
        super().__init__(parent)
        self.threshold_ms = threshold_ms
        self.report = report
        self.slow = 0  # stretches over the threshold so far
        self._thread_id = threading.get_ident()
        self._busy_since: float | None = None
        self._stretch = 0  # counts stretches, so the helper knows which it saw
        self._caught: tuple[int, str] = (0, "")  # a stretch, and where it was
        self._woken = threading.Event()
        self._stopped = False
        self._helper: threading.Thread | None = None
        self._dispatcher: QAbstractEventDispatcher | None = None

    def start(self) -> None:
        dispatcher = QAbstractEventDispatcher.instance(QThread.currentThread())
        if dispatcher is None or self._helper is not None:
            return
        self._dispatcher = dispatcher
        dispatcher.awake.connect(self._awake)
        dispatcher.aboutToBlock.connect(self._about_to_block)
        self._helper = threading.Thread(
            target=self._watch, name="interface-watchdog", daemon=True
        )
        self._helper.start()

    def stop(self) -> None:
        self._stopped = True
        self._woken.set()
        if self._dispatcher is not None:
            self._dispatcher.awake.disconnect(self._awake)
            self._dispatcher.aboutToBlock.disconnect(self._about_to_block)
            self._dispatcher = None
        if self._helper is not None:
            self._helper.join(timeout=1)
            self._helper = None

    # -- on the interface thread --------------------------------------------------------

    @Slot()
    def _awake(self) -> None:
        if self._busy_since is None:
            self._stretch += 1
            self._busy_since = time.perf_counter()
            self._woken.set()

    @Slot()
    def _about_to_block(self) -> None:
        since = self._busy_since
        if since is None:
            return
        self._busy_since = None
        ms = (time.perf_counter() - since) * 1000
        if ms <= self.threshold_ms:
            return
        self.slow += 1
        stretch, where = self._caught
        if stretch != self._stretch:
            where = "a stretch the watchdog didn't catch"
        log.warning("interface thread busy %d ms in %s", round(ms), where)
        if self.report is not None:
            self.report(ms, where)

    # -- on the helper thread -----------------------------------------------------------

    def _watch(self) -> None:
        seconds = self.threshold_ms / 1000
        while not self._stopped:
            self._woken.wait()
            self._woken.clear()
            if self._stopped:
                return
            stretch = self._stretch
            time.sleep(seconds)
            if self._busy_since is not None and self._stretch == stretch:
                self._caught = (stretch, where_in(self._thread_id))


def where_in(thread_id: int) -> str:
    """Where `thread_id` is in the app's own code: the innermost frame, and
    the outermost if it's another (leaving out `main`, which runs the event
    loop) - `file.py:function` only."""
    frame: FrameType | None = sys._current_frames().get(thread_id)
    ours: list[str] = []
    while frame is not None:
        path = Path(frame.f_code.co_filename)
        if PACKAGE in path.parts:
            ours.append(f"{path.name}:{frame.f_code.co_name}")
        frame = frame.f_back
    if ours and ours[-1] == "main.py:main":
        ours.pop()
    if not ours:
        return "Qt or a library, outside the app's code"
    if len(ours) == 1 or ours[0] == ours[-1]:
        return ours[0]
    return f"{ours[0]} (from {ours[-1]})"
