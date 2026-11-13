"""The start with a big learner, held to its budget: `main()` from source,
offscreen, to the main window's first paint, with a made-up learner of
30,000 words met on the real CC-CEDICT (`tools/learner_start.py`) - within
`perf.budgets`' START_FROM_SOURCE (polyglotic-hq 229). `--check-install`
times the start with an empty learner, so a start that grew with the words
met went over unseen: 541-566 ms at 30,000 before #339 (220).

Why 30,000 and not 10,000 words met: with #339 undone, the start at 10,000
measured 406-565 ms on 2026-11-08 - often within the budget, so a gate
there wouldn't keep #339's gain; at 30,000 it was 638-906 ms, and 276-381
ms with it but for one start in 50 (`tools/learner_start.py`, one process
at a time; CI's runner included). A learner
within the budget at 30,000 is within it at 10,000: the start only grows
with the words met.

It needs the real CC-CEDICT, built from its pinned sources: CI's UI lab
job builds it (`python -m tools.dictionaries.build --only cedict`) and
names its folder in POLYGLOTIC_REAL_DICTIONARIES. Without that, it's
skipped: the tests' sample has 30 entries. The learner and a timed
start are tested everywhere on made-up dictionaries
(`tests/tools/test_learner_start.py`)."""

import itertools
import os
import statistics
from pathlib import Path

import pytest
from tests.budget_judge import Sampled, within
from tools.learner_start import made_up_learner, returning_learner, timed_start

from polyglotic_desktop.perf.budgets import START_FROM_SOURCE

WORDS = 30_000
STARTS = 5
"""Starts a try, each a process of its own. Their median is the try's one
sample, held to the budget by `budget_judge.within` and taken again if
over, as every budget test's is: the typical start, as the budget means.
Not every start: on the user's PC, shared with other agents' work, 1 of
50 starts at 30,000 words met took over 500 ms (511; the rest 276-381 ms,
2026-11-08, CI's runner included), so holding all 5 would fail about one
pull request in 100 for nothing. Undoing #339 puts every start over
(638-906 ms): the median catches it."""

REAL_DICTIONARIES = "POLYGLOTIC_REAL_DICTIONARIES"


@pytest.mark.windows_only  # the app's own OS adapters; the budget is Windows'
def test_the_window_is_shown_within_its_budget_with_30000_words_met(
    tmp_path: Path,
) -> None:
    folder = os.environ.get(REAL_DICTIONARIES)
    if not folder:
        pytest.skip(f"the real CC-CEDICT isn't built here ({REAL_DICTIONARIES})")
    dictionaries = Path(folder)
    learning = tmp_path / "learning.sqlite"
    made_up_learner(dictionaries / "cedict.sqlite", WORDS, learning)
    tries = itertools.count(1)

    def take() -> Sampled:
        n = next(tries)
        starts = [
            timed_start(
                returning_learner(tmp_path / f"try-{n}-start-{i}", learning),
                dictionaries,
            )
            for i in range(1, STARTS + 1)
        ]
        print(f"try {n}: " + ", ".join(f"{ms:.0f}" for ms in starts) + " ms")
        return Sampled((statistics.median(starts),))

    within(START_FROM_SOURCE, take)
