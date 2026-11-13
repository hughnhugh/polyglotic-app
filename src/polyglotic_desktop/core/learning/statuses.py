"""Word statuses: computed from the level curve unless set explicitly.

Every word the learner meets has a status - new, learning (in the deck),
known or ignored (glossary). Most are never stored: they're estimated from
the learner's level (`levels`). Only explicit statuses are stored per
entry, each with a source: set by the learner (a click, the vocabulary
list), imported (later: Anki, Pleco), or estimated - a pinned lookup of a
word only assumed known turns it back to new. The learner's own choices
never change by themselves (project 019, agreed 2026-11-04).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.core.shared import EntryFacts, WordStatus


class StatusSource(StrEnum):
    """Where a word's status came from."""

    ESTIMATED = "estimated"  # from the level, or from what the learner did
    LEARNER = "learner"  # set by the learner
    IMPORTED = "imported"  # from another tool (after the MVP)


@dataclass(frozen=True)
class StatusRecord:
    """A word's status and where it came from; `at` is when it was set
    (None for one computed now)."""

    status: WordStatus
    source: StatusSource
    at: datetime | None = None

    @property
    def is_learners_own(self) -> bool:
        """Set by the learner or imported - never changed by Learning."""
        return self.source is not StatusSource.ESTIMATED


def estimated_status(facts: EntryFacts, curve: LevelCurve | None) -> WordStatus:
    """The status a word has until one is set: ignored for a name; known
    if the learner's curve says they likely know it; otherwise new. With no
    level picked yet, every word is new."""
    if facts.is_name:
        return WordStatus.IGNORED
    if curve is not None and curve.estimates_known(facts.level):
        return WordStatus.KNOWN
    return WordStatus.NEW


def status_of(
    facts: EntryFacts, explicit: StatusRecord | None, curve: LevelCurve | None
) -> StatusRecord:
    """A word's status: the explicit one if there is one, else estimated."""
    if explicit is not None:
        return explicit
    return StatusRecord(estimated_status(facts, curve), StatusSource.ESTIMATED)
