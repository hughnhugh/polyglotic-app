"""Words of a spaced language, with simplemma's lemma for each: the
`WordSplit` port for Spanish (and later the other languages written with
spaces).

A word is a run of letters, with apostrophes and hyphens inside - the
same rule as English's (`core.lexicon.english.words`). simplemma (MIT;
dictionary data, 54 languages) gives a lemma: "hablábamos" -> hablar. The
dictionary pack's own inflection table is asked first (it's Wiktionary's,
and knows "supe" is saber), so simplemma's lemma is a guess (`guesses`):
the fallback for a form the table hasn't got.

simplemma is imported only when a pack that needs it is used.
"""

from __future__ import annotations

from collections.abc import Sequence

from polyglotic_desktop.core.lexicon.english import words as letter_runs
from polyglotic_desktop.ports.word_split import SplitWord


class SpacedSplit:
    """Words by letters, lemmas by simplemma, for `language` ("es")."""

    def __init__(self, language: str) -> None:
        self.language = language

    def words(self, text: str) -> Sequence[SplitWord]:
        from simplemma import lemmatize

        out = []
        for start, end in letter_runs(text):
            word = text[start:end]
            lemma = lemmatize(word, lang=self.language)
            guesses = (lemma,) if lemma and lemma != word else ()
            out.append(SplitWord(start, end, guesses=guesses))
        return out
