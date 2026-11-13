"""The Learning page, as plain Python (polyglotic-hq 262; 248's IA.md,
section 3.6): a card per language being learned, and what each says and
offers - facts, not words; the page words them.

One full dictionary's learning data runs at a time today (`running`: the
tools `main` built at the start). Choosing another one (`switched_to`)
applies from the next start, as "You're learning" did on Home - the
cards say so on both sides until then. Words keeps a section per language
once several run at once (polyglotic-hq 265); then `running` becomes a
set and these cards lose their "switch".
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass

from polyglotic_desktop.core.learning.languages import (
    LearningLanguages,
    Tier,
    tier_of,
)
from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.ui_next.views.words import LevelLine, level_line


@dataclass(frozen=True)
class LanguageCard:
    """One language's card on Learning."""

    code: str
    tier: Tier
    main: bool = False
    """The language whose learning data runs - now, or from the next start."""
    running: bool = False
    """Its learning data runs now: lookups, the level, word introductions."""
    level: LevelLine | None = None
    """A full dictionary's level, if it's known (None: a basic one, or none
    without a dictionary)."""
    pack_here: bool = False
    """A basic dictionary's pack is on this PC: its lookups work."""

    @property
    def starts_next(self) -> bool:
        """Chosen to run from the next start (another runs until then)."""
        return self.main and not self.running

    @property
    def stops_next(self) -> bool:
        """Running now, and another runs from the next start."""
        return self.running and not self.main

    @property
    def can_change_level(self) -> bool:
        """Its level is the running learning data's: changed at once."""
        return self.running and self.tier is Tier.FULL

    @property
    def can_switch(self) -> bool:
        """A full dictionary that isn't the main one: it can run instead."""
        return self.tier is Tier.FULL and not self.main


def cards(
    languages: LearningLanguages,
    running: str | None,
    level_of: Callable[[str], LevelCurve | None],
    packs: Collection[str] = (),
) -> tuple[LanguageCard, ...]:
    """The cards, the main language first: `running`, the language whose
    learning data runs now (None: none); `level_of`, a full dictionary's
    level (the running one's, live; another's as it was kept); `packs`,
    the basic dictionaries on this PC."""
    found = []
    for code in languages.all:
        tier = tier_of(code)
        main = code == languages.main
        level = level_line(level_of(code)) if tier is Tier.FULL else None
        found.append(
            LanguageCard(
                code,
                tier,
                main=main,
                running=code == running,
                level=level,
                pack_here=tier is Tier.BASIC and code in packs,
            )
        )
    return tuple(found)


def offered(languages: LearningLanguages, codes: Collection[str]) -> list[str]:
    """The languages "Learn another language" offers, from `codes` (every
    caption language, learned codes, in the order to show them): those not
    learned yet, each once. Full and basic dictionaries aren't put first -
    each says its tier (polyglotic-hq 293: Chinese and English on top made
    the app look as if it were only for them)."""
    return [c for c in dict.fromkeys(codes) if not languages.learns(c)]
