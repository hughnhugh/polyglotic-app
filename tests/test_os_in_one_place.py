"""The OS is picked in one place (decision 0038, polyglotic-hq 179): `main`
loads without any OS's adapters - so it, and the tests that import it, load
on macOS and Linux too - and asks `os_adapters` for them when it starts,
which says what's missing on an OS that has none yet."""

import subprocess
import sys
from typing import cast

import pytest
from tests import conftest

from polyglotic_desktop.main import NoOsAdapters, os_adapters

WINDOWS_ONLY = (
    "polyglotic_desktop.platform.windows",
    "polyglotic_desktop.adapters.windows_credentials",
)


def test_main_loads_without_any_os_adapters() -> None:
    """Before 179, `main` imported every Windows module at the top: 41 test
    files couldn't be collected on Linux (171's probe)."""
    script = (
        "import sys, polyglotic_desktop.main\n"
        f"print('\\n'.join(m for m in sys.modules if m.startswith({WINDOWS_ONLY!r})))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert loaded.stdout.split() == []


@pytest.mark.parametrize(
    ("system", "missing"), [("linux", "linux"), ("darwin", "macos")]
)
def test_an_os_without_adapters_is_told_what_is_missing(
    system: str, missing: str
) -> None:
    with pytest.raises(NoOsAdapters) as error:
        os_adapters(system)
    assert system in str(error.value) and f"platform/{missing}" in str(error.value)


class Item:
    """A collected test, as the hook sees it."""

    def __init__(self, windows_only: bool) -> None:
        self.windows_only = windows_only
        self.added: list[pytest.MarkDecorator] = []

    def get_closest_marker(self, name: str) -> object | None:
        return name if name == "windows_only" and self.windows_only else None

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.added.append(marker)


@pytest.mark.parametrize(("system", "skipped"), [("linux", 1), ("win32", 0)])
def test_windows_only_tests_are_skipped_off_windows(
    monkeypatch: pytest.MonkeyPatch, system: str, skipped: int
) -> None:
    marked, other = Item(windows_only=True), Item(windows_only=False)
    monkeypatch.setattr(sys, "platform", system)
    items = cast(list[pytest.Item], [marked, other])
    conftest.pytest_collection_modifyitems(cast(pytest.Config, None), items)
    assert (len(marked.added), len(other.added)) == (skipped, 0)


def test_whose_copy_is_asked_without_failing_where_an_os_has_no_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main` asks whether it's the Microsoft Store's copy before anything
    else (decision 0056). Where the OS has no adapters yet that's None, not
    an error, so `--check-install` still runs and reports what's missing
    (CI's Linux job found the error on 2026-11-09)."""
    from polyglotic_desktop import main

    def none_here() -> None:
        raise NoOsAdapters("none here")

    monkeypatch.setattr(main, "os_adapters", none_here)
    assert main.store_copy_here() is None
