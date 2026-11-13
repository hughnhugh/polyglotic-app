"""The learning store on disk (adapters.sqlite_learning): everything the
port keeps survives closing and reopening; a file from a newer app is
refused; deleting a category takes its saved words with it."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from tests.learning.fakes import Clock, words_of
from tests.learning.test_vocabulary import ENTRIES, eid, lookup

from polyglotic_desktop.adapters.sqlite_learning import (
    VERSION,
    LearningStoreDamagedError,
    LearningStoreFormatError,
    SqliteLearningStore,
)
from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.core.learning.lookups import LookupContext
from polyglotic_desktop.core.learning.statuses import StatusRecord, StatusSource
from polyglotic_desktop.core.learning.vocabulary import Vocabulary
from polyglotic_desktop.core.shared import Level, WordStatus
from polyglotic_desktop.ports.learning import (
    LearningDataProblem,
    StoredAnkiExport,
    StoredCategory,
    StoredCoverage,
    StoredDeckWord,
    StoredExposures,
    StoredLevel,
    StoredListening,
    StoredSavedWord,
    StoredStatus,
)

AT = datetime(2026, 11, 4, 9, 30, 15, 250000, tzinfo=UTC)


def test_a_new_store_is_empty(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "sub" / "learning.sqlite")
    snapshot = store.load()
    assert snapshot.level is None
    assert not (snapshot.statuses or snapshot.categories or snapshot.saved_words)
    assert not snapshot.exposures
    store.close()


def test_everything_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    store.save_level(StoredLevel("hsk-2025", 3.5))
    store.save_level(StoredLevel("hsk-2021", 2.5))  # replaces
    store.save_status(StoredStatus("cedict:a", "known", "learner", AT))
    store.save_category(StoredCategory("saved", "Saved", "#6fc3ff", 0))
    store.save_category(StoredCategory("saved", "Mine", "#123456", 0))  # renames
    word = StoredSavedWord(
        "cedict:a", "电脑", "電腦", "diàn nǎo", "computer", "saved",
        "我的电脑, 又卡了", 'My computer "froze" again', AT,
    )  # fmt: skip
    store.save_word(word)
    store.save_exposures(
        [StoredExposures("cedict:a", 3, 1, 2)], {date(2026, 11, 4): {"cedict:a": 3}}
    )
    store.save_exposures([], {date(2026, 11, 4): {"cedict:a": -1, "cedict:b": 1}})
    store.close()

    again = SqliteLearningStore(path)
    snapshot = again.load()
    assert snapshot.level == StoredLevel("hsk-2021", 2.5)
    assert snapshot.statuses == [StoredStatus("cedict:a", "known", "learner", AT)]
    assert snapshot.categories == [StoredCategory("saved", "Mine", "#123456", 0)]
    assert snapshot.saved_words == [word]  # renaming kept the word
    assert snapshot.exposures == [StoredExposures("cedict:a", 3, 1, 2)]
    assert again.daily_exposures(date(2026, 11, 4)) == {"cedict:a": 2, "cedict:b": 1}
    assert again.daily_exposures(date(2026, 11, 5)) == {}
    again.close()


def test_deleting_a_category_deletes_its_words(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "learning.sqlite")
    store.save_category(StoredCategory("a", "A", "#111111", 0))
    store.save_category(StoredCategory("b", "B", "#222222", 1))
    for entry_id, category in (("x", "a"), ("y", "b")):
        store.save_word(
            StoredSavedWord(entry_id, entry_id, "", "", "", category, "", "", AT)
        )
    store.delete_word("nothing-there")
    store.delete_category("a")
    snapshot = store.load()
    assert [c.id for c in snapshot.categories] == ["b"]
    assert [w.entry_id for w in snapshot.saved_words] == ["y"]
    store.close()


def test_a_file_from_a_newer_app_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "learning.sqlite"
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {VERSION + 1}")
    db.close()
    with pytest.raises(LearningStoreFormatError, match="version"):
        SqliteLearningStore(path)


def test_a_file_that_isnt_a_database_is_damaged(tmp_path: Path) -> None:
    """Not refused as a newer app's: `open_learning_store` sets it aside
    (tests/test_learning_set_aside.py)."""
    path = tmp_path / "learning.sqlite"
    path.write_bytes(b"not a database at all, just some bytes" * 20)
    with pytest.raises(LearningStoreDamagedError) as raised:
        SqliteLearningStore(path)
    assert raised.value.problem is LearningDataProblem.DAMAGED


def test_the_vocabulary_on_disk(tmp_path: Path) -> None:
    """Learning's rules over the real store, closed and reopened."""
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    vocab = Vocabulary(store, lookup, "hsk-2025", Clock())
    vocab.set_level(Level("hsk-2025", 1))
    vocab.set_status(eid("超市"), WordStatus.LEARNING)
    vocab.looked_up(ENTRIES["我"], pinned=True)
    vocab.save(
        eid("榴莲"), "榴莲", "榴槤", "liú lián", "durian", "tricky",
        LookupContext("榴莲很臭", "Durian stinks"),
    )  # fmt: skip
    vocab.caption_finished("c1", words_of("超市 酸奶 榴莲", ENTRIES), by_you=False)
    vocab.caption_finished("c2", words_of("超市", ENTRIES), by_you=True)
    store.close()

    reopened = Vocabulary(SqliteLearningStore(path), lookup, "hsk-2025")
    assert reopened.curve == LevelCurve("hsk-2025", 1.5)
    assert reopened.status(ENTRIES["超市"]).status is WordStatus.LEARNING
    assert reopened.status(ENTRIES["我"]) == StatusRecord(
        WordStatus.NEW, StatusSource.ESTIMATED, Clock().now
    )
    word = reopened.saved_word(eid("榴莲"))
    assert word is not None and word.source_translation == "Durian stinks"
    assert reopened.exposures(eid("超市")).heard_in_deck == 1
    assert reopened.exposures(eid("超市")).heard_by_you == 1
    assert [c.name for c in reopened.categories] == ["Saved", "Tricky"]


def test_forgetting_an_entry_keeps_its_daily_counts(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "learning.sqlite")
    store.save_category(StoredCategory("a", "A", "#111111", 0))
    store.save_status(StoredStatus("old", "known", "learner", AT))
    store.save_word(StoredSavedWord("old", "w", "", "", "", "a", "", "", AT))
    store.save_exposures(
        [StoredExposures("old", 2, 0, 0)], {date(2026, 11, 4): {"old": 2}}
    )
    store.save_status(StoredStatus("kept", "new", "estimated", AT))
    store.forget_entry("old")
    snapshot = store.load()
    assert [s.entry_id for s in snapshot.statuses] == ["kept"]
    assert not snapshot.saved_words and not snapshot.exposures
    assert store.daily_exposures(date(2026, 11, 4)) == {"old": 2}
    store.close()


def test_daily_counts_handed_over_and_deleting_everything(tmp_path: Path) -> None:
    store = SqliteLearningStore(tmp_path / "learning.sqlite")
    store.save_level(StoredLevel("hsk-2025", 2.5))
    store.save_category(StoredCategory("saved", "Saved", "#ffcc00", 0))
    store.save_status(StoredStatus("cedict:a", "known", "learner", AT))
    store.save_exposures(
        [StoredExposures("cedict:a", 3, 0, 0)],
        {date(2026, 11, 3): {"cedict:a": 2}, date(2026, 11, 4): {"cedict:a": 1}},
    )
    assert store.exposure_days() == [date(2026, 11, 3), date(2026, 11, 4)]
    store.forget_daily_exposures([date(2026, 11, 3)])
    assert store.exposure_days() == [date(2026, 11, 4)]
    store.delete_learning_data()
    data = store.load()
    assert not data.statuses and not data.exposures and not data.saved_words
    assert store.exposure_days() == []
    assert data.level is not None and len(data.categories) == 1


def test_deleting_everything_leaves_none_of_it_readable_in_the_file(
    tmp_path: Path,
) -> None:
    """Polyglotic-hq 207: SQLite only marks a deleted row's space free, so
    "Delete learning data... also from this PC" left every sentence in the
    file and its write-ahead log, readable with any text editor."""
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    store.save_category(StoredCategory("saved", "Saved", "#ffcc00", 0))
    for n in range(50):
        store.save_word(
            StoredSavedWord(
                f"cedict:{n}", "电脑", "電腦", "diàn nǎo", "computer", "saved",
                f"我的电脑又卡了 {n}", f"My computer froze again {n}", AT,
            )
        )  # fmt: skip
    store.delete_word("cedict:1")  # deleted before: already free space
    store.delete_learning_data()
    on_disk = {each.name: each.read_bytes() for each in tmp_path.iterdir()}
    store.close()

    assert {*on_disk} <= {path.name, f"{path.name}-wal", f"{path.name}-shm"}
    for held in on_disk.values():
        assert "我的电脑又卡了".encode() not in held
        assert b"My computer froze again" not in held
    assert b"froze" not in path.read_bytes()
    again = SqliteLearningStore(path)
    kept = again.load()  # the categories stay
    again.close()
    assert [c.id for c in kept.categories] == ["saved"] and not kept.saved_words


def _saved(n: int, category: str, sentence: str) -> StoredSavedWord:
    return StoredSavedWord(
        f"cedict:{n}", "电脑", "電腦", "diàn nǎo", "computer", category,
        sentence, f"In English {sentence}", AT,
    )  # fmt: skip


def _delete_a_word(store: SqliteLearningStore) -> None:
    store.delete_word("cedict:0")


def _delete_a_category(store: SqliteLearningStore) -> None:
    store.delete_category("trip")


def _replace_a_sentence(store: SqliteLearningStore) -> None:
    store.save_word(_saved(0, "trip", "换了一句"))


def _rename_a_category(store: SqliteLearningStore) -> None:
    store.save_category(StoredCategory("trip", "Holiday", "#00ccff", 1))


def _delete_a_deck_word(store: SqliteLearningStore) -> None:
    store.delete_deck_word("cedict:0")


def _replace_a_deck_line(store: SqliteLearningStore) -> None:
    store.save_deck_word(
        StoredDeckWord("cedict:0", "电脑", "電腦", "", "", "另一句", "Another", AT)
    )


def _forget_the_entry(store: SqliteLearningStore) -> None:
    store.forget_entry("cedict:0")


_SENTENCE = [b"GONE1", "长长长长".encode()]
_DECK_LINE = [b"GONE2", b"GONE3"]


@pytest.mark.parametrize(
    ("remove", "gone"),
    [
        (_delete_a_word, _SENTENCE),
        (_delete_a_category, [*_SENTENCE, b"Trip words"]),
        (_replace_a_sentence, _SENTENCE),
        (_rename_a_category, [b"Trip words"]),
        (_delete_a_deck_word, _DECK_LINE),
        (_replace_a_deck_line, _DECK_LINE),
        (_forget_the_entry, [*_SENTENCE, *_DECK_LINE]),
    ],
)
def test_one_delete_leaves_none_of_its_text_readable_while_the_app_runs(
    tmp_path: Path,
    remove: Callable[[SqliteLearningStore], None],
    gone: list[bytes],
) -> None:
    """Polyglotic-hq 213 (207's probe): one delete, or a replace, left the
    old text in the file's free space and the write-ahead log - readable
    with any text editor until written over, and in the file after the app
    closed. Saved in an earlier run, so it's in the file, not only the log;
    a long sentence fills pages of its own (overflow pages)."""
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    store.save_category(StoredCategory("saved", "Saved", "#ffcc00", 0))
    store.save_category(StoredCategory("trip", "Trip words", "#00ccff", 1))
    store.save_word(_saved(0, "trip", "我的电脑又卡了 GONE1 " + "长" * 600))
    store.save_deck_word(
        StoredDeckWord("cedict:0", "电脑", "電腦", "", "", "GONE2 卡了", "GONE3", AT)
    )
    for n in range(1, 40):
        store.save_word(_saved(n, "saved", f"别的句子 KEPT{n}"))
    store.close()

    store = SqliteLearningStore(path)
    remove(store)
    on_disk = {each.name: each.read_bytes() for each in tmp_path.iterdir()}
    store.close()
    after_close = path.read_bytes()

    for name, held in on_disk.items():
        assert not [g for g in gone if g in held], name
    assert not [g for g in gone if g in after_close]
    assert b"KEPT39" in after_close  # the rest stays


def test_a_captions_counts_and_a_new_word_leave_the_log_to_sqlite(
    tmp_path: Path,
) -> None:
    """Only a write that removes the learner's text empties the write-ahead
    log (213): a caption's exposure counts, or a word saved for the first
    time, don't wait on a checkpoint."""
    store = SqliteLearningStore(tmp_path / "learning.sqlite")
    wal = tmp_path / "learning.sqlite-wal"
    for write in (
        lambda: store.save_category(StoredCategory("saved", "Saved", "#ffcc00", 0)),
        lambda: store.save_category(StoredCategory("saved", "Saved", "#ffcc00", 2)),
        lambda: store.save_exposures(
            [StoredExposures("cedict:a", 1, 0, 0)],
            {date(2026, 11, 8): {"cedict:a": 1}},
        ),
        lambda: store.save_word(_saved(1, "saved", "第一次")),
        lambda: store.delete_word("not-saved"),
        lambda: store.forget_entry("not-there"),
    ):
        write()
        assert wal.stat().st_size > 0  # emptied by a checkpoint: 0
    store.close()


def test_deck_words_and_export_marks_survive_reopening_and_go_with_the_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    deck_word = StoredDeckWord(
        "cedict:a", "榴莲", "榴槤", "liú lián", "durian", "榴莲好吃", "yum", AT
    )
    store.save_deck_word(deck_word)
    store.save_anki_exports([StoredAnkiExport("cedict:a", AT)])
    store.close()
    again = SqliteLearningStore(path)
    data = again.load()
    assert data.deck_words == [deck_word]
    assert data.anki_exports == [StoredAnkiExport("cedict:a", AT)]
    again.forget_entry("cedict:a")
    data = again.load()
    assert not data.deck_words and not data.anki_exports
    again.save_deck_word(deck_word)
    again.save_anki_exports([StoredAnkiExport("cedict:a", AT)])
    again.delete_deck_word("cedict:a")
    assert not again.load().deck_words
    again.delete_learning_data()
    assert not again.load().anki_exports


def test_a_version_1_file_gains_the_deck_tables(tmp_path: Path) -> None:
    path = tmp_path / "learning.sqlite"
    SqliteLearningStore(path).close()
    db = sqlite3.connect(path)
    db.execute("DROP TABLE deck_words")
    db.execute("DROP TABLE anki_exports")
    db.execute("DROP TABLE daily_coverage")
    db.execute("DROP TABLE daily_listening")
    db.execute("DROP TABLE handed_over_days")
    db.execute("ALTER TABLE exposures DROP COLUMN first_heard")
    db.execute("PRAGMA user_version = 1")
    db.close()
    store = SqliteLearningStore(path)
    assert store.load().deck_words == []


def test_a_days_coverage_adds_up_survives_reopening_and_goes_with_the_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    day, nxt = date(2026, 11, 4), date(2026, 11, 5)
    store.add_coverage([StoredCoverage(day, 10, 2, 3)])
    store.add_coverage([StoredCoverage(day, -4, 0, -1), StoredCoverage(nxt, 1, 0, 0)])
    store.close()
    again = SqliteLearningStore(path)
    assert again.load().coverage == [
        StoredCoverage(day, 6, 2, 2),
        StoredCoverage(nxt, 1, 0, 0),
    ]
    again.delete_learning_data()
    assert again.load().coverage == []


def test_a_version_2_file_gains_the_coverage_table_and_keeps_its_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    store.save_status(StoredStatus("cedict:a", "known", "learner", AT))
    store.close()
    db = sqlite3.connect(path)
    db.execute("DROP TABLE daily_coverage")
    db.execute("DROP TABLE daily_listening")
    db.execute("DROP TABLE handed_over_days")
    db.execute("ALTER TABLE exposures DROP COLUMN first_heard")
    db.execute("PRAGMA user_version = 2")
    db.close()
    store = SqliteLearningStore(path)
    data = store.load()
    assert data.coverage == [] and len(data.statuses) == 1
    store.add_coverage([StoredCoverage(date(2026, 11, 4), 1, 0, 0)])
    assert len(store.load().coverage) == 1


def test_a_days_listening_adds_up_by_category_and_goes_with_the_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    day = date(2026, 11, 4)
    store.add_listening([StoredListening(day, "video", 4.5)])
    store.add_listening(
        [StoredListening(day, "video", 2.0), StoredListening(day, "game", 1.0)]
    )
    store.close()
    again = SqliteLearningStore(path)
    assert again.load().listening == [
        StoredListening(day, "game", 1.0),
        StoredListening(day, "video", 6.5),
    ]
    again.delete_learning_data()
    assert again.load().listening == []


def test_a_version_3_file_gains_the_listening_table(tmp_path: Path) -> None:
    path = tmp_path / "learning.sqlite"
    SqliteLearningStore(path).close()
    db = sqlite3.connect(path)
    db.execute("DROP TABLE daily_listening")
    db.execute("DROP TABLE handed_over_days")
    db.execute("ALTER TABLE exposures DROP COLUMN first_heard")
    db.execute("PRAGMA user_version = 3")
    db.close()
    store = SqliteLearningStore(path)
    assert store.load().listening == []
    store.add_listening([StoredListening(date(2026, 11, 4), "call", 3.0)])
    assert len(store.load().listening) == 1


def test_first_heard_and_days_handed_over_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(path)
    day = date(2026, 11, 4)
    store.save_exposures(
        [StoredExposures("a", 1, 0, 0, day), StoredExposures("b", 2, 0, 0)],
        {day: {"a": 1}, date(2026, 11, 5): {"b": 2}},
    )
    store.mark_handed_over([day])
    store.close()
    again = SqliteLearningStore(path)
    found = {e.entry_id: e.first_heard for e in again.load().exposures}
    assert found == {"a": day, "b": None}
    assert again.days_to_hand_over() == [date(2026, 11, 5)]
    assert again.exposure_days() == [day, date(2026, 11, 5)]  # kept
    again.forget_daily_exposures([day])
    again.save_exposures([], {day: {"a": 1}})  # a late change to a forgotten day
    assert again.days_to_hand_over() == [day, date(2026, 11, 5)]
    again.delete_learning_data()
    assert again.days_to_hand_over() == [] and again.exposure_days() == []


def test_a_version_4_file_gains_first_heard_and_keeps_its_counts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning.sqlite"
    SqliteLearningStore(path).close()
    db = sqlite3.connect(path)
    db.execute("DROP TABLE handed_over_days")
    db.execute("ALTER TABLE exposures DROP COLUMN first_heard")
    db.execute("INSERT INTO exposures VALUES ('a', 3, 0, 1)")
    db.execute("PRAGMA user_version = 4")
    db.commit()
    db.close()
    store = SqliteLearningStore(path)
    assert store.load().exposures == [StoredExposures("a", 3, 0, 1, None)]
