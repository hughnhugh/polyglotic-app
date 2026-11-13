"""The release notes' one source (polyglotic-hq RELEASING.md section 10, G7):
`RELEASE-NOTES.md` parses, and a version's notes are what the GitHub
Release carries - or the release stops."""

from pathlib import Path

import pytest
import yaml
from tools.package import release_notes
from tools.package.release_notes import notes_for, parse

FILE = """# Release notes

Anything before the first section is the file's own introduction.

## Unreleased

### New

### Better

### Fixed

## 0.2.0 - 2026-11-20

A short paragraph about
the release.

### New

- Something new, wrapped
  onto a second line.

### Fixed

- A fix.

## 0.1.0 - 2026-11-12

### New

- The first alpha.
"""


def test_a_versions_notes_are_its_groups_in_order() -> None:
    section = notes_for(FILE, "v0.2.0")
    assert section.date == "2026-11-20"
    assert section.groups == {
        "New": ["Something new, wrapped onto a second line."],
        "Fixed": ["A fix."],
    }
    assert section.markdown() == (
        "A short paragraph about the release.\n\n"
        "### New\n\n- Something new, wrapped onto a second line.\n\n"
        "### Fixed\n\n- A fix.\n"
    )


def test_unreleased_is_a_section_with_no_lines() -> None:
    unreleased = parse(FILE)[0]
    assert unreleased.title == "Unreleased"
    assert unreleased.groups == {"New": [], "Better": [], "Fixed": []}


def test_a_tag_without_a_section_has_no_notes() -> None:
    with pytest.raises(LookupError, match=r"no '## 0\.3\.0"):
        notes_for(FILE, "v0.3.0")


def test_a_section_with_no_lines_has_no_notes() -> None:
    with pytest.raises(LookupError, match="no lines"):
        notes_for(FILE.replace("- The first alpha.\n", ""), "0.1.0")


@pytest.mark.parametrize(
    ("broken", "says"),
    [
        (FILE.replace("## 0.1.0 - 2026-11-12", "## 0.1.0"), "X.Y.Z - YYYY-MM-DD"),
        (FILE.replace("### Fixed\n\n- A fix.", "### Fixes\n\n- A fix."), "the groups"),
        (
            FILE.replace("A short paragraph about", "- A line before a group"),
            "belongs in",
        ),
        (FILE.replace("- A fix.", "A fix without its dash."), "starts with '- '"),
        (FILE.replace("0.2.0 - 2026", "0.0.9 - 2026"), "newest version comes first"),
        (FILE.replace("0.2.0 - 2026", "0.1.0 - 2026"), "two sections"),
    ],
)
def test_what_the_format_doesnt_allow_is_refused(broken: str, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        parse(broken)


def test_the_command_writes_the_notes_or_fails(tmp_path: Path) -> None:
    source = tmp_path / "RELEASE-NOTES.md"
    source.write_text(FILE, encoding="utf-8")
    out = tmp_path / "notes.md"
    assert release_notes.main(["v0.1.0", "--file", str(source), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "### New\n\n- The first alpha.\n"
    missing = tmp_path / "missing.md"
    assert (
        release_notes.main(["v9.9.9", "--file", str(source), "--out", str(missing)])
        == 1
    )
    assert not missing.exists()


def test_the_repos_own_notes_parse() -> None:
    """RELEASE-NOTES.md keeps the format, with Unreleased first and its three
    groups ready for the next pull request's line."""
    sections = parse(release_notes.NOTES.read_text(encoding="utf-8"))
    assert sections[0].title == "Unreleased"
    assert list(sections[0].groups) == list(release_notes.GROUPS)
    for section in sections[1:]:
        assert section.lines(), f"{section.title} has no lines"


def test_the_release_workflow_carries_the_notes() -> None:
    """release.yml stops a tag without notes before the build, and puts the
    notes above the SHA-256s on the GitHub Release."""

    workflow = Path(release_notes.NOTES.parent, ".github", "workflows", "release.yml")
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    command = 'python -m tools.package.release_notes "$TAG"'
    assert any(command in str(step.get("run", "")) for step in jobs["tag"]["steps"])
    assert jobs["release"]["needs"] == "tag"  # builds and publishes (0050)
    record = next(
        s for s in jobs["release"]["steps"] if "GitHub Release" in s.get("name", "")
    )
    run = record["run"]
    assert command in run
    assert run.index("version-notes.md") < run.index("SHA256SUMS")
