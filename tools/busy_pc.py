"""Whether the PC is saturated right now, for judging timings fairly
(decision 0040).

The budget tests and the UI lab time interface actions in wall time, on a
PC that the CI runners and every agent's test runs share. An action over
its budget is the code or the PC. When every core is busy, the interface
thread waits its turn and a 2 ms action can take 60; on a PC that is
merely busy (the user's, 2026-11-08: 53-100 % of its 16 threads, median
71 %, while they played a game), nothing went over. So only a saturated
PC earns an action over budget more tries: no budget changes, and a calm
or busy PC gets the one retry it always had.
"""

import ctypes
import sys
import time
from pathlib import Path

SATURATED = 0.5
"""The share of the PC's CPU time in use, over `SAMPLE_SECONDS`, from which
the PC counts as saturated. Half, not 0.9 (2026-11-11): with half the
logical cores busy the physical cores are all taken, and the start-time
check (400 ms; 385-425 ms on a quiet main) failed at 49-56 % busy five
times in one evening on changes that added nothing at start."""

SAMPLE_SECONDS = 0.2
"""Long enough for Windows' CPU counters, which move in 15.6 ms ticks."""

MOST_TRIES = 4
"""Tries for an action over budget: the retry every action gets, then up
to two more while the PC measures saturated."""


def _cpu_times() -> tuple[float, float] | None:
    """(idle, total) CPU time since start, in any unit; None where the
    platform's counters aren't read."""
    if sys.platform == "win32":
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        if not ctypes.WinDLL("kernel32").GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        return float(idle.value), float(kernel.value + user.value)  # kernel has idle
    stat = Path("/proc/stat")
    if stat.is_file():
        fields = [float(n) for n in stat.read_text().split("\n", 1)[0].split()[1:]]
        return fields[3] + fields[4], sum(fields)  # idle and iowait; all
    return None


def busy_share(seconds: float = SAMPLE_SECONDS) -> float | None:
    """The share of the PC's CPU time in use over the next `seconds`, from
    0 to 1; None where it can't be read."""
    before = _cpu_times()
    time.sleep(seconds)
    after = _cpu_times()
    if before is None or after is None or after[1] <= before[1]:
        return None
    return 1 - (after[0] - before[0]) / (after[1] - before[1])


def saturated(share: float | None) -> bool:
    return share is not None and share >= SATURATED


def describe(share: float | None) -> str:
    return "the PC's load unknown" if share is None else f"the PC {share:.0%} busy"
