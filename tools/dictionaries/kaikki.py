"""Reading Wiktionary as kaikki.org extracts it (wiktextract JSONL).

One JSON object per line: a word in one language, one part of speech and
etymology - `word`, `pos`, `etymology_number`, `senses` (each with
`glosses`, `tags`, and `form_of` when the sense is "inflection of X"),
`forms` (a lemma's inflection table: `form` with `tags`) and `sounds`
(`ipa`). The English edition glosses every language's words in English;
the Chinese edition glosses them in Chinese.

An entry's reading is its first IPA, unless the language says otherwise
(Russian: its headword with the stress marked, `russian.stressed`).

A line is split here into the two things a dictionary needs:
- an **entry**, from its senses of its own ("casa": house);
- **form relations**, from its "form of" senses ("casas": plural of casa)
  and from a lemma's inflection table (hablar: hablo, hablé...). Each
  says "this written form is an inflection of that lemma".

Glosses are data, never markup: they are kept as text, one per meaning.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Tags on a form-of sense or a form that say it is no word of its own
_FORM_OF_TAGS = frozenset({"form-of", "alt-of"})
# Tags on a lemma's `forms` that aren't inflections: table headings, the
# template's name, spellings in another script, the lemma itself
_NOT_A_FORM = frozenset(
    {
        "table-tags",
        "inflection-template",
        "class",
        "romanization",
        "transliteration",
        "canonical",
        "infinitive",
        "error-unknown-tag",
    }
)
# "decir combined with indirect object me and direct object lo" -> decir
_COMBINED = re.compile(r"\s+combined with\b.*$")
_PRONOUN = re.compile(r"\b(me|te|se|nos|os|lo|la|le|los|las|les)\b")
_REFLEXIVE_TAGS = frozenset({"reflexive", "pronominal"})
# a gloss's trailing grammar note in the Chinese edition: [接 con ...]
_NOTE = re.compile(r"\s*\[[^\]]*\]\s*$")
MAX_MEANINGS = 8  # per entry: the card shows three; the rest is size


@dataclass(frozen=True)
class WiktEntry:
    """A word's own meanings in one part of speech and etymology. `key` is
    `word|pos|etymology number` (kaikki has no IDs; decision 0007 hashes
    this key)."""

    key: str
    word: str
    pos: str
    meanings: tuple[str, ...]
    reading: str = ""
    """How it's said, as the pack shows it: IPA ("/saˈbeɾ/"), or the
    language's own reading (`read_language`'s `reading`)."""


@dataclass
class Language:
    """What one language's lines give: entries, and which lemmas each
    written form is an inflection of."""

    entries: list[WiktEntry] = field(default_factory=list)
    forms: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """Written form -> the lemmas it is an inflection of."""
    imperative: set[tuple[str, str]] = field(default_factory=set)
    """(form, lemma) pairs only ever given as an imperative ("sé" is
    saber's "I know" but only ser's "be!") - rarer in speech than the
    same form's other uses."""
    verb_forms: set[tuple[str, str]] = field(default_factory=set)
    """(form, lemma) pairs where the form is a verb's inflection ("era" of
    ser) - not a noun's or adjective's form or another spelling ("pibe"
    is listed under piba, "güey" is a spelling of buey)."""
    combined: list[Combined] = field(default_factory=list)
    """Forms with pronouns attached ("levántate": levantar with te)."""
    reflexive: dict[str, list[str]] = field(default_factory=dict)
    """Entry key -> its senses marked reflexive or pronominal ("to get up",
    under levantar), which a language's rules may make an entry of their
    own."""


@dataclass(frozen=True)
class Combined:
    """A verb form with pronouns attached, as a form-of sense says it:
    "levántate" is levantar's second-person singular imperative "combined
    with te". `pronouns` in the order given; `tags` the sense's."""

    form: str
    lemma: str
    pronouns: tuple[str, ...]
    tags: frozenset[str]


def lines(path: Path, lang_code: str) -> Iterator[dict[str, object]]:
    """The objects for one language (`lang_code`, e.g. "es") in a kaikki
    file, gzipped or not."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        yield from lines_of(f, lang_code)


def lines_of(text: Iterable[str], lang_code: str) -> Iterator[dict[str, object]]:
    """The objects for one language in lines of JSON. Lines that aren't
    JSON objects are skipped (the extracts carry a few)."""
    needle = f'"lang_code": "{lang_code}"'
    for line in text:
        if needle not in line:  # cheap filter before parsing
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("lang_code") == lang_code:
            yield obj


def _strs(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _dicts(value: object) -> list[dict[str, object]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def lemma_of(form_of: str) -> str:
    """The lemma a form-of target names: "decir combined with indirect
    object me and direct object lo" -> "decir"."""
    return _COMBINED.sub("", form_of).strip()


def first_ipa(obj: Mapping[str, object]) -> str:
    """The object's first IPA transcription ("/saˈbeɾ/"), or ""."""
    return next(
        (
            str(s["ipa"])
            for s in _dicts(obj.get("sounds"))
            if isinstance(s.get("ipa"), str)
        ),
        "",
    )


def read_language(
    objects: Iterable[dict[str, object]],
    reading: Callable[[Mapping[str, object]], str] = first_ipa,
) -> Language:
    """Entries and form relations from one language's objects (`lines`),
    each entry's reading by `reading` (its first IPA unless said)."""
    out = Language()
    seen: dict[str, int] = defaultdict(int)
    moods: dict[tuple[str, str], set[bool]] = defaultdict(set)  # imperative?
    for obj in objects:
        word = obj.get("word")
        if not isinstance(word, str) or not word or " " in word.strip():
            continue  # phrases aren't looked up from a caption's words
        pos = str(obj.get("pos") or "")
        own: list[str] = []
        reflexive: list[str] = []
        for sense in _dicts(obj.get("senses")):
            targets = [
                lemma_of(str(t.get("word") or ""))
                for t in _dicts(sense.get("form_of")) + _dicts(sense.get("alt_of"))
            ]
            tags = set(_strs(sense.get("tags")))
            if targets or _FORM_OF_TAGS & tags:
                # "... of levantar combined with te": in the target, or the gloss
                said = " ".join(_strs(sense.get("glosses")))
                for target in _dicts(sense.get("form_of")):
                    named = str(target.get("word") or "")
                    combined = named if " combined with " in named else said
                    if " combined with " in combined and pos == "verb":
                        attached = combined.split(" combined with ", 1)[1]
                        out.combined.append(
                            Combined(
                                word,
                                lemma_of(named),
                                tuple(_PRONOUN.findall(attached)),
                                frozenset(tags),
                            )
                        )
                for lemma in targets:
                    if lemma and lemma != word:
                        out.forms[word].add(lemma)
                        if pos == "verb" and "alt-of" not in tags:
                            out.verb_forms.add((word, lemma))
                        if tags - _FORM_OF_TAGS:  # not a heading over its senses
                            moods[(word, lemma)].add("imperative" in tags)
                continue
            glosses = _strs(sense.get("glosses"))
            if glosses:
                gloss = " ".join(glosses[-1].split())
                if gloss and gloss not in own:
                    own.append(gloss)
                    if tags & _REFLEXIVE_TAGS:
                        reflexive.append(gloss)
        for form in _dicts(obj.get("forms")):
            text = form.get("form")
            tags = set(_strs(form.get("tags")))
            if (
                isinstance(text, str)
                and text
                and text != word
                and " " not in text
                and not tags & _NOT_A_FORM
            ):
                out.forms[text].add(word)
                moods[(text, word)].add("imperative" in tags)
                if pos == "verb":
                    out.verb_forms.add((text, word))
        if not own:
            continue
        number = obj.get("etymology_number")
        key = f"{word}|{pos}|{number if isinstance(number, int) else ''}"
        seen[key] += 1
        if seen[key] > 1:  # the same word, part of speech and etymology twice
            key = f"{key}|{seen[key]}"
        out.entries.append(
            WiktEntry(key, word, pos, tuple(own[:MAX_MEANINGS]), reading(obj))
        )
        if reflexive:
            out.reflexive[key] = reflexive
    out.imperative = {pair for pair, kinds in moods.items() if kinds == {True}}
    return out


def glosses_by_word(objects: Iterable[dict[str, object]]) -> dict[str, list[str]]:
    """Another edition's glosses (the Chinese edition's, for Chinese
    speakers), by `word|pos`: its own senses only, grammar notes trimmed.
    Form-of senses and redirects carry no meaning of their own."""
    out: dict[str, list[str]] = {}
    for obj in objects:
        word, pos = obj.get("word"), obj.get("pos")
        if not isinstance(word, str) or not isinstance(pos, str):
            continue
        found = out.setdefault(f"{word}|{pos}", [])
        for sense in _dicts(obj.get("senses")):
            if sense.get("form_of") or _FORM_OF_TAGS & set(_strs(sense.get("tags"))):
                continue
            glosses = _strs(sense.get("glosses"))
            gloss = _NOTE.sub("", " ".join(glosses[-1].split())) if glosses else ""
            if gloss and gloss not in found:
                found.append(gloss)
        if not found:
            del out[f"{word}|{pos}"]
    return out
