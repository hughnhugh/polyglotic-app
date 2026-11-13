"""Timing an action against its budget (`perf.budgets`, polyglotic-hq
DECISIONS.md #53) the way the UI lab does: a budget means a typical
action, not the worst moment of a busy PC (polyglotic-hq project 140).

- `sampled` runs the actions once as a warm-up - the first paint, polish
  or font load the app pays once; timed for the record, not judged - then
  times each again with everything it queues. The garbage collector is
  held off throughout: late in the suite this process holds thousands of
  Qt objects, and a full collection landing in one run took 91-99 ms in CI
  (2026-11-07, project 115; the action: 5-20 ms). Single runs of 68-215 ms
  failed three more tests that day whose runs take 1-2 ms.
- `within` holds the median to the budget and every run to the slot budget
  (50 ms; or the budget, where that's longer). If either is over, it takes
  the samples once more, and up to twice more again while the PC measures
  saturated (`tools.busy_pc`, decision 0040); it fails only if the last try
  is over too, naming every try and how busy the PC was. A real slowdown -
  every run slower, or a run over 50 ms in each try - fails every try.
- Each judgement is recorded in `JUDGED`: pytest's summary lists every
  one's median and longest run, the warm-up's too (`tests/conftest.py`),
  and in CI the run's page shows the table.
"""

from __future__ import annotations

import gc
import os
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from polyglotic_desktop.perf import budgets
from polyglotic_desktop.perf.budgets import Budget
from tools import busy_pc

if TYPE_CHECKING:  # the summary (conftest) needs no Qt
    from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Sampled:
    """One try: the judged runs and the warm-up's, in milliseconds."""

    runs: tuple[float, ...]
    warm_up: tuple[float, ...] = ()

    @property
    def median(self) -> float:
        return statistics.median(self.runs)

    @property
    def longest(self) -> float:
        return max(self.runs)

    def describe(self) -> str:
        return f"median {self.median:.1f} ms, longest {self.longest:.1f} ms"


@dataclass(frozen=True)
class Judged:
    """A budget test's verdict: one try, or more if the first was over."""

    test: str
    budget: Budget
    tries: tuple[Sampled, ...]
    passed: bool
    busy: tuple[float | None, ...] = ()
    """The PC's load, read after each try from the second that was over."""

    def verdict(self) -> str:
        """The verdict, with the first try's numbers if there were more."""
        n = len(self.tries)
        if n == 1:
            return "ok"  # a first try over is always taken again
        first = f"try 1: {self.tries[0].describe()}"
        if self.busy:
            first += f"; {busy_pc.describe(self.busy[-1])}"
        if self.passed:
            return f"ok on try {n} ({first})"
        return f"over in {_all(n)} ({first})"


def _all(tries: int) -> str:
    return "both tries" if tries == 2 else f"all {tries} tries"


JUDGED: list[Judged] = []
"""Every judgement of this run, in order, for the summary."""


def timed(qapp: QApplication, action: Callable[[], object]) -> float:
    """Milliseconds for `action` and everything it queues."""
    start = time.perf_counter()
    action()
    qapp.processEvents()
    return (time.perf_counter() - start) * 1000


def sampled(
    qapp: QApplication, actions: Sequence[Callable[[], object]], warm: bool = True
) -> Sampled:
    """Each of `actions` timed, after one pass of them all if `warm` (timed
    for the record, not judged), with the garbage collector held off.
    `warm=False` for a first time, judged as one."""
    collecting = gc.isenabled()
    gc.disable()
    try:
        warm_up = tuple(timed(qapp, action) for action in actions) if warm else ()
        return Sampled(tuple(timed(qapp, action) for action in actions), warm_up)
    finally:
        if collecting:
            gc.enable()


def longest_allowed(budget: Budget) -> float:
    """What any one run may take: the slot budget, or the budget itself
    where that's longer (a theme change, a start)."""
    return max(budget.ms, budgets.SLOT.ms)


def fits(budget: Budget, sample: Sampled) -> bool:
    return sample.median <= budget.ms and sample.longest <= longest_allowed(budget)


def within(budget: Budget, take: Callable[[], Sampled]) -> None:
    """`take`'s samples within `budget`: the median within it and no run
    over `longest_allowed`. If over, they're taken once more, and again
    while the PC measures saturated, up to `busy_pc.MOST_TRIES` (decision
    0040); the test fails only if the last try is over too, and says what
    every try found and how busy the PC was."""
    tries = [take()]
    busy: list[float | None] = []
    while not fits(budget, tries[-1]) and len(tries) < busy_pc.MOST_TRIES:
        if len(tries) >= 2:
            busy.append(busy_pc.busy_share())
            if not busy_pc.saturated(busy[-1]):
                break
        tries.append(take())
    passed = fits(budget, tries[-1])
    if not passed and not busy:
        busy.append(busy_pc.busy_share())  # to say how busy, not to try again
    test = os.environ.get("PYTEST_CURRENT_TEST", "").split(" (")[0]
    JUDGED.append(Judged(test, budget, tuple(tries), passed, tuple(busy)))
    assert passed, (
        f"{budget.name} over its {budget.ms:g} ms (any one run"
        f" {longest_allowed(budget):g} ms) in {_all(len(tries))}: "
        + "; ".join(f"try {n}: {t.describe()}" for n, t in enumerate(tries, 1))
        + f"; {busy_pc.describe(busy[-1])}"
    )


def _ordered() -> list[Judged]:
    """Over first, then retried, then the rest as they ran."""
    return sorted(JUDGED, key=lambda j: (j.passed, len(j.tries) == 1))


def summary_lines() -> list[str]:
    """Every judgement, one line each, for pytest's summary."""
    lines = []
    for judged in _ordered():
        last, first = judged.tries[-1], judged.tries[0]
        warm = f"{max(first.warm_up):.1f}" if first.warm_up else "-"
        lines.append(
            f"{judged.test.rsplit('/', 1)[-1]}  {judged.budget.name}"
            f" {judged.budget.ms:g}: median {last.median:.1f}, longest"
            f" {last.longest:.1f}, warm-up longest {warm} - {judged.verdict()}"
        )
    return lines


def summary_markdown() -> str:
    """Every judgement as a table, for CI's run page."""
    lines = [
        "## Budget tests",
        "",
        (
            "Each timed action in the main suite (pytest), offscreen, in ms: the"
            " median of its runs is held to the budget and its longest run to"
            " 50 ms (or the budget, if longer). A try over either is taken once"
            " more - up to twice more again while the PC measures saturated"
            " (decision 0040) - and the first is shown with the last. The"
            " warm-up (a first pass of the same actions) is recorded, not"
            " judged."
        ),
        "",
        "| Test | Budget | Median | Longest | Warm-up longest | |",
        "|---|---|---|---|---|---|",
    ]
    for judged in _ordered():
        last, first = judged.tries[-1], judged.tries[0]
        warm = f"{max(first.warm_up):.1f}" if first.warm_up else ""
        verdict = judged.verdict()
        lines.append(
            f"| {judged.test.rsplit('/', 1)[-1]} | {judged.budget.name}"
            f" {judged.budget.ms:g} | {last.median:.1f} | {last.longest:.1f} |"
            f" {warm} | {verdict if judged.passed else f'**{verdict}**'} |"
        )
    return "\n".join(lines) + "\n"
