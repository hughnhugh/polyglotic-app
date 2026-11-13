"""The judge's kit (project 119): a contact sheet per surface, the
findings, timings and goldens, and judge.md with the checklist."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QToolButton, QWidget
from tools.ui_lab import __main__ as cli
from tools.ui_lab import goldens, judge, lab, new_parts


@pytest.fixture
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication(["test"])
    assert isinstance(app, QApplication)
    yield app


def test_states_fall_into_their_surfaces() -> None:
    assert judge.surface_of("ui_next.w1_hovered").key == "w1"
    assert judge.surface_of("ui_next.caption_window_1000").key == "foundation"
    assert judge.surface_of("ui_next.joined_three").key == "foundation"
    assert judge.surface_of("ui_next.w2_search").title.startswith("W2, the transcript")
    assert judge.surface_of("ui_next.panel_timing_live").key == "panel"
    assert judge.surface_of("ui_next.picker_full").title == "picker"  # not listed


def test_words_the_glossary_avoids_are_named() -> None:
    found = judge._avoided(["Overlay position", "Finished caption", "Final text"])
    assert len(found) == 2
    assert found[0].startswith("'Overlay position' says \"overlay\"")


def _label(text: str, name: str) -> lab.State:
    def run(lab_: lab.Lab) -> QWidget:
        shown = QLabel(text)
        shown.setObjectName(name)
        shown.setMinimumSize(100, 40)
        shown.setStyleSheet("background: #ffffff; color: #111111; padding: 8px;")
        QToolButton(shown).move(200, 5)  # unnamed: a finding
        shown.resize(260, 50)
        shown.show()
        return shown

    return lab.State(f"ui_next.w1_{name}", run, gated=True)


def test_the_judge_writes_its_kit(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = [_label("Captions appear here", "one"), _label("Overlay", "two")]
    monkeypatch.setattr(new_parts, "STATES", states)
    # only these states, whatever the lab gains later (not each module's list)
    monkeypatch.setattr(cli, "new_states", lambda: list(new_parts.STATES))
    monkeypatch.setattr(goldens, "GOLDENS", tmp_path / "goldens")
    out = tmp_path / "judge"
    assert cli.main(["judge", "--out", str(out)]) == 0  # never gates
    sheet = QImage(str(out / "sheets" / "w1.png"))
    assert sheet.width() > 1000 and sheet.height() > 100
    assert {p.name for p in out.glob("*.md")} >= {
        "judge.md",
        "findings.md",
        "timings.md",
        "goldens.md",
    }
    written = (out / "judge.md").read_text(encoding="utf-8")
    assert (
        "| W1, the caption window | 2 | 2 | [sheets/w1.png](sheets/w1.png) |" in written
    )
    assert "| ui_next.w1_one | 1 finding, golden: new |" in written
    assert "Not seen: idle, hovered" in written
    assert "'Overlay' says \"overlay\"" in written
    assert "# The checklist" in written
    assert "accessible_name" in (out / "findings.md").read_text(encoding="utf-8")


def test_the_joined_window_is_a_surface_of_its_own() -> None:
    assert judge.surface_of("ui_next.w1j_strip").title.startswith("W1j, the joined")
