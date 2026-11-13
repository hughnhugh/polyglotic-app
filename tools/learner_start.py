"""The app's start with a made-up learner of many words met: `main()` from
source, offscreen, timed from its call to the main window's first paint -
the span `--check-install`'s `window_seconds` measures, held to
`perf.budgets.START_FROM_SOURCE` (polyglotic-hq 220, 229). CI's start gate
(`tests/ui/test_start_with_a_big_learner.py`) runs it on the real CC-CEDICT;
by hand:

    uv run python -m tools.dictionaries.build --only cedict
    uv run python -m tools.learner_start --words 10000 --runs 5

The learner is made up, never a real learner's file: CC-CEDICT's commonest
N entries, heard on 163's Zipf curve, HSK 4 picked, with 212's proportions
of deck, known and saved words. A returning learner: the learning language
chosen, the tester agreement accepted, so nothing is asked.

Each start is a process of its own (`--child`), as a real start is. It
signs in nowhere and captures, plays and connects nothing: no hotkeys, no
app list, the device token's store in memory (empty), the update feed an
empty folder; it ends at the window's first paint, before the connection,
speech detection or anything after the window is reached. It writes in
the data folder it's given, and its time in a file beside it.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

LEVEL = 4
"""The made-up learner's HSK level (2025 syllabus)."""

TODAY = date(2026, 11, 8)
"""The made-up learner's today, so the learner is the same whenever made."""

CHILD_TIMEOUT_SECONDS = 120


def made_up_learner(cedict: Path, words: int, out: Path) -> None:
    """A learning data file at `out` for a Chinese learner who has met
    `cedict`'s commonest `words` entries: entry rank r heard
    max(1, round(20 * words / r ** 1.15)) times (163's Zipf curve), first
    heard up to 180 days before `TODAY`; HSK `LEVEL` picked; of the words
    still new at that level, words/40 in the deck, words/25 known by hand
    and words/50 saved (212's proportions)."""
    from polyglotic_desktop.adapters.sqlite_dictionary import GuardedDictionary
    from polyglotic_desktop.adapters.sqlite_learning import open_learning_store
    from polyglotic_desktop.core.learning.lookups import LookupContext
    from polyglotic_desktop.core.learning.vocabulary import Vocabulary
    from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary
    from polyglotic_desktop.core.lexicon.meanings import short_meaning
    from polyglotic_desktop.core.shared import EntryId, Level, WordStatus
    from polyglotic_desktop.ports.learning import StoredExposures

    db = sqlite3.connect(f"{cedict.resolve().as_uri()}?mode=ro", uri=True)
    try:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM entries"
                " ORDER BY frequency_rank IS NULL, frequency_rank, n LIMIT ?",
                (words,),
            )
        ]
    finally:
        db.close()
    if len(ids) < words:  # the tests' sample, say: a small learner, unsaid
        raise ValueError(f"{cedict.name} has {len(ids):,} entries, not {words:,}")
    file = GuardedDictionary(cedict)
    dictionary = ChineseDictionary(file)
    out.unlink(missing_ok=True)
    store = open_learning_store(out)
    try:
        store.save_exposures(
            [
                StoredExposures(
                    entry,
                    max(1, round(20 * words / rank**1.15)),
                    0,
                    0,
                    TODAY - timedelta(days=rank % 180),
                )
                for rank, entry in enumerate(ids, 1)
            ],
            {},
        )
        vocabulary = Vocabulary(store, dictionary.facts, "hsk-2025")
        vocabulary.set_level(Level("hsk-2025", LEVEL))
        new = [
            EntryId(e)
            for e in ids
            if vocabulary.status_of_entry(EntryId(e)).status is WordStatus.NEW
        ]
        deck, by_hand, saved = words // 40, words // 25, words // 50
        for entry_id in new[:deck]:
            vocabulary.set_status(entry_id, WordStatus.LEARNING)
        for entry_id in new[deck : deck + by_hand]:
            vocabulary.set_status(entry_id, WordStatus.KNOWN)
        category = vocabulary.categories[0].id
        for entry_id in new[deck + by_hand : deck + by_hand + saved]:
            entry = dictionary.entry(entry_id)
            if entry is None:
                continue
            vocabulary.save(
                entry_id,
                entry.headword,
                entry.traditional,
                entry.reading,
                short_meaning([entry]),
                category,
                LookupContext(entry.headword),
            )
    finally:
        store.close()
        file.close()


def returning_learner(folder: Path, learning: Path) -> Path:
    """A data folder at `folder` for a returning Chinese learner whose
    learning data is a copy of `learning`: the language chosen and the
    tester agreement accepted (no usage statistics, crash reports or
    exposures shared), so the start asks nothing."""
    from polyglotic_desktop.adapters.sqlite_outbox import open_outbox
    from polyglotic_desktop.core.shared.papers import TESTER_AGREEMENT_VERSION
    from polyglotic_desktop.ports.consent import Agreement, ConsentChoice

    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(
        json.dumps({"learning": "zh"}), encoding="utf-8"
    )
    shutil.copy(learning, folder / "learning.sqlite")
    at = datetime(2026, 11, 8, tzinfo=UTC)
    outbox = open_outbox(folder / "outbox.sqlite")
    try:
        outbox.save_consent(
            ConsentChoice(
                str(uuid.UUID(int=229)),
                at,
                usage=False,
                crashes=False,
                exposures=False,
                agreement=Agreement(TESTER_AGREEMENT_VERSION, at),
            )
        )
    finally:
        outbox.close()
    (folder / "no-feed").mkdir()
    return folder


def timed_start(data: Path, dictionaries: Path) -> float:
    """Milliseconds from `main()`'s call to the main window's first paint,
    in a process of its own, offscreen, on the learner's data folder
    `data` and the dictionaries in `dictionaries`."""
    report = data.parent / f"{data.name}-start.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.learner_start",
            "--child",
            str(data),
            str(dictionaries),
            str(report),
        ],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=CHILD_TIMEOUT_SECONDS,
        check=False,
    )
    if not report.exists():
        raise RuntimeError(
            f"the start didn't reach its window (exit {done.returncode}):"
            f" {done.stderr.decode(errors='replace')[-2000:]}"
        )
    found = json.loads(report.read_text(encoding="utf-8"))
    return float(found["window_ms"])


def _child(data: Path, dictionaries: Path, report: Path) -> None:
    """`main()` on `data`, timed to the window's first paint, then ended at
    once - before the connection or anything after the window."""
    from PySide6.QtWidgets import QApplication
    from tests.fakes import MemoryCredentialStore

    from polyglotic_desktop import main as m

    class NoHotkeys:
        def __init__(self, keys: object) -> None:
            pass

        def start(self) -> list[str]:
            return []

        def stop(self) -> None:
            pass

    class Silent:
        def play(self, audio: object, rate: int) -> bool:
            return True

        def stop(self) -> None:
            pass

    class NoWatch:
        def __init__(self, changed: object) -> None:
            pass

        def start(self) -> bool:
            return False

        def stop(self) -> None:
            pass

    real = m.os_adapters

    def os_adapters(system: str = sys.platform) -> m.OsAdapters:
        return dataclasses.replace(
            real(system),
            app_list=m.NoApps,
            credentials=lambda target: MemoryCredentialStore(),
            hotkeys=NoHotkeys,
            sound_out=Silent,
            foreground_watch=NoWatch,
        )

    shown: list[bool] = []
    started = 0.0

    class Shown(m.DesktopApp):
        def show_window(self) -> None:
            super().show_window()
            shown.append(True)

    class Timed(QApplication):
        def processEvents(self) -> None:  # type: ignore[override]
            super().processEvents()  # as main calls it: no arguments
            if shown:  # main's processEvents after the window: its first paint
                window_ms = (time.perf_counter() - started) * 1000
                report.write_text(
                    json.dumps({"window_ms": round(window_ms, 1)}), encoding="utf-8"
                )
                os._exit(0)  # nothing after the window: no connection, no sign-in

    m.os_adapters = os_adapters
    m.DesktopApp = Shown  # type: ignore[misc]
    m.QApplication = Timed  # type: ignore[misc]
    argv = [
        "--server",
        "http://127.0.0.1:9",  # never reached: the start ends at the window
        "--data",
        str(data),
        "--dictionaries",
        str(dictionaries),
        "--updates",
        str(data / "no-feed"),
    ]
    started = time.perf_counter()
    m.main(argv)
    raise SystemExit("main() returned without showing its window")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--child", nargs=3, type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--dictionaries",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "build" / "dictionaries",
    )
    parser.add_argument("--words", type=int, default=10_000)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)
    if args.child:
        _child(*args.child)
        return 1  # not reached
    with tempfile.TemporaryDirectory(prefix="learner-start-") as folder:
        learning = Path(folder) / "learning.sqlite"
        started = time.perf_counter()
        made_up_learner(args.dictionaries / "cedict.sqlite", args.words, learning)
        made = time.perf_counter() - started
        print(f"made-up learner of {args.words:,} words met: {made:.1f} s")
        runs = []
        for n in range(1, args.runs + 1):
            data = returning_learner(Path(folder) / f"start-{n}", learning)
            runs.append(timed_start(data, args.dictionaries))
            print(f"start {n}: {runs[-1]:.0f} ms")
        print(
            f"median {statistics.median(runs):.0f} ms,"
            f" {min(runs):.0f}-{max(runs):.0f} ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
