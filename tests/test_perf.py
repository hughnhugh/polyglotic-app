"""perf: named spans, timings as JSON, and the interface-thread watchdog -
names and durations only, never caption text."""

import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from polyglotic_desktop.perf import spans, watchdog
from polyglotic_desktop.perf.spans import Timings, checked_name
from polyglotic_desktop.perf.watchdog import Watchdog

CAPTION = "我们周末一起去打游戏吧"  # made-up; must never reach a log


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    yield app


def test_spans_record_nothing_unless_recording() -> None:
    spans.TIMINGS.clear()
    with spans.span("caption_window.paint"):
        pass
    assert spans.TIMINGS.summary() == {}


def test_spans_recorded_by_name() -> None:
    with spans.recorded() as timings:
        for _ in range(3):
            with spans.span("caption_window.paint"):
                time.sleep(0.001)
    (paint,) = timings.summary().values()
    assert paint["n"] == 3
    assert paint["median_ms"] >= 1
    assert not spans.recording()


@pytest.mark.parametrize("name", [CAPTION, "Caption window", "a b", "", "x" * 65])
def test_a_span_name_is_a_constant_never_text(name: str) -> None:
    with pytest.raises(ValueError):
        checked_name(name)
    with pytest.raises(ValueError), spans.recorded(), spans.span(name):
        pass


def test_timings_written_as_json(tmp_path: Path) -> None:
    timings = Timings()
    for ms in (1.0, 2.0, 3.0, 10.0):
        timings.record("transcript.resize_step", ms)
    timings.write(tmp_path / "t.json", state="transcript_1000")
    written = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert written["state"] == "transcript_1000"
    assert written["spans"]["transcript.resize_step"] == {
        "n": 4,
        "median_ms": 2.5,
        "p90_ms": 3.0,
        "max_ms": 10.0,
    }


def run_loop(qapp: QApplication, ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.mark.xfail(
    sys.platform != "win32",
    reason="Linux's event dispatcher (GLib) doesn't give the watchdog its"
    " awake / about-to-block pairs: it sees no slow slot there (179's Linux"
    " checks, 2026-11-08; 171 saw the same)",
    strict=True,
)
def test_the_watchdog_names_a_slow_slot_and_its_duration(
    qapp: QApplication,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(watchdog, "PACKAGE", "tests")  # name this file's frames
    reported: list[tuple[float, str]] = []
    dog = Watchdog(report=lambda ms, where: reported.append((ms, where)))
    dog.start()

    def slow_slot() -> None:
        line = CAPTION  # caption text in a local: must not be logged
        time.sleep(0.12)
        assert line

    try:
        with caplog.at_level(logging.WARNING, logger=watchdog.__name__):
            QTimer.singleShot(10, slow_slot)
            run_loop(qapp, 300)
    finally:
        dog.stop()
    assert dog.slow == 1
    ((ms, where),) = reported
    assert ms >= 120
    assert where.startswith("test_perf.py:slow_slot (from test_perf.py:test_")
    assert "test_perf.py:slow_slot" in caplog.text
    assert CAPTION not in caplog.text


def test_the_watchdog_lets_fast_slots_be(
    qapp: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    dog = Watchdog()
    dog.start()
    try:
        with caplog.at_level(logging.WARNING, logger=watchdog.__name__):
            for n in range(20):
                QTimer.singleShot(n * 5, lambda: time.sleep(0.002))
            run_loop(qapp, 200)
    finally:
        dog.stop()
    assert dog.slow == 0
    assert caplog.text == ""
