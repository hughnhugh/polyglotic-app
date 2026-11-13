"""The release stamp (decision 0015): the tag's version, checked as the
app reads it."""

from pathlib import Path

import pytest
from tools.package import stamp

from polyglotic_desktop.connection.app import Release, this_release


def test_the_tag_names_the_version() -> None:
    assert stamp.version_from_tag("v0.1.0") == "0.1.0"
    assert stamp.version_from_tag("refs/tags/v1.20.3") == "1.20.3"


@pytest.mark.parametrize("tag", ["0.1.0", "release-0.1.0", "v0.1", "v0.1.0-rc1"])
def test_a_tag_that_isnt_a_release_writes_nothing(tag: str, tmp_path: Path) -> None:
    out = tmp_path / "release.json"
    assert stamp.main([tag, "--out", str(out)]) == 1
    assert not out.exists()


def test_a_channel_protocol_md_doesnt_know_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "release.json"
    assert stamp.main(["v0.1.0", "--channel", "alpha", "--out", str(out)]) == 1
    assert not out.exists()


def test_the_app_reads_what_the_build_stamps(tmp_path: Path) -> None:
    out = tmp_path / "package" / "release.json"
    assert stamp.main(["v0.1.0", "--channel", "win-x64-beta", "--out", str(out)]) == 0
    assert this_release(out) == Release("0.1.0", "win-x64-beta")
