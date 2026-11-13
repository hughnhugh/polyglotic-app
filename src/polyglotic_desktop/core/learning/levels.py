"""The learner's level as a curve, and the word statuses estimated from it.

Project 019's recommendation, agreed for the MVP (polyglotic-hq MVP.md,
"Known words", 2026-11-04): a level is not a cut-off but a curve - the
chance the learner knows a word falls as the word's level rises. It's
stored as a scheme and one number, the point on the scheme's scale where
the learner knows about half the words. A word's default status is
computed from it, never stored, so changing the level changes every
default at once.

The scale is the scheme's own levels: HSK 1-6 and 7-9 (as 7), or the
English frequency bands (top 1,000 = 1 ... top 20,000 = 7). A word with no
level in the scheme (not on the HSK lists; rarer than the top 20,000) sits
past the top.

Picking a level in the level picker sets the midpoint half a level above
it, so words at or below the picked level count as known (MVP.md) and the
next level up as new. A vocabulary test (after the MVP) can set any
midpoint; nothing else changes.
"""

import math
from dataclasses import dataclass

from polyglotic_desktop.core.shared import Level

SLOPE = 2.0
"""How fast the chance of knowing a word falls per level above the
midpoint. A guess to tune (019 left the population slope to the test):
at 2, a word one level below the midpoint is known with a chance of 0.88,
half a level below 0.73, half a level above 0.27."""

KNOWN_AT = 0.6
"""The chance from which a word counts as known (estimated) - 019's
starting value. Between 0.6 and 0.85 a word is never highlighted, but
could be offered for a spot-check later."""

STARTING_LEVEL = 3
"""The level words are estimated at until the learner sets theirs - the
first run doesn't ask (polyglotic-hq 293): the middle of the level
picker's eight choices, HSK 3 (about 1,000 words on the 2025 syllabus) or
the 3,000 most common English words. A guess to tune, like `SLOPE`."""

NEXT_BAND = 1.0
"""With "common words only", new words are highlighted only up to this
many levels above the midpoint - about the next band above the learner's
level (019's "i+1")."""


@dataclass(frozen=True)
class LevelCurve:
    """A learner's level in `scheme`: they know about half the words at
    `midpoint` on its scale."""

    scheme: str
    midpoint: float

    @classmethod
    def picked(cls, level: Level) -> "LevelCurve":
        """The curve for a level chosen in the level picker: words at or
        below `level.value` known, the level above new. Level 0 is "just
        starting": nothing known yet."""
        return cls(level.scheme, level.value + 0.5)

    @classmethod
    def starting(cls, scheme: str) -> "LevelCurve":
        """The curve words are estimated on in `scheme` until the learner
        sets their level: `STARTING_LEVEL`, as if picked."""
        return cls.picked(Level(scheme, STARTING_LEVEL))

    @property
    def picked_level(self) -> int:
        """The level picker's level for this curve - the highest level
        whose words count as known."""
        return max(0, math.floor(self.midpoint))

    def chance_known(self, level: float | None) -> float:
        """The chance the learner knows a word at `level` (None: past every
        level of the scheme - treated as no chance)."""
        if level is None:
            return 0.0
        return 1.0 / (1.0 + math.exp(SLOPE * (level - self.midpoint)))

    def estimates_known(self, level: float | None) -> bool:
        return self.chance_known(level) >= KNOWN_AT

    def within_reach(self, level: float | None) -> bool:
        """Whether a new word at `level` is common enough to highlight with
        "common words only": up to about the next band above the level."""
        return level is not None and level <= self.midpoint + NEXT_BAND
