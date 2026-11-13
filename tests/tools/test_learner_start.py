"""`tools/learner_start.py`: the made-up learner and a start timed to its
window, which CI's start gate runs on the real CC-CEDICT
(`tests/ui/test_start_with_a_big_learner.py`) - here on small made-up
dictionaries, so they're tested on every run."""

import sqlite3
from pathlib import Path

import pytest
from tests.ui.test_check_install import sample_dictionaries
from tools.learner_start import made_up_learner, returning_learner, timed_start

from polyglotic_desktop.adapters.json_settings import JsonSettingsStore
from polyglotic_desktop.adapters.sqlite_dictionary import write_dictionary
from polyglotic_desktop.adapters.sqlite_outbox import open_outbox
from polyglotic_desktop.ports.dictionary import EntryRecord
from polyglotic_desktop.ui.consent import agreement_needed
from polyglotic_desktop.ui.settings import Settings


def ranked_dictionary(path: Path, entries: int) -> Path:
    """A made-up CC-CEDICT of `entries` entries, ranked in order, none on
    an HSK list (so every one is new to an HSK 4 learner)."""
    records = [
        EntryRecord(
            f"cedict:{n:04d}",
            chr(0x4E00 + n),
            chr(0x4E00 + n),
            "yi1",
            (f"meaning {n}",),
            frequency_rank=n,
        )
        for n in range(1, entries + 1)
    ]
    forms = {r.headword: [r.entry_id] for r in records}
    write_dictionary(path, {"dictionary": "cedict"}, records, forms)
    return path


def test_the_made_up_learner_has_met_the_commonest_words(tmp_path: Path) -> None:
    cedict = ranked_dictionary(tmp_path / "cedict.sqlite", 300)
    learning = tmp_path / "learning.sqlite"

    made_up_learner(cedict, 200, learning)

    db = sqlite3.connect(learning)
    try:
        heard = dict(db.execute("SELECT entry_id, heard FROM exposures"))
        by_hand = [s for (s,) in db.execute("SELECT status FROM statuses")]
        saved = db.execute("SELECT count(*) FROM saved_words").fetchone()[0]
    finally:
        db.close()
    assert len(heard) == 200  # the commonest 200 of 300
    assert heard["cedict:0001"] == 4000  # 20 * 200 / 1 ** 1.15
    assert heard["cedict:0200"] == 9  # 20 * 200 / 200 ** 1.15, rounded
    assert "cedict:0201" not in heard
    assert by_hand.count("learning") == 200 // 40
    assert by_hand.count("known") == 200 // 25
    assert saved == 200 // 50


def test_a_dictionary_with_too_few_words_is_refused(tmp_path: Path) -> None:
    """A learner of 30,000 words on the tests' sample would quietly be a
    small one."""
    cedict = ranked_dictionary(tmp_path / "cedict.sqlite", 10)

    with pytest.raises(ValueError, match="10 entries"):
        made_up_learner(cedict, 11, tmp_path / "learning.sqlite")


def test_a_returning_learner_is_asked_nothing(tmp_path: Path) -> None:
    learning = tmp_path / "learning.sqlite"
    made_up_learner(ranked_dictionary(tmp_path / "cedict.sqlite", 50), 50, learning)

    data = returning_learner(tmp_path / "data", learning)

    outbox = open_outbox(data / "outbox.sqlite")
    try:
        assert not agreement_needed(outbox.consent())
    finally:
        outbox.close()
    store = JsonSettingsStore(data / "settings.json")
    try:
        assert Settings(store).value.learning == "zh"  # the first run's isn't asked
    finally:
        store.close()
    assert (data / "learning.sqlite").read_bytes() == learning.read_bytes()


@pytest.mark.windows_only  # the app's own OS adapters
def test_a_start_is_timed_from_main_to_its_window(tmp_path: Path) -> None:
    dictionaries = sample_dictionaries(tmp_path / "dictionaries")
    learning = tmp_path / "learning.sqlite"
    made_up_learner(dictionaries / "cedict.sqlite", 5, learning)

    window_ms = timed_start(
        returning_learner(tmp_path / "data", learning), dictionaries
    )

    assert 0 < window_ms < 60_000
