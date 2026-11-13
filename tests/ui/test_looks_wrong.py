""" "Looks wrong?" in the interface (project 101): Ctrl+Alt+W, the
comparison card, the answers, and the count when it closes (a caption
window's and a transcript's way in: tests/ui_next). Offscreen Qt,
with fakes for sending and counting; captions are made-up text."""

from datetime import UTC, datetime

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from tests.ui.fakes import FakeAppList, MemorySettingsStore

from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Clause,
    Language,
)
from polyglotic_desktop.core.listening.history import Caption
from polyglotic_desktop.core.listening.recheck import (
    Answer,
    FlagOutcome,
    LineFlagged,
    RecheckOutcome,
    RecheckResult,
)
from polyglotic_desktop.core.listening.sources import SourceId
from polyglotic_desktop.core.listening.timing import CaptionId
from polyglotic_desktop.ports.capture import SourceCategory
from polyglotic_desktop.ui.app import DesktopApp
from polyglotic_desktop.ui.looks_wrong import ComparisonCard
from polyglotic_desktop.ui_next import style

EN, VI = Language("en"), Language("vi")
SMALL = (Clause("Mình đi ăn chước nha.", {EN: "We'll go eat chước."}),)
BEST = (Clause("Mình đi ăn trước nha.", {EN: "Let's go eat first."}),)


class Flow:
    """A desktop with two finished lines, a sender and a counter that record."""

    def __init__(self, held: bool = True, sent: bool = True) -> None:
        self.desktop = DesktopApp(
            MemorySettingsStore({"targets": ["en"]}), None, FakeAppList()
        )
        self.sent: list[CaptionId] = []
        self.counted: list[LineFlagged] = []
        self._held, self._sent = held, sent
        flow = self.desktop.looks_wrong
        flow.send = self.send
        flow.count = self.counted.append
        for caption_id, clauses in (
            ("c0", (Clause("Hôm nay trời nóng quá."),)),
            ("c1", SMALL),
        ):
            self.desktop.feed.apply(
                CaptionUpdate(
                    CaptionId(caption_id),
                    SourceId("source-1"),
                    CaptionKind.FINISHED,
                    clauses,
                    VI,
                    (VI,),
                )
            )

    def send(
        self, caption: Caption
    ) -> tuple[SourceCategory | None, RecheckOutcome | None]:
        self.sent.append(caption.caption_id)
        if not self._held:
            return None, RecheckOutcome.NOT_HELD
        return SourceCategory.CALL, None if self._sent else RecheckOutcome.NOT_LISTENING

    def check(self, caption_id: str) -> None:
        """ "Looks wrong?" on a line, then Send report (249: it asks first)."""
        self.desktop.looks_wrong.check(caption_id)
        card = self.desktop.looks_wrong.card
        assert card is not None
        card.send_report.click()

    def answer(self, result: RecheckResult) -> None:
        self.desktop.looks_wrong.receive(result)  # as from the session's thread
        QApplication.processEvents()


def test_the_hotkey_checks_the_newest_line_and_the_card_shows_both(
    qapp: object,
) -> None:
    flow = Flow()
    assert flow.desktop.hotkeys["W"] is flow.desktop.check_line
    flow.desktop.check_line.trigger()  # Ctrl+Alt+W
    card = flow.desktop.looks_wrong.card
    assert card is not None and card.isVisible()
    assert flow.sent == []  # it asks first (249, F17)
    card.send_report.click()
    assert flow.sent == ["c1"]
    assert "Checking" in card.status.text()
    assert not card.answers[Answer.BEST_RIGHT].isVisible()
    flow.answer(
        RecheckResult(
            CaptionId("c1"), RecheckOutcome.CHECKED, BEST, VI, processing_ms=2900
        )
    )
    assert "about 3 s" in card.status.text()
    assert "trước" in card.best.text() and "chước" in card.seen.text()
    assert "background-color" in card.best.text()  # what differs is boxed
    assert card.answers[Answer.BEST_RIGHT].isVisible()
    card.answers[Answer.BEST_RIGHT].click()
    line = flow.desktop.history.caption(CaptionId("c1"))
    assert line is not None and line.checked and line.clauses == BEST
    card.accept()  # Done
    assert flow.counted == [
        LineFlagged(VI, SourceCategory.CALL, FlagOutcome.DIFFERS, Answer.BEST_RIGHT)
    ]
    flow.desktop.close()


def test_closed_without_an_answer_counts_none_and_late_answers_are_ignored(
    qapp: object,
) -> None:
    flow = Flow()
    flow.check("c0")
    flow.answer(
        RecheckResult(CaptionId("c1"), RecheckOutcome.CHECKED, BEST)
    )  # not c0's
    card = flow.desktop.looks_wrong.card
    assert card is not None and "Checking" in card.status.text()
    flow.answer(RecheckResult(CaptionId("c0"), RecheckOutcome.BEST_UNAVAILABLE))
    assert "isn't available" in card.status.text()
    card.reject()  # the window's close button
    assert [(c.outcome, c.answer) for c in flow.counted] == [
        (FlagOutcome.BEST_UNAVAILABLE, None)
    ]
    flow.answer(RecheckResult(CaptionId("c0"), RecheckOutcome.CHECKED, BEST))
    assert len(flow.counted) == 1  # closed: nothing more
    flow.desktop.close()


def test_audio_not_held_or_nobody_listening_is_said_at_once(qapp: object) -> None:
    for flow, says, counted in (
        (Flow(held=False), "isn't held any more", FlagOutcome.NOT_HELD),
        (Flow(sent=False), "while Polyglotic is listening", FlagOutcome.FAILED),
    ):
        flow.check("c1")
        card = flow.desktop.looks_wrong.card
        assert card is not None and says in card.status.text()
        card.accept()
        assert [c.outcome for c in flow.counted] == [counted]
        flow.desktop.close()


def test_no_answer_in_time_says_so(qapp: object) -> None:
    flow = Flow()
    flow.check("c1")
    flow.desktop.looks_wrong._waiting.timeout.emit()  # ANSWER_WITHIN_SEC passed
    card = flow.desktop.looks_wrong.card
    assert card is not None and "No answer" in card.status.text()
    flow.desktop.close()


ZH = Language("zh")
SEEN_REAL = (
    Clause(
        "Now widely available throughout the archipelago, Japanese cuisine "
        "forms a part of the local diet and is enjoyed by most people.",
        {
            ZH: "日本料理如今在群岛各地随处可见，已成为当地饮食的一部分，深受大多数人喜爱。"
        },
    ),
)
BEST_REAL = (
    Clause(
        "Now widely available throughout the archipelago, Japanese cuisine's "
        "forms are part of the local diet and enjoyed by most people.",
        {
            ZH: "日本料理如今在整个群岛广泛供应，其形式已成为当地饮食的一部分，深受大多数人的喜爱。"
        },
    ),
)


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.25])
def test_the_card_fits_real_sentences_at_every_text_size(
    qapp: QApplication, scale: float
) -> None:
    """A real line and its translation, both versions, and the answers all
    show whole - 145 saw a line and a half of each and clipped buttons with
    real sentences (the made-up ones above are short). The card sits on a
    window with the interface's style sheet, as it does in the app."""
    try:
        style.use_text_scale(scale)
        window = QWidget()
        window.setStyleSheet(style.stylesheet(style.current()))
        card = ComparisonCard(window)
        now = datetime.now(UTC)
        line = Caption(
            1, CaptionId("c1"), SourceId("s1"), False, False, SEEN_REAL,
            Language("en"), (Language("en"),), now, now,
        )  # fmt: skip
        card.show_line(line, [ZH])
        card.show()
        card.show_result(
            line,
            RecheckResult(CaptionId("c1"), RecheckOutcome.CHECKED, BEST_REAL),
            [ZH],
        )
        QApplication.processEvents()
        assert "日本料理" in card.best.text()  # the translation is there...
        for shown in card.findChildren(QLabel) + card.findChildren(QPushButton):
            if not shown.isVisible():
                continue
            needs = (
                shown.heightForWidth(shown.width())
                if isinstance(shown, QLabel) and shown.wordWrap()
                else shown.sizeHint().height()
            )
            assert shown.height() >= needs, shown.objectName()  # ...and shows
        card.close()
        window.deleteLater()
    finally:
        style.use_text_scale(1.0)


def test_the_card_fits_again_when_the_text_size_changes_while_it_s_open(
    qapp: QApplication,
) -> None:
    """The card is sized to what it shows when that changes; a text size
    change while it's open (Windows', or the app's own: polyglotic-hq 292)
    restyles it with its window - and it fits again, or its larger text was
    cut at the old size."""
    try:
        window = QWidget()
        window.setStyleSheet(style.stylesheet(style.current()))
        card = ComparisonCard(window)
        now = datetime.now(UTC)
        line = Caption(
            1, CaptionId("c1"), SourceId("s1"), False, False, SEEN_REAL,
            Language("en"), (Language("en"),), now, now,
        )  # fmt: skip
        card.show_line(line, [ZH])
        card.show()
        card.show_result(
            line,
            RecheckResult(CaptionId("c1"), RecheckOutcome.CHECKED, BEST_REAL),
            [ZH],
        )
        QApplication.processEvents()
        style.use_text_scale(2.0)
        window.setStyleSheet(style.stylesheet(style.current()))  # as main's restyle
        QApplication.processEvents()
        for shown in card.findChildren(QLabel) + card.findChildren(QPushButton):
            if not shown.isVisible():
                continue
            needs = (
                shown.heightForWidth(shown.width())
                if isinstance(shown, QLabel) and shown.wordWrap()
                else shown.sizeHint().height()
            )
            assert shown.height() >= needs, shown.objectName()
        card.close()
        window.deleteLater()
    finally:
        style.use_text_scale(1.0)
