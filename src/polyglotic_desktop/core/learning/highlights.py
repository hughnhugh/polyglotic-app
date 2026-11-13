"""Which words of a finished caption look different: unfamiliar words,
under the learner's word introductions (`WordIntroductions`).

An unfamiliar word is a word in a finished caption whose status is new
(glossary) - never a live update's, which keeps changing. Names are never
unfamiliar. Highlighting every new word is noise for most learners: a
learner at 2,000 words meets one about every 9 words (project 019,
section 6). So with "common words only" on (the default), a caption shows
- only new words up to about the next band above the learner's level;
- at most about 5% of its words (at least one), and 2 per line;
- each word once, the ones heard most first, then the commonest.
Rarer words stay on hover, and surface in "words you keep hearing" if they
come up again.

The numbers are 019's starting values, to tune with testers.

How many a caption points out is the learner's choice, "Word
introductions" (polyglotic-hq 248, section 3.4 - it was "Common words
only", which nobody understood: the user's F19): none, a few per caption
(the cap above, the default) or every new word.
"""

from collections.abc import Callable, Sequence
from enum import StrEnum

from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.core.shared import EntryFacts, EntryId, WordInLine, WordStatus

CAP_SHARE = 0.05  # of a caption's words
CAP_PER_LINE = 2


class WordIntroductions(StrEnum):
    """How many new words a finished caption points out (glossary: word
    introductions): `OFF`, none - captions only; `A_FEW` per caption,
    under the cap (the default); or `EVERY` new word. Saved words and
    words in the deck show whichever it is: they're the learner's own."""

    OFF = "off"
    A_FEW = "a_few"
    EVERY = "every"

    @classmethod
    def of(cls, off: bool, common_only: bool) -> "WordIntroductions":
        """The choice two settings keep: `off` (newer), and "common words
        only" (`common_only`, kept as it was, so an older version that
        doesn't know `off` still has the cap the learner chose)."""
        if off:
            return cls.OFF
        return cls.A_FEW if common_only else cls.EVERY

    @property
    def off(self) -> bool:
        return self is WordIntroductions.OFF

    @property
    def common_only(self) -> bool:
        """What "common words only" keeps for it: off keeps the cap, so
        turning introductions on again brings back a few."""
        return self is not WordIntroductions.EVERY


def caption_cap(word_count: int) -> int:
    """How many unfamiliar words a caption of `word_count` dictionary words
    may show with "common words only": about 5%, rounded, at least 1."""
    return max(1, int(CAP_SHARE * word_count + 0.5))


def unfamiliar_words(
    lines: Sequence[Sequence[WordInLine]],
    status: Callable[[EntryFacts], WordStatus],
    curve: LevelCurve | None,
    heard: Callable[[EntryId], int],
    common_only: bool,
) -> list[list[WordInLine]]:
    """For each of a finished caption's lines (its words), the unfamiliar
    words to show. `status` gives a word's status, `heard` how many
    captions it's been heard in."""
    candidates = [
        [w for w in line if not w.entry.is_name and status(w.entry) is WordStatus.NEW]
        for line in lines
    ]
    if not common_only:
        return candidates
    within = curve or LevelCurve("", 0.5)
    ranked = sorted(
        (
            (-heard(w.entry.entry_id), w.entry.frequency_rank or 10**9, n, w.start, w)
            for n, line in enumerate(candidates)
            for w in line
            if within.within_reach(w.entry.level)
        ),
        key=lambda item: item[:4],
    )
    allowed = caption_cap(sum(len(line) for line in lines))
    shown: list[list[WordInLine]] = [[] for _ in lines]
    chosen: set[EntryId] = set()
    for *_, n, _start, word in ranked:
        if len(chosen) >= allowed:
            break
        if word.entry.entry_id in chosen or len(shown[n]) >= CAP_PER_LINE:
            continue
        chosen.add(word.entry.entry_id)
        shown[n].append(word)
    return [sorted(line, key=lambda w: w.start) for line in shown]
