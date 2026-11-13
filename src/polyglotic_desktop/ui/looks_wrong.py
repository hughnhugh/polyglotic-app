""" "Looks wrong?": a finished line checked with the best model, side by side.

Project 101, from 087's wireframe 2.2. `LooksWrong` runs it on the Qt
thread:
- `check(caption_id)` - from the overlay's hover button, a Transcript row,
  or Ctrl+Alt+W for the newest finished line: the main window shows the
  comparison card (never over a game: the overlay only asks). It first
  says what checking is and what is sent - the line's audio, again, to
  the best model - with **Send report** and **Cancel**; nothing is sent
  before Send report (the user's rehearsal feedback F17, polyglotic-hq
  249). Then the line's held speech goes to the server through `send`
  (main's: the recent-speech store, then the listening session);
- the answer arrives from the session's thread through `receive`, queued
  here; none within `ANSWER_WITHIN_SEC` is "no answer";
- the card shows what was seen and the best model's version, what differs
  boxed, and the optional answers; "The best model is right" puts its
  version in the transcript (`CaptionFeed.use_checked`);
- when the card closes, the content-free count goes through `count`
  (main's: the `line_flagged` usage event, kept only with consent).

Nothing is kept: the card holds the two versions while it's open. Lines
from calls and "everything the PC plays" are checked the same way - there
is nothing to keep either way. Holds caption text: never log it.
"""

import html
from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.core.listening.captions import Clause, Language
from polyglotic_desktop.core.listening.history import Caption, join_text
from polyglotic_desktop.core.listening.recheck import (
    ANSWER_WITHIN_SEC,
    Answer,
    LineFlagged,
    RecheckOutcome,
    RecheckResult,
    Span,
    differences,
    flag_outcome,
    same_line,
)
from polyglotic_desktop.core.listening.timing import CaptionId
from polyglotic_desktop.ports.capture import SourceCategory
from polyglotic_desktop.ui import theme
from polyglotic_desktop.ui.captions import CaptionFeed
from polyglotic_desktop.ui.widgets import label

Sender = Callable[[Caption], tuple[SourceCategory | None, RecheckOutcome | None]]
"""Sends a line to be checked: its source's category (None: its audio isn't
held) and an outcome already known (None: sent, the answer will come)."""


def _not_sent(caption: Caption) -> tuple[SourceCategory | None, RecheckOutcome | None]:
    return None, RecheckOutcome.NOT_LISTENING


LINE_CHARACTERS = 80
"""The card's width, in average characters of its text: a comfortable line
for a sentence and its translation, which grows with the text size."""


class ComparisonCard(QDialog):
    """Both versions of a line, what differs boxed, and the optional answers.

    Sized to what it shows (`fit`), each time it changes: a real sentence
    wraps to several lines, and a dialog sized by Qt alone gave each version
    a line and a half and clipped the buttons (polyglotic-hq project 145)."""

    answered = Signal(str)  # an Answer's value
    send_wanted = Signal()
    """Send report: the line asked about goes to the best model (F17)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("looks_wrong.card")
        self.setWindowTitle(self.tr("Looks wrong?"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        self.status = label("", "looks_wrong.status", wrap=True)
        layout.addWidget(self.status)
        self.seen_title = label(self.tr("What you saw"), "Dim")
        self.seen = self._text("looks_wrong.seen")
        self.best_title = label(self.tr("Best model"), "Dim")
        self.best = self._text("looks_wrong.best")
        for widget in (self.seen_title, self.seen, self.best_title, self.best):
            layout.addWidget(widget)
        answers = QHBoxLayout()
        self.answers: dict[Answer, QPushButton] = {}
        for answer, text in (
            (Answer.BEST_RIGHT, self.tr("The best model is right")),
            (Answer.BOTH_FINE, self.tr("Both are fine")),
            (Answer.BOTH_WRONG, self.tr("Both are wrong")),
        ):
            button = QPushButton(text)
            button.setObjectName(f"looks_wrong.{answer.value}")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(
                lambda _=False, a=answer: self.answered.emit(a.value)
            )
            answers.addWidget(button)
            self.answers[answer] = button
        layout.addLayout(answers)
        self.answer_note = label(
            self.tr(
                "Answering is optional. Nothing from this line is kept: the "
                "server checks it and forgets it."
            ),
            "Faint",
            wrap=True,
        )
        layout.addWidget(self.answer_note)
        # what Send report sends, in the privacy notice's words (040)
        self.ask_note = label(
            self.tr(
                "Send report sends this line's audio again to our best model; "
                "the server checks it and forgets it. Nothing is sent until "
                "you press Send report."
            ),
            "Faint",
            wrap=True,
        )
        layout.addWidget(self.ask_note)
        self.cancel = QPushButton(self.tr("Cancel"))
        self.cancel.setObjectName("looks_wrong.cancel")
        self.cancel.clicked.connect(self.reject)
        self.send_report = QPushButton(self.tr("Send report"))
        self.send_report.setObjectName("looks_wrong.send")
        self.send_report.setProperty("kind", "primary")
        self.send_report.clicked.connect(self.send_wanted)
        self.done_button = QPushButton(self.tr("Done"))
        self.done_button.setObjectName("looks_wrong.done")
        self.done_button.setProperty("kind", "primary")
        self.done_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        for button in (self.cancel, self.send_report, self.done_button):
            row.addWidget(button)
        layout.addLayout(row)

    @staticmethod
    def _text(name: str) -> QLabel:
        text = label("", name, wrap=True)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return text

    def ask(self, caption: Caption, languages: Sequence[Language]) -> None:
        """Before anything is sent: what checking does, the line as seen,
        what Send report sends, and Send report or Cancel (F17)."""
        self.show_line(caption, languages)
        self.status.setText(
            self.tr(
                "Think this line is wrong? Our best model can listen to it again "
                "and show you its version."
            )
        )
        self._asking(True)
        self.send_report.setDefault(True)
        self.fit()

    def _asking(self, asking: bool) -> None:
        for widget in (self.ask_note, self.cancel, self.send_report):
            widget.setVisible(asking)
        for widget in (self.answer_note, self.done_button):
            widget.setVisible(not asking)

    def show_line(self, caption: Caption, languages: Sequence[Language]) -> None:
        """A new check: the line as seen, the best model's still to come."""
        for button in self.answers.values():
            button.setAutoExclusive(False)
            button.setChecked(False)
            button.setAutoExclusive(True)
        self.seen.setText(versions(caption.clauses, None, languages))
        self.best.setText("")
        self.status.setText(self.tr("Checking with our best model…"))
        self._answers_shown(False)
        self._asking(False)
        self.done_button.setDefault(True)
        self.fit()

    def fit(self) -> None:
        """The card's size for what it shows now: `LINE_CHARACTERS` wide (or
        wider, for the buttons), and as tall as its wrapped text needs at
        that width - wider still if that's taller than the screen."""
        self.ensurePolished()  # the window's style sheet sets the text size
        layout = self.layout()
        assert layout is not None
        layout.activate()
        width = max(
            self.fontMetrics().averageCharWidth() * LINE_CHARACTERS,
            layout.totalMinimumSize().width(),
        )
        screen = self.screen().availableGeometry()
        width = min(width, screen.width())
        height = layout.totalHeightForWidth(width)
        while height > screen.height() and width < screen.width():
            width = min(width + width // 4, screen.width())
            height = layout.totalHeightForWidth(width)
        self.resize(width, min(height, screen.height()))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange and self.isVisible():
            self.fit()  # the window restyled it - at another text size, perhaps

    def show_result(
        self,
        caption: Caption,
        result: RecheckResult,
        languages: Sequence[Language],
    ) -> None:
        checked = result.outcome is RecheckOutcome.CHECKED
        words = checked and bool(result.clauses)
        if words:
            self.seen.setText(versions(caption.clauses, result.clauses, languages))
            self.best.setText(versions(result.clauses, caption.clauses, languages))
        self.status.setText(self.status_text(caption, result))
        self._answers_shown(words)
        self.fit()

    def _answers_shown(self, shown: bool) -> None:
        """The best model's version and the answers: only for one with words."""
        for widget in (self.best_title, self.best, *self.answers.values()):
            widget.setVisible(shown)

    def status_text(self, caption: Caption, result: RecheckResult) -> str:
        match result.outcome:
            case RecheckOutcome.CHECKED if not result.clauses:
                return self.tr("Checked with our best model: it heard no words here.")
            case RecheckOutcome.CHECKED if same_line(caption.clauses, result.clauses):
                return self.tr("Checked with our best model: it heard the same.")
            case RecheckOutcome.CHECKED:
                seconds = round((result.processing_ms or 0) / 1000)
                return (
                    self.tr("Checked with our best model · about %n s", "", seconds)
                    if seconds
                    else self.tr("Checked with our best model")
                )
            case RecheckOutcome.BEST_UNAVAILABLE:
                return self.tr("The best model isn't available right now.")
            case RecheckOutcome.TRY_LATER:
                return self.tr("The best model is busy - try again in a minute.")
            case RecheckOutcome.NOT_HELD:
                return self.tr(
                    "This line's audio isn't held any more: the app keeps only the "
                    "last 2 minutes of speech, in memory. Try a newer line."
                )
            case RecheckOutcome.NOT_LISTENING:
                return self.tr("Lines are checked while Polyglotic is listening.")
            case RecheckOutcome.NO_ANSWER:
                return self.tr("No answer from the best model - try again later.")
            case _:
                return self.tr("This line couldn't be checked.")


def versions(
    clauses: Sequence[Clause],
    other: Sequence[Clause] | None,
    languages: Sequence[Language],
) -> str:
    """A line and its translations as rich text, what differs from `other`
    boxed (none: nothing boxed)."""
    rows = [join_text(c.original for c in clauses)]
    others = [join_text(c.original for c in other)] if other is not None else []
    for language in languages:
        if any(language in c.translations for c in clauses):
            rows.append(join_text(c.translations.get(language, "") for c in clauses))
            if other is not None:
                others.append(
                    join_text(c.translations.get(language, "") for c in other)
                )
    shown = []
    for n, row in enumerate(rows):
        boxes: list[Span] = []
        if other is not None and n < len(others):
            boxes = differences(row, others[n])[0]
        color = theme.TEXT if n == 0 else theme.TEXT_DIM
        shown.append(f'<div style="color:{color}">{boxed(row, boxes)}</div>')
    return "".join(shown)


def boxed(text: str, spans: Sequence[Span]) -> str:
    """`text` as HTML, each span on a tinted box (Qt's rich text has no
    inline borders), in the full text colour: a translation's dim colour
    on the tint is 3.1:1, under the 4.5:1 text needs (the UI lab, 158)."""
    out, at = [], 0
    tint = blend(theme.WARNING, theme.SURFACE, 0.35)
    for start, end in spans:
        out.append(html.escape(text[at:start]))
        out.append(
            f'<span style="background-color:{tint}; color:{theme.TEXT};'
            ' text-decoration:underline">'
            f"{html.escape(text[start:end])}</span>"
        )
        at = end
    out.append(html.escape(text[at:]))
    return "".join(out)


def blend(color: str, under: str, share: float) -> str:
    """`color` laid over `under` at `share` opacity, as #rrggbb."""
    a = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(under[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(
        f"{round(x * share + y * (1 - share)):02x}" for x, y in zip(a, b, strict=True)
    )


class LooksWrong(QObject):
    """The "Looks wrong?" flow: one comparison at a time, in the main window."""

    _received = Signal(object)  # a RecheckResult, from any thread

    def __init__(
        self,
        feed: CaptionFeed,
        languages: Callable[[Caption], Sequence[Language]],
        window: QWidget | None = None,
        show_window: Callable[[], None] = lambda: None,
    ) -> None:
        """`languages`: a line's translations to show, in order.
        `show_window` brings the main window forward for the card."""
        super().__init__(window)
        self.feed = feed
        self.languages = languages
        """A line's translations to show, in order: its source's (`main`
        gives the caption windows' own languages)."""
        self.window = window
        """What the comparison card opens over (`main`'s developer switch
        sets the new main window)."""
        self._show_window = show_window
        self.send: Sender = _not_sent
        self.count: Callable[[LineFlagged], None] = lambda flagged: None
        self.card: ComparisonCard | None = None
        self._caption: Caption | None = None
        self._sent = False
        """Send report pressed for the line asked about: sent once."""
        self._category: SourceCategory | None = None
        self._result: RecheckResult | None = None
        self._answer: Answer | None = None
        self._waiting = QTimer(self)
        self._waiting.setSingleShot(True)
        self._waiting.setInterval(int(ANSWER_WITHIN_SEC * 1000))
        self._waiting.timeout.connect(self._no_answer)
        self._received.connect(self._arrived, Qt.ConnectionType.QueuedConnection)

    def receive(self, result: RecheckResult) -> None:
        """The server's answer, from any thread."""
        self._received.emit(result)

    def newest(self) -> CaptionId | None:
        """The newest finished line in the history, for Ctrl+Alt+W."""
        finished = [c for c in self.feed.history.captions if not c.live]
        return finished[-1].caption_id if finished else None

    @Slot(str)
    def check(self, caption_id: str) -> None:
        """Checks a finished line with the best model, in the main window."""
        caption = self.feed.history.caption(CaptionId(caption_id))
        if caption is None or caption.live:
            return
        self._close_count()
        card = self._card()
        self._caption, self._result, self._answer = caption, None, None
        self._sent = False
        card.ask(caption, self.languages(caption))  # nothing sent yet (F17)
        self._show_window()
        card.show()
        card.raise_()
        card.activateWindow()

    @Slot()
    def _send(self) -> None:
        """Send report: the line asked about goes to the best model."""
        caption, card = self._caption, self.card
        if caption is None or card is None or self._sent:
            return
        self._sent = True
        card.show_line(caption, self.languages(caption))
        self._category, outcome = self.send(caption)
        if outcome is not None:
            self._show(RecheckResult(caption.caption_id, outcome))
        else:
            self._waiting.start()

    def _card(self) -> ComparisonCard:
        if self.card is None:
            self.card = ComparisonCard(self.window)
            self.card.answered.connect(self._answered)
            self.card.send_wanted.connect(self._send)
            self.card.finished.connect(lambda _: self._close_count())
        return self.card

    @Slot(object)
    def _arrived(self, result: RecheckResult) -> None:
        caption = self._caption
        if caption is None or result.caption_id != caption.caption_id:
            return  # an answer for a comparison already closed or replaced
        if self._result is not None:
            return
        self._waiting.stop()
        self._show(result)

    def _no_answer(self) -> None:
        if self._caption is not None and self._result is None:
            self._show(
                RecheckResult(self._caption.caption_id, RecheckOutcome.NO_ANSWER)
            )

    def _show(self, result: RecheckResult) -> None:
        self._result = result
        if self.card is not None and self._caption is not None:
            self.card.show_result(self._caption, result, self.languages(self._caption))

    @Slot(str)
    def _answered(self, value: str) -> None:
        answer = Answer(value)
        if self._caption is None or self._result is None:
            return
        self._answer = answer
        if answer is Answer.BEST_RIGHT:
            self.feed.use_checked(self._caption.caption_id, self._result)
        # changing one's mind after "best is right" leaves the transcript's
        # better line: undoing it isn't drawn (087)

    def _close_count(self) -> None:
        """The comparison closed (or another replaced it): its count, once,
        if it got as far as an outcome."""
        caption, result = self._caption, self._result
        self._caption, self._result = None, None
        self._waiting.stop()
        if caption is None or result is None or caption.language is None:
            return
        self.count(
            LineFlagged(
                language=caption.language,
                source_category=self._category,
                outcome=flag_outcome(caption.clauses, result),
                answer=self._answer,
            )
        )
