""" "Looks wrong?" says what it does and what it sends, with Send report and
Cancel; nothing is sent before Send report (the user's rehearsal feedback
F17, polyglotic-hq 249, 2026-11-08: "What is the point of the looks wrong
button? it should have a button to send report or cancel")."""

from PySide6.QtWidgets import QApplication
from tests.ui.test_looks_wrong import Flow

from polyglotic_desktop.core.listening.recheck import RecheckOutcome, RecheckResult
from polyglotic_desktop.core.listening.timing import CaptionId


def test_it_explains_and_sends_nothing_until_send_report(qapp: QApplication) -> None:
    flow = Flow()
    flow.desktop.looks_wrong.check("c1")
    card = flow.desktop.looks_wrong.card
    assert card is not None and card.isVisible()
    assert flow.sent == []
    assert "best model can listen to it again" in card.status.text()
    assert "sends this line's audio again" in card.ask_note.text()  # 040's words
    assert "Nothing is sent until" in card.ask_note.text()
    assert card.send_report.isVisible() and card.cancel.isVisible()
    assert card.send_report.text() == "Send report"
    assert not card.done_button.isVisible()
    assert "chước" in card.seen.text()  # the line asked about, as seen
    card.send_report.click()
    card.send_report.click()  # (gone: once is all it sends)
    assert flow.sent == ["c1"]
    assert not card.send_report.isVisible() and not card.cancel.isVisible()
    assert card.done_button.isVisible()
    flow.desktop.close()


def test_cancel_sends_and_counts_nothing(qapp: QApplication) -> None:
    flow = Flow()
    flow.desktop.looks_wrong.check("c1")
    card = flow.desktop.looks_wrong.card
    assert card is not None
    card.cancel.click()
    assert not card.isVisible()
    assert flow.sent == [] and flow.counted == []
    flow.answer(RecheckResult(CaptionId("c1"), RecheckOutcome.CHECKED))
    assert flow.counted == []  # nothing was asked: nothing to answer
    flow.desktop.close()


def test_a_second_line_asks_again(qapp: QApplication) -> None:
    flow = Flow()
    flow.check("c1")
    flow.desktop.looks_wrong.check("c0")  # another line, while one is open
    card = flow.desktop.looks_wrong.card
    assert card is not None and card.send_report.isVisible()
    assert flow.sent == ["c1"]
    card.send_report.click()
    assert flow.sent == ["c1", "c0"]
    flow.desktop.close()
