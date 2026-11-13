"""The coverage probe: the share of a caption language's words a pack
finds (polyglotic-hq project 157's rule for the basic tier).

    uv run python -m tools.dictionaries.coverage [es ja ru]

Reads `probe/<code>.txt` (100 FLEURS sentences per language), splits each
with the pack's word split, and looks each content word up the way a
caption's word is looked up (`BasicDictionary`). Words without a letter
(numbers) aren't counted. `packs` runs it after each build, records the
share in the file's `info` and fails below the tier's floor; CI runs it
again (`.github/workflows/dictionary-packs.yml`).

A second measure, `running_words`, counts every word as often as it is
used: the share of wordfreq's list for the language, each word weighed by
its frequency, that a lookup finds (polyglotic-hq 298: Russian's target is
95 % of running words). Function words count, as they do in speech;
words in another script (English in Russian text) don't.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from polyglotic_desktop.adapters.japanese_split import JapaneseSplit
from polyglotic_desktop.adapters.spaced_split import SpacedSplit
from polyglotic_desktop.adapters.sqlite_dictionary import SqliteDictionary
from polyglotic_desktop.core.lexicon.basic import BasicDictionary
from polyglotic_desktop.ports.word_split import WordSplit

PROBE = Path(__file__).parent / "probe"
REPO = Path(__file__).resolve().parents[2]
FLOORS = {"basic": 0.90}
"""The least share of content words a tier's dictionary must find (157)."""
SCRIPTS = {"es": "LATIN", "ru": "CYRILLIC"}
"""The script a language's running words are written in: words in
another are left out of `running_words`."""


@dataclass(frozen=True)
class Coverage:
    found: int
    counted: int
    misses: Counter[str]

    @property
    def share(self) -> float:
        return self.found / self.counted if self.counted else 0.0

    def __str__(self) -> str:
        commonest = ", ".join(f"{w} ({n})" for w, n in self.misses.most_common(12))
        return (
            f"{100 * self.share:.1f} % of {self.counted} content words found; "
            f"commonest misses: {commonest}"
        )


def split_for(language: str) -> WordSplit:
    """The word split a language's pack uses."""
    return JapaneseSplit() if language == "ja" else SpacedSplit(language)


def sentences(language: str) -> list[str]:
    text = (PROBE / f"{language}.txt").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def measure(
    dictionary: BasicDictionary, split: WordSplit, lines: Iterable[str]
) -> Coverage:
    found = counted = 0
    misses: Counter[str] = Counter()
    for line in lines:
        for word in split.words(line):
            text = line[word.start : word.end]
            if not word.content or not any(ch.isalpha() for ch in text):
                continue
            counted += 1
            if dictionary.lookup_split(text, word):
                found += 1
            else:
                misses[text] += 1
    return Coverage(found, counted, misses)


def probe(pack_file: Path, language: str) -> Coverage:
    split = split_for(language)
    file = SqliteDictionary(pack_file)
    try:
        return measure(
            BasicDictionary(file, split, language), split, sentences(language)
        )
    finally:
        file.close()


@dataclass(frozen=True)
class RunningWords:
    """The share of running words found: `found` and `counted` are sums of
    frequencies (wordfreq's share of all words), `words` how many word
    forms were counted."""

    found: float
    counted: float
    words: int
    misses: dict[str, float]

    @property
    def share(self) -> float:
        return self.found / self.counted if self.counted else 0.0

    def __str__(self) -> str:
        commonest = ", ".join(
            f"{w} ({100 * f / self.counted:.2f} %)"
            for w, f in sorted(self.misses.items(), key=lambda m: -m[1])[:12]
        )
        return (
            f"{100 * self.share:.1f} % of running words found ({self.words} word "
            f"forms, weighed by frequency); commonest misses: {commonest}"
        )


def in_script(word: str, script: str | None) -> bool:
    """`word` has a letter, and every letter is in `script` (any, if None)."""
    letters = [ch for ch in word if ch.isalpha()]
    return bool(letters) and (
        script is None or all(script in unicodedata.name(ch, "") for ch in letters)
    )


def running_words(
    dictionary: BasicDictionary, frequencies: Mapping[str, float], language: str
) -> RunningWords:
    """How much of `frequencies` (word -> its share of all words, wordfreq's
    lower-case list) `dictionary` finds, each word as a caption might write
    it: as listed, capitalised (a name: "сша" is США), or in capitals."""
    script = SCRIPTS.get(language)
    found = counted = 0.0
    words = 0
    misses: dict[str, float] = {}
    for word, share in frequencies.items():
        if not in_script(word, script):
            continue
        words += 1
        counted += share
        spellings = dict.fromkeys((word, word.capitalize(), word.upper()))
        if any(dictionary.lookup(w) for w in spellings):
            found += share
        else:
            misses[word] = share
    return RunningWords(found, counted, words, misses)


def probe_running_words(pack_file: Path, language: str, wordfreq: Path) -> RunningWords:
    """`running_words` over wordfreq's list for `language`."""
    from tools.dictionaries import wordfreq_ranks

    file = SqliteDictionary(pack_file)
    try:
        return running_words(
            BasicDictionary(file, split_for(language), language),
            wordfreq_ranks.frequencies(wordfreq, language),
            language,
        )
    finally:
        file.close()


def main(argv: Sequence[str] | None = None) -> int:
    from tools.dictionaries.packs import PACKS

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("languages", nargs="*", default=list(PACKS))
    parser.add_argument(
        "--packs", type=Path, default=REPO / "build" / "dictionaries" / "packs"
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    failed = 0
    for language in args.languages:
        pack = PACKS[language]
        result = probe(args.packs / f"{pack.name}.sqlite", language)
        floor = FLOORS["basic"]
        ok = result.share >= floor
        failed += not ok
        print(
            f"{pack.name} ({language}): {result} - {'pass' if ok else 'FAIL'} "
            f"(floor {100 * floor:.0f} %)"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
