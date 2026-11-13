"""How busy the PC is (`tools.busy_pc`, decision 0040): read from the
system's own CPU counters on Windows and Linux, and only a saturated PC
earns an action over budget more tries."""

import sys

import pytest

from tools import busy_pc


@pytest.mark.skipif(
    sys.platform not in ("win32", "linux"), reason="reads Windows' or Linux's counters"
)
def test_the_load_is_read_as_a_share_of_the_cpu() -> None:
    share = busy_pc.busy_share(0.05)
    assert share is not None and 0.0 <= share <= 1.0


def test_only_a_saturated_pc_counts() -> None:
    assert busy_pc.saturated(0.5) and busy_pc.saturated(1.0)
    assert not busy_pc.saturated(0.49)  # busy, not saturated
    assert not busy_pc.saturated(None)  # unknown: no more tries


def test_the_load_is_said_in_words() -> None:
    assert busy_pc.describe(0.966) == "the PC 97% busy"
    assert busy_pc.describe(None) == "the PC's load unknown"
