"""The tools' tests. The UI lab's fonts are set up before any test draws
text (polyglotic-hq 198): Qt doesn't take Windows' fonts registered late in
a long run, after many other tests have drawn (`pytest tests/ui_next
tests/tools`), and the lab sets them up first, as it starts."""

import pytest


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    if any("test_ui_lab" in item.nodeid for item in items):
        from tools.ui_lab import lab

        lab.application()
