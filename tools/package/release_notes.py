"""The release notes' one source: `RELEASE-NOTES.md` (polyglotic-hq RELEASING.md section 10, G7).

    python -m tools.package.release_notes v0.1.0 [--out notes.md]

Prints that version's notes as Markdown - the text the GitHub Release
carries above the SHA-256s (`release.yml`) - and exits 1 if the file has no
section for it, or the section has no lines. The file:

    ## Unreleased                 <- each pull request people would notice adds a line
    ### New / ### Better / ### Fixed

    ## 0.1.0 - 2026-11-12         <- at a release, Unreleased moves under its version
    One optional paragraph.
    ### New
    - A line, in plain words.

The groups are the site's (`content/releases.json`): New, Better and Fixed,
in that order; a version leaves out a group it has nothing for. Newest
version first. Standard library only: the release workflow runs it without
installing the app.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

NOTES = Path(__file__).resolve().parents[2] / "RELEASE-NOTES.md"
GROUPS = ("New", "Better", "Fixed")
UNRELEASED = "Unreleased"
VERSION_HEADING = re.compile(
    r"^## (?P<version>(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*))"
    r" - (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$"
)


@dataclass
class Section:
    """One `## ` section: Unreleased, or a version and its date."""

    title: str
    date: str = ""
    intro: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)

    def lines(self) -> int:
        return sum(len(items) for items in self.groups.values())

    def markdown(self) -> str:
        """The section's text, without its own heading: the intro, then each
        group that has lines."""
        out = [" ".join(self.intro)] if self.intro else []
        for name in GROUPS:
            if self.groups.get(name):
                out.append(
                    f"### {name}\n\n"
                    + "\n".join(f"- {line}" for line in self.groups[name])
                )
        return "\n\n".join(out) + "\n"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def parse(text: str) -> list[Section]:
    """Every `## ` section, in the file's order; ValueError for anything the
    format doesn't allow (an unknown heading or group, a version without its
    date, versions out of order, a line outside a group)."""
    sections: list[Section] = []
    group: list[str] | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        where = f"RELEASE-NOTES.md line {number}"
        if line.startswith("## "):
            if line == f"## {UNRELEASED}":
                sections.append(Section(UNRELEASED))
            elif heading := VERSION_HEADING.match(line):
                sections.append(Section(heading["version"], heading["date"]))
            else:
                raise ValueError(
                    f"{where}: a section is '## Unreleased' or '## X.Y.Z - YYYY-MM-DD'"
                )
            group = None
        elif not sections:
            continue  # the title and the file's own introduction
        elif line.startswith("### "):
            name = line[4:]
            if name not in GROUPS:
                raise ValueError(f"{where}: the groups are {', '.join(GROUPS)}")
            if name in sections[-1].groups:
                raise ValueError(f"{where}: {name} twice in one section")
            group = sections[-1].groups[name] = []
        elif line.startswith("- "):
            if group is None:
                raise ValueError(f"{where}: a line belongs in New, Better or Fixed")
            group.append(line[2:].strip())
        elif line.startswith("  ") and group:
            group[-1] += " " + line.strip()  # a line wrapped onto the next
        elif line and group is None:
            sections[-1].intro.append(line.strip())
        elif line:
            raise ValueError(f"{where}: inside a group, each line starts with '- '")
    versions = [s.title for s in sections if s.title != UNRELEASED]
    if len(set(versions)) != len(versions):
        raise ValueError("RELEASE-NOTES.md: a version has two sections")
    if versions != sorted(versions, key=_version_key, reverse=True):
        raise ValueError("RELEASE-NOTES.md: the newest version comes first")
    return sections


def notes_for(text: str, version: str) -> Section:
    """`version`'s section (`0.1.0`, or the tag `v0.1.0`); LookupError if
    the file has none or it has no lines."""
    version = version.removeprefix("v")
    for section in parse(text):
        if section.title == version:
            if not section.lines():
                raise LookupError(f"RELEASE-NOTES.md: {version} has no lines")
            return section
    raise LookupError(
        f"RELEASE-NOTES.md has no '## {version} - YYYY-MM-DD': move Unreleased"
        " under it in the release's prep pull request"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.package.release_notes")
    parser.add_argument("tag", help="the release's tag (v0.1.0) or version")
    parser.add_argument("--file", type=Path, default=NOTES)
    parser.add_argument("--out", type=Path, help="write the notes here, not to stdout")
    args = parser.parse_args(argv)
    try:
        section = notes_for(args.file.read_text(encoding="utf-8"), args.tag)
    except (OSError, LookupError, ValueError) as e:
        print(f"No release notes: {e}", file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(section.markdown(), encoding="utf-8")
    else:
        sys.stdout.write(section.markdown())
    return 0


if __name__ == "__main__":
    sys.exit(main())
