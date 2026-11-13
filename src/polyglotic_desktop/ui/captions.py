"""Caption updates onto the Qt thread: the caption history, and exposures.

`CaptionFeed.receive` may be called from any thread - the listening
session calls it on its own (`main` hands it over). The update is queued
to the Qt thread, applied to the caption history there, and counted for
Learning:
- a finished caption (joins included - a join finishes the earlier
  caption's id again, and `Vocabulary` counts only the difference) counts
  its words as exposures and towards the day's coverage, the user's own
  mic as "by you" - **only in the language being learned**: the learner's
  dictionary finds its words in other languages too (polyglotic-hq 174),
  so a caption in another language counts nothing (and a join that turns
  a caption into one takes back what it counted);
- a withdrawn caption, and any caption a join replaces, takes back what
  it counted (nothing, if it never finished).
Then `changed` tells the views (overlays, transcript) to redraw, and
`captioned` names the source of a finished or withdrawn caption (for the
listening mark).

`Vocabulary` and the history are single-threaded: both are only touched
here, on the Qt thread. No caption rules of its own - the history and
Learning have them.
"""

import logging
import time
from collections import deque

from PySide6.QtCore import QObject, Qt, Signal, Slot

from polyglotic_desktop.core.listening.captions import CaptionKind, CaptionUpdate
from polyglotic_desktop.core.listening.delays import (
    CAPTION_LOG,
    delay,
    line,
    milliseconds,
)
from polyglotic_desktop.core.listening.history import CaptionHistory
from polyglotic_desktop.core.listening.recheck import RecheckResult
from polyglotic_desktop.core.listening.timing import CaptionId
from polyglotic_desktop.core.shared import WordInLine
from polyglotic_desktop.ui.learning import LearningTools

caption_log = logging.getLogger(CAPTION_LOG)

UNCOUNTED_MOST = 1000

"""Updates held to be counted until the word split's data is read (0.2-0.9 s
at start: a handful). Enough for minutes of two sources' live updates; the
oldest go after that, so a read that never finishes can't grow the list
for the session (polyglotic-hq 142, Low 2)."""


class CaptionFeed(QObject):
    changed = Signal()  # the history changed
    captioned = Signal(str)  # a source's caption finished or was withdrawn
    applied = Signal(object)
    """Each caption update once applied (a CaptionUpdate): for other views
    keeping captions of their own (the new interface's caption windows)."""
    checked = Signal(str, object)
    """A line's best-model version the learner chose (caption id,
    RecheckResult), once in the history."""
    dictionary_ready = Signal()
    """The dictionary's word-split data is read and the captions that
    arrived before it are counted: marks drawn again. On the Qt thread."""
    _received = Signal(object)  # a CaptionUpdate, from any thread

    def __init__(
        self,
        history: CaptionHistory,
        tools: LearningTools | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.history = history
        self.tools = tools
        self._uncounted: deque[tuple[CaptionUpdate, bool]] = deque(
            maxlen=UNCOUNTED_MOST
        )
        """Updates applied before the dictionary was ready, and whether each
        went into the history: counted for Learning when it is."""
        self._received.connect(self._apply, Qt.ConnectionType.QueuedConnection)
        if tools is not None:
            tools.dictionary_ready.connect(
                self._count_waiting, Qt.ConnectionType.QueuedConnection
            )

    def receive(self, update: CaptionUpdate) -> None:
        """A caption update, from any thread: applied on the Qt thread."""
        self._received.emit(update)

    def apply(self, update: CaptionUpdate) -> None:
        """A caption update, on the Qt thread: applied now."""
        self._apply(update)

    def use_checked(self, caption_id: CaptionId, result: RecheckResult) -> None:
        """The best model's version of a finished line, which the learner
        said is right ("Looks wrong?"): in the history in the line's place,
        its words counted for Learning instead of the first version's."""
        caption = self.history.use_checked(
            caption_id, result.clauses, result.language, result.languages_heard
        )
        if caption is None:
            return
        tools = self.tools
        if tools is not None and tools.learns(caption.language):
            words: list[WordInLine] = []
            for clause in caption.clauses:
                words += tools.words_in(clause.original)
            tools.vocabulary.caption_finished(caption_id, words, caption.by_you)
        elif tools is not None:  # now another language: what it counted goes
            tools.vocabulary.caption_withdrawn(caption_id)
        self.changed.emit()
        self.checked.emit(caption_id, result)

    @Slot(object)
    def _apply(self, update: CaptionUpdate) -> None:
        version = self.history.version
        caption = self.history.apply(update)
        if self.tools is not None:
            if self.tools.ready:
                self._count(update, caption is not None, self.tools)
            else:  # the caption shows now; its words are counted once they can be
                self._uncounted.append((update, caption is not None))
        if self.history.version != version:
            self.changed.emit()
        self.applied.emit(update)
        self._log_shown(update)
        if update.kind is not CaptionKind.LIVE:
            self.captioned.emit(update.source_id)

    def _log_shown(self, update: CaptionUpdate) -> None:
        """The caption log's line for an update the windows now show (they
        draw it as this returns): how long since its speech started and
        ended, and how long it took here, on the interface's thread."""
        times = update.times
        found = delay(update, time.perf_counter())
        if times is None or found is None:
            return
        caption_log.info(
            line(
                "shown",
                update.caption_id,
                kind=update.kind.value,
                since_start_ms=milliseconds(found.from_start),
                since_end_ms=milliseconds(found.from_end),
                interface_ms=milliseconds(found.from_end)
                - milliseconds(times.received - times.speech_end),
            )
        )

    @Slot()
    def _count_waiting(self) -> None:
        tools = self.tools
        if tools is None:
            return
        waiting, self._uncounted = self._uncounted, deque(maxlen=UNCOUNTED_MOST)
        for update, applied in waiting:
            self._count(update, applied, tools)
        self.dictionary_ready.emit()

    def _count(
        self, update: CaptionUpdate, applied: bool, tools: LearningTools
    ) -> None:
        vocabulary = tools.vocabulary
        if update.kind is CaptionKind.WITHDRAWN:
            vocabulary.caption_withdrawn(update.caption_id)
            return
        if update.kind is not CaptionKind.FINISHED or not applied:
            return
        for replaced in update.replaces:
            if replaced != update.caption_id:
                vocabulary.caption_withdrawn(replaced)
        if not tools.learns(update.language):  # another language: not heard
            vocabulary.caption_withdrawn(update.caption_id)
            return
        words: list[WordInLine] = []
        for clause in update.clauses:
            words += tools.words_in(clause.original)
        vocabulary.caption_finished(
            update.caption_id, words, self.history.is_yours(update.source_id)
        )
