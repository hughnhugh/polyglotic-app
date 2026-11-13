"""The judge's kit: what an agent reads to review the new interface (project
108's design, section 5; built in project 119; the loop is in JUDGE.md).

    uv run python -m tools.ui_lab judge            # build/ui-lab/judge/

Runs every state of the new interface (as the gate does), then writes:

- `judge.md` - start here: each surface's states, their verdicts, the
  states 109 asks for and which the lab has, the interface's own words on
  screen (with any the glossary avoids), the checks' notes (Tab order,
  exemptions, elided text), and the checklist (`checklist.md`);
- `sheets/<surface>.png` - a contact sheet: every state of a surface on one
  image, labelled, scaled down (each state's own PNG, full size, is beside
  `judge.md`);
- `findings.md` - the code checks' findings; `timings.md` - the timings
  against the budgets; `goldens.md` - the pictures against their goldens.

Nothing here judges: it lays out what an agent (Claude or Fable) needs to.
"""

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from tools.ui_lab import goldens, lab
from tools.ui_lab.lab import Result, State

CHECKLIST = Path(__file__).resolve().parent / "checklist.md"


@dataclass(frozen=True)
class Surface:
    """A part of the interface the judge looks at as one: its states share
    the first word of their name after `ui_next.`."""

    key: str
    title: str
    expected: tuple[str, ...] = ()
    """The states project 109's STRUCTURE.md draws for it, as words a lab
    state's name would hold (read 2026-11-07)."""


SURFACES = {
    surface.key: surface
    for surface in (
        Surface(
            "foundation",
            "The caption surface (foundation): what every caption window,"
            " transcript and joined window stands on",
        ),
        Surface(
            "w1",
            "W1, the caption window (STRUCTURE.md section 2)",
            (
                "idle",
                "hovered",
                "narrow",
                "locked",
                "scrolled_back",
                "paused",
                "notice",
                "fading",
                "hidden",
                "strip",
                "empty",
                "preview_line",
                "listening",
                "original_only",
                "my_speech",
            ),
        ),
        Surface(
            "w1j",
            "W1j, the joined window (STRUCTURE.md section 2a)",
            (
                "idle",
                "hovered",
                "two",
                "three",
                "strip",
                "empty",
                "scrolled_back",
                "locked",
                "notice",
                "separat",
            ),
        ),
        Surface(
            "w2",
            "W2, the transcript (STRUCTURE.md section 3)",
            (
                "following",
                "scrolled_back",
                "search",
                "empty",
                "rail",
                "paused",
                "notice",
                "1000",
                "minimum",
            ),
        ),
        Surface(
            "w3",
            "W3, the lookup card (STRUCTURE.md section 6)",
            ("hover", "pinned", "part", "not_found", "save_to"),
        ),
        Surface(
            "w4",
            "W4, the main window (STRUCTURE.md section 7)",
            (
                "home",
                "words",
                "account",
                "settings",
                "help",
                "first_run",
                "signed_out",
                "paused",
                "notice",
                "light",
                "dark",
                "minimum",
            ),
        ),
        Surface(
            "panel",
            "The three shared panels (STRUCTURE.md section 4)",
            ("languages", "timing", "look"),
        ),
    )
}
FOUNDATION = ("caption", "transcript", "joined")
"""The first words of the foundation's states (`new_parts.py`)."""
AVOID = {
    "overlay": "caption window (109's principle 6; DOMAIN.md keeps it as the term of art)",
    "final": "finished caption",
    "segment": "word split",
}
"""Words the glossary (DOMAIN.md) replaces on screen, and with what."""


def surface_of(state: str) -> Surface:
    first = state.removeprefix("ui_next.").split("_")[0]
    key = "foundation" if first in FOUNDATION else first
    return SURFACES.get(key) or Surface(key, key)


def run(states: list[State], out: Path) -> list[Result]:
    """Every state run into `out`, then the judge's files beside them."""
    results = lab.run(states, out, goldens.GOLDENS)
    write(results, out)
    return results


def write(results: list[Result], out: Path) -> None:
    groups: dict[str, list[Result]] = {}
    for result in results:
        groups.setdefault(surface_of(result.state).key, []).append(result)
    sheets = out / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    for stale in sheets.glob("*.png"):
        stale.unlink()
    for key, members in groups.items():
        contact_sheet(
            surface_of(members[0].state).title, members, sheets / f"{key}.png"
        )
    (out / "findings.md").write_text(lab.findings_markdown(results), encoding="utf-8")
    (out / "timings.md").write_text(lab.timings_markdown(results), encoding="utf-8")
    (out / "goldens.md").write_text(
        lab.goldens_markdown(results) or "No goldens compared.\n", encoding="utf-8"
    )
    (out / "judge.md").write_text(index(groups), encoding="utf-8")


# -- the contact sheet ----------------------------------------------------------------

COLUMNS = 3
CELL = (480, 320)
"""The most a state's picture takes on a sheet; never scaled up."""
MARGIN, GAP, LABEL = 20, 20, 22
SHEET, INK, DIM, BAD, GOOD = "#1b1e24", "#e9ecf2", "#a0a8b6", "#ff8a80", "#7ee0a8"


def verdict(result: Result) -> tuple[str, str]:
    """A state's verdict in a few words, and its colour."""
    said = []
    if result.over_budget():
        said.append("over budget")
    failed = len(result.failed_checks())
    if failed:
        said.append(f"{failed} finding{'s' if failed > 1 else ''}")
    if result.golden is not None and result.golden.failed:
        said.append(f"golden: {result.golden.status}")
    return (", ".join(said), BAD) if said else ("ok", GOOD)


def contact_sheet(title: str, results: list[Result], path: Path) -> None:
    """Every state on one image, labelled, `COLUMNS` to a row."""
    pictures = [(r, r.photo) for r in results if r.photo is not None]
    scaled = [
        (r, p.scaled(*CELL, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
         if p.width() > CELL[0] or p.height() > CELL[1] else p)
        for r, p in pictures
    ]  # fmt: skip
    rows = [scaled[i : i + COLUMNS] for i in range(0, len(scaled), COLUMNS)]
    heights = [LABEL + max(p.height() for _, p in row) for row in rows]
    width = 2 * MARGIN + COLUMNS * CELL[0] + (COLUMNS - 1) * GAP
    height = 2 * MARGIN + 34 + sum(heights) + GAP * max(0, len(rows) - 1)
    sheet = QImage(width, height, QImage.Format.Format_RGB32)
    sheet.fill(QColor(SHEET))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    heading = QFont()
    heading.setPixelSize(18)
    heading.setBold(True)
    painter.setFont(heading)
    painter.setPen(QColor(INK))
    painter.drawText(QRect(MARGIN, MARGIN, width - 2 * MARGIN, 26), 0, title)
    small = QFont()
    small.setPixelSize(13)
    painter.setFont(small)
    y = MARGIN + 34
    for row, row_height in zip(rows, heights, strict=True):
        for column, (result, picture) in enumerate(row):
            x = MARGIN + column * (CELL[0] + GAP)
            name = result.state.removeprefix("ui_next.")
            said, color = verdict(result)
            painter.setPen(QColor(INK))
            painter.drawText(QRect(x, y, CELL[0], LABEL - 4), 0, name)
            painter.setPen(QColor(color))
            painter.drawText(
                QRect(x, y, CELL[0], LABEL - 4), int(Qt.AlignmentFlag.AlignRight), said
            )
            painter.drawImage(x, y + LABEL, picture)
            painter.setPen(QColor(DIM))
            painter.drawRect(
                x - 1, y + LABEL - 1, picture.width() + 1, picture.height() + 1
            )
        y += row_height + GAP
    painter.end()
    sheet.save(str(path))


# -- judge.md ------------------------------------------------------------------------


def _avoided(words: list[str]) -> list[str]:
    found = []
    for word, instead in AVOID.items():
        pattern = re.compile(rf"\b{word}\b", re.IGNORECASE)
        for text in words:
            if pattern.search(text):
                found.append(
                    f"'{text}' says \"{word}\": the glossary's word is {instead}"
                )
    return found


def _commit() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip()


def index(groups: dict[str, list[Result]]) -> str:
    """judge.md: where to start."""
    when = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    machine = goldens.machine_note() or "the machine that made the goldens"
    lines = [
        "# The judge's run",
        "",
        f"{when}, commit {_commit()}, on {machine}. How to use this: `tools/ui_lab/JUDGE.md`.",
        "",
        "| Surface | States | Not ok | Sheet |",
        "|---|---|---|---|",
    ]
    for key, members in groups.items():
        bad = sum(1 for r in members if verdict(r)[0] != "ok")
        title = surface_of(members[0].state).title.split(" (")[0].split(":")[0]
        lines.append(
            f"| {title} | {len(members)} | {bad} | [sheets/{key}.png](sheets/{key}.png) |"
        )
    lines += [
        "",
        (
            "Also here: [findings.md](findings.md) (the code checks),"
            " [timings.md](timings.md) (against the budgets), [goldens.md](goldens.md),"
            " and each state's PNG and JSON, full size."
        ),
        "",
    ]
    for key, members in groups.items():
        lines += _surface_section(key, members)
    lines += ["", CHECKLIST.read_text(encoding="utf-8")]
    return "\n".join(lines) + "\n"


def _surface_section(key: str, members: list[Result]) -> list[str]:
    surface = surface_of(members[0].state)
    lines = [
        f"## {surface.title}",
        "",
        f"Sheet: [sheets/{key}.png](sheets/{key}.png)",
        "",
    ]
    lines += ["| State | Verdict | Picture |", "|---|---|---|"]
    for result in members:
        said, _ = verdict(result)
        lines.append(
            f"| {result.state} | {said} | [{result.state}.png]({result.state}.png) |"
        )
    if surface.expected:
        names = " ".join(r.state for r in members)
        have = [w for w in surface.expected if w in names]
        missing = [w for w in surface.expected if w not in names]
        lines += [
            "",
            (
                f"**States 109 draws:** in the lab: {', '.join(have) or 'none'}."
                f" Not seen: {', '.join(missing) or 'none'}."
            ),
        ]
    words = []
    for result in members:
        words += [w for w in result.words if w not in words]
    if words:
        lines += ["", "**The interface's words here:** " + " · ".join(words)]
        avoided = _avoided(words)
        if avoided:
            lines += [
                "",
                "**Words the glossary avoids:**",
                *[f"- {a}" for a in avoided],
            ]
    notes = []
    for result in members:
        notes += [n for n in result.notes if n not in notes]
    if notes:
        lines += ["", "**The checks' notes:**", *[f"- {n}" for n in notes]]
    return [*lines, ""]
