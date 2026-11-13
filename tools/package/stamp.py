"""The release's version from its git tag, stamped into the app (decision 0015).

    uv run python -m tools.package.stamp v0.1.0 --channel win-x64-alpha --out build/package/release.json

Writes `{"version": "0.1.0", "channel": "win-x64-alpha"}`. Refuses a tag
that isn't `v` plus protocol.md's `MAJOR.MINOR.PATCH`, and a channel
protocol.md doesn't know - checked by the same reader the app uses
(`connection.app.read_release`), so the build can't write a stamp the app
would refuse.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from polyglotic_desktop.connection.app import Release, read_release


def version_from_tag(tag: str) -> str:
    """`v0.1.0` (or `refs/tags/v0.1.0`) -> `0.1.0`; ValueError otherwise."""
    name = tag.removeprefix("refs/tags/")
    if not name.startswith("v"):
        raise ValueError(f"a release tag starts with v: {name!r}")
    return name[1:]


def stamp(version: str, channel: str) -> str:
    """`release.json`'s text, checked as the app will read it."""
    text = json.dumps({"version": version, "channel": channel}) + "\n"
    read_release(text)  # ValueError if the app would refuse it
    return text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.package.stamp")
    parser.add_argument("tag", help="the release's git tag, e.g. v0.1.0")
    parser.add_argument("--channel", default="win-x64-alpha")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        text = stamp(version_from_tag(args.tag), args.channel)
    except ValueError as e:
        print(f"Not a release tag: {e}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    release: Release = read_release(text)
    print(f"Stamped {release.version} on {release.channel} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
