"""The languages a learner learns, and what each can do (polyglotic-hq 248,
section 3; DECISIONS.md #65).

A language being learned is one the app keeps learning data for. Every
caption language can be learned, in one of three tiers - what its
dictionary can do:
- **full** (Chinese, English): lookups, a level, word introductions, the
  words heard and saved, an Anki deck;
- **basic** (#65's ten for the public launch): lookups only, marked
  basic, from open data - a pack downloaded when it's ready;
- **none yet** (the rest): captions and translation work; no lookups.

The list (`LearningLanguages`) has the language whose learning data runs
now (`main`: one full dictionary at a time until Words keeps a section
per language - polyglotic-hq 265), the others added in order (`also`),
and the languages a lookup asked about once and was told "Not now"
(`not_now`). Codes are the learned language's (`learned_code`): `zh` for
Simplified and Traditional alike; Cantonese (`yue`) is its own.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

FULL = ("zh", "en")
"""Languages with a full dictionary, in the order offered."""
BASIC = ("ja", "es", "ko", "fr", "de", "pt", "it", "ru", "vi", "nl")
"""Languages with a basic dictionary at the public launch (#65): Japanese
and Spanish first, in the beta."""


class Tier(StrEnum):
    """What a language's dictionary can do."""

    FULL = "full"
    BASIC = "basic"
    NONE = "none"


def learned_code(caption_language: str) -> str:
    """The language learned for a caption in `caption_language` (protocol.md's
    code): the same language whatever its script or region - `zh-hant` is
    Chinese - as `exposures.in_learned_language` counts it."""
    return caption_language.lower().split("-")[0]


def tier_of(code: str) -> Tier:
    if code in FULL:
        return Tier.FULL
    return Tier.BASIC if code in BASIC else Tier.NONE


def starting_language(
    main: str | None, own: str | None, kept: Callable[[str], bool]
) -> str:
    """The full dictionary whose learning data runs from this start: the
    main language being learned, once one is chosen. Until then - the first
    run asks no language (polyglotic-hq 293) - a guess from the learner's
    own language (`own`, Windows' first display language's learned code):
    English, unless that's their own, then Chinese. Learning data already
    kept on this PC for the other one, and none for the guess, keeps the
    one it's kept for (`kept`): an install from before, where Chinese ran
    until a language was chosen, keeps its words in view."""
    if main in FULL:
        return main
    guess = "zh" if own == "en" else "en"
    other = "en" if guess == "zh" else "zh"
    if not kept(guess) and kept(other):
        return other
    return guess


@dataclass(frozen=True)
class LearningLanguages:
    """The languages being learned: `main`, whose learning data runs now
    (None: none chosen yet), then `also`, in the order added; and those
    `not_now` - a lookup asked once, and won't again."""

    main: str | None = None
    also: tuple[str, ...] = ()
    not_now: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        main: str | None,
        also: tuple[str, ...] = (),
        not_now: tuple[str, ...] = (),
    ) -> "LearningLanguages":
        """The list as stored, made consistent: each language once, `main`
        not among the others, nothing both learned and "not now"."""
        others = tuple(dict.fromkeys(c for c in also if c != main))
        learned = {main, *others}
        declined = tuple(dict.fromkeys(c for c in not_now if c not in learned))
        return cls(main, others, declined)

    @property
    def all(self) -> tuple[str, ...]:
        """Every language being learned, `main` first."""
        return ((self.main,) if self.main else ()) + self.also

    def learns(self, code: str) -> bool:
        return code in self.all

    def added(self, code: str) -> "LearningLanguages":
        """`code` learned too: the main language if there's none yet and it
        has a full dictionary, else after the others."""
        if self.learns(code):
            return self
        if self.main is None and tier_of(code) is Tier.FULL:
            return LearningLanguages.of(code, self.also, self.not_now)
        return LearningLanguages.of(self.main, (*self.also, code), self.not_now)

    def stopped(self, code: str) -> "LearningLanguages":
        """`code` no longer learned. The main language can't be stopped while
        it's the one whose learning data runs (`can_stop`); its words are
        kept either way - deleting them is Account's."""
        if not self.can_stop(code):
            return self
        return replace(self, also=tuple(c for c in self.also if c != code))

    def can_stop(self, code: str) -> bool:
        return code in self.also

    def switched_to(self, code: str) -> "LearningLanguages":
        """`code`'s learning data runs from the next start (a full dictionary
        only, one at a time); the main language stays learned, first among
        the others, its words kept."""
        if tier_of(code) is not Tier.FULL or code == self.main:
            return self
        others = ((self.main,) if self.main else ()) + self.also
        return LearningLanguages.of(code, others, self.not_now)

    def declined(self, code: str) -> "LearningLanguages":
        """A lookup's "Not now" for `code`: not asked again."""
        return LearningLanguages.of(self.main, self.also, (*self.not_now, code))

    def asks_about(self, caption_language: str | None) -> str | None:
        """The language a pinned lookup of a word in `caption_language`
        offers to learn too (#65: "Learn Japanese too?"), asked once: one
        not learned, not answered "Not now", and with a dictionary - None
        for the rest (and an unknown language)."""
        if not caption_language:
            return None
        code = learned_code(caption_language)
        if self.learns(code) or code in self.not_now or tier_of(code) is Tier.NONE:
            return None
        return code
